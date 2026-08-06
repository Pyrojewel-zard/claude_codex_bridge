from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from provider_backends.codex.runtime_artifacts import codex_runtime_artifact_layout


class ManagedCodexAppServer:
    def __init__(self, runtime_dir: Path) -> None:
        self._runtime_dir = Path(runtime_dir)
        self._process: subprocess.Popen | None = None

    def start(self) -> bool:
        command = _command_from_env()
        socket_path = _socket_from_env()
        artifacts = codex_runtime_artifact_layout(self._runtime_dir)
        if (
            not command
            or socket_path is None
            or not _same_path(socket_path, artifacts.app_server_socket)
        ):
            return False
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale_socket(artifacts.app_server_socket)
        _remove_runtime_file(artifacts.app_server_remote_marker)
        try:
            with artifacts.app_server_stdout_log.open('ab') as stdout_log, artifacts.app_server_stderr_log.open('ab') as stderr_log:
                self._process = subprocess.Popen(
                    command,
                    env=os.environ.copy(),
                    stdout=stdout_log,
                    stderr=stderr_log,
                )
        except (OSError, ValueError):
            self._process = None
            self._cleanup_artifacts()
            return False
        artifacts.app_server_pid.write_text(f'{self._process.pid}\n', encoding='utf-8')
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if socket_path.is_socket():
                return True
            if self._process.poll() is not None:
                self._cleanup_artifacts()
                return False
            time.sleep(0.05)
        if socket_path.is_socket():
            return True
        self.stop()
        return False

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        self._cleanup_artifacts()

    def _cleanup_artifacts(self) -> None:
        artifacts = codex_runtime_artifact_layout(self._runtime_dir)
        _remove_stale_socket(artifacts.app_server_socket)
        _remove_runtime_file(artifacts.app_server_pid)
        _remove_runtime_file(artifacts.app_server_remote_marker)


def _command_from_env() -> list[str]:
    raw = str(os.environ.get('CCB_CODEX_APP_SERVER_COMMAND_JSON') or '').strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item).strip()]


def _socket_from_env() -> Path | None:
    raw = str(os.environ.get('CCB_CODEX_APP_SERVER_SOCKET') or '').strip()
    return Path(raw) if raw else None


def _remove_stale_socket(path: Path) -> None:
    try:
        if path.exists() or path.is_socket():
            path.unlink()
    except FileNotFoundError:
        return


def _remove_runtime_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return False


__all__ = ['ManagedCodexAppServer']
