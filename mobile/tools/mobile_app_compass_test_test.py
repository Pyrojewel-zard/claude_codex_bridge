#!/usr/bin/env python3
"""Self-tests for the CCB Mobile app compass test tool."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name('mobile_app_compass_test.py')
SPEC = importlib.util.spec_from_file_location('mobile_app_compass_test', MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f'could not load {MODULE_PATH}')
COMPASS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COMPASS
SPEC.loader.exec_module(COMPASS)


class MobileAppCompassTest(unittest.TestCase):
    def test_parse_meminfo_extracts_total_pss_and_rss(self) -> None:
        parsed = COMPASS.parse_meminfo(
            '''
            App Summary
                         Pss(KB)                        Rss(KB)
            TOTAL        304540        0        0        176912
            TOTAL RSS: 394336K
            '''
        )

        self.assertEqual(parsed['total_pss_kb'], 304540)
        self.assertEqual(parsed['total_rss_kb'], 394336)

    def test_extract_app_top_line_returns_package_line(self) -> None:
        line = COMPASS.extract_app_top_line(
            '''
            123 system  0.0 com.android.systemui
            456 u0_a268 0.3 io.ccb.mobile.ccb_mobile
            ''',
            'io.ccb.mobile.ccb_mobile',
        )

        self.assertIn('io.ccb.mobile.ccb_mobile', line)

    def test_summarize_api_samples_computes_success_stats(self) -> None:
        summary = COMPASS.summarize_api_samples(
            [
                {'ok': True, 'duration_ms': 80.0},
                {'ok': True, 'duration_ms': 120.0},
                {'ok': False, 'duration_ms': 5000.0},
                {'ok': True, 'duration_ms': 100.0},
            ]
        )

        self.assertEqual(summary['ok_count'], 3)
        self.assertEqual(summary['fail_count'], 1)
        self.assertEqual(summary['p50_ms'], 100.0)
        self.assertEqual(summary['max_ms'], 120.0)

    def test_summarize_memory_reports_delta_and_growth_ratio(self) -> None:
        summary = COMPASS.summarize_memory(
            [
                {'total_pss_kb': 1000},
                {'total_pss_kb': 1200},
                {'total_pss_kb': 1100},
            ]
        )

        self.assertEqual(summary['pss_kb_min'], 1000)
        self.assertEqual(summary['pss_kb_max'], 1200)
        self.assertEqual(summary['pss_kb_delta'], 100)
        self.assertEqual(summary['pss_growth_ratio'], 0.1)

    def test_parse_power_summary_keeps_wake_lock_lines(self) -> None:
        parsed = COMPASS.parse_power_summary(
            '''
              mWakefulness=Awake
              mWakeLockSummary=0x0
              mHoldingWakeLockSuspendBlocker=false
            Wake Locks: size=0
            '''
        )

        self.assertEqual(parsed['wake_locks'], 'Wake Locks: size=0')
        self.assertEqual(parsed['wake_lock_summary'], 'mWakeLockSummary=0x0')
        self.assertEqual(
            parsed['holding_wakelock_suspend_blocker'],
            'mHoldingWakeLockSuspendBlocker=false',
        )

    def test_detect_ui_markers_flags_real_and_fake_surfaces(self) -> None:
        markers = COMPASS.detect_ui_markers(
            'content-desc="test_ccb2_beta" text="Message mobile_probe"'
        )

        self.assertTrue(markers['contains_test_project'])
        self.assertTrue(markers['contains_composer'])
        self.assertFalse(markers['contains_fake_marker'])

        fake = COMPASS.detect_ui_markers('FAKE[mobile_peer] demo')
        self.assertTrue(fake['contains_fake_marker'])

    def test_classify_summary_warns_when_send_lacks_reply_marker(self) -> None:
        status = COMPASS.classify_summary(
            {
                'device_attached': True,
                'app_foreground': True,
                'adb_reverse_has_gateway_port': True,
                'require_adb_reverse': True,
                'expected_project_visible': True,
                'ui_markers': {'contains_fake_marker': False},
                'projects_api': {'fail_count': 0},
                'memory': {'pss_growth_ratio': 0.01},
                'logcat': {'fatal_anr_oom': False},
                'send_probe': {
                    'own_message_visible_ms': 500.0,
                    'reply_marker_visible': False,
                },
            }
        )

        self.assertEqual(status, 'warn')

    def test_classify_summary_blocks_when_app_not_foreground(self) -> None:
        status = COMPASS.classify_summary(
            {
                'device_attached': True,
                'app_foreground': False,
                'adb_reverse_has_gateway_port': True,
                'require_adb_reverse': True,
                'expected_project_visible': True,
                'ui_markers': {'contains_fake_marker': False},
                'projects_api': {'fail_count': 0},
                'memory': {'pss_growth_ratio': 0.0},
                'logcat': {'fatal_anr_oom': False},
            }
        )

        self.assertEqual(status, 'blocked')

    def test_classify_summary_blocks_when_expected_project_is_missing(self) -> None:
        status = COMPASS.classify_summary(
            {
                'device_attached': True,
                'app_foreground': True,
                'adb_reverse_has_gateway_port': True,
                'require_adb_reverse': True,
                'expected_project_visible': False,
                'ui_markers': {'contains_fake_marker': False},
                'projects_api': {'fail_count': 0},
                'memory': {'pss_growth_ratio': 0.0},
                'logcat': {'fatal_anr_oom': False},
            }
        )

        self.assertEqual(status, 'blocked')

    def test_classify_summary_blocks_when_reverse_is_required_and_missing(self) -> None:
        status = COMPASS.classify_summary(
            {
                'device_attached': True,
                'app_foreground': True,
                'adb_reverse_has_gateway_port': False,
                'require_adb_reverse': True,
                'expected_project_visible': True,
                'ui_markers': {'contains_fake_marker': False},
                'projects_api': {'fail_count': 0},
                'memory': {'pss_growth_ratio': 0.0},
                'logcat': {'fatal_anr_oom': False},
            }
        )

        self.assertEqual(status, 'blocked')

    def test_classify_summary_fails_on_fake_marker_by_default(self) -> None:
        status = COMPASS.classify_summary(
            {
                'device_attached': True,
                'app_foreground': True,
                'adb_reverse_has_gateway_port': True,
                'require_adb_reverse': True,
                'expected_project_visible': True,
                'ui_markers': {'contains_fake_marker': True},
                'projects_api': {'fail_count': 0},
                'memory': {'pss_growth_ratio': 0.0},
                'logcat': {'fatal_anr_oom': False},
            }
        )

        self.assertEqual(status, 'fail')

    def test_monitor_sample_count_includes_start_and_end(self) -> None:
        self.assertEqual(COMPASS.monitor_sample_count(180, 30), 7)
        self.assertEqual(COMPASS.monitor_sample_count(0, 30), 1)

    def test_adb_devices_has_device_accepts_whitespace_separated_rows(self) -> None:
        self.assertTrue(
            COMPASS.adb_devices_has_device(
                'List of devices attached\n'
                'emulator-5554          device product:sdk_phone model:emu\n'
            )
        )
        self.assertTrue(
            COMPASS.adb_devices_has_device(
                'List of devices attached\nemulator-5554\tdevice usb:1-1\n'
            )
        )
        self.assertFalse(
            COMPASS.adb_devices_has_device(
                'List of devices attached\nemulator-5554 offline\n'
            )
        )

    def test_adb_input_text_escapes_shell_sensitive_input(self) -> None:
        self.assertEqual(COMPASS.adb_input_text('hello world%'), 'hello%sworld%25')

    def test_dry_run_summary_lists_safe_actions(self) -> None:
        args = COMPASS.parse_args(
            [
                '--dry-run',
                '--gateway-url',
                'http://127.0.0.1:19011',
                '--send-marker',
                'marker',
            ]
        )
        summary = COMPASS.dry_run_summary(args)

        self.assertTrue(summary['dry_run'])
        self.assertEqual(summary['expected_project_text'], 'test_ccb2')
        self.assertTrue(summary['require_adb_reverse'])
        self.assertIn('controlled send', ' '.join(summary['actions']))

    def test_casebook_coverage_names_compass_cases(self) -> None:
        args = COMPASS.parse_args(
            [
                '--gateway-url',
                'http://127.0.0.1:19022',
                '--duration-s',
                '60',
            ]
        )
        summary = {
            'status': 'ok',
            'device_attached': True,
            'app_foreground': True,
            'adb_reverse_has_gateway_port': True,
            'require_adb_reverse': True,
            'expected_project_visible': True,
            'ui_markers': {'contains_fake_marker': False},
            'projects_api': {'fail_count': 0},
            'memory': {'pss_growth_ratio': 0.0},
            'logcat': {'fatal_anr_oom': False},
        }

        coverage = COMPASS.casebook_coverage(summary, args)

        self.assertEqual(coverage['case_ids'], ['C0.1', 'C10.1-debug-preflight'])
        self.assertIsNone(coverage['first_failed_gate'])
        self.assertIsNone(coverage['owner'])
        self.assertFalse(coverage['fake_or_demo_used'])

    def test_casebook_coverage_marks_send_probe_gap(self) -> None:
        args = COMPASS.parse_args(
            [
                '--send-marker',
                'marker',
            ]
        )
        summary = {
            'status': 'warn',
            'device_attached': True,
            'app_foreground': True,
            'adb_reverse_has_gateway_port': True,
            'require_adb_reverse': True,
            'expected_project_visible': True,
            'ui_markers': {'contains_fake_marker': False},
            'projects_api': {'fail_count': 0},
            'memory': {'pss_growth_ratio': 0.0},
            'logcat': {'fatal_anr_oom': False},
            'send_probe': {
                'own_message_visible_ms': 120.0,
                'reply_marker_visible': False,
            },
        }

        coverage = COMPASS.casebook_coverage(summary, args)

        self.assertIn('C3.1-controlled-send-probe', coverage['case_ids'])
        self.assertEqual(
            coverage['first_failed_gate'],
            'controlled send reply marker not visible',
        )
        self.assertEqual(coverage['owner'], 'app-transport')

    def test_write_casebook_artifacts_writes_standard_files(self) -> None:
        args = COMPASS.parse_args(
            [
                '--gateway-url',
                'http://127.0.0.1:19022',
                '--expected-project-text',
                'test_ccb2_beta',
            ]
        )
        summary = {
            'status': 'ok',
            'casebook': {
                'schema_version': 1,
                'case_ids': ['C0.1'],
                'status': 'ok',
            },
            'adb_reverse_has_gateway_port': True,
            'app_foreground': True,
            'window_focus': 'io.ccb.mobile.ccb_mobile.MainActivity',
            'projects_api': {
                'ok_count': 1,
                'fail_count': 0,
                'samples': [{'ok': True, 'duration_ms': 10.0}],
            },
            'memory': {'pss_growth_ratio': 0.0},
            'monitor_samples': [{'elapsed_s': 0, 'total_pss_kb': 100}],
            'power': {'wake_locks': 'Wake Locks: size=0'},
            'batterystats_excerpt': [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            COMPASS.write_casebook_artifacts(artifact_dir, summary, args)

            for name in [
                'environment.json',
                'timings.json',
                'request-counts.json',
                'memory.json',
                'power-summary.json',
                'casebook-summary.json',
            ]:
                self.assertTrue((artifact_dir / name).exists(), name)

            files = summary['files']
            self.assertIn('environment.json', files)
            self.assertIn('request-counts.json', files)


if __name__ == '__main__':
    unittest.main()
