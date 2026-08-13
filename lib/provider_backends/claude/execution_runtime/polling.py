from __future__ import annotations

import os
import re
from dataclasses import replace

from ccbd.system import parse_utc_timestamp
from completion.models import CompletionConfidence, CompletionDecision, CompletionStatus
from provider_execution.active import (
    ensure_active_pane_alive,
    prepare_active_poll_without_liveness,
)
from provider_execution.base import ProviderPollResult, ProviderSubmission

from .event_reading import (
    is_turn_boundary_event,
    read_events,
    terminal_api_error_payload,
)
from .hook_results import poll_exact_hook
from .hook_results_runtime import (
    load_strict_exact_hook_evidence,
    poll_hook_event,
)
from .start import looks_ready, send_prompt, state_session_path
from .state_machine import (
    apply_session_rotation,
    build_poll_state,
    finalize_poll_result,
    handle_assistant_event,
    handle_prompt_lifecycle_event,
    handle_system_event,
    handle_user_event,
    is_top_level_user_prompt,
)


def poll_submission(
    adapter,
    submission: ProviderSubmission,
    *,
    now: str,
) -> ProviderPollResult | None:
    del adapter
    prepared = _prepare_submission_poll(submission, now=now)
    if prepared is None or isinstance(prepared, ProviderPollResult):
        return prepared
    prompt_dispatch = _dispatch_deferred_prompt(
        submission,
        prepared=prepared,
        now=now,
    )
    if isinstance(prompt_dispatch, ProviderPollResult):
        return prompt_dispatch
    dispatch_items = ()
    if isinstance(prompt_dispatch, ProviderSubmission):
        submission = prompt_dispatch
    reply_delivery_terminal = _reply_delivery_terminal_if_dispatched(submission, now=now)
    if reply_delivery_terminal is not None:
        return _merge_poll_result_items(reply_delivery_terminal, prefix_items=dispatch_items)
    hook_result = poll_exact_hook(submission, now=now) if _prompt_completion_is_eligible(submission) else None
    if hook_result is None:
        hook_result = _orphaned_exact_hook(submission, prepared=prepared, now=now)
    if hook_result is not None:
        return _merge_poll_result_items(hook_result, prefix_items=dispatch_items)
    pane_dead_result = _ensure_prepared_pane_alive(submission, prepared=prepared, now=now)
    if pane_dead_result is not None:
        return _merge_poll_result_items(pane_dead_result, prefix_items=dispatch_items)
    state = submission.runtime_state.get("state") or {}
    poll = build_poll_state(submission)
    state = _poll_event_batches(submission, prepared.reader, poll, state=state, now=now)
    if isinstance(state, ProviderPollResult):
        return _merge_poll_result_items(state, prefix_items=dispatch_items)
    pane_terminal = _idle_pane_round_result_terminal(
        submission,
        prepared=prepared,
        poll=poll,
        state=state,
        now=now,
    )
    if pane_terminal is not None:
        return _merge_poll_result_items(pane_terminal, prefix_items=dispatch_items)
    # Bounded one-time activation retry: re-send Enter once for a prompt that was
    # pasted but never activated (see _maybe_resend_activation_enter).
    activation_retry = _maybe_resend_activation_enter(
        submission,
        prepared=prepared,
        poll=poll,
        now=now,
    )
    if activation_retry is not None:
        submission = activation_retry
    return _merge_poll_result_items(
        finalize_poll_result(submission, poll, state=state),
        prefix_items=dispatch_items,
    )


_ROUND_RESULT_RE = re.compile(
    r"(?:^|\n)\s*[●•⏺]\s*round\s+result\s*:\s*"
    r"(pass|partial|replan_required|blocked)\b",
    re.IGNORECASE,
)


def _idle_pane_round_result_terminal(
    submission: ProviderSubmission,
    *,
    prepared,
    poll,
    state: dict[str, object],
    now: str,
) -> ProviderPollResult | None:
    """Recover a parser-enforced round result omitted from Claude's event log.

    Some Claude-compatible endpoints render the final answer and return to the
    input box without persisting a final assistant text event or firing Stop.
    The request anchor, result, and idle prompt must all be visible in order in
    the same pane snapshot; no elapsed-time inference is used.
    """
    if submission.agent_name != "ccb_round_reviewer":
        return None
    if poll.reached_turn_boundary or not poll.anchor_seen or not poll.request_anchor:
        return None
    get_pane_content = getattr(prepared.backend, "get_pane_content", None)
    if not callable(get_pane_content):
        return None
    try:
        pane_text = str(get_pane_content(prepared.pane_id, lines=2000) or "")
    except Exception:
        return None
    anchored = _pane_text_after_latest_anchor(pane_text, poll.request_anchor)
    if anchored is None:
        return None
    matches = tuple(_ROUND_RESULT_RE.finditer(anchored))
    if not matches:
        return None
    match = matches[-1]
    after_result = anchored[match.end() :]
    if not _has_idle_input_box(after_result):
        return None

    round_result = match.group(1).lower()
    reply = f"round result: {round_result}"
    updated = replace(
        submission,
        reply=reply,
        runtime_state={
            **submission.runtime_state,
            "state": state,
            "next_seq": poll.next_seq,
            "anchor_seen": poll.anchor_seen,
            "reply_buffer": reply,
            "raw_buffer": poll.raw_buffer,
            "session_path": poll.session_path,
            "last_assistant_uuid": poll.last_assistant_uuid,
            "active_assistant_message_id": poll.active_assistant_message_id,
            "active_assistant_text": poll.active_assistant_text,
            "active_assistant_stop_reason": poll.active_assistant_stop_reason,
            "active_assistant_has_tool_use": poll.active_assistant_has_tool_use,
            "terminal_reply": reply,
            "prompt_enqueued": poll.prompt_enqueued,
            "queue_dequeue_observed": poll.queue_dequeue_observed,
            "prompt_activated": poll.prompt_activated,
            "prompt_enqueue_uuid": poll.prompt_enqueue_uuid,
            "prompt_activation_uuid": poll.prompt_activation_uuid,
        },
    )
    decision = CompletionDecision(
        terminal=True,
        status=CompletionStatus.COMPLETED,
        reason="claude_idle_pane_round_result",
        confidence=CompletionConfidence.OBSERVED,
        reply=reply,
        anchor_seen=True,
        reply_started=True,
        reply_stable=True,
        provider_turn_ref=poll.request_anchor,
        source_cursor=None,
        finished_at=now,
        diagnostics={
            "completion_source": "idle_pane_round_result",
            "completion_fallback_source": "terminal_capture",
            "completion_fallback_kind": "provider_declared",
            "terminal_capture_role": "provider_declared_fallback",
            "pane_id": prepared.pane_id,
            "round_result": round_result,
            "session_event_final_text_missing": True,
        },
    )
    return ProviderPollResult(submission=updated, items=tuple(poll.items), decision=decision)


def _pane_text_after_latest_anchor(text: str, request_anchor: str) -> str | None:
    index = text.rfind(request_anchor)
    if index < 0:
        return None
    return text[index + len(request_anchor) :]


def _has_idle_input_box(text: str) -> bool:
    if "esc to interrupt" in text.lower():
        return False
    for line in text.splitlines():
        normalized = line.replace("\xa0", " ").strip()
        if normalized.startswith("❯") and not normalized[1:].strip():
            return True
        if re.fullmatch(r"[│|]\s*[>❯]\s*[│|]", normalized):
            return True
    return False


def _prepare_submission_poll(
    submission: ProviderSubmission,
    *,
    now: str,
):
    prepared = prepare_active_poll_without_liveness(submission, now=now)
    return prepared


def _dispatch_deferred_prompt(
    submission: ProviderSubmission,
    *,
    prepared,
    now: str,
) -> ProviderPollResult | ProviderSubmission | None:
    if bool(submission.runtime_state.get("prompt_sent", True)):
        return None
    if not _prompt_delivery_due(submission, backend=prepared.backend, pane_id=prepared.pane_id, now=now):
        if bool(submission.runtime_state.get("prompt_deferred_for_ready", False)):
            return None
        return replace(
            submission,
            runtime_state={
                **submission.runtime_state,
                "prompt_deferred_for_ready": True,
            },
        )
    prompt = str(submission.runtime_state.get("prompt_text") or "")
    send_prompt(prepared.backend, prepared.pane_id, prompt)
    anchor_seen = bool(submission.runtime_state.get("anchor_seen", False))
    updated = replace(
        submission,
        runtime_state={
            **submission.runtime_state,
            "prompt_sent": True,
            "prompt_sent_at": now,
            "anchor_seen": anchor_seen,
            "prompt_activated": bool(submission.runtime_state.get("prompt_activated", False)),
            "prompt_deferred_for_ready": False,
            "prompt_anchor_emitted_at": "",
        },
    )
    return updated


def _prompt_completion_is_eligible(submission: ProviderSubmission) -> bool:
    state = submission.runtime_state
    if bool(state.get("no_wrap", False)):
        return True
    if "prompt_activated" in state:
        return bool(state.get("prompt_activated", False) and state.get("anchor_seen", False))
    if state.get("prompt_anchor_emitted_at"):
        return False
    return bool(state.get("anchor_seen", False))


_ORPHANED_HOOK_GRACE_S = 180.0


def _orphaned_exact_hook(
    submission: ProviderSubmission,
    *,
    prepared,
    now: str,
) -> ProviderPollResult | None:
    """Recover a completed turn whose transcript anchor was missed.

    This bypasses prompt-activation gating only after independent artifact,
    session, time, and idle-pane proof. Missing proof always keeps the normal
    event-log path authoritative.
    """
    if bool(submission.runtime_state.get("no_wrap", False)):
        return None
    evidence = load_strict_exact_hook_evidence(submission, now=now)
    if evidence is None:
        return None
    try:
        age_s = (parse_utc_timestamp(now) - evidence.event_at).total_seconds()
    except Exception:
        return None
    if age_s < _ORPHANED_HOOK_GRACE_S:
        return None
    if not _pane_observably_idle(prepared):
        return None
    return poll_hook_event(
        submission,
        context=evidence.context,
        event=evidence.event,
        now=now,
        extra_diagnostics={
            "completion_fallback_source": "orphaned_exact_hook",
            "request_anchor_observation_missed": True,
            "orphaned_hook_grace_s": _ORPHANED_HOOK_GRACE_S,
            "orphaned_hook_age_s": age_s,
        },
    )


def _pane_observably_idle(prepared) -> bool:
    backend = getattr(prepared, "backend", None)
    get_pane_content = getattr(backend, "get_pane_content", None)
    if not callable(get_pane_content):
        return False
    try:
        text = str(get_pane_content(getattr(prepared, "pane_id", None), lines=80) or "")
    except Exception:
        return False
    if "esc to interrupt" in text.lower():
        return False
    return _has_idle_input_box(text)


def _activation_grace_s() -> float:
    """Seconds to wait after dispatch before a lost Enter is retried once."""
    try:
        return max(0.0, float(os.environ.get("CCB_CLAUDE_ACTIVATION_GRACE_S", 6.0)))
    except Exception:
        return 6.0


def _activation_retry_window() -> tuple[float, float]:
    """Bounded retry window ``[start_s, end_s)`` measured from ``prompt_sent_at``.

    The retry Enter is only eligible inside this window: not before ``start_s``
    (the initial paste may still be inserting, so a second Enter could be eaten
    or become a stray newline) and not after ``end_s`` (give up; an operator
    intervenes manually). Default ``[6.0, 12.0)`` for
    ``CCB_CLAUDE_ACTIVATION_GRACE_S=6``.
    """
    grace_s = _activation_grace_s()
    return grace_s, grace_s * 2.0


def _elapsed_since(from_at: str, now: str) -> float | None:
    try:
        return (parse_utc_timestamp(now) - parse_utc_timestamp(from_at)).total_seconds()
    except Exception:
        return None


def _pane_holds_current_job_marker(text: str, submission: ProviderSubmission) -> bool:
    """True when the pane text still shows a recognizable marker of *this* job.

    The wrapped prompt is ``CCB_REQ_ID: <request_anchor>``; ``no_wrap`` prompts
    carry the anchor (job id) directly. An empty composer or a different job's
    text must not match, so a retry Enter can never submit the wrong prompt.
    """
    if not str(text or ""):
        return False
    anchor = str(
        submission.runtime_state.get("request_anchor")
        or submission.job_id
        or ""
    ).strip()
    if not anchor:
        return False
    if f"CCB_REQ_ID: {anchor}" in text:
        return True
    if "CCB_BEGIN" in text and anchor in text:
        return True
    return anchor in text


def _maybe_resend_activation_enter(
    submission: ProviderSubmission,
    *,
    prepared,
    poll,
    now: str,
) -> ProviderSubmission | None:
    """Bounded one-time activation Enter re-send for a sent-but-stuck prompt.

    Root cause: tmux ``paste-buffer`` returns once bytes hit the pty, but the
    Claude TUI consumes/renders a bracketed-paste stream asynchronously. For a
    long (often multi-KB Unicode) prompt the initial Enter, sent
    ``CCB_TMUX_ENTER_DELAY`` later, can land while the composer is still
    inserting and be swallowed — the prompt stays in the composer, no request
    anchor ever appears, and the job hangs in ``delivering`` until an operator
    presses Enter manually.

    There is no paste ACK in the TUI, so the request anchor is the only real
    activation proof. This monitor re-sends Enter **at most once**, and only
    while every one of these holds:

    * the prompt was already dispatched (``prompt_sent``) with a timestamp;
    * the current job is not yet activated (no ``prompt_activated``/``anchor_seen``);
    * the elapsed time since dispatch is inside the bounded grace window;
    * the pane is not busy (no ``esc to interrupt``) and still holds this job's
      recognizable prompt/anchor text (an empty composer cannot match);
    * this job has not already re-sent Enter (``activation_enter_count < 1``).

    Any failing guard disables the retry: activated, empty composer, busy pane,
    text that does not belong to this job, an expired grace window, or a prior
    re-send. On a successful ``send_key`` the runtime state bumps
    ``activation_enter_count`` so later polls never re-send. (``_has_idle_input_box``
    only recognizes the empty ready box and would never fire for the stuck
    composer that still holds the prompt text, so the marker check is the
    effective "still this job, still submittable" guard.)
    """
    state = submission.runtime_state
    if not bool(state.get("prompt_sent", False)):
        return None
    prompt_sent_at = str(state.get("prompt_sent_at") or "").strip()
    if not prompt_sent_at:
        return None
    if int(state.get("activation_enter_count", 0) or 0) >= 1:
        return None
    if poll is not None and (
        bool(getattr(poll, "anchor_seen", False))
        or bool(getattr(poll, "prompt_activated", False))
    ):
        return None
    elapsed = _elapsed_since(prompt_sent_at, now)
    if elapsed is None:
        return None
    grace_start, grace_end = _activation_retry_window()
    if elapsed < grace_start or elapsed >= grace_end:
        return None
    pane_id = getattr(prepared, "pane_id", None)
    backend = getattr(prepared, "backend", None)
    get_pane_content = getattr(backend, "get_pane_content", None)
    send_key = getattr(backend, "send_key", None)
    if not pane_id or not callable(get_pane_content) or not callable(send_key):
        return None
    try:
        pane_text = str(get_pane_content(pane_id, lines=200) or "")
    except Exception:
        return None
    if "esc to interrupt" in pane_text.lower():
        return None
    if not _pane_holds_current_job_marker(pane_text, submission):
        return None
    try:
        sent = send_key(pane_id, "Enter")
    except Exception:
        return None
    if not sent:
        return None
    return replace(
        submission,
        runtime_state={
            **state,
            "activation_enter_count": int(state.get("activation_enter_count", 0) or 0) + 1,
            "activation_enter_at": now,
        },
    )


def _merge_poll_result_items(result: ProviderPollResult, *, prefix_items: tuple) -> ProviderPollResult:
    if not prefix_items:
        return result
    return ProviderPollResult(
        submission=result.submission,
        items=tuple(prefix_items) + tuple(result.items),
        decision=result.decision,
    )


def _prompt_delivery_due(
    submission: ProviderSubmission,
    *,
    backend: object,
    pane_id: str,
    now: str,
) -> bool:
    get_pane_content = getattr(backend, "get_pane_content", None)
    if not callable(get_pane_content):
        return True
    try:
        text = str(get_pane_content(pane_id, lines=120) or "")
    except Exception:
        return True
    if looks_ready(text):
        return True
    # Reply delivery prefers an observed ready prompt, but it must not deadlock
    # a serial mailbox queue forever when the prompt detector never converges.
    return _ready_wait_timed_out(submission, now=now)


def _reply_delivery_terminal_if_dispatched(
    submission: ProviderSubmission,
    *,
    now: str,
) -> ProviderPollResult | None:
    if not bool(submission.runtime_state.get("reply_delivery_complete_on_dispatch", False)):
        return None
    if not bool(submission.runtime_state.get("prompt_sent", False)):
        return None
    provider_turn_ref = str(
        submission.runtime_state.get("request_anchor")
        or submission.runtime_state.get("pane_id")
        or submission.job_id
    ).strip()
    decision = CompletionDecision(
        terminal=True,
        status=CompletionStatus.COMPLETED,
        reason="reply_delivery_sent",
        confidence=CompletionConfidence.OBSERVED,
        reply="",
        anchor_seen=True,
        reply_started=False,
        reply_stable=True,
        provider_turn_ref=provider_turn_ref or submission.job_id,
        source_cursor=None,
        finished_at=now,
        diagnostics={
            "reply_delivery": True,
            "delivery_status": "sent",
            "provider": submission.provider,
            "submission_mode": "active",
        },
    )
    return ProviderPollResult(submission=submission, decision=decision)


def _ready_wait_timed_out(submission: ProviderSubmission, *, now: str) -> bool:
    started_at = str(submission.runtime_state.get("ready_wait_started_at") or "").strip()
    if not started_at:
        return True
    try:
        timeout_s = float(submission.runtime_state.get("ready_timeout_s", 8.0))
    except Exception:
        timeout_s = 8.0
    try:
        elapsed = (parse_utc_timestamp(now) - parse_utc_timestamp(started_at)).total_seconds()
    except Exception:
        return True
    return elapsed >= max(0.0, timeout_s)


def _ensure_prepared_pane_alive(submission: ProviderSubmission, *, prepared, now: str):
    pane_dead_result = ensure_active_pane_alive(
        submission,
        backend=prepared.backend,
        pane_id=prepared.pane_id,
        now=now,
    )
    if pane_dead_result is not None:
        return pane_dead_result
    return None


def _poll_event_batches(
    submission: ProviderSubmission,
    reader,
    poll,
    *,
    state: dict,
    now: str,
):
    while True:
        batch = _read_event_batch(submission, reader, poll, state=state, now=now)
        if isinstance(batch, ProviderPollResult):
            return batch
        state, has_events = batch
        if not has_events or poll.reached_turn_boundary:
            return state


def _read_event_batch(
    submission: ProviderSubmission,
    reader,
    poll,
    *,
    state: dict,
    now: str,
):
    events, state = read_events(reader, state)
    apply_session_rotation(
        submission,
        poll,
        new_session_path=state_session_path(state),
        now=now,
    )
    if not events:
        return state, False
    event_result = _process_events(submission, poll, events, state=state, now=now)
    if event_result is not None:
        return event_result
    return state, True


def _process_events(
    submission: ProviderSubmission,
    poll,
    events: list[dict],
    *,
    state: dict,
    now: str,
) -> ProviderPollResult | None:
    for event in events:
        result = _process_event(submission, poll, event, state=state, now=now)
        if result is not None:
            return result
        if poll.reached_turn_boundary:
            break
    return None


def _process_event(
    submission: ProviderSubmission,
    poll,
    event: dict,
    *,
    state: dict,
    now: str,
) -> ProviderPollResult | None:
    role = str(event.get("role") or "")
    if role == "prompt_lifecycle":
        handle_prompt_lifecycle_event(submission, poll, event, now=now)
        return None
    if role == "user":
        if is_top_level_user_prompt(event):
            handle_user_event(submission, poll, text=str(event.get("text") or ""), now=now)
        return None
    if role == "system" and poll.anchor_seen:
        return handle_system_event(submission, poll, event, now=now, state=state)
    if role == "assistant" and poll.anchor_seen:
        handle_assistant_event(submission, poll, event, now=now)
    return None


__all__ = [
    "is_turn_boundary_event",
    "poll_exact_hook",
    "poll_submission",
    "read_events",
    "terminal_api_error_payload",
]
