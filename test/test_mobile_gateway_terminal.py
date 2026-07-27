from __future__ import annotations

from dataclasses import replace
import threading
from types import SimpleNamespace

import pytest

from mobile_gateway.terminal import (
    TerminalAttachTarget,
    TerminalGeometry,
    TmuxTerminalSession,
    _send_tmux_terminal_bytes,
    _send_tmux_terminal_literal,
    _select_tmux_terminal_pane,
    _terminal_client_env,
    resolve_tmux_binary,
)


def _target(*, include_history: bool = True) -> TerminalAttachTarget:
    return TerminalAttachTarget(
        terminal_id='term-test',
        socket_path='/tmp/ccb-test/tmux.sock',
        session_name='ccb-test',
        pane_id='%42',
        geometry=TerminalGeometry(),
        target_summary={'project_id': 'proj-test', 'agent': 'lead', 'pane_id': '%42'},
        include_history=include_history,
    )


def test_terminal_output_command_captures_selected_pane_not_session() -> None:
    assert _target().command == [
        'tmux',
        '-S',
        '/tmp/ccb-test/tmux.sock',
        'capture-pane',
        '-p',
        '-e',
        '-t',
        '%42',
        '-S',
        '-1000',
    ]
    assert 'attach-session' not in _target().command


def test_terminal_session_reads_selected_pane_snapshot(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        assert 'attach-session' not in command
        output = (
            b'pane history\npane only\nprompt$ '
            if command.count('-S') > 1
            else b'pane only\nprompt$ '
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    session = TmuxTerminalSession(_target())
    output = session.read(0)

    assert output == (
        b'\x1b[?25l\x1b[3J\x1b[H\x1b[2J'
        b'pane history\r\npane only\r\nprompt$ '
    )
    assert calls == [
        [
            'tmux',
            '-S',
            '/tmp/ccb-test/tmux.sock',
            'capture-pane',
            '-p',
            '-e',
            '-t',
            '%42',
            '-S',
            '-1000',
        ],
        [
            'tmux',
            '-S',
            '/tmp/ccb-test/tmux.sock',
            'capture-pane',
            '-p',
            '-e',
            '-t',
            '%42',
        ],
    ]


def test_terminal_session_repaints_visible_pane_without_reappending_history(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    visible_outputs = iter((b'pane only\nprompt$ ', b'pane changed\nprompt$ '))

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if command.count('-S') > 1:
            output = b'real history\npane only\nprompt$ '
        else:
            output = next(visible_outputs)
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    session = TmuxTerminalSession(_target())

    first = session.read(0)
    second = session.read(0)

    assert first == (
        b'\x1b[?25l\x1b[3J\x1b[H\x1b[2J'
        b'real history\r\npane only\r\nprompt$ '
    )
    assert second == (
        b'\x1b[?25l\x1b[0m'
        b'\x1b[1;1H\x1b[0Jpane changed\r\nprompt$ '
        b'\x1b[0m'
    )
    assert b'\x1b[2J' not in second
    assert sum(command.count('-S') > 1 for command in calls) == 1
    assert len(calls) == 3


def test_terminal_delta_accounts_for_client_side_line_wrapping(monkeypatch) -> None:
    visible_outputs = iter(
        (
            b'12345678\nbefore',
            b'12345678\nafter',
        )
    )

    def fake_run(command, **kwargs):
        output = (
            b'12345678\nbefore'
            if command.count('-S') > 1
            else next(visible_outputs)
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = replace(
        _target(),
        geometry=TerminalGeometry(columns=4, rows=10),
    )
    session = TmuxTerminalSession(target)

    session.read(0)
    output = session.read(0)

    assert output == (
        b'\x1b[?25l\x1b[0m'
        b'\x1b[3;1H\x1b[0Jafter'
        b'\x1b[0m'
    )


def test_terminal_delta_uses_full_repaint_when_wrapped_content_exceeds_viewport(
    monkeypatch,
) -> None:
    visible_outputs = iter(
        (
            b'12345678\nbefore',
            b'12345678\nafter',
        )
    )

    def fake_run(command, **kwargs):
        output = (
            b'12345678\nbefore'
            if command.count('-S') > 1
            else next(visible_outputs)
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = replace(
        _target(),
        geometry=TerminalGeometry(columns=4, rows=2),
    )
    session = TmuxTerminalSession(target)

    session.read(0)
    output = session.read(0)

    assert output == b'\x1b[?25l\x1b[3J\x1b[H\x1b[2J12345678\r\nafter'


def test_terminal_resumed_session_repaints_visible_pane_without_history(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=b'current pane\nprompt$ ', stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    output = TmuxTerminalSession(_target(include_history=False)).read(0)

    assert output == b'\x1b[?25l\x1b[3J\x1b[H\x1b[2Jcurrent pane\r\nprompt$ '
    assert len(calls) == 1
    assert calls[0].count('-S') == 1


def test_terminal_resize_repaints_visible_pane_without_replaying_history(monkeypatch) -> None:
    calls: list[list[str]] = []
    visible_outputs = iter((b'pane before\nprompt$ ', b'pane after\nprompt$ '))

    def fake_run(command, **kwargs):
        calls.append(list(command))
        output = (
            b'history\npane before\nprompt$ '
            if command.count('-S') > 1
            else next(visible_outputs)
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    session = TmuxTerminalSession(_target())

    session.read(0)
    session.resize(TerminalGeometry(columns=100, rows=30))
    output = session.read(0)

    assert output == b'\x1b[?25l\x1b[H\x1b[2Jpane after\r\nprompt$ '
    assert sum(command.count('-S') > 1 for command in calls) == 1
    assert len(calls) == 3


def test_terminal_resize_during_capture_repaints_without_snapshot_race(
    monkeypatch,
) -> None:
    capture_started = threading.Event()
    release_capture = threading.Event()
    visible_reads = iter((b'pane before\nprompt$ ', b'pane after\nprompt$ '))

    def fake_capture(target, geometry, *, include_history):
        if include_history:
            return b'history\npane before\nprompt$ '
        output = next(visible_reads)
        if output.startswith(b'pane after'):
            capture_started.set()
            assert release_capture.wait(timeout=2)
        return output

    monkeypatch.setattr(
        'mobile_gateway.terminal._capture_tmux_terminal_pane',
        fake_capture,
    )
    session = TmuxTerminalSession(_target())
    session.read(0)
    result: dict[str, object] = {}

    def read_after_resize() -> None:
        try:
            result['output'] = session.read(0)
        except Exception as exc:  # pragma: no cover - assertion reports detail
            result['error'] = exc

    reader = threading.Thread(target=read_after_resize)
    reader.start()
    assert capture_started.wait(timeout=2)

    session.resize(TerminalGeometry(columns=100, rows=30))
    release_capture.set()
    reader.join(timeout=2)

    assert reader.is_alive() is False
    assert result.get('error') is None
    assert result.get('output') == (
        b'\x1b[?25l\x1b[H\x1b[2Jpane after\r\nprompt$ '
    )


def test_terminal_open_selects_target_pane_before_attach(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _select_tmux_terminal_pane(_target())

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'select-window', '-t', '%42'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'select-pane', '-t', '%42'],
    ]


def test_terminal_attach_env_removes_nested_tmux_and_sets_term(monkeypatch) -> None:
    monkeypatch.setenv('TMUX', '/tmp/outer-tmux,1,0')
    monkeypatch.setenv('TMUX_PANE', '%99')
    monkeypatch.setenv('TERM', 'dumb')

    env = _terminal_client_env()

    assert 'TMUX' not in env
    assert 'TMUX_PANE' not in env
    assert env['TERM'] == 'xterm-256color'


def test_terminal_selects_client_compatible_with_target_server(tmp_path) -> None:
    old_bin = tmp_path / 'old' / 'tmux'
    current_bin = tmp_path / 'current' / 'tmux'
    old_bin.parent.mkdir()
    current_bin.parent.mkdir()
    old_bin.write_text('#!/bin/sh\necho "server exited unexpectedly" >&2\nexit 1\n')
    current_bin.write_text('#!/bin/sh\nexit 0\n')
    old_bin.chmod(0o755)
    current_bin.chmod(0o755)

    resolved = resolve_tmux_binary(
        '/tmp/ccb-test/tmux.sock',
        'ccb-test',
        environ={'PATH': f'{old_bin.parent}:{current_bin.parent}', 'TERM': 'dumb'},
    )

    assert resolved == str(current_bin)


def test_terminal_literal_input_targets_pane(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _send_tmux_terminal_literal(_target(), 'hello')

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', '-l', 'hello']
    ]


def test_terminal_control_bytes_target_pane(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = _target()

    _send_tmux_terminal_bytes(target, b'\r')
    _send_tmux_terminal_bytes(target, b'\t')
    _send_tmux_terminal_bytes(target, b'\x1b')

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Enter'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Tab'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Escape'],
    ]


def test_terminal_navigation_bytes_target_pane(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = _target()

    _send_tmux_terminal_bytes(target, b'\x1b[A')
    _send_tmux_terminal_bytes(target, b'\x1b[B')
    _send_tmux_terminal_bytes(target, b'\x1b[C')
    _send_tmux_terminal_bytes(target, b'\x1b[D')
    _send_tmux_terminal_bytes(target, b'\x1b[H')
    _send_tmux_terminal_bytes(target, b'\x1b[F')
    _send_tmux_terminal_bytes(target, b'\x1b[3~')
    _send_tmux_terminal_bytes(target, b'\x1b[5~')
    _send_tmux_terminal_bytes(target, b'\x1b[6~')

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Up'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Down'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Right'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Left'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Home'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'End'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Delete'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'PageUp'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'PageDown'],
    ]


def test_terminal_common_ctrl_bytes_target_pane(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = _target()

    _send_tmux_terminal_bytes(target, b'\x03')
    _send_tmux_terminal_bytes(target, b'\x04')
    _send_tmux_terminal_bytes(target, b'\x15')
    _send_tmux_terminal_bytes(target, b'\x0c')

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'C-c'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'C-d'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'C-u'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'C-l'],
    ]


def test_terminal_unsupported_control_bytes_fail_closed(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    with pytest.raises(RuntimeError, match='unsupported terminal input bytes'):
        _send_tmux_terminal_bytes(_target(), b'\x1b[999~')

    assert calls == []


def test_terminal_protocol_reports_are_ignored_not_written_to_pane(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _send_tmux_terminal_bytes(
        _target(),
        b'\x1b[?1;2c'
        b'\x1b[>0;0;0c'
        b'\x1bP!|00000000\x1b\\'
        b'\x1b[0n'
        b'\x1b[12;40R'
        b'\x1b[8;24;80t'
        b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\',
    )

    assert calls == []


def test_terminal_decoded_bytes_fall_back_to_literal_pane_input(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _send_tmux_terminal_bytes(_target(), '你好'.encode('utf-8'))

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', '-l', '你好']
    ]
