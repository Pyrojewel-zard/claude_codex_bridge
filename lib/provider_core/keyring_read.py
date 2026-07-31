from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Iterable


_NODE_KEYTAR_READ_SCRIPT = r"""
const modulePath = process.argv[1];
const service = process.argv[2];
const account = process.argv[3];
Promise.resolve()
  .then(() => {
    const loaded = require(modulePath);
    const keytar = loaded && loaded.default ? loaded.default : loaded;
    return keytar.getPassword(service, account);
  })
  .then((value) => {
    if (typeof value === "string" && value.length > 0) {
      process.stdout.write(value);
    }
  })
  .catch(() => process.exit(2));
"""


def read_keyring_password(
    service: str,
    account: str,
    *,
    command_name: str,
    module_names: tuple[str, ...] = ('@github/keytar', 'keytar'),
    extra_module_paths: Iterable[Path] = (),
    timeout: float = 5.0,
) -> str | None:
    """Read one external credential without ever opening a write API."""
    service_name = str(service or '').strip()
    account_name = str(account or '').strip()
    if not service_name or not account_name:
        return None
    if platform.system() == 'Darwin':
        value = _read_macos_keychain(
            service_name,
            account_name,
            timeout=timeout,
        )
        if value:
            return value
    module_path = _find_keytar_module(
        command_name,
        module_names=module_names,
        extra_module_paths=extra_module_paths,
    )
    if module_path is not None:
        value = _read_node_keytar(
            module_path,
            service_name,
            account_name,
            timeout=timeout,
        )
        if value:
            return value
    if platform.system() == 'Linux':
        return _read_linux_secret_tool(
            service_name,
            account_name,
            timeout=timeout,
        )
    return None


def _read_macos_keychain(service: str, account: str, *, timeout: float) -> str | None:
    security = shutil.which('security') or '/usr/bin/security'
    try:
        result = subprocess.run(
            [
                security,
                'find-generic-password',
                '-s',
                service,
                '-a',
                account,
                '-w',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    return result.stdout.rstrip('\r\n') if result.returncode == 0 else None


def _read_node_keytar(
    module_path: Path,
    service: str,
    account: str,
    *,
    timeout: float,
) -> str | None:
    node = shutil.which('node')
    if not node:
        return None
    try:
        result = subprocess.run(
            [
                node,
                '-e',
                _NODE_KEYTAR_READ_SCRIPT,
                str(module_path),
                service,
                account,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(os.environ),
        )
    except Exception:
        return None
    return result.stdout if result.returncode == 0 and result.stdout else None


def _read_linux_secret_tool(service: str, account: str, *, timeout: float) -> str | None:
    secret_tool = shutil.which('secret-tool')
    if not secret_tool:
        return None
    try:
        result = subprocess.run(
            [
                secret_tool,
                'lookup',
                'service',
                service,
                'account',
                account,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None
    return result.stdout.rstrip('\r\n') if result.returncode == 0 else None


def _find_keytar_module(
    command_name: str,
    *,
    module_names: tuple[str, ...],
    extra_module_paths: Iterable[Path],
) -> Path | None:
    for raw in extra_module_paths:
        candidate = Path(raw).expanduser()
        if candidate.is_file() or (candidate.is_dir() and (candidate / 'package.json').is_file()):
            return candidate
    command = shutil.which(str(command_name or '').strip())
    if not command:
        return None
    try:
        executable = Path(command).resolve()
    except Exception:
        executable = Path(command).expanduser()
    for root in (executable.parent, *executable.parents):
        for module_name in module_names:
            relative = Path(*module_name.split('/'))
            for candidate in (
                root / 'node_modules' / relative,
                root / relative,
            ):
                if candidate.is_file() or (
                    candidate.is_dir()
                    and (candidate / 'package.json').is_file()
                ):
                    return candidate
    return None


__all__ = ['read_keyring_password']
