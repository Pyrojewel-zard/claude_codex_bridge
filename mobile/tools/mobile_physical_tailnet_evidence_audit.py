#!/usr/bin/env python3
"""Audit a physical Tailnet CCB Mobile evidence packet."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


REQUIRED_JSON_FILES = [
    'summary.json',
    'preflight.json',
    'environment.json',
    'projects.json',
    'gateway-health.json',
    'route-diagnostics.json',
    'timings.json',
    'request-counts.json',
    'memory.json',
    'transfer-hashes.json',
    'recovery-events.json',
]
REQUIRED_TEXT_FILES = [
    'power.txt',
    'logcat.txt',
    'gateway.log.tail',
    'source-project.log.tail',
]
REQUIRED_DIRS = [
    'phone-screenshots',
    'phone-ui',
]
ACCEPTED_STATUSES = {'ok', 'passed', 'pass'}
REQUIRED_CASE_IDS = {'T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6'}
REQUIREMENTS_VERSION = 'physical-tailnet-stress-v2'
BAD_TRUE_MARKERS = {
    'fake_or_demo_used',
    'fake_or_demo',
    'ccb_req_id_seen',
    'blind_polling_seen',
    'input_replayed',
    'wrong_project_seen',
    'wrong_agent_seen',
}
BAD_TEXT_MARKERS = [
    'CCB_REQ_ID',
    'FATAL EXCEPTION',
    'OutOfMemoryError',
    ' ANR ',
]
OWN_MESSAGE_LATENCY_KEYS = {
    'prompt_to_visible_own_message_ms',
    'own_message_visible_ms',
    'visible_own_message_ms',
    'send_to_visible_ms',
}
PROVIDER_REPLY_LATENCY_KEYS = {
    'prompt_to_provider_reply_ms',
    'provider_reply_ms',
    'reply_ms',
    'reply_visible_ms',
    'visible_reply_ms',
    'send_to_reply_ms',
}
TAILNET_PATH_KEYS = {
    'tailnet_path',
    'tailscale_path',
    'connection_path',
    'route_path',
}
RECOVERY_EVENT_KEYS = {'events', 'recovery_events', 'steps'}
MAX_DEBUG_PSS_GROWTH_RATIO = 0.3
MIN_TURN_TIMING_SAMPLES = 5
MIN_RECOVERY_EVENTS = 4


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit_physical_tailnet_evidence(args.artifact_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.json_out is not None:
        args.json_out.write_text(text + '\n', encoding='utf-8')
    return 0 if result['status'] == 'ok' else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Audit a physical-device Tailnet evidence artifact directory.',
    )
    parser.add_argument('artifact_dir', type=Path)
    parser.add_argument('--json-out', type=Path)
    return parser.parse_args(argv)


def audit_physical_tailnet_evidence(artifact_dir: Path) -> dict[str, Any]:
    artifact_dir = artifact_dir.resolve()
    missing: list[str] = []
    invalid_json: list[str] = []
    semantic_issues: list[str] = []
    loaded_json: dict[str, dict[str, Any]] = {}

    if not artifact_dir.exists():
        return {
            'schema_version': 1,
            'requirements_version': REQUIREMENTS_VERSION,
            'generated_at': utc_now(),
            'status': 'blocked',
            'artifact_dir': str(artifact_dir),
            'missing': [f'artifact directory does not exist: {artifact_dir}'],
            'invalid_json': [],
            'semantic_issues': [],
            'files': {},
        }

    file_statuses: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_JSON_FILES:
        path = artifact_dir / name
        status = file_status(path)
        file_statuses[name] = status
        if not status['exists']:
            missing.append(name)
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            invalid_json.append(f'{name}: {exc}')
            continue
        if not isinstance(payload, dict):
            invalid_json.append(f'{name}: JSON payload is not an object')
            continue
        loaded_json[name] = payload
        semantic_issues.extend(json_semantic_issues(name, payload))

    for name in REQUIRED_TEXT_FILES:
        path = artifact_dir / name
        status = file_status(path)
        file_statuses[name] = status
        if not status['exists']:
            missing.append(name)
            continue
        semantic_issues.extend(
            text_semantic_issues(
                name,
                path.read_text(encoding='utf-8', errors='replace'),
            )
        )

    for name in REQUIRED_DIRS:
        path = artifact_dir / name
        status = {
            'exists': path.exists(),
            'is_dir': path.is_dir(),
            'entry_count': len(list(path.iterdir())) if path.exists() and path.is_dir() else 0,
        }
        file_statuses[name] = status
        if not status['exists'] or not status['is_dir']:
            missing.append(name)
        elif status['entry_count'] == 0:
            semantic_issues.append(f'{name}: directory is empty')

    semantic_issues.extend(packet_semantic_issues(loaded_json, artifact_dir=artifact_dir))
    status = classify_status(missing, invalid_json, semantic_issues, loaded_json)
    return {
        'schema_version': 1,
        'requirements_version': REQUIREMENTS_VERSION,
        'generated_at': utc_now(),
        'status': status,
        'artifact_dir': str(artifact_dir),
        'missing': missing,
        'invalid_json': invalid_json,
        'semantic_issues': semantic_issues,
        'files': file_statuses,
    }


def file_status(path: Path) -> dict[str, Any]:
    return {
        'exists': path.exists(),
        'is_file': path.is_file(),
        'size_bytes': path.stat().st_size if path.exists() and path.is_file() else 0,
    }


def json_semantic_issues(name: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    status = str(payload.get('status') or '').strip()
    if status and status not in ACCEPTED_STATUSES:
        issues.append(f'{name}: unexpected status {status!r}')
    for marker in BAD_TRUE_MARKERS:
        for value in find_key_values(payload, marker):
            if value is True:
                issues.append(f'{name}: {marker} is True')
    return issues


def packet_semantic_issues(
    loaded_json: dict[str, dict[str, Any]],
    *,
    artifact_dir: Path,
) -> list[str]:
    issues: list[str] = []
    summary = loaded_json.get('summary.json')
    if summary is not None:
        issues.extend(summary_semantic_issues(summary, artifact_dir=artifact_dir))
    preflight = loaded_json.get('preflight.json')
    if preflight is not None and preflight.get('status') != 'ok':
        issues.append('preflight.json: preflight did not pass')
    environment = loaded_json.get('environment.json')
    if environment is not None:
        route_provider_values = [
            str(value)
            for key in ('route_provider', 'routeProvider')
            for value in find_key_values(environment, key)
        ]
        if route_provider_values and 'tailnet' not in route_provider_values:
            issues.append('environment.json: route provider is not tailnet')
        emulator_values = find_key_values(environment, 'is_emulator')
        if True in emulator_values:
            issues.append('environment.json: selected Android device is an emulator')
    transfer_hashes = loaded_json.get('transfer-hashes.json')
    if transfer_hashes is not None:
        if False in find_key_values(transfer_hashes, 'hash_match'):
            issues.append('transfer-hashes.json: hash_match is False')
        if False in find_key_values(transfer_hashes, 'sha256_match'):
            issues.append('transfer-hashes.json: sha256_match is False')
    timings = loaded_json.get('timings.json')
    if timings is not None:
        issues.extend(timings_semantic_issues(timings))
    request_counts = loaded_json.get('request-counts.json')
    if request_counts is not None:
        issues.extend(request_counts_semantic_issues(request_counts))
    memory = loaded_json.get('memory.json')
    if memory is not None:
        issues.extend(memory_semantic_issues(memory))
    recovery_events = loaded_json.get('recovery-events.json')
    if recovery_events is not None:
        issues.extend(recovery_events_semantic_issues(recovery_events))
    return issues


def timings_semantic_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    turns = payload.get('turns')
    if not isinstance(turns, list):
        return ['timings.json: turns must be a list']
    if len(turns) < MIN_TURN_TIMING_SAMPLES:
        issues.append(
            f'timings.json: requires at least {MIN_TURN_TIMING_SAMPLES} turn timing samples'
        )
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            issues.append(f'timings.json: turn {index} must be an object')
            continue
        if not has_positive_number_for_keys(turn, OWN_MESSAGE_LATENCY_KEYS):
            issues.append(f'timings.json: turn {index} missing positive own-message latency')
        if not has_positive_number_for_keys(turn, PROVIDER_REPLY_LATENCY_KEYS):
            issues.append(f'timings.json: turn {index} missing positive provider-reply latency')
        if not has_tailnet_path(turn):
            issues.append(f'timings.json: turn {index} missing direct/DERP/relay path')
    return issues


def request_counts_semantic_issues(payload: dict[str, Any]) -> list[str]:
    values = find_key_values(payload, 'blind_polling_seen')
    if False not in values:
        return ['request-counts.json: blind_polling_seen must be explicitly false']
    return []


def memory_semantic_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    ratios = numeric_key_values(payload, 'pss_growth_ratio')
    if not ratios:
        issues.append('memory.json: missing pss_growth_ratio')
    elif any(ratio > MAX_DEBUG_PSS_GROWTH_RATIO for ratio in ratios):
        issues.append('memory.json: pss_growth_ratio exceeds debug threshold')
    if memory_sample_count(payload) < 2:
        issues.append('memory.json: requires at least 2 memory samples')
    return issues


def recovery_events_semantic_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    values = find_key_values(payload, 'input_replayed')
    if False not in values:
        issues.append('recovery-events.json: input_replayed must be explicitly false')
    if recovery_event_count(payload) < MIN_RECOVERY_EVENTS:
        issues.append(
            f'recovery-events.json: requires at least {MIN_RECOVERY_EVENTS} recovery events'
        )
    return issues


def summary_semantic_issues(
    summary: dict[str, Any],
    *,
    artifact_dir: Path | None = None,
) -> list[str]:
    issues: list[str] = []
    cases = normalize_summary_cases(summary.get('cases'))
    if cases is None:
        return ['summary.json: cases must be an object or list']
    for case_id in sorted(REQUIRED_CASE_IDS):
        case = cases.get(case_id)
        if case is None:
            issues.append(f'summary.json: missing case {case_id}')
            continue
        status = str(case.get('status') or '').strip()
        if status not in ACCEPTED_STATUSES:
            issues.append(f'summary.json: {case_id} status is {status!r}')
            continue
        evidence = case.get('evidence')
        if not isinstance(evidence, list) or not any(str(item).strip() for item in evidence):
            issues.append(f'summary.json: {case_id} has accepted status without evidence')
            continue
        if artifact_dir is not None:
            issues.extend(case_evidence_path_issues(artifact_dir, case_id, evidence))
    return issues


def case_evidence_path_issues(
    artifact_dir: Path,
    case_id: str,
    evidence: list[object],
) -> list[str]:
    issues: list[str] = []
    root = artifact_dir.resolve()
    for value in evidence:
        item = str(value).strip()
        if not item:
            continue
        path = Path(item)
        if path.is_absolute():
            issues.append(f'summary.json: {case_id} evidence path is absolute: {item}')
            continue
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root):
            issues.append(f'summary.json: {case_id} evidence path escapes artifact dir: {item}')
            continue
        if not resolved.exists():
            issues.append(f'summary.json: {case_id} evidence path does not exist: {item}')
            continue
        if resolved.is_file() and resolved.stat().st_size == 0:
            issues.append(f'summary.json: {case_id} evidence file is empty: {item}')
            continue
        if resolved.is_dir() and not any(resolved.iterdir()):
            issues.append(f'summary.json: {case_id} evidence directory is empty: {item}')
            continue
        if not resolved.is_file() and not resolved.is_dir():
            issues.append(
                f'summary.json: {case_id} evidence path is neither file nor directory: {item}'
            )
    return issues


def normalize_summary_cases(value: object) -> dict[str, dict[str, Any]] | None:
    if isinstance(value, dict):
        cases: dict[str, dict[str, Any]] = {}
        for case_id, case_value in value.items():
            if isinstance(case_value, dict):
                cases[str(case_id)] = case_value
            else:
                cases[str(case_id)] = {'status': case_value}
        return cases
    if isinstance(value, list):
        cases = {}
        for case_value in value:
            if not isinstance(case_value, dict):
                return None
            raw_case_id = (
                case_value.get('case_id')
                or case_value.get('caseId')
                or case_value.get('id')
            )
            if raw_case_id is None:
                return None
            cases[str(raw_case_id)] = case_value
        return cases
    return None


def text_semantic_issues(name: str, text: str) -> list[str]:
    issues: list[str] = []
    for marker in BAD_TEXT_MARKERS:
        if marker in text:
            issues.append(f'{name}: contains {marker.strip()}')
    if name == 'power.txt':
        if not (
            re.search(r'Wake Locks:\s*size=0\b', text)
            or re.search(r'mWakeLockSummary=0x0\b', text)
        ):
            issues.append('power.txt: idle wake lock zero evidence missing')
        if re.search(r'Wake Locks:\s*size=(?!0\b)\d+', text):
            issues.append('power.txt: wake locks are not idle-zero')
        if re.search(r'mWakeLockSummary=(?!0x0\b)\S+', text):
            issues.append('power.txt: wake lock summary is not idle-zero')
    return issues


def classify_status(
    missing: list[str],
    invalid_json: list[str],
    semantic_issues: list[str],
    loaded_json: dict[str, dict[str, Any]],
) -> str:
    preflight = loaded_json.get('preflight.json')
    if preflight is not None and preflight.get('status') != 'ok':
        return 'blocked'
    if missing or invalid_json or semantic_issues:
        return 'fail'
    return 'ok'


def find_key_values(value: object, key: str) -> list[object]:
    matches: list[object] = []
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key:
                matches.append(item_value)
            matches.extend(find_key_values(item_value, key))
    elif isinstance(value, list):
        for item in value:
            matches.extend(find_key_values(item, key))
    return matches


def has_positive_number_for_keys(payload: dict[str, Any], keys: set[str]) -> bool:
    for key in keys:
        if any(is_positive_number(value) for value in find_key_values(payload, key)):
            return True
    return False


def numeric_key_values(payload: dict[str, Any], key: str) -> list[float]:
    values: list[float] = []
    for value in find_key_values(payload, key):
        number = number_value(value)
        if number is not None:
            values.append(number)
    return values


def is_positive_number(value: object) -> bool:
    number = number_value(value)
    return number is not None and number > 0


def number_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def has_tailnet_path(payload: dict[str, Any]) -> bool:
    for key in TAILNET_PATH_KEYS:
        for value in find_key_values(payload, key):
            if is_tailnet_path_value(value):
                return True
    return False


def is_tailnet_path_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return any(marker in normalized for marker in ('direct', 'derp', 'relay'))


def memory_sample_count(payload: dict[str, Any]) -> int:
    sample_counts = [int(value) for value in numeric_key_values(payload, 'sample_count')]
    sample_counts.extend(int(value) for value in numeric_key_values(payload, 'samples_count'))
    for value in find_key_values(payload, 'samples'):
        if isinstance(value, list):
            sample_counts.append(len(value))
        elif isinstance(value, int) and not isinstance(value, bool):
            sample_counts.append(value)
    return max(sample_counts, default=0)


def recovery_event_count(payload: dict[str, Any]) -> int:
    counts: list[int] = []
    for key in RECOVERY_EVENT_KEYS:
        for value in find_key_values(payload, key):
            if isinstance(value, list):
                counts.append(len(value))
    return max(counts, default=0)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
