from __future__ import annotations

import os
from pathlib import Path


def default_state_dir() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    if configured:
        return Path(configured).expanduser() / "codex-reconnect"
    return Path.home() / ".local" / "state" / "codex-reconnect"
