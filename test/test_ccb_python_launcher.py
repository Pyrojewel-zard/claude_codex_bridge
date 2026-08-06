from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "bin" / "_ccb-python"


def test_launcher_prefers_install_managed_python_over_stale_inherited_state(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "install"
    installed_launcher = install_root / "bin" / "_ccb-python"
    installed_launcher.parent.mkdir(parents=True)
    shutil.copy2(LAUNCHER, installed_launcher)

    probe_log = tmp_path / "probe.log"
    managed = install_root / ".venv" / "bin" / "python"
    managed.parent.mkdir(parents=True)
    stale_inherited = tmp_path / "stale-python"
    stale_cached = tmp_path / "cached-python"
    _write_probe(managed, compatible=True)
    _write_probe(stale_inherited, compatible=False)
    _write_probe(stale_cached, compatible=False)
    cache_path = tmp_path / "python-cache"
    cache_path.write_text(f"{stale_cached}\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "CCB_PYTHON": str(stale_inherited),
            "CCB_PYTHON_CACHE": str(cache_path),
            "PROBE_LOG": str(probe_log),
        }
    )

    completed = subprocess.run(
        [str(installed_launcher), "--resolve"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert Path(completed.stdout.strip()) == managed
    assert cache_path.read_text(encoding="utf-8").strip() == str(managed)
    probes = probe_log.read_text(encoding="utf-8")
    assert "stale-python:aiohttp" in probes
    assert "python:aiohttp" in probes
    assert "cached-python:aiohttp" not in probes


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
