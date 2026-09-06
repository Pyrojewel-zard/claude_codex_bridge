from __future__ import annotations

import time


def deadline_after(timeout_s: float) -> float:
    """Return an absolute monotonic deadline for one startup transaction."""
    return time.monotonic() + max(0.0, float(timeout_s))


def remaining_budget(deadline: float) -> float:
    """Return non-negative remaining budget without consulting wall time."""
    return max(0.0, float(deadline) - time.monotonic())


def bounded_timeout(deadline: float, requested_s: float) -> float:
    """Cap a child/RPC timeout by the current transaction budget."""
    return min(max(0.0, float(requested_s)), remaining_budget(deadline))


__all__ = ['bounded_timeout', 'deadline_after', 'remaining_budget']
