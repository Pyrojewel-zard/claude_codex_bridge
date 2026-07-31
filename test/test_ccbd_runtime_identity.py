from __future__ import annotations

from types import SimpleNamespace

import pytest

from ccbd.models import CcbdLease, LeaseHealth, LeaseInspection, MountState
from ccbd.services.lifecycle import build_lifecycle
from ccbd.services.ownership import OwnershipConflictError
from ccbd.services.runtime_identity import reconcile_runtime_project_identity


class _Manager:
    def __init__(self) -> None:
        self.unmounted: list[tuple[int | None, str | None]] = []

    def mark_unmounted(
        self,
        *,
        expected_pid: int | None = None,
        expected_daemon_instance_id: str | None = None,
    ):
        self.unmounted.append((expected_pid, expected_daemon_instance_id))
        return None


def _lease(project_id: str) -> CcbdLease:
    return CcbdLease(
        project_id=project_id,
        ccbd_pid=123,
        socket_path='/old/.ccb/ccbd/ccbd.sock',
        owner_uid=1000,
        boot_id='boot-1',
        started_at='2026-07-24T00:00:00Z',
        last_heartbeat_at='2026-07-24T00:00:00Z',
        mount_state=MountState.MOUNTED,
        generation=9,
        daemon_instance_id='daemon-old',
    )


def _inspection(
    lease: CcbdLease,
    *,
    takeover_allowed: bool,
) -> LeaseInspection:
    return LeaseInspection(
        lease=lease,
        health=LeaseHealth.STALE if takeover_allowed else LeaseHealth.HEALTHY,
        pid_alive=not takeover_allowed,
        socket_connectable=not takeover_allowed,
        heartbeat_fresh=not takeover_allowed,
        takeover_allowed=takeover_allowed,
        reason='stale' if takeover_allowed else 'healthy',
    )


def test_reconcile_inactive_foreign_runtime_rebuilds_lifecycle() -> None:
    lifecycle = build_lifecycle(
        project_id='a' * 64,
        occurred_at='2026-07-24T00:00:00Z',
        desired_state='running',
        phase='failed',
        generation=11,
        keeper_pid=111,
        socket_path='/old/.ccb/ccbd/ccbd.sock',
    )
    lease = _lease('a' * 64)
    manager = _Manager()

    result = reconcile_runtime_project_identity(
        project_id='b' * 64,
        lifecycle=lifecycle,
        inspection=_inspection(lease, takeover_allowed=True),
        mount_manager=manager,
        occurred_at='2026-07-24T00:01:00Z',
        socket_path='/new/.ccb/ccbd/ccbd.sock',
        keeper_pid=222,
        config_signature='config-new',
    )

    assert result.reconciled is True
    assert result.previous_project_ids == ('a' * 64,)
    assert result.lifecycle.project_id == 'b' * 64
    assert result.lifecycle.desired_state == 'running'
    assert result.lifecycle.phase == 'unmounted'
    assert result.lifecycle.generation == 11
    assert result.lifecycle.keeper_pid == 222
    assert result.lifecycle.socket_path == '/new/.ccb/ccbd/ccbd.sock'
    assert manager.unmounted == [(123, 'daemon-old')]


def test_reconcile_active_foreign_runtime_fails_closed() -> None:
    lease = _lease('a' * 64)

    with pytest.raises(OwnershipConflictError, match='foreign authority is active'):
        reconcile_runtime_project_identity(
            project_id='b' * 64,
            lifecycle=None,
            inspection=_inspection(lease, takeover_allowed=False),
            mount_manager=_Manager(),
            occurred_at='2026-07-24T00:01:00Z',
            socket_path='/new/.ccb/ccbd/ccbd.sock',
        )


def test_reconcile_matching_identity_is_noop() -> None:
    lifecycle = SimpleNamespace(project_id='a' * 64)
    lease = _lease('a' * 64)

    result = reconcile_runtime_project_identity(
        project_id='a' * 64,
        lifecycle=lifecycle,
        inspection=_inspection(lease, takeover_allowed=False),
        mount_manager=_Manager(),
        occurred_at='2026-07-24T00:01:00Z',
        socket_path='/same/.ccb/ccbd/ccbd.sock',
    )

    assert result.reconciled is False
    assert result.lifecycle is lifecycle
