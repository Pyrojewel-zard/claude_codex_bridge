from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agents.models import AgentState
from agents.config_loader import load_project_config
from ccbd.app import CcbdApp
from ccbd.models import CcbdStartupAgentResult
from ccbd.reload_apply import run_additive_reload_apply
from ccbd.reload_apply_runtime import run_runtime_mount
from ccbd.reload_handoff import ReloadHandoffStore
from ccbd.reload_runtime_mount import AdditiveRuntimeMountResult
from ccbd.services.lifecycle import build_lifecycle
from ccbd.services.project_namespace import ProjectNamespaceController
from ccbd.services.project_namespace_runtime import NamespacePatchApplyResult, build_namespace_topology_plan
from ccbd.services.project_namespace_state import ProjectNamespaceState, ProjectNamespaceStateStore
from ccbd.start_flow_runtime import StartFlowSummary
from cli.render import render_reload


BASE_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""


def test_reload_runtime_mount_defers_provider_runtime_for_herdr_namespace() -> None:
    called = False

    def provider_mount(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError('provider runtime must be deferred for Herdr')

    result = run_runtime_mount(
        object(),
        object(),
        namespace=SimpleNamespace(
            backend_impl='herdr',
            namespace_backend_family='herdr-native',
        ),
        namespace_patch=SimpleNamespace(
            agent_panes={'agent2': 'w1:p3'},
            preserved_before={'agent1': 'w1:p2'},
        ),
        run_runtime_mount_fn=provider_mount,
        run_start_flow_fn=None,
    )

    assert result.status == 'noop'
    assert result.requested_agents == ('agent2',)
    assert result.preserved_runtime_unchanged_agents == ('agent1',)
    assert result.diagnostics['reason'] == 'provider_runtime_deferred_on_herdr'
    assert result.diagnostics['runtime_mount_deferred'] is True
    assert called is False

VIEW_CONFIG = BASE_CONFIG + """
[ui.sidebar.view]
agents_height = "50%"
comms_height = "15%"
tips_height = "35%"
comms_limit = 4
"""

VIEW_CONFIG_CHANGED = BASE_CONFIG + """
[ui.sidebar.view]
agents_height = "60%"
comms_height = "10%"
tips_height = "30%"
comms_limit = 5
"""

MAINTENANCE_CONFIG_CHANGED = BASE_CONFIG + """
[maintenance.heartbeat]
enabled = true
assessor = "ccb_self"
interval_s = 900
min_interval_s = 120
unknown_streak_cap = 4
escalation_policy = "ask_user"
startup_ensure = true
"""

ADD_AGENT_CONFIG = BASE_CONFIG.replace(
    'agent1:codex, agent2:claude',
    'agent1:codex, (agent2:claude; agent3:codex)',
)

TRAILING_ADD_AGENT_CONFIG = BASE_CONFIG.replace(
    'agent1:codex, agent2:claude',
    'agent1:codex, agent2:claude, agent3:codex',
)

ADD_WINDOW_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""

REMOVE_AGENT_CONFIG = BASE_CONFIG.replace(
    'agent1:codex, agent2:claude',
    'agent1:codex',
)

REPLACE_AGENT_CONFIG = BASE_CONFIG.replace(
    'agent2:claude',
    'agent2:codex',
)

ADD_TOOL_WINDOW_CONFIG = BASE_CONFIG + """
[tool_windows.files]
command = "ccb-workbench files"
label = "files"
"""

NOW = '2026-05-29T00:00:00Z'


def test_additive_reload_apply_view_only_publishes_without_namespace_or_runtime_mutation(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-view', VIEW_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, VIEW_CONFIG_CHANGED)
    calls: list[str] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('view-only must skip namespace patch'),
        run_runtime_mount_fn=lambda *_args, **_kwargs: (
            calls.append('runtime') or AdditiveRuntimeMountResult(status='noop')
        ),
    )

    assert result.status == 'published'
    assert result.plan_class == 'view_only_change'
    assert result.namespace_patch['status'] == 'applied'
    assert result.namespace_patch['diagnostics']['reason'] == 'view_only_change'
    assert result.runtime_mount['status'] == 'noop'
    assert calls == ['runtime']
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.config is app.service_graph.config
    assert app.config.sidebar_view.agents_height == '60%'
    assert app.config.sidebar_view.comms_height == '10%'
    assert app.config.sidebar_view.tips_height == '30%'
    assert app.config.sidebar_view.comms_limit == 5
    assert app.config_identity == app.service_graph.config_identity
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']
    assert result.diagnostics['graph_published'] is True
    assert result.diagnostics['config_watch_started'] is False
    assert result.diagnostics['unload_or_replace_executed'] is False


def test_additive_reload_apply_maintenance_change_publishes_without_namespace_or_runtime_mutation(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-maintenance-change', BASE_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, MAINTENANCE_CONFIG_CHANGED)
    calls: list[str] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('maintenance-only change must skip namespace patch'),
        run_runtime_mount_fn=lambda *_args, **_kwargs: (
            calls.append('runtime') or AdditiveRuntimeMountResult(status='noop')
        ),
    )

    assert result.status == 'published'
    assert result.plan_class == 'maintenance_change'
    assert result.namespace_patch['status'] == 'applied'
    assert result.namespace_patch['diagnostics']['reason'] == 'maintenance_change'
    assert result.runtime_mount['status'] == 'noop'
    assert calls == ['runtime']
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.config.maintenance_heartbeat.enabled is True
    assert app.config.maintenance_heartbeat.interval_s == 900
    assert app.config.maintenance_heartbeat.escalation_policy == 'ask_user'
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']
    assert result.diagnostics['graph_published'] is True
    assert result.diagnostics['unload_or_replace_executed'] is False


def test_additive_reload_apply_add_agent_success_mounts_then_publishes(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-add-agent', BASE_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, ADD_AGENT_CONFIG)
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.plan_class == 'add_agent'
    assert result.namespace_patch['agent_panes'] == {'agent3': '%3'}
    assert result.runtime_mount['status'] == 'mounted'
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.config_identity == app.service_graph.config_identity
    assert app.service_graph.registry.get('agent3').pane_id == '%3'
    assert app.service_graph.registry.get('agent1') is None
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']
    assert calls[0]['requested_agents'] == ('agent3',)
    assert calls[0]['cleanup_tmux_orphans'] is False
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%3'}


def test_additive_reload_apply_add_agent_materializes_tmux_pane_before_mount(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-agent-real-patch', BASE_CONFIG)
    backend = _PatchFakeBackend(socket_path=str(app.paths.ccbd_tmux_socket_path))
    backend.add_window(app.paths.ccbd_tmux_session_name, 'main')
    backend.sessions[app.paths.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id=app.project_id, window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id=app.project_id, window='main', agent='agent2')
    app.project_namespace = ProjectNamespaceController(
        app.paths,
        app.project_id,
        clock=app.clock,
        backend_factory=lambda socket_path=None: backend,
    )
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    new_config = _load_config(app.project_root, ADD_AGENT_CONFIG)
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.namespace_patch['agent_panes'] == {'agent3': '%3'}
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert backend.split_calls == [('%2', 'right', 50)]
    assert backend.pane_options['%3']['@ccb_role'] == 'agent'
    assert backend.pane_options['%3']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%3'}
    assert app.service_graph.registry.get('agent3').pane_id == '%3'


def test_additive_reload_apply_dynamic_agent_overlay_materializes_tmux_pane_before_mount(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-dynamic-agent-real-patch', BASE_CONFIG)
    backend = _PatchFakeBackend(socket_path=str(app.paths.ccbd_tmux_socket_path))
    backend.add_window(app.paths.ccbd_tmux_session_name, 'main')
    backend.sessions[app.paths.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id=app.project_id, window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id=app.project_id, window='main', agent='agent2')
    app.project_namespace = ProjectNamespaceController(
        app.paths,
        app.project_id,
        clock=app.clock,
        backend_factory=lambda socket_path=None: backend,
    )
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    _write_dynamic_agent_state(
        app.project_root,
        agent='agent3',
        provider='codex',
        role='agentroles.general',
    )
    new_config = load_project_config(app.project_root).config
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.plan_class == 'add_agent'
    assert result.namespace_patch['agent_panes'] == {'agent3': '%3'}
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert backend.split_calls == [('%2', 'right', 50)]
    assert backend.pane_options['%3']['@ccb_role'] == 'agent'
    assert backend.pane_options['%3']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%3'}
    assert app.service_graph.registry.get('agent3').pane_id == '%3'


def test_additive_reload_apply_dynamic_agent_overlay_materializes_new_window_before_mount(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-dynamic-window-real-patch', BASE_CONFIG)
    backend = _PatchFakeBackend(socket_path=str(app.paths.ccbd_tmux_socket_path))
    backend.add_window(app.paths.ccbd_tmux_session_name, 'main')
    backend.sessions[app.paths.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id=app.project_id, window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id=app.project_id, window='main', agent='agent2')
    app.project_namespace = ProjectNamespaceController(
        app.paths,
        app.project_id,
        clock=app.clock,
        backend_factory=lambda socket_path=None: backend,
    )
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    before_agent1 = app.runtime_service._registry.get('agent1').to_record()
    before_agent2 = app.runtime_service._registry.get('agent2').to_record()
    _write_dynamic_agent_state(
        app.project_root,
        agent='agent3',
        provider='codex',
        role='agentroles.general',
        window_name='review',
    )
    new_config = load_project_config(app.project_root).config
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.plan_class == 'add_window'
    assert result.namespace_patch['created_windows'] == ['review']
    assert result.namespace_patch['sidebar_panes'] == {'review': '%3'}
    assert result.namespace_patch['agent_panes'] == {'agent3': '%4'}
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert app.runtime_service._registry.get('agent1').to_record() == before_agent1
    assert app.runtime_service._registry.get('agent2').to_record() == before_agent2
    assert backend.pane_options['%1']['@ccb_slot'] == 'agent1'
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent2'
    assert backend.pane_options['%4']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%4']['@ccb_window'] == 'review'
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%4'}
    assert app.service_graph.registry.get('agent3').pane_id == '%4'


def test_additive_reload_apply_writes_bounded_handoff_during_apply_and_clears_after_success(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-handoff-success', BASE_CONFIG)
    new_config = _load_config(app.project_root, ADD_AGENT_CONFIG)
    seen_handoffs: list[dict[str, object]] = []

    def _patch_with_handoff_probe(**_kwargs):
        handoff = ReloadHandoffStore(app.paths).load()
        assert handoff is not None
        seen_handoffs.append(handoff.to_record())
        return _namespace_patch_result(agent_panes={'agent3': '%3'})

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_patch_with_handoff_probe,
        run_start_flow_fn=_mounting_start_flow(app, []),
    )

    assert result.status == 'published'
    assert seen_handoffs
    assert seen_handoffs[0]['old_config_signature'] == result.old_config_signature
    assert seen_handoffs[0]['target_config_signature'] == result.new_config_signature
    assert seen_handoffs[0]['daemon_pid'] == app.pid
    assert seen_handoffs[0]['daemon_instance_id'] == app.daemon_instance_id
    assert ReloadHandoffStore(app.paths).load() is None


def test_additive_reload_apply_clears_handoff_after_failed_apply(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-handoff-failed', BASE_CONFIG)
    new_config = _load_config(app.project_root, ADD_WINDOW_CONFIG)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('injected namespace patch failure'),
    )

    assert result.status == 'failed'
    assert result.stage == 'namespace_patch'
    assert ReloadHandoffStore(app.paths).load() is None


def test_additive_reload_apply_add_window_success_mounts_new_window_agent_then_publishes(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-window', BASE_CONFIG)
    new_config = _load_config(app.project_root, ADD_WINDOW_CONFIG)
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_windows=('review',),
            created_panes=('%3', '%4'),
            agent_panes={'agent3': '%4'},
            sidebar_panes={'review': '%3'},
        ),
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.plan_class == 'add_window'
    assert result.namespace_patch['created_windows'] == ['review']
    assert result.namespace_patch['sidebar_panes'] == {'review': '%3'}
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert app.service_graph.version == 2
    assert app.config.entry_window == 'main'
    assert app.service_graph.registry.get('agent3').pane_id == '%4'
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%4'}


def test_additive_reload_apply_add_tool_window_publishes_without_runtime_mount(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-tool-window', BASE_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, ADD_TOOL_WINDOW_CONFIG)
    runtime_calls: list[str] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_windows=('files',),
            created_panes=('%3', '%4'),
            agent_panes={},
            sidebar_panes={'files': '%3'},
            tool_panes={'files': '%4'},
        ),
        run_runtime_mount_fn=lambda *_args, **_kwargs: (
            runtime_calls.append('runtime') or AdditiveRuntimeMountResult(status='noop')
        ),
    )

    assert result.status == 'published'
    assert result.plan_class == 'add_tool_window'
    assert result.namespace_patch['tool_panes'] == {'files': '%4'}
    assert result.runtime_mount['status'] == 'noop'
    assert runtime_calls == ['runtime']
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert [tool.name for tool in app.config.tool_windows] == ['files']
    assert app.service_graph.registry.list_known_agents() == ('agent1', 'agent2')
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']


def test_additive_reload_apply_remove_tool_window_publishes_without_agent_unload(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-remove-tool-window', ADD_TOOL_WINDOW_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, BASE_CONFIG)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_windows=('files',),
            removed_panes=('%4',),
            preserved_before={'agent1': '%1', 'agent2': '%2'},
            preserved_after={'agent1': '%1', 'agent2': '%2'},
        ),
        run_runtime_mount_fn=lambda *_args, **_kwargs: AdditiveRuntimeMountResult(status='noop'),
    )

    assert result.status == 'published'
    assert result.plan_class == 'remove_tool_window'
    assert result.namespace_patch['removed_windows'] == ['files']
    assert result.runtime_mount['status'] == 'noop'
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.config.tool_windows == ()
    assert app.service_graph.registry.list_known_agents() == ('agent1', 'agent2')
    assert result.diagnostics['unload_or_replace_executed'] is False


def test_additive_reload_apply_add_window_materializes_tmux_window_before_mount(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-add-window-real-patch', BASE_CONFIG)
    backend = _PatchFakeBackend(socket_path=str(app.paths.ccbd_tmux_socket_path))
    backend.add_window(app.paths.ccbd_tmux_session_name, 'main')
    backend.sessions[app.paths.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id=app.project_id, window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id=app.project_id, window='main', agent='agent2')
    app.project_namespace = ProjectNamespaceController(
        app.paths,
        app.project_id,
        clock=app.clock,
        backend_factory=lambda socket_path=None: backend,
    )
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    new_config = _load_config(app.project_root, ADD_WINDOW_CONFIG)
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.namespace_patch['created_windows'] == ['review']
    assert result.namespace_patch['sidebar_panes'] == {'review': '%3'}
    assert result.namespace_patch['agent_panes'] == {'agent3': '%4'}
    assert ('new-window', '-d', '-t', app.paths.ccbd_tmux_session_name, '-n', 'review') == backend.tmux_calls[1][:6]
    assert backend.split_calls == [('%3', 'right', 85)]
    assert backend.pane_options['%3']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%4']['@ccb_slot'] == 'agent3'
    assert calls[0]['namespace_agent_panes'] == {'agent3': '%4'}
    assert app.service_graph.registry.get('agent3').pane_id == '%4'


def test_additive_reload_apply_remove_agent_success_unloads_then_publishes(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-remove-agent', BASE_CONFIG)
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, REMOVE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_agents={'agent2': '%2'},
            removed_panes=('%2',),
            preserved_before={'agent1': '%1'},
            preserved_after={'agent1': '%1'},
        ),
    )

    assert result.status == 'published'
    assert result.plan_class == 'remove_agent'
    assert result.namespace_patch['removed_agents'] == {'agent2': '%2'}
    assert result.runtime_mount['status'] == 'unloaded'
    assert result.runtime_mount['unloaded_agents'] == ['agent2']
    assert result.runtime_mount['runtime_authority_stopped_agents'] == ['agent2']
    assert result.diagnostics['unload_or_replace_executed'] is True
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.config_identity == app.service_graph.config_identity
    assert app.service_graph.registry.list_known_agents() == ('agent1',)
    assert old_graph.registry.get('agent2').state is AgentState.STOPPED
    assert old_graph.registry.get('agent2').pane_id is None
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']


def test_additive_reload_apply_can_readd_same_agent_after_unload_residue(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-remove-then-readd-same-agent', TRAILING_ADD_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    _seed_runtime(app.runtime_service, 'agent3', pane_id='%3')

    remove_result = run_additive_reload_apply(
        app,
        _load_config(app.project_root, BASE_CONFIG),
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_agents={'agent3': '%3'},
            removed_panes=('%3',),
            preserved_before={'agent1': '%1', 'agent2': '%2'},
            preserved_after={'agent1': '%1', 'agent2': '%2'},
        ),
    )

    assert remove_result.status == 'published'
    assert remove_result.runtime_mount['status'] == 'unloaded'
    retired = app.service_graph.registry.get('agent3')
    assert retired.state is AgentState.STOPPED
    assert retired.desired_state == 'stopped'
    assert retired.runtime_ref is None
    assert retired.pane_id is None

    calls: list[dict[str, object]] = []
    add_result = run_additive_reload_apply(
        app,
        _load_config(app.project_root, TRAILING_ADD_AGENT_CONFIG),
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_panes=('%4',),
            agent_panes={'agent3': '%4'},
            preserved_before={'agent1': '%1', 'agent2': '%2'},
            preserved_after={'agent1': '%1', 'agent2': '%2'},
        ),
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert add_result.status == 'published'
    assert add_result.runtime_mount['status'] == 'mounted'
    assert add_result.runtime_mount['runtime_authority_written_agents'] == ['agent3']
    assert add_result.diagnostics['graph_published'] is True
    mounted = app.service_graph.registry.get('agent3')
    assert mounted.state is AgentState.IDLE
    assert mounted.desired_state == 'mounted'
    assert mounted.runtime_ref == 'tmux:%4'
    assert mounted.pane_id == '%4'
    assert calls[0]['requested_agents'] == ('agent3',)


def test_additive_reload_apply_blocks_busy_remove_before_namespace_patch(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-remove-busy', BASE_CONFIG)
    app.reload_drain_clock_s = lambda: 10.0
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, REMOVE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    runtime = old_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('busy remove must not patch namespace'),
        run_runtime_mount_fn=_fail_with('busy remove must not mutate runtime'),
        publish_transaction_fn=_fail_with('busy remove must not publish'),
    )

    assert result.status == 'blocked'
    assert result.stage == 'plan'
    assert result.plan_class == 'remove_agent'
    assert result.diagnostics['reason'] == 'agent_busy'
    assert result.diagnostics['drain_action'] == 'enqueued'
    assert result.diagnostics['drain_accepted'] is True
    assert result.diagnostics['drain_record']['phase'] == 'draining'
    assert result.diagnostics['drain_record']['status'] == 'waiting'
    assert result.diagnostics['drain_record']['busy'] is True
    assert result.diagnostics['drain_queue_pending_count'] == 1
    assert result.diagnostics['graph_published'] is False
    assert app.service_graph is old_graph
    drain_records = app.reload_drain_store.load().active_records_for('agent2')
    assert len(drain_records) == 1
    assert drain_records[0].status == 'waiting'


def test_additive_reload_apply_idle_retry_retires_busy_remove_drain_record(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-remove-busy-retry', BASE_CONFIG)
    times = iter([10.0, 20.0])
    app.reload_drain_clock_s = lambda: next(times)
    new_config = _load_config(app.project_root, REMOVE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    runtime = app.service_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)

    blocked = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('busy remove must not patch namespace'),
        run_runtime_mount_fn=_fail_with('busy remove must not mutate runtime'),
        publish_transaction_fn=_fail_with('busy remove must not publish'),
    )
    assert blocked.status == 'blocked'
    assert app.reload_drain_store.load().active_records_for('agent2')

    app.runtime_service.patch_runtime_state(runtime, state=AgentState.IDLE)
    published = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_agents={'agent2': '%2'},
            removed_panes=('%2',),
            preserved_before={'agent1': '%1'},
            preserved_after={'agent1': '%1'},
        ),
    )

    assert published.status == 'published'
    assert published.plan_class == 'remove_agent'
    assert published.runtime_mount['status'] == 'unloaded'
    drain_queue = app.reload_drain_store.load()
    assert drain_queue.active_records_for('agent2') == ()
    assert drain_queue.records[0].status == 'retired'
    assert drain_queue.records[0].phase == 'retired'


def test_reload_apply_busy_replace_records_drain_without_mutation(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-replace-busy', BASE_CONFIG)
    app.reload_drain_clock_s = lambda: 10.0
    old_graph = app.service_graph
    new_config = _load_config(app.project_root, REPLACE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2', provider='claude')
    runtime = old_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('busy replace must not patch namespace'),
        run_runtime_mount_fn=_fail_with('busy replace must not mutate runtime'),
        publish_transaction_fn=_fail_with('busy replace must not publish'),
    )

    assert result.status == 'blocked'
    assert result.stage == 'plan'
    assert result.plan_class == 'replace_agent'
    assert result.diagnostics['reason'] == 'agent_busy'
    assert result.diagnostics['drain_action'] == 'enqueued'
    assert result.diagnostics['drain_accepted'] is True
    assert result.diagnostics['drain_record']['intent']['intent_kind'] == 'replace'
    assert result.diagnostics['drain_record']['phase'] == 'draining'
    assert result.diagnostics['drain_record']['status'] == 'waiting'
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['unload_or_replace_executed'] is False
    assert app.service_graph is old_graph
    drain_records = app.reload_drain_store.load().active_records_for('agent2')
    assert len(drain_records) == 1
    assert drain_records[0].intent.intent_kind == 'replace'
    assert drain_records[0].status == 'waiting'


def test_reload_apply_idle_replace_respawns_same_slot_and_publishes(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-replace-idle', BASE_CONFIG)
    old_graph = app.service_graph
    old_lease = app.mount_manager.load_state().to_record()
    new_config = _load_config(app.project_root, REPLACE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2', provider='claude')
    calls: list[dict[str, object]] = []

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('idle replace must not mutate tmux namespace before runtime respawn'),
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert result.status == 'published'
    assert result.stage == 'publish_transaction'
    assert result.plan_class == 'replace_agent'
    assert result.namespace_patch['status'] == 'applied'
    assert result.namespace_patch['replaced_agents'] == {'agent2': '%2'}
    assert result.namespace_patch['agent_panes'] == {}
    assert result.runtime_mount['status'] == 'replaced'
    assert result.runtime_mount['requested_agents'] == ['agent2']
    assert result.runtime_mount['replaced_agents'] == ['agent2']
    assert result.runtime_mount['mounted_agents'] == ['agent2']
    assert result.runtime_mount['runtime_authority_stopped_agents'] == ['agent2']
    assert result.runtime_mount['runtime_authority_written_agents'] == ['agent2']
    assert result.runtime_mount['helper_terminated_agents'] == []
    assert calls[0]['requested_agents'] == ('agent2',)
    assert calls[0]['namespace_agent_panes'] == {'agent2': '%2'}
    runtime = app.service_graph.registry.get('agent2')
    assert runtime is not None
    assert runtime.provider == 'codex'
    assert runtime.pane_id == '%2'
    assert runtime.active_pane_id == '%2'
    assert runtime.runtime_ref == 'tmux:%2'
    assert runtime.session_ref == 'session-agent2'
    assert app.service_graph is not old_graph
    assert app.service_graph.version == 2
    assert app.mount_manager.load_state().config_signature != old_lease['config_signature']
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.reload_drain_store.load().active_records_for('agent2') == ()


def test_reload_apply_idle_replace_uses_default_start_flow_when_not_injected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-replace-default-start-flow', BASE_CONFIG)
    new_config = _load_config(app.project_root, REPLACE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2', provider='claude')
    calls: list[object] = []

    def fake_mounts(_app, graph, *, namespace, patch_result, run_start_flow_fn):
        del namespace, patch_result
        calls.append(run_start_flow_fn)
        assert callable(run_start_flow_fn)
        graph.runtime_service.attach(
            agent_name='agent2',
            workspace_path=str(graph.runtime_service._layout.workspace_path('agent2')),
            backend_type='pane-backed',
            runtime_ref='tmux:%2',
            session_ref='session-agent2-new',
            health='healthy',
            provider='codex',
            terminal_backend='tmux',
            pane_id='%2',
            active_pane_id='%2',
            tmux_window_name='main',
            slot_key='agent2',
            window_id='@0',
            workspace_epoch=1,
            lifecycle_state='idle',
            managed_by='ccbd',
            binding_source='provider-session',
        )
        return AdditiveRuntimeMountResult(
            status='mounted',
            requested_agents=('agent2',),
            mounted_agents=('agent2',),
            runtime_authority_written_agents=('agent2',),
        )

    monkeypatch.setattr(
        'ccbd.reload_runtime_replace.run_additive_agent_mounts',
        fake_mounts,
    )

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('idle replace must not mutate tmux namespace before runtime respawn'),
    )

    assert result.status == 'published'
    assert result.plan_class == 'replace_agent'
    assert result.runtime_mount['status'] == 'replaced'
    assert len(calls) == 1


def test_reload_apply_idle_retry_retires_busy_replace_drain_record(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-replace-busy-retry', BASE_CONFIG)
    times = iter([10.0, 20.0])
    app.reload_drain_clock_s = lambda: next(times)
    new_config = _load_config(app.project_root, REPLACE_AGENT_CONFIG)
    _seed_runtime(app.runtime_service, 'agent1', pane_id='%1')
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2', provider='claude')
    runtime = app.service_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)

    blocked = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('busy replace must not patch namespace'),
        run_runtime_mount_fn=_fail_with('busy replace must not mutate runtime'),
        publish_transaction_fn=_fail_with('busy replace must not publish'),
    )
    assert blocked.status == 'blocked'
    assert app.reload_drain_store.load().active_records_for('agent2')

    app.runtime_service.patch_runtime_state(runtime, state=AgentState.IDLE)
    calls: list[dict[str, object]] = []
    published = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=_fail_with('idle replace retry must not mutate tmux namespace before runtime respawn'),
        run_start_flow_fn=_mounting_start_flow(app, calls),
    )

    assert published.status == 'published'
    assert published.plan_class == 'replace_agent'
    assert published.runtime_mount['status'] == 'replaced'
    assert published.runtime_mount['replaced_agents'] == ['agent2']
    assert calls[0]['namespace_agent_panes'] == {'agent2': '%2'}
    drain_queue = app.reload_drain_store.load()
    assert drain_queue.active_records_for('agent2') == ()
    assert drain_queue.records[0].intent.intent_kind == 'replace'
    assert drain_queue.records[0].status == 'retired'
    assert drain_queue.records[0].phase == 'retired'


def test_additive_reload_apply_namespace_patch_failure_stops_before_runtime_and_publish(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-namespace-fail', BASE_CONFIG)
    old_graph = app.service_graph
    old_lease = app.mount_manager.load_state().to_record()
    old_lifecycle = app.lifecycle_store.load().to_record()
    new_config = _load_config(app.project_root, ADD_WINDOW_CONFIG)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: NamespacePatchApplyResult(
            status='failed',
            created_windows=('review',),
            created_panes=('%3',),
            partial=True,
            rollback_actions=('created_pane:%3',),
            diagnostics={
                'reason': 'namespace_patch_failed',
                'graph_published': False,
                'runtime_authority_written': False,
                'lease_or_lifecycle_written': False,
            },
        ),
        run_runtime_mount_fn=_fail_with('namespace failure must not mount runtime'),
        publish_transaction_fn=_fail_with('namespace failure must not publish'),
    )

    assert result.status == 'failed'
    assert result.stage == 'namespace_patch'
    assert result.diagnostics['namespace_residue']['created_windows'] == ['review']
    assert result.diagnostics['namespace_residue']['created_panes'] == ['%3']
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False
    assert app.service_graph is old_graph
    assert app.mount_manager.load_state().to_record() == old_lease
    assert app.lifecycle_store.load().to_record() == old_lifecycle


def test_additive_reload_apply_namespace_patch_failure_redacts_restore_token_evidence(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-namespace-token-fail', BASE_CONFIG)
    new_config = _load_config(app.project_root, ADD_WINDOW_CONFIG)
    expected_token = 'expected-session::workspace-1'
    actual_token = 'actual-session::workspace-1'
    nested_token = 'nested-session::workspace-1'
    camel_token = 'camel-session::workspace-1'
    namespace_patch = NamespacePatchApplyResult(
        status='failed',
        diagnostics={
            'reason': 'namespace_patch_failed',
            'error_type': 'MuxCommandErrorV2',
            'error': 'Herdr restore_session returned a restore_token different from the requested token',
            'error_evidence': {
                'socket_ref': 'herdr://local',
                'expected_restore_token': expected_token,
                'nested': {
                    'actual_restore_token': actual_token,
                    'items': [{'restore_token': nested_token, 'restoreToken': camel_token}],
                },
            },
        },
    )

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: namespace_patch,
        run_runtime_mount_fn=_fail_with('namespace failure must not mount runtime'),
        publish_transaction_fn=_fail_with('namespace failure must not publish'),
    )
    payload = result.to_record()
    rendered = '\n'.join(render_reload(payload))
    encoded = json.dumps(payload, sort_keys=True)

    assert result.diagnostics['error_evidence']['expected_restore_token'] == '<redacted>'
    assert payload['namespace_patch']['diagnostics']['error_evidence']['nested']['items'][0]['restore_token'] == '<redacted>'
    assert payload['namespace_patch']['diagnostics']['error_evidence']['nested']['items'][0]['restoreToken'] == '<redacted>'
    for token in (expected_token, actual_token, nested_token, camel_token):
        assert token not in encoded
        assert token not in rendered


def test_additive_reload_apply_runtime_mount_failure_stops_before_publish(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-runtime-fail', BASE_CONFIG)
    old_graph = app.service_graph
    old_lease = app.mount_manager.load_state().to_record()
    old_lifecycle = app.lifecycle_store.load().to_record()
    new_config = _load_config(app.project_root, ADD_AGENT_CONFIG)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
        run_runtime_mount_fn=lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='failed',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
            partial=True,
            diagnostics={
                'reason': 'runtime_mount_failed',
                'graph_published': False,
                'lease_or_lifecycle_written': False,
            },
        ),
        publish_transaction_fn=_fail_with('runtime failure must not publish'),
    )

    assert result.status == 'failed'
    assert result.stage == 'runtime_mount'
    assert result.diagnostics['runtime_residue']['runtime_authority_written_agents'] == ['agent3']
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False
    assert app.service_graph is old_graph
    assert app.mount_manager.load_state().to_record() == old_lease
    assert app.lifecycle_store.load().to_record() == old_lifecycle


def test_additive_reload_apply_publish_transaction_failure_keeps_old_graph(tmp_path: Path) -> None:
    app = _started_app(tmp_path / 'repo-publish-fail', BASE_CONFIG)
    old_graph = app.service_graph
    old_lease = app.mount_manager.load_state().to_record()
    old_lifecycle = app.lifecycle_store.load().to_record()
    new_config = _load_config(app.project_root, ADD_AGENT_CONFIG)

    result = run_additive_reload_apply(
        app,
        new_config,
        current_namespace=_namespace(app),
        apply_namespace_patch_fn=lambda **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
        run_runtime_mount_fn=lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='mounted',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
            diagnostics={'graph_published': False, 'lease_or_lifecycle_written': False},
        ),
        publish_graph_fn=lambda _graph: (_ for _ in ()).throw(RuntimeError('publish failed')),
    )

    assert result.status == 'failed'
    assert result.stage == 'publish_transaction'
    assert result.diagnostics['reason'] == 'service_graph_publish_failed'
    assert result.diagnostics['graph_published'] is False
    assert result.publish_transaction['diagnostics']['signature_rollback']['complete'] is True
    assert app.service_graph is old_graph
    assert app.mount_manager.load_state().to_record() == old_lease
    assert app.lifecycle_store.load().config_signature == old_lifecycle['config_signature']


def test_project_reload_non_dry_run_view_only_publishes_and_refreshes_graph_views(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-view-handler', VIEW_CONFIG)
    old_signature = app.config_identity['config_signature']
    old_view = app.socket_server._handlers['project_view']({'schema_version': 1})
    assert old_view['view']['namespace']['sidebar']['view']['agents_height'] == '50%'
    assert old_view['view']['namespace']['sidebar']['view']['comms_height'] == '15%'
    assert old_view['view']['namespace']['sidebar']['view']['tips_height'] == '35%'
    assert old_view['view']['namespace']['sidebar']['view']['comms_limit'] == 4
    _project(app.project_root, VIEW_CONFIG_CHANGED)

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['dry_run'] is False
    assert payload['mutation_enabled'] is True
    assert payload['plan_class'] == 'view_only_change'
    assert payload['stage'] == 'publish_transaction'
    assert payload['old_graph_version'] == 1
    assert payload['target_graph_version'] == 2
    assert payload['published_graph_version'] == 2
    assert payload['old_config_signature'] == old_signature
    assert payload['new_config_signature'] == old_signature
    assert payload['warnings'] == []
    assert payload['diagnostics']['graph_published'] is True
    assert payload['diagnostics']['project_view_cache_invalidated'] is True
    assert payload['diagnostics']['sidebar_refresh_signal_sent'] is False
    assert app.service_graph.version == 2
    assert app.config.sidebar_view.agents_height == '60%'
    assert app.config.sidebar_view.comms_height == '10%'
    assert app.config.sidebar_view.tips_height == '30%'
    assert app.config.sidebar_view.comms_limit == 5
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']

    ping = app.socket_server._handlers['ping']({'target': 'ccbd'})
    assert ping['config_signature'] == app.config_identity['config_signature']
    assert ping['diagnostics']['service_graph_version'] == 2
    assert ping['known_agents'] == ['agent1', 'agent2']
    view = app.socket_server._handlers['project_view']({'schema_version': 1})
    assert view['view']['namespace']['sidebar']['view']['agents_height'] == '60%'
    assert view['view']['namespace']['sidebar']['view']['comms_height'] == '10%'
    assert view['view']['namespace']['sidebar']['view']['tips_height'] == '30%'
    assert view['view']['namespace']['sidebar']['view']['comms_limit'] == 5


def test_project_reload_non_dry_run_maintenance_change_publishes_policy(
    tmp_path: Path,
) -> None:
    app = _started_app(tmp_path / 'repo-maintenance-handler', BASE_CONFIG)
    old_signature = app.config_identity['config_signature']
    assert app.config.maintenance_heartbeat.enabled is False
    _project(app.project_root, MAINTENANCE_CONFIG_CHANGED)

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['dry_run'] is False
    assert payload['plan_class'] == 'maintenance_change'
    assert payload['old_config_signature'] == old_signature
    assert payload['new_config_signature'] != old_signature
    assert payload['operations'][0]['op'] == 'maintenance_change'
    assert payload['namespace_patch']['diagnostics']['reason'] == 'maintenance_change'
    assert payload['runtime_mount']['status'] == 'noop'
    assert payload['diagnostics']['graph_published'] is True
    assert app.service_graph.version == 2
    assert app.config.maintenance_heartbeat.enabled is True
    assert app.config.maintenance_heartbeat.interval_s == 900
    assert app.config.maintenance_heartbeat.escalation_policy == 'ask_user'
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == app.config_identity['config_signature']


def test_project_reload_non_dry_run_add_agent_publishes_after_additive_stages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-add-agent-handler', BASE_CONFIG)
    _project(app.project_root, ADD_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
    )
    monkeypatch.setattr(
        'ccbd.reload_apply_service.run_runtime_mount',
        lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='mounted',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
            preserved_runtime_unchanged_agents=('agent1', 'agent2'),
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['plan_class'] == 'add_agent'
    assert {item['op'] for item in payload['operations']} == {'add_agent'}
    assert payload['namespace_patch']['agent_panes'] == {'agent3': '%3'}
    assert payload['runtime_mount']['runtime_authority_written_agents'] == ['agent3']
    assert payload['diagnostics']['graph_published'] is True
    assert app.service_graph.version == 2
    assert app.config_identity == app.service_graph.config_identity
    assert app.mount_manager.load_state().config_signature == app.config_identity['config_signature']
    ping = app.socket_server._handlers['ping']({'target': 'ccbd'})
    assert ping['known_agents'] == ['agent1', 'agent2', 'agent3']
    assert ping['config_signature'] == app.config_identity['config_signature']


def test_project_reload_non_dry_run_add_window_publishes_after_additive_stages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-add-window-handler', BASE_CONFIG)
    _project(app.project_root, ADD_WINDOW_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(
            created_windows=('review',),
            created_panes=('%3', '%4'),
            agent_panes={'agent3': '%4'},
            sidebar_panes={'review': '%3'},
        ),
    )
    monkeypatch.setattr(
        'ccbd.reload_apply_service.run_runtime_mount',
        lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='mounted',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
            preserved_runtime_unchanged_agents=('agent1', 'agent2'),
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['plan_class'] == 'add_window'
    assert {item['op'] for item in payload['operations']} == {'add_agent', 'add_window'}
    assert payload['namespace_patch']['created_windows'] == ['review']
    assert payload['namespace_patch']['sidebar_panes'] == {'review': '%3'}
    assert app.service_graph.version == 2
    assert [window.name for window in app.config.windows] == ['main', 'review']
    view = app.socket_server._handlers['project_view']({'schema_version': 1})
    assert [window['name'] for window in view['view']['windows']] == ['main', 'review']


def test_project_reload_non_dry_run_add_tool_window_publishes_after_namespace_patch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-add-tool-handler', BASE_CONFIG)
    _project(app.project_root, ADD_TOOL_WINDOW_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(
            created_windows=('files',),
            created_panes=('%3', '%4'),
            agent_panes={},
            sidebar_panes={'files': '%3'},
            tool_panes={'files': '%4'},
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['plan_class'] == 'add_tool_window'
    assert {item['op'] for item in payload['operations']} == {'add_tool_window'}
    assert payload['namespace_patch']['tool_panes'] == {'files': '%4'}
    assert payload['runtime_mount']['status'] == 'noop'
    assert payload['diagnostics']['graph_published'] is True
    assert app.service_graph.version == 2
    assert [tool.name for tool in app.config.tool_windows] == ['files']
    view = app.socket_server._handlers['project_view']({'schema_version': 1})
    assert [window['name'] for window in view['view']['windows']] == ['main', 'files']
    assert view['view']['windows'][1]['kind'] == 'tool'


def test_project_reload_non_dry_run_remove_tool_window_publishes_after_namespace_patch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-remove-tool-handler', ADD_TOOL_WINDOW_CONFIG)
    _project(app.project_root, BASE_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_windows=('files',),
            removed_panes=('%4',),
            preserved_before={'agent1': '%1', 'agent2': '%2'},
            preserved_after={'agent1': '%1', 'agent2': '%2'},
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['plan_class'] == 'remove_tool_window'
    assert {item['op'] for item in payload['operations']} == {'remove_tool_window'}
    assert payload['namespace_patch']['removed_windows'] == ['files']
    assert payload['runtime_mount']['status'] == 'noop'
    assert payload['diagnostics']['graph_published'] is True
    assert payload['diagnostics']['unload_or_replace_executed'] is False
    assert app.service_graph.version == 2
    assert app.config.tool_windows == ()
    view = app.socket_server._handlers['project_view']({'schema_version': 1})
    assert [window['name'] for window in view['view']['windows']] == ['main']


def test_project_reload_non_dry_run_remove_agent_publishes_after_unload_stages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-remove-handler', BASE_CONFIG)
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    _project(app.project_root, REMOVE_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(
            created_panes=(),
            agent_panes={},
            removed_agents={'agent2': '%2'},
            removed_panes=('%2',),
            preserved_before={'agent1': '%1'},
            preserved_after={'agent1': '%1'},
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'published'
    assert payload['plan_class'] == 'remove_agent'
    assert payload['mutation_enabled'] is True
    assert payload['namespace_patch']['removed_agents'] == {'agent2': '%2'}
    assert payload['runtime_mount']['status'] == 'unloaded'
    assert payload['runtime_mount']['runtime_authority_stopped_agents'] == ['agent2']
    assert payload['diagnostics']['graph_published'] is True
    assert payload['diagnostics']['unload_or_replace_executed'] is True
    assert app.service_graph.version == 2
    assert app.config_identity == app.service_graph.config_identity
    assert app.control_plane_metrics.last_reload_plan_class == 'remove_agent'
    assert app.control_plane_metrics.last_reload_error is None
    ping = app.socket_server._handlers['ping']({'target': 'ccbd'})
    assert ping['known_agents'] == ['agent1']


def test_project_reload_non_dry_run_busy_remove_blocks_without_namespace_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-remove-busy-handler', BASE_CONFIG)
    app.reload_drain_clock_s = lambda: 10.0
    old_graph = app.service_graph
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2')
    runtime = old_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)
    _project(app.project_root, REMOVE_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('busy remove must not patch namespace')),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'blocked'
    assert payload['stage'] == 'plan'
    assert payload['plan_class'] == 'remove_agent'
    assert payload['mutation_enabled'] is False
    assert payload['diagnostics']['reason'] == 'agent_busy'
    assert payload['diagnostics']['drain_action'] == 'enqueued'
    assert payload['diagnostics']['drain_accepted'] is True
    assert payload['diagnostics']['drain_record']['status'] == 'waiting'
    assert payload['reload_drains']['active_count'] == 1
    assert payload['reload_drains']['retry_command'] == 'ccb reload'
    assert payload['reload_drains']['active_records'][0]['agent'] == 'agent2'
    assert payload['reload_drains']['active_records'][0]['status'] == 'waiting'
    assert app.reload_drain_store.load().active_records_for('agent2')
    assert payload['diagnostics']['graph_published'] is False
    assert app.service_graph is old_graph

    dry_run_payload = app.socket_server._handlers['project_reload_config']({'dry_run': True})
    assert dry_run_payload['status'] == 'ok'
    assert dry_run_payload['dry_run'] is True
    assert dry_run_payload['reload_drains']['active_count'] == 1
    assert dry_run_payload['reload_drains']['active_records'][0]['agent'] == 'agent2'


def test_project_reload_non_dry_run_busy_replace_reports_drain_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-replace-handler', BASE_CONFIG)
    app.reload_drain_clock_s = lambda: 10.0
    old_graph = app.service_graph
    _seed_runtime(app.runtime_service, 'agent2', pane_id='%2', provider='claude')
    runtime = old_graph.registry.get('agent2')
    assert runtime is not None
    app.runtime_service.patch_runtime_state(runtime, state=AgentState.BUSY)
    _project(app.project_root, REPLACE_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('busy replace must not patch namespace')),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'blocked'
    assert payload['stage'] == 'plan'
    assert payload['plan_class'] == 'replace_agent'
    assert payload['mutation_enabled'] is False
    assert payload['diagnostics']['reason'] == 'agent_busy'
    assert payload['diagnostics']['drain_record']['intent']['intent_kind'] == 'replace'
    assert payload['diagnostics']['drain_record']['status'] == 'waiting'
    assert payload['reload_drains']['active_count'] == 1
    assert len(app.reload_drain_store.load().active_records_for('agent2')) == 1
    assert payload['diagnostics']['graph_published'] is False
    assert app.service_graph is old_graph


def test_project_reload_non_dry_run_namespace_failure_reports_residue_without_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-namespace-handler', BASE_CONFIG)
    old_graph = app.service_graph
    _project(app.project_root, ADD_WINDOW_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: NamespacePatchApplyResult(
            status='failed',
            created_windows=('review',),
            created_panes=('%3',),
            partial=True,
            rollback_actions=('created_pane:%3',),
            diagnostics={
                'reason': 'namespace_patch_failed',
                'message': 'split failed',
                'error_evidence': {'expected_restore_token': 'handler-session::workspace-1'},
            },
        ),
    )
    monkeypatch.setattr(
        'ccbd.reload_apply_service.run_runtime_mount',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not mount after namespace failure')),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'failed'
    assert payload['stage'] == 'namespace_patch'
    assert payload['mutation_enabled'] is False
    assert payload['diagnostics']['reason'] == 'namespace_patch_failed'
    assert payload['diagnostics']['namespace_residue']['created_windows'] == ['review']
    assert payload['diagnostics']['namespace_residue']['created_panes'] == ['%3']
    assert payload['diagnostics']['graph_published'] is False
    assert 'handler-session::workspace-1' not in json.dumps(payload, sort_keys=True)
    assert app.service_graph is old_graph


def test_project_reload_non_dry_run_runtime_failure_reports_residue_without_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-runtime-handler', BASE_CONFIG)
    old_graph = app.service_graph
    _project(app.project_root, ADD_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
    )
    monkeypatch.setattr(
        'ccbd.reload_apply_service.run_runtime_mount',
        lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='failed',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
            partial=True,
            diagnostics={'reason': 'runtime_mount_failed', 'message': 'provider launch failed'},
        ),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'failed'
    assert payload['stage'] == 'runtime_mount'
    assert payload['mutation_enabled'] is False
    assert payload['diagnostics']['runtime_residue']['runtime_authority_written_agents'] == ['agent3']
    assert payload['diagnostics']['graph_published'] is False
    assert app.service_graph is old_graph


def test_project_reload_non_dry_run_publish_failure_keeps_old_graph_and_reports_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _started_app(tmp_path / 'repo-publish-handler', BASE_CONFIG)
    old_graph = app.service_graph
    _project(app.project_root, ADD_AGENT_CONFIG)
    monkeypatch.setattr(
        'ccbd.reload_apply_service.apply_namespace_patch',
        lambda *_args, **_kwargs: _namespace_patch_result(agent_panes={'agent3': '%3'}),
    )
    monkeypatch.setattr(
        'ccbd.reload_apply_service.run_runtime_mount',
        lambda *_args, **_kwargs: AdditiveRuntimeMountResult(
            status='mounted',
            requested_agents=('agent3',),
            mounted_agents=('agent3',),
            runtime_authority_written_agents=('agent3',),
        ),
    )
    monkeypatch.setattr(
        app,
        'publish_service_graph',
        lambda _graph: (_ for _ in ()).throw(RuntimeError('publish failed')),
    )

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'failed'
    assert payload['stage'] == 'publish_transaction'
    assert payload['mutation_enabled'] is False
    assert payload['diagnostics']['reason'] == 'service_graph_publish_failed'
    assert payload['diagnostics']['graph_published'] is False
    assert payload['diagnostics']['publish_transaction_diagnostics']['signature_rollback']['complete'] is True
    assert app.service_graph is old_graph
    assert app.mount_manager.load_state().config_signature == old_graph.config_identity['config_signature']
    assert app.lifecycle_store.load().config_signature == old_graph.config_identity['config_signature']


def _started_app(project_root: Path, config_text: str) -> CcbdApp:
    app = CcbdApp(_project(project_root, config_text), clock=lambda: NOW, pid=4242)
    _store_namespace(app)
    app.lease = app.mount_manager.mark_mounted(
        project_id=app.project_id,
        pid=app.pid,
        socket_path=app.paths.ccbd_socket_path,
        generation=1,
        started_at=NOW,
        config_signature=app.config_identity['config_signature'],
        keeper_pid=app.keeper_pid,
        daemon_instance_id=app.daemon_instance_id,
    )
    app.lifecycle_store.save(
        build_lifecycle(
            project_id=app.project_id,
            occurred_at=NOW,
            desired_state='running',
            phase='mounted',
            generation=1,
            keeper_pid=app.keeper_pid,
            owner_pid=app.pid,
            owner_daemon_instance_id=app.daemon_instance_id,
            config_signature=app.config_identity['config_signature'],
            socket_path=app.paths.ccbd_socket_path,
            namespace_epoch=3,
        )
    )
    return app


def _fail_with(message: str):
    def _fail(*_args, **_kwargs):
        raise AssertionError(message)

    return _fail


def _namespace_patch_result(
    *,
    created_windows: tuple[str, ...] = (),
    created_panes: tuple[str, ...] = ('%3',),
    agent_panes: dict[str, str],
    sidebar_panes: dict[str, str] | None = None,
    removed_windows: tuple[str, ...] = (),
    removed_panes: tuple[str, ...] = (),
    removed_agents: dict[str, str] | None = None,
    tool_panes: dict[str, str] | None = None,
    preserved_before: dict[str, str] | None = None,
    preserved_after: dict[str, str] | None = None,
) -> NamespacePatchApplyResult:
    return NamespacePatchApplyResult(
        status='applied',
        created_windows=created_windows,
        created_panes=created_panes,
        agent_panes=agent_panes,
        sidebar_panes=sidebar_panes or {},
        removed_windows=removed_windows,
        removed_panes=removed_panes,
        removed_agents=removed_agents or {},
        tool_panes=tool_panes or {},
        preserved_before=preserved_before or {'agent1': '%1', 'agent2': '%2'},
        preserved_after=preserved_after or {'agent1': '%1', 'agent2': '%2'},
        diagnostics={
            'graph_published': False,
            'runtime_authority_written': False,
            'lease_or_lifecycle_written': False,
        },
    )


def _mounting_start_flow(app: CcbdApp, calls: list[dict[str, object]]):
    def _fake_start_flow(**kwargs):
        calls.append(kwargs)
        namespace_agent_panes = dict(kwargs['namespace_agent_panes'])
        for agent_name, pane_id in namespace_agent_panes.items():
            kwargs['runtime_service'].attach(
                agent_name=agent_name,
                workspace_path=str(app.paths.workspace_path(agent_name)),
                backend_type='pane-backed',
                runtime_ref=f'tmux:{pane_id}',
                session_ref=f'session-{agent_name}',
                health='healthy',
                provider='codex',
                terminal_backend='tmux',
                pane_id=pane_id,
                active_pane_id=pane_id,
                pane_state='alive',
                tmux_socket_path=str(kwargs['tmux_socket_path']),
                tmux_window_name='main',
                slot_key=agent_name,
                window_id=kwargs.get('workspace_window_id'),
                workspace_epoch=kwargs.get('workspace_epoch'),
                lifecycle_state='idle',
                managed_by='ccbd',
                binding_source='provider-session',
            )
        return StartFlowSummary(
            project_root=str(app.project_root),
            project_id=app.project_id,
            started=tuple(namespace_agent_panes),
            socket_path=str(app.paths.ccbd_socket_path),
            actions_taken=tuple(f'launch_runtime:{agent}' for agent in namespace_agent_panes),
            agent_results=tuple(
                CcbdStartupAgentResult(
                    agent_name=agent,
                    provider='codex',
                    action='launched',
                    health='healthy',
                    workspace_path=str(app.paths.workspace_path(agent)),
                    runtime_ref=f'tmux:{pane}',
                    session_ref=f'session-{agent}',
                    lifecycle_state='idle',
                    binding_source='provider-session',
                    terminal_backend='tmux',
                    tmux_socket_path=str(kwargs['tmux_socket_path']),
                    tmux_window_name='main',
                    pane_id=pane,
                    active_pane_id=pane,
                    pane_state='alive',
                )
                for agent, pane in namespace_agent_panes.items()
            ),
        )

    return _fake_start_flow


def _seed_runtime(runtime_service, agent_name: str, *, pane_id: str, provider: str = 'codex'):
    return runtime_service.attach(
        agent_name=agent_name,
        workspace_path=str(runtime_service._layout.workspace_path(agent_name)),
        backend_type='pane-backed',
        runtime_ref=f'tmux:{pane_id}',
        session_ref=f'session-{agent_name}',
        health='healthy',
        provider=provider,
        terminal_backend='tmux',
        pane_id=pane_id,
        active_pane_id=pane_id,
        pane_state='alive',
        tmux_socket_path=str(runtime_service._layout.ccbd_tmux_socket_path),
        tmux_window_name='main',
        slot_key=agent_name,
        lifecycle_state='idle',
        managed_by='ccbd',
        binding_source='provider-session',
    )


def _namespace(app: CcbdApp):
    return SimpleNamespace(
        project_id=app.project_id,
        namespace_epoch=3,
        tmux_socket_path=str(app.paths.ccbd_tmux_socket_path),
        tmux_session_name=app.paths.ccbd_tmux_session_name,
        workspace_window_name='main',
        workspace_window_id='@main',
        workspace_epoch=1,
        ui_attachable=True,
    )


def _store_namespace(app: CcbdApp) -> None:
    ProjectNamespaceStateStore(app.paths).save(
        ProjectNamespaceState(
            project_id=app.project_id,
            namespace_epoch=3,
            tmux_socket_path=str(app.paths.ccbd_tmux_socket_path),
            tmux_session_name=app.paths.ccbd_tmux_session_name,
            layout_version=3,
            layout_signature=None,
            control_window_name=app.paths.ccbd_tmux_control_window_name,
            control_window_id='@control',
            workspace_window_name='main',
            workspace_window_id='@main',
            workspace_epoch=1,
            ui_attachable=True,
            last_started_at=NOW,
        )
    )


def _project(project_root: Path, config_text: str) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_text, encoding='utf-8')
    return project_root


def _load_config(project_root: Path, config_text: str):
    return load_project_config(_project(project_root, config_text)).config


def _write_dynamic_agent_state(
    project_root: Path,
    *,
    agent: str,
    provider: str,
    role: str,
    window_name: str | None = None,
) -> None:
    state_path = project_root / '.ccb' / 'runtime' / 'agents' / agent / 'lifecycle.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_dynamic_agent_lifecycle',
                'agent_lifecycle_status': 'active',
                'agent': agent,
                'role': role,
                'provider': provider,
                'workspace_mode': 'inplace',
                'target': '.',
                'lifecycle_state': 'hidden',
                'visibility_state': 'hidden',
                'window_name': window_name,
            },
            sort_keys=True,
        ),
        encoding='utf-8',
    )


class _PatchFakeBackend:
    def __init__(self, socket_path: str | None = None) -> None:
        self.socket_path = socket_path
        self.sessions: dict[str, list[dict[str, object]]] = {}
        self.pane_options: dict[str, dict[str, str]] = {}
        self.pane_titles: dict[str, str] = {}
        self.split_calls: list[tuple[str, str, int]] = []
        self.tmux_calls: list[tuple[str, ...]] = []
        self.respawn_calls: list[tuple[str, str]] = []
        self.pane_counter = 0
        self.window_counter = 0

    def add_window(self, session_name: str, window_name: str) -> str:
        pane_id = self._alloc_pane()
        self.window_counter += 1
        self.sessions.setdefault(session_name, []).append(
            {
                'id': f'@{self.window_counter}',
                'name': window_name,
                'panes': [pane_id],
            }
        )
        return pane_id

    def split_pane(self, parent_pane_id: str, direction: str, percent: int, cmd=None, cwd=None) -> str:
        del cmd, cwd
        self.split_calls.append((parent_pane_id, direction, percent))
        for windows in self.sessions.values():
            for record in windows:
                panes = record['panes']
                if parent_pane_id in panes:
                    pane_id = self._alloc_pane()
                    panes.append(pane_id)
                    return pane_id
        raise RuntimeError(f'pane not found: {parent_pane_id}')

    def list_panes_by_user_options(self, expected: dict[str, str]) -> list[str]:
        return [
            pane_id
            for pane_id, options in self.pane_options.items()
            if all(str(options.get(key, '') or '') == str(value) for key, value in expected.items())
        ]

    def respawn_pane(self, pane_id: str, *, cmd: str, cwd: str | None = None, remain_on_exit: bool = True) -> None:
        del cwd, remain_on_exit
        self.respawn_calls.append((pane_id, cmd))

    def set_pane_title(self, pane_id: str, title: str) -> None:
        self.pane_titles[pane_id] = title

    def set_pane_user_option(self, pane_id: str, name: str, value: str) -> None:
        self.pane_options.setdefault(pane_id, {})[name] = value

    def set_pane_style(self, pane_id: str, *, border_style=None, active_border_style=None) -> None:
        if border_style:
            self.set_pane_user_option(pane_id, 'pane-border-style', border_style)
        if active_border_style:
            self.set_pane_user_option(pane_id, 'pane-active-border-style', active_border_style)

    def describe_pane(self, pane_id: str, *, user_options=()) -> dict[str, str]:
        for session_name, windows in self.sessions.items():
            for window in windows:
                if pane_id not in window['panes']:
                    continue
                details = {
                    'pane_id': pane_id,
                    'session_name': session_name,
                    'window_id': str(window['id']),
                    'window_name': str(window['name']),
                    'pane_dead': '0',
                }
                options = self.pane_options.get(pane_id, {})
                details.update({name: options.get(name, '') for name in user_options})
                return details
        return {}

    def _tmux_run(self, args: list[str], *, check=False, capture=False, input_bytes=None, timeout=None):
        del check, capture, input_bytes, timeout
        if args[:2] == ['display-message', '-p']:
            return SimpleNamespace(returncode=1, stdout='', stderr='unsupported by fake backend')
        self.tmux_calls.append(tuple(args))
        if args[:2] == ['has-session', '-t']:
            return SimpleNamespace(returncode=0 if args[2] in self.sessions else 1, stdout='', stderr='')
        if len(args) >= 7 and args[:2] == ['new-window', '-d']:
            session_name = args[args.index('-t') + 1]
            window_name = args[args.index('-n') + 1]
            self.add_window(session_name, window_name)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 4 and args[:2] == ['list-windows', '-t']:
            session_name = args[2]
            rows = [f"{record['id']}\t{record['name']}\t0" for record in self.sessions.get(session_name, [])]
            return SimpleNamespace(returncode=0, stdout='\n'.join(rows), stderr='')
        if len(args) >= 4 and args[:2] == ['list-panes', '-t']:
            target = args[2]
            session_name, _, window_ref = target.partition(':')
            record = self._window(session_name, window_ref)
            panes = list(record['panes']) if record is not None else []
            return SimpleNamespace(returncode=0, stdout='\n'.join(str(item) for item in panes), stderr='')
        raise AssertionError(f'unexpected tmux command in additive reload test: {args}')

    def _window(self, session_name: str, window_ref: str) -> dict[str, object] | None:
        for record in self.sessions.get(session_name, []):
            if record['name'] == window_ref or record['id'] == window_ref:
                return record
        return None

    def _alloc_pane(self) -> str:
        self.pane_counter += 1
        return f'%{self.pane_counter}'


def _seed_agent_pane(
    backend: _PatchFakeBackend,
    pane_id: str,
    *,
    project_id: str,
    window: str,
    agent: str,
    namespace_epoch: int = 3,
) -> None:
    backend.pane_options[pane_id] = {
        '@ccb_project_id': project_id,
        '@ccb_role': 'agent',
        '@ccb_slot': agent,
        '@ccb_window': window,
        '@ccb_managed_by': 'ccbd',
        '@ccb_namespace_epoch': str(namespace_epoch),
    }
