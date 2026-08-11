#!/usr/bin/env python3
"""Run Android Emulator smoke against server-wide ``ccb install mobile``."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
import urllib.request

import mobile_app_compass_test as compass
import mobile_emulator_ui_smoke as emulator_smoke
import mobile_gateway_terminal_smoke as gateway_smoke


DEFAULT_DEVICE_ID = 'emulator-5554'
DEFAULT_ANDROID_PACKAGE = 'io.ccb.mobile.ccb_mobile'
DEFAULT_GATEWAY_LISTEN = '127.0.0.1:18891'
DEFAULT_SOURCE_CCB = Path('/home/bfly/yunwei/ccb_source_mobile_server_wide_full/ccb')
DEFAULT_PROJECT_PARENT = Path('/home/bfly/yunwei/test_ccb2')
DEFAULT_AGENT = 'mobile_probe'
DEFAULT_SECONDARY_AGENT = 'mobile_peer'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mobile_root = Path(__file__).resolve().parents[1]
    source_ccb = args.source_ccb.expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    projects_root = (
        args.projects_root.expanduser().resolve()
        if args.projects_root is not None
        else DEFAULT_PROJECT_PARENT / f'ccb-mobile-server-wide-avd-{stamp}'
    )
    state_home = (
        args.state_home.expanduser().resolve()
        if args.state_home is not None
        else Path('/tmp') / f'ccb-mobile-server-wide-avd-state-{stamp}'
    )
    alpha_root = projects_root / 'test_ccb2_alpha'
    beta_root = projects_root / 'test_ccb2_beta'
    gateway: dict[str, Any] | None = None
    reverse_host_port: int | None = None
    extra_reverse_host_ports: list[int] = []
    started_projects: list[dict[str, Any]] = []
    request_proxy: CountingHttpProxy | None = None
    result: dict[str, Any] = {
        'status': 'error',
        'source_ccb': str(source_ccb),
        'projects_root': str(projects_root),
        'state_home': str(state_home),
        'gateway_listen': args.gateway_listen,
        'device_id': args.device_id,
    }
    exit_code = 1
    try:
        host, port = gateway_smoke.parse_gateway_listen(args.gateway_listen)
        if host not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError(f'gateway listen must be loopback: {args.gateway_listen}')
        if port is None or port <= 0:
            raise ValueError(f'gateway listen must use a fixed port: {args.gateway_listen}')

        for root in (alpha_root, beta_root):
            init_project(root, provider=args.provider, force=args.force_config)
            started_projects.append(
                {
                    'root': str(root),
                    'start': start_ccb_project(
                        source_ccb=source_ccb,
                        project_root=root,
                        state_home=state_home,
                        timeout_s=args.start_timeout,
                    ),
                }
            )
        gateway = start_server_mobile_gateway(
            source_ccb=source_ccb,
            state_home=state_home,
            listen=args.gateway_listen,
            timeout_s=args.gateway_timeout,
        )
        projects = wait_for_server_projects(
            f'{gateway["gateway_url"].rstrip("/")}/v1/projects',
            minimum=2,
            timeout_s=args.gateway_timeout,
        )
        project_list = list(projects.get('projects') or [])
        if len(project_list) < 2:
            raise RuntimeError(f'server-wide gateway listed too few projects: {projects!r}')
        alpha = require_project(project_list, alpha_root)
        beta = require_project(project_list, beta_root)
        claim = http_post_json(
            gateway['pairing_claim_endpoint'],
            {
                'pairing_code': gateway['pairing_code'],
                'device_name': 'Android Emulator Server-Wide Smoke',
                'device_id': f'avd_{stamp}',
            },
        )
        profile_gateway_url: str | None = None
        idle_proxy_enabled = (
            args.idle_request_smoke
            or args.release_idle_request_smoke
            or args.release_long_history_smoke
            or args.release_file_download_smoke
            or args.release_upload_smoke
        )
        if idle_proxy_enabled:
            proxy_listen = args.request_proxy_listen or f'127.0.0.1:{port + 1}'
            request_proxy = CountingHttpProxy(
                listen=proxy_listen,
                target_base_url=str(gateway['gateway_url']),
            )
            request_proxy.start()
            profile_gateway_url = f'http://{proxy_listen}'
            result['request_proxy'] = request_proxy.summary()
        backfill: dict[str, Any] | None = None
        if args.include_long_history_backfill or args.release_long_history_smoke:
            backfill = seed_long_history(
                project_root=alpha_root,
                state_home=state_home,
                gateway_url=str(gateway['gateway_url']),
                token=str(claim['device_token']),
                project_id=str(alpha['id']),
                agent=args.agent,
                turns=args.backfill_turns,
                run_id=f'{stamp}-{os.getpid()}',
            )
        native_artifact: dict[str, Any] | None = None
        if backfill is None and not args.live_artifact_smoke:
            native_artifact = seed_native_artifact_links(
                project_root=alpha_root,
                state_home=state_home,
                project_id=str(alpha['id']),
                agent=args.agent,
                run_id=f'{stamp}-{os.getpid()}',
                text_body_size_bytes=(
                    args.background_file_download_bytes
                    if args.background_file_download_smoke
                    or args.release_file_download_smoke
                    else None
                ),
            )
        debug_profile = debug_profile_base64(
            claim,
            gateway_url_override=profile_gateway_url,
        )
        device_report = emulator_smoke.ensure_emulator_ready(
            mobile_root=mobile_root,
            device_id=args.device_id,
            timeout_s=args.adb_timeout,
        )
        reverse_host_ports = gateway_reverse_host_ports(
            gateway_port=port,
            idle_proxy_enabled=idle_proxy_enabled,
            request_proxy_listen=args.request_proxy_listen,
        )
        reverse_host_port = reverse_host_ports[0]
        extra_reverse_host_ports = reverse_host_ports[1:]
        reverse_report = emulator_smoke.adb_reverse(
            mobile_root=mobile_root,
            device_id=args.device_id,
            host_port=reverse_host_port,
            timeout_s=args.adb_timeout,
        )
        extra_reverse_reports = [
            emulator_smoke.adb_reverse(
                mobile_root=mobile_root,
                device_id=args.device_id,
                host_port=extra_port,
                timeout_s=args.adb_timeout,
            )
            for extra_port in extra_reverse_host_ports
        ]
        native_pane_evidence: dict[str, Any] | None = None
        if args.release_long_history_smoke:
            if backfill is None:
                raise RuntimeError('release long-history smoke requires seeded backfill')
            if request_proxy is None:
                raise RuntimeError('release long-history smoke requires request proxy')
            integration = run_release_long_history_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                backfill=backfill,
                request_proxy=request_proxy,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'release_long_history_pressure',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'backfill': {
                    'turns': backfill.get('turns'),
                    'latest_text': backfill.get('latest_text'),
                    'oldest_text': backfill.get('oldest_text'),
                    'older_pages': backfill.get('older_pages'),
                },
                'metrics': integration.get('long_history_metrics'),
                'request_counts': integration.get('long_history_request_counts'),
                'request_totals': integration.get('long_history_request_totals'),
                'screenshot_path': integration.get('long_history_screenshot_path'),
            }
        elif args.release_file_download_smoke:
            if native_artifact is None:
                raise RuntimeError('release file download smoke requires seeded artifact')
            if request_proxy is None:
                raise RuntimeError('release file download smoke requires request proxy')
            integration = run_release_file_download_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                native_artifact=native_artifact,
                request_proxy=request_proxy,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'release_file_download_performance',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'artifact_file_name': native_artifact.get('text_file_name'),
                'artifact_file_size_bytes': native_artifact.get('text_size_bytes'),
                'download_metrics': integration.get('download_metrics'),
                'request_counts': integration.get('download_request_counts'),
                'screenshot_path': integration.get('download_screenshot_path'),
            }
        elif args.release_upload_smoke:
            if request_proxy is None:
                raise RuntimeError('release upload smoke requires request proxy')
            integration = run_release_upload_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                upload_size_bytes=args.upload_stress_bytes,
                request_proxy=request_proxy,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
                run_id=f'{stamp}-{os.getpid()}',
            )
            native_pane_evidence = {
                'mode': 'release_upload_stress',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'upload_file_name': integration.get('upload_file', {}).get('file_name'),
                'upload_file_size_bytes': integration.get('upload_file', {}).get('size_bytes'),
                'upload_metrics': integration.get('upload_metrics'),
                'request_counts': integration.get('upload_request_counts'),
                'screenshot_path': integration.get('upload_screenshot_path'),
            }
        elif args.release_reverse_recovery_smoke:
            if reverse_host_port is None:
                raise RuntimeError('release reverse recovery smoke missing reverse host port')
            if native_artifact is None:
                raise RuntimeError('release reverse recovery smoke requires seeded artifact')
            integration = run_release_reverse_recovery_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                native_artifact=native_artifact,
                reverse_host_port=reverse_host_port,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'release_reverse_recovery',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'reverse_removed': integration.get('reverse_removed'),
                'reverse_restored': integration.get('reverse_restored'),
                'recovery_metrics': integration.get('recovery_metrics'),
                'screenshot_path': integration.get('recovery_screenshot_path'),
            }
        elif args.release_idle_request_smoke:
            if request_proxy is None:
                raise RuntimeError('release idle request smoke requires request proxy')
            integration = run_release_idle_request_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                idle_seconds=args.idle_request_seconds,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                request_proxy=request_proxy,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'release_idle_request_audit',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'idle_seconds': args.idle_request_seconds,
                'request_counts': integration.get('idle_request_counts'),
                'request_totals': integration.get('idle_request_totals'),
                'screenshot_path': integration.get('idle_screenshot_path'),
            }
        elif args.release_project_list_smoke:
            integration = run_release_project_list_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                timeout_s=args.flutter_timeout,
                adb_timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'release_project_list_smoke',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'opened_project_text_found': integration.get('opened_project_text_found'),
                'screenshot_path': integration.get('screenshot_path'),
            }
        elif args.skip_integration:
            integration = {
                'skipped': True,
                'manual_app': install_debug_app(
                    mobile_root=mobile_root,
                    device_id=args.device_id,
                    android_package=args.android_package,
                    debug_profile=debug_profile,
                    timeout_s=args.flutter_timeout,
                ),
            }
        elif args.native_pane_multi_smoke:
            native_alpha_expected = f'CCB_MOBILE_NATIVE_ALPHA_OK_{stamp}'
            native_beta_expected = f'CCB_MOBILE_NATIVE_BETA_OK_{stamp}'
            native_alpha_prompt = (
                f'Please reply with exactly {native_alpha_expected} and no other text.'
            )
            native_beta_prompt = (
                f'Please reply with exactly {native_beta_expected} and no other text.'
            )
            integration = run_flutter_native_pane_multi_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                alpha_agent=args.agent,
                beta_agent=args.secondary_agent,
                alpha_prompt=native_alpha_prompt,
                alpha_expected_reply=native_alpha_expected,
                beta_prompt=native_beta_prompt,
                beta_expected_reply=native_beta_expected,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter multi native pane emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'multi_project_multi_agent',
                'cases': [
                    verify_native_pane_evidence(
                        project_root=alpha_root,
                        agent=args.agent,
                        prompt=native_alpha_prompt,
                        expected_reply=native_alpha_expected,
                    ),
                    verify_native_pane_evidence(
                        project_root=beta_root,
                        agent=args.secondary_agent,
                        prompt=native_beta_prompt,
                        expected_reply=native_beta_expected,
                    ),
                ],
            }
        elif args.native_command_smoke:
            integration = run_flutter_native_pane_command_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                command=args.native_command,
                expected_marker=args.native_command_marker,
                timeout_s=args.flutter_timeout,
                collect_device_metrics=args.native_command_device_metrics,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                adb_timeout_s=args.adb_timeout,
                require_live_terminal_marker=(
                    args.native_command_require_live_terminal_marker
                ),
                line_prefix=args.native_command_line_prefix,
                min_line_prefix_count=args.native_command_min_line_prefix_count,
                max_non_local_items=args.native_command_max_non_local_items,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter native pane command smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'native_pane_command',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'command': args.native_command,
                'expected_marker': args.native_command_marker,
                'timing': integration.get('timing'),
                'timings': integration.get('timings'),
                'device_metrics': integration.get('device_metrics'),
                'screenshot_path': integration.get('screenshot_path'),
                'screenshot_bytes': integration.get('screenshot_bytes'),
                'ui_dump_path': integration.get('ui_dump_path'),
                'line_prefix': integration.get('line_prefix'),
                'line_prefix_count': integration.get('line_prefix_count'),
                'min_line_prefix_count': integration.get('min_line_prefix_count'),
                'max_non_local_items': integration.get('max_non_local_items'),
            }
        elif args.desktop_origin_sync_smoke:
            desktop_marker = f'DESKTOP_ORIGIN_SYNC_MARKER_{stamp}'
            view_ms, alpha_view = http_get_json_auth(
                f'{str(gateway["gateway_url"]).rstrip("/")}/v1/projects/{quote(str(alpha["id"]))}/view',
                str(claim['device_token']),
            )
            desktop_target = resolve_agent_pane_target(
                view_payload=alpha_view,
                agent=args.agent,
                fallback_socket_path=project_tmux_socket_path(alpha_root),
            )
            integration = run_flutter_desktop_origin_sync_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                marker=desktop_marker,
                idle_before_refresh_s=args.desktop_origin_idle_seconds,
                desktop_target=desktop_target,
                backfill=backfill,
                build_mode=args.flutter_build_mode,
                state_home=state_home,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter desktop-origin sync smoke returned non-zero')
            native_pane_evidence = verify_desktop_origin_evidence(
                project_root=alpha_root,
                agent=args.agent,
                marker=desktop_marker,
            )
            native_pane_evidence['mode'] = 'desktop_origin_sync'
            native_pane_evidence['view_ms'] = round(view_ms, 3)
            native_pane_evidence['target'] = desktop_target
        elif args.reverse_recovery_smoke:
            integration = run_flutter_reverse_recovery_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                host_port=port,
                adb_timeout_s=args.adb_timeout,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter reverse recovery emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'reverse_recovery',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'reverse_removed': integration.get('reverse_removed'),
                'reverse_restored': integration.get('reverse_restored'),
                'reverse_removed_events': integration.get('reverse_removed_events'),
                'reverse_restored_events': integration.get('reverse_restored_events'),
            }
        elif args.gateway_restart_smoke:
            integration, gateway = run_flutter_gateway_restart_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                source_ccb=source_ccb,
                state_home=state_home,
                listen=args.gateway_listen,
                gateway=gateway,
                gateway_timeout_s=args.gateway_timeout,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter gateway restart emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'gateway_restart',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'gateway_stop_events': integration.get('gateway_stop_events'),
                'gateway_start_events': integration.get('gateway_start_events'),
            }
        elif args.ccbd_restart_smoke:
            integration = run_flutter_ccbd_restart_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                project_root=alpha_root,
                agent=args.agent,
                source_ccb=source_ccb,
                state_home=state_home,
                start_timeout_s=args.start_timeout,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter ccbd restart emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'ccbd_restart',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'ccbd_stop_events': integration.get('ccbd_stop_events'),
                'ccbd_start_events': integration.get('ccbd_start_events'),
            }
        elif args.idle_request_smoke:
            if request_proxy is None:
                raise RuntimeError('idle request smoke requires request proxy')
            integration = run_flutter_idle_request_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                idle_seconds=args.idle_request_seconds,
                metrics_sample_interval_s=args.idle_metrics_sample_interval,
                request_proxy=request_proxy,
                build_mode=args.flutter_build_mode,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter idle request emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'idle_request_audit',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'idle_seconds': args.idle_request_seconds,
                'request_counts': integration.get('idle_request_counts'),
                'request_totals': integration.get('idle_request_totals'),
            }
        elif args.background_resume_smoke:
            integration = run_flutter_background_resume_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                background_seconds=args.background_resume_seconds,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError(
                    'Flutter background/resume emulator smoke returned non-zero'
                )
            native_pane_evidence = {
                'mode': 'background_resume',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'background_seconds': args.background_resume_seconds,
                'background_events': integration.get('background_events'),
                'resume_events': integration.get('resume_events'),
            }
        elif args.background_reverse_recovery_smoke:
            integration = run_flutter_background_reverse_recovery_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                host_port=port,
                background_seconds=args.background_resume_seconds,
                adb_timeout_s=args.adb_timeout,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError(
                    'Flutter background reverse recovery emulator smoke returned non-zero'
                )
            native_pane_evidence = {
                'mode': 'background_reverse_recovery',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'host_port': port,
                'background_seconds': args.background_resume_seconds,
                'background_events': integration.get('background_events'),
                'reverse_removed_events': integration.get('reverse_removed_events'),
                'reverse_restored_events': integration.get('reverse_restored_events'),
                'resume_events': integration.get('resume_events'),
            }
        elif args.background_file_download_smoke:
            if native_artifact is None:
                raise RuntimeError('background file download smoke requires seeded artifact')
            integration = run_flutter_background_file_download_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                native_artifact=native_artifact,
                background_seconds=args.background_resume_seconds,
                build_mode=args.flutter_build_mode,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError(
                    'Flutter background file download emulator smoke returned non-zero'
                )
            native_pane_evidence = {
                'mode': 'background_file_download',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'artifact_file_name': native_artifact.get('text_file_name'),
                'artifact_file_size_bytes': native_artifact.get('text_size_bytes'),
                'background_seconds': args.background_resume_seconds,
                'background_events': integration.get('background_events'),
                'resume_events': integration.get('resume_events'),
                'download_hashes': integration.get('download_hashes'),
            }
        elif args.file_restart_smoke:
            if native_artifact is None:
                raise RuntimeError('file restart smoke requires seeded artifact')
            integration = run_flutter_background_file_download_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                native_artifact=native_artifact,
                background_seconds=args.background_resume_seconds,
                build_mode=args.flutter_build_mode,
                timeout_s=args.flutter_timeout,
                keep_installed=True,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter file restart emulator smoke returned non-zero')
            restart_evidence = verify_download_after_app_restart(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                download_hashes=integration.get('download_hashes') or [],
                expected_file_name=native_artifact['text_file_name'],
                expected_sha256=native_artifact['text_sha256'],
                timeout_s=args.adb_timeout,
            )
            native_pane_evidence = {
                'mode': 'file_restart_persistence',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'artifact_file_name': native_artifact.get('text_file_name'),
                'artifact_file_size_bytes': native_artifact.get('text_size_bytes'),
                'background_seconds': args.background_resume_seconds,
                'background_events': integration.get('background_events'),
                'resume_events': integration.get('resume_events'),
                'download_hashes': integration.get('download_hashes'),
                'restart_evidence': restart_evidence,
            }
        elif args.live_artifact_smoke:
            live_artifact = {
                'file_name': f'mobile-live-artifact-{stamp}-{os.getpid()}.txt',
                'content': f'CCB_LIVE_ARTIFACT_OK_{stamp}_{os.getpid()}',
            }
            view_ms, alpha_view = http_get_json_auth(
                f'{str(gateway["gateway_url"]).rstrip("/")}/v1/projects/{quote(str(alpha["id"]))}/view',
                str(claim['device_token']),
            )
            desktop_target = resolve_agent_pane_target(
                view_payload=alpha_view,
                agent=args.agent,
                fallback_socket_path=project_tmux_socket_path(alpha_root),
            )
            integration = run_flutter_live_artifact_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                artifact_file_name=live_artifact['file_name'],
                artifact_content=live_artifact['content'],
                build_mode=args.flutter_build_mode,
                desktop_target=desktop_target,
                state_home=state_home,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter live artifact emulator smoke returned non-zero')
            native_pane_evidence = verify_live_artifact_evidence(
                project_root=alpha_root,
                state_home=state_home,
                project_id=str(alpha['id']),
                agent=args.agent,
                prompt=live_artifact_prompt(
                    file_name=live_artifact['file_name'],
                    content=live_artifact['content'],
                ),
                artifact_file_name=live_artifact['file_name'],
                artifact_content=live_artifact['content'],
            )
            native_pane_evidence['mode'] = 'live_provider_artifact'
            native_pane_evidence['project_id'] = alpha.get('id')
            native_pane_evidence['project_name'] = alpha.get('display_name')
            native_pane_evidence['download_hashes'] = integration.get('download_hashes')
            native_pane_evidence['view_ms'] = round(view_ms, 3)
            native_pane_evidence['target'] = desktop_target
        elif args.attachment_rejection_smoke:
            integration = run_flutter_attachment_rejection_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                project=alpha,
                agent=args.agent,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter attachment rejection emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'attachment_rejection',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'project_root': str(alpha_root),
                'agent': args.agent,
                'unsupported_file': 'installer.exe',
                'oversized_file': 'too-large.pdf',
                'done': integration.get('done'),
                'stdout_tail': integration.get('stdout_tail'),
            }
        elif (
            args.replay_guard_smoke
            or args.replay_restart_smoke
            or args.replay_gateway_restart_smoke
        ):
            replay_expected = f'CCB_MOBILE_REPLAY_OK_{stamp}'
            replay_prompt = (
                f'Please reply with exactly {replay_expected} and no other text.'
            )
            if args.replay_gateway_restart_smoke:
                integration, gateway = run_flutter_replay_gateway_restart_smoke(
                    mobile_root=mobile_root,
                    device_id=args.device_id,
                    android_package=args.android_package,
                    debug_profile=debug_profile,
                    project=alpha,
                    agent=args.agent,
                    prompt=replay_prompt,
                    expected_reply=replay_expected,
                    source_ccb=source_ccb,
                    state_home=state_home,
                    listen=args.gateway_listen,
                    gateway=gateway,
                    gateway_timeout_s=args.gateway_timeout,
                    timeout_s=args.flutter_timeout,
                )
            elif args.replay_restart_smoke:
                integration = run_flutter_replay_restart_smoke(
                    mobile_root=mobile_root,
                    device_id=args.device_id,
                    android_package=args.android_package,
                    debug_profile=debug_profile,
                    project=alpha,
                    agent=args.agent,
                    prompt=replay_prompt,
                    expected_reply=replay_expected,
                    host_port=port,
                    adb_timeout_s=args.adb_timeout,
                    timeout_s=args.flutter_timeout,
                )
            else:
                integration = run_flutter_replay_guard_smoke(
                    mobile_root=mobile_root,
                    device_id=args.device_id,
                    android_package=args.android_package,
                    debug_profile=debug_profile,
                    project=alpha,
                    agent=args.agent,
                    prompt=replay_prompt,
                    expected_reply=replay_expected,
                    host_port=port,
                    adb_timeout_s=args.adb_timeout,
                    timeout_s=args.flutter_timeout,
                )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter replay guard emulator smoke returned non-zero')
            native_pane_evidence = verify_native_pane_replay_guard_evidence(
                project_root=alpha_root,
                agent=args.agent,
                prompt=replay_prompt,
                expected_reply=replay_expected,
            )
            if args.replay_gateway_restart_smoke:
                native_pane_evidence['mode'] = 'replay_gateway_restart'
            else:
                native_pane_evidence['mode'] = (
                    'replay_restart' if args.replay_restart_smoke else 'replay_guard'
                )
            native_pane_evidence['project_id'] = alpha.get('id')
            native_pane_evidence['project_name'] = alpha.get('display_name')
            native_pane_evidence['reverse_removed_events'] = integration.get(
                'reverse_removed_events'
            )
            native_pane_evidence['reverse_restored_events'] = integration.get(
                'reverse_restored_events'
            )
            if args.replay_gateway_restart_smoke:
                native_pane_evidence['force_stop_returncode'] = integration.get(
                    'force_stop_returncode'
                )
                native_pane_evidence['gateway_stop_events'] = integration.get(
                    'gateway_stop_events'
                )
                native_pane_evidence['gateway_start_events'] = integration.get(
                    'gateway_start_events'
                )
                native_pane_evidence['failed_stage_tail'] = integration.get(
                    'failed_stage_tail'
                )
                native_pane_evidence['retry_stage_tail'] = integration.get(
                    'retry_stage_tail'
                )
            elif args.replay_restart_smoke:
                native_pane_evidence['force_stop_returncode'] = integration.get(
                    'force_stop_returncode'
                )
                native_pane_evidence['failed_stage_tail'] = integration.get(
                    'failed_stage_tail'
                )
                native_pane_evidence['retry_stage_tail'] = integration.get(
                    'retry_stage_tail'
                )
        elif args.revoke_repair_smoke:
            repair_pairing = create_server_pairing_payload(
                source_ccb=source_ccb,
                state_home=state_home,
                project_id=str(gateway['project_id']),
                gateway_url=str(gateway['gateway_url']),
                route_provider='lan',
            )
            integration = run_flutter_revoke_repair_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                gateway_url=str(gateway['gateway_url']),
                repair_pairing_code=str(repair_pairing['pairing_code']),
                project=alpha,
                agent=args.agent,
                initial_claim=claim,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter revoke/re-pair emulator smoke returned non-zero')
            native_pane_evidence = {
                'mode': 'revoke_repair',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'initial_device_id': claim.get('device', {}).get('device_id'),
                'repair_pairing_id': repair_pairing.get('pairing_id'),
                'repair_pairing_expires_at': repair_pairing.get('expires_at'),
                'revoke_events': integration.get('revoke_events'),
                'old_token_denied': integration.get('old_token_denied'),
            }
        elif args.native_pane_smoke:
            native_repeat_cases: list[dict[str, Any]] = []
            for index in range(args.native_pane_repeat):
                suffix = f'{stamp}_{index + 1:02d}'
                native_expected = f'CCB_MOBILE_NATIVE_OK_{suffix}'
                native_prompt = (
                    f'Please reply with exactly {native_expected} and no other text.'
                )
                case_integration = run_flutter_native_pane_smoke(
                    mobile_root=mobile_root,
                    device_id=args.device_id,
                    android_package=args.android_package,
                    debug_profile=debug_profile,
                    project=alpha,
                    agent=args.agent,
                    prompt=native_prompt,
                    expected_reply=native_expected,
                    timeout_s=args.flutter_timeout,
                )
                if case_integration['returncode'] != 0:
                    raise RuntimeError(
                        'Flutter native pane emulator smoke returned non-zero'
                    )
                case_evidence = verify_native_pane_evidence(
                    project_root=alpha_root,
                    agent=args.agent,
                    prompt=native_prompt,
                    expected_reply=native_expected,
                )
                native_repeat_cases.append(
                    {
                        'index': index + 1,
                        'integration': case_integration,
                        'evidence': case_evidence,
                    }
                )
            integration = {
                'returncode': 0,
                'mode': 'native_pane_repeat',
                'repeat': args.native_pane_repeat,
                'cases': [case['integration'] for case in native_repeat_cases],
                'timing_summary': summarize_native_timing_cases(
                    [case['integration'].get('timing') for case in native_repeat_cases]
                ),
            }
            native_pane_evidence = {
                'mode': 'native_pane_repeat',
                'project_id': alpha.get('id'),
                'project_name': alpha.get('display_name'),
                'agent': args.agent,
                'repeat': args.native_pane_repeat,
                'cases': [
                    {
                        'index': case['index'],
                        **case['evidence'],
                    }
                    for case in native_repeat_cases
                ],
                'timing_summary': integration['timing_summary'],
            }
        else:
            integration = run_flutter_server_wide_smoke(
                mobile_root=mobile_root,
                device_id=args.device_id,
                android_package=args.android_package,
                debug_profile=debug_profile,
                alpha_project=alpha,
                beta_project=beta,
                agent=args.agent,
                secondary_agent=args.secondary_agent,
                backfill=backfill,
                native_artifact=native_artifact,
                upload_stress_bytes=args.upload_stress_bytes,
                build_mode=args.flutter_build_mode,
                timeout_s=args.flutter_timeout,
            )
            if integration['returncode'] != 0:
                raise RuntimeError('Flutter server-wide emulator smoke returned non-zero')
        result.update(
            {
                'status': 'ok',
                'app_head': git_head(mobile_root),
                'app_dirty': git_dirty(mobile_root),
                'source_head': git_head(source_ccb.parent),
                'source_dirty': git_dirty(source_ccb.parent),
                'started_projects': started_projects,
                'gateway': gateway_smoke.sanitize_gateway_summary(gateway),
                'projects': project_list,
                'claimed_device_id': claim.get('device', {}).get('device_id'),
                'long_history_backfill': backfill,
                'native_artifact': native_artifact,
                'device': device_report,
                'adb_reverse': reverse_report,
                'integration_smoke': integration,
                'native_pane_evidence': native_pane_evidence,
            }
        )
        if extra_reverse_reports:
            result['adb_reverse_extra'] = extra_reverse_reports
        exit_code = 0
    except Exception as exc:
        result['error'] = str(exc)
        if isinstance(gateway, dict):
            result['gateway'] = gateway_smoke.sanitize_gateway_summary(gateway)
    finally:
        if reverse_host_port is not None and not args.keep_running:
            result['adb_reverse_cleanup'] = emulator_smoke.adb_reverse_remove(
                mobile_root=mobile_root,
                device_id=args.device_id,
                host_port=reverse_host_port,
                timeout_s=args.adb_timeout,
            )
            if extra_reverse_host_ports:
                result['adb_reverse_cleanup_extra'] = [
                    emulator_smoke.adb_reverse_remove(
                        mobile_root=mobile_root,
                        device_id=args.device_id,
                        host_port=extra_port,
                        timeout_s=args.adb_timeout,
                    )
                    for extra_port in extra_reverse_host_ports
                ]
        if request_proxy is not None:
            result['request_proxy_final'] = request_proxy.summary()
            request_proxy.stop()
        result['cleanup'] = cleanup(
            source_ccb=source_ccb,
            projects=[alpha_root, beta_root],
            state_home=state_home,
            gateway_process=gateway.get('process') if isinstance(gateway, dict) else None,
            keep_running=args.keep_running,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.keep_running and args.hold:
            while True:
                time.sleep(60)
    return exit_code


def gateway_reverse_host_ports(
    *,
    gateway_port: int,
    idle_proxy_enabled: bool,
    request_proxy_listen: str | None,
) -> list[int]:
    if not idle_proxy_enabled:
        return [gateway_port]
    proxy_port = (
        gateway_smoke.parse_gateway_listen(request_proxy_listen)[1]
        if request_proxy_listen
        else gateway_port + 1
    )
    if proxy_port is None or proxy_port <= 0:
        raise ValueError(f'request proxy listen must use a fixed port: {request_proxy_listen}')
    if proxy_port == gateway_port:
        return [proxy_port]
    return [proxy_port, gateway_port]


def wait_for_server_projects(
    url: str,
    *,
    minimum: int,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    last_payload: dict[str, Any] = {}
    while True:
        last_payload = http_get_json(url)
        projects = list(last_payload.get('projects') or [])
        if len(projects) >= minimum:
            return last_payload
        if time.monotonic() >= deadline:
            return last_payload
        time.sleep(0.5)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Start two local CCB projects, install the server-wide mobile gateway, and run Android Emulator smoke.',
    )
    parser.add_argument('--source-ccb', type=Path, default=DEFAULT_SOURCE_CCB)
    parser.add_argument('--projects-root', type=Path)
    parser.add_argument('--state-home', type=Path)
    parser.add_argument('--provider', default='fake')
    parser.add_argument('--force-config', action='store_true')
    parser.add_argument('--device-id', default=DEFAULT_DEVICE_ID)
    parser.add_argument('--android-package', default=DEFAULT_ANDROID_PACKAGE)
    parser.add_argument('--gateway-listen', default=DEFAULT_GATEWAY_LISTEN)
    parser.add_argument('--agent', default=DEFAULT_AGENT)
    parser.add_argument('--secondary-agent', default=DEFAULT_SECONDARY_AGENT)
    parser.add_argument('--start-timeout', type=float, default=60.0)
    parser.add_argument('--gateway-timeout', type=float, default=30.0)
    parser.add_argument('--adb-timeout', type=float, default=45.0)
    parser.add_argument('--flutter-timeout', type=float, default=600.0)
    parser.add_argument(
        '--flutter-build-mode',
        choices=('debug', 'profile'),
        default='debug',
        help='build mode for the default server-wide/backfill and live-artifact integration smokes',
    )
    parser.add_argument(
        '--include-long-history-backfill',
        action='store_true',
        help='pre-seed a long real gateway conversation and run the AVD upward-scroll backfill smoke',
    )
    parser.add_argument(
        '--backfill-turns',
        type=int,
        default=56,
        help='number of real gateway message turns to pre-seed for the long-history backfill smoke',
    )
    parser.add_argument(
        '--skip-integration',
        action='store_true',
        help='install and launch the app with the paired profile but do not run the integration test',
    )
    parser.add_argument(
        '--release-project-list-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK and verify via ADB UIAutomator '
            'that real server-wide projects list and open without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--release-idle-request-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK, open a real server-wide '
            'selected-agent page via ADB UIAutomator, and audit idle gateway '
            'requests plus device metrics without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--release-long-history-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK, open a real server-wide '
            'selected-agent page via ADB UIAutomator, seed native long history, '
            'scroll until the oldest marker is visible, and collect request '
            'counts plus device metrics without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--release-file-download-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK, open a real server-wide '
            'selected-agent page via ADB UIAutomator, download a seeded '
            'artifact through the gateway proxy, and collect download/device '
            'metrics without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--release-upload-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK, push a user-origin file '
            'into Android Downloads, select it with the real system picker, '
            'send it through the selected-agent composer, download it back, '
            'and collect route/device metrics without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--release-reverse-recovery-smoke',
        action='store_true',
        help=(
            'build/install the seeded release APK, open a real server-wide '
            'selected-agent page via ADB UIAutomator, remove adb reverse, '
            'verify explicit refresh failure, restore adb reverse, and verify '
            'explicit refresh recovery without Flutter Driver'
        ),
    )
    parser.add_argument(
        '--native-pane-smoke',
        action='store_true',
        help='run a real provider native-pane send/receive integration smoke instead of the fake fixture flow',
    )
    parser.add_argument(
        '--native-pane-repeat',
        type=int,
        default=1,
        help='number of sequential native pane send/reply timing cases to run with --native-pane-smoke',
    )
    parser.add_argument(
        '--native-pane-multi-smoke',
        action='store_true',
        help='run real provider native-pane send/receive across alpha/primary and beta/secondary agents',
    )
    parser.add_argument(
        '--native-command-smoke',
        action='store_true',
        help='run a real provider command smoke and verify the command output is visible in the selected-agent timeline',
    )
    parser.add_argument(
        '--native-command',
        default='/status',
        help='provider command text to send with --native-command-smoke',
    )
    parser.add_argument(
        '--native-command-marker',
        default='Weekly limit:',
        help='visible non-local timeline text expected after --native-command is sent',
    )
    parser.add_argument(
        '--native-command-device-metrics',
        action='store_true',
        help=(
            'collect ADB meminfo/top, gfxinfo, power, logcat, screenshot, and '
            'UI dump around --native-command-smoke for strict real-AVD evidence'
        ),
    )
    parser.add_argument(
        '--native-command-require-live-terminal-marker',
        action='store_true',
        help=(
            'require the native-command expected marker to appear inside the '
            'live Terminal output conversation item before timing evidence is emitted'
        ),
    )
    parser.add_argument(
        '--native-command-line-prefix',
        default='',
        help=(
            'optional line prefix that must appear in non-local conversation '
            'model text when --native-command-min-line-prefix-count is set'
        ),
    )
    parser.add_argument(
        '--native-command-min-line-prefix-count',
        type=int,
        default=0,
        help=(
            'minimum non-local conversation lines starting with '
            '--native-command-line-prefix required before native command '
            'timing evidence is emitted'
        ),
    )
    parser.add_argument(
        '--native-command-max-non-local-items',
        type=int,
        default=0,
        help=(
            'optional upper bound for non-local conversation item count in the '
            'native command smoke; use this to prove high-volume output is not '
            'split into one card per line'
        ),
    )
    parser.add_argument(
        '--desktop-origin-sync-smoke',
        action='store_true',
        help='run a real desktop-pane input sync smoke: host writes tmux pane, app explicit-refreshes it',
    )
    parser.add_argument(
        '--reverse-recovery-smoke',
        action='store_true',
        help='run a real AVD recovery smoke by removing and restoring adb reverse during selected-agent refresh',
    )
    parser.add_argument(
        '--gateway-restart-smoke',
        action='store_true',
        help='run a real AVD recovery smoke by stopping and restarting the mobile gateway process on the same port',
    )
    parser.add_argument(
        '--ccbd-restart-smoke',
        action='store_true',
        help='run a real AVD recovery smoke by stopping and restarting the selected test project ccbd',
    )
    parser.add_argument(
        '--idle-request-smoke',
        action='store_true',
        help='run a real AVD no-idle-polling smoke and count gateway HTTP requests through a local proxy',
    )
    parser.add_argument(
        '--background-resume-smoke',
        action='store_true',
        help='run a real AVD smoke that backgrounds and resumes the app while a selected-agent page stays open',
    )
    parser.add_argument(
        '--background-reverse-recovery-smoke',
        action='store_true',
        help='run a real AVD smoke that backgrounds the app, removes/restores adb reverse, then resumes and refreshes',
    )
    parser.add_argument(
        '--background-file-download-smoke',
        action='store_true',
        help='run a real AVD smoke that starts an artifact download, backgrounds/resumes the app, and verifies the saved file hash',
    )
    parser.add_argument(
        '--file-restart-smoke',
        action='store_true',
        help='run a real AVD smoke that downloads an artifact, force-stops/restarts the app, and verifies the saved file hash persists',
    )
    parser.add_argument(
        '--live-artifact-smoke',
        action='store_true',
        help='run a real AVD smoke where the provider creates a workspace file and the app downloads it',
    )
    parser.add_argument(
        '--attachment-rejection-smoke',
        action='store_true',
        help='run a real AVD smoke that opens a server project and rejects unsupported and oversized local attachments without creating a draft',
    )
    parser.add_argument(
        '--replay-guard-smoke',
        action='store_true',
        help='run a real AVD smoke that fails a draft+attachment send while adb reverse is down, retries after restore, and verifies the pane receives it once',
    )
    parser.add_argument(
        '--replay-restart-smoke',
        action='store_true',
        help='run replay guard in two stages with app force-stop/restart between failed send and retry',
    )
    parser.add_argument(
        '--replay-gateway-restart-smoke',
        action='store_true',
        help='run replay guard in two stages with gateway stop/restart and app force-stop/restart between failed send and retry',
    )
    parser.add_argument(
        '--revoke-repair-smoke',
        action='store_true',
        help='run a real AVD smoke that revokes the current paired device, verifies fail-closed refresh, then re-pairs without clearing app data',
    )
    parser.add_argument(
        '--background-resume-seconds',
        type=int,
        default=10,
        help='seconds to keep the app in Android background during --background-resume-smoke',
    )
    parser.add_argument(
        '--background-file-download-bytes',
        type=int,
        default=8 * 1024 * 1024,
        help='size of the seeded artifact used by --background-file-download-smoke',
    )
    parser.add_argument(
        '--upload-stress-bytes',
        type=int,
        default=0,
        help='size of the user-origin attachment uploaded by the default server-wide integration smoke; 0 keeps the small fixture',
    )
    parser.add_argument(
        '--idle-request-seconds',
        type=int,
        default=180,
        help='seconds to leave selected-agent page idle during --idle-request-smoke',
    )
    parser.add_argument(
        '--idle-metrics-sample-interval',
        type=int,
        default=30,
        help='ADB meminfo/top sample interval during --idle-request-smoke',
    )
    parser.add_argument(
        '--request-proxy-listen',
        help='loopback host:port for the request-counting proxy; defaults to gateway port + 1',
    )
    parser.add_argument(
        '--desktop-origin-idle-seconds',
        type=int,
        default=30,
        help='seconds the desktop-origin sync smoke idles before tapping explicit refresh',
    )
    parser.add_argument(
        '--hold',
        action='store_true',
        help='with --keep-running, keep this process alive so gateway pipes stay open for manual testing',
    )
    parser.add_argument('--keep-running', action='store_true')
    args = parser.parse_args(argv)
    if args.native_pane_repeat < 1:
        parser.error('--native-pane-repeat must be >= 1')
    return args


def init_project(root: Path, *, provider: str, force: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    config = root / '.ccb' / 'ccb.config'
    if config.exists() and not force:
        return
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'cmd; {DEFAULT_AGENT}:{provider}, {DEFAULT_SECONDARY_AGENT}:{provider}\n',
        encoding='utf-8',
    )


def start_ccb_project(
    *,
    source_ccb: Path,
    project_root: Path,
    state_home: Path,
    timeout_s: float,
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(source_ccb), '--project', str(project_root), '-s'],
        cwd=str(project_root),
        env=source_env(project_root=project_root, state_home=state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            'ccb start failed\n'
            f'stdout:\n{completed.stdout}\n'
            f'stderr:\n{completed.stderr}'
        )
    return gateway_smoke.parse_key_value_lines(completed.stdout)


def stop_ccb_project(
    *,
    source_ccb: Path,
    project_root: Path,
    state_home: Path,
    timeout_s: float,
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(source_ccb), '--project', str(project_root), 'kill', '-f'],
        cwd=str(project_root),
        env=source_env(project_root=project_root, state_home=state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            'ccb kill failed\n'
            f'stdout:\n{completed.stdout}\n'
            f'stderr:\n{completed.stderr}'
        )
    summary = gateway_smoke.parse_key_value_lines(completed.stdout)
    summary['returncode'] = completed.returncode
    return summary


def start_server_mobile_gateway(
    *,
    source_ccb: Path,
    state_home: Path,
    listen: str,
    timeout_s: float,
) -> dict[str, Any]:
    process = subprocess.Popen(
        [str(source_ccb), 'install', 'mobile', '--listen', listen, '--route-provider', 'lan'],
        cwd=str(DEFAULT_PROJECT_PARENT),
        env=source_env(project_root=source_ccb.parent, state_home=state_home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    summary = gateway_smoke.read_gateway_startup(process, timeout_s=timeout_s)
    summary['process'] = process
    summary['mode'] = 'server_wide_install'
    return summary


class CountingHttpProxy:
    def __init__(self, *, listen: str, target_base_url: str) -> None:
        host, port = gateway_smoke.parse_gateway_listen(listen)
        if host not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError(f'request proxy listen must be loopback: {listen}')
        if port is None or port <= 0:
            raise ValueError(f'request proxy listen must use a fixed port: {listen}')
        self.listen = listen
        self.target_base_url = target_base_url.rstrip('/')
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer((host, port), self._handler_class())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name='ccb-mobile-request-counting-proxy',
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)
        counts_by_route: dict[str, int] = {}
        counts_by_method_route: dict[str, int] = {}
        for record in records:
            route = str(record.get('route') or '')
            method = str(record.get('method') or '')
            counts_by_route[route] = counts_by_route.get(route, 0) + 1
            key = f'{method} {route}'
            counts_by_method_route[key] = counts_by_method_route.get(key, 0) + 1
        return {
            'listen': self.listen,
            'target_base_url': self.target_base_url,
            'total_requests': len(records),
            'counts_by_route': counts_by_route,
            'counts_by_method_route': counts_by_method_route,
            'records': records,
        }

    def summary(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            'listen': snapshot['listen'],
            'target_base_url': snapshot['target_base_url'],
            'total_requests': snapshot['total_requests'],
            'counts_by_route': snapshot['counts_by_route'],
            'counts_by_method_route': snapshot['counts_by_method_route'],
        }

    def _record(
        self,
        *,
        method: str,
        path: str,
        route: str,
        status: int | None,
        elapsed_ms: float,
        error: str | None = None,
        response_bytes: int | None = None,
        response_sha256: str | None = None,
    ) -> None:
        with self._lock:
            self._records.append(
                {
                    'at': datetime.now(timezone.utc).isoformat(),
                    'method': method,
                    'path': path,
                    'route': route,
                    'status': status,
                    'elapsed_ms': round(elapsed_ms, 3),
                    **(
                        {'response_bytes': response_bytes}
                        if response_bytes is not None
                        else {}
                    ),
                    **(
                        {'response_sha256': response_sha256}
                        if response_sha256 is not None
                        else {}
                    ),
                    **({'error': error} if error else {}),
                }
            )

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self) -> None:  # noqa: N802
                self._proxy()

            def do_POST(self) -> None:  # noqa: N802
                self._proxy()

            def do_PUT(self) -> None:  # noqa: N802
                self._proxy()

            def do_DELETE(self) -> None:  # noqa: N802
                self._proxy()

            def log_message(self, format: str, *args: object) -> None:
                return

            def _proxy(self) -> None:
                started = time.monotonic()
                method = self.command
                path = self.path
                route = normalize_gateway_route(path)
                body_length = int(self.headers.get('Content-Length') or '0')
                body = self.rfile.read(body_length) if body_length > 0 else None
                target_url = f'{owner.target_base_url}{path}'
                request_headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower()
                    not in {'host', 'connection', 'proxy-connection', 'content-length'}
                }
                if body is not None:
                    request_headers['Content-Length'] = str(len(body))
                request = urllib.request.Request(
                    target_url,
                    data=body,
                    headers=request_headers,
                    method=method,
                )
                status: int | None = None
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        status = int(response.status)
                        response_body = response.read()
                        response_headers = dict(response.headers.items())
                except HTTPError as error:
                    status = int(error.code)
                    response_body = error.read()
                    response_headers = dict(error.headers.items())
                except Exception as error:  # pragma: no cover - exercised by AVD smoke failures.
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    owner._record(
                        method=method,
                        path=path,
                        route=route,
                        status=None,
                        elapsed_ms=elapsed_ms,
                        error=str(error),
                    )
                    payload = json.dumps({'error': str(error)}).encode('utf-8')
                    self.send_response(502)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                elapsed_ms = (time.monotonic() - started) * 1000.0
                owner._record(
                    method=method,
                    path=path,
                    route=route,
                    status=status,
                    elapsed_ms=elapsed_ms,
                    response_bytes=len(response_body),
                    response_sha256=hashlib.sha256(response_body).hexdigest(),
                )
                self.send_response(status)
                for key, value in response_headers.items():
                    if key.lower() in {
                        'connection',
                        'content-length',
                        'transfer-encoding',
                    }:
                        continue
                    self.send_header(key, value)
                self.send_header('Content-Length', str(len(response_body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(response_body)

        return Handler


def normalize_gateway_route(path: str) -> str:
    parsed = urlparse(path)
    segments = [segment for segment in parsed.path.split('/') if segment]
    if len(segments) >= 3 and segments[0] == 'v1' and segments[1] == 'projects':
        normalized = ['v1', 'projects', '{project}']
        index = 3
        while index < len(segments):
            segment = segments[index]
            normalized.append(segment)
            if segment == 'agents' and index + 1 < len(segments):
                normalized.append('{agent}')
                index += 2
                continue
            if segment in {'files', 'artifacts', 'terminal-sessions'} and index + 1 < len(segments):
                normalized.append('{id}')
                index += 2
                continue
            index += 1
        return '/' + '/'.join(normalized)
    if len(segments) >= 3 and segments[:2] == ['v1', 'pairing']:
        return '/' + '/'.join(segments[:3])
    return parsed.path or '/'


def stop_server_mobile_gateway(gateway: dict[str, Any]) -> dict[str, Any]:
    process = gateway.get('process')
    if not isinstance(process, subprocess.Popen):
        return {'stopped': False, 'reason': 'missing process'}
    if process.poll() is not None:
        return {
            'stopped': True,
            'already_exited': True,
            'pid': process.pid,
            'returncode': process.returncode,
        }
    process.terminate()
    try:
        process.wait(timeout=5)
        killed = False
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        killed = True
    return {
        'stopped': True,
        'already_exited': False,
        'killed': killed,
        'pid': process.pid,
        'returncode': process.returncode,
    }


def http_get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def http_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def http_get_json_auth(url: str, token: str) -> tuple[float, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'},
        method='GET',
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode('utf-8'))
    return (time.monotonic() - started) * 1000.0, payload


def http_post_json_auth(
    url: str,
    token: str,
    payload: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
        method='POST',
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=10) as response:
        decoded = json.loads(response.read().decode('utf-8'))
    return (time.monotonic() - started) * 1000.0, decoded


def seed_long_history(
    *,
    project_root: Path,
    state_home: Path,
    gateway_url: str,
    token: str,
    project_id: str,
    agent: str,
    turns: int,
    run_id: str,
) -> dict[str, Any]:
    if turns < 56:
        raise ValueError('long-history backfill smoke needs at least 56 seeded turns')
    base = gateway_url.rstrip('/')
    view_ms, view_payload = http_get_json_auth(
        f'{base}/v1/projects/{quote(project_id)}/view',
        token,
    )
    view = view_payload.get('view')
    namespace = view.get('namespace') if isinstance(view, dict) else {}
    namespace_epoch = namespace.get('epoch') if isinstance(namespace, dict) else None
    if not isinstance(namespace_epoch, int):
        raise RuntimeError(f'project view did not include namespace epoch: {view_payload!r}')

    seed_started = time.monotonic()
    markers = [
        f'backfill-{run_id}-{index:02d}'
        for index in range(turns)
    ]
    seed_metadata = write_codex_long_history_rollout(
        project_root=project_root,
        state_home=state_home,
        project_id=project_id,
        agent=agent,
        run_id=run_id,
        markers=markers,
    )
    latest_marker = markers[-1]
    oldest_marker = markers[0]
    latest_text = f'Native backfill answer {latest_marker}'
    oldest_text = f'Native backfill answer {oldest_marker}'
    poll_started = time.monotonic()
    polls = 0
    latest_page: dict[str, Any] = {}
    while time.monotonic() - poll_started < 45:
        polls += 1
        latest_ms, latest_page = http_get_json_auth(
            (
                f'{base}/v1/projects/{quote(project_id)}/agents/{quote(agent)}/'
                f'conversation?namespace_epoch={namespace_epoch}&limit=50'
            ),
            token,
        )
        if conversation_contains(latest_page, latest_text):
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(
            f'latest seeded reply was not visible: {latest_text}; '
            f'latest_page={latest_page!r}'
        )

    conversation = latest_page.get('conversation')
    if not isinstance(conversation, dict):
        raise RuntimeError(f'latest conversation payload missing conversation: {latest_page!r}')
    next_cursor = conversation.get('next_cursor')
    if not isinstance(next_cursor, str) or not next_cursor:
        raise RuntimeError(f'latest page did not expose next_cursor: {latest_page!r}')
    older_pages = 0
    older_ms_total = 0.0
    oldest_page_ms = 0.0
    cursor = next_cursor
    while True:
        older_ms, older_page = http_get_json_auth(
            (
                f'{base}/v1/projects/{quote(project_id)}/agents/{quote(agent)}/'
                f'conversation?namespace_epoch={namespace_epoch}&limit=50&cursor={quote(cursor)}'
            ),
            token,
        )
        older_pages += 1
        older_ms_total += older_ms
        if conversation_contains(older_page, oldest_text):
            oldest_page_ms = older_ms
            break
        conversation = older_page.get('conversation')
        if not isinstance(conversation, dict):
            raise RuntimeError(f'older conversation payload missing conversation: {older_page!r}')
        cursor = conversation.get('next_cursor')
        if not isinstance(cursor, str) or not cursor:
            raise RuntimeError(f'older pages did not include oldest seeded reply: {oldest_text}')

    return {
        'project_id': project_id,
        'agent': agent,
        'turns': turns,
        'namespace_epoch': namespace_epoch,
        'oldest_text': oldest_text,
        'latest_text': latest_text,
        'next_cursor': next_cursor,
        'view_ms': round(view_ms, 3),
        'latest_page_ms': round(latest_ms, 3),
        'older_page_ms': round(older_ms_total, 3),
        'oldest_page_ms': round(oldest_page_ms, 3),
        'older_pages': older_pages,
        'seed_mode': 'codex_native_rollout_fixture',
        'dataset': 'mixed_markdown_attachments_artifacts',
        'dataset_features': seed_metadata.get('dataset_features', []),
        'artifact_files': seed_metadata.get('artifact_files', []),
        'rollout_path': seed_metadata.get('rollout_path'),
        'seed_ms': round((time.monotonic() - seed_started) * 1000.0, 3),
        'latest_message_polls': polls,
    }


def write_codex_long_history_rollout(
    *,
    project_root: Path,
    state_home: Path,
    project_id: str,
    agent: str,
    run_id: str,
    markers: list[str],
) -> dict[str, Any]:
    home = project_root / '.ccb' / 'agents' / agent / 'provider-state' / 'codex' / 'home'
    thread_id = f'ccb-mobile-long-history-{run_id}'
    doc_file_id = f'mobile-long-history-doc-{run_id}'
    image_file_id = f'mobile-long-history-image-{run_id}'
    doc_file_name = f'mobile-long-history-{run_id}.md'
    image_file_name = f'mobile-long-history-{run_id}.png'
    doc_body = (
        f'# Mobile long-history artifact {run_id}\n\n'
        'This fixture document is linked from native Codex rollout history.\n'
        '\n'
        '| field | value |\n'
        '| --- | --- |\n'
        f'| run | {run_id} |\n'
        f'| agent | {agent} |\n'
    ).encode('utf-8')
    image_body = _one_pixel_png_bytes()
    _write_mobile_file(
        state_home=state_home,
        project_id=project_id,
        agent=agent,
        file_id=doc_file_id,
        file_name=doc_file_name,
        mime_type='text/markdown',
        body=doc_body,
    )
    _write_mobile_file(
        state_home=state_home,
        project_id=project_id,
        agent=agent,
        file_id=image_file_id,
        file_name=image_file_name,
        mime_type='image/png',
        body=image_body,
    )
    now_utc = datetime.now(timezone.utc)
    rollout_path = (
        home
        / 'sessions'
        / f'{now_utc:%Y}'
        / f'{now_utc:%m}'
        / f'{now_utc:%d}'
        / f'rollout-{thread_id}.jsonl'
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = [
        {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'session_meta',
            'payload': {
                'id': thread_id,
                'session_id': thread_id,
                'cwd': str(project_root),
                'source': 'ccb-mobile-avd-long-history-fixture',
            },
        }
    ]
    for index, marker in enumerate(markers):
        prompt = 'hi' if index % 11 == 0 else f'Native backfill question {marker}'
        answer_parts = [
            f'Native backfill answer {marker}',
            '',
            '## Mixed Markdown Section',
            '',
            '| field | value |',
            '| --- | --- |',
            f'| marker | {marker} |',
            f'| index | {index} |',
            '',
            '```text',
            f'rollout marker {marker}',
            '```',
        ]
        if index % 25 == 0:
            answer_parts.extend(
                [
                    '',
                    f'- [{doc_file_name}](ccb-artifact://{doc_file_id})',
                    f'- [{image_file_name}](ccb-artifact://{image_file_id})',
                ]
            )
        if index % 9 == 0:
            answer_parts.append(
                'Long paragraph: mobile rendering should keep scroll position stable '
                'while native transcript pages contain repeated short prompts, markdown, '
                'tables, code blocks, and downloadable artifact links.'
            )
        records.extend(
            [
                {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'type': 'event_msg',
                    'payload': {
                        'type': 'user_message',
                        'message': prompt,
                        'images': [],
                        'local_images': [],
                        'text_elements': [],
                    },
                },
                {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'type': 'event_msg',
                    'payload': {
                        'type': 'agent_message',
                        'message': '\n'.join(answer_parts),
                        'phase': 'final_answer',
                    },
                },
            ]
        )
    rollout_path.write_text(
        ''.join(f'{json.dumps(record, separators=(",", ":"))}\n' for record in records),
        encoding='utf-8',
    )
    _insert_codex_thread(
        home=home,
        thread_id=thread_id,
        rollout_path=rollout_path,
        project_root=project_root,
        source='ccb-mobile-avd-long-history-fixture',
        title='CCB Mobile long-history fixture',
        first_user_message='hi',
        preview=f'Native backfill answer {markers[-1]}',
    )
    return {
        'rollout_path': str(rollout_path),
        'dataset_features': [
            'markdown_heading',
            'markdown_table',
            'code_block',
            'duplicate_short_prompts',
            'document_artifact_link',
            'image_artifact_link',
        ],
        'artifact_files': [
            {
                'file_id': doc_file_id,
                'file_name': doc_file_name,
                'mime_type': 'text/markdown',
                'size_bytes': len(doc_body),
                'sha256': hashlib.sha256(doc_body).hexdigest(),
            },
            {
                'file_id': image_file_id,
                'file_name': image_file_name,
                'mime_type': 'image/png',
                'size_bytes': len(image_body),
                'sha256': hashlib.sha256(image_body).hexdigest(),
            },
        ],
    }


def seed_native_artifact_links(
    *,
    project_root: Path,
    state_home: Path,
    project_id: str,
    agent: str,
    run_id: str,
    text_body_size_bytes: int | None = None,
) -> dict[str, Any]:
    text_file_id = f'mobile-file-native-text-{run_id}'
    image_file_id = f'mobile-file-native-image-{run_id}'
    text_file_name = f'native-artifact-{run_id}.txt'
    image_file_name = f'native-image-{run_id}.png'
    marker = f'Native artifact bundle {run_id}'
    text_body = native_artifact_text_body(
        run_id=run_id,
        min_size_bytes=text_body_size_bytes,
    )
    image_body = _one_pixel_png_bytes()
    _write_mobile_file(
        state_home=state_home,
        project_id=project_id,
        agent=agent,
        file_id=text_file_id,
        file_name=text_file_name,
        mime_type='text/plain',
        body=text_body,
    )
    _write_mobile_file(
        state_home=state_home,
        project_id=project_id,
        agent=agent,
        file_id=image_file_id,
        file_name=image_file_name,
        mime_type='image/png',
        body=image_body,
    )

    thread_id = f'ccb-mobile-native-artifact-{run_id}'
    home = project_root / '.ccb' / 'agents' / agent / 'provider-state' / 'codex' / 'home'
    now_utc = datetime.now(timezone.utc)
    rollout_path = (
        home
        / 'sessions'
        / f'{now_utc:%Y}'
        / f'{now_utc:%m}'
        / f'{now_utc:%d}'
        / f'rollout-{thread_id}.jsonl'
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'session_meta',
            'payload': {
                'id': thread_id,
                'session_id': thread_id,
                'cwd': str(project_root),
                'source': 'ccb-mobile-avd-native-artifact-fixture',
            },
        },
        {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'event_msg',
            'payload': {
                'type': 'agent_message',
                'message': (
                    f'{marker}\n'
                    f'- [{text_file_name}](ccb-artifact://{text_file_id})\n'
                    f'- [{image_file_name}](ccb-artifact://{image_file_id})'
                ),
                'phase': 'final_answer',
            },
        },
    ]
    rollout_path.write_text(
        ''.join(f'{json.dumps(record, separators=(",", ":"))}\n' for record in records),
        encoding='utf-8',
    )
    _insert_codex_thread(
        home=home,
        thread_id=thread_id,
        rollout_path=rollout_path,
        project_root=project_root,
        source='ccb-mobile-avd-native-artifact-fixture',
        title='CCB Mobile native artifact fixture',
        first_user_message='',
        preview=marker,
    )
    return {
        'marker': marker,
        'text_file_id': text_file_id,
        'text_file_name': text_file_name,
        'text_sha256': hashlib.sha256(text_body).hexdigest(),
        'text_size_bytes': len(text_body),
        'image_file_id': image_file_id,
        'image_file_name': image_file_name,
        'image_sha256': hashlib.sha256(image_body).hexdigest(),
        'image_size_bytes': len(image_body),
    }


def seed_native_agent_reply(
    *,
    project_root: Path,
    agent: str,
    run_id: str,
    marker: str,
    source: str,
) -> dict[str, Any]:
    thread_id = f'ccb-mobile-{run_id}'
    home = project_root / '.ccb' / 'agents' / agent / 'provider-state' / 'codex' / 'home'
    now_utc = datetime.now(timezone.utc)
    rollout_path = (
        home
        / 'sessions'
        / f'{now_utc:%Y}'
        / f'{now_utc:%m}'
        / f'{now_utc:%d}'
        / f'rollout-{thread_id}.jsonl'
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            'timestamp': now_utc.isoformat(),
            'type': 'session_meta',
            'payload': {
                'id': thread_id,
                'session_id': thread_id,
                'cwd': str(project_root),
                'source': source,
            },
        },
        {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'event_msg',
            'payload': {
                'type': 'agent_message',
                'message': marker,
                'phase': 'final_answer',
            },
        },
    ]
    rollout_path.write_text(
        ''.join(f'{json.dumps(record, separators=(",", ":"))}\n' for record in records),
        encoding='utf-8',
    )
    _insert_codex_thread(
        home=home,
        thread_id=thread_id,
        rollout_path=rollout_path,
        project_root=project_root,
        source=source,
        title='CCB Mobile reverse recovery fixture',
        first_user_message='',
        preview=marker,
    )
    return {
        'marker': marker,
        'rollout_path': str(rollout_path),
        'thread_id': thread_id,
        'source': source,
    }


def native_artifact_text_body(*, run_id: str, min_size_bytes: int | None) -> bytes:
    base = f'Generated native artifact text for {run_id}\n'.encode('utf-8')
    if min_size_bytes is None or min_size_bytes <= len(base):
        return base
    chunk = (
        f'Generated native artifact background payload for {run_id}. '
        'This deterministic filler keeps the AVD download alive across '
        'Android background/resume.\n'
    ).encode('utf-8')
    repeats = ((min_size_bytes - len(base)) // len(chunk)) + 1
    return (base + chunk * repeats)[:min_size_bytes]


def _write_mobile_file(
    *,
    state_home: Path,
    project_id: str,
    agent: str,
    file_id: str,
    file_name: str,
    mime_type: str,
    body: bytes,
) -> None:
    directory = state_home / 'files' / project_id / agent / file_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'content.bin').write_bytes(body)
    (directory / 'metadata.json').write_text(
        json.dumps(
            {
                'schema_version': 1,
                'project_id': project_id,
                'agent': agent,
                'file_id': file_id,
                'file_name': file_name,
                'mime_type': mime_type,
                'size_bytes': len(body),
                'sha256': hashlib.sha256(body).hexdigest(),
                'created_at': datetime.now(timezone.utc).isoformat(),
            },
            separators=(',', ':'),
        ),
        encoding='utf-8',
    )


def _one_pixel_png_bytes() -> bytes:
    return bytes(
        [
            137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
            0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 31, 21, 196, 137, 0, 0,
            0, 13, 73, 68, 65, 84, 120, 156, 99, 248, 15, 4, 0, 9, 251, 3,
            253, 167, 156, 129, 226, 0, 0, 0, 0, 73, 69, 68, 174, 66, 96,
            130,
        ]
    )


def _insert_codex_thread(
    *,
    home: Path,
    thread_id: str,
    rollout_path: Path,
    project_root: Path,
    source: str,
    title: str,
    first_user_message: str,
    preview: str,
) -> None:
    state_path = home / 'state_5.sqlite'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    connection = sqlite3.connect(state_path)
    try:
        connection.execute(
            'create table if not exists threads ('
            'id text primary key, '
            'rollout_path text, '
            'created_at integer, '
            'updated_at integer, '
            'title text, '
            'first_user_message text, '
            'preview text)'
        )
        table_info = list(connection.execute('pragma table_info(threads)'))
        values_by_column: dict[str, object] = {
            'id': thread_id,
            'rollout_path': str(rollout_path),
            'created_at': now,
            'updated_at': now + 1,
            'created_at_ms': now * 1000,
            'updated_at_ms': (now + 1) * 1000,
            'source': source,
            'model_provider': 'openai',
            'cwd': str(project_root),
            'title': title,
            'sandbox_policy': 'workspace-write',
            'approval_mode': 'never',
            'tokens_used': 0,
            'has_user_event': 1 if first_user_message else 0,
            'archived': 0,
            'cli_version': '',
            'first_user_message': first_user_message,
            'agent_nickname': '',
            'agent_role': '',
            'memory_mode': 'enabled',
            'model': '',
            'reasoning_effort': '',
            'agent_path': '',
            'thread_source': 'user',
            'preview': preview,
            'recency_at': now + 1,
            'recency_at_ms': (now + 1) * 1000,
        }
        insert_columns: list[str] = []
        insert_values: list[object] = []
        for row in table_info:
            column = str(row[1])
            not_null = bool(row[3])
            default_value = row[4]
            column_type = str(row[2] or '').upper()
            if column in values_by_column:
                insert_columns.append(column)
                insert_values.append(values_by_column[column])
            elif not_null and default_value is None:
                insert_columns.append(column)
                insert_values.append(0 if 'INT' in column_type else '')
        placeholders = ', '.join('?' for _ in insert_columns)
        columns_sql = ', '.join(insert_columns)
        connection.execute(
            f'insert or replace into threads ({columns_sql}) values ({placeholders})',
            insert_values,
        )
        connection.commit()
    finally:
        connection.close()


def conversation_contains(payload: dict[str, Any], text: str) -> bool:
    conversation = payload.get('conversation')
    items = conversation.get('items') if isinstance(conversation, dict) else []
    if not isinstance(items, list):
        return False
    for item in items:
        if isinstance(item, dict) and text in str(item.get('body') or ''):
            return True
    return False


def extract_native_timing(stdout: str) -> dict[str, Any] | None:
    timings = extract_native_timings(stdout)
    return timings[0] if timings else None


def extract_native_timings(stdout: str) -> list[dict[str, Any]]:
    prefix = 'CCB_MOBILE_NATIVE_TIMING_JSON '
    timings: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        payload = json.loads(line[len(prefix):])
        if not isinstance(payload, dict):
            raise RuntimeError(f'native timing payload is not an object: {payload!r}')
        timings.append(payload)
    return timings


def extract_recovery_timing(stdout: str) -> dict[str, Any] | None:
    prefix = 'CCB_RECOVERY_TIMING_JSON '
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        payload = json.loads(line[len(prefix):])
        if not isinstance(payload, dict):
            raise RuntimeError(f'recovery timing payload is not an object: {payload!r}')
        return payload
    return None


def summarize_native_timing_cases(
    timings: list[dict[str, Any] | None],
) -> dict[str, Any]:
    fields = [
        'send_to_local_bubble_ms',
        'send_to_working_ms',
        'send_to_first_feedback_ms',
        'send_to_expected_reply_ms',
    ]
    feedback_kinds: dict[str, int] = {}
    for timing in timings:
        if not isinstance(timing, dict):
            continue
        kind = timing.get('first_feedback_kind')
        if isinstance(kind, str) and kind:
            feedback_kinds[kind] = feedback_kinds.get(kind, 0) + 1
    return {
        'case_count': len(timings),
        'timing_payload_count': sum(1 for timing in timings if isinstance(timing, dict)),
        'working_captured_count': sum(
            1
            for timing in timings
            if isinstance(timing, dict) and timing.get('send_to_working_ms') is not None
        ),
        'first_feedback_kinds': feedback_kinds,
        'fields': {
            field: summarize_numeric_timing_field(timings, field) for field in fields
        },
    }


def summarize_numeric_timing_field(
    timings: list[dict[str, Any] | None],
    field: str,
) -> dict[str, Any]:
    values: list[float] = []
    missing = 0
    for timing in timings:
        value = timing.get(field) if isinstance(timing, dict) else None
        if isinstance(value, (int, float)):
            values.append(float(value))
        else:
            missing += 1
    values.sort()
    return {
        'count': len(values),
        'missing': missing,
        'min_ms': round(values[0], 3) if values else None,
        'p50_ms': percentile_nearest_rank(values, 50),
        'p95_ms': percentile_nearest_rank(values, 95),
        'max_ms': round(values[-1], 3) if values else None,
    }


def percentile_nearest_rank(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    if percentile <= 0:
        return round(values[0], 3)
    if percentile >= 100:
        return round(values[-1], 3)
    index = max(0, min(len(values) - 1, math.ceil(len(values) * percentile / 100) - 1))
    return round(values[index], 3)


def require_project(projects: list[Any], root: Path) -> dict[str, Any]:
    expected = str(root)
    for project in projects:
        if isinstance(project, dict) and str(project.get('root') or '') == expected:
            return project
    available = [
        str(project.get('root') or project.get('display_name') or '')
        for project in projects
        if isinstance(project, dict)
    ]
    raise RuntimeError(f'missing server project root {expected}: {available}')


def debug_profile_base64(
    claim: dict[str, Any],
    *,
    gateway_url_override: str | None = None,
) -> str:
    profile = claim.get('host_profile')
    token = claim.get('device_token')
    if not isinstance(profile, dict) or not isinstance(token, str):
        raise RuntimeError(f'invalid pairing claim payload: {claim!r}')
    profile_payload = dict(profile)
    if gateway_url_override:
        profile_payload['gateway_url'] = gateway_url_override
    payload = {
        'schema_version': 1,
        'profile': profile_payload,
        'device_token': token,
        'project_id': profile.get('project_id'),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii')
    return encoded.rstrip('=')


def create_server_pairing_payload(
    *,
    source_ccb: Path,
    state_home: Path,
    project_id: str,
    gateway_url: str,
    route_provider: str,
) -> dict[str, Any]:
    script = """
import json
import sys
from mobile_gateway import MobileGatewayPairingStore, mobile_host_state_dir

store = MobileGatewayPairingStore(mobile_host_state_dir())
payload = store.create_pairing_payload(
    project_id=sys.argv[1],
    gateway_url=sys.argv[2],
    route_provider=sys.argv[3],
)
print(json.dumps(payload))
"""
    env = source_env(project_root=source_ccb.parent, state_home=state_home)
    lib_path = source_ccb.parent / 'lib'
    existing_pythonpath = str(env.get('PYTHONPATH') or '').strip()
    env['PYTHONPATH'] = (
        str(lib_path)
        if not existing_pythonpath
        else f'{lib_path}{os.pathsep}{existing_pythonpath}'
    )
    completed = subprocess.run(
        [sys.executable, '-c', script, project_id, gateway_url, route_provider],
        cwd=str(source_ccb.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            'creating server pairing payload failed\n'
            f'stdout:\n{completed.stdout}\n'
            f'stderr:\n{completed.stderr}'
        )
    return json.loads(completed.stdout)


def verify_old_device_token_denied(*, gateway_url: str, token: str) -> dict[str, Any]:
    try:
        http_get_json_auth(f'{gateway_url.rstrip("/")}/v1/devices/me', token)
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        if exc.code not in {401, 403}:
            raise RuntimeError(
                f'revoked device token returned unexpected status {exc.code}: {body}'
            ) from exc
        return {
            'status': 'denied',
            'status_code': exc.code,
            'body': body,
        }
    raise RuntimeError('revoked device token still accessed /v1/devices/me')


def flutter_integration_args(
    *,
    test_target: str,
    device_id: str,
    dart_defines: list[str],
    build_mode: str,
) -> list[str]:
    if build_mode == 'debug':
        args = ['flutter', 'test', test_target, '-d', device_id]
    elif build_mode == 'profile':
        args = [
            'flutter',
            'drive',
            '--profile',
            '--driver',
            'test_driver/integration_test.dart',
            '--target',
            test_target,
            '-d',
            device_id,
        ]
        dart_defines = [*dart_defines, 'CCB_MOBILE_TEST_PROFILE_SEED=true']
    else:
        raise ValueError(f'unsupported Flutter build mode: {build_mode}')
    for item in dart_defines:
        args.extend(['-D', item])
    return args


def run_flutter_server_wide_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    secondary_agent: str,
    backfill: dict[str, Any] | None,
    native_artifact: dict[str, Any] | None,
    upload_stress_bytes: int,
    build_mode: str,
    timeout_s: float,
) -> dict[str, Any]:
    if min_line_prefix_count > 0 and not line_prefix:
        raise ValueError(
            '--native-command-line-prefix is required when '
            '--native-command-min-line-prefix-count is positive'
        )
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    dart_defines = [
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        f'CCB_MOBILE_SERVER_PROJECT_ALPHA_ID={alpha_project["id"]}',
        f'CCB_MOBILE_SERVER_PROJECT_ALPHA_NAME={alpha_project["display_name"]}',
        f'CCB_MOBILE_SERVER_PROJECT_BETA_ID={beta_project["id"]}',
        f'CCB_MOBILE_SERVER_PROJECT_BETA_NAME={beta_project["display_name"]}',
        f'CCB_MOBILE_AGENT={agent}',
        f'CCB_MOBILE_SECONDARY_AGENT={secondary_agent}',
    ]
    if upload_stress_bytes > 0:
        dart_defines.append(f'CCB_MOBILE_UPLOAD_STRESS_BYTES={upload_stress_bytes}')
    if backfill is not None:
        dart_defines.extend(
            [
                'CCB_MOBILE_BACKFILL_ENABLED=true',
                'CCB_MOBILE_BACKFILL_ONLY=true',
                f'CCB_MOBILE_BACKFILL_PROJECT_ID={backfill["project_id"]}',
                f'CCB_MOBILE_BACKFILL_PROJECT_NAME={alpha_project["display_name"]}',
                f'CCB_MOBILE_BACKFILL_AGENT={backfill["agent"]}',
                f'CCB_MOBILE_BACKFILL_LATEST_TEXT={backfill["latest_text"]}',
                f'CCB_MOBILE_BACKFILL_OLDEST_TEXT={backfill["oldest_text"]}',
            ]
        )
    if native_artifact is not None:
        dart_defines.extend(
            [
                f'CCB_MOBILE_NATIVE_ARTIFACT_MARKER={native_artifact["marker"]}',
                (
                    'CCB_MOBILE_NATIVE_ARTIFACT_TEXT_FILE_NAME='
                    f'{native_artifact["text_file_name"]}'
                ),
                (
                    'CCB_MOBILE_NATIVE_ARTIFACT_IMAGE_FILE_NAME='
                    f'{native_artifact["image_file_name"]}'
                ),
                (
                    'CCB_MOBILE_NATIVE_ARTIFACT_TEXT_SHA256='
                    f'{native_artifact["text_sha256"]}'
                ),
                (
                    'CCB_MOBILE_NATIVE_ARTIFACT_IMAGE_SHA256='
                    f'{native_artifact["image_sha256"]}'
                ),
            ]
        )
    flutter_args = flutter_integration_args(
        test_target='integration_test/server_wide_gateway_smoke_test.dart',
        device_id=device_id,
        dart_defines=dart_defines,
        build_mode=build_mode,
    )
    completed = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=flutter_args,
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('server-wide Flutter smoke failed', completed))
    return {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'build_mode': build_mode,
        'stdout_tail': emulator_smoke.tail_lines(completed.stdout, 80),
        'stderr_tail': emulator_smoke.tail_lines(completed.stderr, 40),
        'backfill_metrics': extract_backfill_metrics(completed.stdout),
        'download_hashes': extract_download_hashes(completed.stdout),
        'upload_stress': extract_upload_stress_result(completed.stdout),
    }


def run_flutter_native_pane_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    prompt: str,
    expected_reply: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/native_pane_gateway_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_NATIVE_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_NATIVE_PROMPT={prompt}',
        '-D',
        f'CCB_MOBILE_NATIVE_EXPECTED={expected_reply}',
    ]
    completed = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=flutter_args,
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('native pane Flutter smoke failed', completed))
    return {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'prompt': prompt,
        'expected_reply': expected_reply,
        'timing': extract_native_timing(completed.stdout),
        'timings': extract_native_timings(completed.stdout),
        'stdout_tail': emulator_smoke.tail_lines(completed.stdout, 80),
        'stderr_tail': emulator_smoke.tail_lines(completed.stderr, 40),
    }


def run_flutter_native_pane_command_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    command: str,
    expected_marker: str,
    timeout_s: float,
    collect_device_metrics: bool = False,
    metrics_sample_interval_s: int = 30,
    adb_timeout_s: float = 30.0,
    require_live_terminal_marker: bool = False,
    line_prefix: str = '',
    min_line_prefix_count: int = 0,
    max_non_local_items: int = 0,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/native_pane_gateway_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_NATIVE_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_NATIVE_PROMPT={command}',
        '-D',
        f'CCB_MOBILE_NATIVE_EXPECTED={expected_marker}',
        '-D',
        'CCB_MOBILE_NATIVE_EXPECTED_MODE=any_non_local',
    ]
    if require_live_terminal_marker:
        flutter_args.extend(
            [
                '-D',
                'CCB_MOBILE_NATIVE_REQUIRE_LIVE_TERMINAL_EXPECTED=true',
            ]
        )
    if line_prefix:
        flutter_args.extend(['-D', f'CCB_MOBILE_NATIVE_LINE_PREFIX={line_prefix}'])
    if min_line_prefix_count > 0:
        flutter_args.extend(
            [
                '-D',
                (
                    'CCB_MOBILE_NATIVE_MIN_LINE_PREFIX_COUNT='
                    f'{min_line_prefix_count}'
                ),
            ]
        )
    if max_non_local_items > 0:
        flutter_args.extend(
            [
                '-D',
                f'CCB_MOBILE_NATIVE_MAX_NON_LOCAL_ITEMS={max_non_local_items}',
            ]
        )
    device_metrics: dict[str, Any] | None = None
    screenshot: dict[str, Any] | None = None
    ui_dump_path: str | None = None
    metrics_collector: IdleDeviceMetricsCollector | None = None
    if collect_device_metrics:
        metrics_collector = IdleDeviceMetricsCollector(
            mobile_root=mobile_root,
            device_id=device_id,
            android_package=android_package,
            sample_interval_s=max(1, metrics_sample_interval_s),
        )
    if collect_device_metrics:
        toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
        command_line = (
            f'. {quote_shell(str(toolchain))} && '
            f'{gateway_smoke.shell_command(flutter_args)}'
        )
        process = subprocess.Popen(
            ['sh', '-lc', command_line],
            cwd=str(mobile_root / 'app'),
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        output_lines: list[str] = []
        ready_seen = False
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError(
                        'native pane command Flutter smoke timed out\n'
                        + '\n'.join(output_lines[-160:])
                    )
                line = ''
                if process.stdout is not None:
                    ready, _, _ = select.select([process.stdout], [], [], 0.2)
                    if ready:
                        line = process.stdout.readline()
                if line:
                    output_lines.append(line.rstrip())
                    if (
                        not ready_seen
                        and 'CCB_MOBILE_NATIVE_READY_TO_SEND' in line
                    ):
                        ready_seen = True
                        if metrics_collector is not None:
                            metrics_collector.start()
                    if (
                        'CCB_MOBILE_NATIVE_TIMING_JSON' in line
                        and metrics_collector is not None
                        and device_metrics is None
                    ):
                        device_metrics = metrics_collector.stop()
                        screenshot_path = Path('/tmp') / (
                            f'ccb-mobile-native-command-{int(time.time())}.png'
                        )
                        screenshot = capture_android_screenshot(
                            mobile_root=mobile_root,
                            device_id=device_id,
                            path=screenshot_path,
                            timeout_s=adb_timeout_s,
                        )
                        ui_dump = dump_android_ui(
                            mobile_root=mobile_root,
                            device_id=device_id,
                            timeout_s=adb_timeout_s,
                        )
                        ui_path = Path('/tmp') / (
                            f'ccb-mobile-native-command-{int(time.time())}.xml'
                        )
                        ui_path.write_text(ui_dump, encoding='utf-8')
                        ui_dump_path = str(ui_path)
                if process.poll() is not None:
                    if process.stdout is not None:
                        rest = process.stdout.read()
                        if rest:
                            output_lines.extend(rest.splitlines())
                    break
            completed = subprocess.CompletedProcess(
                flutter_args,
                process.returncode,
                '\n'.join(output_lines),
                '',
            )
        finally:
            if metrics_collector is not None and device_metrics is None:
                device_metrics = metrics_collector.stop()
        if completed.returncode == 0 and not ready_seen:
            raise RuntimeError(
                'native pane command smoke did not emit '
                'CCB_MOBILE_NATIVE_READY_TO_SEND before completion\n'
                + '\n'.join(output_lines[-160:])
            )
    else:
        completed = emulator_smoke.run_toolchain(
            mobile_root=mobile_root,
            argv=flutter_args,
            cwd=mobile_root / 'app',
            timeout_s=timeout_s,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure('native pane command Flutter smoke failed', completed)
        )
    if device_metrics is not None:
        validate_idle_device_metrics(device_metrics)
        if screenshot is None:
            screenshot_path = Path('/tmp') / (
                f'ccb-mobile-native-command-{int(time.time())}.png'
            )
            screenshot = capture_android_screenshot(
                mobile_root=mobile_root,
                device_id=device_id,
                path=screenshot_path,
                timeout_s=adb_timeout_s,
            )
        if ui_dump_path is None:
            ui_dump = dump_android_ui(
                mobile_root=mobile_root,
                device_id=device_id,
                timeout_s=adb_timeout_s,
            )
            ui_path = Path('/tmp') / (
                f'ccb-mobile-native-command-{int(time.time())}.xml'
            )
            ui_path.write_text(ui_dump, encoding='utf-8')
            ui_dump_path = str(ui_path)
    result = {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'command': command,
        'expected_marker': expected_marker,
        'timing': extract_native_timing(completed.stdout),
        'timings': extract_native_timings(completed.stdout),
        'line_prefix': line_prefix or None,
        'min_line_prefix_count': (
            min_line_prefix_count if min_line_prefix_count > 0 else None
        ),
        'max_non_local_items': (
            max_non_local_items if max_non_local_items > 0 else None
        ),
        'stdout_tail': emulator_smoke.tail_lines(completed.stdout, 80),
        'stderr_tail': emulator_smoke.tail_lines(completed.stderr, 40),
    }
    timing = result.get('timing')
    if isinstance(timing, dict):
        result['line_prefix_count'] = timing.get('line_prefix_count')
    if device_metrics is not None:
        result['device_metrics'] = device_metrics
        result['screenshot_path'] = screenshot['path'] if screenshot is not None else None
        result['screenshot_bytes'] = screenshot['bytes'] if screenshot is not None else None
        result['ui_dump_path'] = ui_dump_path
    return result


def run_flutter_native_pane_multi_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    alpha_agent: str,
    beta_agent: str,
    alpha_prompt: str,
    alpha_expected_reply: str,
    beta_prompt: str,
    beta_expected_reply: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/native_pane_multi_gateway_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_NATIVE_ALPHA_PROJECT_ID={alpha_project["id"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_ALPHA_PROJECT_NAME={alpha_project["display_name"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_ALPHA_AGENT={alpha_agent}',
        '-D',
        f'CCB_MOBILE_NATIVE_ALPHA_PROMPT={alpha_prompt}',
        '-D',
        f'CCB_MOBILE_NATIVE_ALPHA_EXPECTED={alpha_expected_reply}',
        '-D',
        f'CCB_MOBILE_NATIVE_BETA_PROJECT_ID={beta_project["id"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_BETA_PROJECT_NAME={beta_project["display_name"]}',
        '-D',
        f'CCB_MOBILE_NATIVE_BETA_AGENT={beta_agent}',
        '-D',
        f'CCB_MOBILE_NATIVE_BETA_PROMPT={beta_prompt}',
        '-D',
        f'CCB_MOBILE_NATIVE_BETA_EXPECTED={beta_expected_reply}',
    ]
    completed = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=flutter_args,
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('multi native pane Flutter smoke failed', completed))
    return {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'alpha': {
            'project_id': alpha_project.get('id'),
            'project_name': alpha_project.get('display_name'),
            'agent': alpha_agent,
            'prompt': alpha_prompt,
            'expected_reply': alpha_expected_reply,
        },
        'beta': {
            'project_id': beta_project.get('id'),
            'project_name': beta_project.get('display_name'),
            'agent': beta_agent,
            'prompt': beta_prompt,
            'expected_reply': beta_expected_reply,
        },
        'stdout_tail': emulator_smoke.tail_lines(completed.stdout, 100),
        'stderr_tail': emulator_smoke.tail_lines(completed.stderr, 40),
    }


def run_flutter_desktop_origin_sync_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    marker: str,
    idle_before_refresh_s: int,
    desktop_target: dict[str, str],
    backfill: dict[str, Any] | None,
    build_mode: str,
    state_home: Path,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    dart_defines = [
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        f'CCB_MOBILE_DESKTOP_SYNC_PROJECT_ID={project["id"]}',
        f'CCB_MOBILE_DESKTOP_SYNC_PROJECT_NAME={project["display_name"]}',
        f'CCB_MOBILE_DESKTOP_SYNC_AGENT={agent}',
        f'CCB_MOBILE_DESKTOP_SYNC_MARKER={marker}',
        f'CCB_MOBILE_DESKTOP_SYNC_IDLE_SECONDS={idle_before_refresh_s}',
    ]
    if backfill is not None:
        dart_defines.extend([
            f'CCB_MOBILE_DESKTOP_SYNC_LATEST_TEXT={backfill["latest_text"]}',
            f'CCB_MOBILE_DESKTOP_SYNC_OLDEST_TEXT={backfill["oldest_text"]}',
        ])
    flutter_args = flutter_integration_args(
        test_target='integration_test/native_pane_desktop_sync_smoke_test.dart',
        device_id=device_id,
        dart_defines=dart_defines,
        build_mode=build_mode,
    )
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    injected = False
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'desktop-origin Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-120:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if not injected and 'CCB_DESKTOP_SYNC_READY' in line:
                    send_tmux_text(
                        socket_path=desktop_target['socket_path'],
                        pane_id=desktop_target['pane_id'],
                        text=marker,
                        state_home=state_home,
                    )
                    injected = True
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not injected:
        raise RuntimeError(
            'desktop-origin smoke never reached READY marker\n'
            + '\n'.join(output_lines[-120:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'desktop-origin Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-160:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'marker': marker,
        'build_mode': build_mode,
        'idle_before_refresh_seconds': idle_before_refresh_s,
        'backfill': (
            {
                'turns': backfill.get('turns'),
                'latest_text': backfill.get('latest_text'),
                'oldest_text': backfill.get('oldest_text'),
                'older_pages': backfill.get('older_pages'),
            }
            if backfill is not None
            else None
        ),
        'stdout_tail': output_lines[-120:],
        'desktop_injected': injected,
    }


def run_flutter_idle_request_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    idle_seconds: int,
    metrics_sample_interval_s: int,
    request_proxy: CountingHttpProxy,
    build_mode: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    dart_defines = [
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        f'CCB_MOBILE_IDLE_PROJECT_ID={project["id"]}',
        f'CCB_MOBILE_IDLE_PROJECT_NAME={project["display_name"]}',
        f'CCB_MOBILE_IDLE_AGENT={agent}',
        f'CCB_MOBILE_IDLE_SECONDS={idle_seconds}',
    ]
    flutter_args = flutter_integration_args(
        test_target='integration_test/server_wide_idle_request_smoke_test.dart',
        device_id=device_id,
        dart_defines=dart_defines,
        build_mode=build_mode,
    )
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    idle_started = False
    idle_counts: dict[str, Any] | None = None
    idle_device_metrics: dict[str, Any] | None = None
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'idle request Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_IDLE_AUDIT_BEGIN' in line:
                    request_proxy.reset()
                    metrics_collector.start()
                    idle_started = True
                if 'CCB_IDLE_AUDIT_END' in line:
                    idle_counts = request_proxy.snapshot()
                    idle_device_metrics = metrics_collector.stop()
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if idle_started and idle_device_metrics is None:
            idle_device_metrics = metrics_collector.stop()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not idle_started:
        raise RuntimeError(
            'idle request smoke never reached begin marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if idle_counts is None:
        raise RuntimeError(
            'idle request smoke never reached end marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'idle request Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )

    totals = idle_request_totals(idle_counts, idle_seconds=idle_seconds)
    if float(totals['conversation_terminal_requests_per_minute']) > 2.0:
        raise RuntimeError(
            'idle conversation/terminal request budget exceeded: '
            f'{json.dumps(totals, sort_keys=True)}; '
            f'counts={json.dumps(idle_counts.get("counts_by_route", {}), sort_keys=True)}'
        )
    if idle_device_metrics is not None:
        validate_idle_device_metrics(idle_device_metrics)
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'build_mode': build_mode,
        'idle_seconds': idle_seconds,
        'idle_request_counts': idle_counts,
        'idle_request_totals': totals,
        'idle_device_metrics': idle_device_metrics,
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_background_resume_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    background_seconds: int,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_background_resume_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_BACKGROUND_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_SECONDS={background_seconds}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    background_events: list[dict[str, Any]] = []
    resume_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'background/resume Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_BACKGROUND_RESUME_READY' in line:
                    background, resume = background_and_resume_app(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        android_package=android_package,
                        background_seconds=background_seconds,
                    )
                    background['marker'] = line.rstrip()
                    resume['marker'] = line.rstrip()
                    background_events.append(background)
                    resume_events.append(resume)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not background_events:
        raise RuntimeError(
            'background/resume smoke never reached ready marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not any('CCB_BACKGROUND_RESUME_DONE' in line for line in output_lines):
        raise RuntimeError(
            'background/resume smoke never reached done marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'background/resume Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'background_seconds': background_seconds,
        'background_events': background_events,
        'resume_events': resume_events,
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_background_reverse_recovery_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    host_port: int,
    background_seconds: int,
    adb_timeout_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_background_reverse_recovery_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_BACKGROUND_REVERSE_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_REVERSE_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_REVERSE_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_BACKGROUND_REVERSE_SECONDS={background_seconds}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    background_events: list[dict[str, Any]] = []
    reverse_removed_events: list[dict[str, Any]] = []
    reverse_restored_events: list[dict[str, Any]] = []
    resume_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'background reverse recovery Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_BACKGROUND_REVERSE_READY' in line:
                    background, removed, restored, resume = (
                        background_remove_restore_reverse_and_resume_app(
                            mobile_root=mobile_root,
                            device_id=device_id,
                            android_package=android_package,
                            host_port=host_port,
                            background_seconds=background_seconds,
                            adb_timeout_s=adb_timeout_s,
                        )
                    )
                    for event in (background, removed, restored, resume):
                        event['marker'] = line.rstrip()
                    background_events.append(background)
                    reverse_removed_events.append(removed)
                    reverse_restored_events.append(restored)
                    resume_events.append(resume)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not background_events:
        raise RuntimeError(
            'background reverse recovery smoke never reached ready marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not any('CCB_BACKGROUND_REVERSE_DONE' in line for line in output_lines):
        raise RuntimeError(
            'background reverse recovery smoke never reached done marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'background reverse recovery Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'host_port': host_port,
        'background_seconds': background_seconds,
        'background_events': background_events,
        'reverse_removed_events': reverse_removed_events,
        'reverse_restored_events': reverse_restored_events,
        'resume_events': resume_events,
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_background_file_download_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    native_artifact: dict[str, Any],
    background_seconds: int,
    build_mode: str,
    timeout_s: float,
    keep_installed: bool = False,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    dart_defines = [
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        f'CCB_MOBILE_BACKGROUND_FILE_PROJECT_ID={project["id"]}',
        f'CCB_MOBILE_BACKGROUND_FILE_PROJECT_NAME={project["display_name"]}',
        f'CCB_MOBILE_BACKGROUND_FILE_AGENT={agent}',
        f'CCB_MOBILE_BACKGROUND_FILE_SECONDS={background_seconds}',
        f'CCB_MOBILE_BACKGROUND_FILE_ARTIFACT_MARKER={native_artifact["marker"]}',
        (
            'CCB_MOBILE_BACKGROUND_FILE_ARTIFACT_NAME='
            f'{native_artifact["text_file_name"]}'
        ),
        (
            'CCB_MOBILE_BACKGROUND_FILE_ARTIFACT_SHA256='
            f'{native_artifact["text_sha256"]}'
        ),
    ]
    flutter_args = flutter_integration_args(
        test_target='integration_test/server_wide_background_file_download_smoke_test.dart',
        device_id=device_id,
        dart_defines=dart_defines,
        build_mode=build_mode,
    )
    if keep_installed:
        flutter_args.append('--no-uninstall')
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    background_events: list[dict[str, Any]] = []
    resume_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'background file download Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_BACKGROUND_FILE_DOWNLOAD_READY' in line:
                    background, resume = background_and_resume_app(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        android_package=android_package,
                        background_seconds=background_seconds,
                    )
                    background['marker'] = line.rstrip()
                    resume['marker'] = line.rstrip()
                    background_events.append(background)
                    resume_events.append(resume)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not background_events:
        raise RuntimeError(
            'background file download smoke never reached ready marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not any('CCB_BACKGROUND_FILE_DOWNLOAD_DONE' in line for line in output_lines):
        raise RuntimeError(
            'background file download smoke never reached done marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'background file download Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'build_mode': build_mode,
        'background_seconds': background_seconds,
        'artifact_file_name': native_artifact.get('text_file_name'),
        'artifact_file_size_bytes': native_artifact.get('text_size_bytes'),
        'background_events': background_events,
        'resume_events': resume_events,
        'download_hashes': extract_download_hashes('\n'.join(output_lines)),
        'stdout_tail': output_lines[-140:],
    }


def verify_download_after_app_restart(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    download_hashes: list[dict[str, Any]],
    expected_file_name: str,
    expected_sha256: str,
    timeout_s: float,
) -> dict[str, Any]:
    matching = [
        item
        for item in download_hashes
        if item.get('file_name') == expected_file_name and isinstance(item.get('path'), str)
    ]
    if not matching:
        raise RuntimeError(
            f'download hashes did not include persisted path for {expected_file_name}: '
            f'{download_hashes!r}'
        )
    download_path = str(matching[-1]['path'])
    force_stop = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'am', 'force-stop', android_package],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if force_stop.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure('force-stopping app failed', force_stop)
        )
    start = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'shell',
            'am',
            'start',
            '-W',
            '-n',
            android_main_activity(android_package),
        ],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )
    if start.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('restarting app failed', start))
    time.sleep(2)
    cat = subprocess.run(
        [
            'adb',
            '-s',
            device_id,
            'exec-out',
            'run-as',
            android_package,
            'cat',
            download_path,
        ],
        cwd=str(mobile_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    if cat.returncode != 0:
        raise RuntimeError(
            'reading downloaded file after app restart failed\n'
            f'path={download_path}\n'
            f'stdout={cat.stdout.decode("utf-8", errors="replace")}\n'
            f'stderr={cat.stderr.decode("utf-8", errors="replace")}'
        )
    actual_sha256 = hashlib.sha256(cat.stdout).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            'downloaded file hash changed after app restart: '
            f'expected {expected_sha256}, got {actual_sha256}'
        )
    return {
        'file_name': expected_file_name,
        'path': download_path,
        'size_bytes': len(cat.stdout),
        'sha256': actual_sha256,
        'expected_sha256': expected_sha256,
        'force_stop_returncode': force_stop.returncode,
        'restart_returncode': start.returncode,
        'restart_stdout_tail': emulator_smoke.tail_lines(start.stdout, 20),
    }


def live_artifact_prompt(*, file_name: str, content: str) -> str:
    return f'''
Create a UTF-8 text file in the current project root.
File name: {file_name}
Exact file content, with no trailing newline: {content}

Use a deterministic write such as Python write_text or printf so the file bytes match exactly.
After creating the file, reply with only this Markdown link and no other prose:
[{file_name}]({file_name})
'''.strip()


def run_flutter_live_artifact_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    artifact_file_name: str,
    artifact_content: str,
    build_mode: str,
    desktop_target: dict[str, str],
    state_home: Path,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    dart_defines = [
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        f'CCB_MOBILE_LIVE_ARTIFACT_PROJECT_ID={project["id"]}',
        f'CCB_MOBILE_LIVE_ARTIFACT_PROJECT_NAME={project["display_name"]}',
        f'CCB_MOBILE_LIVE_ARTIFACT_AGENT={agent}',
        f'CCB_MOBILE_LIVE_ARTIFACT_FILE_NAME={artifact_file_name}',
        f'CCB_MOBILE_LIVE_ARTIFACT_CONTENT={artifact_content}',
    ]
    flutter_args = flutter_integration_args(
        test_target='integration_test/server_wide_live_artifact_smoke_test.dart',
        device_id=device_id,
        dart_defines=dart_defines,
        build_mode=build_mode,
    )
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    injected = False
    prompt = live_artifact_prompt(
        file_name=artifact_file_name,
        content=artifact_content,
    )
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'live artifact Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-180:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if not injected and 'CCB_LIVE_ARTIFACT_READY' in line:
                    paste_tmux_text(
                        socket_path=desktop_target['socket_path'],
                        pane_id=desktop_target['pane_id'],
                        text=prompt,
                        state_home=state_home,
                    )
                    injected = True
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    stdout = '\n'.join(output_lines)
    if not injected:
        raise RuntimeError(
            'live artifact smoke never reached READY marker\n'
            + '\n'.join(output_lines[-180:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'live artifact Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-220:])
        )
    if not any('CCB_LIVE_ARTIFACT_SMOKE_DONE' in line for line in output_lines):
        raise RuntimeError(
            'live artifact smoke never reached done marker\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'build_mode': build_mode,
        'artifact_file_name': artifact_file_name,
        'artifact_content_sha256': hashlib.sha256(
            artifact_content.encode('utf-8')
        ).hexdigest(),
        'download_hashes': extract_download_hashes(stdout),
        'live_artifact_done': extract_live_artifact_done(stdout),
        'injected': injected,
        'target': desktop_target,
        'stdout_tail': output_lines[-140:],
        'stderr_tail': [],
    }


def paste_tmux_text(
    *,
    socket_path: str,
    pane_id: str,
    text: str,
    state_home: Path,
) -> None:
    env = os.environ.copy()
    env['CCB_SOURCE_RUNTIME_OK'] = '1'
    env['CCB_MOBILE_HOST_STATE_HOME'] = str(state_home)
    buffer_name = f'ccb-mobile-smoke-{os.getpid()}'
    commands = [
        (
            ['tmux', '-S', socket_path, 'load-buffer', '-b', buffer_name, '-'],
            text,
        ),
        (
            [
                'tmux',
                '-S',
                socket_path,
                'paste-buffer',
                '-b',
                buffer_name,
                '-t',
                pane_id,
            ],
            None,
        ),
        (
            ['tmux', '-S', socket_path, 'send-keys', '-t', pane_id, 'Enter'],
            None,
        ),
        (
            ['tmux', '-S', socket_path, 'delete-buffer', '-b', buffer_name],
            None,
        ),
    ]
    for argv, stdin in commands:
        completed = subprocess.run(
            argv,
            input=stdin,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f'tmux pane paste failed for {pane_id}\n'
                f'argv={argv!r}\n'
                f'stdout:\n{completed.stdout}\n'
                f'stderr:\n{completed.stderr}'
            )


def run_flutter_attachment_rejection_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_attachment_rejection_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_ATTACHMENT_REJECTION_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_ATTACHMENT_REJECTION_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_ATTACHMENT_REJECTION_AGENT={agent}',
    ]
    completed = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=flutter_args,
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure(
                'attachment rejection Flutter smoke failed',
                completed,
            )
        )
    done = 'CCB_ATTACHMENT_REJECTION_SMOKE_DONE' in completed.stdout
    if not done:
        raise RuntimeError(
            'attachment rejection Flutter smoke never reached done marker\n'
            + '\n'.join(emulator_smoke.tail_lines(completed.stdout, 160))
        )
    return {
        'returncode': completed.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'done': done,
        'stdout_tail': emulator_smoke.tail_lines(completed.stdout, 140),
        'stderr_tail': emulator_smoke.tail_lines(completed.stderr, 40),
    }


def run_flutter_replay_guard_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    prompt: str,
    expected_reply: str,
    host_port: int,
    adb_timeout_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/native_pane_replay_guard_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_REPLAY_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_REPLAY_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_REPLAY_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_REPLAY_PROMPT={prompt}',
        '-D',
        f'CCB_MOBILE_REPLAY_EXPECTED={expected_reply}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    reverse_removed_events: list[dict[str, Any]] = []
    reverse_restored_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'replay guard Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_REPLAY_GUARD_REMOVE_REVERSE_READY' in line:
                    removed = emulator_smoke.adb_reverse_remove(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    removed['marker'] = line.rstrip()
                    if not removed.get('removed'):
                        raise RuntimeError(
                            'adb reverse removal failed during replay guard smoke: '
                            f'{removed!r}'
                        )
                    reverse_removed_events.append(removed)
                if 'CCB_REPLAY_GUARD_RESTORE_REVERSE_READY' in line:
                    restored = emulator_smoke.adb_reverse(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    restored['marker'] = line.rstrip()
                    reverse_restored_events.append(restored)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not reverse_removed_events:
        raise RuntimeError(
            'replay guard smoke never removed adb reverse\n'
            + '\n'.join(output_lines[-160:])
        )
    if not reverse_restored_events:
        raise RuntimeError(
            'replay guard smoke never restored adb reverse\n'
            + '\n'.join(output_lines[-160:])
        )
    if not any('CCB_REPLAY_GUARD_DONE' in line for line in output_lines):
        raise RuntimeError(
            'replay guard smoke never reached done marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'replay guard Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'prompt': prompt,
        'expected_reply': expected_reply,
        'reverse_removed_events': reverse_removed_events,
        'reverse_restored_events': reverse_restored_events,
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_replay_restart_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    prompt: str,
    expected_reply: str,
    host_port: int,
    adb_timeout_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    failed = _run_flutter_replay_stage(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        project=project,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
        stage='fail',
        no_uninstall=True,
        host_port=host_port,
        adb_timeout_s=adb_timeout_s,
        timeout_s=timeout_s,
        failure_mode='reverse',
        handle_reverse_remove=True,
        handle_reverse_restore=False,
    )
    if failed['returncode'] != 0:
        raise RuntimeError(
            'replay restart failed stage returned non-zero\n'
            + '\n'.join(failed['stdout_tail'])
        )
    if not failed['reverse_removed_events']:
        raise RuntimeError(
            'replay restart failed stage never removed adb reverse\n'
            + '\n'.join(failed['stdout_tail'])
        )
    if not failed['failed_persist_ready']:
        raise RuntimeError(
            'replay restart failed stage never reached persistence marker\n'
            + '\n'.join(failed['stdout_tail'])
        )

    force_stop = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'am', 'force-stop', android_package],
        cwd=mobile_root,
        timeout_s=adb_timeout_s,
    )
    if force_stop.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('force-stopping app failed', force_stop))
    restored = emulator_smoke.adb_reverse(
        mobile_root=mobile_root,
        device_id=device_id,
        host_port=host_port,
        timeout_s=adb_timeout_s,
    )

    retry = _run_flutter_replay_stage(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        project=project,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
        stage='retry',
        no_uninstall=True,
        host_port=host_port,
        adb_timeout_s=adb_timeout_s,
        timeout_s=timeout_s,
        failure_mode='reverse',
        handle_reverse_remove=False,
        handle_reverse_restore=False,
    )
    if retry['returncode'] != 0:
        raise RuntimeError(
            'replay restart retry stage returned non-zero\n'
            + '\n'.join(retry['stdout_tail'])
        )
    if not retry['done']:
        raise RuntimeError(
            'replay restart retry stage never reached done marker\n'
            + '\n'.join(retry['stdout_tail'])
        )

    return {
        'returncode': retry['returncode'],
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'prompt': prompt,
        'expected_reply': expected_reply,
        'force_stop_returncode': force_stop.returncode,
        'reverse_removed_events': failed['reverse_removed_events'],
        'reverse_restored_events': [restored],
        'failed_stage_tail': failed['stdout_tail'],
        'retry_stage_tail': retry['stdout_tail'],
        'stdout_tail': retry['stdout_tail'],
    }


def run_flutter_replay_gateway_restart_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    prompt: str,
    expected_reply: str,
    source_ccb: Path,
    state_home: Path,
    listen: str,
    gateway: dict[str, Any],
    gateway_timeout_s: float,
    timeout_s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    failed = _run_flutter_replay_stage(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        project=project,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
        stage='fail',
        no_uninstall=True,
        host_port=0,
        adb_timeout_s=15.0,
        timeout_s=timeout_s,
        failure_mode='gateway',
        gateway_stop_on_failure_marker=gateway,
        handle_reverse_remove=False,
        handle_reverse_restore=False,
    )
    if failed['returncode'] != 0:
        raise RuntimeError(
            'replay gateway restart failed stage returned non-zero\n'
            + '\n'.join(failed['stdout_tail'])
        )
    if not failed['gateway_stop_events']:
        raise RuntimeError(
            'replay gateway restart failed stage never stopped gateway\n'
            + '\n'.join(failed['stdout_tail'])
        )
    if not failed['failed_persist_ready']:
        raise RuntimeError(
            'replay gateway restart failed stage never reached persistence marker\n'
            + '\n'.join(failed['stdout_tail'])
        )

    force_stop = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'am', 'force-stop', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    if force_stop.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('force-stopping app failed', force_stop))

    restarted_gateway = start_server_mobile_gateway(
        source_ccb=source_ccb,
        state_home=state_home,
        listen=listen,
        timeout_s=gateway_timeout_s,
    )
    gateway_start_events = [
        {'gateway': gateway_smoke.sanitize_gateway_summary(restarted_gateway)}
    ]

    retry = _run_flutter_replay_stage(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        project=project,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
        stage='retry',
        no_uninstall=True,
        host_port=0,
        adb_timeout_s=15.0,
        timeout_s=timeout_s,
        failure_mode='gateway',
        handle_reverse_remove=False,
        handle_reverse_restore=False,
    )
    if retry['returncode'] != 0:
        raise RuntimeError(
            'replay gateway restart retry stage returned non-zero\n'
            + '\n'.join(retry['stdout_tail'])
        )
    if not retry['done']:
        raise RuntimeError(
            'replay gateway restart retry stage never reached done marker\n'
            + '\n'.join(retry['stdout_tail'])
        )

    return (
        {
            'returncode': retry['returncode'],
            'app_data_clear_returncode': clear_result.returncode,
            'project_id': project.get('id'),
            'project_name': project.get('display_name'),
            'agent': agent,
            'prompt': prompt,
            'expected_reply': expected_reply,
            'force_stop_returncode': force_stop.returncode,
            'gateway_stop_events': failed['gateway_stop_events'],
            'gateway_start_events': gateway_start_events,
            'reverse_removed_events': [],
            'reverse_restored_events': [],
            'failed_stage_tail': failed['stdout_tail'],
            'retry_stage_tail': retry['stdout_tail'],
            'stdout_tail': retry['stdout_tail'],
        },
        restarted_gateway,
    )


def _run_flutter_replay_stage(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    prompt: str,
    expected_reply: str,
    stage: str,
    no_uninstall: bool,
    host_port: int,
    adb_timeout_s: float,
    timeout_s: float,
    failure_mode: str,
    gateway_stop_on_failure_marker: dict[str, Any] | None = None,
    handle_reverse_remove: bool,
    handle_reverse_restore: bool,
) -> dict[str, Any]:
    flutter_args = [
        'flutter',
        'test',
        'integration_test/native_pane_replay_guard_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_REPLAY_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_REPLAY_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_REPLAY_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_REPLAY_PROMPT={prompt}',
        '-D',
        f'CCB_MOBILE_REPLAY_EXPECTED={expected_reply}',
        '-D',
        f'CCB_MOBILE_REPLAY_STAGE={stage}',
        '-D',
        f'CCB_MOBILE_REPLAY_FAILURE_MODE={failure_mode}',
    ]
    if no_uninstall:
        flutter_args.append('--no-uninstall')
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    reverse_removed_events: list[dict[str, Any]] = []
    reverse_restored_events: list[dict[str, Any]] = []
    gateway_stop_events: list[dict[str, Any]] = []
    failed_persist_ready = False
    done = False
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    f'replay {stage} Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if handle_reverse_remove and 'CCB_REPLAY_GUARD_REMOVE_REVERSE_READY' in line:
                    removed = emulator_smoke.adb_reverse_remove(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    removed['marker'] = line.rstrip()
                    if not removed.get('removed'):
                        raise RuntimeError(
                            'adb reverse removal failed during replay restart smoke: '
                            f'{removed!r}'
                        )
                    reverse_removed_events.append(removed)
                if (
                    gateway_stop_on_failure_marker is not None
                    and 'CCB_REPLAY_GUARD_STOP_GATEWAY_READY' in line
                ):
                    stop_event = stop_server_mobile_gateway(gateway_stop_on_failure_marker)
                    if not stop_event.get('stopped'):
                        raise RuntimeError(
                            'gateway stop failed during replay gateway restart smoke: '
                            f'{stop_event!r}'
                        )
                    stop_event['marker'] = line.rstrip()
                    gateway_stop_events.append(stop_event)
                if handle_reverse_restore and 'CCB_REPLAY_GUARD_RESTORE_REVERSE_READY' in line:
                    restored = emulator_smoke.adb_reverse(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    restored['marker'] = line.rstrip()
                    reverse_restored_events.append(restored)
                if 'CCB_REPLAY_GUARD_FAILED_PERSIST_READY' in line:
                    failed_persist_ready = True
                if 'CCB_REPLAY_GUARD_DONE' in line:
                    done = True
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    return {
        'returncode': process.returncode,
        'reverse_removed_events': reverse_removed_events,
        'reverse_restored_events': reverse_restored_events,
        'gateway_stop_events': gateway_stop_events,
        'failed_persist_ready': failed_persist_ready,
        'done': done,
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_revoke_repair_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    gateway_url: str,
    repair_pairing_code: str,
    project: dict[str, Any],
    agent: str,
    initial_claim: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_revoke_repair_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_REPAIR_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_REPAIR_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_REPAIR_AGENT={agent}',
        '-D',
        f'CCB_MOBILE_REPAIR_GATEWAY_URL={gateway_url}',
        '-D',
        f'CCB_MOBILE_REPAIR_PAIRING_CODE={repair_pairing_code}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    revoke_events: list[dict[str, Any]] = []
    old_token_denied: dict[str, Any] | None = None
    device = initial_claim.get('device')
    device_id_value = (
        str(device.get('device_id') or '').strip()
        if isinstance(device, dict)
        else ''
    )
    token = str(initial_claim.get('device_token') or '').strip()
    if not device_id_value or not token:
        raise RuntimeError(f'invalid initial pairing claim for revoke smoke: {initial_claim!r}')
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'revoke/re-pair Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_REPAIR_READY_REVOKE' in line:
                    _, revoked = http_post_json_auth(
                        f'{gateway_url.rstrip("/")}/v1/devices/{quote(device_id_value)}/revoke',
                        token,
                        {},
                    )
                    old_token_denied = verify_old_device_token_denied(
                        gateway_url=gateway_url,
                        token=token,
                    )
                    revoke_events.append(
                        {
                            'marker': line.rstrip(),
                            'device_id': device_id_value,
                            'revoked': revoked,
                        }
                    )
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not revoke_events:
        raise RuntimeError(
            'revoke/re-pair smoke never revoked the initial device\n'
            + '\n'.join(output_lines[-160:])
        )
    if old_token_denied is None:
        raise RuntimeError(
            'revoke/re-pair smoke did not verify old token denial\n'
            + '\n'.join(output_lines[-160:])
        )
    if not any('CCB_REPAIR_DONE' in line for line in output_lines):
        raise RuntimeError(
            'revoke/re-pair smoke never reached done marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'revoke/re-pair Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'revoke_events': revoke_events,
        'old_token_denied': old_token_denied,
        'stdout_tail': output_lines[-140:],
    }


def android_main_activity(android_package: str) -> str:
    return f'{android_package}/.MainActivity'


def background_and_resume_app(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    background_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    background = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'input', 'keyevent', 'HOME'],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    if background.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure('backgrounding app failed', background)
        )
    time.sleep(max(1, background_seconds))
    resume = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'shell',
            'am',
            'start',
            '-n',
            android_main_activity(android_package),
        ],
        cwd=mobile_root,
        timeout_s=30.0,
    )
    if resume.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('resuming app failed', resume))
    return (
        {
            'returncode': background.returncode,
            'stdout_tail': emulator_smoke.tail_lines(background.stdout, 20),
            'stderr_tail': emulator_smoke.tail_lines(background.stderr, 20),
        },
        {
            'returncode': resume.returncode,
            'stdout_tail': emulator_smoke.tail_lines(resume.stdout, 20),
            'stderr_tail': emulator_smoke.tail_lines(resume.stderr, 20),
            'component': android_main_activity(android_package),
        },
    )


def background_remove_restore_reverse_and_resume_app(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    host_port: int,
    background_seconds: int,
    adb_timeout_s: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    background = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'input', 'keyevent', 'HOME'],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    if background.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure('backgrounding app failed', background)
        )
    removed = emulator_smoke.adb_reverse_remove(
        mobile_root=mobile_root,
        device_id=device_id,
        host_port=host_port,
        timeout_s=adb_timeout_s,
    )
    if not removed.get('removed'):
        raise RuntimeError(
            'adb reverse removal failed during background recovery smoke: '
            f'{removed!r}'
        )
    time.sleep(max(1, background_seconds))
    restored = emulator_smoke.adb_reverse(
        mobile_root=mobile_root,
        device_id=device_id,
        host_port=host_port,
        timeout_s=adb_timeout_s,
    )
    resume = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'shell',
            'am',
            'start',
            '-n',
            android_main_activity(android_package),
        ],
        cwd=mobile_root,
        timeout_s=30.0,
    )
    if resume.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('resuming app failed', resume))
    return (
        {
            'returncode': background.returncode,
            'stdout_tail': emulator_smoke.tail_lines(background.stdout, 20),
            'stderr_tail': emulator_smoke.tail_lines(background.stderr, 20),
        },
        removed,
        restored,
        {
            'returncode': resume.returncode,
            'stdout_tail': emulator_smoke.tail_lines(resume.stdout, 20),
            'stderr_tail': emulator_smoke.tail_lines(resume.stderr, 20),
            'component': android_main_activity(android_package),
        },
    )


def idle_request_totals(
    snapshot: dict[str, Any],
    *,
    idle_seconds: int,
) -> dict[str, Any]:
    counts_by_route = snapshot.get('counts_by_route')
    if not isinstance(counts_by_route, dict):
        counts_by_route = {}
    conversation_requests = sum(
        int(count)
        for route, count in counts_by_route.items()
        if '/conversation' in str(route)
    )
    terminal_history_requests = sum(
        int(count)
        for route, count in counts_by_route.items()
        if 'terminal-history' in str(route)
    )
    total_requests = int(snapshot.get('total_requests') or 0)
    minutes = max(idle_seconds / 60.0, 0.001)
    return {
        'total_requests': total_requests,
        'requests_per_minute': round(total_requests / minutes, 3),
        'conversation_requests': conversation_requests,
        'terminal_history_requests': terminal_history_requests,
        'conversation_terminal_requests': (
            conversation_requests + terminal_history_requests
        ),
        'conversation_terminal_requests_per_minute': round(
            (conversation_requests + terminal_history_requests) / minutes,
            3,
        ),
    }


class IdleDeviceMetricsCollector:
    def __init__(
        self,
        *,
        mobile_root: Path,
        device_id: str,
        android_package: str,
        sample_interval_s: int,
    ) -> None:
        self.mobile_root = mobile_root
        self.device_id = device_id
        self.android_package = android_package
        self.sample_interval_s = sample_interval_s
        self._samples: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._thread: threading.Thread | None = None
        self._summary: dict[str, Any] | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.monotonic()
        self._collect_sample(label='start')
        self._thread = threading.Thread(
            target=self._run,
            name='ccb-mobile-idle-device-metrics',
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        if self._summary is not None:
            return self._summary
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5, self.sample_interval_s + 5))
        self._collect_sample(label='end')
        power = self._adb(['shell', 'dumpsys', 'power'], timeout_s=20)
        batterystats = self._adb(
            ['shell', 'dumpsys', 'batterystats', '--charged', self.android_package],
            timeout_s=35,
        )
        gfxinfo = self._adb(
            ['shell', 'dumpsys', 'gfxinfo', self.android_package],
            timeout_s=25,
        )
        logcat = self._adb(['logcat', '-d', '-t', '900'], timeout_s=35)
        self._summary = summarize_idle_device_metrics(
            samples=self._samples,
            power_text=power.stdout + power.stderr,
            batterystats_text=batterystats.stdout + batterystats.stderr,
            gfxinfo_text=gfxinfo.stdout + gfxinfo.stderr,
            logcat_text=logcat.stdout + logcat.stderr,
            errors=self._errors
            + command_errors(
                {
                    'power': power,
                    'batterystats': batterystats,
                    'gfxinfo': gfxinfo,
                    'logcat': logcat,
                }
            ),
        )
        return self._summary

    def _run(self) -> None:
        while not self._stop_event.wait(self.sample_interval_s):
            self._collect_sample(label='interval')

    def _collect_sample(self, *, label: str) -> None:
        started_at = self._started_at or time.monotonic()
        elapsed_s = round(time.monotonic() - started_at, 3)
        top = self._adb(['shell', 'top', '-b', '-n', '1'], timeout_s=15)
        meminfo = self._adb(
            ['shell', 'dumpsys', 'meminfo', self.android_package],
            timeout_s=20,
        )
        sample: dict[str, Any] = {
            'label': label,
            'elapsed_s': elapsed_s,
            'top_returncode': top.returncode,
            'meminfo_returncode': meminfo.returncode,
            'top_line': compass.extract_app_top_line(top.stdout, self.android_package),
            **compass.parse_meminfo(meminfo.stdout + meminfo.stderr),
        }
        errors = command_errors({'top': top, 'meminfo': meminfo})
        with self._lock:
            self._samples.append(sample)
            self._errors.extend(f'{label}:{error}' for error in errors)

    def _adb(self, argv: list[str], *, timeout_s: float) -> subprocess.CompletedProcess[str]:
        return emulator_smoke.run_toolchain(
            mobile_root=self.mobile_root,
            argv=['adb', '-s', self.device_id, *argv],
            cwd=self.mobile_root,
            timeout_s=timeout_s,
        )


def command_errors(commands: dict[str, subprocess.CompletedProcess[str]]) -> list[str]:
    errors: list[str] = []
    for name, completed in commands.items():
        if completed.returncode != 0:
            text = (completed.stderr or completed.stdout or '').strip()
            errors.append(f'{name} exited {completed.returncode}: {text[-500:]}')
    return errors


def summarize_idle_device_metrics(
    *,
    samples: list[dict[str, Any]],
    power_text: str,
    batterystats_text: str,
    gfxinfo_text: str,
    logcat_text: str,
    errors: list[str],
) -> dict[str, Any]:
    interesting_logcat = compass.filter_interesting_logcat(logcat_text)
    power = compass.parse_power_summary(power_text)
    warnings = list(errors)
    wake_locks = str(power.get('wake_locks') or '')
    if wake_locks and 'size=0' not in wake_locks:
        warnings.append(
            f'device-global wake locks are nonzero; verify app-held wake locks in profile soak: {wake_locks}'
        )
    wake_lock_summary = str(power.get('wake_lock_summary') or '')
    if wake_lock_summary and '0x0' not in wake_lock_summary:
        warnings.append(
            'device-global wake lock summary is nonzero; '
            f'verify app-held wake locks in profile soak: {wake_lock_summary}'
        )
    return {
        'schema_version': 1,
        'sample_count': len(samples),
        'sample_labels': [sample.get('label') for sample in samples],
        'monitor_samples': samples,
        'memory': compass.summarize_memory(samples),
        'power': power,
        'batterystats_excerpt': compass.battery_excerpt(batterystats_text),
        'gfxinfo': compass.parse_gfxinfo(gfxinfo_text),
        'logcat': compass.summarize_logcat(interesting_logcat),
        'errors': errors,
        'warnings': warnings,
    }


def validate_idle_device_metrics(metrics: dict[str, Any]) -> None:
    if _dict(metrics.get('logcat')).get('fatal_anr_oom'):
        raise RuntimeError('idle device metrics detected FATAL/ANR/OOM in logcat')
    memory = _dict(metrics.get('memory'))
    if float(memory.get('pss_growth_ratio') or 0.0) > 0.3:
        raise RuntimeError(f'idle PSS growth exceeded debug budget: {memory!r}')


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def run_flutter_reverse_recovery_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    host_port: int,
    adb_timeout_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_reverse_recovery_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_RECOVERY_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_RECOVERY_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_RECOVERY_AGENT={agent}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    reverse_removed_events: list[dict[str, Any]] = []
    reverse_restored_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'reverse recovery Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_RECOVERY_READY_REMOVE_REVERSE' in line:
                    reverse_removed = emulator_smoke.adb_reverse_remove(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    if not reverse_removed.get('removed'):
                        raise RuntimeError(
                            'adb reverse removal failed during recovery smoke: '
                            f'{reverse_removed!r}'
                        )
                    reverse_removed['marker'] = line.rstrip()
                    reverse_removed_events.append(reverse_removed)
                if 'CCB_RECOVERY_READY_RESTORE_REVERSE' in line:
                    reverse_restored = emulator_smoke.adb_reverse(
                        mobile_root=mobile_root,
                        device_id=device_id,
                        host_port=host_port,
                        timeout_s=adb_timeout_s,
                    )
                    reverse_restored['marker'] = line.rstrip()
                    reverse_restored_events.append(reverse_restored)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not reverse_removed_events:
        raise RuntimeError(
            'reverse recovery smoke never reached remove marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not reverse_restored_events:
        raise RuntimeError(
            'reverse recovery smoke never reached restore marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'reverse recovery Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    stdout = '\n'.join(output_lines)
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'agent': agent,
        'host_port': host_port,
        'reverse_removed': reverse_removed_events[0],
        'reverse_restored': reverse_restored_events[-1],
        'reverse_removed_events': reverse_removed_events,
        'reverse_restored_events': reverse_restored_events,
        'timing': extract_recovery_timing(stdout),
        'stdout_tail': output_lines[-140:],
    }


def run_flutter_gateway_restart_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    agent: str,
    source_ccb: Path,
    state_home: Path,
    listen: str,
    gateway: dict[str, Any],
    gateway_timeout_s: float,
    timeout_s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_gateway_restart_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_GATEWAY_RESTART_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_GATEWAY_RESTART_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_GATEWAY_RESTART_AGENT={agent}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    gateway_stop_events: list[dict[str, Any]] = []
    gateway_start_events: list[dict[str, Any]] = []
    current_gateway = gateway
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'gateway restart Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_GATEWAY_RESTART_READY_STOP' in line:
                    stop_event = stop_server_mobile_gateway(current_gateway)
                    if not stop_event.get('stopped'):
                        raise RuntimeError(
                            'gateway stop failed during restart smoke: '
                            f'{stop_event!r}'
                        )
                    stop_event['marker'] = line.rstrip()
                    gateway_stop_events.append(stop_event)
                if 'CCB_GATEWAY_RESTART_READY_START' in line:
                    current_gateway = start_server_mobile_gateway(
                        source_ccb=source_ccb,
                        state_home=state_home,
                        listen=listen,
                        timeout_s=gateway_timeout_s,
                    )
                    gateway_start_events.append(
                        {
                            'marker': line.rstrip(),
                            'gateway': gateway_smoke.sanitize_gateway_summary(
                                current_gateway
                            ),
                        }
                    )
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not gateway_stop_events:
        raise RuntimeError(
            'gateway restart smoke never reached stop marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not gateway_start_events:
        raise RuntimeError(
            'gateway restart smoke never reached start marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'gateway restart Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return (
        {
            'returncode': process.returncode,
            'app_data_clear_returncode': clear_result.returncode,
            'project_id': project.get('id'),
            'project_name': project.get('display_name'),
            'agent': agent,
            'gateway_stop_events': gateway_stop_events,
            'gateway_start_events': gateway_start_events,
            'stdout_tail': output_lines[-140:],
        },
        current_gateway,
    )


def run_flutter_ccbd_restart_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    project: dict[str, Any],
    project_root: Path,
    agent: str,
    source_ccb: Path,
    state_home: Path,
    start_timeout_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    flutter_args = [
        'flutter',
        'test',
        'integration_test/server_wide_ccbd_restart_smoke_test.dart',
        '-d',
        device_id,
        '-D',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '-D',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        '-D',
        f'CCB_MOBILE_CCBD_RESTART_PROJECT_ID={project["id"]}',
        '-D',
        f'CCB_MOBILE_CCBD_RESTART_PROJECT_NAME={project["display_name"]}',
        '-D',
        f'CCB_MOBILE_CCBD_RESTART_AGENT={agent}',
    ]
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {quote_shell(str(toolchain))} && {gateway_smoke.shell_command(flutter_args)}'
    process = subprocess.Popen(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_lines: list[str] = []
    ccbd_stop_events: list[dict[str, Any]] = []
    ccbd_start_events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError(
                    'ccbd restart Flutter smoke timed out\n'
                    + '\n'.join(output_lines[-160:])
                )
            line = ''
            if process.stdout is not None:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if ready:
                    line = process.stdout.readline()
            if line:
                output_lines.append(line.rstrip())
                if 'CCB_CCBD_RESTART_READY_STOP' in line:
                    stop_event = stop_ccb_project(
                        source_ccb=source_ccb,
                        project_root=project_root,
                        state_home=state_home,
                        timeout_s=start_timeout_s,
                    )
                    stop_event['marker'] = line.rstrip()
                    ccbd_stop_events.append(stop_event)
                if 'CCB_CCBD_RESTART_READY_START' in line:
                    start_event = start_ccb_project(
                        source_ccb=source_ccb,
                        project_root=project_root,
                        state_home=state_home,
                        timeout_s=start_timeout_s,
                    )
                    start_event['marker'] = line.rstrip()
                    ccbd_start_events.append(start_event)
                continue
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    if not ccbd_stop_events:
        raise RuntimeError(
            'ccbd restart smoke never reached stop marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if not ccbd_start_events:
        raise RuntimeError(
            'ccbd restart smoke never reached start marker\n'
            + '\n'.join(output_lines[-160:])
        )
    if process.returncode != 0:
        raise RuntimeError(
            'ccbd restart Flutter smoke failed: '
            f'exit {process.returncode}\n'
            + '\n'.join(output_lines[-180:])
        )
    return {
        'returncode': process.returncode,
        'app_data_clear_returncode': clear_result.returncode,
        'project_id': project.get('id'),
        'project_name': project.get('display_name'),
        'project_root': str(project_root),
        'agent': agent,
        'ccbd_stop_events': ccbd_stop_events,
        'ccbd_start_events': ccbd_start_events,
        'stdout_tail': output_lines[-140:],
    }


def verify_native_pane_evidence(
    *,
    project_root: Path,
    agent: str,
    prompt: str,
    expected_reply: str,
) -> dict[str, Any]:
    jobs_evidence = find_job_matches(
        project_root=project_root,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
    )
    if jobs_evidence['matches']:
        raise RuntimeError(
            'native pane smoke prompt/reply was unexpectedly present in jobs history: '
            f'{jobs_evidence["matches"]!r}'
        )

    codex_events = find_codex_event_messages(project_root=project_root, agent=agent)
    user_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'user_message' and prompt in str(event.get('message') or '')
    ]
    reply_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'agent_message'
        and expected_reply in str(event.get('message') or '')
    ]
    if not user_matches:
        raise RuntimeError('native pane prompt was not found in Codex event transcript')
    if not reply_matches:
        raise RuntimeError('native pane expected reply was not found in Codex event transcript')
    bad_user_messages = [
        str(event.get('message') or '')
        for event in user_matches
        if 'CCB_REQ_ID' in str(event.get('message') or '')
        or 'mobile_gateway' in str(event.get('message') or '')
    ]
    if bad_user_messages:
        raise RuntimeError(f'native pane prompt was polluted: {bad_user_messages!r}')

    return {
        'project_root': str(project_root),
        'agent': agent,
        'jobs_matches': jobs_evidence['matches'],
        'codex_event_files': sorted({str(event['path']) for event in codex_events}),
        'user_match_count': len(user_matches),
        'reply_match_count': len(reply_matches),
        'prompt_contains_ccb_req_id': any(
            'CCB_REQ_ID' in str(event.get('message') or '') for event in user_matches
        ),
        'prompt_contains_mobile_gateway': any(
            'mobile_gateway' in str(event.get('message') or '') for event in user_matches
        ),
        'expected_reply': expected_reply,
    }


def verify_live_artifact_evidence(
    *,
    project_root: Path,
    state_home: Path,
    project_id: str,
    agent: str,
    prompt: str,
    artifact_file_name: str,
    artifact_content: str,
) -> dict[str, Any]:
    jobs_evidence = find_job_matches(
        project_root=project_root,
        agent=agent,
        prompt=prompt,
        expected_reply=artifact_file_name,
    )
    if jobs_evidence['matches']:
        raise RuntimeError(
            'live artifact prompt/reply was unexpectedly present in jobs history: '
            f'{jobs_evidence["matches"]!r}'
        )

    artifact_path = project_root / artifact_file_name
    if not artifact_path.is_file():
        raise RuntimeError(f'live artifact file was not created: {artifact_path}')
    content = artifact_path.read_text(encoding='utf-8')
    if content != artifact_content:
        raise RuntimeError(
            'live artifact file content mismatch: '
            f'expected {artifact_content!r}, got {content!r}'
        )
    artifact_sha256 = hashlib.sha256(content.encode('utf-8')).hexdigest()

    codex_events = find_codex_event_messages(project_root=project_root, agent=agent)
    user_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'user_message'
        and artifact_file_name in str(event.get('message') or '')
    ]
    reply_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'agent_message'
        and artifact_file_name in str(event.get('message') or '')
    ]
    if not user_matches:
        raise RuntimeError('live artifact prompt was not found in Codex event transcript')
    if not reply_matches:
        raise RuntimeError('live artifact reply was not found in Codex event transcript')
    bad_user_messages = [
        str(event.get('message') or '')
        for event in user_matches
        if 'CCB_REQ_ID' in str(event.get('message') or '')
        or 'mobile_gateway' in str(event.get('message') or '')
    ]
    if bad_user_messages:
        raise RuntimeError(f'live artifact prompt was polluted: {bad_user_messages!r}')

    metadata_matches: list[dict[str, Any]] = []
    metadata_root = state_home / 'files' / project_id / agent
    for metadata_path in sorted(metadata_root.glob('*/metadata.json')):
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if metadata.get('file_name') != artifact_file_name:
            continue
        metadata_matches.append(
            {
                'path': str(metadata_path),
                'file_id': metadata.get('file_id'),
                'file_name': metadata.get('file_name'),
                'size_bytes': metadata.get('size_bytes'),
                'sha256': metadata.get('sha256'),
            }
        )
    if not metadata_matches:
        raise RuntimeError(
            f'live artifact mobile metadata was not generated under {metadata_root}'
        )
    if not any(item.get('sha256') == artifact_sha256 for item in metadata_matches):
        raise RuntimeError(
            'live artifact mobile metadata did not include expected sha256: '
            f'{metadata_matches!r}'
        )

    return {
        'project_root': str(project_root),
        'agent': agent,
        'artifact_file_name': artifact_file_name,
        'artifact_path': str(artifact_path),
        'artifact_size_bytes': len(content.encode('utf-8')),
        'artifact_sha256': artifact_sha256,
        'jobs_matches': jobs_evidence['matches'],
        'codex_event_files': sorted({str(event['path']) for event in codex_events}),
        'user_match_count': len(user_matches),
        'reply_match_count': len(reply_matches),
        'prompt_contains_ccb_req_id': any(
            'CCB_REQ_ID' in str(event.get('message') or '') for event in user_matches
        ),
        'prompt_contains_mobile_gateway': any(
            'mobile_gateway' in str(event.get('message') or '')
            for event in user_matches
        ),
        'mobile_file_metadata': metadata_matches,
    }


def verify_native_pane_replay_guard_evidence(
    *,
    project_root: Path,
    agent: str,
    prompt: str,
    expected_reply: str,
) -> dict[str, Any]:
    jobs_evidence = find_job_matches(
        project_root=project_root,
        agent=agent,
        prompt=prompt,
        expected_reply=expected_reply,
    )
    if jobs_evidence['matches']:
        raise RuntimeError(
            'replay guard prompt/reply was unexpectedly present in jobs history: '
            f'{jobs_evidence["matches"]!r}'
        )

    codex_events = find_codex_event_messages(project_root=project_root, agent=agent)
    user_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'user_message' and prompt in str(event.get('message') or '')
    ]
    reply_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'agent_message'
        and expected_reply in str(event.get('message') or '')
    ]
    if len(user_matches) != 1:
        raise RuntimeError(
            'replay guard expected exactly one native pane prompt; '
            f'found {len(user_matches)}'
        )
    if not reply_matches:
        raise RuntimeError('replay guard expected reply was not found in Codex event transcript')
    bad_user_messages = [
        str(event.get('message') or '')
        for event in user_matches
        if 'CCB_REQ_ID' in str(event.get('message') or '')
        or 'mobile_gateway' in str(event.get('message') or '')
    ]
    if bad_user_messages:
        raise RuntimeError(f'replay guard prompt was polluted: {bad_user_messages!r}')

    return {
        'project_root': str(project_root),
        'agent': agent,
        'jobs_matches': jobs_evidence['matches'],
        'codex_event_files': sorted({str(event['path']) for event in codex_events}),
        'user_match_count': len(user_matches),
        'reply_match_count': len(reply_matches),
        'prompt_contains_ccb_req_id': any(
            'CCB_REQ_ID' in str(event.get('message') or '') for event in user_matches
        ),
        'prompt_contains_mobile_gateway': any(
            'mobile_gateway' in str(event.get('message') or '') for event in user_matches
        ),
        'expected_reply': expected_reply,
    }


def verify_desktop_origin_evidence(
    *,
    project_root: Path,
    agent: str,
    marker: str,
) -> dict[str, Any]:
    jobs_evidence = find_job_matches(
        project_root=project_root,
        agent=agent,
        prompt=marker,
        expected_reply=marker,
    )
    if jobs_evidence['matches']:
        raise RuntimeError(
            'desktop-origin marker was unexpectedly present in jobs history: '
            f'{jobs_evidence["matches"]!r}'
        )
    codex_events = find_codex_event_messages(project_root=project_root, agent=agent)
    user_matches = [
        event
        for event in codex_events
        if event.get('kind') == 'user_message' and marker in str(event.get('message') or '')
    ]
    if not user_matches:
        raise RuntimeError('desktop-origin marker was not found in Codex event transcript')
    bad_user_messages = [
        str(event.get('message') or '')
        for event in user_matches
        if 'CCB_REQ_ID' in str(event.get('message') or '')
        or 'mobile_gateway' in str(event.get('message') or '')
    ]
    if bad_user_messages:
        raise RuntimeError(f'desktop-origin marker was polluted: {bad_user_messages!r}')
    return {
        'project_root': str(project_root),
        'agent': agent,
        'marker': marker,
        'jobs_matches': jobs_evidence['matches'],
        'codex_event_files': sorted({str(event['path']) for event in codex_events}),
        'user_match_count': len(user_matches),
        'prompt_contains_ccb_req_id': any(
            'CCB_REQ_ID' in str(event.get('message') or '') for event in user_matches
        ),
        'prompt_contains_mobile_gateway': any(
            'mobile_gateway' in str(event.get('message') or '') for event in user_matches
        ),
    }


def resolve_agent_pane_target(
    *,
    view_payload: dict[str, Any],
    agent: str,
    fallback_socket_path: str = '',
) -> dict[str, str]:
    view = view_payload.get('view')
    if not isinstance(view, dict):
        raise RuntimeError(f'project view payload missing view: {view_payload!r}')
    namespace = view.get('namespace')
    if not isinstance(namespace, dict):
        raise RuntimeError(f'project view payload missing namespace: {view_payload!r}')
    socket_path = str(namespace.get('socket_path') or fallback_socket_path).strip()
    if not socket_path:
        raise RuntimeError(f'project view has no tmux socket path: {view_payload!r}')
    agents = view.get('agents')
    if not isinstance(agents, list):
        raise RuntimeError(f'project view has no agents list: {view_payload!r}')
    for item in agents:
        if not isinstance(item, dict) or str(item.get('name') or '') != agent:
            continue
        pane_id = str(item.get('pane_id') or '').strip()
        if not pane_id:
            raise RuntimeError(f'agent has no pane id: {item!r}')
        return {
            'socket_path': socket_path,
            'pane_id': pane_id,
        }
    raise RuntimeError(f'unknown agent in project view: {agent}')


def project_tmux_socket_path(project_root: Path) -> str:
    state_path = project_root / '.ccb' / 'ccbd' / 'state.json'
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except OSError as exc:
        raise RuntimeError(f'could not read project tmux state: {state_path}') from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'could not parse project tmux state: {state_path}') from exc
    socket_path = str(state.get('tmux_socket_path') or '').strip()
    if not socket_path:
        raise RuntimeError(f'project tmux state has no tmux_socket_path: {state_path}')
    return socket_path


def send_tmux_text(
    *,
    socket_path: str,
    pane_id: str,
    text: str,
    state_home: Path,
) -> None:
    env = os.environ.copy()
    env['CCB_SOURCE_RUNTIME_OK'] = '1'
    env['CCB_MOBILE_HOST_STATE_HOME'] = str(state_home)
    for argv in (
        ['tmux', '-S', socket_path, 'send-keys', '-t', pane_id, '-l', text],
        ['tmux', '-S', socket_path, 'send-keys', '-t', pane_id, 'Enter'],
    ):
        completed = subprocess.run(
            argv,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f'tmux pane send failed for {pane_id}\n'
                f'argv={argv!r}\n'
                f'stdout:\n{completed.stdout}\n'
                f'stderr:\n{completed.stderr}'
            )


def quote_shell(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def find_job_matches(
    *,
    project_root: Path,
    agent: str,
    prompt: str,
    expected_reply: str,
) -> dict[str, Any]:
    jobs_path = project_root / '.ccb' / 'agents' / agent / 'jobs.jsonl'
    matches: list[dict[str, Any]] = []
    if not jobs_path.exists():
        return {'path': str(jobs_path), 'matches': matches}
    for line_number, line in enumerate(jobs_path.read_text(encoding='utf-8').splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if prompt not in serialized and expected_reply not in serialized:
            continue
        request = record.get('request') if isinstance(record, dict) else None
        route_options = request.get('route_options') if isinstance(request, dict) else None
        matches.append(
            {
                'line': line_number,
                'job_id': record.get('job_id') if isinstance(record, dict) else None,
                'source': (
                    route_options.get('source')
                    if isinstance(route_options, dict)
                    else None
                ),
            }
        )
    return {'path': str(jobs_path), 'matches': matches}


def find_codex_event_messages(*, project_root: Path, agent: str) -> list[dict[str, Any]]:
    home = project_root / '.ccb' / 'agents' / agent / 'provider-state' / 'codex' / 'home'
    events: list[dict[str, Any]] = []
    if not home.exists():
        return events
    for path in sorted(home.rglob('*.jsonl')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get('type') != 'event_msg':
                continue
            payload = record.get('payload')
            if not isinstance(payload, dict):
                continue
            payload_type = str(payload.get('type') or '')
            if payload_type not in {'user_message', 'agent_message'}:
                continue
            message = payload.get('message')
            if not isinstance(message, str):
                continue
            events.append(
                {
                    'path': path,
                    'line': line_number,
                    'kind': payload_type,
                    'message': message,
                }
            )
    return events


def extract_backfill_metrics(stdout: str) -> dict[str, Any] | None:
    prefix = 'CCB_BACKFILL_METRICS '
    for line in stdout.splitlines():
        if prefix in line:
            payload = line.split(prefix, 1)[1].strip()
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                return {'parse_error': payload}
            return decoded if isinstance(decoded, dict) else {'value': decoded}
    return None


def extract_download_hashes(stdout: str) -> list[dict[str, Any]]:
    prefix = 'CCB_DOWNLOAD_SHA256 '
    hashes: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if prefix not in line:
            continue
        payload = line.split(prefix, 1)[1].strip()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            hashes.append({'parse_error': payload})
            continue
        if isinstance(decoded, dict):
            hashes.append(decoded)
        else:
            hashes.append({'value': decoded})
    return hashes


def extract_upload_stress_result(stdout: str) -> dict[str, Any] | None:
    prefix = 'CCB_UPLOAD_STRESS_RESULT '
    for line in stdout.splitlines():
        if prefix not in line:
            continue
        payload = line.split(prefix, 1)[1].strip()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {'parse_error': payload}
        return decoded if isinstance(decoded, dict) else {'value': decoded}
    return None


def extract_live_artifact_done(stdout: str) -> dict[str, Any] | None:
    prefix = 'CCB_LIVE_ARTIFACT_SMOKE_DONE '
    for line in stdout.splitlines():
        if prefix not in line:
            continue
        payload = line.split(prefix, 1)[1].strip()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {'parse_error': payload}
        return decoded if isinstance(decoded, dict) else {'value': decoded}
    return None


def install_debug_app(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    build = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'flutter',
            'build',
            'apk',
            '--debug',
            '--dart-define',
            f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
            '--dart-define',
            'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
        ],
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if build.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('debug APK build failed', build))
    apk_path = (
        mobile_root / 'app' / 'build' / 'app' / 'outputs' / 'flutter-apk' / 'app-debug.apk'
    )
    install = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'install', '-r', str(apk_path)],
        cwd=mobile_root,
        timeout_s=90.0,
    )
    if install.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('debug APK install failed', install))
    launch = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'shell',
            'am',
            'start',
            '-n',
            f'{android_package}/.MainActivity',
        ],
        cwd=mobile_root,
        timeout_s=30.0,
    )
    if launch.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('debug app launch failed', launch))
    return {
        'app_data_clear_returncode': clear_result.returncode,
        'build_stdout_tail': emulator_smoke.tail_lines(build.stdout, 40),
        'build_stderr_tail': emulator_smoke.tail_lines(build.stderr, 30),
        'install_stdout_tail': emulator_smoke.tail_lines(install.stdout, 20),
        'launch_stdout_tail': emulator_smoke.tail_lines(launch.stdout, 20),
    }


def seeded_apk_build_args(*, build_mode: str, debug_profile: str) -> list[str]:
    if build_mode not in {'debug', 'profile', 'release'}:
        raise ValueError(f'unsupported seeded APK build mode: {build_mode}')
    args = [
        'flutter',
        'build',
        'apk',
        f'--{build_mode}',
        '--dart-define',
        f'CCB_MOBILE_DEBUG_PAIRED_HOST_BASE64={debug_profile}',
        '--dart-define',
        'CCB_MOBILE_DEBUG_AUTO_ACTIVATE=true',
    ]
    if build_mode in {'profile', 'release'}:
        args.extend(['--dart-define', 'CCB_MOBILE_TEST_PROFILE_SEED=true'])
    return args


def seeded_apk_path(mobile_root: Path, *, build_mode: str) -> Path:
    if build_mode not in {'debug', 'profile', 'release'}:
        raise ValueError(f'unsupported seeded APK build mode: {build_mode}')
    return (
        mobile_root
        / 'app'
        / 'build'
        / 'app'
        / 'outputs'
        / 'flutter-apk'
        / f'app-{build_mode}.apk'
    )


def install_seeded_apk(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    build_mode: str,
    timeout_s: float,
) -> dict[str, Any]:
    clear_result = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'shell', 'pm', 'clear', android_package],
        cwd=mobile_root,
        timeout_s=15.0,
    )
    build = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=seeded_apk_build_args(build_mode=build_mode, debug_profile=debug_profile),
        cwd=mobile_root / 'app',
        timeout_s=timeout_s,
    )
    if build.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure(f'{build_mode} APK build failed', build)
        )
    apk_path = seeded_apk_path(mobile_root, build_mode=build_mode)
    install = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, 'install', '-r', str(apk_path)],
        cwd=mobile_root,
        timeout_s=120.0,
    )
    if install.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure(f'{build_mode} APK install failed', install)
        )
    launch = emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=[
            'adb',
            '-s',
            device_id,
            'shell',
            'am',
            'start',
            '-n',
            android_main_activity(android_package),
        ],
        cwd=mobile_root,
        timeout_s=30.0,
    )
    if launch.returncode != 0:
        raise RuntimeError(
            emulator_smoke.command_failure(f'{build_mode} app launch failed', launch)
        )
    return {
        'build_mode': build_mode,
        'apk_path': str(apk_path),
        'app_data_clear_returncode': clear_result.returncode,
        'build_stdout_tail': emulator_smoke.tail_lines(build.stdout, 50),
        'build_stderr_tail': emulator_smoke.tail_lines(build.stderr, 40),
        'install_stdout_tail': emulator_smoke.tail_lines(install.stdout, 30),
        'launch_stdout_tail': emulator_smoke.tail_lines(launch.stdout, 20),
    }


def adb_command(
    *,
    mobile_root: Path,
    device_id: str,
    argv: list[str],
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    return emulator_smoke.run_toolchain(
        mobile_root=mobile_root,
        argv=['adb', '-s', device_id, *argv],
        cwd=mobile_root,
        timeout_s=timeout_s,
    )


def dump_android_ui(
    *,
    mobile_root: Path,
    device_id: str,
    timeout_s: float,
) -> str:
    dump = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['shell', 'uiautomator', 'dump', '/sdcard/ccb-mobile-window.xml'],
        timeout_s=timeout_s,
    )
    if dump.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('uiautomator dump failed', dump))
    cat = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['exec-out', 'cat', '/sdcard/ccb-mobile-window.xml'],
        timeout_s=timeout_s,
    )
    if cat.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('uiautomator dump cat failed', cat))
    return cat.stdout


def ui_texts(ui_xml: str) -> list[str]:
    root = ET.fromstring(ui_xml)
    texts: list[str] = []
    for node in root.iter('node'):
        for text in ui_node_labels(node):
            if text:
                texts.append(text)
    return texts


def ui_node_bounds_for_text(ui_xml: str, expected_text: str) -> tuple[int, int, int, int] | None:
    root = ET.fromstring(ui_xml)
    for node in root.iter('node'):
        if expected_text not in ui_node_labels(node):
            continue
        bounds = parse_android_bounds(str(node.attrib.get('bounds') or ''))
        if bounds is not None:
            return bounds
    return None


def ui_node_bounds_containing_text(
    ui_xml: str,
    expected_text: str,
) -> tuple[int, int, int, int] | None:
    root = ET.fromstring(ui_xml)
    for node in root.iter('node'):
        if not any(expected_text in label for label in ui_node_labels(node)):
            continue
        bounds = parse_android_bounds(str(node.attrib.get('bounds') or ''))
        if bounds is not None:
            return bounds
    return None


def ui_texts_contain(texts: list[str], expected_text: str) -> bool:
    return any(expected_text in text for text in texts)


def ui_node_labels(node: ET.Element) -> list[str]:
    labels: list[str] = []
    for attr in ('text', 'content-desc'):
        value = str(node.attrib.get(attr) or '').strip()
        if not value:
            continue
        for line in value.splitlines():
            label = line.strip()
            if label:
                labels.append(label)
    return labels


def parse_android_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    # Android UIAutomator emits bounds in the form "[left,top][right,bottom]".
    parts = bounds.replace('][', ',').replace('[', '').replace(']', '').split(',')
    if len(parts) != 4:
        return None
    try:
        left, top, right, bottom = (int(part) for part in parts)
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def tap_android_bounds(
    *,
    mobile_root: Path,
    device_id: str,
    bounds: tuple[int, int, int, int],
    timeout_s: float,
) -> dict[str, Any]:
    left, top, right, bottom = bounds
    x = (left + right) // 2
    y = (top + bottom) // 2
    tap = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['shell', 'input', 'tap', str(x), str(y)],
        timeout_s=timeout_s,
    )
    if tap.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('adb tap failed', tap))
    return {'x': x, 'y': y, 'bounds': list(bounds)}


def tap_android_ui_text(
    *,
    mobile_root: Path,
    device_id: str,
    text: str,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    ui = wait_for_ui_texts(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_texts=[text],
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    bounds = ui_node_bounds_for_text(ui['xml'], text)
    if bounds is None:
        raise RuntimeError(f'could not locate UI bounds for {text!r}')
    tap = tap_android_bounds(
        mobile_root=mobile_root,
        device_id=device_id,
        bounds=bounds,
        timeout_s=adb_timeout_s,
    )
    return {'text': text, 'tap': tap}


def tap_android_ui_text_containing(
    *,
    mobile_root: Path,
    device_id: str,
    text: str,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    ui = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=text,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    bounds = ui_node_bounds_containing_text(ui['xml'], text)
    if bounds is None:
        raise RuntimeError(f'could not locate UI bounds containing {text!r}')
    tap = tap_android_bounds(
        mobile_root=mobile_root,
        device_id=device_id,
        bounds=bounds,
        timeout_s=adb_timeout_s,
    )
    return {'text': text, 'tap': tap}


def android_window_size(
    *,
    mobile_root: Path,
    device_id: str,
    timeout_s: float,
) -> tuple[int, int]:
    size = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['shell', 'wm', 'size'],
        timeout_s=timeout_s,
    )
    if size.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('wm size failed', size))
    for line in size.stdout.splitlines():
        if 'Physical size:' not in line:
            continue
        value = line.split('Physical size:', 1)[1].strip()
        if 'x' not in value:
            continue
        width_text, height_text = value.split('x', 1)
        try:
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            continue
        if width > 0 and height > 0:
            return (width, height)
    raise RuntimeError(f'could not parse Android window size: {size.stdout!r}')


def swipe_android(
    *,
    mobile_root: Path,
    device_id: str,
    start: tuple[int, int],
    end: tuple[int, int],
    duration_ms: int,
    timeout_s: float,
) -> dict[str, Any]:
    swipe = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=[
            'shell',
            'input',
            'swipe',
            str(start[0]),
            str(start[1]),
            str(end[0]),
            str(end[1]),
            str(duration_ms),
        ],
        timeout_s=timeout_s,
    )
    if swipe.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('adb swipe failed', swipe))
    return {
        'start': list(start),
        'end': list(end),
        'duration_ms': duration_ms,
    }


def wait_for_ui_texts(
    *,
    mobile_root: Path,
    device_id: str,
    expected_texts: list[str],
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_texts: list[str] = []
    last_xml = ''
    while time.monotonic() < deadline:
        last_xml = dump_android_ui(
            mobile_root=mobile_root,
            device_id=device_id,
            timeout_s=adb_timeout_s,
        )
        last_texts = ui_texts(last_xml)
        if all(expected in last_texts for expected in expected_texts):
            return {'texts': last_texts, 'xml': last_xml}
        time.sleep(1.0)
    raise RuntimeError(
        'timed out waiting for Android UI text '
        f'{expected_texts!r}; last visible texts: {last_texts!r}'
    )


def wait_for_ui_text_containing(
    *,
    mobile_root: Path,
    device_id: str,
    expected_text: str,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_texts: list[str] = []
    last_xml = ''
    while time.monotonic() < deadline:
        last_xml = dump_android_ui(
            mobile_root=mobile_root,
            device_id=device_id,
            timeout_s=adb_timeout_s,
        )
        last_texts = ui_texts(last_xml)
        if ui_texts_contain(last_texts, expected_text):
            return {'texts': last_texts, 'xml': last_xml}
        time.sleep(1.0)
    raise RuntimeError(
        'timed out waiting for Android UI text containing '
        f'{expected_text!r}; last visible texts: {last_texts!r}'
    )


def capture_android_screenshot(
    *,
    mobile_root: Path,
    device_id: str,
    path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    device_path = '/sdcard/ccb-mobile-release-smoke.png'
    screenshot = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['shell', 'screencap', '-p', device_path],
        timeout_s=timeout_s,
    )
    if screenshot.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('screencap failed', screenshot))
    pull = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['pull', device_path, str(path)],
        timeout_s=timeout_s,
    )
    if pull.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('screenshot pull failed', pull))
    return {'path': str(path), 'bytes': path.stat().st_size}


def run_release_project_list_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    install = install_seeded_apk(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        build_mode='release',
        timeout_s=timeout_s,
    )
    alpha_name = str(alpha_project['display_name'])
    beta_name = str(beta_project['display_name'])
    list_ui = wait_for_ui_texts(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_texts=[alpha_name, beta_name],
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
    )
    bounds = ui_node_bounds_for_text(list_ui['xml'], alpha_name)
    if bounds is None:
        raise RuntimeError(f'could not locate project tile bounds for {alpha_name!r}')
    tap = tap_android_bounds(
        mobile_root=mobile_root,
        device_id=device_id,
        bounds=bounds,
        timeout_s=adb_timeout_s,
    )
    opened_ui = wait_for_ui_texts(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_texts=[alpha_name, agent],
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
    )
    agent_bounds = ui_node_bounds_for_text(opened_ui['xml'], agent)
    if agent_bounds is None:
        raise RuntimeError(f'could not locate agent chip bounds for {agent!r}')
    agent_tap = tap_android_bounds(
        mobile_root=mobile_root,
        device_id=device_id,
        bounds=agent_bounds,
        timeout_s=adb_timeout_s,
    )
    time.sleep(1.0)
    selected_ui = wait_for_ui_texts(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_texts=[alpha_name, agent, 'Refresh conversation'],
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-project-list-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    return {
        'returncode': 0,
        'mode': 'release_project_list_smoke',
        'install': install,
        'project_list_texts': list_ui['texts'],
        'opened_project_texts': selected_ui['texts'],
        'opened_project_text_found': alpha_name in selected_ui['texts'],
        'tap': tap,
        'agent_tap': agent_tap,
        'screenshot_path': screenshot['path'],
        'screenshot_bytes': screenshot['bytes'],
    }


def run_release_idle_request_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    idle_seconds: int,
    metrics_sample_interval_s: int,
    request_proxy: CountingHttpProxy,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    opened = run_release_project_list_smoke(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        alpha_project=alpha_project,
        beta_project=beta_project,
        agent=agent,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    request_proxy.reset()
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    metrics_collector.start()
    time.sleep(max(1, idle_seconds))
    idle_counts = request_proxy.snapshot()
    idle_device_metrics = metrics_collector.stop()
    totals = idle_request_totals(idle_counts, idle_seconds=idle_seconds)
    if float(totals['conversation_terminal_requests_per_minute']) > 2.0:
        raise RuntimeError(
            'release idle conversation/terminal request budget exceeded: '
            f'{json.dumps(totals, sort_keys=True)}; '
            f'counts={json.dumps(idle_counts.get("counts_by_route", {}), sort_keys=True)}'
        )
    validate_idle_device_metrics(idle_device_metrics)
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-idle-request-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    return {
        'returncode': 0,
        'mode': 'release_idle_request_smoke',
        'project_id': alpha_project.get('id'),
        'project_name': alpha_project.get('display_name'),
        'agent': agent,
        'build_mode': 'release',
        'idle_seconds': idle_seconds,
        'opened': opened,
        'idle_request_counts': idle_counts,
        'idle_request_totals': totals,
        'idle_device_metrics': idle_device_metrics,
        'idle_screenshot_path': screenshot['path'],
        'idle_screenshot_bytes': screenshot['bytes'],
    }


def drag_release_timeline_until_text(
    *,
    mobile_root: Path,
    device_id: str,
    expected_text: str,
    direction: str,
    timeout_s: float,
    adb_timeout_s: float,
    max_drags: int = 120,
) -> dict[str, Any]:
    if direction not in {'older', 'newer'}:
        raise ValueError(f'unsupported release timeline drag direction: {direction}')
    width, height = android_window_size(
        mobile_root=mobile_root,
        device_id=device_id,
        timeout_s=adb_timeout_s,
    )
    x = width // 2
    top_y = max(220, int(height * 0.36))
    bottom_y = min(height - 120, int(height * 0.82))
    if bottom_y <= top_y:
        bottom_y = top_y + 200
    if direction == 'older':
        start_y = top_y
        end_y = bottom_y
    else:
        start_y = bottom_y
        end_y = top_y
    deadline = time.monotonic() + timeout_s
    drags: list[dict[str, Any]] = []
    last_texts: list[str] = []
    last_xml = ''
    while time.monotonic() < deadline and len(drags) < max_drags:
        last_xml = dump_android_ui(
            mobile_root=mobile_root,
            device_id=device_id,
            timeout_s=adb_timeout_s,
        )
        last_texts = ui_texts(last_xml)
        if ui_texts_contain(last_texts, expected_text):
            return {
                'found': True,
                'drag_count': len(drags),
                'last_texts': last_texts,
                'last_xml': last_xml,
                'window_size': [width, height],
                'direction': direction,
                'swipe': {
                    'start': [x, start_y],
                    'end': [x, end_y],
                    'duration_ms': 260,
                },
            }
        drags.append(
            swipe_android(
                mobile_root=mobile_root,
                device_id=device_id,
                start=(x, start_y),
                end=(x, end_y),
                duration_ms=260,
                timeout_s=adb_timeout_s,
            )
        )
        time.sleep(0.35)
    raise RuntimeError(
        'timed out waiting for release long-history text containing '
        f'{expected_text!r}; drags={len(drags)}; last visible texts={last_texts!r}'
    )


def run_release_long_history_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    backfill: dict[str, Any],
    request_proxy: CountingHttpProxy,
    metrics_sample_interval_s: int,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    opened = run_release_project_list_smoke(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        alpha_project=alpha_project,
        beta_project=beta_project,
        agent=agent,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    latest_text = str(backfill.get('latest_text') or '')
    oldest_text = str(backfill.get('oldest_text') or '')
    if not latest_text or not oldest_text:
        raise RuntimeError(f'release long-history smoke missing markers: {backfill!r}')
    refresh_tap = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Refresh conversation',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    time.sleep(1.0)
    latest_started = time.monotonic()
    latest = drag_release_timeline_until_text(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=latest_text,
        direction='newer',
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
        max_drags=80,
    )
    latest_visible_ms = round((time.monotonic() - latest_started) * 1000.0, 3)

    request_proxy.reset()
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    metrics_collector.start()
    older_started = time.monotonic()
    older = drag_release_timeline_until_text(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=oldest_text,
        direction='older',
        timeout_s=360.0,
        adb_timeout_s=adb_timeout_s,
        max_drags=180,
    )
    older_visible_ms = round((time.monotonic() - older_started) * 1000.0, 3)
    long_history_counts = request_proxy.snapshot()
    device_metrics = metrics_collector.stop()
    validate_idle_device_metrics(device_metrics)
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-long-history-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    elapsed_seconds = max(1, int(round(older_visible_ms / 1000.0)))
    return {
        'returncode': 0,
        'mode': 'release_long_history_smoke',
        'project_id': alpha_project.get('id'),
        'project_name': alpha_project.get('display_name'),
        'agent': agent,
        'build_mode': 'release',
        'opened': opened,
        'refresh_tap': refresh_tap,
        'backfill': {
            'turns': backfill.get('turns'),
            'namespace_epoch': backfill.get('namespace_epoch'),
            'latest_text': latest_text,
            'oldest_text': oldest_text,
            'older_pages': backfill.get('older_pages'),
            'dataset_features': backfill.get('dataset_features'),
            'artifact_files': backfill.get('artifact_files'),
            'seed_ms': backfill.get('seed_ms'),
            'latest_page_ms': backfill.get('latest_page_ms'),
            'older_page_ms': backfill.get('older_page_ms'),
        },
        'long_history_metrics': {
            'latest_visible_ms': latest_visible_ms,
            'older_visible_ms': older_visible_ms,
            'latest_drag_count': latest.get('drag_count'),
            'drag_count': older.get('drag_count'),
            'elapsed_seconds_for_request_rate': elapsed_seconds,
        },
        'latest_visible_texts': latest.get('last_texts'),
        'oldest_visible_texts': older.get('last_texts'),
        'long_history_request_counts': long_history_counts,
        'long_history_request_totals': idle_request_totals(
            long_history_counts,
            idle_seconds=elapsed_seconds,
        ),
        'long_history_device_metrics': device_metrics,
        'long_history_screenshot_path': screenshot['path'],
        'long_history_screenshot_bytes': screenshot['bytes'],
    }


def gateway_file_download_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records = snapshot.get('records')
    if not isinstance(records, list):
        return []
    result: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        route = str(record.get('route') or '')
        if '/files/{id}' in route or '/artifacts/{id}' in route:
            result.append(record)
    return result


def require_gateway_file_download_record(
    snapshot: dict[str, Any],
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> dict[str, Any]:
    records = gateway_file_download_records(snapshot)
    for record in reversed(records):
        if int(record.get('response_bytes') or -1) != expected_size_bytes:
            continue
        if str(record.get('response_sha256') or '') != expected_sha256:
            continue
        if int(record.get('status') or 0) != 200:
            continue
        return record
    raise RuntimeError(
        'release file download did not return expected bytes/hash: '
        f'expected_size={expected_size_bytes}; expected_sha256={expected_sha256}; '
        f'records={records!r}'
    )


def flutter_attachment_size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    if size_bytes >= 1024:
        return f'{size_bytes / 1024:.1f} KB'
    return f'{size_bytes} B'


def write_deterministic_upload_file(
    *,
    path: Path,
    size_bytes: int,
) -> dict[str, Any]:
    if size_bytes <= 0:
        raise RuntimeError(f'upload stress size must be positive, got {size_bytes}')
    pattern = (
        f'CCB Mobile release upload stress fixture {path.name}\n'
    ).encode('utf-8')
    chunk = bytes(pattern[index % len(pattern)] for index in range(64 * 1024))
    digest = hashlib.sha256()
    remaining = size_bytes
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as handle:
        while remaining > 0:
            write_length = min(remaining, len(chunk))
            data = chunk if write_length == len(chunk) else chunk[:write_length]
            handle.write(data)
            digest.update(data)
            remaining -= write_length
    return {
        'host_path': str(path),
        'file_name': path.name,
        'size_bytes': size_bytes,
        'sha256': digest.hexdigest(),
    }


def push_upload_file_to_downloads(
    *,
    mobile_root: Path,
    device_id: str,
    file_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    device_path = f'/sdcard/Download/{file_path.name}'
    mkdir = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['shell', 'mkdir', '-p', '/sdcard/Download'],
        timeout_s=timeout_s,
    )
    if mkdir.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('create Downloads failed', mkdir))
    push = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=['push', str(file_path), device_path],
        timeout_s=max(timeout_s, 120.0),
    )
    if push.returncode != 0:
        raise RuntimeError(emulator_smoke.command_failure('adb push upload file failed', push))
    scan = adb_command(
        mobile_root=mobile_root,
        device_id=device_id,
        argv=[
            'shell',
            'am',
            'broadcast',
            '-a',
            'android.intent.action.MEDIA_SCANNER_SCAN_FILE',
            '-d',
            f'file://{device_path}',
        ],
        timeout_s=timeout_s,
    )
    return {
        'device_path': device_path,
        'push_stdout': push.stdout.strip(),
        'scan_returncode': scan.returncode,
    }


def tap_release_attachment_file_picker(
    *,
    mobile_root: Path,
    device_id: str,
    file_name: str,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    attach = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Attach file',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    pick = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='File',
        timeout_s=15.0,
        adb_timeout_s=adb_timeout_s,
    )
    try:
        file_ui = wait_for_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            expected_text=file_name,
            timeout_s=timeout_s,
            adb_timeout_s=adb_timeout_s,
        )
    except RuntimeError:
        # DocumentsUI often opens Recents; on some emulator images the pushed
        # file only appears after explicitly switching to Downloads.
        downloads_tap: dict[str, Any] | None = None
        try:
            downloads_tap = tap_android_ui_text_containing(
                mobile_root=mobile_root,
                device_id=device_id,
                text='Downloads',
                timeout_s=10.0,
                adb_timeout_s=adb_timeout_s,
            )
        except RuntimeError:
            downloads_tap = None
        file_ui = wait_for_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            expected_text=file_name,
            timeout_s=timeout_s,
            adb_timeout_s=adb_timeout_s,
        )
        selected = tap_android_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            text=file_name,
            timeout_s=10.0,
            adb_timeout_s=adb_timeout_s,
        )
        return {
            'attach_tap': attach,
            'pick_tap': pick,
            'downloads_tap': downloads_tap,
            'file_texts': file_ui.get('texts'),
            'file_tap': selected,
        }
    selected = tap_android_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        text=file_name,
        timeout_s=10.0,
        adb_timeout_s=adb_timeout_s,
    )
    return {
        'attach_tap': attach,
        'pick_tap': pick,
        'downloads_tap': None,
        'file_texts': file_ui.get('texts'),
        'file_tap': selected,
    }


def run_release_upload_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    upload_size_bytes: int,
    request_proxy: CountingHttpProxy,
    metrics_sample_interval_s: int,
    timeout_s: float,
    adb_timeout_s: float,
    run_id: str,
) -> dict[str, Any]:
    if upload_size_bytes <= 0:
        upload_size_bytes = 8 * 1024 * 1024
    file_path = Path('/tmp') / f'ccb-mobile-release-upload-{run_id}.txt'
    upload_file = write_deterministic_upload_file(
        path=file_path,
        size_bytes=upload_size_bytes,
    )
    pushed = push_upload_file_to_downloads(
        mobile_root=mobile_root,
        device_id=device_id,
        file_path=file_path,
        timeout_s=adb_timeout_s,
    )
    opened = run_release_project_list_smoke(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        alpha_project=alpha_project,
        beta_project=beta_project,
        agent=agent,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    file_name = str(upload_file['file_name'])
    picker = tap_release_attachment_file_picker(
        mobile_root=mobile_root,
        device_id=device_id,
        file_name=file_name,
        timeout_s=45.0,
        adb_timeout_s=adb_timeout_s,
    )
    draft_ui = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=file_name,
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
    )
    request_proxy.reset()
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    metrics_collector.start()
    send_started = time.monotonic()
    send_tap = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Send message',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    sent_ui = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=file_name,
        timeout_s=180.0,
        adb_timeout_s=adb_timeout_s,
    )
    chip_label = f'{file_name} ({flutter_attachment_size_label(upload_size_bytes)})'
    try:
        chip_ui = wait_for_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            expected_text=chip_label,
            timeout_s=30.0,
            adb_timeout_s=adb_timeout_s,
        )
        chip_text = chip_label
    except RuntimeError:
        chip_ui = sent_ui
        chip_text = file_name
    download_started = time.monotonic()
    download_tap = tap_android_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        text=chip_text,
        timeout_s=20.0,
        adb_timeout_s=adb_timeout_s,
    )
    saved = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=f'Saved {file_name}',
        timeout_s=180.0,
        adb_timeout_s=adb_timeout_s,
    )
    counts = request_proxy.snapshot()
    download_record = require_gateway_file_download_record(
        counts,
        expected_size_bytes=upload_size_bytes,
        expected_sha256=str(upload_file['sha256']),
    )
    post_save_settle_seconds = max(5, metrics_sample_interval_s)
    time.sleep(post_save_settle_seconds)
    device_metrics = metrics_collector.stop()
    validate_idle_device_metrics(device_metrics)
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-upload-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    try:
        file_path.unlink()
    except OSError:
        pass
    return {
        'returncode': 0,
        'mode': 'release_upload_smoke',
        'project_id': alpha_project.get('id'),
        'project_name': alpha_project.get('display_name'),
        'agent': agent,
        'build_mode': 'release',
        'opened': opened,
        'pushed': pushed,
        'picker': picker,
        'draft_visible_texts': draft_ui.get('texts'),
        'send_tap': send_tap,
        'sent_visible_texts': sent_ui.get('texts'),
        'chip_visible_texts': chip_ui.get('texts'),
        'download_tap': download_tap,
        'saved_visible_texts': saved.get('texts'),
        'upload_file': upload_file,
        'upload_metrics': {
            'send_to_save_ms': round((time.monotonic() - send_started) * 1000.0, 3),
            'download_saved_visible_ms': round(
                (time.monotonic() - download_started) * 1000.0,
                3,
            ),
            'post_save_settle_seconds': post_save_settle_seconds,
            'download_route_elapsed_ms': download_record.get('elapsed_ms'),
            'response_bytes': download_record.get('response_bytes'),
            'response_sha256': download_record.get('response_sha256'),
        },
        'download_record': download_record,
        'upload_request_counts': counts,
        'upload_device_metrics': device_metrics,
        'upload_screenshot_path': screenshot['path'],
        'upload_screenshot_bytes': screenshot['bytes'],
    }


def run_release_file_download_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    native_artifact: dict[str, Any],
    request_proxy: CountingHttpProxy,
    metrics_sample_interval_s: int,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    opened = run_release_project_list_smoke(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        alpha_project=alpha_project,
        beta_project=beta_project,
        agent=agent,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    marker = str(native_artifact.get('marker') or '')
    file_name = str(native_artifact.get('text_file_name') or '')
    expected_sha256 = str(native_artifact.get('text_sha256') or '')
    expected_size = int(native_artifact.get('text_size_bytes') or 0)
    if not marker or not file_name or not expected_sha256 or expected_size <= 0:
        raise RuntimeError(f'release file smoke missing artifact metadata: {native_artifact!r}')
    download_chip_label = f'{file_name} ({flutter_attachment_size_label(expected_size)})'

    refresh_tap = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Refresh conversation',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=marker,
        timeout_s=60.0,
        adb_timeout_s=adb_timeout_s,
    )
    try:
        file_ui = wait_for_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            expected_text=download_chip_label,
            timeout_s=20.0,
            adb_timeout_s=adb_timeout_s,
        )
    except RuntimeError:
        tap_android_ui_text(
            mobile_root=mobile_root,
            device_id=device_id,
            text='Expand message',
            timeout_s=10.0,
            adb_timeout_s=adb_timeout_s,
        )
        file_ui = wait_for_ui_text_containing(
            mobile_root=mobile_root,
            device_id=device_id,
            expected_text=download_chip_label,
            timeout_s=30.0,
            adb_timeout_s=adb_timeout_s,
        )

    request_proxy.reset()
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    metrics_collector.start()
    started = time.monotonic()
    tap = tap_android_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        text=download_chip_label,
        timeout_s=10.0,
        adb_timeout_s=adb_timeout_s,
    )
    saved = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=f'Saved {file_name}',
        timeout_s=180.0,
        adb_timeout_s=adb_timeout_s,
    )
    download_visible_ms = round((time.monotonic() - started) * 1000.0, 3)
    counts = request_proxy.snapshot()
    download_record = require_gateway_file_download_record(
        counts,
        expected_size_bytes=expected_size,
        expected_sha256=expected_sha256,
    )
    post_save_settle_seconds = max(5, metrics_sample_interval_s)
    time.sleep(post_save_settle_seconds)
    device_metrics = metrics_collector.stop()
    validate_idle_device_metrics(device_metrics)
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-file-download-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    return {
        'returncode': 0,
        'mode': 'release_file_download_smoke',
        'project_id': alpha_project.get('id'),
        'project_name': alpha_project.get('display_name'),
        'agent': agent,
        'build_mode': 'release',
        'opened': opened,
        'refresh_tap': refresh_tap,
        'artifact_visible_texts': file_ui.get('texts'),
        'download_tap': tap,
        'saved_visible_texts': saved.get('texts'),
        'native_artifact': {
            'marker': marker,
            'file_name': file_name,
            'download_chip_label': download_chip_label,
            'file_id': native_artifact.get('text_file_id'),
            'size_bytes': expected_size,
            'sha256': expected_sha256,
        },
        'download_metrics': {
            'saved_visible_ms': download_visible_ms,
            'post_save_settle_seconds': post_save_settle_seconds,
            'download_route_elapsed_ms': download_record.get('elapsed_ms'),
            'response_bytes': download_record.get('response_bytes'),
            'response_sha256': download_record.get('response_sha256'),
        },
        'download_record': download_record,
        'download_request_counts': counts,
        'download_device_metrics': device_metrics,
        'download_screenshot_path': screenshot['path'],
        'download_screenshot_bytes': screenshot['bytes'],
    }


def run_release_reverse_recovery_smoke(
    *,
    mobile_root: Path,
    device_id: str,
    android_package: str,
    debug_profile: str,
    alpha_project: dict[str, Any],
    beta_project: dict[str, Any],
    agent: str,
    native_artifact: dict[str, Any],
    reverse_host_port: int,
    metrics_sample_interval_s: int,
    timeout_s: float,
    adb_timeout_s: float,
) -> dict[str, Any]:
    opened = run_release_project_list_smoke(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        debug_profile=debug_profile,
        alpha_project=alpha_project,
        beta_project=beta_project,
        agent=agent,
        timeout_s=timeout_s,
        adb_timeout_s=adb_timeout_s,
    )
    marker = str(native_artifact.get('marker') or '')
    if not marker:
        raise RuntimeError(f'release recovery smoke missing artifact marker: {native_artifact!r}')
    wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=marker,
        timeout_s=60.0,
        adb_timeout_s=adb_timeout_s,
    )
    metrics_collector = IdleDeviceMetricsCollector(
        mobile_root=mobile_root,
        device_id=device_id,
        android_package=android_package,
        sample_interval_s=max(1, metrics_sample_interval_s),
    )
    metrics_collector.start()
    started = time.monotonic()
    removed = emulator_smoke.adb_reverse_remove(
        mobile_root=mobile_root,
        device_id=device_id,
        host_port=reverse_host_port,
        timeout_s=adb_timeout_s,
    )
    if removed.get('returncode') != 0:
        raise RuntimeError(
            'adb reverse removal failed during release recovery smoke: '
            f"{removed.get('stderr') or removed.get('stdout') or removed!r}"
        )
    failure_tap = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Refresh conversation',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    failure = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text='Connection refused',
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
    )
    project_root_value = str(alpha_project.get('root') or '')
    if not project_root_value:
        raise RuntimeError(f'release recovery smoke missing project root: {alpha_project!r}')
    recovery_marker = f'Native reverse recovery restored {int(time.time())}'
    recovery_seed = seed_native_agent_reply(
        project_root=Path(project_root_value),
        agent=agent,
        run_id=f'reverse-recovery-{int(time.time())}',
        marker=recovery_marker,
        source='ccb-mobile-avd-reverse-recovery-fixture',
    )
    restored = emulator_smoke.adb_reverse(
        mobile_root=mobile_root,
        device_id=device_id,
        host_port=reverse_host_port,
        timeout_s=adb_timeout_s,
    )
    if not restored.get('mapping'):
        raise RuntimeError(f'adb reverse restore failed during release recovery smoke: {restored!r}')
    recovery_tap = tap_android_ui_text(
        mobile_root=mobile_root,
        device_id=device_id,
        text='Refresh conversation',
        timeout_s=30.0,
        adb_timeout_s=adb_timeout_s,
    )
    recovered = wait_for_ui_text_containing(
        mobile_root=mobile_root,
        device_id=device_id,
        expected_text=recovery_marker,
        timeout_s=90.0,
        adb_timeout_s=adb_timeout_s,
    )
    post_recovery_settle_seconds = max(5, metrics_sample_interval_s)
    time.sleep(post_recovery_settle_seconds)
    device_metrics = metrics_collector.stop()
    validate_idle_device_metrics(device_metrics)
    screenshot_path = Path('/tmp') / (
        f'ccb-mobile-release-reverse-recovery-{int(time.time())}.png'
    )
    screenshot = capture_android_screenshot(
        mobile_root=mobile_root,
        device_id=device_id,
        path=screenshot_path,
        timeout_s=adb_timeout_s,
    )
    return {
        'returncode': 0,
        'mode': 'release_reverse_recovery_smoke',
        'project_id': alpha_project.get('id'),
        'project_name': alpha_project.get('display_name'),
        'agent': agent,
        'build_mode': 'release',
        'opened': opened,
        'reverse_removed': removed,
        'reverse_restored': restored,
        'failure_tap': failure_tap,
        'recovery_tap': recovery_tap,
        'failure_visible_texts': failure.get('texts'),
        'recovered_visible_texts': recovered.get('texts'),
        'recovery_metrics': {
            'elapsed_ms': round((time.monotonic() - started) * 1000.0, 3),
            'post_recovery_settle_seconds': post_recovery_settle_seconds,
            'initial_marker': marker,
            'recovery_marker': recovery_marker,
        },
        'recovery_seed': recovery_seed,
        'recovery_device_metrics': device_metrics,
        'recovery_screenshot_path': screenshot['path'],
        'recovery_screenshot_bytes': screenshot['bytes'],
    }


def cleanup(
    *,
    source_ccb: Path,
    projects: list[Path],
    state_home: Path,
    gateway_process: subprocess.Popen[str] | None,
    keep_running: bool,
) -> dict[str, Any]:
    cleanup_result: dict[str, Any] = {'keep_running': keep_running}
    if keep_running:
        cleanup_result['gateway_pid'] = gateway_process.pid if gateway_process else None
        return cleanup_result
    if gateway_process is not None and gateway_process.poll() is None:
        gateway_process.terminate()
        try:
            gateway_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            gateway_process.kill()
            gateway_process.wait(timeout=3)
        cleanup_result['gateway_returncode'] = gateway_process.returncode
    kills = []
    for project in projects:
        try:
            completed = subprocess.run(
                [str(source_ccb), '--project', str(project), 'kill', '-f'],
                cwd=str(project),
                env=source_env(project_root=project, state_home=state_home),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
            kills.append(
                {
                    'project': str(project),
                    'returncode': completed.returncode,
                    'summary': gateway_smoke.parse_key_value_lines(completed.stdout),
                    'stderr': completed.stderr.strip(),
                }
            )
        except subprocess.TimeoutExpired as exc:
            kills.append(
                {
                    'project': str(project),
                    'returncode': None,
                    'timeout': True,
                    'stdout': (exc.stdout or '').strip(),
                    'stderr': (exc.stderr or '').strip(),
                }
            )
    cleanup_result['kills'] = kills
    return cleanup_result


def source_env(*, project_root: Path, state_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env['CCB_NO_ATTACH'] = '1'
    env['CCB_SOURCE_RUNTIME_OK'] = '1'
    env['CCB_MOBILE_HOST_STATE_HOME'] = str(state_home)
    if not gateway_smoke.is_under(project_root, DEFAULT_PROJECT_PARENT):
        env['CCB_SOURCE_ALLOWED_ROOTS'] = str(project_root)
    return env


def git_head(repo: Path) -> str:
    completed = subprocess.run(
        ['git', 'rev-parse', '--short', 'HEAD'],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip()


def git_dirty(repo: Path) -> bool:
    completed = subprocess.run(
        ['git', 'status', '--short'],
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return bool(completed.stdout.strip())

if __name__ == '__main__':
    sys.exit(main())
