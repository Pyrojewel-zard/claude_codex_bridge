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
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, x25519
from cryptography.x509.oid import NameOID

from mobile_gateway.relay_crypto import (
    RelayDirection,
    RelayV2Envelope,
    key_pair_from_private_bytes,
    derive_relay_v2_key_schedule,
    public_key_b64,
)
from mobile_gateway.relay import (
    issue_host_access_grant,
    issue_host_rendezvous_capability,
    issue_phone_session_proof,
)
from mobile_gateway.relay_admission import (
    RelayAdmissionSecrets,
    RelayAdmissionStore,
    generate_host_private_key,
    host_public_key_b64,
    sign_host_session_proof,
)
from mobile_gateway.relay_service import (
    ProductionRelayConfig,
    ProductionRelayService,
    _PeerEndpoint,
)
from mobile_gateway.relay_host_credentials import (
    CCB_OFFICIAL_RELAY_ORIGIN,
    RELAY_MODE_OFFICIAL,
    RELAY_MODE_SELF_HOSTED,
    RelayHostCredentials,
    RelayHostCredentialsError,
    activate_relay_host,
    load_relay_host_credentials,
)


def test_official_mode_rejects_custom_relay_origin() -> None:
    with pytest.raises(RelayHostCredentialsError, match='official relay mode'):
        RelayHostCredentials(
            relay_origin='wss://relay.example.test',
            host_id='host-test',
            invitation_id='invite-test',
            host_signing_private_key_b64='a' * 43,
            host_crypto_private_key_b64='b' * 43,
            activated_at='2026-07-25T00:00:00+00:00',
            relay_mode=RELAY_MODE_OFFICIAL,
        )
    assert CCB_OFFICIAL_RELAY_ORIGIN == 'wss://47.120.71.142'
from mobile_gateway.relay_host_runtime import (
    RelayHostConnectorRuntime,
    RelayHostRuntimeError,
)


def test_public_activation_consumes_invitation_once_without_persisting_secret(
    tmp_path: Path,
) -> None:
    asyncio.run(_public_activation_consumes_invitation_once(tmp_path))


async def _public_activation_consumes_invitation_once(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path)
    invitation = issued.store.issue_invitation(ttl_seconds=120)
    signing_key = generate_host_private_key()
    raw_invitation = invitation.invitation
    url = service.url('/v2/activate').replace('wss://', 'https://', 1)
    try:
        async with _client_session() as client:
            response = await client.post(
                url,
                ssl=_client_ssl(),
                json={
                    'invitation': raw_invitation,
                    'host_public_key_b64': host_public_key_b64(signing_key),
                },
            )
            assert response.status == 201
            credential = await response.json()
            assert credential['type'] == 'ccb_relay_host_credential_v1'
            assert credential['invitation_id'] == invitation.invite_id
            assert credential['host_public_key_b64'] == host_public_key_b64(
                signing_key
            )
            assert raw_invitation not in json.dumps(credential, sort_keys=True)

            with pytest.raises(aiohttp.ClientResponseError) as replay_error:
                await client.post(
                    url,
                    ssl=_client_ssl(),
                    json={
                        'invitation': raw_invitation,
                        'host_public_key_b64': host_public_key_b64(signing_key),
                    },
                )
            assert replay_error.value.status == 401
            assert raw_invitation not in str(replay_error.value)

        assert issued.store.invitation_status(invitation.invite_id)['state'] == 'consumed'
        assert service.metrics_snapshot()['activation_attempts'] == 2
        assert service.metrics_snapshot()['activation_successes'] == 1
        _assert_canary_not_persisted(tmp_path, raw_invitation)
    finally:
        await service.stop()


def test_host_activation_client_persists_owner_only_bound_keys(tmp_path: Path) -> None:
    asyncio.run(_host_activation_client_persists_owner_only_bound_keys(tmp_path))


async def _host_activation_client_persists_owner_only_bound_keys(
    tmp_path: Path,
) -> None:
    service, issued = await _started_service(tmp_path)
    invitation = issued.store.issue_invitation(ttl_seconds=120)
    credential_path = tmp_path / 'client-state' / 'relay-host-credentials.json'
    try:
        credentials = await asyncio.to_thread(
            activate_relay_host,
            relay_mode=RELAY_MODE_SELF_HOSTED,
            relay_origin=service.url('/').removesuffix('/'),
            invitation=invitation.invitation,
            credential_path=credential_path,
            ssl_context=_client_ssl(),
        )
        loaded = load_relay_host_credentials(credential_path)

        assert loaded == credentials
        assert credential_path.stat().st_mode & 0o777 == 0o600
        assert credentials.host_id == issued.store.invitation_status(
            invitation.invite_id
        )['host_id']
        assert credentials.host_signing_public_key_b64 == issued.store.host_public_key_for_rendezvous(
            credentials.host_id
        )
        assert invitation.invitation not in credential_path.read_text(encoding='utf-8')
    finally:
        await service.stop()


def test_host_runtime_registers_real_outbound_connector_and_stops_cleanly(
    tmp_path: Path,
) -> None:
    asyncio.run(_host_runtime_registers_and_stops(tmp_path))


async def _host_runtime_registers_and_stops(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path)
    credentials = RelayHostCredentials(
        relay_origin=service.url('/').removesuffix('/'),
        host_id=issued.host_id,
        invitation_id='already-consumed',
        host_signing_private_key_b64=_raw_private_key_b64(issued.private_key),
        host_crypto_private_key_b64=_raw_private_key_b64(
            x25519.X25519PrivateKey.generate()
        ),
        activated_at='2026-07-22T00:00:00+00:00',
        relay_mode=RELAY_MODE_SELF_HOSTED,
    )
    runtime = RelayHostConnectorRuntime(
        credentials=credentials,
        gateway_origin='http://127.0.0.1:9',
        tls_context=_client_ssl(),
    )
    try:
        await asyncio.to_thread(runtime.start)
        for _ in range(80):
            if service.metrics_snapshot()['active_hosts'] == 1:
                break
            await asyncio.sleep(0.05)
        assert service.metrics_snapshot()['active_hosts'] == 1
        assert runtime.diagnostics()['state'] == 'registered'
    finally:
        await asyncio.to_thread(runtime.stop)
        await service.stop()


def test_host_runtime_fails_startup_for_revoked_credentials(tmp_path: Path) -> None:
    asyncio.run(_host_runtime_fails_startup_for_revoked_credentials(tmp_path))


async def _host_runtime_fails_startup_for_revoked_credentials(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path)
    issued.store.revoke_host(issued.host_id, reason='test revoked runtime')
    credentials = RelayHostCredentials(
        relay_origin=service.url('/').removesuffix('/'),
        host_id=issued.host_id,
        invitation_id='already-consumed',
        host_signing_private_key_b64=_raw_private_key_b64(issued.private_key),
        host_crypto_private_key_b64=_raw_private_key_b64(
            x25519.X25519PrivateKey.generate()
        ),
        activated_at='2026-07-22T00:00:00+00:00',
        relay_mode=RELAY_MODE_SELF_HOSTED,
    )
    runtime = RelayHostConnectorRuntime(
        credentials=credentials,
        gateway_origin='http://127.0.0.1:9',
        tls_context=_client_ssl(),
    )
    try:
        with pytest.raises(RelayHostRuntimeError, match='authentication|failed to start'):
            await asyncio.to_thread(runtime.start, timeout_seconds=1.0)
        assert service.metrics_snapshot()['active_hosts'] == 0
    finally:
        await asyncio.to_thread(runtime.stop)
        await service.stop()


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
            client_hello = _client_hello(issued=issued, session_id='relay-session-1', host_id=issued.host_id)
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
            assert rejected['payload'] == {'code': 'relay_frame_rejected', 'message': 'relay frame rejected'}

            oversized = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await oversized.send_str(json.dumps({'padding': 'x' * 1200}))
            rejected = await oversized.receive_json()
            assert rejected['kind'] == 'error'
            assert rejected['payload'] == {'code': 'relay_frame_rejected', 'message': 'relay frame rejected'}
    finally:
        await service.stop()


def test_phone_rendezvous_required_before_quota_or_host_forward(tmp_path: Path) -> None:
    asyncio.run(_phone_rendezvous_required_before_quota_or_host_forward(tmp_path))


async def _phone_rendezvous_required_before_quota_or_host_forward(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path, max_sessions=1)
    canary = 'RENDEZVOUS-CANARY-session-and-kind'
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(
                {
                    'schema_version': 2,
                    'session_id': canary,
                    'seq': 1,
                    'kind': 'client_hello',
                    'payload': {
                        'host_id': issued.host_id,
                        'device_id': 'device-public-routing-id',
                        'client_pubkey_b64': _b64(b'client public key'),
                        'phone_nonce_b64': _b64(b'fresh phone nonce'),
                        'supported_versions': [2],
                    },
                }
            )
            rejected = await phone.receive_json()
            assert rejected == {
                'schema_version': 2,
                'session_id': 'relay-control',
                'seq': 1,
                'kind': 'error',
                'payload': {
                    'code': 'relay_auth_rejected',
                    'message': 'relay authentication rejected',
                },
            }
            assert canary not in json.dumps(rejected)
            assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 0
            await _assert_no_host_frame(host)
            _assert_canary_not_persisted(tmp_path, canary)
    finally:
        await service.stop()


def test_rendezvous_valid_replay_mismatch_and_expiry(tmp_path: Path) -> None:
    asyncio.run(_rendezvous_valid_replay_mismatch_and_expiry(tmp_path))


async def _rendezvous_valid_replay_mismatch_and_expiry(tmp_path: Path) -> None:
    # Keep this authentication test independent from the deliberately aggressive
    # default test heartbeat, which can close an otherwise idle host on slow CI.
    service, issued = await _started_service(
        tmp_path,
        max_sessions=4,
        heartbeat_interval=5.0,
    )
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            valid_hello = _client_hello(issued=issued, session_id='rv-valid', host_id=issued.host_id)
            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(valid_hello.to_json())
            assert await host.receive_json() == valid_hello.to_json()
            await phone.close()
            assert (await host.receive_json())['kind'] == 'close'
            await _wait_for_active_sessions(issued, 0)

            replay = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await replay.send_json(valid_hello.to_json())
            assert (await replay.receive_json())['payload']['code'] == 'relay_auth_rejected'
            assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 0
            await _assert_no_host_frame(host)

            token_client_pubkey = _b64(b'token client key')
            frame_client_pubkey = _b64(b'frame client key')
            phone_nonce = _b64(b'mismatch phone nonce')
            mismatch_token = issue_host_rendezvous_capability(
                issued.private_key,
                host_id=issued.host_id,
                session_id='rv-mismatch',
                client_pubkey_b64=token_client_pubkey,
                phone_nonce_b64=phone_nonce,
                audience='wss://relay.seemlab.top',
                expires_at=int(time.time()) + 30,
            )
            mismatch = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await mismatch.send_json(
                _client_hello(
                    session_id='rv-mismatch',
                    host_id=issued.host_id,
                    client_pubkey_b64=frame_client_pubkey,
                    phone_nonce_b64=phone_nonce,
                    rendezvous_capability=mismatch_token,
                ).to_json()
            )
            assert (await mismatch.receive_json())['payload']['code'] == 'relay_auth_rejected'

            wrong_audience = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await wrong_audience.send_json(
                _client_hello(
                    issued=issued,
                    session_id='rv-wrong-audience',
                    host_id=issued.host_id,
                    audience='wss://other-relay.invalid',
                ).to_json()
            )
            assert (await wrong_audience.receive_json())['payload']['code'] == 'relay_auth_rejected'

            now = int(time.time())
            expired_nonce = _b64(b'expired phone nonce')
            expired_token = issue_host_rendezvous_capability(
                issued.private_key,
                host_id=issued.host_id,
                session_id='rv-expired',
                client_pubkey_b64=_b64(b'expired client key'),
                phone_nonce_b64=expired_nonce,
                audience='wss://relay.seemlab.top',
                issued_at=now - 60,
                expires_at=now - 1,
            )
            expired = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await expired.send_json(
                _client_hello(
                    session_id='rv-expired',
                    host_id=issued.host_id,
                    client_pubkey_b64=_b64(b'expired client key'),
                    phone_nonce_b64=expired_nonce,
                    rendezvous_capability=expired_token,
                ).to_json()
            )
            assert (await expired.receive_json())['payload']['code'] == 'relay_auth_rejected'
            assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 0
            await _assert_no_host_frame(host)
    finally:
        await service.stop()


def test_durable_phone_grant_allows_fresh_reconnect_and_rejects_proof_replay(
    tmp_path: Path,
) -> None:
    asyncio.run(_durable_phone_grant_allows_fresh_reconnect_and_rejects_proof_replay(tmp_path))


async def _durable_phone_grant_allows_fresh_reconnect_and_rejects_proof_replay(
    tmp_path: Path,
) -> None:
    service, issued = await _started_service(tmp_path, max_sessions=4)
    phone_key = ed25519.Ed25519PrivateKey.generate()
    now = int(time.time())
    grant = issue_host_access_grant(
        issued.private_key,
        host_id=issued.host_id,
        device_id='device-durable',
        phone_auth_pubkey_b64=_ed25519_public_b64(phone_key),
        audience='wss://relay.seemlab.top',
        scopes=('view', 'notify'),
        issued_at=now,
        expires_at=now + 3600,
    )
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            first_hello = _access_client_hello(
                session_id='access-session-1',
                host_id=issued.host_id,
                phone_key=phone_key,
                access_grant=grant,
            )
            first = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await first.send_json(first_hello.to_json())
            assert await host.receive_json() == first_hello.to_json()
            await first.close()
            assert (await host.receive_json())['kind'] == 'close'
            await _wait_for_active_sessions(issued, 0)

            replay = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await replay.send_json(first_hello.to_json())
            assert (await replay.receive_json())['payload']['code'] == 'relay_auth_rejected'

            second_hello = _access_client_hello(
                session_id='access-session-2',
                host_id=issued.host_id,
                phone_key=phone_key,
                access_grant=grant,
            )
            second = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await second.send_json(second_hello.to_json())
            assert await host.receive_json() == second_hello.to_json()
            await second.close()
            assert (await host.receive_json())['kind'] == 'close'
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
            assert (await bad_host.receive_json())['payload'] == {
                'code': 'relay_auth_rejected',
                'message': 'relay authentication rejected',
            }

            missing_capability = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            register_without_forward = _host_register_frame(issued, session_id='missing-forward').to_json()
            register_without_forward['payload']['capabilities'] = ['relay.observe']
            await missing_capability.send_json(register_without_forward)
            assert (await missing_capability.receive_json())['payload']['code'] == 'relay_rejected'

            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(_host_register_frame(issued, session_id='host-control').to_json())
            assert (await host.receive_json())['kind'] == 'ack'

            phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await phone.send_json(_client_hello(issued=issued, session_id='quota-session', host_id=issued.host_id).to_json())
            await host.receive_json()

            second_hello = _client_hello(
                issued=issued,
                session_id='quota-session-2',
                host_id=issued.host_id,
            )
            second_phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await second_phone.send_json(second_hello.to_json())
            assert (await second_phone.receive_json())['payload'] == {
                'code': 'relay_auth_rejected',
                'message': 'relay authentication rejected',
            }

            await phone.close()
            assert (await host.receive_json())['kind'] == 'close'
            await _wait_for_active_sessions(issued, 0)

            retry_phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await retry_phone.send_json(second_hello.to_json())
            assert await host.receive_json() == second_hello.to_json()
            await retry_phone.close()
            assert (await host.receive_json())['kind'] == 'close'
            await _wait_for_active_sessions(issued, 0)

            issued.store.revoke_host(issued.host_id, reason='test revoke')
            revoked_phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await revoked_phone.send_json(_client_hello(issued=issued, session_id='revoked-session', host_id=issued.host_id).to_json())
            assert (await revoked_phone.receive_json())['payload']['code'] == 'relay_auth_rejected'
    finally:
        await service.stop()


def test_heartbeat_and_bounded_peer_queue_backpressure(tmp_path: Path) -> None:
    asyncio.run(_heartbeat_and_bounded_peer_queue_backpressure(tmp_path))


def test_peer_queue_absorbs_transient_writer_backpressure() -> None:
    asyncio.run(_peer_queue_absorbs_transient_writer_backpressure())


async def _peer_queue_absorbs_transient_writer_backpressure() -> None:
    release_writer = asyncio.Event()
    writer_started = asyncio.Event()
    slow_consumers: list[object] = []

    class _DelayedWebSocket:
        closed = False

        async def send_str(self, _payload: str) -> None:
            writer_started.set()
            await release_writer.wait()

        async def close(self, *, code: int, message: bytes) -> None:
            self.closed = True

    endpoint = _PeerEndpoint(
        role='phone',
        websocket=_DelayedWebSocket(),
        queue_limit=1,
        write_timeout=0.5,
    )
    endpoint.start_writer(slow_consumers.append)
    try:
        await endpoint.send_frame({'seq': 1})
        await writer_started.wait()
        await endpoint.send_frame({'seq': 2})
        pending = asyncio.create_task(endpoint.send_frame({'seq': 3}))
        await asyncio.sleep(0.05)
        assert not pending.done()

        release_writer.set()
        await asyncio.wait_for(pending, timeout=0.5)

        assert slow_consumers == []
        assert endpoint.closed is False
    finally:
        await endpoint.close()


async def _heartbeat_and_bounded_peer_queue_backpressure(tmp_path: Path) -> None:
    service, issued = await _started_service(
        tmp_path,
        idle_timeout=0.5,
        peer_queue_limit=1,
        write_timeout=0.1,
        heartbeat_interval=5.0,
    )
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
            await phone.send_json(_client_hello(issued=issued, session_id='backpressure-session', host_id=issued.host_id).to_json())
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
            try:
                idle_message = await idle_host.receive()
            except aiohttp.ClientConnectionError:
                idle_message = None
            if idle_message is not None and idle_message.type == aiohttp.WSMsgType.TEXT:
                assert json.loads(idle_message.data)['payload'] == {
                    'code': 'relay_rejected',
                    'message': 'relay request rejected',
                }
            elif idle_message is not None:
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
            await phone.send_json(_client_hello(issued=issued, session_id='drain-session', host_id=issued.host_id).to_json())
            await host.receive_json()
            await restarted.drain()
            assert restarted.metrics_snapshot()['draining'] is True
            with pytest.raises(aiohttp.ClientResponseError) as excinfo:
                await client.ws_connect(restarted.url('/v2/phone'), ssl=_client_ssl())
            assert excinfo.value.status == 503
    finally:
        await restarted.stop()


def test_registered_connections_use_heartbeat_instead_of_business_idle_timeout(
    tmp_path: Path,
) -> None:
    asyncio.run(_registered_connections_use_heartbeat(tmp_path))


async def _registered_connections_use_heartbeat(tmp_path: Path) -> None:
    service, issued = await _started_service(
        tmp_path,
        idle_timeout=0.1,
        heartbeat_interval=0.2,
    )
    try:
        async with _client_session() as client:
            host = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
            await host.send_json(
                _host_register_frame(issued, session_id='heartbeat-host').to_json()
            )
            assert (await host.receive_json())['kind'] == 'ack'

            pending_receive = asyncio.create_task(host.receive())
            await asyncio.sleep(0.7)
            assert not host.closed
            await host.send_json(
                {
                    'schema_version': 2,
                    'session_id': 'host-control',
                    'seq': 2,
                    'kind': 'heartbeat',
                    'payload': {},
                }
            )
            message = await pending_receive
            assert message.type == aiohttp.WSMsgType.TEXT
            assert json.loads(message.data)['kind'] == 'ack'
    finally:
        await service.stop()


def test_service_start_reconciles_crashed_sessions_and_enforces_single_instance(
    tmp_path: Path,
) -> None:
    asyncio.run(_service_start_reconciles_crashed_sessions(tmp_path))


async def _service_start_reconciles_crashed_sessions(tmp_path: Path) -> None:
    service, issued = await _started_service(tmp_path)
    issued.store.reserve_host_session(
        host_id=issued.host_id,
        session_id='orphaned-after-crash',
    )
    await service.stop()
    assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 1

    restarted = ProductionRelayService(service.config, admission_store=issued.store)
    await restarted.start()
    try:
        assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == 0
        duplicate = ProductionRelayService(service.config, admission_store=issued.store)
        with pytest.raises(RuntimeError, match='another relay service instance'):
            await duplicate.start()
        await duplicate.stop()
    finally:
        await restarted.stop()


def test_rate_limiter_bounds_unique_source_keys(tmp_path: Path) -> None:
    asyncio.run(_rate_limiter_bounds_unique_source_keys(tmp_path))


async def _rate_limiter_bounds_unique_source_keys(tmp_path: Path) -> None:
    service, _issued = await _started_service(
        tmp_path,
        unauth_rate_limit=10,
        unauth_rate_limit_max_keys=3,
    )
    try:
        async with _client_session() as client:
            for index in range(8):
                address = f'203.0.113.{index + 1}'
                socket = await client.ws_connect(
                    service.url('/v2/host'),
                    ssl=_client_ssl(),
                    headers={
                        'X-CCB-Client-IP': address,
                        'X-Forwarded-For': address,
                    },
                )
                await socket.close()
        assert service._rate_limiter.key_count <= 3
    finally:
        await service.stop()


def test_public_admin_endpoints_absent_and_admin_loopback_only(tmp_path: Path) -> None:
    asyncio.run(_public_admin_endpoints_absent_and_admin_loopback_only(tmp_path))


async def _public_admin_endpoints_absent_and_admin_loopback_only(tmp_path: Path) -> None:
    service, _issued = await _started_service(tmp_path)
    try:
        async with aiohttp.ClientSession(raise_for_status=False) as client:
            public_metrics = await client.get(_public_http_url(service, '/metrics'), ssl=_client_ssl())
            assert public_metrics.status == 404
            public_health = await client.get(_public_http_url(service, '/healthz'), ssl=_client_ssl())
            assert public_health.status == 404
            admin_metrics = await client.get(service.admin_url('/metrics'))
            assert admin_metrics.status == 200
            assert 'payload_bytes_persisted' in await admin_metrics.text()
            admin_ready = await client.get(service.admin_url('/readyz'))
            assert admin_ready.status == 200
    finally:
        await service.stop()


def test_trusted_proxy_client_ip_rate_limit_and_spoofing(tmp_path: Path) -> None:
    asyncio.run(_trusted_proxy_client_ip_rate_limit_and_spoofing(tmp_path))


async def _trusted_proxy_client_ip_rate_limit_and_spoofing(tmp_path: Path) -> None:
    service, _issued = await _started_service(tmp_path, unauth_rate_limit=1)
    try:
        async with _client_session() as client:
            first = await client.ws_connect(
                service.url('/v2/host'),
                ssl=_client_ssl(),
                headers={'X-CCB-Client-IP': '203.0.113.10', 'X-Forwarded-For': '203.0.113.10'},
            )
            await first.close()
            with pytest.raises(aiohttp.ClientResponseError) as excinfo:
                await client.ws_connect(
                    service.url('/v2/host'),
                    ssl=_client_ssl(),
                    headers={'X-CCB-Client-IP': '203.0.113.10', 'X-Forwarded-For': '203.0.113.10'},
                )
            assert excinfo.value.status == 429

            other_client_ip = await client.ws_connect(
                service.url('/v2/host'),
                ssl=_client_ssl(),
                headers={'X-CCB-Client-IP': '203.0.113.11', 'X-Forwarded-For': '203.0.113.11'},
            )
            await other_client_ip.close()

            with pytest.raises(aiohttp.ClientResponseError) as bad_header:
                await client.ws_connect(
                    service.url('/v2/host'),
                    ssl=_client_ssl(),
                    headers={'X-CCB-Client-IP': '203.0.113.12, 203.0.113.13'},
                )
            assert bad_header.value.status == 400
    finally:
        await service.stop()

    untrusted, _issued = await _started_service(
        tmp_path / 'untrusted',
        unauth_rate_limit=1,
        trusted_proxy_cidrs=(),
    )
    try:
        async with _client_session() as client:
            first = await client.ws_connect(
                untrusted.url('/v2/host'),
                ssl=_client_ssl(),
                headers={'X-CCB-Client-IP': '203.0.113.20'},
            )
            await first.close()
            with pytest.raises(aiohttp.ClientResponseError) as spoofed:
                await client.ws_connect(
                    untrusted.url('/v2/host'),
                    ssl=_client_ssl(),
                    headers={'X-CCB-Client-IP': '203.0.113.21'},
                )
            assert spoofed.value.status == 429
    finally:
        await untrusted.stop()


def test_protocol_ws_cap_binary_and_canary_redaction(tmp_path: Path) -> None:
    asyncio.run(_protocol_ws_cap_binary_and_canary_redaction(tmp_path))


async def _protocol_ws_cap_binary_and_canary_redaction(tmp_path: Path) -> None:
    service, _issued = await _started_service(
        tmp_path,
        max_frame_bytes=300,
        websocket_max_msg_bytes=384,
        unauth_rate_limit=10,
    )
    canary = 'PREBUFFER-CANARY-secret-kind-session'
    try:
        async with _client_session() as client:
            semantic = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await semantic.send_json(
                {
                    'schema_version': 2,
                    'session_id': canary,
                    'seq': 1,
                    'kind': f'proxy_connect_{canary}',
                    'payload': {'padding': canary},
                }
            )
            semantic_error = await semantic.receive_json()
            assert semantic_error['payload'] == {'code': 'relay_frame_rejected', 'message': 'relay frame rejected'}
            assert canary not in json.dumps(semantic_error)

            binary = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await binary.send_bytes(canary.encode('utf-8'))
            binary_message = await binary.receive()
            if binary_message.type == aiohttp.WSMsgType.TEXT:
                assert canary not in binary_message.data
                assert json.loads(binary_message.data)['payload']['code'] == 'relay_rejected'

            oversized = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
            await oversized.send_str(json.dumps({'padding': canary * 80}))
            oversized_message = await oversized.receive()
            if oversized_message.type == aiohttp.WSMsgType.TEXT:
                assert canary not in oversized_message.data
                assert json.loads(oversized_message.data)['payload']['code'] in {'relay_frame_rejected', 'relay_rejected'}
            else:
                assert oversized_message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
            _assert_canary_not_persisted(tmp_path, canary)
    finally:
        await service.stop()


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

    with pytest.raises(ValueError, match='admin listener'):
        ProductionRelayConfig(
            listen_host='127.0.0.1',
            listen_port=0,
            admin_host='0.0.0.0',
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


def test_relay_deployment_templates_match_tested_runtime_limits() -> None:
    project_root = Path(__file__).resolve().parents[1]
    deploy_root = project_root / 'deploy' / 'mobile-relay'
    environment = (deploy_root / 'ccb-mobile-relay.env.example').read_text(
        encoding='utf-8'
    )
    service = (deploy_root / 'ccb-mobile-relay.service').read_text(
        encoding='utf-8'
    )
    nginx = (deploy_root / 'nginx-relay.seemlab.top.conf').read_text(
        encoding='utf-8'
    )
    bootstrap = (deploy_root / 'nginx-relay-acme-bootstrap.conf').read_text(
        encoding='utf-8'
    )

    assert 'CCB_RELAY_MAX_FRAME_BYTES=786432' in environment
    assert 'CCB_RELAY_WEBSOCKET_MAX_MSG_BYTES=790528' in environment
    assert 'CCB_RELAY_PEER_QUEUE_LIMIT=8' in environment
    assert (
        'ExecStart=/opt/ccb-relay-venv/bin/python -m mobile_gateway.relay_service'
        in service
    )
    assert 'Documentation=file:/opt/ccb-source/' in service
    assert 'proxy_pass https://127.0.0.1:18444;' in nginx
    assert 'proxy_ssl_protocols TLSv1.3;' in nginx
    assert '$ccb_relay_connection_upgrade' in nginx
    assert 'ssl_protocols TLSv1.2 TLSv1.3;' in nginx
    assert '18445' not in nginx.split('server {', 1)[-1]
    assert 'listen 80;' in bootstrap
    assert 'listen 443' not in bootstrap
    assert '/var/www/ccb-mobile-relay-acme' in bootstrap
    assert '18444' not in bootstrap


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
    websocket_max_msg_bytes: int | None = None,
    peer_queue_limit: int = 4,
    write_timeout: float = 1.0,
    idle_timeout: float = 5.0,
    unauth_rate_limit: int = 100,
    unauth_rate_limit_window: float = 60.0,
    unauth_rate_limit_max_keys: int = 10_000,
    heartbeat_interval: float = 0.1,
    trusted_proxy_cidrs: tuple[str, ...] = ('127.0.0.1/32', '::1/128'),
) -> tuple[ProductionRelayService, _IssuedHost]:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        admin_host='127.0.0.1',
        admin_port=0,
        tls_cert_file=cert_path,
        tls_key_file=key_path,
        admission_db_path=tmp_path / 'relay.sqlite3',
        state_dir=tmp_path / 'state',
        max_frame_bytes=max_frame_bytes,
        websocket_max_msg_bytes=websocket_max_msg_bytes,
        peer_queue_limit=peer_queue_limit,
        write_timeout=write_timeout,
        idle_timeout=idle_timeout,
        heartbeat_interval=heartbeat_interval,
        unauth_rate_limit=unauth_rate_limit,
        unauth_rate_limit_window=unauth_rate_limit_window,
        unauth_rate_limit_max_keys=unauth_rate_limit_max_keys,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
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


def _client_hello(
    *,
    session_id: str,
    host_id: str,
    issued: _IssuedHost | None = None,
    client_pubkey_b64: str | None = None,
    phone_nonce_b64: str | None = None,
    rendezvous_capability: str | None = None,
    expires_at: int | None = None,
    audience: str = 'wss://relay.seemlab.top',
):
    client_pubkey = client_pubkey_b64 or _b64(b'client public key')
    phone_nonce = phone_nonce_b64 or _b64(f'phone nonce {session_id}'.encode('utf-8'))
    token = rendezvous_capability
    if token is None and issued is not None:
        token = issue_host_rendezvous_capability(
            issued.private_key,
            host_id=host_id,
            session_id=session_id,
            client_pubkey_b64=client_pubkey,
            phone_nonce_b64=phone_nonce,
            audience=audience,
            expires_at=expires_at or (int(time.time()) + 30),
        )
    payload: dict[str, object] = {
        'host_id': host_id,
        'device_id': 'device-public-routing-id',
        'client_pubkey_b64': client_pubkey,
        'phone_nonce_b64': phone_nonce,
        'supported_versions': [2],
    }
    if token is not None:
        payload['rendezvous_capability'] = token
    return _RelayFrame(
        session_id=session_id,
        seq=1,
        kind='client_hello',
        payload=payload,
    )


def _access_client_hello(
    *,
    session_id: str,
    host_id: str,
    phone_key: ed25519.Ed25519PrivateKey,
    access_grant: str,
):
    client_pubkey_b64 = _b64(f'fresh client key {session_id}'.encode('utf-8'))
    phone_nonce_b64 = _b64(f'fresh phone nonce {session_id}'.encode('utf-8'))
    now = int(time.time())
    proof = issue_phone_session_proof(
        phone_key,
        access_grant=access_grant,
        host_id=host_id,
        device_id='device-durable',
        session_id=session_id,
        client_pubkey_b64=client_pubkey_b64,
        phone_nonce_b64=phone_nonce_b64,
        audience='wss://relay.seemlab.top',
        issued_at=now,
        expires_at=now + 60,
    )
    return _RelayFrame(
        session_id=session_id,
        seq=1,
        kind='client_hello',
        payload={
            'host_id': host_id,
            'device_id': 'device-durable',
            'client_pubkey_b64': client_pubkey_b64,
            'phone_nonce_b64': phone_nonce_b64,
            'supported_versions': [2],
            'access_grant': access_grant,
            'phone_session_proof': proof,
        },
    )


def _ed25519_public_b64(key: ed25519.Ed25519PrivateKey) -> str:
    return _b64(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
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


async def _assert_no_host_frame(host: aiohttp.ClientWebSocketResponse) -> None:
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(host.receive(), timeout=0.05)


async def _wait_for_active_sessions(issued: _IssuedHost, expected: int) -> None:
    for _ in range(40):
        if issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == expected:
            return
        await asyncio.sleep(0.025)
    assert issued.store.host_status(issued.host_id)['quota_usage']['active_sessions'] == expected


def _public_http_url(service: ProductionRelayService, path: str) -> str:
    return service.url(path).replace('wss://', 'https://').replace('ws://', 'http://')


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


def _raw_private_key_b64(key) -> str:
    return _b64(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + '=' * (-len(value) % 4)).encode('ascii'))
