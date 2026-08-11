from __future__ import annotations

from pathlib import Path

from ccbd.services.project_namespace_runtime.backend import respawn_pane
from terminal_runtime.shell_launch import herdr_respawn_command


def _fake_resolve_sh(path: str | None):
    def resolve() -> str | None:
        return path

    return resolve


class _FakeMuxBackend:
    """最小 mux(herdr) backend 替身：有 capabilities，无 _tmux_run。"""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, list[str], str, dict]] = []
        self._ccb_project_pane_refs = {'wE:p2': {'backend_impl': 'herdr', 'pane_id': 'wE:p2'}}

    def capabilities(self):
        status = {
            'session_attach': 'supported',
            'pane_list': 'supported',
            'pane_run': 'supported',
        }
        return {
            'backend_impl': 'herdr',
            'command_status': status,
            'semantic_status': status,
        }

    def respawn_pane(self, pane_ref, *, command, cwd, env):
        self.calls.append((dict(pane_ref), command, str(cwd), dict(env)))


def test_herdr_respawn_command_uses_full_sh_path_when_available(monkeypatch, tmp_path) -> None:
    """Git Bash is invoked by a structured PowerShell wrapper without cmd.exe."""
    monkeypatch.setattr(
        'terminal_runtime.shell_launch.resolve_sh_executable',
        _fake_resolve_sh(r'C:\Program Files\Git\bin\sh.exe'),
    )
    monkeypatch.setattr('terminal_runtime.shell_launch.tempfile.gettempdir', lambda: str(tmp_path))
    argv = herdr_respawn_command('export A=1 && codex', Path(r'D:\proj'), 'agent_1')
    assert argv[:5] == ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File']
    ps1_path = Path(argv[5])
    script = ps1_path.with_suffix('.sh').read_text(encoding='utf-8')
    assert script.startswith("cd 'D:\\proj' && ")
    assert 'export A=1 && codex' in script
    assert '& "C:\\Program Files\\Git\\bin\\sh.exe" $shScript' in ps1_path.read_text(
        encoding='utf-8-sig'
    )


def test_herdr_respawn_command_falls_back_to_sh_lc_when_sh_missing(monkeypatch) -> None:
    """无 Git Bash 时回退 `['sh', '-lc', command]`（与历史 tmux 行为一致）。"""
    monkeypatch.setattr(
        'terminal_runtime.shell_launch.resolve_sh_executable',
        _fake_resolve_sh(None),
    )
    argv = herdr_respawn_command('codex', Path(r'D:\proj'), 'agent_1')
    assert argv == ['sh', '-lc', 'codex']


def test_respawn_pane_mux_uses_herdr_respawn_command(monkeypatch, tmp_path) -> None:
    """mux(herdr) respawn reuses the structured PowerShell wrapper."""
    monkeypatch.setattr(
        'terminal_runtime.shell_launch.resolve_sh_executable',
        _fake_resolve_sh(r'C:\Program Files\Git\bin\sh.exe'),
    )
    monkeypatch.setattr('terminal_runtime.shell_launch.tempfile.gettempdir', lambda: str(tmp_path))
    backend = _FakeMuxBackend()
    respawn_pane(backend, pane_id='wE:p2', command='export A=1 && codex', cwd=str(tmp_path))
    assert len(backend.calls) == 1
    pane_ref, command, cwd, env = backend.calls[0]
    assert pane_ref['pane_id'] == 'wE:p2'
    assert command[:5] == ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File']
    assert command[5].endswith('.ps1')
    assert cwd == str(tmp_path)
