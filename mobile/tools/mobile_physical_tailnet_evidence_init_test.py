#!/usr/bin/env python3
"""Self-tests for physical Tailnet evidence packet initialization."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


INIT_MODULE_PATH = Path(__file__).with_name('mobile_physical_tailnet_evidence_init.py')
AUDIT_MODULE_PATH = Path(__file__).with_name('mobile_physical_tailnet_evidence_audit.py')


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'could not load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


INIT = load_module('mobile_physical_tailnet_evidence_init', INIT_MODULE_PATH)
AUDIT = load_module('mobile_physical_tailnet_evidence_audit', AUDIT_MODULE_PATH)


class MobilePhysicalTailnetEvidenceInitTest(unittest.TestCase):
    def test_init_creates_summary_readme_and_capture_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'physical-run'

            result = INIT.init_evidence_dir(artifact)

            summary = json.loads((artifact / 'summary.json').read_text(encoding='utf-8'))
            readme_exists = (artifact / 'README.md').exists()
            screenshots_exists = (artifact / 'phone-screenshots').is_dir()
            ui_exists = (artifact / 'phone-ui').is_dir()

        self.assertEqual(result['status'], 'initialized')
        self.assertTrue(readme_exists)
        self.assertTrue(screenshots_exists)
        self.assertTrue(ui_exists)
        self.assertEqual(set(summary['cases'].keys()), {'T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6'})
        self.assertEqual(
            {case['status'] for case in summary['cases'].values()},
            {'pending'},
        )

    def test_init_does_not_overwrite_existing_summary_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'physical-run'
            artifact.mkdir()
            (artifact / 'summary.json').write_text('{"status":"custom"}\n', encoding='utf-8')

            result = INIT.init_evidence_dir(artifact)

            summary = json.loads((artifact / 'summary.json').read_text(encoding='utf-8'))

        self.assertIn('summary.json', result['skipped'])
        self.assertEqual(summary, {'status': 'custom'})

    def test_force_rewrites_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'physical-run'
            artifact.mkdir()
            (artifact / 'summary.json').write_text('{"status":"custom"}\n', encoding='utf-8')

            result = INIT.init_evidence_dir(artifact, force=True)

            summary = json.loads((artifact / 'summary.json').read_text(encoding='utf-8'))

        self.assertIn('summary.json', result['created'])
        self.assertEqual(summary['status'], 'pending')
        self.assertIn('T6', summary['cases'])

    def test_initialized_packet_cannot_pass_audit_without_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / 'physical-run'
            INIT.init_evidence_dir(artifact)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('preflight.json', result['missing'])
        self.assertIn("summary.json: T0 status is 'pending'", result['semantic_issues'])


if __name__ == '__main__':
    unittest.main()
