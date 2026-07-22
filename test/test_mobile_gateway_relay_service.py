from __future__ import annotations

import asyncio
import base64
import json
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mobile_gateway.relay_crypto import (
    RelayDirection,
    RelayV2Envelope,
    key_pair_from_private_bytes,
    derive_relay_v2_key_schedule,
    public_key_b64,
)
from mobile_gateway.relay_admission import (
    RelayAdmissionSecrets,
    RelayAdmissionStore,
    generate_host_private_key,
    host_public_key_b64,
    sign_host_session_proof,
)
from mobile_gateway.relay_service import ProductionRelayConfig, ProductionRelayService


def test_wss_host_phone_forward_opaque_bidirectional_frames(tmp_path: Path) -> None:
    asyncio.run(_wss_host_phone_forward_opaque_bidirectional_frames(tmp_path))


async def _wss_host_phone_forward_opaque_bidirectional_frames(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path)
    canary = 'PACKAGE-C-CANARY-opaque-payload'
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            client_hello = _client_hello(session_id='relay-session-1', host_id=issued.host_id)
            await phone.send_json(client_hello.to_json())
            assert await host.receive_json() == client_hello.to_json()

            host_hello = _host_hello(session_id='relay-session-1', host_id=issued.host_id)
            await host.send_json(host_hello.to_json())
            assert await phone.receive_json() == host_hello.to_json()

            phone_frame = _gateway_frame(
                session_id='relay-session-1',
                outer_seq=3,
                envelope=_relay_envelope(
                    session_id='relay-session-1',
                    direction=RelayDirection.PHONE_TO_HOST,
                    seq=1,
                    plaintext=canary.encode('utf-8'),
                ),
            )
            await phone.send_json(phone_frame)
            assert await host.receive_json() == phone_frame

            host_frame = _gateway_frame(
                session_id='relay-session-1',
                outer_seq=4,
                envelope=_relay_envelope(
                    session_id='relay-session-1',
                    direction=RelayDirection.HOST_TO_PHONE,
                    seq=1,
                    plaintext=b'host reply bytes',
                ),
            )
            await host.send_json(host_frame)
            assert await phone.receive_json() == host_frame

        metrics = service.metrics_snapshot()
        assert metrics['sessions_opened'] == 1
        assert metrics['frames_forwarded'] == 2
        assert metrics['payload_bytes_persisted'] == 0
        _assert_canary_not_persisted(tmp_path, canary)
    finally:
        await service.stop()


def test_fixed_frame_rejection_and_frame_size_limit(tmp_path: Path) -> None:
    asyncio.run(_fixed_frame_rejection_and_frame_size_limit(tmp_path))


async def _fixed_frame_rejection_and_frame_size_limit(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path, max_frame_bytes=900)
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            await host.receive_json()

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json({'schema_version': 2, 'session_id': 's', 'seq': 1, 'kind': 'proxy_connect', 'payload': {}})
            rejected = await phone.receive_json()
            assert rejected['kind'] == 'error'
            assert 'unknown relay frame kind' in rejected['payload']['reason']

            oversized = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await oversized.send_str(json.dumps({'padding': 'x' * 1200}))
            rejected = await oversized.receive_json()
            assert rejected['kind'] == 'error'
            assert 'frame too large' in rejected['payload']['reason']
    finally:
        await service.stop()


def test_host_authentication_revocation_and_quota_release(tmp_path: Path) -> None:
    asyncio.run(_host_authentication_revocation_and_quota_release(tmp_path))


async def _host_authentication_revocation_and_quota_release(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path, max_sessions=1)
    try:
        async with _client_session() as client:
            bad_host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            bad_register = _host_register_frame(issued, session_id='bad-host', signer=generate_host_private_key())
            await bad_host.send_json(bad_register.to_json())
            assert 'proof rejected' in (await bad_host.receive_json())['payload']['reason']

            missing_capability = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            register_without_forward = _host_register_frame(issued, session_id='missing-forward').to_json()
            register_without_forward['payload']['capabilities'] = ['relay.observe']
            await missing_capability.send_json(register_without_forward)
            assert 'relay.forward' in (await missing_capability.receive_json())['payload']['reason']

            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(_client_hello(session_id='quota-session', host_id=issued.host_id).to_json())
            await host.receive_json()

            second_phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await second_phone.send_json(_client_hello(session_id='quota-session-2', host_id=issued.host_id).to_json())
            assert 'quota exceeded' in (await second_phone.receive_json())['payload']['reason']

            await phone.close()
            await asyncio.sleep(0.05)
            assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 0

            issued.store.revoke_host(issued.host_id, reason='test revoke')
            revoked_phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await revoked_phone.send_json(_client_hello(session_id='revoked-session', host_id=issued.host_id).to_json())
            assert 'not active' in (await revoked_phone.receive_json())['payload']['reason']
    finally:
        await service.stop()


def test_heartbeat_and_bounded_peer_queue_backpressure(tmp_path: Path) -> None:
    asyncio.run(_heartbeat_and_bounded_peer_queue_backpressure(tmp_path))


async def _heartbeat_and_bounded_peer_queue_backpressure(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path, idle_timeout=0.5, peer_queue_limit=1)
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            await host.receive_json()
            await host.send_json(
                {
                    'schema_version': 2,
                    'session_id': 'host-control',
                    'seq': 2,
                    'kind': 'heartbeat',
                    'payload': {},
                }
            )
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(_client_hello(session_id='backpressure-session', host_id=issued.host_id).to_json())
            await host.receive_json()
            service._sessions['backpressure-session'].host.writer_task.cancel()

            await phone.send_json(
                _gateway_frame(
                    session_id='backpressure-session',
                    outer_seq=3,
                    envelope=_relay_envelope(
                        session_id='backpressure-session',
                        direction=RelayDirection.PHONE_TO_HOST,
                        seq=1,
                        plaintext=b'first',
                    ),
                )
            )
            await phone.send_json(
                _gateway_frame(
                    session_id='backpressure-session',
                    outer_seq=4,
                    envelope=_relay_envelope(
                        session_id='backpressure-session',
                        direction=RelayDirection.PHONE_TO_HOST,
                        seq=2,
                        plaintext=b'second',
                    ),
                )
            )
            error = await phone.receive_json()
            assert error['kind'] == 'close'
            assert error['payload']['reason'] == 'slow_consumer'
            assert service.metrics_snapshot()['slow_consumer_disconnects'] >= 1
    finally:
        await service.stop()


def test_rate_limit_idle_timeout_restart_and_graceful_drain(tmp_path: Path) -> None:
    asyncio.run(_rate_limit_idle_timeout_restart_and_graceful_drain(tmp_path))


async def _rate_limit_idle_timeout_restart_and_graceful_drain(tmp_path: Path) -> None:
    service, issued = await _started_service(
        tmp_path,
        idle_timeout=0.25,
        unauth_rate_limit=2,
        unauth_rate_limit_window=60,
    )
    try:
        async with _client_session() as client:
            idle_host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await asyncio.sleep(0.5)
            idle_message = await idle_host.receive()
            if idle_message.type == aiohttp.WSMsgType.TEXT:
                assert 'idle timeout' in json.loads(idle_message.data)['payload']['reason']
            else:
                assert idle_host.closed or idle_message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                }

            denied = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await denied.send_json(_host_register_frame(issued, session_id='rate-1').to_json())
            await denied.receive_json()
            with pytest.raises(aiohttp.ClientResponseError) as excinfo:
                await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            assert excinfo.value.status == 429
    finally:
        await service.stop()

    restarted = ProductionRelayService(service.config, admission_store=issued.store)
    await restarted.start()
    try:
        async with _client_session() as client:
            host = await client.ws_connect(restarted.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-after-restart').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(restarted.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(_client_hello(session_id='drain-session', host_id=issued.host_id).to_json())
            await host.receive_json()
            await restarted.drain()
            assert restarted.metrics_snapshot()['draining'] is True
            with pytest.raises(aiohttp.ClientResponseError) as excinfo:
                await client.ws_connect(restarted.url('/v2/phone'), ssl=_client_ssl())
            assert excinfo.value.status == 503
    finally:
        await restarted.stop()


def test_tls_is_required_except_explicit_loopback_test_mode(tmp_path: Path) -> None:
    cert_path, key_path = _write_self_signed_cert(tmp_path)
    ProductionRelayConfig(
        listen_host='127.0.0.1',
        listen_port=0,
        tls_cert_file=cert_path,
        tls_key_file=key_path,
        admission_db_path=tmp_path / 'relay.sqlite3',
        state_dir=tmp_path / 'state',
    ).validate()

    with pytest.raises(ValueError, match='TLS certificate'):
        ProductionRelayConfig(
            listen_host='0.0.0.0',
            listen_port=443,
            admission_db_path=tmp_path / 'relay.sqlite3',
            state_dir=tmp_path / 'state',
        ).validate()

    with pytest.raises(ValueError, match='public origin'):
        ProductionRelayConfig(
            listen_host='127.0.0.1',
            listen_port=0,
            public_origin='http://relay.invalid',
            tls_cert_file=cert_path,
            tls_key_file=key_path,
            admission_db_path=tmp_path / 'relay.sqlite3',
            state_dir=tmp_path / 'state',
        ).validate()

    with pytest.raises(ValueError, match='loopback'):
        ProductionRelayConfig(
            listen_host='0.0.0.0',
            listen_port=8080,
            admission_db_path=tmp_path / 'relay.sqlite3',
            state_dir=tmp_path / 'state',
            unsafe_plaintext_for_tests=True,
        ).validate()


@dataclass
class _IssuedHost:
    store: RelayAdmissionStore
    host_id: str
    private_key: Any


async def _started_service(
    tmp_path: Path,
    *,
    max_sessions: int = 4,
    max_bytes_per_day: int = 1024 * 1024,
    max_frame_bytes: int = 4096,
    peer_queue_limit: int = 4,
    idle_timeout: float = 5.0,
    unauth_rate_limit: int = 100,
    unauth_rate_limit_window: float = 60.0,
) -> tuple[ProductionRelayService, _IssuedHost]:
    cert_path, key_path = _write_self_signed_cert(tmp_path)
    secrets = RelayAdmissionSecrets.generate_for_testing()
    store = RelayAdmissionStore(tmp_path / 'relay.sqlite3', admission_secrets=secrets)
    host_private = generate_host_private_key()
    invitation = store.issue_invitation(
        ttl_seconds=600,
        max_sessions=max_sessions,
        max_bytes_per_day=max_bytes_per_day,
    )
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(host_private),
    )
    config = ProductionRelayConfig(
        listen_host='127.0.0.1',
        listen_port=0,
        tls_cert_file=cert_path,
        tls_key_file=key_path,
        admission_db_path=tmp_path / 'relay.sqlite3',
        state_dir=tmp_path / 'state',
        max_frame_bytes=max_frame_bytes,
        peer_queue_limit=peer_queue_limit,
        write_timeout=1.0,
        idle_timeout=idle_timeout,
        heartbeat_interval=0.1,
        unauth_rate_limit=unauth_rate_limit,
        unauth_rate_limit_window=unauth_rate_limit_window,
    )
    service = ProductionRelayService(config, admission_store=store)
    await service.start()
    return service, _IssuedHost(store=store, host_id=credential.host_id, private_key=host_private)


def _host_register_frame(
    issued: _IssuedHost,
    *,
    session_id: str,
    signer: Any | None = None,
):
    nonce_b64 = _b64(f'nonce-{session_id}'.encode('utf-8'))
    expires_at = int(__import__('time').time()) + 30
    signing_key = signer or issued.private_key
    return _RelayFrame(
        session_id=session_id,
        seq=1,
        kind='host_register',
        payload={
            'host_id': issued.host_id,
            'nonce_b64': nonce_b64,
            'proof_expires_at': expires_at,
            'signature_b64': sign_host_session_proof(
                signing_key,
                host_id=issued.host_id,
                nonce_b64=nonce_b64,
                expires_at=expires_at,
            ),
            'supported_versions': [2],
            'capabilities': ['relay.forward'],
        },
    )


def _client_hello(*, session_id: str, host_id: str):
    return _RelayFrame(
        session_id=session_id,
        seq=1,
        kind='client_hello',
        payload={
            'host_id': host_id,
            'device_id': 'device-public-routing-id',
            'client_pubkey_b64': _b64(b'client public key'),
            'supported_versions': [2],
        },
    )


def _host_hello(*, session_id: str, host_id: str):
    return _RelayFrame(
        session_id=session_id,
        seq=2,
        kind='host_hello',
        payload={
            'host_id': host_id,
            'server_fingerprint': 'sha256:host-fingerprint',
            'host_pubkey_b64': _b64(b'host public key'),
            'accepted_version': 2,
        },
    )


def _gateway_frame(*, session_id: str, outer_seq: int, envelope: RelayV2Envelope) -> dict[str, object]:
    return {
        'schema_version': 2,
        'session_id': session_id,
        'seq': outer_seq,
        'kind': 'gateway_envelope',
        'payload': {'envelope': envelope.to_json()},
    }


def _relay_envelope(
    *,
    session_id: str,
    direction: RelayDirection,
    seq: int,
    plaintext: bytes,
) -> RelayV2Envelope:
    client_private = key_pair_from_private_bytes(bytes(range(1, 33)))
    host_private = key_pair_from_private_bytes(bytes(range(101, 133)))
    client_public = public_key_b64(client_private)
    host_public = public_key_b64(host_private)
    schedule = derive_relay_v2_key_schedule(
        local_private_key=client_private if direction == RelayDirection.PHONE_TO_HOST else host_private,
        peer_public_key_b64=host_public if direction == RelayDirection.PHONE_TO_HOST else client_public,
        role='phone' if direction == RelayDirection.PHONE_TO_HOST else 'host',
        session_id=session_id,
        client_public_key_b64=client_public,
        host_public_key_b64=host_public,
        expected_host_fingerprint='sha256:' + _b64(__import__('hashlib').sha256(_b64decode(host_public)).digest()),
    )
    crypto = schedule.session(role='phone' if direction == RelayDirection.PHONE_TO_HOST else 'host')
    while crypto._next_send_seq < seq:
        crypto.seal(op='padding', plaintext=b'pad')
    return crypto.seal(op='gateway', plaintext=plaintext)


class _RelayFrame:
    def __init__(self, *, session_id: str, seq: int, kind: str, payload: dict[str, object]):
        self.session_id = session_id
        self.seq = seq
        self.kind = kind
        self.payload = payload

    def to_json(self) -> dict[str, object]:
        return {
            'schema_version': 2,
            'session_id': self.session_id,
            'seq': self.seq,
            'kind': self.kind,
            'payload': self.payload,
        }


def _client_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(raise_for_status=True)


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
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.DNSName('127.0.0.1')]), critical=False)
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


def _assert_canary_not_persisted(root: Path, canary: str) -> None:
    needle = canary.encode('utf-8')
    for path in root.rglob('*'):
        if path.is_file() and path.suffix not in {'.pem'}:
            assert needle not in path.read_bytes(), path


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + '=' * (-len(value) % 4)).encode('ascii'))
