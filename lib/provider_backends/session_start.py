from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SessionStartReason(str, Enum):
    NEW_EXPLICIT = 'NEW_EXPLICIT'
    NEW_PRISTINE = 'NEW_PRISTINE'
    NEW_NO_BINDING = 'NEW_NO_BINDING'
    RESUME = 'RESUME'
    FORK = 'FORK'
    NEW_INCOMPATIBLE = 'NEW_INCOMPATIBLE'
    UNKNOWN_INVALID = 'UNKNOWN/INVALID'


@dataclass(frozen=True)
class SessionStartDecision:
    """Launch-local, redacted metadata; never a persisted absence cache."""

    reason: SessionStartReason


def create_pristine_managed_home(home: Path, *, binding_path: Path | None) -> bool:
    """Prove absence and win exclusive home creation in this transaction.

    Existing homes (including empty ones), dangling binding symlinks, and
    uncertain filesystem state must use normal restoration. The caller must
    supply an agent-managed home, never an ambient/source home.
    """
    if binding_path is None:
        return False
    try:
        binding_path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    else:
        return False
    try:
        home.mkdir(parents=True, exist_ok=False, mode=0o700)
    except OSError:
        return False
    # Recheck after creation: another writer may have published a binding.
    try:
        binding_path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        pass
    return False
