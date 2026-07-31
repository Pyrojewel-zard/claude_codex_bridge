from __future__ import annotations

from pathlib import Path

import pytest

from provider_core import keyring_read
from provider_core.one_way_inheritance import (
    copy_regular_file,
    copy_regular_tree,
    ensure_private_descendant_directory,
    ensure_private_inheritance_directory,
)


def test_copy_regular_file_detaches_target_symlink_and_never_updates_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "auth.json"
    target = tmp_path / "target" / "auth.json"
    source.parent.mkdir()
    target.parent.mkdir()
    source.write_text('{"token":"source"}\n', encoding="utf-8")
    target.symlink_to(source)

    assert copy_regular_file(source, target)
    assert target.is_file() and not target.is_symlink()

    target.write_text('{"token":"managed"}\n', encoding="utf-8")
    assert source.read_text(encoding="utf-8") == '{"token":"source"}\n'


def test_copy_regular_file_ignores_source_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external.json"
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    external.write_text('{"token":"external"}\n', encoding="utf-8")
    source.symlink_to(external)

    assert not copy_regular_file(source, target)
    assert not target.exists()
    assert external.read_text(encoding="utf-8") == '{"token":"external"}\n'


def test_copy_regular_file_detaches_target_symlink_when_source_is_missing(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external.json"
    target = tmp_path / "managed" / "auth.json"
    external.write_text('{"token":"external"}\n', encoding="utf-8")
    target.parent.mkdir()
    target.symlink_to(external)

    assert not copy_regular_file(tmp_path / "missing.json", target)
    assert not target.exists()
    assert not target.is_symlink()
    assert external.read_text(encoding="utf-8") == '{"token":"external"}\n'


def test_copy_regular_file_breaks_target_hardlink_before_managed_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    external = tmp_path / "external.json"
    target = tmp_path / "managed" / "auth.json"
    source.write_text('{"token":"source"}\n', encoding="utf-8")
    external.write_text('{"token":"external"}\n', encoding="utf-8")
    target.parent.mkdir()
    target.hardlink_to(external)

    assert copy_regular_file(source, target)
    target.write_text('{"token":"managed"}\n', encoding="utf-8")
    assert external.read_text(encoding="utf-8") == '{"token":"external"}\n'


def test_copy_regular_file_same_path_is_non_destructive(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"source"}\n', encoding="utf-8")

    assert not copy_regular_file(auth, auth)
    assert auth.read_text(encoding="utf-8") == '{"token":"source"}\n'


def test_private_inheritance_directory_rejects_source_as_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "provider-home"
    source.mkdir()

    with pytest.raises(ValueError, match="inheritance target must differ"):
        ensure_private_inheritance_directory(source, source)


def test_private_descendant_detaches_each_legacy_symlink_component(
    tmp_path: Path,
) -> None:
    managed_home = tmp_path / "managed"
    external_config = tmp_path / "external-config"
    managed_home.mkdir()
    external_config.mkdir()
    (managed_home / ".config").symlink_to(external_config, target_is_directory=True)

    target = ensure_private_descendant_directory(
        managed_home,
        Path(".config") / "provider",
    )
    (target / "auth.json").write_text("managed\n", encoding="utf-8")

    assert target.is_dir()
    assert not (managed_home / ".config").is_symlink()
    assert not (external_config / "provider").exists()


def test_copy_regular_tree_detaches_nested_target_symlink(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "managed" / "auth"
    external = tmp_path / "external"
    (source / "nested").mkdir(parents=True)
    target.mkdir(parents=True)
    external.mkdir()
    (source / "nested" / "token.json").write_text("source\n", encoding="utf-8")
    (target / "nested").symlink_to(external, target_is_directory=True)

    assert copy_regular_tree(source, target) == 1
    assert (target / "nested" / "token.json").read_text(encoding="utf-8") == "source\n"
    assert not (target / "nested").is_symlink()
    assert not (external / "token.json").exists()


def test_private_descendant_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be relative"):
        ensure_private_descendant_directory(tmp_path / "managed", Path("..") / "external")


def test_keyring_reader_uses_read_only_macos_security_command(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "inherited-secret\n"

    def fake_run(argv, **kwargs):
        calls.append([str(part) for part in argv])
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        return Result()

    monkeypatch.setattr(keyring_read.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(keyring_read.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(keyring_read.subprocess, "run", fake_run)

    assert keyring_read.read_keyring_password(
        "provider-service",
        "provider-account",
        command_name="provider",
    ) == "inherited-secret"
    assert calls == [
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            "provider-service",
            "-a",
            "provider-account",
            "-w",
        ]
    ]
