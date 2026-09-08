#!/usr/bin/env python3
"""Fail-closed startup wall-time benchmark for a source CCB checkout.

This harness deliberately owns only measurement and official control-plane
invocation.  It never deletes ``.ccb`` state, invokes tmux directly, or kills
processes outside official ``ccb_test kill`` calls used by scenario prime/reset
and final teardown.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import hmac
import json
import math
import os
import platform
import random
import re
import shlex
import stat
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence

DEV_TOOLS_ROOT = Path(__file__).resolve().parent
if str(DEV_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(DEV_TOOLS_ROOT))

from perf_process_resources import (  # noqa: E402
    capture_cleanup_resource_audit,
    run_profiled_command,
    run_timed_command,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CCB_TEST = SOURCE_ROOT / "ccb_test"
DEFAULT_TEST_ROOT = SOURCE_ROOT.parent / "test_ccb2"
DEFAULT_RESULT_ROOT = DEFAULT_TEST_ROOT / "perf_artifacts" / "startup"
DEFAULT_SOURCE_HOME = DEFAULT_TEST_ROOT / "source_home"

SCHEMA_VERSION = 2
STARTUP_REPORT_SCHEMA_VERSION = 2
STARTUP_REPORT_API_VERSION = 2
OWNER_MARKER_NAME = ".ccb-startup-perf-owner.json"
LOCK_NAME = ".ccb-startup-perf.lock"
OWNER_RECORD_TYPE = "ccb_startup_perf_fixture_owner"
RUN_RECORD_TYPE = "ccb_startup_perf_run"
SUMMARY_RECORD_TYPE = "ccb_startup_perf_summary"
SCENARIO_CONSTRUCTION_RECORD_TYPE = "ccb_startup_scenario_construction"
SCENARIO_CONSTRUCTION_SCHEMA_VERSION = 1
SCENARIOS = ("cli-only", "warm", "mixed-recovery", "full-cold", "pristine")
SCENARIO_SPECS: Mapping[str, Mapping[str, str]] = {
    "cli-only": {
        "id": "S0",
        "name": "cli-only-hot-path",
        "report_policy": "unchanged_existing_start_report",
    },
    "warm": {
        "id": "S1",
        "name": "warm-attach",
        "report_policy": "changed_start_report",
    },
    "full-cold": {
        "id": "S4",
        "name": "full-cold",
        "report_policy": "authority_transition",
    },
    "mixed-recovery": {
        "id": "S3",
        "name": "mixed-recovery",
        "report_policy": "authority_transition",
    },
    "pristine": {
        "id": "S5a",
        "name": "pristine-cold",
        "report_policy": "authority_transition",
    },
}
RESTORE_POLICIES = ("resume", "fresh")
PROVIDER_ENV_MODES = ("stub", "inherited")
INSTRUMENTATION_MODES = ("profiled", "instrumentation-ab")
FORMAL_MIN_WARMUPS = 3
FORMAL_MIN_SAMPLES = 20
MIXED_RECOVERY_SUPERVISION_FENCE_S = 120.0
MIXED_RECOVERY_FAULT_WAIT_S = 5.0
NEGATIVE_RESIDUAL_TOLERANCE_MS = 0.05
TIMING_CONTAINMENT_TOLERANCE_MS = 0.01
SUCCESS_RUNTIME_HEALTHS = frozenset({"healthy", "restored"})
CLI_REQUIRED_TIMING_KEYS = frozenset(
    {
        "cli_pre_rpc",
        "daemon_ensure",
        "start_rpc",
        "cli_post_rpc",
        "sidebar_helper_refresh",
        "layout_status",
        "maintenance_heartbeat",
        "cli_total",
    }
)
PROCESS_BOOTSTRAP_TIMING_KEYS = (
    "popen_begin_to_ccb_test_entry",
    "ccb_test_entry_to_pre_exec",
    "ccb_test_pre_exec_to_ccb_py_entry",
    "ccb_py_entry_to_main",
    "ccb_py_main_to_cli_start",
)
READINESS_POINT_NAMES = (
    "T0_cli_entry",
    "T1_lifecycle_intent",
    "T2_control_plane_ready",
    "T3_namespace_attachable",
    "T4_requested_agents_ready",
    "T5_foreground_attached",
    "T6_fully_warm",
)
INPUT_READINESS_STATUSES = frozenset({'not_observed_at_startup'})
NATIVE_SESSION_ID_STATUSES = frozenset(
    {
        'pending',
        'not_observed_at_startup',
        'not_observed_after_startup_failure',
    }
)
AGENT_TIMING_KEYS = frozenset(
    {
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
)
SUPERVISOR_REQUIRED_TIMING_KEYS = frozenset(
    {
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
)
_STUB_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "TMPDIR",
        "TMP",
        "TEMP",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "USER",
        "LOGNAME",
        "SHELL",
        "NATIVE_CLI_STUB_MODE",
    }
)
_STUB_PROVIDER_NAMES = frozenset(
    {
        "CODEX",
        "CLAUDE",
        "GEMINI",
        "OPENCODE",
        "DROID",
        "AGY",
        "KIMI",
        "DEEPSEEK",
        "MIMO",
        "QWEN",
        "CURSOR",
        "COPILOT",
        "CODEBUDDY",
        "CRUSH",
        "GROK",
        "KIRO",
        "PI",
        "OMP",
        "ZAI",
    }
)
_BENCHMARK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STARTUP_TRACE_ENV_KEYS = (
    "CCB_STARTUP_TIMING_TRACE",
    "CCB_STARTUP_TRACE_ID",
    "CCB_STARTUP_TRACE_SPAWN_NS",
    "CCB_STARTUP_TRACE_WRAPPER_ENTRY_NS",
    "CCB_STARTUP_TRACE_WRAPPER_PRE_EXEC_NS",
)
_WARM_LAUNCH_ONLY_TIMING_KEYS = frozenset(
    {
        "prepare_launch_context",
        "build_start_cmd",
        "tmux_respawn",
        "pane_identity",
        "session_write",
        "provider_post_launch",
        "binding_resolve",
    }
)
_WARM_MUTATING_ACTION_PREFIXES = (
    "bootstrap_cmd_pane:",
    "degraded_stale_binding:",
    "launch_runtime:",
    "relabel_runtime_pane:",
    "relaunch_runtime:",
    "restore_runtime:",
    "use_namespace_topology:",
)
_WARM_NAMESPACE_FIELDS = (
    "project_id",
    "namespace_epoch",
    "tmux_socket_path",
    "tmux_session_name",
    "layout_version",
    "layout_signature",
    "control_window_name",
    "control_window_id",
    "workspace_window_name",
    "workspace_window_id",
    "workspace_epoch",
    "ui_attachable",
)
_WARM_LEASE_FIELDS = (
    "project_id",
    "generation",
    "config_signature",
    "ccbd_pid",
    "keeper_pid",
    "daemon_instance_id",
    "boot_id",
    "socket_path",
    "started_at",
)
_WARM_AGENT_FIELDS = (
    "agent_name",
    "provider",
    "workspace_path",
    "runtime_ref",
    "session_ref",
    "binding_source",
    "terminal_backend",
    "tmux_socket_name",
    "tmux_socket_path",
    "tmux_window_name",
    "tmux_window_id",
    "pane_id",
    "active_pane_id",
    "runtime_pid",
    "runtime_root",
)
_WARM_RUNTIME_FIELDS = (
    "agent_name",
    "state",
    "pid",
    "runtime_ref",
    "session_ref",
    "workspace_path",
    "project_id",
    "backend_type",
    "health",
    "provider",
    "runtime_root",
    "runtime_pid",
    "terminal_backend",
    "pane_id",
    "active_pane_id",
    "tmux_socket_name",
    "tmux_socket_path",
    "tmux_window_name",
    "tmux_window_id",
    "session_file",
    "session_id",
    "slot_key",
    "window_id",
    "workspace_epoch",
    "lifecycle_state",
    "binding_generation",
    "managed_by",
    "binding_source",
    "daemon_generation",
    "runtime_generation",
    "desired_state",
    "reconcile_state",
    "restart_count",
    "mount_attempt_id",
)
_WARM_SESSION_FIELDS = (
    "ccb_session_id",
    "agent_name",
    "ccb_project_id",
    "project_root",
    "project_anchor_path",
    "runtime_state_root",
    "runtime_dir",
    "completion_artifact_dir",
    "terminal",
    "tmux_session",
    "pane_id",
    "pane_title_marker",
    "workspace_path",
    "work_dir",
    "work_dir_norm",
    "start_dir",
    "active",
    "tmux_socket_path",
    "input_fifo",
    "output_fifo",
)


class StartupBenchmarkError(RuntimeError):
    """Base error for benchmark failures."""


class SafetyError(StartupBenchmarkError):
    """Raised before mutation when a safety boundary cannot be proved."""


class LockBusyError(SafetyError):
    """Raised when another benchmark owns the fixture."""


class ReportValidationError(StartupBenchmarkError):
    """Raised when the latest-only startup report cannot be tied to a run."""


@dataclass(frozen=True)
class StartupBenchmarkOptions:
    project_root: Path
    ccb_test_path: Path
    scenario: str
    result_root: Path
    source_home: Path
    test_roots: tuple[Path, ...] = ()
    iterations: int = 20
    warmup: int = 3
    launch_cap: int = 1
    restore_policy: str = "resume"
    provider_env_mode: str = "stub"
    instrumentation_mode: str = "profiled"
    instrumentation_ab_seed: int | None = None
    command_timeout_s: float = 120.0
    kill_timeout_s: float = 60.0
    stop_wait_s: float = 10.0
    report_wait_s: float = 2.0
    resource_sample_interval_ms: float = 50.0
    benchmark_id: str | None = None


@dataclass(frozen=True)
class ValidatedContext:
    project_root: Path
    ccb_test_path: Path
    source_root: Path
    source_home: Path
    result_root: Path
    test_roots: tuple[Path, ...]
    owner_uuid: str
    owner_marker_sha256: str
    source_sha: str
    wrapper_sha256: str
    source_tree_fingerprint: str
    config_sha256: str
    config_version: int
    configured_agent_count: int
    configured_agent_names: tuple[str, ...]
    configured_window_count: int
    provider_counts: tuple[tuple[str, int], ...]
    model_counts: tuple[tuple[str, int], ...]
    scenario_identity_key: bytes


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    resource_profile: Mapping[str, Any] | None = None
    tracked_process_instances: tuple[tuple[int, int], ...] = ()
    active_process_instances: tuple[tuple[int, int], ...] | None = None
    command_wall_ms: float | None = None
    startup_process_trace_id: str | None = None


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str], float], CommandResult]
StartCommandRunner = Callable[
    [Sequence[str], Path, Mapping[str, str], float, float, Sequence[tuple[int, int]]],
    CommandResult,
]


@dataclass(frozen=True)
class BenchmarkDependencies:
    command_runner: CommandRunner
    start_command_runner: StartCommandRunner | None = None
    control_start_command_runner: StartCommandRunner | None = None
    perf_counter_ns: Callable[[], int] = time.perf_counter_ns
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    sleep: Callable[[float], None] = time.sleep


def _default_command_runner(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> CommandResult:
    command = tuple(str(item) for item in argv)
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            argv=command,
            returncode=None,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            timed_out=True,
        )
    return CommandResult(
        argv=command,
        returncode=int(completed.returncode),
        stdout=str(completed.stdout or ""),
        stderr=str(completed.stderr or ""),
        timed_out=False,
    )


def _default_start_command_runner(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    sample_interval_s: float,
    known_instances: Sequence[tuple[int, int]],
) -> CommandResult:
    outcome = run_profiled_command(
        argv,
        cwd,
        env,
        timeout_s,
        sample_interval_s=sample_interval_s,
        known_instances=known_instances,
        # Only the start service consumes and publishes the source bootstrap
        # trace.  S0 deliberately exits through the introspection fast path and
        # must not pretend that an unconsumed startup trace belongs to it.
        startup_timing_trace=not _is_cli_only_command(argv),
    )
    window = outcome.resource_profile.get("window")
    command_wall_ms = (
        _finite_nonnegative_or_none(window.get("command_wall_ms"))
        if isinstance(window, Mapping)
        else None
    )
    return CommandResult(
        argv=outcome.argv,
        returncode=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        timed_out=outcome.timed_out,
        resource_profile=outcome.resource_profile,
        tracked_process_instances=outcome.tracked_process_instances,
        active_process_instances=outcome.active_process_instances,
        command_wall_ms=command_wall_ms,
        startup_process_trace_id=outcome.startup_timing_trace_id,
    )


def _default_control_start_command_runner(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    sample_interval_s: float,
    known_instances: Sequence[tuple[int, int]],
) -> CommandResult:
    del sample_interval_s, known_instances
    outcome = run_timed_command(argv, cwd, env, timeout_s)
    return CommandResult(
        argv=outcome.argv,
        returncode=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        timed_out=outcome.timed_out,
        command_wall_ms=outcome.command_wall_ms,
    )


DEFAULT_DEPENDENCIES = BenchmarkDependencies(
    command_runner=_default_command_runner,
    start_command_runner=_default_start_command_runner,
    control_start_command_runner=_default_control_start_command_runner,
)


def owner_marker_payload(
    *,
    project_root: Path,
    source_home: Path,
    owner_uuid: str,
    source_root: Path,
    source_sha: str,
) -> dict[str, Any]:
    """Return the exact marker payload required for an explicitly owned fixture."""
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": OWNER_RECORD_TYPE,
        "owner_uuid": str(uuid.UUID(owner_uuid)),
        "project_root": str(project_root.resolve()),
        "source_home": str(source_home.resolve()),
        "source_root": str(source_root.resolve()),
        "source_sha": source_sha,
    }


def validate_preflight(
    options: StartupBenchmarkOptions,
    *,
    environ: Mapping[str, str] | None = None,
) -> ValidatedContext:
    env = os.environ if environ is None else environ
    if "CCB_SOURCE_RUNTIME_OK" in env:
        raise SafetyError("CCB_SOURCE_RUNTIME_OK is set; benchmark refuses source-runtime bypasses")
    if options.scenario == "partial":
        raise SafetyError(
            "partial scenario is unavailable until a real partial-recovery constructor and validator exist"
        )
    if options.scenario not in SCENARIOS:
        raise SafetyError(f"unsupported scenario: {options.scenario!r}")
    if options.restore_policy not in RESTORE_POLICIES:
        raise SafetyError(f"unsupported restore policy: {options.restore_policy!r}")
    if options.provider_env_mode not in PROVIDER_ENV_MODES:
        raise SafetyError(f"unsupported provider environment mode: {options.provider_env_mode!r}")
    if options.instrumentation_mode not in INSTRUMENTATION_MODES:
        raise SafetyError(f"unsupported instrumentation mode: {options.instrumentation_mode!r}")
    if options.instrumentation_mode == "instrumentation-ab" and options.scenario != "warm":
        raise SafetyError("instrumentation A/B currently supports only the warm scenario")
    if options.instrumentation_ab_seed is not None:
        if (
            type(options.instrumentation_ab_seed) is not int
            or options.instrumentation_ab_seed < 0
            or options.instrumentation_ab_seed > 0x7FFF_FFFF_FFFF_FFFF
        ):
            raise SafetyError("instrumentation A/B seed must be a nonnegative 63-bit integer")
        if options.instrumentation_mode != "instrumentation-ab":
            raise SafetyError("instrumentation A/B seed requires instrumentation-ab mode")
    if options.iterations < 1:
        raise SafetyError("iterations must be at least 1")
    if options.warmup < 0:
        raise SafetyError("warmup cannot be negative")
    if options.launch_cap not in {1, 2, 3, 4}:
        raise SafetyError("launch-cap must be one of 1, 2, 3, 4")
    if options.launch_cap != 1:
        raise SafetyError(
            "launch-cap above 1 is not implemented by the current source runtime; refusing a mislabeled benchmark"
        )
    if not all(
        math.isfinite(value)
        for value in (
            options.command_timeout_s,
            options.kill_timeout_s,
            options.stop_wait_s,
            options.report_wait_s,
        )
    ):
        raise SafetyError("command timeouts and wait durations must be finite")
    if options.command_timeout_s <= 0 or options.kill_timeout_s <= 0:
        raise SafetyError("command timeouts must be positive")
    if options.stop_wait_s < 0 or options.report_wait_s < 0:
        raise SafetyError("wait durations cannot be negative")
    if not math.isfinite(options.resource_sample_interval_ms) or not (
        1.0 <= options.resource_sample_interval_ms <= 1000.0
    ):
        raise SafetyError("resource sample interval must be between 1 and 1000 ms")
    if options.scenario == "pristine" and (options.iterations != 1 or options.warmup != 0):
        raise SafetyError(f"{options.scenario} currently requires --iterations 1 --warmup 0")

    _require_absolute(options.project_root, "project-root")
    _require_absolute(options.ccb_test_path, "ccb-test")
    _require_absolute(options.result_root, "result-root")
    _require_absolute(options.source_home, "source-home")
    project_root = options.project_root.resolve(strict=True)
    ccb_test_path = options.ccb_test_path.resolve(strict=True)
    result_root = options.result_root.resolve(strict=False)
    source_home = options.source_home.resolve(strict=True)
    source_root = ccb_test_path.parent.resolve(strict=True)
    harness_source_root = SOURCE_ROOT.resolve(strict=True)

    expected_wrapper = (harness_source_root / "ccb_test").resolve(strict=True)
    if ccb_test_path != expected_wrapper or source_root != harness_source_root:
        raise SafetyError(
            "ccb-test realpath must be the wrapper from the same source checkout as this harness"
        )
    if not ccb_test_path.is_file():
        raise SafetyError("ccb-test must be a regular file")
    if not project_root.is_dir():
        raise SafetyError("project-root must be an existing directory")
    if not source_home.is_dir():
        raise SafetyError("source-home must be an existing directory")

    test_roots = _effective_test_roots(options, env)
    if not test_roots:
        raise SafetyError("at least one external test root is required")
    for label, path in (
        ("project-root", project_root),
        ("result-root", result_root),
        ("source-home", source_home),
    ):
        if _path_is_under(path, source_root):
            raise SafetyError(f"{label} cannot be inside the source checkout")
        if not any(_path_is_under(path, root) for root in test_roots):
            raise SafetyError(f"{label} is outside all allowed test roots")
    if _paths_overlap(project_root, source_home):
        raise SafetyError("project-root and source-home must be separate trees")
    if _paths_overlap(project_root, result_root):
        raise SafetyError("project-root and result-root must be separate trees")
    if _path_is_under(result_root, source_home):
        raise SafetyError("result-root cannot be inside source-home")

    config_path = project_root / ".ccb" / "ccb.config"
    if not config_path.is_file():
        raise SafetyError("owned fixture must already contain .ccb/ccb.config")
    inventory = _load_fixture_inventory(project_root, source_root=source_root)
    if set(inventory["default_agents"]) != set(inventory["agent_names"]):
        raise SafetyError(
            "benchmark fixtures must start every configured agent; default_agents differs from agents"
        )
    if options.scenario == "mixed-recovery":
        if options.provider_env_mode != "stub":
            raise SafetyError(
                "mixed-recovery is currently available only with deterministic provider stubs"
            )
        if any(
            _stub_launch_environment_key(key) and str(value or "").strip()
            for key, value in env.items()
        ):
            raise SafetyError(
                "mixed-recovery stub launch controls are reserved for the benchmark harness"
            )
    if options.provider_env_mode == "stub":
        _validate_stub_fixture(
            inventory,
            environ=env,
            source_root=source_root,
            test_roots=test_roots,
        )
    if options.scenario == "mixed-recovery" and len(inventory["agent_names"]) < 2:
        raise SafetyError("mixed-recovery requires at least two configured agents")
    source_sha = _read_source_sha(source_root)
    marker_path = project_root / OWNER_MARKER_NAME
    marker = _read_json_object(marker_path, label="fixture owner marker")
    owner_uuid = _validate_owner_marker(
        marker,
        project_root=project_root,
        source_home=source_home,
        source_root=source_root,
        source_sha=source_sha,
    )
    if options.scenario == "pristine":
        _validate_pristine_fixture(project_root=project_root, source_home=source_home)

    return ValidatedContext(
        project_root=project_root,
        ccb_test_path=ccb_test_path,
        source_root=source_root,
        source_home=source_home,
        result_root=result_root,
        test_roots=test_roots,
        owner_uuid=owner_uuid,
        owner_marker_sha256=_sha256_file(marker_path),
        source_sha=source_sha,
        wrapper_sha256=_sha256_file(ccb_test_path),
        source_tree_fingerprint=_source_tree_fingerprint(source_root),
        config_sha256=_sha256_file(config_path),
        config_version=int(inventory["config_version"]),
        configured_agent_count=len(inventory["agent_names"]),
        configured_agent_names=tuple(sorted(str(name) for name in inventory["agent_names"])),
        configured_window_count=int(inventory["window_count"]),
        provider_counts=tuple(sorted(inventory["provider_counts"].items())),
        model_counts=tuple(sorted(inventory["model_counts"].items())),
        scenario_identity_key=os.urandom(32),
    )


@contextlib.contextmanager
def benchmark_lock(context: ValidatedContext) -> Iterator[Path]:
    path = context.project_root / LOCK_NAME
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusyError(f"benchmark fixture is already locked: {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {"owner_uuid": context.owner_uuid, "pid": os.getpid(), "acquired_at": _utc_text()},
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
        yield path
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _build_instrumentation_ab_plan(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    benchmark_id: str,
) -> dict[str, Any]:
    seed = (
        int(options.instrumentation_ab_seed)
        if options.instrumentation_ab_seed is not None
        else int.from_bytes(os.urandom(8), "big") & 0x7FFF_FFFF_FFFF_FFFF
    )
    rng = random.Random(seed)
    total_pairs = options.warmup + options.iterations
    pairs: list[dict[str, Any]] = []
    sequence = 0
    while sequence < total_pairs:
        control_first = bool(rng.getrandbits(1))
        block_orders = (
            (("control", "instrumented"), ("instrumented", "control"))
            if control_first
            else (("instrumented", "control"), ("control", "instrumented"))
        )
        for arm_order in block_orders:
            if sequence >= total_pairs:
                break
            included = sequence >= options.warmup
            pairs.append(
                {
                    "pair_sequence": sequence + 1,
                    "round_role": "measured" if included else "warmup",
                    "measured_pair_index": sequence - options.warmup if included else None,
                    "arm_order": list(arm_order),
                }
            )
            sequence += 1
    return {
        "schema_version": 1,
        "record_type": "ccb_startup_instrumentation_ab_plan",
        "benchmark_id": benchmark_id,
        "seed": seed,
        "order_policy": "seeded_balanced_abba_blocks",
        "pairs_expected": options.iterations,
        "warmup_pairs": options.warmup,
        "source": {
            "commit": context.source_sha,
            "worktree_fingerprint_sha256": context.source_tree_fingerprint,
            "ccb_test_sha256": context.wrapper_sha256,
        },
        "fixture": {
            "owner_uuid": context.owner_uuid,
            "ccb_config_sha256": context.config_sha256,
            "project_root": str(context.project_root),
            "source_home": str(context.source_home),
        },
        "pairs": pairs,
    }


def _scenario_construction_kind(*, scenario: str, round_role: str) -> str:
    if scenario in {"cli-only", "warm", "mixed-recovery"} and round_role == "prime":
        return "official_full_cold_reset_then_prime"
    if scenario == "cli-only":
        return "verify_existing_healthy_cli_only_hot_path"
    if scenario == "warm":
        return "verify_existing_warm_reuse"
    if scenario == "mixed-recovery":
        return "official_single_agent_restart_then_injected_failure"
    if scenario == "full-cold":
        return "official_full_cold_reset"
    if scenario == "pristine":
        return "preflight_pristine_fixture"
    raise ReportValidationError(f"unsupported scenario construction: {scenario!r}")


def _scenario_report_policy(*, scenario: str, round_role: str) -> str:
    if scenario == "cli-only" and round_role == "prime":
        return "changed_start_report"
    return str(SCENARIO_SPECS[scenario]["report_policy"])


def _scenario_identity_digest(
    payload: object,
    *,
    context: ValidatedContext,
    benchmark_id: str,
) -> str | None:
    if payload in (None, [], {}):
        return None
    key = hmac.new(
        context.scenario_identity_key,
        f"{benchmark_id}:scenario-identity".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "scid_" + hmac.new(key, encoded, hashlib.sha256).hexdigest()


def _scenario_slot_id(
    agent_name: str,
    *,
    context: ValidatedContext,
    benchmark_id: str,
) -> str:
    key = hmac.new(
        context.scenario_identity_key,
        f"{benchmark_id}:scenario-slot".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return "scslot_" + hmac.new(
        key,
        agent_name.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _scenario_optional_json(
    path: Path,
    *,
    reason_code: str,
    reason_codes: list[str],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _read_json_object(path, label=reason_code)
    except SafetyError:
        reason_codes.append(reason_code)
        return None


def _scenario_process_identity(pid: int) -> dict[str, Any]:
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass
    except (ProcessLookupError, OSError):
        return {"alive": False, "start_ticks": None}
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        fields = (
            stat_path.read_text(encoding="utf-8", errors="replace")
            .rsplit(")", 1)[1]
            .strip()
            .split()
        )
        state = fields[0]
        start_ticks = int(fields[19])
    except (OSError, IndexError, ValueError):
        return {"alive": True, "start_ticks": None}
    return {"alive": state != "Z", "start_ticks": start_ticks}


def _capture_scenario_identity_once(
    context: ValidatedContext,
    *,
    benchmark_id: str,
) -> dict[str, Any]:
    ccbd_root = _runtime_ccbd_root(context.project_root)
    agents_root = _runtime_agents_root(context.project_root)
    reason_codes: list[str] = []
    lifecycle = _scenario_optional_json(
        ccbd_root / "lifecycle.json",
        reason_code="invalid_lifecycle_json",
        reason_codes=reason_codes,
    )
    lease = _scenario_optional_json(
        ccbd_root / "lease.json",
        reason_code="invalid_lease_json",
        reason_codes=reason_codes,
    )
    namespace = _scenario_optional_json(
        ccbd_root / "state.json",
        reason_code="invalid_namespace_json",
        reason_codes=reason_codes,
    )
    startup_report_identity = _file_identity(ccbd_root / "startup-report.json")

    runtimes: list[dict[str, Any]] = []
    if agents_root.is_dir():
        try:
            runtime_paths = sorted(agents_root.glob("*/runtime.json"))
        except OSError:
            runtime_paths = []
            reason_codes.append("runtime_inventory_unreadable")
        for path in runtime_paths:
            runtime = _scenario_optional_json(
                path,
                reason_code="invalid_runtime_json",
                reason_codes=reason_codes,
            )
            if runtime is not None:
                runtimes.append(runtime)

    try:
        source_home_empty = next(context.source_home.iterdir(), None) is None
    except OSError:
        source_home_empty = None
        reason_codes.append("source_home_unreadable")

    daemon_identity = (
        {
            key: lease.get(key)
            for key in (
                "project_id",
                "config_signature",
                "generation",
                "daemon_instance_id",
                "boot_id",
                "ccbd_pid",
                "keeper_pid",
                "socket_path",
                "started_at",
            )
        }
        if isinstance(lease, Mapping)
        else None
    )
    namespace_identity = (
        {
            key: namespace.get(key)
            for key in (
                "project_id",
                "namespace_epoch",
                "tmux_socket_path",
                "tmux_session_name",
                "layout_signature",
                "workspace_epoch",
                "workspace_window_id",
                "control_window_id",
            )
        }
        if isinstance(namespace, Mapping)
        else None
    )
    process_identities = {
        int(runtime["runtime_pid"]): _scenario_process_identity(
            int(runtime["runtime_pid"])
        )
        for runtime in runtimes
        if type(runtime.get("runtime_pid")) is int
        and int(runtime["runtime_pid"]) > 0
    }
    runtime_identity_fields = (
        "agent_name",
        "provider",
        "project_id",
        "runtime_pid",
        "runtime_ref",
        "session_id",
        "session_file",
        "session_ref",
        "pane_id",
        "active_pane_id",
        "tmux_socket_path",
        "tmux_window_id",
        "slot_key",
        "window_id",
        "workspace_epoch",
        "runtime_generation",
        "daemon_generation",
        "desired_state",
        "lifecycle_state",
        "reconcile_state",
        "health",
    )
    runtime_identity_records = [
        {
            "process_identity": (
                process_identities.get(int(runtime["runtime_pid"]))
                if type(runtime.get("runtime_pid")) is int
                and int(runtime["runtime_pid"]) > 0
                else None
            ),
            **{key: runtime.get(key) for key in runtime_identity_fields},
        }
        for runtime in runtimes
    ]
    runtime_identities = sorted(
        runtime_identity_records,
        key=lambda value: json.dumps(value, sort_keys=True, default=str),
    )
    runtime_by_name: dict[str, dict[str, Any]] = {}
    duplicate_runtime_names: set[str] = set()
    for runtime, identity_record in zip(runtimes, runtime_identity_records):
        name = str(runtime.get("agent_name") or "").strip()
        if not name:
            continue
        if name in runtime_by_name:
            duplicate_runtime_names.add(name)
            continue
        runtime_by_name[name] = {"runtime": runtime, "identity": identity_record}
    runtime_slots: list[dict[str, Any]] = []
    for agent_name in context.configured_agent_names:
        entry = runtime_by_name.get(agent_name)
        runtime = entry.get("runtime") if isinstance(entry, Mapping) else None
        identity_record = entry.get("identity") if isinstance(entry, Mapping) else None
        runtime_pid = (
            int(runtime["runtime_pid"])
            if isinstance(runtime, Mapping)
            and type(runtime.get("runtime_pid")) is int
            and int(runtime["runtime_pid"]) > 0
            else None
        )
        process_identity = process_identities.get(runtime_pid) if runtime_pid is not None else None
        active = bool(
            isinstance(runtime, Mapping)
            and runtime.get("desired_state") == "mounted"
            and runtime.get("lifecycle_state") in {"idle", "running", "active"}
            and runtime_pid is not None
        )
        healthy = bool(
            isinstance(runtime, Mapping)
            and runtime.get("health") in SUCCESS_RUNTIME_HEALTHS
        )
        steady = bool(
            isinstance(runtime, Mapping) and runtime.get("reconcile_state") == "steady"
        )
        runtime_slots.append(
            {
                "slot_id": _scenario_slot_id(
                    agent_name,
                    context=context,
                    benchmark_id=benchmark_id,
                ),
                "record_present": isinstance(runtime, Mapping),
                "active": active,
                "live": bool(
                    active
                    and isinstance(process_identity, Mapping)
                    and process_identity.get("alive") is True
                ),
                "healthy": healthy,
                "steady": steady,
                "identity_digest": _scenario_identity_digest(
                    identity_record,
                    context=context,
                    benchmark_id=benchmark_id,
                ),
                "desired_state": runtime.get("desired_state") if isinstance(runtime, Mapping) else None,
                "lifecycle_state": (
                    runtime.get("lifecycle_state") if isinstance(runtime, Mapping) else None
                ),
                "reconcile_state": (
                    runtime.get("reconcile_state") if isinstance(runtime, Mapping) else None
                ),
                "runtime_generation": (
                    runtime.get("runtime_generation") if isinstance(runtime, Mapping) else None
                ),
                "daemon_generation": (
                    runtime.get("daemon_generation") if isinstance(runtime, Mapping) else None
                ),
            }
        )
    active_runtimes = [
        runtime
        for runtime in runtimes
        if runtime.get("desired_state") == "mounted"
        and runtime.get("lifecycle_state") in {"idle", "running", "active"}
        and type(runtime.get("runtime_pid")) is int
        and int(runtime["runtime_pid"]) > 0
    ]
    active_runtime_count = len(active_runtimes)
    live_active_runtime_count = sum(
        1
        for runtime in active_runtimes
        if process_identities.get(int(runtime["runtime_pid"]), {}).get("alive") is True
    )
    healthy_active_runtime_count = sum(
        1 for runtime in active_runtimes if runtime.get("health") in SUCCESS_RUNTIME_HEALTHS
    )
    steady_active_runtime_count = sum(
        1 for runtime in active_runtimes if runtime.get("reconcile_state") == "steady"
    )
    lifecycle_generation = (
        lifecycle.get("generation") if isinstance(lifecycle, Mapping) else None
    )
    lease_generation = lease.get("generation") if isinstance(lease, Mapping) else None
    lifecycle_project_id = (
        str(lifecycle.get("project_id") or "") if isinstance(lifecycle, Mapping) else ""
    )
    lease_project_id = str(lease.get("project_id") or "") if isinstance(lease, Mapping) else ""
    lifecycle_signature = (
        str(lifecycle.get("config_signature") or "")
        if isinstance(lifecycle, Mapping)
        else ""
    )
    lease_signature = (
        str(lease.get("config_signature") or "") if isinstance(lease, Mapping) else ""
    )
    authority_absent = lifecycle is None and lease is None and namespace is None
    authority_consistent = authority_absent or bool(
        isinstance(lifecycle, Mapping)
        and isinstance(lease, Mapping)
        and lifecycle.get("record_type") == "ccbd_lifecycle"
        and lease.get("record_type") == "ccbd_lease"
        and type(lifecycle_generation) is int
        and lifecycle_generation == lease_generation
        and lifecycle_project_id
        and lifecycle_project_id == lease_project_id
        and lifecycle_signature
        and lifecycle_signature == lease_signature
        and (
            namespace is None
            or (
                isinstance(namespace, Mapping)
                and namespace.get("record_type") == "ccbd_project_namespace_state"
                and str(namespace.get("project_id") or "") == lifecycle_project_id
            )
        )
    )
    runtime_records_consistent = all(
        runtime.get("record_type") == "agent_runtime"
        and (
            not lifecycle_project_id
            or str(runtime.get("project_id") or "") == lifecycle_project_id
        )
        and (
            type(lifecycle_generation) is not int
            or runtime.get("daemon_generation") == lifecycle_generation
        )
        for runtime in runtimes
    )
    if not authority_consistent:
        reason_codes.append("authority_records_inconsistent")
    if not runtime_records_consistent:
        reason_codes.append("runtime_records_inconsistent")
    if duplicate_runtime_names:
        reason_codes.append("duplicate_runtime_agent_records")
    return {
        "status": "failed" if reason_codes else "ok",
        "reason_codes": sorted(set(reason_codes)),
        "authority": {
            "lifecycle": (
                {
                    "phase": lifecycle.get("phase"),
                    "desired_state": lifecycle.get("desired_state"),
                    "generation": lifecycle.get("generation"),
                    "startup_stage": lifecycle.get("startup_stage"),
                }
                if isinstance(lifecycle, Mapping)
                else None
            ),
            "lease": (
                {
                    "mount_state": lease.get("mount_state"),
                    "generation": lease.get("generation"),
                }
                if isinstance(lease, Mapping)
                else None
            ),
            "namespace": (
                {
                    "ui_attachable": namespace.get("ui_attachable"),
                    "namespace_epoch": namespace.get("namespace_epoch"),
                }
                if isinstance(namespace, Mapping)
                else None
            ),
        },
        "daemon_identity_digest": _scenario_identity_digest(
            daemon_identity,
            context=context,
            benchmark_id=benchmark_id,
        ),
        "namespace_identity_digest": _scenario_identity_digest(
            namespace_identity,
            context=context,
            benchmark_id=benchmark_id,
        ),
        "agent_runtime_identity_digest": _scenario_identity_digest(
            runtime_identities,
            context=context,
            benchmark_id=benchmark_id,
        ),
        "startup_report_identity": startup_report_identity,
        "runtime_slots": runtime_slots,
        "runtime": {
            "ccbd_dir_exists": ccbd_root.is_dir(),
            "agents_dir_exists": agents_root.is_dir(),
            "configured_runtime_record_count": len(runtimes),
            "active_runtime_record_count": active_runtime_count,
            "live_active_runtime_record_count": live_active_runtime_count,
            "healthy_active_runtime_record_count": healthy_active_runtime_count,
            "steady_active_runtime_record_count": steady_active_runtime_count,
            "source_home_empty": source_home_empty,
        },
        "consistency": {
            "authority_records": "absent" if authority_absent else (
                "consistent" if authority_consistent else "inconsistent"
            ),
            "runtime_records": (
                "consistent" if runtime_records_consistent else "inconsistent"
            ),
        },
    }


def _scenario_identity_stability_token(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _capture_scenario_identity(
    context: ValidatedContext,
    *,
    benchmark_id: str,
) -> dict[str, Any]:
    previous = _capture_scenario_identity_once(context, benchmark_id=benchmark_id)
    reads = 1
    for _attempt in range(2):
        current = _capture_scenario_identity_once(context, benchmark_id=benchmark_id)
        reads += 1
        if _scenario_identity_stability_token(previous) == _scenario_identity_stability_token(current):
            current["snapshot_consistency"] = {
                "status": "stable_double_read",
                "reads": reads,
            }
            return current
        previous = current
    reasons = list(previous.get("reason_codes") or ())
    reasons.append("identity_snapshot_unstable")
    previous["status"] = "failed"
    previous["reason_codes"] = sorted(set(str(reason) for reason in reasons))
    previous["snapshot_consistency"] = {
        "status": "unstable",
        "reads": reads,
    }
    return previous


def _scenario_runtime_slot_map(identity: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    slots = identity.get("runtime_slots")
    if not isinstance(slots, list):
        return {}
    mapped: dict[str, Mapping[str, Any]] = {}
    for slot in slots:
        if not isinstance(slot, Mapping):
            return {}
        slot_id = str(slot.get("slot_id") or "").strip()
        if not re.fullmatch(r"scslot_[0-9a-f]{64}", slot_id) or slot_id in mapped:
            return {}
        mapped[slot_id] = slot
    return mapped


def _mixed_recovery_target_name(context: ValidatedContext) -> str:
    if len(context.configured_agent_names) < 2:
        raise ReportValidationError("mixed recovery requires at least two configured agents")
    return context.configured_agent_names[0]


def _mixed_recovery_target_slot_id(
    context: ValidatedContext,
    *,
    benchmark_id: str,
) -> str:
    return _scenario_slot_id(
        _mixed_recovery_target_name(context),
        context=context,
        benchmark_id=benchmark_id,
    )


def _mixed_recovery_probe_path(context: ValidatedContext, *, benchmark_id: str) -> Path:
    return context.result_root / benchmark_id / "s3-launch-probe.json"


def _mixed_recovery_release_dir(context: ValidatedContext, *, benchmark_id: str) -> Path:
    return context.result_root / benchmark_id / "s3-failure-releases"


def _configure_mixed_recovery_stub_commands(
    env: dict[str, str],
    *,
    options: StartupBenchmarkOptions,
    context: ValidatedContext,
    benchmark_id: str,
) -> None:
    target_name = _mixed_recovery_target_name(context)
    total_rounds = options.warmup + options.iterations
    selected_indices = ",".join(str(index * 2) for index in range(1, total_rounds + 1))
    probe_args = (
        "--stub-launch-state-path",
        str(_mixed_recovery_probe_path(context, benchmark_id=benchmark_id)),
        "--stub-launch-run-id",
        benchmark_id,
        "--stub-launch-fail-stage",
        "after_active",
        "--stub-launch-fail-agents",
        target_name,
        "--stub-launch-fail-match-indices",
        selected_indices,
        "--stub-launch-fail-release-dir",
        str(_mixed_recovery_release_dir(context, benchmark_id=benchmark_id)),
        "--stub-launch-fail-release-timeout",
        str(max(10.0, min(options.command_timeout_s, 30.0))),
    )
    for provider, _count in context.provider_counts:
        env_name = f"{provider.upper().replace('-', '_')}_START_CMD"
        raw_command = str(env.get(env_name) or "").strip()
        try:
            command = shlex.split(raw_command)
        except ValueError as exc:  # pragma: no cover - preflight owns this validation.
            raise SafetyError(f"{env_name} became invalid after preflight: {exc}") from exc
        if not command:
            raise SafetyError(f"{env_name} disappeared after preflight")
        sentinel_index = command.index("--") if "--" in command else len(command)
        env[env_name] = shlex.join(
            [*command[:sentinel_index], *probe_args, *command[sentinel_index:]]
        )
    # Keep the deterministic foreground compensation ahead of automatic
    # supervision.  The ordinary start RPC still exercises the production
    # recovery path; this source-test-only fence prevents an unrelated periodic
    # heartbeat from winning the race before that request arrives.
    env["CCB_CCBD_MIN_POLL_INTERVAL_S"] = str(MIXED_RECOVERY_SUPERVISION_FENCE_S)


def _mixed_recovery_probe_evidence(
    context: ValidatedContext,
    *,
    benchmark_id: str,
    expected_target_matches: int,
    expected_failures: int,
    expected_armed: int,
    expected_released: int,
    expected_active: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    path = _mixed_recovery_probe_path(context, benchmark_id=benchmark_id)
    try:
        payload = _read_json_object(path, label="mixed recovery launch probe")
    except SafetyError:
        return {
            "status": "failed",
            "reason_codes": ["mixed_probe_missing_or_invalid"],
            "artifact": path.name,
            "target_slot_id": _mixed_recovery_target_slot_id(
                context,
                benchmark_id=benchmark_id,
            ),
        }
    if payload.get("schema_version") != 2:
        reasons.append("mixed_probe_schema_invalid")
    if payload.get("run_id") != benchmark_id:
        reasons.append("mixed_probe_run_id_mismatch")
    if payload.get("metric_scope") != "injected_process_start_interval":
        reasons.append("mixed_probe_scope_invalid")
    events = payload.get("events")
    if not isinstance(events, list) or not all(isinstance(event, Mapping) for event in events):
        reasons.append("mixed_probe_events_invalid")
        events = []
    sequences = [event.get("seq") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        reasons.append("mixed_probe_event_sequence_invalid")
    if any(event.get("run_id") != benchmark_id for event in events):
        reasons.append("mixed_probe_event_run_id_mismatch")
    active_processes = payload.get("active_processes")
    active = payload.get("active")
    if (
        type(active) is not int
        or active < 0
        or not isinstance(active_processes, Mapping)
        or active != len(active_processes)
    ):
        reasons.append("mixed_probe_active_state_invalid")
    elif active != expected_active:
        reasons.append("mixed_probe_active_count_mismatch")
    max_observed = payload.get("max_observed")
    if type(max_observed) is not int or max_observed != 1:
        reasons.append("mixed_probe_not_strictly_serial")

    target_name = _mixed_recovery_target_name(context)
    target_events = [event for event in events if event.get("agent") == target_name]
    matches = [event for event in target_events if event.get("event") == "injection_match"]
    match_indices = [event.get("match_index") for event in matches]
    if match_indices != list(range(1, expected_target_matches + 1)):
        reasons.append("mixed_probe_target_match_sequence_mismatch")
    expected_selected = [index for index in range(2, expected_target_matches + 1, 2)]
    selected = [
        event.get("match_index")
        for event in matches
        if event.get("selected") is True
    ]
    rejected = [
        event.get("match_index")
        for event in matches
        if event.get("selected") is False
    ]
    if selected != expected_selected:
        reasons.append("mixed_probe_selected_match_sequence_mismatch")
    if rejected != [index for index in range(1, expected_target_matches + 1, 2)]:
        reasons.append("mixed_probe_nonselected_match_sequence_mismatch")
    if any(type(event.get("selected")) is not bool for event in matches):
        reasons.append("mixed_probe_match_selection_invalid")
    failures = [event for event in target_events if event.get("event") == "injected_failure"]
    armed = [
        event for event in target_events if event.get("event") == "injected_failure_armed"
    ]
    released = [
        event for event in target_events if event.get("event") == "injected_failure_released"
    ]
    if [event.get("match_index") for event in failures] != expected_selected[:expected_failures]:
        reasons.append("mixed_probe_failure_sequence_mismatch")
    if [event.get("match_index") for event in armed] != expected_selected[:expected_armed]:
        reasons.append("mixed_probe_armed_sequence_mismatch")
    if [event.get("match_index") for event in released] != expected_selected[:expected_released]:
        reasons.append("mixed_probe_release_sequence_mismatch")
    if len(failures) != expected_failures:
        reasons.append("mixed_probe_failure_count_mismatch")
    if len(armed) != expected_armed:
        reasons.append("mixed_probe_armed_count_mismatch")
    if len(released) != expected_released:
        reasons.append("mixed_probe_release_count_mismatch")
    if any(
        event.get("event") in {"injected_failure_release_timeout", "stale_reaped"}
        for event in events
    ):
        reasons.append("mixed_probe_timeout_or_stale_process")
    return {
        "status": "failed" if reasons else "pass",
        "reason_codes": sorted(set(reasons)),
        "artifact": path.name,
        "target_slot_id": _mixed_recovery_target_slot_id(
            context,
            benchmark_id=benchmark_id,
        ),
        "target_match_count": len(matches),
        "selected_match_indices": selected,
        "injected_failure_count": len(failures),
        "armed_failure_count": len(armed),
        "released_failure_count": len(released),
        "active": active,
        "max_observed": max_observed,
        "event_count": len(events),
    }


def _supervision_cursor(context: ValidatedContext) -> dict[str, Any]:
    path = _runtime_ccbd_root(context.project_root) / "supervision.jsonl"
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        payload = b""
    except OSError as exc:
        raise ReportValidationError(f"supervision event cursor is unreadable: {exc}") from exc
    return {
        "byte_length": len(payload),
        "prefix_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _supervision_recovery_audit(
    context: ValidatedContext,
    *,
    cursor: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    length = cursor.get("byte_length")
    prefix_sha256 = str(cursor.get("prefix_sha256") or "")
    if type(length) is not int or length < 0 or not re.fullmatch(r"[0-9a-f]{64}", prefix_sha256):
        return {
            "status": "failed",
            "reason_codes": ["supervision_cursor_invalid"],
            "new_event_count": 0,
            "recovery_event_count": 0,
        }
    path = _runtime_ccbd_root(context.project_root) / "supervision.jsonl"
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        payload = b""
    except OSError:
        return {
            "status": "failed",
            "reason_codes": ["supervision_events_unreadable"],
            "new_event_count": 0,
            "recovery_event_count": 0,
        }
    if len(payload) < length or hashlib.sha256(payload[:length]).hexdigest() != prefix_sha256:
        reasons.append("supervision_event_prefix_changed")
        suffix = b""
    else:
        suffix = payload[length:]
    new_events: list[Mapping[str, Any]] = []
    for line in suffix.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            reasons.append("supervision_new_event_invalid")
            continue
        if not isinstance(event, Mapping):
            reasons.append("supervision_new_event_invalid")
            continue
        new_events.append(event)
    recovery_events = [
        event
        for event in new_events
        if str(event.get("event_kind") or "").startswith("recover_")
    ]
    if recovery_events:
        reasons.append("automatic_supervision_won_recovery_race")
    return {
        "status": "failed" if reasons else "pass",
        "reason_codes": sorted(set(reasons)),
        "new_event_count": len(new_events),
        "recovery_event_count": len(recovery_events),
    }


def _scenario_generation(identity: Mapping[str, Any]) -> object:
    authority = identity.get("authority")
    lifecycle = authority.get("lifecycle") if isinstance(authority, Mapping) else None
    return lifecycle.get("generation") if isinstance(lifecycle, Mapping) else None


def _mixed_recovery_ready_reason_codes(
    before: Mapping[str, Any],
    ready: Mapping[str, Any],
    *,
    target_slot_id: str,
    configured_agent_count: int,
) -> list[str]:
    reasons: list[str] = []
    if before.get("status") != "ok" or ready.get("status") != "ok":
        reasons.append("mixed_identity_unavailable")
    if not _scenario_authority_is_mounted(before) or not _scenario_authority_is_mounted(ready):
        reasons.append("mixed_authority_not_mounted")
    for key in ("daemon_identity_digest", "namespace_identity_digest"):
        if not before.get(key) or before.get(key) != ready.get(key):
            reasons.append(f"mixed_ready_{key}_changed")
    if _scenario_generation(before) != _scenario_generation(ready):
        reasons.append("mixed_ready_daemon_generation_changed")
    if before.get("agent_runtime_identity_digest") == ready.get("agent_runtime_identity_digest"):
        reasons.append("mixed_ready_runtime_identity_unchanged")
    before_slots = _scenario_runtime_slot_map(before)
    ready_slots = _scenario_runtime_slot_map(ready)
    if len(before_slots) != configured_agent_count or set(before_slots) != set(ready_slots):
        reasons.append("mixed_ready_slot_inventory_mismatch")
        return reasons
    if target_slot_id not in before_slots:
        reasons.append("mixed_ready_target_slot_missing")
        return reasons
    for slot_id, before_slot in before_slots.items():
        ready_slot = ready_slots[slot_id]
        if before_slot.get("record_present") is not True or before_slot.get("live") is not True:
            reasons.append("mixed_before_slot_not_live")
        if slot_id == target_slot_id:
            if ready_slot.get("record_present") is not True or ready_slot.get("live") is not False:
                reasons.append("mixed_ready_target_not_dead")
            if ready_slot.get("identity_digest") == before_slot.get("identity_digest"):
                reasons.append("mixed_ready_target_identity_unchanged")
        else:
            if ready_slot.get("active") is not True or ready_slot.get("live") is not True:
                reasons.append("mixed_ready_peer_not_live")
            if ready_slot.get("identity_digest") != before_slot.get("identity_digest"):
                reasons.append("mixed_ready_peer_identity_changed")
    runtime = ready.get("runtime")
    if not isinstance(runtime, Mapping):
        reasons.append("mixed_ready_runtime_summary_missing")
    else:
        if runtime.get("configured_runtime_record_count") != configured_agent_count:
            reasons.append("mixed_ready_runtime_record_count_mismatch")
        if runtime.get("live_active_runtime_record_count") != configured_agent_count - 1:
            reasons.append("mixed_ready_live_runtime_count_mismatch")
    return sorted(set(reasons))


def _mixed_recovery_after_reason_codes(
    before: Mapping[str, Any],
    ready: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    target_slot_id: str,
    configured_agent_count: int,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    reasons: list[str] = []
    for key in ("daemon_identity_digest", "namespace_identity_digest"):
        if not ready.get(key) or ready.get(key) != after.get(key):
            reasons.append(f"mixed_after_{key}_changed")
    if _scenario_generation(ready) != _scenario_generation(after):
        reasons.append("mixed_after_daemon_generation_changed")
    if ready.get("agent_runtime_identity_digest") == after.get(
        "agent_runtime_identity_digest"
    ):
        reasons.append("mixed_after_runtime_identity_unchanged")
    before_slots = _scenario_runtime_slot_map(before)
    ready_slots = _scenario_runtime_slot_map(ready)
    after_slots = _scenario_runtime_slot_map(after)
    slot_relations: dict[str, dict[str, str]] = {}
    if (
        len(before_slots) != configured_agent_count
        or set(before_slots) != set(ready_slots)
        or set(before_slots) != set(after_slots)
    ):
        reasons.append("mixed_after_slot_inventory_mismatch")
        return sorted(set(reasons)), slot_relations
    if target_slot_id not in after_slots:
        reasons.append("mixed_after_target_slot_missing")
        return sorted(set(reasons)), slot_relations
    for slot_id, before_slot in before_slots.items():
        ready_slot = ready_slots[slot_id]
        after_slot = after_slots[slot_id]
        slot_relations[slot_id] = {
            "before_to_ready": _scenario_relation(
                before_slot.get("identity_digest"),
                ready_slot.get("identity_digest"),
            ),
            "ready_to_after": _scenario_relation(
                ready_slot.get("identity_digest"),
                after_slot.get("identity_digest"),
            ),
        }
        if after_slot.get("record_present") is not True:
            reasons.append("mixed_after_runtime_record_missing")
        if slot_id == target_slot_id:
            if after_slot.get("active") is not True or after_slot.get("live") is not True:
                reasons.append("mixed_after_target_not_recovered")
            if after_slot.get("identity_digest") in {
                before_slot.get("identity_digest"),
                ready_slot.get("identity_digest"),
            }:
                reasons.append("mixed_after_target_identity_not_new")
        else:
            if after_slot.get("active") is not True or after_slot.get("live") is not True:
                reasons.append("mixed_after_peer_not_live")
            if (
                ready_slot.get("identity_digest") != before_slot.get("identity_digest")
                or after_slot.get("identity_digest") != before_slot.get("identity_digest")
            ):
                reasons.append("mixed_after_peer_identity_changed")
    runtime = after.get("runtime")
    if not isinstance(runtime, Mapping):
        reasons.append("mixed_after_runtime_summary_missing")
    else:
        for key in (
            "configured_runtime_record_count",
            "active_runtime_record_count",
            "live_active_runtime_record_count",
        ):
            if runtime.get(key) != configured_agent_count:
                reasons.append(f"mixed_after_{key}_mismatch")
    return sorted(set(reasons)), slot_relations


def _new_scenario_construction_manifest(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    benchmark_id: str,
    ordinal: int,
    round_role: str,
    instrumentation_arm: str,
    expected_daemon_started: bool | None,
    require_cold_launch: bool,
    require_warm_reuse: bool,
) -> dict[str, Any]:
    spec = SCENARIO_SPECS[options.scenario]
    return {
        "schema_version": SCENARIO_CONSTRUCTION_SCHEMA_VERSION,
        "record_type": SCENARIO_CONSTRUCTION_RECORD_TYPE,
        "benchmark_id": benchmark_id,
        "round_ordinal": ordinal,
        "scenario": {
            "id": spec["id"],
            "name": spec["name"],
            "cli_name": options.scenario,
            "variant": round_role,
        },
        "fixture": {
            "owner_marker_sha256": context.owner_marker_sha256,
            "config_sha256": context.config_sha256,
            "source_sha": context.source_sha,
            "source_tree_fingerprint_sha256": context.source_tree_fingerprint,
        },
        "construction": {
            "kind": _scenario_construction_kind(
                scenario=options.scenario,
                round_role=round_role,
            ),
            "status": "pending",
        },
        "before": _capture_scenario_identity(context, benchmark_id=benchmark_id),
        "ready_for_measurement": {"status": "pending", "reason_codes": []},
        "expectation": {
            "report_policy": _scenario_report_policy(
                scenario=options.scenario,
                round_role=round_role,
            ),
            "daemon_started": expected_daemon_started,
            "cold_launch": bool(require_cold_launch),
            "warm_reuse": bool(require_warm_reuse),
            "configured_agent_count": context.configured_agent_count,
            "instrumentation_arm": instrumentation_arm,
            "recovery_target_slot_id": (
                _mixed_recovery_target_slot_id(context, benchmark_id=benchmark_id)
                if options.scenario == "mixed-recovery"
                else None
            ),
        },
        "observation": {"status": "pending"},
        "validation": {"status": "pending", "reason_codes": []},
        "privacy": {
            "agent_names_persisted": False,
            "process_ids_persisted": False,
            "provider_prompts_persisted": False,
            "raw_runtime_records_persisted": False,
        },
    }


def _scenario_authority_is_stopped(identity: Mapping[str, Any]) -> bool:
    authority = identity.get("authority")
    consistency = identity.get("consistency")
    if not isinstance(authority, Mapping):
        return False
    if (
        isinstance(consistency, Mapping)
        and consistency.get("authority_records") == "absent"
        and all(authority.get(key) is None for key in ("lifecycle", "lease", "namespace"))
    ):
        # A never-started project has no lifecycle/lease records yet.  It is
        # already stopped for constructor purposes, provided the snapshot
        # also proves that no authority record exists.
        return True
    lifecycle = authority.get("lifecycle")
    lease = authority.get("lease")
    namespace = authority.get("namespace")
    return bool(
        isinstance(consistency, Mapping)
        and consistency.get("authority_records") == "consistent"
        and
        isinstance(lifecycle, Mapping)
        and lifecycle.get("phase") == "unmounted"
        and lifecycle.get("desired_state") == "stopped"
        and isinstance(lease, Mapping)
        and lease.get("mount_state") == "unmounted"
        and lifecycle.get("generation") == lease.get("generation")
        and (
            namespace is None
            or (
                isinstance(namespace, Mapping)
                and namespace.get("ui_attachable") is False
            )
        )
    )


def _scenario_authority_is_mounted(identity: Mapping[str, Any]) -> bool:
    authority = identity.get("authority")
    consistency = identity.get("consistency")
    if not isinstance(authority, Mapping):
        return False
    lifecycle = authority.get("lifecycle")
    lease = authority.get("lease")
    namespace = authority.get("namespace")
    return bool(
        isinstance(consistency, Mapping)
        and consistency.get("authority_records") == "consistent"
        and
        isinstance(lifecycle, Mapping)
        and lifecycle.get("phase") == "mounted"
        and lifecycle.get("desired_state") == "running"
        and isinstance(lease, Mapping)
        and lease.get("mount_state") == "mounted"
        and lifecycle.get("generation") == lease.get("generation")
        and isinstance(namespace, Mapping)
        and namespace.get("ui_attachable") is True
    )


def _cli_only_identity_reason_codes(
    identity: Mapping[str, Any],
    *,
    configured_agent_count: int,
    baseline: Mapping[str, Any] | None,
    phase: str,
) -> list[str]:
    reasons: list[str] = []
    if identity.get("status") != "ok":
        reasons.append(f"cli_only_{phase}_identity_unavailable")
    if not _scenario_authority_is_mounted(identity):
        reasons.append(f"cli_only_{phase}_authority_not_mounted")
    runtime = identity.get("runtime")
    if not isinstance(runtime, Mapping):
        reasons.append(f"cli_only_{phase}_runtime_summary_missing")
    else:
        for key in (
            "configured_runtime_record_count",
            "active_runtime_record_count",
            "live_active_runtime_record_count",
            "healthy_active_runtime_record_count",
            "steady_active_runtime_record_count",
        ):
            if runtime.get(key) != configured_agent_count:
                reasons.append(f"cli_only_{phase}_{key}_mismatch")
    slots = _scenario_runtime_slot_map(identity)
    if len(slots) != configured_agent_count:
        reasons.append(f"cli_only_{phase}_slot_inventory_mismatch")
    elif any(
        slot.get("record_present") is not True
        or slot.get("active") is not True
        or slot.get("live") is not True
        or slot.get("healthy") is not True
        or slot.get("steady") is not True
        or not slot.get("identity_digest")
        for slot in slots.values()
    ):
        reasons.append(f"cli_only_{phase}_provider_not_healthy_and_steady")
    for key in (
        "daemon_identity_digest",
        "namespace_identity_digest",
        "agent_runtime_identity_digest",
    ):
        if not identity.get(key):
            reasons.append(f"cli_only_{phase}_{key}_missing")
    report_identity = identity.get("startup_report_identity")
    if not isinstance(report_identity, Mapping):
        reasons.append(f"cli_only_{phase}_startup_report_missing")

    if baseline is not None:
        if baseline.get("status") != "ok":
            reasons.append("cli_only_frozen_baseline_unavailable")
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "startup_report_identity",
        ):
            if baseline.get(key) != identity.get(key):
                reasons.append(f"cli_only_{phase}_{key}_changed_from_frozen_baseline")
        if _scenario_generation(baseline) != _scenario_generation(identity):
            reasons.append(f"cli_only_{phase}_daemon_generation_changed_from_frozen_baseline")
        if set(_scenario_runtime_slot_map(baseline)) != set(slots):
            reasons.append(f"cli_only_{phase}_slot_inventory_changed_from_frozen_baseline")
    return sorted(set(reasons))


def _cli_only_manifest_baseline(identity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(identity, Mapping):
        return None
    return {
        "status": identity.get("status"),
        "daemon_generation": _scenario_generation(identity),
        "daemon_identity_digest": identity.get("daemon_identity_digest"),
        "namespace_identity_digest": identity.get("namespace_identity_digest"),
        "agent_runtime_identity_digest": identity.get("agent_runtime_identity_digest"),
        "startup_report_identity": identity.get("startup_report_identity"),
        "runtime_slot_ids": sorted(_scenario_runtime_slot_map(identity)),
    }


def _capture_cli_only_preservation_audit(
    context: ValidatedContext,
    *,
    benchmark_id: str,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        current = _capture_scenario_identity(context, benchmark_id=benchmark_id)
        reasons = _cli_only_identity_reason_codes(
            current,
            configured_agent_count=context.configured_agent_count,
            baseline=baseline,
            phase="pre_teardown",
        )
    except Exception as exc:
        return {
            "status": "failed",
            "reason_codes": [f"cli_only_preservation_audit_exception:{type(exc).__name__}"],
            "failure_reason": str(exc),
            "baseline": _cli_only_manifest_baseline(baseline),
            "observed": None,
        }
    return {
        "status": "failed" if reasons else "pass",
        "reason_codes": reasons,
        "baseline": _cli_only_manifest_baseline(baseline),
        "observed": _cli_only_manifest_baseline(current),
    }


def _prepare_scenario_construction_manifest(
    manifest: dict[str, Any],
    *,
    options: StartupBenchmarkOptions,
    context: ValidatedContext,
    benchmark_id: str,
    round_role: str,
    precondition: Mapping[str, Any],
    dependencies: BenchmarkDependencies,
    source_failure: str | None = None,
    cli_only_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    construction = dict(manifest.get("construction") or {})
    construction["precondition_kind"] = precondition.get("kind")
    construction["precondition_status"] = precondition.get("status")
    construction["status"] = (
        "failed"
        if source_failure is not None or precondition.get("status") == "failed"
        else "ok"
    )
    if options.scenario == "mixed-recovery" and round_role != "prime":
        construction["mixed_recovery"] = {
            key: precondition.get(key)
            for key in (
                "target_slot_id",
                "probe_armed",
                "probe_after_failure",
                "supervision_cursor",
                "supervision_audit",
                "release_token",
            )
        }
    manifest["construction"] = construction
    mixed_ready = precondition.get("mixed_identity")
    ready = (
        dict(mixed_ready)
        if options.scenario == "mixed-recovery"
        and round_role != "prime"
        and isinstance(mixed_ready, Mapping)
        else _capture_scenario_identity(context, benchmark_id=benchmark_id)
    )
    reasons: list[str] = []
    before = manifest.get("before")
    if not isinstance(before, Mapping) or before.get("status") != "ok":
        reasons.append("before_identity_unavailable")
    if ready.get("status") != "ok":
        reasons.append("ready_identity_unavailable")
    if source_failure is not None:
        reasons.append("source_identity_drift")
        construction["failure_reason"] = source_failure
    cold_constructor = options.scenario == "full-cold" or (
        options.scenario in {"cli-only", "warm", "mixed-recovery"}
        and round_role == "prime"
    )
    constructor_resource_audit: dict[str, Any] | None = None
    if cold_constructor or options.scenario == "pristine":
        constructor_resource_audit = capture_cleanup_resource_audit(
            context.project_root,
            known_instances=frozenset(),
            sample_interval_s=options.resource_sample_interval_ms / 1000.0,
            max_samples=2,
            required_consecutive_clean=2,
            perf_counter_ns=dependencies.perf_counter_ns,
            sleep=dependencies.sleep,
        )
        if constructor_resource_audit.get("status") != "clean":
            reasons.append("constructor_process_residue_or_audit_degraded")
    if cold_constructor:
        if precondition.get("kind") != "official_ccb_test_kill":
            reasons.append("official_kill_precondition_missing")
        if precondition.get("status") != "ok":
            reasons.append("official_kill_precondition_failed")
        if not _scenario_authority_is_stopped(ready):
            reasons.append("ready_authority_not_stopped")
        runtime = ready.get("runtime")
        if not isinstance(runtime, Mapping) or runtime.get("active_runtime_record_count") != 0:
            reasons.append("cold_ready_active_runtime_residue")
        elif runtime.get("live_active_runtime_record_count") != 0:
            reasons.append("cold_ready_live_runtime_residue")
    elif options.scenario == "cli-only":
        if precondition.get("status") != "not_required":
            reasons.append("unexpected_cli_only_constructor_mutation")
        reasons.extend(
            _cli_only_identity_reason_codes(
                before if isinstance(before, Mapping) else {},
                configured_agent_count=context.configured_agent_count,
                baseline=cli_only_baseline,
                phase="before",
            )
        )
        reasons.extend(
            _cli_only_identity_reason_codes(
                ready,
                configured_agent_count=context.configured_agent_count,
                baseline=cli_only_baseline,
                phase="ready",
            )
        )
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "startup_report_identity",
        ):
            if not isinstance(before, Mapping) or before.get(key) != ready.get(key):
                reasons.append(f"cli_only_ready_{key}_changed")
        manifest["expectation"]["frozen_baseline"] = _cli_only_manifest_baseline(
            cli_only_baseline
        )
    elif options.scenario == "warm":
        if precondition.get("status") != "not_required":
            reasons.append("unexpected_warm_constructor_mutation")
        if not _scenario_authority_is_mounted(ready):
            reasons.append("warm_ready_authority_not_mounted")
        runtime = ready.get("runtime")
        if not isinstance(runtime, Mapping):
            reasons.append("warm_ready_runtime_identity_missing")
        else:
            if runtime.get("configured_runtime_record_count") != context.configured_agent_count:
                reasons.append("warm_ready_runtime_count_mismatch")
            if runtime.get("active_runtime_record_count") != context.configured_agent_count:
                reasons.append("warm_ready_active_runtime_count_mismatch")
            if runtime.get("live_active_runtime_record_count") != context.configured_agent_count:
                reasons.append("warm_ready_live_runtime_count_mismatch")
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
        ):
            if not ready.get(key):
                reasons.append(f"warm_ready_{key}_missing")
    elif options.scenario == "mixed-recovery":
        if precondition.get("kind") != "official_ccb_test_restart_injected_target_failure":
            reasons.append("mixed_official_restart_precondition_missing")
        if precondition.get("status") != "ok":
            reasons.append("mixed_official_restart_precondition_failed")
        target_slot_id = _mixed_recovery_target_slot_id(
            context,
            benchmark_id=benchmark_id,
        )
        reasons.extend(
            _mixed_recovery_ready_reason_codes(
                before if isinstance(before, Mapping) else {},
                ready,
                target_slot_id=target_slot_id,
                configured_agent_count=context.configured_agent_count,
            )
        )
        for evidence_key in ("probe_after_failure", "supervision_audit"):
            evidence = precondition.get(evidence_key)
            if not isinstance(evidence, Mapping) or evidence.get("status") != "pass":
                reasons.append(f"mixed_{evidence_key}_failed")
    elif options.scenario == "pristine":
        runtime = before.get("runtime") if isinstance(before, Mapping) else None
        if not isinstance(runtime, Mapping):
            reasons.append("pristine_runtime_identity_missing")
        else:
            if runtime.get("ccbd_dir_exists") is not False:
                reasons.append("pristine_ccbd_state_exists")
            if runtime.get("agents_dir_exists") is not False:
                reasons.append("pristine_agent_state_exists")
            if runtime.get("source_home_empty") is not True:
                reasons.append("pristine_source_home_not_empty")
    else:  # pragma: no cover - preflight rejects unsupported scenarios.
        reasons.append("unsupported_scenario")

    manifest["ready_for_measurement"] = {
        **ready,
        "status": "failed" if reasons else "ready",
        "reason_codes": sorted(set(reasons)),
        "constructor_resource_audit": constructor_resource_audit,
    }
    manifest["validation"] = {
        "status": "failed" if reasons else "ready_for_measurement",
        "reason_codes": sorted(set(reasons)),
    }
    return manifest


def _scenario_relation(before: object, after: object) -> str:
    if before is None and after is None:
        return "absent"
    if before is None:
        return "created"
    if after is None:
        return "removed"
    return "same" if before == after else "changed"


def _complete_scenario_construction_manifest(
    manifest: dict[str, Any],
    *,
    options: StartupBenchmarkOptions,
    context: ValidatedContext,
    benchmark_id: str,
    run_dir: Path,
    round_role: str,
    startup_record_status: str,
    startup_report_bytes: bytes | None,
    cli_only_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ready = manifest.get("ready_for_measurement")
    after = _capture_scenario_identity(context, benchmark_id=benchmark_id)
    ready_mapping = ready if isinstance(ready, Mapping) else {}
    reasons = list(
        (
            manifest.get("validation", {}).get("reason_codes")
            if isinstance(manifest.get("validation"), Mapping)
            else ()
        )
        or ()
    )
    if startup_record_status != "ok":
        reasons.append("startup_record_not_ok")
    if startup_report_bytes is None:
        reasons.append("startup_report_snapshot_missing")
    if after.get("status") != "ok":
        reasons.append("after_identity_unavailable")
    if not _scenario_authority_is_mounted(after):
        reasons.append("after_authority_not_mounted")
    runtime = after.get("runtime")
    if not isinstance(runtime, Mapping) or (
        runtime.get("active_runtime_record_count") != context.configured_agent_count
    ):
        reasons.append("after_configured_runtime_count_mismatch")
    elif runtime.get("live_active_runtime_record_count") != context.configured_agent_count:
        reasons.append("after_live_runtime_count_mismatch")

    relations = {
        key: _scenario_relation(ready_mapping.get(key), after.get(key))
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
        )
    }
    ready_authority = ready_mapping.get("authority")
    after_authority = after.get("authority")
    ready_lifecycle = (
        ready_authority.get("lifecycle")
        if isinstance(ready_authority, Mapping)
        else None
    )
    after_lifecycle = (
        after_authority.get("lifecycle")
        if isinstance(after_authority, Mapping)
        else None
    )
    relations["daemon_generation"] = _scenario_relation(
        ready_lifecycle.get("generation") if isinstance(ready_lifecycle, Mapping) else None,
        after_lifecycle.get("generation") if isinstance(after_lifecycle, Mapping) else None,
    )
    if options.scenario == "cli-only" and round_role != "prime":
        relations["startup_report_identity"] = _scenario_relation(
            ready_mapping.get("startup_report_identity"),
            after.get("startup_report_identity"),
        )
    slot_relations: dict[str, dict[str, str]] = {}
    fault_injection_observation: dict[str, Any] | None = None
    if options.scenario == "cli-only" and round_role != "prime":
        reasons.extend(
            _cli_only_identity_reason_codes(
                after,
                configured_agent_count=context.configured_agent_count,
                baseline=cli_only_baseline,
                phase="after",
            )
        )
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "daemon_generation",
            "startup_report_identity",
        ):
            if relations[key] != "same":
                reasons.append(f"cli_only_{key}_changed_during_measurement")
    elif options.scenario == "warm" and round_role != "prime":
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "daemon_generation",
        ):
            if relations[key] != "same":
                reasons.append(f"warm_{key}_not_reused")
    elif options.scenario == "mixed-recovery" and round_role != "prime":
        if relations["daemon_identity_digest"] != "same":
            reasons.append("mixed_daemon_identity_not_reused")
        if relations["namespace_identity_digest"] != "same":
            reasons.append("mixed_namespace_identity_not_reused")
        if relations["daemon_generation"] != "same":
            reasons.append("mixed_daemon_generation_not_reused")
        if relations["agent_runtime_identity_digest"] != "changed":
            reasons.append("mixed_agent_runtime_identity_not_recovered")
        before_mapping = manifest.get("before")
        target_slot_id = _mixed_recovery_target_slot_id(
            context,
            benchmark_id=benchmark_id,
        )
        after_reasons, slot_relations = _mixed_recovery_after_reason_codes(
            before_mapping if isinstance(before_mapping, Mapping) else {},
            ready_mapping,
            after,
            target_slot_id=target_slot_id,
            configured_agent_count=context.configured_agent_count,
        )
        reasons.extend(after_reasons)
        ordinal = manifest.get("round_ordinal")
        if type(ordinal) is not int or ordinal < 1:
            reasons.append("mixed_round_ordinal_invalid")
            ordinal = 0
        final_probe = _mixed_recovery_probe_evidence(
            context,
            benchmark_id=benchmark_id,
            expected_target_matches=ordinal * 2 + 1,
            expected_failures=ordinal,
            expected_armed=ordinal,
            expected_released=ordinal,
            expected_active=0,
        )
        construction = manifest.get("construction")
        mixed_construction = (
            construction.get("mixed_recovery")
            if isinstance(construction, Mapping)
            else None
        )
        cursor = (
            mixed_construction.get("supervision_cursor")
            if isinstance(mixed_construction, Mapping)
            else None
        )
        final_supervision = (
            _supervision_recovery_audit(context, cursor=cursor)
            if isinstance(cursor, Mapping)
            else {
                "status": "failed",
                "reason_codes": ["supervision_cursor_missing"],
                "new_event_count": 0,
                "recovery_event_count": 0,
            }
        )
        if final_probe.get("status") != "pass":
            reasons.extend(str(item) for item in final_probe.get("reason_codes") or ())
        if final_supervision.get("status") != "pass":
            reasons.extend(
                str(item) for item in final_supervision.get("reason_codes") or ()
            )
        fault_injection_observation = {
            "target_slot_id": target_slot_id,
            "probe_after_recovery": final_probe,
            "supervision_audit": final_supervision,
            "supervision_fence_s": MIXED_RECOVERY_SUPERVISION_FENCE_S,
        }
        probe_path = _mixed_recovery_probe_path(context, benchmark_id=benchmark_id)
        probe_snapshot_path = run_dir / "launch-probe.json"
        try:
            probe_snapshot_bytes = probe_path.read_bytes()
            _write_bytes(probe_snapshot_path, probe_snapshot_bytes)
            fault_injection_observation["raw_probe_snapshot"] = {
                "artifact": probe_snapshot_path.name,
                "sha256": hashlib.sha256(probe_snapshot_bytes).hexdigest(),
                "access_boundary": "benchmark_run_directory_0700_file_0600",
            }
        except OSError:
            reasons.append("mixed_probe_snapshot_unavailable")
    else:
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "daemon_generation",
        ):
            allowed_relations = (
                {"created"}
                if options.scenario == "pristine"
                else {"created", "changed"}
            )
            if relations[key] not in allowed_relations:
                reasons.append(f"cold_{key}_not_new")

    manifest["observation"] = {
        "status": "failed" if reasons else "matched",
        "startup_report_sha256": (
            hashlib.sha256(startup_report_bytes).hexdigest()
            if startup_report_bytes is not None
            else None
        ),
        "startup_report_snapshot_role": (
            "preexisting_unchanged_sentinel"
            if options.scenario == "cli-only" and round_role != "prime"
            else "report_generated_by_round_start_command"
        ),
        "after": after,
        "relations": relations,
        "slot_relations": slot_relations,
        "fault_injection": fault_injection_observation,
    }
    manifest["validation"] = {
        "status": "failed" if reasons else "pass",
        "reason_codes": sorted(set(str(reason) for reason in reasons)),
    }
    return manifest


def _persist_scenario_construction_manifest(
    path: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    _write_json(path, manifest)
    scenario = manifest.get("scenario")
    validation = manifest.get("validation")
    return {
        "record_type": manifest.get("record_type"),
        "benchmark_id": manifest.get("benchmark_id"),
        "round_ordinal": manifest.get("round_ordinal"),
        "artifact": f"{path.parent.name}/{path.name}",
        "snapshot": path.name,
        "sha256": _sha256_file(path),
        "schema_version": manifest.get("schema_version"),
        "scenario_id": scenario.get("id") if isinstance(scenario, Mapping) else None,
        "scenario": scenario.get("cli_name") if isinstance(scenario, Mapping) else None,
        "variant": scenario.get("variant") if isinstance(scenario, Mapping) else None,
        "instrumentation_arm": (
            manifest.get("expectation", {}).get("instrumentation_arm")
            if isinstance(manifest.get("expectation"), Mapping)
            else None
        ),
        "status": validation.get("status") if isinstance(validation, Mapping) else None,
        "reason_codes": (
            list(validation.get("reason_codes") or ())
            if isinstance(validation, Mapping)
            else []
        ),
    }


def _scenario_phase_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: reference.get(key)
        for key in (
            "record_type",
            "benchmark_id",
            "round_ordinal",
            "artifact",
            "snapshot",
            "sha256",
            "schema_version",
            "scenario_id",
            "scenario",
            "variant",
            "instrumentation_arm",
            "status",
        )
    }


def _persist_scenario_construction_phase(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    if phase not in {"before", "ready", "final"}:
        raise ReportValidationError(f"unsupported scenario construction phase: {phase!r}")
    phase_chain = dict(manifest.get("phase_chain") or {})
    predecessor = phase_chain.get("ready" if phase == "final" else "before")
    manifest["audit_phase"] = {
        "name": phase,
        "predecessor_sha256": (
            predecessor.get("sha256") if isinstance(predecessor, Mapping) else None
        ),
    }
    current_path = run_dir / "scenario-construction.json"
    if phase == "final":
        return _persist_scenario_construction_manifest(current_path, manifest)

    phase_path = run_dir / f"scenario-construction.{phase}.json"
    reference = _persist_scenario_construction_manifest(phase_path, manifest)
    phase_chain[phase] = _scenario_phase_reference(reference)
    manifest["phase_chain"] = phase_chain
    _write_json(current_path, manifest)
    return reference


def run_startup_benchmark(
    options: StartupBenchmarkOptions,
    *,
    dependencies: BenchmarkDependencies = DEFAULT_DEPENDENCIES,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    context = validate_preflight(options, environ=environ)
    benchmark_id = options.benchmark_id or _new_benchmark_id(dependencies.utc_now())
    if not _BENCHMARK_ID_RE.fullmatch(benchmark_id):
        raise SafetyError("benchmark-id contains unsupported characters")

    benchmark_dir = context.result_root / benchmark_id
    instrumentation_ab_plan = (
        _build_instrumentation_ab_plan(options, context=context, benchmark_id=benchmark_id)
        if options.instrumentation_mode == "instrumentation-ab"
        else None
    )
    base_env = _benchmark_env(options, context, environ=environ)
    if options.provider_env_mode == "stub":
        base_env["STUB_LAUNCH_RUN_ID"] = benchmark_id
        for provider, _count in context.provider_counts:
            stem = provider.upper().replace("-", "_")
            base_env[f"{stem}_STUB_LAUNCH_RUN_ID"] = benchmark_id
    if options.scenario == "mixed-recovery":
        _configure_mixed_recovery_stub_commands(
            base_env,
            options=options,
            context=context,
            benchmark_id=benchmark_id,
        )
    run_records: list[dict[str, Any]] = []
    abort_reason: str | None = None
    cleanup_verdict: dict[str, Any] = {"status": "not_run", "reason": "benchmark_not_started"}
    cleanup_permitted = True
    benchmark_may_have_started = False
    pending_exception: Exception | None = None
    summary: dict[str, Any] | None = None
    formal_config_signature: str | None = None
    warm_daemon_generation: int | None = None
    warm_reuse_identity: dict[str, Any] | None = None
    cli_only_baseline: dict[str, Any] | None = None
    cli_only_preservation_audit: dict[str, Any] | None = None
    seen_startup_run_ids: set[str] = set()
    active_resource_instances: set[tuple[int, int]] = set()
    cleanup_resource_instances: set[tuple[int, int]] = set()
    with benchmark_lock(context):
        source_drift = _source_drift_reason(context)
        if source_drift is not None:
            raise SafetyError(source_drift)
        if benchmark_dir.exists():
            raise SafetyError(f"benchmark result directory already exists: {benchmark_dir}")
        context.result_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        benchmark_dir.mkdir(mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(benchmark_dir, 0o700)
        if instrumentation_ab_plan is not None:
            _write_json(benchmark_dir / "benchmark-plan.json", instrumentation_ab_plan)
        try:
            if options.scenario in {"cli-only", "warm", "mixed-recovery"}:
                prime_dir = benchmark_dir / "prime-0001"
                prime_dir.mkdir(mode=0o700)
                benchmark_may_have_started = True
                prime_record = _execute_round(
                    options,
                    context=context,
                    dependencies=dependencies,
                    env=base_env,
                    run_dir=prime_dir,
                    benchmark_id=benchmark_id,
                    ordinal=0,
                    measured_index=None,
                    included_in_statistics=False,
                    round_role="prime",
                    instrumentation_arm="instrumented",
                    precondition_override=None,
                    expected_config_signature=None,
                    expected_daemon_generation=None,
                    expected_daemon_started=True,
                    require_cold_launch=True,
                    require_warm_reuse=False,
                    expected_warm_reuse_identity=None,
                    capture_warm_reuse_identity=(options.scenario == "warm"),
                    active_resource_instances=active_resource_instances,
                    cleanup_resource_instances=cleanup_resource_instances,
                    seen_startup_run_ids=seen_startup_run_ids,
                )
                prime_precondition = prime_record.get("precondition")
                if (
                    isinstance(prime_precondition, Mapping)
                    and prime_precondition.get("kind") == "official_ccb_test_kill"
                    and prime_precondition.get("status") != "ok"
                ):
                    cleanup_permitted = False
                run_records.append(prime_record)
                _write_json(prime_dir / "run.json", prime_record)
                if prime_record["status"] != "ok":
                    abort_reason = str(
                        prime_record.get("failure_reason") or "scenario_prime_failed"
                    )
                else:
                    formal_config_signature = _record_config_signature(prime_record)
                    warm_daemon_generation = _record_daemon_generation(prime_record)
                    if options.scenario == "warm":
                        warm_reuse_identity = _record_warm_reuse_identity(prime_record)
                    if options.scenario == "cli-only":
                        cli_only_baseline = _capture_scenario_identity(
                            context,
                            benchmark_id=benchmark_id,
                        )
                        baseline_reasons = _cli_only_identity_reason_codes(
                            cli_only_baseline,
                            configured_agent_count=context.configured_agent_count,
                            baseline=None,
                            phase="frozen_baseline",
                        )
                        if baseline_reasons:
                            abort_reason = (
                                "cli-only frozen baseline validation failed: "
                                + ", ".join(baseline_reasons)
                            )

            if abort_reason is None and instrumentation_ab_plan is not None:
                abort_reason = _execute_instrumentation_ab_pairs(
                    options,
                    context=context,
                    dependencies=dependencies,
                    env=base_env,
                    benchmark_dir=benchmark_dir,
                    benchmark_id=benchmark_id,
                    plan=instrumentation_ab_plan,
                    expected_config_signature=formal_config_signature,
                    expected_daemon_generation=warm_daemon_generation,
                    expected_warm_reuse_identity=warm_reuse_identity,
                    run_records=run_records,
                    seen_startup_run_ids=seen_startup_run_ids,
                    active_resource_instances=active_resource_instances,
                    cleanup_resource_instances=cleanup_resource_instances,
                )

            if abort_reason is None and instrumentation_ab_plan is None:
                total = options.warmup + options.iterations
                for sequence in range(total):
                    measured_index = sequence - options.warmup
                    included = measured_index >= 0
                    label = (
                        f"run-{measured_index + 1:04d}"
                        if included
                        else f"warmup-{sequence + 1:04d}"
                    )
                    run_dir = benchmark_dir / label
                    run_dir.mkdir(mode=0o700)
                    benchmark_may_have_started = True
                    record = _execute_round(
                        options,
                        context=context,
                        dependencies=dependencies,
                        env=base_env,
                        run_dir=run_dir,
                        benchmark_id=benchmark_id,
                        ordinal=sequence + (
                            1
                            if options.scenario in {"cli-only", "warm", "mixed-recovery"}
                            else 0
                        ),
                        measured_index=(measured_index if included else None),
                        included_in_statistics=included,
                        round_role="measured" if included else "warmup",
                        instrumentation_arm="instrumented",
                        precondition_override=None,
                        expected_config_signature=formal_config_signature,
                        expected_daemon_generation=(
                            warm_daemon_generation
                            if options.scenario in {"cli-only", "warm", "mixed-recovery"}
                            else None
                        ),
                        expected_daemon_started=(
                            False
                            if options.scenario in {"cli-only", "warm", "mixed-recovery"}
                            else True
                        ),
                        require_cold_launch=(options.scenario in {"full-cold", "pristine"}),
                        require_warm_reuse=(options.scenario == "warm"),
                        expected_warm_reuse_identity=(
                            warm_reuse_identity if options.scenario == "warm" else None
                        ),
                        capture_warm_reuse_identity=(options.scenario == "warm"),
                        active_resource_instances=active_resource_instances,
                        cleanup_resource_instances=cleanup_resource_instances,
                        seen_startup_run_ids=seen_startup_run_ids,
                        cli_only_baseline=cli_only_baseline,
                    )
                    run_records.append(record)
                    _write_json(run_dir / "run.json", record)
                    if record["status"] == "ok" and formal_config_signature is None:
                        formal_config_signature = _record_config_signature(record)
                    if record["status"] != "ok":
                        abort_reason = str(record.get("failure_reason") or "round_failed")
                        precondition = record.get("precondition")
                        if (
                            options.scenario == "full-cold"
                            and isinstance(precondition, Mapping)
                            and precondition.get("kind") == "official_ccb_test_kill"
                            and precondition.get("status") != "ok"
                        ):
                            cleanup_permitted = False
                        break
        except Exception as exc:
            pending_exception = exc
            abort_reason = f"unexpected {type(exc).__name__}: {exc}"
        finally:
            if options.scenario == "cli-only" and cli_only_baseline is not None:
                cli_only_preservation_audit = _capture_cli_only_preservation_audit(
                    context,
                    benchmark_id=benchmark_id,
                    baseline=cli_only_baseline,
                )
                if cli_only_preservation_audit.get("status") != "pass" and abort_reason is None:
                    reasons = cli_only_preservation_audit.get("reason_codes") or ()
                    abort_reason = "cli-only pre-teardown preservation failed: " + (
                        ", ".join(str(reason) for reason in reasons) or "unknown"
                    )
            if benchmark_may_have_started and cleanup_permitted:
                source_drift = _source_drift_reason(context)
                if source_drift is None:
                    try:
                        cleanup_verdict = _run_full_cold_precondition(
                            options,
                            context=context,
                            dependencies=dependencies,
                            env=base_env,
                            purpose="final_cleanup",
                        )
                    except Exception as cleanup_exc:
                        cleanup_verdict = {
                            "kind": "official_ccb_test_kill",
                            "purpose": "final_cleanup",
                            "status": "failed",
                            "failure_reason": (
                                f"cleanup raised {type(cleanup_exc).__name__}: {cleanup_exc}"
                            ),
                        }
                else:
                    cleanup_verdict = {
                        "kind": "official_ccb_test_kill",
                        "purpose": "final_cleanup",
                        "status": "skipped",
                        "failure_reason": source_drift,
                    }
            elif benchmark_may_have_started:
                cleanup_verdict = {
                    "kind": "official_ccb_test_kill",
                    "purpose": "final_cleanup",
                    "status": "skipped",
                    "failure_reason": "a full-cold precondition kill did not converge; no additional mutation attempted",
                }
            else:
                cleanup_verdict = {
                    "kind": "official_ccb_test_kill",
                    "purpose": "final_cleanup",
                    "status": "not_required",
                    "failure_reason": "no benchmark command could have started runtime",
                }
            cleanup_resource_audit = _capture_cleanup_resource_evidence(
                options,
                context=context,
                dependencies=dependencies,
                benchmark_id=benchmark_id,
                benchmark_dir=benchmark_dir,
                cleanup_verdict=cleanup_verdict,
                startup_run_ids=seen_startup_run_ids,
                tracked_process_instances=cleanup_resource_instances,
                benchmark_may_have_started=benchmark_may_have_started,
            )
            cleanup_verdict = dict(cleanup_verdict)
            if cli_only_preservation_audit is not None:
                cleanup_verdict["pre_teardown_preservation"] = cli_only_preservation_audit
            cleanup_verdict["resource_audit"] = {
                "snapshot": "cleanup-resource-audit.json",
                "status": cleanup_resource_audit.get("status"),
                "consecutive_clean_snapshots": cleanup_resource_audit.get(
                    "consecutive_clean_snapshots"
                ),
                "required_consecutive_clean_snapshots": cleanup_resource_audit.get(
                    "required_consecutive_clean_snapshots"
                ),
            }
            if cleanup_resource_audit.get("status") == "residue" and abort_reason is None:
                abort_reason = "cleanup_process_residue_detected"
            if cleanup_verdict.get("status") != "ok" and abort_reason is None:
                abort_reason = str(cleanup_verdict.get("failure_reason") or "final_cleanup_failed")
            summary = _build_summary(
                options,
                context=context,
                benchmark_id=benchmark_id,
                benchmark_dir=benchmark_dir,
                runs=run_records,
                abort_reason=abort_reason,
                cleanup_verdict=cleanup_verdict,
                formal_config_signature=formal_config_signature,
                warm_daemon_generation=warm_daemon_generation,
                instrumentation_ab_plan=instrumentation_ab_plan,
            )
            if pending_exception is not None:
                _best_effort_write_json(
                    benchmark_dir / "failure.json",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "ccb_startup_perf_failure",
                        "benchmark_id": benchmark_id,
                        "generated_at": _utc_text(),
                        "error_type": type(pending_exception).__name__,
                        "error": str(pending_exception),
                        "cleanup": cleanup_verdict,
                    },
                )
            summary_write_error = _best_effort_write_json(benchmark_dir / "summary.json", summary)
            if summary_write_error is not None and pending_exception is None:
                pending_exception = summary_write_error

    if pending_exception is not None:
        raise pending_exception
    assert summary is not None
    return summary


def _execute_instrumentation_ab_pairs(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    dependencies: BenchmarkDependencies,
    env: Mapping[str, str],
    benchmark_dir: Path,
    benchmark_id: str,
    plan: Mapping[str, Any],
    expected_config_signature: str | None,
    expected_daemon_generation: int | None,
    expected_warm_reuse_identity: Mapping[str, Any] | None,
    run_records: list[dict[str, Any]],
    seen_startup_run_ids: set[str],
    active_resource_instances: set[tuple[int, int]],
    cleanup_resource_instances: set[tuple[int, int]],
) -> str | None:
    pairs = plan.get("pairs")
    if not isinstance(pairs, list):
        return "instrumentation A/B plan has no pair schedule"
    ordinal = 1
    for pair in pairs:
        if not isinstance(pair, Mapping):
            return "instrumentation A/B plan contains an invalid pair"
        pair_sequence = int(pair.get("pair_sequence") or 0)
        measured_pair_index = pair.get("measured_pair_index")
        included = measured_pair_index is not None
        round_role = "measured" if included else "warmup"
        arm_order = pair.get("arm_order")
        if not isinstance(arm_order, list) or set(arm_order) != {"control", "instrumented"}:
            return f"instrumentation A/B pair {pair_sequence} has invalid arm order"
        for order_position, arm in enumerate(arm_order):
            pair_label = (
                f"pair-{int(measured_pair_index) + 1:04d}"
                if included
                else f"warmup-pair-{pair_sequence:04d}"
            )
            run_dir = benchmark_dir / f"{pair_label}-{arm}"
            run_dir.mkdir(mode=0o700)
            record = _execute_round(
                options,
                context=context,
                dependencies=dependencies,
                env=env,
                run_dir=run_dir,
                benchmark_id=benchmark_id,
                ordinal=ordinal,
                measured_index=(int(measured_pair_index) if included else None),
                included_in_statistics=included,
                round_role=round_role,
                instrumentation_arm=str(arm),
                precondition_override=None,
                expected_config_signature=expected_config_signature,
                expected_daemon_generation=expected_daemon_generation,
                expected_daemon_started=False,
                require_cold_launch=False,
                require_warm_reuse=True,
                expected_warm_reuse_identity=expected_warm_reuse_identity,
                capture_warm_reuse_identity=True,
                active_resource_instances=active_resource_instances,
                cleanup_resource_instances=cleanup_resource_instances,
                seen_startup_run_ids=seen_startup_run_ids,
            )
            record.update(
                {
                    "instrumentation_pair_sequence": pair_sequence,
                    "instrumentation_pair_index": (
                        int(measured_pair_index) if included else None
                    ),
                    "instrumentation_order_position": order_position,
                }
            )
            run_records.append(record)
            _write_json(run_dir / "run.json", record)
            ordinal += 1
            if record.get("status") != "ok":
                return str(record.get("failure_reason") or "instrumentation A/B arm failed")
    return None


def _execute_round(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    dependencies: BenchmarkDependencies,
    env: Mapping[str, str],
    run_dir: Path,
    benchmark_id: str,
    ordinal: int,
    measured_index: int | None,
    included_in_statistics: bool,
    round_role: str,
    instrumentation_arm: str,
    precondition_override: Mapping[str, Any] | None,
    expected_config_signature: str | None,
    expected_daemon_generation: int | None,
    expected_daemon_started: bool | None,
    require_cold_launch: bool,
    require_warm_reuse: bool,
    expected_warm_reuse_identity: Mapping[str, Any] | None,
    capture_warm_reuse_identity: bool,
    active_resource_instances: set[tuple[int, int]],
    cleanup_resource_instances: set[tuple[int, int]],
    seen_startup_run_ids: set[str],
    cli_only_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if instrumentation_arm not in {"control", "instrumented"}:
        raise ReportValidationError(f"unsupported instrumentation arm: {instrumentation_arm}")
    instrumented = instrumentation_arm == "instrumented"
    cli_only_measurement = options.scenario == "cli-only" and round_role != "prime"
    precondition: dict[str, Any] = dict(
        precondition_override or {"kind": "none", "status": "not_required"}
    )
    scenario_manifest = _new_scenario_construction_manifest(
        options,
        context=context,
        benchmark_id=benchmark_id,
        ordinal=ordinal,
        round_role=round_role,
        instrumentation_arm=instrumentation_arm,
        expected_daemon_started=expected_daemon_started,
        require_cold_launch=require_cold_launch,
        require_warm_reuse=require_warm_reuse,
    )
    _persist_scenario_construction_phase(
        run_dir,
        scenario_manifest,
        phase="before",
    )
    source_drift = _source_drift_reason(context)
    if source_drift is not None:
        scenario_manifest = _prepare_scenario_construction_manifest(
            scenario_manifest,
            options=options,
            context=context,
            benchmark_id=benchmark_id,
            round_role=round_role,
            precondition=precondition,
            dependencies=dependencies,
            source_failure=source_drift,
            cli_only_baseline=cli_only_baseline,
        )
        _persist_scenario_construction_phase(
            run_dir,
            scenario_manifest,
            phase="ready",
        )
        record = _base_run_record(
            benchmark_id=benchmark_id,
            ordinal=ordinal,
            measured_index=measured_index,
            included_in_statistics=included_in_statistics,
            scenario=options.scenario,
            round_role=round_role,
            status="failed",
            wall_ms=None,
            timed_out=False,
            exit_code=None,
            failure_reason=source_drift,
            precondition=precondition,
            instrumentation_arm=instrumentation_arm,
        )
        record["scenario_construction"] = _persist_scenario_construction_phase(
            run_dir,
            scenario_manifest,
            phase="final",
        )
        return record
    cold_constructor = options.scenario == "full-cold" or (
        options.scenario in {"cli-only", "warm", "mixed-recovery"}
        and round_role == "prime"
    )
    if cold_constructor and precondition_override is None:
        try:
            precondition = _run_full_cold_precondition(
                options,
                context=context,
                dependencies=dependencies,
                env=env,
                purpose=(
                    "scenario_prime_reset"
                    if round_role == "prime"
                    else "round_precondition"
                ),
            )
        except Exception as exc:
            precondition = {
                "kind": "official_ccb_test_kill",
                "purpose": (
                    "scenario_prime_reset"
                    if round_role == "prime"
                    else "round_precondition"
                ),
                "status": "failed",
                "failure_reason": f"official ccb_test kill audit raised {type(exc).__name__}: {exc}",
            }
    if (
        options.scenario == "mixed-recovery"
        and round_role != "prime"
        and precondition_override is None
    ):
        before_identity = scenario_manifest.get("before")
        try:
            precondition = _run_mixed_recovery_precondition(
                options,
                context=context,
                dependencies=dependencies,
                env=env,
                benchmark_id=benchmark_id,
                ordinal=ordinal,
                before_identity=(
                    before_identity if isinstance(before_identity, Mapping) else {}
                ),
            )
        except Exception as exc:
            precondition = {
                "kind": "official_ccb_test_restart_injected_target_failure",
                "purpose": "mixed_recovery_constructor",
                "status": "failed",
                "failure_reason": (
                    "official mixed recovery constructor raised "
                    f"{type(exc).__name__}: {exc}"
                ),
            }
    scenario_manifest = _prepare_scenario_construction_manifest(
        scenario_manifest,
        options=options,
        context=context,
        benchmark_id=benchmark_id,
        round_role=round_role,
        precondition=precondition,
        dependencies=dependencies,
        cli_only_baseline=cli_only_baseline,
    )
    scenario_reference = _persist_scenario_construction_phase(
        run_dir,
        scenario_manifest,
        phase="ready",
    )
    if scenario_reference.get("status") != "ready_for_measurement":
        reason_codes = scenario_reference.get("reason_codes") or ()
        failure_reason = str(
            precondition.get("failure_reason")
            or "scenario construction failed: "
            + (", ".join(str(reason) for reason in reason_codes) or "unknown")
        )
        record = _base_run_record(
            benchmark_id=benchmark_id,
            ordinal=ordinal,
            measured_index=measured_index,
            included_in_statistics=included_in_statistics,
            scenario=options.scenario,
            round_role=round_role,
            status="failed",
            wall_ms=None,
            timed_out=bool(precondition.get("timed_out")),
            exit_code=precondition.get("exit_code"),
            failure_reason=failure_reason,
            precondition=precondition,
            instrumentation_arm=instrumentation_arm,
        )
        record["scenario_construction"] = _persist_scenario_construction_phase(
            run_dir,
            scenario_manifest,
            phase="final",
        )
        return record

    report_path = _runtime_ccbd_root(context.project_root) / "startup-report.json"
    before = _file_identity(report_path)
    started_utc = dependencies.utc_now().astimezone(timezone.utc)
    started_ns = dependencies.perf_counter_ns()
    command = _start_command(options, context, round_role=round_role)
    command_env = (
        {key: value for key, value in env.items() if not _stub_launch_environment_key(key)}
        if cli_only_measurement
        else env
    )
    selected_start_runner = (
        dependencies.start_command_runner
        if instrumented
        else dependencies.control_start_command_runner
    )
    profile_evidence_required = instrumented and selected_start_runner is not None
    if selected_start_runner is not None:
        result = selected_start_runner(
            command,
            context.project_root,
            command_env,
            options.command_timeout_s,
            options.resource_sample_interval_ms / 1000.0,
            tuple(active_resource_instances),
        )
    else:
        result = dependencies.command_runner(
            command,
            context.project_root,
            command_env,
            options.command_timeout_s,
        )
    ended_ns = dependencies.perf_counter_ns()
    ended_utc = dependencies.utc_now().astimezone(timezone.utc)
    runner_outer_wall_ms = max(0.0, (ended_ns - started_ns) / 1_000_000.0)
    wall_ms = (
        float(result.command_wall_ms)
        if result.command_wall_ms is not None
        and math.isfinite(float(result.command_wall_ms))
        and float(result.command_wall_ms) >= 0
        else runner_outer_wall_ms
    )
    observed_instances = set(result.tracked_process_instances)
    cleanup_resource_instances.update(observed_instances)
    if instrumented and selected_start_runner is not None:
        next_active_instances = (
            set(result.active_process_instances)
            if result.active_process_instances is not None
            else observed_instances
        )
        active_resource_instances.clear()
        active_resource_instances.update(next_active_instances)
    stdout_run_id: str | None = None
    cli_timings_ms: dict[str, float] | None = None
    stdout_process_trace_id: str | None = None
    process_bootstrap_timings_ms: dict[str, float] | None = None
    stdout_parse_error: str | None = None
    if cli_only_measurement:
        try:
            _validate_cli_only_stdout(
                result.stdout,
                expected_version=_read_version(context.source_root),
            )
            if result.stderr:
                raise ReportValidationError("cli-only command unexpectedly emitted stderr")
        except ReportValidationError as exc:
            stdout_parse_error = str(exc)
        if instrumented and result.resource_profile is not None:
            if result.startup_process_trace_id is not None:
                stdout_parse_error = (
                    "cli-only runner unexpectedly retained a startup process trace id"
                )
        elif profile_evidence_required:
            stdout_parse_error = "instrumented cli-only runner did not supply a resource profile"
        elif not instrumented and result.resource_profile is not None:
            stdout_parse_error = "control cli-only command unexpectedly supplied a resource profile"
        elif not instrumented and result.startup_process_trace_id is not None:
            stdout_parse_error = "control cli-only command unexpectedly retained a process trace id"
    else:
        try:
            (
                stdout_run_id,
                cli_timings_ms,
                stdout_process_trace_id,
                process_bootstrap_timings_ms,
            ) = _parse_start_stdout(result.stdout)
        except ReportValidationError as exc:
            stdout_parse_error = str(exc)
        if instrumented and result.resource_profile is not None:
            expected_trace_id = str(result.startup_process_trace_id or "").strip()
            if not expected_trace_id:
                stdout_parse_error = "profiled startup runner did not retain its process trace id"
            elif stdout_process_trace_id != expected_trace_id:
                stdout_parse_error = (
                    "startup process trace correlation mismatch: expected "
                    f"{expected_trace_id}, got {stdout_process_trace_id or '<missing>'}"
                )
            elif process_bootstrap_timings_ms is None:
                stdout_parse_error = "startup process bootstrap timings are missing"
            else:
                missing_process_timings = sorted(
                    set(PROCESS_BOOTSTRAP_TIMING_KEYS) - set(process_bootstrap_timings_ms)
                )
                if missing_process_timings:
                    stdout_parse_error = (
                        "startup process timing trace is missing bootstrap keys: "
                        + ", ".join(missing_process_timings)
                    )
            if stdout_parse_error is None and process_bootstrap_timings_ms is not None:
                extra_process_timings = sorted(
                    set(process_bootstrap_timings_ms) - set(PROCESS_BOOTSTRAP_TIMING_KEYS)
                )
                if extra_process_timings:
                    stdout_parse_error = (
                        "startup process timing trace has unsupported bootstrap keys: "
                        + ", ".join(extra_process_timings)
                    )
            if stdout_parse_error is None and stdout_process_trace_id is None:
                stdout_parse_error = (
                    "startup process trace id is missing from profiled startup stdout"
                )
        elif profile_evidence_required:
            stdout_parse_error = "instrumented startup runner did not supply a resource profile"
        elif not instrumented:
            if result.resource_profile is not None:
                stdout_parse_error = "control startup unexpectedly supplied a resource profile"
            elif result.startup_process_trace_id is not None:
                stdout_parse_error = "control startup unexpectedly retained a process trace id"
            elif stdout_process_trace_id is not None or process_bootstrap_timings_ms is not None:
                stdout_parse_error = "control startup unexpectedly emitted process trace evidence"

    # The first startup may create runtime-root-ref.json and relocate all
    # daemon state away from the project anchor.  Resolve the report path
    # again after the command so the benchmark observes the same state root
    # as ccbd rather than the pre-start fallback path.
    report_path = _runtime_ccbd_root(context.project_root) / "startup-report.json"
    report_read_error: str | None = None
    if cli_only_measurement:
        report_bytes, after, report_read_error = _read_unchanged_report(
            report_path,
            before=before,
        )
        snapshot_path = run_dir / "startup-report-sentinel.json"
    else:
        report_bytes, after = _wait_for_changed_report(
            report_path,
            before=before,
            wait_s=options.report_wait_s,
            dependencies=dependencies,
        )
        snapshot_path = run_dir / "startup-report.json"
    validation_error: str | None = report_read_error
    report: dict[str, Any] | None = None
    sentinel_report: dict[str, Any] | None = None
    readiness_timeline: dict[str, Any] | None = None
    observed_warm_reuse_identity: dict[str, Any] | None = None
    if report_bytes is not None:
        _write_bytes(snapshot_path, report_bytes)
        try:
            decoded_report = json.loads(report_bytes.decode("utf-8"))
            if not isinstance(decoded_report, dict):
                raise ReportValidationError("startup report root must be an object")
            if cli_only_measurement:
                _validate_cli_only_report_sentinel(
                    decoded_report,
                    before=before,
                    after=after,
                    expected_config_signature=expected_config_signature,
                    expected_daemon_generation=expected_daemon_generation,
                )
                sentinel_report = decoded_report
                readiness_timeline = {
                    "schema_version": 1,
                    "status": "not_applicable_cli_only",
                    "reason": "no_startup_transaction",
                    "timeline_complete": False,
                }
            else:
                report = decoded_report
                _validate_startup_report(
                    report,
                    before=before,
                    after=after,
                    started_utc=started_utc,
                    ended_utc=ended_utc,
                    project_root=context.project_root,
                    command_succeeded=(not result.timed_out and result.returncode == 0),
                    stdout_run_id=stdout_run_id,
                    expected_config_signature=expected_config_signature,
                    expected_daemon_generation=expected_daemon_generation,
                    expected_daemon_started=expected_daemon_started,
                    expected_agent_count=context.configured_agent_count,
                    expected_provider_counts=dict(context.provider_counts),
                    require_cold_launch=require_cold_launch,
                )
                raw_readiness = report.get("readiness_timeline")
                if instrumented and isinstance(raw_readiness, Mapping):
                    readiness_timeline = _validate_readiness_timeline(
                        raw_readiness,
                        startup_run_id=str(report.get("startup_run_id") or ""),
                        stdout_process_trace_id=stdout_process_trace_id,
                        daemon_generation=report.get("daemon_generation"),
                        desired_agents=report.get("desired_agents"),
                        command_wall_ms=wall_ms,
                        require_complete=profile_evidence_required,
                    )
                elif profile_evidence_required:
                    raise ReportValidationError(
                        "profiled source startup report is missing readiness_timeline"
                    )
                elif isinstance(raw_readiness, Mapping) and raw_readiness:
                    raise ReportValidationError(
                        "control startup unexpectedly persisted readiness_timeline"
                    )
                elif raw_readiness not in (None, {}):
                    raise ReportValidationError(
                        "control startup has invalid disabled readiness_timeline"
                    )
                if capture_warm_reuse_identity:
                    observed_warm_reuse_identity = _capture_stable_warm_reuse_identity(
                        report,
                        project_root=context.project_root,
                        dependencies=dependencies,
                    )
                if require_warm_reuse:
                    _validate_warm_reuse_report(
                        report,
                        expected_identity=expected_warm_reuse_identity,
                        observed_identity=observed_warm_reuse_identity,
                    )
                if options.scenario == "mixed-recovery" and round_role != "prime":
                    _validate_mixed_recovery_report(
                        report,
                        target_agent_name=_mixed_recovery_target_name(context),
                        configured_agent_names=context.configured_agent_names,
                    )
        except (UnicodeDecodeError, json.JSONDecodeError, ReportValidationError, ValueError) as exc:
            validation_error = str(exc)
    else:
        validation_error = validation_error or (
            "startup report was not created or updated within the report wait window"
        )
    if stdout_parse_error is not None:
        validation_error = stdout_parse_error
    source_drift = _source_drift_reason(context)
    if source_drift is not None:
        validation_error = source_drift
    native_run_id = str((report or {}).get("startup_run_id") or "").strip() or None
    resource_snapshot_path = run_dir / "resource-profile.json"
    resource_integrity_error: str | None = None
    resource_write_error: Exception | None = None
    if instrumented:
        resource_profile, resource_integrity_error = _finalize_resource_profile(
            result.resource_profile,
            context=context,
            benchmark_id=benchmark_id,
            ordinal=ordinal,
            measured_index=measured_index,
            included_in_statistics=included_in_statistics,
            round_role=round_role,
            scenario=options.scenario,
            native_run_id=native_run_id,
            stdout_run_id=stdout_run_id,
            report_bytes=report_bytes,
            report_validation_error=validation_error,
            wall_ms=wall_ms,
            runner_outer_wall_ms=runner_outer_wall_ms,
            tracked_process_instances=result.tracked_process_instances,
            measurement_kind=("cli_only" if cli_only_measurement else "startup"),
            command_stdout=result.stdout,
            cli_only_report_unchanged=(
                cli_only_measurement
                and before is not None
                and after is not None
                and before == after
            ),
            cli_only_authority_token=(
                _scenario_identity_stability_token(cli_only_baseline)
                if cli_only_measurement and isinstance(cli_only_baseline, Mapping)
                else None
            ),
        )
        resource_write_error = _best_effort_write_json(resource_snapshot_path, resource_profile)
        if resource_write_error is not None:
            resource_profile = dict(resource_profile)
            quality = dict(resource_profile.get("quality") or {})
            quality.update(status="degraded", formal_eligible=False)
            reason_codes = list(quality.get("reason_codes") or [])
            reason_codes.append("resource_profile_write_failed")
            quality["reason_codes"] = sorted(set(str(item) for item in reason_codes))
            resource_profile["quality"] = quality
    else:
        resource_profile = {
            "status": "disabled_by_design",
            "quality": {
                "status": "disabled_by_design",
                "formal_eligible": False,
                "reason_codes": ["instrumentation_ab_control"],
            },
        }
    derived_timings_ms = _derived_timings(
        wall_ms=wall_ms,
        cli_timings_ms=cli_timings_ms,
        process_bootstrap_timings_ms=process_bootstrap_timings_ms,
        report=report,
    )
    if validation_error is None:
        for key, residual in derived_timings_ms.items():
            if residual is not None and residual < -NEGATIVE_RESIDUAL_TOLERANCE_MS:
                validation_error = (
                    f"{key} is materially negative ({residual:.3f} ms; "
                    f"tolerance {NEGATIVE_RESIDUAL_TOLERANCE_MS:.3f} ms)"
                )
                break

    status = "ok"
    failure_reason = None
    if result.timed_out:
        status = "timeout"
        failure_reason = (
            "cli-only command timed out" if cli_only_measurement else "startup command timed out"
        )
    elif result.returncode != 0:
        status = "failed"
        failure_reason = (
            f"{'cli-only' if cli_only_measurement else 'startup'} command exited "
            f"with status {result.returncode}"
        )
    elif validation_error is not None:
        status = "failed"
        failure_reason = (
            f"{'cli-only evidence' if cli_only_measurement else 'startup report'} "
            f"validation failed: {validation_error}"
        )
    elif resource_integrity_error is not None:
        status = "failed"
        failure_reason = f"resource profile validation failed: {resource_integrity_error}"

    evidence_report = sentinel_report if cli_only_measurement else report
    if cli_only_measurement:
        startup_report_record = {
            "policy": "unchanged_existing_start_report",
            "snapshot_role": "preexisting_unchanged_sentinel",
            "snapshot": snapshot_path.name if report_bytes is not None else None,
            "before": before,
            "after": after,
            "bytes_unchanged": bool(before is not None and after is not None and before == after),
            "validation": "ok" if validation_error is None else "failed",
            "validation_error": validation_error,
            "native_run_id_available": False,
            "startup_run_id": None,
            "new_startup_run_id_observed": False,
            "correlation": (
                "benchmark_coordinates+exclusive_lock+frozen_authority+"
                "pre_post_identical_report_identity"
            ),
            "trigger": evidence_report.get("trigger") if evidence_report else None,
            "generated_at": evidence_report.get("generated_at") if evidence_report else None,
            "daemon_generation": (
                evidence_report.get("daemon_generation") if evidence_report else None
            ),
            "config_signature": (
                evidence_report.get("config_signature") if evidence_report else None
            ),
            "timings_ms": {},
            "operation_counts": {},
            "warm_reuse_identity": None,
        }
    else:
        startup_report_record = {
            "policy": "changed_start_report",
            "snapshot_role": "report_generated_by_round_start_command",
            "snapshot": snapshot_path.name if report_bytes is not None else None,
            "before": before,
            "after": after,
            "validation": "ok" if validation_error is None else "failed",
            "validation_error": validation_error,
            "native_run_id_available": bool(native_run_id),
            "startup_run_id": native_run_id,
            "correlation": (
                "stdout_report_run_id+exclusive_lock+pre_post_hash+mtime+generated_at_window"
                if native_run_id
                else "exclusive_lock+pre_post_hash+mtime+generated_at_window"
            ),
            "trigger": report.get("trigger") if report else None,
            "generated_at": report.get("generated_at") if report else None,
            "daemon_generation": report.get("daemon_generation") if report else None,
            "config_signature": report.get("config_signature") if report else None,
            "timings_ms": _duration_mapping_for_record(
                report.get("timings_ms") if report else None
            ),
            "operation_counts": _operation_mapping_for_record(
                report.get("operation_counts") if report else None
            ),
            "warm_reuse_identity": observed_warm_reuse_identity,
        }

    record = _base_run_record(
        benchmark_id=benchmark_id,
        ordinal=ordinal,
        measured_index=measured_index,
        included_in_statistics=included_in_statistics,
        scenario=options.scenario,
        round_role=round_role,
        status=status,
        wall_ms=wall_ms,
        timed_out=result.timed_out,
        exit_code=result.returncode,
        failure_reason=failure_reason,
        precondition=precondition,
        instrumentation_arm=instrumentation_arm,
    )
    record.update(
        {
            "started_at": _format_utc(started_utc),
            "ended_at": _format_utc(ended_utc),
            "command": [Path(command[0]).name, Path(command[1]).name, *command[2:]],
            "stdout": _output_metadata(result.stdout),
            "stderr": _output_metadata(result.stderr),
            "runner_outer_wall_ms": runner_outer_wall_ms,
            "startup_report": startup_report_record,
            "resource_profile": {
                "snapshot": resource_snapshot_path.name if instrumented else None,
                "sha256": (
                    _sha256_file(resource_snapshot_path)
                    if resource_write_error is None and resource_snapshot_path.is_file()
                    else None
                ),
                "profile_id": resource_profile.get("profile_id"),
                "status": resource_profile.get("status"),
                "correlation": dict(resource_profile.get("correlation") or {}),
                "quality": dict(resource_profile.get("quality") or {}),
                "capabilities": dict(resource_profile.get("capabilities") or {}),
                "metrics": dict(resource_profile.get("metrics") or {}),
                "sampler": dict(resource_profile.get("sampler") or {}),
                "window": dict(resource_profile.get("window") or {}),
            },
            "cli_timings_ms": dict(cli_timings_ms or {}),
            "process_trace_id": stdout_process_trace_id,
            "process_bootstrap_timings_ms": dict(process_bootstrap_timings_ms or {}),
            "agent_metrics": _agent_metrics_for_record(report),
            "readiness_timeline": dict(readiness_timeline or {}),
            "readiness_ms": (
                _readiness_point_durations(readiness_timeline)
                if readiness_timeline is not None
                else (
                    {}
                    if not instrumented
                    else _derived_readiness_ms(
                    cli_timings_ms=cli_timings_ms,
                    process_bootstrap_timings_ms=process_bootstrap_timings_ms,
                    report=report,
                    )
                )
            ),
            "derived_timings_ms": derived_timings_ms,
            "attribution": (
                _cli_only_attribution_record(wall_ms)
                if cli_only_measurement
                else _attribution_record(
                    wall_ms=wall_ms,
                    cli_timings_ms=cli_timings_ms,
                    process_bootstrap_timings_ms=process_bootstrap_timings_ms,
                    report=report,
                )
            ),
        }
    )
    _enforce_unique_startup_run_id(record, seen=seen_startup_run_ids)
    scenario_manifest = _complete_scenario_construction_manifest(
        scenario_manifest,
        options=options,
        context=context,
        benchmark_id=benchmark_id,
        run_dir=run_dir,
        round_role=round_role,
        startup_record_status=str(record.get("status") or "failed"),
        startup_report_bytes=report_bytes,
        cli_only_baseline=cli_only_baseline,
    )
    scenario_reference = _persist_scenario_construction_phase(
        run_dir,
        scenario_manifest,
        phase="final",
    )
    record["scenario_construction"] = scenario_reference
    if scenario_reference.get("status") != "pass" and record.get("status") == "ok":
        reasons = scenario_reference.get("reason_codes") or ()
        record["status"] = "failed"
        record["failure_reason"] = "scenario construction validation failed: " + (
            ", ".join(str(reason) for reason in reasons) or "unknown"
        )
    return record


def _finalize_resource_profile(
    raw_profile: Mapping[str, Any] | None,
    *,
    context: ValidatedContext,
    benchmark_id: str,
    ordinal: int,
    measured_index: int | None,
    included_in_statistics: bool,
    round_role: str,
    scenario: str,
    native_run_id: str | None,
    stdout_run_id: str | None,
    report_bytes: bytes | None,
    report_validation_error: str | None,
    wall_ms: float,
    runner_outer_wall_ms: float,
    tracked_process_instances: Sequence[tuple[int, int]],
    measurement_kind: str = "startup",
    command_stdout: str = "",
    cli_only_report_unchanged: bool = False,
    cli_only_authority_token: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Bind a raw sampler envelope to validated command coordinates."""

    integrity_errors: list[str] = []
    allowed_fields = {
        "schema_version",
        "record_type",
        "profile_id",
        "status",
        "reason_codes",
        "backend",
        "privacy",
        "capabilities",
        "window",
        "sampler",
        "metrics",
        "buckets",
        "samples",
    }
    if raw_profile is None:
        profile: dict[str, Any] = {
            "schema_version": 1,
            "record_type": "ccb_startup_resource_profile_raw",
            "profile_id": f"rprof_{uuid.uuid4().hex}",
            "status": "unavailable",
            "reason_codes": ["start_runner_did_not_supply_resource_profile"],
            "backend": "unavailable",
            "privacy": {
                "argv_persisted": False,
                "cwd_persisted": False,
                "environment_persisted": False,
                "raw_proc_text_persisted": False,
            },
            "capabilities": {},
            "window": {},
            "sampler": {},
            "metrics": {},
            "buckets": {},
            "samples": [],
        }
    else:
        try:
            profile = json.loads(
                json.dumps(
                    {key: value for key, value in raw_profile.items() if key in allowed_fields},
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError):
            profile = {
                "schema_version": 1,
                "record_type": "ccb_startup_resource_profile_raw",
                "profile_id": f"rprof_{uuid.uuid4().hex}",
                "status": "unavailable",
                "reason_codes": ["resource_profile_not_json_safe"],
                "backend": "unavailable",
                "privacy": {},
                "capabilities": {},
                "window": {},
                "sampler": {},
                "metrics": {},
                "buckets": {},
                "samples": [],
            }
            integrity_errors.append("resource profile is not JSON-safe")
        if "startup_run_id" in raw_profile:
            integrity_errors.append("raw resource profile must not pre-bind startup_run_id")
        if raw_profile.get("record_type") != "ccb_startup_resource_profile_raw":
            integrity_errors.append("unexpected raw resource profile record_type")
        if raw_profile.get("schema_version") != 1:
            integrity_errors.append("unsupported raw resource profile schema_version")
        if raw_profile.get("status") not in {"complete", "degraded", "unavailable"}:
            integrity_errors.append("invalid raw resource profile status")

    privacy = dict(profile.get("privacy") or {})
    for field in (
        "argv_persisted",
        "cwd_persisted",
        "environment_persisted",
        "raw_proc_text_persisted",
    ):
        if privacy.get(field) is not False:
            integrity_errors.append(f"privacy contract not proven: {field}")
    profile_id = str(profile.get("profile_id") or "")
    if not re.fullmatch(r"rprof_[0-9a-f]{32}", profile_id):
        integrity_errors.append("invalid resource profile_id")
    window = dict(profile.get("window") or {})
    sampled_wall = _finite_nonnegative_or_none(window.get("command_wall_ms"))
    if raw_profile is not None and sampled_wall is None:
        integrity_errors.append("resource profile is missing command_wall_ms")
    elif sampled_wall is not None and abs(sampled_wall - wall_ms) > 1.0:
        integrity_errors.append("resource profile command wall does not match benchmark wall")
    signed_outer_residual_ms = runner_outer_wall_ms - wall_ms
    if signed_outer_residual_ms < -NEGATIVE_RESIDUAL_TOLERANCE_MS:
        integrity_errors.append(
            "resource profile command wall exceeds independently measured runner wall "
            f"({signed_outer_residual_ms:.6f} ms residual)"
        )

    if measurement_kind not in {"startup", "cli_only"}:
        integrity_errors.append("unsupported resource profile measurement_kind")
    correlation_reasons: list[str] = []
    if measurement_kind == "cli_only":
        if native_run_id or stdout_run_id:
            correlation_reasons.append("unexpected_startup_run_id_for_cli_only")
        if not cli_only_report_unchanged:
            correlation_reasons.append("cli_only_report_identity_not_unchanged")
        if not cli_only_authority_token:
            correlation_reasons.append("cli_only_frozen_authority_token_missing")
        if raw_profile is not None:
            metrics = profile.get("metrics")
            created_count = (
                metrics.get("created_process_instance_count")
                if isinstance(metrics, Mapping)
                else None
            )
            if type(created_count) is not int or created_count != 1:
                integrity_errors.append(
                    "cli-only resource profile must observe exactly one newly created "
                    "process identity across sampled snapshots"
                )
    else:
        if not native_run_id:
            correlation_reasons.append("native_startup_run_id_missing")
        if not stdout_run_id:
            correlation_reasons.append("stdout_startup_run_id_missing")
        if native_run_id and stdout_run_id and native_run_id != stdout_run_id:
            correlation_reasons.append("stdout_report_startup_run_id_mismatch")
    if report_validation_error is not None:
        correlation_reasons.append(
            "cli_only_evidence_not_validated"
            if measurement_kind == "cli_only"
            else "startup_report_not_validated"
        )
    if profile.get("status") == "unavailable":
        correlation_reasons.append("resource_profile_unavailable")
    correlation_status = (
        "verified"
        if not correlation_reasons and not integrity_errors
        else ("rejected" if integrity_errors else "unverified")
    )
    raw_reasons = [str(item) for item in profile.get("reason_codes") or []]
    quality_reasons = sorted(set((*raw_reasons, *correlation_reasons)))
    raw_status = str(profile.get("status") or "unavailable")
    quality_status = (
        "invalid"
        if integrity_errors
        else ("complete" if raw_status == "complete" and correlation_status == "verified" else "degraded")
    )
    profile.update(
        {
            "schema_version": 1,
            "record_type": "ccb_startup_resource_profile",
            "benchmark_id": benchmark_id,
            "startup_run_id": native_run_id,
            "measurement_kind": measurement_kind,
            "run": {
                "ordinal": ordinal,
                "measured_index": measured_index,
                "round_role": round_role,
                "scenario": scenario,
                "included_in_statistics": included_in_statistics,
            },
            "correlation": {
                "status": correlation_status,
                "method": (
                    "benchmark_coordinates+profile_id+command_output_hash+"
                    "frozen_authority+unchanged_start_report"
                    if measurement_kind == "cli_only"
                    else "stdout_report_startup_run_id+benchmark_coordinates"
                ),
                "stdout_startup_run_id": stdout_run_id,
                "report_startup_run_id": native_run_id,
                "command_stdout_sha256": hashlib.sha256(
                    command_stdout.encode("utf-8", errors="replace")
                ).hexdigest(),
                "cli_only_report_unchanged": (
                    cli_only_report_unchanged if measurement_kind == "cli_only" else None
                ),
                "cli_only_authority_token": (
                    cli_only_authority_token if measurement_kind == "cli_only" else None
                ),
                "startup_report_sha256": hashlib.sha256(report_bytes).hexdigest()
                if report_bytes is not None
                else None,
                "reason_codes": correlation_reasons,
            },
            "quality": {
                "status": quality_status,
                "formal_eligible": quality_status == "complete",
                "reason_codes": quality_reasons,
                "integrity_errors": integrity_errors,
            },
            "scope": {
                "identity_method": "pid+proc_stat_start_ticks",
                "observed_process_instance_count": len(set(tracked_process_instances)),
                "observed_instance_ids": _redacted_process_instance_ids(
                    tracked_process_instances,
                    owner_uuid=context.owner_uuid,
                    benchmark_id=benchmark_id,
                ),
            },
        }
    )
    window.update(
        {
            "benchmark_wall_ms": wall_ms,
            "runner_outer_wall_ms": runner_outer_wall_ms,
            "sampler_and_runner_overhead_ms": signed_outer_residual_ms,
        }
    )
    profile["window"] = window
    return profile, "; ".join(integrity_errors) if integrity_errors else None


def _capture_cleanup_resource_evidence(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    dependencies: BenchmarkDependencies,
    benchmark_id: str,
    benchmark_dir: Path,
    cleanup_verdict: Mapping[str, Any],
    startup_run_ids: set[str],
    tracked_process_instances: set[tuple[int, int]],
    benchmark_may_have_started: bool,
) -> dict[str, Any]:
    path = benchmark_dir / "cleanup-resource-audit.json"
    if not benchmark_may_have_started or cleanup_verdict.get("status") != "ok":
        payload: dict[str, Any] = {
            "schema_version": 1,
            "record_type": "ccb_startup_cleanup_resource_audit",
            "benchmark_id": benchmark_id,
            "status": "not_run",
            "reason_codes": [
                "benchmark_not_started"
                if not benchmark_may_have_started
                else "official_cleanup_not_successful"
            ],
            "official_cleanup_status": cleanup_verdict.get("status"),
            "startup_run_ids": sorted(startup_run_ids),
            "known_process_instance_count": len(tracked_process_instances),
        }
    else:
        try:
            raw = capture_cleanup_resource_audit(
                context.project_root,
                known_instances=tracked_process_instances,
                sample_interval_s=options.resource_sample_interval_ms / 1000.0,
                perf_counter_ns=dependencies.perf_counter_ns,
                sleep=dependencies.sleep,
            )
            payload = dict(raw)
            payload.update(
                record_type="ccb_startup_cleanup_resource_audit",
                benchmark_id=benchmark_id,
                startup_run_ids=sorted(startup_run_ids),
                official_cleanup_status=cleanup_verdict.get("status"),
                authority_evidence=cleanup_verdict.get("authority_evidence"),
            )
        except Exception as exc:
            payload = {
                "schema_version": 1,
                "record_type": "ccb_startup_cleanup_resource_audit",
                "benchmark_id": benchmark_id,
                "status": "degraded",
                "reason_codes": [f"sampler_exception:{type(exc).__name__}"],
                "official_cleanup_status": cleanup_verdict.get("status"),
                "startup_run_ids": sorted(startup_run_ids),
                "known_process_instance_count": len(tracked_process_instances),
            }
    write_error = _best_effort_write_json(path, payload)
    if write_error is not None:
        payload = dict(payload)
        payload["status"] = "degraded"
        reasons = list(payload.get("reason_codes") or [])
        reasons.append("cleanup_resource_audit_write_failed")
        payload["reason_codes"] = sorted(set(str(item) for item in reasons))
    return payload


def _redacted_process_instance_ids(
    instances: Sequence[tuple[int, int]],
    *,
    owner_uuid: str,
    benchmark_id: str,
) -> list[str]:
    key = hashlib.sha256(f"{owner_uuid}:{benchmark_id}".encode("utf-8")).digest()
    return sorted(
        {
            "pinst_"
            + hmac.new(key, f"{pid}:{start_ticks}".encode("ascii"), hashlib.sha256).hexdigest()
            for pid, start_ticks in instances
        }
    )


def _run_full_cold_precondition(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    dependencies: BenchmarkDependencies,
    env: Mapping[str, str],
    purpose: str,
) -> dict[str, Any]:
    command = (sys.executable, str(context.ccb_test_path), "kill")
    started_ns = dependencies.perf_counter_ns()
    drift_reason = _source_drift_reason(context)
    if drift_reason is not None:
        return {
            "kind": "official_ccb_test_kill",
            "purpose": purpose,
            "status": "failed",
            "exit_code": None,
            "timed_out": False,
            "wall_ms": 0.0,
            "command": [Path(command[0]).name, Path(command[1]).name, "kill"],
            "failure_reason": drift_reason,
        }
    try:
        result = dependencies.command_runner(command, context.project_root, env, options.kill_timeout_s)
    except Exception as exc:
        return {
            "kind": "official_ccb_test_kill",
            "purpose": purpose,
            "status": "failed",
            "exit_code": None,
            "timed_out": False,
            "wall_ms": max(0.0, (dependencies.perf_counter_ns() - started_ns) / 1_000_000.0),
            "command": [Path(command[0]).name, Path(command[1]).name, "kill"],
            "failure_reason": f"official ccb_test kill raised {type(exc).__name__}: {exc}",
        }
    elapsed_ms = max(0.0, (dependencies.perf_counter_ns() - started_ns) / 1_000_000.0)
    payload: dict[str, Any] = {
        "kind": "official_ccb_test_kill",
        "purpose": purpose,
        "status": "ok",
        "exit_code": result.returncode,
        "timed_out": result.timed_out,
        "wall_ms": elapsed_ms,
        "command": [Path(command[0]).name, Path(command[1]).name, "kill"],
        "stdout": _output_metadata(result.stdout),
        "stderr": _output_metadata(result.stderr),
    }
    if result.timed_out:
        payload.update(status="failed", failure_reason="official ccb_test kill timed out")
        return payload
    if result.returncode != 0:
        payload.update(status="failed", failure_reason=f"official ccb_test kill exited with status {result.returncode}")
        return payload
    stopped, evidence = _wait_for_unmounted(
        context.project_root,
        wait_s=options.stop_wait_s,
        dependencies=dependencies,
    )
    payload["authority_evidence"] = evidence
    if not stopped:
        payload.update(status="failed", failure_reason="official ccb_test kill did not converge to unmounted")
    return payload


def _run_mixed_recovery_precondition(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    dependencies: BenchmarkDependencies,
    env: Mapping[str, str],
    benchmark_id: str,
    ordinal: int,
    before_identity: Mapping[str, Any],
) -> dict[str, Any]:
    target_name = _mixed_recovery_target_name(context)
    target_slot_id = _mixed_recovery_target_slot_id(context, benchmark_id=benchmark_id)
    payload: dict[str, Any] = {
        "kind": "official_ccb_test_restart_injected_target_failure",
        "purpose": "mixed_recovery_constructor",
        "status": "failed",
        "target_slot_id": target_slot_id,
        "command": [Path(sys.executable).name, context.ccb_test_path.name, "restart", target_slot_id],
    }
    if ordinal < 1:
        payload["failure_reason"] = "mixed recovery round ordinal must follow the prime"
        return payload
    prior_probe = _mixed_recovery_probe_evidence(
        context,
        benchmark_id=benchmark_id,
        expected_target_matches=ordinal * 2 - 1,
        expected_failures=ordinal - 1,
        expected_armed=ordinal - 1,
        expected_released=ordinal - 1,
        expected_active=0,
    )
    payload["probe_before"] = prior_probe
    if prior_probe.get("status") != "pass":
        payload["failure_reason"] = "mixed recovery probe history was not exact before restart"
        return payload
    source_drift = _source_drift_reason(context)
    if source_drift is not None:
        payload["failure_reason"] = source_drift
        return payload
    try:
        cursor = _supervision_cursor(context)
    except ReportValidationError as exc:
        payload["failure_reason"] = str(exc)
        return payload
    payload["supervision_cursor"] = cursor
    command = (sys.executable, str(context.ccb_test_path), "restart", target_name)
    started_ns = dependencies.perf_counter_ns()
    try:
        result = dependencies.command_runner(
            command,
            context.project_root,
            env,
            options.command_timeout_s,
        )
    except Exception as exc:
        payload.update(
            timed_out=False,
            exit_code=None,
            wall_ms=max(
                0.0,
                (dependencies.perf_counter_ns() - started_ns) / 1_000_000.0,
            ),
            failure_reason=f"official ccb_test restart raised {type(exc).__name__}: {exc}",
        )
        return payload
    payload.update(
        timed_out=result.timed_out,
        exit_code=result.returncode,
        wall_ms=(
            float(result.command_wall_ms)
            if result.command_wall_ms is not None
            else max(0.0, (dependencies.perf_counter_ns() - started_ns) / 1_000_000.0)
        ),
        stdout=_output_metadata(result.stdout),
        stderr=_output_metadata(result.stderr),
    )
    armed_probe = _mixed_recovery_probe_evidence(
        context,
        benchmark_id=benchmark_id,
        expected_target_matches=ordinal * 2,
        expected_failures=ordinal - 1,
        expected_armed=ordinal,
        expected_released=ordinal - 1,
        expected_active=1,
    )
    payload["probe_armed"] = armed_probe
    command_ok = not result.timed_out and result.returncode == 0
    armed_enough_to_release = bool(
        armed_probe.get("target_match_count") == ordinal * 2
        and armed_probe.get("armed_failure_count") == ordinal
        and armed_probe.get("active") == 1
    )
    if not armed_enough_to_release:
        payload["failure_reason"] = "restart did not return with the selected failure latch armed"
        return payload

    release_dir = _mixed_recovery_release_dir(context, benchmark_id=benchmark_id)
    release_path = release_dir / f"match-{ordinal * 2:06d}.release"
    if release_path.exists():
        payload["failure_reason"] = "mixed recovery release token already exists"
        return payload
    try:
        release_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(release_dir, 0o700)
        _write_bytes(release_path, b"release\n")
    except OSError as exc:
        payload["failure_reason"] = f"mixed recovery release token could not be persisted: {exc}"
        return payload
    payload["release_token"] = {
        "artifact": f"{release_dir.name}/{release_path.name}",
        "sha256": _sha256_file(release_path),
    }

    latest_probe: dict[str, Any] = armed_probe
    latest_identity: dict[str, Any] | None = None
    latest_ready_reasons: list[str] = ["mixed_fault_not_observed"]
    latest_supervision = _supervision_recovery_audit(context, cursor=cursor)
    attempts = max(1, int(MIXED_RECOVERY_FAULT_WAIT_S / 0.005) + 1)
    for _attempt in range(attempts):
        latest_probe = _mixed_recovery_probe_evidence(
            context,
            benchmark_id=benchmark_id,
            expected_target_matches=ordinal * 2,
            expected_failures=ordinal,
            expected_armed=ordinal,
            expected_released=ordinal,
            expected_active=0,
        )
        if latest_probe.get("status") == "pass":
            latest_identity = _capture_scenario_identity(
                context,
                benchmark_id=benchmark_id,
            )
            latest_ready_reasons = _mixed_recovery_ready_reason_codes(
                before_identity,
                latest_identity,
                target_slot_id=target_slot_id,
                configured_agent_count=context.configured_agent_count,
            )
            latest_supervision = _supervision_recovery_audit(context, cursor=cursor)
            if not latest_ready_reasons and latest_supervision.get("status") == "pass":
                break
        dependencies.sleep(0.005)
    payload["probe_after_failure"] = latest_probe
    payload["mixed_identity"] = latest_identity
    payload["mixed_identity_reason_codes"] = latest_ready_reasons
    payload["supervision_audit"] = latest_supervision
    failure_reasons: list[str] = []
    if not command_ok:
        failure_reasons.append("official_restart_command_failed")
    if armed_probe.get("status") != "pass":
        failure_reasons.extend(str(item) for item in armed_probe.get("reason_codes") or ())
    if latest_probe.get("status") != "pass":
        failure_reasons.extend(str(item) for item in latest_probe.get("reason_codes") or ())
    failure_reasons.extend(latest_ready_reasons)
    if latest_supervision.get("status") != "pass":
        failure_reasons.extend(
            str(item) for item in latest_supervision.get("reason_codes") or ()
        )
    if failure_reasons:
        payload["failure_reason"] = "mixed recovery constructor failed: " + ", ".join(
            sorted(set(failure_reasons))
        )
        return payload
    payload.update(status="ok", failure_reason=None)
    return payload


def _validate_startup_report(
    report: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    started_utc: datetime,
    ended_utc: datetime,
    project_root: Path,
    command_succeeded: bool,
    stdout_run_id: str | None,
    expected_config_signature: str | None,
    expected_daemon_generation: int | None,
    expected_daemon_started: bool | None,
    expected_agent_count: int,
    expected_provider_counts: Mapping[str, int],
    require_cold_launch: bool,
) -> None:
    if report.get("schema_version") != STARTUP_REPORT_SCHEMA_VERSION:
        raise ReportValidationError(
            f"startup report schema_version must be {STARTUP_REPORT_SCHEMA_VERSION}"
        )
    if report.get("api_version") != STARTUP_REPORT_API_VERSION:
        raise ReportValidationError(
            f"startup report api_version must be {STARTUP_REPORT_API_VERSION}"
        )
    if report.get("record_type") != "ccbd_startup_report":
        raise ReportValidationError("record_type is not ccbd_startup_report")
    if report.get("trigger") != "start_command":
        raise ReportValidationError("trigger is not start_command")
    if command_succeeded and report.get("status") != "ok":
        raise ReportValidationError("successful command did not produce an ok startup report")
    project_id = str(report.get("project_id") or "").strip()
    signature = str(report.get("config_signature") or "").strip()
    generation = report.get("daemon_generation")
    if not project_id or not signature or not isinstance(generation, int) or generation < 1:
        raise ReportValidationError("report identity is missing project/config/generation authority")
    if expected_config_signature is not None and signature != expected_config_signature:
        raise ReportValidationError("startup report config_signature changed during the benchmark")
    if expected_daemon_generation is not None and generation != expected_daemon_generation:
        raise ReportValidationError("warm startup daemon_generation changed after priming")
    if type(report.get("daemon_started")) is not bool:
        raise ReportValidationError("startup report daemon_started must be a boolean")
    if (
        expected_daemon_started is not None
        and report.get("daemon_started") is not expected_daemon_started
    ):
        raise ReportValidationError(
            "startup report daemon_started does not match the benchmark scenario"
        )
    report_run_id = str(report.get("startup_run_id") or "").strip() or None
    if report_run_id is None or not re.fullmatch(r"start_[0-9a-f]{32}", report_run_id):
        raise ReportValidationError("startup report has an invalid startup_run_id")
    if stdout_run_id is None:
        raise ReportValidationError("stdout is missing the required startup_run_id")
    if stdout_run_id != report_run_id:
        raise ReportValidationError("stdout startup_run_id does not match startup report")
    supervisor_timings = _validate_duration_mapping(
        report.get("timings_ms"),
        label="startup report timings_ms",
        required=(tuple(SUPERVISOR_REQUIRED_TIMING_KEYS) if command_succeeded else ("supervisor_total",)),
    )
    if command_succeeded:
        flow_stage_sum = sum(
            supervisor_timings[key]
            for key in (
                "context_and_layout_plan",
                "tmux_namespace_runtime",
                "agent_prepare_and_classify",
                "tmux_layout",
                "active_panes_and_cmd",
                "agent_runtime_commit",
                "tmux_cleanup",
            )
        )
        if flow_stage_sum > supervisor_timings["flow_total"] + NEGATIVE_RESIDUAL_TOLERANCE_MS:
            raise ReportValidationError("startup report flow stage sum exceeds flow_total")
        if (
            supervisor_timings["namespace_ensure"] + supervisor_timings["flow_total"]
            > supervisor_timings["supervisor_total"] + NEGATIVE_RESIDUAL_TOLERANCE_MS
        ):
            raise ReportValidationError(
                "startup report namespace_ensure + flow_total exceeds supervisor_total"
            )
    desired_agents = report.get("desired_agents")
    if not isinstance(desired_agents, list) or not all(
        isinstance(item, str) and item.strip() for item in desired_agents
    ):
        raise ReportValidationError("startup report desired_agents must be a valid agent list")
    if len(desired_agents) != len(set(desired_agents)):
        raise ReportValidationError("startup report desired_agents contains duplicates")
    if command_succeeded and len(desired_agents) != expected_agent_count:
        raise ReportValidationError("startup report desired_agents does not match fixture agent count")
    agent_results = report.get("agent_results")
    if not isinstance(agent_results, list):
        raise ReportValidationError("startup report agent_results must be a list")
    result_names: list[str] = []
    observed_provider_counts: dict[str, int] = {}
    for index, result in enumerate(agent_results):
        if not isinstance(result, Mapping):
            raise ReportValidationError(f"startup report agent_results[{index}] must be an object")
        agent_name = str(result.get("agent_name") or "").strip()
        provider = str(result.get("provider") or "").strip().lower()
        action = str(result.get("action") or "").strip()
        health = str(result.get("health") or "").strip().lower()
        if not agent_name or not provider or not action or not health:
            raise ReportValidationError(
                f"startup report agent_results[{index}] is missing identity/outcome fields"
            )
        result_names.append(agent_name)
        observed_provider_counts[provider] = observed_provider_counts.get(provider, 0) + 1
        if command_succeeded and action not in {"attached", "launched", "relaunched"}:
            raise ReportValidationError(
                f"startup report agent_results[{index}] has a non-ready action"
            )
        if command_succeeded and health in {"", "failed", "degraded", "unmounted", "stopped"}:
            raise ReportValidationError(
                f"startup report agent_results[{index}] has non-ready health"
            )
        if require_cold_launch and action not in {"launched", "relaunched"}:
            raise ReportValidationError(
                f"cold startup agent_results[{index}] reused a runtime instead of launching"
            )
        duration_ms = _validated_duration(
            result.get("duration_ms"),
            label=f"startup report agent_results[{index}].duration_ms",
        )
        _validated_duration(
            result.get("provider_prepare_ms"),
            label=f"startup report agent_results[{index}].provider_prepare_ms",
        )
        agent_timings = _validate_duration_mapping(
            result.get("timings_ms"),
            label=f"startup report agent_results[{index}].timings_ms",
            required=(tuple(AGENT_TIMING_KEYS) if command_succeeded else ()),
        )
        substage_sum = sum(agent_timings.get(key, 0.0) for key in AGENT_TIMING_KEYS)
        tolerance = max(1e-6, math.ulp(duration_ms) * 8)
        if substage_sum > duration_ms + tolerance:
            raise ReportValidationError(
                f"startup report agent_results[{index}] substage sum exceeds duration_ms"
            )
    if command_succeeded:
        if len(result_names) != len(set(result_names)):
            raise ReportValidationError("startup report agent_results contains duplicate agents")
        if sorted(result_names) != sorted(desired_agents):
            raise ReportValidationError(
                "startup report agent_results is not a bijection with desired_agents"
            )
        if observed_provider_counts != dict(expected_provider_counts):
            raise ReportValidationError(
                "startup report provider counts do not match the frozen fixture config"
            )
    operation_counts = report.get("operation_counts")
    if not isinstance(operation_counts, Mapping):
        raise ReportValidationError("startup report operation_counts must be an object")
    for key, raw_value in operation_counts.items():
        if not str(key or "").strip() or type(raw_value) is not int or raw_value < 0:
            raise ReportValidationError("startup report operation_counts is malformed")
    if command_succeeded and operation_counts.get("startup_report_write_attempt_count") != 1:
        raise ReportValidationError(
            "startup report must record exactly one startup report write attempt"
        )
    if before is not None and after is not None and before.get("sha256") == after.get("sha256"):
        raise ReportValidationError("startup report content hash did not change")
    if before is not None and after is not None:
        before_mtime = before.get("mtime_ns")
        after_mtime = after.get("mtime_ns")
        if not isinstance(before_mtime, int) or not isinstance(after_mtime, int) or after_mtime <= before_mtime:
            raise ReportValidationError("startup report mtime did not advance")
    generated_at = _parse_utc(str(report.get("generated_at") or ""))
    skew = timedelta(seconds=2)
    if generated_at < started_utc - skew or generated_at > ended_utc + skew:
        raise ReportValidationError("startup report generated_at is outside the external command window")

    runtime_root = _runtime_state_root(project_root)
    runtime_roots = _project_state_roots(project_root)
    try:
        lease = _read_json_object(
            runtime_root / "ccbd" / "lease.json",
            label="ccbd lease",
        )
    except SafetyError as exc:
        raise ReportValidationError(str(exc)) from exc
    if lease.get("record_type") != "ccbd_lease" or lease.get("mount_state") != "mounted":
        raise ReportValidationError("ccbd lease is not mounted authority")
    for key, report_value, lease_value in (
        ("project_id", project_id, lease.get("project_id")),
        ("config_signature", signature, lease.get("config_signature")),
        ("daemon_generation", generation, lease.get("generation")),
    ):
        if report_value != lease_value:
            raise ReportValidationError(f"startup report {key} does not match ccbd lease")
    lifecycle_path = runtime_root / "ccbd" / "lifecycle.json"
    if lifecycle_path.exists():
        try:
            lifecycle = _read_json_object(lifecycle_path, label="ccbd lifecycle")
        except SafetyError as exc:
            raise ReportValidationError(str(exc)) from exc
        if lifecycle.get("phase") != "mounted":
            raise ReportValidationError("ccbd lifecycle is not mounted")
        for key, report_value, lifecycle_value in (
            ("project_id", project_id, lifecycle.get("project_id")),
            ("config_signature", signature, lifecycle.get("config_signature")),
            ("daemon_generation", generation, lifecycle.get("generation")),
        ):
            if report_value != lifecycle_value:
                raise ReportValidationError(f"startup report {key} does not match ccbd lifecycle")


def _capture_stable_warm_reuse_identity(
    report: Mapping[str, Any],
    *,
    project_root: Path,
    dependencies: BenchmarkDependencies,
) -> dict[str, Any]:
    first = _capture_warm_reuse_identity(report, project_root=project_root)
    dependencies.sleep(0.02)
    second = _capture_warm_reuse_identity(report, project_root=project_root)
    difference = _first_identity_difference(first, second)
    if difference is not None:
        raise ReportValidationError(
            f"warm reuse identity was not stable after startup: {difference}"
        )
    return second


def _capture_warm_reuse_identity(
    report: Mapping[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    runtime_roots = _project_state_roots(project_root)
    inspection = report.get("inspection")
    if not isinstance(inspection, Mapping) or not isinstance(inspection.get("lease"), Mapping):
        raise ReportValidationError("warm reuse identity is missing inspected lease authority")
    lease = dict(inspection["lease"])
    for field in ("ccbd_pid", "keeper_pid", "generation"):
        if type(lease.get(field)) is not int or int(lease[field]) < 1:
            raise ReportValidationError(f"warm reuse lease {field} is not a positive integer")
    for field in (
        "project_id",
        "config_signature",
        "daemon_instance_id",
        "boot_id",
        "socket_path",
        "started_at",
    ):
        if not str(lease.get(field) or "").strip():
            raise ReportValidationError(f"warm reuse lease {field} is missing")

    try:
        namespace = _read_json_object(
            _runtime_ccbd_root(project_root) / "state.json",
            label="project namespace state",
        )
    except SafetyError as exc:
        raise ReportValidationError(str(exc)) from exc
    if namespace.get("record_type") != "ccbd_project_namespace_state":
        raise ReportValidationError("warm reuse namespace state has the wrong record_type")
    if type(namespace.get("namespace_epoch")) is not int or namespace["namespace_epoch"] < 1:
        raise ReportValidationError("warm reuse namespace_epoch is not a positive integer")
    if namespace.get("ui_attachable") is not True:
        raise ReportValidationError("warm reuse namespace is not attachable")
    for field in ("project_id", "tmux_socket_path", "tmux_session_name", "layout_signature"):
        if not str(namespace.get(field) or "").strip():
            raise ReportValidationError(f"warm reuse namespace {field} is missing")

    namespace_marker = (
        f"ensure_namespace:epoch={namespace['namespace_epoch']},"
        f"session={namespace['tmux_session_name']}"
    )
    namespace_actions = [
        str(item)
        for item in report.get("actions_taken") or ()
        if str(item).startswith("ensure_namespace:")
    ]
    if namespace_actions != [namespace_marker]:
        raise ReportValidationError(
            "warm reuse report namespace marker does not match namespace authority"
        )

    cleanup_identity = _warm_cleanup_identity(report.get("cleanup_summaries"))
    operation_counts = report.get("operation_counts")
    if not isinstance(operation_counts, Mapping):
        raise ReportValidationError("warm reuse operation_counts must be an object")
    owned_pane_count = operation_counts.get("orphan_cleanup_owned_pane_count")
    expected_owned_count = sum(len(item["owned_panes"]) for item in cleanup_identity)
    if type(owned_pane_count) is not int or owned_pane_count != expected_owned_count:
        raise ReportValidationError(
            "warm reuse owned pane counter does not match cleanup topology"
        )

    agent_results = report.get("agent_results")
    if not isinstance(agent_results, list):
        raise ReportValidationError("warm reuse identity agent_results must be a list")
    agents: dict[str, Any] = {}
    for index, result in enumerate(agent_results):
        if not isinstance(result, Mapping):
            raise ReportValidationError(
                f"warm reuse identity agent_results[{index}] must be an object"
            )
        agent_name = str(result.get("agent_name") or "").strip()
        if not agent_name or agent_name in agents:
            raise ReportValidationError("warm reuse identity has invalid or duplicate agents")
        runtime_pid = result.get("runtime_pid")
        if type(runtime_pid) is not int or runtime_pid < 1:
            raise ReportValidationError(
                f"warm reuse identity agent {agent_name!r} has no runtime_pid"
            )
        for field in (
            "provider",
            "workspace_path",
            "runtime_ref",
            "session_ref",
            "terminal_backend",
            "tmux_socket_path",
            "tmux_window_name",
            "tmux_window_id",
            "pane_id",
            "active_pane_id",
            "runtime_root",
        ):
            if not str(result.get(field) or "").strip():
                raise ReportValidationError(
                    f"warm reuse identity agent {agent_name!r} is missing {field}"
                )

        runtime_path = _runtime_agents_root(project_root) / agent_name / "runtime.json"
        try:
            runtime = _read_json_object(runtime_path, label=f"runtime record for {agent_name}")
        except SafetyError as exc:
            raise ReportValidationError(str(exc)) from exc
        if runtime.get("record_type") != "agent_runtime":
            raise ReportValidationError(
                f"warm reuse runtime record for {agent_name!r} has the wrong record_type"
            )

        session_identity: dict[str, Any] | None = None
        session_path = Path(str(result["session_ref"])).expanduser()
        if session_path.is_absolute() and _path_is_under_any(session_path, runtime_roots):
            try:
                session = _read_json_object(
                    session_path,
                    label=f"provider session record for {agent_name}",
                )
            except SafetyError as exc:
                raise ReportValidationError(str(exc)) from exc
            session_identity = _selected_identity_fields(session, _WARM_SESSION_FIELDS)
            if session_identity.get("agent_name") != agent_name:
                raise ReportValidationError(
                    f"warm reuse provider session record belongs to another agent: {agent_name}"
                )
            for fifo_field in ("input_fifo", "output_fifo"):
                fifo_value = str(session_identity.get(fifo_field) or "").strip()
                if fifo_value:
                    fifo_path = Path(fifo_value).expanduser()
                    if not fifo_path.is_absolute() or not _path_is_under_any(
                        fifo_path, runtime_roots
                    ):
                        raise ReportValidationError(
                            f"warm reuse {fifo_field} for {agent_name!r} is outside project state"
                        )
                    try:
                        fifo_mode = fifo_path.stat().st_mode
                    except OSError as exc:
                        raise ReportValidationError(
                            f"warm reuse {fifo_field} for {agent_name!r} is unavailable: {exc}"
                        ) from exc
                    if not stat.S_ISFIFO(fifo_mode):
                        raise ReportValidationError(
                            f"warm reuse {fifo_field} for {agent_name!r} is not a FIFO"
                        )

        agents[agent_name] = {
            "report": _selected_identity_fields(result, _WARM_AGENT_FIELDS),
            "runtime": _selected_identity_fields(runtime, _WARM_RUNTIME_FIELDS),
            "session": session_identity,
            "process": _warm_process_identity(runtime_pid),
        }

    return {
        "daemon": _selected_identity_fields(lease, _WARM_LEASE_FIELDS),
        "namespace": _selected_identity_fields(namespace, _WARM_NAMESPACE_FIELDS),
        "namespace_marker": namespace_marker,
        "pane_topology": cleanup_identity,
        "agents": {name: agents[name] for name in sorted(agents)},
    }


def _warm_cleanup_identity(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ReportValidationError("warm reuse cleanup_summaries must be a non-empty list")
    identity: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ReportValidationError(f"warm reuse cleanup_summaries[{index}] must be an object")
        socket_name = str(item.get("socket_name") or "").strip()
        if not socket_name:
            raise ReportValidationError(f"warm reuse cleanup_summaries[{index}] has no socket")
        panes: dict[str, list[str]] = {}
        for field in ("owned_panes", "active_panes", "orphaned_panes", "killed_panes"):
            raw_panes = item.get(field)
            if not isinstance(raw_panes, list) or not all(
                isinstance(pane, str) and pane.strip() for pane in raw_panes
            ):
                raise ReportValidationError(
                    f"warm reuse cleanup_summaries[{index}].{field} is malformed"
                )
            normalized = sorted(str(pane).strip() for pane in raw_panes)
            if len(normalized) != len(set(normalized)):
                raise ReportValidationError(
                    f"warm reuse cleanup_summaries[{index}].{field} has duplicates"
                )
            panes[field] = normalized
        if panes["orphaned_panes"] or panes["killed_panes"]:
            raise ReportValidationError("warm reuse cleanup found or killed orphan panes")
        if panes["owned_panes"] != panes["active_panes"]:
            raise ReportValidationError("warm reuse cleanup topology has inactive owned panes")
        identity.append({"socket_name": socket_name, **panes})
    return sorted(identity, key=lambda item: item["socket_name"])


def _selected_identity_fields(
    value: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, Any]:
    return {field: value.get(field) for field in fields}


def _warm_process_identity(pid: int) -> dict[str, Any]:
    alive = False
    try:
        os.kill(pid, 0)
        alive = True
    except PermissionError:
        alive = True
    except (ProcessLookupError, OSError):
        alive = False
    start_ticks: int | None = None
    state: str | None = None
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        parts = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].strip().split()
        state = parts[0]
        start_ticks = int(parts[19])
        if state == "Z":
            alive = False
    except (OSError, IndexError, ValueError):
        pass
    if not alive:
        raise ReportValidationError(f"warm reuse runtime process {pid} is not alive")
    return {
        "pid": pid,
        "alive": True,
        "proc_start_ticks": start_ticks,
    }


def _first_identity_difference(expected: object, observed: object, path: str = "identity") -> str | None:
    if type(expected) is not type(observed):
        return f"{path} type changed from {type(expected).__name__} to {type(observed).__name__}"
    if isinstance(expected, Mapping):
        expected_keys = set(expected)
        observed_keys = set(observed)  # type: ignore[arg-type]
        if expected_keys != observed_keys:
            return f"{path} keys changed"
        for key in sorted(expected_keys, key=str):
            difference = _first_identity_difference(
                expected[key],  # type: ignore[index]
                observed[key],  # type: ignore[index]
                f"{path}.{key}",
            )
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(observed):  # type: ignore[arg-type]
            return f"{path} length changed from {len(expected)} to {len(observed)}"  # type: ignore[arg-type]
        for index, (left, right) in enumerate(zip(expected, observed)):  # type: ignore[arg-type]
            difference = _first_identity_difference(left, right, f"{path}[{index}]")
            if difference is not None:
                return difference
        return None
    if expected != observed:
        return f"{path} changed from {expected!r} to {observed!r}"
    return None


def _validate_warm_reuse_report(
    report: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any] | None = None,
    observed_identity: Mapping[str, Any] | None = None,
) -> None:
    if report.get("daemon_started") is not False:
        raise ReportValidationError("warm sample started a daemon instead of reusing the primed daemon")
    desired_agents = report.get("desired_agents")
    agent_results = report.get("agent_results")
    if not isinstance(desired_agents, list) or not all(
        isinstance(item, str) and item.strip() for item in desired_agents
    ):
        raise ReportValidationError("warm sample desired_agents is not a valid agent list")
    if not isinstance(agent_results, list):
        raise ReportValidationError("warm sample agent_results must be a list")
    result_names: list[str] = []
    for index, result in enumerate(agent_results):
        if not isinstance(result, Mapping):
            raise ReportValidationError(f"warm sample agent_results[{index}] must be an object")
        result_names.append(str(result.get("agent_name") or "").strip())
        if result.get("action") != "attached":
            raise ReportValidationError(
                f"warm sample agent_results[{index}] did not reuse an existing binding"
            )
        prepare_count = result.get("provider_prepare_count")
        if type(prepare_count) is not int or prepare_count != 0:
            raise ReportValidationError(
                f"warm sample agent_results[{index}] performed provider preparation"
            )
        if _validated_duration(
            result.get("provider_prepare_ms"),
            label=f"warm sample agent_results[{index}].provider_prepare_ms",
        ) != 0:
            raise ReportValidationError(
                f"warm sample agent_results[{index}] spent time in provider preparation"
            )
        if result.get("health") not in SUCCESS_RUNTIME_HEALTHS:
            raise ReportValidationError(
                f"warm sample agent_results[{index}].health is not successful"
            )
        for field, expected in (
            ("pane_state", "alive"),
            ("lifecycle_state", "idle"),
            ("desired_state", "mounted"),
            ("reconcile_state", "steady"),
        ):
            if result.get(field) != expected:
                raise ReportValidationError(
                    f"warm sample agent_results[{index}].{field} is not {expected}"
                )
        for field in ("failure_reason", "binding_reject_reason"):
            if result.get(field) not in (None, ""):
                raise ReportValidationError(
                    f"warm sample agent_results[{index}] retained {field}"
                )
        timings = _validate_duration_mapping(
            result.get("timings_ms"),
            label=f"warm sample agent_results[{index}].timings_ms",
            required=tuple(_WARM_LAUNCH_ONLY_TIMING_KEYS),
        )
        if any(timings[key] != 0 for key in _WARM_LAUNCH_ONLY_TIMING_KEYS):
            raise ReportValidationError(
                f"warm sample agent_results[{index}] performed launch-only work"
            )
    if sorted(result_names) != sorted(desired_agents):
        raise ReportValidationError("warm sample did not report one reused binding for every desired agent")
    actions = report.get("actions_taken")
    if not isinstance(actions, list):
        raise ReportValidationError("warm sample actions_taken must be a list")
    for action in actions:
        text = str(action or "")
        if text.startswith(_WARM_MUTATING_ACTION_PREFIXES):
            raise ReportValidationError(f"warm sample performed mutating action: {text}")
    reuse_actions = sorted(
        text for text in (str(item or "") for item in actions) if text.startswith("reuse_binding:")
    )
    if reuse_actions != sorted(f"reuse_binding:{name}" for name in desired_agents):
        raise ReportValidationError("warm sample reuse actions do not match desired agents")
    operation_counts = report.get("operation_counts")
    if not isinstance(operation_counts, Mapping):
        raise ReportValidationError("warm sample operation_counts must be an object")
    for key, raw_value in operation_counts.items():
        if not str(key).startswith("provider_prepare"):
            continue
        if type(raw_value) is not int or raw_value < 0:
            raise ReportValidationError("warm sample has malformed provider preparation counters")
        if raw_value != 0:
            raise ReportValidationError("warm sample operation counters recorded provider preparation")
    if expected_identity is not None:
        if observed_identity is None:
            raise ReportValidationError("warm sample is missing a live reuse identity snapshot")
        difference = _first_identity_difference(expected_identity, observed_identity)
        if difference is not None:
            raise ReportValidationError(f"warm sample identity drifted after priming: {difference}")


def _validate_mixed_recovery_report(
    report: Mapping[str, Any],
    *,
    target_agent_name: str,
    configured_agent_names: Sequence[str],
) -> None:
    if report.get("daemon_started") is not False:
        raise ReportValidationError("mixed recovery started a new daemon")
    desired_agents = report.get("desired_agents")
    if not isinstance(desired_agents, list) or sorted(desired_agents) != sorted(
        configured_agent_names
    ):
        raise ReportValidationError("mixed recovery desired_agents changed from the fixture")
    agent_results = report.get("agent_results")
    if not isinstance(agent_results, list):
        raise ReportValidationError("mixed recovery agent_results must be a list")
    results: dict[str, Mapping[str, Any]] = {}
    for index, result in enumerate(agent_results):
        if not isinstance(result, Mapping):
            raise ReportValidationError(
                f"mixed recovery agent_results[{index}] must be an object"
            )
        name = str(result.get("agent_name") or "").strip()
        if not name or name in results:
            raise ReportValidationError("mixed recovery has invalid or duplicate agent results")
        results[name] = result
    if set(results) != set(configured_agent_names) or target_agent_name not in results:
        raise ReportValidationError("mixed recovery agent results do not match the fixture")
    for name, result in results.items():
        target = name == target_agent_name
        action = result.get("action")
        if target:
            if action != "relaunched":
                raise ReportValidationError(
                    "mixed recovery target was not the unique relaunched runtime"
                )
            if result.get("binding_reject_reason") != "pane_dead":
                raise ReportValidationError(
                    "mixed recovery target did not retain the expected pane_dead cause"
                )
            expected_prepare_count = 1
        else:
            if action != "attached":
                raise ReportValidationError("mixed recovery relaunched a peer runtime")
            expected_prepare_count = 0
        prepare_count = result.get("provider_prepare_count")
        if type(prepare_count) is not int or prepare_count != expected_prepare_count:
            raise ReportValidationError(
                "mixed recovery provider preparation was not isolated to the target"
            )
        _validated_duration(
            result.get("provider_prepare_ms"),
            label=f"mixed recovery result {name!r}.provider_prepare_ms",
        )
        if not target and float(result.get("provider_prepare_ms") or 0.0) != 0.0:
            raise ReportValidationError("mixed recovery peer spent time in provider preparation")
        if result.get("health") not in SUCCESS_RUNTIME_HEALTHS:
            raise ReportValidationError("mixed recovery result health is not successful")
        for field, expected in (
            ("pane_state", "alive"),
            ("lifecycle_state", "idle"),
            ("desired_state", "mounted"),
            ("reconcile_state", "steady"),
        ):
            if result.get(field) != expected:
                raise ReportValidationError(
                    f"mixed recovery result {name!r}.{field} is not {expected}"
                )
        if not target:
            timings = _validate_duration_mapping(
                result.get("timings_ms"),
                label=f"mixed recovery peer {name!r}.timings_ms",
                required=tuple(_WARM_LAUNCH_ONLY_TIMING_KEYS),
            )
            if any(timings[key] != 0 for key in _WARM_LAUNCH_ONLY_TIMING_KEYS):
                raise ReportValidationError("mixed recovery peer performed launch-only work")

    actions = report.get("actions_taken")
    if not isinstance(actions, list):
        raise ReportValidationError("mixed recovery actions_taken must be a list")
    expected_target_action = f"relaunch_runtime:{target_agent_name}"
    launch_actions = [
        str(action)
        for action in actions
        if str(action).startswith(("launch_runtime:", "relaunch_runtime:"))
    ]
    if launch_actions != [expected_target_action]:
        raise ReportValidationError("mixed recovery launch action is not unique to the target")
    reuse_actions = sorted(
        str(action) for action in actions if str(action).startswith("reuse_binding:")
    )
    expected_reuse = sorted(
        f"reuse_binding:{name}" for name in configured_agent_names if name != target_agent_name
    )
    if reuse_actions != expected_reuse:
        raise ReportValidationError("mixed recovery peer reuse actions are incomplete")
    topology_actions = [
        str(action) for action in actions if str(action).startswith("use_namespace_topology:")
    ]
    if topology_actions != [f"use_namespace_topology:{target_agent_name}"]:
        raise ReportValidationError(
            "mixed recovery did not assign exactly the dead target's structural slot"
        )
    if any(
        str(action).startswith("bootstrap_cmd_pane:")
        for action in actions
    ):
        raise ReportValidationError("mixed recovery performed a project-wide cold reset")

    operation_counts = report.get("operation_counts")
    if not isinstance(operation_counts, Mapping):
        raise ReportValidationError("mixed recovery operation_counts must be an object")
    for key in ("provider_prepare_attempt_count", "provider_prepare_count"):
        if operation_counts.get(key) != 1:
            raise ReportValidationError(f"mixed recovery {key} must be exactly one")
    cleanup = report.get("cleanup_summaries")
    if not isinstance(cleanup, list) or not cleanup:
        raise ReportValidationError("mixed recovery cleanup topology is missing")
    if any(
        not isinstance(item, Mapping)
        or item.get("orphaned_panes") not in ([], ())
        or item.get("killed_panes") not in ([], ())
        for item in cleanup
    ):
        raise ReportValidationError("mixed recovery found or killed project pane residue")


def _validated_duration(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ReportValidationError(f"{label} must be a finite non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReportValidationError(f"{label} must be a finite non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ReportValidationError(f"{label} must be a finite non-negative number")
    return parsed


def _validate_duration_mapping(
    value: object,
    *,
    label: str,
    required: Sequence[str] = (),
) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ReportValidationError(f"{label} must be an object")
    missing = sorted(set(required) - {str(key) for key in value})
    if missing:
        raise ReportValidationError(f"{label} is missing required keys: {', '.join(missing)}")
    return {
        str(key): _validated_duration(raw_value, label=f"{label}.{key}")
        for key, raw_value in value.items()
    }


def _record_config_signature(record: Mapping[str, Any]) -> str:
    startup_report = record.get("startup_report")
    signature = (
        str(startup_report.get("config_signature") or "").strip()
        if isinstance(startup_report, Mapping)
        else ""
    )
    if not signature:
        raise ReportValidationError("successful benchmark record is missing config_signature")
    return signature


def _record_daemon_generation(record: Mapping[str, Any]) -> int:
    startup_report = record.get("startup_report")
    generation = (
        startup_report.get("daemon_generation")
        if isinstance(startup_report, Mapping)
        else None
    )
    if type(generation) is not int or generation < 1:
        raise ReportValidationError("successful benchmark record is missing daemon_generation")
    return generation


def _record_warm_reuse_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    startup_report = record.get("startup_report")
    identity = (
        startup_report.get("warm_reuse_identity")
        if isinstance(startup_report, Mapping)
        else None
    )
    if not isinstance(identity, Mapping) or not identity:
        raise ReportValidationError(
            "successful warm prime is missing a complete reuse identity"
        )
    return json.loads(json.dumps(identity, sort_keys=True))


def summarize_samples(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "n": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
            "mean": None,
            "stddev": None,
            "mad": None,
            "iqr": None,
            "cv": None,
        }
    ordered = sorted(clean)
    mean = statistics.fmean(ordered)
    stddev = statistics.pstdev(ordered)
    median = _percentile(ordered, 0.50)
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p50": median,
        "p90": _percentile(ordered, 0.90),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
        "mean": mean,
        "stddev": stddev,
        "mad": statistics.median(abs(value - median) for value in ordered),
        "iqr": _percentile(ordered, 0.75) - _percentile(ordered, 0.25),
        "cv": stddev / mean if mean else None,
    }


def _mixed_recovery_manifest_audit(
    payload: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    benchmark_dir: Path,
    run_directory_name: str,
) -> tuple[str, ...]:
    if run.get("round_role") == "prime":
        return ()
    reasons: list[str] = []
    ordinal = run.get("ordinal")
    if type(ordinal) is not int or ordinal < 1:
        return ("mixed_manifest_ordinal_invalid",)
    expectation = payload.get("expectation")
    construction = payload.get("construction")
    observation = payload.get("observation")
    target_slot_id = (
        str(expectation.get("recovery_target_slot_id") or "")
        if isinstance(expectation, Mapping)
        else ""
    )
    if not re.fullmatch(r"scslot_[0-9a-f]{64}", target_slot_id):
        reasons.append("mixed_manifest_target_slot_invalid")
    mixed_construction = (
        construction.get("mixed_recovery")
        if isinstance(construction, Mapping)
        else None
    )
    fault = observation.get("fault_injection") if isinstance(observation, Mapping) else None
    if not isinstance(mixed_construction, Mapping):
        reasons.append("mixed_manifest_constructor_evidence_missing")
        mixed_construction = {}
    if not isinstance(fault, Mapping):
        reasons.append("mixed_manifest_final_fault_evidence_missing")
        fault = {}
    if mixed_construction.get("target_slot_id") != target_slot_id:
        reasons.append("mixed_manifest_constructor_target_mismatch")
    if fault.get("target_slot_id") != target_slot_id:
        reasons.append("mixed_manifest_final_target_mismatch")
    constructor_probe = mixed_construction.get("probe_after_failure")
    final_probe = fault.get("probe_after_recovery")
    constructor_supervision = mixed_construction.get("supervision_audit")
    final_supervision = fault.get("supervision_audit")
    for label, evidence in (
        ("constructor_probe", constructor_probe),
        ("final_probe", final_probe),
        ("constructor_supervision", constructor_supervision),
        ("final_supervision", final_supervision),
    ):
        if not isinstance(evidence, Mapping) or evidence.get("status") != "pass":
            reasons.append(f"mixed_manifest_{label}_not_pass")
    if isinstance(constructor_probe, Mapping) and (
        constructor_probe.get("target_match_count") != ordinal * 2
        or constructor_probe.get("injected_failure_count") != ordinal
        or constructor_probe.get("active") != 0
    ):
        reasons.append("mixed_manifest_constructor_probe_counts_invalid")
    if isinstance(final_probe, Mapping) and (
        final_probe.get("target_match_count") != ordinal * 2 + 1
        or final_probe.get("injected_failure_count") != ordinal
        or final_probe.get("armed_failure_count") != ordinal
        or final_probe.get("released_failure_count") != ordinal
        or final_probe.get("active") != 0
        or final_probe.get("max_observed") != 1
    ):
        reasons.append("mixed_manifest_final_probe_counts_invalid")
    if any(
        isinstance(evidence, Mapping) and evidence.get("recovery_event_count") != 0
        for evidence in (constructor_supervision, final_supervision)
    ):
        reasons.append("mixed_manifest_supervision_recovery_detected")
    slot_relations = observation.get("slot_relations") if isinstance(observation, Mapping) else None
    if not isinstance(slot_relations, Mapping) or target_slot_id not in slot_relations:
        reasons.append("mixed_manifest_slot_relations_missing")
    else:
        for slot_id, relation in slot_relations.items():
            if not re.fullmatch(r"scslot_[0-9a-f]{64}", str(slot_id)) or not isinstance(
                relation,
                Mapping,
            ):
                reasons.append("mixed_manifest_slot_relation_invalid")
                continue
            expected = (
                {"before_to_ready": "changed", "ready_to_after": "changed"}
                if slot_id == target_slot_id
                else {"before_to_ready": "same", "ready_to_after": "same"}
            )
            if dict(relation) != expected:
                reasons.append("mixed_manifest_slot_relation_semantics_invalid")

    snapshot = fault.get("raw_probe_snapshot") if isinstance(fault, Mapping) else None
    if not isinstance(snapshot, Mapping) or snapshot.get("artifact") != "launch-probe.json":
        reasons.append("mixed_manifest_probe_snapshot_reference_invalid")
        return tuple(sorted(set(reasons)))
    snapshot_path = benchmark_dir / run_directory_name / "launch-probe.json"
    try:
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot_mode = stat.S_IMODE(snapshot_path.stat().st_mode)
        run_dir_mode = stat.S_IMODE(snapshot_path.parent.stat().st_mode)
    except OSError:
        reasons.append("mixed_manifest_probe_snapshot_missing")
        return tuple(sorted(set(reasons)))
    if hashlib.sha256(snapshot_bytes).hexdigest() != snapshot.get("sha256"):
        reasons.append("mixed_manifest_probe_snapshot_digest_mismatch")
    if snapshot_mode != 0o600 or run_dir_mode & 0o077:
        reasons.append("mixed_manifest_probe_snapshot_permissions_invalid")
    try:
        raw_probe = json.loads(snapshot_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reasons.append("mixed_manifest_probe_snapshot_json_invalid")
        return tuple(sorted(set(reasons)))
    events = raw_probe.get("events") if isinstance(raw_probe, Mapping) else None
    if (
        not isinstance(raw_probe, Mapping)
        or raw_probe.get("run_id") != run.get("benchmark_id")
        or raw_probe.get("active") != 0
        or raw_probe.get("max_observed") != 1
        or not isinstance(events, list)
        or not all(isinstance(event, Mapping) for event in events)
    ):
        reasons.append("mixed_manifest_probe_snapshot_semantics_invalid")
        return tuple(sorted(set(reasons)))
    selected_events = [
        event
        for event in events
        if event.get("event") == "injection_match" and event.get("selected") is True
    ]
    selected_agents = {str(event.get("agent") or "") for event in selected_events}
    if len(selected_agents) != 1 or "" in selected_agents:
        reasons.append("mixed_manifest_probe_snapshot_target_ambiguous")
        return tuple(sorted(set(reasons)))
    raw_target = next(iter(selected_agents))
    target_events = [event for event in events if event.get("agent") == raw_target]
    matches = [event for event in target_events if event.get("event") == "injection_match"]
    if [event.get("match_index") for event in matches] != list(range(1, ordinal * 2 + 2)):
        reasons.append("mixed_manifest_probe_snapshot_match_sequence_invalid")
    if [
        event.get("match_index")
        for event in matches
        if event.get("selected") is True
    ] != list(range(2, ordinal * 2 + 1, 2)):
        reasons.append("mixed_manifest_probe_snapshot_selection_invalid")
    for event_kind in (
        "injected_failure_armed",
        "injected_failure_released",
        "injected_failure",
    ):
        indices = [
            event.get("match_index")
            for event in target_events
            if event.get("event") == event_kind
        ]
        if indices != list(range(2, ordinal * 2 + 1, 2)):
            reasons.append(f"mixed_manifest_probe_snapshot_{event_kind}_invalid")
    return tuple(sorted(set(reasons)))


def _cli_only_manifest_audit(
    payload: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    round_role = str(run.get("round_role") or "")
    expectation = payload.get("expectation")
    observation = payload.get("observation")
    if not isinstance(expectation, Mapping) or not isinstance(observation, Mapping):
        return ("cli_only_manifest_semantics_missing",)
    expected_policy = (
        "changed_start_report" if round_role == "prime" else "unchanged_existing_start_report"
    )
    if expectation.get("report_policy") != expected_policy:
        reasons.append("cli_only_manifest_report_policy_invalid")
    startup_report = run.get("startup_report")
    if not isinstance(startup_report, Mapping):
        reasons.append("cli_only_run_startup_report_evidence_missing")
        return tuple(sorted(set(reasons)))
    if round_role == "prime":
        if run.get("measurement_kind") != "startup":
            reasons.append("cli_only_prime_measurement_kind_invalid")
        if startup_report.get("native_run_id_available") is not True:
            reasons.append("cli_only_prime_native_run_id_missing")
        if observation.get("startup_report_snapshot_role") != (
            "report_generated_by_round_start_command"
        ):
            reasons.append("cli_only_prime_snapshot_role_invalid")
        return tuple(sorted(set(reasons)))

    if run.get("measurement_kind") != "cli_only":
        reasons.append("cli_only_measurement_kind_invalid")
    if observation.get("startup_report_snapshot_role") != "preexisting_unchanged_sentinel":
        reasons.append("cli_only_manifest_snapshot_role_invalid")
    frozen = expectation.get("frozen_baseline")
    if not isinstance(frozen, Mapping) or frozen.get("status") != "ok":
        reasons.append("cli_only_manifest_frozen_baseline_missing")
    relations = observation.get("relations")
    if not isinstance(relations, Mapping):
        reasons.append("cli_only_manifest_relations_missing")
    else:
        for key in (
            "daemon_identity_digest",
            "namespace_identity_digest",
            "agent_runtime_identity_digest",
            "daemon_generation",
            "startup_report_identity",
        ):
            if relations.get(key) != "same":
                reasons.append(f"cli_only_manifest_{key}_not_same")
    if startup_report.get("policy") != "unchanged_existing_start_report":
        reasons.append("cli_only_run_report_policy_invalid")
    if startup_report.get("snapshot_role") != "preexisting_unchanged_sentinel":
        reasons.append("cli_only_run_report_snapshot_role_invalid")
    if startup_report.get("native_run_id_available") is not False:
        reasons.append("cli_only_run_native_id_availability_invalid")
    if startup_report.get("startup_run_id") is not None:
        reasons.append("cli_only_run_unexpected_startup_run_id")
    if startup_report.get("new_startup_run_id_observed") is not False:
        reasons.append("cli_only_run_new_startup_id_semantics_invalid")
    if startup_report.get("bytes_unchanged") is not True:
        reasons.append("cli_only_run_report_not_unchanged")
    before = startup_report.get("before")
    after = startup_report.get("after")
    frozen_report = frozen.get("startup_report_identity") if isinstance(frozen, Mapping) else None
    if not isinstance(before, Mapping) or before != after or before != frozen_report:
        reasons.append("cli_only_run_report_identity_not_frozen")
    return tuple(sorted(set(reasons)))


def _scenario_construction_reference_audit(
    reference: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    benchmark_dir: Path,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    run_scenario = str(run.get("scenario") or "")
    expected_spec = SCENARIO_SPECS.get(run_scenario)
    expected_scenario_id = expected_spec.get("id") if expected_spec else None
    if reference.get("record_type") != SCENARIO_CONSTRUCTION_RECORD_TYPE:
        reasons.append("scenario_manifest_reference_record_type_invalid")
    if reference.get("schema_version") != SCENARIO_CONSTRUCTION_SCHEMA_VERSION:
        reasons.append("scenario_manifest_reference_schema_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256") or "")):
        reasons.append("scenario_manifest_reference_digest_invalid")
    if str(reference.get("snapshot") or "") != "scenario-construction.json":
        reasons.append("scenario_manifest_reference_snapshot_invalid")
    if str(reference.get("scenario_id") or "") not in {"S0", "S1", "S3", "S4", "S5a"}:
        reasons.append("scenario_manifest_reference_scenario_invalid")
    if str(reference.get("status") or "") not in {"pass", "failed"}:
        reasons.append("scenario_manifest_reference_status_invalid")
    expected_manifest_status = "pass" if run.get("status") == "ok" else "failed"
    if reference.get("status") != expected_manifest_status:
        reasons.append("scenario_manifest_reference_run_status_mismatch")
    if reference.get("benchmark_id") != run.get("benchmark_id"):
        reasons.append("scenario_manifest_reference_run_benchmark_mismatch")
    if reference.get("round_ordinal") != run.get("ordinal"):
        reasons.append("scenario_manifest_reference_run_ordinal_mismatch")
    if reference.get("scenario") != run_scenario:
        reasons.append("scenario_manifest_reference_run_scenario_mismatch")
    if reference.get("scenario_id") != expected_scenario_id:
        reasons.append("scenario_manifest_reference_run_scenario_id_mismatch")
    if reference.get("variant") != run.get("round_role"):
        reasons.append("scenario_manifest_reference_run_variant_mismatch")
    if reference.get("instrumentation_arm") != run.get("instrumentation_arm"):
        reasons.append("scenario_manifest_reference_run_instrumentation_mismatch")
    reference_reason_codes = reference.get("reason_codes")
    if not isinstance(reference_reason_codes, list):
        reasons.append("scenario_manifest_reference_reason_codes_invalid")
    elif reference.get("status") == "pass" and reference_reason_codes:
        reasons.append("scenario_manifest_reference_pass_has_reasons")

    artifact = str(reference.get("artifact") or "")
    artifact_path = PurePosixPath(artifact)
    if (
        artifact_path.is_absolute()
        or len(artifact_path.parts) != 2
        or any(part in {"", ".", ".."} for part in artifact_path.parts)
        or artifact_path.name != "scenario-construction.json"
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", artifact_path.parts[0])
    ):
        reasons.append("scenario_manifest_artifact_path_invalid")
        return False, tuple(sorted(set(reasons)))

    path = benchmark_dir / artifact_path.parts[0] / artifact_path.name
    try:
        payload_bytes = path.read_bytes()
    except FileNotFoundError:
        reasons.append("scenario_manifest_artifact_missing")
        return False, tuple(sorted(set(reasons)))
    except OSError:
        reasons.append("scenario_manifest_artifact_unreadable")
        return False, tuple(sorted(set(reasons)))
    if hashlib.sha256(payload_bytes).hexdigest() != reference.get("sha256"):
        reasons.append("scenario_manifest_artifact_digest_mismatch")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reasons.append("scenario_manifest_artifact_json_invalid")
        return False, tuple(sorted(set(reasons)))
    if not isinstance(payload, Mapping):
        reasons.append("scenario_manifest_artifact_root_invalid")
        return False, tuple(sorted(set(reasons)))
    scenario = payload.get("scenario")
    validation = payload.get("validation")
    privacy = payload.get("privacy")
    expectation = payload.get("expectation")
    construction = payload.get("construction")
    ready_for_measurement = payload.get("ready_for_measurement")
    observation = payload.get("observation")
    if payload.get("record_type") != SCENARIO_CONSTRUCTION_RECORD_TYPE:
        reasons.append("scenario_manifest_artifact_record_type_invalid")
    if payload.get("schema_version") != SCENARIO_CONSTRUCTION_SCHEMA_VERSION:
        reasons.append("scenario_manifest_artifact_schema_invalid")
    if payload.get("benchmark_id") != reference.get("benchmark_id"):
        reasons.append("scenario_manifest_artifact_benchmark_mismatch")
    if payload.get("round_ordinal") != run.get("ordinal"):
        reasons.append("scenario_manifest_artifact_ordinal_mismatch")
    if not isinstance(scenario, Mapping):
        reasons.append("scenario_manifest_artifact_scenario_missing")
    else:
        if scenario.get("id") != reference.get("scenario_id"):
            reasons.append("scenario_manifest_artifact_scenario_mismatch")
        if scenario.get("variant") != reference.get("variant"):
            reasons.append("scenario_manifest_artifact_variant_mismatch")
        if scenario.get("cli_name") != run_scenario:
            reasons.append("scenario_manifest_artifact_cli_scenario_mismatch")
    if not isinstance(expectation, Mapping) or (
        expectation.get("instrumentation_arm") != run.get("instrumentation_arm")
    ):
        reasons.append("scenario_manifest_artifact_instrumentation_mismatch")
    if not isinstance(validation, Mapping):
        reasons.append("scenario_manifest_artifact_validation_missing")
    else:
        if validation.get("status") != reference.get("status"):
            reasons.append("scenario_manifest_artifact_status_mismatch")
        if list(validation.get("reason_codes") or ()) != list(reference_reason_codes or ()):
            reasons.append("scenario_manifest_artifact_reason_codes_mismatch")
    if reference.get("status") == "pass" and (
        not isinstance(construction, Mapping)
        or construction.get("status") != "ok"
        or not isinstance(ready_for_measurement, Mapping)
        or ready_for_measurement.get("status") != "ready"
        or ready_for_measurement.get("reason_codes") not in ([], ())
        or not isinstance(observation, Mapping)
        or observation.get("status") != "matched"
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(observation.get("startup_report_sha256") or ""),
        )
    ):
        reasons.append("scenario_manifest_artifact_pass_semantics_invalid")
    if not isinstance(privacy, Mapping) or any(
        privacy.get(key) is not False
        for key in (
            "agent_names_persisted",
            "process_ids_persisted",
            "provider_prompts_persisted",
            "raw_runtime_records_persisted",
        )
    ):
        reasons.append("scenario_manifest_artifact_privacy_contract_invalid")
    if reference.get("status") == "pass" and expected_scenario_id == "S3":
        reasons.extend(
            _mixed_recovery_manifest_audit(
                payload,
                run=run,
                benchmark_dir=benchmark_dir,
                run_directory_name=artifact_path.parts[0],
            )
        )
    if reference.get("status") == "pass" and expected_scenario_id == "S0":
        reasons.extend(_cli_only_manifest_audit(payload, run=run))
    audit_phase = payload.get("audit_phase")
    if not isinstance(audit_phase, Mapping) or audit_phase.get("name") != "final":
        reasons.append("scenario_manifest_final_phase_invalid")

    phase_chain = payload.get("phase_chain")
    if not isinstance(phase_chain, Mapping):
        reasons.append("scenario_manifest_phase_chain_missing")
        return False, tuple(sorted(set(reasons)))

    def audit_immutable_phase(
        phase_name: str,
        *,
        predecessor_sha256: str | None,
    ) -> str | None:
        phase_reference = phase_chain.get(phase_name)
        if not isinstance(phase_reference, Mapping):
            reasons.append(f"scenario_manifest_{phase_name}_phase_reference_missing")
            return None
        phase_artifact = PurePosixPath(str(phase_reference.get("artifact") or ""))
        expected_name = f"scenario-construction.{phase_name}.json"
        if (
            phase_artifact.is_absolute()
            or len(phase_artifact.parts) != 2
            or phase_artifact.parts[0] != artifact_path.parts[0]
            or phase_artifact.name != expected_name
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_path_invalid")
            return None
        phase_path = benchmark_dir / phase_artifact.parts[0] / phase_artifact.name
        try:
            phase_bytes = phase_path.read_bytes()
        except FileNotFoundError:
            reasons.append(f"scenario_manifest_{phase_name}_phase_missing")
            return None
        except OSError:
            reasons.append(f"scenario_manifest_{phase_name}_phase_unreadable")
            return None
        phase_sha256 = hashlib.sha256(phase_bytes).hexdigest()
        if phase_sha256 != phase_reference.get("sha256"):
            reasons.append(f"scenario_manifest_{phase_name}_phase_digest_mismatch")
        try:
            phase_payload = json.loads(phase_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            reasons.append(f"scenario_manifest_{phase_name}_phase_json_invalid")
            return phase_sha256
        if not isinstance(phase_payload, Mapping):
            reasons.append(f"scenario_manifest_{phase_name}_phase_root_invalid")
            return phase_sha256
        phase_marker = phase_payload.get("audit_phase")
        phase_validation = phase_payload.get("validation")
        if (
            not isinstance(phase_marker, Mapping)
            or phase_marker.get("name") != phase_name
            or phase_marker.get("predecessor_sha256") != predecessor_sha256
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_chain_invalid")
        if (
            not isinstance(phase_validation, Mapping)
            or phase_validation.get("status") != phase_reference.get("status")
            or (
                phase_name == "before"
                and phase_validation.get("status") != "pending"
            )
            or (
                phase_name == "ready"
                and phase_validation.get("status")
                not in {"ready_for_measurement", "failed"}
            )
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_status_invalid")
        if (
            phase_payload.get("record_type") != SCENARIO_CONSTRUCTION_RECORD_TYPE
            or phase_payload.get("schema_version") != SCENARIO_CONSTRUCTION_SCHEMA_VERSION
            or phase_payload.get("benchmark_id") != run.get("benchmark_id")
            or phase_payload.get("round_ordinal") != run.get("ordinal")
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_identity_invalid")
        phase_scenario = phase_payload.get("scenario")
        if not isinstance(phase_scenario, Mapping) or (
            phase_scenario.get("id") != expected_scenario_id
            or phase_scenario.get("cli_name") != run_scenario
            or phase_scenario.get("variant") != run.get("round_role")
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_scenario_invalid")
        phase_expectation = phase_payload.get("expectation")
        if not isinstance(phase_expectation, Mapping) or (
            phase_expectation.get("instrumentation_arm") != run.get("instrumentation_arm")
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_instrumentation_invalid")
        phase_privacy = phase_payload.get("privacy")
        if not isinstance(phase_privacy, Mapping) or any(
            phase_privacy.get(key) is not False
            for key in (
                "agent_names_persisted",
                "process_ids_persisted",
                "provider_prompts_persisted",
                "raw_runtime_records_persisted",
            )
        ):
            reasons.append(f"scenario_manifest_{phase_name}_phase_privacy_invalid")
        return phase_sha256

    before_sha256 = audit_immutable_phase("before", predecessor_sha256=None)
    ready_sha256 = audit_immutable_phase(
        "ready",
        predecessor_sha256=before_sha256,
    )
    if isinstance(audit_phase, Mapping) and audit_phase.get("predecessor_sha256") != ready_sha256:
        reasons.append("scenario_manifest_final_phase_chain_invalid")
    return not reasons, tuple(sorted(set(reasons)))


def _scenario_construction_summary(
    runs: Sequence[Mapping[str, Any]],
    *,
    benchmark_dir: Path,
) -> dict[str, Any]:
    attempted_dirs = {
        path.parent.name
        for path in benchmark_dir.glob("*/scenario-construction.before.json")
        if path.is_file()
    }
    expected = max(len(runs), len(attempted_dirs))
    run_references = [
        (run, run.get("scenario_construction"))
        for run in runs
        if isinstance(run.get("scenario_construction"), Mapping)
    ]
    references = [reference for _run, reference in run_references]
    audit_results = [
        (
            reference,
            *_scenario_construction_reference_audit(
                reference,
                run=run,
                benchmark_dir=benchmark_dir,
            ),
        )
        for run, reference in run_references
    ]
    valid_references = [
        reference
        for reference, valid, _reasons in audit_results
        if valid
    ]
    audit_reason_codes = sorted(
        {
            reason
            for _reference, _valid, reasons in audit_results
            for reason in reasons
        }
    )
    passed = sum(1 for reference in valid_references if reference.get("status") == "pass")
    failed = sum(1 for reference in valid_references if reference.get("status") == "failed")
    by_scenario: dict[str, dict[str, int]] = {}
    for reference in valid_references:
        scenario_id = str(reference.get("scenario_id") or "")
        payload = by_scenario.setdefault(
            scenario_id,
            {"present": 0, "passed": 0, "failed": 0},
        )
        payload["present"] += 1
        if reference.get("status") == "pass":
            payload["passed"] += 1
        elif reference.get("status") == "failed":
            payload["failed"] += 1
    complete = expected > 0 and len(valid_references) == expected and passed == expected
    referenced_dirs = {
        PurePosixPath(str(reference.get("artifact") or "")).parts[0]
        for reference in references
        if len(PurePosixPath(str(reference.get("artifact") or "")).parts) == 2
    }
    orphan_attempts = sorted(attempted_dirs - referenced_dirs)
    return {
        "status": "pass" if complete else ("failed" if references else "missing"),
        "manifests_expected": expected,
        "manifests_present": len(references),
        "manifests_valid": len(valid_references),
        "manifests_passed": passed,
        "manifests_failed": failed,
        "attempt_directories_discovered": len(attempted_dirs),
        "orphan_attempt_directories": len(orphan_attempts),
        "by_scenario": dict(sorted(by_scenario.items())),
        "reason_codes": sorted(set(audit_reason_codes + [
            reason
            for reason, applies in (
                ("scenario_manifest_missing", len(references) != expected),
                ("scenario_manifest_orphan_attempt", bool(orphan_attempts)),
                ("scenario_manifest_reference_invalid", len(valid_references) != len(references)),
                ("scenario_manifest_validation_failed", passed != expected),
            )
            if applies
        ])),
    }


def _build_summary(
    options: StartupBenchmarkOptions,
    *,
    context: ValidatedContext,
    benchmark_id: str,
    benchmark_dir: Path,
    runs: Sequence[Mapping[str, Any]],
    abort_reason: str | None,
    cleanup_verdict: Mapping[str, Any],
    formal_config_signature: str | None,
    warm_daemon_generation: int | None,
    instrumentation_ab_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ab_mode = options.instrumentation_mode == "instrumentation-ab"
    cli_only_scenario = options.scenario == "cli-only"
    measured_all = [run for run in runs if run.get("included_in_statistics")]
    measured = (
        [run for run in measured_all if run.get("instrumentation_arm") == "instrumented"]
        if ab_mode
        else measured_all
    )
    successful = [
        run
        for run in measured
        if run.get("status") == "ok" and run.get("wall_ms") is not None
    ]
    successful_all = [
        run
        for run in measured_all
        if run.get("status") == "ok" and run.get("wall_ms") is not None
    ]
    failures = sum(1 for run in measured_all if run.get("status") not in {"ok", "timeout"})
    timeouts = sum(
        1
        for run in measured_all
        if run.get("status") == "timeout" or run.get("timed_out")
    )
    startup_transaction_runs = [
        run
        for run in runs
        if run.get("started_at") is not None and run.get("measurement_kind") == "startup"
    ]
    cli_only_command_runs = [
        run
        for run in runs
        if run.get("started_at") is not None and run.get("measurement_kind") == "cli_only"
    ]
    native_run_count = sum(
        1
        for run in startup_transaction_runs
        if isinstance(run.get("startup_report"), Mapping)
        and bool(run["startup_report"].get("native_run_id_available"))
    )
    startup_command_count = len(startup_transaction_runs)
    instrumented_start_runs = [
        run
        for run in startup_transaction_runs
        if run.get("started_at") is not None
        and run.get("instrumentation_arm") != "control"
    ]
    instrumented_startup_count = len(instrumented_start_runs)
    instrumented_profiled_runs = (
        [
            run
            for run in cli_only_command_runs
            if run.get("instrumentation_arm") != "control"
        ]
        if cli_only_scenario
        else instrumented_start_runs
    )
    instrumented_profiled_count = len(instrumented_profiled_runs)
    readiness_timelines = [
        run.get("readiness_timeline")
        for run in instrumented_start_runs
        if run.get("started_at") is not None
        and isinstance(run.get("readiness_timeline"), Mapping)
        and bool(run.get("readiness_timeline"))
    ]
    readiness_timelines_complete = sum(
        1
        for timeline in readiness_timelines
        if timeline.get("timeline_complete") is True
        and timeline.get("generation_correlation") == "matched"
    )
    readiness_complete = (
        instrumented_startup_count > 0
        and len(readiness_timelines) == instrumented_startup_count
        and readiness_timelines_complete == instrumented_startup_count
    )
    readiness_t1_upper_bounds = sum(
        1
        for timeline in readiness_timelines
        if isinstance(timeline.get("points"), Mapping)
        and isinstance(timeline["points"].get("T1_lifecycle_intent"), Mapping)
        and timeline["points"]["T1_lifecycle_intent"].get("status")
        == "observed_upper_bound"
    )
    readiness_t1_exact = sum(
        1
        for timeline in readiness_timelines
        if isinstance(timeline.get("points"), Mapping)
        and isinstance(timeline["points"].get("T1_lifecycle_intent"), Mapping)
        and timeline["points"]["T1_lifecycle_intent"].get("status") == "reached"
        and timeline["points"]["T1_lifecycle_intent"].get("source")
        == "keeper_lifecycle_starting_committed"
    )
    readiness_t1_not_required = sum(
        1
        for timeline in readiness_timelines
        if isinstance(timeline.get("points"), Mapping)
        and isinstance(timeline["points"].get("T1_lifecycle_intent"), Mapping)
        and timeline["points"]["T1_lifecycle_intent"].get("status")
        == "not_required_already_mounted"
    )
    resource_profiles = [
        run.get("resource_profile")
        for run in instrumented_profiled_runs
        if isinstance(run.get("resource_profile"), Mapping)
    ]
    measured_resource_profiles = [
        run.get("resource_profile")
        for run in successful
        if isinstance(run.get("resource_profile"), Mapping)
    ]
    resource_profiles_verified = sum(
        1
        for profile in resource_profiles
        if isinstance(profile.get("correlation"), Mapping)
        and profile["correlation"].get("status") == "verified"
    )
    resource_profiles_formal_eligible = sum(
        1
        for profile in resource_profiles
        if isinstance(profile.get("quality"), Mapping)
        and profile["quality"].get("formal_eligible") is True
    )
    measured_resource_profiles_formal_eligible = sum(
        1
        for profile in measured_resource_profiles
        if isinstance(profile.get("quality"), Mapping)
        and profile["quality"].get("formal_eligible") is True
    )
    resource_profiles_io_complete = sum(
        1
        for profile in resource_profiles
        if isinstance(profile.get("capabilities"), Mapping)
        and profile["capabilities"].get("process_io") == "available"
    )
    measured_resource_profiles_io_complete = sum(
        1
        for profile in measured_resource_profiles
        if isinstance(profile.get("capabilities"), Mapping)
        and profile["capabilities"].get("process_io") == "available"
    )
    resource_profiles_correlated = (
        instrumented_profiled_count > 0
        and len(resource_profiles) == instrumented_profiled_count
        and resource_profiles_verified == instrumented_profiled_count
    )
    resource_profiles_formal_complete = (
        resource_profiles_correlated
        and len(measured_resource_profiles) == len(successful)
        and measured_resource_profiles_formal_eligible == len(successful)
    )
    cleanup_resource = cleanup_verdict.get("resource_audit")
    cleanup_resource_status = (
        cleanup_resource.get("status") if isinstance(cleanup_resource, Mapping) else None
    )
    io_and_residue_complete = (
        resource_profiles_formal_complete
        and measured_resource_profiles_io_complete == len(successful)
        and cleanup_resource_status == "clean"
    )
    scenario_construction = _scenario_construction_summary(
        runs,
        benchmark_dir=benchmark_dir,
    )
    scenario_construction_complete = scenario_construction.get("status") == "pass"
    expected_measured_commands = options.iterations * (2 if ab_mode else 1)
    benchmark_ok = (
        abort_reason is None
        and len(successful_all) == expected_measured_commands
        and len(successful) == options.iterations
        and scenario_construction_complete
    )
    instrumentation_ab = _instrumentation_ab_summary(
        options,
        runs=runs,
        plan=instrumentation_ab_plan,
    )
    qualification_reasons: list[str] = ["phase0_measurement_contract_incomplete"]
    if not ab_mode:
        qualification_reasons.extend(
            [
                "instrumentation_overhead_not_qualified",
                "ab_comparison_not_implemented",
            ]
        )
    elif instrumentation_ab.get("overhead_gate", {}).get("status") != "pass":
        qualification_reasons.append("instrumentation_overhead_not_qualified")
        qualification_reasons.append(
            str(
                instrumentation_ab.get("overhead_gate", {}).get("reason")
                or "instrumentation_ab_incomplete"
            )
        )
    qualification_reasons.append("scenario_matrix_incomplete")
    if not scenario_construction_complete:
        qualification_reasons.insert(1, "scenario_construction_missing_or_failed")
    if not cli_only_scenario and not readiness_complete:
        qualification_reasons.insert(1, "readiness_timeline_incomplete")
    elif not cli_only_scenario and readiness_t1_upper_bounds:
        qualification_reasons.insert(1, "readiness_keeper_intent_checkpoint_upper_bound")
    if not resource_profiles_correlated:
        qualification_reasons.insert(1, "resource_profile_not_correlated")
    elif not resource_profiles_formal_complete:
        qualification_reasons.insert(1, "resource_profile_quality_degraded")
    if not io_and_residue_complete:
        insertion = 5 if resource_profiles_formal_complete else 6
        qualification_reasons.insert(
            min(insertion, len(qualification_reasons)),
            "process_io_or_cleanup_incomplete",
        )
    if not benchmark_ok:
        qualification_reasons.append("benchmark_incomplete")
    if options.warmup < FORMAL_MIN_WARMUPS:
        qualification_reasons.append(
            f"warmups_below_formal_minimum:{options.warmup}<{FORMAL_MIN_WARMUPS}"
        )
    if options.iterations < FORMAL_MIN_SAMPLES:
        qualification_reasons.append(
            f"samples_below_formal_minimum:{options.iterations}<{FORMAL_MIN_SAMPLES}"
        )
    formal_sample_thresholds_met = (
        benchmark_ok
        and options.warmup >= FORMAL_MIN_WARMUPS
        and options.iterations >= FORMAL_MIN_SAMPLES
    )
    qualification = "smoke_only"
    formal_claim_allowed = False
    prime = next((run for run in runs if run.get("round_role") == "prime"), None)
    cli_only_unchanged_report_count = sum(
        1
        for run in cli_only_command_runs
        if isinstance(run.get("startup_report"), Mapping)
        and run["startup_report"].get("policy") == "unchanged_existing_start_report"
        and run["startup_report"].get("bytes_unchanged") is True
        and run["startup_report"].get("startup_run_id") is None
        and run["startup_report"].get("validation") == "ok"
    )
    if cli_only_scenario:
        readiness_gate = {
            "status": "not_applicable_cli_only",
            "reason": "no_startup_transaction_in_measured_command",
            "timelines_expected": 0,
            "timelines_present": 0,
            "timelines_complete": 0,
            "prime_startup_timeline_excluded": bool(instrumented_startup_count),
        }
    else:
        readiness_gate = {
            "status": (
                "provisional_upper_bound"
                if readiness_complete and readiness_t1_upper_bounds
                else (
                    "pass"
                    if readiness_complete
                    and readiness_t1_exact + readiness_t1_not_required
                    == len(readiness_timelines)
                    else "incomplete"
                )
            ),
            "timelines_expected": instrumented_startup_count,
            "timelines_present": len(readiness_timelines),
            "timelines_complete": readiness_timelines_complete,
            "t1_exact_keeper_checkpoints": readiness_t1_exact,
            "t1_exact_statistics_ms": summarize_samples(
                [
                    float(timeline["points"]["T1_lifecycle_intent"]["elapsed_ms"])
                    for timeline in readiness_timelines
                    if isinstance(timeline.get("points"), Mapping)
                    and isinstance(
                        timeline["points"].get("T1_lifecycle_intent"),
                        Mapping,
                    )
                    and timeline["points"]["T1_lifecycle_intent"].get("status")
                    == "reached"
                    and timeline["points"]["T1_lifecycle_intent"].get("elapsed_ms")
                    is not None
                ]
            ),
            "t1_observed_upper_bounds": readiness_t1_upper_bounds,
            "t1_not_required_already_mounted": readiness_t1_not_required,
            "no_attach_t5_not_applicable": sum(
                1
                for timeline in readiness_timelines
                if isinstance(timeline.get("points"), Mapping)
                and isinstance(timeline["points"].get("T5_foreground_attached"), Mapping)
                and timeline["points"]["T5_foreground_attached"].get("status")
                == "not_applicable_no_attach"
            ),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": SUMMARY_RECORD_TYPE,
        "benchmark_id": benchmark_id,
        "generated_at": _utc_text(),
        "status": "ok" if benchmark_ok else "incomplete",
        "qualification": qualification,
        "formal_claim_allowed": formal_claim_allowed,
        "qualification_reasons": qualification_reasons,
        "formal_sample_thresholds_met": formal_sample_thresholds_met,
        "abort_reason": abort_reason,
        "scenario": options.scenario,
        "parameters": {
            "iterations": options.iterations,
            "warmup": options.warmup,
            "launch_cap": options.launch_cap,
            "restore_policy": options.restore_policy,
            "provider_env_mode": options.provider_env_mode,
            "instrumentation_mode": options.instrumentation_mode,
            "instrumentation_ab_seed": (
                instrumentation_ab_plan.get("seed")
                if isinstance(instrumentation_ab_plan, Mapping)
                else None
            ),
            "command_timeout_s": options.command_timeout_s,
            "resource_sample_interval_ms": options.resource_sample_interval_ms,
        },
        "source": {
            "mode": "source_checkout",
            "root": str(context.source_root),
            "commit": context.source_sha,
            "version": _read_version(context.source_root),
            "ccb_test_realpath": str(context.ccb_test_path),
            "ccb_test_sha256": context.wrapper_sha256,
            "worktree_fingerprint_sha256": context.source_tree_fingerprint,
        },
        "fixture": {
            "project_root": str(context.project_root),
            "source_home": str(context.source_home),
            "owner_uuid": context.owner_uuid,
            "result_dir": str(benchmark_dir),
            "ccb_config_sha256": context.config_sha256,
            "formal_config_signature": formal_config_signature,
            "warm_daemon_generation": warm_daemon_generation,
            "config_version": context.config_version,
            "configured_agent_count": context.configured_agent_count,
            "configured_window_count": context.configured_window_count,
            "provider_counts": dict(context.provider_counts),
            "model_counts": dict(context.model_counts),
        },
        "warm_priming": (
            {
                "required": True,
                "status": prime.get("status") if isinstance(prime, Mapping) else "missing",
                "failure_reason": prime.get("failure_reason") if isinstance(prime, Mapping) else "missing",
                "precondition": prime.get("precondition") if isinstance(prime, Mapping) else None,
            }
            if options.scenario in {"cli-only", "warm", "mixed-recovery"}
            else {"required": False, "status": "not_applicable"}
        ),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "memory": _memory_metadata(),
            "filesystem": _filesystem_metadata(context.project_root),
        },
        "report_correlation": {
            "native_run_id_required": not cli_only_scenario,
            "native_run_id_available": (
                False
                if cli_only_scenario
                else startup_command_count > 0 and native_run_count == startup_command_count
            ),
            "native_run_id_runs": native_run_count,
            "startup_command_runs": startup_command_count,
            "cli_only_command_runs": len(cli_only_command_runs),
            "cli_only_unchanged_report_runs": cli_only_unchanged_report_count,
            "cli_only_native_run_id_status": (
                "not_applicable"
                if cli_only_scenario
                else "startup_transaction_required"
            ),
            "config_signature": formal_config_signature,
            "method": (
                "benchmark_coordinates+exclusive_lock+frozen_authority+"
                "pre_post_identical_report_identity"
                if cli_only_scenario
                else "stdout_report_run_id+exclusive_lock+pre_post_hash+mtime+"
                "generated_at_window+lease_identity"
            ),
        },
        "scenario_construction_gate": scenario_construction,
        "readiness_gate": readiness_gate,
        "resource_gate": {
            "status": (
                "pass"
                if io_and_residue_complete
                else ("degraded" if resource_profiles else "unavailable")
            ),
            "profiles_expected": instrumented_profiled_count,
            "profiles_present": len(resource_profiles),
            "profiles_verified": resource_profiles_verified,
            "profiles_formal_eligible": resource_profiles_formal_eligible,
            "profiles_process_io_complete": resource_profiles_io_complete,
            "measured_profiles_expected": len(successful),
            "measured_profiles_present": len(measured_resource_profiles),
            "measured_profiles_formal_eligible": measured_resource_profiles_formal_eligible,
            "measured_profiles_process_io_complete": measured_resource_profiles_io_complete,
            "cleanup_audit_status": cleanup_resource_status,
            "reason_codes": [
                reason
                for reason, missing in (
                    ("resource_profiles_missing_or_uncorrelated", not resource_profiles_correlated),
                    ("resource_profiles_quality_degraded", not resource_profiles_formal_complete),
                    ("process_io_or_cleanup_incomplete", not io_and_residue_complete),
                )
                if missing
            ],
        },
        "resource_statistics": _resource_statistics(successful),
        "statistics_ms": summarize_samples([float(run["wall_ms"]) for run in successful]),
        "control_statistics_ms": summarize_samples(
            [
                float(run["wall_ms"])
                for run in measured_all
                if run.get("instrumentation_arm") == "control"
                and run.get("status") == "ok"
                and run.get("wall_ms") is not None
            ]
        ),
        "instrumentation_ab": instrumentation_ab,
        "cli_stage_statistics_ms": _mapping_statistics(
            successful,
            lambda run: run.get("cli_timings_ms"),
        ),
        "process_bootstrap_stage_statistics_ms": _mapping_statistics(
            successful,
            lambda run: run.get("process_bootstrap_timings_ms"),
        ),
        "supervisor_stage_statistics_ms": _mapping_statistics(
            successful,
            lambda run: (
                run.get("startup_report", {}).get("timings_ms")
                if isinstance(run.get("startup_report"), Mapping)
                else None
            ),
        ),
        "derived_statistics_ms": {
            key: summarize_samples(
                [
                    float(run["derived_timings_ms"][key])
                    for run in successful
                    if isinstance(run.get("derived_timings_ms"), Mapping)
                    and run["derived_timings_ms"].get(key) is not None
                ]
            )
            for key in (
                "process_bootstrap_total",
                "post_cli_residual",
                "external_minus_cli_total",
                "external_minus_supervisor_total",
            )
        },
        "readiness_statistics_ms": _mapping_statistics(
            successful,
            lambda run: (
                {
                    key: value
                    for key, value in run.get("readiness_ms", {}).items()
                    if str(key).startswith("T")
                }
                if isinstance(run.get("readiness_ms"), Mapping)
                else None
            ),
        ),
        "operation_count_statistics": _operation_statistics(successful),
        "agent_statistics_ms": _agent_statistics(successful),
        "agent_outcomes": _agent_outcome_counts(successful),
        "attribution": _attribution_summary(successful),
        "counts": {
            "requested": options.iterations,
            "completed": len(measured),
            "successful": len(successful),
            **(
                {
                    "measured_commands_completed": len(measured_all),
                    "measured_commands_successful": len(successful_all),
                }
                if ab_mode
                else {}
            ),
            "failures": failures,
            "timeouts": timeouts,
            "warmups_completed": (
                len(
                    {
                        run.get("instrumentation_pair_sequence")
                        for run in runs
                        if run.get("round_role") == "warmup"
                        and run.get("instrumentation_pair_sequence") is not None
                    }
                )
                if ab_mode
                else sum(1 for run in runs if run.get("round_role") == "warmup")
            ),
            "prime_completed": sum(1 for run in runs if run.get("round_role") == "prime"),
        },
        "cleanup": dict(cleanup_verdict),
        "runs": [
            {
                "ordinal": run.get("ordinal"),
                "measured_index": run.get("measured_index"),
                "included_in_statistics": run.get("included_in_statistics"),
                "round_role": run.get("round_role"),
                "measurement_kind": run.get("measurement_kind"),
                "instrumentation_arm": run.get("instrumentation_arm"),
                "instrumentation_pair_index": run.get("instrumentation_pair_index"),
                "instrumentation_pair_sequence": run.get("instrumentation_pair_sequence"),
                "instrumentation_order_position": run.get("instrumentation_order_position"),
                "status": run.get("status"),
                "wall_ms": run.get("wall_ms"),
                "failure_reason": run.get("failure_reason"),
                "scenario_construction": dict(run.get("scenario_construction") or {}),
            }
            for run in runs
        ],
    }


def _instrumentation_ab_summary(
    options: StartupBenchmarkOptions,
    *,
    runs: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if options.instrumentation_mode != "instrumentation-ab":
        return {"status": "not_requested"}
    seed = int(plan.get("seed") or 0) if isinstance(plan, Mapping) else 0
    measured = [run for run in runs if run.get("included_in_statistics")]
    by_pair: dict[int, list[Mapping[str, Any]]] = {}
    for run in measured:
        pair_index = run.get("instrumentation_pair_index")
        if type(pair_index) is int and pair_index >= 0:
            by_pair.setdefault(pair_index, []).append(run)
    invalid_pairs: list[dict[str, Any]] = []
    pair_records: list[dict[str, Any]] = []
    control_walls: list[float] = []
    instrumented_walls: list[float] = []
    deltas: list[float] = []
    control_trust_failures = 0
    instrumented_trust_failures = 0
    for pair_index in range(options.iterations):
        items = by_pair.get(pair_index, [])
        reasons: list[str] = []
        arms = {
            str(item.get("instrumentation_arm") or ""): item
            for item in items
            if str(item.get("instrumentation_arm") or "") in {"control", "instrumented"}
        }
        if len(items) != 2 or set(arms) != {"control", "instrumented"}:
            reasons.append("pair_does_not_have_exactly_one_of_each_arm")
        control = arms.get("control")
        instrumented = arms.get("instrumented")
        if control is not None:
            control_reasons = _control_arm_trust_reasons(control)
            if control_reasons:
                control_trust_failures += 1
                reasons.extend(f"control:{reason}" for reason in control_reasons)
        if instrumented is not None:
            instrumented_reasons = _instrumented_arm_trust_reasons(instrumented)
            if instrumented_reasons:
                instrumented_trust_failures += 1
                reasons.extend(f"instrumented:{reason}" for reason in instrumented_reasons)
        if control is not None and instrumented is not None:
            control_report = control.get("startup_report")
            instrumented_report = instrumented.get("startup_report")
            if isinstance(control_report, Mapping) and isinstance(instrumented_report, Mapping):
                for field in ("daemon_generation", "config_signature"):
                    if control_report.get(field) != instrumented_report.get(field):
                        reasons.append(f"cross_arm_{field}_mismatch")
            positions = {
                control.get("instrumentation_order_position"),
                instrumented.get("instrumentation_order_position"),
            }
            if positions != {0, 1}:
                reasons.append("arm_order_positions_invalid")
        if reasons:
            invalid_pairs.append(
                {"pair_index": pair_index, "reason_codes": sorted(set(reasons))}
            )
            continue
        assert control is not None and instrumented is not None
        control_wall = float(control["wall_ms"])
        instrumented_wall = float(instrumented["wall_ms"])
        delta = instrumented_wall - control_wall
        control_walls.append(control_wall)
        instrumented_walls.append(instrumented_wall)
        deltas.append(delta)
        pair_records.append(
            {
                "pair_index": pair_index,
                "arm_order": [
                    str(item.get("instrumentation_arm"))
                    for item in sorted(
                        (control, instrumented),
                        key=lambda item: int(item.get("instrumentation_order_position") or 0),
                    )
                ],
                "control_wall_ms": control_wall,
                "instrumented_wall_ms": instrumented_wall,
                "paired_delta_ms": delta,
            }
        )
    control_statistics = summarize_samples(control_walls)
    instrumented_statistics = summarize_samples(instrumented_walls)
    delta_statistics = summarize_samples(deltas)
    bootstrap_ci = _bootstrap_median_ci(deltas, seed=seed)
    control_p50 = _finite_nonnegative_or_none(control_statistics.get("p50"))
    budget_ms = max(10.0, 0.02 * control_p50) if control_p50 is not None else None
    sample_thresholds_met = (
        options.warmup >= FORMAL_MIN_WARMUPS
        and options.iterations >= FORMAL_MIN_SAMPLES
    )
    pairs_complete = len(pair_records) == options.iterations and not invalid_pairs
    delta_p50 = _finite_or_none(delta_statistics.get("p50"))
    ci_upper = _finite_or_none(bootstrap_ci.get("upper_ms"))
    if not pairs_complete:
        gate_status = "incomplete"
        gate_reason = "instrumentation_ab_pairs_incomplete"
    elif not sample_thresholds_met:
        gate_status = "smoke_only"
        gate_reason = "instrumentation_ab_pairs_below_formal_minimum"
    elif budget_ms is None or delta_p50 is None or ci_upper is None:
        gate_status = "incomplete"
        gate_reason = "instrumentation_ab_statistics_incomplete"
    elif delta_p50 > budget_ms:
        gate_status = "failed"
        gate_reason = "instrumentation_ab_p50_over_budget"
    elif ci_upper > budget_ms:
        gate_status = "failed"
        gate_reason = "instrumentation_ab_ci_upper_over_budget"
    else:
        gate_status = "pass"
        gate_reason = None
    return {
        "status": "ok" if pairs_complete else "incomplete",
        "plan_snapshot": "benchmark-plan.json",
        "seed": seed,
        "order_policy": (
            plan.get("order_policy") if isinstance(plan, Mapping) else None
        ),
        "pairs_expected": options.iterations,
        "pairs_valid": len(pair_records),
        "warmup_pairs": options.warmup,
        "invalid_pairs": invalid_pairs,
        "pairs": pair_records,
        "arms": {
            "control": control_statistics,
            "instrumented": instrumented_statistics,
        },
        "paired_delta_ms": delta_statistics,
        "bootstrap_median_95_ci_ms": bootstrap_ci,
        "control_trust_gate": {
            "status": "pass" if control_trust_failures == 0 and pairs_complete else "failed",
            "failed_arms": control_trust_failures,
        },
        "instrumented_evidence_gate": {
            "status": (
                "pass" if instrumented_trust_failures == 0 and pairs_complete else "failed"
            ),
            "failed_arms": instrumented_trust_failures,
        },
        "overhead_gate": {
            "status": gate_status,
            "reason": gate_reason,
            "budget_ms": budget_ms,
            "budget_formula": "max(10ms,2%*control_p50)",
            "observed_p50_ms": delta_p50,
            "bootstrap_ci_upper_ms": ci_upper,
            "formal_pair_thresholds_met": sample_thresholds_met,
        },
    }


def _control_arm_trust_reasons(run: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if run.get("status") != "ok" or run.get("wall_ms") is None:
        reasons.append("run_not_successful")
    if run.get("process_trace_id") is not None or run.get("process_bootstrap_timings_ms"):
        reasons.append("process_trace_present")
    if run.get("readiness_timeline") or run.get("readiness_ms"):
        reasons.append("readiness_present")
    resource_profile = run.get("resource_profile")
    if not isinstance(resource_profile, Mapping) or resource_profile.get("status") != "disabled_by_design":
        reasons.append("resource_profile_not_disabled")
    report = run.get("startup_report")
    if not isinstance(report, Mapping) or report.get("validation") != "ok":
        reasons.append("startup_report_not_validated")
    elif not report.get("native_run_id_available"):
        reasons.append("native_run_id_missing")
    elif not isinstance(report.get("warm_reuse_identity"), Mapping):
        reasons.append("warm_reuse_identity_missing")
    return reasons


def _instrumented_arm_trust_reasons(run: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if run.get("status") != "ok" or run.get("wall_ms") is None:
        reasons.append("run_not_successful")
    if not re.fullmatch(r"trace_[0-9a-f]{32}", str(run.get("process_trace_id") or "")):
        reasons.append("process_trace_missing")
    timings = run.get("process_bootstrap_timings_ms")
    if not isinstance(timings, Mapping) or set(timings) != set(PROCESS_BOOTSTRAP_TIMING_KEYS):
        reasons.append("process_bootstrap_timings_incomplete")
    readiness = run.get("readiness_timeline")
    if not isinstance(readiness, Mapping) or readiness.get("timeline_complete") is not True:
        reasons.append("readiness_incomplete")
    profile = run.get("resource_profile")
    correlation = profile.get("correlation") if isinstance(profile, Mapping) else None
    if not isinstance(correlation, Mapping) or correlation.get("status") != "verified":
        reasons.append("resource_profile_not_correlated")
    report = run.get("startup_report")
    if not isinstance(report, Mapping) or report.get("validation") != "ok":
        reasons.append("startup_report_not_validated")
    elif not report.get("native_run_id_available"):
        reasons.append("native_run_id_missing")
    elif not isinstance(report.get("warm_reuse_identity"), Mapping):
        reasons.append("warm_reuse_identity_missing")
    return reasons


def _bootstrap_median_ci(
    values: Sequence[float],
    *,
    seed: int,
    resamples: int = 5000,
) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"confidence": 0.95, "resamples": 0, "lower_ms": None, "upper_ms": None}
    rng = random.Random(int(seed) ^ 0x4343425F4142)
    size = len(clean)
    medians = sorted(
        statistics.median(rng.choice(clean) for _ in range(size))
        for _ in range(max(1, int(resamples)))
    )
    return {
        "confidence": 0.95,
        "resamples": len(medians),
        "lower_ms": _percentile(medians, 0.025),
        "upper_ms": _percentile(medians, 0.975),
    }


def _finite_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mapping_statistics(
    runs: Sequence[Mapping[str, Any]],
    extractor: Callable[[Mapping[str, Any]], object],
) -> dict[str, dict[str, Any]]:
    values_by_key: dict[str, list[float]] = {}
    for run in runs:
        payload = extractor(run)
        if not isinstance(payload, Mapping):
            continue
        for key, raw_value in payload.items():
            if isinstance(raw_value, bool):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values_by_key.setdefault(str(key), []).append(value)
    return {key: summarize_samples(values) for key, values in sorted(values_by_key.items())}


def _operation_statistics(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    mappings: list[dict[str, int]] = []
    all_keys: set[str] = set()
    for run in runs:
        report = run.get("startup_report")
        payload = report.get("operation_counts") if isinstance(report, Mapping) else None
        clean = _operation_mapping_for_record(payload)
        mappings.append(clean)
        all_keys.update(clean)
    return {
        key: summarize_samples([float(mapping.get(key, 0)) for mapping in mappings])
        for key in sorted(all_keys)
    }


def _resource_statistics(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    values: dict[str, list[float]] = {}
    for run in runs:
        profile = run.get("resource_profile")
        if not isinstance(profile, Mapping):
            continue
        correlation = profile.get("correlation")
        if not isinstance(correlation, Mapping) or correlation.get("status") != "verified":
            continue
        metrics = profile.get("metrics")
        if isinstance(metrics, Mapping):
            for field in (
                "sampled_process_tree_cpu_seconds",
                "command_rusage_cpu_seconds",
                "baseline_rss_bytes",
                "sampled_peak_rss_bytes",
                "peak_rss_delta_from_baseline_bytes",
                "baseline_process_count",
                "sampled_peak_process_count",
                "end_process_count",
                "unique_process_instance_count",
                "created_process_instance_count",
            ):
                number = _finite_nonnegative_or_none(metrics.get(field))
                if number is not None:
                    values.setdefault(field, []).append(number)
            io_metrics = metrics.get("io")
            if isinstance(io_metrics, Mapping):
                for field in (
                    "read_bytes",
                    "write_bytes",
                    "rchar_bytes",
                    "wchar_bytes",
                    "syscr",
                    "syscw",
                ):
                    number = _finite_nonnegative_or_none(io_metrics.get(field))
                    if number is not None:
                        values.setdefault(f"io_{field}", []).append(number)
        sampler = profile.get("sampler")
        if isinstance(sampler, Mapping):
            for field in (
                "sample_count",
                "scan_wall_ms_total",
                "scan_wall_ms_max",
                "baseline_scan_wall_ms",
                "command_window_scan_wall_ms_total",
                "command_window_scan_wall_ms_max",
            ):
                number = _finite_nonnegative_or_none(sampler.get(field))
                if number is not None:
                    values.setdefault(field, []).append(number)
        window = profile.get("window")
        if isinstance(window, Mapping):
            number = _finite_nonnegative_or_none(window.get("sampler_and_runner_overhead_ms"))
            if number is not None:
                values.setdefault("sampler_and_runner_overhead_ms", []).append(number)
    return {key: summarize_samples(items) for key, items in sorted(values.items())}


def _agent_statistics(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [
        metric
        for run in runs
        for metric in (run.get("agent_metrics") or ())
        if isinstance(metric, Mapping)
    ]
    return {
        "duration": summarize_samples(
            [float(value) for metric in metrics if (value := metric.get("duration_ms")) is not None]
        ),
        "provider_prepare": summarize_samples(
            [
                float(value)
                for metric in metrics
                if (value := metric.get("provider_prepare_ms")) is not None
            ]
        ),
        "stages": _mapping_statistics(metrics, lambda metric: metric.get("timings_ms")),
    }


def _agent_outcome_counts(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {"provider": {}, "action": {}, "health": {}}
    for run in runs:
        for metric in run.get("agent_metrics") or ():
            if not isinstance(metric, Mapping):
                continue
            for field_name in counts:
                value = str(metric.get(field_name) or "").strip()
                if value:
                    counts[field_name][value] = counts[field_name].get(value, 0) + 1
    return counts


def _attribution_summary(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    layers: dict[str, Any] = {}
    all_coverages: list[float] = []
    for layer in ("external", "supervisor", "flow"):
        coverages: list[float] = []
        residuals: list[float] = []
        for run in runs:
            attribution = run.get("attribution")
            payload = attribution.get(layer) if isinstance(attribution, Mapping) else None
            if not isinstance(payload, Mapping):
                continue
            coverage = _finite_nonnegative_or_none(payload.get("coverage"))
            residual = _finite_nonnegative_or_none(payload.get("unattributed_ms"))
            if coverage is not None:
                coverages.append(coverage)
                all_coverages.append(coverage)
            if residual is not None:
                residuals.append(residual)
        layers[layer] = {
            "coverage": summarize_samples(coverages),
            "unattributed_ms": summarize_samples(residuals),
        }
    minimum = min(all_coverages) if all_coverages else None
    return {
        "layers": layers,
        "minimum_coverage": minimum,
        "all_observed_layers_at_least_90_percent": bool(
            all_coverages and all(value >= 0.90 for value in all_coverages)
        ),
    }


def _memory_metadata() -> dict[str, int | None]:
    total_bytes: int | None = None
    available_bytes: int | None = None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        physical_pages = int(os.sysconf("SC_PHYS_PAGES"))
        if page_size > 0 and physical_pages > 0:
            total_bytes = page_size * physical_pages
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                available_bytes = int(line.split()[1]) * 1024
                break
    except (OSError, IndexError, TypeError, ValueError):
        pass
    return {"total_bytes": total_bytes, "available_bytes_at_start": available_bytes}


def _filesystem_metadata(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": None,
        "detection": "unavailable",
        "remote_or_mounted_drive_like": None,
    }
    try:
        stats = os.statvfs(path)
        payload.update(
            block_size=int(stats.f_bsize),
            fragment_size=int(stats.f_frsize),
        )
    except OSError:
        pass
    if platform.system() != "Linux":
        return payload
    try:
        resolved = path.resolve(strict=True)
        candidates: list[tuple[int, str]] = []
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            separator = fields.index("-")
            mount_point = Path(_unescape_mountinfo(fields[4])).resolve(strict=False)
            if _path_is_under(resolved, mount_point):
                candidates.append((len(str(mount_point)), fields[separator + 1]))
        if candidates:
            fs_type = max(candidates)[1]
            payload.update(
                type=fs_type,
                detection="linux_mountinfo",
                remote_or_mounted_drive_like=fs_type.lower()
                in {"9p", "cifs", "drvfs", "fuse.sshfs", "nfs", "nfs4", "smb3"},
            )
    except (OSError, ValueError):
        pass
    return payload


def _unescape_mountinfo(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _enforce_unique_startup_run_id(
    record: dict[str, Any],
    *,
    seen: set[str],
) -> None:
    startup_report = record.get("startup_report")
    run_id = (
        str(startup_report.get("startup_run_id") or "").strip()
        if isinstance(startup_report, Mapping)
        else ""
    )
    if not run_id:
        return
    if run_id not in seen:
        seen.add(run_id)
        return
    reason = f"startup report validation failed: duplicate startup_run_id across rounds: {run_id}"
    record["status"] = "failed"
    record["failure_reason"] = reason
    if isinstance(startup_report, dict):
        startup_report["validation"] = "failed"
        startup_report["validation_error"] = reason


def _base_run_record(
    *,
    benchmark_id: str,
    ordinal: int,
    measured_index: int | None,
    included_in_statistics: bool,
    scenario: str,
    round_role: str,
    status: str,
    wall_ms: float | None,
    timed_out: bool,
    exit_code: int | None,
    failure_reason: str | None,
    precondition: Mapping[str, Any],
    instrumentation_arm: str = "instrumented",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RUN_RECORD_TYPE,
        "benchmark_id": benchmark_id,
        "ordinal": ordinal,
        "measured_index": measured_index,
        "included_in_statistics": included_in_statistics,
        "scenario": scenario,
        "round_role": round_role,
        "measurement_kind": (
            "cli_only" if scenario == "cli-only" and round_role != "prime" else "startup"
        ),
        "instrumentation_arm": instrumentation_arm,
        "status": status,
        "wall_ms": wall_ms,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "failure_reason": failure_reason,
        "precondition": dict(precondition),
    }


def _benchmark_env(
    options: StartupBenchmarkOptions,
    context: ValidatedContext,
    *,
    environ: Mapping[str, str] | None,
) -> dict[str, str]:
    source_env = dict(os.environ if environ is None else environ)
    if options.provider_env_mode == "stub":
        env = {
            key: value
            for key, value in source_env.items()
            if _stub_environment_key_allowed(key)
        }
    else:
        env = source_env
    env.pop("CCB_SOURCE_RUNTIME_OK", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    for key in _STARTUP_TRACE_ENV_KEYS:
        env.pop(key, None)
    env.setdefault("PATH", os.defpath)
    env["HOME"] = str(context.source_home)
    env["CCB_SOURCE_HOME"] = str(context.source_home)
    env["CCB_NO_ATTACH"] = "1"
    roots = os.pathsep.join(str(root) for root in context.test_roots)
    env["CCB_TEST_ROOTS"] = roots
    env["CCB_SOURCE_ALLOWED_ROOTS"] = roots
    env["CCB_SKIP_STARTUP_UPDATE_CHECK"] = "1"
    return env


def _stub_environment_key_allowed(key: str) -> bool:
    if key in _STUB_ENV_ALLOWLIST or key.startswith("STUB_"):
        return True
    for provider in _STUB_PROVIDER_NAMES:
        if key == f"{provider}_START_CMD" or key.startswith(f"{provider}_STUB_"):
            return True
    return False


def _stub_launch_environment_key(key: str) -> bool:
    name = str(key or "").strip().upper()
    if name.startswith("STUB_LAUNCH_"):
        return True
    return any(name.startswith(f"{provider}_STUB_LAUNCH_") for provider in _STUB_PROVIDER_NAMES)


def _start_command(
    options: StartupBenchmarkOptions,
    context: ValidatedContext,
    *,
    round_role: str = "measured",
) -> tuple[str, ...]:
    args = [sys.executable, str(context.ccb_test_path)]
    if options.scenario == "cli-only" and round_role != "prime":
        args.append("--print-version")
        return tuple(args)
    if options.restore_policy == "fresh":
        args.append("-n")
    return tuple(args)


def _is_cli_only_command(argv: Sequence[str]) -> bool:
    command = tuple(str(item) for item in argv)
    return len(command) == 3 and command[-1] == "--print-version"


def _read_unchanged_report(
    path: Path,
    *,
    before: Mapping[str, Any] | None,
) -> tuple[bytes | None, dict[str, Any] | None, str | None]:
    data, after = _read_file_snapshot(path)
    if before is None:
        return data, after, "cli-only requires an existing startup report sentinel"
    if data is None or after is None:
        return None, None, "cli-only startup report sentinel disappeared"
    if dict(before) != after:
        return data, after, "cli-only startup report sentinel changed"
    return data, after, None


def _validate_cli_only_report_sentinel(
    report: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    expected_config_signature: str | None,
    expected_daemon_generation: int | None,
) -> None:
    """Validate an old report as an unchanged sentinel, never as this run's result."""

    if before is None or after is None or dict(before) != dict(after):
        raise ReportValidationError("cli-only startup report sentinel identity changed")
    if report.get("schema_version") != STARTUP_REPORT_SCHEMA_VERSION:
        raise ReportValidationError("cli-only startup report sentinel schema is unsupported")
    if report.get("api_version") != STARTUP_REPORT_API_VERSION:
        raise ReportValidationError("cli-only startup report sentinel API is unsupported")
    if report.get("record_type") != "ccbd_startup_report":
        raise ReportValidationError("cli-only sentinel is not a ccbd_startup_report")
    if report.get("trigger") != "start_command" or report.get("status") != "ok":
        raise ReportValidationError("cli-only startup report sentinel is not a successful start")
    run_id = str(report.get("startup_run_id") or "").strip()
    if not re.fullmatch(r"start_[0-9a-f]{32}", run_id):
        raise ReportValidationError("cli-only startup report sentinel has an invalid run id")
    signature = str(report.get("config_signature") or "").strip()
    generation = report.get("daemon_generation")
    if not signature or type(generation) is not int or generation < 1:
        raise ReportValidationError("cli-only startup report sentinel lacks authority identity")
    if expected_config_signature is not None and signature != expected_config_signature:
        raise ReportValidationError("cli-only startup report sentinel config signature changed")
    if expected_daemon_generation is not None and generation != expected_daemon_generation:
        raise ReportValidationError("cli-only startup report sentinel generation changed")


def _wait_for_changed_report(
    path: Path,
    *,
    before: Mapping[str, Any] | None,
    wait_s: float,
    dependencies: BenchmarkDependencies,
) -> tuple[bytes | None, dict[str, Any] | None]:
    deadline = dependencies.perf_counter_ns() + int(max(0.0, wait_s) * 1_000_000_000)
    while True:
        try:
            data = path.read_bytes()
        except OSError:
            data = None
        if data is not None:
            after = _identity_from_bytes(path, data)
            if before is None or before.get("sha256") != after.get("sha256"):
                return data, after
        if dependencies.perf_counter_ns() >= deadline:
            return None, _file_identity(path)
        dependencies.sleep(0.02)


def _wait_for_unmounted(
    project_root: Path,
    *,
    wait_s: float,
    dependencies: BenchmarkDependencies,
) -> tuple[bool, dict[str, Any]]:
    lease_path = _runtime_ccbd_root(project_root) / "lease.json"
    lifecycle_path = _runtime_ccbd_root(project_root) / "lifecycle.json"
    deadline = dependencies.perf_counter_ns() + int(max(0.0, wait_s) * 1_000_000_000)
    evidence: dict[str, Any] = {}
    while True:
        lease = _try_read_json_object(lease_path)
        lifecycle = _try_read_json_object(lifecycle_path)
        evidence = {
            "lease": None if lease is None else {"mount_state": lease.get("mount_state"), "generation": lease.get("generation")},
            "lifecycle": None if lifecycle is None else {"phase": lifecycle.get("phase"), "desired_state": lifecycle.get("desired_state"), "generation": lifecycle.get("generation")},
        }
        lease_stopped = lease is None or lease.get("mount_state") == "unmounted"
        lifecycle_stopped = lifecycle is None or (
            lifecycle.get("phase") == "unmounted" and lifecycle.get("desired_state") == "stopped"
        )
        if lease_stopped and lifecycle_stopped:
            return True, evidence
        if dependencies.perf_counter_ns() >= deadline:
            return False, evidence
        dependencies.sleep(0.05)


def _load_fixture_inventory(project_root: Path, *, source_root: Path) -> dict[str, Any]:
    """Load the frozen project config without runtime/dynamic overlays."""

    lib_path = str((source_root / "lib").resolve(strict=True))
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
    try:
        from agents.config_loader import load_project_config

        config = load_project_config(project_root, include_loop_overlays=False).config
    except Exception as exc:
        raise SafetyError(f"fixture ccb.config cannot be loaded by this source checkout: {exc}") from exc

    provider_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    agent_names: list[str] = []
    command_templates: list[str] = []
    config_env_keys: set[str] = set()
    for agent_name, spec in sorted(dict(config.agents).items()):
        name = str(agent_name or "").strip()
        provider = str(getattr(spec, "provider", "") or "").strip().lower()
        if not name or not provider:
            raise SafetyError("fixture config contains an agent without a stable name/provider")
        agent_names.append(name)
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        model = str(getattr(spec, "model", "") or "<default>").strip()
        model_key = f"{provider}:{model}"
        model_counts[model_key] = model_counts.get(model_key, 0) + 1
        template = str(getattr(spec, "provider_command_template", "") or "").strip()
        if template:
            command_templates.append(name)
        config_env_keys.update(str(key) for key in dict(getattr(spec, "env", {}) or {}))
        profile = getattr(spec, "provider_profile", None)
        config_env_keys.update(str(key) for key in dict(getattr(profile, "env", {}) or {}))

    return {
        "config_version": int(config.version),
        "agent_names": tuple(agent_names),
        "default_agents": tuple(str(item) for item in tuple(config.default_agents or ())),
        "window_count": len(tuple(config.windows or ())),
        "provider_counts": provider_counts,
        "model_counts": model_counts,
        "command_template_agents": tuple(command_templates),
        "config_env_keys": tuple(sorted(config_env_keys)),
    }


def _validate_stub_fixture(
    inventory: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    source_root: Path,
    test_roots: Sequence[Path],
) -> None:
    if inventory.get("command_template_agents"):
        raise SafetyError(
            "stub benchmark fixtures cannot override provider commands in agent config"
        )
    if inventory.get("config_env_keys"):
        raise SafetyError(
            "stub benchmark fixtures cannot carry agent/provider-profile environment values"
        )

    expected_stub = (source_root / "test" / "stubs" / "provider_stub.py").resolve(strict=True)
    for provider in sorted(dict(inventory.get("provider_counts") or {})):
        stem = provider.upper().replace("-", "_")
        if stem not in _STUB_PROVIDER_NAMES:
            raise SafetyError(f"stub benchmark does not recognize configured provider: {provider}")
        env_name = f"{stem}_START_CMD"
        raw_command = str(environ.get(env_name) or "").strip()
        if not raw_command:
            raise SafetyError(
                f"stub benchmark requires explicit {env_name} mapped to the source provider stub"
            )
        try:
            parts = shlex.split(raw_command)
        except ValueError as exc:
            raise SafetyError(f"{env_name} is not a valid command: {exc}") from exc
        if not parts or not Path(parts[0]).expanduser().is_absolute():
            raise SafetyError(f"{env_name} executable must be an absolute path")
        try:
            executable = Path(parts[0]).expanduser().resolve(strict=True)
        except OSError as exc:
            raise SafetyError(f"{env_name} executable cannot be resolved: {exc}") from exc
        if executable != expected_stub:
            raise SafetyError(
                f"{env_name} must resolve to this checkout's deterministic provider stub"
            )
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise SafetyError(f"{env_name} provider stub is not executable")
        explicit_providers: list[str] = []
        index = 1
        while index < len(parts):
            part = parts[index]
            if part.startswith("--stub-launch-"):
                raise SafetyError(
                    f"{env_name} launch-probe options are reserved for the benchmark harness"
                )
            if part == "--":
                if any(
                    item.startswith(("--prov", "--stub-launch-"))
                    for item in parts[index + 1 :]
                ):
                    raise SafetyError(
                        f"{env_name} must not place provider options after --"
                    )
                break
            if part == "--provider":
                if index + 1 >= len(parts) or parts[index + 1].startswith("-"):
                    raise SafetyError(f"{env_name} has an invalid --provider argument")
                explicit_providers.append(parts[index + 1].strip().lower())
                index += 2
                continue
            elif part.startswith("--provider="):
                value = part.partition("=")[2].strip().lower()
                if not value:
                    raise SafetyError(f"{env_name} has an invalid --provider argument")
                explicit_providers.append(value)
            elif part.startswith("--prov"):
                raise SafetyError(f"{env_name} has an invalid provider option: {part}")
            index += 1
        if len(explicit_providers) > 1:
            raise SafetyError(f"{env_name} must not repeat --provider")
        invoked_provider = (
            explicit_providers[0]
            if explicit_providers
            else Path(parts[0]).name.strip().lower()
        )
        if invoked_provider != provider:
            raise SafetyError(
                f"{env_name} does not identify configured provider {provider!r}; "
                f"use a {provider!r}-named symlink or pass --provider {provider}"
            )

    for key, raw_value in environ.items():
        if key == "PATH" or not _stub_environment_key_allowed(key):
            continue
        if not (key.endswith("_STATE_PATH") or key.endswith("_BARRIER_PATH")):
            continue
        value = str(raw_value or "").strip()
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise SafetyError(f"{key} must be an absolute path")
        resolved = path.resolve(strict=False)
        if not any(_path_is_under(resolved, root) for root in test_roots):
            raise SafetyError(f"{key} is outside all allowed external test roots")


def _validate_owner_marker(
    marker: Mapping[str, Any],
    *,
    project_root: Path,
    source_home: Path,
    source_root: Path,
    source_sha: str,
) -> str:
    if marker.get("schema_version") != SCHEMA_VERSION or marker.get("record_type") != OWNER_RECORD_TYPE:
        raise SafetyError("fixture owner marker has the wrong schema or record type")
    try:
        owner_uuid = str(uuid.UUID(str(marker.get("owner_uuid") or "")))
    except (ValueError, AttributeError) as exc:
        raise SafetyError("fixture owner marker has an invalid owner UUID") from exc
    expected = {
        "project_root": str(project_root),
        "source_home": str(source_home),
        "source_root": str(source_root),
        "source_sha": source_sha,
    }
    for key, value in expected.items():
        if marker.get(key) != value:
            raise SafetyError(f"fixture owner marker {key} does not match this benchmark")
    return owner_uuid


def _validate_pristine_fixture(*, project_root: Path, source_home: Path) -> None:
    ccbd_dir = _runtime_ccbd_root(project_root)
    agents_dir = _runtime_agents_root(project_root)
    if ccbd_dir.exists() or agents_dir.exists():
        raise SafetyError("pristine scenario requires no existing .ccb/ccbd or .ccb/agents runtime state")
    if any(source_home.iterdir()):
        raise SafetyError("pristine scenario requires an empty isolated source-home")


def _effective_test_roots(options: StartupBenchmarkOptions, env: Mapping[str, str]) -> tuple[Path, ...]:
    raw_roots: list[Path] = list(options.test_roots)
    if not raw_roots:
        for name in ("CCB_TEST_ROOTS", "CCB_SOURCE_ALLOWED_ROOTS"):
            raw_roots.extend(Path(value).expanduser() for value in str(env.get(name) or "").split(os.pathsep) if value)
        raw_roots.append(DEFAULT_TEST_ROOT)
    roots: list[Path] = []
    seen: set[str] = set()
    for root in raw_roots:
        _require_absolute(root, "test-root")
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise SafetyError(f"test-root is not a directory: {resolved}")
        if _path_is_under(resolved, SOURCE_ROOT.resolve()):
            raise SafetyError("test-root cannot be inside the source checkout")
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    return tuple(roots)


def _source_drift_reason(context: ValidatedContext) -> str | None:
    try:
        current_sha = _read_source_sha(context.source_root)
        current_wrapper_sha = _sha256_file(context.ccb_test_path)
        current_tree = _source_tree_fingerprint(context.source_root)
        current_config_sha = _sha256_file(context.project_root / ".ccb" / "ccb.config")
        marker_path = context.project_root / OWNER_MARKER_NAME
        current_marker_sha = _sha256_file(marker_path)
        current_marker = _read_json_object(marker_path, label="fixture owner marker")
        current_owner_uuid = _validate_owner_marker(
            current_marker,
            project_root=context.project_root,
            source_home=context.source_home,
            source_root=context.source_root,
            source_sha=context.source_sha,
        )
    except Exception as exc:
        return f"source identity could not be revalidated: {exc}"
    if current_sha != context.source_sha:
        return "source HEAD changed during the benchmark"
    if current_wrapper_sha != context.wrapper_sha256:
        return "ccb_test wrapper content changed during the benchmark"
    if current_tree != context.source_tree_fingerprint:
        return "source worktree content changed during the benchmark"
    if current_config_sha != context.config_sha256:
        return ".ccb/ccb.config content changed during the benchmark"
    if current_marker_sha != context.owner_marker_sha256 or current_owner_uuid != context.owner_uuid:
        return "fixture owner marker changed during the benchmark"
    return None


def _source_tree_fingerprint(source_root: Path) -> str:
    """Hash tracked changes and untracked content without scanning clean files."""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    commands = (
        ("git", "diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", "--"),
        ("git", "ls-files", "--others", "--exclude-standard", "-z"),
    )
    outputs: list[bytes] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=str(source_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SafetyError(f"source worktree fingerprint command failed: {command[1]}: {exc}") from exc
        if completed.returncode != 0:
            detail = _coerce_output(completed.stderr).strip()
            raise SafetyError(
                f"source worktree fingerprint command failed: {command[1]}: {detail or completed.returncode}"
            )
        outputs.append(bytes(completed.stdout or b""))

    digest = hashlib.sha256()
    digest.update(b"git-diff\0")
    digest.update(outputs[0])
    digest.update(b"\0untracked\0")
    try:
        untracked = sorted(item for item in outputs[1].split(b"\0") if item)
        for raw_relative in untracked:
            relative = raw_relative.decode("utf-8", errors="surrogateescape")
            path = source_root / relative
            digest.update(raw_relative)
            digest.update(b"\0")
            if path.is_symlink():
                digest.update(b"L")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest.update(b"F")
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"MISSING")
            digest.update(b"\0")
    except OSError as exc:
        raise SafetyError(f"source worktree fingerprint failed: {exc}") from exc
    return digest.hexdigest()


def _read_source_sha(source_root: Path) -> str:
    git_dir_path = source_root / ".git"
    if git_dir_path.is_dir():
        git_dir = git_dir_path
    elif git_dir_path.is_file():
        line = git_dir_path.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            raise SafetyError("source checkout .git file is invalid")
        candidate = Path(line.split(":", 1)[1].strip())
        git_dir = (source_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    else:
        raise SafetyError("ccb-test is not inside a git source checkout")
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        return head.lower()
    if not head.startswith("ref: "):
        raise SafetyError("source checkout HEAD cannot be resolved")
    ref = head[5:].strip()
    git_bases = [git_dir]
    common_dir_file = git_dir / "commondir"
    if common_dir_file.is_file():
        common = (git_dir / common_dir_file.read_text(encoding="utf-8").strip()).resolve()
        git_bases.append(common)
    for candidate in (base / ref for base in git_bases):
        if candidate.is_file():
            value = candidate.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
                return value.lower()
    for base in git_bases:
        packed = base / "packed-refs"
        if not packed.is_file():
            continue
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "^")):
                value, name = line.split(" ", 1)
                if name == ref:
                    return value.lower()
    raise SafetyError("source checkout HEAD ref cannot be resolved")


def _read_version(source_root: Path) -> str | None:
    try:
        return (source_root / "VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _file_identity(path: Path) -> dict[str, Any] | None:
    _data, identity = _read_file_snapshot(path)
    return identity


def _read_file_snapshot(path: Path) -> tuple[bytes | None, dict[str, Any] | None]:
    try:
        with path.open("rb") as handle:
            data = handle.read()
            file_stat = os.fstat(handle.fileno())
    except OSError:
        return None, None
    return data, _identity_from_stat(data, file_stat)


def _identity_from_bytes(path: Path, data: bytes) -> dict[str, Any]:
    try:
        file_stat = path.stat()
    except OSError:
        file_stat = None
    return _identity_from_stat(data, file_stat)


def _identity_from_stat(data: bytes, file_stat: os.stat_result | None) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "mtime_ns": file_stat.st_mtime_ns if file_stat is not None else None,
        "ctime_ns": file_stat.st_ctime_ns if file_stat is not None else None,
        "device": file_stat.st_dev if file_stat is not None else None,
        "inode": file_stat.st_ino if file_stat is not None else None,
        "mode": stat.S_IMODE(file_stat.st_mode) if file_stat is not None else None,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SafetyError(f"{label} is missing: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafetyError(f"{label} cannot be read as JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SafetyError(f"{label} must contain a JSON object")
    return payload


def _try_read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _output_metadata(value: str) -> dict[str, Any]:
    data = value.encode("utf-8", errors="replace")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _parse_start_stdout(
    value: str,
) -> tuple[str | None, dict[str, float] | None, str | None, dict[str, float] | None]:
    run_ids: list[str] = []
    timing_payloads: list[dict[str, float]] = []
    process_trace_ids: list[str] = []
    process_timing_payloads: list[dict[str, float]] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line.startswith("startup_run_id:"):
            run_id = line.split(":", 1)[1].strip()
            if not re.fullmatch(r"start_[0-9a-f]{32}", run_id):
                raise ReportValidationError("stdout has an invalid startup_run_id")
            run_ids.append(run_id)
        elif line.startswith("startup_cli_timings_ms:"):
            text = line.split(":", 1)[1].strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ReportValidationError("stdout startup_cli_timings_ms is invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ReportValidationError("stdout startup_cli_timings_ms must be an object")
            clean: dict[str, float] = {}
            for key, value_item in payload.items():
                parsed = _validated_duration(
                    value_item,
                    label=f"stdout startup_cli_timings_ms.{key}",
                )
                clean[str(key)] = parsed
            timing_payloads.append(clean)
        elif line.startswith("startup_process_trace_id:"):
            trace_id = line.split(":", 1)[1].strip()
            if not re.fullmatch(r"trace_[0-9a-f]{32}", trace_id):
                raise ReportValidationError("stdout has an invalid startup_process_trace_id")
            process_trace_ids.append(trace_id)
        elif line.startswith("startup_process_bootstrap_timings_ms:"):
            text = line.split(":", 1)[1].strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ReportValidationError(
                    "stdout startup_process_bootstrap_timings_ms is invalid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise ReportValidationError(
                    "stdout startup_process_bootstrap_timings_ms must be an object"
                )
            clean = {}
            for key, value_item in payload.items():
                clean[str(key)] = _validated_duration(
                    value_item,
                    label=f"stdout startup_process_bootstrap_timings_ms.{key}",
                )
            process_timing_payloads.append(clean)
    if any(
        len(items) > 1
        for items in (run_ids, timing_payloads, process_trace_ids, process_timing_payloads)
    ):
        raise ReportValidationError("stdout contains duplicate startup correlation lines")
    if len(run_ids) != 1 or len(timing_payloads) != 1:
        raise ReportValidationError(
            "stdout must contain exactly one startup_run_id and startup_cli_timings_ms line"
        )
    timings = timing_payloads[0]
    missing = sorted(CLI_REQUIRED_TIMING_KEYS - set(timings))
    if missing:
        raise ReportValidationError(
            "stdout startup_cli_timings_ms is missing required keys: " + ", ".join(missing)
        )
    cli_partition = sum(
        timings[key]
        for key in ("cli_pre_rpc", "daemon_ensure", "start_rpc", "cli_post_rpc")
    )
    if cli_partition - timings["cli_total"] > TIMING_CONTAINMENT_TOLERANCE_MS:
        raise ReportValidationError(
            "stdout startup_cli_timings_ms has non-contained CLI phases: "
            f"partition={cli_partition:.6f} cli_total={timings['cli_total']:.6f}"
        )
    post_rpc_partition = sum(
        timings[key]
        for key in ("sidebar_helper_refresh", "layout_status", "maintenance_heartbeat")
    )
    if post_rpc_partition - timings["cli_post_rpc"] > TIMING_CONTAINMENT_TOLERANCE_MS:
        raise ReportValidationError(
            "stdout startup_cli_timings_ms has non-contained post-RPC phases: "
            f"partition={post_rpc_partition:.6f} cli_post_rpc={timings['cli_post_rpc']:.6f}"
        )
    if bool(process_trace_ids) != bool(process_timing_payloads):
        raise ReportValidationError(
            "stdout process trace id and bootstrap timings must be emitted together"
        )
    return (
        run_ids[0],
        timings,
        process_trace_ids[0] if process_trace_ids else None,
        process_timing_payloads[0] if process_timing_payloads else None,
    )


def _validate_cli_only_stdout(value: str, *, expected_version: str | None) -> None:
    """Require deterministic introspection output and reject start-transaction evidence."""

    if expected_version is None:
        raise ReportValidationError("source VERSION is unavailable for cli-only validation")
    metadata_prefixes = (
        "startup_run_id:",
        "startup_cli_timings_ms:",
        "startup_process_trace_id:",
        "startup_process_bootstrap_timings_ms:",
    )
    if any(line.strip().startswith(metadata_prefixes) for line in value.splitlines()):
        raise ReportValidationError("cli-only stdout contains unexpected startup metadata")
    if value != f"v{expected_version}\n":
        raise ReportValidationError("cli-only stdout does not exactly match the source version")


def _validate_readiness_timeline(
    value: Mapping[str, Any],
    *,
    startup_run_id: str,
    stdout_process_trace_id: str | None,
    daemon_generation: object,
    desired_agents: object,
    command_wall_ms: float,
    require_complete: bool,
) -> dict[str, Any]:
    validated_command_wall_ms = _validated_duration(
        command_wall_ms,
        label="readiness_timeline foreground command wall",
    )
    if value.get("schema_version") != 1:
        raise ReportValidationError("readiness_timeline has unsupported schema_version")
    trace_id = str(value.get("trace_id") or "").strip()
    if not re.fullmatch(r"trace_[0-9a-f]{32}", trace_id):
        raise ReportValidationError("readiness_timeline has invalid trace_id")
    if stdout_process_trace_id is not None and trace_id != stdout_process_trace_id:
        raise ReportValidationError("readiness_timeline trace_id does not match stdout process trace")
    if str(value.get("startup_run_id") or "") != startup_run_id:
        raise ReportValidationError("readiness_timeline startup_run_id correlation mismatch")
    if value.get("clock") != "host_perf_counter_ns" or value.get("origin") != "ccb_py_entry":
        raise ReportValidationError("readiness_timeline clock/origin contract mismatch")
    if value.get("attach_mode") != "no_attach":
        raise ReportValidationError("latency benchmark readiness_timeline must use no_attach mode")
    if "origin_monotonic_ns" in json.dumps(value, ensure_ascii=True, sort_keys=True):
        raise ReportValidationError("readiness_timeline persisted a raw monotonic origin")
    report_generation = _validated_nonnegative_int(
        daemon_generation,
        label="startup report daemon_generation",
    )
    timeline_generation = _validated_nonnegative_int(
        value.get("daemon_generation"),
        label="readiness_timeline daemon_generation",
    )
    expected_generation = _validated_nonnegative_int(
        value.get("expected_daemon_generation"),
        label="readiness_timeline expected_daemon_generation",
    )
    if (
        timeline_generation != report_generation
        or expected_generation != report_generation
        or value.get("generation_correlation") != "matched"
    ):
        raise ReportValidationError("readiness_timeline daemon generation correlation mismatch")
    desired = _validated_agent_name_list(desired_agents, label="startup report desired_agents")
    timeline_desired = _validated_agent_name_list(
        value.get("desired_agents"),
        label="readiness_timeline desired_agents",
    )
    effective = _validated_agent_name_list(
        value.get("effective_requested_agents"),
        label="readiness_timeline effective_requested_agents",
    )
    if set(timeline_desired) != set(desired) or set(effective) != set(desired):
        raise ReportValidationError("readiness_timeline Agent scope does not match eager desired set")
    rpc_accepted_ms = _validated_duration(
        value.get("rpc_accepted_ms"),
        label="readiness_timeline.rpc_accepted_ms",
    )
    raw_points = value.get("points")
    if not isinstance(raw_points, Mapping):
        raise ReportValidationError("readiness_timeline.points must be an object")
    missing_points = sorted(set(READINESS_POINT_NAMES) - set(raw_points))
    if missing_points:
        raise ReportValidationError(
            "readiness_timeline is missing points: " + ", ".join(missing_points)
        )
    extra_points = sorted(set(raw_points) - set(READINESS_POINT_NAMES))
    if extra_points:
        raise ReportValidationError(
            "readiness_timeline has unknown points: " + ", ".join(extra_points)
        )
    points: dict[str, dict[str, Any]] = {}
    allowed_statuses = {
        "reached",
        "observed_upper_bound",
        "not_required_already_mounted",
        "not_applicable_no_attach",
        "not_reached_at_rpc_return",
        "failed_before_ready",
        "not_observed",
    }
    for name in READINESS_POINT_NAMES:
        raw_point = raw_points.get(name)
        if not isinstance(raw_point, Mapping):
            raise ReportValidationError(f"readiness_timeline.points.{name} must be an object")
        status = str(raw_point.get("status") or "").strip()
        if status not in allowed_statuses:
            raise ReportValidationError(f"readiness_timeline.points.{name} has invalid status")
        raw_elapsed = raw_point.get("elapsed_ms")
        elapsed_ms = (
            None
            if raw_elapsed is None
            else _validated_duration(
                raw_elapsed,
                label=f"readiness_timeline.points.{name}.elapsed_ms",
            )
        )
        if status in {"reached", "observed_upper_bound", "failed_before_ready"}:
            if elapsed_ms is None:
                raise ReportValidationError(
                    f"readiness_timeline.points.{name} requires elapsed_ms"
                )
        elif elapsed_ms is not None:
            raise ReportValidationError(
                f"readiness_timeline.points.{name} must not carry elapsed_ms for {status}"
            )
        source = str(raw_point.get("source") or "").strip()
        if not source or len(source) > 256:
            raise ReportValidationError(f"readiness_timeline.points.{name} has invalid source")
        agents = _validated_agent_name_list(
            raw_point.get("agents"),
            label=f"readiness_timeline.points.{name}.agents",
        )
        if not set(agents).issubset(set(desired)):
            raise ReportValidationError(f"readiness_timeline.points.{name} has unknown agents")
        points[name] = {
            "status": status,
            "elapsed_ms": elapsed_ms,
            "source": source,
            "agents": list(agents),
        }
    if points["T0_cli_entry"] != {
        "status": "reached",
        "elapsed_ms": 0.0,
        "source": points["T0_cli_entry"]["source"],
        "agents": [],
    }:
        raise ReportValidationError("readiness_timeline T0_cli_entry contract mismatch")
    if points["T2_control_plane_ready"]["status"] != "reached":
        raise ReportValidationError("readiness_timeline T2_control_plane_ready was not reached")
    if points["T1_lifecycle_intent"]["status"] not in {
        "reached",
        "observed_upper_bound",
        "not_required_already_mounted",
    }:
        raise ReportValidationError("readiness_timeline T1_lifecycle_intent has invalid provenance")
    for name in ("T3_namespace_attachable", "T4_requested_agents_ready", "T6_fully_warm"):
        if points[name]["status"] != "reached":
            raise ReportValidationError(f"readiness_timeline {name} was not reached")
    if points["T5_foreground_attached"]["status"] != "not_applicable_no_attach":
        raise ReportValidationError("readiness_timeline T5 must be not_applicable_no_attach")
    expected_sources = {
        "T0_cli_entry": "ccb_py_process_entry",
        "T1_lifecycle_intent": (
            "keeper_lifecycle_starting_committed"
            if points["T1_lifecycle_intent"]["status"] == "reached"
            else (
                "cli_compatible_daemon_observation"
                if points["T1_lifecycle_intent"]["status"] == "observed_upper_bound"
                else "cli_existing_mounted_generation"
            )
        ),
        "T2_control_plane_ready": "cli_compatible_daemon_handle",
        "T3_namespace_attachable": "ccbd_namespace_ensure_current_generation",
        "T4_requested_agents_ready": "ccbd_start_flow_authority_committed",
        "T5_foreground_attached": "ccb_no_attach",
        "T6_fully_warm": "ccbd_start_flow_all_desired_agents_committed",
    }
    if any(points[name]["source"] != source for name, source in expected_sources.items()):
        raise ReportValidationError("readiness_timeline milestone provenance mismatch")
    empty_scope_points = (
        "T0_cli_entry",
        "T1_lifecycle_intent",
        "T2_control_plane_ready",
        "T3_namespace_attachable",
        "T5_foreground_attached",
    )
    if any(points[name]["agents"] for name in empty_scope_points):
        raise ReportValidationError("readiness_timeline non-Agent milestones carry Agent scope")
    if set(points["T4_requested_agents_ready"]["agents"]) != set(effective):
        raise ReportValidationError("readiness_timeline T4 Agent scope mismatch")
    if set(points["T6_fully_warm"]["agents"]) != set(timeline_desired):
        raise ReportValidationError("readiness_timeline T6 Agent scope mismatch")
    t1_elapsed = points["T1_lifecycle_intent"]["elapsed_ms"]
    t2_elapsed = points["T2_control_plane_ready"]["elapsed_ms"]
    t3_elapsed = points["T3_namespace_attachable"]["elapsed_ms"]
    t4_elapsed = points["T4_requested_agents_ready"]["elapsed_ms"]
    t6_elapsed = points["T6_fully_warm"]["elapsed_ms"]
    ordered = [t2_elapsed, rpc_accepted_ms, t3_elapsed, t4_elapsed, t6_elapsed]
    if any(left > right + TIMING_CONTAINMENT_TOLERANCE_MS for left, right in zip(ordered, ordered[1:])):
        raise ReportValidationError("readiness_timeline T2/RPC/T3/T4/T6 order is invalid")
    if t1_elapsed is not None and t1_elapsed > t2_elapsed + TIMING_CONTAINMENT_TOLERANCE_MS:
        raise ReportValidationError("readiness_timeline T1/T2 order is invalid")
    if (
        points["T1_lifecycle_intent"]["status"] == "observed_upper_bound"
        and abs(t1_elapsed - t2_elapsed) > TIMING_CONTAINMENT_TOLERANCE_MS
    ):
        raise ReportValidationError("readiness_timeline T1 upper bound must share T2 observation")
    keeper_startup_id = str(value.get("keeper_startup_id") or "").strip() or None
    if (
        points["T1_lifecycle_intent"]["status"]
        in {"reached", "observed_upper_bound"}
        and keeper_startup_id is None
    ):
        raise ReportValidationError("readiness_timeline cold T1 lacks keeper startup id")
    if t6_elapsed > validated_command_wall_ms + TIMING_CONTAINMENT_TOLERANCE_MS:
        raise ReportValidationError("readiness_timeline exceeds foreground command wall")
    timeline_complete = value.get("timeline_complete") is True
    if require_complete and not timeline_complete:
        raise ReportValidationError("readiness_timeline is incomplete")
    return {
        "schema_version": 1,
        "trace_id": trace_id,
        "clock": "host_perf_counter_ns",
        "origin": "ccb_py_entry",
        "attach_mode": "no_attach",
        "startup_run_id": startup_run_id,
        "keeper_startup_id": keeper_startup_id,
        "daemon_generation": timeline_generation,
        "expected_daemon_generation": expected_generation,
        "generation_correlation": "matched",
        "rpc_accepted_ms": rpc_accepted_ms,
        "effective_requested_agents": list(effective),
        "desired_agents": list(timeline_desired),
        "points": points,
        "timeline_complete": timeline_complete,
    }


def _readiness_point_durations(value: Mapping[str, Any]) -> dict[str, float | None]:
    points = value.get("points") if isinstance(value, Mapping) else None
    if not isinstance(points, Mapping):
        return {}
    result = {
        name: (
            _finite_nonnegative_or_none(points[name].get("elapsed_ms"))
            if isinstance(points.get(name), Mapping)
            and points[name].get("status") == "reached"
            else None
        )
        for name in READINESS_POINT_NAMES
    }
    t1 = points.get("T1_lifecycle_intent")
    result["T1_lifecycle_intent_upper_bound"] = (
        _finite_nonnegative_or_none(t1.get("elapsed_ms"))
        if isinstance(t1, Mapping) and t1.get("status") == "observed_upper_bound"
        else None
    )
    return result


def _validated_nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise ReportValidationError(f"{label} must be a nonnegative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReportValidationError(f"{label} must be a nonnegative integer") from exc
    if parsed < 0 or str(parsed) != str(value).strip():
        raise ReportValidationError(f"{label} must be a nonnegative integer")
    return parsed


def _validated_agent_name_list(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ReportValidationError(f"{label} must be an array")
    clean = tuple(str(item).strip() for item in value if str(item).strip())
    if len(clean) != len(value) or len(set(clean)) != len(clean):
        raise ReportValidationError(f"{label} contains empty or duplicate Agent names")
    return clean


def _derived_timings(
    *,
    wall_ms: float,
    cli_timings_ms: Mapping[str, float] | None,
    process_bootstrap_timings_ms: Mapping[str, float] | None,
    report: Mapping[str, Any] | None,
) -> dict[str, float | None]:
    cli_total = (
        _finite_nonnegative_or_none(cli_timings_ms.get("cli_total"))
        if cli_timings_ms is not None
        else None
    )
    report_timings = report.get("timings_ms") if isinstance(report, Mapping) else None
    supervisor_total = (
        _finite_nonnegative_or_none(report_timings.get("supervisor_total"))
        if isinstance(report_timings, Mapping)
        else None
    )
    process_bootstrap_total = _sum_finite_durations(
        dict(process_bootstrap_timings_ms or {}),
        PROCESS_BOOTSTRAP_TIMING_KEYS,
    )
    post_cli_residual = (
        wall_ms - process_bootstrap_total - cli_total
        if process_bootstrap_total is not None and cli_total is not None
        else None
    )
    return {
        "process_bootstrap_total": process_bootstrap_total,
        "post_cli_residual": post_cli_residual,
        "external_minus_cli_total": wall_ms - cli_total if cli_total is not None else None,
        "external_minus_supervisor_total": wall_ms - supervisor_total if supervisor_total is not None else None,
    }


def _derived_readiness_ms(
    *,
    cli_timings_ms: Mapping[str, float] | None,
    process_bootstrap_timings_ms: Mapping[str, float] | None,
    report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cli = dict(cli_timings_ms or {})
    report_timings = (
        dict(report.get("timings_ms") or {})
        if isinstance(report, Mapping) and isinstance(report.get("timings_ms"), Mapping)
        else {}
    )
    control_plane_ready = _sum_finite_durations(
        cli,
        ("cli_pre_rpc", "daemon_ensure"),
    )
    namespace_ready = _finite_nonnegative_or_none(report_timings.get("namespace_ensure"))
    flow_to_agents_ready = _sum_finite_durations(
        report_timings,
        (
            "context_and_layout_plan",
            "tmux_namespace_runtime",
            "agent_prepare_and_classify",
            "tmux_layout",
            "active_panes_and_cmd",
            "agent_runtime_commit",
        ),
    )
    requested_ready = (
        namespace_ready + flow_to_agents_ready
        if namespace_ready is not None and flow_to_agents_ready is not None
        else None
    )
    t0_observed = _sum_finite_durations(
        dict(process_bootstrap_timings_ms or {}),
        PROCESS_BOOTSTRAP_TIMING_KEYS[:3],
    ) is not None
    missing = [
        "T1_lifecycle_intent",
        "T2_control_plane_ready",
        "T3_namespace_attachable",
        "T4_requested_agents_ready",
        "T6_fully_warm",
    ]
    if not t0_observed:
        missing.insert(0, "T0_cli_entry")
    return {
        "schema_version": 1,
        "status": "legacy_partial_mixed_origins",
        "mode": "no_attach",
        "clock": "host_perf_counter_ns",
        "origin": "ccb_py_entry",
        "T0_cli_entry": 0.0 if t0_observed else None,
        "T1_lifecycle_intent": None,
        "T2_control_plane_ready": None,
        "T3_namespace_attachable": None,
        "T4_requested_agents_ready": None,
        "T5_foreground_attached": None,
        "T6_fully_warm": None,
        "point_states": {
            "T0_cli_entry": "observed" if t0_observed else "unavailable",
            "T1_lifecycle_intent": "unavailable_no_keeper_checkpoint",
            "T2_control_plane_ready": "unavailable_mixed_origin_legacy_duration",
            "T3_namespace_attachable": "unavailable_mixed_origin_legacy_duration",
            "T4_requested_agents_ready": "unavailable_mixed_origin_legacy_duration",
            "T5_foreground_attached": "not_applicable_no_attach",
            "T6_fully_warm": "unavailable_mixed_origin_legacy_duration",
        },
        "legacy_relative_estimates_ms": {
            "control_plane_ready_after_cli_start": control_plane_ready,
            "namespace_ensure_after_supervisor_start": namespace_ready,
            "requested_ready_after_supervisor_start": requested_ready,
        },
        "timeline_complete": False,
        "missing": missing,
    }


def _attribution_record(
    *,
    wall_ms: float,
    cli_timings_ms: Mapping[str, float] | None,
    process_bootstrap_timings_ms: Mapping[str, float] | None,
    report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cli = dict(cli_timings_ms or {})
    report_timings = (
        dict(report.get("timings_ms") or {})
        if isinstance(report, Mapping) and isinstance(report.get("timings_ms"), Mapping)
        else {}
    )
    cli_total = _finite_nonnegative_or_none(cli.get("cli_total"))
    process_bootstrap_total = _sum_finite_durations(
        dict(process_bootstrap_timings_ms or {}),
        PROCESS_BOOTSTRAP_TIMING_KEYS,
    )
    external_named = (
        cli_total + process_bootstrap_total
        if cli_total is not None and process_bootstrap_total is not None
        else None
    )
    supervisor_total = _finite_nonnegative_or_none(report_timings.get("supervisor_total"))
    supervisor_named = _sum_finite_durations(
        report_timings,
        ("namespace_ensure", "flow_total"),
    )
    flow_named = _sum_finite_durations(
        report_timings,
        (
            "context_and_layout_plan",
            "tmux_namespace_runtime",
            "agent_prepare_and_classify",
            "tmux_layout",
            "active_panes_and_cmd",
            "agent_runtime_commit",
            "tmux_cleanup",
        ),
    )
    flow_total = _finite_nonnegative_or_none(report_timings.get("flow_total"))
    return {
        "external": _coverage_payload(total=wall_ms, named=external_named),
        "supervisor": _coverage_payload(total=supervisor_total, named=supervisor_named),
        "flow": _coverage_payload(total=flow_total, named=flow_named),
    }


def _cli_only_attribution_record(wall_ms: float) -> dict[str, Any]:
    return {
        "external": _coverage_payload(total=wall_ms, named=wall_ms),
        "supervisor": {
            "status": "not_applicable_cli_only",
            **_coverage_payload(total=None, named=None),
        },
        "flow": {
            "status": "not_applicable_cli_only",
            **_coverage_payload(total=None, named=None),
        },
    }


def _coverage_payload(*, total: float | None, named: float | None) -> dict[str, float | None]:
    if total is None or named is None:
        return {"total_ms": total, "named_ms": named, "unattributed_ms": None, "coverage": None}
    unattributed = max(0.0, total - named)
    return {
        "total_ms": total,
        "named_ms": named,
        "unattributed_ms": unattributed,
        "coverage": min(1.0, named / total) if total > 0 else 1.0,
    }


def _sum_finite_durations(
    values: Mapping[str, Any],
    keys: Sequence[str],
) -> float | None:
    parsed: list[float] = []
    for key in keys:
        value = _finite_nonnegative_or_none(values.get(key))
        if value is None:
            return None
        parsed.append(value)
    return sum(parsed)


def _agent_metrics_for_record(report: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(report, Mapping) or not isinstance(report.get("agent_results"), list):
        return []
    metrics: list[dict[str, Any]] = []
    for result in report["agent_results"]:
        if not isinstance(result, Mapping):
            continue
        metrics.append(
            {
                "provider": str(result.get("provider") or "").strip().lower() or None,
                "action": str(result.get("action") or "").strip() or None,
                "health": str(result.get("health") or "").strip() or None,
                "duration_ms": _finite_nonnegative_or_none(result.get("duration_ms")),
                "provider_prepare_ms": _finite_nonnegative_or_none(
                    result.get("provider_prepare_ms")
                ),
                "provider_prepare_count": (
                    int(result["provider_prepare_count"])
                    if type(result.get("provider_prepare_count")) is int
                    and int(result["provider_prepare_count"]) >= 0
                    else None
                ),
                "timings_ms": _duration_mapping_for_record(result.get("timings_ms")),
                "input_readiness_status": _redacted_status(
                    result.get("input_readiness_status"),
                    allowed=INPUT_READINESS_STATUSES,
                ),
                "native_session_id_status": _redacted_status(
                    result.get("native_session_id_status"),
                    allowed=NATIVE_SESSION_ID_STATUSES,
                ),
            }
        )
    return metrics


def _redacted_status(value: object, *, allowed: frozenset[str]) -> str | None:
    if not isinstance(value, str):
        return None
    status = value.strip()
    return status if status in allowed else None


def _finite_nonnegative_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _duration_mapping_for_record(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    clean: dict[str, float] = {}
    for key, raw_value in value.items():
        parsed = _finite_nonnegative_or_none(raw_value)
        if parsed is not None:
            clean[str(key)] = parsed
    return clean


def _operation_mapping_for_record(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    clean: dict[str, int] = {}
    for key, raw_value in value.items():
        if type(raw_value) is not int or raw_value < 0:
            continue
        name = str(key or "").strip()
        if name:
            clean[name] = int(raw_value)
    return clean


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_bytes(path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _best_effort_write_json(path: Path, payload: Mapping[str, Any]) -> Exception | None:
    try:
        _write_json(path, payload)
    except Exception as exc:
        return exc
    return None


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            os.fchmod(handle.fileno(), 0o600)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _require_absolute(path: Path, label: str) -> None:
    if not path.expanduser().is_absolute():
        raise SafetyError(f"{label} must be an absolute path")


RUNTIME_ROOT_REF_NAME = "runtime-root-ref.json"
RUNTIME_ROOT_REF_RECORD_TYPE = "ccb_runtime_root_ref"


def _runtime_state_root(project_root: Path) -> Path:
    """Resolve the daemon state root while keeping the project anchor separate.

    The fork relocates mutable runtime state by writing a small reference under
    ``project/.ccb``.  The benchmark is intentionally standalone, so it mirrors
    the product's fail-safe semantics instead of importing the full storage
    package: malformed or missing references fall back to the anchor.
    """

    anchor = project_root / ".ccb"
    reference = anchor / RUNTIME_ROOT_REF_NAME
    try:
        payload = _read_json_object(reference, label="runtime root reference")
    except SafetyError:
        return anchor
    if payload.get("record_type") != RUNTIME_ROOT_REF_RECORD_TYPE:
        return anchor
    if payload.get("schema_version") != 1:
        return anchor
    if not str(payload.get("project_id") or "").strip():
        return anchor
    raw_root = str(payload.get("runtime_state_root") or "").strip()
    if not raw_root:
        return anchor
    candidate = Path(raw_root).expanduser()
    if not candidate.is_absolute():
        return anchor
    return candidate


def _runtime_ccbd_root(project_root: Path) -> Path:
    return _runtime_state_root(project_root) / "ccbd"


def _runtime_agents_root(project_root: Path) -> Path:
    return _runtime_state_root(project_root) / "agents"


def _project_state_roots(project_root: Path) -> tuple[Path, ...]:
    """Return anchor plus the active runtime root for containment checks."""

    anchor = project_root / ".ccb"
    runtime_root = _runtime_state_root(project_root)
    if runtime_root == anchor:
        return (anchor,)
    return (anchor, runtime_root)


def _path_is_under_any(path: Path, roots: Sequence[Path]) -> bool:
    return any(_path_is_under(path, root) for root in roots)


def _path_is_under(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _paths_overlap(left: Path, right: Path) -> bool:
    return _path_is_under(left, right) or _path_is_under(right, left)


def _parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_text() -> str:
    return _format_utc(datetime.now(timezone.utc))


def _new_benchmark_id(now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"startup-{stamp}-{uuid.uuid4().hex[:8]}"


def _parse_args(argv: Sequence[str] | None = None) -> StartupBenchmarkOptions:
    parser = argparse.ArgumentParser(description="Safely benchmark source CCB startup wall latency.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--ccb-test", required=True, type=Path)
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--launch-cap", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--result-root", required=True, type=Path)
    parser.add_argument("--source-home", type=Path, default=DEFAULT_SOURCE_HOME)
    parser.add_argument("--test-root", action="append", type=Path, default=[])
    parser.add_argument("--restore-policy", choices=RESTORE_POLICIES, default="resume")
    parser.add_argument(
        "--provider-env-mode",
        choices=PROVIDER_ENV_MODES,
        default="stub",
        help="stub uses a sanitized allowlist; inherited explicitly opts into the caller's provider environment",
    )
    parser.add_argument(
        "--instrumentation-mode",
        choices=INSTRUMENTATION_MODES,
        default="profiled",
    )
    parser.add_argument("--instrumentation-ab-seed", type=int, default=None)
    parser.add_argument("--command-timeout-s", type=float, default=120.0)
    parser.add_argument("--kill-timeout-s", type=float, default=60.0)
    parser.add_argument("--stop-wait-s", type=float, default=10.0)
    parser.add_argument("--report-wait-s", type=float, default=2.0)
    parser.add_argument("--resource-sample-interval-ms", type=float, default=50.0)
    parser.add_argument("--benchmark-id", default=None)
    args = parser.parse_args(argv)
    return StartupBenchmarkOptions(
        project_root=args.project_root,
        ccb_test_path=args.ccb_test,
        scenario=args.scenario,
        result_root=args.result_root,
        source_home=args.source_home,
        test_roots=tuple(args.test_root),
        iterations=args.iterations,
        warmup=args.warmup,
        launch_cap=args.launch_cap,
        restore_policy=args.restore_policy,
        provider_env_mode=args.provider_env_mode,
        instrumentation_mode=args.instrumentation_mode,
        instrumentation_ab_seed=args.instrumentation_ab_seed,
        command_timeout_s=args.command_timeout_s,
        kill_timeout_s=args.kill_timeout_s,
        stop_wait_s=args.stop_wait_s,
        report_wait_s=args.report_wait_s,
        resource_sample_interval_ms=args.resource_sample_interval_ms,
        benchmark_id=args.benchmark_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        summary = run_startup_benchmark(_parse_args(argv))
    except StartupBenchmarkError as exc:
        print(f"startup benchmark refused/failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
