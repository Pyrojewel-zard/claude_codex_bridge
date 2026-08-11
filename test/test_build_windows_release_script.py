from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import zipfile


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_windows_release.py"
    spec = importlib.util.spec_from_file_location("build_windows_release", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_windows_release_artifact_is_x64_zip() -> None:
    module = _load_module()

    assert module.release_artifact_basename("Windows", machine="AMD64") == "ccb-windows-x86_64"
    assert module.release_artifact_basename("win32", machine="x64") == "ccb-windows-x86_64"
    assert module.release_artifact_name("windows", machine="x86_64") == "ccb-windows-x86_64.zip"
    assert module.release_build_arch("windows", machine="arm64") is None


def test_windows_create_zip_archive_contains_release_tree_without_tar_alias(tmp_path: Path) -> None:
    module = _load_module()
    stage_root = tmp_path / "stage"
    artifact_root = stage_root / "ccb-windows-x86_64"
    artifact_root.mkdir(parents=True)
    (artifact_root / "install.ps1").write_text("Write-Host install\n", encoding="utf-8")
    (artifact_root / "BUILD_INFO.json").write_text("{}\n", encoding="utf-8")
    (artifact_root / "bin").mkdir()
    (artifact_root / "bin" / "ccb-agent-sidebar.exe").write_bytes(b"MZfake")
    artifact_path = tmp_path / "ccb-windows-x86_64.zip"

    module.create_release_archive(stage_root=stage_root, artifact_root=artifact_root, artifact_path=artifact_path)

    with zipfile.ZipFile(artifact_path) as archive:
        names = set(archive.namelist())

    assert "ccb-windows-x86_64/install.ps1" in names
    assert "ccb-windows-x86_64/BUILD_INFO.json" in names
    assert "ccb-windows-x86_64/bin/ccb-agent-sidebar.exe" in names
    assert "ccb-windows-x86_64.zip" not in names
    assert not stage_root.exists()


def test_build_sidebar_helper_for_windows_copies_exe(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-agent-sidebar"
    output_bin = artifact_root / "bin" / "ccb-agent-sidebar.exe"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-agent-sidebar"\n', encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["cargo", "build", "--release"]
        built = crate_dir / "target" / "release" / "ccb-agent-sidebar.exe"
        built.parent.mkdir(parents=True)
        built.write_bytes(b"MZsidebar")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.build_sidebar_helper_for_release.__globals__["subprocess"], "run", _fake_run)

    module.build_sidebar_helper_for_release(artifact_root, target_platform="windows")

    assert output_bin.read_bytes() == b"MZsidebar"
    assert not (crate_dir / "target").exists()


def test_build_rs_helper_for_windows_copies_exe(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-rs-helper"
    output_bin = artifact_root / "bin" / "ccb-rs-helper.exe"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-rs-helper"\n', encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["cargo", "build", "--release"]
        built = crate_dir / "target" / "release" / "ccb-rs-helper.exe"
        built.parent.mkdir(parents=True)
        built.write_bytes(b"MZrshelper")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.build_rs_helper_for_release.__globals__["subprocess"], "run", _fake_run)

    module.build_rs_helper_for_release(artifact_root, target_platform="windows")

    assert output_bin.read_bytes() == b"MZrshelper"
    assert not (crate_dir / "target").exists()


def test_build_runtime_accelerator_for_windows_skips_unix_socket_crate(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    workspace_dir = artifact_root / "rust"
    crate_dir = workspace_dir / "crates" / "ccb-runtime-accelerator"
    output_bin = artifact_root / "bin" / "ccb-runtime-accelerator.exe"
    crate_dir.mkdir(parents=True)
    (workspace_dir / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/ccb-runtime-accelerator"]\n', encoding="utf-8")
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-runtime-accelerator"\n', encoding="utf-8")

    monkeypatch.setattr(
        module.build_runtime_accelerator_for_release.__globals__["subprocess"],
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Windows release must not build the Unix-socket accelerator")
        ),
    )

    module.build_runtime_accelerator_for_release(artifact_root, target_platform="windows")

    assert not output_bin.exists()
