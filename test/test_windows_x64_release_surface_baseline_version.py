from __future__ import annotations

import json
from pathlib import Path

from terminal_runtime.windows_x64_release_surface import (
    windows_x64_release_surface_baseline_version_admission,
)


def test_current_workspace_is_strict_v852() -> None:
    admission = windows_x64_release_surface_baseline_version_admission(Path.cwd())

    assert admission["status"] == "ready"
    assert admission["baseline_version_status"] == "v8.5.2"
    assert admission["version_ref"] == "VERSION"
    assert admission["package_version_ref"] == "package.json"


def test_mismatched_version_blocks_release_route(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("8.2.1\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "8.2.1"}), encoding="utf-8")

    admission = windows_x64_release_surface_baseline_version_admission(tmp_path)

    assert admission["status"] == "blocked"
    assert admission["baseline_version_status"] == "mismatch"
    assert admission["implementation_admission"] == "blocked_baseline_mismatch"
