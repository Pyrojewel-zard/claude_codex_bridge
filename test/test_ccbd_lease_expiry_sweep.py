from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ccbd.api_models import JobStatus, TargetKind
from ccbd.app_runtime.bootstrap import MAILBOX_LEASE_EXPIRY_TTL_S
from ccbd.app_runtime.lifecycle import (
    _agents_with_running_jobs,
    _sweep_expired_delivery_leases,
)
from mailbox_kernel import (
    InboundEventRecord,
    InboundEventStatus,
    InboundEventStore,
    InboundEventType,
    MailboxKernelService,
)
from storage.paths import PathLayout


def _seed_delivering(layout: PathLayout) -> None:
    inbound_store = InboundEventStore(layout)
    inbound_store.append(
        InboundEventRecord(
            inbound_event_id='evt-task',
            agent_name='agent1',
            event_type=InboundEventType.TASK_REPLY,
            message_id='msg-1',
            attempt_id='att-1',
            payload_ref='reply:rep-1',
            priority=10,
            status=InboundEventStatus.QUEUED,
            created_at='2026-07-09T10:00:00Z',
        )
    )
    seeder = MailboxKernelService(
        layout,
        clock=lambda: '2026-07-09T10:00:00Z',
        lease_ttl_seconds=MAILBOX_LEASE_EXPIRY_TTL_S,
    )
    seeder.claim('agent1', 'evt-task', started_at='2026-07-09T10:00:00Z')


def _fake_dispatcher(*, running_agent: str | None) -> SimpleNamespace:
    jobs: dict[str, SimpleNamespace] = {}
    active: list[tuple[TargetKind, str, str]] = []
    if running_agent is not None:
        jobs['job-1'] = SimpleNamespace(
            status=JobStatus.RUNNING,
            target_kind=TargetKind.AGENT,
            target_name=running_agent,
        )
        active.append((TargetKind.AGENT, running_agent, 'job-1'))
    state = SimpleNamespace(active_items=lambda: tuple(active))
    return SimpleNamespace(_state=state, get=lambda job_id: jobs.get(job_id))


def _fake_app(tmp_path: Path, *, running_agent: str | None) -> SimpleNamespace:
    layout = PathLayout(tmp_path / 'repo')
    return SimpleNamespace(
        paths=layout,
        clock=lambda: '2026-07-09T11:00:00Z',
        mailbox_lease_ttl_s=MAILBOX_LEASE_EXPIRY_TTL_S,
        dispatcher=_fake_dispatcher(running_agent=running_agent),
    )


def test_bootstrap_lease_ttl_is_positive() -> None:
    assert isinstance(MAILBOX_LEASE_EXPIRY_TTL_S, float)
    assert MAILBOX_LEASE_EXPIRY_TTL_S > 0


def test_sweep_terminates_idle_delivering_lease(tmp_path: Path) -> None:
    app = _fake_app(tmp_path, running_agent=None)
    _seed_delivering(app.paths)

    _sweep_expired_delivery_leases(app)

    current = InboundEventStore(app.paths).get_latest('agent1', 'evt-task')
    assert current is not None
    assert current.status is InboundEventStatus.ABANDONED


def test_sweep_skips_agent_with_running_job(tmp_path: Path) -> None:
    app = _fake_app(tmp_path, running_agent='agent1')
    _seed_delivering(app.paths)

    _sweep_expired_delivery_leases(app)

    current = InboundEventStore(app.paths).get_latest('agent1', 'evt-task')
    assert current is not None
    assert current.status is InboundEventStatus.DELIVERING


def test_sweep_disabled_when_ttl_not_positive(tmp_path: Path) -> None:
    app = _fake_app(tmp_path, running_agent=None)
    app.mailbox_lease_ttl_s = 0
    _seed_delivering(app.paths)

    _sweep_expired_delivery_leases(app)

    current = InboundEventStore(app.paths).get_latest('agent1', 'evt-task')
    assert current is not None
    assert current.status is InboundEventStatus.DELIVERING


def test_agents_with_running_jobs_collects_normalized_names(tmp_path: Path) -> None:
    app = _fake_app(tmp_path, running_agent='agent1')

    assert _agents_with_running_jobs(app) == {'agent1'}
