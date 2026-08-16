from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import ccbd.daemon_process as ccbd_daemon_process
import ccbd.startup_policy as startup_policy
import cli.services.daemon as daemon_service
from ccbd.models import LeaseHealth
from ccbd.services.lifecycle import CcbdLifecycleStore, build_lifecycle
from cli.services.daemon_runtime.lifecycle import ensure_daemon_started as ensure_daemon_started_runtime
from cli.services.daemon_runtime.models import CcbdServiceError, DaemonHandle
from storage.paths import PathLayout


def test_lifecycle_store_roundtrip_preserves_startup_progress_fields(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-lifecycle-progress'
    layout = PathLayout(project_root)
    lifecycle = build_lifecycle(
        project_id='proj-1',
        occurred_at='2026-04-24T00:00:00Z',
        desired_state='running',
        phase='starting',
        generation=3,
        startup_id='startup-123',
        startup_stage='socket_listening',
        last_progress_at='2026-04-24T00:00:04Z',
        startup_deadline_at='2026-04-24T00:00:20Z',
        keeper_pid=111,
        socket_path=layout.ccbd_socket_path,
    )

    CcbdLifecycleStore(layout).save(lifecycle)
    loaded = CcbdLifecycleStore(layout).load()

    assert loaded == lifecycle


def test_ensure_daemon_started_can_wait_past_legacy_five_second_budget(monkeypatch) -> None:
    current = {'t': 0.0}

    def _now() -> float:
        return current['t']

    def _sleep(seconds: float) -> None:
        current['t'] += float(seconds)

    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.time', _now)
    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.sleep', _sleep)

    def _inspection():
        if current['t'] < 6.0:
            return SimpleNamespace(
                phase='starting',
                desired_state='running',
                health=LeaseHealth.UNMOUNTED,
                socket_connectable=False,
                reason='startup_in_progress',
                last_failure_reason=None,
                startup_stage='spawn_requested',
                last_progress_at='1970-01-01T00:00:00Z',
                startup_deadline_at='1970-01-01T00:00:20Z',
            )
        return SimpleNamespace(
            phase='mounted',
            desired_state='running',
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            reason='healthy',
            last_failure_reason=None,
            startup_stage='mounted',
            last_progress_at='1970-01-01T00:00:06Z',
            startup_deadline_at=None,
        )

    handle = ensure_daemon_started_runtime(
        SimpleNamespace(),
        clear_shutdown_intent_fn=lambda context: None,
        record_running_intent_fn=lambda context: True,
        ensure_keeper_started_fn=lambda context: True,
        inspect_daemon_fn=lambda context: (None, None, _inspection()),
        connect_compatible_daemon_fn=lambda context, inspection, restart_on_mismatch: (
            DaemonHandle(client='ccbd-client', inspection=inspection, started=False)
            if inspection.phase == 'mounted'
            else None
        ),
        should_restart_unreachable_daemon_fn=lambda inspection: False,
        restart_unreachable_daemon_fn=lambda context, inspection: None,
        incompatible_daemon_error_fn=lambda: 'incompatible',
        start_timeout_s=20.0,
        progress_stall_timeout_s=0.0,
    )

    assert handle.client == 'ccbd-client'
    assert handle.started is True
    assert current['t'] >= 6.0
    assert current['t'] < 7.0


def test_ensure_daemon_started_waits_for_final_mounted_stage(monkeypatch) -> None:
    current = {'t': 0.0}
    connect_stages: list[str] = []

    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.time', lambda: current['t'])
    monkeypatch.setattr(
        'cli.services.daemon_runtime.lifecycle.time.sleep',
        lambda seconds: current.__setitem__('t', current['t'] + float(seconds)),
    )

    def inspection():
        stage = 'runtime_bootstrap' if current['t'] < 1.0 else 'mounted'
        return SimpleNamespace(
            phase='mounted',
            desired_state='running',
            health=LeaseHealth.HEALTHY,
            socket_connectable=True,
            reason='healthy',
            last_failure_reason=None,
            startup_stage=stage,
            last_progress_at='1970-01-01T00:00:00Z',
            startup_deadline_at='1970-01-01T00:00:10Z',
        )

    def connect(context, observed, restart_on_mismatch):
        del context, restart_on_mismatch
        connect_stages.append(observed.startup_stage)
        return DaemonHandle(client='ccbd-client', inspection=observed, started=False)

    handle = ensure_daemon_started_runtime(
        SimpleNamespace(),
        clear_shutdown_intent_fn=lambda context: None,
        record_running_intent_fn=lambda context: True,
        ensure_keeper_started_fn=lambda context: True,
        inspect_daemon_fn=lambda context: (None, None, inspection()),
        connect_compatible_daemon_fn=connect,
        should_restart_unreachable_daemon_fn=lambda observed: False,
        restart_unreachable_daemon_fn=lambda context, observed: None,
        incompatible_daemon_error_fn=lambda: 'incompatible',
        start_timeout_s=5.0,
        progress_stall_timeout_s=0.0,
    )

    assert handle.client == 'ccbd-client'
    assert connect_stages == ['mounted']
    assert current['t'] >= 1.0


def test_ensure_daemon_started_uses_shared_startup_deadline(monkeypatch) -> None:
    current = {'t': 0.0}

    def _now() -> float:
        return current['t']

    def _sleep(seconds: float) -> None:
        current['t'] += float(seconds)

    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.time', _now)
    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.sleep', _sleep)

    inspection = SimpleNamespace(
        phase='starting',
        desired_state='running',
        health=LeaseHealth.UNMOUNTED,
        socket_connectable=False,
        reason='startup_in_progress',
        last_failure_reason=None,
        startup_stage='spawn_requested',
        last_progress_at='1970-01-01T00:00:00Z',
        startup_deadline_at='1970-01-01T00:00:08Z',
    )

    with pytest.raises(CcbdServiceError, match=r'lifecycle_starting\(stage=spawn_requested\)'):
        ensure_daemon_started_runtime(
            SimpleNamespace(),
            clear_shutdown_intent_fn=lambda context: None,
            record_running_intent_fn=lambda context: True,
            ensure_keeper_started_fn=lambda context: True,
            inspect_daemon_fn=lambda context: (None, None, inspection),
            connect_compatible_daemon_fn=lambda context, inspection, restart_on_mismatch: None,
            should_restart_unreachable_daemon_fn=lambda inspection: False,
            restart_unreachable_daemon_fn=lambda context, inspection: None,
            incompatible_daemon_error_fn=lambda: 'incompatible',
            start_timeout_s=20.0,
            progress_stall_timeout_s=0.0,
        )

    assert current['t'] >= 8.0
    assert current['t'] < 9.0


def test_ensure_daemon_started_surfaces_failed_terminal_state_without_waiting(monkeypatch) -> None:
    current = {'t': 100.0}

    monkeypatch.setattr('cli.services.daemon_runtime.lifecycle.time.time', lambda: current['t'])
    monkeypatch.setattr(
        'cli.services.daemon_runtime.lifecycle.time.sleep',
        lambda seconds: (_ for _ in ()).throw(AssertionError('failed startup should not sleep')),
    )

    inspection = SimpleNamespace(
        phase='failed',
        desired_state='stopped',
        health=LeaseHealth.MISSING,
        socket_connectable=False,
        reason='lease_missing',
        last_failure_reason='ccbd exited before ready with code 1',
        startup_stage='spawn_failed',
        last_progress_at='1970-01-01T00:00:00Z',
        startup_deadline_at=None,
    )

    with pytest.raises(
        CcbdServiceError,
        match='ccbd is unavailable: lease_missing; lifecycle_failure: ccbd exited before ready with code 1',
    ):
        ensure_daemon_started_runtime(
            SimpleNamespace(),
            clear_shutdown_intent_fn=lambda context: None,
            record_running_intent_fn=lambda context: True,
            ensure_keeper_started_fn=lambda context: True,
            inspect_daemon_fn=lambda context: (None, None, inspection),
            connect_compatible_daemon_fn=lambda context, inspection, restart_on_mismatch: None,
            should_restart_unreachable_daemon_fn=lambda inspection: False,
            restart_unreachable_daemon_fn=lambda context, inspection: None,
            incompatible_daemon_error_fn=lambda: 'incompatible',
            start_timeout_s=20.0,
            progress_stall_timeout_s=0.0,
        )

    assert current['t'] == 100.0


def test_connect_compatible_daemon_uses_short_control_plane_timeout(monkeypatch, tmp_path: Path) -> None:
    captured: list[float | None] = []

    class FakeClient:
        def __init__(self, socket_path, *, timeout_s=None) -> None:
            del socket_path
            self.timeout_s = timeout_s
            captured.append(timeout_s)

        def ping(self, target: str = 'ccbd') -> dict[str, object]:
            assert target == 'ccbd'
            return {'config_signature': 'sig'}

    monkeypatch.setattr(daemon_service, 'CcbdClient', FakeClient)
    monkeypatch.setattr(daemon_service, '_daemon_matches_project_config', lambda context, client: True)

    context = SimpleNamespace(paths=SimpleNamespace(ccbd_socket_path=tmp_path / 'ccbd.sock'))
    inspection = SimpleNamespace(socket_connectable=True, phase='mounted', health=LeaseHealth.HEALTHY)

    handle = daemon_service._connect_compatible_daemon(
        context,
        inspection,
        restart_on_mismatch=False,
    )

    assert handle is not None
    assert captured == [daemon_service.CONTROL_PLANE_RPC_TIMEOUT_S, None]
    assert handle.client.timeout_s is None


def test_spawned_ccbd_readiness_probe_uses_shared_control_plane_timeout(monkeypatch, tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    socket_path.touch()
    captured: list[float | None] = []

    class FakeClient:
        def __init__(self, socket_path_arg, *, timeout_s=None) -> None:
            assert socket_path_arg == socket_path
            captured.append(timeout_s)

        def ping(self, target: str = 'ccbd') -> dict[str, object]:
            assert target == 'ccbd'
            return {'ok': True}

    monkeypatch.setattr(ccbd_daemon_process, 'CcbdClient', FakeClient)
    process = SimpleNamespace(poll=lambda: None)

    ccbd_daemon_process._wait_for_ccbd_ready(process=process, socket_path=socket_path, timeout_s=1.0)

    assert captured == [ccbd_daemon_process.CONTROL_PLANE_RPC_TIMEOUT_S]


def test_spawned_ccbd_readiness_rejects_old_socket_identity(monkeypatch, tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    socket_path.touch()
    payloads = iter(
        (
            {
                'generation': 6,
                'mount_state': 'mounted',
                'desired_state': 'running',
                'serving_pid': 999,
                'serving_daemon_instance_id': 'old-daemon',
                'serving_lease_generation': 6,
                'accepted_startup_id': 'b' * 32,
                'diagnostics': {
                    'startup_id': 'b' * 32,
                    'startup_stage': 'mounted',
                },
            },
            {
                'generation': 7,
                'mount_state': 'mounted',
                'desired_state': 'running',
                'serving_pid': 4321,
                'serving_daemon_instance_id': 'new-daemon',
                'serving_lease_generation': 7,
                'accepted_startup_id': 'a' * 32,
                'diagnostics': {
                    'startup_id': 'a' * 32,
                    'startup_stage': 'mounted',
                },
            },
        )
    )

    class FakeClient:
        def __init__(self, socket_path_arg, *, timeout_s=None) -> None:
            assert socket_path_arg == socket_path
            assert timeout_s == ccbd_daemon_process.CONTROL_PLANE_RPC_TIMEOUT_S

        def ping(self, target: str = 'ccbd') -> dict[str, object]:
            assert target == 'ccbd'
            return next(payloads)

    monkeypatch.setattr(ccbd_daemon_process, 'CcbdClient', FakeClient)
    monkeypatch.setattr(ccbd_daemon_process.time, 'sleep', lambda _seconds: None)
    process = SimpleNamespace(pid=4321, poll=lambda: None)

    ccbd_daemon_process._wait_for_ccbd_ready(
        process=process,
        socket_path=socket_path,
        timeout_s=1.0,
        expected_startup_id='a' * 32,
        expected_generation=7,
    )

    with pytest.raises(StopIteration):
        next(payloads)


def test_startup_policy_defaults_to_thirty_second_cold_start_budget(monkeypatch) -> None:
    monkeypatch.delenv('CCB_STARTUP_TRANSACTION_TIMEOUT_S', raising=False)

    reloaded = importlib.reload(startup_policy)

    assert reloaded.STARTUP_TRANSACTION_TIMEOUT_S == 30.0


def test_startup_policy_clamps_foreground_attach_timeout_to_startup_budget(monkeypatch) -> None:
    monkeypatch.setenv('CCB_STARTUP_TRANSACTION_TIMEOUT_S', '4.0')
    monkeypatch.setenv('CCB_FOREGROUND_ATTACH_RPC_TIMEOUT_S', '2.5')
    monkeypatch.setenv('CCB_FOREGROUND_ATTACH_TARGET_READY_TIMEOUT_S', '10.0')

    reloaded = importlib.reload(startup_policy)

    assert reloaded.FOREGROUND_ATTACH_RPC_TIMEOUT_S == 2.5
    assert reloaded.FOREGROUND_ATTACH_TARGET_READY_TIMEOUT_S == 4.0

    monkeypatch.delenv('CCB_STARTUP_TRANSACTION_TIMEOUT_S', raising=False)
    monkeypatch.delenv('CCB_FOREGROUND_ATTACH_RPC_TIMEOUT_S', raising=False)
    monkeypatch.delenv('CCB_FOREGROUND_ATTACH_TARGET_READY_TIMEOUT_S', raising=False)
    importlib.reload(startup_policy)
