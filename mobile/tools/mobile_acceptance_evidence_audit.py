#!/usr/bin/env python3
"""Audit CCB Mobile stress-test evidence files.

The audit is intentionally conservative: local AVD accepted evidence must be
present and valid JSON, while the physical Tailnet lane must have an explicit
preflight result. Overall status is ``ok`` only when both local AVD evidence and
physical Tailnet evidence are green.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_PLAN_ROOT = Path('docs/plantree/plans/mobile-tmux-control')
LOCAL_MATRIX = Path('topics/app-local-avd-full-acceptance-matrix.md')
CASEBOOK = Path('topics/app-real-avd-stress-casebook.md')
PHYSICAL_PREFLIGHT = Path('history/physical-tailnet-preflight-blocked-20260627.json')
PHYSICAL_FINAL_AUDIT = Path('history/physical-tailnet-final-audit.json')
PHYSICAL_RUNBOOK = Path('topics/physical-tailnet-device-validation-runbook.md')
LINK_RE = re.compile(r'\[[^\]]+\]\(([^)]+)\)')
ACCEPTED_EVIDENCE_STATUSES = {'ok', 'passed', 'pass'}
BAD_BOOLEAN_MARKERS = {
    'fake_or_demo_used': True,
    'fake_or_demo': True,
    'ccb_req_id_seen': True,
    'blind_polling_seen': True,
}
PHYSICAL_FINAL_REQUIREMENTS_VERSION = 'physical-tailnet-stress-v2'


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit_acceptance_evidence(args.plan_root)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.json_out is not None:
        args.json_out.write_text(text + '\n', encoding='utf-8')
    return 0 if result['status'] == 'ok' else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Audit CCB Mobile acceptance evidence referenced by plan-tree.',
    )
    parser.add_argument(
        '--plan-root',
        type=Path,
        default=DEFAULT_PLAN_ROOT,
        help='mobile-tmux-control plan root',
    )
    parser.add_argument('--json-out', type=Path, help='optional JSON output path')
    return parser.parse_args(argv)


def audit_acceptance_evidence(plan_root: Path) -> dict[str, Any]:
    plan_root = plan_root.resolve()
    local_matrix_path = plan_root / LOCAL_MATRIX
    casebook_path = plan_root / CASEBOOK
    physical_preflight_path = plan_root / PHYSICAL_PREFLIGHT
    physical_final_audit_path = plan_root / PHYSICAL_FINAL_AUDIT
    physical_runbook_path = plan_root / PHYSICAL_RUNBOOK
    local_matrix = audit_markdown_table(
        local_matrix_path,
        label='local_avd_matrix',
        row_prefixes=tuple(str(index) for index in range(11)),
    )
    casebook = audit_markdown_table(
        casebook_path,
        label='real_avd_casebook',
        row_prefixes=('C',),
    )
    physical = audit_physical_tailnet(
        physical_preflight_path=physical_preflight_path,
        physical_final_audit_path=physical_final_audit_path,
        physical_runbook_path=physical_runbook_path,
    )
    status = overall_status(local_matrix, casebook, physical)
    return {
        'schema_version': 1,
        'generated_at': utc_now(),
        'status': status,
        'plan_root': str(plan_root),
        'local_avd_matrix': local_matrix,
        'real_avd_casebook': casebook,
        'physical_tailnet': physical,
    }


def audit_markdown_table(
    path: Path,
    *,
    label: str,
    row_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    missing: list[str] = []
    invalid_json: list[str] = []
    semantic_issues: list[str] = []
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return {
            'status': 'fail',
            'path': str(path),
            'row_count': 0,
            'evidence_count': 0,
            'missing': [f'{label} file does not exist: {path}'],
            'invalid_json': [],
            'semantic_issues': [],
            'rows': [],
        }
    for line in path.read_text(encoding='utf-8').splitlines():
        row = parse_table_row(line)
        if row is None:
            continue
        name, status, evidence_cell = row
        if status != 'Accepted' or not name.startswith(row_prefixes):
            continue
        evidence_paths = [
            resolve_markdown_link(path, link)
            for link in LINK_RE.findall(evidence_cell)
            if link.endswith('.json')
        ]
        row_missing: list[str] = []
        row_invalid: list[str] = []
        row_semantic_issues: list[str] = []
        for evidence_path in evidence_paths:
            if not evidence_path.exists():
                row_missing.append(str(evidence_path))
                continue
            try:
                payload = json.loads(evidence_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError as exc:
                row_invalid.append(f'{evidence_path}: {exc}')
                continue
            row_semantic_issues.extend(evidence_semantic_issues(evidence_path, payload))
        missing.extend(row_missing)
        invalid_json.extend(row_invalid)
        semantic_issues.extend(row_semantic_issues)
        rows.append(
            {
                'name': name,
                'status': status,
                'evidence_count': len(evidence_paths),
                'missing': row_missing,
                'invalid_json': row_invalid,
                'semantic_issues': row_semantic_issues,
            }
        )
    status = 'ok'
    if not rows or missing or invalid_json or semantic_issues:
        status = 'fail'
    return {
        'status': status,
        'path': str(path),
        'row_count': len(rows),
        'evidence_count': sum(int(row['evidence_count']) for row in rows),
        'missing': missing,
        'invalid_json': invalid_json,
        'semantic_issues': semantic_issues,
        'rows': rows,
    }


def audit_physical_tailnet(
    *,
    physical_preflight_path: Path,
    physical_final_audit_path: Path,
    physical_runbook_path: Path,
) -> dict[str, Any]:
    missing: list[str] = []
    issues: list[str] = []
    preflight_payload: dict[str, Any] | None = None
    final_payload: dict[str, Any] | None = None
    if not physical_runbook_path.exists():
        missing.append(f'physical Tailnet runbook does not exist: {physical_runbook_path}')
    if physical_final_audit_path.exists():
        try:
            payload = json.loads(physical_final_audit_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            issues.append(f'physical Tailnet final audit is invalid JSON: {exc}')
        else:
            if isinstance(payload, dict):
                final_payload = payload
            else:
                issues.append('physical Tailnet final audit is not a JSON object')
    if not physical_preflight_path.exists():
        missing.append(f'physical Tailnet preflight evidence does not exist: {physical_preflight_path}')
    else:
        try:
            payload = json.loads(physical_preflight_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            missing.append(f'physical Tailnet preflight evidence is invalid JSON: {exc}')
        else:
            if isinstance(payload, dict):
                preflight_payload = payload
            else:
                missing.append('physical Tailnet preflight evidence is not a JSON object')
    final_status = str((final_payload or {}).get('status') or '')
    preflight_status = str((preflight_payload or {}).get('status') or '')
    if final_payload is not None:
        final_issues = final_audit_issues(final_payload)
        status = 'ok' if not missing and not issues and not final_issues else 'fail'
        return {
            'status': status,
            'runbook': str(physical_runbook_path),
            'preflight': str(physical_preflight_path),
            'final_audit': str(physical_final_audit_path),
            'final_audit_status': final_status or None,
            'preflight_status': preflight_status or None,
            'missing': missing,
            'semantic_issues': issues + final_issues,
            'preflight_missing': list((preflight_payload or {}).get('missing') or []),
        }
    if missing:
        status = 'blocked'
    elif preflight_status != 'ok':
        status = 'blocked'
    else:
        status = 'ok'
    return {
        'status': status,
        'runbook': str(physical_runbook_path),
        'preflight': str(physical_preflight_path),
        'final_audit': str(physical_final_audit_path),
        'final_audit_status': None,
        'preflight_status': preflight_status or None,
        'missing': missing,
        'semantic_issues': issues,
        'preflight_missing': list((preflight_payload or {}).get('missing') or []),
    }


def overall_status(
    local_matrix: dict[str, Any],
    casebook: dict[str, Any],
    physical: dict[str, Any],
) -> str:
    if local_matrix.get('status') != 'ok' or casebook.get('status') != 'ok':
        return 'fail'
    if physical.get('status') == 'fail':
        return 'fail'
    if physical.get('status') != 'ok':
        return 'blocked'
    return 'ok'


def final_audit_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    status = str(payload.get('status') or '').strip()
    if status != 'ok':
        issues.append(f'physical Tailnet final audit status is {status!r}')
    requirements_version = str(payload.get('requirements_version') or '').strip()
    if requirements_version != PHYSICAL_FINAL_REQUIREMENTS_VERSION:
        issues.append(
            'physical Tailnet final audit requirements_version is '
            f'{requirements_version!r}; expected {PHYSICAL_FINAL_REQUIREMENTS_VERSION!r}'
        )
    for key in ('missing', 'invalid_json', 'semantic_issues'):
        values = payload.get(key)
        if values:
            issues.append(f'physical Tailnet final audit has non-empty {key}')
    return issues


def parse_table_row(line: str) -> tuple[str, str, str] | None:
    stripped = line.strip()
    if not stripped.startswith('|') or stripped.startswith('| :---'):
        return None
    parts = [part.strip() for part in stripped.strip('|').split('|')]
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def evidence_semantic_issues(path: Path, payload: object) -> list[str]:
    issues: list[str] = []
    if not isinstance(payload, dict):
        return [f'{path}: evidence payload is not a JSON object']
    status = str(payload.get('status') or '').strip()
    if status and status not in ACCEPTED_EVIDENCE_STATUSES:
        issues.append(f'{path}: unexpected accepted-evidence status {status!r}')
    for key, bad_value in BAD_BOOLEAN_MARKERS.items():
        observed = find_key_values(payload, key)
        for value in observed:
            if value is bad_value:
                issues.append(f'{path}: {key} is {bad_value!r}')
    return issues


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


def resolve_markdown_link(markdown_path: Path, link: str) -> Path:
    target = link.split('#', 1)[0]
    return (markdown_path.parent / target).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
