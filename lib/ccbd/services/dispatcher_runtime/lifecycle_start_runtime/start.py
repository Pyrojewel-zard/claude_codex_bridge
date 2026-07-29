from __future__ import annotations

from dataclasses import replace

from agents.models import AgentState
from completion.models import CompletionConfidence, CompletionDecision, CompletionStatus
from provider_core.registry import TEST_DOUBLE_PROVIDER_NAMES

from ccbd.api_models import JobRecord, JobStatus, TargetKind

from ..cancel_flags import cancel_flag_path
from ..context import build_job_runtime_context
from ..records import append_event, append_job
from ..reply_delivery import is_reply_delivery_job
from ..reply_delivery_runtime.start_completion import (
    complete_reply_delivery_after_start,
)
from ..runtime_state import sync_runtime
from .models import QueuedTargetSlot

_NATIVE_CANCEL_NOTICE_FREE_PROVIDERS = frozenset({'pi'})


def write_running_snapshot(dispatcher, running: JobRecord, *, started_at: str) -> None:
    if dispatcher._completion_tracker is not None:
        tracked = dispatcher._completion_tracker.start(running, started_at=started_at)
        dispatcher._snapshot_writer.write_completion(
            job_id=running.job_id,
            agent_name=running.agent_name,
            profile_family=dispatcher._profile_family_for_job(running),
            state=tracked.state,
            decision=tracked.decision,
            updated_at=started_at,
        )
        return
    dispatcher._snapshot_writer.write_pending(
        job_id=running.job_id,
        agent_name=running.agent_name,
        profile_family=dispatcher._profile_family_for_job(running),
    )


def start_running_job(
    dispatcher,
    current: JobRecord,
    *,
    slot: QueuedTargetSlot,
    started_at: str | None = None,
) -> JobRecord:
    started_at = started_at or dispatcher._clock()
    running = replace(current, status=JobStatus.RUNNING, updated_at=started_at)
    if dispatcher._message_bureau is not None:
        dispatcher._message_bureau.mark_attempt_started(running, started_at=started_at)
    append_job(dispatcher, running)
    append_event(dispatcher, running, 'job_started', {'status': JobStatus.RUNNING.value}, timestamp=started_at)
    write_running_snapshot(dispatcher, running, started_at=started_at)
    runtime_context = build_job_runtime_context(running, slot.runtime)
    dispatcher._state.mark_active_for(running.target_kind, running.target_name, running.job_id)
    if slot.requires_runtime_sync:
        sync_runtime(dispatcher, running.agent_name, state=AgentState.BUSY)
    submission = None
    if dispatcher._execution_service is not None and should_start_execution(dispatcher, running, runtime_context):
        try:
            submission = dispatcher._execution_service.start(
                with_cancel_flag_notice(dispatcher, running),
                runtime_context=runtime_context,
            )
        except Exception as exc:
            return fail_provider_start(dispatcher, running, exc, failed_at=dispatcher._clock())
    if is_reply_delivery_job(running) and dispatcher._execution_service is not None:
        return complete_reply_delivery_after_start(
            dispatcher,
            running,
            started_at=started_at,
            submission=submission,
        )
    return running


def fail_provider_start(dispatcher, running: JobRecord, exc: Exception, *, failed_at: str) -> JobRecord:
    diagnostics = {
        'error_type': type(exc).__name__,
        'provider': running.provider,
        'provider_start_error': str(exc),
    }
    append_event(
        dispatcher,
        running,
        'provider_start_failed',
        diagnostics,
        timestamp=failed_at,
    )
    decision = CompletionDecision(
        terminal=True,
        status=CompletionStatus.FAILED,
        reason='provider_start_failed',
        confidence=CompletionConfidence.EXACT,
        reply='',
        anchor_seen=False,
        reply_started=False,
        reply_stable=False,
        provider_turn_ref=None,
        source_cursor=None,
        finished_at=failed_at,
        diagnostics=diagnostics,
    )
    return dispatcher.complete(running.job_id, decision)


def with_cancel_flag_notice(dispatcher, running: JobRecord) -> JobRecord:
    """Append the cancel-flag protocol note to the prompt handed to execution.

    Only the in-memory copy passed to the execution service is modified; the
    stored job/message records keep the original body.
    """
    if running.target_kind is not TargetKind.AGENT or not running.agent_name:
        return running
    if is_reply_delivery_job(running):
        return running
    provider = str(running.provider or '').strip().lower()
    if provider in TEST_DOUBLE_PROVIDER_NAMES:
        return running
    if provider in _NATIVE_CANCEL_NOTICE_FREE_PROVIDERS:
        # Pi pane runs are interrupted through provider-native keys and Pi
        # headless runs through process termination. Asking the model to probe
        # a cancel flag before every step adds a tool call and uncached tokens
        # without strengthening either cancellation path.
        return running
    try:
        flag_path = cancel_flag_path(dispatcher._layout, running.agent_name, running.job_id)
    except Exception:
        return running
    notice = (
        "\n\n[ccb] Before each work step, check whether the file "
        f"`{flag_path}` exists. If it does, this task has been cancelled: "
        "stop immediately, reply with CANCELLED, and wait for new instructions."
    )
    return replace(running, request=replace(running.request, body=running.request.body + notice))


def should_start_execution(dispatcher, current: JobRecord, runtime_context) -> bool:
    if runtime_context is None:
        return False
    if not bool(getattr(dispatcher, '_require_actionable_runtime_binding_for_execution', False)):
        return True
    if str(current.provider or '').strip().lower() in TEST_DOUBLE_PROVIDER_NAMES:
        return True
    if current.target_kind is not TargetKind.AGENT:
        return True

    runtime_ref = str(runtime_context.runtime_ref or '').strip()
    backend_type = str(runtime_context.backend_type or '').strip().lower()
    if backend_type in {'headless', 'pty-backed'}:
        return True
    return ':' in runtime_ref


__all__ = ['fail_provider_start', 'should_start_execution', 'start_running_job', 'write_running_snapshot']
