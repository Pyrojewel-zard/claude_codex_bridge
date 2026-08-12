from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_closure_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_closure_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_config_declares_full_workflow_and_loop_profiles() -> None:
    module = _load_module()

    text = module.build_config(provider="fake")

    assert "frontdesk:fake; planner:fake; task_detailer:fake; clarification_broker:fake" in text
    assert "frontdesk:fake" in text
    assert "planner:fake" in text
    assert "task_detailer:fake" in text
    assert "clarification_broker:fake" in text
    assert "plan_reviewer:fake" in text
    assert "orchestrator:fake" in text
    assert "ccb_round_reviewer:fake" in text
    assert 'role = "agentroles.ccb_frontdesk"' in text
    assert 'role = "agentroles.ccb_planner"' in text
    assert 'role = "agentroles.ccb_task_detailer"' in text
    assert 'role = "agentroles.ccb_clarification_broker"' in text
    assert 'role = "agentroles.ccb_plan_reviewer"' in text
    assert 'role = "agentroles.ccb_orchestrator"' in text
    assert 'role = "agentroles.ccb_round_reviewer"' in text
    assert '[loop.role_profiles.worker]' in text
    assert 'role = "agentroles.coder"' in text
    assert '[loop.role_profiles.code_reviewer]' in text
    assert 'role = "agentroles.code_reviewer"' in text
    assert "round_checker:fake" not in text
    assert 'role = "agentroles.ccb_worker"' not in text
    assert 'role = "agentroles.ccb_checker"' not in text
    assert 'role = "agentroles.ccb_round_checker"' not in text


def test_prepare_project_writes_config_roles_plan_root_and_shims(tmp_path: Path) -> None:
    module = _load_module()
    test_root = tmp_path / "test_ccb2"
    ccb_test = tmp_path / "ccb_test"
    ccb_test.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    payload = module.prepare_project(
        test_root=test_root,
        project_name="workflow-closure-smoke",
        provider="fake",
        ccb_test=ccb_test,
        reset=False,
    )

    project_root = Path(payload["project_root"])
    role_store = Path(payload["role_store"])
    assert (project_root / ".ccb" / "ccb.config").is_file()
    assert (project_root / "docs" / "plantree" / "plans" / "workflow-smoke" / "README.md").is_file()
    assert (role_store / "installed" / "agentroles.ccb_planner" / "current" / "role.toml").is_file()
    assert (role_store / "installed" / "agentroles.ccb_orchestrator" / "current" / "role.toml").is_file()
    assert (role_store / "installed" / "agentroles.ccb_task_detailer" / "current" / "role.toml").is_file()
    assert (role_store / "installed" / "agentroles.ccb_round_reviewer" / "current" / "role.toml").is_file()
    assert (role_store / "installed" / "agentroles.coder" / "current" / "role.toml").is_file()
    assert (role_store / "installed" / "agentroles.code_reviewer" / "current" / "role.toml").is_file()
    assert (project_root / "bin" / "ccb").is_file()
    assert (project_root / "bin" / "ask").is_file()
    assert str(ccb_test.resolve(strict=False)) in (project_root / "bin" / "ccb").read_text(encoding="utf-8")


def test_phase6_route_artifact_writers_include_detail_steps_and_blocker_evidence(tmp_path: Path) -> None:
    module = _load_module()

    detail_paths = module.write_detail_artifacts(project_root=tmp_path, task_id="smoke-needs-detail-pass")
    partial_paths = module.write_partial_step_artifacts(project_root=tmp_path, task_id="smoke-partial-completion")
    blocker_path = Path(module.write_blocker_evidence(project_root=tmp_path, task_id="smoke-blocked"))

    assert {"detail_design", "detail_summary", "detail_packet", "detail_step_1", "detail_step_2"} <= set(detail_paths)
    packet = json.loads(Path(detail_paths["detail_packet"]).read_text(encoding="utf-8"))
    assert packet["step_refs"] == ["details/steps/step-1.md", "details/steps/step-2.md"]
    assert Path(detail_paths["detail_step_1"]).read_text(encoding="utf-8").startswith("# Step 1")
    assert Path(detail_paths["detail_step_2"]).read_text(encoding="utf-8").startswith("# Step 2")
    assert "status: passed" in Path(partial_paths["detail_step_1"]).read_text(encoding="utf-8")
    assert "status: open" in Path(partial_paths["detail_step_2"]).read_text(encoding="utf-8")
    assert blocker_path.read_text(encoding="utf-8").startswith("# Blocker Evidence")


def test_run_workflow_smoke_runs_direct_execution_and_releases_mount_topology(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    ccb_test = tmp_path / "ccb_test"
    ccb_test.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    runner_count = 0
    ready_count = 0
    artifact_count = 0

    def fake_run(command, **_kwargs):
        nonlocal runner_count, ready_count, artifact_count
        if command[-2:] == ["kill", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="kill_status: ok\n", stderr="")
        if "--diagnose" in command:
            return subprocess.CompletedProcess(command, 0, stdout="allowed_source_test_project: yes\n", stderr="")
        if command[-2:] == ["config", "validate"]:
            return subprocess.CompletedProcess(command, 0, stdout="config_status: valid\n", stderr="")
        if "plan" in command and "task-create" in command:
            return subprocess.CompletedProcess(command, 0, stdout=_json({"status": "draft", "task_id": "task-closure"}), stderr="")
        if "plan" in command and "task-artifact" in command:
            artifact_count += 1
            payload = {"status": "draft"}
            if "--route" in command:
                payload["artifact"] = {"orchestrator_route": command[command.index("--route") + 1]}
            return subprocess.CompletedProcess(command, 0, stdout=_json(payload), stderr="")
        if "plan" in command and "task-status" in command:
            ready_count += 1
            return subprocess.CompletedProcess(command, 0, stdout=_json({"status": "ready_for_orchestration"}), stderr="")
        if "plan" in command and "task-show" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_json(
                    {
                        "status": "done",
                        "task": {
                            "status": "done",
                            "artifacts": {
                                "round_summary": {
                                    "kind": "round_summary",
                                    "path": "rounds/lpabc123/round_summary.md",
                                }
                            },
                        },
                    }
                ),
                stderr="",
            )
        if "loop" in command and "runner" in command:
            runner_count += 1
            project_arg = Path(command[command.index("--project") + 1])
            round_path = project_arg / ".ccb" / "runtime" / "loops" / "lpabc123" / "round.json"
            round_path.parent.mkdir(parents=True, exist_ok=True)
            round_path.write_text(
                _json(
                    {
                        "loop_id": "lpabc123",
                        "worker": {"target": "loop-lpabc123-coder-1"},
                        "reviewer": {"target": "loop-lpabc123-code_reviewer-1"},
                        "orchestrator": {"target": "orchestrator"},
                        "ccb_round_reviewer": {"target": "ccb_round_reviewer"},
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_json(
                        {
                            "loop_runner_status": "ok",
                            "action": "ran_one_round",
                            "execution_mode": "ask_first_direct_execution",
                            "loop_id": "lpabc123",
                            "round_result": "pass",
                            "round_result_source": "ask_first_round",
                            "round": {"round_json_path": str(round_path)},
                            "project_root": str(project_arg),
                            "topology": {"status": "ready"},
                            "release": {
                                "loop_topology_status": "released",
                                "released_count": 2,
                                "retained_count": 0,
                            },
                        }
                    ),
                    stderr="",
                )
        if command[-1] == "ps":
            return subprocess.CompletedProcess(command, 0, stdout="agent: frontdesk\nagent: orchestrator\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    payload = module.run_workflow_smoke(
        test_root=tmp_path,
        project_name="workflow-closure-smoke",
        provider="fake",
        ccb_test=ccb_test,
        timeout_s=1,
        reset=True,
    )

    assert payload["workflow_smoke_status"] == "ok"
    assert payload["summary"]["checks"]["route_direct_execution_imported"] is True
    assert payload["summary"]["checks"]["ask_first_execution_mode"] is True
    assert payload["summary"]["checks"]["mount_topology_ready"] is True
    assert payload["summary"]["checks"]["release_retained_zero"] is True
    assert payload["summary"]["checks"]["release_count_two"] is True
    assert payload["summary"]["checks"]["dynamic_agents_absent_from_ps"] is True
    assert payload["summary"]["final_status"] == "done"
    assert payload["summary"]["round_result"] == "pass"
    assert runner_count == 1
    assert ready_count == 1
    assert artifact_count == 3


@pytest.mark.parametrize(
    ("case_id", "route", "round_result", "final_status", "checks"),
    (
        (
            "smoke-partial-completion",
            "partial_completion",
            "partial",
            "partial",
            ("partial_step_evidence_imported", "partial_not_done"),
        ),
        (
            "smoke-reviewer-reject-rework",
            "direct_execution",
            "pass",
            "done",
            ("bounded_rework_cycle", "no_extra_rework_cycle"),
        ),
        (
            "smoke-reviewer-cannot-accept",
            "direct_execution",
            "replan_required",
            "replan_required",
            ("bounded_rework_cycle", "no_extra_rework_cycle", "cannot_accept_not_done"),
        ),
    ),
)
def test_run_phase6_execution_case_smoke_summarizes_remaining_matrix_cases(
    tmp_path: Path,
    monkeypatch,
    case_id: str,
    route: str,
    round_result: str,
    final_status: str,
    checks: tuple[str, ...],
) -> None:
    module = _load_module()
    ccb_test = tmp_path / "ccb_test"
    ccb_test.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        if command[-2:] == ["kill", "-f"]:
            return subprocess.CompletedProcess(command, 0, stdout="kill_status: ok\n", stderr="")
        if "--diagnose" in command:
            return subprocess.CompletedProcess(command, 0, stdout="allowed_source_test_project: yes\n", stderr="")
        if command[-2:] == ["config", "validate"]:
            return subprocess.CompletedProcess(command, 0, stdout="config_status: valid\n", stderr="")
        if "plan" in command and "task-create" in command:
            return subprocess.CompletedProcess(command, 0, stdout=_json({"status": "draft", "task_id": case_id}), stderr="")
        if "plan" in command and "task-artifact" in command:
            payload = {"status": "draft"}
            if "--route" in command:
                payload["artifact"] = {"orchestrator_route": command[command.index("--route") + 1]}
            return subprocess.CompletedProcess(command, 0, stdout=_json(payload), stderr="")
        if "plan" in command and "task-status" in command:
            return subprocess.CompletedProcess(command, 0, stdout=_json({"status": "ready_for_orchestration"}), stderr="")
        if "plan" in command and "task-show" in command:
            artifacts = {
                "round_summary": {"kind": "round_summary", "path": "rounds/lpabc123/round_summary.md"},
            }
            if case_id == "smoke-partial-completion":
                artifacts["detail_step_1"] = {"kind": "detail_step_1", "path": "details/steps/step-1.md"}
                artifacts["detail_step_2"] = {"kind": "detail_step_2", "path": "details/steps/step-2.md"}
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_json(
                    {
                        "status": final_status,
                        "task": {
                            "status": final_status,
                            "next_owner": "planner" if final_status in {"partial", "replan_required"} else "terminal",
                            "artifacts": artifacts,
                        },
                    }
                ),
                stderr="",
            )
        if "loop" in command and "runner" in command:
            project_arg = Path(command[command.index("--project") + 1])
            loop_id = "lpabc123"
            loop_dir = project_arg / ".ccb" / "runtime" / "loops" / loop_id
            round_path = loop_dir / "round.json"
            desired_path = loop_dir / "agent_mount_topology.desired.json"
            asks_path = loop_dir / "asks.jsonl"
            loop_dir.mkdir(parents=True, exist_ok=True)
            desired_path.write_text(_json({"record_type": "ccb_loop_agent_mount_topology_desired", "nodes": []}), encoding="utf-8")
            ask_purposes = ["worker", "reviewer", "orchestrator", "ccb_round_reviewer"]
            rework = {}
            if case_id in {"smoke-reviewer-reject-rework", "smoke-reviewer-cannot-accept"}:
                ask_purposes = ["worker", "reviewer", "worker_rework", "reviewer_recheck", "orchestrator", "ccb_round_reviewer"]
                rework = {
                    "worker_rework": {"target": f"loop-{loop_id}-coder-1", "status": "completed", "job_id": "job_3"},
                    "reviewer_recheck": {"target": f"loop-{loop_id}-code_reviewer-1", "status": "completed", "job_id": "job_4"},
                }
            asks_path.write_text(
                "".join(_json({"purpose": purpose}) for purpose in ask_purposes),
                encoding="utf-8",
            )
            round_path.write_text(
                _json(
                    {
                        "loop_id": loop_id,
                        "round_result": round_result,
                        "round_result_source": "round_reviewer_reply",
                        "worker": {"target": f"loop-{loop_id}-coder-1", "status": "completed"},
                        "reviewer": {"target": f"loop-{loop_id}-code_reviewer-1", "status": "completed"},
                        "rework": rework,
                        "orchestrator": {"target": "orchestrator", "status": "completed"},
                        "ccb_round_reviewer": {"target": "ccb_round_reviewer", "status": "completed"},
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_json(
                    {
                        "loop_runner_status": "ok",
                        "action": "ran_one_round",
                        "execution_mode": "ask_first_direct_execution",
                        "loop_id": loop_id,
                        "round_result": round_result,
                        "round_result_source": "round_reviewer_reply",
                        "round": {"round_json_path": str(round_path)},
                        "project_root": str(project_arg),
                        "topology": {"status": "ready", "desired_path": str(desired_path)},
                        "release": {
                            "loop_topology_status": "released",
                            "released_count": 2,
                            "retained_count": 0,
                        },
                    }
                ),
                stderr="",
            )
        if command[-1] == "ps":
            return subprocess.CompletedProcess(command, 0, stdout="agent: frontdesk\nagent: orchestrator\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    payload = module.run_phase6_execution_case_smoke(
        test_root=tmp_path,
        project_name=f"workflow-{case_id}",
        case_id=case_id,
        provider="fake",
        ccb_test=ccb_test,
        timeout_s=1,
        reset=True,
    )

    assert payload["workflow_smoke_status"] == "ok"
    assert payload["summary"]["observed_route"] == route
    assert payload["summary"]["round_result"] == round_result
    assert payload["summary"]["final_status"] == final_status
    assert payload["summary"]["cleanup_status"] == "released"
    for check in checks:
        assert payload["summary"]["checks"][check] is True


def test_tests_workflow_runs_workflow_closure_layout_cleanup_smoke() -> None:
    text = Path(".github/workflows/test.yml").read_text(encoding="utf-8")

    assert "Guard workflow closure layout cleanup smoke" in text
    assert "scripts/single_lane_multi_workgroup_smoke.py" in text
    assert "--count 1" in text
    assert "--shape parallel" in text
    assert "--scenario pass" in text
    assert "matrix.os == 'ubuntu-latest' && matrix.python-version == '3.11'" in text
    assert 'payload["status"] == "pass"' in text
    for key in (
        "release_clean",
        "raw_observed_no_live_agents",
        "dynamic_residue_absent",
        "child_worktree_residue_absent",
        "external_cleanup_succeeded",
        "process_residue_absent",
        "socket_residue_absent",
        "socket_filesystem_entries_absent",
    ):
        assert f'"{key}",' in text


def test_real_wsl_gate_keeps_mounted_drive_startup_smoke() -> None:
    text = Path(".github/workflows/ccbd-real-platform.yml").read_text(
        encoding="utf-8"
    )
    step = text.split("- name: Smoke ccb startup from /mnt/c in WSL", 1)[1].split(
        "- name: Lifecycle smoke in WSL",
        1,
    )[0]

    assert 'export CCB_PYTHON=/tmp/ccb-ci-py311/bin/python' in step
    assert 'project="/mnt/c/Temp/ccb-wsl-mnt-smoke-' in step
    assert "runtime_root_kind: relocated" in step
    assert "ccbd_tmux_socket_root_kind: runtime" in step


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"
def test_smoke_env_propagates_explicit_source_wrapper_allowed_root(tmp_path: Path) -> None:
    module = _load_module()
    test_root = tmp_path / 'external-test-root'
    project_root = test_root / 'project'
    role_store = project_root / 'roles'

    env = module._smoke_env(
        test_root=test_root,
        project_root=project_root,
        role_store=role_store,
    )

    assert env['CCB_TEST_ROOTS'] == str(test_root.resolve())
    assert env['CCB_SOURCE_ALLOWED_ROOTS'] == str(test_root.resolve())
