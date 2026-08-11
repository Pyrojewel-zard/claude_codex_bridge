from __future__ import annotations

import subprocess
from pathlib import Path

from cli.services.runtime_launch_runtime import pane_runtime
from terminal_runtime import shell_launch


class FakeRespawnBackend:
    """记录 respawn_pane / capture_pane 调用的最小 herdr 后端替身。"""

    def __init__(self) -> None:
        self.respawn_calls: list[tuple[dict, dict]] = []
        self.capture_calls: list[int] = []

    def respawn_pane(self, pane_ref, *, command, cwd, env):
        self.respawn_calls.append((dict(pane_ref), {'command': command, 'cwd': cwd, 'env': env}))

    def capture_pane(self, pane_ref, *, lines):
        self.capture_calls.append(lines)
        return '', None


def _fake_resolve_sh_exe(path: str | None):
    def resolve() -> str | None:
        return path

    return resolve


def test_herdr_launch_command_returns_argv_so_list2cmdline_does_not_quote_whole(monkeypatch, tmp_path) -> None:
    """respawn_pane 经 list2cmdline 把 command 当 argv 拼 pane run 命令行（cli.py:1363）。

    `& <sh.exe> <script>` 必须作为三个 argv 片段返回；若返回整条 PowerShell 字符串，
    会被整体加引号而在 pane 里被当作字符串字面量回显而不执行（2026-08-06 实测）。
    """
    monkeypatch.setattr(
        shell_launch,
        'resolve_sh_executable',
        _fake_resolve_sh_exe(r'C:\Program Files\Git\bin\sh.exe'),
    )
    monkeypatch.setattr(shell_launch.tempfile, 'gettempdir', lambda: str(tmp_path))
    command = pane_runtime._herdr_launch_command('export A=1 && codex', Path(r'D:\proj'), 'agent_1')
    assert command[0] == '&'
    assert command[1] == r'C:\Program Files\Git\bin\sh.exe'
    script_path = command[2]
    assert Path(script_path).suffix == '.sh'
    cmdline = subprocess.list2cmdline(command)
    assert cmdline.startswith('& "C:\\Program Files\\Git\\bin\\sh.exe"')
    assert not cmdline.startswith('"&')  # 整体被引号化 = 字符串字面量 = 不执行


def test_herdr_launch_command_writes_bash_script_with_cd_and_start_cmd(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        shell_launch,
        'resolve_sh_executable',
        _fake_resolve_sh_exe(r'C:\Program Files\Git\bin\sh.exe'),
    )
    monkeypatch.setattr(shell_launch.tempfile, 'gettempdir', lambda: str(tmp_path))
    command = pane_runtime._herdr_launch_command('exec codex --remote', Path(r'D:\proj'), 'agent_1')
    script = Path(command[2]).read_text(encoding='utf-8')
    assert script.startswith("cd 'D:\\proj' && ")
    assert 'exec codex --remote' in script


def test_herdr_launch_command_falls_back_to_sh_lc_when_sh_missing(monkeypatch) -> None:
    monkeypatch.setattr(shell_launch, 'resolve_sh_executable', _fake_resolve_sh_exe(None))
    command = pane_runtime._herdr_launch_command('codex', Path(r'D:\proj'), 'agent_1')
    assert command == ['sh', '-lc', 'codex']


def test_launch_runtime_pane_respawns_herdr_pane_ref_with_argv_command(monkeypatch) -> None:
    backend = FakeRespawnBackend()
    pane_ref = {
        'backend_impl': 'herdr',
        'pane_id': 'w2:p2',
        'session_name': 'ccb-avaprintdesigner-x',
    }
    pane_runtime.launch_runtime_pane(
        backend,
        spec_name='agent_1',
        assigned_pane_id='w2:p2',
        assigned_pane_ref=pane_ref,
        start_cmd='export A=1 && codex',
        run_cwd=Path(r'D:\proj'),
        create_detached_tmux_pane_fn=lambda *a, **k: None,
        pane_meets_minimum_size_fn=lambda *a, **k: True,
        best_effort_kill_tmux_pane_fn=lambda *a, **k: None,
        allow_detached_fallback=True,
    )
    assert len(backend.respawn_calls) == 1
    pane, opts = backend.respawn_calls[0]
    assert pane['pane_id'] == 'w2:p2'
    command = opts['command']
    assert command[0] == '&'
    assert command[1].lower().endswith('sh.exe')
    assert command[2].endswith('.sh')
    assert opts['cwd'] == r'D:\proj'
    assert backend.capture_calls  # 成功后 best-effort 捕获 pane


def test_launch_runtime_pane_non_herdr_falls_through_to_launch_pane(monkeypatch) -> None:
    launched = {}

    def launch_pane(backend, *, spec_name, assigned_pane_id, start_cmd, run_cwd, **kwargs):
        launched['spec_name'] = spec_name
        launched['start_cmd'] = start_cmd
        launched['run_cwd'] = run_cwd
        return {'pane_id': assigned_pane_id or 't:p1'}

    monkeypatch.setattr(pane_runtime, 'launch_pane', launch_pane)
    backend = object()
    pane = pane_runtime.launch_runtime_pane(
        backend,
        spec_name='agent_1',
        assigned_pane_id='t:p1',
        assigned_pane_ref=None,  # 非 herdr ref
        start_cmd='export A=1 && codex',
        run_cwd=Path(r'D:\proj'),
        create_detached_tmux_pane_fn=lambda *a, **k: None,
        pane_meets_minimum_size_fn=lambda *a, **k: True,
        best_effort_kill_tmux_pane_fn=lambda *a, **k: None,
        allow_detached_fallback=True,
    )
    assert launched == {'spec_name': 'agent_1', 'start_cmd': 'export A=1 && codex', 'run_cwd': Path(r'D:\proj')}
    assert pane['pane_id'] == 't:p1'
