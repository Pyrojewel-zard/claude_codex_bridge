#!/usr/bin/env python3
"""Prepare or inspect an isolated CCB project for mobile terminal validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import socket
import sys
from typing import Any


API_VERSION = 2
DEFAULT_PROJECT_ROOT = Path('/tmp/ccb-mobile-terminal-harness')
DEFAULT_CONFIG_TEXT = 'cmd, mobile_probe:codex\n'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = args.project_root.expanduser().resolve()

    if args.init:
        init_project(project_root, force=args.force_config)

    socket_path = resolve_ccbd_socket(project_root, args.socket)
    if socket_path is None:
        print_missing_socket_guidance(project_root)
        return 2

    ping = rpc(socket_path, 'ping', {'target': 'ccbd'}, timeout_s=args.timeout)
    project_view = rpc(socket_path, 'project_view', {'schema_version': 1}, timeout_s=args.timeout)
    evidence = build_evidence(project_root, socket_path, ping, project_view)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Inspect a running isolated CCB project and print mobile terminal '
            'target evidence. The script does not start or stop CCB by default.'
        )
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        default=DEFAULT_PROJECT_ROOT,
        help=f'isolated CCB project root (default: {DEFAULT_PROJECT_ROOT})',
    )
    parser.add_argument(
        '--socket',
        type=Path,
        help='explicit ccbd Unix socket path when it is not discoverable from the project root',
    )
    parser.add_argument(
        '--init',
        action='store_true',
        help='create the isolated project root and a minimal .ccb/ccb.config if missing',
    )
    parser.add_argument(
        '--force-config',
        action='store_true',
        help='rewrite the generated harness .ccb/ccb.config during --init',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=3.0,
        help='Unix socket RPC timeout in seconds',
    )
    return parser.parse_args(argv)


def init_project(project_root: Path, *, force: bool) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / '.ccb' / 'ccb.config'
    if config_path.exists() and not force:
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(DEFAULT_CONFIG_TEXT, encoding='utf-8')


def resolve_ccbd_socket(project_root: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()

    lease_path = project_root / '.ccb' / 'ccbd' / 'lease.json'
    if lease_path.exists():
        try:
            lease = json.loads(lease_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            lease = {}
        socket_text = str(lease.get('socket_path') or '').strip()
        if socket_text:
            return Path(socket_text).expanduser().resolve()

    candidates = [
        project_root / '.ccb' / 'ccbd' / 'ccbd.sock',
        *sorted((project_root / '.ccb' / 'ccbd').glob('ccbd-*.sock')),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def rpc(socket_path: Path, op: str, request: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    payload = {
        'api_version': API_VERSION,
        'op': op,
        'request': request,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(max(0.1, float(timeout_s)))
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))
        raw = recv_line(client)
    response = json.loads(raw.decode('utf-8'))
    if response.get('api_version') != API_VERSION:
        raise RuntimeError(f'unsupported ccbd api_version: {response.get("api_version")!r}')
    if not response.get('ok'):
        raise RuntimeError(f'ccbd {op} failed: {response.get("error") or response!r}')
    response.pop('api_version', None)
    response.pop('ok', None)
    return response


def recv_line(client: socket.socket) -> bytes:
    raw = b''
    while b'\n' not in raw:
        chunk = client.recv(65536)
        if not chunk:
            break
        raw += chunk
    if not raw:
        raise RuntimeError('empty response from ccbd')
    return raw.split(b'\n', 1)[0]


def build_evidence(
    project_root: Path,
    socket_path: Path,
    ping: dict[str, Any],
    project_view: dict[str, Any],
) -> dict[str, Any]:
    view = as_dict(project_view.get('view'))
    namespace = as_dict(view.get('namespace'))
    agents = [as_dict(item) for item in as_list(view.get('agents'))]
    active_agent = next((item for item in agents if item.get('active') is True), None)
    first_agent = active_agent or (agents[0] if agents else {})
    tmux_socket = text(namespace.get('socket_path'))
    tmux_session = text(namespace.get('session_name'))
    attach_command = tmux_attach_command(tmux_socket, tmux_session)
    return {
        'project_root': str(project_root),
        'ccbd_socket_path': str(socket_path),
        'ping': ping,
        'project': as_dict(view.get('project')),
        'namespace': {
            'epoch': namespace.get('epoch'),
            'socket_path': tmux_socket,
            'session_name': tmux_session,
            'active_window': namespace.get('active_window'),
            'active_pane_id': namespace.get('active_pane_id'),
        },
        'selected_agent': {
            'name': first_agent.get('name'),
            'window': first_agent.get('window'),
            'pane_id': first_agent.get('pane_id'),
            'active': first_agent.get('active'),
        },
        'mobile_terminal_target_ok': bool(tmux_socket and tmux_session and namespace.get('epoch') is not None),
        'attach_command': attach_command,
    }


def tmux_attach_command(socket_path: str, session_name: str) -> str | None:
    if not socket_path or not session_name:
        return None
    return ' '.join(
        shlex.quote(part)
        for part in ('tmux', '-S', socket_path, 'attach-session', '-t', session_name)
    )


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def text(value: Any) -> str:
    return str(value or '').strip()


def print_missing_socket_guidance(project_root: Path) -> None:
    print(
        json.dumps(
            {
                'project_root': str(project_root),
                'status': 'ccbd_socket_not_found',
                'next_steps': [
                    f'cd {shlex.quote(str(project_root))}',
                    'ccb -s',
                    're-run this script with --project-root pointing at the isolated project',
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == '__main__':
    sys.exit(main())
