from __future__ import annotations

from ccbd.herdr_surface_projection import build_herdr_surface_projection


def test_herdr_surface_projection_returns_redacted_contract() -> None:
    projection = build_herdr_surface_projection(
        {
            "backend_impl": "herdr",
            "capability_status": "blocked",
            "support_tier_projection_source": "backend_capability",
            "beta_gaps": ["mobile-terminal-validation-pending"],
            "blocking_gaps": ["auto-restore observe-only blocks CCB-owned recovery"],
            "degraded_next_action": "wait-probation",
            "namespace_ref": {
                "backend_impl": "herdr",
                "namespace_id": "workspace-1",
                "restore_token": "raw-token",
            },
            "pane_ref": {"backend_impl": "herdr", "pane_id": "pane-1"},
            "provider_runtime_backend_ref": {
                "backend_impl": "herdr",
                "namespace_ref": {
                    "backend_impl": "herdr",
                    "namespace_id": "workspace-1",
                    "restore_token": "nested-token",
                },
                "pane_ref": {"backend_impl": "herdr", "pane_id": "pane-1"},
            },
        }
    )

    assert projection == {
        "backend_impl": "herdr",
        "capability_status": "blocked",
        "support_tier_projection": "experimental",
        "support_tier_projection_source": "backend_capability",
        "beta_gaps": ["mobile-terminal-validation-pending"],
        "blocking_gaps": ["auto-restore observe-only blocks CCB-owned recovery"],
        "degraded_next_action": "wait-probation",
        "evidence_refs": {
            "namespace_ref": {"backend_impl": "herdr", "namespace_id": "workspace-1"},
            "pane_ref": {"backend_impl": "herdr", "pane_id": "pane-1"},
            "provider_runtime_backend_ref": {
                "backend_impl": "herdr",
                "namespace_ref": {"backend_impl": "herdr", "namespace_id": "workspace-1"},
                "pane_ref": {"backend_impl": "herdr", "pane_id": "pane-1"},
            },
        },
    }
    assert "raw-token" not in str(projection)
    assert "nested-token" not in str(projection)


def test_herdr_surface_projection_derives_blocked_recovery_next_action() -> None:
    projection = build_herdr_surface_projection(
        {
            "backend_impl": "herdr",
            "recovery_evidence_ledger": {
                "backend_impl": "herdr",
                "action": "circuit_open",
                "reason": "recovery-circuit-open",
                "namespace_ref": {
                    "backend_impl": "herdr",
                    "namespace_id": "workspace-1",
                    "restore_token": "raw-token",
                },
                "pane_ref": {"backend_impl": "herdr", "pane_id": "pane-1"},
            },
        }
    )

    assert projection is not None
    assert projection["capability_status"] == "blocked"
    assert projection["support_tier_projection"] == "experimental"
    assert projection["support_tier_projection_source"] == "validation_pending"
    assert projection["blocking_gaps"] == ["recovery-circuit-open"]
    assert projection["degraded_next_action"] == "wait-probation"
    assert projection["beta_gaps"] == ["validation_pending"]
    assert "raw-token" not in str(projection)


def test_herdr_surface_projection_omits_non_herdr_evidence() -> None:
    assert build_herdr_surface_projection({"backend_impl": "tmux"}) is None
