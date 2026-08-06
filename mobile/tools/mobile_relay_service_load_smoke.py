from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import ssl
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
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
    sign_host_session_proof,
)
from mobile_gateway.relay_crypto import (
    RelayDirection,
    derive_relay_v2_key_schedule,
    key_pair_from_private_bytes,
    public_key_b64,
)
from mobile_gateway.relay_service import ProductionRelayConfig, ProductionRelayService


@dataclass
class _Host:
    host_id: str
    private_key: Any
    ws: aiohttp.ClientWebSocketResponse


async def run_load_smoke(args: argparse.Namespace) -> dict[str, object]:
    workdir = Path(args.workdir).expanduser() if args.workdir else Path(tempfile.mkdtemp(prefix='ccb-relay-load-'))
    workdir.mkdir(parents=True, exist_ok=True)
    workdir.chmod(0o700)
    cert_path, key_path = _write_self_signed_cert(workdir)
    store = RelayAdmissionStore(
        workdir / 'relay-admission.sqlite3',
        admission_secrets=RelayAdmissionSecrets.generate_for_testing(),
    )
    service = ProductionRelayService(
        ProductionRelayConfig(
            listen_host='127.0.0.1',
            listen_port=0,
            tls_cert_file=cert_path,
            tls_key_file=key_path,
            admission_db_path=workdir / 'relay-admission.sqlite3',
            state_dir=workdir / 'state',
            write_timeout=5,
            idle_timeout=30,
            unauth_rate_limit=max(args.hosts + args.phones + 10, 200),
        ),
        admission_store=store,
    )
    await service.start()
    started = time.perf_counter()
    canary = f'PACKAGE-C-LOAD-CANARY-{int(time.time())}'
    hosts: list[_Host] = []
    phones: list[aiohttp.ClientWebSocketResponse] = []
    try:
        async with aiohttp.ClientSession(raise_for_status=True) as client:
            for index in range(args.hosts):
                host_private = generate_host_private_key()
                invite = store.issue_invitation(
                    ttl_seconds=600,
                    max_sessions=max(1, args.phones),
                    max_bytes_per_day=256 * 1024 * 1024,
                )
                credential = store.claim_invitation(
                    invite.invitation,
                    host_public_key_b64=host_public_key_b64(host_private),
                )
                ws = await client.ws_connect(service.url('/v2/host'), ssl=_client_ssl())
                await ws.send_json(_host_register(credential.host_id, host_private, f'host-{index}'))
                ack = await ws.receive_json()
                if ack.get('kind') != 'ack':
                    raise RuntimeError(f'host registration failed: {ack}')
                hosts.append(_Host(host_id=credential.host_id, private_key=host_private, ws=ws))

            for index in range(args.phones):
                host = hosts[index % len(hosts)]
                session_id = f'load-session-{index}'
                phone = await client.ws_connect(service.url('/v2/phone'), ssl=_client_ssl())
                await phone.send_json(_client_hello(session_id, host, index, service.config.public_origin))
                observed_client_hello = await host.ws.receive_json()
                if observed_client_hello.get('kind') != 'client_hello':
                    raise RuntimeError(f'host did not receive client_hello: {observed_client_hello}')
                await host.ws.send_json(_host_hello(session_id, host.host_id))
                observed_host_hello = await phone.receive_json()
                if observed_host_hello.get('kind') != 'host_hello':
                    raise RuntimeError(f'phone did not receive host_hello: {observed_host_hello}')
                phones.append(phone)

            active = min(args.active, len(phones))
            for index in range(active):
                host = hosts[index % len(hosts)]
                session_id = f'load-session-{index}'
                plaintext = canary.encode('utf-8') if index == 0 else f'payload-{index}'.encode('utf-8')
                phone_frame = _gateway_frame(
                    session_id,
                    3,
                    RelayDirection.PHONE_TO_HOST,
                    1,
                    plaintext,
                )
                await phones[index].send_json(phone_frame)
                if await host.ws.receive_json() != phone_frame:
                    raise RuntimeError('host did not receive opaque phone frame')
                host_frame = _gateway_frame(
                    session_id,
                    4,
                    RelayDirection.HOST_TO_PHONE,
                    1,
                    f'reply-{index}'.encode('utf-8'),
                )
                await host.ws.send_json(host_frame)
                if await phones[index].receive_json() != host_frame:
                    raise RuntimeError('phone did not receive opaque host frame')

            for index in range(active, len(phones)):
                await phones[index].send_json(
                    {
                        'schema_version': 2,
                        'session_id': f'load-session-{index}',
                        'seq': 5,
                        'kind': 'heartbeat',
                        'payload': {},
                    }
                )
                if (await phones[index].receive_json()).get('kind') != 'ack':
                    raise RuntimeError('phone heartbeat was not acknowledged')

        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        scan_hits = _scan_for_canary(workdir, canary)
        result = {
            'relay_load_smoke': 'pass' if not scan_hits else 'fail',
            'hosts': args.hosts,
            'phones': args.phones,
            'active_streams': active,
            'elapsed_ms': elapsed_ms,
            'service_url': service.url('/v2/phone'),
            'metrics': service.metrics_snapshot(),
            'canary_scan_hits': scan_hits,
            'workdir': str(workdir),
        }
        if args.output:
            output = Path(args.output).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return result
    finally:
        for ws in [*(host.ws for host in hosts), *phones]:
            await ws.close()
        await service.stop()


def _host_register(host_id: str, private_key: Any, label: str) -> dict[str, object]:
    nonce_b64 = _b64(f'load-{label}'.encode('utf-8'))
    expires_at = int(time.time()) + 60
    return {
        'schema_version': 2,
        'session_id': f'host-control-{label}',
        'seq': 1,
        'kind': 'host_register',
        'payload': {
            'host_id': host_id,
            'nonce_b64': nonce_b64,
            'proof_expires_at': expires_at,
            'signature_b64': sign_host_session_proof(
                private_key,
                host_id=host_id,
                nonce_b64=nonce_b64,
                expires_at=expires_at,
            ),
            'supported_versions': [2],
            'capabilities': ['relay.forward'],
        },
    }


def _client_hello(session_id: str, host: _Host, index: int, audience: str) -> dict[str, object]:
    client_pubkey_b64 = _b64(f'client-{index}'.encode('utf-8'))
    phone_nonce_b64 = _b64(f'phone-nonce-{index}'.encode('utf-8'))
    rendezvous_capability = issue_host_rendezvous_capability(
        host.private_key,
        host_id=host.host_id,
        session_id=session_id,
        client_pubkey_b64=client_pubkey_b64,
        phone_nonce_b64=phone_nonce_b64,
        audience=audience,
        expires_at=int(time.time()) + 60,
    )
    return {
        'schema_version': 2,
        'session_id': session_id,
        'seq': 1,
        'kind': 'client_hello',
        'payload': {
            'host_id': host.host_id,
            'device_id': f'load-phone-{index}',
            'client_pubkey_b64': client_pubkey_b64,
            'phone_nonce_b64': phone_nonce_b64,
            'rendezvous_capability': rendezvous_capability,
            'supported_versions': [2],
        },
    }


def _host_hello(session_id: str, host_id: str) -> dict[str, object]:
    return {
        'schema_version': 2,
        'session_id': session_id,
        'seq': 2,
        'kind': 'host_hello',
        'payload': {
            'host_id': host_id,
            'server_fingerprint': 'sha256:load-host',
            'host_pubkey_b64': _b64(b'load-host-public'),
            'accepted_version': 2,
        },
    }


def _gateway_frame(
    session_id: str,
    outer_seq: int,
    direction: RelayDirection,
    envelope_seq: int,
    plaintext: bytes,
) -> dict[str, object]:
    envelope = _relay_envelope(
        session_id=session_id,
        direction=direction,
        seq=envelope_seq,
        plaintext=plaintext,
    )
    return {
        'schema_version': 2,
        'session_id': session_id,
        'seq': outer_seq,
        'kind': 'gateway_envelope',
        'payload': {'envelope': envelope},
    }


def _relay_envelope(
    *,
    session_id: str,
    direction: RelayDirection,
    seq: int,
    plaintext: bytes,
) -> dict[str, object]:
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
        expected_host_fingerprint='sha256:' + _b64(hashlib.sha256(_b64decode(host_public)).digest()),
    )
    crypto = schedule.session(role='phone' if direction == RelayDirection.PHONE_TO_HOST else 'host')
    while crypto._next_send_seq < seq:
        crypto.seal(op='padding', plaintext=b'pad')
    return crypto.seal(op='gateway', plaintext=plaintext).to_json()


def _write_self_signed_cert(workdir: Path) -> tuple[Path, Path]:
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
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = workdir / 'relay-load-cert.pem'
    key_path = workdir / 'relay-load-key.pem'
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


def _scan_for_canary(root: Path, canary: str) -> list[str]:
    needle = canary.encode('utf-8')
    hits: list[str] = []
    for path in root.rglob('*'):
        if path.is_file() and path.suffix not in {'.pem'} and needle in path.read_bytes():
            hits.append(str(path))
    return hits


def _client_ssl() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + '=' * (-len(value) % 4)).encode('ascii'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run a local TLS/WSS CCB relay synthetic load smoke.')
    parser.add_argument('--hosts', type=int, default=50)
    parser.add_argument('--phones', type=int, default=50)
    parser.add_argument('--active', type=int, default=10)
    parser.add_argument('--workdir', default=None)
    parser.add_argument('--output', default=None)
    args = parser.parse_args(argv)
    result = asyncio.run(run_load_smoke(args))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['relay_load_smoke'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
