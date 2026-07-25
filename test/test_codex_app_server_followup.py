from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import struct
import sys
from threading import Event, Thread
from types import SimpleNamespace

from completion.models import CompletionSourceKind
import provider_backends.codex.app_server_followup as app_server_followup
from provider_backends.codex.app_server_followup import steer_active_turn
from provider_backends.codex.bridge_runtime.app_server import ManagedCodexAppServer
from provider_backends.codex.execution import CodexProviderAdapter
from provider_backends.codex.launcher_runtime.command_runtime.managed_app_server import (
    build_managed_app_server_command,
    supports_managed_app_server,
)
from provider_backends.codex.runtime_artifacts import codex_runtime_artifact_layout
from provider_backends.codex.start_cmd_runtime.parsing import extract_resume_session_id
from provider_backends.codex.start_cmd_runtime.rewriting import (
    build_resume_start_cmd,
    strip_resume_start_cmd,
)
from provider_execution.base import ProviderSubmission
from provider_execution.followups import ActiveFollowupRequest
from storage.path_helpers import unix_socket_path_is_safe


def _read_exact(connection: socket.socket, length: int) -> bytes:
    payload = bytearray()
    while len(payload) < length:
        chunk = connection.recv(length - len(payload))
        if not chunk:
            raise AssertionError('test WebSocket connection closed')
        payload.extend(chunk)
    return bytes(payload)


def _receive_client_json(connection: socket.socket) -> dict[str, object]:
    first, second = _read_exact(connection, 2)
    assert first & 0x0F == 0x1
    assert second & 0x80
    length = second & 0x7F
    if length == 126:
        length = struct.unpack('!H', _read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack('!Q', _read_exact(connection, 8))[0]
    mask = _read_exact(connection, 4)
    encoded = _read_exact(connection, length)
    decoded = bytes(value ^ mask[index % 4] for index, value in enumerate(encoded))
    return json.loads(decoded.decode('utf-8'))


def _send_server_json(connection: socket.socket, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload).encode('utf-8')
    header = bytearray([0x81])
    if len(encoded) < 126:
        header.append(len(encoded))
    else:
        header.append(126)
        header.extend(struct.pack('!H', len(encoded)))
    connection.sendall(bytes(header) + encoded)


def _serve_test_websocket(socket_path: Path, ready: Event, seen: list[dict[str, object]]) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    ready.set()
    try:
        connection, _address = server.accept()
        with connection:
            request = bytearray()
            while b'\r\n\r\n' not in request:
                request.extend(connection.recv(4096))
            headers = request.decode('iso-8859-1')
            key_line = next(line for line in headers.split('\r\n') if line.lower().startswith('sec-websocket-key:'))
            key = key_line.split(':', 1)[1].strip()
            accept = base64.b64encode(
                hashlib.sha1(f'{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11'.encode('ascii')).digest()
            ).decode('ascii')
            connection.sendall(
                (
                    'HTTP/1.1 101 Switching Protocols\r\n'
                    'Upgrade: websocket\r\n'
                    'Connection: Upgrade\r\n'
                    f'Sec-WebSocket-Accept: {accept}\r\n\r\n'
                ).encode('ascii')
            )
            initialize = _receive_client_json(connection)
            seen.append(initialize)
            _send_server_json(connection, {'id': initialize['id'], 'result': {'userAgent': 'fake'}})
            seen.append(_receive_client_json(connection))
            steer = _receive_client_json(connection)
            seen.append(steer)
            _send_server_json(connection, {'id': steer['id'], 'result': {'turnId': 'turn_1'}})
    finally:
        server.close()


def test_steer_active_turn_uses_exact_active_turn_precondition_and_idempotency_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def exchange(socket_path, **kwargs):
        captured['socket_path'] = str(socket_path)
        captured.update(kwargs)
        return app_server_followup._WebSocketExchange(
            initialize={'id': 'fup_1:initialize', 'result': {'userAgent': 'codex-test'}},
            steer={'id': 'fup_1:steer', 'result': {'turnId': 'turn_1'}},
        )

    monkeypatch.setattr(app_server_followup, '_websocket_exchange', exchange)
    result = steer_active_turn(
        '/tmp/codex.sock',
        thread_id='thread_1',
        turn_id='turn_1',
        followup_id='fup_1',
        message='correct the current task',
    )

    assert result.accepted is True
    assert captured['socket_path'] == '/tmp/codex.sock'
    wire = [captured['initialize'], captured['initialized'], captured['steer']]
    assert [record['method'] for record in wire] == ['initialize', 'initialized', 'turn/steer']
    assert wire[2]['params'] == {
        'threadId': 'thread_1',
        'expectedTurnId': 'turn_1',
        'input': [{'type': 'text', 'text': 'correct the current task'}],
        'clientUserMessageId': 'fup_1',
    }


def test_steer_active_turn_uses_masked_websocket_frames_over_unix_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / 'app-server.sock'
    ready = Event()
    seen: list[dict[str, object]] = []
    server = Thread(target=_serve_test_websocket, args=(socket_path, ready, seen))
    server.start()
    assert ready.wait(timeout=5)

    result = steer_active_turn(
        socket_path,
        thread_id='thread_1',
        turn_id='turn_1',
        followup_id='fup_1',
        message='correct over WebSocket',
    )
    server.join(timeout=5)

    assert not server.is_alive()
    assert result.accepted is True
    assert [record['method'] for record in seen] == ['initialize', 'initialized', 'turn/steer']
    assert seen[2]['params']['expectedTurnId'] == 'turn_1'


def test_steer_active_turn_fails_closed_on_terminal_or_mismatched_turn(monkeypatch) -> None:
    monkeypatch.setattr(
        app_server_followup,
        '_websocket_exchange',
        lambda *args, **kwargs: app_server_followup._WebSocketExchange(
            initialize={'id': 'fup_1:initialize', 'result': {}},
            steer={
                'id': 'fup_1:steer',
                'error': {'code': -32602, 'message': 'expected turn is not the active turn'},
            }
        ),
    )
    terminal = steer_active_turn(
        '/tmp/codex.sock',
        thread_id='thread_1',
        turn_id='turn_1',
        followup_id='fup_1',
        message='late',
    )
    assert terminal.accepted is False
    assert terminal.reason == 'provider_turn_not_active'

    monkeypatch.setattr(
        app_server_followup,
        '_websocket_exchange',
        lambda *args, **kwargs: app_server_followup._WebSocketExchange(
            initialize={'id': 'fup_1:initialize', 'result': {}},
            steer={'id': 'fup_1:steer', 'result': {'turnId': 'turn_2'}}
        ),
    )
    mismatch = steer_active_turn(
        '/tmp/codex.sock',
        thread_id='thread_1',
        turn_id='turn_1',
        followup_id='fup_1',
        message='wrong turn',
    )
    assert mismatch.accepted is False
    assert mismatch.reason == 'app_server_steer_turn_mismatch'

    monkeypatch.setattr(
        app_server_followup,
        '_websocket_exchange',
        lambda *args, **kwargs: app_server_followup._WebSocketExchange(
            initialize={'id': 'fup_1:initialize', 'result': {}},
            steer={
                'id': 'fup_1:steer',
                'error': {'code': -32600, 'message': 'thread not found: thread_1'},
            },
        ),
    )
    missing = steer_active_turn(
        '/tmp/codex.sock',
        thread_id='thread_1',
        turn_id='turn_1',
        followup_id='fup_1',
        message='missing thread',
    )
    assert missing.accepted is False
    assert missing.reason == 'provider_turn_not_active'


def test_codex_adapter_requires_live_managed_socket_and_exact_bound_turn(tmp_path: Path, monkeypatch) -> None:
    session_id = '12345678-1234-1234-1234-123456789abc'
    session_path = tmp_path / f'rollout-{session_id}.jsonl'
    session_path.write_text('', encoding='utf-8')
    socket_path = tmp_path / 'app-server.sock'
    remote_marker = tmp_path / 'app-server.remote'
    remote_marker.write_text(f'{socket_path}\n', encoding='utf-8')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen()
    monkeypatch.setattr('provider_backends.codex.execution.app_server_socket_ready', lambda path: True)
    submission = ProviderSubmission(
        job_id='job_1',
        agent_name='codex',
        provider='codex',
        accepted_at='2026-07-21T00:00:00Z',
        ready_at='2026-07-21T00:00:00Z',
        source_kind=CompletionSourceKind.PROTOCOL_EVENT_STREAM,
        reply='',
        runtime_state={
            'mode': 'active',
            'anchor_seen': True,
            'bound_turn_id': 'turn_1',
            'session_path': str(session_path),
            'codex_app_server_enabled': True,
            'codex_app_server_socket': str(socket_path),
            'codex_app_server_remote_marker': str(remote_marker),
        },
    )
    adapter = CodexProviderAdapter()
    try:
        capability = adapter.active_followup_capability(submission)
        assert capability.supported is True
        assert capability.provider_turn_ref == f'codex:{session_id}:turn_1'

        monkeypatch.setattr(
            'provider_backends.codex.execution.steer_active_turn',
            lambda *args, **kwargs: SimpleNamespace(
                accepted=True,
                reason='provider_turn_steered',
                error='',
            ),
        )
        injected = adapter.inject_active_followup(
            submission,
            request=ActiveFollowupRequest(
                followup_id='fup_1',
                job_id='job_1',
                message='correct it',
                expected_provider_turn_ref=capability.provider_turn_ref,
            ),
            now='2026-07-21T00:00:01Z',
        )
        assert injected.status == 'injected'
        assert injected.submission.runtime_state['active_followup_ids'] == ['fup_1']

        steer_calls: list[object] = []
        monkeypatch.setattr(
            'provider_backends.codex.execution.steer_active_turn',
            lambda *args, **kwargs: steer_calls.append((args, kwargs)),
        )
        replayed = adapter.inject_active_followup(
            injected.submission,
            request=ActiveFollowupRequest(
                followup_id='fup_1',
                job_id='job_1',
                message='must not send twice',
                expected_provider_turn_ref=capability.provider_turn_ref,
            ),
            now='2026-07-21T00:00:01Z',
        )
        assert replayed.status == 'injected'
        assert replayed.reason == 'provider_turn_steered_idempotent_replay'
        assert steer_calls == []

        changed = adapter.inject_active_followup(
            submission,
            request=ActiveFollowupRequest(
                followup_id='fup_2',
                job_id='job_1',
                message='wrong binding',
                expected_provider_turn_ref=f'codex:{session_id}:turn_old',
            ),
            now='2026-07-21T00:00:02Z',
        )
        assert changed.status == 'terminal'
        assert changed.reason == 'codex_active_turn_binding_changed'
    finally:
        listener.close()

    monkeypatch.setattr('provider_backends.codex.execution.app_server_socket_ready', lambda path: False)
    missing = adapter.active_followup_capability(submission)
    assert missing.supported is False
    assert missing.reason == 'codex_managed_app_server_unavailable'
    legacy = adapter.active_followup_capability(
        ProviderSubmission(
            **{
                **submission.__dict__,
                'runtime_state': {**submission.runtime_state, 'codex_app_server_enabled': False},
            }
        )
    )
    assert legacy.supported is False
    assert legacy.reason == 'codex_legacy_tui_missing_expected_turn_precondition'

    remote_marker.unlink()
    local_fallback = adapter.active_followup_capability(submission)
    assert local_fallback.supported is False
    assert local_fallback.reason == 'codex_managed_remote_tui_unconfirmed'


def test_codex_adapter_keeps_ambiguous_transport_result_durably_accepted(tmp_path: Path, monkeypatch) -> None:
    session_id = '12345678-1234-1234-1234-123456789abc'
    session_path = tmp_path / f'rollout-{session_id}.jsonl'
    session_path.write_text('', encoding='utf-8')
    socket_path = tmp_path / 'app-server.sock'
    remote_marker = tmp_path / 'app-server.remote'
    remote_marker.write_text(f'{socket_path}\n', encoding='utf-8')
    submission = ProviderSubmission(
        job_id='job_1',
        agent_name='codex',
        provider='codex',
        accepted_at='2026-07-21T00:00:00Z',
        ready_at='2026-07-21T00:00:00Z',
        source_kind=CompletionSourceKind.PROTOCOL_EVENT_STREAM,
        reply='',
        runtime_state={
            'mode': 'active',
            'anchor_seen': True,
            'bound_turn_id': 'turn_1',
            'session_path': str(session_path),
            'codex_app_server_enabled': True,
            'codex_app_server_socket': str(socket_path),
            'codex_app_server_remote_marker': str(remote_marker),
        },
    )
    monkeypatch.setattr('provider_backends.codex.execution.app_server_socket_ready', lambda path: True)
    monkeypatch.setattr(
        'provider_backends.codex.execution.steer_active_turn',
        lambda *args, **kwargs: SimpleNamespace(
            accepted=False,
            reason='app_server_websocket_timeout',
            error='',
        ),
    )
    adapter = CodexProviderAdapter()
    capability = adapter.active_followup_capability(submission)
    result = adapter.inject_active_followup(
        submission,
        request=ActiveFollowupRequest(
            followup_id='fup_ambiguous',
            job_id='job_1',
            message='may already be delivered',
            expected_provider_turn_ref=capability.provider_turn_ref,
        ),
        now='2026-07-21T00:00:01Z',
    )
    assert result.status == 'accepted'
    assert result.reason == 'app_server_websocket_timeout'


def test_managed_launcher_preserves_resume_rewrites_and_fallback(tmp_path: Path) -> None:
    session_id = '12345678-1234-1234-1234-123456789abc'
    command, state = build_managed_app_server_command(
        ['codex', '--profile', 'ccb', 'resume', session_id],
        runtime_dir=tmp_path,
    )

    assert state['codex_app_server_command'] == [
        'codex',
        'app-server',
        '--listen',
        f'unix://{tmp_path / "app-server.sock"}',
    ]
    assert state['codex_app_server_remote_marker'] == str(tmp_path / 'app-server.remote')
    assert f'codex --remote unix://{tmp_path / "app-server.sock"} --profile ccb' in command
    assert f"printf '%s\\n' {tmp_path / 'app-server.sock'} > {tmp_path / 'app-server.remote'}" in command
    assert 'else exec codex --profile ccb' in command
    assert extract_resume_session_id(command) == session_id

    rewritten = build_resume_start_cmd(command, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    assert extract_resume_session_id(rewritten) == 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    stripped = strip_resume_start_cmd(rewritten)
    assert extract_resume_session_id(stripped) is None
    assert 'CCB_CODEX_MANAGED_REMOTE=1' in stripped


def test_managed_app_server_capability_probe_is_explicit(monkeypatch) -> None:
    supports_managed_app_server.cache_clear()

    def run(command, **kwargs):
        del kwargs
        if command[-1] == '--version':
            return SimpleNamespace(returncode=0, stdout='codex-cli 0.144.6')
        if command[-1] == '--help' and command[1:] == ['--help']:
            return SimpleNamespace(returncode=0, stdout='usage: codex --remote unix://PATH')
        return SimpleNamespace(returncode=0, stdout='usage: codex app-server --listen unix://PATH')

    monkeypatch.setattr(subprocess, 'run', run)
    assert supports_managed_app_server(('codex',)) is True
    assert supports_managed_app_server(('env', 'codex')) is False


def test_managed_app_server_supervisor_starts_and_stops_exact_child(tmp_path: Path, monkeypatch) -> None:
    socket_path = tmp_path / 'app-server.sock'
    child = (
        'import socket,time; '
        f's=socket.socket(socket.AF_UNIX); s.bind({str(socket_path)!r}); s.listen(); time.sleep(30)'
    )
    monkeypatch.setenv('CCB_CODEX_APP_SERVER_COMMAND_JSON', json.dumps([sys.executable, '-c', child]))
    monkeypatch.setenv('CCB_CODEX_APP_SERVER_SOCKET', str(socket_path))
    supervisor = ManagedCodexAppServer(tmp_path)

    assert supervisor.start() is True
    pid = int((tmp_path / 'app-server.pid').read_text(encoding='utf-8').strip())
    assert pid > 0
    assert socket_path.is_socket()
    supervisor.stop()

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('managed app-server child remained alive after supervisor stop')
    assert not socket_path.exists()
    assert not (tmp_path / 'app-server.pid').exists()
    assert not (tmp_path / 'app-server.remote').exists()


def test_managed_app_server_failed_start_cleans_owned_runtime_artifacts(tmp_path: Path, monkeypatch) -> None:
    socket_path = tmp_path / 'app-server.sock'
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()
    monkeypatch.setenv(
        'CCB_CODEX_APP_SERVER_COMMAND_JSON',
        json.dumps([sys.executable, '-c', 'raise SystemExit(7)']),
    )
    monkeypatch.setenv('CCB_CODEX_APP_SERVER_SOCKET', str(socket_path))

    assert ManagedCodexAppServer(tmp_path).start() is False
    assert not socket_path.exists()
    assert not (tmp_path / 'app-server.pid').exists()

    monkeypatch.setenv(
        'CCB_CODEX_APP_SERVER_COMMAND_JSON',
        json.dumps([str(tmp_path / 'missing-codex'), 'app-server']),
    )
    assert ManagedCodexAppServer(tmp_path).start() is False
    assert not (tmp_path / 'app-server.pid').exists()


def test_managed_app_server_refuses_foreign_socket_path_without_unlinking_it(tmp_path: Path, monkeypatch) -> None:
    foreign_socket = tmp_path / 'foreign.sock'
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(foreign_socket))
    stale.close()
    monkeypatch.setenv(
        'CCB_CODEX_APP_SERVER_COMMAND_JSON',
        json.dumps([sys.executable, '-c', 'raise SystemExit(0)']),
    )
    monkeypatch.setenv('CCB_CODEX_APP_SERVER_SOCKET', str(foreign_socket))

    assert ManagedCodexAppServer(tmp_path / 'runtime').start() is False
    assert foreign_socket.is_socket()


def test_managed_app_server_uses_owned_short_socket_for_long_runtime_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('XDG_RUNTIME_DIR', '/tmp')
    runtime_dir = tmp_path / ('long-runtime-' * 5) / ('nested-' * 5) / 'codex'
    runtime_dir.mkdir(parents=True)
    artifacts = codex_runtime_artifact_layout(runtime_dir)
    assert artifacts.app_server_socket_placement.preferred_path == runtime_dir / 'app-server.sock'
    assert artifacts.app_server_socket_placement.fallback_reason == 'path_too_long'
    assert artifacts.app_server_socket.parent == Path('/tmp/ccb-runtime')
    assert unix_socket_path_is_safe(artifacts.app_server_socket)

    child = (
        'import socket,time; '
        f's=socket.socket(socket.AF_UNIX); s.bind({str(artifacts.app_server_socket)!r}); '
        's.listen(); time.sleep(30)'
    )
    monkeypatch.setenv(
        'CCB_CODEX_APP_SERVER_COMMAND_JSON',
        json.dumps([sys.executable, '-c', child]),
    )
    monkeypatch.setenv('CCB_CODEX_APP_SERVER_SOCKET', str(artifacts.app_server_socket))
    supervisor = ManagedCodexAppServer(runtime_dir)
    assert supervisor.start() is True
    assert artifacts.app_server_socket.is_socket()
    supervisor.stop()
    assert not artifacts.app_server_socket.exists()
