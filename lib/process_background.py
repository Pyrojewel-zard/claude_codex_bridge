from __future__ import annotations

import os
import subprocess


def background_process_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {'start_new_session': True}
    if os.name == 'nt':
        flags = (
            _subprocess_flag('CREATE_NEW_PROCESS_GROUP', 0x00000200)
            | _subprocess_flag('DETACHED_PROCESS', 0x00000008)
            | _subprocess_flag('CREATE_NO_WINDOW', 0x08000000)
        )
        kwargs['creationflags'] = flags
    return kwargs


def no_window_process_kwargs() -> dict[str, object]:
    if os.name != 'nt':
        return {}
    return {'creationflags': _subprocess_flag('CREATE_NO_WINDOW', 0x08000000)}


def _subprocess_flag(name: str, fallback: int) -> int:
    return int(getattr(subprocess, name, fallback) or fallback)


__all__ = ['background_process_kwargs', 'no_window_process_kwargs']
