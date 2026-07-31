from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    return node


def _npm_installer_fixture(tmp_path: Path) -> tuple[Path, Path]:
    package_root = tmp_path / "package"
    package_bin = package_root / "bin"
    package_bin.mkdir(parents=True)
    shutil.copy2(ROOT / "package.json", package_root / "package.json")
    shutil.copy2(
        ROOT / "bin" / "ccb-npm-install.js",
        package_bin / "ccb-npm-install.js",
    )
    installer = package_bin / "ccb-npm-install.js"
    info = json.loads(
        subprocess.run(
            [
                _node(),
                "-e",
                (
                    f"const installer = require({json.dumps(str(installer))});"
                    "process.stdout.write(JSON.stringify(installer.artifactForHost()));"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout
    )
    release_root = package_root / ".ccb-release" / info["directory"]
    release_root.mkdir(parents=True)
    manifest = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    (release_root / "VERSION").write_text(
        f"{manifest['version']}\n",
        encoding="utf-8",
    )
    ccb = release_root / "ccb"
    ccb.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    ccb.chmod(0o755)
    return installer, release_root


def _write_runtime_bootstrap_installer(
    release_root: Path,
    *,
    exit_code: int = 0,
    delay_seconds: float = 0,
) -> None:
    installer = release_root / "install.sh"
    installer.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            test "${{1:-}}" = runtime-bootstrap
            test "$CODEX_INSTALL_PREFIX" = {json.dumps(str(release_root))}
            test "$CCB_SOURCE_KIND" = release
            test "$CCB_USE_MANAGED_VENV" = 1
            test "$CCB_INSTALL_TOMLI" = 1
            test "$CCB_INSTALL_MOBILE_RELAY_DEPS" = 1
            sleep {delay_seconds}
            printf '%s\\n' runtime-bootstrap >> "$CODEX_INSTALL_PREFIX/bootstrap.log"
            if [[ {exit_code} -ne 0 ]]; then
              exit {exit_code}
            fi
            mkdir -p "$CODEX_INSTALL_PREFIX/.venv/bin"
            cat > "$CODEX_INSTALL_PREFIX/.venv/bin/python" <<'PY'
            #!/usr/bin/env bash
            exit 0
            PY
            chmod +x "$CODEX_INSTALL_PREFIX/.venv/bin/python"
            """
        ),
        encoding="utf-8",
    )
    installer.chmod(0o755)


def _installer_module_script(installer: Path) -> str:
    return (
        f"const installer = require({json.dumps(str(installer))});"
        "installer.install().catch((error) => {"
        "console.error(error.message || error);"
        "process.exit(1);"
        "});"
    )


def _run_installer_module(installer: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), "-e", _installer_module_script(installer)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def test_npm_runner_attests_package_ownership_and_overrides_stale_markers() -> None:
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
        [_node(), "-e", script],
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


def test_npm_installer_bootstraps_and_reuses_release_local_runtime(
    tmp_path: Path,
) -> None:
    installer, release_root = _npm_installer_fixture(tmp_path)
    _write_runtime_bootstrap_installer(release_root)

    first = _run_installer_module(installer)
    assert first.returncode == 0, first.stderr or first.stdout
    second = _run_installer_module(installer)
    assert second.returncode == 0, second.stderr or second.stdout

    assert (release_root / "bootstrap.log").read_text(encoding="utf-8").splitlines() == [
        "runtime-bootstrap"
    ]
    assert (release_root / ".venv" / "bin" / "python").is_file()
    assert not (installer.parents[1] / ".ccb-install.lock").exists()


def test_npm_installer_serializes_concurrent_runtime_repairs(tmp_path: Path) -> None:
    installer, release_root = _npm_installer_fixture(tmp_path)
    _write_runtime_bootstrap_installer(release_root, delay_seconds=0.5)
    command = [_node(), "-e", _installer_module_script(installer)]

    first = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    second = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    first_stdout, first_stderr = first.communicate(timeout=30)
    second_stdout, second_stderr = second.communicate(timeout=30)

    assert first.returncode == 0, first_stderr or first_stdout
    assert second.returncode == 0, second_stderr or second_stdout
    assert (release_root / "bootstrap.log").read_text(encoding="utf-8").splitlines() == [
        "runtime-bootstrap"
    ]
    assert not (installer.parents[1] / ".ccb-install.lock").exists()


def test_npm_installer_repairs_an_unhealthy_managed_runtime(tmp_path: Path) -> None:
    installer, release_root = _npm_installer_fixture(tmp_path)
    broken_python = release_root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    broken_python.chmod(0o755)
    _write_runtime_bootstrap_installer(release_root)

    completed = _run_installer_module(installer)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert (release_root / "bootstrap.log").read_text(encoding="utf-8") == (
        "runtime-bootstrap\n"
    )


def test_npm_installer_fails_closed_and_releases_lock_when_bootstrap_fails(
    tmp_path: Path,
) -> None:
    installer, release_root = _npm_installer_fixture(tmp_path)
    _write_runtime_bootstrap_installer(release_root, exit_code=23)

    completed = _run_installer_module(installer)

    assert completed.returncode == 1
    assert "runtime-bootstrap failed with exit 23" in completed.stderr
    assert not (installer.parents[1] / ".ccb-install.lock").exists()
