from __future__ import annotations

from contextlib import contextmanager, nullcontext
import errno
from pathlib import Path
from types import SimpleNamespace

from agents.config_identity import project_config_identity_payload
from agents.config_loader import load_project_config
from ccbd.keeper import KeeperState, KeeperStateStore, ProjectKeeper, ShutdownIntent, ShutdownIntentStore
from ccbd.keeper_runtime.failure_policy import (
    KEEPER_RESTART_SUPPRESSED_PREFIX,
    KEEPER_START_FAILURE_SUPPRESS_AFTER,
)
from ccbd.models import CcbdLease, LeaseHealth, LeaseInspection, MountState
from ccbd.reload_handoff import ReloadHandoff, ReloadHandoffStore, reload_handoff_allows_signature_mismatch
from ccbd.services.lifecycle import CcbdLifecycleStore, build_lifecycle
from ccbd.services.project_namespace_state import ProjectNamespaceState, ProjectNamespaceStateStore
from cli.context import CliContext
from cli.models import ParsedStartCommand
import cli.services.daemon as daemon_service
import ccbd.keeper as keeper_module
import ccbd.keeper_runtime.loop as keeper_loop
from project.resolver import bootstrap_project
from storage.paths import PathLayout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _context(project_root: Path, config_text: str) -> CliContext:
    project_root.mkdir(parents=True, exist_ok=True)
    _write(project_root / '.ccb' / 'ccb.config', config_text)
    project = bootstrap_project(project_root)
    command = ParsedStartCommand(project=None, agent_names=(), restore=False, auto_permission=False)
    return CliContext(command=command, cwd=project_root, project=project, paths=PathLayout(project_root))


def _inspection(
    context: CliContext,
    *,
    health: LeaseHealth,
    socket_connectable: bool,
    pid_alive: bool,
    heartbeat_fresh: bool,
    mount_state: MountState = MountState.MOUNTED,
    reason: str,
    config_signature: str | None = None,
    daemon_instance_id: str | None = None,
    generation: int = 1,
) -> LeaseInspection:
    lease = None
    if health is not LeaseHealth.MISSING:
        lease = CcbdLease(
            project_id=context.project.project_id,
            ccbd_pid=321,
            socket_path=str(context.paths.ccbd_socket_path),
            owner_uid=1000,
            boot_id='boot-id',
            started_at='2026-04-02T00:00:00Z',
            last_heartbeat_at='2026-04-02T00:00:00Z',
            mount_state=mount_state,
            generation=generation,
            config_signature=config_signature,
            daemon_instance_id=daemon_instance_id,
        )
    return LeaseInspection(
        lease=lease,
        health=health,
        pid_alive=pid_alive,
        socket_connectable=socket_connectable,
        heartbeat_fresh=heartbeat_fresh,
        takeover_allowed=health in {LeaseHealth.MISSING, LeaseHealth.UNMOUNTED, LeaseHealth.STALE},
        reason=reason,
    )


def _repeat_last_inspection(inspections):
    items = tuple(inspections)
    assert items
    iterator = iter(items)
    last = items[-1]

    def _inspect(context):
        del context
        try:
            current = next(iterator)
        except StopIteration:
            current = last
        return None, None, current

    return _inspect


def _ownership_guard_stub(inspect):
    return SimpleNamespace(inspect=inspect, startup_lock=nullcontext)


class _TrackingOwnershipGuard:
    def __init__(self, inspect, *, on_enter=None) -> None:
        self._inspect = inspect
        self._on_enter = on_enter
        self.active = False
        self.entries = 0

    def inspect(self):
        return self._inspect()

    @contextmanager
    def startup_lock(self):
        assert self.active is False
        self.active = True
        self.entries += 1
        try:
            if self._on_enter is not None:
                self._on_enter()
            yield
        finally:
            self.active = False


def test_keeper_state_store_roundtrip(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-state'
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex\n')
    layout = PathLayout(project_root)
    state = KeeperState(
        project_id='project-1',
        keeper_pid=555,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
        restart_count=2,
        last_restart_at='2026-04-02T00:00:10Z',
        last_failure_reason='socket_unreachable',
    )

    KeeperStateStore(layout).save(state)
    loaded = KeeperStateStore(layout).load()

    assert loaded == state


def test_keeper_state_store_debounces_last_check_only_writes(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-state-debounce'
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex\n')
    layout = PathLayout(project_root)
    store = KeeperStateStore(layout)
    state = KeeperState(
        project_id='project-1',
        keeper_pid=555,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    store.save(state)
    store.save(state.with_check('2026-04-02T00:00:01Z'))
    assert KeeperStateStore(layout).load().last_check_at == '2026-04-02T00:00:00Z'

    store.save(state.with_check('2026-04-02T00:00:05Z'))
    assert KeeperStateStore(layout).load().last_check_at == '2026-04-02T00:00:05Z'


def test_project_keeper_spawns_missing_daemon(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-missing'
    ctx = _context(project_root, 'agent1:codex\n')
    spawn_calls: list[dict] = []
    keeper = ProjectKeeper(
        project_root,
        pid=777,
        spawn_ccbd_process_fn=lambda **kwargs: spawn_calls.append(dict(kwargs)),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=777,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=777,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert len(spawn_calls) == 1
    assert spawn_calls[0]['project_root'] == project_root
    assert spawn_calls[0]['keeper_pid'] == 777
    assert len(str(spawn_calls[0]['expected_startup_id'])) == 32
    assert spawn_calls[0]['expected_generation'] == 1
    assert int(spawn_calls[0]['keeper_startup_accepted_perf_counter_ns']) > 0
    assert next_state.restart_count == 1
    assert next_state.last_failure_reason is None


def test_keeper_reloads_missing_lifecycle_after_acquiring_startup_lock(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-lifecycle-create-race'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=778)
    store = CcbdLifecycleStore(keeper.paths)
    stale_inspection = _inspection(
        ctx,
        health=LeaseHealth.MISSING,
        socket_connectable=False,
        pid_alive=False,
        heartbeat_fresh=False,
        reason='lease_missing',
    )
    injected = False

    def _inject_running_intent() -> None:
        nonlocal injected
        if injected:
            return
        injected = True
        store.save(
            build_lifecycle(
                project_id=ctx.project.project_id,
                occurred_at='2026-07-17T00:00:00Z',
                desired_state='running',
                phase='unmounted',
                generation=0,
                socket_path=ctx.paths.ccbd_socket_path,
            )
        )

    guard = _TrackingOwnershipGuard(lambda: stale_inspection, on_enter=_inject_running_intent)
    keeper._ownership_guard = guard

    lifecycle = keeper_loop.ensure_project_lifecycle(
        keeper,
        inspection=stale_inspection,
        now='2026-07-17T00:00:00Z',
    )

    assert guard.entries == 1
    assert lifecycle.desired_state == 'running'
    assert lifecycle.phase == 'unmounted'
    assert lifecycle.keeper_pid == 778
    assert store.load() == lifecycle


def test_keeper_releases_startup_lock_before_spawn_and_preserves_child_mounted_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-spawn-lock-boundary'
    ctx = _context(project_root, 'agent1:codex\n')
    store = CcbdLifecycleStore(PathLayout(project_root))
    child_records = []
    keeper = None

    events: list[str] = []

    def _sample_accepted_ns() -> int:
        assert guard.active is True
        starting = store.load()
        assert starting is not None and starting.phase == 'starting'
        events.append('sample_after_starting_save')
        return 1234567

    def _spawn(**kwargs) -> None:
        assert keeper is not None
        assert guard.active is False
        assert kwargs['keeper_startup_accepted_perf_counter_ns'] == 1234567
        events.append('spawn')
        starting = store.load()
        assert starting is not None
        assert starting.phase == 'starting'
        assert starting.control_plane_endpoint is None
        child_mounted = starting.with_phase(
            'mounted',
            occurred_at='2026-07-17T00:00:02Z',
            owner_pid=1234,
            owner_daemon_instance_id='child-daemon',
            namespace_epoch=7,
            startup_stage='mounted',
            last_progress_at='2026-07-17T00:00:02Z',
            startup_deadline_at=None,
        )
        store.save(child_mounted)
        child_records.append(child_mounted)

    keeper = ProjectKeeper(project_root, pid=779, spawn_ccbd_process_fn=_spawn)
    monkeypatch.setattr(keeper_module.time, 'perf_counter_ns', _sample_accepted_ns)
    inspection = _inspection(
        ctx,
        health=LeaseHealth.MISSING,
        socket_connectable=False,
        pid_alive=False,
        heartbeat_fresh=False,
        reason='lease_missing',
    )
    guard = _TrackingOwnershipGuard(lambda: inspection)
    keeper._ownership_guard = guard
    store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=779,
            socket_path=ctx.paths.ccbd_socket_path,
            control_plane_endpoint={
                'kind': 'unix_socket',
                'address': str(ctx.paths.ccbd_socket_path),
                'display': str(ctx.paths.ccbd_socket_path),
                'legacy_socket_path': str(ctx.paths.ccbd_socket_path),
            },
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=779,
        started_at='2026-07-17T00:00:00Z',
        last_check_at='2026-07-17T00:00:00Z',
        state='running',
    )

    next_state = keeper._spawn_daemon(state=state, start_timeout_s=1.0)

    assert next_state.last_failure_reason is None
    assert guard.entries == 2
    assert len(child_records) == 1
    assert store.load() == child_records[0]
    assert events == ['sample_after_starting_save', 'spawn']


def test_keeper_success_does_not_overwrite_superseding_startup_transaction(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-superseding-startup'
    ctx = _context(project_root, 'agent1:codex\n')
    store = CcbdLifecycleStore(PathLayout(project_root))
    superseding_records = []

    def _spawn(**_kwargs) -> None:
        current = store.load()
        assert current is not None
        superseding = current.with_phase(
            'starting',
            occurred_at='2026-07-17T00:00:03Z',
            generation=current.generation + 1,
            startup_id='newer-startup-id',
            startup_stage='spawn_requested',
            last_progress_at='2026-07-17T00:00:03Z',
        )
        store.save(superseding)
        superseding_records.append(superseding)

    keeper = ProjectKeeper(project_root, pid=780, spawn_ccbd_process_fn=_spawn)
    inspection = _inspection(
        ctx,
        health=LeaseHealth.MISSING,
        socket_connectable=False,
        pid_alive=False,
        heartbeat_fresh=False,
        reason='lease_missing',
    )
    keeper._ownership_guard = _TrackingOwnershipGuard(lambda: inspection)
    store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=780,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=780,
        started_at='2026-07-17T00:00:00Z',
        last_check_at='2026-07-17T00:00:00Z',
        state='running',
    )

    next_state = keeper._spawn_daemon(state=state, start_timeout_s=1.0)

    assert next_state.last_failure_reason is None
    assert store.load() == superseding_records[0]


def test_keeper_failure_does_not_overwrite_concurrent_stop_intent(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-stop-wins'
    ctx = _context(project_root, 'agent1:codex\n')
    store = CcbdLifecycleStore(PathLayout(project_root))
    stopping_records = []

    def _spawn(**_kwargs) -> None:
        current = store.load()
        assert current is not None
        stopping = current.with_phase(
            'stopping',
            occurred_at='2026-07-17T00:00:04Z',
            desired_state='stopped',
            shutdown_intent='kill',
        )
        store.save(stopping)
        stopping_records.append(stopping)
        raise RuntimeError('spawn failed after stop won')

    keeper = ProjectKeeper(project_root, pid=781, spawn_ccbd_process_fn=_spawn)
    inspection = _inspection(
        ctx,
        health=LeaseHealth.MISSING,
        socket_connectable=False,
        pid_alive=False,
        heartbeat_fresh=False,
        reason='lease_missing',
    )
    keeper._ownership_guard = _TrackingOwnershipGuard(lambda: inspection)
    store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=781,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=781,
        started_at='2026-07-17T00:00:00Z',
        last_check_at='2026-07-17T00:00:00Z',
        state='running',
    )

    next_state = keeper._spawn_daemon(state=state, start_timeout_s=1.0)

    assert next_state.last_failure_reason == 'spawn failed after stop won'
    assert store.load() == stopping_records[0]


def test_project_keeper_does_not_restart_degraded_unreachable_daemon_with_fresh_heartbeat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-crash'
    ctx = _context(project_root, 'agent1:codex\n')
    spawn_calls: list[dict] = []
    terminated: list[int] = []
    keeper = ProjectKeeper(
        project_root,
        pid=888,
        process_exists_fn=lambda pid: pid == 321,
        spawn_ccbd_process_fn=lambda **kwargs: spawn_calls.append(dict(kwargs)),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.DEGRADED,
            socket_connectable=False,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='socket_unreachable',
        )
    )
    monkeypatch.setattr(
        keeper_module,
        'terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=888,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert next_state == state
    assert terminated == []
    assert spawn_calls == []


def test_project_keeper_restarts_stale_unreachable_daemon(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-stale'
    ctx = _context(project_root, 'agent1:codex\n')
    spawn_calls: list[dict] = []
    terminated: list[int] = []
    keeper = ProjectKeeper(
        project_root,
        pid=889,
        process_exists_fn=lambda pid: pid == 321,
        spawn_ccbd_process_fn=lambda **kwargs: spawn_calls.append(dict(kwargs)),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.STALE,
            socket_connectable=False,
            pid_alive=True,
            heartbeat_fresh=False,
            reason='heartbeat_stale,socket_unreachable',
        )
    )
    monkeypatch.setattr(
        keeper_module,
        'terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=889,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert terminated == [321]
    assert len(spawn_calls) == 1
    assert next_state.restart_count == 1
    assert next_state.last_failure_reason is None


def test_project_keeper_suppresses_restart_on_resource_exhaustion(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-resource-exhausted'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(
        project_root,
        pid=890,
        spawn_ccbd_process_fn=lambda **kwargs: (_ for _ in ()).throw(
            OSError(errno.EAGAIN, 'Resource temporarily unavailable')
        ),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=890,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=890,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = CcbdLifecycleStore(keeper.paths).load()

    assert next_state.state == 'failed'
    assert next_state.restart_count == 1
    assert next_state.last_failure_reason is not None
    assert next_state.last_failure_reason.startswith(
        f'{KEEPER_RESTART_SUPPRESSED_PREFIX}:resource_exhausted:'
    )
    assert lifecycle is not None
    assert lifecycle.phase == 'failed'
    assert lifecycle.desired_state == 'stopped'
    assert lifecycle.last_failure_reason == next_state.last_failure_reason


def test_project_keeper_suppresses_restart_after_repeated_start_failures(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-start-crash-loop'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(
        project_root,
        pid=891,
        spawn_ccbd_process_fn=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('boot loop')),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=891,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=891,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
        restart_count=KEEPER_START_FAILURE_SUPPRESS_AFTER - 1,
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = CcbdLifecycleStore(keeper.paths).load()

    assert next_state.state == 'failed'
    assert next_state.restart_count == KEEPER_START_FAILURE_SUPPRESS_AFTER
    assert next_state.last_failure_reason is not None
    assert next_state.last_failure_reason.startswith(
        f'{KEEPER_RESTART_SUPPRESSED_PREFIX}:max_start_failures:'
    )
    assert lifecycle is not None
    assert lifecycle.phase == 'failed'
    assert lifecycle.desired_state == 'stopped'
    assert lifecycle.last_failure_reason == next_state.last_failure_reason


def test_project_keeper_suppression_records_lifecycle_before_starting_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-config-crash-loop'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(
        project_root,
        pid=892,
        spawn_ccbd_process_fn=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError('spawn should not run')
        ),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=892,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    monkeypatch.setattr(
        keeper_module,
        'load_project_config',
        lambda _root: (_ for _ in ()).throw(RuntimeError('config boom')),
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=892,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
        restart_count=KEEPER_START_FAILURE_SUPPRESS_AFTER - 1,
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = CcbdLifecycleStore(keeper.paths).load()

    assert next_state.state == 'failed'
    assert next_state.last_failure_reason is not None
    assert next_state.last_failure_reason.startswith(
        f'{KEEPER_RESTART_SUPPRESSED_PREFIX}:max_start_failures:'
    )
    assert lifecycle is not None
    assert lifecycle.phase == 'failed'
    assert lifecycle.desired_state == 'stopped'
    assert lifecycle.last_failure_reason == next_state.last_failure_reason


def test_project_keeper_run_forever_exits_after_restart_suppression(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-resource-exhausted-loop'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(
        project_root,
        pid=892,
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError('keeper should exit')),
        spawn_ccbd_process_fn=lambda **kwargs: (_ for _ in ()).throw(
            OSError(errno.EAGAIN, 'Resource temporarily unavailable')
        ),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=892,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )

    code = keeper.run_forever(poll_interval=0.1, start_timeout_s=0.1)
    state = KeeperStateStore(keeper.paths).load()

    assert code == 0
    assert state is not None
    assert state.state == 'failed'
    assert state.last_failure_reason is not None
    assert state.last_failure_reason.startswith(
        f'{KEEPER_RESTART_SUPPRESSED_PREFIX}:resource_exhausted:'
    )


def test_project_keeper_preserves_namespace_epoch_when_confirming_mounted_daemon(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-mounted-namespace'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=890)
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='healthy',
        )
    )
    ProjectNamespaceStateStore(keeper.paths).save(
        ProjectNamespaceState(
            project_id=ctx.project.project_id,
            namespace_epoch=6,
            tmux_socket_path=str(ctx.paths.ccbd_tmux_socket_path),
            tmux_session_name=ctx.paths.ccbd_tmux_session_name,
            layout_version=3,
            control_window_name='__ccb_ctl',
            control_window_id='@0',
            workspace_window_name='ccb',
            workspace_window_id='@1',
            workspace_epoch=1,
            ui_attachable=True,
            last_started_at='2026-04-22T00:00:00Z',
        )
    )
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    lifecycle_store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-22T00:00:00Z',
            desired_state='running',
            phase='starting',
            generation=1,
            keeper_pid=890,
            socket_path=ctx.paths.ccbd_socket_path,
            namespace_epoch=None,
        )
    )
    monkeypatch.setattr('ccbd.keeper_runtime.loop.daemon_matches_project_config', lambda app: True)
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=890,
        started_at='2026-04-22T00:00:00Z',
        last_check_at='2026-04-22T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = lifecycle_store.load()

    assert next_state.last_failure_reason is None
    assert lifecycle is not None
    assert lifecycle.phase == 'mounted'
    assert lifecycle.namespace_epoch == 6


def test_project_keeper_does_not_promote_child_runtime_bootstrap_early(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-child-runtime-bootstrap'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=896)
    observed = _inspection(
        ctx,
        health=LeaseHealth.HEALTHY,
        socket_connectable=True,
        pid_alive=True,
        heartbeat_fresh=True,
        reason='healthy',
        daemon_instance_id='child-daemon',
        generation=4,
    )
    keeper._ownership_guard = _ownership_guard_stub(inspect=lambda: observed)
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    runtime_bootstrap = build_lifecycle(
        project_id=ctx.project.project_id,
        occurred_at='2026-07-17T00:00:00Z',
        desired_state='running',
        phase='starting',
        generation=4,
        startup_id='a' * 32,
        startup_stage='runtime_bootstrap',
        keeper_pid=896,
        owner_pid=321,
        owner_daemon_instance_id='child-daemon',
        config_signature=observed.lease.config_signature,
        socket_path=ctx.paths.ccbd_socket_path,
    )
    lifecycle_store.save(runtime_bootstrap)
    monkeypatch.setattr(
        'ccbd.keeper_runtime.loop.daemon_matches_project_config',
        lambda app: (_ for _ in ()).throw(AssertionError('keeper must not probe/promote child bootstrap')),
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=896,
        started_at='2026-07-17T00:00:00Z',
        last_check_at='2026-07-17T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert lifecycle_store.load() == runtime_bootstrap
    assert next_state.last_failure_reason is None


def test_project_keeper_does_not_let_stale_child_stage_mask_replacement_lease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-stale-child-replacement'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=897)
    observed = _inspection(
        ctx,
        health=LeaseHealth.HEALTHY,
        socket_connectable=True,
        pid_alive=True,
        heartbeat_fresh=True,
        reason='healthy',
        daemon_instance_id='replacement-daemon',
        generation=5,
    )
    keeper._ownership_guard = _ownership_guard_stub(inspect=lambda: observed)
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    lifecycle_store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='starting',
            generation=4,
            startup_id='a' * 32,
            startup_stage='runtime_bootstrap',
            keeper_pid=897,
            owner_pid=321,
            owner_daemon_instance_id='old-child',
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    monkeypatch.setattr('ccbd.keeper_runtime.loop.daemon_matches_project_config', lambda app: True)
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=897,
        started_at='2026-07-17T00:00:00Z',
        last_check_at='2026-07-17T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    lifecycle = lifecycle_store.load()
    assert lifecycle is not None
    assert lifecycle.phase == 'mounted'
    assert lifecycle.startup_stage == 'mounted'
    assert lifecycle.generation == 5
    assert lifecycle.startup_id is None
    assert lifecycle.owner_pid == 321
    assert lifecycle.owner_daemon_instance_id == 'replacement-daemon'
    assert next_state.last_failure_reason is None


def test_project_keeper_keeps_mounted_phase_when_config_check_times_out(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-mounted-config-check-timeout'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=891)
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='healthy',
        )
    )
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    lifecycle_store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-22T00:00:00Z',
            desired_state='running',
            phase='mounted',
            generation=1,
            keeper_pid=891,
            owner_pid=321,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    monkeypatch.setattr(
        'ccbd.keeper_runtime.loop.daemon_matches_project_config',
        lambda app: (_ for _ in ()).throw(TimeoutError('ping timeout')),
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=891,
        started_at='2026-04-22T00:00:00Z',
        last_check_at='2026-04-22T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = lifecycle_store.load()

    assert next_state.last_failure_reason == 'config_check_failed:ping timeout'
    assert lifecycle is not None
    assert lifecycle.phase == 'mounted'
    assert lifecycle.desired_state == 'running'
    assert lifecycle.last_failure_reason == 'config_check_failed:ping timeout'


def test_project_keeper_stale_match_observation_cannot_overwrite_concurrent_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-mounted-concurrent-stop'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=893)
    observed = _inspection(
        ctx,
        health=LeaseHealth.HEALTHY,
        socket_connectable=True,
        pid_alive=True,
        heartbeat_fresh=True,
        reason='healthy',
    )
    keeper._ownership_guard = _ownership_guard_stub(inspect=lambda: observed)
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    starting = build_lifecycle(
        project_id=ctx.project.project_id,
        occurred_at='2026-04-22T00:00:00Z',
        desired_state='running',
        phase='starting',
        generation=1,
        startup_id='startup-1',
        keeper_pid=893,
        socket_path=ctx.paths.ccbd_socket_path,
    )
    lifecycle_store.save(starting)
    stopped = starting.with_phase(
        'stopping',
        occurred_at='2026-04-22T00:00:01Z',
        desired_state='stopped',
        shutdown_intent='kill',
    )

    def stop_during_probe(app) -> bool:
        del app
        lifecycle_store.save(stopped)
        return True

    monkeypatch.setattr('ccbd.keeper_runtime.loop.daemon_matches_project_config', stop_during_probe)
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=893,
        started_at='2026-04-22T00:00:00Z',
        last_check_at='2026-04-22T00:00:00Z',
        state='running',
    )

    keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert lifecycle_store.load() == stopped


def test_project_keeper_stale_probe_failure_cannot_overwrite_concurrent_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-failed-probe-concurrent-stop'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=894)
    observed = _inspection(
        ctx,
        health=LeaseHealth.HEALTHY,
        socket_connectable=True,
        pid_alive=True,
        heartbeat_fresh=True,
        reason='healthy',
    )
    keeper._ownership_guard = _ownership_guard_stub(inspect=lambda: observed)
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    mounted = build_lifecycle(
        project_id=ctx.project.project_id,
        occurred_at='2026-04-22T00:00:00Z',
        desired_state='running',
        phase='mounted',
        generation=1,
        keeper_pid=894,
        owner_pid=321,
        socket_path=ctx.paths.ccbd_socket_path,
    )
    lifecycle_store.save(mounted)
    stopped = mounted.with_phase(
        'stopping',
        occurred_at='2026-04-22T00:00:01Z',
        desired_state='stopped',
        shutdown_intent='kill',
    )

    def fail_after_stop(app):
        del app
        lifecycle_store.save(stopped)
        raise TimeoutError('ping timeout')

    monkeypatch.setattr('ccbd.keeper_runtime.loop.daemon_matches_project_config', fail_after_stop)
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=894,
        started_at='2026-04-22T00:00:00Z',
        last_check_at='2026-04-22T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    assert next_state.last_failure_reason == 'config_check_failed:ping timeout'
    assert lifecycle_store.load() == stopped


def test_project_keeper_does_not_rewrite_stable_mounted_lifecycle(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-mounted-stable'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(project_root, pid=892)
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='healthy',
        )
    )
    lifecycle_store = CcbdLifecycleStore(keeper.paths)
    lifecycle_store.save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-22T00:00:00Z',
            desired_state='running',
            phase='mounted',
            generation=1,
            keeper_pid=892,
            owner_pid=321,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    monkeypatch.setattr('ccbd.keeper_runtime.loop.daemon_matches_project_config', lambda app: True)
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=892,
        started_at='2026-04-22T00:00:00Z',
        last_check_at='2026-04-22T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)
    lifecycle = lifecycle_store.load()

    assert next_state.last_failure_reason is None
    assert lifecycle.phase == 'mounted'
    assert lifecycle.phase_started_at == '2026-04-22T00:00:00Z'


def test_project_keeper_config_probe_uses_shared_control_plane_timeout(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-keeper-probe-timeout'
    ctx = _context(project_root, 'agent1:codex\n')
    expected = project_config_identity_payload(load_project_config(project_root).config)
    captured: list[float | None] = []

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            assert socket_path == ctx.paths.ccbd_socket_path
            captured.append(timeout_s)

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {'config_signature': expected['config_signature']}

        def stop_all(self, *, force: bool = False) -> dict[str, object]:
            assert force is False
            return {'ok': True}

    keeper = ProjectKeeper(project_root, pid=892)
    monkeypatch.setattr(keeper_loop, 'CcbdClient', _FakeClient)

    assert keeper_loop.daemon_matches_project_config(keeper) is True
    keeper_loop.request_shutdown(keeper)

    assert captured == [
        keeper_loop.CONTROL_PLANE_RPC_TIMEOUT_S,
        keeper_loop.CONTROL_PLANE_RPC_TIMEOUT_S,
    ]


def test_project_keeper_accepts_bounded_reload_handoff_signature_window(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-keeper-reload-handoff'
    ctx = _context(project_root, 'agent1:codex\n')
    old_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex, agent2:claude\n')
    new_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    keeper = ProjectKeeper(project_root, pid=893, clock=lambda: '2026-05-29T00:00:20Z')
    inspection = _inspection(
        ctx,
        health=LeaseHealth.HEALTHY,
        socket_connectable=True,
        pid_alive=True,
        heartbeat_fresh=True,
        reason='healthy',
        config_signature=old_signature,
        daemon_instance_id='daemon-1',
        generation=1,
    )
    keeper._ownership_guard = _ownership_guard_stub(lambda: inspection)
    ReloadHandoffStore(keeper.paths).save(
        ReloadHandoff(
            project_id=ctx.project.project_id,
            started_at='2026-05-29T00:00:00Z',
            old_config_signature=old_signature,
            target_config_signature=new_signature,
            daemon_pid=321,
            daemon_instance_id='daemon-1',
            generation=1,
        )
    )

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            assert socket_path == ctx.paths.ccbd_socket_path
            assert timeout_s == keeper_loop.CONTROL_PLANE_RPC_TIMEOUT_S

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {'config_signature': old_signature}

    monkeypatch.setattr(keeper_loop, 'CcbdClient', _FakeClient)

    assert keeper_loop.daemon_matches_project_config(keeper) is True


def test_project_keeper_tolerates_config_drift_after_expired_reload_handoff(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-keeper-reload-handoff-expired'
    ctx = _context(project_root, 'agent1:codex\n')
    old_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex, agent2:claude\n')
    new_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    keeper = ProjectKeeper(project_root, pid=894, clock=lambda: '2026-05-29T00:02:00Z')
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='healthy',
            config_signature=old_signature,
            daemon_instance_id='daemon-1',
            generation=1,
        )
    )
    ReloadHandoffStore(keeper.paths).save(
        ReloadHandoff(
            project_id=ctx.project.project_id,
            started_at='2026-05-29T00:00:00Z',
            old_config_signature=old_signature,
            target_config_signature=new_signature,
            daemon_pid=321,
            daemon_instance_id='daemon-1',
            generation=1,
        )
    )

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            del socket_path, timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {'config_signature': old_signature}

    monkeypatch.setattr(keeper_loop, 'CcbdClient', _FakeClient)

    assert reload_handoff_allows_signature_mismatch(
        keeper,
        expected_config_signature=new_signature,
        actual_config_signature=old_signature,
    ) is False
    assert keeper_loop.daemon_matches_project_config(keeper) is True


def test_project_keeper_tolerates_config_drift_with_wrong_holder_handoff(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-keeper-reload-handoff-holder'
    ctx = _context(project_root, 'agent1:codex\n')
    old_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    _write(project_root / '.ccb' / 'ccb.config', 'agent1:codex, agent2:claude\n')
    new_signature = project_config_identity_payload(load_project_config(project_root).config)['config_signature']
    keeper = ProjectKeeper(project_root, pid=895, clock=lambda: '2026-05-29T00:00:20Z')
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            pid_alive=True,
            heartbeat_fresh=True,
            reason='healthy',
            config_signature=old_signature,
            daemon_instance_id='daemon-2',
            generation=1,
        )
    )
    ReloadHandoffStore(keeper.paths).save(
        ReloadHandoff(
            project_id=ctx.project.project_id,
            started_at='2026-05-29T00:00:00Z',
            old_config_signature=old_signature,
            target_config_signature=new_signature,
            daemon_pid=321,
            daemon_instance_id='daemon-1',
            generation=1,
        )
    )

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            del socket_path, timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {'config_signature': old_signature}

    monkeypatch.setattr(keeper_loop, 'CcbdClient', _FakeClient)

    assert reload_handoff_allows_signature_mismatch(
        keeper,
        expected_config_signature=new_signature,
        actual_config_signature=old_signature,
    ) is False
    assert keeper_loop.daemon_matches_project_config(keeper) is True


def test_project_keeper_stops_when_shutdown_intent_exists(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-stop'
    ctx = _context(project_root, 'agent1:codex\n')
    layout = PathLayout(project_root)
    ShutdownIntentStore(layout).save(
        ShutdownIntent(
            project_id=ctx.project.project_id,
            requested_at='2026-04-02T00:00:00Z',
            requested_by_pid=1,
            reason='kill',
        )
    )
    keeper = ProjectKeeper(
        project_root,
        pid=999,
        sleep_fn=lambda _seconds: (_ for _ in ()).throw(AssertionError('keeper should not sleep')),
        spawn_ccbd_process_fn=lambda **kwargs: (_ for _ in ()).throw(AssertionError('keeper should not spawn')),
    )

    code = keeper.run_forever(poll_interval=0.1, start_timeout_s=0.1)
    state = KeeperStateStore(layout).load()

    assert code == 0
    assert state is not None
    assert state.state == 'stopped'


def test_project_keeper_uses_builtin_default_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-missing-config'
    monkeypatch.setenv('HOME', str(tmp_path / 'empty-home'))
    _context(project_root, 'agent1:codex\n')
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.unlink()
    ctx = CliContext(
        command=ParsedStartCommand(project=None, agent_names=(), restore=False, auto_permission=False),
        cwd=project_root,
        project=bootstrap_project(project_root),
        paths=PathLayout(project_root),
    )
    spawn_calls: list[dict] = []

    keeper = ProjectKeeper(
        project_root,
        pid=1001,
        spawn_ccbd_process_fn=lambda **kwargs: spawn_calls.append(dict(kwargs)),
    )
    keeper._ownership_guard = _ownership_guard_stub(
        inspect=lambda: _inspection(
            ctx,
            health=LeaseHealth.MISSING,
            socket_connectable=False,
            pid_alive=False,
            heartbeat_fresh=False,
            reason='lease_missing',
        )
    )
    CcbdLifecycleStore(keeper.paths).save(
        build_lifecycle(
            project_id=ctx.project.project_id,
            occurred_at='2026-04-02T00:00:00Z',
            desired_state='running',
            phase='unmounted',
            generation=0,
            keeper_pid=1001,
            socket_path=ctx.paths.ccbd_socket_path,
        )
    )
    state = KeeperState(
        project_id=ctx.project.project_id,
        keeper_pid=1001,
        started_at='2026-04-02T00:00:00Z',
        last_check_at='2026-04-02T00:00:00Z',
        state='running',
    )

    next_state = keeper._reconcile_once(state=state, start_timeout_s=0.1)

    loaded_config = load_project_config(project_root)
    assert loaded_config.source_path is None
    assert loaded_config.source_kind == 'builtin_default'
    assert loaded_config.used_default is True
    assert (project_root / '.ccb' / 'ccb.config').exists() is False
    assert len(spawn_calls) == 1
    assert spawn_calls[0]['project_root'] == project_root
    assert spawn_calls[0]['keeper_pid'] == 1001
    assert next_state.restart_count == 1
    assert next_state.last_failure_reason is None


def test_reap_child_processes_drains_exited_children() -> None:
    seen: list[tuple[int, int]] = []
    responses = iter(((321, 0), (654, 0), (0, 0)))
    original = keeper_module._reap_child_processes

    reaped = original(waitpid_fn=lambda pid, flags: seen.append((pid, flags)) or next(responses))

    assert reaped == (321, 654)
    assert seen == [(-1, keeper_module.os.WNOHANG)] * 3


def test_ensure_daemon_started_waits_for_keeper_started_backend(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-keeper-start'
    ctx = _context(project_root, 'agent1:codex\n')
    expected = project_config_identity_payload(load_project_config(project_root).config)
    inspections = iter(
        [
            _inspection(
                ctx,
                health=LeaseHealth.MISSING,
                socket_connectable=False,
                pid_alive=False,
                heartbeat_fresh=False,
                reason='lease_missing',
            ),
            _inspection(
                ctx,
                health=LeaseHealth.MISSING,
                socket_connectable=False,
                pid_alive=False,
                heartbeat_fresh=False,
                reason='lease_missing',
            ),
            _inspection(
                ctx,
                health=LeaseHealth.HEALTHY,
                socket_connectable=True,
                pid_alive=True,
                heartbeat_fresh=True,
                reason='healthy',
            ),
        ]
    )
    running_intents: list[str] = []

    class FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            del socket_path, timeout_s

        def ping(self, target: str = 'ccbd') -> dict:
            assert target == 'ccbd'
            return {
                'known_agents': list(expected['known_agents']),
                'config_signature': expected['config_signature'],
            }

    monkeypatch.setattr(daemon_service, 'inspect_daemon', _repeat_last_inspection(inspections))
    monkeypatch.setattr(daemon_service, 'CcbdClient', FakeClient)
    monkeypatch.setattr(daemon_service, '_record_running_intent', lambda context: running_intents.append(context.project.project_id))
    monkeypatch.setattr(daemon_service, '_ensure_keeper_started', lambda context: True)

    handle = daemon_service.ensure_daemon_started(ctx)

    assert handle.started is True
    assert running_intents == [ctx.project.project_id]


def test_shutdown_daemon_records_intent_and_terminates_keeper(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-kill-keeper'
    ctx = _context(project_root, 'agent1:codex\n')
    layout = PathLayout(project_root)
    KeeperStateStore(layout).save(
        KeeperState(
            project_id=ctx.project.project_id,
            keeper_pid=654,
            started_at='2026-04-02T00:00:00Z',
            last_check_at='2026-04-02T00:00:00Z',
            state='running',
        )
    )
    lease = SimpleNamespace(
        mount_state=SimpleNamespace(value='unmounted'),
        ccbd_pid=0,
        keeper_pid=None,
    )
    manager = SimpleNamespace(
        mark_unmounted=lambda **kwargs: lease,
        load_state=lambda: lease,
    )
    inspection = SimpleNamespace(
        socket_connectable=False,
        pid_alive=False,
        lease=lease,
    )
    terminated: list[int] = []

    monkeypatch.setattr(daemon_service, 'inspect_daemon', lambda context: (manager, None, inspection))
    monkeypatch.setattr(daemon_service, '_wait_for_keeper_exit', lambda context, timeout_s: False)
    monkeypatch.setattr('cli.services.daemon.is_pid_alive', lambda pid: pid == 654)
    monkeypatch.setattr(
        'cli.services.daemon.terminate_pid_tree',
        lambda pid, timeout_s, is_pid_alive_fn: terminated.append(pid) or True,
    )

    summary = daemon_service.shutdown_daemon(ctx, force=False)
    intent = ShutdownIntentStore(layout).load()
    lifecycle = CcbdLifecycleStore(layout).load()

    assert summary.state == 'unmounted'
    assert terminated == [654]
    assert intent is not None
    assert intent.reason == 'kill'
    assert lifecycle is not None
    assert lifecycle.desired_state == 'stopped'
    assert lifecycle.phase == 'unmounted'


def test_keeper_reconciles_moved_project_identity_before_startup_fence(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'repo-moved-runtime'
    ctx = _context(project_root, 'agent1:codex\n')
    keeper = ProjectKeeper(
        project_root,
        pid=432,
        clock=lambda: '2026-07-24T00:02:00Z',
    )
    foreign_project_id = 'f' * 64
    keeper._mount_manager.mark_mounted(
        project_id=foreign_project_id,
        pid=999999,
        socket_path=project_root / '.ccb' / 'ccbd' / 'old.sock',
        generation=8,
        started_at='2026-07-24T00:00:00Z',
        keeper_pid=999998,
        daemon_instance_id='old-daemon',
    )
    keeper._lifecycle_store.save(
        build_lifecycle(
            project_id=foreign_project_id,
            occurred_at='2026-07-24T00:00:00Z',
            desired_state='running',
            phase='failed',
            generation=8,
            keeper_pid=432,
            socket_path=project_root / '.ccb' / 'ccbd' / 'old.sock',
        )
    )

    inspection = keeper._ownership_guard.inspect()
    lifecycle = keeper_loop.ensure_project_lifecycle(
        keeper,
        inspection=inspection,
        now='2026-07-24T00:02:00Z',
    )
    lease = keeper._mount_manager.load_state()

    assert lifecycle.project_id == ctx.project.project_id
    assert lifecycle.desired_state == 'running'
    assert lifecycle.phase == 'unmounted'
    assert lifecycle.keeper_pid == 432
    assert lifecycle.socket_path == str(ctx.paths.ccbd_socket_path)
    assert lease is not None
    assert lease.project_id == foreign_project_id
    assert lease.mount_state is MountState.UNMOUNTED
