#!/usr/bin/env python3
"""Run a staged CCB Mobile app compass test against an already-open emulator.

The default mode is intentionally low-disruption:

* no app install or restart;
* no batterystats reset;
* no message send or file upload;
* only reads app/gateway/device state and writes artifacts under /tmp.

Use ``--send-marker`` only for a controlled real-backend send probe in a test
project. This keeps performance/power baselines repeatable without polluting
real CCB projects by accident.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import time
from typing import Any
from urllib import request


DEFAULT_ANDROID_PACKAGE = 'io.ccb.mobile.ccb_mobile'
DEFAULT_GATEWAY_URL = 'http://127.0.0.1:19011'
DEFAULT_ARTIFACT_ROOT = Path('/tmp')
DEFAULT_COMPOSER_TAP = '260,2260'
DEFAULT_SEND_TAP = '1010,2260'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run_summary(args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    runner = CommandRunner(adb=args.adb)
    artifact_dir = make_artifact_dir(args.artifact_root, prefix='ccb-mobile-compass')
    summary = run_compass(args, runner=runner, artifact_dir=artifact_dir)
    status = classify_summary(summary)
    summary['status'] = status
    summary['casebook'] = casebook_coverage(summary, args)
    write_casebook_artifacts(artifact_dir, summary, args)
    write_json(artifact_dir / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status in {'ok', 'warn'} else 1


def run_compass(
    args: argparse.Namespace,
    *,
    runner: 'CommandRunner',
    artifact_dir: Path,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    summary: dict[str, Any] = {
        'schema_version': 1,
        'started_at': started_at,
        'artifact_dir': str(artifact_dir),
        'android_package': args.android_package,
        'gateway_url': args.gateway_url,
        'device_id': args.device_id,
        'phase': 'safe_baseline',
        'expected_project_text': args.expected_project_text,
        'allow_fake_marker': args.allow_fake_marker,
        'require_adb_reverse': args.require_adb_reverse,
        'files': {},
        'steps': [],
    }
    if args.send_marker:
        summary['phase'] = 'safe_baseline_plus_controlled_send'
        summary['send_marker'] = args.send_marker

    collect_device_state(summary, runner, args, artifact_dir)
    collect_gateway_api_samples(summary, args, artifact_dir)
    collect_monitor_samples(summary, runner, args)
    collect_power_and_logs(summary, runner, args, artifact_dir)
    if args.send_marker:
        run_send_probe(summary, runner, args, artifact_dir)
    return summary


class CommandRunner:
    def __init__(self, *, adb: str = 'adb') -> None:
        self.adb = adb

    def run(
        self,
        cmd: list[str],
        *,
        timeout_s: float = 20.0,
        binary: bool = False,
    ) -> tuple[int, bytes | str, bytes | str]:
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_s,
            )
        except Exception as exc:
            if binary:
                return 999, b'', str(exc).encode()
            return 999, '', str(exc)
        if binary:
            return completed.returncode, completed.stdout, completed.stderr
        return (
            completed.returncode,
            completed.stdout.decode('utf-8', 'replace'),
            completed.stderr.decode('utf-8', 'replace'),
        )

    def adb_run(
        self,
        args: list[str],
        *,
        device_id: str | None = None,
        timeout_s: float = 20.0,
        binary: bool = False,
    ) -> tuple[int, bytes | str, bytes | str]:
        cmd = [self.adb]
        if device_id:
            cmd.extend(['-s', device_id])
        cmd.extend(args)
        return self.run(cmd, timeout_s=timeout_s, binary=binary)


def collect_device_state(
    summary: dict[str, Any],
    runner: CommandRunner,
    args: argparse.Namespace,
    artifact_dir: Path,
) -> None:
    rc, out, err = runner.adb_run(['devices', '-l'], device_id=None, timeout_s=10)
    text = as_text(out) + as_text(err)
    save_text(artifact_dir, 'adb_devices.txt', text, summary)
    summary['device_attached'] = adb_devices_has_device(as_text(out))
    summary['adb_devices_rc'] = rc

    rc, out, err = runner.adb_run(
        ['shell', 'dumpsys', 'window'],
        device_id=args.device_id,
        timeout_s=15,
    )
    focus = '\n'.join(
        line
        for line in as_text(out).splitlines()
        if 'mCurrentFocus' in line or 'mFocusedApp' in line
    )
    save_text(artifact_dir, 'window_focus.txt', focus or as_text(out) + as_text(err), summary)
    summary['window_focus'] = focus
    summary['app_foreground'] = args.android_package in focus

    rc, out, err = runner.adb_run(['reverse', '--list'], device_id=args.device_id, timeout_s=10)
    reverse = as_text(out) + as_text(err)
    save_text(artifact_dir, 'adb_reverse.txt', reverse, summary)
    summary['adb_reverse_has_gateway_port'] = gateway_port(args.gateway_url) in reverse

    ui = dump_ui(runner, args, artifact_dir, name='initial_ui')
    summary['ui_markers'] = detect_ui_markers(ui)
    summary['expected_project_visible'] = (
        not args.expected_project_text or args.expected_project_text in ui
    )
    screenshot(runner, args, artifact_dir, name='initial_screen')


def collect_gateway_api_samples(
    summary: dict[str, Any],
    args: argparse.Namespace,
    artifact_dir: Path,
) -> None:
    samples: list[dict[str, Any]] = []
    projects_count = None
    healthy_count = None
    last_payload: dict[str, Any] | None = None
    for _ in range(max(0, args.api_samples)):
        started = time.perf_counter()
        ok = False
        status: int | str | None = None
        try:
            with request.urlopen(args.gateway_url.rstrip('/') + '/v1/projects', timeout=5) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
                last_payload = payload
                projects = list(payload.get('projects') or [])
                projects_count = len(projects)
                healthy_count = sum(
                    1 for project in projects if project.get('health') == 'healthy'
                )
                ok = True
        except Exception as exc:
            status = repr(exc)
        samples.append(
            {
                'ok': ok,
                'status': status,
                'duration_ms': round((time.perf_counter() - started) * 1000.0, 1),
            }
        )
        if args.api_sample_interval_s > 0:
            time.sleep(args.api_sample_interval_s)
    summary['projects_api'] = summarize_api_samples(samples)
    summary['projects_count'] = projects_count
    summary['healthy_projects_count'] = healthy_count
    if last_payload is not None:
        save_json(artifact_dir, 'projects.json', last_payload, summary)


def collect_monitor_samples(
    summary: dict[str, Any],
    runner: CommandRunner,
    args: argparse.Namespace,
) -> None:
    samples: list[dict[str, Any]] = []
    sample_count = monitor_sample_count(args.duration_s, args.sample_interval_s)
    for index in range(sample_count):
        elapsed = index * args.sample_interval_s
        rc, top, err = runner.adb_run(
            ['shell', 'top', '-b', '-n', '1'],
            device_id=args.device_id,
            timeout_s=15,
        )
        rc, meminfo, memerr = runner.adb_run(
            ['shell', 'dumpsys', 'meminfo', args.android_package],
            device_id=args.device_id,
            timeout_s=20,
        )
        samples.append(
            {
                'elapsed_s': elapsed,
                'top_line': extract_app_top_line(as_text(top), args.android_package),
                **parse_meminfo(as_text(meminfo) + as_text(memerr)),
            }
        )
        if index < sample_count - 1 and args.sample_interval_s > 0:
            time.sleep(args.sample_interval_s)
    summary['monitor_samples'] = samples
    summary['memory'] = summarize_memory(samples)


def collect_power_and_logs(
    summary: dict[str, Any],
    runner: CommandRunner,
    args: argparse.Namespace,
    artifact_dir: Path,
) -> None:
    rc, power, err = runner.adb_run(
        ['shell', 'dumpsys', 'power'],
        device_id=args.device_id,
        timeout_s=20,
    )
    power_text = as_text(power) + as_text(err)
    save_text(artifact_dir, 'power.txt', power_text, summary)
    summary['power'] = parse_power_summary(power_text)

    rc, batt, err = runner.adb_run(
        ['shell', 'dumpsys', 'batterystats', '--charged', args.android_package],
        device_id=args.device_id,
        timeout_s=35,
    )
    batt_text = as_text(batt) + as_text(err)
    save_text(artifact_dir, 'batterystats_package.txt', batt_text, summary)
    summary['batterystats_excerpt'] = battery_excerpt(batt_text)

    rc, gfx, err = runner.adb_run(
        ['shell', 'dumpsys', 'gfxinfo', args.android_package],
        device_id=args.device_id,
        timeout_s=25,
    )
    gfx_text = as_text(gfx) + as_text(err)
    save_text(artifact_dir, 'gfxinfo.txt', gfx_text, summary)
    summary['gfxinfo'] = parse_gfxinfo(gfx_text)

    rc, logcat, err = runner.adb_run(
        ['logcat', '-d', '-t', str(args.logcat_tail)],
        device_id=args.device_id,
        timeout_s=35,
    )
    log_text = filter_interesting_logcat(as_text(logcat) + as_text(err))
    save_text(artifact_dir, 'logcat_interesting.txt', log_text[-80000:], summary)
    summary['logcat'] = summarize_logcat(log_text)


def run_send_probe(
    summary: dict[str, Any],
    runner: CommandRunner,
    args: argparse.Namespace,
    artifact_dir: Path,
) -> None:
    composer_x, composer_y = parse_xy(args.composer_tap)
    send_x, send_y = parse_xy(args.send_tap)
    started = time.perf_counter()
    runner.adb_run(
        ['shell', 'input', 'tap', str(composer_x), str(composer_y)],
        device_id=args.device_id,
        timeout_s=5,
    )
    time.sleep(0.4)
    runner.adb_run(
        ['shell', 'input', 'text', adb_input_text(args.send_marker)],
        device_id=args.device_id,
        timeout_s=10,
    )
    time.sleep(0.4)
    runner.adb_run(
        ['shell', 'input', 'tap', str(send_x), str(send_y)],
        device_id=args.device_id,
        timeout_s=5,
    )
    own_visible_ms = None
    marker_count = 0
    last_ui = ''
    for index in range(max(1, args.send_poll_count)):
        ui = dump_ui(runner, args, artifact_dir, name=f'send_poll_{index:02d}')
        last_ui = ui
        marker_count = ui.count(args.send_marker)
        if own_visible_ms is None and marker_count > 0:
            own_visible_ms = round((time.perf_counter() - started) * 1000.0, 1)
            screenshot(runner, args, artifact_dir, name='send_own_visible')
        if marker_count >= 2:
            break
        time.sleep(args.send_poll_interval_s)
    screenshot(runner, args, artifact_dir, name='send_after')
    save_text(artifact_dir, 'send_last_ui.xml', last_ui, summary)
    summary['send_probe'] = {
        'marker': args.send_marker,
        'own_message_visible_ms': own_visible_ms,
        'marker_count': marker_count,
        'reply_marker_visible': marker_count >= 2,
        'ui_markers': detect_ui_markers(last_ui),
    }


def dump_ui(
    runner: CommandRunner,
    args: argparse.Namespace,
    artifact_dir: Path,
    *,
    name: str,
) -> str:
    runner.adb_run(
        ['shell', 'uiautomator', 'dump', '/sdcard/ccb_window.xml'],
        device_id=args.device_id,
        timeout_s=20,
    )
    rc, out, err = runner.adb_run(
        ['exec-out', 'cat', '/sdcard/ccb_window.xml'],
        device_id=args.device_id,
        timeout_s=20,
        binary=True,
    )
    data = out if isinstance(out, bytes) else str(out).encode()
    text = data.decode('utf-8', 'replace') if data else as_text(err)
    path = artifact_dir / f'{name}.xml'
    path.write_text(text, encoding='utf-8')
    return text


def screenshot(
    runner: CommandRunner,
    args: argparse.Namespace,
    artifact_dir: Path,
    *,
    name: str,
) -> None:
    rc, out, err = runner.adb_run(
        ['exec-out', 'screencap', '-p'],
        device_id=args.device_id,
        timeout_s=20,
        binary=True,
    )
    if rc == 0 and isinstance(out, bytes) and out:
        (artifact_dir / f'{name}.png').write_bytes(out)


def parse_meminfo(text: str) -> dict[str, int | None]:
    total_pss = None
    total_rss = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('TOTAL RSS:'):
            numbers = re.findall(r'\d+', stripped)
            if numbers:
                total_rss = int(numbers[0])
        elif stripped.startswith('TOTAL'):
            numbers = re.findall(r'\d+', stripped)
            if numbers:
                total_pss = int(numbers[0])
                if total_rss is None and len(numbers) >= 4:
                    total_rss = int(numbers[-1])
    return {'total_pss_kb': total_pss, 'total_rss_kb': total_rss}


def extract_app_top_line(text: str, package_name: str) -> str:
    for line in text.splitlines():
        if package_name in line:
            return line.strip()
    return ''


def summarize_api_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(sample['duration_ms']) for sample in samples if sample.get('ok')]
    summary: dict[str, Any] = {
        'samples': samples,
        'ok_count': len(durations),
        'fail_count': len(samples) - len(durations),
    }
    if durations:
        summary.update(
            {
                'p50_ms': round(statistics.median(durations), 1),
                'max_ms': round(max(durations), 1),
            }
        )
    return summary


def summarize_memory(samples: list[dict[str, Any]]) -> dict[str, Any]:
    pss_values = [
        int(sample['total_pss_kb'])
        for sample in samples
        if isinstance(sample.get('total_pss_kb'), int)
    ]
    if not pss_values:
        return {'samples': 0}
    return {
        'samples': len(pss_values),
        'pss_kb_min': min(pss_values),
        'pss_kb_max': max(pss_values),
        'pss_kb_delta': pss_values[-1] - pss_values[0],
        'pss_growth_ratio': round((pss_values[-1] - pss_values[0]) / max(pss_values[0], 1), 4),
    }


def parse_power_summary(text: str) -> dict[str, Any]:
    return {
        'wake_locks': find_first(text, r'Wake Locks:.*'),
        'wake_lock_summary': find_first(text, r'\s*mWakeLockSummary=.*'),
        'holding_wakelock_suspend_blocker': find_first(
            text,
            r'\s*mHoldingWakeLockSuspendBlocker=.*',
        ),
        'wakefulness': find_first(text, r'\s*mWakefulness=.*'),
    }


def parse_gfxinfo(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('Total frames rendered:'):
            result['total_frames_rendered'] = stripped
        elif stripped.startswith('Janky frames'):
            result['janky_frames'] = stripped
    return result


def battery_excerpt(text: str) -> list[str]:
    pattern = re.compile(
        r'wake|Wake|Estimated power|UID|cpu=|wifi=|Mobile|Network|Sensor|Job|Sync',
        re.I,
    )
    return [line.strip() for line in text.splitlines() if pattern.search(line)][:40]


def filter_interesting_logcat(text: str) -> str:
    pattern = re.compile(
        r'ccb_mobile|FATAL|ANR|Exception|Choreographer|Skipped|OutOfMemory|InputDispatcher',
        re.I,
    )
    return '\n'.join(line for line in text.splitlines() if pattern.search(line))


def summarize_logcat(text: str) -> dict[str, Any]:
    return {
        'fatal_anr_oom': bool(re.search(r'FATAL|ANR|OutOfMemory', text, re.I)),
        'skipped_frames_count': len(re.findall(r'Skipped \d+ frames', text)),
        'tail': text.splitlines()[-20:],
    }


def detect_ui_markers(ui_xml: str) -> dict[str, Any]:
    lowered = ui_xml.lower()
    return {
        'contains_fake_marker': 'fake[' in lowered or 'demo' in lowered,
        'contains_test_project': 'test_ccb2' in ui_xml,
        'contains_ccb_mobile_project': 'ccb_mobile' in ui_xml,
        'contains_composer': 'Message ' in ui_xml or 'Message' in ui_xml,
    }


def classify_summary(summary: dict[str, Any]) -> str:
    if not summary.get('device_attached') or not summary.get('app_foreground'):
        return 'blocked'
    if summary.get('require_adb_reverse') and not summary.get('adb_reverse_has_gateway_port'):
        return 'blocked'
    if not summary.get('expected_project_visible', True):
        return 'blocked'
    ui_markers = _as_dict(summary.get('ui_markers'))
    if not summary.get('allow_fake_marker') and ui_markers.get('contains_fake_marker'):
        return 'fail'
    if _as_dict(summary.get('logcat')).get('fatal_anr_oom'):
        return 'fail'
    memory = _as_dict(summary.get('memory'))
    growth = float(memory.get('pss_growth_ratio') or 0.0)
    if growth > 0.3:
        return 'fail'
    projects_api = _as_dict(summary.get('projects_api'))
    if int(projects_api.get('fail_count') or 0) >= 2:
        return 'blocked'
    send_probe = summary.get('send_probe')
    if isinstance(send_probe, dict) and send_probe.get('own_message_visible_ms') is None:
        return 'blocked'
    if isinstance(send_probe, dict) and not send_probe.get('reply_marker_visible'):
        return 'warn'
    return 'ok'


def monitor_sample_count(duration_s: int, interval_s: int) -> int:
    if duration_s <= 0:
        return 1
    if interval_s <= 0:
        return 1
    return max(1, int(duration_s // interval_s) + 1)


def adb_devices_has_device(text: str) -> bool:
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            return True
    return False


def gateway_port(gateway_url: str) -> str:
    match = re.search(r':(\d+)(?:/|$)', gateway_url)
    return f'tcp:{match.group(1)}' if match else ''


def find_first(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(0).strip() if match else None


def parse_xy(value: str) -> tuple[int, int]:
    left, right = value.split(',', 1)
    return int(left.strip()), int(right.strip())


def adb_input_text(value: str) -> str:
    return value.replace('%', '%25').replace(' ', '%s')


def as_text(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return value


def save_text(
    artifact_dir: Path,
    name: str,
    text: str,
    summary: dict[str, Any],
) -> None:
    path = artifact_dir / name
    path.write_text(text, encoding='utf-8')
    _as_dict(summary.setdefault('files', {}))[name] = str(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')


def save_json(
    artifact_dir: Path,
    name: str,
    value: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    path = artifact_dir / name
    write_json(path, value)
    _as_dict(summary.setdefault('files', {}))[name] = str(path)


def write_casebook_artifacts(
    artifact_dir: Path,
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    mobile_root = Path(__file__).resolve().parents[1]
    environment: dict[str, Any] = {
        'schema_version': 1,
        'app_root': str(mobile_root),
        'app_commit': git_head(mobile_root),
        'app_dirty': git_status_short(mobile_root),
        'source_root': str(args.source_root.expanduser().resolve()) if args.source_root else None,
        'source_commit': git_head(args.source_root.expanduser().resolve()) if args.source_root else None,
        'source_dirty': git_status_short(args.source_root.expanduser().resolve()) if args.source_root else None,
        'android_package': args.android_package,
        'device_id': args.device_id,
        'gateway_url': args.gateway_url,
        'expected_project_text': args.expected_project_text,
        'adb_reverse_has_gateway_port': summary.get('adb_reverse_has_gateway_port'),
        'app_foreground': summary.get('app_foreground'),
        'window_focus': summary.get('window_focus'),
    }
    save_json(artifact_dir, 'environment.json', environment, summary)

    timings = {
        'schema_version': 1,
        'projects_api': _as_dict(summary.get('projects_api')),
        'send_probe': summary.get('send_probe'),
    }
    save_json(artifact_dir, 'timings.json', timings, summary)

    request_counts = {
        'schema_version': 1,
        'scope': 'host_compass_projects_api_samples_only',
        'note': (
            'This compass run counts host-side /v1/projects samples made by '
            'the test tool. Full app endpoint request-rate evidence still '
            'requires gateway access-log parsing or instrumentation.'
        ),
        'gateway_url': args.gateway_url,
        'projects_api': _as_dict(summary.get('projects_api')),
    }
    save_json(artifact_dir, 'request-counts.json', request_counts, summary)

    memory = {
        'schema_version': 1,
        'summary': _as_dict(summary.get('memory')),
        'samples': summary.get('monitor_samples') or [],
    }
    save_json(artifact_dir, 'memory.json', memory, summary)

    power_summary = {
        'schema_version': 1,
        'summary': _as_dict(summary.get('power')),
        'batterystats_excerpt': summary.get('batterystats_excerpt') or [],
    }
    save_json(artifact_dir, 'power-summary.json', power_summary, summary)

    save_json(artifact_dir, 'casebook-summary.json', _as_dict(summary.get('casebook')), summary)


def casebook_coverage(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    cases = ['C0.1']
    if args.duration_s > 0:
        cases.append('C10.1-debug-preflight')
    if args.send_marker:
        cases.append('C3.1-controlled-send-probe')
    return {
        'schema_version': 1,
        'case_ids': cases,
        'status': summary.get('status'),
        'first_failed_gate': first_failed_gate(summary),
        'owner': failure_owner(summary),
        'fake_or_demo_used': bool(_as_dict(summary.get('ui_markers')).get('contains_fake_marker')),
        'real_pane_verified': None,
        'ccb_req_id_seen': None,
        'blind_polling_seen': None,
        'notes': [
            'Compass evidence is low-disruption environment/performance evidence.',
            'It does not prove selected-agent pane identity or real provider reply unless paired with native-pane smoke evidence.',
        ],
    }


def first_failed_gate(summary: dict[str, Any]) -> str | None:
    if not summary.get('device_attached'):
        return 'device not attached'
    if not summary.get('app_foreground'):
        return 'app not foreground'
    if summary.get('require_adb_reverse') and not summary.get('adb_reverse_has_gateway_port'):
        return 'adb reverse missing gateway port'
    if not summary.get('expected_project_visible', True):
        return 'expected project not visible'
    if _as_dict(summary.get('ui_markers')).get('contains_fake_marker'):
        return 'fake/demo marker visible'
    if _as_dict(summary.get('logcat')).get('fatal_anr_oom'):
        return 'fatal/anr/oom in logcat'
    if float(_as_dict(summary.get('memory')).get('pss_growth_ratio') or 0.0) > 0.3:
        return 'memory growth over debug threshold'
    if int(_as_dict(summary.get('projects_api')).get('fail_count') or 0) >= 2:
        return 'projects api repeated failure'
    send_probe = summary.get('send_probe')
    if isinstance(send_probe, dict) and send_probe.get('own_message_visible_ms') is None:
        return 'controlled send own message not visible'
    if isinstance(send_probe, dict) and not send_probe.get('reply_marker_visible'):
        return 'controlled send reply marker not visible'
    return None


def failure_owner(summary: dict[str, Any]) -> str | None:
    failed = first_failed_gate(summary)
    if failed is None:
        return None
    if failed in {'device not attached', 'app not foreground', 'adb reverse missing gateway port'}:
        return 'environment'
    if failed in {'expected project not visible', 'fake/demo marker visible'}:
        return 'app-ui'
    if failed == 'projects api repeated failure':
        return 'source-gateway'
    if failed in {
        'controlled send own message not visible',
        'controlled send reply marker not visible',
    }:
        return 'app-transport'
    if failed in {'fatal/anr/oom in logcat', 'memory growth over debug threshold'}:
        return 'app-ui'
    return 'environment'


def git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_status_short(root: Path) -> str:
    try:
        completed = subprocess.run(
            ['git', 'status', '--short'],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception as exc:
        return f'error: {exc}'
    if completed.returncode != 0:
        return completed.stderr.strip()
    return completed.stdout.strip()


def make_artifact_dir(root: Path, *, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    path = root.expanduser().resolve() / f'{prefix}-{stamp}'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def dry_run_summary(args: argparse.Namespace) -> dict[str, Any]:
    actions = [
        'read adb devices and focused window',
        'read adb reverse and require gateway port unless disabled',
        'dump current UI and screenshot',
        f'call {args.gateway_url.rstrip()}/v1/projects {args.api_samples} time(s)',
        (
            f'collect top/meminfo every {args.sample_interval_s}s '
            f'for {args.duration_s}s'
        ),
        'read dumpsys power, package batterystats, gfxinfo, and logcat tail',
    ]
    if args.send_marker:
        actions.append(
            'perform one controlled send probe using configured tap coordinates',
        )
    return {
        'dry_run': True,
        'android_package': args.android_package,
        'device_id': args.device_id,
        'gateway_url': args.gateway_url,
        'artifact_root': str(args.artifact_root),
        'expected_project_text': args.expected_project_text,
        'allow_fake_marker': args.allow_fake_marker,
        'require_adb_reverse': args.require_adb_reverse,
        'send_marker': args.send_marker,
        'actions': actions,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run low-disruption CCB Mobile app compass/performance checks.',
    )
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--device-id', default=None)
    parser.add_argument('--android-package', default=DEFAULT_ANDROID_PACKAGE)
    parser.add_argument('--gateway-url', default=DEFAULT_GATEWAY_URL)
    parser.add_argument(
        '--source-root',
        type=Path,
        default=None,
        help='optional CCB source worktree root to include in environment.json',
    )
    parser.add_argument('--artifact-root', type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        '--expected-project-text',
        default='test_ccb2',
        help='text that must be visible in the UI dump for real-project tests',
    )
    parser.add_argument(
        '--allow-fake-marker',
        action='store_true',
        help='allow fake/demo markers in the UI dump; off by default',
    )
    parser.add_argument(
        '--no-require-adb-reverse',
        dest='require_adb_reverse',
        action='store_false',
        help='do not require adb reverse to contain the gateway port',
    )
    parser.set_defaults(require_adb_reverse=True)
    parser.add_argument('--duration-s', type=int, default=180)
    parser.add_argument('--sample-interval-s', type=int, default=30)
    parser.add_argument('--api-samples', type=int, default=5)
    parser.add_argument('--api-sample-interval-s', type=float, default=2.0)
    parser.add_argument('--logcat-tail', type=int, default=900)
    parser.add_argument(
        '--send-marker',
        default=None,
        help='optional marker text for one controlled real-backend send probe',
    )
    parser.add_argument('--composer-tap', default=DEFAULT_COMPOSER_TAP)
    parser.add_argument('--send-tap', default=DEFAULT_SEND_TAP)
    parser.add_argument('--send-poll-count', type=int, default=45)
    parser.add_argument('--send-poll-interval-s', type=float, default=1.0)
    return parser.parse_args(argv)


if __name__ == '__main__':
    raise SystemExit(main())
