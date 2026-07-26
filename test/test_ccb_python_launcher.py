from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "_ccb-python"


def test_launcher_skips_higher_python_missing_required_packages(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    probe_log = tmp_path / "probe.log"
    incompatible = fake_bin / "python3.13"
    incompatible_312 = fake_bin / "python3.12"
    incompatible_311 = fake_bin / "python3.11"
    compatible = fake_bin / "python3.10"
    _write_probe(incompatible, compatible=False)
    _write_probe(incompatible_312, compatible=False)
    _write_probe(incompatible_311, compatible=False)
    _write_probe(compatible, compatible=True)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CCB_PYTHON_CACHE": str(tmp_path / "python-cache"),
            "PROBE_LOG": str(probe_log),
        }
    )
    env.pop("CCB_PYTHON", None)

    completed = subprocess.run(
        [str(LAUNCHER), "--resolve"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert Path(completed.stdout.strip()) == compatible
    probes = probe_log.read_text(encoding="utf-8")
    assert "python3.13:aiohttp" in probes
    assert "python3.13:cryptography-runtime" in probes


def _write_probe(path: Path, *, compatible: bool) -> None:
    result = "0" if compatible else "1"
    path.write_text(
        f"""#!/usr/bin/env bash
payload="$(cat)"
grep -q 'import aiohttp' <<<"$payload" && echo "$(basename "$0"):aiohttp" >>"$PROBE_LOG"
grep -q 'cryptography.hazmat' <<<"$payload" && echo "$(basename "$0"):cryptography-runtime" >>"$PROBE_LOG"
exit {result}
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
