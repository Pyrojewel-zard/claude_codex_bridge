from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_npm_runner_attests_package_ownership_and_overrides_stale_markers() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    script = """
const runner = require('./bin/ccb-npm-runner');
const env = runner.npmManagedEnvironment({
  KEEP_ME: 'yes',
  CCB_INSTALL_KIND: 'spoofed',
  CCB_NPM_PACKAGE_NAME: 'wrong',
  CCB_NPM_PACKAGE_ROOT: '/wrong',
  CCB_NPM_PACKAGE_VERSION: '0.0.0',
});
process.stdout.write(JSON.stringify(env));
"""

    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    payload = json.loads(completed.stdout)
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert payload["KEEP_ME"] == "yes"
    assert payload["CCB_INSTALL_KIND"] == "npm"
    assert payload["CCB_NPM_PACKAGE_NAME"] == "@seemseam/ccb"
    assert payload["CCB_NPM_PACKAGE_ROOT"] == str(ROOT)
    assert payload["CCB_NPM_PACKAGE_VERSION"] == manifest["version"]
