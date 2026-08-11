from __future__ import annotations

from types import SimpleNamespace

from cli.context import CliContextBuilder
from cli.models import ParsedPsCommand
from cli.services.ps import ps_summary
from ccbd.services.project_namespace_state import ProjectNamespaceState, ProjectNamespaceStateStore
from project.resolver import bootstrap_project


def test_ps_summary_includes_tmux_socket_and_pane_observation(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-ps'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('agent1:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = CliContextBuilder().build(ParsedPsCommand(project=None), cwd=project_root, bootstrap_if_missing=False)

    runtime = SimpleNamespace(
        state=SimpleNamespace(value='idle'),
        queue_depth=0,
        backend_type='pane_backed',
        binding_source=SimpleNamespace(value='provider-session'),
        runtime_ref='tmux:%52',
        session_ref='session-2',
        session_file=None,
        session_id='session-2',
        workspace_path=str(project_root / '.ccb' / 'workspaces' / 'agent1'),
        terminal_backend='tmux',
        tmux_socket_name='sock-a',
        tmux_socket_path='/tmp/ccb.sock',
        tmux_window_name='main',
        tmux_window_id='@1',
        pane_id='%41',
        active_pane_id='%52',
        pane_title_marker='CCB-agent1-demo',
        pane_state='alive',
    )

    class _Store:
        def __init__(self, paths) -> None:
            self.paths = paths

        def load(self, agent_name: str):
            return runtime if agent_name == 'agent1' else None

    monkeypatch.setattr('cli.services.ps.AgentRuntimeStore', _Store)
    monkeypatch.setattr('cli.services.ps.ping_local_state', lambda context: SimpleNamespace(mount_state='mounted'))

    payload = ps_summary(context, ParsedPsCommand(project=None))

    assert payload['ccbd_state'] == 'mounted'
    assert len(payload['agents']) == 1
    agent = payload['agents'][0]
    assert agent['runtime_ref'] == 'tmux:%52'
    assert agent['session_ref'] == 'session-2'
    assert agent['tmux_socket_name'] == 'sock-a'
    assert agent['tmux_socket_path'] == '/tmp/ccb.sock'
    assert agent['tmux_window_name'] == 'main'
    assert agent['tmux_window_id'] == '@1'
    assert agent['pane_id'] == '%41'
    assert agent['active_pane_id'] == '%52'
    assert agent['pane_title_marker'] == 'CCB-agent1-demo'
    assert agent['pane_state'] == 'alive'


def test_ps_summary_degrades_cached_alive_runtime_when_ccbd_is_stale(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-ps-stale'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('agent1:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = CliContextBuilder().build(ParsedPsCommand(project=None), cwd=project_root, bootstrap_if_missing=False)

    runtime = SimpleNamespace(
        state=SimpleNamespace(value='idle'),
        queue_depth=0,
        backend_type='pane_backed',
        binding_source=SimpleNamespace(value='provider-session'),
        runtime_ref='tmux:%52',
        session_ref='session-2',
        session_file=None,
        session_id='session-2',
        workspace_path=str(project_root / '.ccb' / 'workspaces' / 'agent1'),
        terminal_backend='tmux',
        tmux_socket_name='sock-a',
        tmux_socket_path='/tmp/ccb.sock',
        tmux_window_name='main',
        tmux_window_id='@1',
        pane_id='%41',
        active_pane_id='%52',
        pane_title_marker='CCB-agent1-demo',
        pane_state='alive',
    )

    class _Store:
        def __init__(self, paths) -> None:
            self.paths = paths

        def load(self, agent_name: str):
            return runtime if agent_name == 'agent1' else None

    monkeypatch.setattr('cli.services.ps.AgentRuntimeStore', _Store)
    monkeypatch.setattr(
        'cli.services.ps.ping_local_state',
        lambda context: SimpleNamespace(
            mount_state='mounted',
            health='stale',
            reason='pid_missing,heartbeat_stale,socket_unreachable',
            pid_alive=False,
            socket_connectable=False,
            heartbeat_fresh=False,
        ),
    )

    payload = ps_summary(context, ParsedPsCommand(project=None))

    assert payload['ccbd_state'] == 'stale'
    assert payload['ccbd_mount_state'] == 'mounted'
    assert payload['ccbd_reason'] == 'pid_missing,heartbeat_stale,socket_unreachable'
    assert len(payload['agents']) == 1
    agent = payload['agents'][0]
    assert agent['state'] == 'degraded'
    assert agent['binding_status'] == 'stale'
    assert agent['pane_state'] == 'missing'


def test_ps_summary_projects_herdr_namespace_surface(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-ps-herdr'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('agent1:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = CliContextBuilder().build(ParsedPsCommand(project=None), cwd=project_root, bootstrap_if_missing=False)
    ProjectNamespaceStateStore(context.paths).save(
        ProjectNamespaceState(
            project_id=context.project.project_id,
            namespace_epoch=4,
            tmux_socket_path='',
            tmux_session_name='ccb-herdr',
            namespace_backend_family='herdr-native',
            backend_impl='herdr',
            namespace_id='workspace-1',
            namespace_session_name='ccb-herdr',
            namespace_ipc_kind='herdr_socket',
            namespace_ipc_ref='herdr://workspace-1',
            namespace_restore_token='raw-secret-token',
        )
    )

    monkeypatch.setattr('cli.services.ps.ping_local_state', lambda context: SimpleNamespace(mount_state='mounted'))

    payload = ps_summary(context, ParsedPsCommand(project=None))

    projection = payload['herdr_surface_projection']
    assert projection['backend_impl'] == 'herdr'
    assert projection['capability_status'] == 'partial'
    assert projection['support_tier_projection'] == 'experimental'
    assert projection['support_tier_projection_source'] == 'validation_pending'
    assert projection['degraded_next_action'] is None
    assert projection['evidence_refs']['namespace_ref'] == {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'session_name': 'ccb-herdr',
        'ipc_kind': 'herdr_socket',
        'ipc_ref': 'herdr://workspace-1',
    }
    assert 'raw-secret-token' not in str(projection)
