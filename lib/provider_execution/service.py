from __future__ import annotations

from threading import RLock

from ccbd.api_models import JobRecord
from completion.models import CompletionDecision

from fault_injection import FaultInjectionService
from .base import ProviderRuntimeContext, ProviderSubmission
from .registry import ProviderExecutionRegistry
from .state_store import ExecutionStateStore
from .service_state import ExecutionServiceRuntimeState, ExecutionServiceStateMixin
from .service_runtime import (
    ExecutionRestoreResult,
    ExecutionUpdate,
    acknowledge,
    acknowledge_item,
    persist_submission,
    poll_updates,
    restore_submission,
    active_runtime_snapshots,
)
from .common import interrupt_and_clear_runtime_target
from .followups import (
    ActiveFollowupCapability,
    ActiveFollowupRequest,
    ActiveFollowupResult,
    unsupported_active_followup_capability,
)


class ExecutionService(ExecutionServiceStateMixin):
    def __init__(
        self,
        registry: ProviderExecutionRegistry,
        *,
        clock,
        state_store: ExecutionStateStore | None = None,
        fault_injection: FaultInjectionService | None = None,
    ) -> None:
        self._runtime_state = ExecutionServiceRuntimeState(
            registry=registry,
            clock=clock,
            state_store=state_store,
            fault_injection=fault_injection,
            active={},
            starting={},
            runtime_contexts={},
            pending_replays={},
            active_transition_lock=RLock(),
        )

    def start(self, job: JobRecord, *, runtime_context: ProviderRuntimeContext | None = None) -> ProviderSubmission | None:
        start_token = object()
        with self._active_transition_lock:
            now = self._clock()
            if self._fault_injection is not None:
                injected = self._fault_injection.consume_for_job(job, now=now)
                if injected is not None:
                    items, decision = self._fault_injection.build_terminal_replay(job, injected)
                    self._runtime_contexts[job.job_id] = runtime_context
                    self._pending_replays[job.job_id] = (items, decision)
                    return None
            adapter = self._registry.get(job.provider)
            if adapter is None:
                return None
            self._starting[job.job_id] = start_token
        try:
            submission = adapter.start(job, context=runtime_context, now=now)
        except Exception:
            with self._active_transition_lock:
                if self._starting.get(job.job_id) is start_token:
                    self._starting.pop(job.job_id, None)
            raise
        with self._active_transition_lock:
            if self._starting.get(job.job_id) is start_token:
                self._starting.pop(job.job_id, None)
                self._active[job.job_id] = submission
                self._runtime_contexts[job.job_id] = runtime_context
                self._persist(job.job_id)
                return submission
        _cancel_submission(adapter, submission)
        return None

    def cancel(self, job_id: str) -> None:
        with self._active_transition_lock:
            self._starting.pop(job_id, None)
            submission = self._active.pop(job_id, None)
            self._runtime_contexts.pop(job_id, None)
            self._pending_replays.pop(job_id, None)
            if self._state_store is not None:
                self._state_store.remove(job_id)
        if submission is not None:
            adapter = self._registry.get(submission.provider)
            _cancel_submission(adapter, submission)

    def finish(self, job_id: str) -> None:
        with self._active_transition_lock:
            self._starting.pop(job_id, None)
            self._active.pop(job_id, None)
            self._runtime_contexts.pop(job_id, None)
            self._pending_replays.pop(job_id, None)
            if self._state_store is not None:
                self._state_store.remove(job_id)

    def acknowledge(self, job_id: str) -> None:
        with self._active_transition_lock:
            acknowledge(self, job_id)

    def acknowledge_item(self, job_id: str, *, event_seq: int | None) -> None:
        with self._active_transition_lock:
            acknowledge_item(self, job_id, event_seq=event_seq)

    def restore(self, job: JobRecord, *, runtime_context: ProviderRuntimeContext | None = None) -> ExecutionRestoreResult:
        with self._active_transition_lock:
            return restore_submission(self, job, runtime_context=runtime_context)

    def poll(self) -> tuple[ExecutionUpdate, ...]:
        return poll_updates(self)

    def active_runtime_snapshots(self) -> tuple[dict[str, object], ...]:
        with self._active_transition_lock:
            return active_runtime_snapshots(self)

    def active_followup_capability(self, job_id: str) -> ActiveFollowupCapability:
        with self._active_transition_lock:
            submission = self._active.get(job_id)
            if submission is None:
                if job_id in self._starting:
                    return unsupported_active_followup_capability(
                        'active_submission_starting',
                        mechanism='starting_active_submission',
                    )
                persisted = self._state_store.load(job_id) if self._state_store is not None else None
                if persisted is not None and persisted.pending_decision is not None:
                    return unsupported_active_followup_capability(
                        'provider_terminal_pending',
                        mechanism='terminal_pending',
                    )
                return unsupported_active_followup_capability(
                    'active_submission_missing',
                    mechanism='missing_active_submission',
                )
            adapter = self._registry.get(submission.provider)
            capability_fn = getattr(adapter, 'active_followup_capability', None) if adapter is not None else None
            if not callable(capability_fn):
                return unsupported_active_followup_capability(
                    'provider_active_followup_unsupported',
                    diagnostics={'provider': submission.provider},
                )
            capability = capability_fn(submission)
            if not isinstance(capability, ActiveFollowupCapability):
                return unsupported_active_followup_capability(
                    'provider_active_followup_capability_invalid',
                    diagnostics={'provider': submission.provider},
                )
            return capability

    def inject_active_followup(self, request: ActiveFollowupRequest) -> ActiveFollowupResult:
        with self._active_transition_lock:
            submission = self._active.get(request.job_id)
            if submission is None:
                if request.job_id in self._starting:
                    return ActiveFollowupResult(
                        submission=None,
                        status='rejected',
                        reason='active_submission_starting',
                        mechanism='starting_active_submission',
                    )
                persisted = self._state_store.load(request.job_id) if self._state_store is not None else None
                reason = 'provider_terminal_pending' if persisted is not None and persisted.pending_decision is not None else 'active_submission_missing'
                return ActiveFollowupResult(
                    submission=None,
                    status='terminal',
                    reason=reason,
                    mechanism='missing_active_submission',
                )
            adapter = self._registry.get(submission.provider)
            inject_fn = getattr(adapter, 'inject_active_followup', None) if adapter is not None else None
            if not callable(inject_fn):
                return ActiveFollowupResult(
                    submission=submission,
                    status='rejected',
                    reason='provider_active_followup_unsupported',
                    mechanism='unsupported',
                )
            result = inject_fn(submission, request=request, now=self._clock())
            if not isinstance(result, ActiveFollowupResult):
                return ActiveFollowupResult(
                    submission=submission,
                    status='rejected',
                    reason='provider_active_followup_result_invalid',
                    mechanism='invalid_adapter_result',
                )
            updated = result.submission
            if updated is not None:
                if updated.job_id != submission.job_id or updated.provider != submission.provider:
                    return ActiveFollowupResult(
                        submission=submission,
                        status='rejected',
                        reason='provider_active_followup_changed_binding',
                        mechanism=result.mechanism,
                    )
                self._active[request.job_id] = updated
                self._persist(request.job_id)
            return result

    def _persist(
        self,
        job_id: str,
        *,
        pending_items: tuple = (),
        applied_event_seqs: tuple[int, ...] = (),
        pending_decision=None,
    ) -> None:
        persist_submission(
            self,
            job_id,
            pending_decision=pending_decision,
            pending_items=pending_items,
            applied_event_seqs=applied_event_seqs,
        )


def interrupt_active_submission(submission: ProviderSubmission) -> None:
    backend = submission.runtime_state.get("backend")
    pane_id = str(submission.runtime_state.get("pane_id") or "").strip()
    if backend is None or not pane_id:
        return
    interrupt_and_clear_runtime_target(backend, pane_id)


def _cancel_submission(adapter, submission: ProviderSubmission) -> None:
    provider_cancel = getattr(adapter, 'cancel', None) if adapter is not None else None
    if callable(provider_cancel):
        provider_cancel(submission)
    interrupt_active_submission(submission)


__all__ = ["ExecutionRestoreResult", "ExecutionService", "ExecutionUpdate"]
