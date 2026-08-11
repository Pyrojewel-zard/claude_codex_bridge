#!/usr/bin/env python3
"""Initialize a physical Tailnet CCB Mobile evidence packet directory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


CASE_DEFINITIONS = [
    ('T0', 'Physical Device And Tailnet Readiness'),
    ('T1', 'Server-Wide Pairing And Project List'),
    ('T2', 'Pane-Equivalent Conversation'),
    ('T3', 'Desktop-Origin Sync And History'),
    ('T4', 'Files And Backend Artifacts'),
    ('T5', 'Tailnet Recovery'),
    ('T6', 'Performance, Power, And Soak'),
]

REQUIRED_EVIDENCE_FILES = [
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
    'power.txt',
    'logcat.txt',
    'gateway.log.tail',
    'source-project.log.tail',
]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = init_evidence_dir(args.artifact_dir, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create a skeleton artifact directory for physical Tailnet validation.',
    )
    parser.add_argument('artifact_dir', type=Path)
    parser.add_argument(
        '--force',
        action='store_true',
        help='overwrite generated summary.json and README.md if they already exist',
    )
    return parser.parse_args(argv)


def init_evidence_dir(artifact_dir: Path, *, force: bool = False) -> dict[str, Any]:
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []

    for dirname in ('phone-screenshots', 'phone-ui'):
        path = artifact_dir / dirname
        if path.exists():
            skipped.append(dirname)
        else:
            path.mkdir()
            created.append(dirname)

    summary_path = artifact_dir / 'summary.json'
    if write_file(summary_path, summary_payload(), force=force):
        created.append('summary.json')
    else:
        skipped.append('summary.json')

    readme_path = artifact_dir / 'README.md'
    if write_file(readme_path, readme_text(), force=force):
        created.append('README.md')
    else:
        skipped.append('README.md')

    return {
        'schema_version': 1,
        'status': 'initialized',
        'artifact_dir': str(artifact_dir),
        'created': created,
        'skipped': skipped,
        'required_evidence_files': REQUIRED_EVIDENCE_FILES,
        'required_dirs': ['phone-screenshots', 'phone-ui'],
        'next_command': (
            f'tools/mobile_physical_tailnet_evidence_audit.py {artifact_dir}'
        ),
    }


def write_file(path: Path, content: dict[str, Any] | str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    if isinstance(content, str):
        path.write_text(content, encoding='utf-8')
    else:
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return True


def summary_payload() -> dict[str, Any]:
    return {
        'schema_version': 1,
        'status': 'pending',
        'generated_at': utc_now(),
        'cases': {
            case_id: {
                'name': name,
                'status': 'pending',
                'evidence': [],
                'notes': '',
            }
            for case_id, name in CASE_DEFINITIONS
        },
    }


def readme_text() -> str:
    files = '\n'.join(f'- {name}' for name in REQUIRED_EVIDENCE_FILES)
    cases = '\n'.join(f'- {case_id}: {name}' for case_id, name in CASE_DEFINITIONS)
    return (
        '# CCB Mobile Physical Tailnet Evidence Packet\n\n'
        'Fill this directory with real physical Android phone + Tailnet evidence. '
        'Do not mark a case `ok`, `passed`, or `pass` until the linked artifacts '
        'prove that case on a real phone.\n\n'
        'Required cases:\n'
        f'{cases}\n\n'
        'Required evidence files:\n'
        f'{files}\n\n'
        'Required directories:\n'
        '- phone-screenshots/\n'
        '- phone-ui/\n\n'
        'Audit command:\n\n'
        '```bash\n'
        'tools/mobile_physical_tailnet_evidence_audit.py . --json-out audit.json\n'
        '```\n'
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    raise SystemExit(main())
