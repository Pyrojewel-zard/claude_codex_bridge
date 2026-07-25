from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import shlex
import shutil
import subprocess

from provider_backends.codex.runtime_artifacts import codex_runtime_artifact_layout


def supports_managed_app_server(provider_start: tuple[str, ...]) -> bool:
    if len(provider_start) != 1:
        return False
    executable = str(provider_start[0] or '').strip()
    if not executable:
        return False
    resolved = shutil.which(executable)
    if not resolved:
        return False
    path = Path(resolved).resolve()
    try:
        stat = path.stat()
    except OSError:
        return False
    return _supports_managed_app_server_executable(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=16)
def _supports_managed_app_server_executable(executable: str, mtime_ns: int, size: int) -> bool:
    del mtime_ns, size
    try:
        version = subprocess.run(
            [executable, '--version'],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
        if version.returncode != 0 or not str(version.stdout or '').strip().startswith('codex-cli '):
            return False
        cli_help = subprocess.run(
            [executable, '--help'],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        app_server_help = subprocess.run(
            [executable, 'app-server', '--help'],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except Exception:
        return False
    return (
        cli_help.returncode == 0
        and '--remote' in cli_help.stdout
        and app_server_help.returncode == 0
        and '--listen' in app_server_help.stdout
    )


supports_managed_app_server.cache_clear = _supports_managed_app_server_executable.cache_clear


def build_managed_app_server_command(
    codex_args: list[str],
    *,
    runtime_dir: Path,
) -> tuple[str, dict[str, object]]:
    base_args, resume_id = _split_resume(codex_args)
    if not base_args:
        raise ValueError('managed Codex app-server requires an executable')
    artifacts = codex_runtime_artifact_layout(runtime_dir)
    socket_path = artifacts.app_server_socket
    socket_url = f'unix://{socket_path}'
    remote_args = [base_args[0], '--remote', socket_url, *base_args[1:]]
    local_args = list(base_args)
    command = _managed_shell_command(
        remote_args=remote_args,
        local_args=local_args,
        socket_path=socket_path,
        remote_marker=artifacts.app_server_remote_marker,
        resume_id=resume_id,
    )
    executable = base_args[0]
    return command, {
        'codex_app_server_enabled': True,
        'codex_app_server_socket': str(socket_path),
        'codex_app_server_remote_marker': str(artifacts.app_server_remote_marker),
        'codex_app_server_command': [executable, 'app-server', '--listen', socket_url],
    }


def _split_resume(codex_args: list[str]) -> tuple[list[str], str]:
    for index, token in enumerate(codex_args):
        if token != 'resume':
            continue
        if index + 1 >= len(codex_args) or index + 2 != len(codex_args):
            raise ValueError('managed Codex resume requires one terminal session id')
        return list(codex_args[:index]), str(codex_args[index + 1])
    return list(codex_args), ''


def _managed_shell_command(
    *,
    remote_args: list[str],
    local_args: list[str],
    socket_path: Path,
    remote_marker: Path,
    resume_id: str,
) -> str:
    quoted_socket = shlex.quote(str(socket_path))
    quoted_marker = shlex.quote(str(remote_marker))
    quoted_resume = shlex.quote(resume_id)
    remote = ' '.join(shlex.quote(str(part)) for part in remote_args)
    local = ' '.join(shlex.quote(str(part)) for part in local_args)
    return '; '.join(
        (
            f'export CCB_CODEX_MANAGED_REMOTE=1 CCB_CODEX_RESUME_ID={quoted_resume}',
            f'rm -f {quoted_marker}',
            '_ccb_codex_wait=0',
            (
                f'while [ ! -S {quoted_socket} ] && [ "$_ccb_codex_wait" -lt 100 ]; '
                'do sleep 0.05; _ccb_codex_wait=$((_ccb_codex_wait + 1)); done'
            ),
            (
                f'if [ -S {quoted_socket} ]; then '
                f"printf '%s\\n' {quoted_socket} > {quoted_marker}; "
                f'if [ -n "$CCB_CODEX_RESUME_ID" ]; then exec {remote} resume "$CCB_CODEX_RESUME_ID"; '
                f'else exec {remote}; fi; fi'
            ),
            (
                f'if [ -n "$CCB_CODEX_RESUME_ID" ]; then exec {local} resume "$CCB_CODEX_RESUME_ID"; '
                f'else exec {local}; fi'
            ),
        )
    )


__all__ = ['build_managed_app_server_command', 'supports_managed_app_server']
