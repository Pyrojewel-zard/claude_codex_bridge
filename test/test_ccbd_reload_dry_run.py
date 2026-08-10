from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.config_loader import load_project_config
from ccbd.app import CcbdApp
from ccbd.models import LeaseHealth, LeaseInspection
import ccbd.handlers.project_reload as project_reload_handler
from ccbd.reload_handoff import ReloadHandoffStore
from ccbd.reload_plan import build_reload_dry_run_plan
from ccbd.socket_client import CcbdClient
from cli.context import CliContext
from cli.models import ParsedReloadCommand
from cli.parser import CliParser
from cli.phase2 import maybe_handle_phase2
from cli.render import render_reload
from cli.services.reload import reload_config
from project.resolver import bootstrap_project
from storage.paths import PathLayout


BASE_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""


def test_reload_dry_run_no_change_updates_metrics_without_mutation(tmp_path: Path, monkeypatch) -> None:
    project_root = _project(tmp_path / 'repo-no-change', BASE_CONFIG)
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    before_snapshot = _runtime_file_snapshot(project_root)
    load_calls: list[Path] = []
    original_load = project_reload_handler.load_project_config

    def _load_once(root):
        load_calls.append(Path(root))
        return original_load(root)

    _block_mutation_paths(app, monkeypatch)
    monkeypatch.setattr(project_reload_handler, 'load_project_config', _load_once)

    assert app.control_plane_metrics.last_reload_duration_s is None

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': True})

    assert payload['status'] == 'ok'
    assert payload['plan_class'] == 'no_change'
    assert payload['operations'] == []
    assert payload['drain_intents'] == []
    assert payload['namespace_patch_plan']['status'] == 'no_op'
    assert payload['safe_to_apply'] is False
    assert payload['future_safe_to_apply'] is True
    assert payload['mutation_enabled'] is False
    assert load_calls == [project_root]
    assert _runtime_file_snapshot(project_root) == before_snapshot
    assert app.service_graph.version == 1
    assert app.config_identity['config_signature'] == payload['old_config_signature']
    assert app.config_identity['config_signature'] == payload['new_config_signature']
    assert app.control_plane_metrics.last_reload_duration_s is not None
    assert app.control_plane_metrics.last_reload_plan_class == 'no_change'
    assert app.control_plane_metrics.last_reload_error is None


@pytest.mark.parametrize(
    ('new_text', 'expected_class', 'expected_ops'),
    [
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent2:claude, agent3:codex'),
            'add_agent',
            {'add_agent'},
        ),
        (
            """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
""",
            'add_window',
            {'add_window', 'add_agent'},
        ),
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex'),
            'remove_agent',
            {'remove_agent'},
        ),
        (
            BASE_CONFIG.replace('agent2:claude', 'agent2:codex'),
            'replace_agent',
            {'replace_agent'},
        ),
        (
            BASE_CONFIG
            + '''
[agents.agent1]
model = "gpt-5.5"
thinking = "high"
''',
            'replace_agent',
            {'replace_agent'},
        ),
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent2:claude, agent1:codex'),
            'layout_change',
            {'layout_change'},
        ),
        (
            """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"

[ui.sidebar]
mode = "every_window"
""".replace(
                'main = "agent1:codex, agent2:claude"\nreview = "agent3:codex"',
                'main = "agent1:codex, agent3:codex"\nreview = "agent2:claude"',
            ),
            'move_agent',
            {'move_agent'},
        ),
    ],
)
def test_reload_plan_classifies_runtime_and_layout_changes(
    tmp_path: Path,
    new_text: str,
    expected_class: str,
    expected_ops: set[str],
) -> None:
    current = _load_config(tmp_path / 'current', BASE_CONFIG)
    new = _load_config(tmp_path / 'new', new_text)

    plan = build_reload_dry_run_plan(current, new)

    assert plan['status'] == 'ok'
    assert plan['plan_class'] == expected_class
    assert expected_ops <= {item['op'] for item in plan['operations']}
    if expected_ops & {'remove_agent', 'replace_agent'}:
        assert plan['drain_intents']
    else:
        assert plan['drain_intents'] == []
    assert 'namespace_patch_plan' in plan
    assert plan['safe_to_apply'] is False
    assert plan['mutation_enabled'] is False


@pytest.mark.parametrize(
    ('old_hapi', 'new_hapi'),
    [
        ('', '\n[hapi]\nenabled = true\n'),
        ('\n[hapi]\nenabled = true\n', '\n[hapi]\nenabled = false\n'),
        (
            '\n[hapi]\nenabled = true\ncommand = "hapi"\n',
            '\n[hapi]\nenabled = true\ncommand = "/opt/hapi-v2"\n',
        ),
    ],
)
def test_reload_plan_replaces_every_existing_agent_when_hapi_launch_config_changes(
    tmp_path: Path,
    old_hapi: str,
    new_hapi: str,
) -> None:
    current = _load_config(tmp_path / 'current-hapi', BASE_CONFIG + old_hapi)
    new = _load_config(tmp_path / 'new-hapi', BASE_CONFIG + new_hapi)

    plan = build_reload_dry_run_plan(current, new)

    replace_ops = [item for item in plan['operations'] if item['op'] == 'replace_agent']
    assert plan['plan_class'] == 'replace_agent'
    assert {item['agent'] for item in replace_ops} == {'agent1', 'agent2'}
    assert all('hapi' in item['fields'] for item in replace_ops)
    assert len(plan['drain_intents']) == 2


def test_reload_plan_classifies_tool_window_add_remove_and_change(tmp_path: Path) -> None:
    current = _load_config(tmp_path / 'current-tool', BASE_CONFIG)
    added = _load_config(
        tmp_path / 'new-tool-add',
        BASE_CONFIG
        + """
[tool_windows.files]
command = "ccb-workbench files"
""",
    )

    add_plan = build_reload_dry_run_plan(current, added, project_id='project-1', current_namespace=_namespace('project-1'))

    assert add_plan['plan_class'] == 'add_tool_window'
    assert {item['op'] for item in add_plan['operations']} == {'add_tool_window'}
    assert add_plan['future_safe_to_apply'] is True
    assert add_plan['namespace_patch_plan']['status'] == 'planned'
    assert any(step['action'] == 'create_tool_pane' for step in add_plan['namespace_patch_plan']['steps'])
    assert add_plan['new_known_agents'] == ['agent1', 'agent2']

    remove_plan = build_reload_dry_run_plan(added, current, project_id='project-1', current_namespace=_namespace('project-1'))

    assert remove_plan['plan_class'] == 'remove_tool_window'
    assert {item['op'] for item in remove_plan['operations']} == {'remove_tool_window'}
    assert remove_plan['future_safe_to_apply'] is True
    assert any(step['action'] == 'kill_tool_window' for step in remove_plan['namespace_patch_plan']['steps'])

    changed = _load_config(
        tmp_path / 'new-tool-change',
        BASE_CONFIG
        + """
[tool_windows.files]
command = "files"
""",
    )
    change_plan = build_reload_dry_run_plan(added, changed, project_id='project-1', current_namespace=_namespace('project-1'))

    assert change_plan['plan_class'] == 'change_tool_window'
    assert {item['op'] for item in change_plan['operations']} == {'change_tool_window'}
    assert change_plan['future_safe_to_apply'] is False
    assert change_plan['namespace_patch_plan']['status'] == 'blocked'


def test_reload_plan_treats_tool_window_label_and_visibility_as_view_only(tmp_path: Path) -> None:
    current = _load_config(
        tmp_path / 'current-tool-view',
        BASE_CONFIG
        + """
[tool_windows.files]
command = "ccb-workbench files"
label = "files"
show_in_sidebar = true
""",
    )
    new = _load_config(
        tmp_path / 'new-tool-view',
        BASE_CONFIG
        + """
[tool_windows.files]
command = "ccb-workbench files"
label = "editor"
show_in_sidebar = false
""",
    )

    plan = build_reload_dry_run_plan(
        current,
        new,
        project_id='project-1',
        current_namespace=_namespace('project-1'),
    )

    assert plan['plan_class'] == 'view_only_change'
    assert plan['old_config_signature'] == plan['new_config_signature']
    assert plan['namespace_patch_plan']['status'] == 'planned'
    assert plan['namespace_patch_plan']['steps'][0]['action'] == 'refresh_project_view'


def test_reload_plan_classifies_sidebar_view_only_change(tmp_path: Path) -> None:
    current = _load_config(
        tmp_path / 'current-view',
        BASE_CONFIG
        + """
[ui.sidebar.view]
agents_height = "50%"
comms_height = "15%"
tips_height = "35%"
comms_limit = 4
tips = ["C-b d detach"]
""",
    )
    new = _load_config(
        tmp_path / 'new-view',
        BASE_CONFIG
        + """
[ui.sidebar.view]
agents_height = "60%"
comms_height = "10%"
tips_height = "30%"
comms_limit = 5
tips = ["C-b c new win"]
""",
    )

    plan = build_reload_dry_run_plan(current, new)

    assert plan['plan_class'] == 'view_only_change'
    assert plan['operations'][0]['op'] == 'view_only_change'
    assert plan['drain_intents'] == []
    assert plan['namespace_patch_plan']['status'] == 'planned'
    assert plan['old_config_signature'] == plan['new_config_signature']
    assert plan['future_safe_to_apply'] is True


def test_reload_plan_classifies_maintenance_only_change(tmp_path: Path) -> None:
    current = _load_config(
        tmp_path / 'current-maintenance',
        BASE_CONFIG
        + """
[maintenance.heartbeat]
enabled = false
assessor = "ccb_self"
interval_s = 3600
min_interval_s = 300
unknown_streak_cap = 3
escalation_policy = "report_only"
startup_ensure = true
""",
    )
    new = _load_config(
        tmp_path / 'new-maintenance',
        BASE_CONFIG
        + """
[maintenance.heartbeat]
enabled = true
assessor = "ccb_self"
interval_s = 900
min_interval_s = 120
unknown_streak_cap = 4
escalation_policy = "ask_user"
startup_ensure = true
""",
    )

    plan = build_reload_dry_run_plan(current, new)

    assert plan['status'] == 'ok'
    assert plan['plan_class'] == 'maintenance_change'
    assert plan['old_config_signature'] != plan['new_config_signature']
    assert plan['operations'] == [
        {
            'op': 'maintenance_change',
            'fields': ['enabled', 'escalation_policy', 'interval_s', 'min_interval_s', 'unknown_streak_cap'],
            'reason': 'maintenance heartbeat policy changed',
        }
    ]
    assert plan['drain_intents'] == []
    assert plan['future_safe_to_apply'] is True
    assert plan['namespace_patch_plan']['status'] == 'planned'
    assert plan['namespace_patch_plan']['steps'][0]['action'] == 'refresh_project_view'


def test_reload_dry_run_invalid_config_is_structured_and_non_mutating(tmp_path: Path, monkeypatch) -> None:
    project_root = _project(tmp_path / 'repo-invalid', BASE_CONFIG)
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    before_identity = dict(app.config_identity)
    before_snapshot = _runtime_file_snapshot(project_root)
    _block_mutation_paths(app, monkeypatch)
    _write_config(project_root, 'version = 2\n\n[windows]\nmain = "agent1"\n')

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': True})

    assert payload['status'] == 'invalid_config'
    assert payload['plan_class'] == 'invalid_config'
    assert payload['errors']
    assert payload['safe_to_apply'] is False
    assert app.config_identity == before_identity
    assert _runtime_file_snapshot(project_root) == before_snapshot
    assert app.control_plane_metrics.last_reload_plan_class == 'invalid_config'
    assert app.control_plane_metrics.last_reload_error


def test_reload_dry_run_missing_project_config_is_invalid_not_default_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _project(tmp_path / 'repo-missing-config', BASE_CONFIG)
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    before_identity = dict(app.config_identity)
    before_snapshot = _runtime_file_snapshot(project_root)
    _block_mutation_paths(app, monkeypatch)
    (project_root / '.ccb' / 'ccb.config').unlink()

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': True})

    assert payload['status'] == 'invalid_config'
    assert payload['plan_class'] == 'invalid_config'
    assert payload['errors'] == [f'project config not found: {project_root / ".ccb" / "ccb.config"}']
    assert app.config_identity == before_identity
    assert _runtime_file_snapshot(project_root) == before_snapshot
    assert app.control_plane_metrics.last_reload_plan_class == 'invalid_config'
    assert app.control_plane_metrics.last_reload_error


def test_reload_non_dry_run_no_change_is_successful_noop_without_mutation(tmp_path: Path) -> None:
    project_root = _project(tmp_path / 'repo-block-no-change', BASE_CONFIG)
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    before_snapshot = _runtime_file_snapshot(project_root)
    before_graph = app.service_graph

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'noop'
    assert payload['dry_run'] is False
    assert payload['mutation_enabled'] is False
    assert payload['plan_class'] == 'no_change'
    assert payload['stage'] == 'no_op'
    assert payload['diagnostics']['reason'] == 'no_change'
    assert payload['diagnostics']['graph_published'] is False
    assert app.service_graph is before_graph
    assert _runtime_file_snapshot(project_root) == before_snapshot
    assert app.control_plane_metrics.last_reload_duration_s is not None
    assert app.control_plane_metrics.last_reload_plan_class == 'no_change'
    assert app.control_plane_metrics.last_reload_error is None


def test_reload_cli_parser_endpoint_render_and_phase2_return_code(monkeypatch, tmp_path: Path) -> None:
    parser = CliParser()
    assert parser.parse(['reload', '--dry-run']) == ParsedReloadCommand(project=None, dry_run=True)
    assert parser.parse(['reload']) == ParsedReloadCommand(project=None, dry_run=False)

    rendered = render_reload(
        {
            'status': 'ok',
            'dry_run': True,
            'mutation_enabled': False,
            'plan_class': 'add_agent',
            'safe_to_apply': False,
            'future_safe_to_apply': True,
            'old_config_signature': 'old',
            'new_config_signature': 'new',
            'operations': [{'op': 'add_agent', 'agent': 'agent3', 'window': 'main', 'reason': 'new'}],
            'drain_intents': [],
            'namespace_patch_plan': {
                'status': 'blocked',
                'apply_deferred': True,
                'steps': [],
                'blocked_operations': [{'op': 'namespace_scope', 'reason': 'namespace unavailable'}],
            },
            'warnings': [],
            'reasons': ['add_agent agent3: new'],
            'errors': [],
        }
    )
    assert rendered == (
        'reload_status: ok',
        'dry_run: true',
        'mutation_enabled: false',
        'plan_class: add_agent',
        'safe_to_apply: false',
        'future_safe_to_apply: true',
        'old_config_signature: old',
        'new_config_signature: new',
        'reload_operation: op=add_agent agent=agent3 window=main reason=new',
        'reload_namespace_patch_status: blocked',
        'reload_namespace_patch_apply_deferred: true',
        'reload_namespace_patch_blocked: op=namespace_scope reason=namespace unavailable',
        'reload_reason: add_agent agent3: new',
    )

    import cli.phase2 as phase2_module

    fake_context = SimpleNamespace(project=SimpleNamespace(project_root=tmp_path, project_id='proj-reload'))
    bootstrap_called = False

    def _unexpected_bootstrap(_project_root):
        nonlocal bootstrap_called
        bootstrap_called = True
        raise AssertionError('reload dry-run must not bootstrap or write config')

    monkeypatch.setattr(phase2_module, '_build_context', lambda command, cwd, out: fake_context)
    monkeypatch.setattr(phase2_module, 'ensure_bootstrap_project_config', _unexpected_bootstrap)
    phase2_calls: list[bool] = []

    def _reload_payload(_context, command):
        phase2_calls.append(command.dry_run)
        if command.dry_run:
            return {
                'status': 'ok',
                'dry_run': True,
                'mutation_enabled': False,
                'plan_class': 'no_change',
                'safe_to_apply': False,
                'future_safe_to_apply': True,
                'old_config_signature': 'same',
                'new_config_signature': 'same',
                'operations': [],
                'drain_intents': [],
                'namespace_patch_plan': {'status': 'no_op', 'apply_deferred': True, 'steps': [], 'blocked_operations': []},
                'reasons': ['config identity and presentation fields are unchanged'],
                'warnings': [],
                'errors': [],
            }
        return {
            'status': 'published',
            'dry_run': False,
            'mutation_enabled': True,
            'plan_class': 'view_only_change',
            'stage': 'publish_transaction',
            'safe_to_apply': True,
            'future_safe_to_apply': True,
            'old_graph_version': 1,
            'target_graph_version': 2,
            'published_graph_version': 2,
            'old_config_signature': 'same',
            'new_config_signature': 'same',
            'operations': [{'op': 'view_only_change', 'field': 'sidebar_view'}],
            'drain_intents': [],
            'namespace_patch_plan': {'status': 'planned', 'apply_deferred': True, 'steps': [], 'blocked_operations': []},
            'diagnostics': {
                'graph_published': True,
                'lease_or_lifecycle_written': True,
                'config_watch_started': False,
                'unload_or_replace_executed': False,
            },
            'reasons': [],
            'warnings': [],
            'errors': [],
        }

    monkeypatch.setattr(phase2_module, 'reload_config', _reload_payload)

    stdout = StringIO()
    stderr = StringIO()
    code = maybe_handle_phase2(['reload', '--dry-run'], cwd=tmp_path, stdout=stdout, stderr=stderr)

    assert code == 0
    assert phase2_calls == [True]
    assert bootstrap_called is False
    assert 'reload_status: ok\n' in stdout.getvalue()
    assert 'plan_class: no_change\n' in stdout.getvalue()
    assert stderr.getvalue() == ''

    stdout = StringIO()
    stderr = StringIO()
    code = maybe_handle_phase2(['reload'], cwd=tmp_path, stdout=stdout, stderr=stderr)

    assert code == 0
    assert phase2_calls == [True, False]
    assert 'reload_status: published\n' in stdout.getvalue()
    assert 'dry_run: false\n' in stdout.getvalue()
    assert 'reload_stage: publish_transaction\n' in stdout.getvalue()
    assert 'reload_published_graph_version: 2\n' in stdout.getvalue()
    assert 'reload_diagnostic: graph_published=true\n' in stdout.getvalue()
    assert stderr.getvalue() == ''


def test_ccbd_client_reload_endpoint_builds_reload_payload(monkeypatch, tmp_path: Path) -> None:
    client = CcbdClient(tmp_path / 'ccbd.sock')
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(client, 'request', lambda op, payload=None: calls.append((op, payload)) or {'status': 'ok'})

    assert client.project_reload_config(dry_run=True) == {'status': 'ok'}
    assert client.project_reload_config(dry_run=False) == {'status': 'ok'}
    assert calls == [
        ('project_reload_config', {'dry_run': True}),
        ('project_reload_config', {'dry_run': False}),
    ]


@pytest.mark.parametrize('dry_run', [True, False])
def test_reload_service_connects_drifted_current_daemon_without_compatibility_restart(
    monkeypatch,
    tmp_path: Path,
    dry_run: bool,
) -> None:
    project_root = _project(tmp_path / 'repo-drifted-reload-service', BASE_CONFIG)
    project = bootstrap_project(project_root)
    command = ParsedReloadCommand(project=None, dry_run=dry_run)
    context = CliContext(command=command, cwd=project_root, project=project, paths=PathLayout(project_root))
    inspection = LeaseInspection(
        lease=None,
        health=LeaseHealth.HEALTHY,
        pid_alive=True,
        socket_connectable=True,
        heartbeat_fresh=True,
        takeover_allowed=False,
        reason='healthy',
    )
    object.__setattr__(inspection, 'phase', 'mounted')

    import cli.services.daemon as daemon_service

    monkeypatch.setattr(daemon_service, 'inspect_daemon', lambda _context: (None, None, inspection))
    monkeypatch.setattr(
        daemon_service,
        'connect_mounted_daemon',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('reload dry-run must not require config-compatible daemon')),
    )

    class _Client:
        def __init__(self, socket_path):
            self.socket_path = socket_path

        def project_reload_config(self, *, dry_run: bool) -> dict:
            return {'status': 'ok', 'dry_run': dry_run, 'socket_path': str(self.socket_path)}

    monkeypatch.setattr(daemon_service, 'CcbdClient', _Client)

    payload = reload_config(context, command)

    assert payload == {
        'status': 'ok',
        'dry_run': dry_run,
        'socket_path': str(context.paths.ccbd_socket_path),
    }


def test_reload_service_writes_cli_handoff_before_non_dry_run_rpc_and_clears_after(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _project(tmp_path / 'repo-cli-handoff', BASE_CONFIG)
    project = bootstrap_project(project_root)
    command = ParsedReloadCommand(project=None, dry_run=False)
    context = CliContext(command=command, cwd=project_root, project=project, paths=PathLayout(project_root))
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    app.lease = app.mount_manager.mark_mounted(
        project_id=app.project_id,
        pid=app.pid,
        socket_path=app.paths.ccbd_socket_path,
        generation=1,
        started_at='2026-05-29T00:00:00Z',
        config_signature=app.config_identity['config_signature'],
        daemon_instance_id=app.daemon_instance_id,
    )
    _write_config(
        project_root,
        BASE_CONFIG.replace(
            'agent1:codex, agent2:claude',
            'agent1:codex, agent2:claude, agent3:codex',
        ),
    )

    import cli.services.daemon as daemon_service

    inspection = SimpleNamespace(
        phase='mounted',
        health=LeaseHealth.HEALTHY,
        pid_alive=True,
        socket_connectable=True,
        heartbeat_fresh=True,
        takeover_allowed=False,
        reason='healthy',
        lease=app.lease,
    )
    monkeypatch.setattr(daemon_service, 'inspect_daemon', lambda _context: (None, None, inspection))
    seen: list[dict[str, object]] = []

    class _Client:
        def __init__(self, socket_path):
            self.socket_path = socket_path

        def project_reload_config(self, *, dry_run: bool) -> dict:
            assert dry_run is False
            handoff = ReloadHandoffStore(context.paths).load()
            assert handoff is not None
            seen.append(handoff.to_record())
            return {'status': 'published', 'dry_run': False}

    monkeypatch.setattr(daemon_service, 'CcbdClient', _Client)

    payload = reload_config(context, command)

    assert payload == {'status': 'published', 'dry_run': False}
    assert seen
    assert seen[0]['old_config_signature'] == app.config_identity['config_signature']
    assert seen[0]['daemon_pid'] == app.pid
    assert seen[0]['daemon_instance_id'] == app.daemon_instance_id
    assert ReloadHandoffStore(context.paths).load() is None


def test_reload_service_clears_cli_handoff_when_daemon_connection_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = _project(tmp_path / 'repo-cli-handoff-connect-fail', BASE_CONFIG)
    project = bootstrap_project(project_root)
    command = ParsedReloadCommand(project=None, dry_run=False)
    context = CliContext(command=command, cwd=project_root, project=project, paths=PathLayout(project_root))
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    app.lease = app.mount_manager.mark_mounted(
        project_id=app.project_id,
        pid=app.pid,
        socket_path=app.paths.ccbd_socket_path,
        generation=1,
        started_at='2026-05-29T00:00:00Z',
        config_signature=app.config_identity['config_signature'],
        daemon_instance_id=app.daemon_instance_id,
    )
    _write_config(
        project_root,
        BASE_CONFIG.replace(
            'agent1:codex, agent2:claude',
            'agent1:codex, agent2:claude, agent3:codex',
        ),
    )

    import cli.services.daemon as daemon_service

    inspection = SimpleNamespace(
        phase='mounted',
        health=LeaseHealth.HEALTHY,
        pid_alive=True,
        socket_connectable=True,
        heartbeat_fresh=True,
        takeover_allowed=False,
        reason='healthy',
        lease=app.lease,
    )
    monkeypatch.setattr(daemon_service, 'inspect_daemon', lambda _context: (None, None, inspection))

    class _Client:
        def __init__(self, socket_path):
            del socket_path
            handoff = ReloadHandoffStore(context.paths).load()
            assert handoff is not None
            raise RuntimeError('connect failed')

    monkeypatch.setattr(daemon_service, 'CcbdClient', _Client)

    try:
        reload_config(context, command)
    except RuntimeError as exc:
        assert str(exc) == 'connect failed'
    else:
        raise AssertionError('reload_config should propagate connection failure')

    assert ReloadHandoffStore(context.paths).load() is None


def _project(project_root: Path, config_text: str) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    _write_config(project_root, config_text)
    return project_root


def _write_config(project_root: Path, text: str) -> None:
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding='utf-8')


def _load_config(project_root: Path, text: str):
    _project(project_root, text)
    return load_project_config(project_root).config


def _namespace(project_id: str):
    return SimpleNamespace(
        project_id=project_id,
        namespace_epoch=7,
        tmux_socket_path='/tmp/ccb-tmux.sock',
        tmux_session_name='ccb-test',
        ui_attachable=True,
    )


def _runtime_file_snapshot(project_root: Path) -> dict[str, bytes]:
    root = project_root / '.ccb' / 'ccbd'
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob('*'))
        if path.is_file()
    }


def _block_mutation_paths(app: CcbdApp, monkeypatch) -> None:
    def _fail(*_args, **_kwargs):
        raise AssertionError('reload dry-run must not mutate runtime, tmux, or service graph')

    monkeypatch.setattr(app, 'publish_service_graph', _fail, raising=False)
    for method_name in ('ensure_started', 'destroy', 'recreate', 'patch_topology', 'refresh'):
        monkeypatch.setattr(app.project_namespace, method_name, _fail, raising=False)
    for store_name in (
        'lifecycle_store',
        'namespace_state_store',
        'namespace_event_store',
        'start_policy_store',
        'restore_store',
        'startup_report_store',
        'shutdown_report_store',
        'restore_report_store',
    ):
        store = getattr(app, store_name, None)
        if store is not None:
            monkeypatch.setattr(store, 'save', _fail, raising=False)
            monkeypatch.setattr(store, 'append', _fail, raising=False)
