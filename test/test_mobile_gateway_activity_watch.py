from __future__ import annotations

import json
from pathlib import Path

from mobile_gateway.activity_watch import probe_mobile_agent_activity
from storage.paths import PathLayout


def test_claude_probe_reports_idle_from_real_footer_over_stale_hook(
    tmp_path: Path,
) -> None:
    layout = _write_binding(tmp_path, provider='claude', agent='worker')
    runtime_dir = layout.agent_provider_runtime_dir('worker', 'claude')
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / 'activity.json').write_text(
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'provider_activity',
                'project_id': 'proj-demo',
                'agent_name': 'worker',
                'provider': 'claude',
                'state': 'pending',
                'source': 'claude_hook',
                'event_name': 'Notification',
                'ccb_session_id': 'ccb-worker',
                'runtime_dir': str(runtime_dir),
                'pane_id': '%2',
                'workspace_path': str(tmp_path),
                'updated_at': '2026-07-28T10:00:00Z',
                'diagnostics': {},
            }
        ),
        encoding='utf-8',
    )

    result = probe_mobile_agent_activity(
        project_root=tmp_path,
        project_id='proj-demo',
        agent='worker',
        provider='claude',
        namespace_epoch=3,
        now='2026-07-28T11:00:00Z',
        pane_capture=lambda _: (
            '✻ Sautéed for 5s\n'
            '────────────────────────\n'
            '❯\u00a0\n'
            '────────────────────────\n'
            '⏵⏵ bypass permissions on\n'
        ),
    )

    assert result.activity_state == 'idle'
    assert result.reason == 'claude_pane_idle_prompt'
    assert result.source == 'claude_runtime'


def test_claude_probe_keeps_live_tool_active_even_with_footer_prompt(
    tmp_path: Path,
) -> None:
    _write_binding(tmp_path, provider='claude', agent='worker')

    result = probe_mobile_agent_activity(
        project_root=tmp_path,
        project_id='proj-demo',
        agent='worker',
        provider='claude',
        namespace_epoch=3,
        now='2026-07-28T11:00:00Z',
        pane_capture=lambda _: (
            '● Thinking for 9s, running 1 shell command…\n'
            '❯\u00a0\n'
            '⏵⏵ bypass permissions on\n'
        ),
    )

    assert result.activity_state == 'active'
    assert result.reason == 'claude_pane_tool_running'


def test_unknown_claude_pane_does_not_manufacture_idle(
    tmp_path: Path,
) -> None:
    _write_binding(tmp_path, provider='claude', agent='worker')

    result = probe_mobile_agent_activity(
        project_root=tmp_path,
        project_id='proj-demo',
        agent='worker',
        provider='claude',
        namespace_epoch=3,
        now='2026-07-28T11:00:00Z',
        pane_capture=lambda _: 'unclassified provider screen',
    )

    assert result.activity_state == 'unknown'


def test_codex_probe_uses_bounded_session_boundary_when_pane_is_quiet(
    tmp_path: Path,
) -> None:
    layout = _write_binding(tmp_path, provider='codex', agent='worker')
    sessions = (
        layout.agent_provider_state_dir('worker', 'codex') / 'home' / 'sessions'
    )
    rollout = sessions / '2026' / '07' / '28' / 'rollout.jsonl'
    rollout.parent.mkdir(parents=True, exist_ok=True)
    rollout.write_text(
        '\n'.join(
            (
                json.dumps(
                    {
                        'type': 'session_meta',
                        'payload': {'cwd': str(tmp_path)},
                    }
                ),
                json.dumps(
                    {
                        'type': 'event_msg',
                        'payload': {'type': 'task_complete'},
                    }
                ),
            )
        )
        + '\n',
        encoding='utf-8',
    )

    result = probe_mobile_agent_activity(
        project_root=tmp_path,
        project_id='proj-demo',
        agent='worker',
        provider='codex',
        namespace_epoch=3,
        now='2026-07-28T11:00:00Z',
        pane_capture=lambda _: 'quiet codex screen',
    )

    assert result.activity_state == 'idle'
    assert result.reason == 'codex_session_task_complete'


def test_probe_rejects_stale_namespace_binding(tmp_path: Path) -> None:
    _write_binding(tmp_path, provider='claude', agent='worker')

    result = probe_mobile_agent_activity(
        project_root=tmp_path,
        project_id='proj-demo',
        agent='worker',
        provider='claude',
        namespace_epoch=4,
        now='2026-07-28T11:00:00Z',
        pane_capture=lambda _: '❯\n',
    )

    assert result.activity_state == 'unknown'
    assert result.reason == 'provider_activity_probe_stale_binding'


def _write_binding(
    project_root: Path,
    *,
    provider: str,
    agent: str,
) -> PathLayout:
    layout = PathLayout(project_root)
    layout.runtime_state_root.mkdir(parents=True, exist_ok=True)
    runtime_path = layout.agent_runtime_path(agent)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    session_path = layout.runtime_state_root / f'.{provider}-{agent}-session'
    session = {
        'ccb_session_id': f'ccb-{agent}',
        'agent_name': agent,
        'ccb_project_id': 'proj-demo',
        'pane_id': '%2',
        'tmux_session': '%2',
        'tmux_socket_path': str(layout.runtime_state_root / 'ccbd' / 'tmux.sock'),
        'workspace_path': str(project_root),
        'work_dir': str(project_root),
    }
    if provider == 'codex':
        session['codex_home'] = str(
            layout.agent_provider_state_dir(agent, 'codex') / 'home'
        )
    session_path.write_text(json.dumps(session), encoding='utf-8')
    runtime_path.write_text(
        json.dumps(
            {
                'agent_name': agent,
                'project_id': 'proj-demo',
                'provider': provider,
                'workspace_epoch': 3,
                'workspace_path': str(project_root),
                'desired_state': 'mounted',
                'pane_state': 'alive',
                'pane_id': '%2',
                'active_pane_id': '%2',
                'tmux_socket_path': session['tmux_socket_path'],
                'tmux_window_name': 'main',
                'session_ref': str(session_path),
            }
        ),
        encoding='utf-8',
    )
    return layout
