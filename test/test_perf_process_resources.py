from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "dev_tools" / "perf_process_resources.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("perf_process_resources_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reading(runner, *, pid: int, start: int, user: int, system: int, rss: int, io: int | None):
    return runner.ProcessReading(
        pid=pid,
        ppid=1,
        start_ticks=start,
        user_ticks=user,
        system_ticks=system,
        rss_bytes=rss,
        read_bytes=io,
        write_bytes=io,
        rchar_bytes=io,
        wchar_bytes=io,
        syscr=io,
        syscw=io,
        bucket="other/project",
    )


def _snapshot(runner, timestamp: int, *readings, io_unavailable_count: int = 0):
    return runner.ProcessSnapshot(
        monotonic_ns=timestamp,
        readings=tuple(readings),
        scanned_pid_count=len(readings),
        vanished_process_count=0,
        permission_error_count=0,
        parse_error_count=0,
        io_unavailable_count=io_unavailable_count,
        scan_wall_ns=100,
        procfs_available=True,
    )


class _FakePipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _HangingForegroundProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode = None
        self.stdout = _FakePipe()
        self.stderr = _FakePipe()
        self.terminate_calls = 0
        self.kill_calls = 0
        self.communicate_timeouts: list[float | None] = []
        self.wait_timeouts: list[float | None] = []

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        raise subprocess.TimeoutExpired(
            "fake-foreground",
            timeout,
            output=b"partial-out",
            stderr=b"partial-err",
        )

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        self.returncode = -9
        return self.returncode


def test_parse_proc_stat_handles_spaces_and_parentheses_in_comm() -> None:
    runner = _load_runner()
    fields = ["S", "7", *(["0"] * 9), "11", "5", *(["0"] * 6), "1234", "0", "3"]

    parsed = runner._parse_proc_stat(f"42 (worker ) name) {' '.join(fields)}")

    assert parsed == (42, 7, 11, 5, 1234, 3)


def test_proc_record_announces_identity_before_later_metadata_read(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    pid_path = tmp_path / "42"
    pid_path.mkdir()
    fields = ["S", "7", *(["0"] * 9), "11", "5", *(["0"] * 6), "1234", "0", "3"]
    (pid_path / "stat").write_text(
        f"42 (short lived) {' '.join(fields)}",
        encoding="utf-8",
    )
    observed = []

    with pytest.raises(FileNotFoundError):
        runner._read_proc_record(
            pid_path,
            project_root=tmp_path,
            page_size=4096,
            identity_observer=lambda path, identity: observed.append((path, identity)),
        )

    assert observed == [(pid_path, (42, 1234))]


def test_related_io_reads_prioritize_foreground_root_then_descendants() -> None:
    runner = _load_runner()

    ordered = runner._ordered_related_io_pids(
        {4, 5, 7, 9},
        root_pid=7,
        discovered_descendants={5, 9},
    )

    assert ordered == (7, 5, 9, 4)


def test_stable_proc_io_handle_survives_path_disappearance(tmp_path: Path) -> None:
    runner = _load_runner()
    pid_path = tmp_path / "42"
    pid_path.mkdir()
    fields = ["S", "1", *(["0"] * 9), "1", "1", *(["0"] * 6), "1234", "0", "1"]
    (pid_path / "stat").write_text(
        f"42 (short lived) {' '.join(fields)}",
        encoding="utf-8",
    )
    io_path = pid_path / "io"
    io_path.write_text(
        "rchar: 10\nwchar: 20\nsyscr: 1\nsyscw: 2\n"
        "read_bytes: 30\nwrite_bytes: 40\n",
        encoding="utf-8",
    )
    tracker = runner._ProcIoHandleTracker()
    try:
        assert tracker.read(pid_path, (42, 1234))["write_bytes"] == 40
        assert os.get_inheritable(next(iter(tracker._handles.values()))) is False
        io_path.write_text(
            "rchar: 11\nwchar: 22\nsyscr: 2\nsyscw: 3\n"
            "read_bytes: 33\nwrite_bytes: 44\n",
            encoding="utf-8",
        )
        io_path.unlink()

        with pytest.raises(FileNotFoundError):
            runner._read_proc_io(io_path)
        assert tracker.read(pid_path, (42, 1234))["write_bytes"] == 44
        assert tracker.statistics()["io_stable_handle_open_count"] == 1
        assert tracker.statistics()["io_stable_handle_reused_read_count"] == 1
    finally:
        tracker.close()


def test_stable_proc_io_handle_rejects_pid_reuse_identity(tmp_path: Path) -> None:
    runner = _load_runner()
    pid_path = tmp_path / "42"
    pid_path.mkdir()
    fields = ["S", "1", *(["0"] * 9), "1", "1", *(["0"] * 6), "9999", "0", "1"]
    (pid_path / "stat").write_text(
        f"42 (reused) {' '.join(fields)}",
        encoding="utf-8",
    )
    (pid_path / "io").write_text("read_bytes: 1\n", encoding="utf-8")
    tracker = runner._ProcIoHandleTracker()
    try:
        with pytest.raises(ProcessLookupError, match="identity changed"):
            tracker.read(pid_path, (42, 1234))
        stats = tracker.statistics()
        assert stats["io_stable_handle_open_count"] == 0
        assert stats["io_stable_handle_identity_mismatch_count"] == 1
    finally:
        tracker.close()


def test_stable_proc_io_handle_limit_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "_MAX_STABLE_PROC_IO_HANDLES", 0)
    tracker = runner._ProcIoHandleTracker()
    try:
        with pytest.raises(OSError, match="handle limit exceeded"):
            tracker.read(tmp_path / "42", (42, 1234))
        stats = tracker.statistics()
        assert stats["io_stable_handle_open_failure_count"] == 1
        assert stats["io_stable_handle_limit_exceeded_count"] == 1
    finally:
        tracker.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "pread"),
    reason="requires Linux procfs stable-handle semantics",
)
def test_stable_proc_io_handle_reads_a_reaped_pending_zombie() -> None:
    runner = _load_runner()
    tracker = runner._ProcIoHandleTracker()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; time.sleep(0.5); os.write(1, b'x')",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not Path(f"/proc/{process.pid}/io").is_file():
            pytest.skip("kernel does not expose child procfs I/O counters")
        identity = tracker.prime_pid(process.pid)
        deadline = time.monotonic() + 2.0
        state = ""
        while time.monotonic() < deadline:
            stat_text = Path(f"/proc/{process.pid}/stat").read_text(encoding="utf-8")
            state = stat_text[stat_text.rfind(")") + 1 :].strip().split()[0]
            if state == "Z":
                break
            time.sleep(0.005)
        assert state == "Z"

        values = tracker.read(Path(f"/proc/{process.pid}"), identity)
        assert values["wchar"] >= 1
        assert values["syscw"] >= 1
    finally:
        tracker.close()
        process.wait(timeout=2.0)


def test_aggregate_uses_window_deltas_and_pid_starttime_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "_sysconf_positive", lambda name: 100 if name == "SC_CLK_TCK" else 4096)
    snapshots = [
        _snapshot(runner, 0, _reading(runner, pid=10, start=100, user=100, system=50, rss=100, io=100)),
        _snapshot(
            runner,
            10_000_000,
            _reading(runner, pid=10, start=100, user=110, system=55, rss=120, io=130),
            _reading(runner, pid=11, start=200, user=3, system=2, rss=80, io=20),
        ),
        _snapshot(
            runner,
            20_000_000,
            _reading(runner, pid=10, start=999, user=1, system=0, rss=90, io=5),
        ),
    ]

    profile = runner.aggregate_resource_snapshots(
        snapshots,
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=20_000_000,
        profile_ended_ns=20_000_001,
        command_rusage_cpu_seconds=0.5,
    )

    assert profile["status"] == "complete"
    assert profile["metrics"]["cpu_ticks_delta"] == 21
    assert profile["metrics"]["sampled_process_tree_cpu_seconds"] == pytest.approx(0.21)
    assert profile["metrics"]["unique_process_instance_count"] == 3
    assert profile["metrics"]["created_process_instance_count"] == 2
    assert profile["metrics"]["sampled_peak_rss_bytes"] == 200
    assert profile["metrics"]["sampled_peak_process_count"] == 2
    assert profile["metrics"]["io"]["read_bytes"] == 55


@pytest.mark.parametrize(
    "timestamps",
    (
        (20_000_000, 10_000_000, 30_000_000, 40_000_000, 50_000_000),
        (10_000_000, 30_000_000, 20_000_000, 40_000_000, 50_000_000),
        (10_000_000, 20_000_000, 40_000_000, 30_000_000, 50_000_000),
        (10_000_000, 20_000_000, 30_000_000, 50_000_000, 40_000_000),
    ),
)
def test_aggregate_fails_closed_on_reversed_profile_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    timestamps: tuple[int, int, int, int, int],
) -> None:
    runner = _load_runner()
    (
        profile_started_ns,
        spawn_begin_ns,
        spawn_completed_ns,
        command_exited_ns,
        profile_ended_ns,
    ) = timestamps
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )

    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(runner, profile_started_ns),
            _snapshot(runner, max(profile_started_ns, profile_ended_ns)),
        ],
        sample_interval_s=0.01,
        profile_started_ns=profile_started_ns,
        spawn_begin_ns=spawn_begin_ns,
        spawn_completed_ns=spawn_completed_ns,
        command_exited_ns=command_exited_ns,
        profile_ended_ns=profile_ended_ns,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "unavailable"
    assert "non_monotonic_profile_timestamps" in profile["reason_codes"]
    assert profile["window"]["spawn_begin_offset_ms"] == pytest.approx(
        (spawn_begin_ns - profile_started_ns) / 1_000_000.0
    )


@pytest.mark.parametrize("sample_timestamps", ((5_000_000, 10_000_000), (10_000_000, 55_000_000)))
def test_aggregate_fails_closed_when_samples_are_outside_profile_window(
    monkeypatch: pytest.MonkeyPatch,
    sample_timestamps: tuple[int, int],
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )

    profile = runner.aggregate_resource_snapshots(
        [_snapshot(runner, timestamp) for timestamp in sample_timestamps],
        sample_interval_s=0.01,
        profile_started_ns=10_000_000,
        spawn_begin_ns=20_000_000,
        spawn_completed_ns=30_000_000,
        command_exited_ns=40_000_000,
        profile_ended_ns=50_000_000,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "unavailable"
    assert "samples_outside_profile_window" in profile["reason_codes"]


def test_aggregate_retains_identity_counters_across_missing_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    identity_first_seen = _reading(
        runner,
        pid=10,
        start=100,
        user=5,
        system=5,
        rss=100,
        io=10,
    )
    identity_reappeared = _reading(
        runner,
        pid=10,
        start=100,
        user=8,
        system=7,
        rss=120,
        io=16,
    )

    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(runner, 0),
            _snapshot(runner, 10_000_000, identity_first_seen),
            _snapshot(runner, 20_000_000),
            _snapshot(runner, 30_000_000, identity_reappeared),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=30_000_000,
        profile_ended_ns=30_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "degraded"
    assert "process_identity_sample_gap" in profile["reason_codes"]
    assert profile["sampler"]["identity_gap_event_count"] == 1
    assert profile["sampler"]["identity_gap_missing_sample_count"] == 1
    assert profile["metrics"]["cpu_ticks_delta"] == 15
    assert profile["metrics"]["io"]["read_bytes"] == 16


def test_aggregate_recovers_transient_process_io_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(
                runner,
                0,
                _reading(runner, pid=10, start=100, user=1, system=1, rss=100, io=100),
            ),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=10, start=100, user=2, system=1, rss=100, io=None),
                io_unavailable_count=1,
            ),
            _snapshot(
                runner,
                20_000_000,
                _reading(runner, pid=10, start=100, user=3, system=1, rss=100, io=150),
            ),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=20_000_000,
        profile_ended_ns=20_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "complete"
    assert profile["capabilities"]["process_io"] == "available"
    assert profile["metrics"]["io"]["read_bytes"] == 50
    assert profile["metrics"]["io_completeness"] == "sampled_lower_bound"
    assert profile["sampler"]["io_unavailable_event_count"] == 1
    assert profile["sampler"]["io_recovered_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_identity_count"] == 0
    assert profile["sampler"]["io_unresolved_baseline_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_terminal_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_never_valid_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_regression_gap_count"] == 0
    assert [sample["io_unavailable_event_count"] for sample in profile["samples"]] == [
        0,
        1,
        0,
    ]


def test_aggregate_recovers_new_process_io_from_zero_after_transient_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(runner, 0),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=11, start=200, user=1, system=1, rss=100, io=None),
                io_unavailable_count=1,
            ),
            _snapshot(
                runner,
                20_000_000,
                _reading(runner, pid=11, start=200, user=2, system=1, rss=100, io=30),
            ),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=20_000_000,
        profile_ended_ns=20_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "complete"
    assert profile["metrics"]["io"]["read_bytes"] == 30
    assert profile["sampler"]["io_recovered_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_gap_count"] == 0


def test_aggregate_keeps_terminal_process_io_gap_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(
                runner,
                0,
                _reading(runner, pid=10, start=100, user=1, system=1, rss=100, io=100),
            ),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=10, start=100, user=2, system=1, rss=100, io=110),
            ),
            _snapshot(
                runner,
                20_000_000,
                _reading(runner, pid=10, start=100, user=3, system=1, rss=100, io=None),
                io_unavailable_count=1,
            ),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=20_000_000,
        profile_ended_ns=20_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "degraded"
    assert "process_io_partial" in profile["reason_codes"]
    assert profile["capabilities"]["process_io"] == "partial"
    assert profile["metrics"]["io"]["read_bytes"] == 10
    assert profile["metrics"]["io_completeness"] == "partial"
    assert profile["sampler"]["io_recovered_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_identity_count"] == 1
    assert profile["sampler"]["io_unresolved_baseline_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_terminal_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_never_valid_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_regression_gap_count"] == 0
    assert profile["samples"][-1]["io_unavailable_event_count"] == 1


def test_aggregate_keeps_missing_baseline_process_io_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(
                runner,
                0,
                _reading(runner, pid=10, start=100, user=1, system=1, rss=100, io=None),
                io_unavailable_count=1,
            ),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=10, start=100, user=2, system=1, rss=100, io=120),
            ),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=10_000_000,
        profile_ended_ns=10_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "degraded"
    assert profile["metrics"]["io"]["read_bytes"] == 0
    assert profile["sampler"]["io_recovered_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_baseline_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_terminal_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_never_valid_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_regression_gap_count"] == 0


def test_aggregate_classifies_never_valid_new_process_io_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(runner, 0),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=11, start=200, user=1, system=1, rss=100, io=None),
                io_unavailable_count=1,
            ),
            _snapshot(runner, 20_000_000),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=20_000_000,
        profile_ended_ns=20_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "degraded"
    assert profile["sampler"]["io_unresolved_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_baseline_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_terminal_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_never_valid_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_regression_gap_count"] == 0


def test_aggregate_keeps_process_io_counter_regression_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )
    profile = runner.aggregate_resource_snapshots(
        [
            _snapshot(
                runner,
                0,
                _reading(runner, pid=10, start=100, user=1, system=1, rss=100, io=100),
            ),
            _snapshot(
                runner,
                10_000_000,
                _reading(runner, pid=10, start=100, user=2, system=1, rss=100, io=90),
            ),
        ],
        sample_interval_s=0.01,
        profile_started_ns=0,
        spawn_begin_ns=1,
        spawn_completed_ns=2,
        command_exited_ns=10_000_000,
        profile_ended_ns=10_000_001,
        command_rusage_cpu_seconds=0.0,
    )

    assert profile["status"] == "degraded"
    assert profile["metrics"]["io"]["read_bytes"] == 0
    assert profile["sampler"]["io_counter_regression_count"] == 6
    assert profile["sampler"]["io_unresolved_gap_count"] == 6
    assert profile["sampler"]["io_unresolved_baseline_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_terminal_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_never_valid_gap_count"] == 0
    assert profile["sampler"]["io_unresolved_regression_gap_count"] == 6


def test_profiled_command_timeout_uses_bounded_foreground_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    process = _HangingForegroundProcess()
    now_ns = 0
    trackers = []

    class RecordingTracker(runner._ProcIoHandleTracker):
        def __init__(self) -> None:
            super().__init__()
            self.was_closed = False
            trackers.append(self)

        def close(self) -> None:
            self.was_closed = True
            super().close()

    def clock() -> int:
        nonlocal now_ns
        now_ns += 10_000_000
        return now_ns

    def capture(*_args, perf_counter_ns, **_kwargs):
        return _snapshot(runner, perf_counter_ns())

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runner, "capture_project_snapshot", capture)
    monkeypatch.setattr(runner, "_child_rusage_cpu_seconds", lambda: 0.0)
    monkeypatch.setattr(runner, "_ProcIoHandleTracker", RecordingTracker)
    monkeypatch.setattr(
        runner,
        "_sysconf_positive",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
    )

    outcome = runner.run_profiled_command(
        ["fake-command"],
        tmp_path,
        {},
        0.0,
        perf_counter_ns=clock,
    )

    assert outcome.timed_out is True
    assert outcome.returncode is None
    assert outcome.stdout == "partial-out"
    assert outcome.stderr == "partial-err"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.communicate_timeouts == [runner._PROCESS_TERMINATE_GRACE_S]
    assert process.wait_timeouts == [runner._PROCESS_KILL_GRACE_S]
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert len(trackers) == 1
    assert trackers[0].was_closed is True


def test_profiled_command_sampling_exception_cleans_up_and_preserves_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    process = _HangingForegroundProcess()
    capture_count = 0
    trackers = []

    class RecordingTracker(runner._ProcIoHandleTracker):
        def __init__(self) -> None:
            super().__init__()
            self.was_closed = False
            trackers.append(self)

        def close(self) -> None:
            self.was_closed = True
            super().close()

    def capture(*_args, **_kwargs):
        nonlocal capture_count
        capture_count += 1
        if capture_count == 1:
            return _snapshot(runner, 1)
        raise RuntimeError("sampling failed")

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runner, "capture_project_snapshot", capture)
    monkeypatch.setattr(runner, "_child_rusage_cpu_seconds", lambda: 0.0)
    monkeypatch.setattr(runner, "_ProcIoHandleTracker", RecordingTracker)

    with pytest.raises(RuntimeError, match="sampling failed"):
        runner.run_profiled_command(["fake-command"], tmp_path, {}, 5.0)

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.communicate_timeouts == [runner._PROCESS_TERMINATE_GRACE_S]
    assert process.wait_timeouts == [runner._PROCESS_KILL_GRACE_S]
    assert process.stdout.closed is True
    assert process.stderr.closed is True
    assert len(trackers) == 1
    assert trackers[0].was_closed is True


def test_profiled_command_popen_failure_closes_stable_io_tracker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    trackers = []

    class RecordingTracker(runner._ProcIoHandleTracker):
        def __init__(self) -> None:
            super().__init__()
            self.was_closed = False
            trackers.append(self)

        def close(self) -> None:
            self.was_closed = True
            super().close()

    monkeypatch.setattr(runner, "_ProcIoHandleTracker", RecordingTracker)
    monkeypatch.setattr(
        runner,
        "capture_project_snapshot",
        lambda *_args, perf_counter_ns, **_kwargs: _snapshot(
            runner,
            perf_counter_ns(),
        ),
    )

    def fail_popen(*_args, **_kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(runner.subprocess, "Popen", fail_popen)

    with pytest.raises(OSError, match="spawn failed"):
        runner.run_profiled_command(["fake-command"], tmp_path, {}, 5.0)

    assert len(trackers) == 1
    assert trackers[0].was_closed is True


def test_profiled_command_aggregate_failure_closes_stable_io_tracker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    trackers = []

    class RecordingTracker(runner._ProcIoHandleTracker):
        def __init__(self) -> None:
            super().__init__()
            self.was_closed = False
            trackers.append(self)

        def close(self) -> None:
            self.was_closed = True
            super().close()

    class CompletedProcess:
        pid = 4242
        returncode = 0
        stdout = _FakePipe()
        stderr = _FakePipe()

        def communicate(self, timeout=None):
            return "", ""

        def poll(self):
            return self.returncode

    process = CompletedProcess()
    monkeypatch.setattr(runner, "_ProcIoHandleTracker", RecordingTracker)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        runner,
        "capture_project_snapshot",
        lambda *_args, perf_counter_ns, **_kwargs: _snapshot(
            runner,
            perf_counter_ns(),
        ),
    )
    monkeypatch.setattr(runner, "_child_rusage_cpu_seconds", lambda: 0.0)

    def fail_aggregate(*_args, **_kwargs):
        raise RuntimeError("aggregate failed")

    monkeypatch.setattr(runner, "aggregate_resource_snapshots", fail_aggregate)

    with pytest.raises(RuntimeError, match="aggregate failed"):
        runner.run_profiled_command(["fake-command"], tmp_path, {}, 5.0)

    assert len(trackers) == 1
    assert trackers[0].was_closed is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not hasattr(os, "pread"),
    reason="profiled command I/O assertions require Linux procfs stable handles",
)
def test_profiled_command_never_persists_argv_cwd_or_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    secret = "do-not-persist-this-prompt-token"
    project = tmp_path / "private-project-name"
    project.mkdir()
    trackers = []

    class RecordingTracker(runner._ProcIoHandleTracker):
        def __init__(self) -> None:
            super().__init__()
            self.was_closed = False
            trackers.append(self)

        def close(self) -> None:
            self.was_closed = True
            super().close()

    monkeypatch.setattr(runner, "_ProcIoHandleTracker", RecordingTracker)

    outcome = runner.run_profiled_command(
        [sys.executable, "-c", "import time; time.sleep(0.03)", secret],
        project,
        {"PRIVATE_TOKEN": secret},
        5.0,
        sample_interval_s=0.01,
    )
    encoded = json.dumps(outcome.resource_profile, sort_keys=True)

    assert outcome.returncode == 0
    assert secret not in encoded
    assert str(project) not in encoded
    assert '"argv_persisted": false' in encoded
    assert outcome.resource_profile["window"]["command_wall_ms"] < 1000
    sampler = outcome.resource_profile["sampler"]
    prime_successes = sampler["io_stable_handle_prime_success_count"]
    prime_failures = sampler["io_stable_handle_prime_failure_count"]
    assert prime_successes + prime_failures == 1
    if prime_successes:
        assert sampler["io_stable_handle_open_count"] >= 1
        assert sampler["io_stable_handle_read_count"] >= 1
    else:
        assert sampler["io_stable_handle_open_failure_count"] >= 1
        assert sampler["io_unavailable_event_count"] >= 1
    assert len(trackers) == 1
    assert trackers[0].was_closed is True
    assert trackers[0]._handles == {}


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires Linux procfs process discovery",
)
def test_snapshot_keeps_live_process_when_proc_io_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
    )
    try:
        def missing_io(_path: Path) -> dict[str, int]:
            raise FileNotFoundError("proc I/O counters unavailable")

        monkeypatch.setattr(runner, "_read_proc_io", missing_io)
        snapshot = runner.capture_project_snapshot(
            tmp_path,
            root_pid=process.pid,
            known_instances=set(),
        )
    finally:
        process.terminate()
        process.wait(timeout=5)

    readings = [reading for reading in snapshot.readings if reading.pid == process.pid]
    assert len(readings) == 1
    assert readings[0].read_bytes is None
    assert readings[0].write_bytes is None
    assert snapshot.io_unavailable_count == 1
    assert snapshot.vanished_process_count == 0


def test_profiled_command_does_not_return_stale_seed_as_observed(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    project = tmp_path / "active-seed"
    project.mkdir()
    stale = (999_999, 123)

    outcome = runner.run_profiled_command(
        [sys.executable, "-c", "pass"],
        project,
        {"PATH": os.environ.get("PATH", "")},
        5.0,
        known_instances=(stale,),
    )

    assert stale not in outcome.tracked_process_instances
    assert stale not in outcome.active_process_instances


def test_profiled_command_owns_fresh_trace_envelope_without_mutating_caller_env(tmp_path: Path) -> None:
    runner = _load_runner()
    project = tmp_path / "trace-envelope"
    project.mkdir()
    inherited = {
        "CCB_STARTUP_TRACE_ID": "trace_" + "f" * 32,
        "CCB_STARTUP_TRACE_WRAPPER_ENTRY_NS": "111",
        "CCB_STARTUP_TRACE_WRAPPER_PRE_EXEC_NS": "222",
        "PATH": os.environ.get("PATH", ""),
    }
    original = dict(inherited)
    script = (
        "import json,os; print(json.dumps({k:os.environ.get(k) for k in "
        "['CCB_STARTUP_TIMING_TRACE','CCB_STARTUP_TRACE_ID',"
        "'CCB_STARTUP_TRACE_SPAWN_NS','CCB_STARTUP_TRACE_WRAPPER_ENTRY_NS',"
        "'CCB_STARTUP_TRACE_WRAPPER_PRE_EXEC_NS']}))"
    )

    outcome = runner.run_profiled_command(
        [sys.executable, "-c", script],
        project,
        inherited,
        5.0,
        startup_timing_trace=True,
    )
    child_trace = json.loads(outcome.stdout)

    assert inherited == original
    assert outcome.startup_timing_trace_id == child_trace["CCB_STARTUP_TRACE_ID"]
    assert child_trace["CCB_STARTUP_TIMING_TRACE"] == "1"
    assert int(child_trace["CCB_STARTUP_TRACE_SPAWN_NS"]) > 0
    assert child_trace["CCB_STARTUP_TRACE_WRAPPER_ENTRY_NS"] is None
    assert child_trace["CCB_STARTUP_TRACE_WRAPPER_PRE_EXEC_NS"] is None


def test_timed_control_command_strips_trace_and_uses_spawn_to_exit_wall(tmp_path: Path) -> None:
    runner = _load_runner()
    project = tmp_path / "timed-control"
    project.mkdir()
    inherited = {
        "CCB_STARTUP_TIMING_TRACE": "1",
        "CCB_STARTUP_TRACE_ID": "trace_" + "f" * 32,
        "CCB_STARTUP_TRACE_SPAWN_NS": "123",
        "PATH": os.environ.get("PATH", ""),
    }
    script = (
        "import json,os; print(json.dumps({k:os.environ.get(k) for k in "
        "['CCB_STARTUP_TIMING_TRACE','CCB_STARTUP_TRACE_ID',"
        "'CCB_STARTUP_TRACE_SPAWN_NS']}))"
    )

    outcome = runner.run_timed_command(
        [sys.executable, "-c", script],
        project,
        inherited,
        5.0,
    )

    assert outcome.returncode == 0
    assert outcome.timed_out is False
    assert outcome.command_wall_ms >= 0.0
    assert json.loads(outcome.stdout) == {
        "CCB_STARTUP_TIMING_TRACE": None,
        "CCB_STARTUP_TRACE_ID": None,
        "CCB_STARTUP_TRACE_SPAWN_NS": None,
    }
    assert inherited["CCB_STARTUP_TIMING_TRACE"] == "1"


def test_timed_control_timeout_uses_bounded_foreground_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    process = _HangingForegroundProcess()
    now_ns = 0

    def clock() -> int:
        nonlocal now_ns
        now_ns += 10_000_000
        return now_ns

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)

    outcome = runner.run_timed_command(
        ["fake-command"],
        tmp_path,
        {},
        0.0,
        perf_counter_ns=clock,
    )

    assert outcome.timed_out is True
    assert outcome.returncode is None
    assert outcome.stdout == "partial-out"
    assert outcome.stderr == "partial-err"
    assert outcome.command_wall_ms == 10.0
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.communicate_timeouts == [0.0, runner._PROCESS_TERMINATE_GRACE_S]
    assert process.wait_timeouts == [runner._PROCESS_KILL_GRACE_S]


def test_cleanup_requires_two_consecutive_clean_snapshots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _load_runner()
    residue = _snapshot(
        runner,
        1,
        _reading(runner, pid=10, start=100, user=1, system=1, rss=10, io=1),
    )
    clean1 = _snapshot(runner, 2)
    clean2 = _snapshot(runner, 3)
    snapshots = iter((residue, clean1, clean2))
    monkeypatch.setattr(runner, "capture_project_snapshot", lambda *_args, **_kwargs: next(snapshots))

    audit = runner.capture_cleanup_resource_audit(
        tmp_path,
        known_instances=set(),
        sample_interval_s=0.0,
        sleep=lambda _value: None,
    )

    assert audit["status"] == "clean"
    assert audit["consecutive_clean_snapshots"] == 2
    assert [sample["process_count"] for sample in audit["samples"]] == [1, 0, 0]


def test_procfs_capability_failure_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner.Path, "is_dir", lambda _path: False)

    snapshot = runner.capture_project_snapshot(
        tmp_path,
        root_pid=None,
        known_instances=set(),
    )
    profile = runner.aggregate_resource_snapshots(
        [snapshot],
        sample_interval_s=0.05,
        profile_started_ns=snapshot.monotonic_ns,
        spawn_begin_ns=snapshot.monotonic_ns,
        spawn_completed_ns=snapshot.monotonic_ns,
        command_exited_ns=snapshot.monotonic_ns,
        profile_ended_ns=snapshot.monotonic_ns,
        command_rusage_cpu_seconds=None,
    )

    assert profile["status"] == "unavailable"
    assert "procfs_unavailable" in profile["reason_codes"]
    assert profile["capabilities"]["process_io"] == "unavailable"
