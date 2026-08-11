from __future__ import annotations

import copy
import importlib.util
import subprocess
from pathlib import Path

import pytest


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / ".codestable"
    / "roadmap"
    / "windows-native-herdr-ccb"
    / "drafts"
    / "herdr-backend-contract-spike"
    / "run_spike.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("herdr_contract_spike_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _passing_operation(name: str, ref: str) -> dict[str, object]:
    return {
        "operation": name,
        "status": "pass",
        "command_ref": ref,
        "elapsed_ms": 1,
        "evidence_ref": ref,
        "failure_class": None,
        "diagnostic": "passed",
    }


def _passing_evidence(tmp_path: Path) -> dict[str, object]:
    refs = {}
    for name in ["platform_gate", "version", "schema", "status", *runner.CORE_OPERATIONS]:
        ref = tmp_path / f"{name}.json"
        ref.write_text("{}", encoding="utf-8")
        refs[name] = ref.as_posix()
    return {
        "schema_version": 1,
        "feature": runner.FEATURE,
        "generated_at": "2026-08-01T00:00:00+00:00",
        "host": {
            "os_platform": "win32",
            "cpu_arch": "x64",
            "python_bitness": "64bit",
            "is_wsl": False,
            "dedicated_host_label": "WIN-HERDR",
            "platform_gate_host_label": "WIN-HERDR",
            "platform_gate_os_platform": "win32",
            "platform_gate_cpu_arch": "x64",
            "platform_gate_python_bitness": "64bit",
            "platform_gate_ref": refs["platform_gate"],
            "platform_gate_supported": True,
            "platform_gate_failure_reason": None,
            "platform_gate_detail_reason": None,
        },
        "herdr": {
            "executable": "C:/Tools/herdr/herdr.exe",
            "version": "herdr 0.1.0",
            "api_schema_ref": "evidence/schema.json",
            "socket_ref": "isolated://ccb-herdr-spike",
            "server_identity": "server-1",
            "status": "available",
        },
        "operations": [_passing_operation(name, refs[name]) for name in runner.CORE_OPERATIONS],
        "provider_cli_dry_run": {
            "provider_slug": "codex",
            "dry_run_kind": "provider_cli",
            "command": ["codex", "--version"],
            "pane_ref": {"pane_id": "pane-provider"},
            "output_match": True,
            "exit_observed": True,
            "killed_by_spike": False,
            "treated_as_completion_authority": False,
            "public_provider_parity_claimed": False,
            "failure_class": None,
        },
        "fallback_terminal_smoke": None,
        "restore": {
            "detach_reattach_checked": True,
            "detach_process_continues": True,
            "server_restart_checked": True,
            "restart_isolation": {
                "server_ref_kind": "dedicated-disposable-server",
                "session_name": "ccb-herdr-spike",
                "socket_ref": "isolated://ccb-herdr-spike",
                "config_ref": "evidence/herdr-config.toml",
                "server_identity_before": "server-1",
                "server_identity_after": "server-2",
                "preexisting_sessions_before": [],
                "created_by_spike": True,
                "stop_command_ref": refs["server_restart_layout_restore"],
                "cleanup_targets": ["ccb-herdr-spike"],
            },
            "restart_scope": "dedicated-disposable-server",
            "server_identity": "server-2",
            "preexisting_sessions_checked": True,
            "restart_authorized": True,
            "layout_restored": True,
            "output_history_restored": True,
            "agent_session_restored": None,
            "old_process_expected_to_survive": False,
            "ui_detach_reattach_harness": {
                "status": "follow-up",
                "required_context": "HERDR_ENV=1 with Herdr UI client pane context",
                "recorded_as": "herdr-ui-detach-reattach-harness",
                "current_env": {"HERDR_ENV": False, "HERDR_PANE_ID": False, "HERDR_SESSION": False},
            },
            "diagnostic": "restart restored layout and history",
        },
        "capability_projection": {
            "command_status": {name: "supported" for name in runner.CORE_OPERATIONS},
            "semantic_status": {name: "supported" for name in runner.CORE_OPERATIONS},
            "windows_beta_gaps": [],
            "blocking_gaps": [],
        },
        "verdict": "pass",
        "failure_class": "none",
        "adapter_recommendation": "continue",
        "residual_risks": [],
        "artifact_refs": {
            "platform_gate": refs["platform_gate"],
            "version": refs["version"],
            "schema": refs["schema"],
            "status": refs["status"],
        },
    }


def _restore_matrix_v2_evidence(tmp_path: Path) -> dict[str, object]:
    evidence = _passing_evidence(tmp_path)
    refs = evidence["artifact_refs"]
    evidence["verdict"] = "partial"
    evidence["failure_class"] = "windows-beta-gap"
    evidence["adapter_recommendation"] = "continue-with-gaps"
    evidence["operations"] = [
        _passing_operation(name, refs["schema"])
        for name in [
            "schema",
            "server_status",
            "session_attach",
            "pane_spawn",
            "send_input",
            "read_output",
            "kill_pane",
            "server_restart_layout_restore",
        ]
    ]
    evidence["operations"].extend(
        [
            {
                "operation": "server_restart_process_continuity",
                "status": "blocked",
                "command_ref": refs["schema"],
                "elapsed_ms": None,
                "evidence_ref": refs["schema"],
                "failure_class": "windows-beta-gap",
                "diagnostic": "fresh process after restart",
            },
            {
                "operation": "server_restart_output_history",
                "status": "blocked",
                "command_ref": refs["schema"],
                "elapsed_ms": None,
                "evidence_ref": refs["schema"],
                "failure_class": "windows-beta-gap",
                "diagnostic": "output history not restored",
            },
            {
                "operation": "ui_detach_reattach",
                "status": "needs_harness",
                "command_ref": "not-run",
                "elapsed_ms": None,
                "evidence_ref": None,
                "failure_class": "needs-ui-harness",
                "diagnostic": "requires Herdr UI harness",
            },
        ]
    )
    evidence["capability_projection"] = {
        "command_status": {
            **{name: "supported" for name in runner.CORE_OPERATIONS},
            "server_restart_process_continuity": "unsupported",
            "server_restart_output_history": "unsupported",
            "ui_detach_reattach": "needs_harness",
        },
        "semantic_status": {
            **{name: "supported" for name in runner.CORE_OPERATIONS},
            "server_restart_process_continuity": "unsupported",
            "server_restart_output_history": "unsupported",
            "ui_detach_reattach": "needs_harness",
        },
        "windows_beta_gaps": [],
        "blocking_gaps": [
            "server_restart_process_continuity",
            "server_restart_output_history",
            "ui_detach_reattach",
        ],
    }
    evidence["residual_risks"] = [
        "process continuity and output history are unsupported; UI detach/reattach requires follow-up harness"
    ]
    return evidence


def test_minimal_machine_check_accepts_platform_gate_blocked_evidence(tmp_path: Path) -> None:
    gate_ref = tmp_path / "platform-gate-summary.json"
    evidence = runner.build_blocked_evidence(
        platform_gate_ref=gate_ref,
        platform_payload={"gate": {"supported": False, "detail_reason": "ccb-version-mismatch"}},
        failure_class="platform-gate-blocked",
        diagnostic="ccb-version-mismatch",
    )

    runner.validate_evidence(evidence)

    assert evidence["verdict"] == "blocked"
    assert evidence["adapter_recommendation"] == "stop"
    assert evidence["host"]["platform_gate_supported"] is False


def test_truth_table_accepts_full_continue_fixture(tmp_path: Path) -> None:
    runner.validate_evidence(_passing_evidence(tmp_path))


def test_truth_table_accepts_restore_matrix_v2_continue_with_gaps(tmp_path: Path) -> None:
    runner.validate_evidence(_restore_matrix_v2_evidence(tmp_path))


def test_truth_table_rejects_blocked_continue(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["verdict"] = "blocked"
    evidence["failure_class"] = "platform-gate-blocked"

    with pytest.raises(runner.EvidenceError, match="blocked evidence cannot recommend continue"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_pass_without_continue_recommendation(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["adapter_recommendation"] = "stop"

    with pytest.raises(runner.EvidenceError, match="pass verdict requires continue recommendation"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_pass_with_blocked_operation(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["status"] = "blocked"
    evidence["operations"][0]["failure_class"] = "schema-mismatch"
    evidence["capability_projection"] = copy.deepcopy(evidence["capability_projection"])
    evidence["capability_projection"]["blocking_gaps"] = ["schema"]

    with pytest.raises(runner.EvidenceError, match="pass verdict requires full passing truth table"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_failure_class_none_with_blocking_gap(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["verdict"] = "partial"
    evidence["adapter_recommendation"] = "continue-with-gaps"
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["status"] = "blocked"
    evidence["operations"][0]["failure_class"] = "schema-mismatch"
    evidence["capability_projection"] = copy.deepcopy(evidence["capability_projection"])
    evidence["capability_projection"]["blocking_gaps"] = ["schema"]

    with pytest.raises(runner.EvidenceError, match="failure_class none requires pass verdict"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_non_blocked_without_platform_gate(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["host"] = copy.deepcopy(evidence["host"])
    evidence["host"]["platform_gate_ref"] = None

    with pytest.raises(runner.EvidenceError, match="requires platform_gate_ref"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_non_blocked_without_platform_gate_host_label(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["host"] = copy.deepcopy(evidence["host"])
    evidence["host"]["platform_gate_host_label"] = None

    with pytest.raises(runner.EvidenceError, match="requires platform gate host label"):
        runner.validate_evidence(evidence)


def test_truth_table_rejects_non_blocked_platform_gate_host_mismatch(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["host"] = copy.deepcopy(evidence["host"])
    evidence["host"]["platform_gate_host_label"] = "OTHER-HOST"

    with pytest.raises(runner.EvidenceError, match="current host to match platform gate"):
        runner.validate_evidence(evidence)


def test_restart_authorization_requires_spike_created_isolation(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["restore"] = copy.deepcopy(evidence["restore"])
    evidence["restore"]["restart_isolation"] = copy.deepcopy(evidence["restore"]["restart_isolation"])
    evidence["restore"]["restart_isolation"]["created_by_spike"] = False

    with pytest.raises(runner.EvidenceError, match="requires spike-created isolation"):
        runner.validate_evidence(evidence)


def test_restart_authorization_requires_isolated_socket_or_config(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["restore"] = copy.deepcopy(evidence["restore"])
    evidence["restore"]["restart_isolation"] = copy.deepcopy(evidence["restore"]["restart_isolation"])
    evidence["restore"]["restart_isolation"]["socket_ref"] = None
    evidence["restore"]["restart_isolation"]["config_ref"] = None

    with pytest.raises(runner.EvidenceError, match="requires isolated socket or config ref"):
        runner.validate_evidence(evidence)


def test_restart_authorization_requires_stop_command_ref(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["restore"] = copy.deepcopy(evidence["restore"])
    evidence["restore"]["restart_isolation"] = copy.deepcopy(evidence["restore"]["restart_isolation"])
    evidence["restore"]["restart_isolation"]["stop_command_ref"] = None

    with pytest.raises(runner.EvidenceError, match="requires stop_command_ref"):
        runner.validate_evidence(evidence)


def test_restart_authorization_requires_existing_stop_command_ref(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["restore"] = copy.deepcopy(evidence["restore"])
    evidence["restore"]["restart_isolation"] = copy.deepcopy(evidence["restore"]["restart_isolation"])
    evidence["restore"]["restart_isolation"]["stop_command_ref"] = (tmp_path / "missing-stop.json").as_posix()

    with pytest.raises(runner.EvidenceError, match="requires stop_command_ref"):
        runner.validate_evidence(evidence)


def test_blocking_gaps_must_match_non_pass_operations(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["verdict"] = "blocked"
    evidence["failure_class"] = "schema-mismatch"
    evidence["adapter_recommendation"] = "stop"
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["status"] = "blocked"
    evidence["operations"][0]["failure_class"] = "schema-mismatch"

    with pytest.raises(runner.EvidenceError, match="blocking_gaps must match non-pass operations"):
        runner.validate_evidence(evidence)


def test_duplicate_core_operations_are_rejected(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"].append(copy.deepcopy(evidence["operations"][0]))

    with pytest.raises(runner.EvidenceError, match="duplicate core operations"):
        runner.validate_evidence(evidence)


def test_trace_ref_rejects_unknown_uri_scheme() -> None:
    assert runner._trace_ref_exists("bogus://missing") is False


def test_fallback_terminal_smoke_cannot_substitute_provider_dry_run(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["verdict"] = "pass"
    evidence["adapter_recommendation"] = "continue"
    evidence["provider_cli_dry_run"] = copy.deepcopy(evidence["provider_cli_dry_run"])
    evidence["provider_cli_dry_run"]["output_match"] = False
    evidence["provider_cli_dry_run"]["exit_observed"] = False
    evidence["provider_cli_dry_run"]["failure_class"] = "provider-dry-run-unavailable"
    evidence["fallback_terminal_smoke"] = {
        "dry_run_kind": "fallback_terminal_smoke",
        "command": ["powershell", "-NoProfile", "-Command", "Write-Output HERDR"],
        "pane_ref": {"pane_id": "pane-fallback"},
        "output_match": True,
        "exit_observed": True,
        "killed_by_spike": False,
        "public_provider_parity_claimed": False,
        "failure_class": None,
    }

    with pytest.raises(runner.EvidenceError, match="fallback smoke alone cannot produce pass verdict"):
        runner.validate_evidence(evidence)


def test_pass_operation_requires_existing_command_ref(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["command_ref"] = "not-run"

    with pytest.raises(runner.EvidenceError, match="pass requires command_ref"):
        runner.validate_evidence(evidence)


def test_pass_operation_requires_existing_evidence_ref(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["evidence_ref"] = None

    with pytest.raises(runner.EvidenceError, match="pass requires evidence_ref"):
        runner.validate_evidence(evidence)


def test_pass_operation_requires_existing_local_ref(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["operations"] = copy.deepcopy(evidence["operations"])
    evidence["operations"][0]["command_ref"] = (tmp_path / "missing-command.json").as_posix()

    with pytest.raises(runner.EvidenceError, match="pass requires command_ref"):
        runner.validate_evidence(evidence)


def test_pass_verdict_requires_artifact_refs(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["artifact_refs"] = {"platform_gate": evidence["artifact_refs"]["platform_gate"]}

    with pytest.raises(runner.EvidenceError, match="requires traceable artifact refs"):
        runner.validate_evidence(evidence)


def test_json_object_output_passed_rejects_non_json_stdout() -> None:
    result = subprocess.CompletedProcess(["herdr", "status", "--json"], 0, stdout="ready", stderr="")

    assert runner._json_object_output_passed(result) is False


def test_json_object_output_passed_accepts_json_object_stdout() -> None:
    result = subprocess.CompletedProcess(["herdr", "status", "--json"], 0, stdout='{"status": "ok"}', stderr="")

    assert runner._json_object_output_passed(result) is True


def test_run_converts_timeout_to_completed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=20, output="partial")

    monkeypatch.setattr(runner.subprocess, "run", _timeout)

    result, _ = runner._run(["herdr", "status", "--json"])

    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_run_converts_oserror_to_completed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def _oserror(*args, **kwargs):
        raise OSError("cannot execute")

    monkeypatch.setattr(runner.subprocess, "run", _oserror)

    result, _ = runner._run(["herdr", "status", "--json"])

    assert result.returncode == 127
    assert "cannot execute" in result.stderr


def test_command_ref_redacts_home_and_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = subprocess.CompletedProcess(
        ["cmd", f"--path={Path.home()}", "token=abc123", "--api-key", "abc123"],
        0,
        stdout=f"{Path.home()} api_key=abc123",
        stderr="Bearer abc123",
    )

    ref = runner._command_ref(tmp_path, "redacted", result.args, result)
    payload = (tmp_path / Path(ref).name).read_text(encoding="utf-8")

    assert "abc123" not in payload
    assert str(Path.home()) not in payload
    assert "<redacted>" in payload
