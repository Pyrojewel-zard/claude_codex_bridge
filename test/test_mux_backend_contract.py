from __future__ import annotations

import json
from pathlib import Path

import pytest

import terminal_runtime.api as terminal_api
from terminal_runtime.backend_selection import TerminalBackendSelection
from terminal_runtime.backend_resolver import build_herdr_capability_blocked_fixture
from terminal_runtime.fake_mux_backend import FakeMuxBackend
from terminal_runtime.mux_backend_contract import (
    MuxCommandErrorV2,
    capability_statuses_supported,
    make_capabilities,
    make_namespace_ref,
    make_pane_ref,
)


class _FakeTmuxBackend:
    pass


def test_mux_backend_contract_only_selects_existing_tmux_backend(monkeypatch) -> None:
    selection = TerminalBackendSelection(
        detect_terminal_fn=lambda: "tmux",
        tmux_backend_factory=lambda: _FakeTmuxBackend(),
    )

    assert isinstance(selection.get_backend(), _FakeTmuxBackend)
    monkeypatch.setattr(terminal_api, "_backend_cache", None)
    monkeypatch.setattr(terminal_api, "_herdr_platform_gate", lambda: None)
    monkeypatch.setattr(terminal_api, "_herdr_capability_report", lambda: None)
    monkeypatch.setattr(terminal_api, "_herdr_capability_report_ref", lambda: None)
    with pytest.raises(MuxCommandErrorV2) as exc_info:
        terminal_api.get_backend("herdr")
    assert exc_info.value.operation == "select_backend"


def test_mux_backend_contract_v2_expresses_herdr_refs_capabilities_and_schema_errors() -> None:
    namespace = make_namespace_ref(
        backend_impl="herdr",
        namespace_id="workspace-42",
        session_name="ccb-demo",
        ipc_kind="herdr_socket",
        ipc_ref="herdr://workspace-42",
        restore_token="opaque-restore-token",
    )
    pane = make_pane_ref(
        backend_impl="herdr",
        pane_id="pane-abc",
        session_name="ccb-demo",
        window_name="workspace",
        agent_slug="codex",
    )
    capabilities = make_capabilities(
        backend_impl="herdr",
        command_status={"pane_spawn": "supported", "server_restart_output_history": "unsupported"},
        semantic_status={"pane_spawn": "supported", "server_restart_output_history": "unsupported"},
        windows_beta_gaps=["server_restart_output_history"],
        blocking_gaps=["server_restart_output_history"],
        source_ref="spike-evidence.json",
    )
    error = MuxCommandErrorV2(
        category="schema-mismatch",
        backend_impl="herdr",
        operation="server_info",
        detail="unexpected schema version",
        ipc_ref=namespace["ipc_ref"],
        evidence={"expected": "v1", "actual": "v2"},
    )

    assert namespace["backend_family"] == "herdr-native"
    assert namespace["ipc_kind"] == "herdr_socket"
    assert namespace["restore_token"] == "opaque-restore-token"
    assert pane["pane_id"] == "pane-abc"
    assert pane["agent_slug"] == "codex"
    assert capability_statuses_supported(capabilities) is False
    assert error.category == "schema-mismatch"
    assert error.evidence == {"expected": "v1", "actual": "v2"}


@pytest.mark.parametrize(
    ("ipc_kind", "ipc_ref"),
    [
        ("none", ""),
        ("socket_path", "C:/tmp/herdr.sock"),
        ("herdr_socket", ""),
    ],
)
def test_herdr_namespace_ref_requires_addressable_ipc(ipc_kind: str, ipc_ref: str) -> None:
    with pytest.raises(ValueError, match="Herdr namespace refs require"):
        make_namespace_ref(
            backend_impl="herdr",
            namespace_id="workspace-42",
            session_name="ccb-demo",
            ipc_kind=ipc_kind,  # type: ignore[arg-type]
            ipc_ref=ipc_ref,
        )


@pytest.mark.parametrize(
    ("namespace_id", "session_name"),
    [
        ("", "ccb-demo"),
        ("   ", "ccb-demo"),
        ("workspace-42", ""),
        ("workspace-42", "   "),
    ],
)
def test_namespace_ref_requires_stable_identifiers(namespace_id: str, session_name: str) -> None:
    with pytest.raises(ValueError, match="Namespace refs require"):
        make_namespace_ref(
            backend_impl="herdr",
            namespace_id=namespace_id,
            session_name=session_name,
            ipc_kind="herdr_socket",
            ipc_ref="herdr://workspace-42",
        )


@pytest.mark.parametrize(
    ("pane_id", "session_name"),
    [
        ("", "ccb-demo"),
        ("   ", "ccb-demo"),
        ("pane-abc", ""),
        ("pane-abc", "   "),
    ],
)
def test_pane_ref_requires_stable_identifiers(pane_id: str, session_name: str) -> None:
    with pytest.raises(ValueError, match="Pane refs require"):
        make_pane_ref(
            backend_impl="herdr",
            pane_id=pane_id,
            session_name=session_name,
        )


def test_empty_capability_statuses_fail_closed() -> None:
    capabilities = make_capabilities(
        backend_impl="herdr",
        command_status={},
        semantic_status={},
    )

    assert capability_statuses_supported(capabilities) is False


def test_capability_statuses_require_herdr_required_keys() -> None:
    required_statuses = {
        "session_attach": "supported",
        "pane_spawn": "supported",
        "send_input": "supported",
        "read_output": "supported",
        "kill_pane": "supported",
    }
    wrong_backend = make_capabilities(
        backend_impl="tmux",
        command_status=required_statuses,
        semantic_status=required_statuses,
    )
    missing_required = make_capabilities(
        backend_impl="herdr",
        command_status={"pane_spawn": "supported"},
        semantic_status=required_statuses,
    )

    assert capability_statuses_supported(wrong_backend) is False
    assert capability_statuses_supported(missing_required) is False


def test_fake_mux_backend_supports_herdr_contract_without_herdr_json() -> None:
    backend = FakeMuxBackend()
    namespace = backend.create_session(project_id="demo", cwd="/tmp/demo", title="ccb-demo")
    root_pane = backend.create_pane(
        namespace,
        command=["python", "-V"],
        cwd="/tmp/demo",
        env={"DEMO": "1"},
        title="workspace",
    )
    child_pane = backend.split_pane(
        root_pane,
        command=["python", "-c", "print('ready')"],
        cwd="/tmp/demo",
        title="agent",
    )
    send = backend.send_text(child_pane, "echo marker")
    captured, capture = backend.capture_pane(child_pane, lines=2)
    killed = backend.kill_pane(child_pane)
    after_kill = backend.send_text(child_pane, "echo should-not-run")

    assert namespace["backend_family"] == "herdr-native"
    assert root_pane["pane_id"] != child_pane["pane_id"]
    assert send["status"] == "ok"
    assert "echo marker" in captured
    assert capture["operation"] == "capture_pane"
    assert killed["operation"] == "kill_pane"
    assert after_kill["status"] == "failed"


def test_fake_mux_backend_restore_fails_closed_for_unknown_tokens() -> None:
    backend = FakeMuxBackend()

    with pytest.raises(KeyError, match="unknown fake restore token"):
        backend.restore_session(restore_token="missing-token")


def test_mux_backend_contract_herdr_native_surface_is_limited_to_contract_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime_root = root / "lib" / "terminal_runtime"
    matches = [
        path.relative_to(root)
        for path in runtime_root.rglob("*.py")
        if "herdr-native" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    allowed = {
        Path("lib/terminal_runtime/mux_backend_contract.py"),
        Path("lib/terminal_runtime/backend_resolver.py"),
    }
    assert set(matches) == allowed


def test_partial_spike_evidence_has_a_fail_closed_herdr_blocked_fixture() -> None:
    root = Path(__file__).resolve().parents[1]
    spike_path = (
        root
        / ".codestable"
        / "features"
        / "2026-07-31-herdr-backend-contract-spike"
        / "evidence"
        / "herdr-contract-spike-evidence.json"
    )
    fixture_path = (
        root
        / ".codestable"
        / "features"
        / "2026-07-31-mux-backend-contract-herdr-v2"
        / "evidence"
        / "herdr-capability-blocked-fixture.json"
    )
    spike_evidence = json.loads(spike_path.read_text(encoding="utf-8"))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture == build_herdr_capability_blocked_fixture(
        spike_evidence,
        capability_report_ref=spike_path.relative_to(root).as_posix(),
    )


def test_mux_backend_contract_has_no_production_runtime_diff() -> None:
    root = Path(__file__).resolve().parents[1]
    scope_gate = json.loads(
        (
            root
            / ".codestable"
            / "features"
            / "2026-07-31-herdr-backend-contract-spike"
            / "evidence"
            / "scope-gate.json"
        ).read_text(encoding="utf-8")
    )
    changed_files = scope_gate["evidence"][0]["changed_files"]

    assert [path for path in changed_files if path.startswith("lib/terminal_runtime/")] == []
