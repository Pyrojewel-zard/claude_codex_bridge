from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def test_release_install_preserves_shared_python_launcher_in_place(tmp_path: Path) -> None:
    install_prefix = tmp_path / "install"
    install_bin = install_prefix / "bin"
    external_bin = tmp_path / "home" / "bin"
    install_bin.mkdir(parents=True)
    external_bin.mkdir(parents=True)

    installed_launcher = install_bin / "_ccb-python"
    shutil.copy2(REPO_ROOT / "bin" / "_ccb-python", installed_launcher)
    installed_launcher.chmod(0o755)

    fake_python = tmp_path / "python3.11"
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "CODEX_INSTALL_PREFIX": str(install_prefix),
            "CODEX_BIN_DIR": str(install_bin),
            "CCB_SOURCE_KIND": "release",
            "CCB_PYTHON": str(fake_python),
        }
    )
    command = textwrap.dedent(
        f"""
        set -euo pipefail
        source {shlex.quote(str(INSTALL_SH))}
        ! is_ccb_launcher_entrypoint {shlex.quote(str(installed_launcher))}
        is_ccb_launcher_entrypoint {shlex.quote(str(REPO_ROOT / 'ccb'))}
        is_ccb_launcher_entrypoint {shlex.quote(str(REPO_ROOT / 'bin' / 'ask'))}
        install_entrypoint_executable {shlex.quote(str(installed_launcher))} {shlex.quote(str(installed_launcher))}
        test "$({shlex.quote(str(installed_launcher))} --resolve)" = {shlex.quote(str(fake_python))}
        install_entrypoint_executable {shlex.quote(str(installed_launcher))} {shlex.quote(str(external_bin / '_ccb-python'))}
        test -L {shlex.quote(str(external_bin / '_ccb-python'))}
        test "$({shlex.quote(str(external_bin / '_ccb-python'))} --resolve)" = {shlex.quote(str(fake_python))}
        """
    )

    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert installed_launcher.read_bytes() == (REPO_ROOT / "bin" / "_ccb-python").read_bytes()


def test_release_launcher_uses_managed_venv_python_directly(tmp_path: Path) -> None:
    install_prefix = tmp_path / "install"
    install_bin = install_prefix / "bin"
    external_bin = tmp_path / "home" / "bin"
    managed_python = install_prefix / ".venv" / "bin" / "python"
    install_bin.mkdir(parents=True)
    external_bin.mkdir(parents=True)
    managed_python.parent.mkdir(parents=True)

    shutil.copy2(REPO_ROOT / "ccb", install_prefix / "ccb")
    shutil.copy2(REPO_ROOT / "ccb.py", install_prefix / "ccb.py")
    shutil.copy2(REPO_ROOT / "bin" / "_ccb-python", install_bin / "_ccb-python")
    managed_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    managed_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "CODEX_INSTALL_PREFIX": str(install_prefix),
            "CODEX_BIN_DIR": str(external_bin),
            "CCB_SOURCE_KIND": "release",
            "CCB_USE_MANAGED_VENV": "1",
        }
    )
    command = textwrap.dedent(
        f"""
        set -euo pipefail
        source {shlex.quote(str(INSTALL_SH))}
        install_entrypoint_executable \
          {shlex.quote(str(install_prefix / 'ccb'))} \
          {shlex.quote(str(external_bin / 'ccb'))}
        """
    )

    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    wrapper_text = (external_bin / "ccb").read_text(encoding="utf-8")
    assert str(managed_python) in wrapper_text
    assert str(install_prefix / "ccb.py") in wrapper_text
    assert str(install_bin / "_ccb-python") not in wrapper_text
    assert f'export CCB_PYTHON="{managed_python}"' in wrapper_text
