from __future__ import annotations

from io import StringIO
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from agents.models import AgentState
from ccbd.app import CcbdApp
import ccbd.handlers.project_restart as project_restart
from ccbd.handlers.project_restart import build_project_restart_agent_handler
from ccbd.socket_client import CcbdClient, CcbdClientError
from cli.models import ParsedRestartCommand
from cli.parser import CliParser, CliUsageError
from cli.phase2 import maybe_handle_phase2


class _Registry:
    def __init__(self, runtimes: dict[str, object]) -> None:
        self._runtimes = runtimes

    def get(self, agent_name: str):
        return self._runtimes.get(agent_name)


class _Dispatcher:
    def __init__(
        self,
        *,
        queue_agent: dict[str, object] | None = None,
        active_job_id: str | None = None,
        callback_edges: tuple[object, ...] = (),
    ) -> None:
        self._queue_agent = queue_agent or {
            'queue_depth': 0,
            'pending_reply_count': 0,
            'active_inbound_event_id': None,
        }
        self._state = SimpleNamespace(active_job=lambda agent_name: active_job_id)
        self._message_bureau = SimpleNamespace(pending_callback_edges=lambda: callback_edges)

    def queue(self, agent_name: str) -> dict[str, object]:
        return {'target': agent_name, 'agent': dict(self._queue_agent)}


def _runtime(*, state=AgentState.IDLE, queue_depth: int = 0, pane_id: str = '%1'):
    return SimpleNamespace(
        state=state,
        queue_depth=queue_depth,
        health='healthy',
        pane_id=pane_id,
        active_pane_id=pane_id,
        runtime_ref=f'tmux:{pane_id}',
        session_ref='session-1',
        runtime_pid=123,
        restart_count=0,
    )


def _app(*, runtimes: dict[str, object], dispatcher=None):
    return SimpleNamespace(
        config=SimpleNamespace(agents={'agent1': object(), 'agent2': object()}),
        registry=_Registry(runtimes),
        dispatcher=dispatcher or _Dispatcher(),
        start_maintenance_lock=threading.Lock(),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _wait_for_socket(path: Path, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        if path.exists():
            try:
                payload = CcbdClient(path, timeout_s=1.0).ping('ccbd')
                diagnostics = payload.get('diagnostics')
                stage = diagnostics.get('startup_stage') if isinstance(diagnostics, dict) else None
                if stage in {None, '', 'mounted'}:
                    return
                last_error = f'startup_stage={stage}'
            except CcbdClientError as exc:
                last_error = str(exc)
        time.sleep(0.05)
    raise AssertionError(f'timed out waiting for {path}; last_error={last_error!r}')


def test_restart_parser_accepts_single_agent_and_rejects_all() -> None:
    parser = CliParser()

    assert parser.parse(['restart', 'agent1']) == ParsedRestartCommand(project=None, agent_name='agent1')

    with pytest.raises(CliUsageError, match='restart all is not supported'):
        parser.parse(['restart', 'all'])
    with pytest.raises(CliUsageError, match='restart requires exactly one'):
        parser.parse(['restart', 'agent1', 'agent2'])


def test_phase2_restart_sends_request_and_renders_summary(monkeypatch, tmp_path: Path) -> None:
    import cli.phase2 as phase2_module

    fake_context = SimpleNamespace(project=SimpleNamespace(project_root=tmp_path, project_id='proj-restart'))
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(phase2_module, '_build_context', lambda command, cwd, out: fake_context)
    monkeypatch.setattr(phase2_module, 'ensure_bootstrap_project_config', lambda project_root: None)

    def _restart_agent(context, command):
        calls.append((context.project.project_id, command.agent_name))
        return {
            'restart_status': 'ok',
            'agent_name': command.agent_name,
            'restartable_agents': ['agent1', 'agent2'],
            'busy_gate': {
                'passed': True,
                'runtime_state': 'idle',
                'runtime_queue_depth': 0,
                'queue_depth': 0,
                'pending_reply_count': 0,
                'active_job_id': None,
                'active_inbound_event_id': None,
                'pending_callback_count': 0,
            },
            'old_runtime': {'state': 'idle', 'health': 'healthy', 'pane_id': '%1', 'active_pane_id': '%1'},
            'new_runtime': {'state': 'idle', 'health': 'healthy', 'pane_id': '%2', 'active_pane_id': '%2'},
            'result': {'agent': command.agent_name, 'status': 'restarted', 'pane_id': '%2'},
        }

    monkeypatch.setattr(phase2_module, 'restart_agent', _restart_agent)

    stdout = StringIO()
    stderr = StringIO()
    code = maybe_handle_phase2(['restart', 'agent1'], cwd=tmp_path, stdout=stdout, stderr=stderr)

    assert code == 0
    assert calls == [('proj-restart', 'agent1')]
    assert 'restart_status: ok\n' in stdout.getvalue()
    assert 'agent_name: agent1\n' in stdout.getvalue()
    assert 'restart_busy_gate: passed=true' in stdout.getvalue()
    assert 'old_runtime: state=idle health=healthy pane_id=%1 active_pane_id=%1' in stdout.getvalue()
    assert 'new_runtime: state=idle health=healthy pane_id=%2 active_pane_id=%2' in stdout.getvalue()
    assert stderr.getvalue() == ''


def test_restart_service_uses_current_mounted_daemon(monkeypatch) -> None:
    import cli.services.restart as restart_module

    calls: list[str] = []

    class _Client:
        def project_restart_agent(self, agent_name: str) -> dict:
            calls.append(agent_name)
            return {'restart_status': 'ok', 'agent_name': agent_name}

    monkeypatch.setattr(
        restart_module,
        'connect_current_mounted_daemon',
        lambda context: SimpleNamespace(client=_Client()),
    )

    payload = restart_module.restart_agent(
        SimpleNamespace(),
        ParsedRestartCommand(project=None, agent_name='agent1'),
    )

    assert payload == {'restart_status': 'ok', 'agent_name': 'agent1'}
    assert calls == ['agent1']


def test_project_restart_agent_handler_rejects_unknown_with_current_graph_list() -> None:
    handler = build_project_restart_agent_handler(_app(runtimes={}))

    payload = handler({'agent_name': 'missing'})

    assert payload['restart_status'] == 'failed'
    assert payload['reason'] == 'unknown_agent'
    assert payload['restartable_agents'] == ['agent1', 'agent2']


def test_project_restart_agent_handler_blocks_busy_runtime(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        project_restart,
        'restart_project_agent_panes_in_place',
        lambda app, *, agent_names: calls.append(agent_names),
    )
    handler = build_project_restart_agent_handler(
        _app(runtimes={'agent1': _runtime(state=AgentState.BUSY)})
    )

    payload = handler({'agent_name': 'agent1'})

    assert payload['restart_status'] == 'blocked'
    assert payload['busy_gate']['passed'] is False
    assert {'reason': 'runtime_active', 'detail': 'state=busy'} in payload['blockers']
    assert calls == []


def test_project_restart_agent_handler_blocks_pending_reply_and_callback(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        project_restart,
        'restart_project_agent_panes_in_place',
        lambda app, *, agent_names: calls.append(agent_names),
    )
    edge = SimpleNamespace(
        edge_id='cb_1',
        parent_agent='agent1',
        callback_target_agent='agent1',
        child_job_id='job_child',
        state=SimpleNamespace(value='child_completed'),
    )
    dispatcher = _Dispatcher(
        queue_agent={
            'queue_depth': 1,
            'pending_reply_count': 1,
            'active_inbound_event_id': 'iev_reply',
        },
        callback_edges=(edge,),
    )
    handler = build_project_restart_agent_handler(
        _app(runtimes={'agent1': _runtime()}, dispatcher=dispatcher)
    )

    payload = handler({'agent_name': 'agent1'})

    assert payload['restart_status'] == 'blocked'
    reasons = [item['reason'] for item in payload['blockers']]
    assert 'queue_depth' in reasons
    assert 'pending_reply_delivery' in reasons
    assert 'active_inbound_delivery' in reasons
    assert 'pending_chain_continuation' in reasons
    assert calls == []


def test_project_restart_agent_handler_blocks_on_stale_role_digest(monkeypatch, tmp_path: Path) -> None:
    session = SimpleNamespace(
        data={
            'ccb_role_id': 'test.locked',
            'ccb_role_version': '1.0.0',
            'ccb_role_digest': 'sha256:olddigest',
        },
        start_cmd='reuse-session',
    )
    monkeypatch.setattr(
        project_restart,
        '_load_agent_provider_session',
        lambda app, agent_name, runtime: session,
    )
    monkeypatch.setattr(
        project_restart,
        'load_installed_role',
        lambda role_id: SimpleNamespace(id='test.locked', version='2.0.0', root=tmp_path / 'roles' / 'test.locked'),
    )
    monkeypatch.setattr(project_restart, 'installed_role_metadata', lambda role_id: {'digest': 'sha256:newdigest'})

    app = _app(runtimes={'agent1': _runtime(pane_id='%1')})
    app.project_namespace = SimpleNamespace(
        load=lambda: SimpleNamespace(tmux_socket_path=str(tmp_path / '.tmux' / 'tmux.sock'))
    )
    handler = build_project_restart_agent_handler(app)

    payload = handler({'agent_name': 'agent1'})

    assert payload['status'] == 'failed'
    assert payload['restart_status'] == 'failed'
    assert payload['reason'] == 'role_digest_changed_fresh_restart_unsupported'
    assert payload['result']['status'] == 'failed'
    assert payload['result']['reason'] == 'role_digest_changed_fresh_restart_unsupported'
    assert payload['result']['detail'].startswith('role_id=test.locked launch_version=1.0.0')


def test_project_restart_agent_handler_restarts_one_agent(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def _restart(app_arg, *, agent_names):
        calls.append(agent_names)
        return ({'agent': agent_names[0], 'status': 'restarted', 'pane_id': '%9'},)

    monkeypatch.setattr(project_restart, 'restart_project_agent_panes_in_place', _restart)
    handler = build_project_restart_agent_handler(
        _app(runtimes={'agent1': _runtime(pane_id='%1'), 'agent2': _runtime(pane_id='%2')})
    )

    payload = handler({'agent_name': 'agent1'})

    assert payload['restart_status'] == 'ok'
    assert payload['agent_name'] == 'agent1'
    assert payload['old_runtime']['pane_id'] == '%1'
    assert payload['result'] == {'agent': 'agent1', 'status': 'restarted', 'pane_id': '%9'}
    assert calls == [('agent1',)]


def test_project_restart_agent_handler_defers_herdr_namespace_without_tmux_backend(monkeypatch) -> None:
    def _tmux_backend(*_args, **_kwargs):
        raise AssertionError('Herdr restart must not create TmuxBackend')

    monkeypatch.setattr(project_restart, 'TmuxBackend', _tmux_backend)
    app = _app(runtimes={'agent1': _runtime(pane_id='herdr-pane-1')})
    app.project_namespace = SimpleNamespace(
        load=lambda: SimpleNamespace(
            namespace_backend_family='herdr-native',
            backend_impl='herdr',
            tmux_socket_path='',
        )
    )
    handler = build_project_restart_agent_handler(app)

    payload = handler({'agent_name': 'agent1'})

    assert payload['status'] == 'unsupported'
    assert payload['restart_status'] == 'deferred'
    assert payload['reason'] == 'deferred_to_provider_runtime_on_herdr'
    assert payload['result']['status'] == 'deferred'
    assert payload['result']['backend_impl'] == 'herdr'
    assert payload['result']['restart_evidence'] == {
        'backend_impl': 'herdr',
        'namespace_backend_family': 'herdr-native',
        'restart_surface': 'provider_runtime_required',
        'restart_status': 'deferred',
        'reason': 'deferred_to_provider_runtime_on_herdr',
        'respawn_evidence': 'not_attempted',
        'session_binding_evidence': 'not_attempted',
        'agent': 'agent1',
    }
    assert payload['old_runtime']['pane_id'] == 'herdr-pane-1'
    assert payload['new_runtime']['pane_id'] == 'herdr-pane-1'


def test_project_restart_agent_socket_targets_one_agent(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-restart-socket'
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex,agent2:codex\n')
    app = CcbdApp(project_root)
    monkeypatch.setattr(
        app,
        'execute_project_stop',
        lambda **kwargs: SimpleNamespace(to_record=lambda: {'status': 'ok'}),
    )
    calls: list[tuple[str, ...]] = []

    def _restart(app_arg, *, agent_names):
        calls.append(agent_names)
        return ({'agent': agent_names[0], 'status': 'restarted', 'pane_id': '%7'},)

    monkeypatch.setattr(project_restart, 'restart_project_agent_panes_in_place', _restart)

    thread = threading.Thread(target=app.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    _wait_for_socket(app.paths.ccbd_socket_path)
    client = CcbdClient(app.paths.ccbd_socket_path)

    payload = client.project_restart_agent('agent1')
    client.shutdown()
    thread.join(timeout=2)

    assert payload['restart_status'] == 'ok'
    assert payload['agent_name'] == 'agent1'
    assert calls == [('agent1',)]
    assert not thread.is_alive()
