from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace

import cli.kill_runtime.processes as processes
from project.resolver import bootstrap_project
from runtime_accelerator.ownership import ProcessIdentity, legacy_marker_path
from runtime_pid_cleanup import (
    collect_project_authority_pid_candidates,
    collect_project_process_candidates,
    list_process_cmdlines,
    remove_pid_files,
)


def _patch_process_os_name(monkeypatch, name: str) -> None:
    os_proxy = SimpleNamespace(**vars(processes.os))
    os_proxy.name = name
    monkeypatch.setattr(processes, 'os', os_proxy)


def test_kill_pid_tree_once_uses_taskkill_on_windows(monkeypatch) -> None:
    calls: list[list[str]] = []

    _patch_process_os_name(monkeypatch, 'nt')
    monkeypatch.setattr(
        processes.subprocess,
        'run',
        lambda args, capture_output=True: calls.append(list(args)) or None,
    )

    assert processes._kill_pid_tree_once(321, force=True) is True
    assert calls == [["taskkill", "/F", "/T", "/PID", "321"]]


def test_kill_pid_tree_once_prefers_process_group_on_posix(monkeypatch) -> None:
    killed: list[tuple[int, signal.Signals]] = []
    kill_pid_calls: list[tuple[int, bool]] = []

    _patch_process_os_name(monkeypatch, 'posix')
    monkeypatch.setattr(processes, '_safe_getpgid', lambda pid: 900)
    monkeypatch.setattr(processes, '_safe_getpgrp', lambda: 901)
    monkeypatch.setattr(processes.os, 'killpg', lambda pgid, sig: killed.append((pgid, sig)), raising=False)
    monkeypatch.setattr(processes, 'kill_pid', lambda pid, force=False: kill_pid_calls.append((pid, force)) or True)

    assert processes._kill_pid_tree_once(123, force=False) is True
    assert killed == [(900, signal.SIGTERM)]
    assert kill_pid_calls == []


def test_collect_project_process_candidates_finds_ccbd_project_arg(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-control-plane-scan'
    project_root.mkdir()
    bootstrap_project(project_root)
    proc_root = tmp_path / 'proc'
    (proc_root / '101').mkdir(parents=True)
    (proc_root / '102').mkdir()
    cmdlines = {
        101: f'/usr/bin/python /opt/ccb/lib/ccbd/main.py --project {project_root}',
        102: f'/usr/bin/python /opt/ccb/lib/ccbd/main.py --project {tmp_path / "other"}',
    }

    candidates = collect_project_process_candidates(
        project_root,
        proc_root=proc_root,
        read_proc_cmdline_fn=lambda pid: cmdlines.get(pid, ''),
        current_pid=999,
    )

    assert set(candidates) == {101}
    assert candidates[101] == [project_root / '.ccb' / 'ccbd']


def test_list_process_cmdlines_falls_back_to_ps_when_proc_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    proc_root = tmp_path / 'missing-proc'

    class _Result:
        returncode = 0
        stdout = ' 101 /usr/bin/python /opt/ccb/lib/ccbd/main.py --project /tmp/repo\n 202 helper\n'

    monkeypatch.setattr(
        'runtime_pid_cleanup.procfs.subprocess.run',
        lambda args, check=False, capture_output=True, text=True: _Result(),
    )

    mapping = list_process_cmdlines(proc_root=proc_root, current_pid=202)

    assert mapping == {101: '/usr/bin/python /opt/ccb/lib/ccbd/main.py --project /tmp/repo'}


def test_list_process_cmdlines_uses_one_ps_snapshot_for_system_proc(monkeypatch) -> None:
    expected = {101: '/usr/bin/python bridge.py --runtime-dir /tmp/repo/.ccb'}
    monkeypatch.setattr(
        'runtime_pid_cleanup.procfs._list_process_cmdlines_via_ps',
        lambda *, current_pid: expected if current_pid == 202 else {},
    )

    mapping = list_process_cmdlines(
        current_pid=202,
        read_proc_cmdline_fn=lambda _pid: (_ for _ in ()).throw(
            AssertionError('system /proc must not be read one pid at a time when ps succeeds')
        ),
    )

    assert mapping == expected


def test_collect_project_process_candidates_falls_back_to_ps_without_proc(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-ps-scan'
    project_root.mkdir()
    bootstrap_project(project_root)

    candidates = collect_project_process_candidates(
        project_root,
        proc_root=tmp_path / 'missing-proc',
        list_process_cmdlines_fn=lambda **kwargs: {
            101: f'/usr/bin/python /opt/ccb/lib/ccbd/main.py --project {project_root}',
            202: f'/usr/bin/python /opt/ccb/lib/ccbd/keeper_main.py --project {project_root}',
            303: '/usr/bin/python unrelated.py',
        },
        current_pid=999,
    )

    assert sorted(candidates) == [101, 202]
    assert candidates[101] == [project_root / '.ccb' / 'ccbd']
    assert candidates[202] == [project_root / '.ccb' / 'ccbd']


def test_collect_project_process_candidates_finds_legacy_accelerator_by_exact_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / 'repo-legacy-accelerator').resolve()
    project_root.mkdir()
    bootstrap_project(project_root)
    socket_path = (tmp_path / 'accelerator.sock').resolve()
    executable = Path('/opt/ccb/bin/ccb-runtime-accelerator')
    cmdline = f'{executable} serve --socket {socket_path}'
    monkeypatch.setenv('CCB_RUNTIME_ACCELERATOR_SOCKET', str(socket_path))
    monkeypatch.setattr(
        'runtime_accelerator.ownership.inspect_process_identity',
        lambda pid: ProcessIdentity(
            pid=pid,
            argv=(str(executable), 'serve', '--socket', str(socket_path)),
            cwd=project_root,
            executable=executable,
            start_token='proc:100',
        ),
    )
    monkeypatch.setattr('runtime_accelerator.ownership.is_pid_alive', lambda pid: pid == 707)

    candidates = collect_project_process_candidates(
        project_root,
        list_process_cmdlines_fn=lambda **kwargs: {707: cmdline, 808: 'sh editor.py'},
        current_pid=999,
    )

    assert candidates == {707: [legacy_marker_path(project_root)]}


def test_collect_project_authority_pid_candidates_reads_lifecycle(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-authority-lifecycle'
    project_root.mkdir()
    bootstrap_project(project_root)
    lifecycle_path = project_root / '.ccb' / 'ccbd' / 'lifecycle.json'
    lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_path.write_text(
        '{"owner_pid": 321, "keeper_pid": 654}\n',
        encoding='utf-8',
    )

    candidates = collect_project_authority_pid_candidates(project_root)

    assert candidates[321] == [lifecycle_path]
    assert candidates[654] == [lifecycle_path]


def test_collect_project_authority_pid_candidates_reads_runtime_accelerator_owner(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-accelerator-authority'
    project_root.mkdir()
    bootstrap_project(project_root)
    owner_path = project_root / '.ccb' / 'ccbd' / 'runtime-accelerator.json'
    owner_path.parent.mkdir(parents=True, exist_ok=True)
    owner_path.write_text('{"pid": 765}\n', encoding='utf-8')

    candidates = collect_project_authority_pid_candidates(project_root)

    assert candidates[765] == [owner_path]


def test_remove_pid_files_removes_only_pid_and_accelerator_authority(tmp_path: Path) -> None:
    pid_path = tmp_path / 'runtime.pid'
    owner_path = tmp_path / 'runtime-accelerator.json'
    unrelated_path = tmp_path / 'lease.json'
    for path in (pid_path, owner_path, unrelated_path):
        path.write_text('{}\n', encoding='utf-8')

    remove_pid_files((pid_path, owner_path, unrelated_path))

    assert not pid_path.exists()
    assert not owner_path.exists()
    assert unrelated_path.exists()
