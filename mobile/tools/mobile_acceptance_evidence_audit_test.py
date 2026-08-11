#!/usr/bin/env python3
"""Self-tests for mobile acceptance evidence audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name('mobile_acceptance_evidence_audit.py')
SPEC = importlib.util.spec_from_file_location('mobile_acceptance_evidence_audit', MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f'could not load {MODULE_PATH}')
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class MobileAcceptanceEvidenceAuditTest(unittest.TestCase):
    def test_audit_passes_when_local_and_physical_evidence_are_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), physical_status='ok')

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['local_avd_matrix']['status'], 'ok')
        self.assertEqual(result['real_avd_casebook']['status'], 'ok')
        self.assertEqual(result['physical_tailnet']['status'], 'ok')

    def test_physical_blocked_keeps_overall_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(
                Path(tmp),
                physical_status='blocked',
                physical_missing=['No online Android device is attached.'],
            )

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['local_avd_matrix']['status'], 'ok')
        self.assertEqual(result['physical_tailnet']['status'], 'blocked')
        self.assertEqual(
            result['physical_tailnet']['preflight_missing'],
            ['No online Android device is attached.'],
        )

    def test_final_physical_audit_can_close_physical_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(
                Path(tmp),
                physical_status='blocked',
                physical_missing=['old preflight blocker'],
                final_audit_status='ok',
            )

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['physical_tailnet']['status'], 'ok')
        self.assertEqual(result['physical_tailnet']['final_audit_status'], 'ok')

    def test_failed_final_physical_audit_fails_overall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), final_audit_status='fail')

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['physical_tailnet']['status'], 'fail')
        self.assertIn(
            "physical Tailnet final audit status is 'fail'",
            result['physical_tailnet']['semantic_issues'],
        )

    def test_stale_final_physical_audit_requirements_fails_overall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(
                Path(tmp),
                final_audit_status='ok',
                final_audit_requirements_version='physical-tailnet-stress-v1',
            )

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            "physical Tailnet final audit requirements_version is "
            "'physical-tailnet-stress-v1'; expected 'physical-tailnet-stress-v2'",
            result['physical_tailnet']['semantic_issues'],
        )

    def test_dirty_final_physical_audit_fails_overall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(
                Path(tmp),
                final_audit_status='ok',
                final_audit_semantic_issues=['summary.json: T4 missing'],
            )

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'physical Tailnet final audit has non-empty semantic_issues',
            result['physical_tailnet']['semantic_issues'],
        )

    def test_missing_local_evidence_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), missing_local=True)

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['local_avd_matrix']['status'], 'fail')
        self.assertTrue(result['local_avd_matrix']['missing'])

    def test_invalid_json_evidence_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), invalid_json=True)

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['local_avd_matrix']['status'], 'fail')
        self.assertTrue(result['local_avd_matrix']['invalid_json'])

    def test_blocked_status_in_accepted_evidence_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), local_status='blocked')

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['local_avd_matrix']['status'], 'fail')
        self.assertIn(
            "unexpected accepted-evidence status 'blocked'",
            '\n'.join(result['local_avd_matrix']['semantic_issues']),
        )

    def test_bad_boolean_marker_in_accepted_evidence_fails_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_plan_root(Path(tmp), bad_marker=True)

            result = AUDIT.audit_acceptance_evidence(root)

        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['local_avd_matrix']['status'], 'fail')
        self.assertIn(
            'ccb_req_id_seen is True',
            '\n'.join(result['local_avd_matrix']['semantic_issues']),
        )


def make_plan_root(
    root: Path,
    *,
    physical_status: str = 'ok',
    physical_missing: list[str] | None = None,
    final_audit_status: str | None = None,
    final_audit_requirements_version: str | None = 'physical-tailnet-stress-v2',
    final_audit_semantic_issues: list[str] | None = None,
    missing_local: bool = False,
    invalid_json: bool = False,
    local_status: str = 'ok',
    bad_marker: bool = False,
) -> Path:
    plan_root = root / 'mobile-tmux-control'
    topics = plan_root / 'topics'
    history = plan_root / 'history'
    topics.mkdir(parents=True)
    history.mkdir()
    local_a = history / 'local-a.json'
    local_b = history / 'local-b.json'
    case_a = history / 'case-a.json'
    if not missing_local:
        local_payload = {'status': local_status}
        if bad_marker:
            local_payload['summary'] = {'ccb_req_id_seen': True}
        local_a.write_text(
            'not-json' if invalid_json else json.dumps(local_payload),
            encoding='utf-8',
        )
    local_b.write_text('{"status":"ok"}', encoding='utf-8')
    case_a.write_text('{"status":"ok"}', encoding='utf-8')
    (topics / 'app-local-avd-full-acceptance-matrix.md').write_text(
        (
            '| Stage | Status | Primary Evidence |\n'
            '| :--- | :--- | :--- |\n'
            '| 0. Safe baseline | Accepted | '
            '[local-a.json](../history/local-a.json), '
            '[local-b.json](../history/local-b.json) |\n'
        ),
        encoding='utf-8',
    )
    (topics / 'app-real-avd-stress-casebook.md').write_text(
        (
            '| Case | Status | Evidence |\n'
            '| :--- | :--- | :--- |\n'
            '| C0.1 Environment | Accepted | [case-a.json](../history/case-a.json) |\n'
        ),
        encoding='utf-8',
    )
    (topics / 'physical-tailnet-device-validation-runbook.md').write_text(
        '# Physical Tailnet Device Validation Runbook\n',
        encoding='utf-8',
    )
    (history / 'physical-tailnet-preflight-blocked-20260627.json').write_text(
        json.dumps({'status': physical_status, 'missing': physical_missing or []}),
        encoding='utf-8',
    )
    if final_audit_status is not None:
        (history / 'physical-tailnet-final-audit.json').write_text(
            json.dumps(
                {
                    'status': final_audit_status,
                    'requirements_version': final_audit_requirements_version,
                    'missing': [],
                    'invalid_json': [],
                    'semantic_issues': final_audit_semantic_issues or [],
                }
            ),
            encoding='utf-8',
        )
    return plan_root


if __name__ == '__main__':
    unittest.main()
