#!/usr/bin/env python3
"""Collect read-only environment evidence for physical Tailnet validation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

import mobile_physical_tailnet_evidence_init as evidence_init
import mobile_physical_tailnet_preflight as preflight


Runner = Callable[[list[str], float], tuple[int, str, str]]

DEFAULT_SOURCE_WORKTREE = Path('/home/bfly/yunwei/ccb_source_mobile_agent_native')


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = collect_environment(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result['status'] == 'ok' else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Collect physical Tailnet preflight and environment evidence.',
    )
    parser.add_argument('artifact_dir', type=Path)
    parser.add_argument('--adb', default='adb', help='adb executable path')
    parser.add_argument(
        '--tailscale-bin',
        default='tailscale',
        help='tailscale executable path',
    )
    parser.add_argument(
        '--gateway-url',
        help='Tailnet gateway URL, e.g. https://host.tail.ts.net:8787',
    )
    parser.add_argument(
        '--allow-emulator',
        action='store_true',
        help='allow emulator dry-run evidence',
    )
    parser.add_argument('--timeout-s', type=float, default=10.0)
    parser.add_argument('--app-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-worktree', type=Path, default=DEFAULT_SOURCE_WORKTREE)
    parser.add_argument('--force-init', action='store_true', help='overwrite generated init files')
    return parser.parse_args(argv)


def collect_environment(
    args: argparse.Namespace,
    *,
    runner: Runner | None = None,
    http_get: Callable[[str, float], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    runner = runner or preflight.run_command
    http_get = http_get or preflight.get_url
    artifact_dir = args.artifact_dir.resolve()
    init_result = evidence_init.init_evidence_dir(artifact_dir, force=args.force_init)

    preflight_args = argparse.Namespace(
        adb=args.adb,
        tailscale_bin=args.tailscale_bin,
        allow_emulator=args.allow_emulator,
        gateway_url=args.gateway_url,
        timeout_s=args.timeout_s,
        json_out=None,
    )
    preflight_result = preflight.run_preflight(
        preflight_args,
        runner=runner,
        http_get=http_get,
    )
    write_json(artifact_dir / 'preflight.json', preflight_result)

    environment = environment_payload(args, runner=runner)
    write_json(artifact_dir / 'environment.json', environment)

    return {
        'schema_version': 1,
        'status': preflight_result['status'],
        'artifact_dir': str(artifact_dir),
        'generated_at': utc_now(),
        'init': init_result,
        'preflight_file': str(artifact_dir / 'preflight.json'),
        'environment_file': str(artifact_dir / 'environment.json'),
        'preflight_missing': preflight_result.get('missing', []),
        'next_command': f'tools/mobile_physical_tailnet_evidence_audit.py {artifact_dir}',
    }


def environment_payload(args: argparse.Namespace, *, runner: Runner) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'schema_version': 1,
        'status': 'ok',
        'generated_at': utc_now(),
        'route_provider': 'tailnet' if args.gateway_url else None,
        'gateway': {'public_url': args.gateway_url},
        'app': git_snapshot(args.app_root, runner=runner, timeout_s=args.timeout_s),
        'source': git_snapshot(args.source_worktree, runner=runner, timeout_s=args.timeout_s),
        'android': {},
        'tailscale': {},
        'commands': {},
    }
    payload['commands']['adb_devices'] = command_snapshot(
        [args.adb, 'devices', '-l'],
        timeout_s=args.timeout_s,
        runner=runner,
    )
    payload['commands']['tailscale_status_json'] = command_snapshot(
        [args.tailscale_bin, 'status', '--json'],
        timeout_s=args.timeout_s,
        runner=runner,
    )
    status_out = payload['commands']['tailscale_status_json'].get('stdout', '')
    if isinstance(status_out, str):
        try:
            payload['tailscale']['status'] = json.loads(status_out)
        except json.JSONDecodeError:
            payload['tailscale']['status_parse_error'] = 'invalid JSON'
    payload['commands']['tailscale_netcheck'] = command_snapshot(
        [args.tailscale_bin, 'netcheck'],
        timeout_s=args.timeout_s,
        runner=runner,
    )
    if args.gateway_url:
        payload['commands']['tailscale_serve_status'] = command_snapshot(
            [args.tailscale_bin, 'serve', 'status'],
            timeout_s=args.timeout_s,
            runner=runner,
        )
    return payload


def git_snapshot(path: Path, *, runner: Runner, timeout_s: float) -> dict[str, Any]:
    path = path.resolve()
    snapshot: dict[str, Any] = {'path': str(path), 'exists': path.exists()}
    if not path.exists():
        snapshot['status'] = 'missing'
        return snapshot
    head = command_snapshot(
        ['git', '-C', str(path), 'rev-parse', 'HEAD'],
        timeout_s=timeout_s,
        runner=runner,
    )
    dirty = command_snapshot(
        ['git', '-C', str(path), 'status', '--short'],
        timeout_s=timeout_s,
        runner=runner,
    )
    snapshot['head'] = head.get('stdout', '').strip() if head['returncode'] == 0 else None
    snapshot['dirty'] = bool(str(dirty.get('stdout', '')).strip()) if dirty['returncode'] == 0 else None
    snapshot['commands'] = {'rev_parse_head': head, 'status_short': dirty}
    snapshot['status'] = 'ok' if head['returncode'] == 0 and dirty['returncode'] == 0 else 'unknown'
    return snapshot


def command_snapshot(cmd: list[str], *, timeout_s: float, runner: Runner) -> dict[str, Any]:
    rc, out, err = runner(cmd, timeout_s)
    return {
        'command': cmd,
        'returncode': rc,
        'stdout': out,
        'stderr': err,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
