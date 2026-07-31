from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import cli.services.followup as followup_service
from agents.models import (
    AgentRuntime,
    AgentSpec,
    AgentState,
    PermissionMode,
    ProjectConfig,
    QueuePolicy,
    RestoreMode,
    RuntimeMode,
    WorkspaceMode,
)
from ccbd.active_followups import ActiveFollowupRecord, ActiveFollowupStore
from ccbd.api_models import DeliveryScope, MessageEnvelope
from ccbd.app_runtime.request_guard import rejection_for_request
from ccbd.handlers.followup import build_followup_handler
from ccbd.services.dispatcher import JobDispatcher
from ccbd.services.registry import AgentRegistry
from ccbd.socket_client import CcbdClient
from cli.models import ParsedFollowupCommand
from cli.parser import CliParser
from cli.phase2_runtime.handlers_mailbox import handle_followup
from cli.render import render_followup
from completion.models import CompletionConfidence, CompletionDecision, CompletionStatus
from project.ids import compute_project_id
from provider_execution.fake import FakeProviderAdapter
from provider_execution.followups import ActiveFollowupResult
from provider_execution.registry import ProviderExecutionRegistry
from provider_execution.service import ExecutionService
from provider_execution.state_store import ExecutionStateStore
from storage.paths import PathLayout


class MutableClock:
    def __init__(self, value: str = '2026-07-21T00:00:00Z') -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class UnsupportedProviderAdapter:
    provider = 'fake'
    restart_resume_supported = True

    def __init__(self) -> None:
        self._delegate = FakeProviderAdapter(provider=self.provider, latency_seconds=60)

    def start(self, job, *, context, now):
        return self._delegate.start(job, context=context, now=now)

    def poll(self, submission, *, now):
        return self._delegate.poll(submission, now=now)

    def export_runtime_state(self, submission):
        return self._delegate.export_runtime_state(submission)

    def resume(self, job, submission, *, context, persisted_state, now):
        return self._delegate.resume(
            job,
            submission,
            context=context,
            persisted_state=persisted_state,
            now=now,
        )


class BlockingCancelFakeAdapter(FakeProviderAdapter):
    def __init__(self) -> None:
        super().__init__(latency_seconds=60)
        self.cancel_entered = Event()
        self.cancel_release = Event()

    def cancel(self, submission) -> None:
        del submission
        self.cancel_entered.set()
        assert self.cancel_release.wait(timeout=5)


class BlockingPollFakeAdapter(FakeProviderAdapter):
    def __init__(self) -> None:
        super().__init__(latency_seconds=0)
        self.poll_entered = Event()
        self.poll_release = Event()

    def poll(self, submission, *, now):
        self.poll_entered.set()
        assert self.poll_release.wait(timeout=5)
        return super().poll(submission, now=now)


class BlockingStartFakeAdapter(FakeProviderAdapter):
    def __init__(self) -> None:
        super().__init__(latency_seconds=60)
        self.start_entered = Event()
        self.start_release = Event()
        self.late_submission_cancelled = Event()

    def start(self, job, *, context, now):
        self.start_entered.set()
        assert self.start_release.wait(timeout=5)
        return super().start(job, context=context, now=now)

    def cancel(self, submission) -> None:
        del submission
        self.late_submission_cancelled.set()


class PendingFollowupFakeAdapter(FakeProviderAdapter):
    def __init__(self, *, pending: bool) -> None:
        super().__init__(latency_seconds=60)
        self.pending = pending
        self.injected_ids: list[str] = []

    def inject_active_followup(self, submission, *, request, now):
        if self.pending:
            return ActiveFollowupResult(
                submission=submission,
                status='accepted',
                reason='ambiguous_transport_for_test',
                mechanism='fake_exact_active_turn',
                provider_turn_ref=submission.job_id,
            )
        self.injected_ids.append(request.followup_id)
        return super().inject_active_followup(
            submission,
            request=request,
            now=now,
        )


def _config(provider: str = 'fake') -> ProjectConfig:
    spec = AgentSpec(
        name='demo',
        provider=provider,
        target='.',
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
    )
    return ProjectConfig(version=2, default_agents=('demo',), agents={'demo': spec})


def _dispatcher(
    tmp_path: Path,
    *,
    adapter=None,
    project_name: str = 'repo',
    clock: MutableClock | None = None,
) -> tuple[JobDispatcher, ExecutionService, PathLayout, MutableClock]:
    project_root = tmp_path / project_name
    project_root.mkdir()
    (project_root / '.ccb').mkdir()
    selected_adapter = adapter or FakeProviderAdapter(latency_seconds=60)
    provider = selected_adapter.provider
    config = _config(provider)
    layout = PathLayout(project_root)
    project_id = compute_project_id(project_root)
    registry = AgentRegistry(layout, config)
    registry.upsert(
        AgentRuntime(
            agent_name='demo',
            state=AgentState.IDLE,
            pid=101,
            started_at='2026-07-21T00:00:00Z',
            last_seen_at='2026-07-21T00:00:00Z',
            runtime_ref='demo-runtime',
            session_ref='demo-session',
            workspace_path=str(layout.workspace_path('demo')),
            project_id=project_id,
            backend_type='tmux',
            queue_depth=0,
            socket_path=None,
            health='healthy',
        )
    )
    mutable_clock = clock or MutableClock()
    execution = ExecutionService(
        ProviderExecutionRegistry([selected_adapter]),
        clock=mutable_clock,
        state_store=ExecutionStateStore(layout),
    )
    dispatcher = JobDispatcher(
        layout,
        config,
        registry,
        execution_service=execution,
        clock=mutable_clock,
    )
    return dispatcher, execution, layout, mutable_clock


def _submit(dispatcher: JobDispatcher, layout: PathLayout, body: str) -> str:
    receipt = dispatcher.submit(
        MessageEnvelope(
            project_id=compute_project_id(layout.project_root),
            to_agent='demo',
            from_actor='user',
            body=body,
            task_id=None,
            reply_to=None,
            message_type='ask',
            delivery_scope=DeliveryScope.SINGLE,
        )
    )
    return receipt.jobs[0].job_id


def _terminal_decision(now: str) -> CompletionDecision:
    return CompletionDecision(
        terminal=True,
        status=CompletionStatus.COMPLETED,
        reason='task_complete',
        confidence=CompletionConfidence.EXACT,
        reply='done',
        anchor_seen=True,
        reply_started=True,
        reply_stable=True,
        provider_turn_ref='fake-turn',
        source_cursor=None,
        finished_at=now,
        diagnostics={},
    )


def test_followup_injects_only_exact_active_job_and_preserves_fifo_lineage(tmp_path: Path) -> None:
    dispatcher, execution, layout, _clock = _dispatcher(tmp_path)
    active_job = _submit(dispatcher, layout, 'active')
    queued_job = _submit(dispatcher, layout, 'queued')
    dispatcher.tick()

    wrong = dispatcher.followup(queued_job, 'must not reach active turn')
    first = dispatcher.followup(active_job, 'first correction')
    second = dispatcher.followup(active_job, 'second correction')

    assert wrong['status'] == 'rejected'
    assert wrong['reason'] == 'job_not_running:queued'
    assert first['status'] == second['status'] == 'injected'
    assert first['sequence'] == 1
    assert second['sequence'] == 2
    assert 'message' not in first
    delivered = execution._active[active_job].runtime_state['active_followups']
    assert [(item['followup_id'], item['message']) for item in delivered] == [
        (first['followup_id'], 'first correction'),
        (second['followup_id'], 'second correction'),
    ]
    assert execution._active.get(queued_job) is None
    assert {record.job_id for record in dispatcher._job_store.list_agent('demo')} == {
        active_job,
        queued_job,
    }

    direct_trace = dispatcher.trace(first['followup_id'])
    assert direct_trace['resolved_kind'] == 'active_followup'
    assert direct_trace['resolved_job_kind'] == 'job'
    assert direct_trace['job_id'] == active_job
    assert direct_trace['jobs']
    assert [item['sequence'] for item in direct_trace['active_followups']] == [1, 2]
    assert all('message' not in item for item in direct_trace['active_followups'])


def test_followup_rejects_unknown_unsupported_and_too_late_targets(tmp_path: Path) -> None:
    dispatcher, _execution, layout, clock = _dispatcher(tmp_path)
    assert dispatcher.followup('job_missing', 'correction')['reason'] == 'unknown_job'

    job_id = _submit(dispatcher, layout, 'complete me')
    dispatcher.tick()
    dispatcher.complete(job_id, _terminal_decision(clock()))
    too_late = dispatcher.followup(job_id, 'late correction')
    assert too_late['status'] == 'too_late'
    assert too_late['reason'] == 'job_already_completed'

    unsupported, _service, unsupported_layout, _ = _dispatcher(
        tmp_path,
        adapter=UnsupportedProviderAdapter(),
        project_name='unsupported-repo',
    )
    unsupported_job = _submit(unsupported, unsupported_layout, 'unsupported')
    unsupported.tick()
    refused = unsupported.followup(unsupported_job, 'do not pane inject')
    assert refused['status'] == 'rejected'
    assert refused['reason'] == 'provider_active_followup_unsupported'
    assert refused['mechanism'] == 'unsupported'


def test_followup_reports_terminal_when_provider_completion_is_pending(tmp_path: Path) -> None:
    adapter = FakeProviderAdapter(latency_seconds=0)
    dispatcher, execution, layout, clock = _dispatcher(tmp_path, adapter=adapter)
    job_id = _submit(dispatcher, layout, 'complete in provider')
    dispatcher.tick()
    clock.value = '2026-07-21T00:00:01Z'
    updates = execution.poll()
    assert updates and updates[0].decision is not None and updates[0].decision.terminal
    assert dispatcher.get(job_id).status.value == 'running'

    raced = dispatcher.followup(job_id, 'too late for provider turn')
    assert raced['status'] == 'terminal'
    assert raced['reason'] == 'provider_terminal_pending'


def test_followup_and_cancel_share_an_ordered_terminal_boundary(tmp_path: Path) -> None:
    adapter = BlockingCancelFakeAdapter()
    dispatcher, _execution, layout, _clock = _dispatcher(tmp_path, adapter=adapter)
    job_id = _submit(dispatcher, layout, 'cancel race')
    dispatcher.tick()
    cancel_result: dict[str, object] = {}
    followup_result: dict[str, object] = {}

    def cancel() -> None:
        cancel_result['receipt'] = dispatcher.cancel(job_id)

    def followup() -> None:
        followup_result.update(dispatcher.followup(job_id, 'raced correction'))

    cancel_thread = Thread(target=cancel)
    cancel_thread.start()
    assert adapter.cancel_entered.wait(timeout=5)
    followup_thread = Thread(target=followup)
    followup_thread.start()
    adapter.cancel_release.set()
    followup_thread.join(timeout=5)
    cancel_thread.join(timeout=5)

    assert not followup_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert followup_result['status'] == 'terminal'
    assert followup_result['reason'] == 'active_submission_missing'
    assert cancel_result['receipt'].status.value == 'cancelled'
    assert dispatcher.get(job_id).status.value == 'cancelled'


def test_stale_provider_poll_cannot_overwrite_injected_followup_state(tmp_path: Path) -> None:
    adapter = BlockingPollFakeAdapter()
    dispatcher, execution, layout, clock = _dispatcher(tmp_path, adapter=adapter)
    job_id = _submit(dispatcher, layout, 'poll race')
    dispatcher.tick()
    clock.value = '2026-07-21T00:00:01Z'
    completed: list[tuple] = []

    poll_thread = Thread(target=lambda: completed.append(dispatcher.poll_completions()))
    poll_thread.start()
    assert adapter.poll_entered.wait(timeout=5)
    injected = dispatcher.followup(job_id, 'wins before stale poll commit')
    adapter.poll_release.set()
    poll_thread.join(timeout=5)

    assert not poll_thread.is_alive()
    assert injected['status'] == 'injected'
    assert completed == [()]
    assert execution._active[job_id].runtime_state['active_followups'][0]['followup_id'] == injected['followup_id']

    terminal = dispatcher.poll_completions()
    assert terminal and terminal[0].status.value == 'completed'


def test_cancel_revokes_slow_start_without_waiting_or_restoring_late_submission(tmp_path: Path) -> None:
    adapter = BlockingStartFakeAdapter()
    dispatcher, execution, layout, _clock = _dispatcher(tmp_path, adapter=adapter)
    job_id = _submit(dispatcher, layout, 'slow start')
    tick_thread = Thread(target=dispatcher.tick)
    tick_thread.start()
    assert adapter.start_entered.wait(timeout=5)

    starting = dispatcher.followup(job_id, 'not bound yet')
    assert starting['status'] == 'rejected'
    assert starting['reason'] == 'active_submission_starting'

    receipt = dispatcher.cancel(job_id)
    assert receipt.status.value == 'cancelled'
    assert tick_thread.is_alive()

    adapter.start_release.set()
    tick_thread.join(timeout=5)
    assert not tick_thread.is_alive()
    assert adapter.late_submission_cancelled.is_set()
    assert job_id not in execution._active
    assert job_id not in execution._starting
    assert execution._state_store.load(job_id) is None
    assert dispatcher.get(job_id).status.value == 'cancelled'


def test_restart_replays_durable_accepted_followup_once(tmp_path: Path) -> None:
    dispatcher, execution, layout, clock = _dispatcher(tmp_path)
    job_id = _submit(dispatcher, layout, 'survive restart')
    dispatcher.tick()
    accepted = ActiveFollowupRecord(
        followup_id='fup_restart',
        job_id=job_id,
        message='durable correction',
        agent_name='demo',
        provider='fake',
        sequence=1,
        status='accepted',
        reason='durable_outbox_accepted',
        mechanism='fake_exact_active_turn',
        expected_provider_turn_ref=job_id,
        provider_turn_ref=job_id,
        created_at=clock(),
        updated_at=clock(),
    )
    ActiveFollowupStore(layout).append(accepted)

    restarted_execution = ExecutionService(
        ProviderExecutionRegistry([FakeProviderAdapter(latency_seconds=60)]),
        clock=clock,
        state_store=execution._state_store,
    )
    restarted = JobDispatcher(
        layout,
        dispatcher._config,
        dispatcher._registry,
        execution_service=restarted_execution,
        clock=clock,
    )
    restored = restarted.restore_running_jobs()

    assert restored and restored[0].job_id == job_id
    latest = ActiveFollowupStore(layout).get_latest('fup_restart')
    assert latest is not None and latest.status == 'injected'
    delivered = restarted_execution._active[job_id].runtime_state['active_followups']
    assert [item['followup_id'] for item in delivered] == ['fup_restart']
    restarted.restore_running_jobs()
    delivered = restarted_execution._active[job_id].runtime_state['active_followups']
    assert [item['followup_id'] for item in delivered] == ['fup_restart']


def test_accepted_followup_store_preserves_append_fifo_across_targets(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path)
    store = ActiveFollowupStore(layout)
    base = ActiveFollowupRecord(
        followup_id='fup_z',
        job_id='job_z',
        message='first appended',
        agent_name='z',
        provider='fake',
        sequence=1,
        status='accepted',
        reason='durable_outbox_accepted',
        mechanism='fake_exact_active_turn',
        expected_provider_turn_ref='job_z',
        provider_turn_ref='job_z',
        created_at='2026-07-21T00:00:00Z',
        updated_at='2026-07-21T00:00:00Z',
    )
    store.append(base)
    store.append(
        replace(
            base,
            followup_id='fup_a',
            job_id='job_a',
            message='second appended',
            agent_name='a',
            expected_provider_turn_ref='job_a',
            provider_turn_ref='job_a',
        )
    )
    store.append(replace(base, reason='ambiguous_transport_retry'))

    assert [record.followup_id for record in store.accepted()] == ['fup_z', 'fup_a']


def test_ambiguous_followup_blocks_later_delivery_and_replays_fifo(tmp_path: Path) -> None:
    pending_adapter = PendingFollowupFakeAdapter(pending=True)
    dispatcher, execution, layout, clock = _dispatcher(tmp_path, adapter=pending_adapter)
    job_id = _submit(dispatcher, layout, 'ambiguous followup')
    dispatcher.tick()

    first = dispatcher.followup(job_id, 'first correction')
    second = dispatcher.followup(job_id, 'second correction')
    assert first['status'] == second['status'] == 'accepted'
    assert second['reason'] == 'durable_outbox_waiting_for_prior_followup'
    assert [record.followup_id for record in ActiveFollowupStore(layout).accepted()] == [
        first['followup_id'],
        second['followup_id'],
    ]

    replay_adapter = PendingFollowupFakeAdapter(pending=False)
    restarted_execution = ExecutionService(
        ProviderExecutionRegistry([replay_adapter]),
        clock=clock,
        state_store=execution._state_store,
    )
    restarted = JobDispatcher(
        layout,
        dispatcher._config,
        dispatcher._registry,
        execution_service=restarted_execution,
        clock=clock,
    )
    restarted.restore_running_jobs()

    assert replay_adapter.injected_ids == [first['followup_id'], second['followup_id']]
    assert ActiveFollowupStore(layout).accepted() == ()


def test_rejected_followup_does_not_persist_correction_text(tmp_path: Path) -> None:
    dispatcher, _execution, layout, _clock = _dispatcher(tmp_path)
    outcome = dispatcher.followup('job_missing', 'sensitive rejected correction')
    stored = ActiveFollowupStore(layout).get_latest(outcome['followup_id'])
    assert stored is not None
    assert stored.status == 'rejected'
    assert stored.message == ''
    trace = dispatcher.trace(outcome['followup_id'])
    assert trace['resolved_kind'] == 'active_followup'
    assert trace['resolved_job_kind'] is None
    assert trace['job_id'] == 'job_missing'


def test_followup_cli_parser_and_renderer_expose_outcome_without_message() -> None:
    parsed = CliParser().parse(['followup', 'job_123', '--message', 'correct scope'])
    assert parsed == ParsedFollowupCommand(
        project=None,
        job_id='job_123',
        message='correct scope',
    )
    rendered = render_followup(
        {
            'followup_id': 'fup_123',
            'job_id': 'job_123',
            'status': 'injected',
            'reason': 'provider_turn_steered',
        }
    )
    assert rendered[0] == 'followup_status: injected'
    assert all('correct scope' not in line for line in rendered)


def test_followup_handler_client_exit_status_and_shutdown_guard_preserve_outcome(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    handler = build_followup_handler(
        SimpleNamespace(
            followup=lambda job_id, message: calls.append((job_id, message))
            or {'job_id': job_id, 'status': 'injected'}
        )
    )
    assert handler({'job_id': 'job_1', 'message': 'correct it'})['status'] == 'injected'
    assert calls == [('job_1', 'correct it')]

    requests: list[tuple[str, dict[str, object]]] = []
    client = CcbdClient('/tmp/not-used.sock')
    monkeypatch.setattr(
        client,
        'request',
        lambda op, payload: requests.append((op, payload)) or {'status': 'terminal'},
    )
    assert client.followup('job_1', 'late')['status'] == 'terminal'
    assert requests == [('followup', {'job_id': 'job_1', 'message': 'late'})]

    output: list[str] = []
    services = SimpleNamespace(
        active_job_followup=lambda context, command: {'status': 'rejected', 'reason': 'unsupported'},
        render_followup=render_followup,
        write_lines=lambda out, lines: out.extend(lines),
    )
    exit_code = handle_followup(
        SimpleNamespace(),
        ParsedFollowupCommand(project=None, job_id='job_1', message='correct'),
        output,
        services,
    )
    assert exit_code == 3
    assert output[0] == 'followup_status: rejected'

    app = SimpleNamespace(
        lifecycle_store=SimpleNamespace(
            load=lambda: SimpleNamespace(
                phase='stopping',
                desired_state='stopped',
                shutdown_intent='kill',
            )
        )
    )
    assert rejection_for_request(app, 'followup') == 'ccbd is unavailable: lifecycle_stopping'


def test_followup_cli_service_uses_bounded_rpc_timeout(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Client:
        def with_timeout(self, timeout_s):
            calls.append(('timeout', timeout_s))
            return self

        def followup(self, job_id, message):
            calls.append(('followup', (job_id, message)))
            return {'status': 'injected'}

    monkeypatch.setattr(
        followup_service,
        'invoke_mounted_daemon',
        lambda context, *, allow_restart_stale, request_fn: request_fn(Client()),
    )
    result = followup_service.active_job_followup(
        SimpleNamespace(),
        ParsedFollowupCommand(project=None, job_id='job_1', message='correct'),
    )
    assert result['status'] == 'injected'
    assert calls == [('timeout', 5.0), ('followup', ('job_1', 'correct'))]
