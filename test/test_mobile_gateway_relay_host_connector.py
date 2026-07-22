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

            assert response['ok'] is True
            assert response['status'] == 200
            assert response['body']['status'] == 'ok'
            assert response['body']['served_by'] == 'loopback-gateway'
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

            assert response == {
                'ok': False,
                'status': 400,
                'error': 'relay_operation_not_allowed',
            }
            assert gateway.requests == []
            assert connector.diagnostics()['requests_rejected'] == 1
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


async def _round_trip_gateway_request(
    phone: aiohttp.ClientWebSocketResponse,
    phone_crypto,
    *,
    session_id: str,
    outer_seq: int,
    operation: str,
    payload: dict[str, object],
) -> dict[str, object]:
    envelope = phone_crypto.seal(op=operation, plaintext=json.dumps(payload, sort_keys=True).encode('utf-8'))
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
    return json.loads(plaintext.decode('utf-8'))


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

    async def stop(self) -> None:
        await self.runner.cleanup()


async def _started_gateway() -> _GatewayStub:
    requests: list[tuple[str, str]] = []

    async def health(request: web.Request) -> web.Response:
        requests.append((request.method, request.path))
        return web.json_response({'schema_version': 1, 'status': 'ok', 'served_by': 'loopback-gateway'})

    app = web.Application()
    app.router.add_get('/v1/health', health)
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
