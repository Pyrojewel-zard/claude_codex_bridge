from __future__ import annotations

from provider_backends.session_start import SessionStartDecision, SessionStartReason
from runtime_observability import record_startup_operations

from .session_paths import (
    agent_session_path,
    load_linked_continuation_session_id,
    load_resume_session_id,
    preferred_session_path,
    read_session_payload,
    resolve_linked_continuation_payload,
    resolve_resume_payload,
)


def resolve_session_start(
    spec,
    runtime_dir,
    *,
    restore,
    profile,
    authority_fingerprint_fn,
    memory_fingerprint_fn,
    resume_fn,
    linked_fn=None,
    supports_fork_fn=None,
) -> tuple[SessionStartDecision, list[str]]:
    """Resolve once; keep sensitive command arguments outside the decision.

    Custom loaders retain their original arguments and invocation semantics.
    Only the native pair shares a payload; durable repair still rereads under
    its existing lock. Nothing here caches absence across launch commands.
    """
    if not restore:
        return SessionStartDecision(SessionStartReason.NEW_EXPLICIT), []
    native = resume_fn is load_resume_session_id and linked_fn in (
        None, load_linked_continuation_session_id,
    )
    if native:
        path = preferred_session_path(spec, runtime_dir)
        if path is None:
            if agent_session_path(spec, runtime_dir) is None:
                return SessionStartDecision(SessionStartReason.UNKNOWN_INVALID), []
            record_startup_operations({'session_decision_no_binding_count': 1})
            return SessionStartDecision(SessionStartReason.NEW_NO_BINDING), []
        data = read_session_payload(path)
        if not data:
            record_startup_operations({'session_decision_history_unusable_count': 1})
            return SessionStartDecision(SessionStartReason.UNKNOWN_INVALID), []

    # Authority errors must still abort startup, as in the compatibility path.
    # In particular, do not turn unreadable credentials into permission to start.
    fingerprint = authority_fingerprint_fn(profile, runtime_dir=runtime_dir)
    memory_fingerprint = memory_fingerprint_fn(runtime_dir)
    decision = SessionStartDecision(SessionStartReason.UNKNOWN_INVALID)
    if native:
        session_id, decision = resolve_resume_payload(
            path, data, runtime_dir=runtime_dir, profile=profile,
            current_fingerprint=fingerprint,
            current_memory_fingerprint=memory_fingerprint,
        )
    else:
        session_id = resume_fn(
            spec, runtime_dir, profile,
            current_fingerprint=fingerprint,
            current_memory_fingerprint=memory_fingerprint,
        )
    if session_id:
        return SessionStartDecision(SessionStartReason.RESUME), ['resume', session_id]
    if linked_fn is not None:
        continuation_id = (
            resolve_linked_continuation_payload(path, data, current_fingerprint=fingerprint)
            if native else linked_fn(spec, runtime_dir, current_fingerprint=fingerprint)
        )
        if continuation_id:
            if supports_fork_fn is not None and supports_fork_fn():
                return SessionStartDecision(SessionStartReason.FORK), ['fork', continuation_id]
            decision = SessionStartDecision(SessionStartReason.NEW_INCOMPATIBLE)
    return decision, []
