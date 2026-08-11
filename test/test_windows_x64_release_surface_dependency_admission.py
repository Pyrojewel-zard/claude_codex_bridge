from __future__ import annotations

from pathlib import Path

from terminal_runtime.windows_x64_release_surface import (
    windows_x64_release_surface_dependency_admission,
)


def test_current_roadmap_dependencies_are_admitted() -> None:
    admission = windows_x64_release_surface_dependency_admission(Path.cwd())

    assert admission["status"] == "ready"
    assert admission["implementation_admission"] == "admitted"
    assert admission["baseline_gate_ref"].endswith(
        "windows-x64-v852-baseline-gate/windows-x64-v852-baseline-gate-acceptance.md"
    )
    assert admission["user_surfaces_parity_ref"].endswith(
        "herdr-user-surfaces-parity/herdr-user-surfaces-parity-acceptance.md"
    )
    assert admission["baseline_evidence_ref"].endswith("evidence/platform-gate-summary.json")
    assert admission["user_surface_evidence_ref"].endswith("evidence/cmd-008-native-windows-surface-transcript.md")


def test_missing_parent_acceptance_blocks_admission(tmp_path: Path) -> None:
    roadmap = tmp_path / ".codestable" / "roadmap" / "windows-native-herdr-ccb"
    roadmap.mkdir(parents=True)
    (roadmap / "windows-native-herdr-ccb-items.yaml").write_text(
        "\n".join(
            [
                "items:",
                "  - slug: windows-x64-v852-baseline-gate",
                "    status: done",
                "  - slug: herdr-user-surfaces-parity",
                "    status: done",
                "",
            ]
        ),
        encoding="utf-8",
    )

    admission = windows_x64_release_surface_dependency_admission(tmp_path)

    assert admission["status"] == "blocked"
    assert admission["implementation_admission"] == "blocked_upstream_pending"
    assert "parent acceptance missing" in admission["reason"]
