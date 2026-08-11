from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

from cli.management_runtime.commands_runtime import update as update_runtime
from terminal_runtime.windows_x64_release_surface import default_blocked_projection


def _install_ps1_projection() -> dict[str, object]:
    projection = default_blocked_projection()
    projection.update(
        {
            "implementation_admission": "admitted",
            "baseline_version_status": "v8.5.2",
            "package_os": ["linux", "darwin", "win32"],
            "package_metadata_policy": "win32-enabled-postinstall-gated",
            "artifact_status": "ready",
            "artifact_basename": "ccb-windows-x86_64",
            "archive_name": "ccb-windows-x86_64.zip",
            "extract_dir": "ccb-windows-x86_64",
            "checksum_entry": "ccb-windows-x86_64.zip",
            "release_artifact_ref": "release/v8.5.2",
            "windows_installer_entry": "install.ps1",
            "windows_executable_entry": "ccb.exe",
            "windows_bin_entries": {"ccb": "ccb.exe"},
            "release_install_entry": "install_ps1",
            "update_entry": "install_ps1",
            "surface_state": "available",
            "failure_reason": None,
            "diagnostic": "Windows x64 release update route is available.",
            "next_action": "Run the staged install.ps1 update route.",
        }
    )
    return projection


def test_windows_update_diagnostic_only_does_not_download_or_mutate(monkeypatch, tmp_path: Path, capsys) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "identity.txt").write_text("old build\n", encoding="utf-8")
    projection = default_blocked_projection(
        failure_reason="upstream-not-admitted",
        diagnostic="Windows update release route is blocked by upstream admission.",
        next_action="Use install.ps1 for source/dev checkout installs.",
    )

    monkeypatch.setenv("CODEX_INSTALL_PREFIX", str(install_dir))
    monkeypatch.setattr(update_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(update_runtime.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(update_runtime, "load_windows_x64_release_surface_projection", lambda *_args, **_kwargs: projection)
    monkeypatch.setattr(
        update_runtime,
        "download_tarball",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("diagnostic route must not download")),
    )
    monkeypatch.setattr(
        update_runtime,
        "get_available_versions",
        lambda: (_ for _ in ()).throw(AssertionError("diagnostic route must not resolve releases")),
    )

    code = update_runtime.cmd_update(SimpleNamespace(target=None), script_root=tmp_path / "script-root")

    assert code == 1
    assert (install_dir / "identity.txt").read_text(encoding="utf-8") == "old build\n"
    output = capsys.readouterr().out
    assert "Windows update release route is blocked by upstream admission." in output
    assert "Use install.ps1 for source/dev checkout installs." in output


def test_windows_install_ps1_update_restores_backup_and_never_uses_unix_installer(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    tmp_base = tmp_path / "tmp-base"
    tmp_base.mkdir()
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "identity.txt").write_text("old build\n", encoding="utf-8")

    def _fake_download(_url: str, destination: Path) -> bool:
        if destination.name == "SHA256SUMS":
            archive_path = destination.parent / "ccb-windows-x86_64.zip"
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            destination.write_text(f"{digest}  ccb-windows-x86_64.zip\n", encoding="utf-8")
            return True
        payload = tmp_path / "payload" / "ccb-windows-x86_64"
        payload.mkdir(parents=True)
        (payload / "install.ps1").write_text("Write-Host install\n", encoding="utf-8")
        with zipfile.ZipFile(destination, "w") as archive:
            archive.write(payload / "install.ps1", "ccb-windows-x86_64/install.ps1")
        return True

    def _fake_windows_install(*_args, install_dir: Path, **_kwargs) -> int:
        shutil.rmtree(install_dir)
        install_dir.mkdir()
        (install_dir / "identity.txt").write_text("partial replacement\n", encoding="utf-8")
        return 23

    monkeypatch.setattr(update_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(update_runtime.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(update_runtime, "download_tarball", _fake_download)
    monkeypatch.setattr(update_runtime, "get_version_info", lambda _path: {"version": "8.5.2", "commit": "newbuild"})
    monkeypatch.setattr(update_runtime, "_run_staged_windows_installer", _fake_windows_install)
    monkeypatch.setattr(
        update_runtime,
        "run_staged_unix_installer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Windows update must not use Unix installer")),
    )

    code = update_runtime._update_via_windows_release_surface(
        tmp_base,
        install_dir=install_dir,
        target_version="8.5.2",
        old_info={"version": "8.5.1", "commit": "oldbuild"},
        projection=_install_ps1_projection(),
    )

    assert code == 23
    assert (install_dir / "identity.txt").read_text(encoding="utf-8") == "old build\n"
    assert "installer exited with code 23" in capsys.readouterr().out


def test_windows_install_ps1_update_fails_closed_on_checksum_mismatch(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    tmp_base = tmp_path / "tmp-base"
    tmp_base.mkdir()
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    def _fake_download(_url: str, destination: Path) -> bool:
        if destination.name == "SHA256SUMS":
            destination.write_text(f"{'0' * 64}  ccb-windows-x86_64.zip\n", encoding="utf-8")
            return True
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("ccb-windows-x86_64/install.ps1", "Write-Host install\n")
        return True

    monkeypatch.setattr(update_runtime, "download_tarball", _fake_download)
    monkeypatch.setattr(
        update_runtime,
        "_run_staged_windows_installer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("checksum mismatch must stop before install")),
    )

    code = update_runtime._update_via_windows_release_surface(
        tmp_base,
        install_dir=install_dir,
        target_version="8.5.2",
        old_info={"version": "8.5.1", "commit": "oldbuild"},
        projection=_install_ps1_projection(),
    )

    assert code == 1
    assert "checksum mismatch" in capsys.readouterr().out
