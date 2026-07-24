from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shlex
import subprocess
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "dev_tools" / "perf_ccb_startup.py"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="startup performance harness requires the Linux procfs sampler",
)
AGENT_TIMING_KEYS = {
    "prepare_launch_context",
    "build_start_cmd",
    "tmux_respawn",
    "pane_identity",
    "session_write",
    "provider_post_launch",
    "binding_resolve",
    "pane_and_runtime_facts",
    "authority_commit",
    "restore_bookkeeping",
    "unattributed",
}
SUPERVISOR_TIMING_KEYS = {
    "namespace_ensure",
    "context_and_layout_plan",
    "tmux_namespace_runtime",
    "agent_prepare_and_classify",
    "tmux_layout",
    "active_panes_and_cmd",
    "agent_runtime_commit",
    "agent_runtime_duration_sum",
    "agent_runtime_loop_overhead",
    "tmux_cleanup",
    "flow_total",
    "supervisor_total",
    *(f"agent_runtime_{key}" for key in AGENT_TIMING_KEYS),
}


def _stub_environ(**overrides: str) -> dict[str, str]:
    env = {
        "CODEX_START_CMD": (
            f"{REPO_ROOT / 'test' / 'stubs' / 'provider_stub.py'} --provider codex"
        ),
    }
    env.update(overrides)
    return env


def _load_runner():
    spec = importlib.util.spec_from_file_location("perf_ccb_startup", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def runner(monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda _root: "test-worktree-fingerprint")
    monkeypatch.setenv(
        "CODEX_START_CMD",
        f"{REPO_ROOT / 'test' / 'stubs' / 'provider_stub.py'} --provider codex",
    )
    return module


def _fixture_options(runner, tmp_path: Path, **overrides):
    test_root = tmp_path / "test-root"
    project = test_root / "project"
    source_home = test_root / "source-home"
    result_root = test_root / "artifacts"
    (project / ".ccb").mkdir(parents=True)
    (project / ".ccb" / "ccb.config").write_text("cmd; agent1:codex\n", encoding="utf-8")
    source_home.mkdir()
    source_sha = runner._read_source_sha(REPO_ROOT)
    marker = runner.owner_marker_payload(
        project_root=project,
        source_home=source_home,
        owner_uuid=str(uuid.uuid4()),
        source_root=REPO_ROOT,
        source_sha=source_sha,
    )
    (project / runner.OWNER_MARKER_NAME).write_text(json.dumps(marker) + "\n", encoding="utf-8")
    values = {
        "project_root": project,
        "ccb_test_path": REPO_ROOT / "ccb_test",
        "scenario": "warm",
        "result_root": result_root,
        "source_home": source_home,
        "test_roots": (test_root,),
        "iterations": 2,
        "warmup": 1,
        "report_wait_s": 0.0,
        "stop_wait_s": 0.0,
        "resource_sample_interval_ms": 1.0,
        "benchmark_id": "test-run",
    }
    values.update(overrides)
    return runner.StartupBenchmarkOptions(**values)


def _startup_stdout(run_id: str, **timing_overrides: float) -> str:
    timings = {
        "cli_pre_rpc": 0.0,
        "daemon_ensure": 0.0,
        "start_rpc": 0.0,
        "cli_post_rpc": 0.0,
        "sidebar_helper_refresh": 0.0,
        "layout_status": 0.0,
        "maintenance_heartbeat": 0.0,
        "cli_total": 0.0,
    }
    process_timings = {
        "popen_begin_to_ccb_test_entry": 0.0,
        "ccb_test_entry_to_pre_exec": 0.0,
        "ccb_test_pre_exec_to_ccb_py_entry": 0.0,
        "ccb_py_entry_to_main": 0.0,
        "ccb_py_main_to_cli_start": 0.0,
    }
    timings.update(timing_overrides)
    return (
        f"startup_run_id: {run_id}\n"
        f"startup_cli_timings_ms: {json.dumps(timings, separators=(',', ':'))}\n"
        f"startup_process_trace_id: trace_{'a' * 32}\n"
        "startup_process_bootstrap_timings_ms: "
        f"{json.dumps(process_timings, separators=(',', ':'))}\n"
    )


def _control_startup_stdout(run_id: str, **timing_overrides: float) -> str:
    timings = {
        "cli_pre_rpc": 0.0,
        "daemon_ensure": 0.0,
        "start_rpc": 0.0,
        "cli_post_rpc": 0.0,
        "sidebar_helper_refresh": 0.0,
        "layout_status": 0.0,
        "maintenance_heartbeat": 0.0,
        "cli_total": 0.0,
    }
    timings.update(timing_overrides)
    return (
        f"startup_run_id: {run_id}\n"
        f"startup_cli_timings_ms: {json.dumps(timings, separators=(',', ':'))}\n"
    )


def _cli_only_stdout() -> str:
    return f"v{(REPO_ROOT / 'VERSION').read_text(encoding='utf-8').strip()}\n"


def _raw_resource_profile(*, wall_ms: float = 5.0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "ccb_startup_resource_profile_raw",
        "profile_id": f"rprof_{uuid.uuid4().hex}",
        "status": "complete",
        "reason_codes": [],
        "backend": "linux_procfs_v1",
        "privacy": {
            "argv_persisted": False,
            "cwd_persisted": False,
            "environment_persisted": False,
            "raw_proc_text_persisted": False,
        },
        "capabilities": {
            "process_identity": "available",
            "ancestry": "available",
            "cpu_ticks": "available",
            "rss": "available",
            "process_io": "available",
            "command_rusage": "available",
        },
        "window": {"clock": "perf_counter_ns", "command_wall_ms": wall_ms},
        "sampler": {
            "sample_count": 3,
            "scan_wall_ms_total": 1.0,
            "scan_wall_ms_max": 0.5,
        },
        "metrics": {
            "sampled_process_tree_cpu_seconds": 0.1,
            "command_rusage_cpu_seconds": 0.2,
            "baseline_rss_bytes": 10,
            "sampled_peak_rss_bytes": 20,
            "peak_rss_delta_from_baseline_bytes": 10,
            "baseline_process_count": 1,
            "sampled_peak_process_count": 2,
            "end_process_count": 1,
            "unique_process_instance_count": 2,
            "created_process_instance_count": 1,
            "io": {
                "read_bytes": 1,
                "write_bytes": 2,
                "rchar_bytes": 3,
                "wchar_bytes": 4,
                "syscr": 5,
                "syscw": 6,
            },
        },
        "buckets": {},
        "samples": [],
    }


def _write_mounted_round(
    project: Path,
    *,
    sequence: int,
    generated_at: datetime | None = None,
    action: str = "attached",
    daemon_started: bool = False,
    exact_t1: bool = False,
    provider_prepare_count: int | None = None,
    supervisor_total: float = 0.0,
) -> str:
    ccbd = project / ".ccb" / "ccbd"
    ccbd.mkdir(parents=True, exist_ok=True)
    timestamp = (generated_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    project_id = "project-id"
    signature = "config-signature"
    lifecycle_path = project / ".ccb" / "ccbd" / "lifecycle.json"
    try:
        previous_lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        previous_lifecycle = {}
    previous_generation = previous_lifecycle.get("generation")
    generation = (
        int(previous_generation) + 1
        if daemon_started and type(previous_generation) is int
        else int(previous_generation)
        if type(previous_generation) is int
        else 7
    )
    run_id = f"start_{sequence:032x}"
    runtime_pid = os.getpid()
    state_path = project / ".ccb" / "ccbd" / "state.json"
    try:
        previous_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        previous_state = {}
    previous_namespace_epoch = previous_state.get("namespace_epoch")
    namespace_epoch = (
        int(previous_namespace_epoch) + 1
        if daemon_started and type(previous_namespace_epoch) is int
        else int(previous_namespace_epoch)
        if type(previous_namespace_epoch) is int
        else 3
    )
    tmux_socket_path = str(project / ".ccb" / "ccbd" / "tmux.sock")
    tmux_session_name = "ccb-project-test"
    pane_id = "%1"
    runtime_root = project / ".ccb" / "agents" / "agent1" / "provider-runtime" / "codex"
    runtime_root.mkdir(parents=True, exist_ok=True)
    input_fifo = runtime_root / "input.fifo"
    output_fifo = runtime_root / "output.fifo"
    for fifo in (input_fifo, output_fifo):
        if not fifo.exists():
            os.mkfifo(fifo)
    session_ref = project / ".ccb" / ".codex-agent1-session"
    prepare_count = (
        provider_prepare_count
        if provider_prepare_count is not None
        else (1 if action in {"launched", "relaunched"} else 0)
    )
    report = {
        "schema_version": 2,
        "api_version": 2,
        "record_type": "ccbd_startup_report",
        "project_id": project_id,
        "generated_at": timestamp,
        "trigger": "start_command",
        "status": "ok",
        "daemon_started": daemon_started,
        "startup_run_id": run_id,
        "daemon_generation": generation,
        "config_signature": signature,
        "requested_agents": [],
        "desired_agents": ["agent1"],
        "actions_taken": [
            f"ensure_namespace:epoch={namespace_epoch},session={tmux_session_name}",
            (
                "reuse_binding:agent1"
                if action == "attached"
                else (
                    "launch_runtime:agent1"
                    if action == "launched"
                    else "relaunch_runtime:agent1"
                )
            ),
            "cleanup_tmux_orphans:killed=0",
        ],
        "inspection": {
            "health": "healthy",
            "lease": {
                "schema_version": 2,
                "record_type": "ccbd_lease",
                "project_id": project_id,
                "ccbd_pid": runtime_pid,
                "socket_path": str(project / ".ccb" / "ccbd" / "ccbd.sock"),
                "owner_uid": os.getuid(),
                "boot_id": "test-boot-id",
                "started_at": "2026-07-16T00:00:00Z",
                "last_heartbeat_at": timestamp,
                "mount_state": "mounted",
                "generation": generation,
                "config_signature": signature,
                "keeper_pid": runtime_pid,
                "daemon_instance_id": "test-daemon-instance",
            },
        },
        "agent_results": [
            {
                "agent_name": "agent1",
                "provider": "codex",
                "action": action,
                "health": "healthy",
                "workspace_path": str(project),
                "runtime_ref": f"tmux:{pane_id}",
                "session_ref": str(session_ref),
                "lifecycle_state": "idle",
                "desired_state": "mounted",
                "reconcile_state": "steady",
                "binding_source": "provider-session",
                "terminal_backend": "tmux",
                "tmux_socket_name": None,
                "tmux_socket_path": tmux_socket_path,
                "tmux_window_name": "main",
                "tmux_window_id": "@0",
                "pane_id": pane_id,
                "active_pane_id": pane_id,
                "pane_state": "alive",
                "runtime_pid": runtime_pid,
                "runtime_root": str(runtime_root),
                "failure_reason": None,
                "binding_reject_reason": None,
                "duration_ms": 0.0,
                "provider_prepare_ms": 0.0,
                "provider_prepare_count": prepare_count,
                "timings_ms": {key: 0.0 for key in AGENT_TIMING_KEYS},
            }
        ],
        "operation_counts": {
            "startup_report_write_attempt_count": 1,
            "orphan_cleanup_owned_pane_count": 2,
            **(
                {
                    "provider_prepare_attempt_count": prepare_count,
                    "provider_prepare_count": prepare_count,
                }
                if prepare_count
                else {}
            ),
        },
        "cleanup_summaries": [
            {
                "socket_name": tmux_socket_path,
                "owned_panes": ["%0", pane_id],
                "active_panes": ["%0", pane_id],
                "orphaned_panes": [],
                "killed_panes": [],
            }
        ],
        "timings_ms": {
            **{key: 0.0 for key in SUPERVISOR_TIMING_KEYS},
            "supervisor_total": supervisor_total,
        },
        "readiness_timeline": {
            "schema_version": 1,
            "trace_id": "trace_" + "a" * 32,
            "clock": "host_perf_counter_ns",
            "origin": "ccb_py_entry",
            "attach_mode": "no_attach",
            "startup_run_id": run_id,
            "keeper_startup_id": "keeper-startup-test" if daemon_started else None,
            "daemon_generation": generation,
            "expected_daemon_generation": generation,
            "generation_correlation": "matched",
            "rpc_accepted_ms": 0.0,
            "effective_requested_agents": ["agent1"],
            "desired_agents": ["agent1"],
            "points": {
                "T0_cli_entry": {
                    "status": "reached", "elapsed_ms": 0.0,
                    "source": "ccb_py_process_entry", "agents": []
                },
                "T1_lifecycle_intent": {
                    "status": (
                        "reached"
                        if daemon_started and exact_t1
                        else "observed_upper_bound"
                        if daemon_started
                        else "not_required_already_mounted"
                    ),
                    "elapsed_ms": 0.0 if daemon_started else None,
                    "source": (
                        "keeper_lifecycle_starting_committed"
                        if daemon_started and exact_t1
                        else "cli_compatible_daemon_observation"
                        if daemon_started
                        else "cli_existing_mounted_generation"
                    ),
                    "agents": [],
                },
                "T2_control_plane_ready": {
                    "status": "reached", "elapsed_ms": 0.0,
                    "source": "cli_compatible_daemon_handle", "agents": []
                },
                "T3_namespace_attachable": {
                    "status": "reached", "elapsed_ms": 0.0,
                    "source": "ccbd_namespace_ensure_current_generation", "agents": []
                },
                "T4_requested_agents_ready": {
                    "status": "reached", "elapsed_ms": 0.0,
                    "source": "ccbd_start_flow_authority_committed", "agents": ["agent1"]
                },
                "T5_foreground_attached": {
                    "status": "not_applicable_no_attach",
                    "elapsed_ms": None,
                    "source": "ccb_no_attach",
                    "agents": [],
                },
                "T6_fully_warm": {
                    "status": "reached", "elapsed_ms": 0.0,
                    "source": "ccbd_start_flow_all_desired_agents_committed",
                    "agents": ["agent1"]
                },
            },
            "timeline_complete": True,
        },
        "sequence_for_test": sequence,
    }
    lease = {
        "schema_version": 2,
        "record_type": "ccbd_lease",
        "project_id": project_id,
        "mount_state": "mounted",
        "generation": generation,
        "config_signature": signature,
        "ccbd_pid": runtime_pid,
        "keeper_pid": runtime_pid,
        "daemon_instance_id": "test-daemon-instance",
        "boot_id": "test-boot-id",
        "socket_path": str(project / ".ccb" / "ccbd" / "ccbd.sock"),
        "started_at": "2026-07-16T00:00:00Z",
    }
    lifecycle = {
        "schema_version": 2,
        "record_type": "ccbd_lifecycle",
        "project_id": project_id,
        "desired_state": "running",
        "phase": "mounted",
        "generation": generation,
        "config_signature": signature,
        "namespace_epoch": namespace_epoch,
    }
    namespace_state = {
        "schema_version": 2,
        "record_type": "ccbd_project_namespace_state",
        "project_id": project_id,
        "namespace_epoch": namespace_epoch,
        "tmux_socket_path": tmux_socket_path,
        "tmux_session_name": tmux_session_name,
        "layout_version": 3,
        "layout_signature": "test-layout-signature",
        "control_window_name": "__ccb_ctl",
        "control_window_id": None,
        "workspace_window_name": "main",
        "workspace_window_id": "@0",
        "workspace_epoch": 1,
        "ui_attachable": True,
    }
    runtime = {
        "schema_version": 2,
        "record_type": "agent_runtime",
        "agent_name": "agent1",
        "state": "idle",
        "pid": runtime_pid,
        "runtime_ref": f"tmux:{pane_id}",
        "session_ref": str(session_ref),
        "workspace_path": str(project),
        "project_id": project_id,
        "backend_type": "pane-backed",
        "health": "healthy",
        "provider": "codex",
        "runtime_root": str(runtime_root),
        "runtime_pid": runtime_pid,
        "terminal_backend": "tmux",
        "pane_id": pane_id,
        "active_pane_id": pane_id,
        "tmux_socket_name": None,
        "tmux_socket_path": tmux_socket_path,
        "tmux_window_name": "main",
        "tmux_window_id": "@0",
        "session_file": str(session_ref),
        "session_id": "ccb-agent1-test-session",
        "slot_key": "agent1",
        "window_id": "@0",
        "workspace_epoch": 1,
        "lifecycle_state": "idle",
        "binding_generation": namespace_epoch,
        "managed_by": "ccbd",
        "binding_source": "provider-session",
        "daemon_generation": generation,
        "runtime_generation": namespace_epoch,
        "desired_state": "mounted",
        "reconcile_state": "steady",
        "restart_count": 0,
        "mount_attempt_id": None,
    }
    session = {
        "ccb_session_id": "ccb-agent1-test-session",
        "agent_name": "agent1",
        "ccb_project_id": project_id,
        "project_root": str(project),
        "project_anchor_path": str(project / ".ccb"),
        "runtime_state_root": str(project / ".ccb"),
        "runtime_dir": str(runtime_root),
        "completion_artifact_dir": str(runtime_root / "completion"),
        "terminal": "tmux",
        "tmux_session": pane_id,
        "pane_id": pane_id,
        "pane_title_marker": "CCB-agent1-test",
        "workspace_path": str(project),
        "work_dir": str(project),
        "work_dir_norm": str(project),
        "start_dir": str(project),
        "active": True,
        "tmux_socket_path": tmux_socket_path,
        "input_fifo": str(input_fifo),
        "output_fifo": str(output_fifo),
    }
    (ccbd / "startup-report.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
    (ccbd / "lease.json").write_text(json.dumps(lease) + "\n", encoding="utf-8")
    (ccbd / "lifecycle.json").write_text(json.dumps(lifecycle) + "\n", encoding="utf-8")
    (ccbd / "state.json").write_text(json.dumps(namespace_state) + "\n", encoding="utf-8")
    runtime_path = project / ".ccb" / "agents" / "agent1" / "runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")
    session_ref.write_text(json.dumps(session) + "\n", encoding="utf-8")
    return run_id


def _write_unmounted(project: Path) -> None:
    ccbd = project / ".ccb" / "ccbd"
    ccbd.mkdir(parents=True, exist_ok=True)
    lifecycle_path = ccbd / "lifecycle.json"
    state_path = ccbd / "state.json"
    try:
        previous_lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        previous_lifecycle = {}
    try:
        previous_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        previous_state = {}
    generation = (
        int(previous_lifecycle["generation"])
        if type(previous_lifecycle.get("generation")) is int
        else 6
    )
    namespace_epoch = (
        int(previous_state["namespace_epoch"])
        if type(previous_state.get("namespace_epoch")) is int
        else 2
    )
    project_id = "project-id"
    signature = "config-signature"
    (ccbd / "lease.json").write_text(
        json.dumps(
            {
                "record_type": "ccbd_lease",
                "project_id": project_id,
                "config_signature": signature,
                "mount_state": "unmounted",
                "generation": generation,
                "ccbd_pid": None,
                "keeper_pid": None,
                "daemon_instance_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    lifecycle_path.write_text(
        json.dumps(
            {
                "record_type": "ccbd_lifecycle",
                "project_id": project_id,
                "config_signature": signature,
                "phase": "unmounted",
                "desired_state": "stopped",
                "generation": generation,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "record_type": "ccbd_project_namespace_state",
                "project_id": project_id,
                "namespace_epoch": namespace_epoch,
                "ui_attachable": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    agents_root = project / ".ccb" / "agents"
    runtime_paths = agents_root.glob("*/runtime.json") if agents_root.is_dir() else ()
    for runtime_path in runtime_paths:
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime.update(
            desired_state="stopped",
            lifecycle_state="stopped",
            runtime_pid=None,
            daemon_generation=generation,
        )
        runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")


def _read_scenario_evidence(summary: dict[str, object], label: str):
    fixture = summary["fixture"]
    assert isinstance(fixture, dict)
    run_dir = Path(str(fixture["result_dir"])) / label
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    manifest_path = run_dir / "scenario-construction.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    reference = run["scenario_construction"]
    assert reference["sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert reference["artifact"] == f"{label}/scenario-construction.json"
    return run_dir, run, manifest


def test_preflight_accepts_explicit_owned_external_fixture(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path)

    context = runner.validate_preflight(options, environ=_stub_environ())

    assert context.project_root == options.project_root.resolve()
    assert context.ccb_test_path == (REPO_ROOT / "ccb_test").resolve()
    assert len(context.wrapper_sha256) == 64
    assert str(uuid.UUID(context.owner_uuid)) == context.owner_uuid


def test_scenario_identity_stable_double_read_rejects_authority_generation_mismatch(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path)
    context = runner.validate_preflight(options, environ=_stub_environ())
    _write_unmounted(options.project_root)
    lease_path = options.project_root / ".ccb" / "ccbd" / "lease.json"
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["generation"] += 1
    lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")

    identity = runner._capture_scenario_identity(context, benchmark_id="test-run")

    assert identity["status"] == "failed"
    assert "authority_records_inconsistent" in identity["reason_codes"]
    assert identity["consistency"]["authority_records"] == "inconsistent"
    assert identity["snapshot_consistency"]["status"] == "stable_double_read"


def test_preflight_rejects_source_runtime_override_even_falsey(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path)

    with pytest.raises(runner.SafetyError, match="CCB_SOURCE_RUNTIME_OK"):
        runner.validate_preflight(options, environ={"CCB_SOURCE_RUNTIME_OK": "0"})


def test_preflight_rejects_project_inside_source_checkout(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        project_root=REPO_ROOT,
        test_roots=(REPO_ROOT.parent,),
    )

    with pytest.raises(runner.SafetyError, match="project-root cannot be inside"):
        runner.validate_preflight(options, environ=_stub_environ())


def test_preflight_rejects_wrapper_from_another_tree(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path)
    foreign = options.project_root.parent / "foreign-source" / "ccb_test"
    foreign.parent.mkdir()
    foreign.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    options = runner.StartupBenchmarkOptions(**{**options.__dict__, "ccb_test_path": foreign})

    with pytest.raises(runner.SafetyError, match="same source checkout"):
        runner.validate_preflight(options, environ=_stub_environ())


def test_preflight_rejects_missing_or_mismatched_owner_marker(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path)
    marker_path = options.project_root / runner.OWNER_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["project_root"] = str(options.project_root.parent)
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(runner.SafetyError, match="project_root does not match"):
        runner.validate_preflight(options, environ=_stub_environ())


def test_preflight_rejects_home_overlap_and_nonrepeatable_scenarios(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, source_home=None)
    options = runner.StartupBenchmarkOptions(**{**options.__dict__, "source_home": options.project_root})
    with pytest.raises(runner.SafetyError, match="separate trees"):
        runner.validate_preflight(options, environ=_stub_environ())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("command_timeout_s", float("nan")),
        ("kill_timeout_s", float("inf")),
        ("stop_wait_s", float("nan")),
        ("report_wait_s", float("inf")),
    ),
)
def test_preflight_rejects_nonfinite_time_controls_before_mutation(
    runner,
    tmp_path: Path,
    field: str,
    value: float,
) -> None:
    options = _fixture_options(runner, tmp_path / field)
    options = runner.StartupBenchmarkOptions(**{**options.__dict__, field: value})

    with pytest.raises(runner.SafetyError, match="must be finite"):
        runner.validate_preflight(options, environ=_stub_environ())

    options = _fixture_options(runner, tmp_path / "second", scenario="partial", iterations=1, warmup=0)
    with pytest.raises(runner.SafetyError, match="partial scenario is unavailable"):
        runner.validate_preflight(options, environ=_stub_environ())


def test_benchmark_lock_is_nonblocking(runner, tmp_path: Path) -> None:
    context = runner.validate_preflight(_fixture_options(runner, tmp_path), environ=_stub_environ())

    with runner.benchmark_lock(context):
        with pytest.raises(runner.LockBusyError):
            with runner.benchmark_lock(context):
                pass


def test_atomic_artifact_write_fsyncs_file_and_parent_directory(
    runner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_directory_flags: list[bool] = []
    real_fsync = os.fsync

    def observing_fsync(fd: int) -> None:
        observed_directory_flags.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(runner.os, "fsync", observing_fsync)
    target = tmp_path / "artifacts" / "record.json"

    runner._write_bytes(target, b"{}\n")

    assert target.read_bytes() == b"{}\n"
    assert observed_directory_flags == [False, True]


def test_benchmark_env_forces_isolation_and_no_attach(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, launch_cap=1)
    context = runner.validate_preflight(options, environ=_stub_environ())

    env = runner._benchmark_env(
        options,
        context,
        environ={
            "HOME": "/live",
            "PYTEST_CURRENT_TEST": "x",
            "PATH": "/stub/bin",
            "CODEX_START_CMD": "/stub/bin/codex",
            "OPENAI_API_KEY": "must-not-leak",
            "CCB_SKIP_STARTUP_UPDATE_CHECK": "0",
        },
    )

    assert env["HOME"] == str(options.source_home.resolve())
    assert env["CCB_SOURCE_HOME"] == str(options.source_home.resolve())
    assert env["CCB_NO_ATTACH"] == "1"
    assert env["CODEX_START_CMD"] == "/stub/bin/codex"
    assert "OPENAI_API_KEY" not in env
    assert env["CCB_SKIP_STARTUP_UPDATE_CHECK"] == "1"
    assert "CCB_STARTUP_LAUNCH_CAP" not in env
    assert "CCB_SOURCE_RUNTIME_OK" not in env
    assert "PYTEST_CURRENT_TEST" not in env


def test_stub_preflight_requires_the_source_stub_and_sanitizes_session_roots(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path)

    with pytest.raises(runner.SafetyError, match="explicit CODEX_START_CMD"):
        runner.validate_preflight(options, environ={})
    with pytest.raises(runner.SafetyError, match="deterministic provider stub"):
        runner.validate_preflight(options, environ={"CODEX_START_CMD": "/usr/bin/true"})
    with pytest.raises(runner.SafetyError, match="does not identify configured provider"):
        runner.validate_preflight(
            options,
            environ={
                "CODEX_START_CMD": str(REPO_ROOT / "test" / "stubs" / "provider_stub.py")
            },
        )
    with pytest.raises(runner.SafetyError, match="does not identify configured provider"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(
                CODEX_START_CMD=(
                    f"{REPO_ROOT / 'test' / 'stubs' / 'provider_stub.py'} --provider claude"
                )
            ),
        )
    with pytest.raises(runner.SafetyError, match="provider options after --"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(
                CODEX_START_CMD=(
                    f"{REPO_ROOT / 'test' / 'stubs' / 'provider_stub.py'} "
                    "-- --provider codex"
                )
            ),
        )
    stub_path = REPO_ROOT / "test" / "stubs" / "provider_stub.py"
    codex_symlink = tmp_path / "codex"
    codex_symlink.symlink_to(stub_path)
    runner.validate_preflight(
        options,
        environ=_stub_environ(CODEX_START_CMD=str(codex_symlink)),
    )
    runner.validate_preflight(
        options,
        environ=_stub_environ(CODEX_START_CMD=f"{stub_path} --provider=codex"),
    )
    with pytest.raises(runner.SafetyError, match="invalid provider option"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(CODEX_START_CMD=f"{codex_symlink} --prov claude"),
        )
    with pytest.raises(runner.SafetyError, match="must not repeat --provider"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(
                CODEX_START_CMD=(
                    f"{stub_path} --provider codex --provider codex"
                )
            ),
        )
    with pytest.raises(runner.SafetyError, match="outside all allowed"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(STUB_LAUNCH_STATE_PATH="/tmp/not-owned-probe.json"),
        )

    context = runner.validate_preflight(
        options,
        environ=_stub_environ(CODEX_SESSION_ROOT="/home/bfly/.codex/sessions"),
    )
    env = runner._benchmark_env(
        options,
        context,
        environ=_stub_environ(CODEX_SESSION_ROOT="/home/bfly/.codex/sessions"),
    )
    assert "CODEX_SESSION_ROOT" not in env


def test_inherited_provider_environment_requires_explicit_mode(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, provider_env_mode="inherited")
    context = runner.validate_preflight(options, environ=_stub_environ())

    env = runner._benchmark_env(
        options,
        context,
        environ={"PATH": "/bin", "OPENAI_API_KEY": "explicitly-inherited"},
    )

    assert env["OPENAI_API_KEY"] == "explicitly-inherited"
    assert env["CCB_SKIP_STARTUP_UPDATE_CHECK"] == "1"


def test_preflight_rejects_unimplemented_parallel_launch_cap(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, launch_cap=3)

    with pytest.raises(runner.SafetyError, match="not implemented"):
        runner.validate_preflight(options, environ=_stub_environ())


def test_instrumentation_ab_requires_warm_scenario_and_valid_seed(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        instrumentation_mode="instrumentation-ab",
        instrumentation_ab_seed=7,
    )
    with pytest.raises(runner.SafetyError, match="supports only the warm scenario"):
        runner.validate_preflight(options, environ=_stub_environ())

    invalid_seed = _fixture_options(
        runner,
        tmp_path / "invalid-seed",
        instrumentation_mode="instrumentation-ab",
        instrumentation_ab_seed=-1,
    )
    with pytest.raises(runner.SafetyError, match="nonnegative 63-bit"):
        runner.validate_preflight(invalid_seed, environ=_stub_environ())


def test_instrumentation_ab_plan_is_seeded_balanced_and_reproducible(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        instrumentation_mode="instrumentation-ab",
        instrumentation_ab_seed=42,
        warmup=1,
        iterations=4,
    )
    context = runner.validate_preflight(options, environ=_stub_environ())

    first = runner._build_instrumentation_ab_plan(options, context=context, benchmark_id="ab")
    second = runner._build_instrumentation_ab_plan(options, context=context, benchmark_id="ab")

    assert first == second
    assert len(first["pairs"]) == 5
    assert all(set(pair["arm_order"]) == {"control", "instrumented"} for pair in first["pairs"])
    for left, right in zip(first["pairs"][::2], first["pairs"][1::2]):
        assert left["arm_order"] == list(reversed(right["arm_order"]))


def test_instrumentation_ab_pairs_control_and_profiled_arms_without_mixing_gates(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        instrumentation_mode="instrumentation-ab",
        instrumentation_ab_seed=7,
        warmup=0,
        iterations=1,
    )
    starts = 0
    clock_ns = 0

    def clock() -> int:
        nonlocal clock_ns
        clock_ns += 200_000_000
        return clock_ns

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def write_start(cwd: Path, *, instrumented: bool):
        nonlocal starts
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if not instrumented:
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["readiness_timeline"] = {}
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return run_id

    def profiled_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        del env, timeout_s, sample_interval_s, known_instances
        run_id = write_start(cwd, instrumented=True)
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=_raw_resource_profile(wall_ms=105.0),
            command_wall_ms=105.0,
            startup_process_trace_id="trace_" + "a" * 32,
        )

    def timed_control_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        del env, timeout_s, sample_interval_s, known_instances
        run_id = write_start(cwd, instrumented=False)
        return runner.CommandResult(
            tuple(argv),
            0,
            _control_startup_stdout(run_id),
            "",
            False,
            command_wall_ms=100.0,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=profiled_runner,
            control_start_command_runner=timed_control_runner,
            perf_counter_ns=clock,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["counts"]["successful"] == 1
    assert summary["counts"]["measured_commands_successful"] == 2
    ab = summary["instrumentation_ab"]
    assert ab["pairs_valid"] == 1
    assert ab["control_trust_gate"]["status"] == "pass"
    assert ab["instrumented_evidence_gate"]["status"] == "pass"
    assert ab["paired_delta_ms"]["p50"] == 5.0
    assert ab["overhead_gate"]["status"] == "smoke_only"
    assert summary["statistics_ms"]["p50"] == 105.0
    assert summary["control_statistics_ms"]["p50"] == 100.0
    assert summary["resource_gate"]["measured_profiles_expected"] == 1
    assert summary["readiness_gate"]["timelines_expected"] == 2  # prime + treatment
    result_dir = Path(summary["fixture"]["result_dir"])
    assert (result_dir / "benchmark-plan.json").is_file()
    control_dir = next(result_dir.glob("pair-*-control"))
    instrumented_dir = next(result_dir.glob("pair-*-instrumented"))
    assert not (control_dir / "resource-profile.json").exists()
    assert (instrumented_dir / "resource-profile.json").is_file()


def test_instrumentation_ab_trust_gates_reject_cross_arm_evidence(runner) -> None:
    control = {
        "status": "ok",
        "wall_ms": 100.0,
        "process_trace_id": "trace_" + "a" * 32,
        "process_bootstrap_timings_ms": {},
        "readiness_timeline": {},
        "readiness_ms": {},
        "resource_profile": {"status": "disabled_by_design"},
        "startup_report": {
            "validation": "ok",
            "native_run_id_available": True,
            "warm_reuse_identity": {},
        },
    }
    instrumented = {
        "status": "ok",
        "wall_ms": 105.0,
        "process_trace_id": None,
        "process_bootstrap_timings_ms": {},
        "readiness_timeline": {},
        "resource_profile": {},
        "startup_report": {
            "validation": "ok",
            "native_run_id_available": True,
            "warm_reuse_identity": {},
        },
    }

    assert "process_trace_present" in runner._control_arm_trust_reasons(control)
    reasons = runner._instrumented_arm_trust_reasons(instrumented)
    assert "process_trace_missing" in reasons
    assert "process_bootstrap_timings_incomplete" in reasons
    assert "readiness_incomplete" in reasons
    assert "resource_profile_not_correlated" in reasons


def test_bootstrap_median_ci_is_seeded_and_preserves_delta_sign(runner) -> None:
    first = runner._bootstrap_median_ci((4.0, 5.0, 6.0), seed=123, resamples=500)
    second = runner._bootstrap_median_ci((4.0, 5.0, 6.0), seed=123, resamples=500)

    assert first == second
    assert 4.0 <= first["lower_ms"] <= first["upper_ms"] <= 6.0


def test_summary_statistics_include_robust_dispersion(runner) -> None:
    summary = runner.summarize_samples([1.0, 2.0, 3.0, 4.0])

    assert summary["n"] == 4
    assert summary["min"] == 1.0
    assert summary["p50"] == 2.5
    assert summary["p90"] == pytest.approx(3.7)
    assert summary["p95"] == pytest.approx(3.85)
    assert summary["max"] == 4.0
    assert summary["mean"] == 2.5
    assert summary["stddev"] == pytest.approx(1.11803398875)
    assert summary["mad"] == 1.0
    assert summary["iqr"] == 1.5
    assert summary["cv"] == pytest.approx(0.4472135955)


def test_cli_only_primes_once_then_measures_unchanged_report(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=1,
        iterations=2,
    )
    calls: list[tuple[str, ...]] = []
    cli_envs: list[dict[str, str]] = []
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del timeout_s
        command = tuple(argv)
        calls.append(command)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        if command[-1] == "--print-version":
            cli_envs.append(dict(env))
            return runner.CommandResult(command, 0, _cli_only_stdout(), "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert starts == 1
    assert [Path(command[-1]).name for command in calls] == [
        "kill",
        "ccb_test",
        "--print-version",
        "--print-version",
        "--print-version",
        "kill",
    ]
    assert all(
        not runner._stub_launch_environment_key(key)
        for env in cli_envs
        for key in env
    )
    assert summary["readiness_gate"] == {
        "status": "not_applicable_cli_only",
        "reason": "no_startup_transaction_in_measured_command",
        "timelines_expected": 0,
        "timelines_present": 0,
        "timelines_complete": 0,
        "prime_startup_timeline_excluded": True,
    }
    assert summary["report_correlation"]["native_run_id_required"] is False
    assert summary["report_correlation"]["native_run_id_runs"] == 1
    assert summary["report_correlation"]["startup_command_runs"] == 1
    assert summary["report_correlation"]["cli_only_command_runs"] == 3
    assert summary["report_correlation"]["cli_only_unchanged_report_runs"] == 3
    assert summary["cleanup"]["pre_teardown_preservation"]["status"] == "pass"
    assert summary["scenario_construction_gate"]["by_scenario"] == {
        "S0": {"present": 4, "passed": 4, "failed": 0}
    }

    result_dir = Path(summary["fixture"]["result_dir"])
    prime = json.loads((result_dir / "prime-0001" / "run.json").read_text(encoding="utf-8"))
    prime_id = prime["startup_report"]["startup_run_id"]
    assert prime_id
    for label in ("warmup-0001", "run-0001", "run-0002"):
        run_dir, run, manifest = _read_scenario_evidence(summary, label)
        assert run["measurement_kind"] == "cli_only"
        assert run["command"][-1] == "--print-version"
        assert run["startup_report"]["startup_run_id"] is None
        assert run["startup_report"]["bytes_unchanged"] is True
        assert run["startup_report"]["snapshot_role"] == "preexisting_unchanged_sentinel"
        assert (run_dir / "startup-report-sentinel.json").is_file()
        assert not (run_dir / "startup-report.json").exists()
        assert manifest["scenario"]["id"] == "S0"
        assert manifest["observation"]["relations"] == {
            "daemon_generation": "same",
            "daemon_identity_digest": "same",
            "namespace_identity_digest": "same",
            "agent_runtime_identity_digest": "same",
            "startup_report_identity": "same",
        }
        sentinel = json.loads(
            (run_dir / "startup-report-sentinel.json").read_text(encoding="utf-8")
        )
        assert sentinel["startup_run_id"] == prime_id


@pytest.mark.parametrize("transition", ["rewrite_same_bytes", "change_content", "delete"])
def test_cli_only_rejects_any_report_transition(
    runner,
    tmp_path: Path,
    transition: str,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=2,
    )
    version_calls = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal version_calls
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        if command[-1] != "--print-version":
            run_id = _write_mounted_round(
                cwd,
                sequence=1,
                action="launched",
                daemon_started=True,
            )
            return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)
        version_calls += 1
        report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
        original = report_path.read_bytes()
        if transition == "rewrite_same_bytes":
            report_path.write_bytes(original)
            file_stat = report_path.stat()
            os.utime(
                report_path,
                ns=(file_stat.st_atime_ns, file_stat.st_mtime_ns + 1_000_000_000),
            )
        elif transition == "change_content":
            report = json.loads(original)
            report["sequence_for_test"] = 999
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        else:
            report_path.unlink()
        return runner.CommandResult(command, 0, _cli_only_stdout(), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert version_calls == 1
    assert summary["counts"]["completed"] == 1
    assert "startup report sentinel" in summary["abort_reason"]
    run = json.loads(
        (
            Path(summary["fixture"]["result_dir"])
            / "run-0001"
            / "run.json"
        ).read_text(encoding="utf-8")
    )
    assert run["startup_report"]["startup_run_id"] is None
    assert run["status"] == "failed"


def test_cli_only_rejects_startup_metadata_in_stdout(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=1,
    )

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        if command[-1] == "--print-version":
            return runner.CommandResult(
                command,
                0,
                _cli_only_stdout() + f"startup_run_id: start_{'f' * 32}\n",
                "",
                False,
            )
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "unexpected startup metadata" in summary["abort_reason"]
    assert summary["report_correlation"]["native_run_id_runs"] == 1
    assert summary["report_correlation"]["cli_only_command_runs"] == 1


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("health", "failed", "healthy_active_runtime_record_count_mismatch"),
        ("health", "degraded", "healthy_active_runtime_record_count_mismatch"),
        ("reconcile_state", "recovering", "steady_active_runtime_record_count_mismatch"),
    ],
)
def test_cli_only_requires_strict_healthy_mounted_baseline(
    runner,
    tmp_path: Path,
    field: str,
    value: str,
    expected_reason: str,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=1,
    )
    version_calls = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal version_calls
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        if command[-1] == "--print-version":
            version_calls += 1
            return runner.CommandResult(command, 0, _cli_only_stdout(), "", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        runtime_path = cwd / ".ccb" / "agents" / "agent1" / "runtime.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime[field] = value
        runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert version_calls == 0
    assert expected_reason in summary["abort_reason"]


def test_cli_only_accepts_restored_as_a_success_runtime_health(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path, scenario="cli-only")
    context = runner.validate_preflight(options, environ=_stub_environ())
    _write_mounted_round(
        options.project_root,
        sequence=1,
        action="launched",
        daemon_started=True,
    )
    runtime_path = options.project_root / ".ccb" / "agents" / "agent1" / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["health"] = "restored"
    runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")

    identity = runner._capture_scenario_identity(context, benchmark_id="restored-health")
    reasons = runner._cli_only_identity_reason_codes(
        identity,
        configured_agent_count=1,
        baseline=None,
        phase="test",
    )

    assert identity["runtime"]["healthy_active_runtime_record_count"] == 1
    assert identity["runtime_slots"][0]["healthy"] is True
    assert reasons == []


def test_cli_only_command_failure_stops_and_preserves_report(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=2,
    )
    version_calls = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal version_calls
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        if command[-1] == "--print-version":
            version_calls += 1
            return runner.CommandResult(command, 23, "", "version failed", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert version_calls == 1
    assert "cli-only command exited with status 23" in summary["abort_reason"]
    assert summary["cleanup"]["pre_teardown_preservation"]["status"] == "pass"
    run = json.loads(
        (
            Path(summary["fixture"]["result_dir"])
            / "run-0001"
            / "run.json"
        ).read_text(encoding="utf-8")
    )
    assert run["startup_report"]["bytes_unchanged"] is True
    assert run["startup_report"]["startup_run_id"] is None


def test_cli_only_resource_profile_correlates_without_startup_run_id(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=1,
    )
    starts = 0

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def profiled_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        nonlocal starts
        del env, timeout_s, sample_interval_s, known_instances
        command = tuple(argv)
        if command[-1] == "--print-version":
            return runner.CommandResult(
                command,
                0,
                _cli_only_stdout(),
                "",
                False,
                resource_profile=_raw_resource_profile(wall_ms=0.0),
                tracked_process_instances=((900_001, 101),),
                active_process_instances=(),
                command_wall_ms=0.0,
                startup_process_trace_id=None,
            )
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
            exact_t1=True,
        )
        return runner.CommandResult(
            command,
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=_raw_resource_profile(wall_ms=0.0),
            tracked_process_instances=((900_000, 100),),
            active_process_instances=((900_000, 100),),
            command_wall_ms=0.0,
            startup_process_trace_id="trace_" + "a" * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=profiled_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["resource_gate"]["status"] == "pass"
    assert summary["resource_gate"]["profiles_expected"] == 1
    assert summary["resource_gate"]["profiles_verified"] == 1
    assert summary["readiness_gate"]["status"] == "not_applicable_cli_only"
    run = json.loads(
        (
            Path(summary["fixture"]["result_dir"])
            / "run-0001"
            / "run.json"
        ).read_text(encoding="utf-8")
    )
    correlation = run["resource_profile"]["correlation"]
    assert correlation["status"] == "verified"
    assert correlation["stdout_startup_run_id"] is None
    assert correlation["report_startup_run_id"] is None
    assert correlation["cli_only_report_unchanged"] is True
    assert correlation["cli_only_authority_token"]
    assert run["resource_profile"]["quality"]["formal_eligible"] is True


def test_cli_only_resource_profile_rejects_more_than_one_observed_created_process(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        warmup=0,
        iterations=1,
    )

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def profiled_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        del env, timeout_s, sample_interval_s, known_instances
        command = tuple(argv)
        profile = _raw_resource_profile(wall_ms=0.0)
        if command[-1] == "--print-version":
            profile["metrics"]["created_process_instance_count"] = 2
            return runner.CommandResult(
                command,
                0,
                _cli_only_stdout(),
                "",
                False,
                resource_profile=profile,
                command_wall_ms=0.0,
            )
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
            exact_t1=True,
        )
        return runner.CommandResult(
            command,
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=profile,
            command_wall_ms=0.0,
            startup_process_trace_id="trace_" + "a" * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=profiled_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert (
        "observe exactly one newly created process identity across sampled snapshots"
        in summary["abort_reason"]
    )


def test_cli_only_command_surface_and_profile_trace_policy(
    runner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="cli-only",
        restore_policy="fresh",
    )
    context = runner.validate_preflight(options, environ=_stub_environ())
    measured = runner._start_command(options, context, round_role="measured")
    prime = runner._start_command(options, context, round_role="prime")

    assert measured == (sys.executable, str(context.ccb_test_path), "--print-version")
    assert "-n" not in measured
    assert prime == (sys.executable, str(context.ccb_test_path), "-n")
    assert runner._is_cli_only_command(measured) is True
    assert runner._is_cli_only_command(prime) is False

    trace_flags: list[bool] = []

    class Outcome:
        def __init__(self, argv, trace: bool):
            self.argv = tuple(argv)
            self.returncode = 0
            self.stdout = _cli_only_stdout() if not trace else ""
            self.stderr = ""
            self.timed_out = False
            self.resource_profile = {
                "window": {"command_wall_ms": 1.0},
            }
            self.tracked_process_instances = ()
            self.active_process_instances = ()
            self.startup_timing_trace_id = "trace_" + "a" * 32 if trace else None

    def fake_profiled(argv, cwd, env, timeout_s, **kwargs):
        del cwd, env, timeout_s
        trace = bool(kwargs["startup_timing_trace"])
        trace_flags.append(trace)
        return Outcome(argv, trace)

    monkeypatch.setattr(runner, "run_profiled_command", fake_profiled)
    cli_result = runner._default_start_command_runner(
        measured,
        context.project_root,
        {},
        1.0,
        0.01,
        (),
    )
    startup_result = runner._default_start_command_runner(
        prime,
        context.project_root,
        {},
        1.0,
        0.01,
        (),
    )

    assert trace_flags == [False, True]
    assert cli_result.startup_process_trace_id is None
    assert startup_result.startup_process_trace_id == "trace_" + "a" * 32


def test_warmup_is_excluded_and_each_round_snapshots_report(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=2, iterations=3)
    calls: list[tuple[str, ...]] = []
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        calls.append(tuple(argv))
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "stopped", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    deps = runner.BenchmarkDependencies(command_runner=fake_run)
    summary = runner.run_startup_benchmark(options, dependencies=deps, environ=_stub_environ())

    assert summary["status"] == "ok"
    assert summary["counts"] == {
        "requested": 3,
        "completed": 3,
        "successful": 3,
        "failures": 0,
        "timeouts": 0,
        "warmups_completed": 2,
        "prime_completed": 1,
    }
    assert summary["statistics_ms"]["n"] == 3
    assert starts == 6
    assert len(calls) == 8
    assert calls[0][-1] == "kill"
    assert calls[-1][-1] == "kill"
    assert summary["cleanup"]["status"] == "ok"
    result_dir = Path(summary["fixture"]["result_dir"])
    assert (result_dir / "summary.json").is_file()
    for label in ("prime-0001", "warmup-0001", "warmup-0002", "run-0001", "run-0002", "run-0003"):
        run_dir = result_dir / label
        assert (run_dir / "run.json").is_file()
        assert (run_dir / "startup-report.json").is_file()
    first_run = json.loads((result_dir / "run-0001" / "run.json").read_text(encoding="utf-8"))
    assert first_run["startup_report"]["validation"] == "ok"
    assert first_run["startup_report"]["native_run_id_available"] is True
    gate = summary["scenario_construction_gate"]
    assert gate["status"] == "pass"
    assert gate["manifests_expected"] == 6
    assert gate["manifests_present"] == 6
    assert gate["manifests_valid"] == 6
    assert gate["manifests_passed"] == 6
    assert gate["by_scenario"] == {
        "S1": {"present": 6, "passed": 6, "failed": 0}
    }
    for label in (
        "prime-0001",
        "warmup-0001",
        "warmup-0002",
        "run-0001",
        "run-0002",
        "run-0003",
    ):
        scenario_dir, _run, manifest = _read_scenario_evidence(summary, label)
        assert (scenario_dir / "scenario-construction.before.json").is_file()
        assert (scenario_dir / "scenario-construction.ready.json").is_file()
        assert manifest["scenario"]["id"] == "S1"
        assert manifest["validation"] == {"status": "pass", "reason_codes": []}
        assert manifest["audit_phase"]["name"] == "final"
        assert set(manifest["phase_chain"]) == {"before", "ready"}
    measured_manifest = _read_scenario_evidence(summary, "run-0001")[2]
    assert measured_manifest["observation"]["relations"] == {
        "daemon_generation": "same",
        "daemon_identity_digest": "same",
        "namespace_identity_digest": "same",
        "agent_runtime_identity_digest": "same",
    }
    assert summary["warm_priming"]["status"] == "ok"
    assert summary["qualification"] == "smoke_only"
    assert "warmups_below_formal_minimum:2<3" in summary["qualification_reasons"]


def test_stale_report_fails_closed_and_stops_following_rounds(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=3)
    calls = 0
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal calls, starts
        del env, timeout_s
        calls += 1
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        if starts == 1:
            run_id = _write_mounted_round(
                cwd,
                sequence=starts,
                action="launched",
                daemon_started=True,
            )
            return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(f"start_{starts:032x}"), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert summary["counts"]["failures"] == 1
    assert summary["counts"]["completed"] == 1
    assert calls == 4  # reset, prime, one failed measured start, final cleanup
    assert "not created or updated" in summary["abort_reason"]


def test_duplicate_native_run_id_across_rounds_fails_closed(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            repeated = "start_" + f"{1:032x}"
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["startup_run_id"] = repeated
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
            run_id = repeated
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "duplicate startup_run_id" in summary["abort_reason"]
    _run_dir, run, manifest = _read_scenario_evidence(summary, "run-0001")
    assert run["status"] == "failed"
    assert manifest["validation"]["status"] == "failed"
    assert "startup_record_not_ok" in manifest["validation"]["reason_codes"]
    assert run["scenario_construction"]["status"] == "failed"


def test_owner_marker_drift_aborts_and_skips_cleanup_mutation(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        commands.append(command)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        marker_path = cwd / runner.OWNER_MARKER_NAME
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["owner_uuid"] = str(uuid.uuid4())
        marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert len(commands) == 1
    assert summary["status"] == "incomplete"
    assert "owner marker changed" in summary["abort_reason"]
    assert summary["cleanup"]["status"] == "skipped"


def test_unexpected_start_spawn_error_still_runs_official_cleanup_and_audits_failure(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        commands.append(command)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "", "", False)
        raise OSError("simulated subprocess creation failure")

    with pytest.raises(OSError, match="simulated subprocess creation failure"):
        runner.run_startup_benchmark(
            options,
            dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
            environ=_stub_environ(),
        )

    assert [command[-1] == "kill" for command in commands] == [False, True]
    result_dir = options.result_root / "test-run"
    failure = json.loads((result_dir / "failure.json").read_text(encoding="utf-8"))
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == "OSError"
    assert failure["cleanup"]["status"] == "ok"
    assert summary["status"] == "incomplete"
    assert summary["cleanup"]["purpose"] == "final_cleanup"
    assert summary["cleanup"]["status"] == "ok"
    scenario_dir = result_dir / "run-0001"
    assert (scenario_dir / "scenario-construction.before.json").is_file()
    assert (scenario_dir / "scenario-construction.ready.json").is_file()
    scenario = json.loads(
        (scenario_dir / "scenario-construction.json").read_text(encoding="utf-8")
    )
    assert scenario["audit_phase"]["name"] == "ready"
    assert scenario["validation"]["status"] == "ready_for_measurement"
    assert scenario["observation"]["status"] == "pending"
    gate = summary["scenario_construction_gate"]
    assert gate["status"] == "missing"
    assert gate["orphan_attempt_directories"] == 1
    assert "scenario_manifest_orphan_attempt" in gate["reason_codes"]


def test_report_identity_mismatch_is_preserved_as_failed_artifact(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        run_id = _write_mounted_round(cwd, sequence=1, action="launched", daemon_started=True)
        lease_path = cwd / ".ccb" / "ccbd" / "lease.json"
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        lease["generation"] = 8
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "daemon_generation does not match ccbd lease" in summary["abort_reason"]
    run_dir = Path(summary["fixture"]["result_dir"]) / "run-0001"
    assert (run_dir / "startup-report.json").is_file()
    assert json.loads((run_dir / "run.json").read_text())["startup_report"]["validation"] == "failed"


def test_native_run_id_and_cli_stage_timings_are_correlated_and_aggregated(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    run_id = "start_" + "a" * 32

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        _write_mounted_round(
            cwd,
            sequence=12,
            action="launched",
            daemon_started=True,
            supervisor_total=0.0,
        )
        report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["startup_run_id"] = run_id
        report["readiness_timeline"]["startup_run_id"] = run_id
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        stdout = _startup_stdout(run_id, cli_pre_rpc=0.0, start_rpc=0.0, cli_total=0.0)
        return runner.CommandResult(tuple(argv), 0, stdout, "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["report_correlation"]["native_run_id_available"] is True
    assert summary["report_correlation"]["native_run_id_runs"] == 1
    assert summary["cli_stage_statistics_ms"]["cli_total"]["p50"] == 0.0
    assert summary["supervisor_stage_statistics_ms"]["supervisor_total"]["p95"] == 0.0
    run = json.loads(
        (Path(summary["fixture"]["result_dir"]) / "run-0001" / "run.json").read_text(encoding="utf-8")
    )
    assert run["startup_report"]["startup_run_id"] == run_id
    assert run["derived_timings_ms"]["external_minus_cli_total"] is not None
    assert run["derived_timings_ms"]["external_minus_supervisor_total"] is not None


def test_stdout_and_report_run_id_mismatch_rejects_sample(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    report_run_id = "start_" + "a" * 32
    stdout_run_id = "start_" + "b" * 32

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        _write_mounted_round(cwd, sequence=1, action="launched", daemon_started=True)
        report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["startup_run_id"] = report_run_id
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        stdout = _startup_stdout(stdout_run_id)
        return runner.CommandResult(tuple(argv), 0, stdout, "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "does not match" in summary["abort_reason"]


def test_current_source_stdout_requires_native_run_id_and_all_cli_timing_keys(runner) -> None:
    with pytest.raises(runner.ReportValidationError, match="exactly one startup_run_id"):
        runner._parse_start_stdout("start_status: ok\n")

    run_id = "start_" + "a" * 32
    with pytest.raises(runner.ReportValidationError, match="missing required keys"):
        runner._parse_start_stdout(
            f"startup_run_id: {run_id}\n"
            'startup_cli_timings_ms: {"cli_total":0.0}\n'
        )


def test_stdout_process_trace_requires_correlated_pair_and_valid_durations(runner) -> None:
    run_id = "start_" + "a" * 32
    stdout = _startup_stdout(run_id)

    parsed = runner._parse_start_stdout(stdout)

    assert parsed[2] == "trace_" + "a" * 32
    assert set(parsed[3] or {}) == set(runner.PROCESS_BOOTSTRAP_TIMING_KEYS)
    with pytest.raises(runner.ReportValidationError, match="must be emitted together"):
        runner._parse_start_stdout(
            stdout.replace(
                "startup_process_bootstrap_timings_ms: ",
                "ignored_process_bootstrap_timings_ms: ",
            )
        )


def test_stdout_cli_phase_partitions_must_be_contained_by_their_parent(runner) -> None:
    run_id = "start_" + "a" * 32

    with pytest.raises(runner.ReportValidationError, match="non-contained CLI phases"):
        runner._parse_start_stdout(
            _startup_stdout(run_id, cli_pre_rpc=2.0, cli_total=1.0)
        )
    with pytest.raises(runner.ReportValidationError, match="non-contained post-RPC phases"):
        runner._parse_start_stdout(
            _startup_stdout(
                run_id,
                cli_post_rpc=1.0,
                sidebar_helper_refresh=0.5,
                layout_status=0.5,
                maintenance_heartbeat=0.5,
                cli_total=2.0,
            )
        )


def test_process_bootstrap_derived_math_and_external_coverage_are_non_overlapping(runner) -> None:
    process_timings = {
        key: value
        for key, value in zip(runner.PROCESS_BOOTSTRAP_TIMING_KEYS, (1.0, 2.0, 3.0, 4.0, 5.0))
    }
    cli_timings = {"cli_total": 20.0}

    derived = runner._derived_timings(
        wall_ms=40.0,
        cli_timings_ms=cli_timings,
        process_bootstrap_timings_ms=process_timings,
        report=None,
    )
    attribution = runner._attribution_record(
        wall_ms=40.0,
        cli_timings_ms=cli_timings,
        process_bootstrap_timings_ms=process_timings,
        report=None,
    )

    assert derived["process_bootstrap_total"] == 15.0
    assert derived["post_cli_residual"] == 5.0
    assert derived["external_minus_cli_total"] == 20.0
    assert attribution["external"]["named_ms"] == 35.0
    assert attribution["external"]["unattributed_ms"] == 5.0
    assert attribution["external"]["coverage"] == pytest.approx(0.875)


def test_legacy_readiness_estimates_are_not_published_as_same_origin_milestones(runner) -> None:
    readiness = runner._derived_readiness_ms(
        cli_timings_ms={"cli_pre_rpc": 1.0, "daemon_ensure": 2.0},
        process_bootstrap_timings_ms={key: 1.0 for key in runner.PROCESS_BOOTSTRAP_TIMING_KEYS},
        report={"timings_ms": {"namespace_ensure": 3.0, "context_and_layout_plan": 1.0}},
    )

    assert readiness["T0_cli_entry"] == 0.0
    assert readiness["T2_control_plane_ready"] is None
    assert readiness["T3_namespace_attachable"] is None
    assert readiness["T5_foreground_attached"] is None
    assert readiness["point_states"]["T5_foreground_attached"] == "not_applicable_no_attach"
    assert readiness["timeline_complete"] is False


def test_readiness_timeline_validator_accepts_correlated_complete_record(
    runner, tmp_path: Path
) -> None:
    run_id = _write_mounted_round(tmp_path, sequence=31, daemon_started=True)
    report = json.loads(
        (tmp_path / ".ccb" / "ccbd" / "startup-report.json").read_text(encoding="utf-8")
    )

    validated = runner._validate_readiness_timeline(
        report["readiness_timeline"],
        startup_run_id=run_id,
        stdout_process_trace_id="trace_" + "a" * 32,
        daemon_generation=report["daemon_generation"],
        desired_agents=report["desired_agents"],
        command_wall_ms=10.0,
        require_complete=True,
    )

    assert validated["timeline_complete"] is True
    assert validated["points"]["T4_requested_agents_ready"]["agents"] == ["agent1"]
    durations = runner._readiness_point_durations(validated)
    assert durations["T1_lifecycle_intent"] is None
    assert durations["T1_lifecycle_intent_upper_bound"] == 0.0


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("trace", "trace_id does not match"),
        ("run", "startup_run_id correlation mismatch"),
        ("generation", "daemon generation correlation mismatch"),
        ("order", "T2/RPC/T3/T4/T6 order is invalid"),
        ("scope", "T4 Agent scope mismatch"),
        ("t1_status", "T1_lifecycle_intent has invalid provenance"),
        ("source", "milestone provenance mismatch"),
        ("t1_bound", "upper bound must share T2 observation"),
        ("keeper", "lacks keeper startup id"),
        ("wall", "exceeds foreground command wall"),
        ("extra_point", "unknown points"),
    ),
)
def test_readiness_timeline_validator_rejects_broken_correlation_or_order(
    runner,
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    run_id = _write_mounted_round(tmp_path, sequence=32, daemon_started=True)
    report = json.loads(
        (tmp_path / ".ccb" / "ccbd" / "startup-report.json").read_text(encoding="utf-8")
    )
    timeline = report["readiness_timeline"]
    stdout_trace_id = "trace_" + "a" * 32
    expected_run_id = run_id
    if case == "trace":
        stdout_trace_id = "trace_" + "b" * 32
    elif case == "run":
        expected_run_id = "start_" + "f" * 32
    elif case == "generation":
        timeline["expected_daemon_generation"] += 1
    elif case == "order":
        timeline["points"]["T4_requested_agents_ready"]["elapsed_ms"] = 5.0
        timeline["points"]["T6_fully_warm"]["elapsed_ms"] = 4.0
    elif case == "scope":
        timeline["points"]["T4_requested_agents_ready"]["agents"] = []
    elif case == "t1_status":
        timeline["points"]["T1_lifecycle_intent"]["status"] = "failed_before_ready"
    elif case == "source":
        timeline["points"]["T0_cli_entry"]["source"] = "forged"
    elif case == "t1_bound":
        timeline["points"]["T2_control_plane_ready"]["elapsed_ms"] = 0.02
        timeline["rpc_accepted_ms"] = 0.02
        for name in (
            "T3_namespace_attachable",
            "T4_requested_agents_ready",
            "T6_fully_warm",
        ):
            timeline["points"][name]["elapsed_ms"] = 0.02
    elif case == "keeper":
        timeline["keeper_startup_id"] = None
    elif case == "wall":
        timeline["points"]["T6_fully_warm"]["elapsed_ms"] = 11.0
    elif case == "extra_point":
        timeline["points"]["T7_unknown"] = {
            "status": "reached",
            "elapsed_ms": 6.0,
            "source": "test",
            "agents": [],
        }

    with pytest.raises(runner.ReportValidationError, match=message):
        runner._validate_readiness_timeline(
            timeline,
            startup_run_id=expected_run_id,
            stdout_process_trace_id=stdout_trace_id,
            daemon_generation=report["daemon_generation"],
            desired_agents=report["desired_agents"],
            command_wall_ms=10.0,
            require_complete=True,
        )


def test_current_source_report_requires_native_run_id(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    run_id = _write_mounted_round(
        options.project_root,
        sequence=1,
        action="launched",
        daemon_started=True,
    )
    report_path = options.project_root / ".ccb" / "ccbd" / "startup-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.pop("startup_run_id")
    now = datetime.now(timezone.utc)

    with pytest.raises(runner.ReportValidationError, match="invalid startup_run_id"):
        runner._validate_startup_report(
            report,
            before=None,
            after=runner._file_identity(report_path),
            started_utc=now,
            ended_utc=now,
            project_root=options.project_root,
            command_succeeded=True,
            stdout_run_id=run_id,
            expected_config_signature="config-signature",
            expected_daemon_generation=None,
            expected_daemon_started=True,
            expected_agent_count=1,
            expected_provider_counts={"codex": 1},
            require_cold_launch=True,
        )


def test_report_schema_timings_and_agent_substage_sum_are_strict(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    run_id = _write_mounted_round(
        options.project_root,
        sequence=1,
        action="launched",
        daemon_started=True,
    )
    report_path = options.project_root / ".ccb" / "ccbd" / "startup-report.json"
    base = json.loads(report_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    common = {
        "before": None,
        "after": runner._file_identity(report_path),
        "started_utc": now,
        "ended_utc": now,
        "project_root": options.project_root,
        "command_succeeded": True,
        "stdout_run_id": run_id,
        "expected_config_signature": "config-signature",
        "expected_daemon_generation": None,
        "expected_daemon_started": True,
        "expected_agent_count": 1,
        "expected_provider_counts": {"codex": 1},
        "require_cold_launch": True,
    }

    wrong_schema = dict(base, api_version=1)
    with pytest.raises(runner.ReportValidationError, match="api_version"):
        runner._validate_startup_report(wrong_schema, **common)

    bad_duration = json.loads(json.dumps(base))
    bad_duration["timings_ms"]["supervisor_total"] = float("nan")
    with pytest.raises(runner.ReportValidationError, match="finite non-negative"):
        runner._validate_startup_report(bad_duration, **common)

    excessive = json.loads(json.dumps(base))
    excessive["agent_results"][0]["duration_ms"] = 1.0
    excessive["agent_results"][0]["timings_ms"]["build_start_cmd"] = 0.75
    excessive["agent_results"][0]["timings_ms"]["tmux_respawn"] = 0.75
    with pytest.raises(runner.ReportValidationError, match="substage sum exceeds"):
        runner._validate_startup_report(excessive, **common)

    missing_agents = json.loads(json.dumps(base))
    missing_agents["agent_results"] = []
    with pytest.raises(runner.ReportValidationError, match="not a bijection"):
        runner._validate_startup_report(missing_agents, **common)


def test_pristine_sample_requires_a_new_daemon_and_launch_outcomes(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="attached",
            daemon_started=False,
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "daemon_started does not match" in summary["abort_reason"]


def test_warm_sample_rejects_relaunch_after_current_source_prime(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        action = "launched" if starts == 1 else "relaunched"
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action=action,
            daemon_started=(starts == 1),
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "did not reuse an existing binding" in summary["abort_reason"]
    assert summary["warm_priming"]["status"] == "ok"


def test_warm_sample_rejects_provider_preparation_even_if_action_claims_reuse(runner) -> None:
    report = {
        "daemon_started": False,
        "desired_agents": ["agent1"],
        "agent_results": [
            {
                "agent_name": "agent1",
                "action": "attached",
                "provider_prepare_count": 1,
            }
        ],
        "actions_taken": ["reuse_binding:agent1"],
        "operation_counts": {"provider_prepare_count": 1},
    }

    with pytest.raises(runner.ReportValidationError, match="performed provider preparation"):
        runner._validate_warm_reuse_report(report)


def test_warm_sample_rejects_daemon_generation_drift_after_prime(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            ccbd = cwd / ".ccb" / "ccbd"
            for name in ("startup-report.json", "lease.json", "lifecycle.json"):
                path = ccbd / name
                payload = json.loads(path.read_text(encoding="utf-8"))
                if name == "startup-report.json":
                    payload["daemon_generation"] = 8
                else:
                    payload["generation"] = 8
                path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "daemon_generation changed after priming" in summary["abort_reason"]
    assert summary["fixture"]["warm_daemon_generation"] == 7


def test_warm_sample_rejects_namespace_epoch_drift_after_prime(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            state_path = cwd / ".ccb" / "ccbd" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["namespace_epoch"] = 4
            state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["actions_taken"][0] = "ensure_namespace:epoch=4,session=ccb-project-test"
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "namespace_epoch" in summary["abort_reason"]


def test_warm_sample_rejects_agent_identity_drift(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["agent_results"][0]["pane_id"] = "%9"
            report["agent_results"][0]["active_pane_id"] = "%9"
            report["agent_results"][0]["runtime_ref"] = "tmux:%9"
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "pane_id" in summary["abort_reason"] or "runtime_ref" in summary["abort_reason"]


def test_warm_sample_rejects_dead_runtime_after_prime(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["agent_results"][0]["runtime_pid"] = 2_000_000_000
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "is not alive" in summary["abort_reason"]


def test_warm_sample_rejects_cmd_or_sidebar_topology_drift(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        if starts == 2:
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["cleanup_summaries"][0]["owned_panes"].append("%9")
            report["cleanup_summaries"][0]["active_panes"].append("%9")
            report["operation_counts"]["orphan_cleanup_owned_pane_count"] = 3
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "pane_topology" in summary["abort_reason"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("action", "mutating action"),
        ("timing", "launch-only work"),
    ],
)
def test_warm_sample_rejects_mutating_actions_and_launch_stages(
    runner,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    options = _fixture_options(runner, tmp_path)
    _write_mounted_round(
        options.project_root,
        sequence=1,
        action="attached",
        daemon_started=False,
    )
    report = json.loads(
        (options.project_root / ".ccb" / "ccbd" / "startup-report.json").read_text(
            encoding="utf-8"
        )
    )
    if mutation == "action":
        report["actions_taken"].append("bootstrap_cmd_pane:%8")
    else:
        report["agent_results"][0]["timings_ms"]["tmux_respawn"] = 0.01

    with pytest.raises(runner.ReportValidationError, match=message):
        runner._validate_warm_reuse_report(report)


def test_warm_prime_requires_complete_live_reuse_baseline(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        (cwd / ".ccb" / "ccbd" / "state.json").unlink()
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "project namespace state" in summary["abort_reason"]


def test_warm_prime_reset_failure_never_attempts_start_or_second_cleanup(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del cwd, env, timeout_s
        command = tuple(argv)
        commands.append(command)
        return runner.CommandResult(command, 9, "", "reset failed", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert len(commands) == 1
    assert commands[0][-1] == "kill"
    assert summary["status"] == "incomplete"
    assert summary["warm_priming"]["status"] == "failed"
    assert summary["cleanup"]["status"] == "skipped"
    prime_dir, _run, manifest = _read_scenario_evidence(summary, "prime-0001")
    assert (prime_dir / "scenario-construction.before.json").is_file()
    assert (prime_dir / "scenario-construction.ready.json").is_file()
    assert manifest["validation"]["status"] == "failed"
    assert "official_kill_precondition_failed" in manifest["validation"]["reason_codes"]
    gate = summary["scenario_construction_gate"]
    assert gate["status"] == "failed"
    assert gate["manifests_valid"] == 1
    assert gate["manifests_failed"] == 1


def test_warm_prime_persists_pre_kill_before_phase_and_complete_constructor_chain(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path, warmup=0, iterations=1)
    _write_mounted_round(
        options.project_root,
        sequence=99,
        action="launched",
        daemon_started=True,
    )
    starts = 0
    kills = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts, kills
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            kills += 1
            if kills == 1:
                prime_dir = options.result_root / "test-run" / "prime-0001"
                before_path = prime_dir / "scenario-construction.before.json"
                current_path = prime_dir / "scenario-construction.json"
                assert before_path.is_file()
                assert current_path.is_file()
                before = json.loads(before_path.read_text(encoding="utf-8"))
                current = json.loads(current_path.read_text(encoding="utf-8"))
                assert before["audit_phase"] == {
                    "name": "before",
                    "predecessor_sha256": None,
                }
                assert before["before"]["authority"]["lifecycle"]["phase"] == "mounted"
                assert current["audit_phase"]["name"] == "before"
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert starts == 2
    prime = _read_scenario_evidence(summary, "prime-0001")[2]
    assert prime["before"]["authority"]["lifecycle"]["phase"] == "mounted"
    assert prime["ready_for_measurement"]["authority"]["lifecycle"]["phase"] == "unmounted"
    assert prime["observation"]["after"]["authority"]["lifecycle"]["phase"] == "mounted"
    assert prime["observation"]["relations"]["daemon_generation"] == "changed"


def test_config_file_hash_and_formal_report_signature_are_frozen(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="full-cold", warmup=0, iterations=2)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
        )
        if starts == 2:
            report_path = cwd / ".ccb" / "ccbd" / "startup-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["config_signature"] = "different-signature"
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
            for authority_name in ("lease.json", "lifecycle.json"):
                authority_path = cwd / ".ccb" / "ccbd" / authority_name
                authority = json.loads(authority_path.read_text(encoding="utf-8"))
                authority["config_signature"] = "different-signature"
                authority_path.write_text(json.dumps(authority) + "\n", encoding="utf-8")
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "config_signature changed" in summary["abort_reason"]
    assert summary["fixture"]["ccb_config_sha256"]
    assert summary["fixture"]["formal_config_signature"] == "config-signature"


def test_ccb_config_content_change_aborts_and_skips_further_mutation(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        commands.append(command)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        (cwd / ".ccb" / "ccb.config").write_text("cmd; changed:codex\n", encoding="utf-8")
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert len(commands) == 1
    assert summary["status"] == "incomplete"
    assert ".ccb/ccb.config content changed" in summary["abort_reason"]
    assert summary["cleanup"]["status"] == "skipped"


def test_materially_negative_external_residual_rejects_sample(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="pristine", warmup=0, iterations=1)

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id, cli_total=10_000.0), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "materially negative" in summary["abort_reason"]


def test_three_warmups_and_twenty_samples_remain_smoke_without_correlated_resources(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, warmup=3, iterations=20)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["formal_sample_thresholds_met"] is True
    assert summary["qualification"] == "smoke_only"
    assert summary["qualification_reasons"][0] == "phase0_measurement_contract_incomplete"
    assert "readiness_keeper_intent_checkpoint_upper_bound" in summary["qualification_reasons"]
    assert "resource_profile_not_correlated" in summary["qualification_reasons"]
    assert "readiness_timeline_incomplete" not in summary["qualification_reasons"]
    assert summary["readiness_gate"]["status"] == "provisional_upper_bound"
    assert summary["readiness_gate"]["t1_observed_upper_bounds"] == 1
    assert summary["readiness_gate"]["t1_exact_keeper_checkpoints"] == 0
    assert summary["counts"]["warmups_completed"] == 3
    assert summary["counts"]["successful"] == 20


def test_exact_keeper_t1_passes_readiness_gate_without_changing_other_phase0_gates(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(runner, tmp_path, warmup=3, iterations=20)
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        if tuple(argv)[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(tuple(argv), 0, "", "", False)
        starts += 1
        daemon_started = starts == 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if daemon_started else "attached",
            daemon_started=daemon_started,
            exact_t1=daemon_started,
        )
        return runner.CommandResult(tuple(argv), 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["readiness_gate"]["status"] == "pass"
    assert summary["readiness_gate"]["t1_exact_keeper_checkpoints"] == 1
    assert summary["readiness_gate"]["t1_exact_statistics_ms"]["n"] == 1
    assert summary["readiness_gate"]["t1_observed_upper_bounds"] == 0
    assert summary["readiness_gate"]["t1_not_required_already_mounted"] == 23
    assert "readiness_keeper_intent_checkpoint_upper_bound" not in summary["qualification_reasons"]
    assert "resource_profile_not_correlated" in summary["qualification_reasons"]


def test_full_cold_uses_only_official_kill_before_each_start(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="full-cold", warmup=0, iterations=2)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        commands.append(command)
        if command[-1] == "kill":
            _write_unmounted(cwd)
        else:
            run_id = _write_mounted_round(
                cwd,
                sequence=len(commands),
                action="launched",
                daemon_started=True,
            )
            return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)
        return runner.CommandResult(command, 0, "", "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert [command[-1] == "kill" for command in commands] == [True, False, True, False, True]
    assert all(command[1] == str((REPO_ROOT / "ccb_test").resolve()) for command in commands)
    assert summary["cleanup"]["purpose"] == "final_cleanup"
    gate = summary["scenario_construction_gate"]
    assert gate["status"] == "pass"
    assert gate["manifests_expected"] == gate["manifests_valid"] == 2
    assert gate["by_scenario"] == {
        "S4": {"present": 2, "passed": 2, "failed": 0}
    }
    for label in ("run-0001", "run-0002"):
        _run_dir, _run, manifest = _read_scenario_evidence(summary, label)
        ready = manifest["ready_for_measurement"]
        after = manifest["observation"]["after"]
        assert manifest["scenario"]["id"] == "S4"
        assert manifest["construction"]["kind"] == "official_full_cold_reset"
        assert ready["authority"]["lifecycle"]["phase"] == "unmounted"
        assert ready["authority"]["namespace"]["ui_attachable"] is False
        assert ready["runtime"]["active_runtime_record_count"] == 0
        assert ready["constructor_resource_audit"]["status"] == "clean"
        assert after["authority"]["lifecycle"]["phase"] == "mounted"
        assert after["runtime"]["active_runtime_record_count"] == 1
        assert after["runtime"]["live_active_runtime_record_count"] == 1
        assert manifest["observation"]["relations"]["daemon_generation"] in {
            "created",
            "changed",
        }


def test_full_cold_kill_failure_aborts_without_start(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path, scenario="full-cold", warmup=0, iterations=2)
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, cwd, env, timeout_s):
        del cwd, env, timeout_s
        command = tuple(argv)
        commands.append(command)
        return runner.CommandResult(command, 9, "", "kill failed", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert len(commands) == 1
    assert commands[0][-1] == "kill"
    assert "official ccb_test kill exited" in summary["abort_reason"]
    _run_dir, _run, manifest = _read_scenario_evidence(summary, "run-0001")
    assert manifest["validation"]["status"] == "failed"
    assert "official_kill_precondition_failed" in manifest["validation"]["reason_codes"]
    assert summary["scenario_construction_gate"]["manifests_valid"] == 1
    assert summary["scenario_construction_gate"]["manifests_failed"] == 1


def test_pristine_constructor_proves_empty_fixture_then_created_authority(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="pristine",
        warmup=0,
        iterations=1,
    )

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["scenario_construction_gate"]["by_scenario"] == {
        "S5a": {"present": 1, "passed": 1, "failed": 0}
    }
    _run_dir, _run, manifest = _read_scenario_evidence(summary, "run-0001")
    assert manifest["scenario"]["id"] == "S5a"
    assert manifest["before"]["runtime"] == {
        "ccbd_dir_exists": False,
        "agents_dir_exists": False,
        "configured_runtime_record_count": 0,
        "active_runtime_record_count": 0,
        "live_active_runtime_record_count": 0,
        "healthy_active_runtime_record_count": 0,
        "steady_active_runtime_record_count": 0,
        "source_home_empty": True,
    }
    assert manifest["ready_for_measurement"]["constructor_resource_audit"]["status"] == "clean"
    assert manifest["observation"]["relations"] == {
        "daemon_identity_digest": "created",
        "namespace_identity_digest": "created",
        "agent_runtime_identity_digest": "created",
        "daemon_generation": "created",
    }
    serialized = json.dumps(manifest, sort_keys=True)
    assert "agent1" not in serialized
    assert str(options.project_root) not in serialized
    assert manifest["privacy"] == {
        "agent_names_persisted": False,
        "process_ids_persisted": False,
        "provider_prompts_persisted": False,
        "raw_runtime_records_persisted": False,
    }


def test_full_cold_constructor_rejects_attachable_namespace_and_active_runtime_residue(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=1,
    )
    _write_mounted_round(
        options.project_root,
        sequence=1,
        action="launched",
        daemon_started=True,
    )
    starts = 0

    def dirty_kill(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        command = tuple(argv)
        if command[-1] != "kill":
            starts += 1
            raise AssertionError("start must not run with constructor residue")
        lifecycle_path = cwd / ".ccb" / "ccbd" / "lifecycle.json"
        lease_path = cwd / ".ccb" / "ccbd" / "lease.json"
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        lifecycle.update(phase="unmounted", desired_state="stopped")
        lease.update(mount_state="unmounted")
        lifecycle_path.write_text(json.dumps(lifecycle) + "\n", encoding="utf-8")
        lease_path.write_text(json.dumps(lease) + "\n", encoding="utf-8")
        return runner.CommandResult(command, 0, "claimed stopped", "", False)

    residue = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=options.project_root,
    )
    try:
        summary = runner.run_startup_benchmark(
            options,
            dependencies=runner.BenchmarkDependencies(
                command_runner=dirty_kill,
                sleep=lambda _value: None,
            ),
            environ=_stub_environ(),
        )
    finally:
        residue.terminate()
        residue.wait(timeout=5)

    assert starts == 0
    assert summary["status"] == "incomplete"
    _run_dir, _run, manifest = _read_scenario_evidence(summary, "run-0001")
    reasons = set(manifest["validation"]["reason_codes"])
    assert "ready_authority_not_stopped" in reasons
    assert "cold_ready_active_runtime_residue" in reasons
    assert "constructor_process_residue_or_audit_degraded" in reasons


def test_scenario_gate_rejects_missing_tampered_and_unreferenced_artifacts(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="pristine",
        warmup=0,
        iterations=1,
    )

    def fake_run(argv, cwd, env, timeout_s):
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        run_id = _write_mounted_round(cwd, sequence=1, action="launched", daemon_started=True)
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )
    benchmark_dir = Path(summary["fixture"]["result_dir"])
    run_path = benchmark_dir / "run-0001" / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    manifest_path = benchmark_dir / "run-0001" / "scenario-construction.json"
    original = manifest_path.read_bytes()

    manifest_path.write_bytes(original + b"\n")
    tampered = runner._scenario_construction_summary([run], benchmark_dir=benchmark_dir)
    assert tampered["status"] == "failed"
    assert "scenario_manifest_artifact_digest_mismatch" in tampered["reason_codes"]

    manifest_path.write_bytes(original)
    before_path = benchmark_dir / "run-0001" / "scenario-construction.before.json"
    before_original = before_path.read_bytes()
    before_path.write_bytes(before_original + b"\n")
    phase_tampered = runner._scenario_construction_summary([run], benchmark_dir=benchmark_dir)
    assert "scenario_manifest_before_phase_digest_mismatch" in phase_tampered["reason_codes"]
    assert "scenario_manifest_ready_phase_chain_invalid" in phase_tampered["reason_codes"]
    before_path.write_bytes(before_original)

    manifest_path.unlink()
    missing = runner._scenario_construction_summary([run], benchmark_dir=benchmark_dir)
    assert missing["status"] == "failed"
    assert "scenario_manifest_artifact_missing" in missing["reason_codes"]
    manifest_path.write_bytes(original)

    without_reference = dict(run)
    without_reference.pop("scenario_construction")
    orphan = runner._scenario_construction_summary(
        [without_reference],
        benchmark_dir=benchmark_dir,
    )
    assert orphan["status"] == "missing"
    assert "scenario_manifest_missing" in orphan["reason_codes"]
    assert "scenario_manifest_orphan_attempt" in orphan["reason_codes"]


def test_scenario_gate_rejects_swapped_run_references(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=2,
    )
    starts = 0

    def fake_run(argv, cwd, env, timeout_s):
        nonlocal starts
        del env, timeout_s
        command = tuple(argv)
        if command[-1] == "kill":
            _write_unmounted(cwd)
            return runner.CommandResult(command, 0, "stopped", "", False)
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(command, 0, _startup_stdout(run_id), "", False)

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(command_runner=fake_run),
        environ=_stub_environ(),
    )
    benchmark_dir = Path(summary["fixture"]["result_dir"])
    first = json.loads((benchmark_dir / "run-0001" / "run.json").read_text(encoding="utf-8"))
    second = json.loads((benchmark_dir / "run-0002" / "run.json").read_text(encoding="utf-8"))
    first["scenario_construction"], second["scenario_construction"] = (
        second["scenario_construction"],
        first["scenario_construction"],
    )

    gate = runner._scenario_construction_summary([first, second], benchmark_dir=benchmark_dir)

    assert gate["status"] == "failed"
    assert "scenario_manifest_reference_run_ordinal_mismatch" in gate["reason_codes"]
    assert "scenario_manifest_artifact_ordinal_mismatch" in gate["reason_codes"]


def test_cli_exposes_only_implemented_scenarios_and_explicit_provider_env_mode(runner, tmp_path: Path) -> None:
    options = runner._parse_args(
        [
            "--project-root",
            str(tmp_path / "project"),
            "--ccb-test",
            str(REPO_ROOT / "ccb_test"),
            "--scenario",
            "warm",
            "--iterations",
            "1",
            "--warmup",
            "0",
            "--launch-cap",
            "1",
            "--provider-env-mode",
            "inherited",
            "--result-root",
            str(tmp_path / "results"),
            "--source-home",
            str(tmp_path / "home"),
            "--test-root",
            str(tmp_path),
        ]
    )

    assert options.scenario == "warm"
    assert options.launch_cap == 1
    assert options.provider_env_mode == "inherited"
    assert options.iterations == 1
    assert options.test_roots == (tmp_path,)


def test_worktree_fingerprint_hashes_git_diff_and_untracked_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_runner()
    source = tmp_path / "source"
    source.mkdir()
    untracked = source / "new.py"
    untracked.write_text("first\n", encoding="utf-8")

    class Completed:
        returncode = 0
        stderr = b""

        def __init__(self, stdout: bytes):
            self.stdout = stdout

    def fake_git(command, **kwargs):
        del kwargs
        if command[1] == "diff":
            return Completed(b"tracked-diff")
        return Completed(b"new.py\0")

    monkeypatch.setattr(module.subprocess, "run", fake_git)
    first = module._source_tree_fingerprint(source)
    untracked.write_text("second\n", encoding="utf-8")
    second = module._source_tree_fingerprint(source)

    assert first != second


def test_resource_profile_is_bound_to_native_run_id_and_cleanup_audit(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=1,
    )
    starts = 0

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def start_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        nonlocal starts
        del env, timeout_s, sample_interval_s, known_instances
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=_raw_resource_profile(wall_ms=0.0),
            tracked_process_instances=((999_999, 123),),
            command_wall_ms=0.0,
            startup_process_trace_id='trace_' + 'a' * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=start_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    result_dir = Path(summary["fixture"]["result_dir"])
    run = json.loads((result_dir / "run-0001" / "run.json").read_text(encoding="utf-8"))
    profile = json.loads(
        (result_dir / "run-0001" / "resource-profile.json").read_text(encoding="utf-8")
    )
    cleanup = json.loads(
        (result_dir / "cleanup-resource-audit.json").read_text(encoding="utf-8")
    )

    assert summary["status"] == "ok"
    assert summary["formal_claim_allowed"] is False
    assert summary["resource_gate"]["status"] == "pass"
    assert summary["resource_gate"]["profiles_verified"] == 1
    assert "schema_version" not in summary["readiness_statistics_ms"]
    assert "resource_profile_not_correlated" not in summary["qualification_reasons"]
    assert "process_io_or_cleanup_incomplete" not in summary["qualification_reasons"]
    assert profile["startup_run_id"] == run["startup_report"]["startup_run_id"]
    assert profile["correlation"]["status"] == "verified"
    assert profile["quality"]["formal_eligible"] is True
    assert run["resource_profile"]["sha256"]
    assert run["process_trace_id"] == 'trace_' + 'a' * 32
    assert set(run["process_bootstrap_timings_ms"]) == set(runner.PROCESS_BOOTSTRAP_TIMING_KEYS)
    assert "CCB_STARTUP_TRACE_SPAWN_NS" not in json.dumps(run, sort_keys=True)
    assert cleanup["status"] == "clean"
    assert cleanup["consecutive_clean_snapshots"] == 2


def test_repeated_resource_rounds_replace_active_seed_but_accumulate_cleanup_set(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=2,
    )
    starts = 0
    known_inputs: list[tuple[tuple[int, int], ...]] = []

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def start_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        nonlocal starts
        del env, timeout_s, sample_interval_s
        known_inputs.append(tuple(sorted(known_instances)))
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched",
            daemon_started=True,
        )
        observed = ((900_000 + starts, 100 + starts),)
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=_raw_resource_profile(wall_ms=0.0),
            tracked_process_instances=observed,
            active_process_instances=observed,
            command_wall_ms=0.0,
            startup_process_trace_id="trace_" + "a" * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=start_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    cleanup = json.loads(
        (
            Path(summary["fixture"]["result_dir"])
            / "cleanup-resource-audit.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["status"] == "ok"
    assert known_inputs == [(), ((900_001, 101),)]
    assert cleanup["known_process_instance_count"] == 2


def test_profiled_start_trace_id_mismatch_is_measurement_integrity_failure(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=1,
    )

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def start_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        del env, timeout_s, sample_interval_s, known_instances
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=_raw_resource_profile(wall_ms=0.0),
            command_wall_ms=0.0,
            startup_process_trace_id='trace_' + 'b' * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=start_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "startup process trace correlation mismatch" in summary["abort_reason"]


def test_resource_command_wall_cannot_exceed_independent_runner_wall(runner, tmp_path: Path) -> None:
    options = _fixture_options(runner, tmp_path)
    context = runner.validate_preflight(options, environ=_stub_environ())

    profile, error = runner._finalize_resource_profile(
        _raw_resource_profile(wall_ms=2.0),
        context=context,
        benchmark_id="wall-containment",
        ordinal=1,
        measured_index=0,
        included_in_statistics=True,
        round_role="measured",
        scenario="warm",
        native_run_id="start_" + "a" * 32,
        stdout_run_id="start_" + "a" * 32,
        report_bytes=b"{}",
        report_validation_error=None,
        wall_ms=2.0,
        runner_outer_wall_ms=1.0,
        tracked_process_instances=(),
    )

    assert "exceeds independently measured runner wall" in str(error)
    assert profile["window"]["sampler_and_runner_overhead_ms"] == -1.0


def test_degraded_warmup_resource_does_not_disqualify_complete_measured_profile(
    runner,
    tmp_path: Path,
) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="warm",
        warmup=1,
        iterations=1,
    )
    starts = 0

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def start_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        nonlocal starts
        del env, timeout_s, sample_interval_s, known_instances
        starts += 1
        run_id = _write_mounted_round(
            cwd,
            sequence=starts,
            action="launched" if starts == 1 else "attached",
            daemon_started=(starts == 1),
        )
        raw = _raw_resource_profile(wall_ms=0.0)
        if starts == 2:  # non-statistical warmup only
            raw["status"] = "degraded"
            raw["reason_codes"] = ["process_io_partial"]
            raw["capabilities"]["process_io"] = "partial"
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=raw,
            command_wall_ms=0.0,
            startup_process_trace_id='trace_' + 'a' * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=start_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "ok"
    assert summary["resource_gate"]["status"] == "pass"
    assert summary["resource_gate"]["profiles_formal_eligible"] == 2
    assert summary["resource_gate"]["measured_profiles_formal_eligible"] == 1
    assert "resource_profile_quality_degraded" not in summary["qualification_reasons"]


def test_prebound_resource_profile_is_measurement_integrity_failure(runner, tmp_path: Path) -> None:
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="full-cold",
        warmup=0,
        iterations=1,
    )

    def control_runner(argv, cwd, env, timeout_s):
        del env, timeout_s
        _write_unmounted(cwd)
        return runner.CommandResult(tuple(argv), 0, "stopped", "", False)

    def start_runner(argv, cwd, env, timeout_s, sample_interval_s, known_instances):
        del env, timeout_s, sample_interval_s, known_instances
        run_id = _write_mounted_round(
            cwd,
            sequence=1,
            action="launched",
            daemon_started=True,
        )
        raw = _raw_resource_profile(wall_ms=0.0)
        raw["startup_run_id"] = "start_wrong"
        return runner.CommandResult(
            tuple(argv),
            0,
            _startup_stdout(run_id),
            "",
            False,
            resource_profile=raw,
            command_wall_ms=0.0,
            startup_process_trace_id='trace_' + 'a' * 32,
        )

    summary = runner.run_startup_benchmark(
        options,
        dependencies=runner.BenchmarkDependencies(
            command_runner=control_runner,
            start_command_runner=start_runner,
            sleep=lambda _value: None,
        ),
        environ=_stub_environ(),
    )

    assert summary["status"] == "incomplete"
    assert "raw resource profile must not pre-bind startup_run_id" in summary["abort_reason"]


def _mixed_recovery_options(runner, tmp_path: Path, **overrides):
    options = _fixture_options(
        runner,
        tmp_path,
        scenario="mixed-recovery",
        warmup=0,
        iterations=1,
        **overrides,
    )
    (options.project_root / ".ccb" / "ccb.config").write_text(
        "cmd; agent2:codex, agent1:codex\n",
        encoding="utf-8",
    )
    return options


def test_mixed_recovery_preflight_requires_stub_and_two_agents(
    runner,
    tmp_path: Path,
) -> None:
    single = _fixture_options(
        runner,
        tmp_path / "single",
        scenario="mixed-recovery",
        warmup=0,
        iterations=1,
    )
    with pytest.raises(runner.SafetyError, match="at least two configured agents"):
        runner.validate_preflight(single, environ=_stub_environ())

    inherited = _mixed_recovery_options(
        runner,
        tmp_path / "inherited",
        provider_env_mode="inherited",
    )
    with pytest.raises(runner.SafetyError, match="deterministic provider stubs"):
        runner.validate_preflight(inherited, environ={})

    accepted = _mixed_recovery_options(runner, tmp_path / "accepted")
    context = runner.validate_preflight(accepted, environ=_stub_environ())
    assert context.configured_agent_names == ("agent1", "agent2")


@pytest.mark.parametrize(
    "environment_key",
    (
        "STUB_LAUNCH_AGENT",
        "STUB_LAUNCH_DELAY",
        "CODEX_STUB_LAUNCH_CANCEL_STAGE",
        "CODEX_STUB_LAUNCH_BARRIER_PATH",
    ),
)
def test_mixed_recovery_rejects_caller_owned_stub_launch_controls(
    runner,
    tmp_path: Path,
    environment_key: str,
) -> None:
    options = _mixed_recovery_options(runner, tmp_path / environment_key.lower())

    with pytest.raises(runner.SafetyError, match="reserved for the benchmark harness"):
        runner.validate_preflight(
            options,
            environ=_stub_environ(**{environment_key: "/caller-controlled"}),
        )


def test_mixed_recovery_stub_command_projection_is_harness_owned_and_before_sentinel(
    runner,
    tmp_path: Path,
) -> None:
    options = _mixed_recovery_options(runner, tmp_path)
    stub = REPO_ROOT / "test" / "stubs" / "provider_stub.py"
    environ = _stub_environ(CODEX_START_CMD=f"{stub} --provider codex -- --bare")
    context = runner.validate_preflight(options, environ=environ)
    env = runner._benchmark_env(options, context, environ=environ)

    runner._configure_mixed_recovery_stub_commands(
        env,
        options=options,
        context=context,
        benchmark_id="test-run",
    )

    parts = shlex.split(env["CODEX_START_CMD"])
    sentinel = parts.index("--")
    assert parts.index("--stub-launch-state-path") < sentinel
    assert parts.index("--stub-launch-fail-release-dir") < sentinel
    assert parts[parts.index("--stub-launch-fail-agents") + 1] == "agent1"
    assert env["CCB_CCBD_MIN_POLL_INTERVAL_S"] == str(
        runner.MIXED_RECOVERY_SUPERVISION_FENCE_S
    )

    reserved = _stub_environ(
        CODEX_START_CMD=(
            f"{stub} --provider codex --stub-launch-run-id caller-controlled"
        )
    )
    with pytest.raises(runner.SafetyError, match="reserved for the benchmark harness"):
        runner.validate_preflight(
            _mixed_recovery_options(runner, tmp_path / "reserved"),
            environ=reserved,
        )


def _mixed_identity(*, target_state: str, target_digest: str, peer_digest: str) -> dict:
    target_live = target_state != "dead"
    return {
        "status": "ok",
        "reason_codes": [],
        "authority": {
            "lifecycle": {
                "phase": "mounted",
                "desired_state": "running",
                "generation": 7,
            },
            "lease": {"mount_state": "mounted", "generation": 7},
            "namespace": {"ui_attachable": True, "namespace_epoch": 3},
        },
        "consistency": {"authority_records": "consistent", "runtime_records": "consistent"},
        "daemon_identity_digest": "daemon",
        "namespace_identity_digest": "namespace",
        "agent_runtime_identity_digest": f"aggregate-{target_digest}",
        "runtime_slots": [
            {
                "slot_id": "scslot_" + "a" * 64,
                "record_present": True,
                "active": target_live,
                "live": target_live,
                "identity_digest": target_digest,
            },
            {
                "slot_id": "scslot_" + "b" * 64,
                "record_present": True,
                "active": True,
                "live": True,
                "identity_digest": peer_digest,
            },
        ],
        "runtime": {
            "configured_runtime_record_count": 2,
            "active_runtime_record_count": 2 if target_live else 1,
            "live_active_runtime_record_count": 2 if target_live else 1,
        },
    }


def test_mixed_recovery_slot_semantics_require_only_target_failure_and_replacement(
    runner,
) -> None:
    target = "scslot_" + "a" * 64
    before = _mixed_identity(target_state="live", target_digest="target-before", peer_digest="peer")
    ready = _mixed_identity(target_state="dead", target_digest="target-dead", peer_digest="peer")
    after = _mixed_identity(target_state="live", target_digest="target-after", peer_digest="peer")

    assert runner._mixed_recovery_ready_reason_codes(
        before,
        ready,
        target_slot_id=target,
        configured_agent_count=2,
    ) == []
    reasons, relations = runner._mixed_recovery_after_reason_codes(
        before,
        ready,
        after,
        target_slot_id=target,
        configured_agent_count=2,
    )
    assert reasons == []
    assert relations[target] == {
        "before_to_ready": "changed",
        "ready_to_after": "changed",
    }
    assert relations["scslot_" + "b" * 64] == {
        "before_to_ready": "same",
        "ready_to_after": "same",
    }

    peer_failed = _mixed_identity(
        target_state="dead",
        target_digest="target-dead",
        peer_digest="peer-changed",
    )
    assert "mixed_ready_peer_identity_changed" in runner._mixed_recovery_ready_reason_codes(
        before,
        peer_failed,
        target_slot_id=target,
        configured_agent_count=2,
    )


def test_mixed_recovery_report_allows_one_target_relaunch_and_rejects_peer_mutation(
    runner,
) -> None:
    def result(name: str, action: str, prepare_count: int) -> dict:
        return {
            "agent_name": name,
            "action": action,
            "health": "healthy",
            "pane_state": "alive",
            "lifecycle_state": "idle",
            "desired_state": "mounted",
            "reconcile_state": "steady",
            "provider_prepare_count": prepare_count,
            "provider_prepare_ms": 0.0,
            "binding_reject_reason": "pane_dead" if name == "agent1" else None,
            "timings_ms": {key: 0.0 for key in AGENT_TIMING_KEYS},
        }

    report = {
        "daemon_started": False,
        "desired_agents": ["agent1", "agent2"],
        "agent_results": [
            result("agent1", "relaunched", 1),
            result("agent2", "attached", 0),
        ],
        "actions_taken": [
            "ensure_namespace:epoch=3,session=test",
            "use_namespace_topology:agent1",
            "relaunch_runtime:agent1",
            "reuse_binding:agent2",
            "cleanup_tmux_orphans:killed=0",
        ],
        "operation_counts": {
            "provider_prepare_attempt_count": 1,
            "provider_prepare_count": 1,
        },
        "cleanup_summaries": [{"orphaned_panes": [], "killed_panes": []}],
    }
    runner._validate_mixed_recovery_report(
        report,
        target_agent_name="agent1",
        configured_agent_names=("agent1", "agent2"),
    )

    report["agent_results"][1]["action"] = "relaunched"
    report["agent_results"][1]["provider_prepare_count"] = 1
    with pytest.raises(runner.ReportValidationError, match="peer runtime"):
        runner._validate_mixed_recovery_report(
            report,
            target_agent_name="agent1",
            configured_agent_names=("agent1", "agent2"),
        )
