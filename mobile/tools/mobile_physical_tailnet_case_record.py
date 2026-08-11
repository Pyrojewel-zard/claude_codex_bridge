#!/usr/bin/env python3
"""Record a physical Tailnet validation case result in summary.json."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import mobile_physical_tailnet_evidence_init as evidence_init


ACCEPTED_STATUSES = {'ok', 'passed', 'pass'}
NON_ACCEPTED_STATUSES = {'pending', 'blocked', 'fail', 'failed'}
VALID_STATUSES = ACCEPTED_STATUSES | NON_ACCEPTED_STATUSES
CASE_IDS = {case_id for case_id, _ in evidence_init.CASE_DEFINITIONS}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = record_case(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Update a physical Tailnet evidence packet summary case result.',
    )
    parser.add_argument('artifact_dir', type=Path)
    parser.add_argument('case_id', choices=sorted(CASE_IDS))
    parser.add_argument('--status', required=True, choices=sorted(VALID_STATUSES))
    parser.add_argument(
        '--evidence',
        action='append',
        default=[],
        help='evidence path relative to artifact dir, repeatable',
    )
    parser.add_argument('--notes', default='', help='replace notes for this case')
    parser.add_argument(
        '--allow-missing-evidence',
        action='store_true',
        help='allow accepted status without evidence paths; avoid for final acceptance',
    )
    return parser.parse_args(argv)


def record_case(args: argparse.Namespace) -> dict[str, Any]:
    artifact_dir = args.artifact_dir.resolve()
    summary_path = artifact_dir / 'summary.json'
    if not summary_path.exists():
        evidence_init.init_evidence_dir(artifact_dir)
    summary = load_summary(summary_path)
    cases = ensure_cases(summary)
    status = str(args.status)
    evidence = normalize_evidence(args.evidence)
    if status in ACCEPTED_STATUSES and not evidence and not args.allow_missing_evidence:
        raise SystemExit(
            f'{args.case_id} cannot be marked {status!r} without at least one --evidence path',
        )
    if status in ACCEPTED_STATUSES:
        evidence_issues = evidence_path_issues(
            artifact_dir,
            evidence,
            require_exists=not args.allow_missing_evidence,
        )
        if evidence_issues:
            raise SystemExit('; '.join(evidence_issues))
    case = cases[args.case_id]
    case['status'] = status
    case['evidence'] = evidence
    case['notes'] = args.notes
    case['updated_at'] = utc_now()
    summary['status'] = rollup_status(cases)
    summary['updated_at'] = utc_now()
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return {
        'schema_version': 1,
        'status': 'recorded',
        'artifact_dir': str(artifact_dir),
        'summary_file': str(summary_path),
        'case_id': args.case_id,
        'case_status': status,
        'summary_status': summary['status'],
        'evidence': evidence,
    }


def load_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise SystemExit(f'{path} is not valid JSON: {exc}') from exc
    if not isinstance(payload, dict):
        raise SystemExit(f'{path} JSON payload must be an object')
    return payload


def ensure_cases(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_cases = summary.setdefault('cases', {})
    if not isinstance(raw_cases, dict):
        raise SystemExit('summary.json cases must be an object for case recording')
    expected_names = dict(evidence_init.CASE_DEFINITIONS)
    cases: dict[str, dict[str, Any]] = {}
    for case_id, name in expected_names.items():
        raw_case = raw_cases.setdefault(
            case_id,
            {'name': name, 'status': 'pending', 'evidence': [], 'notes': ''},
        )
        if not isinstance(raw_case, dict):
            raise SystemExit(f'summary.json case {case_id} must be an object')
        raw_case.setdefault('name', name)
        raw_case.setdefault('status', 'pending')
        raw_case.setdefault('evidence', [])
        raw_case.setdefault('notes', '')
        cases[case_id] = raw_case
    return cases


def normalize_evidence(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return normalized


def evidence_path_issues(
    artifact_dir: Path,
    evidence: list[str],
    *,
    require_exists: bool,
) -> list[str]:
    issues: list[str] = []
    root = artifact_dir.resolve()
    for item in evidence:
        path = Path(item)
        if path.is_absolute():
            issues.append(f'evidence path must be relative: {item}')
            continue
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root):
            issues.append(f'evidence path escapes artifact dir: {item}')
            continue
        if require_exists and not resolved.exists():
            issues.append(f'evidence path does not exist: {item}')
            continue
        if require_exists and resolved.is_file() and resolved.stat().st_size == 0:
            issues.append(f'evidence file is empty: {item}')
            continue
        if require_exists and resolved.is_dir() and not any(resolved.iterdir()):
            issues.append(f'evidence directory is empty: {item}')
            continue
        if require_exists and resolved.exists() and not resolved.is_file() and not resolved.is_dir():
            issues.append(f'evidence path is neither file nor directory: {item}')
    return issues


def rollup_status(cases: dict[str, dict[str, Any]]) -> str:
    statuses = {str(case.get('status') or '').strip() for case in cases.values()}
    if all(status in ACCEPTED_STATUSES for status in statuses):
        return 'ok'
    if any(status in {'blocked', 'fail', 'failed'} for status in statuses):
        return 'blocked'
    return 'pending'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
