from __future__ import annotations

from pathlib import Path

from mailbox_kernel import (
    DeliveryLeaseStore,
    InboundEventRecord,
    InboundEventStatus,
    InboundEventStore,
    InboundEventType,
    MailboxKernelService,
    MailboxState,
    MailboxStore,
)
from mailbox_kernel.model_enums import LeaseState
from storage.paths import PathLayout


def _seed_queued_task(inbound_store: InboundEventStore, *, created_at: str) -> None:
    inbound_store.append(
        InboundEventRecord(
            inbound_event_id='evt-task',
            agent_name='agent1',
            event_type=InboundEventType.TASK_REQUEST,
            message_id='msg-1',
            attempt_id='att-1',
            payload_ref='job:job-1',
            priority=100,
            status=InboundEventStatus.QUEUED,
            created_at=created_at,
        )
    )


def test_claim_populates_lease_expires_at_from_ttl(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T10:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    _seed_queued_task(inbound_store, created_at='2026-07-09T10:00:00Z')

    claimed = service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')

    assert claimed is not None
    assert claimed.status is InboundEventStatus.DELIVERING
    lease = lease_store.load('agent1')
    assert lease is not None
    assert lease.lease_state is LeaseState.ACQUIRED
    assert lease.expires_at == '2026-07-09T10:30:00Z'


def test_claim_without_ttl_leaves_expires_at_none(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T10:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
    )
    _seed_queued_task(inbound_store, created_at='2026-07-09T10:00:00Z')

    service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')

    lease = lease_store.load('agent1')
    assert lease is not None
    assert lease.expires_at is None


def test_expired_delivery_leases_reports_idle_lease_past_deadline(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    _seed_queued_task(inbound_store, created_at='2026-07-09T10:00:00Z')
    service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')

    expired = service.expired_delivery_leases(now='2026-07-09T11:00:00Z')

    assert len(expired) == 1
    assert expired[0].agent_name == 'agent1'


def test_healthy_delivery_is_not_reported_expired(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T10:05:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    _seed_queued_task(inbound_store, created_at='2026-07-09T10:00:00Z')
    service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')

    expired = service.expired_delivery_leases(now='2026-07-09T10:05:00Z')

    assert expired == ()


def test_legacy_lease_without_expires_at_uses_acquired_at_plus_ttl(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    # Production dispatcher kernels are not threaded the TTL, so a legacy claim
    # persists expires_at=None. The sweep's own kernel supplies ttl and must
    # still derive a deadline from acquired_at.
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    inbound_store.append(
        InboundEventRecord(
            inbound_event_id='evt-task',
            agent_name='agent1',
            event_type=InboundEventType.TASK_REQUEST,
            message_id='msg-1',
            attempt_id='att-1',
            payload_ref='job:job-1',
            priority=100,
            status=InboundEventStatus.DELIVERING,
            created_at='2026-07-09T10:00:00Z',
            started_at='2026-07-09T10:00:00Z',
        )
    )
    lease_store.save(
        service._delivery_lease_cls(
            agent_name='agent1',
            inbound_event_id='evt-task',
            lease_version=1,
            acquired_at='2026-07-09T10:00:00Z',
            last_progress_at=None,
            expires_at=None,
            lease_state=LeaseState.ACQUIRED,
        )
    )

    expired = service.expired_delivery_leases(now='2026-07-09T11:00:00Z')

    assert len(expired) == 1
    assert expired[0].expires_at is None


def test_expire_lease_terminates_event_and_marks_lease_expired(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    mailbox_store = MailboxStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        inbound_store=inbound_store,
        mailbox_store=mailbox_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    # A following queued task so we can assert the queue advances after expiry.
    inbound_store.append(
        InboundEventRecord(
            inbound_event_id='evt-task',
            agent_name='agent1',
            event_type=InboundEventType.TASK_REQUEST,
            message_id='msg-1',
            attempt_id='att-1',
            payload_ref='job:job-1',
            priority=100,
            status=InboundEventStatus.QUEUED,
            created_at='2026-07-09T10:00:00Z',
        )
    )
    inbound_store.append(
        InboundEventRecord(
            inbound_event_id='evt-next',
            agent_name='agent1',
            event_type=InboundEventType.TASK_REQUEST,
            message_id='msg-2',
            attempt_id='att-2',
            payload_ref='job:job-2',
            priority=100,
            status=InboundEventStatus.QUEUED,
            created_at='2026-07-09T10:00:01Z',
        )
    )
    service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')

    terminal = service.expire_lease('agent1', finished_at='2026-07-09T11:00:00Z')

    assert terminal is not None
    assert terminal.inbound_event_id == 'evt-task'
    assert terminal.status is InboundEventStatus.ABANDONED
    lease = lease_store.load('agent1')
    assert lease is not None
    assert lease.lease_state is LeaseState.EXPIRED
    mailbox = mailbox_store.load('agent1')
    assert mailbox is not None
    assert mailbox.active_inbound_event_id is None
    assert mailbox.head_inbound_event_id == 'evt-next'
    assert mailbox.queue_depth == 1


def test_expire_lease_is_noop_when_event_already_terminal(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    _seed_queued_task(inbound_store, created_at='2026-07-09T10:00:00Z')
    service.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')
    # Phase-1 (or normal consume) already terminated the event; the sweep must
    # not re-terminate and must clear the stranded lease.
    service.consume('agent1', 'evt-task', finished_at='2026-07-09T10:30:00Z')

    terminal = service.expire_lease('agent1', finished_at='2026-07-09T11:00:00Z')

    assert terminal is None
    assert lease_store.load('agent1') is None


def test_expired_delivery_leases_ignores_released_lease(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')
    inbound_store = InboundEventStore(layout)
    lease_store = DeliveryLeaseStore(layout)
    service = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        inbound_store=inbound_store,
        lease_store=lease_store,
        lease_ttl_seconds=1800.0,
    )
    lease_store.save(
        service._delivery_lease_cls(
            agent_name='agent1',
            inbound_event_id='evt-task',
            lease_version=1,
            acquired_at='2026-07-09T10:00:00Z',
            last_progress_at=None,
            expires_at='2026-07-09T10:30:00Z',
            lease_state=LeaseState.RELEASED,
        )
    )

    assert service.expired_delivery_leases(now='2026-07-09T11:00:00Z') == ()
