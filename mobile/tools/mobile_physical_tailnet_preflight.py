#!/usr/bin/env python3
"""Preflight checks for physical-device CCB Mobile Tailnet validation.

This tool is intentionally read-only. It does not install Tailscale, run
``tailscale up``, change ACLs/grants, start Funnel, or modify CCB gateway
state. It only reports whether the host and attached Android device are ready
for a manual physical-device Tailnet smoke.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import urlparse


Runner = Callable[[list[str], float], tuple[int, str, str]]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_preflight(args)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.json_out is not None:
        args.json_out.write_text(text + '\n', encoding='utf-8')
    return 0 if result['status'] == 'ok' else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Check readiness for CCB Mobile physical Tailnet validation.',
    )
    parser.add_argument('--adb', default='adb', help='adb executable path')
    parser.add_argument(
        '--tailscale-bin',
        default='tailscale',
        help='tailscale executable path',
    )
    parser.add_argument(
        '--allow-emulator',
        action='store_true',
        help='allow an emulator for dry-run checks; physical validation should omit this',
    )
    parser.add_argument(
        '--gateway-url',
        help='optional CCB Mobile gateway URL to probe, e.g. https://host.tail.ts.net:8787',
    )
    parser.add_argument(
        '--timeout-s',
        type=float,
        default=10.0,
        help='timeout per external command or HTTP probe',
    )
    parser.add_argument(
        '--json-out',
        type=Path,
        help='optional path to write the JSON result',
    )
    return parser.parse_args(argv)


def run_preflight(
    args: argparse.Namespace,
    *,
    runner: Runner | None = None,
    http_get: Callable[[str, float], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    runner = runner or run_command
    http_get = http_get or get_url
    result: dict[str, Any] = {
        'schema_version': 1,
        'started_at': utc_now(),
        'status': 'ok',
        'checks': {},
        'missing': [],
        'warnings': [],
        'manual_requirements': [
            'Android phone is logged in to the same Tailnet and the Tailscale VPN is on.',
            'CCB Mobile is installed and can be opened on the phone.',
            'CCB mobile gateway is loopback-only and exposed through Tailscale Serve, not Funnel.',
            'Use a disposable real CCB test project for message/file validation.',
        ],
        'commands': [
            f'{args.adb} devices -l',
            f'{args.tailscale_bin} status --json',
            'tailscale serve status',
        ],
    }

    adb_summary = check_adb_device(
        adb=args.adb,
        allow_emulator=args.allow_emulator,
        timeout_s=args.timeout_s,
        runner=runner,
    )
    result['checks']['adb_device'] = adb_summary
    if not adb_summary['ok']:
        result['missing'].extend(adb_summary['missing'])
    elif adb_summary.get('selected_serial'):
        boot_summary = check_android_boot(
            adb=args.adb,
            serial=str(adb_summary['selected_serial']),
            timeout_s=args.timeout_s,
            runner=runner,
        )
        result['checks']['android_boot'] = boot_summary
        if not boot_summary['ok']:
            result['missing'].extend(boot_summary['missing'])

    tailscale_summary = check_tailscale_status(
        tailscale_bin=args.tailscale_bin,
        timeout_s=args.timeout_s,
        runner=runner,
    )
    result['checks']['tailscale_status'] = tailscale_summary
    if not tailscale_summary['ok']:
        result['missing'].extend(tailscale_summary['missing'])

    if args.gateway_url:
        serve_summary = check_tailscale_serve_status(
            tailscale_bin=args.tailscale_bin,
            gateway_url=args.gateway_url,
            timeout_s=args.timeout_s,
            runner=runner,
        )
        result['checks']['tailscale_serve_status'] = serve_summary
        if not serve_summary['ok']:
            result['missing'].extend(serve_summary['missing'])
        gateway_summary = check_gateway_health(
            gateway_url=args.gateway_url,
            timeout_s=args.timeout_s,
            http_get=http_get,
        )
        result['checks']['gateway_health'] = gateway_summary
        if not gateway_summary['ok']:
            result['missing'].extend(gateway_summary['missing'])
        result['commands'].append(f'curl -fsS {args.gateway_url.rstrip("/")}/v1/health')
    else:
        result['warnings'].append('No --gateway-url supplied; Tailnet gateway health was not probed.')

    if result['missing']:
        result['status'] = 'blocked'
    return result


def check_adb_device(
    *,
    adb: str,
    allow_emulator: bool,
    timeout_s: float,
    runner: Runner,
) -> dict[str, Any]:
    rc, out, err = runner([adb, 'devices', '-l'], timeout_s)
    devices = parse_adb_devices(out)
    ready = [device for device in devices if device['state'] == 'device']
    physical = [device for device in ready if not device['is_emulator']]
    selected = physical[0] if physical else (ready[0] if allow_emulator and ready else None)
    missing: list[str] = []
    if rc != 0:
        missing.append(f'adb devices failed: {err.strip() or out.strip()}')
    elif not ready:
        missing.append('No online Android device is attached.')
    elif not physical and not allow_emulator:
        missing.append('Only emulator devices are attached; physical Tailnet validation needs a phone.')
    return {
        'ok': not missing,
        'returncode': rc,
        'devices': devices,
        'allow_emulator': allow_emulator,
        'selected_serial': selected['serial'] if selected else None,
        'selected_is_emulator': selected['is_emulator'] if selected else None,
        'missing': missing,
    }


def check_android_boot(
    *,
    adb: str,
    serial: str,
    timeout_s: float,
    runner: Runner,
) -> dict[str, Any]:
    rc, out, err = runner(
        [adb, '-s', serial, 'shell', 'getprop', 'sys.boot_completed'],
        timeout_s,
    )
    boot_completed = out.strip() == '1'
    missing: list[str] = []
    if rc != 0:
        missing.append(f'adb boot check failed for {serial}: {err.strip() or out.strip()}')
    elif not boot_completed:
        missing.append(f'Android device {serial} has not completed boot.')
    return {
        'ok': not missing,
        'serial': serial,
        'boot_completed': boot_completed,
        'returncode': rc,
        'missing': missing,
    }


def check_tailscale_status(
    *,
    tailscale_bin: str,
    timeout_s: float,
    runner: Runner,
) -> dict[str, Any]:
    rc, out, err = runner([tailscale_bin, 'status', '--json'], timeout_s)
    missing: list[str] = []
    parsed: dict[str, Any] | None = None
    backend_state = None
    tailnet = None
    self_dns = None
    if rc != 0:
        missing.append(f'tailscale status failed: {err.strip() or out.strip()}')
    else:
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as exc:
            missing.append(f'tailscale status --json returned invalid JSON: {exc}')
        if parsed is not None:
            backend_state = parsed.get('BackendState')
            tailnet_value = parsed.get('CurrentTailnet')
            if isinstance(tailnet_value, dict):
                tailnet = tailnet_value.get('Name')
            elif isinstance(tailnet_value, str):
                tailnet = tailnet_value
            self_value = parsed.get('Self')
            if isinstance(self_value, dict):
                self_dns = self_value.get('DNSName')
            if backend_state != 'Running':
                missing.append(
                    'Tailscale is not logged in/running; run tailscale up and confirm login.',
                )
    return {
        'ok': not missing,
        'returncode': rc,
        'backend_state': backend_state,
        'tailnet': tailnet,
        'self_dns_name': self_dns,
        'missing': missing,
    }


def check_tailscale_serve_status(
    *,
    tailscale_bin: str,
    gateway_url: str,
    timeout_s: float,
    runner: Runner,
) -> dict[str, Any]:
    rc, out, err = runner([tailscale_bin, 'serve', 'status'], timeout_s)
    expected_port = tailnet_https_port(gateway_url)
    missing: list[str] = []
    output = out + err
    if rc != 0:
        missing.append(f'tailscale serve status failed: {err.strip() or out.strip()}')
    else:
        if expected_port is None:
            missing.append(f'Gateway URL does not include a valid HTTPS port: {gateway_url}')
        elif not public_https_port_seen(output, expected_port):
            missing.append(
                f'tailscale serve status does not mention HTTPS port {expected_port}.',
            )
        if '127.0.0.1' not in output and 'localhost' not in output:
            missing.append(
                'tailscale serve status does not show a loopback origin.',
            )
    return {
        'ok': not missing,
        'returncode': rc,
        'expected_https_port': expected_port,
        'loopback_origin_seen': '127.0.0.1' in output or 'localhost' in output,
        'output_preview': output[:600],
        'missing': missing,
    }


def tailnet_https_port(gateway_url: str) -> int | None:
    parsed = urlparse(gateway_url)
    if parsed.scheme != 'https':
        return None
    if parsed.port is not None:
        return parsed.port
    return 443


def public_https_port_seen(output: str, expected_port: int) -> bool:
    public_urls = re.findall(r'https://[^\s]+', output)
    if not public_urls:
        return False
    for public_url in public_urls:
        parsed = urlparse(public_url.rstrip('.,;'))
        port = parsed.port if parsed.port is not None else 443
        if port == expected_port:
            return True
    return False


def check_gateway_health(
    *,
    gateway_url: str,
    timeout_s: float,
    http_get: Callable[[str, float], tuple[int, str]],
) -> dict[str, Any]:
    health_url = gateway_url.rstrip('/') + '/v1/health'
    missing: list[str] = []
    status_code = None
    body = ''
    try:
        status_code, body = http_get(health_url, timeout_s)
    except Exception as exc:
        missing.append(f'Gateway health probe failed: {exc}')
    else:
        if status_code < 200 or status_code >= 300:
            missing.append(f'Gateway health returned HTTP {status_code}.')
        elif '"ok"' not in body and 'ok' not in body.lower():
            missing.append('Gateway health response did not include ok status.')
    return {
        'ok': not missing,
        'url': health_url,
        'status_code': status_code,
        'body_preview': body[:300],
        'missing': missing,
    }


def parse_adb_devices(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith('List of devices'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        detail = ' '.join(parts[2:])
        devices.append(
            {
                'serial': serial,
                'state': state,
                'detail': detail,
                'is_emulator': serial.startswith('emulator-') or 'model:sdk_' in detail,
            }
        )
    return devices


def run_command(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_s,
            text=True,
        )
    except Exception as exc:
        return 999, '', str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def get_url(url: str, timeout_s: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={'accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read(4096).decode('utf-8', 'replace')
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode('utf-8', 'replace')
        return exc.code, body


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
