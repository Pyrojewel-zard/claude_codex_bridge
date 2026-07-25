#!/usr/bin/env python3
"""Privacy-safe Linux process resource sampling for performance harnesses.

The sampler is deliberately observational.  It reads ``/proc`` and owns only
the foreground command that the caller already intended to execute.  It never
persists argv, cwd, environment values, provider prompts, or raw procfs text.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:  # ``resource`` is unavailable on native Windows.
    import resource
except ImportError:  # pragma: no cover - exercised by cross-platform smoke.
    resource = None  # type: ignore[assignment]


RESOURCE_PROFILE_SCHEMA_VERSION = 1
RESOURCE_PROFILE_RECORD_TYPE = "ccb_startup_resource_profile_raw"
RESOURCE_BACKEND = "linux_procfs_v1"
DEFAULT_SAMPLE_INTERVAL_S = 0.05
_PROCESS_TERMINATE_GRACE_S = 0.25
_PROCESS_KILL_GRACE_S = 0.25
_MAX_STABLE_PROC_IO_HANDLES = 256
_IO_STABLE_HANDLE_STAT_KEYS = frozenset(
    {
        "io_stable_handle_open_count",
        "io_stable_handle_read_count",
        "io_stable_handle_read_failure_count",
        "io_stable_handle_reused_read_count",
        "io_stable_handle_open_failure_count",
        "io_stable_handle_limit_exceeded_count",
        "io_stable_handle_identity_mismatch_count",
        "io_stable_handle_prime_success_count",
        "io_stable_handle_prime_failure_count",
    }
)
_STARTUP_TRACE_ENV_KEYS = (
    "CCB_STARTUP_TIMING_TRACE",
    "CCB_STARTUP_TRACE_ID",
    "CCB_STARTUP_TRACE_SPAWN_NS",
    "CCB_STARTUP_TRACE_WRAPPER_ENTRY_NS",
    "CCB_STARTUP_TRACE_WRAPPER_PRE_EXEC_NS",
)
_KNOWN_PROVIDERS = (
    "codex",
    "claude",
    "gemini",
    "opencode",
    "droid",
    "agy",
    "kimi",
    "deepseek",
    "mimo",
    "qwen",
    "cursor",
    "copilot",
    "codebuddy",
    "crush",
    "grok",
    "kiro",
    "omp",
)

ProcessIdentity = tuple[int, int]


@dataclass(frozen=True)
class ProcessReading:
    pid: int
    ppid: int
    start_ticks: int
    user_ticks: int
    system_ticks: int
    rss_bytes: int
    read_bytes: int | None
    write_bytes: int | None
    rchar_bytes: int | None
    wchar_bytes: int | None
    syscr: int | None
    syscw: int | None
    bucket: str

    @property
    def identity(self) -> ProcessIdentity:
        return (self.pid, self.start_ticks)


@dataclass(frozen=True)
class ProcessSnapshot:
    monotonic_ns: int
    readings: tuple[ProcessReading, ...]
    scanned_pid_count: int
    vanished_process_count: int
    permission_error_count: int
    parse_error_count: int
    io_unavailable_count: int
    scan_wall_ns: int
    procfs_available: bool


@dataclass(frozen=True)
class ProfiledCommandOutcome:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    resource_profile: Mapping[str, Any]
    tracked_process_instances: tuple[ProcessIdentity, ...]
    active_process_instances: tuple[ProcessIdentity, ...]
    startup_timing_trace_id: str | None = None


@dataclass(frozen=True)
class TimedCommandOutcome:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    command_wall_ms: float


@dataclass(frozen=True)
class _ProcRecord:
    pid: int
    ppid: int
    start_ticks: int
    user_ticks: int
    system_ticks: int
    rss_bytes: int
    cwd_under_project: bool
    command_mentions_project: bool
    command_text: str
    executable_name: str

    @property
    def identity(self) -> ProcessIdentity:
        return (self.pid, self.start_ticks)


class _ProcIoHandleTracker:
    """Keep identity-validated proc I/O handles alive for one profile window.

    Linux denies a fresh open of ``/proc/<pid>/io`` after a process becomes a
    zombie even though ``stat`` remains readable until the parent reaps it.  A
    handle opened while the process is alive remains readable and exposes the
    final counters.  Keeping that handle avoids a torn stat-to-I/O snapshot
    without an extra I/O read or any persisted process text.
    """

    def __init__(self) -> None:
        self._handles: dict[ProcessIdentity, int] = {}
        self.open_count = 0
        self.read_count = 0
        self.read_failure_count = 0
        self.reused_read_count = 0
        self.open_failure_count = 0
        self.handle_limit_exceeded_count = 0
        self.identity_mismatch_count = 0
        self.prime_success_count = 0
        self.prime_failure_count = 0

    def prime_pid(self, pid: int) -> ProcessIdentity:
        """Open the foreground handle promptly and return its verified identity."""

        try:
            identity, _fd = self._open_validated(Path("/proc") / str(int(pid)))
        except BaseException:
            self.prime_failure_count += 1
            raise
        self.prime_success_count += 1
        return identity

    def read(self, pid_path: Path, identity: ProcessIdentity) -> dict[str, int]:
        fd = self._handles.get(identity)
        if fd is None:
            _opened_identity, fd = self._open_validated(
                pid_path,
                expected_identity=identity,
            )
        else:
            self.reused_read_count += 1
        try:
            values = _read_proc_io_fd(fd)
        except BaseException:
            self.read_failure_count += 1
            raise
        self.read_count += 1
        return values

    def ensure(self, pid_path: Path, identity: ProcessIdentity) -> None:
        """Acquire one validated handle before slower proc metadata reads."""

        if identity not in self._handles:
            self._open_validated(pid_path, expected_identity=identity)

    def statistics(self) -> dict[str, int]:
        return {
            "io_stable_handle_open_count": self.open_count,
            "io_stable_handle_read_count": self.read_count,
            "io_stable_handle_read_failure_count": self.read_failure_count,
            "io_stable_handle_reused_read_count": self.reused_read_count,
            "io_stable_handle_open_failure_count": self.open_failure_count,
            "io_stable_handle_limit_exceeded_count": self.handle_limit_exceeded_count,
            "io_stable_handle_identity_mismatch_count": self.identity_mismatch_count,
            "io_stable_handle_prime_success_count": self.prime_success_count,
            "io_stable_handle_prime_failure_count": self.prime_failure_count,
        }

    def close(self) -> None:
        handles, self._handles = self._handles, {}
        for fd in handles.values():
            with contextlib.suppress(OSError):
                os.close(fd)

    def _open_validated(
        self,
        pid_path: Path,
        *,
        expected_identity: ProcessIdentity | None = None,
    ) -> tuple[ProcessIdentity, int]:
        if expected_identity is not None:
            existing = self._handles.get(expected_identity)
            if existing is not None:
                return expected_identity, existing
        if len(self._handles) >= _MAX_STABLE_PROC_IO_HANDLES:
            self.open_failure_count += 1
            self.handle_limit_exceeded_count += 1
            raise OSError(
                errno.EMFILE,
                "stable proc I/O handle limit exceeded",
                os.fspath(pid_path),
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
        directory_fd: int | None = None
        stat_fd: int | None = None
        io_fd: int | None = None
        retained = False
        try:
            directory_fd = os.open(os.fspath(pid_path), directory_flags)
            io_fd = os.open("io", flags, dir_fd=directory_fd)
            stat_fd = os.open("stat", flags, dir_fd=directory_fd)
            stat_text = os.pread(stat_fd, 65536, 0).decode(
                "utf-8",
                errors="replace",
            )
            parsed = _parse_proc_stat(stat_text)
            identity = (parsed[0], parsed[4])
            if expected_identity is not None and identity != expected_identity:
                self.identity_mismatch_count += 1
                raise ProcessLookupError(
                    errno.ESRCH,
                    "proc identity changed while opening stable I/O handle",
                    os.fspath(pid_path),
                )
            existing = self._handles.get(identity)
            if existing is not None:
                return identity, existing
            self._handles[identity] = io_fd
            retained = True
            self.open_count += 1
            return identity, io_fd
        except BaseException:
            self.open_failure_count += 1
            raise
        finally:
            if stat_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(stat_fd)
            if io_fd is not None and not retained:
                with contextlib.suppress(OSError):
                    os.close(io_fd)
            if directory_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(directory_fd)


def run_profiled_command(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    *,
    sample_interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
    known_instances: Sequence[ProcessIdentity] = (),
    startup_timing_trace: bool = False,
    perf_counter_ns: Callable[[], int] = time.perf_counter_ns,
) -> ProfiledCommandOutcome:
    """Run one command while sampling its project-scoped process envelope."""

    command = tuple(str(item) for item in argv)
    interval_s = max(0.001, float(sample_interval_s))
    io_tracker = _ProcIoHandleTracker()
    try:
        snapshots: list[ProcessSnapshot] = []
        known: set[ProcessIdentity] = set(known_instances)
        observed: set[ProcessIdentity] = set()
        baseline = capture_project_snapshot(
            cwd,
            root_pid=None,
            known_instances=known,
            perf_counter_ns=perf_counter_ns,
            io_tracker=io_tracker,
        )
        snapshots.append(baseline)
        baseline_identities = {reading.identity for reading in baseline.readings}
        known.update(baseline_identities)
        observed.update(baseline_identities)
        rusage_before = _child_rusage_cpu_seconds()
        profile_started_ns = baseline.monotonic_ns
        spawn_begin_ns = perf_counter_ns()
        child_env = dict(env)
        for key in _STARTUP_TRACE_ENV_KEYS:
            child_env.pop(key, None)
        startup_timing_trace_id: str | None = None
        if startup_timing_trace:
            startup_timing_trace_id = f"trace_{uuid.uuid4().hex}"
            child_env["CCB_STARTUP_TIMING_TRACE"] = "1"
            child_env["CCB_STARTUP_TRACE_ID"] = startup_timing_trace_id
            child_env["CCB_STARTUP_TRACE_SPAWN_NS"] = str(spawn_begin_ns)
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except BaseException:
        io_tracker.close()
        raise
    timed_out = False
    stdout = ""
    stderr = ""
    partial_stdout = ""
    partial_stderr = ""
    try:
        with contextlib.suppress(
            FileNotFoundError,
            ProcessLookupError,
            PermissionError,
            OSError,
            ValueError,
            IndexError,
        ):
            io_tracker.prime_pid(process.pid)
        spawn_completed_ns = perf_counter_ns()
        deadline_ns = spawn_begin_ns + max(
            0,
            int(float(timeout_s) * 1_000_000_000),
        )

        def sample() -> None:
            snapshot = capture_project_snapshot(
                cwd,
                root_pid=process.pid,
                known_instances=known,
                perf_counter_ns=perf_counter_ns,
                io_tracker=io_tracker,
            )
            snapshots.append(snapshot)
            snapshot_identities = {reading.identity for reading in snapshot.readings}
            known.update(snapshot_identities)
            observed.update(snapshot_identities)

        sample()
        while True:
            remaining_s = (deadline_ns - perf_counter_ns()) / 1_000_000_000.0
            if remaining_s <= 0:
                timed_out = True
                stdout, stderr = _terminate_kill_reap_bounded(
                    process,
                    partial_stdout=partial_stdout,
                    partial_stderr=partial_stderr,
                )
                break
            try:
                stdout, stderr = process.communicate(
                    timeout=min(interval_s, remaining_s)
                )
                break
            except subprocess.TimeoutExpired as exc:
                partial_stdout = _updated_partial_output(partial_stdout, exc.stdout)
                partial_stderr = _updated_partial_output(partial_stderr, exc.stderr)
                sample()

        command_exited_ns = perf_counter_ns()
        sample()
        rusage_after = _child_rusage_cpu_seconds()
        profile_ended_ns = perf_counter_ns()
        rusage_delta = (
            max(0.0, rusage_after - rusage_before)
            if rusage_before is not None and rusage_after is not None
            else None
        )
        profile = aggregate_resource_snapshots(
            snapshots,
            sample_interval_s=interval_s,
            profile_started_ns=profile_started_ns,
            spawn_begin_ns=spawn_begin_ns,
            spawn_completed_ns=spawn_completed_ns,
            command_exited_ns=command_exited_ns,
            profile_ended_ns=profile_ended_ns,
            command_rusage_cpu_seconds=rusage_delta,
            io_handle_statistics=io_tracker.statistics(),
        )
    except BaseException:
        with contextlib.suppress(Exception):
            _terminate_kill_reap_bounded(
                process,
                partial_stdout=partial_stdout or stdout,
                partial_stderr=partial_stderr or stderr,
            )
        raise
    finally:
        io_tracker.close()
    return ProfiledCommandOutcome(
        argv=command,
        returncode=None if timed_out else int(process.returncode),
        stdout=str(stdout or ""),
        stderr=str(stderr or ""),
        timed_out=timed_out,
        resource_profile=profile,
        tracked_process_instances=tuple(sorted(observed)),
        active_process_instances=tuple(
            sorted(reading.identity for reading in snapshots[-1].readings)
        ),
        startup_timing_trace_id=startup_timing_trace_id,
    )


def run_timed_command(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    *,
    perf_counter_ns: Callable[[], int] = time.perf_counter_ns,
) -> TimedCommandOutcome:
    """Run the no-sampler A/B control with the same spawn-to-exit wall boundary."""

    command = tuple(str(item) for item in argv)
    child_env = dict(env)
    for key in _STARTUP_TRACE_ENV_KEYS:
        child_env.pop(key, None)
    spawn_begin_ns = perf_counter_ns()
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        try:
            stdout, stderr = process.communicate(timeout=max(0.0, float(timeout_s)))
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout, stderr = _terminate_kill_reap_bounded(
                process,
                partial_stdout=_updated_partial_output("", exc.stdout),
                partial_stderr=_updated_partial_output("", exc.stderr),
            )
    except BaseException:
        with contextlib.suppress(Exception):
            _terminate_kill_reap_bounded(
                process,
                partial_stdout=stdout,
                partial_stderr=stderr,
            )
        raise
    command_exited_ns = perf_counter_ns()
    return TimedCommandOutcome(
        argv=command,
        returncode=None if timed_out else int(process.returncode),
        stdout=str(stdout or ""),
        stderr=str(stderr or ""),
        timed_out=timed_out,
        command_wall_ms=max(0.0, (command_exited_ns - spawn_begin_ns) / 1_000_000.0),
    )


def capture_project_snapshot(
    project_root: Path,
    *,
    root_pid: int | None,
    known_instances: set[ProcessIdentity] | frozenset[ProcessIdentity],
    full_discovery: bool | None = None,
    perf_counter_ns: Callable[[], int] = time.perf_counter_ns,
    io_tracker: _ProcIoHandleTracker | None = None,
) -> ProcessSnapshot:
    """Capture a project-scoped snapshot without returning sensitive text."""

    started_ns = perf_counter_ns()
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return ProcessSnapshot(
            monotonic_ns=started_ns,
            readings=(),
            scanned_pid_count=0,
            vanished_process_count=0,
            permission_error_count=0,
            parse_error_count=0,
            io_unavailable_count=0,
            scan_wall_ns=max(0, perf_counter_ns() - started_ns),
            procfs_available=False,
        )

    page_size = _sysconf_positive("SC_PAGE_SIZE") or 1
    records: dict[int, _ProcRecord] = {}
    vanished = 0
    permission_errors = 0
    parse_errors = 0
    profile_pid = os.getpid()
    discover_all = (
        root_pid is None and not known_instances
        if full_discovery is None
        else bool(full_discovery)
    )
    authority_pids = _authority_seed_pids(project_root) if not discover_all else set()
    discovered_descendants: set[int] = set()
    if discover_all:
        try:
            candidate_pids = [
                int(path.name) for path in proc_root.iterdir() if path.name.isdigit()
            ]
        except OSError:
            candidate_pids = []
            permission_errors += 1
    else:
        candidate_pids = sorted(
            {
                *(pid for pid, _start_ticks in known_instances),
                *authority_pids,
                *(() if root_pid is None else (root_pid,)),
            }
        )
    pending = list(candidate_pids)
    attempted: set[int] = set()

    def observe_identity(pid_path: Path, identity: ProcessIdentity) -> None:
        if io_tracker is None or discover_all:
            return
        with contextlib.suppress(
            FileNotFoundError,
            ProcessLookupError,
            PermissionError,
            OSError,
            ValueError,
            IndexError,
        ):
            io_tracker.ensure(pid_path, identity)

    while pending:
        pid = pending.pop()
        if pid in attempted or pid == profile_pid or pid <= 0:
            continue
        attempted.add(pid)
        pid_path = proc_root / str(pid)
        try:
            record = _read_proc_record(
                pid_path,
                project_root=project_root,
                page_size=page_size,
                identity_observer=observe_identity,
            )
        except (FileNotFoundError, ProcessLookupError):
            vanished += 1
            continue
        except PermissionError:
            permission_errors += 1
            continue
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.ESRCH}:
                vanished += 1
            else:
                parse_errors += 1
            continue
        except (ValueError, IndexError):
            parse_errors += 1
            continue
        records[pid] = record
        if not discover_all:
            for child_pid in _read_child_pids(pid_path):
                if child_pid not in attempted:
                    discovered_descendants.add(child_pid)
                    pending.append(child_pid)

    related: set[int] = set()
    for pid, record in records.items():
        if (
            record.cwd_under_project
            or record.command_mentions_project
            or record.identity in known_instances
            or (root_pid is not None and pid == root_pid)
            or pid in discovered_descendants
        ):
            related.add(pid)
            continue
        if pid in authority_pids and (
            record.cwd_under_project or record.command_mentions_project
        ):
            related.add(pid)
    changed = True
    while changed:
        changed = False
        for pid, record in records.items():
            if pid not in related and record.ppid in related:
                related.add(pid)
                changed = True

    readings: list[ProcessReading] = []
    io_unavailable = 0
    for pid in _ordered_related_io_pids(
        related,
        root_pid=root_pid,
        discovered_descendants=discovered_descendants,
    ):
        record = records[pid]
        io_values: dict[str, int] | None
        try:
            io_values = (
                io_tracker.read(proc_root / str(pid), record.identity)
                if io_tracker is not None
                else _read_proc_io(proc_root / str(pid) / "io")
            )
        except FileNotFoundError:
            if _proc_identity_matches(
                proc_root / str(pid),
                record.identity,
            ):
                io_values = None
                io_unavailable += 1
            else:
                vanished += 1
                continue
        except ProcessLookupError:
            vanished += 1
            continue
        except PermissionError:
            io_values = None
            io_unavailable += 1
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.ESRCH}:
                vanished += 1
                continue
            io_values = None
            io_unavailable += 1
        except ValueError:
            io_values = None
            io_unavailable += 1
        readings.append(
            ProcessReading(
                pid=record.pid,
                ppid=record.ppid,
                start_ticks=record.start_ticks,
                user_ticks=record.user_ticks,
                system_ticks=record.system_ticks,
                rss_bytes=record.rss_bytes,
                read_bytes=_io_value(io_values, "read_bytes"),
                write_bytes=_io_value(io_values, "write_bytes"),
                rchar_bytes=_io_value(io_values, "rchar"),
                wchar_bytes=_io_value(io_values, "wchar"),
                syscr=_io_value(io_values, "syscr"),
                syscw=_io_value(io_values, "syscw"),
                bucket=_classify_process(record.command_text, record.executable_name),
            )
        )
    ended_ns = perf_counter_ns()
    return ProcessSnapshot(
        monotonic_ns=started_ns,
        readings=tuple(readings),
        scanned_pid_count=len(records),
        vanished_process_count=vanished,
        permission_error_count=permission_errors,
        parse_error_count=parse_errors,
        io_unavailable_count=io_unavailable,
        scan_wall_ns=max(0, ended_ns - started_ns),
        procfs_available=True,
    )


def aggregate_resource_snapshots(
    snapshots: Sequence[ProcessSnapshot],
    *,
    sample_interval_s: float,
    profile_started_ns: int,
    spawn_begin_ns: int,
    spawn_completed_ns: int,
    command_exited_ns: int,
    profile_ended_ns: int,
    command_rusage_cpu_seconds: float | None,
    io_handle_statistics: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Aggregate snapshots into a redacted, versioned resource envelope."""

    clock_ticks = _sysconf_positive("SC_CLK_TCK")
    ordered = list(snapshots)
    monotonic_valid = all(
        left.monotonic_ns <= right.monotonic_ns for left, right in zip(ordered, ordered[1:])
    )
    profile_timestamps = (
        profile_started_ns,
        spawn_begin_ns,
        spawn_completed_ns,
        command_exited_ns,
        profile_ended_ns,
    )
    profile_timestamps_valid = all(
        left <= right
        for left, right in zip(profile_timestamps, profile_timestamps[1:])
    )
    samples_within_profile_window = all(
        profile_started_ns <= sample.monotonic_ns <= profile_ended_ns
        for sample in ordered
    )
    procfs_available = bool(ordered) and all(sample.procfs_available for sample in ordered)
    permission_errors = sum(sample.permission_error_count for sample in ordered)
    parse_errors = sum(sample.parse_error_count for sample in ordered)
    io_unavailable = sum(sample.io_unavailable_count for sample in ordered)
    status = "complete"
    reason_codes: list[str] = []
    if not procfs_available or clock_ticks is None or len(ordered) < 2:
        status = "unavailable"
        if not procfs_available:
            reason_codes.append("procfs_unavailable")
        if clock_ticks is None:
            reason_codes.append("clock_ticks_unavailable")
        if len(ordered) < 2:
            reason_codes.append("insufficient_samples")
    if not monotonic_valid:
        status = "unavailable"
        reason_codes.append("non_monotonic_samples")
    if not profile_timestamps_valid:
        status = "unavailable"
        reason_codes.append("non_monotonic_profile_timestamps")
    if not samples_within_profile_window:
        status = "unavailable"
        reason_codes.append("samples_outside_profile_window")
    if status != "unavailable" and (permission_errors or parse_errors):
        status = "degraded"
        if permission_errors:
            reason_codes.append("proc_permission_errors")
        if parse_errors:
            reason_codes.append("proc_parse_errors")

    last_seen: dict[ProcessIdentity, ProcessReading] = {}
    last_seen_sample_index: dict[ProcessIdentity, int] = {}
    last_valid_io: dict[tuple[ProcessIdentity, str], int] = {}
    io_open_gaps: set[tuple[ProcessIdentity, str]] = set()
    io_irrecoverable_gaps: set[tuple[ProcessIdentity, str]] = set()
    io_baseline_gaps: set[tuple[ProcessIdentity, str]] = set()
    io_regression_gaps: set[tuple[ProcessIdentity, str]] = set()
    io_recovered_gap_count = 0
    io_counter_regression_count = 0
    baseline_identities: set[ProcessIdentity] = set()
    all_identities: set[ProcessIdentity] = set()
    buckets: dict[str, dict[str, Any]] = {}
    time_series: list[dict[str, Any]] = []
    total_cpu_ticks = 0
    io_totals = {key: 0 for key in ("read_bytes", "write_bytes", "rchar_bytes", "wchar_bytes", "syscr", "syscw")}
    baseline_rss = 0
    peak_rss = 0
    end_rss = 0
    baseline_count = 0
    peak_count = 0
    end_count = 0
    identity_gap_event_count = 0
    identity_gap_missing_sample_count = 0

    for sample_index, sample in enumerate(ordered):
        current = {reading.identity: reading for reading in sample.readings}
        if sample_index == 0:
            baseline_identities = set(current)
            baseline_rss = sum(reading.rss_bytes for reading in current.values())
            baseline_count = len(current)
        all_identities.update(current)
        rss_total = sum(reading.rss_bytes for reading in current.values())
        peak_rss = max(peak_rss, rss_total)
        peak_count = max(peak_count, len(current))
        end_rss = rss_total
        end_count = len(current)
        sample_cpu_ticks = 0
        sample_io = {key: 0 for key in io_totals}
        for identity, reading in current.items():
            prior = last_seen.get(identity)
            prior_sample_index = last_seen_sample_index.get(identity)
            if (
                prior is not None
                and prior_sample_index is not None
                and prior_sample_index < sample_index - 1
            ):
                identity_gap_event_count += 1
                identity_gap_missing_sample_count += sample_index - prior_sample_index - 1
            is_new_after_baseline = sample_index > 0 and identity not in baseline_identities and prior is None
            user_delta = _counter_delta(
                reading.user_ticks,
                prior.user_ticks if prior is not None else (0 if is_new_after_baseline else None),
            )
            system_delta = _counter_delta(
                reading.system_ticks,
                prior.system_ticks if prior is not None else (0 if is_new_after_baseline else None),
            )
            cpu_delta = user_delta + system_delta
            sample_cpu_ticks += cpu_delta
            bucket = buckets.setdefault(reading.bucket, _empty_bucket())
            bucket["cpu_ticks_delta"] += cpu_delta
            bucket["sampled_peak_rss_bytes"] = max(
                int(bucket["sampled_peak_rss_bytes"]),
                sum(item.rss_bytes for item in current.values() if item.bucket == reading.bucket),
            )
            bucket["sampled_peak_process_count"] = max(
                int(bucket["sampled_peak_process_count"]),
                sum(1 for item in current.values() if item.bucket == reading.bucket),
            )
            bucket.setdefault("_identities", set()).add(identity)
            for field in sample_io:
                current_value = getattr(reading, field)
                io_key = (identity, field)
                if current_value is None:
                    if sample_index == 0 and identity in baseline_identities:
                        io_irrecoverable_gaps.add(io_key)
                        io_baseline_gaps.add(io_key)
                    else:
                        io_open_gaps.add(io_key)
                    continue
                prior_value = last_valid_io.get(io_key)
                if prior_value is None:
                    if identity in baseline_identities:
                        last_valid_io[io_key] = current_value
                        continue
                    prior_value = 0
                if current_value < prior_value:
                    io_counter_regression_count += 1
                    io_irrecoverable_gaps.add(io_key)
                    io_regression_gaps.add(io_key)
                    io_open_gaps.discard(io_key)
                    last_valid_io[io_key] = current_value
                    continue
                delta = current_value - prior_value
                sample_io[field] += delta
                bucket["io"][field] += delta
                last_valid_io[io_key] = current_value
                if io_key in io_open_gaps:
                    io_open_gaps.remove(io_key)
                    io_recovered_gap_count += 1
            last_seen[identity] = reading
            last_seen_sample_index[identity] = sample_index
        total_cpu_ticks += sample_cpu_ticks
        for field, amount in sample_io.items():
            io_totals[field] += amount
        time_series.append(
            {
                "offset_ms": round(
                    (sample.monotonic_ns - profile_started_ns) / 1_000_000.0,
                    6,
                ),
                "process_count": len(current),
                "rss_bytes": rss_total,
                "cpu_ticks_delta": sample_cpu_ticks,
                "read_bytes_delta": sample_io["read_bytes"],
                "write_bytes_delta": sample_io["write_bytes"],
                "io_unavailable_event_count": sample.io_unavailable_count,
            }
        )
    for payload in buckets.values():
        identities = payload.pop("_identities", set())
        payload["unique_process_instance_count"] = len(identities)
        payload["cpu_seconds"] = (
            round(payload["cpu_ticks_delta"] / clock_ticks, 9) if clock_ticks else None
        )
    gaps_ns = [
        right.monotonic_ns - left.monotonic_ns for left, right in zip(ordered, ordered[1:])
    ]
    # The first snapshot is a pre-spawn full-discovery baseline.  Its scan is
    # intentionally outside the measured command wall and therefore is not a
    # sampler scheduling deadline.
    scheduled_gaps_ns = gaps_ns[1:] if gaps_ns else []
    target_gap_ns = max(1, int(float(sample_interval_s) * 1_000_000_000))
    deadline_misses = sum(1 for gap in scheduled_gaps_ns if gap > target_gap_ns * 2)
    if identity_gap_event_count:
        if status != "unavailable":
            status = "degraded"
        reason_codes.append("process_identity_sample_gap")
    unresolved_io_gaps = io_open_gaps | io_irrecoverable_gaps
    unresolved_io_identities = {identity for identity, _field in unresolved_io_gaps}
    # Keep the persisted diagnosis privacy-safe while making every unresolved
    # identity-field gap attributable.  These four sets are deliberately
    # disjoint, so their counts sum to ``io_unresolved_gap_count``.
    unresolved_baseline_gaps = unresolved_io_gaps & io_baseline_gaps
    unresolved_regression_gaps = (
        unresolved_io_gaps - unresolved_baseline_gaps
    ) & io_regression_gaps
    unresolved_without_fixed_cause = (
        unresolved_io_gaps
        - unresolved_baseline_gaps
        - unresolved_regression_gaps
    )
    unresolved_never_valid_gaps = {
        io_key
        for io_key in unresolved_without_fixed_cause
        if io_key not in last_valid_io
    }
    unresolved_terminal_gaps = (
        unresolved_without_fixed_cause - unresolved_never_valid_gaps
    )
    if unresolved_io_gaps:
        if status != "unavailable":
            status = "degraded"
        reason_codes.append("process_io_partial")
    if status == "complete" and deadline_misses:
        status = "degraded"
        reason_codes.append("sampling_deadline_missed")
    last_sample_ns = ordered[-1].monotonic_ns if ordered else profile_ended_ns
    return {
        "schema_version": RESOURCE_PROFILE_SCHEMA_VERSION,
        "record_type": RESOURCE_PROFILE_RECORD_TYPE,
        "profile_id": f"rprof_{uuid.uuid4().hex}",
        "status": status,
        "reason_codes": sorted(set(reason_codes)),
        "backend": RESOURCE_BACKEND,
        "privacy": {
            "policy": "aggregate_no_sensitive_proc_text_v1",
            "argv_persisted": False,
            "cwd_persisted": False,
            "environment_persisted": False,
            "raw_proc_text_persisted": False,
        },
        "capabilities": {
            "process_identity": "available" if procfs_available else "unavailable",
            "ancestry": "available" if procfs_available else "unavailable",
            "cpu_ticks": "available" if clock_ticks else "unavailable",
            "rss": "available" if procfs_available else "unavailable",
            "process_io": (
                "unavailable"
                if not procfs_available
                else ("partial" if unresolved_io_gaps else "available")
            ),
            "command_rusage": "available" if command_rusage_cpu_seconds is not None else "unavailable",
        },
        "window": {
            "clock": "perf_counter_ns",
            "profile_duration_ms": round(
                (profile_ended_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
            "command_wall_ms": round(
                (command_exited_ns - spawn_begin_ns) / 1_000_000.0,
                6,
            ),
            "spawn_begin_offset_ms": round(
                (spawn_begin_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
            "spawn_completed_offset_ms": round(
                (spawn_completed_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
            "command_exit_offset_ms": round(
                (command_exited_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
            "profile_end_offset_ms": round(
                (profile_ended_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
            "last_sample_offset_ms": round(
                (last_sample_ns - profile_started_ns) / 1_000_000.0,
                6,
            ),
        },
        "sampler": {
            "target_interval_ms": round(float(sample_interval_s) * 1000.0, 6),
            "sample_count": len(ordered),
            "max_gap_ms": round(max(scheduled_gaps_ns, default=0) / 1_000_000.0, 6),
            "deadline_miss_count": deadline_misses,
            "identity_gap_event_count": identity_gap_event_count,
            "identity_gap_missing_sample_count": identity_gap_missing_sample_count,
            "scan_wall_ms_total": round(sum(sample.scan_wall_ns for sample in ordered) / 1_000_000.0, 6),
            "scan_wall_ms_max": round(max((sample.scan_wall_ns for sample in ordered), default=0) / 1_000_000.0, 6),
            "baseline_scan_wall_ms": round(
                (ordered[0].scan_wall_ns if ordered else 0) / 1_000_000.0,
                6,
            ),
            "command_window_scan_wall_ms_total": round(
                sum(sample.scan_wall_ns for sample in ordered[1:]) / 1_000_000.0,
                6,
            ),
            "command_window_scan_wall_ms_max": round(
                max((sample.scan_wall_ns for sample in ordered[1:]), default=0)
                / 1_000_000.0,
                6,
            ),
            "scanned_pid_count_max": max((sample.scanned_pid_count for sample in ordered), default=0),
            "vanished_process_count": sum(sample.vanished_process_count for sample in ordered),
            "permission_error_count": permission_errors,
            "parse_error_count": parse_errors,
            "io_unavailable_count": io_unavailable,
            "io_unavailable_event_count": io_unavailable,
            "io_recovered_gap_count": io_recovered_gap_count,
            "io_unresolved_gap_count": len(unresolved_io_gaps),
            "io_unresolved_identity_count": len(unresolved_io_identities),
            "io_unresolved_baseline_gap_count": len(unresolved_baseline_gaps),
            "io_unresolved_terminal_gap_count": len(unresolved_terminal_gaps),
            "io_unresolved_never_valid_gap_count": len(unresolved_never_valid_gaps),
            "io_unresolved_regression_gap_count": len(unresolved_regression_gaps),
            "io_counter_regression_count": io_counter_regression_count,
            **{
                str(key): max(0, int(value))
                for key, value in (io_handle_statistics or {}).items()
                if str(key) in _IO_STABLE_HANDLE_STAT_KEYS
            },
        },
        "metrics": {
            "cpu_ticks_delta": total_cpu_ticks,
            "clock_ticks_per_second": clock_ticks,
            "sampled_process_tree_cpu_seconds": (
                round(total_cpu_ticks / clock_ticks, 9) if clock_ticks else None
            ),
            "command_rusage_cpu_seconds": (
                round(command_rusage_cpu_seconds, 9)
                if command_rusage_cpu_seconds is not None
                else None
            ),
            "cpu_completeness": "sampled_lower_bound",
            "baseline_rss_bytes": baseline_rss,
            "sampled_peak_rss_bytes": peak_rss,
            "end_rss_bytes": end_rss,
            "peak_rss_delta_from_baseline_bytes": max(0, peak_rss - baseline_rss),
            "baseline_process_count": baseline_count,
            "sampled_peak_process_count": peak_count,
            "end_process_count": end_count,
            "unique_process_instance_count": len(all_identities),
            "created_process_instance_count": len(all_identities - baseline_identities),
            "io": io_totals,
            "io_completeness": "partial" if unresolved_io_gaps else "sampled_lower_bound",
        },
        "buckets": dict(sorted(buckets.items())),
        "samples": time_series,
    }


def capture_cleanup_resource_audit(
    project_root: Path,
    *,
    known_instances: set[ProcessIdentity] | frozenset[ProcessIdentity],
    sample_interval_s: float,
    max_samples: int = 4,
    required_consecutive_clean: int = 2,
    perf_counter_ns: Callable[[], int] = time.perf_counter_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Observe post-control-plane process residue with a bounded settle window."""

    samples: list[dict[str, Any]] = []
    consecutive_clean = 0
    status = "degraded"
    for index in range(max(1, max_samples)):
        snapshot = capture_project_snapshot(
            project_root,
            root_pid=None,
            known_instances=known_instances,
            full_discovery=True,
            perf_counter_ns=perf_counter_ns,
        )
        bucket_counts: dict[str, int] = {}
        for reading in snapshot.readings:
            bucket_counts[reading.bucket] = bucket_counts.get(reading.bucket, 0) + 1
        clean = snapshot.procfs_available and not snapshot.readings
        consecutive_clean = consecutive_clean + 1 if clean else 0
        samples.append(
            {
                "index": index,
                "process_count": len(snapshot.readings),
                "bucket_counts": dict(sorted(bucket_counts.items())),
                "procfs_available": snapshot.procfs_available,
                "permission_error_count": snapshot.permission_error_count,
                "parse_error_count": snapshot.parse_error_count,
                "vanished_process_count": snapshot.vanished_process_count,
            }
        )
        if consecutive_clean >= required_consecutive_clean:
            status = "clean"
            break
        if index + 1 < max_samples:
            sleep(max(0.0, float(sample_interval_s)))
    if status != "clean":
        if samples and all(sample["procfs_available"] for sample in samples):
            status = "residue" if samples[-1]["process_count"] else "degraded"
    return {
        "schema_version": RESOURCE_PROFILE_SCHEMA_VERSION,
        "record_type": "ccb_startup_cleanup_resource_audit_raw",
        "status": status,
        "backend": RESOURCE_BACKEND,
        "required_consecutive_clean_snapshots": required_consecutive_clean,
        "consecutive_clean_snapshots": consecutive_clean,
        "sample_interval_ms": round(float(sample_interval_s) * 1000.0, 6),
        "known_process_instance_count": len(known_instances),
        "samples": samples,
        "privacy": {
            "argv_persisted": False,
            "cwd_persisted": False,
            "environment_persisted": False,
            "raw_proc_text_persisted": False,
        },
    }


def _authority_seed_pids(project_root: Path) -> set[int]:
    ccb_root = project_root / ".ccb"
    paths = [
        ccb_root / "ccbd" / "lease.json",
        ccb_root / "ccbd" / "lifecycle.json",
    ]
    agents_root = ccb_root / "agents"
    with contextlib.suppress(OSError):
        paths.extend(path for path in agents_root.glob("*/runtime.json"))
    allowed_fields = {
        "pid",
        "ccbd_pid",
        "keeper_pid",
        "runtime_pid",
        "provider_pid",
        "helper_pid",
        "sidebar_pid",
        "process_pid",
    }
    pids: set[int] = set()
    for path in paths:
        try:
            if path.stat().st_size > 1_048_576:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        for key, value in payload.items():
            if key not in allowed_fields or isinstance(value, bool):
                continue
            try:
                pid = int(value)
            except (TypeError, ValueError):
                continue
            if pid > 0:
                pids.add(pid)
    return pids


def _ordered_related_io_pids(
    related: set[int],
    *,
    root_pid: int | None,
    discovered_descendants: set[int],
) -> tuple[int, ...]:
    """Read short-lived foreground identities before persistent project peers."""

    return tuple(
        sorted(
            related,
            key=lambda pid: (
                0
                if root_pid is not None and pid == root_pid
                else (1 if pid in discovered_descendants else 2),
                pid,
            ),
        )
    )


def _read_child_pids(pid_path: Path) -> tuple[int, ...]:
    path = pid_path / "task" / pid_path.name / "children"
    try:
        values = path.read_text(encoding="ascii", errors="strict").split()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError, UnicodeDecodeError):
        return ()
    children: list[int] = []
    for raw in values:
        with contextlib.suppress(ValueError):
            child = int(raw)
            if child > 0:
                children.append(child)
    return tuple(children)


def _read_proc_record(
    pid_path: Path,
    *,
    project_root: Path,
    page_size: int,
    identity_observer: Callable[[Path, ProcessIdentity], None] | None = None,
) -> _ProcRecord:
    stat_text = (pid_path / "stat").read_text(encoding="utf-8", errors="replace")
    pid, ppid, user_ticks, system_ticks, start_ticks, rss_pages = _parse_proc_stat(stat_text)
    if identity_observer is not None:
        identity_observer(pid_path, (pid, start_ticks))
    command_bytes = (pid_path / "cmdline").read_bytes()[:65536]
    command_text = command_bytes.replace(b"\0", b" ").decode("utf-8", errors="replace")
    executable_name = ""
    with contextlib.suppress(OSError):
        executable_name = Path(os.readlink(pid_path / "exe")).name
    cwd_under_project = False
    with contextlib.suppress(OSError, ValueError):
        cwd_under_project = _path_is_under(Path(os.readlink(pid_path / "cwd")), project_root)
    project_marker = os.fsencode(str(project_root))
    command_mentions_project = bool(project_marker and project_marker in command_bytes)
    return _ProcRecord(
        pid=pid,
        ppid=ppid,
        start_ticks=start_ticks,
        user_ticks=user_ticks,
        system_ticks=system_ticks,
        rss_bytes=max(0, rss_pages) * page_size,
        cwd_under_project=cwd_under_project,
        command_mentions_project=command_mentions_project,
        command_text=command_text,
        executable_name=executable_name,
    )


def _proc_identity_matches(
    pid_path: Path,
    expected_identity: ProcessIdentity,
) -> bool:
    try:
        stat_text = (pid_path / "stat").read_text(
            encoding="utf-8",
            errors="replace",
        )
        pid, _ppid, _user, _system, start_ticks, _rss = _parse_proc_stat(
            stat_text
        )
    except (OSError, ValueError):
        return False
    return (pid, start_ticks) == expected_identity


def _parse_proc_stat(value: str) -> tuple[int, int, int, int, int, int]:
    left = value.find("(")
    right = value.rfind(")")
    if left <= 0 or right <= left:
        raise ValueError("malformed proc stat")
    pid = int(value[:left].strip())
    fields = value[right + 1 :].strip().split()
    if len(fields) < 22:
        raise ValueError("truncated proc stat")
    return (
        pid,
        int(fields[1]),
        int(fields[11]),
        int(fields[12]),
        int(fields[19]),
        int(fields[21]),
    )


def _read_proc_io(path: Path) -> dict[str, int]:
    return _parse_proc_io_text(path.read_text(encoding="utf-8", errors="strict"))


def _read_proc_io_fd(fd: int) -> dict[str, int]:
    try:
        payload = os.pread(int(fd), 65536, 0)
    except AttributeError as exc:  # pragma: no cover - native Windows lacks procfs.
        raise OSError(errno.ENOSYS, "pread is unavailable") from exc
    return _parse_proc_io_text(payload.decode("utf-8", errors="strict"))


def _parse_proc_io_text(value: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in value.splitlines():
        name, separator, raw = line.partition(":")
        if separator:
            values[name.strip()] = int(raw.strip())
    return values


def _io_value(values: Mapping[str, int] | None, key: str) -> int | None:
    if values is None:
        return None
    value = values.get(key)
    return int(value) if value is not None else None


def _counter_delta(current: int, previous: int | None) -> int:
    if previous is None or current < previous:
        return 0
    return current - previous


def _terminate_kill_reap_bounded(
    process: subprocess.Popen[str],
    *,
    partial_stdout: str = "",
    partial_stderr: str = "",
) -> tuple[str, str]:
    """Bound cleanup to the foreground process even when descendants own its pipes."""

    stdout = partial_stdout
    stderr = partial_stderr
    try:
        running = process.poll() is None
    except (OSError, ValueError):
        running = True
    if running:
        with contextlib.suppress(OSError, ValueError):
            process.terminate()
        try:
            completed_stdout, completed_stderr = process.communicate(
                timeout=_PROCESS_TERMINATE_GRACE_S
            )
            stdout = _updated_partial_output(stdout, completed_stdout)
            stderr = _updated_partial_output(stderr, completed_stderr)
        except subprocess.TimeoutExpired as exc:
            stdout = _updated_partial_output(stdout, exc.stdout)
            stderr = _updated_partial_output(stderr, exc.stderr)
        except (OSError, ValueError):
            pass
        try:
            running = process.poll() is None
        except (OSError, ValueError):
            running = True
        if running:
            with contextlib.suppress(OSError, ValueError):
                process.kill()
            try:
                process.wait(timeout=_PROCESS_KILL_GRACE_S)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            with contextlib.suppress(OSError, ValueError):
                pipe.close()
    return stdout, stderr


def _updated_partial_output(previous: str, value: str | bytes | None) -> str:
    if value is None:
        return previous
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _optional_counter_delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None or current < previous:
        return None
    return current - previous


def _empty_bucket() -> dict[str, Any]:
    return {
        "cpu_ticks_delta": 0,
        "cpu_seconds": None,
        "sampled_peak_rss_bytes": 0,
        "sampled_peak_process_count": 0,
        "unique_process_instance_count": 0,
        "io": {
            "read_bytes": 0,
            "write_bytes": 0,
            "rchar_bytes": 0,
            "wchar_bytes": 0,
            "syscr": 0,
            "syscw": 0,
        },
    }


def _classify_process(command: str, executable_name: str) -> str:
    text = str(command or "").lower()
    executable = str(executable_name or "").lower()
    if "ccbd/keeper_main.py" in text or "keeper_main.py" in text:
        return "ccb/keeper"
    if "/ccbd/main.py" in text or "lib/ccbd/main.py" in text:
        return "ccb/ccbd"
    if "ccbd/sidebar" in text or "sidecar_sidebar" in text or "sidecar-sidebar" in text:
        return "ccb/sidebar"
    if executable.startswith("tmux") or "tmux: server" in text:
        return "tmux/server"
    for provider in _KNOWN_PROVIDERS:
        if executable == provider or f"/{provider}/" in text or f" --provider {provider}" in text:
            return f"provider/{provider}"
    if "ccb_test" in text or " ccb " in f" {text} ":
        return "command/ccb_test"
    if executable in {"sh", "bash", "zsh", "fish"} or " -lc " in f" {text} ":
        return "shell/wrapper"
    return "other/project"


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path_text = os.path.realpath(os.fspath(path))
        root_text = os.path.realpath(os.fspath(root))
        return os.path.commonpath((path_text, root_text)) == root_text
    except (OSError, ValueError):
        return False


def _sysconf_positive(name: str) -> int | None:
    try:
        value = int(os.sysconf(name))
    except (AttributeError, OSError, ValueError):
        return None
    return value if value > 0 else None


def _child_rusage_cpu_seconds() -> float | None:
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (AttributeError, OSError, ValueError):
        return None
    return float(usage.ru_utime) + float(usage.ru_stime)


__all__ = [
    "DEFAULT_SAMPLE_INTERVAL_S",
    "ProcessIdentity",
    "ProcessReading",
    "ProcessSnapshot",
    "ProfiledCommandOutcome",
    "TimedCommandOutcome",
    "aggregate_resource_snapshots",
    "capture_cleanup_resource_audit",
    "capture_project_snapshot",
    "run_profiled_command",
    "run_timed_command",
]
