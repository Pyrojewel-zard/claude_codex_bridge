from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from cli.models import ParsedLayoutCommand
from cli.parser import CliParser
from cli.phase2 import maybe_handle_phase2
from ccbd.services.project_namespace_state import ProjectNamespaceState, ProjectNamespaceStateStore
from storage.paths import PathLayout
import pytest


def _write_config(project_root: Path, text: str) -> None:
    path = project_root / '.ccb' / 'ccb.config'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')


def _run_phase2(args: list[str], *, cwd: Path) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    result = maybe_handle_phase2(args, cwd=cwd, stdout=stdout, stderr=stderr)
    text = stdout.getvalue().strip()
    payload = json.loads(text) if text else {}
    return result, payload, stderr.getvalue()


def test_layout_parser_supports_plan_and_smoke() -> None:
    parser = CliParser()

    assert parser.parse(['layout', 'plan', '--panes', '6', '--window-prefix', 'frontdesk', '--json']) == ParsedLayoutCommand(
        project=None,
        action='plan',
        panes=6,
        window_prefix='frontdesk',
        json_output=True,
    )
    assert parser.parse(['layout', 'smoke', '--panes', '7', '--session', 'demo', '--keep', '--json']) == ParsedLayoutCommand(
        project=None,
        action='smoke',
        panes=7,
        session_name='demo',
        cleanup=False,
        json_output=True,
    )
    assert parser.parse(['layout', 'dynamic-smoke', '--panes', '8', '--window-prefix', 'frontdesk', '--json']) == ParsedLayoutCommand(
        project=None,
        action='dynamic-smoke',
        panes=8,
        window_prefix='frontdesk',
        json_output=True,
    )
    assert parser.parse(
        [
            'layout',
            'resolve',
            'planner2',
            '--window-class',
            'plan-orchestrate',
            '--loop-id',
            'round1',
            '--node-id',
            'node1',
            '--json',
        ]
    ) == ParsedLayoutCommand(
        project=None,
        action='resolve',
        agent_name='planner2',
        window_class='plan-orchestrate',
        loop_id='round1',
        node_id='node1',
        json_output=True,
    )
    assert parser.parse(['layout', 'arrange', '--window', 'plan-orchestrate', '--timeout', '2.5', '--json']) == ParsedLayoutCommand(
        project=None,
        action='arrange',
        window_name='plan-orchestrate',
        timeout_s=2.5,
        json_output=True,
    )
    assert parser.parse(['layout', 'move-plan', 'helper1', '--window', 'review', '--json']) == ParsedLayoutCommand(
        project=None,
        action='move-plan',
        agent_name='helper1',
        window_name='review',
        json_output=True,
    )


def test_layout_arrange_reflows_mounted_window(tmp_path: Path, monkeypatch) -> None:
    import cli.services.layout as layout_service

    project_root = tmp_path / 'repo-layout-arrange'
    _write_config(
        project_root,
        """version = 2
entry_window = "main"

[windows]
main = "frontdesk:fake"
plan-orchestrate = "planner:fake, helper:fake"
""",
    )
    paths = PathLayout(project_root)
    ProjectNamespaceStateStore(paths).save(
        ProjectNamespaceState(
            project_id=paths.project_id,
            namespace_epoch=1,
            tmux_socket_path=str(project_root / 'tmux.sock'),
            tmux_session_name='ccb-test',
            workspace_window_name='main',
            workspace_window_id='@1',
        )
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_root=project_root, project_id=paths.project_id),
        paths=paths,
    )
    calls = {}

    class FakeBackend:
        def __init__(self, *, socket_path: str) -> None:
            calls['socket_path'] = socket_path

    def fake_reflow(controller, backend, *, current, topology_plan, window_name, result, timeout_s):
        calls['project_id'] = controller._project_id
        calls['backend_type'] = type(backend).__name__
        calls['session'] = current.tmux_session_name
        calls['agents'] = [list(window.agent_names) for window in topology_plan.windows if window.name == window_name][0]
        calls['window_name'] = window_name
        calls['timeout_s'] = timeout_s
        result.reflowed_windows.append(window_name)

    monkeypatch.setattr(layout_service, 'TmuxBackend', FakeBackend)
    monkeypatch.setattr(layout_service, 'ping_local_state', lambda _context: SimpleNamespace(mount_state='mounted', socket_connectable=True))
    monkeypatch.setattr(layout_service, 'session_alive', lambda _backend, _session, timeout_s=None: True)
    monkeypatch.setattr(layout_service, 'reflow_window_after_agent_change', fake_reflow)
    monkeypatch.setattr(
        layout_service,
        'layout_status',
        lambda _context: {
            'namespace': {'status': 'mounted'},
            'observed': {'observe_status': 'ok'},
            'pane_count': 3,
            'window_count': 2,
            'windows': [{'name': 'plan-orchestrate', 'agent_names': ['planner', 'helper']}],
        },
    )

    payload = layout_service.layout_command(
        context,
        ParsedLayoutCommand(project=None, action='arrange', window_name='plan-orchestrate', timeout_s=2.5, json_output=True),
    )

    assert payload['layout_status'] == 'ok'
    assert payload['arrange_status'] == 'ok'
    assert payload['window_name'] == 'plan-orchestrate'
    assert payload['reflowed_windows'] == ['plan-orchestrate']
    assert payload['reflow_errors'] == {}
    assert payload['windows'] == [{'name': 'plan-orchestrate', 'agent_names': ['planner', 'helper']}]
    assert calls == {
        'socket_path': str(project_root / 'tmux.sock'),
        'project_id': paths.project_id,
        'backend_type': 'FakeBackend',
        'session': 'ccb-test',
        'agents': ['planner', 'helper'],
        'window_name': 'plan-orchestrate',
        'timeout_s': 2.5,
    }


def test_layout_status_projects_herdr_namespace_surface(tmp_path: Path, monkeypatch) -> None:
    import cli.services.layout_status as layout_status_service

    project_root = tmp_path / 'repo-layout-herdr'
    _write_config(project_root, 'agent1:codex\n')
    paths = PathLayout(project_root)
    ProjectNamespaceStateStore(paths).save(
        ProjectNamespaceState(
            project_id=paths.project_id,
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
    context = SimpleNamespace(
        project=SimpleNamespace(project_root=project_root, project_id=paths.project_id),
        paths=paths,
    )

    monkeypatch.setattr(
        layout_status_service,
        'ping_local_state',
        lambda _context: SimpleNamespace(mount_state='mounted', socket_connectable=True),
    )

    payload = layout_status_service.layout_status(context)

    projection = payload['namespace']['herdr_surface_projection']
    assert projection['backend_impl'] == 'herdr'
    assert projection['capability_status'] == 'partial'
    assert projection['support_tier_projection'] == 'experimental'
    assert projection['support_tier_projection_source'] == 'validation_pending'
    assert projection['evidence_refs']['namespace_ref']['namespace_id'] == 'workspace-1'
    assert 'raw-secret-token' not in str(projection)


def test_layout_arrange_requires_mounted_namespace(tmp_path: Path, monkeypatch) -> None:
    import cli.services.layout as layout_service

    project_root = tmp_path / 'repo-layout-arrange-unmounted'
    _write_config(
        project_root,
        """version = 2
entry_window = "main"

[windows]
main = "frontdesk:fake"
""",
    )
    paths = PathLayout(project_root)
    context = SimpleNamespace(
        project=SimpleNamespace(project_root=project_root, project_id=paths.project_id),
        paths=paths,
    )

    def fail_reflow(*_args, **_kwargs):
        raise AssertionError('unmounted arrange must not call reflow')

    monkeypatch.setattr(layout_service, 'ping_local_state', lambda _context: SimpleNamespace(mount_state='unmounted', socket_connectable=False))
    monkeypatch.setattr(layout_service, 'reflow_window_after_agent_change', fail_reflow)

    payload = layout_service.layout_command(
        context,
        ParsedLayoutCommand(project=None, action='arrange', window_name='main', json_output=True),
    )

    assert payload['layout_status'] == 'failed'
    assert payload['arrange_status'] == 'blocked'
    assert payload['reason'] == 'namespace_not_mounted'
    assert payload['window_name'] == 'main'


def test_layout_move_plan_reports_dynamic_agent_cross_window_plan(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-layout-move-plan'
    _write_config(
        project_root,
        """version = 2
entry_window = "main"

[windows]
main = "frontdesk:fake"
plan-orchestrate = "planner:fake"
""",
    )
    layout = PathLayout(project_root)
    _write_json(
        layout.runtime_state_root / 'runtime' / 'agents' / 'helper1' / 'lifecycle.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_dynamic_agent_lifecycle',
            'agent_lifecycle_status': 'active',
            'agent': 'helper1',
            'role': 'agentroles.worker',
            'provider': 'fake',
            'workspace_mode': 'inplace',
            'target': '.',
            'lifecycle_state': 'visible',
            'visibility_state': 'visible',
            'window_name': 'plan-orchestrate',
            'placement': {
                'mode': 'window',
                'window_name': 'plan-orchestrate',
                'layout_policy': 'append-or-create-window',
            },
            'apply': {
                'apply_status': 'applied',
                'plan_class': 'add_agent',
                'stage': 'publish_transaction',
            },
        },
    )

    result, payload, stderr = _run_phase2(['layout', 'move-plan', 'helper1', '--window', 'review', '--json'], cwd=project_root)

    assert result == 0, stderr
    assert payload['layout_status'] == 'planned'
    assert payload['move_plan_status'] == 'planned'
    assert payload['plan_class'] == 'move_dynamic_agent'
    assert payload['read_only'] is True
    assert payload['mutation_performed'] is False
    assert payload['apply_command_supported'] is False
    assert payload['agent'] == 'helper1'
    assert payload['agent_source'] == 'dynamic'
    assert payload['source_window_name'] == 'plan-orchestrate'
    assert payload['target_window_name'] == 'review'
    assert payload['target_window_exists'] is False
    assert payload['will_create_window'] is True
    assert payload['source_window_agent_names'] == ['planner', 'helper1']
    assert payload['source_window_would_be_agent_names'] == ['planner']
    assert payload['target_window_agent_names'] == []
    assert payload['target_window_would_be_agent_names'] == ['helper1']


def test_layout_move_plan_blocks_static_agent_cross_window_move(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-layout-move-plan-static'
    _write_config(
        project_root,
        """version = 2
entry_window = "main"

[windows]
main = "frontdesk:fake"
review = "reviewer:fake"
""",
    )

    result, payload, stderr = _run_phase2(['layout', 'move-plan', 'frontdesk', '--window', 'review', '--json'], cwd=project_root)

    assert result == 1, stderr
    assert payload['layout_status'] == 'failed'
    assert payload['move_plan_status'] == 'blocked'
    assert payload['reason'] == 'configured_agent_not_movable'
    assert payload['source_window_name'] == 'main'
    assert payload['target_window_name'] == 'review'
    assert payload['target_window_exists'] is True
    assert payload['target_window_would_be_agent_names'] == ['reviewer', 'frontdesk']


def test_layout_move_plan_same_window_is_noop_for_static_agent(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-layout-move-plan-noop'
    _write_config(
        project_root,
        """version = 2
entry_window = "main"

[windows]
main = "frontdesk:fake"
""",
    )

    result, payload, stderr = _run_phase2(['layout', 'move-plan', 'frontdesk', '--window', 'main', '--json'], cwd=project_root)

    assert result == 0, stderr
    assert payload['layout_status'] == 'planned'
    assert payload['move_plan_status'] == 'noop'
    assert payload['reason'] == 'same_window'
    assert payload['source_window_name'] == 'main'
    assert payload['target_window_name'] == 'main'
    assert payload['same_window'] is True


def test_layout_plan_json_reports_one_to_six_and_overflow(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-layout-cli'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    stdout = StringIO()
    stderr = StringIO()

    code = maybe_handle_phase2(
        ['layout', 'plan', '--panes', '7', '--window-prefix', 'frontdesk-dialog', '--json'],
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload['layout_status'] == 'planned'
    assert payload['pane_count'] == 7
    assert [window['name'] for window in payload['windows']] == ['frontdesk-dialog', 'frontdesk-dialog-2']
    assert payload['windows'][0]['layout_spec'] == 'p1, p3, p5; p2, p4, p6'
    assert payload['windows'][1]['layout_spec'] == 'p7'


def test_layout_dynamic_smoke_grows_and_shrinks_pages(tmp_path: Path) -> None:
    if shutil.which('tmux') is None:
        pytest.skip('tmux is not installed')
    project_root = tmp_path / 'repo-layout-dynamic-smoke'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    stdout = StringIO()
    stderr = StringIO()

    code = maybe_handle_phase2(
        ['layout', 'dynamic-smoke', '--panes', '7', '--window-prefix', 'frontdesk-dialog', '--json'],
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload['layout_status'] == 'ok'
    assert payload['dynamic_status'] == 'ok'
    assert payload['cleanup_status'] == 'ok'
    events = payload['dynamic_events']
    assert [event['target_count'] for event in events] == [1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2, 1]
    assert events[6]['phase'] == 'grow'
    assert events[6]['window_count'] == 2
    assert [window['pane_count'] for window in events[6]['observed_windows']] == [6, 1]
    assert events[7]['phase'] == 'shrink'
    assert events[7]['agent'] == 'p7'
    assert events[7]['window_count'] == 1
    assert [window['pane_count'] for window in events[7]['observed_windows']] == [6]
    assert all(event['all_retained_alive'] for event in events)
