from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.phase2_runtime import handlers_start
from project_command_trust import ProjectCommandApproval, ProjectCommandField


class _TtyInput(StringIO):
    def isatty(self) -> bool:
        return True


class _TtyOutput(StringIO):
    def isatty(self) -> bool:
        return True


def _approval(tmp_path: Path, *, status: str = 'approval_required') -> ProjectCommandApproval:
    return ProjectCommandApproval(
        project_root=tmp_path / 'repo',
        fields=(ProjectCommandField('tool_windows.files.command', 'printf "ok"\n'),),
        digest='digest',
        status=status,
        receipt_path=tmp_path / 'state' / 'receipt.json',
    )


def test_noninteractive_start_fails_before_start_agents(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    services = SimpleNamespace(
        inspect_project_commands=lambda _context: _approval(tmp_path),
        start_agents=lambda *_args, **_kwargs: calls.append('start') or {},
    )
    monkeypatch.setattr(handlers_start.sys, 'stdin', StringIO('yes\n'))

    with pytest.raises(RuntimeError, match='ccb config approve-commands'):
        handlers_start.handle_start(object(), object(), StringIO(), services)

    assert calls == []


def test_interactive_start_displays_exact_fields_and_approves_once(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    pending = _approval(tmp_path)
    approved = _approval(tmp_path, status='approved')
    out = _TtyOutput()
    services = SimpleNamespace(
        inspect_project_commands=lambda _context: pending,
        approve_project_commands_context=lambda _context, **_kwargs: calls.append('approve') or approved,
        start_agents=lambda *_args, **_kwargs: calls.append('start') or {'status': 'ok'},
        render_start=lambda _summary: ('status: ok',),
        write_lines=lambda stream, lines: stream.write('\n'.join(lines) + '\n'),
    )
    monkeypatch.setattr(handlers_start.sys, 'stdin', _TtyInput('yes\n'))
    monkeypatch.setenv('CCB_NO_ATTACH', '1')

    assert handlers_start.handle_start(object(), object(), out, services) == 0

    assert calls == ['approve', 'start']
    assert '"tool_windows.files.command" = "printf \\"ok\\"\\n"' in out.getvalue()


def test_explicit_approve_command_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    services = SimpleNamespace(
        inspect_project_commands=lambda _context: _approval(tmp_path),
        approve_project_commands_context=lambda _context, **_kwargs: calls.append('approve') or _approval(
            tmp_path,
            status='approved',
        ),
        write_lines=lambda stream, lines: stream.write('\n'.join(lines) + '\n'),
    )
    monkeypatch.setattr(handlers_start.sys, 'stdin', _TtyInput('no\n'))

    with pytest.raises(RuntimeError, match='cancelled'):
        handlers_start.handle_config_validate(
            object(),
            SimpleNamespace(action='approve-commands', json_output=False),
            StringIO(),
            services,
        )

    assert calls == []
