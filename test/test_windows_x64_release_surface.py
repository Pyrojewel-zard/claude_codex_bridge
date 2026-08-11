from __future__ import annotations

import json
import subprocess
from pathlib import Path

from terminal_runtime.windows_x64_release_surface import (
    PROJECTION_RELATIVE_PATH,
    assert_windows_x64_release_surface_projection_fresh,
    canonical_projection_json,
    default_blocked_projection,
    load_windows_x64_release_surface_projection,
)


def _write_projection(root: Path, projection: dict[str, object]) -> Path:
    path = root / PROJECTION_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_projection_json(projection), encoding="utf-8")
    return path


def _base_projection() -> dict[str, object]:
    return {
        "schema_version": 1,
        "projection_source": "packaged_json",
        "baseline_gate_ref": ".codestable/features/baseline/acceptance.md",
        "user_surfaces_parity_ref": ".codestable/features/surfaces/acceptance.md",
        "packaged_projection_ref": PROJECTION_RELATIVE_PATH.as_posix(),
        "implementation_admission": "admitted",
        "baseline_version_ref": "VERSION",
        "baseline_version_status": "v8.5.2",
        "package_os": ["linux", "darwin", "win32"],
        "package_cpu": ["x64", "arm64"],
        "package_metadata_policy": "win32-enabled-postinstall-gated",
        "host_gate": {
            "default_failure_reason": "projection-schema-invalid",
            "default_next_action": "Regenerate the Windows x64 release-surface projection.",
            "rules": [
                {
                    "field": "os_platform",
                    "op": "equals",
                    "value": "win32",
                    "failure_reason": "not-windows",
                    "diagnostic": "Windows release route requires os_platform=win32.",
                    "next_action": "Use Linux/macOS release routes or retry on native Windows x64.",
                },
                {
                    "field": "cpu_arch",
                    "op": "equals",
                    "value": "x64",
                    "failure_reason": "not-x64",
                    "diagnostic": "Windows release route requires a native x64 host.",
                    "next_action": "Retry from a native Windows x64 host.",
                },
                {
                    "field": "wow64",
                    "op": "is_false",
                    "value": False,
                    "failure_reason": "wow64",
                    "diagnostic": "WOW64 is not a native Windows x64 process.",
                    "next_action": "Use a native 64-bit shell and Node runtime.",
                },
            ],
        },
        "windows_npm_enabled": True,
        "artifact_status": "ready",
        "artifact_basename": "ccb-windows-x86_64",
        "archive_name": "ccb-windows-x86_64.zip",
        "extract_dir": "ccb-windows-x86_64",
        "checksum_entry": "ccb-windows-x86_64.zip",
        "release_artifact_ref": "release/v8.5.2",
        "windows_installer_entry": "install.ps1",
        "windows_executable_entry": "ccb.exe",
        "windows_bin_entries": {
            "ccb": "ccb.exe",
            "ask": "bin/ask.exe",
            "autonew": "bin/autonew.exe",
            "ctx-transfer": "bin/ctx-transfer.exe",
        },
        "release_install_entry": "npm",
        "source_install_allowed": True,
        "source_install_entry": "install_ps1",
        "update_entry": "install_ps1",
        "managed_python_status": "ready",
        "native_helper_status": "ready",
        "upstream_gate_status": "ready",
        "upstream_failure_ref": None,
        "upstream_detail_reason": None,
        "beta_gaps": [],
        "surface_state": "available",
        "failure_reason": None,
        "release_gate_detail": "Windows x64 release surface admitted by fake fixture.",
        "diagnostic": "Windows x64 release route is available.",
        "next_action": "Run the code-level Windows npm install dry-run.",
    }


def test_default_projection_is_blocked_when_packaged_json_is_missing(tmp_path: Path) -> None:
    projection = load_windows_x64_release_surface_projection(tmp_path, {})

    assert projection["projection_source"] == "default_blocked"
    assert projection["surface_state"] == "blocked"
    assert projection["windows_npm_enabled"] is False
    assert projection["release_install_entry"] == "diagnostic_only"
    assert projection["source_install_allowed"] is True
    assert projection["failure_reason"] == "release-artifact-missing"
    assert projection["baseline_version_status"] == "v8.5.2"
    assert projection["package_metadata_policy"] == "win32-enabled-postinstall-gated"
    assert "win32" in projection["package_os"]
    assert projection["next_action"]


def test_loader_accepts_strict_packaged_projection_for_native_windows_x64(tmp_path: Path) -> None:
    _write_projection(tmp_path, _base_projection())

    projection = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "x64", "wow64": False},
    )

    assert projection["projection_source"] == "packaged_json"
    assert projection["surface_state"] == "available"
    assert projection["windows_npm_enabled"] is True
    assert projection["windows_bin_entries"]["ctx-transfer"] == "bin/ctx-transfer.exe"


def test_host_gate_first_failure_overrides_packaged_route(tmp_path: Path) -> None:
    _write_projection(tmp_path, _base_projection())

    projection = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "arm64", "wow64": False},
    )

    assert projection["surface_state"] == "blocked"
    assert projection["windows_npm_enabled"] is False
    assert projection["failure_reason"] == "not-x64"
    assert projection["diagnostic"] == "Windows release route requires a native x64 host."


def test_malformed_packaged_projection_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / PROJECTION_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    projection = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "x64", "wow64": False},
    )

    assert projection["surface_state"] == "blocked"
    assert projection["failure_reason"] == "projection-schema-invalid"


def test_stale_packaged_projection_schema_fails_closed(tmp_path: Path) -> None:
    projection = _base_projection()
    projection["schema_version"] = 2
    _write_projection(tmp_path, projection)

    loaded = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "x64", "wow64": False},
    )

    assert loaded["surface_state"] == "blocked"
    assert loaded["failure_reason"] == "projection-schema-invalid"


def test_available_projection_requires_ready_artifact_fields(tmp_path: Path) -> None:
    projection = _base_projection()
    projection["artifact_status"] = "missing"
    projection["archive_name"] = None
    _write_projection(tmp_path, projection)

    loaded = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "x64", "wow64": False},
    )

    assert loaded["surface_state"] == "blocked"
    assert loaded["failure_reason"] == "projection-schema-invalid"


def test_host_gate_comparison_rule_without_value_fails_closed(tmp_path: Path) -> None:
    projection = _base_projection()
    del projection["host_gate"]["rules"][0]["value"]
    _write_projection(tmp_path, projection)

    loaded = load_windows_x64_release_surface_projection(
        tmp_path,
        {"os_platform": "win32", "cpu_arch": "x64", "wow64": False},
    )

    assert loaded["surface_state"] == "blocked"
    assert loaded["failure_reason"] == "projection-schema-invalid"


def test_node_adapter_reads_projection_and_evaluates_host_gate(tmp_path: Path) -> None:
    _write_projection(tmp_path, _base_projection())
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const projection = adapter.readWindowsX64ReleaseSurfaceProjection(process.argv[1]);
const result = adapter.evaluateWindowsX64ReleaseHostGate(
  projection,
  { os_platform: 'win32', cpu_arch: 'arm64', wow64: false }
);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["allowed"] is False
    assert result["failure_reason"] == "not-x64"
    assert result["diagnostic"] == "Windows release route requires a native x64 host."


def test_node_adapter_allows_generic_host_gate_all_pass(tmp_path: Path) -> None:
    _write_projection(tmp_path, _base_projection())
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const projection = adapter.readWindowsX64ReleaseSurfaceProjection(process.argv[1]);
const result = adapter.evaluateWindowsX64ReleaseHostGate(
  projection,
  { os_platform: 'win32', cpu_arch: 'x64', wow64: false }
);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["allowed"] is True
    assert result["failure_reason"] is None


def test_node_adapter_rejects_comparison_rule_without_value(tmp_path: Path) -> None:
    projection = _base_projection()
    del projection["host_gate"]["rules"][0]["value"]
    _write_projection(tmp_path, projection)
    script = """
const adapter = require('./bin/ccb-npm-install.js');
try {
  adapter.readWindowsX64ReleaseSurfaceProjection(process.argv[1]);
} catch (error) {
  process.stdout.write(String(error.message || error));
  process.exit(0);
}
process.exit(1);
"""

    completed = subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert "comparison rule value is required" in completed.stdout


def test_node_host_evidence_uses_supplied_environment_for_wow64() -> None:
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const evidence = adapter.collectWindowsX64ReleaseHostEvidence({ PROCESSOR_ARCHITEW6432: 'AMD64' });
process.stdout.write(JSON.stringify(evidence));
"""

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    evidence = json.loads(completed.stdout)
    assert evidence["wow64"] is True


def test_install_ps1_declares_release_surface_projection_helpers() -> None:
    text = Path("install.ps1").read_text(encoding="utf-8")

    assert "Get-WindowsX64ReleaseSurfaceProjection" in text
    assert "Test-WindowsX64ReleaseHostGate" in text
    for op in ("equals", "in", "not_equals", "is_false", "exists"):
        assert op in text


def test_packaged_projection_matches_canonical_default_blocked_record() -> None:
    assert_windows_x64_release_surface_projection_fresh(Path.cwd())


def test_packaged_projection_freshness_gate_rejects_stale_payload(tmp_path: Path) -> None:
    projection = default_blocked_projection()
    projection["diagnostic"] = "stale"
    _write_projection(tmp_path, projection)

    try:
        assert_windows_x64_release_surface_projection_fresh(tmp_path)
    except ValueError as exc:
        assert "not fresh" in str(exc)
    else:
        raise AssertionError("stale packaged projection was accepted")


def test_package_metadata_allows_windows_postinstall_but_keeps_cpu_envelope() -> None:
    manifest = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert "win32" in manifest["os"]
    assert manifest["cpu"] == ["x64", "arm64"]
    assert PROJECTION_RELATIVE_PATH.as_posix() in manifest["files"]


def test_node_postinstall_uses_projection_for_fake_admitted_windows_route(tmp_path: Path) -> None:
    _write_projection(tmp_path, _base_projection())
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const info = adapter.artifactForWindowsX64ReleaseSurface(process.argv[1], {
  os_platform: 'win32',
  cpu_arch: 'x64',
  wow64: false,
});
process.stdout.write(JSON.stringify(info));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(tmp_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    info = json.loads(completed.stdout)
    assert info["directory"] == "ccb-windows-x86_64"
    assert info["file"] == "ccb-windows-x86_64.zip"


def test_node_postinstall_blocks_current_default_projection_on_windows_x64() -> None:
    script = """
const adapter = require('./bin/ccb-npm-install.js');
try {
  adapter.artifactForWindowsX64ReleaseSurface(process.cwd(), {
    os_platform: 'win32',
    cpu_arch: 'x64',
    wow64: false,
  });
} catch (error) {
  process.stdout.write(String(error.message || error));
  process.exit(0);
}
process.exit(1);
"""

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert "Windows x64 release route is blocked" in completed.stdout
    assert "diagnostic-only" in completed.stdout


def test_windows_npm_runner_uses_projection_entries_for_every_public_bin(tmp_path: Path) -> None:
    projection = _base_projection()
    package_root = tmp_path / "package"
    _write_projection(package_root, projection)
    manifest = json.loads(Path("package.json").read_text(encoding="utf-8"))
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const projection = adapter.readWindowsX64ReleaseSurfaceProjection(process.argv[1]);
const info = {
  directory: projection.extract_dir,
  file: projection.archive_name,
  windows_executable_entry: projection.windows_executable_entry,
  windows_bin_entries: projection.windows_bin_entries,
};
const base = process.argv[2];
const commands = JSON.parse(process.argv[3]);
const mapped = {};
for (const command of commands) {
  mapped[command] = adapter.executablePathForArtifact(info, command, base);
}
process.stdout.write(JSON.stringify(mapped));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(package_root), str(tmp_path / "staged"), json.dumps(sorted(manifest["bin"]))],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    mapped = json.loads(completed.stdout)
    assert set(mapped) == set(manifest["bin"])
    assert mapped["ccb"].endswith("ccb.exe")
    normalized = {name: value.replace("\\", "/") for name, value in mapped.items()}
    assert normalized["ask"].endswith("bin/ask.exe")
    assert normalized["autonew"].endswith("bin/autonew.exe")
    assert normalized["ctx-transfer"].endswith("bin/ctx-transfer.exe")


def test_windows_npm_install_readiness_uses_projected_executable_entry(tmp_path: Path) -> None:
    release_dir = tmp_path / "ccb-windows-x86_64"
    release_dir.mkdir()
    (release_dir / "VERSION").write_text("8.5.2\n", encoding="utf-8")
    (release_dir / "ccb.exe").write_text("stub\n", encoding="utf-8")
    script = """
const adapter = require('./bin/ccb-npm-install.js');
const path = require('path');
const releaseDir = process.argv[1];
const info = {
  _base_dir: path.dirname(releaseDir),
  directory: path.basename(releaseDir),
  file: 'ccb-windows-x86_64.zip',
  windows_bin_entries: { ccb: 'ccb.exe' }
};
process.stdout.write(JSON.stringify({
  releaseInstalled: adapter.isReleaseInstalled(info),
  runtimeReady: adapter.isRuntimeReady(info),
  runtimePythonPath: adapter.runtimePythonPath(info)
}));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(release_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result == {
        "releaseInstalled": True,
        "runtimeReady": True,
        "runtimePythonPath": None,
    }


def test_windows_npm_runner_fails_closed_when_bin_entry_is_missing() -> None:
    script = """
const adapter = require('./bin/ccb-npm-install.js');
try {
  adapter.executablePathForArtifact(
    { directory: 'ccb-windows-x86_64', file: 'ccb-windows-x86_64.zip', windows_bin_entries: { ccb: 'ccb.exe' } },
    'ask',
    'C:/fake/staged'
  );
} catch (error) {
  process.stdout.write(String(error.message || error));
  process.exit(0);
}
process.exit(1);
"""

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert "does not contain Windows executable entry for ask" in completed.stdout


def test_install_ps1_reports_release_surface_without_blocking_source_install() -> None:
    text = Path("install.ps1").read_text(encoding="utf-8")
    install_body = text.split("function Install-Native", 1)[1]

    assert "Show-WindowsX64ReleaseSurfaceProjection" in text
    assert "Get-WindowsX64ReleaseHostEvidence" in text
    assert install_body.index("Show-WindowsX64ReleaseSurfaceProjection") < install_body.index("$pythonCmd = Find-Python")
    assert "source_install_allowed" in text
    assert "release_install_entry" in text
