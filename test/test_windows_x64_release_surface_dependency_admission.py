from __future__ import annotations

from pathlib import Path

from platforms.windows.release.surface import windows_x64_release_surface_dependency_admission


def test_current_windows_release_dependencies_are_admitted() -> None:
    admission = windows_x64_release_surface_dependency_admission(Path.cwd())

    assert admission["status"] == "ready"
    assert admission["implementation_admission"] == "admitted"
    refs = admission["dependency_refs"]
    assert refs["launcher"] == "platforms/windows/launcher/Cargo.toml"
    assert refs["builder"] == "platforms/windows/packaging/build_release.py"
    assert refs["workflow"] == ".github/workflows/release-windows.yml"


def test_missing_windows_release_dependency_blocks_admission(tmp_path: Path) -> None:
    admission = windows_x64_release_surface_dependency_admission(tmp_path)

    assert admission["status"] == "blocked"
    assert admission["implementation_admission"] == "blocked_upstream_pending"
    assert "Windows release dependency missing" in admission["reason"]
