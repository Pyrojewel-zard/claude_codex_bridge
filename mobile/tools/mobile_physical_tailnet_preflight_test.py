#!/usr/bin/env python3
"""Self-tests for physical Tailnet preflight checks."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).with_name('mobile_physical_tailnet_preflight.py')
SPEC = importlib.util.spec_from_file_location('mobile_physical_tailnet_preflight', MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f'could not load {MODULE_PATH}')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREFLIGHT
SPEC.loader.exec_module(PREFLIGHT)


class FakeRunner:
    def __init__(
        self,
        *,
        adb_devices: str | None = None,
        boot_completed: str = '1\n',
        tailscale_status: dict[str, object] | None = None,
        tailscale_rc: int = 0,
        tailscale_err: str = '',
        serve_status: str | None = None,
        serve_rc: int = 0,
        serve_err: str = '',
    ) -> None:
        self.calls: list[list[str]] = []
        self.adb_devices = adb_devices or (
            'List of devices attached\n'
            'R5CT1234567 device usb:1-1 product:phone model:Pixel_8 device:husky\n'
        )
        self.boot_completed = boot_completed
        self.tailscale_status = tailscale_status or {
            'BackendState': 'Running',
            'CurrentTailnet': {'Name': 'example.ts.net'},
            'Self': {'DNSName': 'host.example.ts.net.'},
        }
        self.tailscale_rc = tailscale_rc
        self.tailscale_err = tailscale_err
        self.serve_status = serve_status or (
            'https://host.example.ts.net:8787 -> http://127.0.0.1:8787\n'
        )
        self.serve_rc = serve_rc
        self.serve_err = serve_err

    def __call__(self, cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
        self.calls.append(cmd)
        if cmd == ['adb', 'devices', '-l']:
            return 0, self.adb_devices, ''
        if cmd[:5] == ['adb', '-s', cmd[2], 'shell', 'getprop']:
            return 0, self.boot_completed, ''
        if cmd == ['tailscale', 'status', '--json']:
            if self.tailscale_rc != 0:
                return self.tailscale_rc, '', self.tailscale_err
            return 0, json.dumps(self.tailscale_status), ''
        if cmd == ['tailscale', 'serve', 'status']:
            if self.serve_rc != 0:
                return self.serve_rc, '', self.serve_err
            return 0, self.serve_status, ''
        raise AssertionError(f'unexpected command: {cmd}')


class MobilePhysicalTailnetPreflightTest(unittest.TestCase):
    def test_ok_with_physical_device_tailscale_and_gateway_health(self) -> None:
        args = make_args(gateway_url='https://host.example.ts.net:8787')
        result = PREFLIGHT.run_preflight(
            args,
            runner=FakeRunner(),
            http_get=lambda url, timeout_s: (200, '{"status":"ok"}'),
        )

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['checks']['adb_device']['selected_serial'], 'R5CT1234567')
        self.assertFalse(result['checks']['adb_device']['selected_is_emulator'])
        self.assertEqual(result['checks']['tailscale_status']['backend_state'], 'Running')
        self.assertEqual(
            result['checks']['gateway_health']['url'],
            'https://host.example.ts.net:8787/v1/health',
        )
        self.assertEqual(
            result['checks']['tailscale_serve_status']['expected_https_port'],
            8787,
        )
        self.assertTrue(result['checks']['tailscale_serve_status']['loopback_origin_seen'])

    def test_blocks_when_no_android_device_is_attached(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(),
            runner=FakeRunner(adb_devices='List of devices attached\n'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('No online Android device is attached.', result['missing'])

    def test_blocks_when_only_emulator_is_attached_by_default(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(),
            runner=FakeRunner(
                adb_devices=(
                    'List of devices attached\n'
                    'emulator-5554 device product:sdk_phone model:sdk_gphone64\n'
                )
            ),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn(
            'Only emulator devices are attached; physical Tailnet validation needs a phone.',
            result['missing'],
        )

    def test_allow_emulator_supports_dry_run(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(allow_emulator=True),
            runner=FakeRunner(
                adb_devices=(
                    'List of devices attached\n'
                    'emulator-5554 device product:sdk_phone model:sdk_gphone64\n'
                )
            ),
        )

        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['checks']['adb_device']['selected_is_emulator'])

    def test_blocks_when_tailscale_is_not_available(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(),
            runner=FakeRunner(tailscale_rc=127, tailscale_err='tailscale: not found'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('tailscale status failed: tailscale: not found', result['missing'])

    def test_blocks_when_tailscale_needs_login(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(),
            runner=FakeRunner(tailscale_status={'BackendState': 'NeedsLogin'}),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn(
            'Tailscale is not logged in/running; run tailscale up and confirm login.',
            result['missing'],
        )

    def test_blocks_when_gateway_health_fails(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(gateway_url='https://host.example.ts.net:8787'),
            runner=FakeRunner(),
            http_get=lambda url, timeout_s: (503, 'unavailable'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Gateway health returned HTTP 503.', result['missing'])

    def test_blocks_when_serve_status_omits_https_port(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(gateway_url='https://host.example.ts.net:8787'),
            runner=FakeRunner(
                serve_status='https://host.example.ts.net:443 -> http://127.0.0.1:8787\n',
            ),
            http_get=lambda url, timeout_s: (200, '{"status":"ok"}'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn(
            'tailscale serve status does not mention HTTPS port 8787.',
            result['missing'],
        )

    def test_blocks_when_serve_status_omits_loopback_origin(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(gateway_url='https://host.example.ts.net:8787'),
            runner=FakeRunner(
                serve_status='https://host.example.ts.net:8787 -> http://10.0.0.4:8787\n',
            ),
            http_get=lambda url, timeout_s: (200, '{"status":"ok"}'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn(
            'tailscale serve status does not show a loopback origin.',
            result['missing'],
        )

    def test_blocks_when_serve_status_command_fails(self) -> None:
        result = PREFLIGHT.run_preflight(
            make_args(gateway_url='https://host.example.ts.net:8787'),
            runner=FakeRunner(serve_rc=1, serve_err='serve is not configured'),
            http_get=lambda url, timeout_s: (200, '{"status":"ok"}'),
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn(
            'tailscale serve status failed: serve is not configured',
            result['missing'],
        )

    def test_parse_adb_devices_ignores_offline_devices(self) -> None:
        devices = PREFLIGHT.parse_adb_devices(
            'List of devices attached\n'
            'R5CT1234567 offline usb:1-1\n'
            'R5CT7654321 device usb:1-2 model:Pixel_7\n'
        )

        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]['state'], 'offline')
        self.assertFalse(devices[1]['is_emulator'])


def make_args(
    *,
    allow_emulator: bool = False,
    gateway_url: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        adb='adb',
        tailscale_bin='tailscale',
        allow_emulator=allow_emulator,
        gateway_url=gateway_url,
        timeout_s=10.0,
        json_out=None,
    )


if __name__ == '__main__':
    unittest.main()
