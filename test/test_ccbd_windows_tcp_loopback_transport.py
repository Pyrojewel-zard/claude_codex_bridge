from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib
import json
import re
import socket
import threading
import time

import pytest

from ccbd.api_models import RpcRequest
from ccbd.control_plane_transport.endpoint import endpoint_from_record, endpoint_to_record
from ccbd.control_plane_transport.endpoint_store import (
    endpoint_store_path,
    read_endpoint,
    token_store_path,
    unlink_endpoint,
    write_endpoint,
)
from ccbd.control_plane_transport.factory import connect_endpoint, transport_for_legacy_socket_path
from ccbd.control_plane_transport.token_auth import RpcTransportAuthError, create_token_file, load_token_file, _current_windows_user
from platforms.windows.control_plane.tcp import WindowsTcpControlPlaneTransport
from ccbd.services.lifecycle import build_lifecycle
from ccbd.services.project_inspection import ProjectDaemonInspection
from ccbd.socket_client import CcbdClient, CcbdClientError
from ccbd.socket_client_runtime import decode_response, recv_response_line, send_request
from ccbd.socket_server import CcbdSocketServer
from ccbd.socket_server_runtime.loop import enqueue_connection, start_worker, stop_worker


def _patch_module_os_name(monkeypatch, module_name: str, name: str) -> None:
    module = importlib.import_module(module_name)
    os_proxy = SimpleNamespace(**vars(module.os))
    os_proxy.name = name
    monkeypatch.setattr(module, 'os', os_proxy)


def _ok_runner(command, **kwargs):
    del kwargs
    if command[:3] == ['powershell', '-NoProfile', '-Command']:
        if 'FileStream' in command[3]:
            Path(_ps_literal_value(command[3], 'path')).write_text(
                _ps_literal_value(command[3], 'payload') + '\n',
                encoding='utf-8',
            )
            return SimpleNamespace(returncode=0, stdout='ok', stderr='')
        owner = _current_windows_user() or 'DESKTOP\\User'
        owner_sid = 'S-1-5-21-1'
        if 'WindowsIdentity' in command[3]:
            return SimpleNamespace(returncode=0, stdout=owner_sid, stderr='')
        if 'Get-Acl' in command[3] or 'GetAccessControl' in command[3]:
            payload = {
                'owner': owner,
                'sddl': f'O:{owner_sid}G:{owner_sid}D:',
                'access': [
                    {
                        'identity': owner,
                        'rights': 'Read',
                        'access_type': 'Allow',
                        'inherited': False,
                    }
                ],
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
    return SimpleNamespace(returncode=0, stdout='ok', stderr='')


def _failing_runner(command, **kwargs):
    del command, kwargs
    return SimpleNamespace(returncode=1, stdout='', stderr='access denied')


def _windows_acl_runner(
    *,
    owner: str,
    owner_sid: str,
    access: list[dict],
    current_sid: str | None = None,
):
    writes: list[tuple[str, str]] = []

    def runner(command, **kwargs):
        del kwargs
        if command[:3] == ['powershell', '-NoProfile', '-Command'] and 'FileStream' in command[3]:
            path = _ps_literal_value(command[3], 'path')
            payload = _ps_literal_value(command[3], 'payload')
            Path(path).write_text(payload + '\n', encoding='utf-8')
            writes.append((path, payload))
            return SimpleNamespace(returncode=0, stdout='ok', stderr='')
        if command[:3] == ['powershell', '-NoProfile', '-Command'] and 'WindowsIdentity' in command[3]:
            return SimpleNamespace(returncode=0, stdout=current_sid or owner_sid, stderr='')
        if command[:3] == ['powershell', '-NoProfile', '-Command'] and 'GetAccessControl' in command[3]:
            payload = {
                'owner': owner,
                'sddl': f'O:{owner_sid}G:{owner_sid}D:',
                'access': access,
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    runner.writes = writes
    return runner


def _ps_literal_value(script: str, name: str) -> str:
    match = re.search(rf'\${re.escape(name)} = \'((?:\'\'|[^\'])*)\'', script)
    assert match is not None
    return match.group(1).replace("''", "'")


def test_factory_selects_windows_tcp_for_legacy_socket_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory._is_windows', lambda: True)
    write_endpoint(
        endpoint_from_record(
            {
                'kind': 'tcp_loopback',
                'host': '127.0.0.1',
                'port': 32123,
                'token_ref': str(tmp_path / 'token.json'),
                'generation': 'gen-1',
                'acl_status': 'windows-icacls-user-read',
                'fingerprint': 'deadbeefcafebabe',
            }
        ),
        legacy_socket_path=tmp_path / 'ccbd.sock',
    )

    transport = transport_for_legacy_socket_path(tmp_path / 'ccbd.sock')

    assert isinstance(transport, WindowsTcpControlPlaneTransport)


def test_windows_client_without_endpoint_fails_with_endpoint_error_not_af_unix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory._is_windows', lambda: True)
    client = CcbdClient(tmp_path / 'ccbd.sock', timeout_s=0.1)

    with pytest.raises(CcbdClientError) as error:
        client.request('ping', {})

    message = str(error.value)
    assert 'endpoint' in message
    assert 'unix domain sockets are not supported' not in message


def test_socket_server_prefers_windows_tcp_without_endpoint_descriptor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory._is_windows', lambda: True)
    monkeypatch.setattr('ccbd.socket_server_runtime.server._is_windows', lambda: True)

    server = CcbdSocketServer(tmp_path / 'ccbd.sock')

    assert isinstance(server._control_plane_transport, WindowsTcpControlPlaneTransport)
    assert server._control_plane_transport.endpoint is None


def test_windows_lifecycle_does_not_synthesize_legacy_endpoint_from_socket_path(monkeypatch, tmp_path: Path) -> None:
    _patch_module_os_name(monkeypatch, 'ccbd.services.lifecycle', 'nt')

    lifecycle = build_lifecycle(
        project_id='proj-1',
        occurred_at='2026-08-04T00:00:00Z',
        desired_state='running',
        phase='starting',
        generation=1,
        socket_path=tmp_path / 'ccbd.sock',
    )

    assert lifecycle.control_plane_endpoint is None


def test_windows_project_inspection_does_not_fall_back_to_legacy_endpoint(monkeypatch, tmp_path: Path) -> None:
    _patch_module_os_name(monkeypatch, 'ccbd.services.project_inspection', 'nt')

    inspection = ProjectDaemonInspection(
        lease=None,
        health=None,
        pid_alive=False,
        socket_connectable=False,
        heartbeat_fresh=False,
        takeover_allowed=True,
        reason='missing',
        phase='unmounted',
        desired_state='stopped',
        lifecycle=SimpleNamespace(socket_path=str(tmp_path / 'ccbd.sock'), control_plane_endpoint=None),
    )

    assert inspection.control_plane_endpoint is None


def test_tcp_endpoint_record_roundtrips_without_legacy_socket_path() -> None:
    endpoint = endpoint_from_record(
        {
            'kind': 'tcp_loopback',
            'host': '127.0.0.1',
            'port': 32123,
            'token_ref': 'C:/runtime/token.json',
            'generation': 'gen-1',
            'acl_status': 'windows-icacls-user-read',
            'fingerprint': 'deadbeefcafebabe',
        }
    )

    record = endpoint_to_record(endpoint)

    assert record['kind'] == 'tcp_loopback'
    assert record['address'] == '127.0.0.1:32123'
    assert record['legacy_socket_path'] is None
    assert record['socket_path'] is None
    assert record['token_ref'] == 'C:/runtime/token.json'
    assert record['auth_ref'] == 'C:/runtime/token.json'
    assert record['fingerprint'] == 'deadbeefcafebabe'


def test_create_token_file_fails_fast_when_acl_cannot_be_proven(tmp_path: Path) -> None:
    token_path = tmp_path / 'token.json'
    with pytest.raises(RpcTransportAuthError) as error:
        create_token_file(
            token_path,
            command_runner=_failing_runner,
            os_name='nt',
        )

    assert error.value.category in {'token-owner-mismatch', 'token-unprotectable'}
    assert not token_path.exists()


def test_create_token_file_proves_acl_convergence(tmp_path: Path, monkeypatch) -> None:
    token_path = tmp_path / 'token.json'
    runner = _windows_acl_runner(
        owner='DESKTOP\\User',
        owner_sid='S-1-5-21-1',
        access=[
            {
                'identity': 'DESKTOP\\User',
                'rights': 'Read',
                'access_type': 'Allow',
                'inherited': False,
            }
        ],
    )
    monkeypatch.setattr('ccbd.control_plane_transport.token_auth._current_windows_user', lambda: 'DESKTOP\\User')

    token_file = create_token_file(
        token_path,
        command_runner=runner,
        os_name='nt',
    )

    assert token_file.acl_status == 'windows-icacls-user-read'
    assert load_token_file(token_path).generation == token_file.generation
    assert runner.writes


def test_create_token_file_fails_when_acl_owner_is_not_current_user(tmp_path: Path, monkeypatch) -> None:
    token_path = tmp_path / 'token.json'
    runner = _windows_acl_runner(
        owner='DESKTOP\\OtherUser',
        owner_sid='S-1-5-21-other',
        current_sid='S-1-5-21-current',
        access=[
            {
                'identity': 'DESKTOP\\User',
                'rights': 'Read',
                'access_type': 'Allow',
                'inherited': False,
            }
        ],
    )
    monkeypatch.setattr('ccbd.control_plane_transport.token_auth._current_windows_user', lambda: 'DESKTOP\\User')

    with pytest.raises(RpcTransportAuthError) as error:
        create_token_file(
            token_path,
            command_runner=runner,
            os_name='nt',
        )

    assert error.value.category in {'token-owner-mismatch', 'token-unprotectable'}
    assert not token_path.exists()


def test_load_token_file_maps_unreadable_token(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / 'token.json'
    token_path.write_text('{}', encoding='utf-8')

    def _raise_permission_error(self, *args, **kwargs):
        del self, args, kwargs
        raise PermissionError('denied')

    monkeypatch.setattr(Path, 'read_text', _raise_permission_error)

    with pytest.raises(RpcTransportAuthError) as error:
        load_token_file(token_path)

    assert error.value.category == 'token-unreadable'


def test_create_token_file_fails_when_acl_proof_contains_unexpected_principal(tmp_path: Path, monkeypatch) -> None:
    token_path = tmp_path / 'token.json'
    runner = _windows_acl_runner(
        owner='DESKTOP\\User',
        owner_sid='S-1-5-21-1',
        access=[
            {
                'identity': 'DESKTOP\\User',
                'rights': 'Read',
                'access_type': 'Allow',
                'inherited': False,
            },
            {
                'identity': 'Everyone',
                'rights': 'Read',
                'access_type': 'Allow',
                'inherited': False,
            },
        ],
    )
    monkeypatch.setattr('ccbd.control_plane_transport.token_auth._current_windows_user', lambda: 'DESKTOP\\User')

    with pytest.raises(RpcTransportAuthError) as error:
        create_token_file(
            token_path,
            command_runner=runner,
            os_name='nt',
        )

    assert error.value.category in {'token-owner-mismatch', 'token-unprotectable'}
    assert not token_path.exists()


def test_tcp_listener_publishes_endpoint_and_roundtrips_ping(tmp_path: Path) -> None:
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=tmp_path / 'ccbd.sock',
        command_runner=_ok_runner,
    )
    server = CcbdSocketServer(tmp_path / 'ccbd.sock', control_plane_transport=transport)
    server.register_handler('ping', lambda payload: {'echo': payload})
    client = None
    try:
        server.listen()
        endpoint = read_endpoint(tmp_path / 'ccbd.sock')
        assert endpoint is not None
        assert endpoint['kind'] == 'tcp_loopback'
        assert endpoint['host'] == '127.0.0.1'
        assert int(endpoint['port']) > 0
        assert endpoint['legacy_socket_path'] is None
        assert endpoint['token_ref'] == endpoint['auth_ref']
        assert endpoint['fingerprint']
        assert server.control_plane_endpoint['fingerprint'] == endpoint['fingerprint']

        accepted_result = {}
        accept_thread = threading.Thread(
            target=lambda: accepted_result.update(zip(('conn', 'peer'), server._server.accept())),
            daemon=True,
        )
        accept_thread.start()
        client = transport.connect(timeout_s=1.0)
        accept_thread.join(timeout=1.0)
        assert 'conn' in accepted_result
        send_request(client, RpcRequest(op='ping', request={'target': 'ccbd'}))
        accepted = accepted_result['conn']
        peer = accepted_result['peer']
        assert peer['kind'] == 'tcp_loopback_token'
        start_worker(server, interval=0.0, on_tick=None)
        enqueue_connection(server, accepted)

        response = _wait_for_response(client)

        assert response.ok is True
        assert response.payload['echo'] == {'target': 'ccbd'}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        stop_worker(server)
        server.shutdown()


def test_bad_tcp_token_is_not_accepted_by_listener(tmp_path: Path) -> None:
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=tmp_path / 'ccbd.sock',
        command_runner=_ok_runner,
    )
    listener = transport.listen()
    listener.settimeout(0.2)
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        raw.connect(('127.0.0.1', int(listener.endpoint['port'])))
        raw.sendall(
            json.dumps(
                {
                    'schema': 'ccbd-control-plane-token-v1',
                    'token': 'wrong-token',
                }
            ).encode('utf-8')
            + b'\n'
        )

        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        raw.close()
        listener.close()
        transport.unlink_bound_endpoint(bound_identity=listener.bound_socket_stat)


def test_windows_legacy_socket_path_rejects_invalid_tcp_endpoint_descriptor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory._is_windows', lambda: True)
    endpoint_store_path(tmp_path / 'ccbd.sock').write_text(
        json.dumps({'kind': 'tcp_loopback', 'host': '127.0.0.2', 'port': 32123, 'token_ref': 'token.json'}) + '\n',
        encoding='utf-8',
    )

    transport = transport_for_legacy_socket_path(tmp_path / 'ccbd.sock')

    with pytest.raises(RpcTransportAuthError) as error:
        transport.connect(timeout_s=0.1)

    assert error.value.category == 'endpoint-invalid'


def test_direct_windows_endpoint_rejects_non_tcp_descriptor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory._is_windows', lambda: True)

    with pytest.raises(RpcTransportAuthError) as error:
        connect_endpoint({'socket_path': str(tmp_path / 'ccbd.sock')}, timeout_s=0.1)

    assert error.value.category == 'endpoint-invalid'


def test_tcp_bootstrap_probe_uses_authenticated_loopback_path(tmp_path: Path) -> None:
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=tmp_path / 'ccbd.sock',
        command_runner=_ok_runner,
    )
    server = CcbdSocketServer(tmp_path / 'ccbd.sock', control_plane_transport=transport)
    seen: list[str] = []

    def _handle_ping(payload):
        nonce = str(payload.get('bootstrap_probe_nonce') or '')
        seen.append(nonce)
        return {'bootstrap_probe_nonce': nonce, 'identity': 'tcp-loopback'}

    server.register_handler('ping', _handle_ping)
    server.listen()
    try:
        with server.bootstrap_readiness_probe(timeout_s=1.0) as payload:
            assert payload['identity'] == 'tcp-loopback'
            assert payload['bootstrap_probe_nonce'] == seen[0]
            assert server._bootstrap_probe_active is True

        assert server._bootstrap_probe_active is False
        assert server._stop_event.is_set() is False
    finally:
        server.shutdown()


def test_tcp_bootstrap_probe_ignores_slow_preauth_connection(tmp_path: Path) -> None:
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=tmp_path / 'ccbd.sock',
        command_runner=_ok_runner,
    )
    server = CcbdSocketServer(tmp_path / 'ccbd.sock', control_plane_transport=transport)
    server.register_handler(
        'ping',
        lambda payload: {'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce'), 'identity': 'tcp-loopback'},
    )
    server.listen()
    slow_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        slow_client.connect(('127.0.0.1', int(server.control_plane_endpoint['port'])))

        started = time.monotonic()
        with server.bootstrap_readiness_probe(timeout_s=1.0) as payload:
            assert payload['identity'] == 'tcp-loopback'
        assert time.monotonic() - started < 0.8
    finally:
        slow_client.close()
        server.shutdown()


def test_tcp_bootstrap_probe_rejects_deferred_bad_token_before_handler(tmp_path: Path) -> None:
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=tmp_path / 'ccbd.sock',
        command_runner=_ok_runner,
    )
    server = CcbdSocketServer(tmp_path / 'ccbd.sock', control_plane_transport=transport)
    handled = 0

    def _handle_ping(payload):
        nonlocal handled
        handled += 1
        return {'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce'), 'identity': 'tcp-loopback'}

    server.register_handler('ping', _handle_ping)
    server.listen()
    bad_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        bad_client.connect(('127.0.0.1', int(server.control_plane_endpoint['port'])))
        bad_client.sendall(
            json.dumps(
                {
                    'schema': 'ccbd-control-plane-token-v1',
                    'token': 'wrong-token',
                }
            ).encode('utf-8')
            + b'\n'
        )

        with server.bootstrap_readiness_probe(timeout_s=1.0) as payload:
            assert payload['identity'] == 'tcp-loopback'

        assert handled == 1
    finally:
        bad_client.close()
        server.shutdown()


def test_shutdown_removes_only_current_endpoint_generation(tmp_path: Path) -> None:
    legacy_socket_path = tmp_path / 'ccbd.sock'
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=legacy_socket_path,
        command_runner=_ok_runner,
    )
    listener = transport.listen()
    path = endpoint_store_path(legacy_socket_path)
    assert path.exists()
    assert legacy_socket_path.exists()

    stale_identity = ('other-generation', listener.bound_socket_stat[1])
    transport.unlink_bound_endpoint(bound_identity=stale_identity)
    assert path.exists()
    assert legacy_socket_path.exists()

    listener.close()
    transport.unlink_bound_endpoint(bound_identity=listener.bound_socket_stat)
    assert not path.exists()
    assert not legacy_socket_path.exists()


def test_shutdown_tolerates_locked_token_cleanup(monkeypatch, tmp_path: Path) -> None:
    legacy_socket_path = tmp_path / 'ccbd.sock'
    transport = WindowsTcpControlPlaneTransport(
        None,
        legacy_socket_path=legacy_socket_path,
        command_runner=_ok_runner,
    )
    listener = transport.listen()
    path = endpoint_store_path(legacy_socket_path)
    token_ref = listener.bound_socket_stat[1]
    original_unlink = Path.unlink

    def locked_token_once(self):
        if self == Path(token_ref):
            raise PermissionError('token still open')
        return original_unlink(self)

    monkeypatch.setattr(Path, 'unlink', locked_token_once)

    listener.close()
    transport.unlink_bound_endpoint(bound_identity=listener.bound_socket_stat)

    assert not path.exists()
    assert not legacy_socket_path.exists()
    assert Path(token_ref).exists()


def test_unlink_endpoint_skips_when_generation_is_missing(tmp_path: Path) -> None:
    legacy_socket_path = tmp_path / 'ccbd.sock'
    endpoint = endpoint_from_record(
        {
            'kind': 'tcp_loopback',
            'host': '127.0.0.1',
            'port': 32123,
            'token_ref': str(tmp_path / 'token.json'),
            'generation': 'gen-1',
            'acl_status': 'windows-icacls-user-read',
            'fingerprint': 'deadbeefcafebabe',
        }
    )
    write_endpoint(endpoint, legacy_socket_path=legacy_socket_path)

    endpoint_store_path_value = endpoint_store_path(legacy_socket_path)
    assert endpoint_store_path_value.exists()

    assert unlink_endpoint(legacy_socket_path=legacy_socket_path, expected_generation=None) is False
    assert endpoint_store_path_value.exists()

    assert unlink_endpoint(legacy_socket_path=legacy_socket_path, expected_generation='gen-mismatch') is False
    assert endpoint_store_path_value.exists()

    assert unlink_endpoint(legacy_socket_path=legacy_socket_path, expected_generation='gen-1') is True
    assert not endpoint_store_path_value.exists()


def test_token_store_path_rejects_generation_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        token_store_path(tmp_path / 'ccbd.sock', '../escape')

    with pytest.raises(ValueError):
        token_store_path(tmp_path / 'ccbd.sock', 'nested/token')


def _wait_for_response(client):
    deadline = time.monotonic() + 2.0
    raw = b''
    while b'\n' not in raw and time.monotonic() < deadline:
        raw = recv_response_line(client)
        if not raw:
            time.sleep(0.01)
    assert raw
    return decode_response(raw)
