from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from cli.services.runtime_launch_runtime.session_files import write_session_file


def test_write_session_file_persists_ccb_session_id_only(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    ccb_dir.mkdir(parents=True, exist_ok=True)

    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id="proj-1", project_root=tmp_path),
    )
    spec = SimpleNamespace(name="agent1", provider="codex")
    plan = SimpleNamespace(workspace_path=tmp_path / "workspace")
    runtime_dir = ccb_dir / "runtime" / "agent1"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_cwd = tmp_path / "workspace"
    run_cwd.mkdir(parents=True, exist_ok=True)

    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=runtime_dir,
        run_cwd=run_cwd,
        pane_id="%7",
        tmux_socket_name="ccb-demo",
        tmux_socket_path=str(ccb_dir / "ccbd" / "tmux.sock"),
        pane_title_marker="CCB-agent1",
        start_cmd="codex",
        launch_session_id="ccb-agent1-123",
        provider_payload={"codex_session_id": "provider-sid"},
    )

    data = json.loads(session_path.read_text(encoding="utf-8"))
    assert data["ccb_session_id"] == "ccb-agent1-123"
    assert "session_id" not in data
    assert data["codex_session_id"] == "provider-sid"


def test_write_session_file_skips_stale_codex_resume_binding_without_bound_authority(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    ccb_dir.mkdir(parents=True, exist_ok=True)
    (ccb_dir / ".codex-agent1-session").write_text(
        json.dumps(
            {
                "codex_session_id": "legacy-sid",
                "codex_session_path": str(tmp_path / "legacy.jsonl"),
                "codex_provider_authority_fingerprint": "fp-1",
                "updated_at": "2026-04-26 00:00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id="proj-1", project_root=tmp_path),
    )
    spec = SimpleNamespace(name="agent1", provider="codex")
    plan = SimpleNamespace(workspace_path=tmp_path / "workspace")
    runtime_dir = ccb_dir / "runtime" / "agent1"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_cwd = tmp_path / "workspace"
    run_cwd.mkdir(parents=True, exist_ok=True)

    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=runtime_dir,
        run_cwd=run_cwd,
        pane_id="%7",
        tmux_socket_name="ccb-demo",
        tmux_socket_path=str(ccb_dir / "ccbd" / "tmux.sock"),
        pane_title_marker="CCB-agent1",
        start_cmd="codex",
        launch_session_id="ccb-agent1-456",
        provider_payload={
            "codex_home": str(ccb_dir / "provider-profiles" / "agent1" / "codex"),
            "codex_session_root": str(ccb_dir / "provider-profiles" / "agent1" / "codex" / "sessions"),
            "codex_provider_authority_fingerprint": "fp-1",
        },
    )

    data = json.loads(session_path.read_text(encoding="utf-8"))
    assert data["codex_provider_authority_fingerprint"] == "fp-1"
    assert "codex_session_id" not in data
    assert "codex_session_path" not in data
    assert "updated_at" not in data


def test_write_session_file_preserves_codex_resume_binding_when_bound_authority_matches(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    ccb_dir.mkdir(parents=True, exist_ok=True)
    (ccb_dir / ".codex-agent1-session").write_text(
        json.dumps(
            {
                "codex_session_id": "bound-sid",
                "codex_session_path": str(tmp_path / "bound.jsonl"),
                "codex_provider_authority_fingerprint": "fp-1",
                "codex_session_authority_fingerprint": "fp-1",
                "updated_at": "2026-04-26 00:00:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id="proj-1", project_root=tmp_path),
    )
    spec = SimpleNamespace(name="agent1", provider="codex")
    plan = SimpleNamespace(workspace_path=tmp_path / "workspace")
    runtime_dir = ccb_dir / "runtime" / "agent1"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_cwd = tmp_path / "workspace"
    run_cwd.mkdir(parents=True, exist_ok=True)

    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=runtime_dir,
        run_cwd=run_cwd,
        pane_id="%7",
        tmux_socket_name="ccb-demo",
        tmux_socket_path=str(ccb_dir / "ccbd" / "tmux.sock"),
        pane_title_marker="CCB-agent1",
        start_cmd="codex",
        launch_session_id="ccb-agent1-789",
        provider_payload={
            "codex_home": str(ccb_dir / "provider-profiles" / "agent1" / "codex"),
            "codex_session_root": str(ccb_dir / "provider-profiles" / "agent1" / "codex" / "sessions"),
            "codex_provider_authority_fingerprint": "fp-1",
        },
    )

    data = json.loads(session_path.read_text(encoding="utf-8"))
    assert data["codex_session_id"] == "bound-sid"
    assert data["codex_session_path"] == str(tmp_path / "bound.jsonl")
    assert data["codex_session_authority_fingerprint"] == "fp-1"
    assert data["updated_at"] == "2026-04-26 00:00:00"


def test_write_session_file_persists_herdr_provider_runtime_backend_ref_without_restore_token(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    ccb_dir.mkdir(parents=True, exist_ok=True)

    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id="proj-1", project_root=tmp_path),
    )
    spec = SimpleNamespace(name="agent1", provider="codex")
    plan = SimpleNamespace(workspace_path=tmp_path / "workspace")
    runtime_dir = ccb_dir / "runtime" / "agent1"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_cwd = tmp_path / "workspace"
    run_cwd.mkdir(parents=True, exist_ok=True)
    namespace_ref = {
        "backend_family": "herdr-native",
        "backend_impl": "herdr",
        "namespace_id": "ns-1",
        "session_name": "ccb-demo",
        "ipc_kind": "herdr_socket",
        "ipc_ref": "127.0.0.1:54321",
        "restore_token": "raw-token-1",
    }
    pane_ref = {
        "backend_family": "herdr-native",
        "backend_impl": "herdr",
        "pane_id": "pane-1",
        "namespace_id": "ns-1",
        "ipc_kind": "herdr_socket",
        "ipc_ref": "127.0.0.1:54321",
    }

    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=runtime_dir,
        run_cwd=run_cwd,
        pane_id="pane-1",
        tmux_socket_name=None,
        tmux_socket_path=None,
        pane_title_marker="CCB-agent1",
        start_cmd="codex",
        launch_session_id="ccb-agent1-herdr",
        provider_payload={
            "codex_home": str(ccb_dir / "provider-profiles" / "agent1" / "codex"),
        },
        backend_family="herdr-native",
        backend_impl="herdr",
        namespace_ref=namespace_ref,
        pane_ref=pane_ref,
    )

    raw_json = session_path.read_text(encoding="utf-8")
    data = json.loads(raw_json)
    backend_ref = data["provider_runtime_backend_ref"]

    assert data["terminal"] == "mux"
    assert data["backend_family"] == "herdr-native"
    assert data["backend_impl"] == "herdr"
    assert data["namespace_ref"]["ipc_kind"] == "herdr_socket"
    assert data["namespace_ref"]["ipc_ref"] == "127.0.0.1:54321"
    assert data["pane_ref"] == pane_ref
    assert data["managed_home"] == str(ccb_dir / "provider-profiles" / "agent1" / "codex")
    assert data["completion_source_kind"] == "protocol_event_stream"
    assert data["completion_source"] == "provider_event_stream"
    assert data["namespace_restore_token_present"] is True
    assert backend_ref["provider"] == "codex"
    assert backend_ref["agent_slug"] == "agent1"
    assert backend_ref["backend_impl"] == "herdr"
    assert backend_ref["namespace_ref"] == data["namespace_ref"]
    assert backend_ref["pane_ref"] == pane_ref
    assert backend_ref["managed_home"] == data["managed_home"]
    assert backend_ref["completion_source"] == "provider_event_stream"
    assert backend_ref["completion_source_kind"] == "protocol_event_stream"
    assert "raw-token-1" not in raw_json
    assert "restore_token" not in data["namespace_ref"]
    assert "restore_token" not in backend_ref["namespace_ref"]


def test_write_session_file_preserves_shared_keys_when_provider_payload_conflicts(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    ccb_dir.mkdir(parents=True, exist_ok=True)

    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id="proj-1", project_root=tmp_path),
    )
    spec = SimpleNamespace(name="agent1", provider="codex")
    plan = SimpleNamespace(workspace_path=tmp_path / "workspace")
    runtime_dir = ccb_dir / "runtime" / "agent1"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_cwd = tmp_path / "workspace"
    run_cwd.mkdir(parents=True, exist_ok=True)

    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=runtime_dir,
        run_cwd=run_cwd,
        pane_id="%7",
        tmux_socket_name="ccb-demo",
        tmux_socket_path=str(ccb_dir / "ccbd" / "tmux.sock"),
        pane_title_marker="CCB-agent1",
        start_cmd="codex",
        launch_session_id="ccb-agent1-conflict",
        provider_payload={
            "terminal": "provider-terminal",
            "backend_impl": "herdr",
            "pane_id": "provider-pane",
            "tmux_socket_name": "provider-sock",
            "codex_session_id": "provider-sid",
        },
    )

    data = json.loads(session_path.read_text(encoding="utf-8"))
    assert data["terminal"] == "tmux"
    assert data["backend_impl"] == "tmux"
    assert data["pane_id"] == "%7"
    assert data["tmux_socket_name"] == "ccb-demo"
    assert data["codex_session_id"] == "provider-sid"
    assert data["provider_payload_conflicts"] == [
        "backend_impl",
        "pane_id",
        "terminal",
        "tmux_socket_name",
    ]
