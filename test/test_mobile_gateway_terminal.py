from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from mobile_gateway.terminal import (
    HostTerminalManager,
    TerminalAttachTarget,
    TerminalGeometry,
    TmuxTerminalSession,
    _capture_tmux_pane_window_state,
    _fit_terminal_snapshot,
    _send_tmux_terminal_bytes,
    _send_tmux_terminal_literal,
    _select_tmux_terminal_pane,
    _terminal_client_env,
    resolve_tmux_binary,
)


@pytest.mark.skipif(
    os.name == 'nt' or shutil.which('tmux') is None,
    reason='host terminal requires tmux on a POSIX host',
)
def test_host_terminal_manager_opens_isolated_persistent_home_shells(
    tmp_path: Path,
) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    manager = HostTerminalManager(tmp_path / 'mobile', home_dir=home)
    first = manager.attach_target(
        terminal_id='term-1',
        device_id='phone-a',
        client_session_id='shell-1',
        display_name='Shell 1',
        geometry=TerminalGeometry(columns=90, rows=24),
        include_history=True,
    )
    second = manager.attach_target(
        terminal_id='term-2',
        device_id='phone-a',
        client_session_id='shell-2',
        display_name='Shell 2',
        geometry=TerminalGeometry(columns=100, rows=30),
        include_history=True,
    )
    marker = tmp_path / 'pwd.txt'
    try:
        assert first.session_name != second.session_name
        assert first.socket_path == second.socket_path
        reopened = manager.attach_target(
            terminal_id='term-3',
            device_id='phone-a',
            client_session_id='shell-1',
            display_name='Shell 1',
            geometry=TerminalGeometry(columns=80, rows=20),
            include_history=False,
        )
        assert reopened.session_name == first.session_name
        assert reopened.pane_id == first.pane_id

        _send_tmux_terminal_literal(first, f'pwd > {shlex.quote(str(marker))}')
        _send_tmux_terminal_bytes(first, b'\r')
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text(encoding='utf-8').strip() == str(home)

        assert manager.terminate(
            device_id='phone-a',
            client_session_id='shell-1',
        ) is True
        still_open = manager.attach_target(
            terminal_id='term-4',
            device_id='phone-a',
            client_session_id='shell-2',
            display_name='Shell 2',
            geometry=TerminalGeometry(),
            include_history=False,
        )
        assert still_open.session_name == second.session_name
    finally:
        manager.terminate(device_id='phone-a', client_session_id='shell-1')
        manager.terminate(device_id='phone-a', client_session_id='shell-2')


def test_host_terminal_manager_rejects_slots_above_limit(tmp_path: Path) -> None:
    manager = HostTerminalManager(tmp_path / 'mobile', max_sessions=2)

    with pytest.raises(RuntimeError, match='shell-1 through shell-2'):
        manager.attach_target(
            terminal_id='term-3',
            device_id='phone-a',
            client_session_id='shell-3',
            display_name='Shell 3',
            geometry=TerminalGeometry(),
            include_history=True,
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
        if 'display-message' in command:
            return SimpleNamespace(returncode=0, stdout=b'1\n', stderr=b'')
        output = (
            b'pane history\n'
            if '-E' in command
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
            'display-message',
            '-p',
            '-t',
            '%42',
            '#{history_size}',
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
            '-J',
            '-S',
            '-1000',
            '-E',
            '-1',
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
            '-J',
        ],
    ]


def test_source_terminal_repaints_visible_pane_for_client_side_reflow(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    visible_outputs = iter((b'pane only\nprompt$ ', b'pane changed\nprompt$ '))

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if 'display-message' in command:
            return SimpleNamespace(returncode=0, stdout=b'1\n', stderr=b'')
        if '-E' in command:
            output = b'real history\n'
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
    assert second == b'\x1b[?25l\x1b[H\x1b[2Jpane changed\r\nprompt$ '
    assert sum(command.count('-S') > 1 for command in calls) == 1
    assert len(calls) == 4
    assert all(
        '-J' in command for command in calls if 'capture-pane' in command
    )


def test_source_terminal_projection_replaces_edits_and_appends_only_scrolled_rows(
    monkeypatch,
) -> None:
    visible_outputs = iter(
        (
            b'line one\nline two\nprompt$ xxxxx',
            b'line one\nline two\nprompt$ xxxx',
            b'line two\nprompt$ xxxx\nnew output',
        )
    )

    def fake_run(command, **kwargs):
        if 'display-message' in command:
            return SimpleNamespace(returncode=0, stdout=b'1\n', stderr=b'')
        output = b'older history\n' if '-E' in command else next(visible_outputs)
        return SimpleNamespace(returncode=0, stdout=output, stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    session = TmuxTerminalSession(_target())

    session.read(0)
    assert session.take_output_projection() == {
        'history_reset': True,
        'history': b'older history\n',
        'screen': b'line one\nline two\nprompt$ xxxxx',
    }

    session.read(0)
    assert session.take_output_projection() == {
        'screen': b'line one\nline two\nprompt$ xxxx',
    }

    session.read(0)
    assert session.take_output_projection() == {
        'screen': b'line two\nprompt$ xxxx\nnew output',
        'history_append': b'line one\n',
    }


def test_source_terminal_projection_does_not_duplicate_screen_without_history(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if 'display-message' in command:
            return SimpleNamespace(returncode=0, stdout=b'0\n', stderr=b'')
        return SimpleNamespace(
            returncode=0,
            stdout=b'prompt$ abc',
            stderr=b'',
        )

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    session = TmuxTerminalSession(_target())

    rendered = session.read(0)

    assert rendered is not None
    assert rendered.count(b'prompt$ abc') == 1
    assert session.take_output_projection() == {
        'history_reset': True,
        'history': b'',
        'screen': b'prompt$ abc',
    }
    assert sum('capture-pane' in command for command in calls) == 1


def test_terminal_delta_preserves_complete_source_rows(monkeypatch) -> None:
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
        geometry=TerminalGeometry(columns=8, rows=10),
        target_summary={'kind': 'host_shell', 'project_id': '@host'},
    )
    session = TmuxTerminalSession(target)

    session.read(0)
    output = session.read(0)

    assert output == b'\x1b[?25l\x1b[0m\x1b[2;1H\x1b[0Jafter\x1b[0m'


def test_terminal_delta_repaints_when_source_rows_exceed_source_viewport(
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
        target_summary={'kind': 'host_shell', 'project_id': '@host'},
    )
    session = TmuxTerminalSession(target)

    session.read(0)
    output = session.read(0)

    assert output == (
        b'\x1b[?25l\x1b[3J\x1b[H\x1b[2J12345678\r\nafter'
    )


def test_terminal_snapshot_normalization_preserves_ansi_and_wide_characters() -> None:
    snapshot = (
        '\x1b[36m状态 OK and trailing text\x1b[0m\n'
        'short'
    ).encode()

    fitted = _fit_terminal_snapshot(snapshot, 9)

    assert fitted == snapshot


def test_terminal_snapshot_trims_join_padding_but_keeps_prompt_cursor_space() -> None:
    snapshot = b'joined row   \x1b[0m\nprompt$ '

    assert _fit_terminal_snapshot(snapshot, 80) == (
        b'joined row \x1b[0m\nprompt$ '
    )


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


def test_agent_terminal_reports_fixed_source_geometry_and_ignores_resize(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        'mobile_gateway.terminal._capture_tmux_pane_geometry',
        lambda target: TerminalGeometry(columns=164, rows=47),
    )
    session = TmuxTerminalSession(
        replace(_target(), geometry=TerminalGeometry(columns=42, rows=20))
    )

    assert session.viewport_state() == {
        'revision': 1,
        'geometry': {
            'columns': 164,
            'rows': 47,
            'pixel_width': 0,
            'pixel_height': 0,
        },
        'resize_policy': 'fixed_source',
    }

    session.resize(TerminalGeometry(columns=36, rows=16))
    assert session.viewport_state()['geometry'] == {
        'columns': 164,
        'rows': 47,
        'pixel_width': 0,
        'pixel_height': 0,
    }


@pytest.mark.skipif(
    os.name == 'nt' or shutil.which('tmux') is None,
    reason='fixed source pane geometry requires tmux on a POSIX host',
)
def test_agent_terminal_never_changes_desktop_layout(
    tmp_path: Path,
) -> None:
    tmux = str(shutil.which('tmux'))
    socket_path = tmp_path / 'fixed-source.sock'
    session_name = 'fixed-source-mobile'

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [tmux, '-S', str(socket_path), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=3,
            env=_terminal_client_env(),
        )

    run('new-session', '-d', '-s', session_name, '-x', '120', '-y', '40')
    terminal_session = None
    second_terminal_session = None
    try:
        run('split-window', '-h', '-l', '12', '-t', session_name)
        panes = run(
            'list-panes',
            '-t',
            session_name,
            '-F',
            '#{pane_id}\t#{pane_width}',
        ).stdout.splitlines()
        pane_id = max(panes, key=lambda value: int(value.split('\t')[1])).split(
            '\t',
        )[0]
        target = TerminalAttachTarget(
            terminal_id='fixed-source-real',
            socket_path=str(socket_path),
            session_name=session_name,
            pane_id=pane_id,
            geometry=TerminalGeometry(columns=51, rows=24),
            target_summary={
                'project_id': 'proj-test',
                'agent': 'lead',
                'pane_id': pane_id,
            },
            tmux_binary=tmux,
            include_history=False,
        )
        before = _capture_tmux_pane_window_state(target)
        terminal_session = TmuxTerminalSession(target)

        opened = terminal_session.viewport_state()
        assert opened['resize_policy'] == 'fixed_source'
        assert opened['geometry']['columns'] == before.pane_columns
        assert opened['geometry']['rows'] == before.pane_rows

        terminal_session.resize(TerminalGeometry(columns=72, rows=20))
        while_open = _capture_tmux_pane_window_state(target)
        assert while_open == before

        second_terminal_session = TmuxTerminalSession(
            replace(
                target,
                terminal_id='fixed-source-real-second',
                geometry=TerminalGeometry(columns=44, rows=18),
            )
        )
        second_viewport = second_terminal_session.viewport_state()
        assert second_viewport['resize_policy'] == 'fixed_source'
        second_active = _capture_tmux_pane_window_state(target)
        assert second_active == before

        second_terminal_session.close()
        second_terminal_session = None
        after_second_close = _capture_tmux_pane_window_state(target)
        assert after_second_close == before

        terminal_session.close()
        terminal_session = None
        restored = _capture_tmux_pane_window_state(target)
        assert restored == before
    finally:
        if second_terminal_session is not None:
            second_terminal_session.close()
        if terminal_session is not None:
            terminal_session.close()
        subprocess.run(
            [tmux, '-S', str(socket_path), 'kill-server'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
            env=_terminal_client_env(),
        )


@pytest.mark.skipif(
    os.name == 'nt' or shutil.which('tmux') is None,
    reason='terminal projection requires tmux on a POSIX host',
)
def test_agent_terminal_projection_joins_wraps_and_replaces_prompt_edits(
    tmp_path: Path,
) -> None:
    tmux = str(shutil.which('tmux'))
    socket_path = tmp_path / 'projection-source.sock'
    session_name = 'projection-source-mobile'

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [tmux, '-S', str(socket_path), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=3,
            env=_terminal_client_env(),
        )

    run(
        'new-session',
        '-d',
        '-s',
        session_name,
        '-x',
        '24',
        '-y',
        '8',
        (
            "env BASH_SILENCE_DEPRECATION_WARNING=1 "
            "PS1='probe$ ' bash --noprofile --norc -i"
        ),
    )
    terminal_session = None
    try:
        pane_id = run(
            'display-message',
            '-p',
            '-t',
            session_name,
            '#{pane_id}',
        ).stdout.strip()
        time.sleep(0.15)
        before = run(
            'display-message',
            '-p',
            '-t',
            pane_id,
            '#{pane_width}x#{pane_height}:#{window_layout}',
        ).stdout.strip()
        target = TerminalAttachTarget(
            terminal_id='projection-source-real',
            socket_path=str(socket_path),
            session_name=session_name,
            pane_id=pane_id,
            geometry=TerminalGeometry(columns=24, rows=8),
            target_summary={
                'project_id': 'proj-test',
                'agent': 'lead',
                'pane_id': pane_id,
            },
            tmux_binary=tmux,
            include_history=True,
        )
        terminal_session = TmuxTerminalSession(target)
        terminal_session.viewport_state()

        run('send-keys', '-t', pane_id, '-l', 'abcdefghijklmnopqrstuvwxyz0123456789')
        time.sleep(0.15)
        terminal_session.read(0)
        initial = terminal_session.take_output_projection()

        assert initial is not None
        assert initial['history'] == b''
        assert b'probe$ abcdefghijklmnopqrstuvwxyz0123456789' in initial['screen']
        assert bytes(initial['screen']).count(b'probe$ ') == 1

        run('send-keys', '-t', pane_id, 'BSpace', 'BSpace', 'BSpace')
        time.sleep(0.15)
        terminal_session.read(0)
        edited = terminal_session.take_output_projection()

        assert edited is not None
        assert 'history_append' not in edited
        assert b'probe$ abcdefghijklmnopqrstuvwxyz0123456' in edited['screen']
        assert b'0123456789' not in edited['screen']
        after = run(
            'display-message',
            '-p',
            '-t',
            pane_id,
            '#{pane_width}x#{pane_height}:#{window_layout}',
        ).stdout.strip()
        assert after == before
    finally:
        if terminal_session is not None:
            terminal_session.close()
        subprocess.run(
            [tmux, '-S', str(socket_path), 'kill-server'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
            env=_terminal_client_env(),
        )


def test_host_terminal_resize_updates_owned_tmux_session(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)
    target = replace(
        _target(),
        target_summary={'kind': 'host_shell', 'project_id': '@host'},
    )
    session = TmuxTerminalSession(target)

    session.resize(TerminalGeometry(columns=92, rows=31))

    assert calls == [[
        'tmux',
        '-S',
        '/tmp/ccb-test/tmux.sock',
        'resize-window',
        '-t',
        'ccb-test',
        '-x',
        '92',
        '-y',
        '31',
    ]]
    assert session.viewport_state()['resize_policy'] == 'client'
    assert session.viewport_state()['geometry']['columns'] == 92


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
    suffix = '.cmd' if os.name == 'nt' else ''
    old_bin = tmp_path / 'old' / f'tmux{suffix}'
    current_bin = tmp_path / 'current' / f'tmux{suffix}'
    old_bin.parent.mkdir()
    current_bin.parent.mkdir()
    if os.name == 'nt':
        old_bin.write_text('@echo off\necho server exited unexpectedly 1>&2\nexit /b 1\n')
        current_bin.write_text('@echo off\nexit /b 0\n')
    else:
        old_bin.write_text('#!/bin/sh\necho "server exited unexpectedly" >&2\nexit 1\n')
        current_bin.write_text('#!/bin/sh\nexit 0\n')
    old_bin.chmod(0o755)
    current_bin.chmod(0o755)

    resolved = resolve_tmux_binary(
        '/tmp/ccb-test/tmux.sock',
        'ccb-test',
        environ={'PATH': os.pathsep.join((str(old_bin.parent), str(current_bin.parent))), 'TERM': 'dumb'},
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


def test_terminal_text_and_enter_in_one_frame_target_pane_in_order(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _send_tmux_terminal_bytes(_target(), b'test2\r')

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', '-l', 'test2'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Enter'],
    ]


def test_terminal_mixed_unicode_text_and_keys_preserve_frame_order(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    _send_tmux_terminal_bytes(_target(), '你好\t世界\r\n'.encode('utf-8'))

    assert calls == [
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', '-l', '你好'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Tab'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', '-l', '世界'],
        ['tmux', '-S', '/tmp/ccb-test/tmux.sock', 'send-keys', '-t', '%42', 'Enter'],
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


def test_terminal_mixed_frame_is_fully_validated_before_pane_input(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr('mobile_gateway.terminal.subprocess.run', fake_run)

    with pytest.raises(RuntimeError, match='unsupported terminal input bytes'):
        _send_tmux_terminal_bytes(_target(), b'not-delivered\x1b[999~')

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
