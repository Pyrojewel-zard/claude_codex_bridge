from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from agents.models import AgentRuntime, AgentState, AgentSpec, PermissionMode, QueuePolicy, RestoreMode, RuntimeMode, WorkspaceMode
from agents.store import AgentRuntimeStore
from ccbd.lifecycle_report_store import CcbdShutdownReportStore
from ccbd.models import LeaseHealth
from ccbd.services.start_policy import CcbdStartPolicy, CcbdStartPolicyStore
from ccbd.socket_client import CcbdClientError
from cli.context import CliContextBuilder
from cli.services.kill_runtime.agent_cleanup import collect_candidate_tmux_sockets, prepare_local_shutdown
from cli.services.kill_runtime.remote import await_remote_shutdown
import cli.services.daemon as daemon_service
import cli.services.kill as kill_service
from cli.services.daemon import CcbdServiceError
from cli.models import ParsedKillCommand
from cli.services.daemon import KillSummary, shutdown_daemon
from cli.services.kill import kill_project
from cli.services.tmux_project_cleanup import ProjectTmuxCleanupSummary
from project.resolver import bootstrap_project
from workspace.materializer import WorkspaceMaterializer
from workspace.planner import WorkspacePlanner


def test_post_kill_cleanup_removes_retired_project_provider_cache(monkeypatch) -> None:
    context = SimpleNamespace(paths=SimpleNamespace())
    summary = KillSummary(
        project_id='project-id',
        state='unmounted',
        socket_path='/tmp/ccb.sock',
        forced=False,
        runtime_actions=('existing-action',),
    )
    monkeypatch.setattr(
        kill_service,
        'current_project_legacy_provider_cache_present',
        lambda _paths: True,
    )
    monkeypatch.setattr(
        kill_service,
        'cleanup_current_project_legacy_provider_caches',
        lambda _context, *, measure_bytes: SimpleNamespace(
            actions=(
                SimpleNamespace(kind='legacy_cache_link'),
                SimpleNamespace(kind='legacy_project_cache'),
            ),
            skipped_count=0,
        ),
    )

    result = kill_service._cleanup_legacy_provider_cache_after_kill(context, summary)

    assert result.runtime_actions == (
        'existing-action',
        'cleanup_legacy_provider_cache:deleted=1',
    )


def test_post_kill_cleanup_failure_is_deferred_non_destructively(monkeypatch) -> None:
    context = SimpleNamespace(paths=SimpleNamespace())
    summary = KillSummary(
        project_id='project-id',
        state='unmounted',
        socket_path='/tmp/ccb.sock',
        forced=False,
    )
    monkeypatch.setattr(
        kill_service,
        'current_project_legacy_provider_cache_present',
        lambda _paths: True,
    )
    monkeypatch.setattr(
        kill_service,
        'cleanup_current_project_legacy_provider_caches',
        lambda _context, *, measure_bytes: (_ for _ in ()).throw(RuntimeError('still busy')),
    )

    result = kill_service._cleanup_legacy_provider_cache_after_kill(context, summary)

    assert result.state == 'unmounted'
    assert 'cleanup deferred after kill' in result.runtime_warnings[0]


def test_post_kill_cleanup_does_not_run_when_shutdown_is_incomplete(monkeypatch) -> None:
    context = SimpleNamespace(paths=SimpleNamespace())
    summary = KillSummary(
        project_id='project-id',
        state='mounted',
        socket_path='/tmp/ccb.sock',
        forced=False,
    )
    monkeypatch.setattr(
        kill_service,
        'current_project_legacy_provider_cache_present',
        lambda _paths: (_ for _ in ()).throw(AssertionError('must not inspect cache')),
    )

    assert kill_service._cleanup_legacy_provider_cache_after_kill(context, summary) is summary


def _namespace_controller(*, destroyed: bool):
    return lambda paths, project_id: SimpleNamespace(
        destroy=lambda **kwargs: SimpleNamespace(
            destroyed=destroyed,
            namespace_epoch=1,
            tmux_socket_path=str(getattr(paths, 'ccbd_tmux_socket_path', '')),
            tmux_session_name='ccb-test',
            reason=str(kwargs.get('reason') or 'kill'),
        )
    )


def _git_worktree_spec() -> AgentSpec:
    return AgentSpec(
        name='agent1',
        provider='codex',
        target='.',
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
        branch_template=None,
    )


def test_await_remote_shutdown_waits_for_ccbd_and_keeper_exit(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-remote-waits-pids'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    context = CliContextBuilder().build(
        ParsedKillCommand(project=None, force=False),
        cwd=project_root,
        bootstrap_if_missing=False,
    )
    lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='unmounted'),
        ccbd_pid=321,
        keeper_pid=654,
    )
    inspections: list[object] = []

    def _inspect(_context):
        inspections.append(object())
        return (
            None,
            None,
            SimpleNamespace(
                socket_connectable=False,
                health=LeaseHealth.UNMOUNTED,
                lease=lease,
            ),
        )

    alive = {321, 654}
    terminated: list[int] = []

    def _terminate(pid, *, timeout_s, is_pid_alive_fn):
        del timeout_s
        del is_pid_alive_fn
        terminated.append(pid)
        alive.discard(pid)
        return True

    summary = await_remote_shutdown(
        context,
        force=False,
        inspect_daemon_fn=_inspect,
        lease_health_cls=LeaseHealth,
        kill_summary_cls=KillSummary,
        timeout_s=0.01,
        lease_pid_fn=lambda lease: lease.ccbd_pid,
        keeper_pid_fn=lambda context, lease: lease.keeper_pid,
        wait_for_pid_exit_fn=lambda pid, timeout_s: False,
        wait_for_keeper_exit_fn=lambda context, timeout_s: False,
        is_pid_alive_fn=lambda pid: pid in alive,
        terminate_pid_tree_fn=_terminate,
        shutdown_timeout_s=0.01,
    )

    assert summary.state == 'unmounted'
    assert len(inspections) >= 2
    assert terminated == [321, 654]


def test_await_remote_shutdown_tracks_prepared_and_current_lease_pids(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-remote-prepared-and-current-pids'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    context = CliContextBuilder().build(
        ParsedKillCommand(project=None, force=False),
        cwd=project_root,
        bootstrap_if_missing=False,
    )
    new_lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='unmounted'),
        ccbd_pid=9001,
        keeper_pid=9002,
    )
    alive = {111, 222, 9001, 9002}
    terminated: list[int] = []

    def _terminate(pid, *, timeout_s, is_pid_alive_fn):
        del timeout_s
        del is_pid_alive_fn
        terminated.append(pid)
        alive.discard(pid)
        return True

    await_remote_shutdown(
        context,
        force=False,
        inspect_daemon_fn=lambda _context: (
            None,
            None,
            SimpleNamespace(
                socket_connectable=False,
                health=LeaseHealth.UNMOUNTED,
                lease=new_lease,
            ),
        ),
        lease_health_cls=LeaseHealth,
        kill_summary_cls=KillSummary,
        timeout_s=0.01,
        expected_pids=(111, 222),
        lease_pid_fn=lambda lease: lease.ccbd_pid,
        keeper_pid_fn=lambda context, lease: lease.keeper_pid,
        wait_for_pid_exit_fn=lambda pid, timeout_s: False,
        wait_for_keeper_exit_fn=lambda context, timeout_s: False,
        is_pid_alive_fn=lambda pid: pid in alive,
        terminate_pid_tree_fn=_terminate,
        shutdown_timeout_s=0.01,
    )

    assert terminated == [111, 222, 9001, 9002]
    assert alive == set()


def test_await_remote_shutdown_finalizes_lifecycle_after_remote_stop(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-remote-finalizes-lifecycle'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    context = CliContextBuilder().build(
        ParsedKillCommand(project=None, force=False),
        cwd=project_root,
        bootstrap_if_missing=False,
    )
    finalized: list[Path] = []

    summary = await_remote_shutdown(
        context,
        force=False,
        inspect_daemon_fn=lambda _context: (
            None,
            None,
            SimpleNamespace(
                socket_connectable=False,
                health=LeaseHealth.UNMOUNTED,
                lease=SimpleNamespace(mount_state=SimpleNamespace(value='unmounted')),
            ),
        ),
        lease_health_cls=LeaseHealth,
        kill_summary_cls=KillSummary,
        timeout_s=0.01,
        is_pid_alive_fn=lambda pid: False,
        terminate_pid_tree_fn=lambda pid, timeout_s, is_pid_alive_fn: True,
        finalize_shutdown_lifecycle_fn=lambda current: finalized.append(current.project.project_root),
        shutdown_timeout_s=0.01,
    )

    assert summary.state == 'unmounted'
    assert finalized == [project_root]


def test_kill_project_returns_tmux_cleanup_summary(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-cleanup'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr(
        'cli.services.kill.cleanup_project_tmux_orphans_by_socket',
        lambda **kwargs: (
            ProjectTmuxCleanupSummary(
                socket_name=None,
                owned_panes=('%1',),
                active_panes=(),
                orphaned_panes=('%1',),
                killed_panes=('%1',),
            ),
        ),
    )
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    summary = kill_project(context, command)

    assert len(summary.cleanup_summaries) == 1
    assert summary.cleanup_summaries[0].killed_panes == ('%1',)


def test_kill_project_snapshots_control_plane_pids_before_remote_stop(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-pid-snapshot-before-remote'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    events: list[str] = []
    captured_expected_pids: list[tuple[int, ...]] = []

    class _FakeClient:
        def stop_all(self, *, force: bool):
            assert force is False
            events.append('remote_stop')
            return {
                'project_id': context.project.project_id,
                'state': 'unmounted',
                'socket_path': str(context.paths.ccbd_socket_path),
                'forced': False,
                'cleanup_summaries': [],
            }

    def _collect_authority(_project_root):
        events.append('collect_authority')
        return {111: [project_root / '.ccb' / 'ccbd' / 'lease.json']}

    monkeypatch.setattr(
        'cli.services.kill.connect_mounted_daemon',
        lambda context, allow_restart_stale: SimpleNamespace(client=_FakeClient()),
    )
    monkeypatch.setattr('cli.services.kill._collect_project_authority_pid_candidates', _collect_authority)
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill._await_remote_shutdown',
        lambda context, *, force, expected_pids: captured_expected_pids.append(tuple(expected_pids))
        or KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill._pid_matches_project', lambda pid, project_root, hint_paths: True)
    monkeypatch.setattr('cli.services.kill.is_pid_alive', lambda pid: pid == 111)
    monkeypatch.setattr('cli.services.kill.terminate_pid_tree', lambda pid, timeout_s, is_pid_alive_fn: True)

    kill_project(context, command)

    assert events == ['collect_authority', 'remote_stop']
    assert captured_expected_pids == [(111,)]


def test_remote_stop_records_shutdown_intent_before_stop_all(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-intent-before-stop-all'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    events: list[str] = []

    class _FakeClient:
        def stop_all(self, *, force: bool):
            assert force is False
            events.append('remote_stop')
            return {
                'project_id': context.project.project_id,
                'state': 'unmounted',
                'socket_path': str(context.paths.ccbd_socket_path),
                'forced': False,
                'cleanup_summaries': [],
            }

    def _connect(_context, *, allow_restart_stale: bool):
        assert allow_restart_stale is False
        events.append('connect')
        return SimpleNamespace(client=_FakeClient())

    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', _connect)
    monkeypatch.setattr('cli.services.kill.record_shutdown_intent', lambda context, reason: events.append(f'intent:{reason}'))
    monkeypatch.setattr('cli.services.kill._collect_project_authority_pid_candidates', lambda _project_root: {})
    monkeypatch.setattr('cli.services.kill._await_remote_shutdown', lambda context, *, force, expected_pids: KillSummary(
        project_id=context.project.project_id,
        state='unmounted',
        socket_path=str(context.paths.ccbd_socket_path),
        forced=force,
    ))
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())

    kill_project(context, command)

    assert events == ['connect', 'intent:kill', 'remote_stop']


def test_remote_stop_transport_loss_after_intent_falls_back_to_local_shutdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-kill-remote-stop-socket-race'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    events: list[str] = []

    class _DisappearingClient:
        def stop_all(self, *, force: bool):
            assert force is False
            events.append('remote_stop')
            cause = FileNotFoundError(2, 'No such file or directory')
            raise CcbdClientError(str(cause)) from cause

    monkeypatch.setattr(
        'cli.services.kill.connect_mounted_daemon',
        lambda context, allow_restart_stale: events.append('connect')
        or SimpleNamespace(client=_DisappearingClient()),
    )
    monkeypatch.setattr(
        'cli.services.kill.record_shutdown_intent',
        lambda context, reason: events.append(f'intent:{reason}'),
    )
    monkeypatch.setattr('cli.services.kill._collect_project_authority_pid_candidates', lambda _project_root: {})
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: events.append('local_shutdown')
        or KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())

    summary = kill_project(context, command)

    assert summary.state == 'unmounted'
    assert events == ['connect', 'intent:kill', 'remote_stop', 'local_shutdown']


def test_kill_project_writes_shutdown_report_after_remote_stop_all(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-report-remote'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    AgentRuntimeStore(context.paths).save(
        AgentRuntime(
            agent_name='demo',
            state=AgentState.STOPPED,
            pid=None,
            started_at='2026-04-03T00:00:00Z',
            last_seen_at='2026-04-03T00:00:01Z',
            runtime_ref=None,
            session_ref=None,
            workspace_path=str(context.paths.workspace_path('demo')),
            project_id=context.project.project_id,
            backend_type='tmux',
            queue_depth=0,
            socket_path=None,
            health='stopped',
            desired_state='stopped',
            reconcile_state='stopped',
        )
    )

    class _FakeClient:
        def stop_all(self, *, force: bool):
            assert force is False
            return {
                'project_id': context.project.project_id,
                'state': 'unmounted',
                'socket_path': str(context.paths.ccbd_socket_path),
                'forced': False,
                'stopped_agents': ['demo'],
                'cleanup_summaries': [],
            }

    monkeypatch.setattr(
        'cli.services.kill.connect_mounted_daemon',
        lambda context, allow_restart_stale: SimpleNamespace(client=_FakeClient()),
    )
    monkeypatch.setattr(
        'cli.services.kill.inspect_daemon',
        lambda context: (
            None,
            None,
            SimpleNamespace(
                socket_connectable=False,
                health=LeaseHealth.UNMOUNTED,
                lease=SimpleNamespace(mount_state=SimpleNamespace(value='unmounted')),
            ),
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())

    summary = kill_project(context, command)
    report = CcbdShutdownReportStore(context.paths).load()

    assert summary.state == 'unmounted'
    assert report is not None
    assert report.trigger == 'kill'
    assert report.reason == 'kill'
    assert report.status == 'ok'
    assert report.stopped_agents == ('demo',)


def test_kill_project_clears_start_policy(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-policy'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    CcbdStartPolicyStore(context.paths).save(
        CcbdStartPolicy(
            project_id=context.project.project_id,
            auto_permission=True,
            recovery_restore=True,
            last_started_at='2026-04-03T00:00:00Z',
            source='start_command',
        )
    )

    monkeypatch.setattr(
        'cli.services.kill.connect_mounted_daemon',
        lambda context, allow_restart_stale: SimpleNamespace(client=None),
    )
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())

    kill_project(context, command)

    assert CcbdStartPolicyStore(context.paths).load() is None


def test_kill_project_remote_stop_all_still_runs_local_cleanup(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-remote-hard-cleanup'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    class _FakeClient:
        def stop_all(self, *, force: bool):
            assert force is False
            seen['remote_stop_all'] = True
            return {
                'project_id': context.project.project_id,
                'state': 'unmounted',
                'socket_path': str(context.paths.ccbd_socket_path),
                'forced': False,
                'cleanup_summaries': [],
            }

    monkeypatch.setattr(
        'cli.services.kill.connect_mounted_daemon',
        lambda context, allow_restart_stale: SimpleNamespace(client=_FakeClient()),
    )

    monkeypatch.setattr(
        'cli.services.kill.inspect_daemon',
        lambda context: (
            None,
            None,
            SimpleNamespace(
                socket_connectable=False,
                health=LeaseHealth.UNMOUNTED,
                lease=SimpleNamespace(mount_state=SimpleNamespace(value='unmounted')),
            ),
        ),
    )
    monkeypatch.delenv('TMUX', raising=False)
    monkeypatch.delenv('CCB_TMUX_SOCKET', raising=False)
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))

    def _cleanup(**kwargs):
        seen['cleanup'] = kwargs['active_panes_by_socket']
        return ()

    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', _cleanup)

    summary = kill_project(context, command)

    assert seen['remote_stop_all'] is True
    assert 'shutdown_daemon' not in seen
    assert seen['cleanup'] == {None: ()}
    assert summary.state == 'unmounted'


def test_kill_project_uses_current_tmux_socket_when_binding_missing(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-current-socket'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/ccb,123,0')
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))

    def _cleanup(**kwargs):
        seen['active_panes_by_socket'] = kwargs['active_panes_by_socket']
        return ()

    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', _cleanup)
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    kill_project(context, command)

    assert seen['active_panes_by_socket'] == {'/tmp/tmux-1000/ccb': ()}


def test_collect_candidate_tmux_sockets_preserves_tmux_socket_path(monkeypatch) -> None:
    monkeypatch.delenv('CCB_TMUX_SOCKET', raising=False)
    monkeypatch.delenv('CCB_TMUX_SOCKET_PATH', raising=False)
    monkeypatch.setenv('TMUX', '/tmp/ccb project/tmux.sock,123,0')

    assert collect_candidate_tmux_sockets() == {'/tmp/ccb project/tmux.sock'}


def test_prepare_local_shutdown_captures_runtime_tmux_socket_path(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-runtime-socket-path'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = CliContextBuilder().build(
        ParsedKillCommand(project=None, force=False),
        cwd=project_root,
        bootstrap_if_missing=False,
    )
    AgentRuntimeStore(context.paths).save(
        AgentRuntime(
            agent_name='demo',
            state=AgentState.IDLE,
            pid=None,
            started_at='2026-04-01T00:00:00Z',
            last_seen_at='2026-04-01T00:00:00Z',
            runtime_ref='tmux:%1',
            session_ref=None,
            workspace_path=str(context.paths.workspace_path('demo')),
            project_id=context.project.project_id,
            backend_type='pane-backed',
            queue_depth=0,
            socket_path=str(context.paths.ccbd_socket_path),
            health='healthy',
            tmux_socket_path='/tmp/ccb project/tmux.sock',
        )
    )
    monkeypatch.delenv('TMUX', raising=False)
    monkeypatch.delenv('CCB_TMUX_SOCKET', raising=False)
    monkeypatch.delenv('CCB_TMUX_SOCKET_PATH', raising=False)

    preparation = prepare_local_shutdown(
        context,
        force=False,
        collect_agent_pid_candidates_fn=lambda **kwargs: {},
        collect_project_authority_pid_candidates_fn=lambda _project_root: {},
    )

    assert '/tmp/ccb project/tmux.sock' in preparation.tmux_sockets


def test_kill_project_terminates_runtime_pid_files(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-pids'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    runtime_dir = context.paths.agent_provider_runtime_dir('demo', 'codex')
    runtime_dir.mkdir(parents=True, exist_ok=True)
    helper_path = context.paths.agent_helper_path('demo')
    helper_path.write_text(
        (
            '{"schema_version":1,"record_type":"provider_helper_manifest","agent_name":"demo",'
            '"runtime_generation":2,"helper_kind":"codex_bridge","leader_pid":111,"pgid":111,'
            '"started_at":"2026-04-21T00:00:00Z","owner_daemon_generation":5,"state":"running"}\n'
        ),
        encoding='utf-8',
    )
    bridge_pid = runtime_dir / 'bridge.pid'
    codex_pid = runtime_dir / 'codex.pid'
    bridge_pid.write_text('111\n', encoding='utf-8')
    codex_pid.write_text('222\n', encoding='utf-8')
    AgentRuntimeStore(context.paths).save(
        AgentRuntime(
            agent_name='demo',
            state=AgentState.IDLE,
            pid=333,
            started_at='2026-04-01T00:00:00Z',
            last_seen_at='2026-04-01T00:00:00Z',
            runtime_ref='tmux:%1',
            session_ref=str(project_root / '.ccb' / '.codex-demo-session'),
            workspace_path=str(context.paths.workspace_path('demo')),
            project_id=context.project.project_id,
            backend_type='pane-backed',
            queue_depth=2,
            socket_path=str(context.paths.ccbd_socket_path),
            health='healthy',
        )
    )

    terminated: list[int] = []
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )
    monkeypatch.setattr('cli.services.kill._pid_matches_project', lambda pid, project_root, hint_paths: True)
    monkeypatch.setattr('cli.services.kill.is_pid_alive', lambda pid: pid in {111, 222, 333})
    monkeypatch.setattr(
        'cli.services.kill.terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )

    kill_project(context, command)

    assert terminated == [111, 222, 333]
    assert bridge_pid.exists() is False
    assert codex_pid.exists() is False
    assert helper_path.exists() is False
    runtime = AgentRuntimeStore(context.paths).load('demo')
    assert runtime is not None
    assert runtime.state is AgentState.STOPPED
    assert runtime.pid is None
    assert runtime.runtime_ref is None
    assert runtime.desired_state == 'stopped'
    assert runtime.reconcile_state == 'stopped'


def test_kill_project_force_terminates_authority_pids_via_project_cmdline_without_procfs(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-authority-pids-cmdline'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    terminated: list[int] = []
    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', lambda context, allow_restart_stale: (_ for _ in ()).throw(CcbdServiceError('down')))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr(
        'cli.services.kill._collect_project_authority_pid_candidates',
        lambda _project_root: {
            321: [context.paths.ccbd_lease_path],
            654: [context.paths.ccbd_keeper_path],
        },
    )
    monkeypatch.setattr('cli.services.kill._read_proc_path', lambda pid, entry: None)
    monkeypatch.setattr(
        'cli.services.kill._read_proc_cmdline',
        lambda pid: (
            f'/usr/bin/python /opt/ccb/lib/ccbd/main.py --project {project_root}'
            if pid == 321
            else f'/usr/bin/python /opt/ccb/lib/ccbd/keeper_main.py --project {project_root}'
            if pid == 654
            else ''
        ),
    )
    monkeypatch.setattr('cli.services.kill.is_pid_alive', lambda pid: pid in {321, 654})
    monkeypatch.setattr(
        'cli.services.kill.terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    summary = kill_project(context, command)

    assert summary.state == 'unmounted'
    assert terminated == [321, 654]


def test_shutdown_daemon_terminates_lingering_ccbd_pid(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-daemon-pid'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='unmounted'),
        ccbd_pid=321,
        daemon_instance_id='daemon-a',
    )
    mark_calls: list[dict[str, object]] = []
    manager = SimpleNamespace(
        mark_unmounted=lambda **kwargs: mark_calls.append(dict(kwargs)) or lease,
        load_state=lambda: lease,
    )
    inspection = SimpleNamespace(
        socket_connectable=True,
        pid_alive=True,
        lease=lease,
    )
    client_calls: list[str] = []
    captured: dict[str, float | None] = {}
    terminated: list[int] = []

    class FakeClient:
        def __init__(self, _path, *, timeout_s=None):
            captured['timeout_s'] = timeout_s

        def shutdown(self):
            client_calls.append('shutdown')

    monkeypatch.setattr('cli.services.daemon.inspect_daemon', lambda context: (manager, None, inspection))
    monkeypatch.setattr('cli.services.daemon.CcbdClient', FakeClient)
    monkeypatch.setattr('cli.services.daemon._wait_for_pid_exit', lambda pid, timeout_s: False)
    monkeypatch.setattr('cli.services.daemon.is_pid_alive', lambda pid: False)
    monkeypatch.setattr(
        'cli.services.daemon.terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )

    summary = shutdown_daemon(context, force=False)

    assert client_calls == ['shutdown']
    assert captured['timeout_s'] is None
    assert terminated == [321]
    assert mark_calls == [
        {
            'expected_pid': 321,
            'expected_daemon_instance_id': 'daemon-a',
        }
    ]
    assert summary.state == 'unmounted'


def test_shutdown_daemon_finishes_when_socket_disappears_after_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-kill-daemon-socket-race'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='unmounted'),
        ccbd_pid=0,
        daemon_instance_id='daemon-a',
    )
    manager = SimpleNamespace(
        mark_unmounted=lambda **kwargs: lease,
        load_state=lambda: lease,
    )
    inspection = SimpleNamespace(
        phase='unmounted',
        socket_connectable=True,
        pid_alive=False,
        lease=lease,
    )
    client_calls: list[str] = []

    class DisappearingClient:
        def __init__(self, _path, *, timeout_s=None):
            pass

        def shutdown(self):
            client_calls.append('shutdown')
            cause = FileNotFoundError(2, 'No such file or directory')
            raise CcbdClientError(str(cause)) from cause

    monkeypatch.setattr('cli.services.daemon.inspect_daemon', lambda context: (manager, None, inspection))
    monkeypatch.setattr('cli.services.daemon.CcbdClient', DisappearingClient)
    monkeypatch.setattr('cli.services.daemon._wait_for_keeper_exit', lambda context, timeout_s: True)

    summary = shutdown_daemon(context, force=False)

    assert client_calls == ['shutdown']
    assert summary.state == 'unmounted'


def test_shutdown_daemon_does_not_unmount_replaced_lease_holder(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-daemon-replaced'
    project_root.mkdir(parents=True, exist_ok=True)
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=False)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    inspected_lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='mounted'),
        ccbd_pid=321,
        daemon_instance_id='daemon-a',
    )
    replacement_lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='mounted'),
        ccbd_pid=654,
        daemon_instance_id='daemon-b',
    )
    mark_calls: list[dict[str, object]] = []

    def _mark_unmounted(**kwargs):
        mark_calls.append(dict(kwargs))
        raise RuntimeError('ccbd lease holder changed')

    manager = SimpleNamespace(
        mark_unmounted=_mark_unmounted,
        load_state=lambda: replacement_lease,
    )
    inspection = SimpleNamespace(
        socket_connectable=False,
        pid_alive=False,
        lease=inspected_lease,
    )

    monkeypatch.setattr('cli.services.daemon.inspect_daemon', lambda context: (manager, None, inspection))
    monkeypatch.setattr('cli.services.daemon._wait_for_keeper_exit', lambda context, timeout_s: True)
    monkeypatch.setattr('cli.services.daemon.is_pid_alive', lambda pid: False)

    summary = shutdown_daemon(context, force=False)

    assert mark_calls == [
        {
            'expected_pid': 321,
            'expected_daemon_instance_id': 'daemon-a',
        }
    ]
    assert summary.state == 'mounted'


def test_kill_project_force_ignores_invalid_runtime_file_for_unknown_agent(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-invalid-extra-runtime'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    invalid_runtime = context.paths.agent_runtime_path('legacy')
    invalid_runtime.parent.mkdir(parents=True, exist_ok=True)
    invalid_runtime.write_text('{"agent_name":"legacy"}\n', encoding='utf-8')

    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', lambda context, allow_restart_stale: (_ for _ in ()).throw(CcbdServiceError('down')))
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    summary = kill_project(context, command)

    assert summary.state == 'unmounted'


def test_kill_project_fallback_writes_shutdown_report(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-report-fallback'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    AgentRuntimeStore(context.paths).save(
        AgentRuntime(
            agent_name='demo',
            state=AgentState.STOPPED,
            pid=None,
            started_at='2026-04-03T00:00:00Z',
            last_seen_at='2026-04-03T00:00:01Z',
            runtime_ref=None,
            session_ref=None,
            workspace_path=str(context.paths.workspace_path('demo')),
            project_id=context.project.project_id,
            backend_type='tmux',
            queue_depth=0,
            socket_path=None,
            health='stopped',
            desired_state='stopped',
            reconcile_state='stopped',
        )
    )

    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', lambda context, allow_restart_stale: (_ for _ in ()).throw(CcbdServiceError('down')))
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    kill_project(context, command)
    report = CcbdShutdownReportStore(context.paths).load()

    assert report is not None
    assert report.trigger == 'kill_fallback'
    assert report.reason == 'kill'
    assert report.status == 'ok'


def test_kill_project_fallback_still_cleans_external_tmux_after_namespace_destroy(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-namespace-first'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', lambda context, allow_restart_stale: (_ for _ in ()).throw(CcbdServiceError('down')))
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=True))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr(
        'cli.services.kill.cleanup_project_tmux_orphans_by_socket',
        lambda **kwargs: (
            ProjectTmuxCleanupSummary(
                socket_name=None,
                owned_panes=('%7',),
                active_panes=(),
                orphaned_panes=('%7',),
                killed_panes=('%7',),
            ),
        ),
    )

    summary = kill_project(context, command)

    assert len(summary.cleanup_summaries) == 1
    assert summary.cleanup_summaries[0].killed_panes == ('%7',)


def test_kill_project_force_prunes_missing_registered_project_worktrees(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-prune-worktree'
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / 'README.md').write_text('hello\n', encoding='utf-8')
    subprocess.run(['git', 'init'], cwd=project_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=project_root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=project_root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=project_root, check=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=project_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('agent1:codex\n', encoding='utf-8')
    bootstrap_project(project_root)

    command = ParsedKillCommand(project=None, force=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    plan = WorkspacePlanner().plan(_git_worktree_spec(), context.project)
    WorkspaceMaterializer().materialize(plan)
    shutil.rmtree(plan.workspace_path)

    monkeypatch.setattr('cli.services.kill.connect_mounted_daemon', lambda context, allow_restart_stale: (_ for _ in ()).throw(CcbdServiceError('down')))
    monkeypatch.setattr('cli.services.kill.ProjectNamespaceController', _namespace_controller(destroyed=False))
    monkeypatch.setattr(
        'cli.services.kill.shutdown_daemon',
        lambda context, force: KillSummary(
            project_id=context.project.project_id,
            state='unmounted',
            socket_path=str(context.paths.ccbd_socket_path),
            forced=force,
        ),
    )
    monkeypatch.setattr('cli.services.kill.set_tmux_ui_active', lambda active: None)
    monkeypatch.setattr('cli.services.kill.cleanup_project_tmux_orphans_by_socket', lambda **kwargs: ())
    monkeypatch.setattr(
        'cli.services.kill.TmuxCleanupHistoryStore',
        lambda paths: type('Store', (), {'append': staticmethod(lambda event: None)})(),
    )

    summary = kill_project(context, command)

    assert summary.state == 'unmounted'
    worktrees = subprocess.run(
        ['git', '-C', str(project_root), 'worktree', 'list', '--porcelain'],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    assert str(plan.workspace_path) not in worktrees
