from __future__ import annotations

import json
import time

import pytest

from ccbd.api_models import RpcRequest
from ccbd.control_plane_transport.fake import FakeConnection, FakeControlPlaneTransport
from ccbd.socket_client_runtime import CcbdClientError, decode_response, recv_response_line, send_request
from ccbd.socket_server import CcbdSocketServer
from ccbd.socket_server_runtime.loop import enqueue_connection, start_worker, stop_worker


def test_fake_transport_listen_request_and_shutdown_roundtrip() -> None:
    transport = FakeControlPlaneTransport()
    server = CcbdSocketServer('fake://ccbd.sock', control_plane_transport=transport)
    calls: list[dict] = []
    server.register_handler('ping', lambda payload: calls.append(payload) or {'ok': True, 'echo': payload})

    server.listen()
    try:
        connection = FakeConnection()
        request = RpcRequest(op='ping', request={'target': 'ccbd'})
        connection.push_recv((json.dumps(request.to_record()) + '\n').encode('utf-8'))
        transport.listener.enqueue(connection)
        accepted, peer = server._server.accept()
        assert peer['kind'] == 'fake'
        start_worker(server, interval=0.0, on_tick=None)
        enqueue_connection(server, accepted)
        deadline = time.monotonic() + 2.0
        while (
            (not calls or not connection.closed or b'"ok": true' not in bytes(connection.sent))
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert calls == [{'target': 'ccbd'}]
        assert connection.closed is True
        assert b'"ok": true' in bytes(connection.sent)
    finally:
        stop_worker(server)
        server.shutdown()


def test_fake_bootstrap_probe_roundtrip() -> None:
    transport = FakeControlPlaneTransport()
    server = CcbdSocketServer('fake://ccbd.sock', control_plane_transport=transport)
    seen: list[str] = []

    def _handle_ping(payload):
        nonce = str(payload.get('bootstrap_probe_nonce') or '')
        seen.append(nonce)
        return {'bootstrap_probe_nonce': nonce}

    server.register_handler('ping', _handle_ping)
    server.listen()
    try:
        with server.bootstrap_readiness_probe(timeout_s=0.5) as payload:
            assert payload['bootstrap_probe_nonce'] == seen[0]
            assert len(seen[0]) == 32
    finally:
        server.shutdown()


def test_fake_transport_rejects_connect_after_listener_close() -> None:
    transport = FakeControlPlaneTransport()
    transport.listener.close()

    assert transport.is_connectable() is False
    with pytest.raises(OSError):
        transport.listener.accept()
    with pytest.raises(OSError):
        transport.connect(timeout_s=0.1)


def test_recv_response_line_rejects_response_without_newline_over_max_size() -> None:
    class _OversizedSocket:
        def __init__(self) -> None:
            self._chunks = [b'a' * (1024 * 1024), b'b']

        def recv(self, size: int) -> bytes:
            del size
            if not self._chunks:
                return b''
            return self._chunks.pop(0)

    with pytest.raises(CcbdClientError, match='response exceeds maximum size'):
        recv_response_line(_OversizedSocket())
