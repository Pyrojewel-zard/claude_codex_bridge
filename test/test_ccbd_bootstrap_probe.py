from __future__ import annotations

from pathlib import Path
import os
import socket
import time

import pytest

from ccbd.api_models import RpcRequest
from ccbd.control_plane_transport.fake import FakeControlPlaneTransport
from ccbd.socket_client_runtime import decode_response, recv_response_line, send_request
from ccbd.socket_server import CcbdSocketServer


def _server(tmp_path: Path) -> CcbdSocketServer:
    return CcbdSocketServer(
        tmp_path / 'ccbd.sock',
        control_plane_transport=FakeControlPlaneTransport(),
    )


def test_bootstrap_probe_roundtrips_through_normal_request_worker(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.register_handler(
        'ping',
        lambda payload: {
            'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce'),
            'identity': 'current-generation',
        },
    )
    server.listen()
    try:
        with server.bootstrap_readiness_probe(timeout_s=1.0) as payload:
            assert payload['identity'] == 'current-generation'
            assert server._bootstrap_probe_active is True
            assert server._worker_thread is not None
            assert server._worker_thread.is_alive()

        assert server._bootstrap_probe_active is False
        assert server._stop_event.is_set() is False
    finally:
        server.shutdown()


def test_runtime_bootstrap_gate_rejects_non_ping_without_calling_handler(tmp_path: Path) -> None:
    server = _server(tmp_path)
    called = []
    server.register_handler('submit', lambda payload: called.append(payload) or {'accepted': True})
    client, accepted = socket.socketpair()
    server.listen()
    server.begin_runtime_bootstrap()
    try:
        send_request(client, RpcRequest(op='submit', request={'message': 'must-not-run'}))
        assert server._handle_connection(accepted) == 'submit'
        response = decode_response(recv_response_line(client))

        assert response.ok is False
        assert response.error == 'ccbd bootstrap accepts ping only'
        assert called == []
    finally:
        client.close()
        accepted.close()
        server.shutdown()


def test_probe_failure_stops_server_without_latching_active_flag(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.register_handler(
        'ping',
        lambda payload: {'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce')},
    )
    server.listen()

    with pytest.raises(RuntimeError, match='planned identity rejection'):
        with server.bootstrap_readiness_probe(timeout_s=1.0):
            raise RuntimeError('planned identity rejection')

    assert server._stop_event.is_set() is True
    assert server._bootstrap_probe_active is False
    server.shutdown()
    assert server._bootstrap_probe_active is False
    assert server._runtime_bootstrap_active is False
    assert server._worker_thread is None
    assert not server.socket_path.exists()


def test_nested_bootstrap_probe_fails_closed(tmp_path: Path) -> None:
    server = _server(tmp_path)
    server.register_handler(
        'ping',
        lambda payload: {'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce')},
    )
    server.listen()
    try:
        with server.bootstrap_readiness_probe(timeout_s=1.0):
            with pytest.raises(RuntimeError, match='already active'):
                with server.bootstrap_readiness_probe(timeout_s=1.0):
                    pass
    finally:
        server.shutdown()


def test_slow_preexisting_client_cannot_consume_self_probe_budget(tmp_path: Path) -> None:
    if os.name == 'nt' or not hasattr(socket, 'AF_UNIX'):
        pytest.skip('AF_UNIX bootstrap slow-client regression is Unix-only')
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    server.register_handler(
        'ping',
        lambda payload: {'bootstrap_probe_nonce': payload.get('bootstrap_probe_nonce')},
    )
    server.listen()
    slow_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    slow_client.connect(str(server.socket_path))
    started = time.monotonic()
    try:
        with server.bootstrap_readiness_probe(timeout_s=0.5):
            pass
        elapsed = time.monotonic() - started
        assert elapsed < 0.25
    finally:
        slow_client.close()
        server.shutdown()
