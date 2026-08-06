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


def test_write_session_file_keeps_conversation_id_across_authority_generations(
    tmp_path: Path,
) -> None:
    ccb_dir = tmp_path / '.ccb'
    ccb_dir.mkdir(parents=True)
    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id='proj-1', project_root=tmp_path),
    )
    spec = SimpleNamespace(name='agent1', provider='codex')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    plan = SimpleNamespace(workspace_path=workspace)
    runtime_dir = ccb_dir / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    runtime_dir.mkdir(parents=True)
    codex_home = ccb_dir / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    native_a = session_root / '2026' / '08' / '05' / 'native-a.jsonl'
    native_b = session_root / '2026' / '08' / '05' / 'native-b.jsonl'
    native_a.parent.mkdir(parents=True)
    native_a.write_text('{}\n', encoding='utf-8')
    native_b.write_text('{}\n', encoding='utf-8')

    common = {
        'context': context,
        'spec': spec,
        'plan': plan,
        'runtime_dir': runtime_dir,
        'run_cwd': workspace,
        'pane_id': '%7',
        'tmux_socket_name': 'ccb-demo',
        'tmux_socket_path': str(ccb_dir / 'ccbd' / 'tmux.sock'),
        'pane_title_marker': 'CCB-agent1',
        'start_cmd': 'codex',
    }
    session_path = write_session_file(
        **common,
        launch_session_id='ccb-launch-a',
        provider_payload={
            'codex_home': str(codex_home),
            'codex_session_root': str(session_root),
            'codex_provider_authority_fingerprint': 'fp-a',
            'codex_session_authority_fingerprint': 'fp-a',
            'codex_session_id': 'native-a',
            'codex_session_path': str(native_a),
        },
    )
    first = json.loads(session_path.read_text(encoding='utf-8'))
    conversation_id = first['ccb_conversation_id']
    assert first['ccb_authority_generation'] == 1

    write_session_file(
        **common,
        launch_session_id='ccb-launch-a2',
        provider_payload={
            'codex_home': str(codex_home),
            'codex_session_root': str(session_root),
            'codex_provider_authority_fingerprint': 'fp-a',
        },
    )
    same_authority = json.loads(session_path.read_text(encoding='utf-8'))
    assert same_authority['ccb_conversation_id'] == conversation_id
    assert same_authority['ccb_authority_generation'] == 1
    assert same_authority['codex_session_id'] == 'native-a'

    write_session_file(
        **common,
        launch_session_id='ccb-launch-b',
        provider_payload={
            'codex_home': str(codex_home),
            'codex_session_root': str(session_root),
            'codex_provider_authority_fingerprint': 'fp-b',
        },
    )
    second_generation = json.loads(session_path.read_text(encoding='utf-8'))
    assert second_generation['ccb_conversation_id'] == conversation_id
    assert second_generation['ccb_authority_generation'] == 2
    assert second_generation['ccb_session_history'][0]['provider_session_id'] == 'native-a'

    second_generation.update(
        {
            'codex_session_id': 'native-b',
            'codex_session_path': str(native_b),
            'codex_session_authority_fingerprint': 'fp-b',
        }
    )
    session_path.write_text(json.dumps(second_generation), encoding='utf-8')
    write_session_file(
        **common,
        launch_session_id='ccb-launch-c',
        provider_payload={
            'codex_home': str(codex_home),
            'codex_session_root': str(session_root),
            'codex_provider_authority_fingerprint': 'fp-c',
        },
    )
    third_generation = json.loads(session_path.read_text(encoding='utf-8'))
    assert third_generation['ccb_conversation_id'] == conversation_id
    assert third_generation['ccb_authority_generation'] == 3
    assert [
        item['provider_session_id']
        for item in third_generation['ccb_session_history']
    ] == ['native-a', 'native-b']


def test_write_session_file_preserves_gemini_linked_continuation_binding(
    tmp_path: Path,
) -> None:
    ccb_dir = tmp_path / '.ccb'
    ccb_dir.mkdir(parents=True)
    old_session = tmp_path / 'managed-home' / '.gemini' / 'tmp' / 'hash' / 'chats' / 'session-old.jsonl'
    old_session.parent.mkdir(parents=True)
    old_session.write_text('{}\n', encoding='utf-8')
    session_path = ccb_dir / '.gemini-reviewer-session'
    session_path.write_text(
        json.dumps(
            {
                'ccb_session_id': 'ccb-old-launch',
                'ccb_conversation_id': 'conversation-1',
                'ccb_authority_generation': 2,
                'ccb_continuity_status': 'continued_on_new_authority',
                'ccb_resume_compatibility': 'linked_continuation',
                'gemini_provider_authority_fingerprint': 'fp-new',
                'gemini_root': str(old_session.parents[2]),
                'old_gemini_session_id': 'native-old',
                'old_gemini_session_path': str(old_session),
                'ccb_session_history': [
                    {
                        'provider': 'gemini',
                        'authority_generation': 1,
                        'provider_session_id': 'native-old',
                        'provider_session_path': str(old_session),
                    }
                ],
            }
        ),
        encoding='utf-8',
    )
    context = SimpleNamespace(
        paths=SimpleNamespace(ccb_dir=ccb_dir),
        project=SimpleNamespace(project_id='proj-1', project_root=tmp_path),
    )
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    write_session_file(
        context=context,
        spec=SimpleNamespace(name='reviewer', provider='gemini'),
        plan=SimpleNamespace(workspace_path=workspace),
        runtime_dir=ccb_dir / 'agents' / 'reviewer' / 'provider-runtime' / 'gemini',
        run_cwd=workspace,
        pane_id='%7',
        tmux_socket_name='ccb-demo',
        tmux_socket_path=str(ccb_dir / 'ccbd' / 'tmux.sock'),
        pane_title_marker='CCB-reviewer',
        start_cmd=f'gemini --session-file {old_session}',
        launch_session_id='ccb-new-launch',
        provider_payload={
            'gemini_provider_authority_fingerprint': 'fp-new',
            'gemini_root': str(old_session.parents[2]),
        },
    )

    rewritten = json.loads(session_path.read_text(encoding='utf-8'))
    assert rewritten['ccb_conversation_id'] == 'conversation-1'
    assert rewritten['ccb_authority_generation'] == 2
    assert rewritten['ccb_resume_compatibility'] == 'linked_continuation'
    assert rewritten['old_gemini_session_id'] == 'native-old'
    assert rewritten['old_gemini_session_path'] == str(old_session)
    assert rewritten['ccb_session_history'][0]['provider_session_id'] == 'native-old'
