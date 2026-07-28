from __future__ import annotations

from dataclasses import dataclass, replace
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import threading
import time
import unicodedata
from typing import Mapping


MOBILE_TERMINAL_INITIAL_HISTORY_LINES = 1000


@dataclass(frozen=True)
class TerminalGeometry:
    columns: int = 80
    rows: int = 24
    pixel_width: int = 0
    pixel_height: int = 0

    @classmethod
    def from_mapping(cls, value: object) -> 'TerminalGeometry':
        payload = value if isinstance(value, Mapping) else {}
        return cls(
            columns=_positive_int(payload.get('columns'), 80),
            rows=_positive_int(payload.get('rows'), 24),
            pixel_width=max(0, _int(payload.get('pixel_width'), 0)),
            pixel_height=max(0, _int(payload.get('pixel_height'), 0)),
        )


@dataclass(frozen=True)
class TerminalAttachTarget:
    terminal_id: str
    socket_path: str
    session_name: str
    pane_id: str | None
    geometry: TerminalGeometry
    target_summary: dict[str, object]
    tmux_binary: str = 'tmux'
    include_history: bool = True

    @property
    def command(self) -> list[str]:
        return _tmux_capture_command(self, self.geometry)


@dataclass(frozen=True)
class TerminalHistoryTarget:
    project_id: str
    namespace_epoch: int
    agent: str
    window: str
    pane_id: str
    socket_path: str
    session_name: str
    max_lines: int = 200
    tmux_binary: str = 'tmux'

    @property
    def command(self) -> list[str]:
        return [
            self.tmux_binary,
            '-S',
            self.socket_path,
            'capture-pane',
            '-p',
            '-t',
            self.pane_id,
            '-S',
            f'-{max(1, int(self.max_lines))}',
        ]


@dataclass(frozen=True)
class PaneMessageTarget:
    project_id: str
    namespace_epoch: int
    agent: str
    window: str
    pane_id: str
    socket_path: str
    session_name: str
    tmux_binary: str = 'tmux'


def capture_tmux_pane_text(
    target: TerminalHistoryTarget,
    *,
    timeout: float = 2.0,
) -> str:
    target = _with_compatible_tmux(target)
    cp = subprocess.run(
        target.command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=max(0.05, float(timeout)),
        env=_terminal_client_env(),
    )
    if cp.returncode != 0:
        message = (cp.stderr or '').strip() or 'tmux capture-pane failed'
        raise RuntimeError(message)
    return _strip_ansi(cp.stdout or '')


def create_tmux_terminal_history(target: TerminalHistoryTarget) -> dict[str, object]:
    text = capture_tmux_pane_text(target)
    return {
        'agent': target.agent,
        'history_scope': 'tmux_scrollback',
        'source_pane_id': target.pane_id,
        'stale': False,
        'blocks': _readable_history_blocks(text),
    }


def send_tmux_pane_message(target: PaneMessageTarget, text: str) -> dict[str, object]:
    target = _with_compatible_tmux(target)
    message = str(text or '')
    _tmux_run(target, ['send-keys', '-t', target.pane_id, 'C-u'])
    _tmux_run(target, ['send-keys', '-t', target.pane_id, '-l', message])
    _tmux_run(target, ['send-keys', '-t', target.pane_id, 'Enter'])
    return {
        'project_id': target.project_id,
        'agent': target.agent,
        'window': target.window,
        'pane_id': target.pane_id,
        'namespace_epoch': target.namespace_epoch,
    }


def _tmux_run(
    target: PaneMessageTarget,
    args: list[str],
) -> None:
    cp = subprocess.run(
        [target.tmux_binary, '-S', target.socket_path, *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=2.0,
        env=_terminal_client_env(),
    )
    if cp.returncode != 0:
        message = (cp.stderr or '').strip() or 'tmux send failed'
        raise RuntimeError(message)


class TmuxTerminalSession:
    def __init__(self, target: TerminalAttachTarget) -> None:
        self.target = target
        self._geometry = target.geometry
        self._closed = False
        self._last_snapshot: bytes | None = None
        self._initial_read_complete = False
        self._snapshot_generation = 0
        self._state_lock = threading.Lock()
        if not target.pane_id:
            raise RuntimeError('terminal target pane evidence is required')

    def read(self, timeout_seconds: float = 0.1) -> bytes | None:
        with self._state_lock:
            if self._closed:
                return None
            initial_read_complete = self._initial_read_complete
        if initial_read_complete:
            time.sleep(max(0.0, min(float(timeout_seconds), 0.25)))
        with self._state_lock:
            if self._closed:
                return None
            initial_read = not self._initial_read_complete
            if initial_read:
                self._initial_read_complete = True
            geometry = self._geometry
            previous = self._last_snapshot
            snapshot_generation = self._snapshot_generation
        if initial_read:
            if not self.target.include_history:
                snapshot = _capture_tmux_terminal_pane(
                    self.target,
                    geometry,
                    include_history=False,
                )
                with self._state_lock:
                    if self._closed:
                        return None
                    self._last_snapshot = snapshot
                return _render_terminal_snapshot(snapshot, clear_scrollback=True)
            history = _capture_tmux_terminal_pane(
                self.target,
                geometry,
                include_history=True,
            )
            snapshot = _capture_tmux_terminal_pane(
                self.target,
                geometry,
                include_history=False,
            )
            with self._state_lock:
                if self._closed:
                    return None
                self._last_snapshot = snapshot
            return _render_terminal_snapshot(history, clear_scrollback=True)
        if previous is None:
            snapshot = _capture_tmux_terminal_pane(
                self.target,
                geometry,
                include_history=False,
            )
            with self._state_lock:
                if self._closed:
                    return None
                self._last_snapshot = snapshot
            return _render_terminal_snapshot(snapshot)
        snapshot = _capture_tmux_terminal_pane(
            self.target,
            geometry,
            include_history=False,
        )
        with self._state_lock:
            if self._closed:
                return None
            if snapshot_generation != self._snapshot_generation:
                self._last_snapshot = snapshot
                return _render_terminal_snapshot(snapshot)
            if snapshot == previous:
                return b''
            self._last_snapshot = snapshot
            return _render_terminal_delta(
                previous,
                snapshot,
                columns=geometry.columns,
                rows=geometry.rows,
            )

    def write(self, data: bytes) -> None:
        if not data:
            return
        if self.target.pane_id:
            _send_tmux_terminal_bytes(self.target, data)
            return
        os.write(self._master_fd, data)

    def paste(self, text: str) -> None:
        if self.target.pane_id:
            _send_tmux_terminal_literal(self.target, str(text or ''))
            return
        self.write(str(text).encode('utf-8'))

    def resize(self, geometry: TerminalGeometry) -> None:
        with self._state_lock:
            self._geometry = geometry
            self._last_snapshot = None
            self._snapshot_generation += 1

    def close(self) -> None:
        with self._state_lock:
            self._closed = True

    def _resize(self, geometry: TerminalGeometry) -> None:
        rows = max(1, int(geometry.rows))
        columns = max(1, int(geometry.columns))
        pixels_y = max(0, int(geometry.pixel_height))
        pixels_x = max(0, int(geometry.pixel_width))
        packed = struct.pack('HHHH', rows, columns, pixels_y, pixels_x)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, packed)


def create_tmux_terminal_session(target: TerminalAttachTarget) -> TmuxTerminalSession:
    return TmuxTerminalSession(_with_compatible_tmux(target))


def _terminal_client_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    if not env.get('TERM') or env.get('TERM') == 'dumb':
        env['TERM'] = 'xterm-256color'
    return env


def resolve_tmux_binary(
    socket_path: str,
    session_name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = _terminal_client_env(environ)
    candidates: list[str] = []
    seen: set[str] = set()
    for directory in os.get_exec_path(env):
        candidate = os.path.join(directory, 'tmux')
        if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
            continue
        identity = os.path.realpath(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(candidate)

    failures: list[str] = []
    for candidate in candidates:
        try:
            cp = subprocess.run(
                [
                    candidate,
                    '-S',
                    socket_path,
                    'has-session',
                    '-t',
                    session_name,
                ],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=2.0,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f'{candidate}: {exc}')
            continue
        if cp.returncode == 0:
            return candidate
        failures.append(f'{candidate}: {(cp.stderr or "").strip() or "incompatible"}')

    detail = '; '.join(failures) or 'no executable tmux found in PATH'
    raise RuntimeError(f'no compatible tmux client for {session_name}: {detail}')


def _with_compatible_tmux(target):
    return replace(
        target,
        tmux_binary=resolve_tmux_binary(target.socket_path, target.session_name),
    )


def _tmux_capture_command(
    target: TerminalAttachTarget,
    geometry: TerminalGeometry,
    *,
    include_history: bool = True,
) -> list[str]:
    pane_id = str(target.pane_id or '').strip()
    if not pane_id:
        raise RuntimeError('terminal target pane evidence is required')
    history_lines = max(
        MOBILE_TERMINAL_INITIAL_HISTORY_LINES,
        max(1, int(geometry.rows)),
    )
    command = [
        target.tmux_binary,
        '-S',
        target.socket_path,
        'capture-pane',
        '-p',
        '-e',
        '-t',
        pane_id,
    ]
    if include_history:
        command.extend(('-S', f'-{history_lines}'))
    return command


def _capture_tmux_terminal_pane(
    target: TerminalAttachTarget,
    geometry: TerminalGeometry,
    *,
    include_history: bool,
) -> bytes:
    cp = subprocess.run(
        _tmux_capture_command(
            target,
            geometry,
            include_history=include_history,
        ),
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=2.0,
        env=_terminal_client_env(),
    )
    if cp.returncode != 0:
        message = (cp.stderr or b'').decode('utf-8', errors='replace').strip()
        raise RuntimeError(message or 'tmux capture-pane failed')
    return bytes(cp.stdout or b'')


def _render_terminal_snapshot(
    snapshot: bytes,
    *,
    clear_scrollback: bool = False,
) -> bytes:
    text = snapshot.decode('utf-8', errors='replace').rstrip('\n')
    rendered = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
    clear = b'\x1b[3J' if clear_scrollback else b''
    return b'\x1b[?25l' + clear + b'\x1b[H\x1b[2J' + rendered.encode('utf-8')


def _render_terminal_delta(
    previous: bytes,
    snapshot: bytes,
    *,
    columns: int,
    rows: int,
) -> bytes:
    previous_lines = _terminal_snapshot_lines(previous)
    snapshot_lines = _terminal_snapshot_lines(snapshot)
    first_changed = _first_changed_terminal_line(previous_lines, snapshot_lines)
    if first_changed is None:
        return b''
    previous_visual_rows = _terminal_visual_rows(previous_lines, columns)
    snapshot_visual_rows = _terminal_visual_rows(snapshot_lines, columns)
    if previous_visual_rows > rows or snapshot_visual_rows > rows:
        return _render_terminal_snapshot(snapshot, clear_scrollback=True)
    start_row = _terminal_visual_rows(previous_lines[:first_changed], columns) + 1
    suffix = '\r\n'.join(snapshot_lines[first_changed:]).encode('utf-8')
    return (
        b'\x1b[?25l\x1b[0m'
        + f'\x1b[{start_row};1H\x1b[0J'.encode('ascii')
        + suffix
        + b'\x1b[0m'
    )


def _terminal_snapshot_lines(snapshot: bytes) -> list[str]:
    text = snapshot.decode('utf-8', errors='replace')
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
    return normalized.split('\n') if normalized else []


def _first_changed_terminal_line(
    previous_lines: list[str],
    snapshot_lines: list[str],
) -> int | None:
    for index, (before, after) in enumerate(zip(previous_lines, snapshot_lines)):
        if before != after:
            return index
    if len(previous_lines) != len(snapshot_lines):
        return min(len(previous_lines), len(snapshot_lines))
    return None


def _terminal_visual_rows(lines: list[str], columns: int) -> int:
    width = max(1, int(columns))
    rows = 0
    for line in lines:
        display_width = _terminal_display_width(_strip_ansi(line))
        rows += max(1, (display_width + width - 1) // width)
    return rows


def _terminal_display_width(text: str) -> int:
    width = 0
    for character in text:
        if unicodedata.combining(character):
            continue
        if unicodedata.category(character).startswith('C'):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {'F', 'W'} else 1
    return width


def _select_tmux_terminal_pane(target: TerminalAttachTarget) -> None:
    _tmux_terminal_run(target, ['select-window', '-t', str(target.pane_id)])
    _tmux_terminal_run(target, ['select-pane', '-t', str(target.pane_id)])


def _send_tmux_terminal_literal(target: TerminalAttachTarget, text: str) -> None:
    if not text:
        return
    _tmux_terminal_run(target, ['send-keys', '-t', str(target.pane_id), '-l', text])


def _send_tmux_terminal_bytes(target: TerminalAttachTarget, data: bytes) -> None:
    key_names = {
        b'\r': 'Enter',
        b'\n': 'Enter',
        b'\t': 'Tab',
        b'\x1b': 'Escape',
        b'\x01': 'C-a',
        b'\x03': 'C-c',
        b'\x04': 'C-d',
        b'\x05': 'C-e',
        b'\x0b': 'C-k',
        b'\x0c': 'C-l',
        b'\x12': 'C-r',
        b'\x15': 'C-u',
        b'\x17': 'C-w',
        b'\x1a': 'C-z',
        b'\x7f': 'BSpace',
        b'\b': 'BSpace',
        b'\x1b[A': 'Up',
        b'\x1b[B': 'Down',
        b'\x1b[C': 'Right',
        b'\x1b[D': 'Left',
        b'\x1b[H': 'Home',
        b'\x1b[F': 'End',
        b'\x1bOH': 'Home',
        b'\x1bOF': 'End',
        b'\x1b[1~': 'Home',
        b'\x1b[4~': 'End',
        b'\x1b[3~': 'Delete',
        b'\x1b[5~': 'PageUp',
        b'\x1b[6~': 'PageDown',
    }
    key = key_names.get(data)
    if key is not None:
        _tmux_terminal_run(target, ['send-keys', '-t', str(target.pane_id), key])
        return
    if _is_terminal_protocol_response(data):
        return
    if _has_control_byte(data):
        raise RuntimeError(f'unsupported terminal input bytes for {target.terminal_id}')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise RuntimeError(f'unsupported terminal input bytes for {target.terminal_id}')
    _send_tmux_terminal_literal(target, text)


def _has_control_byte(data: bytes) -> bool:
    return any(byte < 0x20 or byte == 0x7F for byte in data)


_TERMINAL_PROTOCOL_RESPONSES = (
    re.compile(r'\x1b\[\?[0-9;]*c'),  # primary device attributes
    re.compile(r'\x1b\[>[0-9;]*c'),  # secondary device attributes
    re.compile(r'\x1bP!\|[0-9A-Fa-f]*\x1b\\'),  # tertiary device attributes
    re.compile(r'\x1b\[0n'),  # operating status
    re.compile(r'\x1b\[[0-9;]*R'),  # cursor position report
    re.compile(r'\x1b\[8;[0-9]+;[0-9]+t'),  # terminal size report
    re.compile(r'\x1b\[[IO]'),  # focus in/out
    re.compile(r'\x1b\[<[0-9;]+[mM]'),  # SGR mouse report
    re.compile(r'\x1b\]1[01];(?:rgb:)?[0-9A-Fa-f/]+(?:\x07|\x1b\\)'),  # OSC colors
)


def _is_terminal_protocol_response(data: bytes) -> bool:
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    index = 0
    while index < len(text):
        for pattern in _TERMINAL_PROTOCOL_RESPONSES:
            match = pattern.match(text, index)
            if match is not None:
                index = match.end()
                break
        else:
            return False
    return bool(text)


def _tmux_terminal_run(
    target: TerminalAttachTarget,
    args: list[str],
) -> None:
    cp = subprocess.run(
        [target.tmux_binary, '-S', target.socket_path, *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=2.0,
        env=_terminal_client_env(),
    )
    if cp.returncode != 0:
        message = (cp.stderr or '').strip() or 'tmux terminal input failed'
        raise RuntimeError(message)


def _readable_history_blocks(text: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    current_type = ''
    current: list[str] = []

    def flush() -> None:
        nonlocal current_type, current
        rendered = '\n'.join(line.rstrip() for line in current).strip()
        if not rendered:
            current_type = ''
            current = []
            return
        block_type = current_type or _classify_line(rendered)
        blocks.append(
            {
                'id': f'history-{len(blocks) + 1}',
                'type': block_type,
                'title': _block_title(block_type),
                'text': rendered,
            }
        )
        current_type = ''
        current = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        line_type = _classify_line(line)
        if current and line_type != current_type and line_type in {'command', 'diff', 'error'}:
            flush()
        if not current:
            current_type = line_type
        current.append(line)
    flush()
    return blocks


def _classify_line(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(('$ ', '> ', '# ')):
        return 'command'
    if stripped.startswith(('Traceback ', 'Error:', 'ERROR:', 'Exception:', 'FAILED')):
        return 'error'
    if stripped.startswith(('diff --git ', '+++ ', '--- ', '+ ', '- ', '@@ ')):
        return 'diff'
    if stripped.startswith(('```', 'def ', 'class ', 'import ', 'from ', 'const ', 'final ', 'Future<')):
        return 'code'
    return 'log'


def _block_title(block_type: str) -> str:
    return {
        'command': 'Command',
        'code': 'Code',
        'diff': 'Diff',
        'error': 'Error',
    }.get(block_type, 'Log')


def _strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)


def _int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _positive_int(value: object, fallback: int) -> int:
    return max(1, _int(value, fallback))
