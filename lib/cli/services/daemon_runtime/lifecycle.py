from __future__ import annotations

from datetime import datetime, timezone
import inspect
import time

from ccbd.models import LeaseHealth
from ccbd.startup_deadline import deadline_after, remaining_budget

from .models import CcbdServiceError, DaemonHandle
from .lifecycle_start import (
    DaemonStartState,
    finalize_daemon_start,
    mounted_control_plane_ready,
    poll_daemon_start_iteration,
)


def ensure_daemon_started(
    context,
    *,
    clear_shutdown_intent_fn,
    record_running_intent_fn,
    ensure_keeper_started_fn,
    inspect_daemon_fn,
    connect_compatible_daemon_fn,
    should_restart_unreachable_daemon_fn,
    restart_unreachable_daemon_fn,
    incompatible_daemon_error_fn,
    start_timeout_s: float,
    progress_stall_timeout_s: float,
) -> DaemonHandle:
    local_deadline = deadline_after(start_timeout_s)
    clear_shutdown_intent_fn(context)
    startup_requested = bool(record_running_intent_fn(context))
    ensure_keeper_with_budget = _budgeted_callable(
        ensure_keeper_started_fn,
        local_deadline=local_deadline,
        keyword='timeout_s',
    )
    state = DaemonStartState(
        keeper_started=bool(ensure_keeper_with_budget(context)),
        started=startup_requested,
    )
    transaction_deadline = None
    progress_deadline = None
    progress_marker = None

    while True:
        handle = poll_daemon_start_iteration(
            context,
            state=state,
            ensure_keeper_started_fn=ensure_keeper_with_budget,
            inspect_daemon_fn=inspect_daemon_fn,
            connect_compatible_daemon_fn=connect_compatible_daemon_fn,
            should_restart_unreachable_daemon_fn=should_restart_unreachable_daemon_fn,
            restart_unreachable_daemon_fn=restart_unreachable_daemon_fn,
        )
        if handle is not None:
            return handle
        _, _, inspection = inspect_daemon_fn(context)
        transaction_deadline = _resolve_transaction_deadline(
            inspection,
            existing_deadline=transaction_deadline,
        )
        progress_deadline, progress_marker = _resolve_progress_deadline(
            inspection,
            progress_stall_timeout_s=progress_stall_timeout_s,
            existing_deadline=progress_deadline,
            existing_marker=progress_marker,
        )
        if _startup_wait_exhausted(
            inspection,
            local_deadline=local_deadline,
            transaction_deadline=transaction_deadline,
            progress_deadline=progress_deadline,
        ):
            break
        time.sleep(min(0.05, remaining_budget(local_deadline)))

    return finalize_daemon_start(
        context,
        started=state.started,
        inspect_daemon_fn=inspect_daemon_fn,
        connect_compatible_daemon_fn=connect_compatible_daemon_fn,
        incompatible_daemon_error_fn=incompatible_daemon_error_fn,
        remaining_budget_s=remaining_budget(local_deadline),
    )


def connect_mounted_daemon(
    context,
    *,
    allow_restart_stale: bool,
    inspect_daemon_fn,
    connect_compatible_daemon_fn,
    ensure_daemon_started_fn,
    should_restart_unreachable_daemon_fn,
    incompatible_daemon_error_fn,
) -> DaemonHandle:
    _manager, _guard, inspection = inspect_daemon_fn(context)
    phase = _phase(inspection)
    if phase == 'mounted' and mounted_control_plane_ready(inspection):
        handle = connect_compatible_daemon_fn(context, inspection, restart_on_mismatch=allow_restart_stale)
        if handle is not None:
            return handle
    _manager, _guard, inspection = inspect_daemon_fn(context)
    phase = _phase(inspection)
    # start 命令（allow_restart_stale=True）是用户的显式启动意图：即使 lifecycle
    # desired_state=stopped（如 prestart kill -f 遗留 stop_all），也应通过
    # ensure_daemon_started 把意图恢复为 running 并拉起 ccbd，而不是直接报
    # lease_unmounted（2026-08-06 采集暴露）。
    if allow_restart_stale and (
        _should_wait_or_recover(inspection, should_restart_unreachable_daemon_fn)
        or _desired_state(inspection) == 'stopped'
    ):
        return ensure_daemon_started_fn(context)
    if phase == 'unmounted':
        raise CcbdServiceError('project ccbd is unmounted; run `ccb` first')
    if phase == 'starting':
        raise CcbdServiceError('project ccbd is starting; wait for keeper to finish startup')
    if phase == 'stopping':
        raise CcbdServiceError('project ccbd is stopping; wait for shutdown to finish')
    if phase == 'mounted' and mounted_control_plane_ready(inspection):
        handle = connect_compatible_daemon_fn(context, inspection, restart_on_mismatch=False)
        if handle is not None:
            return handle
        raise CcbdServiceError(incompatible_daemon_error_fn())
    failure_reason = str(getattr(inspection, 'last_failure_reason', '') or '').strip()
    if phase == 'failed' and failure_reason:
        raise CcbdServiceError(
            f'ccbd is unavailable: {inspection.reason}; lifecycle_failure: {failure_reason}'
        )
    if phase == 'mounted':
        stage = str(getattr(inspection, 'startup_stage', '') or '').strip()
        if stage:
            raise CcbdServiceError(f'ccbd is unavailable: lifecycle_mounted(stage={stage})')
    raise CcbdServiceError(f'ccbd is unavailable: {inspection.reason}')


def _should_wait_or_recover(inspection, should_restart_unreachable_daemon_fn) -> bool:
    phase = _phase(inspection)
    if _desired_state(inspection) != 'running':
        return False
    if phase in {'unmounted', 'starting', 'failed'}:
        return True
    if phase == 'mounted' and not mounted_control_plane_ready(inspection):
        return True
    return (
        phase == 'mounted'
        and (
            inspection.health in {LeaseHealth.MISSING, LeaseHealth.UNMOUNTED, LeaseHealth.STALE}
            or should_restart_unreachable_daemon_fn(inspection)
        )
    )


def _phase(inspection) -> str:
    phase = str(getattr(inspection, 'phase', '') or '').strip()
    if phase:
        return phase
    health = getattr(inspection, 'health', None)
    if health in {LeaseHealth.MISSING, LeaseHealth.UNMOUNTED}:
        return 'unmounted'
    if health is LeaseHealth.HEALTHY:
        return 'mounted'
    return 'failed'


def _desired_state(inspection) -> str:
    desired_state = str(getattr(inspection, 'desired_state', '') or '').strip()
    if desired_state:
        return desired_state
    return 'running'


def _startup_wait_exhausted(
    inspection,
    *,
    local_deadline: float,
    transaction_deadline: float | None,
    progress_deadline: float | None,
) -> bool:
    phase = _phase(inspection)
    now = time.monotonic()
    if now >= local_deadline:
        return True
    if phase == 'failed':
        return _desired_state(inspection) != 'running' or bool(
            str(getattr(inspection, 'last_failure_reason', '') or '').strip()
        )
    if phase != 'starting' and not (
        phase == 'mounted' and not mounted_control_plane_ready(inspection)
    ):
        return False
    if transaction_deadline is not None and now >= transaction_deadline:
        return True
    return progress_deadline is not None and now >= progress_deadline


def _resolve_transaction_deadline(inspection, *, existing_deadline: float | None) -> float | None:
    if existing_deadline is not None:
        return existing_deadline
    wall_deadline = _timestamp_seconds(getattr(inspection, 'startup_deadline_at', None))
    if wall_deadline is None:
        return None
    # The persisted timestamp is shared-process observability. Convert it once
    # at the observation boundary, then use only monotonic time while waiting.
    wall_remaining = wall_deadline - time.time()
    return time.monotonic() + max(0.0, wall_remaining)


def _resolve_progress_deadline(
    inspection,
    *,
    progress_stall_timeout_s: float,
    existing_deadline: float | None,
    existing_marker: str | None,
) -> tuple[float | None, str | None]:
    marker = str(getattr(inspection, 'last_progress_at', '') or '').strip() or None
    if marker == existing_marker:
        return existing_deadline, existing_marker
    if progress_stall_timeout_s <= 0.0:
        return None, marker
    wall_progress = _timestamp_seconds(marker)
    if wall_progress is None:
        return None, marker
    # Convert the persisted wall-clock progress marker once per marker change.
    # The wait loop itself remains monotonic even if wall time is adjusted.
    wall_remaining = wall_progress + float(progress_stall_timeout_s) - time.time()
    return time.monotonic() + max(0.0, wall_remaining), marker


def _budgeted_callable(fn, *, local_deadline: float, keyword: str):
    def invoke(context):
        timeout_s = remaining_budget(local_deadline)
        if timeout_s <= 0.0:
            return False
        try:
            parameters = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return fn(context)
        accepts_keyword = keyword in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_keyword:
            return fn(context, **{keyword: timeout_s})
        return fn(context)

    return invoke


def _timestamp_seconds(value: object) -> float | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        normalized = text[:-1] + '+00:00' if text.endswith('Z') else text
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


__all__ = ['connect_mounted_daemon', 'ensure_daemon_started']
