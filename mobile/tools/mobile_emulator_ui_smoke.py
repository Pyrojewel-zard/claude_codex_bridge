#!/usr/bin/env python3
"""Run a local Android Emulator UI smoke against a loopback CCB gateway."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

import mobile_gateway_terminal_smoke as gateway_smoke


DEFAULT_DEVICE_ID = 'emulator-5554'
DEFAULT_GATEWAY_LISTEN = '127.0.0.1:8787'
DEFAULT_ANDROID_PACKAGE = 'io.ccb.mobile.ccb_mobile'
DEFAULT_SECONDARY_AGENT = 'mobile_peer'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mobile_root = Path(__file__).resolve().parents[1]
    project_root = (
        args.project_root.expanduser().resolve()
        if args.project_root is not None
        else default_project_root()
    )
    source_ccb = args.source_ccb.expanduser().resolve()
    gateway: dict[str, Any] | None = None
    runtime_started = False
    reverse_installed = False
    result: dict[str, Any] = {
        'status': 'error',
        'project_root': str(project_root),
        'source_ccb': str(source_ccb),
        'device_id': args.device_id,
        'gateway_listen': args.gateway_listen,
    }
    exit_code = 1
    try:
        listen_host, listen_port = gateway_smoke.parse_gateway_listen(
            args.gateway_listen,
        )
        if listen_host not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError(
                f'gateway listen must be loopback for emulator smoke: {args.gateway_listen}'
            )
        if listen_port is None or listen_port <= 0:
            raise ValueError(
                f'gateway listen must use a fixed TCP port: {args.gateway_listen}'
            )

        init_emulator_project(
            project_root,
            force=args.force_config,
            primary_agent=args.agent,
            secondary_agent=args.secondary_agent,
            provider=args.provider,
        )
        start_summary = gateway_smoke.start_ccb_project(
            source_ccb=source_ccb,
            project_root=project_root,
            timeout_s=args.start_timeout,
        )
        runtime_started = True
        pre_harness = gateway_smoke.run_harness(
            mobile_root,
            project_root,
            timeout_s=args.harness_timeout,
        )
        gateway = gateway_smoke.start_mobile_gateway(
            source_ccb=source_ccb,
            project_root=project_root,
            timeout_s=args.gateway_timeout,
            listen=args.gateway_listen,
            public_url=None,
            route_provider='lan',
        )

        device_report = ensure_emulator_ready(
            mobile_root=mobile_root,
            device_id=args.device_id,
            timeout_s=args.adb_timeout,
        )
        reverse_report = adb_reverse(
            mobile_root=mobile_root,
            device_id=args.device_id,
            host_port=listen_port,
            timeout_s=args.adb_timeout,
        )
        reverse_installed = True
        integration_smoke = run_flutter_integration_smoke(
            mobile_root=mobile_root,
            device_id=args.device_id,
            gateway_url=gateway['gateway_url'],
            pairing_code=gateway['pairing_code'],
            agent=args.agent,
            secondary_agent=args.secondary_agent,
            android_package=args.android_package,
            include_lifecycle_stop=args.include_lifecycle_stop,
            include_terminal_route=not args.skip_terminal_test,
            include_attachment_route=args.include_attachment_route,
            include_image_route=args.include_image_route,
            include_markdown_route=args.include_markdown_route,
            include_backend_artifact_route=args.include_backend_artifact_route,
            include_multi_agent_route=args.include_multi_agent_route,
            timeout_s=args.flutter_timeout,
        )
        if integration_smoke['returncode'] != 0:
            raise RuntimeError('Flutter emulator UI smoke returned non-zero')
        if args.include_lifecycle_stop or args.skip_terminal_test:
            post_harness = {
                'skipped': True,
                'reason': (
                    'lifecycle stop was requested by the AVD smoke'
                    if args.include_lifecycle_stop
                    else 'terminal route smoke was skipped'
                ),
            }
        else:
            post_harness = gateway_smoke.run_harness(
                mobile_root,
                project_root,
                timeout_s=args.harness_timeout,
            )
            if post_harness.get('mobile_terminal_target_ok') is not True:
                raise RuntimeError(
                    'post-smoke harness did not report an attachable terminal target'
                )
        post_harness_summary = (
            post_harness
            if post_harness.get('skipped') is True
            else gateway_smoke.summarize_harness(post_harness)
        )
        result.update(
            {
                'status': 'ok',
                'started': start_summary,
                'pre_harness': gateway_smoke.summarize_harness(pre_harness),
                'gateway': gateway_smoke.sanitize_gateway_summary(gateway),
                'device': device_report,
                'adb_reverse': reverse_report,
                'integration_smoke': integration_smoke,
                'post_harness': post_harness_summary,
            }
        )
        exit_code = 0
    except Exception as exc:
        result['error'] = str(exc)
        if isinstance(gateway, dict):
            result['gateway'] = gateway_smoke.sanitize_gateway_summary(gateway)
    finally:
        if reverse_installed and not args.keep_running:
            result['adb_reverse_cleanup'] = adb_reverse_remove(
                mobile_root=mobile_root,
                device_id=args.device_id,
                host_port=gateway_smoke.parse_gateway_listen(args.gateway_listen)[1],
                timeout_s=args.adb_timeout,
            )
        if runtime_started or isinstance(gateway, dict):
            result['cleanup'] = gateway_smoke.cleanup_runtime(
                source_ccb=source_ccb,
                project_root=project_root,
                gateway_process=gateway.get('process') if isinstance(gateway, dict) else None,
                cloudflared_process=None,
                keep_running=args.keep_running,
            )
        else:
            result['cleanup'] = {
                'keep_running': args.keep_running,
                'runtime_started': False,
            }
        print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Start a disposable CCB runtime, serve a fixed loopback mobile '
            'gateway, install adb reverse, and run the Flutter Android '
            'Emulator UI smoke.'
        ),
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        help='disposable project root; defaults under /home/bfly/yunwei/test_ccb2',
    )
    parser.add_argument(
        '--source-ccb',
        type=Path,
        default=gateway_smoke.DEFAULT_SOURCE_CCB,
        help=f'CCB source CLI to exercise (default: {gateway_smoke.DEFAULT_SOURCE_CCB})',
    )
    parser.add_argument(
        '--agent',
        default=gateway_smoke.DEFAULT_AGENT,
        help=f'configured agent to select/open (default: {gateway_smoke.DEFAULT_AGENT})',
    )
    parser.add_argument(
        '--secondary-agent',
        default=DEFAULT_SECONDARY_AGENT,
        help=(
            'second configured agent used by the chat-first AVD smoke to '
            f'validate switching/draft retention (default: {DEFAULT_SECONDARY_AGENT})'
        ),
    )
    parser.add_argument(
        '--provider',
        default='codex',
        help=(
            'provider to write into generated .ccb/ccb.config for both smoke '
            'agents; use fake for deterministic local backend reply checks '
            '(default: codex)'
        ),
    )
    parser.add_argument(
        '--device-id',
        default=DEFAULT_DEVICE_ID,
        help=f'Android Emulator adb/flutter device id (default: {DEFAULT_DEVICE_ID})',
    )
    parser.add_argument(
        '--gateway-listen',
        default=DEFAULT_GATEWAY_LISTEN,
        help=f'fixed loopback host:port for emulator adb reverse (default: {DEFAULT_GATEWAY_LISTEN})',
    )
    parser.add_argument(
        '--android-package',
        default=DEFAULT_ANDROID_PACKAGE,
        help=f'app package id to clear before the smoke (default: {DEFAULT_ANDROID_PACKAGE})',
    )
    parser.add_argument(
        '--force-config',
        action='store_true',
        help='rewrite generated .ccb/ccb.config',
    )
    parser.add_argument(
        '--keep-running',
        action='store_true',
        help='leave gateway, CCB runtime, and adb reverse running',
    )
    parser.add_argument(
        '--include-lifecycle-stop',
        action='store_true',
        help=(
            'also exercise the destructive Stop lifecycle action in the AVD UI; '
            'use only with a throwaway runtime because the terminal smoke is skipped'
        ),
    )
    parser.add_argument(
        '--include-attachment-route',
        action='store_true',
        help=(
            'exercise real gateway file upload/download plus deterministic '
            'message-route reply; intended for --provider fake local matrix runs'
        ),
    )
    parser.add_argument(
        '--include-markdown-route',
        action='store_true',
        help=(
            'exercise deterministic Markdown reply rendering through the real '
            'gateway message route; intended for --provider fake local matrix runs'
        ),
    )
    parser.add_argument(
        '--include-image-route',
        action='store_true',
        help=(
            'exercise real gateway image upload/download through Android '
            'Emulator UI; intended for --provider fake local matrix runs'
        ),
    )
    parser.add_argument(
        '--include-backend-artifact-route',
        action='store_true',
        help=(
            'exercise backend-agent generated artifact links and downloads '
            'through the real gateway; intended for --provider fake local '
            'matrix runs'
        ),
    )
    parser.add_argument(
        '--include-multi-agent-route',
        action='store_true',
        help=(
            'exercise multi-agent draft isolation, multi-turn send/reply, '
            'per-agent image upload/download, and per-agent backend artifacts '
            'through the real gateway; intended for --provider fake local '
            'matrix runs'
        ),
    )
    parser.add_argument(
        '--skip-terminal-test',
        action='store_true',
        help=(
            'skip the terminal route UI smoke and post-smoke terminal target check; '
            'useful for deterministic fake-provider attachment lanes'
        ),
    )
    parser.add_argument('--start-timeout', type=float, default=30.0)
    parser.add_argument('--gateway-timeout', type=float, default=15.0)
    parser.add_argument('--harness-timeout', type=float, default=5.0)
    parser.add_argument('--adb-timeout', type=float, default=15.0)
    parser.add_argument('--flutter-timeout', type=float, default=180.0)
    return parser.parse_args(argv)


def default_project_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    return (
        gateway_smoke.DEFAULT_PROJECT_PARENT / f'ccb-mobile-emulator-ui-smoke-{stamp}'
    ).resolve()


def init_emulator_project(
    project_root: Path,
    *,
    force: bool,
    primary_agent: str,
    secondary_agent: str,
    provider: str,
) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / '.ccb' / 'ccb.config'
    if config_path.exists() and not force:
        return
    agents = [primary_agent.strip(), secondary_agent.strip()]
    unique_agents = []
    for agent in agents:
        if agent and agent not in unique_agents:
            unique_agents.append(agent)
    if not unique_agents:
        unique_agents = [gateway_smoke.DEFAULT_AGENT]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    provider_name = provider.strip() or 'codex'
    config_text = (
        'cmd, '
        + '; '.join(f'{agent}:{provider_name}' for agent in unique_agents)
        + '\n'
    )
    config_path.write_text(config_text, encoding='utf-8')


def ensure_emulator_ready(
    *,
    mobile_root: Path,
    device_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    adb = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'wait-for-device'],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if adb.returncode != 0:
        raise RuntimeError(command_failure('adb wait-for-device failed', adb))
    devices = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', 'devices', '-l'],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if devices.returncode != 0:
        raise RuntimeError(command_failure('adb devices failed', devices))
    if device_id not in devices.stdout:
        raise RuntimeError(f'Android device not found: {device_id}\n{devices.stdout}')
    boot = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'getprop', 'sys.boot_completed'],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if boot.returncode != 0:
        raise RuntimeError(command_failure('adb boot check failed', boot))
    if boot.stdout.strip() != '1':
        raise RuntimeError(f'Android device is not boot-complete: {device_id}')
    return {
        'device_id': device_id,
        'boot_completed': True,
        'devices': devices.stdout.strip().splitlines(),
    }


def adb_reverse(
    *,
    mobile_root: Path,
    device_id: str,
    host_port: int,
    timeout_s: float,
) -> dict[str, Any]:
    completed = run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'reverse',
            f'tcp:{host_port}',
            f'tcp:{host_port}',
        ],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(command_failure('adb reverse failed', completed))
    reverse_list = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'reverse', '--list'],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if reverse_list.returncode != 0:
        raise RuntimeError(command_failure('adb reverse --list failed', reverse_list))
    expected = f'tcp:{host_port} tcp:{host_port}'
    if expected not in reverse_list.stdout:
        raise RuntimeError(
            f'adb reverse did not report {expected}:\n{reverse_list.stdout}'
        )
    return {'device_id': device_id, 'mapping': expected}


def adb_reverse_remove(
    *,
    mobile_root: Path,
    device_id: str,
    host_port: int | None,
    timeout_s: float,
) -> dict[str, Any]:
    if host_port is None:
        return {'removed': False, 'reason': 'unknown port'}
    completed = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'reverse', '--remove', f'tcp:{host_port}'],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    return {
        'removed': completed.returncode == 0,
        'returncode': completed.returncode,
        'stderr': completed.stderr.strip(),
    }


def run_flutter_integration_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    gateway_url: str,
    pairing_code: str,
    agent: str,
    secondary_agent: str,
    android_package: str,
    include_lifecycle_stop: bool,
    include_terminal_route: bool,
    include_attachment_route: bool,
    include_image_route: bool,
    include_markdown_route: bool,
    include_backend_artifact_route: bool,
    include_multi_agent_route: bool,
    timeout_s: float,
) -> dict[str, Any]:
    parsed = urlparse(gateway_url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}:
        raise ValueError(
            f'emulator UI smoke requires a loopback HTTP gateway URL: {gateway_url}'
        )
    clear_result = run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    completed = run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'flutter',
            'test',
            'integration_test/emulator_gateway_smoke_test.dart',
            '-d',
            device_id,
            '-D',
            f'CCB_MOBILE_GATEWAY_URL={gateway_url}',
            '-D',
            f'CCB_MOBILE_PAIRING_CODE={pairing_code}',
            '-D',
            f'CCB_MOBILE_AGENT={agent}',
            '-D',
            f'CCB_MOBILE_SECONDARY_AGENT={secondary_agent}',
            '-D',
            'CCB_MOBILE_REQUIRE_GATEWAY=true',
            '-D',
            f'CCB_MOBILE_INCLUDE_LIFECYCLE_STOP={str(include_lifecycle_stop).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_TERMINAL_ROUTE={str(include_terminal_route).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_ATTACHMENT_ROUTE={str(include_attachment_route).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_IMAGE_ROUTE={str(include_image_route).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_MARKDOWN_ROUTE={str(include_markdown_route).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_BACKEND_ARTIFACT_ROUTE={str(include_backend_artifact_route).lower()}',
            '-D',
            f'CCB_MOBILE_INCLUDE_MULTI_AGENT_ROUTE={str(include_multi_agent_route).lower()}',
        ],
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(command_failure('flutter integration smoke failed', completed))
    return {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'include_lifecycle_stop': include_lifecycle_stop,
        'include_terminal_route': include_terminal_route,
        'include_attachment_route': include_attachment_route,
        'include_image_route': include_image_route,
        'include_markdown_route': include_markdown_route,
        'include_backend_artifact_route': include_backend_artifact_route,
        'include_multi_agent_route': include_multi_agent_route,
        'stdout_tail': tail_lines(completed.stdout, 60),
        'stderr_tail': tail_lines(completed.stderr, 30),
    }


def run_toolchain(
    *,
    mobile_root: Path,
    argv: list[str],
    cwd: Path,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {shlex.quote(str(toolchain))} && {gateway_smoke.shell_command(argv)}'
    return subprocess.run(
        ['sh', '-lc', command],
        cwd=str(cwd),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )


def command_failure(
    title: str,
    completed: subprocess.CompletedProcess[str],
) -> str:
    return (
        f'{title}: exit {completed.returncode}\n'
        f'stdout:\n{completed.stdout}\n'
        f'stderr:\n{completed.stderr}'
    )


def tail_lines(text: str, limit: int) -> list[str]:
    lines = text.splitlines()
    return lines[-limit:]


if __name__ == '__main__':
    sys.exit(main())
