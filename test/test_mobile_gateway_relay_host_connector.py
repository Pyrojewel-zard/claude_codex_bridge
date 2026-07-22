from __future__ import annotations

import asyncio
import base64
import json
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mobile_gateway.relay import issue_host_rendezvous_capability
from mobile_gateway.relay_admission import (
    RelayAdmissionSecrets,
    RelayAdmissionStore,
    generate_host_private_key,
    host_public_key_b64,
)
from mobile_gateway.relay_crypto import (
    RelayDirection,
    RelayV2Envelope,
    derive_relay_v2_key_schedule,
    host_fingerprint_for_public_key,
    key_pair_from_private_bytes,
    public_key_b64,
)
from mobile_gateway.relay_host_connector import (
    RelayHostConnector,
    RelayHostConnectorConfig,
)
from mobile_gateway.relay_service import ProductionRelayConfig, ProductionRelayService
from mobile_gateway.relay_stream import (
    RELAY_STREAM_INITIAL_WINDOW_BYTES,
    RelayInnerMessage,
    relay_inner_payload_size,
)


def test_relay_host_connector_requires_safe_origins() -> None:
    host_signing_key = generate_host_private_key()
    host_crypto_key = key_pair_from_private_bytes(bytes(range(101, 133)))

    with pytest.raises(ValueError, match='wss://'):
        RelayHostConnectorConfig(
            relay_origin='ws://relay.example',
            gateway_origin='http://127.0.0.1:8787',
            host_id='rhost_demo',
            host_signing_key=host_signing_key,
            host_crypto_private_key=host_crypto_key,
        )

    with pytest.raises(ValueError, match='origin'):
        RelayHostConnectorConfig(
            relay_origin='wss://relay.example/v2/host',
            gateway_origin='http://127.0.0.1:8787',
            host_id='rhost_demo',
            host_signing_key=host_signing_key,
            host_crypto_private_key=host_crypto_key,
        )

    with pytest.raises(ValueError, match='loopback'):
        RelayHostConnectorConfig(
            relay_origin='wss://relay.example',
            gateway_origin='http://gateway.example:8787',
            host_id='rhost_demo',
            host_signing_key=host_signing_key,
            host_crypto_private_key=host_crypto_key,
        )


def test_relay_host_connector_proxies_encrypted_gateway_request(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_proxies_encrypted_gateway_request(tmp_path))


async def _relay_host_connector_proxies_encrypted_gateway_request(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    gateway = await _started_gateway()
    host_crypto_key = key_pair_from_private_bytes(bytes(range(101, 133)))
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin=gateway.origin,
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=host_crypto_key,
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    task = asyncio.create_task(connector.connect_once())
    try:
        await _wait_for(lambda: connector.diagnostics()['state'] == 'registered')
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            phone = await client.ws_connect(relay.url('/v2/phone'), ssl=_client_ssl())
            phone_crypto, host_hello = await _open_phone_session(
                phone,
                issued=issued,
                relay_origin=issued.relay_audience,
                expected_host_public_key=public_key_b64(host_crypto_key),
            )
            assert host_hello['payload']['server_fingerprint'] == host_fingerprint_for_public_key(
                public_key_b64(host_crypto_key)
            )

            response = await _round_trip_gateway_request(
                phone,
                phone_crypto,
                session_id='relay-host-connector-session',
                outer_seq=2,
                operation='health',
                payload={'request_id': 'req-health-1'},
            )

            assert response.kind == 'response'
            assert response.request_id == 'req-health-1'
            assert response.payload['ok'] is True
            assert response.payload['status'] == 200
            assert response.payload['body']['status'] == 'ok'
            assert response.payload['body']['served_by'] == 'loopback-gateway'
            assert gateway.requests == [('GET', '/v1/health')]
            assert connector.diagnostics()['requests_proxied'] == 1
    finally:
        connector.stop()
        await asyncio.wait_for(task, timeout=2)
        await gateway.stop()
        await relay.stop()


def test_relay_host_connector_rejects_unallowlisted_gateway_request(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_rejects_unallowlisted_gateway_request(tmp_path))


async def _relay_host_connector_rejects_unallowlisted_gateway_request(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    gateway = await _started_gateway()
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin=gateway.origin,
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=key_pair_from_private_bytes(bytes(range(101, 133))),
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    task = asyncio.create_task(connector.connect_once())
    try:
        await _wait_for(lambda: connector.diagnostics()['state'] == 'registered')
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            phone = await client.ws_connect(relay.url('/v2/phone'), ssl=_client_ssl())
            phone_crypto, _host_hello = await _open_phone_session(
                phone,
                issued=issued,
                relay_origin=issued.relay_audience,
                expected_host_public_key=public_key_b64(connector.config.host_crypto_private_key),
            )
            response = await _round_trip_gateway_request(
                phone,
                phone_crypto,
                session_id='relay-host-connector-session',
                outer_seq=2,
                operation='raw_request',
                payload={
                    'method': 'GET',
                    'path': '/v1/projects/../../secrets',
                    'device_token': 'secret-token',
                },
            )

            assert response.kind == 'error'
            assert response.payload == {'code': 'operation_not_allowed'}
            assert gateway.requests == []
            assert connector.diagnostics()['requests_rejected'] == 1
    finally:
        connector.stop()
        await asyncio.wait_for(task, timeout=2)
        await gateway.stop()
        await relay.stop()


def test_relay_host_connector_demultiplexes_concurrent_requests(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_demultiplexes_concurrent_requests(tmp_path))


async def _relay_host_connector_demultiplexes_concurrent_requests(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    gateway = await _started_gateway()
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin=gateway.origin,
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=key_pair_from_private_bytes(bytes(range(101, 133))),
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    task = asyncio.create_task(connector.connect_once())
    try:
        await _wait_for(lambda: connector.diagnostics()['state'] == 'registered')
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            phone = await client.ws_connect(relay.url('/v2/phone'), ssl=_client_ssl())
            phone_crypto, _ = await _open_phone_session(
                phone,
                issued=issued,
                relay_origin=issued.relay_audience,
                expected_host_public_key=public_key_b64(connector.config.host_crypto_private_key),
            )
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=2,
                message=RelayInnerMessage(
                    kind='request',
                    request_id='request-health-slow-1',
                    operation='health',
                    payload={},
                ),
            )
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=3,
                message=RelayInnerMessage(
                    kind='request',
                    request_id='request-device-fast-1',
                    operation='device',
                    payload={'device_token': 'device-token-demo'},
                ),
            )

            first = await _receive_phone_inner(phone, phone_crypto)
            second = await _receive_phone_inner(phone, phone_crypto)

            assert first.request_id == 'request-device-fast-1'
            assert first.payload['body']['device']['device_id'] == 'device-demo'
            assert second.request_id == 'request-health-slow-1'
            assert second.payload['body']['status'] == 'ok'
            assert set(gateway.requests) == {
                ('GET', '/v1/devices/me'),
                ('GET', '/v1/health'),
            }
    finally:
        connector.stop()
        await asyncio.wait_for(task, timeout=2)
        await gateway.stop()
        await relay.stop()


def test_relay_host_connector_revoked_host_reports_auth_diagnostic(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_revoked_host_reports_auth_diagnostic(tmp_path))


async def _relay_host_connector_revoked_host_reports_auth_diagnostic(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    issued.store.revoke_host(issued.host_id, reason='test revoke before connect')
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin='http://127.0.0.1:8787',
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=key_pair_from_private_bytes(bytes(range(101, 133))),
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    try:
        await connector.connect_once()
        assert connector.diagnostics()['state'] == 'auth_rejected'
        assert connector.diagnostics()['last_error_code'] == 'relay_auth_rejected'
    finally:
        connector.stop()
        await relay.stop()


def test_relay_host_connector_streams_terminal_without_replaying_input(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_streams_terminal_without_replaying_input(tmp_path))


async def _relay_host_connector_streams_terminal_without_replaying_input(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    gateway = await _started_gateway()
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin=gateway.origin,
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=key_pair_from_private_bytes(bytes(range(101, 133))),
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    task = asyncio.create_task(connector.connect_once())
    try:
        await _wait_for(lambda: connector.diagnostics()['state'] == 'registered')
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            phone = await client.ws_connect(relay.url('/v2/phone'), ssl=_client_ssl())
            phone_crypto, _ = await _open_phone_session(
                phone,
                issued=issued,
                relay_origin=issued.relay_audience,
                expected_host_public_key=public_key_b64(connector.config.host_crypto_private_key),
            )
            stream_id = 'terminal-stream-demo-1'
            opening_payload = {
                'frame': {
                    'type': 'open',
                    'terminal_id': 'term-demo',
                    'resume_cursor': 0,
                    'last_input_seq': 0,
                }
            }
            opening_credit = relay_inner_payload_size(opening_payload)
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=2,
                message=RelayInnerMessage(
                    kind='stream_open',
                    stream_id=stream_id,
                    operation='terminal',
                    credit_bytes=opening_credit,
                    payload={
                        'terminal_id': 'term-demo',
                        'terminal_token': 'terminal-token-demo',
                    },
                ),
            )
            opening = await _receive_until_kind(phone, phone_crypto, 'stream_data')
            assert opening.stream_id == stream_id
            assert opening.payload['frame']['type'] == 'open'
            await _receive_until_kind(phone, phone_crypto, 'stream_window')

            input_frame = {
                'type': 'input',
                'seq': 1,
                'data_b64': _b64(b'MOBILE_STREAM_INPUT'),
            }
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=3,
                message=RelayInnerMessage(
                    kind='stream_data',
                    stream_id=stream_id,
                    payload={'frame': input_frame},
                ),
            )
            await _wait_for(lambda: gateway.terminal_inputs == [input_frame])
            output_payload = {
                'frame': {
                    'type': 'output',
                    'seq': 1,
                    'data_b64': input_frame['data_b64'],
                }
            }
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=4,
                message=RelayInnerMessage(
                    kind='stream_window',
                    stream_id=stream_id,
                    credit_bytes=relay_inner_payload_size(output_payload),
                    payload={},
                ),
            )
            output = await _receive_until_kind(phone, phone_crypto, 'stream_data')
            assert output.payload['frame']['type'] == 'output'
            assert base64.urlsafe_b64decode(
                str(output.payload['frame']['data_b64']) + '=='
            ) == b'MOBILE_STREAM_INPUT'
            resize_frame = {
                'type': 'resize',
                'seq': 2,
                'cols': 100,
                'rows': 32,
            }
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=5,
                message=RelayInnerMessage(
                    kind='stream_data',
                    stream_id=stream_id,
                    payload={'frame': resize_frame},
                ),
            )
            await _wait_for(
                lambda: gateway.terminal_inputs == [input_frame, resize_frame]
            )
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=6,
                message=RelayInnerMessage(
                    kind='stream_cancel',
                    stream_id=stream_id,
                    payload={},
                ),
            )
            await _receive_until_kind(phone, phone_crypto, 'stream_close')
            assert gateway.terminal_inputs == [input_frame, resize_frame]
    finally:
        connector.stop()
        await asyncio.wait_for(task, timeout=2)
        await gateway.stop()
        await relay.stop()
    _assert_canary_not_persisted(tmp_path, 'MOBILE_STREAM_INPUT')


def test_relay_host_connector_notification_stream_resumes_without_duplicates(tmp_path: Path) -> None:
    asyncio.run(_relay_host_connector_notification_stream_resumes_without_duplicates(tmp_path))


async def _relay_host_connector_notification_stream_resumes_without_duplicates(tmp_path: Path) -> None:
    relay, issued = await _started_relay(tmp_path)
    gateway = await _started_gateway()
    connector = RelayHostConnector(
        RelayHostConnectorConfig(
            relay_origin=_relay_origin(relay),
            gateway_origin=gateway.origin,
            host_id=issued.host_id,
            host_signing_key=issued.private_key,
            host_crypto_private_key=key_pair_from_private_bytes(bytes(range(101, 133))),
            tls_context=_client_ssl(),
            request_timeout_seconds=1.0,
        )
    )
    task = asyncio.create_task(connector.connect_once())
    try:
        await _wait_for(lambda: connector.diagnostics()['state'] == 'registered')
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            phone = await client.ws_connect(relay.url('/v2/phone'), ssl=_client_ssl())
            phone_crypto, _ = await _open_phone_session(
                phone,
                issued=issued,
                relay_origin=issued.relay_audience,
                expected_host_public_key=public_key_b64(connector.config.host_crypto_private_key),
            )
            stream_id = 'notification-stream-demo-1'
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=2,
                message=RelayInnerMessage(
                    kind='stream_open',
                    stream_id=stream_id,
                    operation='notifications',
                    credit_bytes=RELAY_STREAM_INITIAL_WINDOW_BYTES,
                    payload={'device_token': 'device-token-demo'},
                ),
            )
            received_ids: list[str] = []
            while len(received_ids) < 2:
                message = await _receive_phone_inner(phone, phone_crypto, timeout=3.0)
                if message.kind != 'stream_data':
                    continue
                event = message.payload['event']
                received_ids.append(str(event['id']))
                await _send_phone_inner(
                    phone,
                    phone_crypto,
                    outer_seq=2 + len(received_ids),
                    message=RelayInnerMessage(
                        kind='stream_window',
                        stream_id=stream_id,
                        credit_bytes=relay_inner_payload_size(message.payload),
                        payload={},
                    ),
                )
            assert received_ids == ['evt-1', 'evt-2']
            assert gateway.notification_cursors[:2] == [None, 'evt-1']
            await _send_phone_inner(
                phone,
                phone_crypto,
                outer_seq=5,
                message=RelayInnerMessage(
                    kind='stream_cancel',
                    stream_id=stream_id,
                    payload={},
                ),
            )
    finally:
        connector.stop()
        await asyncio.wait_for(task, timeout=2)
        await gateway.stop()
        await relay.stop()


async def _round_trip_gateway_request(
    phone: aiohttp.ClientWebSocketResponse,
    phone_crypto,
    *,
    session_id: str,
    outer_seq: int,
    operation: str,
    payload: dict[str, object],
) -> RelayInnerMessage:
    inner = {
        'schema_version': 1,
        'kind': 'request',
        'request_id': str(payload.pop('request_id', 'request-demo-1')),
        'operation': operation,
        'payload': payload,
    }
    envelope = phone_crypto.seal(
        op='relay.inner.v1',
        plaintext=json.dumps(inner, sort_keys=True, separators=(',', ':')).encode('utf-8'),
    )
    await phone.send_json(
        {
            'schema_version': 2,
            'session_id': session_id,
            'seq': outer_seq,
            'kind': 'gateway_envelope',
            'payload': {'envelope': envelope.to_json()},
        }
    )
    response_frame = await phone.receive_json()
    assert response_frame['kind'] == 'gateway_envelope'
    response_envelope = RelayV2Envelope.from_json(response_frame['payload']['envelope'])
    plaintext = phone_crypto.open(response_envelope)
    return RelayInnerMessage.from_bytes(plaintext)


async def _send_phone_inner(
    phone: aiohttp.ClientWebSocketResponse,
    phone_crypto,
    *,
    outer_seq: int,
    message: RelayInnerMessage,
) -> None:
    envelope = phone_crypto.seal(op='relay.inner.v1', plaintext=message.to_bytes())
    await phone.send_json(
        {
            'schema_version': 2,
            'session_id': 'relay-host-connector-session',
            'seq': outer_seq,
            'kind': 'gateway_envelope',
            'payload': {'envelope': envelope.to_json()},
        }
    )


async def _receive_phone_inner(
    phone: aiohttp.ClientWebSocketResponse,
    phone_crypto,
    *,
    timeout: float = 2.0,
) -> RelayInnerMessage:
    response_frame = await asyncio.wait_for(phone.receive_json(), timeout=timeout)
    assert response_frame['kind'] == 'gateway_envelope'
    envelope = RelayV2Envelope.from_json(response_frame['payload']['envelope'])
    assert envelope.op == 'relay.inner.v1'
    return RelayInnerMessage.from_bytes(phone_crypto.open(envelope))


async def _receive_until_kind(
    phone: aiohttp.ClientWebSocketResponse,
    phone_crypto,
    kind: str,
) -> RelayInnerMessage:
    for _ in range(8):
        message = await _receive_phone_inner(phone, phone_crypto)
        if message.kind == kind:
            return message
    raise AssertionError(f'relay inner message kind not received: {kind}')


async def _open_phone_session(
    phone: aiohttp.ClientWebSocketResponse,
    *,
    issued: '_IssuedHost',
    relay_origin: str,
    expected_host_public_key: str,
):
    session_id = 'relay-host-connector-session'
    client_private = key_pair_from_private_bytes(bytes(range(1, 33)))
    client_public = public_key_b64(client_private)
    phone_nonce_b64 = _b64(b'fresh phone nonce for host connector test')
    rendezvous = issue_host_rendezvous_capability(
        issued.private_key,
        host_id=issued.host_id,
        session_id=session_id,
        client_pubkey_b64=client_public,
        phone_nonce_b64=phone_nonce_b64,
        audience=relay_origin,
        expires_at=int(time.time()) + 30,
    )
    await phone.send_json(
        {
            'schema_version': 2,
            'session_id': session_id,
            'seq': 1,
            'kind': 'client_hello',
            'payload': {
                'host_id': issued.host_id,
                'device_id': 'device-relay-host-connector',
                'client_pubkey_b64': client_public,
                'phone_nonce_b64': phone_nonce_b64,
                'supported_versions': [2],
                'rendezvous_capability': rendezvous,
            },
        }
    )
    host_hello = await phone.receive_json()
    assert host_hello['kind'] == 'host_hello'
    assert host_hello['payload']['host_pubkey_b64'] == expected_host_public_key
    schedule = derive_relay_v2_key_schedule(
        local_private_key=client_private,
        peer_public_key_b64=host_hello['payload']['host_pubkey_b64'],
        role='phone',
        session_id=session_id,
        client_public_key_b64=client_public,
        host_public_key_b64=host_hello['payload']['host_pubkey_b64'],
        expected_host_fingerprint=host_hello['payload']['server_fingerprint'],
    )
    return schedule.session(role='phone'), host_hello


@dataclass
class _IssuedHost:
    store: RelayAdmissionStore
    host_id: str
    private_key: Any
    relay_audience: str = 'wss://relay.seemlab.top'


async def _started_relay(tmp_path: Path) -> tuple[ProductionRelayService, _IssuedHost]:
    cert_path, key_path = _write_self_signed_cert(tmp_path)
    store = RelayAdmissionStore(
        tmp_path / 'relay.sqlite3',
        admission_secrets=RelayAdmissionSecrets.generate_for_testing(),
    )
    host_private = generate_host_private_key()
    invitation = store.issue_invitation(ttl_seconds=600, max_sessions=4)
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(host_private),
    )
    service = ProductionRelayService(
        ProductionRelayConfig(
            listen_host='127.0.0.1',
            listen_port=0,
            admin_host='127.0.0.1',
            admin_port=0,
            tls_cert_file=cert_path,
            tls_key_file=key_path,
            admission_db_path=tmp_path / 'relay.sqlite3',
            state_dir=tmp_path / 'state',
            handshake_timeout=2.0,
            idle_timeout=5.0,
            write_timeout=1.0,
        ),
        admission_store=store,
    )
    await service.start()
    return service, _IssuedHost(store=store, host_id=credential.host_id, private_key=host_private)


@dataclass
class _GatewayStub:
    origin: str
    runner: web.AppRunner
    site: web.TCPSite
    requests: list[tuple[str, str]]
    terminal_inputs: list[dict[str, object]]
    notification_cursors: list[str | None]

    async def stop(self) -> None:
        await self.runner.cleanup()


async def _started_gateway() -> _GatewayStub:
    requests: list[tuple[str, str]] = []
    terminal_inputs: list[dict[str, object]] = []
    notification_cursors: list[str | None] = []

    async def health(request: web.Request) -> web.Response:
        await asyncio.sleep(0.05)
        requests.append((request.method, request.path))
        return web.json_response({'schema_version': 1, 'status': 'ok', 'served_by': 'loopback-gateway'})

    async def device(request: web.Request) -> web.Response:
        requests.append((request.method, request.path))
        assert request.headers['authorization'] == 'Bearer device-token-demo'
        return web.json_response(
            {
                'schema_version': 1,
                'device': {
                    'device_id': 'device-demo',
                    'project_id': 'project-demo',
                    'route_provider': 'relay',
                    'scopes': ['view'],
                },
            }
        )

    async def terminal(request: web.Request) -> web.WebSocketResponse:
        websocket = web.WebSocketResponse(max_msg_size=512 * 1024)
        await websocket.prepare(request)
        opening = await websocket.receive_json()
        assert opening == {
            'type': 'open',
            'terminal_id': 'term-demo',
            'token': 'terminal-token-demo',
        }
        await websocket.send_json(
            {
                'type': 'open',
                'terminal_id': 'term-demo',
                'resume_cursor': 0,
                'last_input_seq': 0,
            }
        )
        async for incoming in websocket:
            if incoming.type != aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(incoming.data)
            assert isinstance(frame, dict)
            terminal_inputs.append(frame)
            if frame.get('type') == 'input':
                await websocket.send_json(
                    {
                        'type': 'output',
                        'seq': 1,
                        'data_b64': frame['data_b64'],
                    }
                )
        return websocket

    async def notifications(request: web.Request) -> web.StreamResponse:
        cursor = request.headers.get('Last-Event-ID')
        notification_cursors.append(cursor)
        event_id = 'evt-1' if cursor is None else 'evt-2'
        response = web.StreamResponse(
            status=200,
            headers={'Content-Type': 'text/event-stream'},
        )
        await response.prepare(request)
        first = '{"kind":"task_completed",'
        second = f'"event_id":"{event_id}"}}'
        await response.write(f'id: {event_id}\n'.encode())
        await response.write(b'event: task_completed\n')
        await response.write(b'retry: 10\n')
        await response.write(f'data: {first}\n'.encode())
        await response.write(f'data: {second}\n\n'.encode())
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get('/v1/health', health)
    app.router.add_get('/v1/devices/me', device)
    app.router.add_get('/v1/terminals/term-demo', terminal)
    app.router.add_get('/v1/mobile/notifications', notifications)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return _GatewayStub(
        origin=f'http://127.0.0.1:{port}',
        runner=runner,
        site=site,
        requests=requests,
        terminal_inputs=terminal_inputs,
        notification_cursors=notification_cursors,
    )


async def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    assert predicate()


def _relay_origin(service: ProductionRelayService) -> str:
    return service.url('/').rstrip('/')


def _client_ssl() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _assert_canary_not_persisted(root: Path, canary: str) -> None:
    needle = canary.encode('utf-8')
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        assert needle not in path.read_bytes(), f'relay persisted payload canary in {path}'


def _write_self_signed_cert(tmp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.DNSName('127.0.0.1')]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / 'relay-cert.pem'
    key_path = tmp_path / 'relay-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.chmod(0o600)
    key_path.chmod(0o600)
    return cert_path, key_path


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')
