from __future__ import annotations

from cli.render_runtime.ops_views_doctor import render_doctor


def test_doctor_render_keeps_release_surface_separate_from_legacy_backend_rows() -> None:
    payload = {
        'project': '/tmp/repo',
        'project_id': 'proj-1',
        'installation': {},
        'entrypoint': {},
        'runtime': {},
        'requirements': {},
        'ccbd': {
            'state': 'unmounted',
            'health': 'unknown',
            'generation': 0,
            'last_heartbeat_at': None,
            'pid_alive': False,
            'socket_connectable': False,
            'heartbeat_fresh': False,
            'takeover_allowed': True,
            'reason': 'not_started',
            'active_execution_count': 0,
            'recoverable_execution_count': 0,
            'nonrecoverable_execution_count': 0,
            'pending_items_count': 0,
            'terminal_pending_count': 0,
            'recoverable_execution_providers': [],
            'nonrecoverable_execution_providers': [],
        },
        'active_inbound_diagnostics': [],
        'agents': [
            {
                'agent_name': 'demo',
                'provider': 'fake',
                'health': 'healthy',
                'completion_family': 'protocol_turn',
                'binding_status': 'ready',
                'runtime_ref': 'rmux:%1',
                'session_ref': 'rmux-session',
                'binding_source': 'legacy-backend',
                'workspace_path': '/tmp/repo',
                'terminal': 'rmux',
                'tmux_socket_name': None,
                'tmux_socket_path': None,
                'tmux_window_name': 'main',
                'tmux_window_id': '@1',
                'pane_id': '%1',
                'active_pane_id': '%1',
                'pane_title_marker': 'CCB-demo',
                'pane_state': 'alive',
                'execution_resume_supported': True,
                'execution_restore_mode': 'provider_resume',
                'execution_restore_reason': None,
                'execution_restore_detail': 'resume ok',
            }
        ],
    }

    lines = render_doctor(payload)

    assert any('terminal=rmux' in line and 'runtime=rmux:%1' in line for line in lines)
    assert not any(line.startswith('windows_x64_release_surface:') for line in lines)
