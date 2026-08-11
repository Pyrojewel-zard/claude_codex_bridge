#!/usr/bin/env python3
"""Self-tests for physical Tailnet case result recording."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOLS_DIR))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'could not load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


INIT = load_module('mobile_physical_tailnet_evidence_init', TOOLS_DIR / 'mobile_physical_tailnet_evidence_init.py')
RECORD = load_module('mobile_physical_tailnet_case_record', TOOLS_DIR / 'mobile_physical_tailnet_case_record.py')
AUDIT = load_module('mobile_physical_tailnet_evidence_audit', TOOLS_DIR / 'mobile_physical_tailnet_evidence_audit.py')


class MobilePhysicalTailnetCaseRecordTest(unittest.TestCase):
    def test_rejects_accepted_case_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)

            with self.assertRaises(SystemExit) as raised:
                RECORD.record_case(make_args(artifact, 'T0', status='ok'))

        self.assertIn('without at least one --evidence path', str(raised.exception))

    def test_rejects_missing_evidence_path_for_accepted_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)

            with self.assertRaises(SystemExit) as raised:
                RECORD.record_case(
                    make_args(artifact, 'T0', status='ok', evidence=['missing.json'])
                )

        self.assertIn('evidence path does not exist: missing.json', str(raised.exception))

    def test_rejects_escaping_evidence_path_for_accepted_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)

            with self.assertRaises(SystemExit) as raised:
                RECORD.record_case(make_args(artifact, 'T0', status='ok', evidence=['../x']))

        self.assertIn('evidence path escapes artifact dir: ../x', str(raised.exception))

    def test_rejects_empty_evidence_file_for_accepted_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)
            (artifact / 'empty.txt').write_text('', encoding='utf-8')

            with self.assertRaises(SystemExit) as raised:
                RECORD.record_case(
                    make_args(artifact, 'T0', status='ok', evidence=['empty.txt'])
                )

        self.assertIn('evidence file is empty: empty.txt', str(raised.exception))

    def test_rejects_empty_evidence_directory_for_accepted_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)
            (artifact / 'empty-dir').mkdir()

            with self.assertRaises(SystemExit) as raised:
                RECORD.record_case(
                    make_args(artifact, 'T0', status='ok', evidence=['empty-dir'])
                )

        self.assertIn('evidence directory is empty: empty-dir', str(raised.exception))

    def test_records_case_evidence_and_keeps_summary_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)
            touch(artifact / 'preflight.json')
            touch(artifact / 'environment.json')

            result = RECORD.record_case(
                make_args(
                    artifact,
                    'T0',
                    status='ok',
                    evidence=['preflight.json', 'environment.json', 'preflight.json'],
                    notes='phone and tailnet ready',
                )
            )

            summary = read_summary(artifact)

        self.assertEqual(result['summary_status'], 'pending')
        self.assertEqual(summary['cases']['T0']['status'], 'ok')
        self.assertEqual(summary['cases']['T0']['evidence'], ['preflight.json', 'environment.json'])
        self.assertEqual(summary['cases']['T0']['notes'], 'phone and tailnet ready')

    def test_rolls_summary_to_ok_when_all_cases_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)

            for case_id in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6'):
                evidence_path = f'{case_id.lower()}-evidence.json'
                touch(artifact / evidence_path)
                RECORD.record_case(
                    make_args(
                        artifact,
                        case_id,
                        status='ok',
                        evidence=[evidence_path],
                    )
                )

            summary = read_summary(artifact)

        self.assertEqual(summary['status'], 'ok')

    def test_blocked_case_rolls_summary_to_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'artifact'
            INIT.init_evidence_dir(artifact)

            RECORD.record_case(
                make_args(
                    artifact,
                    'T5',
                    status='blocked',
                    notes='phone vpn unavailable',
                )
            )

            summary = read_summary(artifact)

        self.assertEqual(summary['status'], 'blocked')
        self.assertEqual(summary['cases']['T5']['notes'], 'phone vpn unavailable')

    def test_audit_fails_accepted_case_without_evidence(self) -> None:
        summary = INIT.summary_payload()
        summary['status'] = 'ok'
        for case in summary['cases'].values():
            case['status'] = 'ok'
            case['evidence'] = ['case-evidence.json']
        summary['cases']['T4']['evidence'] = []

        issues = AUDIT.summary_semantic_issues(summary)

        self.assertIn('summary.json: T4 has accepted status without evidence', issues)


def make_args(
    artifact_dir: Path,
    case_id: str,
    *,
    status: str,
    evidence: list[str] | None = None,
    notes: str = '',
) -> argparse.Namespace:
    return argparse.Namespace(
        artifact_dir=artifact_dir,
        case_id=case_id,
        status=status,
        evidence=evidence or [],
        notes=notes,
        allow_missing_evidence=False,
    )


def read_summary(artifact_dir: Path) -> dict[str, object]:
    return json.loads((artifact_dir / 'summary.json').read_text(encoding='utf-8'))


def touch(path: Path) -> None:
    path.write_text('evidence\n', encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
