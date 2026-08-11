#!/usr/bin/env python3
"""Self-tests for physical Tailnet evidence packet audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name('mobile_physical_tailnet_evidence_audit.py')
SPEC = importlib.util.spec_from_file_location(
    'mobile_physical_tailnet_evidence_audit',
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f'could not load {MODULE_PATH}')
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class MobilePhysicalTailnetEvidenceAuditTest(unittest.TestCase):
    def test_ok_packet_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['requirements_version'], 'physical-tailnet-stress-v2')
        self.assertEqual(result['missing'], [])
        self.assertEqual(result['semantic_issues'], [])

    def test_preflight_blocked_keeps_packet_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp), preflight_status='blocked')

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('preflight.json: preflight did not pass', result['semantic_issues'])

    def test_missing_required_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            (artifact / 'projects.json').unlink()

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('projects.json', result['missing'])

    def test_missing_case_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(
                artifact / 'summary.json',
                {
                    'status': 'ok',
                    'cases': {
                        case_id: {'status': 'ok'}
                        for case_id in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5')
                    },
                },
            )

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('summary.json: missing case T6', result['semantic_issues'])

    def test_blocked_case_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            summary = ok_summary()
            summary['cases']['T4'] = {'status': 'blocked'}
            write_json(artifact / 'summary.json', summary)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn("summary.json: T4 status is 'blocked'", result['semantic_issues'])

    def test_case_list_shape_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(
                artifact / 'summary.json',
                {
                    'status': 'ok',
                    'cases': [
                        {
                            'case_id': case_id,
                            'status': 'ok',
                            'evidence': [f'{case_id.lower()}-evidence.json'],
                        }
                        for case_id in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6')
                    ],
                },
            )

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['semantic_issues'], [])

    def test_missing_case_evidence_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            summary = ok_summary()
            summary['cases']['T3']['evidence'] = ['missing-case-evidence.json']
            write_json(artifact / 'summary.json', summary)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'summary.json: T3 evidence path does not exist: missing-case-evidence.json',
            result['semantic_issues'],
        )

    def test_escaping_case_evidence_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            summary = ok_summary()
            summary['cases']['T3']['evidence'] = ['../outside.txt']
            write_json(artifact / 'summary.json', summary)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'summary.json: T3 evidence path escapes artifact dir: ../outside.txt',
            result['semantic_issues'],
        )

    def test_empty_case_evidence_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            (artifact / 'empty.txt').write_text('', encoding='utf-8')
            summary = ok_summary()
            summary['cases']['T3']['evidence'] = ['empty.txt']
            write_json(artifact / 'summary.json', summary)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'summary.json: T3 evidence file is empty: empty.txt',
            result['semantic_issues'],
        )

    def test_empty_case_evidence_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            (artifact / 'empty-dir').mkdir()
            summary = ok_summary()
            summary['cases']['T3']['evidence'] = ['empty-dir']
            write_json(artifact / 'summary.json', summary)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'summary.json: T3 evidence directory is empty: empty-dir',
            result['semantic_issues'],
        )

    def test_non_tailnet_environment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp), route_provider='lan')

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('environment.json: route provider is not tailnet', result['semantic_issues'])

    def test_hash_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp), hash_match=False)

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('transfer-hashes.json: hash_match is False', result['semantic_issues'])

    def test_log_marker_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp), logcat_text='CCB_REQ_ID leaked\n')

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn('logcat.txt: contains CCB_REQ_ID', result['semantic_issues'])

    def test_short_timing_sample_set_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(artifact / 'timings.json', {'status': 'ok', 'turns': [ok_turn()]})

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'timings.json: requires at least 5 turn timing samples',
            result['semantic_issues'],
        )

    def test_timing_turn_without_reply_latency_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            turns = ok_turns()
            turns[1] = {
                'prompt_to_visible_own_message_ms': 240,
                'tailnet_path': 'direct',
            }
            write_json(artifact / 'timings.json', {'status': 'ok', 'turns': turns})

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'timings.json: turn 2 missing positive provider-reply latency',
            result['semantic_issues'],
        )

    def test_timing_turn_without_tailnet_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            turns = ok_turns()
            turns[2] = {
                'prompt_to_visible_own_message_ms': 250,
                'prompt_to_provider_reply_ms': 1800,
            }
            write_json(artifact / 'timings.json', {'status': 'ok', 'turns': turns})

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'timings.json: turn 3 missing direct/DERP/relay path',
            result['semantic_issues'],
        )

    def test_request_counts_without_explicit_no_blind_polling_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(artifact / 'request-counts.json', {'status': 'ok'})

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'request-counts.json: blind_polling_seen must be explicitly false',
            result['semantic_issues'],
        )

    def test_memory_without_samples_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(artifact / 'memory.json', {'status': 'ok', 'pss_growth_ratio': 0.01})

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'memory.json: requires at least 2 memory samples',
            result['semantic_issues'],
        )

    def test_memory_growth_over_threshold_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(
                artifact / 'memory.json',
                {
                    'status': 'ok',
                    'pss_growth_ratio': 0.31,
                    'samples': [{'total_pss_kb': 1000}, {'total_pss_kb': 1310}],
                },
            )

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'memory.json: pss_growth_ratio exceeds debug threshold',
            result['semantic_issues'],
        )

    def test_recovery_without_events_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            write_json(
                artifact / 'recovery-events.json',
                {'status': 'ok', 'input_replayed': False, 'events': []},
            )

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'recovery-events.json: requires at least 4 recovery events',
            result['semantic_issues'],
        )

    def test_power_without_idle_wake_lock_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_artifact_dir(Path(tmp))
            (artifact / 'power.txt').write_text('Wake Locks: size=1\n', encoding='utf-8')

            result = AUDIT.audit_physical_tailnet_evidence(artifact)

        self.assertEqual(result['status'], 'fail')
        self.assertIn(
            'power.txt: wake locks are not idle-zero',
            result['semantic_issues'],
        )


def make_artifact_dir(
    root: Path,
    *,
    preflight_status: str = 'ok',
    route_provider: str = 'tailnet',
    hash_match: bool = True,
    logcat_text: str = 'clean logcat\n',
) -> Path:
    artifact = root / 'artifact'
    artifact.mkdir()
    write_json(artifact / 'summary.json', ok_summary())
    write_json(
        artifact / 'preflight.json',
        {'status': preflight_status, 'checks': {'adb_device': {'selected_is_emulator': False}}},
    )
    write_json(
        artifact / 'environment.json',
        {
            'status': 'ok',
            'route_provider': route_provider,
            'android': {'serial': 'R5CT1234567', 'is_emulator': False},
            'project_roots': ['/home/bfly/yunwei/test_ccb2/test_alpha'],
        },
    )
    write_json(artifact / 'projects.json', {'status': 'ok', 'healthy_count': 2})
    write_json(artifact / 'gateway-health.json', {'status': 'ok'})
    write_json(artifact / 'route-diagnostics.json', {'status': 'ok'})
    write_json(artifact / 'timings.json', {'status': 'ok', 'turns': ok_turns()})
    write_json(artifact / 'request-counts.json', {'status': 'ok', 'blind_polling_seen': False})
    write_json(
        artifact / 'memory.json',
        {
            'status': 'ok',
            'pss_growth_ratio': 0.01,
            'samples': [{'total_pss_kb': 1000}, {'total_pss_kb': 1010}],
        },
    )
    write_json(
        artifact / 'transfer-hashes.json',
        {'status': 'ok', 'files': [{'name': 'report.md', 'hash_match': hash_match}]},
    )
    write_json(
        artifact / 'recovery-events.json',
        {
            'status': 'ok',
            'input_replayed': False,
            'events': [
                {'event': 'vpn_off'},
                {'event': 'vpn_on'},
                {'event': 'tailscale_serve_restart'},
                {'event': 'gateway_restart'},
            ],
        },
    )
    (artifact / 'power.txt').write_text('Wake Locks: size=0\n', encoding='utf-8')
    (artifact / 'logcat.txt').write_text(logcat_text, encoding='utf-8')
    (artifact / 'gateway.log.tail').write_text('gateway ok\n', encoding='utf-8')
    (artifact / 'source-project.log.tail').write_text('source ok\n', encoding='utf-8')
    screenshots = artifact / 'phone-screenshots'
    screenshots.mkdir()
    (screenshots / 'screen.txt').write_text('screenshot placeholder\n', encoding='utf-8')
    ui = artifact / 'phone-ui'
    ui.mkdir()
    (ui / 'ui.xml').write_text('<hierarchy />\n', encoding='utf-8')
    for case_id in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6'):
        (artifact / f'{case_id.lower()}-evidence.json').write_text(
            '{"status":"ok"}\n',
            encoding='utf-8',
        )
    return artifact


def ok_turns() -> list[dict[str, object]]:
    return [
        ok_turn(own_ms=220 + index * 10, reply_ms=1200 + index * 100)
        for index in range(5)
    ]


def ok_turn(*, own_ms: int = 220, reply_ms: int = 1200) -> dict[str, object]:
    return {
        'prompt_to_visible_own_message_ms': own_ms,
        'prompt_to_provider_reply_ms': reply_ms,
        'tailnet_path': 'direct',
    }


def ok_summary() -> dict[str, object]:
    return {
        'status': 'ok',
        'cases': {
            case_id: {'status': 'ok', 'evidence': [f'{case_id.lower()}-evidence.json']}
            for case_id in ('T0', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6')
        },
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
