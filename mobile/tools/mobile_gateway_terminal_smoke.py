#!/usr/bin/env python3
"""Run an isolated CCB mobile gateway terminal smoke."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import shutil
import shlex
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_PROJECT_PARENT = Path('/home/bfly/yunwei/test_ccb2')
DEFAULT_SOURCE_CCB = Path('/home/bfly/yunwei/ccb_source/ccb')
DEFAULT_AGENT = 'mobile_probe'
DEFAULT_CONFIG_TEXT = f'cmd, {DEFAULT_AGENT}:codex\n'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cloudflared_named_tunnel_preflight:
        preflight_result = run_named_tunnel_preflight(args)
        print(json.dumps(preflight_result, indent=2, sort_keys=True))
        return 0 if preflight_result['status'] == 'ok' else 1

    mobile_root = Path(__file__).resolve().parents[1]
    project_root = (
        args.project_root.expanduser().resolve()
        if args.project_root is not None
        else default_project_root()
    )
    source_ccb = args.source_ccb.expanduser().resolve()
    gateway = None
    cloudflared = None
    named_tunnel_preflight = None
    public_gateway_ready = None
    public_dns_override = None
    runtime_started = False
    gateway_listen = args.gateway_listen
    gateway_public_url = args.gateway_public_url
    route_provider = args.route_provider
    result: dict[str, Any] = {
        'status': 'error',
        'project_root': str(project_root),
        'source_ccb': str(source_ccb),
    }
    exit_code = 1
    try:
        if args.cloudflared_named_tunnel and args.cloudflared_quick_tunnel:
            raise ValueError(
                '--cloudflared-named-tunnel cannot be combined with '
                '--cloudflared-quick-tunnel'
            )
        if args.cloudflared_named_tunnel:
            route_provider = route_provider or 'cloudflare_tunnel'
            named_tunnel_preflight = run_named_tunnel_preflight(args)
            if named_tunnel_preflight['status'] != 'ok':
                raise RuntimeError(
                    'cloudflared named tunnel preflight failed: '
                    f'{named_tunnel_preflight["named_tunnel_preflight"]["missing"]!r}'
                )
        init_project(project_root, force=args.force_config)
        start_summary = start_ccb_project(
            source_ccb=source_ccb,
            project_root=project_root,
            timeout_s=args.start_timeout,
        )
        runtime_started = True
        pre_harness = run_harness(mobile_root, project_root, timeout_s=args.harness_timeout)
        if args.cloudflared_quick_tunnel:
            if gateway_public_url:
                raise ValueError(
                    '--cloudflared-quick-tunnel cannot be combined with --gateway-public-url'
                )
            port = allocate_loopback_port()
            gateway_listen = f'127.0.0.1:{port}'
            cloudflared = start_cloudflared_quick_tunnel(
                cloudflared_bin=args.cloudflared_bin,
                origin_url=f'http://127.0.0.1:{port}',
                timeout_s=args.cloudflared_timeout,
            )
            gateway_public_url = str(cloudflared['public_url'])
            route_provider = route_provider or 'cloudflare_tunnel'
        route_provider = route_provider or ('cloudflare_tunnel' if gateway_public_url else 'lan')
        gateway = start_mobile_gateway(
            source_ccb=source_ccb,
            project_root=project_root,
            timeout_s=args.gateway_timeout,
            listen=gateway_listen,
            public_url=gateway_public_url,
            route_provider=route_provider,
        )
        if args.cloudflared_named_tunnel:
            cloudflared = start_cloudflared_named_tunnel(
                cloudflared_bin=args.cloudflared_bin,
                config_path=args.cloudflared_config,
                tunnel_name=args.cloudflared_tunnel_name,
                timeout_s=args.cloudflared_timeout,
            )
        if gateway_public_url:
            public_dns_override = public_dns_override_for_gateway_url(
                gateway['gateway_url'],
                dns_server=args.public_dns_server,
                disabled=args.disable_public_dns_override,
                force=args.cloudflared_quick_tunnel,
            )
            public_gateway_ready = wait_public_gateway_ready(
                gateway_url=gateway['gateway_url'],
                timeout_s=args.public_ready_timeout,
                dns_override=public_dns_override,
                dns_server=args.public_dns_server,
                allow_dns_override=not args.disable_public_dns_override,
                force_dns_override=args.cloudflared_quick_tunnel,
            )
            public_dns_override = public_gateway_ready.get('dns_override')
        dart_smoke = run_dart_smoke(
            mobile_root=mobile_root,
            gateway_url=gateway['gateway_url'],
            pairing_code=gateway['pairing_code'],
            agent=args.agent,
            route_provider=route_provider,
            dns_override=public_dns_override,
            timeout_s=args.dart_timeout,
        )
        post_harness = run_harness(mobile_root, project_root, timeout_s=args.harness_timeout)
        if dart_smoke.get('status') != 'ok':
            raise RuntimeError(f'Dart gateway smoke failed: {dart_smoke!r}')
        if dart_smoke.get('terminal_history_loaded') is not True:
            raise RuntimeError('Dart gateway smoke did not load terminal history')
        if not dart_smoke.get('terminal_history_source_pane_id'):
            raise RuntimeError('Dart gateway smoke did not report a terminal history pane')
        if post_harness.get('mobile_terminal_target_ok') is not True:
            raise RuntimeError('post-smoke harness did not report an attachable terminal target')
        result.update(
            {
                'status': 'ok',
                'started': start_summary,
                'pre_harness': summarize_harness(pre_harness),
                'gateway': sanitize_gateway_summary(gateway),
                'cloudflared': sanitize_cloudflared_summary(cloudflared),
                'named_tunnel_preflight': named_tunnel_preflight,
                'public_dns_override': public_dns_override,
                'public_gateway_ready': public_gateway_ready,
                'dart_smoke': dart_smoke,
                'post_harness': summarize_harness(post_harness),
            }
        )
        exit_code = 0
    except Exception as exc:
        result['error'] = str(exc)
        if isinstance(gateway, dict):
            result['gateway'] = sanitize_gateway_summary(gateway)
        if isinstance(cloudflared, dict):
            result['cloudflared'] = sanitize_cloudflared_summary(cloudflared)
        if named_tunnel_preflight is not None:
            result['named_tunnel_preflight'] = named_tunnel_preflight
        if public_dns_override is not None:
            result['public_dns_override'] = public_dns_override
        if public_gateway_ready is not None:
            result['public_gateway_ready'] = public_gateway_ready
    finally:
        if runtime_started or isinstance(gateway, dict) or isinstance(cloudflared, dict):
            cleanup = cleanup_runtime(
                source_ccb=source_ccb,
                project_root=project_root,
                gateway_process=gateway.get('process') if isinstance(gateway, dict) else None,
                cloudflared_process=cloudflared.get('process') if isinstance(cloudflared, dict) else None,
                keep_running=args.keep_running,
            )
        else:
            cleanup = {'keep_running': args.keep_running, 'runtime_started': False}
        result['cleanup'] = cleanup
        print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Start a disposable CCB project and prove gateway terminal WebSocket input/output.',
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        help='disposable project root; defaults under /home/bfly/yunwei/test_ccb2',
    )
    parser.add_argument(
        '--source-ccb',
        type=Path,
        default=DEFAULT_SOURCE_CCB,
        help=f'CCB source CLI to exercise (default: {DEFAULT_SOURCE_CCB})',
    )
    parser.add_argument(
        '--agent',
        default=DEFAULT_AGENT,
        help=f'configured agent to focus and open (default: {DEFAULT_AGENT})',
    )
    parser.add_argument('--force-config', action='store_true', help='rewrite generated .ccb/ccb.config')
    parser.add_argument('--keep-running', action='store_true', help='leave gateway and CCB runtime running')
    parser.add_argument(
        '--gateway-listen',
        default='127.0.0.1:0',
        help='loopback address for ccb mobile serve; use a fixed port for an external named tunnel',
    )
    parser.add_argument(
        '--gateway-public-url',
        help='external HTTPS gateway URL to write into the pairing payload, for example a Cloudflare Tunnel hostname',
    )
    parser.add_argument(
        '--route-provider',
        choices=('lan', 'tailnet', 'cloudflare_tunnel', 'relay'),
        default=None,
        help='route provider to write into pairing metadata; defaults to cloudflare_tunnel when a public URL is used',
    )
    parser.add_argument(
        '--cloudflared-quick-tunnel',
        action='store_true',
        help='start cloudflared tunnel --url against a generated loopback port and use the trycloudflare URL',
    )
    parser.add_argument(
        '--cloudflared-named-tunnel',
        action='store_true',
        help='start cloudflared tunnel run after named-tunnel preflight passes',
    )
    parser.add_argument(
        '--cloudflared-tunnel-name',
        help='optional tunnel name or UUID passed to cloudflared tunnel run; defaults to config.yml tunnel',
    )
    parser.add_argument('--cloudflared-bin', default='cloudflared')
    parser.add_argument(
        '--cloudflared-config',
        type=Path,
        default=Path.home() / '.cloudflared' / 'config.yml',
        help='cloudflared config.yml used by the named-tunnel preflight',
    )
    parser.add_argument(
        '--cloudflared-named-tunnel-preflight',
        action='store_true',
        help='check named Cloudflare Tunnel prerequisites and exit without starting CCB runtime',
    )
    parser.add_argument(
        '--public-dns-server',
        default='1.1.1.1',
        help='DNS server used for smoke-only public hostname override when system resolution fails',
    )
    parser.add_argument(
        '--disable-public-dns-override',
        action='store_true',
        help='do not use a smoke-only host=ip override when the system resolver cannot resolve the public URL',
    )
    parser.add_argument('--start-timeout', type=float, default=30.0)
    parser.add_argument('--gateway-timeout', type=float, default=15.0)
    parser.add_argument('--cloudflared-timeout', type=float, default=30.0)
    parser.add_argument(
        '--public-ready-timeout',
        type=float,
        default=60.0,
        help='seconds to wait for a public tunnel URL to serve /v1/health before Dart smoke',
    )
    parser.add_argument('--dart-timeout', type=float, default=60.0)
    parser.add_argument('--harness-timeout', type=float, default=5.0)
    return parser.parse_args(argv)


def run_named_tunnel_preflight(args: argparse.Namespace) -> dict[str, Any]:
    report = cloudflared_named_tunnel_preflight(
        cloudflared_bin=args.cloudflared_bin,
        config_path=args.cloudflared_config,
        tunnel_name=args.cloudflared_tunnel_name,
        gateway_public_url=args.gateway_public_url,
        gateway_listen=args.gateway_listen,
        route_provider=args.route_provider,
    )
    return {
        'status': 'ok' if report['ok'] else 'blocked',
        'named_tunnel_preflight': report,
    }


def cloudflared_named_tunnel_preflight(
    *,
    cloudflared_bin: str,
    config_path: Path,
    gateway_public_url: str | None,
    gateway_listen: str,
    route_provider: str | None,
    tunnel_name: str | None = None,
) -> dict[str, Any]:
    missing: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []
    parsed_public_url = urlparse(gateway_public_url or '')
    suggested_gateway_public_url, public_url_missing = (
        validate_gateway_public_url_origin(parsed_public_url)
    )
    expanded_config_path = config_path.expanduser()
    public_hostname = parsed_public_url.hostname or '<hostname>'
    effective_tunnel_name = tunnel_name or 'ccb-mobile'
    quoted_tunnel_name = shlex.quote(effective_tunnel_name)
    gateway_listen_ok, suggested_gateway_listen, gateway_listen_missing = (
        validate_named_tunnel_gateway_listen(gateway_listen)
    )
    config_template = cloudflared_config_template(
        public_hostname=public_hostname,
        gateway_listen=suggested_gateway_listen,
        config_path=expanded_config_path,
    )
    smoke_command = named_tunnel_smoke_command(
        cloudflared_bin=cloudflared_bin,
        config_path=expanded_config_path,
        tunnel_name=tunnel_name,
        gateway_public_url=suggested_gateway_public_url or gateway_public_url,
        gateway_listen=suggested_gateway_listen,
    )
    manual_cloudflared_command = cloudflared_named_tunnel_run_command(
        cloudflared_bin=cloudflared_bin,
        config_path=expanded_config_path,
        tunnel_name=tunnel_name,
    )
    existing_tunnel_command = existing_tunnel_smoke_command(
        gateway_public_url=suggested_gateway_public_url or gateway_public_url,
        gateway_listen=suggested_gateway_listen,
    )
    resolved_cloudflared = shutil.which(cloudflared_bin)
    if resolved_cloudflared is None:
        missing.append(f'cloudflared binary not found: {cloudflared_bin}')
        next_actions.append(
            'Install cloudflared or pass --cloudflared-bin /path/to/cloudflared.'
        )
        resolved_cloudflared = cloudflared_bin

    version = ''
    if resolved_cloudflared and not missing:
        version = read_cloudflared_version(resolved_cloudflared)

    effective_route_provider = route_provider or (
        'cloudflare_tunnel' if gateway_public_url else 'lan'
    )
    if effective_route_provider != 'cloudflare_tunnel':
        missing.append(
            'route provider must be cloudflare_tunnel for named tunnel validation'
        )
        next_actions.append('Pass --route-provider cloudflare_tunnel.')

    if not gateway_public_url:
        missing.append('--gateway-public-url is required for named tunnel validation')
        next_actions.append('Pass --gateway-public-url https://<your-mobile-hostname>.')
    elif parsed_public_url.scheme != 'https' or not parsed_public_url.hostname:
        missing.append('--gateway-public-url must be an absolute https URL')
        next_actions.append('Use an HTTPS public URL such as https://mobile.example.com.')
    elif public_url_missing:
        missing.extend(public_url_missing)
        next_actions.append(
            f'Use --gateway-public-url {suggested_gateway_public_url}.'
        )

    if not gateway_listen_ok:
        missing.extend(gateway_listen_missing)
        next_actions.append(
            f'Pass --gateway-listen {suggested_gateway_listen} or another fixed '
            'loopback host:port, and make cloudflared ingress use the same port.'
        )

    config_exists = expanded_config_path.is_file()
    config_values: dict[str, Any] = {}
    if config_exists:
        config_values = parse_cloudflared_config(expanded_config_path)
    else:
        missing.append(f'cloudflared config not found: {expanded_config_path}')
        next_actions.extend(
            cloudflared_setup_next_actions(
                tunnel_name=effective_tunnel_name,
                public_hostname=public_hostname,
                gateway_listen=suggested_gateway_listen,
                config_path=expanded_config_path,
            )
        )

    tunnel_value = config_values.get('tunnel', '')
    if config_exists and not tunnel_value:
        missing.append('cloudflared config is missing tunnel')
        next_actions.append(
            f'Add tunnel: <tunnel-uuid-or-name> to {expanded_config_path}.'
        )

    credentials_file = config_values.get('credentials-file', '')
    credentials_path = ''
    credentials_exists = False
    has_credentials_env = any(
        os.environ.get(name)
        for name in ('TUNNEL_CRED_FILE', 'TUNNEL_CRED_CONTENTS', 'TUNNEL_TOKEN')
    )
    if credentials_file:
        resolved_credentials = resolve_config_path(
            credentials_file,
            expanded_config_path.parent,
        )
        credentials_path = str(resolved_credentials)
        credentials_exists = resolved_credentials.is_file()
        if not credentials_exists:
            missing.append(
                f'cloudflared credentials file not found: {resolved_credentials}'
            )
            next_actions.append(
                f'Run cloudflared tunnel create {quoted_tunnel_name} or fix '
                f'credentials-file in {expanded_config_path}.'
            )
    elif config_exists and not has_credentials_env:
        missing.append('cloudflared config is missing credentials-file')
        next_actions.append(
            f'Add credentials-file: <path-to-tunnel-json> to {expanded_config_path}.'
        )

    origin_service, origin_selection = select_cloudflared_origin_service(
        config_values,
        public_hostname=parsed_public_url.hostname,
    )
    origin_action_listen = (
        suggested_gateway_listen if not gateway_listen_ok else gateway_listen
    )
    origin_matches_gateway_listen = None
    if origin_service:
        origin_matches_gateway_listen = origin_service_matches_listen(
            origin_service,
            gateway_listen,
        )
        if origin_matches_gateway_listen is False:
            missing.append(
                f'cloudflared origin service {origin_service} does not match '
                f'gateway listen {gateway_listen}'
            )
            next_actions.append(
                f'Change the matched ingress service to http://{origin_action_listen}.'
            )
    elif config_exists:
        if parsed_public_url.hostname:
            missing.append(
                'cloudflared config has no HTTP ingress service for hostname '
                f'{parsed_public_url.hostname}'
            )
            next_actions.append(
                'Add an ingress rule with hostname '
                f'{parsed_public_url.hostname} and service http://{suggested_gateway_listen}.'
            )
        else:
            missing.append('cloudflared config has no concrete HTTP origin service')
            next_actions.append(
                f'Add an ingress service pointing to http://{suggested_gateway_listen}.'
            )

    origin_cert_path = Path.home() / '.cloudflared' / 'cert.pem'
    origin_cert_exists = origin_cert_path.is_file()
    if not origin_cert_exists:
        warnings.append(
            'origin cert.pem is missing; running an existing UUID tunnel may still work '
            'with credentials-file, but login/create/route commands need Cloudflare credentials'
        )
        if not config_exists or not tunnel_value:
            next_actions.append('Run cloudflared tunnel login before create/route commands.')

    if not missing:
        next_actions.append(
            f'Preflight passed; run {smoke_command}.'
        )

    return {
        'ok': not missing,
        'cloudflared_bin': cloudflared_bin,
        'cloudflared_resolved': resolved_cloudflared,
        'cloudflared_version': version,
        'cloudflared_tunnel_name': tunnel_name or '',
        'setup_tunnel_name': effective_tunnel_name,
        'config_path': str(expanded_config_path),
        'config_exists': config_exists,
        'tunnel': tunnel_value,
        'credentials_file': credentials_path or credentials_file,
        'credentials_file_exists': credentials_exists or has_credentials_env,
        'credentials_from_env': has_credentials_env,
        'origin_service': origin_service,
        'origin_selection': origin_selection,
        'gateway_listen': gateway_listen,
        'origin_matches_gateway_listen': origin_matches_gateway_listen,
        'gateway_public_url': gateway_public_url or '',
        'suggested_gateway_public_url': suggested_gateway_public_url,
        'suggested_gateway_listen': suggested_gateway_listen,
        'route_provider': effective_route_provider,
        'origin_cert_path': str(origin_cert_path),
        'origin_cert_exists': origin_cert_exists,
        'config_template': config_template,
        'cloudflared_run_command': manual_cloudflared_command,
        'existing_tunnel_smoke_command': existing_tunnel_command,
        'named_tunnel_smoke_command': smoke_command,
        'missing': missing,
        'warnings': warnings,
        'next_actions': dedupe_preserving_order(next_actions),
    }


def validate_gateway_public_url_origin(parsed_public_url: Any) -> tuple[str, list[str]]:
    if not parsed_public_url.scheme or not parsed_public_url.hostname:
        return '', []
    missing: list[str] = []
    try:
        public_port = parsed_public_url.port
    except ValueError:
        public_port = None
        missing.append('--gateway-public-url port must be valid')
    public_host = parsed_public_url.hostname
    if ':' in public_host and not public_host.startswith('['):
        public_host = f'[{public_host}]'
    public_netloc = public_host
    if public_port is not None:
        public_netloc = f'{public_netloc}:{public_port}'
    suggested_public_url = f'{parsed_public_url.scheme}://{public_netloc}'
    if parsed_public_url.username or parsed_public_url.password:
        missing.append('--gateway-public-url must not include credentials')
    if parsed_public_url.path not in {'', '/'}:
        missing.append('--gateway-public-url must be the gateway origin URL without a path')
    if parsed_public_url.params or parsed_public_url.query or parsed_public_url.fragment:
        missing.append('--gateway-public-url must not include params, query, or fragment')
    return suggested_public_url, missing


def read_cloudflared_version(cloudflared_bin: str) -> str:
    try:
        completed = subprocess.run(
            [cloudflared_bin, '--version'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return f'unavailable: {exc}'
    text = (completed.stdout or completed.stderr).strip()
    return text


def cloudflared_setup_next_actions(
    *,
    tunnel_name: str,
    public_hostname: str,
    gateway_listen: str,
    config_path: Path,
) -> list[str]:
    quoted_tunnel_name = shlex.quote(tunnel_name)
    return [
        'Run cloudflared tunnel login.',
        f'Run cloudflared tunnel create {quoted_tunnel_name}.',
        f'Run cloudflared tunnel route dns {quoted_tunnel_name} {public_hostname}.',
        (
            f'Create {config_path} with tunnel, credentials-file, and ingress '
            f'service http://{gateway_listen}.'
        ),
    ]


def cloudflared_config_template(
    *,
    public_hostname: str,
    gateway_listen: str,
    config_path: Path,
) -> str:
    credentials_file = config_path.parent / '<tunnel-uuid>.json'
    return (
        'tunnel: <tunnel-uuid>\n'
        f'credentials-file: {credentials_file}\n'
        '\n'
        'ingress:\n'
        f'  - hostname: {public_hostname}\n'
        f'    service: http://{gateway_listen}\n'
        '  - service: http_status:404\n'
    )


def named_tunnel_smoke_command(
    *,
    cloudflared_bin: str,
    config_path: Path,
    tunnel_name: str | None,
    gateway_public_url: str | None,
    gateway_listen: str,
) -> str:
    default_config = Path.home() / '.cloudflared' / 'config.yml'
    public_url = gateway_public_url or 'https://<your-mobile-hostname>'
    argv = [
        'tools/mobile_gateway_terminal_smoke.py',
        '--cloudflared-named-tunnel',
    ]
    if cloudflared_bin != 'cloudflared':
        argv.extend(['--cloudflared-bin', cloudflared_bin])
    if config_path != default_config:
        argv.extend(['--cloudflared-config', str(config_path)])
    if tunnel_name:
        argv.extend(['--cloudflared-tunnel-name', tunnel_name])
    argv.extend(
        [
            '--gateway-listen',
            gateway_listen,
            '--gateway-public-url',
            public_url,
            '--route-provider',
            'cloudflare_tunnel',
        ]
    )
    return shell_command(argv)


def existing_tunnel_smoke_command(
    *,
    gateway_public_url: str | None,
    gateway_listen: str,
) -> str:
    public_url = gateway_public_url or 'https://<your-mobile-hostname>'
    return shell_command(
        [
            'tools/mobile_gateway_terminal_smoke.py',
            '--gateway-listen',
            gateway_listen,
            '--gateway-public-url',
            public_url,
            '--route-provider',
            'cloudflare_tunnel',
        ]
    )


def cloudflared_named_tunnel_run_command(
    *,
    cloudflared_bin: str,
    config_path: Path,
    tunnel_name: str | None,
) -> str:
    argv = [
        cloudflared_bin,
        'tunnel',
        '--config',
        str(config_path),
        'run',
    ]
    if tunnel_name:
        argv.append(tunnel_name)
    return shell_command(argv)


def shell_command(argv: list[str]) -> str:
    return ' '.join(shlex.quote(value) for value in argv)


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def parse_cloudflared_config(config_path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {'ingress': []}
    ingress: list[dict[str, str]] = values['ingress']
    in_ingress = False
    current_ingress: dict[str, str] | None = None
    for raw_line in config_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.split('#', 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == 'ingress:':
            in_ingress = True
            current_ingress = None
            continue
        if in_ingress and stripped.startswith('- '):
            current_ingress = {}
            ingress.append(current_ingress)
            maybe_set_config_pair(current_ingress, stripped[2:].strip())
            continue
        if in_ingress and current_ingress is not None and line.startswith(' '):
            maybe_set_config_pair(current_ingress, stripped)
            continue
        in_ingress = False
        current_ingress = None
        if ':' not in stripped:
            continue
        key, value = parse_config_pair(stripped)
        if key in {'tunnel', 'credentials-file'}:
            values[key] = value
    return values


def maybe_set_config_pair(target: dict[str, str], text: str) -> None:
    if ':' not in text:
        return
    key, value = parse_config_pair(text)
    if key in {'hostname', 'service'}:
        target[key] = value


def parse_config_pair(text: str) -> tuple[str, str]:
    key, value = text.split(':', 1)
    return key.strip(), unquote_yaml_scalar(value.strip())


def unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def select_cloudflared_origin_service(
    config_values: dict[str, Any],
    *,
    public_hostname: str | None,
) -> tuple[str, str]:
    ingress = config_values.get('ingress')
    if not isinstance(ingress, list):
        return '', 'none'
    origins: list[dict[str, str]] = []
    for entry in ingress:
        if not isinstance(entry, dict):
            continue
        service = entry.get('service', '')
        if not service or service.startswith('http_status:'):
            continue
        if not service.startswith(('http://', 'https://')):
            continue
        hostname = entry.get('hostname', '')
        origins.append({'hostname': hostname, 'service': service})
    if public_hostname:
        for origin in origins:
            if origin['hostname'] == public_hostname:
                return origin['service'], 'matched_hostname'
    if len(origins) == 1:
        return origins[0]['service'], 'single_origin'
    return '', 'none'


def resolve_config_path(value: str, config_dir: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    if expanded.is_absolute():
        return expanded
    return config_dir / expanded


def origin_service_matches_listen(
    origin_service: str,
    gateway_listen: str,
) -> bool | None:
    parsed_service = urlparse(origin_service)
    if parsed_service.scheme not in {'http', 'https'} or not parsed_service.hostname:
        return None
    listen_host, listen_port = parse_gateway_listen(gateway_listen)
    if listen_host is None or listen_port is None:
        return None
    service_host = parsed_service.hostname
    service_port = parsed_service.port or (
        443 if parsed_service.scheme == 'https' else 80
    )
    localhost_names = {'localhost', '127.0.0.1', '::1'}
    if service_host not in localhost_names or listen_host not in localhost_names:
        return None
    return service_port == listen_port


def validate_named_tunnel_gateway_listen(
    gateway_listen: str,
) -> tuple[bool, str, list[str]]:
    suggested = '127.0.0.1:8787'
    listen_host, listen_port = parse_gateway_listen(gateway_listen)
    missing: list[str] = []
    if listen_host is None or listen_port is None:
        missing.append(
            'gateway listen must be an explicit loopback host:port for '
            f'named tunnel validation: {gateway_listen}'
        )
        return False, suggested, missing
    localhost_names = {'localhost', '127.0.0.1', '::1'}
    if listen_host not in localhost_names:
        missing.append(
            'gateway listen must be loopback for named tunnel validation: '
            f'{gateway_listen}'
        )
    if listen_port <= 0 or listen_port > 65535:
        missing.append(
            'gateway listen must use a fixed TCP port for named tunnel validation: '
            f'{gateway_listen}'
        )
    if missing:
        return False, suggested, missing
    return True, gateway_listen, []


def parse_gateway_listen(gateway_listen: str) -> tuple[str | None, int | None]:
    host, separator, port_text = gateway_listen.rpartition(':')
    if not separator:
        return None, None
    host = host.strip('[]') or '127.0.0.1'
    try:
        port = int(port_text)
    except ValueError:
        return host, None
    return host, port


def default_project_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    return (DEFAULT_PROJECT_PARENT / f'ccb-mobile-gateway-smoke-{stamp}').resolve()


def init_project(project_root: Path, *, force: bool) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / '.ccb' / 'ccb.config'
    if config_path.exists() and not force:
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(DEFAULT_CONFIG_TEXT, encoding='utf-8')


def start_ccb_project(*, source_ccb: Path, project_root: Path, timeout_s: float) -> dict[str, Any]:
    env = source_env(project_root)
    completed = subprocess.run(
        [str(source_ccb), '--project', str(project_root), '-s'],
        cwd=str(source_ccb.parent),
        env=env,
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
    return parse_key_value_lines(completed.stdout)


def start_mobile_gateway(
    *,
    source_ccb: Path,
    project_root: Path,
    timeout_s: float,
    listen: str,
    public_url: str | None,
    route_provider: str,
) -> dict[str, Any]:
    env = source_env(project_root)
    command = [
        str(source_ccb),
        '--project',
        str(project_root),
        'mobile',
        'serve',
        '--listen',
        listen,
    ]
    if public_url:
        command.extend(['--public-url', public_url])
    command.extend(['--route-provider', route_provider])
    process = subprocess.Popen(
        command,
        cwd=str(source_ccb.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    summary = read_gateway_startup(process, timeout_s=timeout_s)
    summary['process'] = process
    summary['route_provider'] = route_provider
    summary['requested_public_url'] = public_url or ''
    return summary


def start_cloudflared_quick_tunnel(
    *,
    cloudflared_bin: str,
    origin_url: str,
    timeout_s: float,
) -> dict[str, Any]:
    process = subprocess.Popen(
        [cloudflared_bin, 'tunnel', '--url', origin_url],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    try:
        public_url, stderr_text = read_cloudflared_public_url(process, timeout_s=timeout_s)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        close_process_pipes(process)
        raise
    return {
        'mode': 'quick',
        'process': process,
        'origin_url': origin_url,
        'public_url': public_url,
        'stderr': stderr_text,
    }


def start_cloudflared_named_tunnel(
    *,
    cloudflared_bin: str,
    config_path: Path,
    tunnel_name: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    command = [
        cloudflared_bin,
        'tunnel',
        '--config',
        str(config_path.expanduser()),
        'run',
    ]
    if tunnel_name:
        command.append(tunnel_name)
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    try:
        output_text = read_cloudflared_named_tunnel_ready(process, timeout_s=timeout_s)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        close_process_pipes(process)
        raise
    return {
        'mode': 'named',
        'process': process,
        'config_path': str(config_path.expanduser()),
        'tunnel_name': tunnel_name or '',
        'stderr': output_text,
    }


def read_cloudflared_public_url(
    process: subprocess.Popen[str],
    *,
    timeout_s: float,
) -> tuple[str, str]:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError('cloudflared stdout/stderr pipes are missing')
    lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
    threading.Thread(
        target=enqueue_lines,
        args=('stdout', process.stdout, lines),
        daemon=True,
    ).start()
    threading.Thread(
        target=enqueue_lines,
        args=('stderr', process.stderr, lines),
        daemon=True,
    ).start()
    deadline = time.monotonic() + timeout_s
    output_lines: list[str] = []
    url_pattern = re.compile(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com')
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                'cloudflared exited during startup\n'
                f'code: {process.returncode}\n'
                f'output:\n{"".join(output_lines)}'
            )
        try:
            _stream_name, line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            continue
        output_lines.append(line)
        match = url_pattern.search(line)
        if match:
            return match.group(0).rstrip('/'), ''.join(output_lines).strip()
    raise TimeoutError(
        'timed out waiting for cloudflared quick tunnel URL\n'
        f'output:\n{"".join(output_lines)}'
    )


def close_process_pipes(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def read_cloudflared_named_tunnel_ready(
    process: subprocess.Popen[str],
    *,
    timeout_s: float,
) -> str:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError('cloudflared stdout/stderr pipes are missing')
    lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
    threading.Thread(
        target=enqueue_lines,
        args=('stdout', process.stdout, lines),
        daemon=True,
    ).start()
    threading.Thread(
        target=enqueue_lines,
        args=('stderr', process.stderr, lines),
        daemon=True,
    ).start()
    deadline = time.monotonic() + timeout_s
    output_lines: list[str] = []
    ready_patterns = (
        'Registered tunnel connection',
        'Connection registered',
    )
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                'cloudflared named tunnel exited during startup\n'
                f'code: {process.returncode}\n'
                f'output:\n{"".join(output_lines)}'
            )
        try:
            _stream_name, line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        if line is None:
            continue
        output_lines.append(line)
        if any(pattern in line for pattern in ready_patterns):
            return ''.join(output_lines).strip()
    raise TimeoutError(
        'timed out waiting for cloudflared named tunnel connection\n'
        f'output:\n{"".join(output_lines)}'
    )


def read_gateway_startup(
    process: subprocess.Popen[str],
    *,
    timeout_s: float,
) -> dict[str, Any]:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError('mobile gateway stdout/stderr pipes are missing')
    lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_reader = threading.Thread(
        target=enqueue_lines,
        args=('stdout', process.stdout, lines),
        daemon=True,
    )
    stderr_reader = threading.Thread(
        target=enqueue_lines,
        args=('stderr', process.stderr, lines),
        daemon=True,
    )
    stdout_reader.start()
    stderr_reader.start()
    deadline = time.monotonic() + timeout_s
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    fields: dict[str, str] = {}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr_lines.extend(process.stderr.readlines())
            stdout_lines.extend(process.stdout.readlines())
            raise RuntimeError(
                'mobile serve exited during startup\n'
                f'code: {process.returncode}\n'
                f'stdout:\n{"".join(stdout_lines)}\n'
                f'stderr:\n{"".join(stderr_lines)}'
            )
        try:
            stream_name, line = lines.get(timeout=0.1)
        except queue.Empty:
            continue
        collect_gateway_line(stream_name, line, stdout_lines, stderr_lines, fields)
        while True:
            try:
                stream_name, line = lines.get_nowait()
            except queue.Empty:
                break
            collect_gateway_line(stream_name, line, stdout_lines, stderr_lines, fields)
        pairing_code = fields.get('pairing_code', '').strip()
        claim_endpoint = fields.get('pairing_claim_endpoint', '').strip()
        if pairing_code and claim_endpoint:
            parsed = urlparse(claim_endpoint)
            if not parsed.scheme or not parsed.netloc:
                raise RuntimeError(f'invalid pairing_claim_endpoint: {claim_endpoint!r}')
            gateway_url = f'{parsed.scheme}://{parsed.netloc}'
            listen = fields.get('listen', '')
            return {
                'listen': listen,
                'project_id': fields.get('project_id', ''),
                'project_root': fields.get('project_root', ''),
                'gateway_url': gateway_url,
                'local_gateway_url': f'http://{listen}' if listen else '',
                'route_provider': fields.get('route_provider', ''),
                'pairing_code': pairing_code,
                'pairing_code_seen': True,
                'pairing_claim_endpoint': claim_endpoint,
                'stderr': ''.join(stderr_lines).strip(),
            }
    raise TimeoutError(
        'timed out waiting for mobile serve pairing summary\n'
        f'stdout:\n{"".join(stdout_lines)}\n'
        f'stderr:\n{"".join(stderr_lines)}'
    )


def wait_public_gateway_ready(
    *,
    gateway_url: str,
    timeout_s: float,
    dns_override: dict[str, str] | None,
    dns_server: str,
    allow_dns_override: bool,
    force_dns_override: bool,
) -> dict[str, Any]:
    health_url = f'{gateway_url.rstrip("/")}/v1/health'
    deadline = time.monotonic() + timeout_s
    attempts = 0
    last_error = ''
    while time.monotonic() < deadline:
        attempts += 1
        if dns_override is None and allow_dns_override:
            dns_override = public_dns_override_for_gateway_url(
                gateway_url,
                dns_server=dns_server,
                disabled=False,
                force=force_dns_override,
            )
        try:
            if dns_override is None:
                status_code, body = read_public_health_with_system_dns(health_url)
            else:
                status_code, body = read_public_health_with_dns_override(
                    health_url,
                    dns_override=dns_override,
                )
            payload = json.loads(body)
            if status_code == 200 and payload.get('status') == 'ok':
                capabilities = payload.get('capabilities')
                return {
                    'health_url': health_url,
                    'attempts': attempts,
                    'dns_override': dns_override,
                    'status_code': status_code,
                    'status': payload.get('status'),
                    'capabilities': (
                        sorted(capabilities)
                        if isinstance(capabilities, list)
                        else []
                    ),
                }
            last_error = f'unexpected health response {status_code}: {body[:300]}'
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode('utf-8', errors='replace')
            last_error = f'http {exc.code}: {body[:300]}'
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(
        f'timed out waiting for public gateway health {health_url}\n'
        f'attempts: {attempts}\n'
        f'last_error: {last_error}'
    )


def read_public_health_with_system_dns(health_url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        health_url,
        headers={'Accept': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        body = response.read(4096).decode('utf-8', errors='replace')
        return response.status, body


def read_public_health_with_dns_override(
    health_url: str,
    *,
    dns_override: dict[str, str],
) -> tuple[int, str]:
    parsed = urlparse(health_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError(f'unsupported public health URL: {health_url}')
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    target_host = dns_override['address'] if host == dns_override['host'] else host
    raw_socket = socket.create_connection((target_host, port), timeout=3)
    try:
        if parsed.scheme == 'https':
            context = ssl.create_default_context()
            stream = context.wrap_socket(raw_socket, server_hostname=host)
        else:
            stream = raw_socket
        try:
            stream.settimeout(3)
            path = parsed.path or '/'
            if parsed.query:
                path = f'{path}?{parsed.query}'
            host_header = host if parsed.port is None else f'{host}:{port}'
            request = (
                f'GET {path} HTTP/1.1\r\n'
                f'Host: {host_header}\r\n'
                'Accept: application/json\r\n'
                'Connection: close\r\n'
                '\r\n'
            )
            stream.sendall(request.encode('ascii'))
            response = bytearray()
            while True:
                chunk = stream.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
        finally:
            stream.close()
    except Exception:
        raw_socket.close()
        raise
    header, _sep, body = bytes(response).partition(b'\r\n\r\n')
    status_line = header.splitlines()[0].decode('ascii', errors='replace')
    parts = status_line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f'invalid public health response: {status_line}')
    return int(parts[1]), body.decode('utf-8', errors='replace')


def public_dns_override_for_gateway_url(
    gateway_url: str,
    *,
    dns_server: str,
    disabled: bool,
    force: bool = False,
) -> dict[str, str] | None:
    if disabled:
        return None
    parsed = urlparse(gateway_url)
    host = parsed.hostname
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if not force:
        try:
            socket.getaddrinfo(host, parsed.port or 443)
            return None
        except socket.gaierror:
            pass
    addresses = resolve_a_records_with_dig(host, dns_server=dns_server)
    if not addresses:
        return None
    return {
        'host': host,
        'address': addresses[0],
        'mode': 'forced' if force else 'auto',
        'source': f'dig @{dns_server}',
    }


def resolve_a_records_with_dig(host: str, *, dns_server: str) -> list[str]:
    completed = subprocess.run(
        ['dig', f'@{dns_server}', host, 'A', '+time=5', '+tries=1', '+short'],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        return []
    addresses: list[str] = []
    for line in completed.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address.version == 4:
            addresses.append(str(address))
    return addresses


def enqueue_lines(name: str, stream, out: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in iter(stream.readline, ''):
            out.put((name, line))
    finally:
        out.put((name, None))


def collect_gateway_line(
    stream_name: str,
    line: str | None,
    stdout_lines: list[str],
    stderr_lines: list[str],
    fields: dict[str, str],
) -> None:
    if line is None:
        return
    if stream_name == 'stderr':
        stderr_lines.append(line)
        return
    stdout_lines.append(line)
    parsed = parse_key_value_line(line)
    if parsed is not None:
        name, value = parsed
        fields[name] = value


def run_dart_smoke(
    *,
    mobile_root: Path,
    gateway_url: str,
    pairing_code: str,
    agent: str,
    route_provider: str,
    dns_override: dict[str, str] | None,
    timeout_s: float,
) -> dict[str, Any]:
    env = os.environ.copy()
    env['CCB_MOBILE_GATEWAY_URL'] = gateway_url
    env['CCB_MOBILE_PAIRING_CODE'] = pairing_code
    env['CCB_MOBILE_AGENT'] = agent
    env['CCB_MOBILE_DEVICE_NAME'] = 'Gateway Smoke'
    env['CCB_MOBILE_ROUTE_PROVIDER'] = route_provider
    if dns_override is not None:
        env['CCB_MOBILE_DNS_OVERRIDE'] = (
            f'{dns_override["host"]}={dns_override["address"]}'
        )
    env['CCB_MOBILE_TIMEOUT_SECONDS'] = str(max(5, int(timeout_s // 3)))
    toolchain = mobile_root / 'tools' / 'mobile_toolchain_env.sh'
    command = f'. {shlex.quote(str(toolchain))} && dart run tool/gateway_terminal_smoke.dart'
    completed = subprocess.run(
        ['sh', '-lc', command],
        cwd=str(mobile_root / 'app'),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
    )
    parsed = parse_json_from_stdout(completed.stdout)
    parsed['dart_returncode'] = completed.returncode
    if completed.stderr.strip():
        parsed['dart_stderr'] = completed.stderr.strip()
    if completed.returncode != 0:
        raise RuntimeError(
            'Dart gateway terminal smoke failed\n'
            f'stdout:\n{completed.stdout}\n'
            f'stderr:\n{completed.stderr}'
        )
    return parsed


def run_harness(mobile_root: Path, project_root: Path, *, timeout_s: float) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(mobile_root / 'tools' / 'mobile_terminal_harness.py'),
            '--project-root',
            str(project_root),
            '--timeout',
            str(timeout_s),
        ],
        cwd=str(mobile_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(10.0, timeout_s + 5.0),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            'mobile terminal harness failed\n'
            f'stdout:\n{completed.stdout}\n'
            f'stderr:\n{completed.stderr}'
        )
    return json.loads(completed.stdout)


def cleanup_runtime(
    *,
    source_ccb: Path,
    project_root: Path,
    gateway_process: subprocess.Popen[str] | None,
    cloudflared_process: subprocess.Popen[str] | None,
    keep_running: bool,
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {'keep_running': keep_running}
    if keep_running:
        cleanup['gateway_pid'] = gateway_process.pid if gateway_process is not None else None
        cleanup['cloudflared_pid'] = cloudflared_process.pid if cloudflared_process is not None else None
        return cleanup
    if gateway_process is not None and gateway_process.poll() is None:
        gateway_process.terminate()
        try:
            gateway_process.wait(timeout=3)
            cleanup['gateway_returncode'] = gateway_process.returncode
        except subprocess.TimeoutExpired:
            gateway_process.kill()
            gateway_process.wait(timeout=3)
            cleanup['gateway_returncode'] = gateway_process.returncode
            cleanup['gateway_killed'] = True
    if cloudflared_process is not None and cloudflared_process.poll() is None:
        cloudflared_process.terminate()
        try:
            cloudflared_process.wait(timeout=3)
            cleanup['cloudflared_returncode'] = cloudflared_process.returncode
        except subprocess.TimeoutExpired:
            cloudflared_process.kill()
            cloudflared_process.wait(timeout=3)
            cleanup['cloudflared_returncode'] = cloudflared_process.returncode
            cleanup['cloudflared_killed'] = True
    env = source_env(project_root)
    completed = subprocess.run(
        [str(source_ccb), '--project', str(project_root), 'kill', '-f'],
        cwd=str(source_ccb.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    cleanup['kill_returncode'] = completed.returncode
    cleanup['kill_summary'] = parse_key_value_lines(completed.stdout)
    if completed.stderr.strip():
        cleanup['kill_stderr'] = completed.stderr.strip()
    return cleanup


def source_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env['CCB_NO_ATTACH'] = '1'
    if not is_under(project_root, DEFAULT_PROJECT_PARENT):
        env['CCB_SOURCE_ALLOWED_ROOTS'] = str(project_root)
    return env


def allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def is_under(path: Path, root: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        resolved_path = path.absolute()
        resolved_root = root.absolute()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def parse_key_value_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        parsed = parse_key_value_line(line)
        if parsed is not None:
            key, value = parsed
            result[key] = value
    return result


def parse_key_value_line(line: str) -> tuple[str, str] | None:
    if ':' not in line:
        return None
    key, value = line.split(':', 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def parse_json_from_stdout(stdout: str) -> dict[str, Any]:
    start = stdout.find('{')
    if start < 0:
        raise RuntimeError(f'Dart smoke did not print JSON:\n{stdout}')
    return json.loads(stdout[start:])


def summarize_harness(payload: dict[str, Any]) -> dict[str, Any]:
    namespace = payload.get('namespace') if isinstance(payload.get('namespace'), dict) else {}
    selected_agent = payload.get('selected_agent') if isinstance(payload.get('selected_agent'), dict) else {}
    return {
        'mobile_terminal_target_ok': payload.get('mobile_terminal_target_ok'),
        'project_id': (payload.get('project') or {}).get('id') if isinstance(payload.get('project'), dict) else None,
        'namespace_epoch': namespace.get('epoch'),
        'tmux_socket_path': namespace.get('socket_path'),
        'tmux_session_name': namespace.get('session_name'),
        'selected_agent': selected_agent.get('name'),
        'selected_window': selected_agent.get('window'),
        'selected_pane_id': selected_agent.get('pane_id'),
    }


def sanitize_gateway_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        'listen': summary.get('listen'),
        'gateway_url': summary.get('gateway_url'),
        'local_gateway_url': summary.get('local_gateway_url'),
        'route_provider': summary.get('route_provider'),
        'requested_public_url': summary.get('requested_public_url'),
        'project_id': summary.get('project_id'),
        'project_root': summary.get('project_root'),
        'pairing_code_seen': bool(summary.get('pairing_code_seen')),
        'pairing_claim_endpoint': summary.get('pairing_claim_endpoint'),
        'stderr': summary.get('stderr') or '',
    }


def sanitize_cloudflared_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return {
        'mode': summary.get('mode'),
        'origin_url': summary.get('origin_url'),
        'public_url': summary.get('public_url'),
        'config_path': summary.get('config_path'),
        'tunnel_name': summary.get('tunnel_name'),
        'stderr': summary.get('stderr') or '',
    }


if __name__ == '__main__':
    sys.exit(main())
