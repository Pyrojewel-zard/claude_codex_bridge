from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import time

from cli.kill_runtime.processes import is_pid_alive


@dataclass(frozen=True)
class HapiWrapperIdentity:
    session_id: str
    pid: int
    pgid: int
    path: Path


def wrapper_identity_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / 'hapi-wrapper.json'


def load_current_wrapper_identity(
    path: Path,
    *,
    is_pid_alive_fn=is_pid_alive,
    getpgid_fn=os.getpgid,
    read_environ_fn=None,
) -> HapiWrapperIdentity | None:
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        session_id = str(payload.get('sessionId') or '').strip()
        pid = int(payload.get('pid'))
        pgid = int(payload.get('pgid'))
    except (OSError, TypeError, ValueError, json.JSONDecodeError, AttributeError):
        return None
    if int(payload.get('schemaVersion') or 0) != 1 or not session_id or pid <= 1 or pgid <= 1:
        return None
    try:
        if not is_pid_alive_fn(pid) or int(getpgid_fn(pid)) != pgid:
            return None
    except Exception:
        return None
    environ_reader = read_environ_fn or read_proc_environ
    environment = environ_reader(pid)
    if str(environment.get('HAPI_CCB_SESSION_ID') or '') != session_id:
        return None
    return HapiWrapperIdentity(
        session_id=session_id,
        pid=pid,
        pgid=pgid,
        path=Path(path),
    )


def graceful_stop_wrapper_records(
    paths: tuple[Path, ...],
    *,
    timeout_s: float,
    is_pid_alive_fn=is_pid_alive,
    load_identity_fn=load_current_wrapper_identity,
    signal_group_fn=None,
    monotonic_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> tuple[int, int]:
    """TERM every verified wrapper group, then wait on one shared deadline."""
    deadline = monotonic_fn() + max(0.0, float(timeout_s))
    identities: list[HapiWrapperIdentity] = []
    seen_groups: set[int] = set()
    for path in paths:
        try:
            identity = load_identity_fn(path, is_pid_alive_fn=is_pid_alive_fn)
        except Exception:
            continue
        if identity is None or identity.pgid in seen_groups:
            continue
        seen_groups.add(identity.pgid)
        identities.append(identity)

    sender = signal_group_fn or signal_wrapper_group
    signaled: list[HapiWrapperIdentity] = []
    for identity in identities:
        try:
            if sender(identity):
                signaled.append(identity)
        except Exception:
            continue

    while signaled and monotonic_fn() < deadline:
        if all(not is_pid_alive_fn(identity.pid) for identity in signaled):
            break
        sleep_fn(min(0.05, max(0.0, deadline - monotonic_fn())))
    exited = sum(not is_pid_alive_fn(identity.pid) for identity in signaled)
    return len(signaled), exited


def signal_wrapper_group(identity: HapiWrapperIdentity) -> bool:
    if os.name == 'nt':
        os.kill(identity.pid, signal.SIGTERM)
        return True
    if identity.pgid == os.getpgrp():
        return False
    os.killpg(identity.pgid, signal.SIGTERM)
    return True


def read_proc_environ(pid: int, *, proc_root: Path = Path('/proc')) -> dict[str, str]:
    try:
        raw = (proc_root / str(pid) / 'environ').read_bytes()
    except OSError:
        return {}
    environment: dict[str, str] = {}
    for entry in raw.split(b'\0'):
        if b'=' not in entry:
            continue
        key, value = entry.split(b'=', 1)
        environment[key.decode(errors='replace')] = value.decode(errors='replace')
    return environment


__all__ = [
    'HapiWrapperIdentity',
    'graceful_stop_wrapper_records',
    'load_current_wrapper_identity',
    'read_proc_environ',
    'signal_wrapper_group',
    'wrapper_identity_path',
]
