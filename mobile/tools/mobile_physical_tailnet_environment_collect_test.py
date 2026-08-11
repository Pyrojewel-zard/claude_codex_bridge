#!/usr/bin/env python3
"""Self-tests for physical Tailnet environment evidence collection."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name('mobile_physical_tailnet_environment_collect.py')
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location(
    'mobile_physical_tailnet_environment_collect',
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f'could not load {MODULE_PATH}')
COLLECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COLLECT
SPEC.loader.exec_module(COLLECT)


class FakeRunner:
    def __init__(self, *, no_device: bool = False, tailscale_missing: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.no_device = no_device
        self.tailscale_missing = tailscale_missing

    def __call__(self, cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
        self.calls.append(cmd)
        if cmd == ['adb', 'devices', '-l']:
            if self.no_device:
                return 0, 'List of devices attached\n', ''
            return (
                0,
                'List of devices attached\n'
                'R5CT1234567 device usb:1-1 product:phone model:Pixel_8 device:husky\n',
                '',
            )
        if len(cmd) >= 6 and cmd[:2] == ['adb', '-s'] and cmd[3:6] == [
            'shell',
            'getprop',
            'sys.boot_completed',
        ]:
            return 0, '1\n', ''
        if cmd == ['tailscale', 'status', '--json']:
            if self.tailscale_missing:
                return 127, '', 'tailscale: not found'
            return (
                0,
                json.dumps(
                    {
                        'BackendState': 'Running',
                        'CurrentTailnet': {'Name': 'example.ts.net'},
                        'Self': {'DNSName': 'host.example.ts.net.'},
                    }
                ),
                '',
            )
        if cmd == ['tailscale', 'serve', 'status']:
            return 0, 'https://host.example.ts.net:8787 -> http://127.0.0.1:8787\n', ''
        if cmd == ['tailscale', 'netcheck']:
            return 0, 'Report:\n\t* UDP: true\n', ''
        if len(cmd) >= 4 and cmd[0] == 'git' and cmd[1] == '-C':
            if cmd[3:] == ['rev-parse', 'HEAD']:
                return 0, 'abcdef1234567890\n', ''
            if cmd[3:] == ['status', '--short']:
                return 0, '', ''
        raise AssertionError(f'unexpected command: {cmd}')


class MobilePhysicalTailnetEnvironmentCollectTest(unittest.TestCase):
    def test_collect_writes_preflight_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / 'artifact'
            app_root = root / 'app'
            source_root = root / 'source'
            app_root.mkdir()
            source_root.mkdir()

            result = COLLECT.collect_environment(
                make_args(
                    artifact,
                    app_root=app_root,
                    source_worktree=source_root,
                    gateway_url='https://host.example.ts.net:8787',
                ),
                runner=FakeRunner(),
                http_get=lambda url, timeout_s: (200, '{"status":"ok"}'),
            )

            preflight = json.loads((artifact / 'preflight.json').read_text(encoding='utf-8'))
            environment = json.loads((artifact / 'environment.json').read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'ok')
        self.assertEqual(preflight['status'], 'ok')
        self.assertEqual(environment['status'], 'ok')
        self.assertEqual(environment['route_provider'], 'tailnet')
        self.assertEqual(environment['app']['head'], 'abcdef1234567890')
        self.assertFalse(environment['source']['dirty'])
        self.assertIn('tailscale_netcheck', environment['commands'])

    def test_collect_blocked_preflight_still_writes_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / 'artifact'
            app_root = root / 'app'
            source_root = root / 'source'
            app_root.mkdir()
            source_root.mkdir()

            result = COLLECT.collect_environment(
                make_args(artifact, app_root=app_root, source_worktree=source_root),
                runner=FakeRunner(no_device=True, tailscale_missing=True),
            )

            preflight = json.loads((artifact / 'preflight.json').read_text(encoding='utf-8'))
            environment = json.loads((artifact / 'environment.json').read_text(encoding='utf-8'))

        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(preflight['status'], 'blocked')
        self.assertEqual(environment['status'], 'ok')
        self.assertIn('No online Android device is attached.', preflight['missing'])
        self.assertIn('tailscale: not found', environment['commands']['tailscale_status_json']['stderr'])


def make_args(
    artifact_dir: Path,
    *,
    app_root: Path,
    source_worktree: Path,
    gateway_url: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        artifact_dir=artifact_dir,
        adb='adb',
        tailscale_bin='tailscale',
        gateway_url=gateway_url,
        allow_emulator=False,
        timeout_s=10.0,
        app_root=app_root,
        source_worktree=source_worktree,
        force_init=False,
    )


if __name__ == '__main__':
    unittest.main()
