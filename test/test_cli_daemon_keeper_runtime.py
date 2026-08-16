from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

from ccbd.keeper import KeeperState, KeeperStateStore
from ccbd.services.lifecycle import CcbdLifecycleStore, build_lifecycle
from ccbd.services.mount import MountManager
from ccbd.services.ownership import OwnershipGuard
from cli.services.daemon_runtime import keeper as keeper_runtime
from storage.paths import PathLayout


class _NoopStartupLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _runtime_context(project_root: Path):
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('agent1:codex\n', encoding='utf-8')
    paths = PathLayout(project_root)
    return SimpleNamespace(
        project=SimpleNamespace(project_id=paths.project_id, project_root=project_root),
        paths=paths,
    )


def _record_running_intent_child(project_root: str, started, finished, results) -> None:
    started.set()
    try:
        results.put(keeper_runtime.record_running_intent(_runtime_context(Path(project_root))))
    finally:
        finished.set()


def _record_shutdown_intent_child(project_root: str, started, finished) -> None:
    started.set()
    try:
        keeper_runtime.record_shutdown_intent(
            _runtime_context(Path(project_root)),
            reason='kill',
        )
    finally:
        finished.set()


def test_spawn_keeper_process_uses_lib_root_keeper_main(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo'
    paths = PathLayout(project_root)
    context = SimpleNamespace(
        project=SimpleNamespace(project_root=project_root),
        paths=paths,
    )
    popen_calls: list[dict[str, object]] = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            popen_calls.append({'cmd': cmd, **kwargs})

    monkeypatch.setattr(keeper_runtime.subprocess, 'Popen', _FakePopen)

    keeper_runtime.spawn_keeper_process(context)

    assert len(popen_calls) == 1
    call = popen_calls[0]
    expected_script = Path(keeper_runtime.__file__).resolve().parents[3] / 'ccbd' / 'keeper_main.py'
    assert call['cmd'][1] == str(expected_script)
    assert str(expected_script.parent.parent) in str(call['env']['PYTHONPATH'])
    assert call['start_new_session'] is True
    if os.name == 'nt':
        assert call['creationflags'] & getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
        assert call['creationflags'] & getattr(subprocess, 'DETACHED_PROCESS', 0x00000008)


def test_ensure_keeper_started_replaces_state_for_unrelated_live_pid(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    paths = PathLayout(project_root)
    context = SimpleNamespace(
        project=SimpleNamespace(project_id='project-1', project_root=project_root),
        paths=paths,
    )
    KeeperStateStore(paths).save(
        KeeperState(
            project_id='project-1',
            keeper_pid=28,
            started_at='2026-05-23T00:00:00Z',
            last_check_at='2026-05-23T00:00:00Z',
            state='running',
        )
    )
    spawn_calls: list[object] = []

    def _spawn(ctx) -> None:
        spawn_calls.append(ctx)
        KeeperStateStore(paths).save(
            KeeperState(
                project_id='project-1',
                keeper_pid=777,
                started_at='2026-05-23T00:00:01Z',
                last_check_at='2026-05-23T00:00:01Z',
                state='running',
            )
        )

    assert keeper_runtime.ensure_keeper_started(
        context,
        mount_manager_factory=lambda _paths: object(),
        ownership_guard_factory=lambda _paths, _manager: SimpleNamespace(startup_lock=lambda: _NoopStartupLock()),
        process_exists_fn=lambda pid: pid in {28, 777},
        process_cmdline_fn=lambda pid: {
            28: ('[idle_inject/4]',),
            777: ('python3', '/repo/lib/ccbd/keeper_main.py', '--project', str(project_root)),
        }.get(pid, ()),
        spawn_keeper_process_fn=_spawn,
        ready_timeout_s=0.01,
    )

    assert spawn_calls == [context]


def test_ensure_keeper_started_reuses_matching_keeper_state(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    paths = PathLayout(project_root)
    context = SimpleNamespace(
        project=SimpleNamespace(project_id='project-1', project_root=project_root),
        paths=paths,
    )
    KeeperStateStore(paths).save(
        KeeperState(
            project_id='project-1',
            keeper_pid=777,
            started_at='2026-05-23T00:00:00Z',
            last_check_at='2026-05-23T00:00:00Z',
            state='running',
        )
    )
    spawn_calls: list[object] = []

    assert keeper_runtime.ensure_keeper_started(
        context,
        mount_manager_factory=lambda _paths: object(),
        ownership_guard_factory=lambda _paths, _manager: SimpleNamespace(startup_lock=lambda: _NoopStartupLock()),
        process_exists_fn=lambda pid: pid == 777,
        process_cmdline_fn=lambda pid: ('python3', '/repo/lib/ccbd/keeper_main.py', '--project', str(project_root)),
        spawn_keeper_process_fn=lambda ctx: spawn_calls.append(ctx),
        ready_timeout_s=0.01,
    )

    assert spawn_calls == []


def test_record_running_intent_does_not_rewrite_active_startup_transaction(tmp_path: Path) -> None:
    context = _runtime_context(tmp_path / 'repo-active-start')
    store = CcbdLifecycleStore(context.paths)
    starting = build_lifecycle(
        project_id=context.project.project_id,
        occurred_at='2026-07-17T00:00:00Z',
        desired_state='running',
        phase='starting',
        generation=4,
        startup_id='keeper-startup-4',
        startup_stage='socket_listening',
        last_progress_at='2026-07-17T00:00:01Z',
        startup_deadline_at='2026-07-17T00:01:00Z',
        keeper_pid=444,
        socket_path=context.paths.ccbd_socket_path,
    )
    store.save(starting)
    inode_before = context.paths.ccbd_lifecycle_path.stat().st_ino

    assert keeper_runtime.record_running_intent(context) is True

    assert store.load() == starting
    assert context.paths.ccbd_lifecycle_path.stat().st_ino == inode_before


def test_record_running_intent_does_not_rewrite_mounted_lifecycle(tmp_path: Path) -> None:
    context = _runtime_context(tmp_path / 'repo-mounted')
    store = CcbdLifecycleStore(context.paths)
    mounted = build_lifecycle(
        project_id=context.project.project_id,
        occurred_at='2026-07-17T00:00:00Z',
        desired_state='running',
        phase='mounted',
        generation=8,
        startup_id='keeper-startup-8',
        keeper_pid=888,
        owner_pid=999,
        config_signature='accepted-daemon-signature',
        socket_path=context.paths.ccbd_socket_path,
        last_failure_reason='preserve-observation',
        shutdown_intent='preserve-authority-field',
    )
    store.save(mounted)
    inode_before = context.paths.ccbd_lifecycle_path.stat().st_ino

    assert keeper_runtime.record_running_intent(context) is False

    assert store.load() == mounted
    assert context.paths.ccbd_lifecycle_path.stat().st_ino == inode_before


def test_record_running_intent_transitions_stopped_lifecycle(tmp_path: Path) -> None:
    context = _runtime_context(tmp_path / 'repo-stopped')
    store = CcbdLifecycleStore(context.paths)
    store.save(
        build_lifecycle(
            project_id=context.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='stopped',
            phase='unmounted',
            generation=3,
            keeper_pid=333,
            config_signature='previous-generation-signature',
            socket_path=context.paths.ccbd_socket_path,
            last_failure_reason='old-failure',
            shutdown_intent='kill',
        )
    )

    assert keeper_runtime.record_running_intent(context) is True

    current = store.load()
    assert current is not None
    assert current.desired_state == 'running'
    assert current.phase == 'unmounted'
    assert current.generation == 3
    assert current.last_failure_reason is None
    assert current.shutdown_intent is None
    assert current.config_signature == 'previous-generation-signature'


def test_stale_shutdown_finalize_does_not_cancel_new_startup(tmp_path: Path) -> None:
    context = _runtime_context(tmp_path / 'repo-stale-finalize')
    store = CcbdLifecycleStore(context.paths)
    store.save(
        build_lifecycle(
            project_id=context.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='mounted',
            generation=1,
            owner_pid=111,
            socket_path=context.paths.ccbd_socket_path,
        )
    )
    keeper_runtime.record_shutdown_intent(context, reason='kill')
    assert keeper_runtime.record_running_intent(context) is True
    starting = build_lifecycle(
        project_id=context.project.project_id,
        occurred_at='2026-07-17T00:00:02Z',
        desired_state='running',
        phase='starting',
        generation=2,
        startup_id='new-startup-2',
        startup_stage='spawn_requested',
        last_progress_at='2026-07-17T00:00:02Z',
        startup_deadline_at='2026-07-17T00:01:02Z',
        socket_path=context.paths.ccbd_socket_path,
    )
    store.save(starting)
    lifecycle_bytes = context.paths.ccbd_lifecycle_path.read_bytes()

    keeper_runtime.finalize_shutdown_lifecycle(context)

    assert store.load() == starting
    assert context.paths.ccbd_lifecycle_path.read_bytes() == lifecycle_bytes


@pytest.mark.skipif(os.name != 'posix', reason='startup flock regression requires POSIX')
def test_record_running_intent_process_waits_for_keeper_startup_commit(tmp_path: Path) -> None:
    context = _runtime_context(tmp_path / 'repo-process-race')
    store = CcbdLifecycleStore(context.paths)
    store.save(
        build_lifecycle(
            project_id=context.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='stopped',
            phase='unmounted',
            generation=0,
            socket_path=context.paths.ccbd_socket_path,
        )
    )
    mp = multiprocessing.get_context('spawn')
    started = mp.Event()
    finished = mp.Event()
    results = mp.Queue()
    process = mp.Process(
        target=_record_running_intent_child,
        args=(str(context.project.project_root), started, finished, results),
    )
    manager = MountManager(context.paths)
    guard = OwnershipGuard(context.paths, manager)
    try:
        with guard.startup_lock():
            process.start()
            assert started.wait(5.0)
            time.sleep(0.1)
            assert not finished.is_set()
            starting = build_lifecycle(
                project_id=context.project.project_id,
                occurred_at='2026-07-17T00:00:01Z',
                desired_state='running',
                phase='starting',
                generation=1,
                startup_id='keeper-startup-1',
                startup_stage='spawn_requested',
                last_progress_at='2026-07-17T00:00:01Z',
                startup_deadline_at='2026-07-17T00:01:01Z',
                keeper_pid=111,
                socket_path=context.paths.ccbd_socket_path,
            )
            store.save(starting)
        assert finished.wait(5.0)
        process.join(5.0)
        assert process.exitcode == 0
        assert results.get(timeout=1.0) is True
        assert store.load() == starting
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5.0)


@pytest.mark.skipif(os.name != 'posix', reason='startup flock regression requires POSIX')
def test_record_shutdown_intent_process_waits_and_uses_fresh_startup_transaction(
    tmp_path: Path,
) -> None:
    context = _runtime_context(tmp_path / 'repo-shutdown-process-race')
    store = CcbdLifecycleStore(context.paths)
    store.save(
        build_lifecycle(
            project_id=context.project.project_id,
            occurred_at='2026-07-17T00:00:00Z',
            desired_state='running',
            phase='mounted',
            generation=1,
            owner_pid=111,
            socket_path=context.paths.ccbd_socket_path,
        )
    )
    mp = multiprocessing.get_context('spawn')
    started = mp.Event()
    finished = mp.Event()
    process = mp.Process(
        target=_record_shutdown_intent_child,
        args=(str(context.project.project_root), started, finished),
    )
    guard = OwnershipGuard(context.paths, MountManager(context.paths))
    try:
        with guard.startup_lock():
            process.start()
            assert started.wait(5.0)
            time.sleep(0.1)
            assert not finished.is_set()
            starting = build_lifecycle(
                project_id=context.project.project_id,
                occurred_at='2026-07-17T00:00:01Z',
                desired_state='running',
                phase='starting',
                generation=2,
                startup_id='new-startup-2',
                startup_stage='spawn_requested',
                last_progress_at='2026-07-17T00:00:01Z',
                startup_deadline_at='2026-07-17T00:01:01Z',
                socket_path=context.paths.ccbd_socket_path,
            )
            store.save(starting)
        assert finished.wait(5.0)
        process.join(5.0)
        assert process.exitcode == 0
        stopped = store.load()
        assert stopped is not None
        assert stopped.desired_state == 'stopped'
        assert stopped.phase == 'stopping'
        assert stopped.generation == 2
        assert stopped.startup_id == 'new-startup-2'
        assert stopped.shutdown_intent == 'kill'
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5.0)
