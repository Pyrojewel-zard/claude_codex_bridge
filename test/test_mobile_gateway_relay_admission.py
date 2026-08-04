from __future__ import annotations

import base64
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from cli.parser import CliParser
from cli.render import render_relay_operator
from cli.services.relay_operator import relay_operator_command
from mobile_gateway.relay_admission import (
    RelayAdmissionError,
    RelayAdmissionSecrets,
    RelayAdmissionStore,
    generate_host_private_key,
    host_public_key_b64,
    sign_host_session_proof,
)


def test_relay_invitation_issue_stores_only_keyed_verifier(tmp_path) -> None:
    now = [1_000]
    secrets = _admission_secrets()
    store = RelayAdmissionStore(tmp_path / 'relay.sqlite3', admission_secrets=secrets, now=lambda: now[0])

    issued = store.issue_invitation(label='operator-visible label', ttl_seconds=120)

    assert issued.invitation.startswith('ccb-relay-inv-v2.')
    assert issued.quota['max_bytes_per_day'] == 1024 * 1024 * 1024
    status = store.invitation_status(issued.invite_id)
    assert status['state'] == 'unused'
    assert 'invitation' not in status
    _assert_secret_not_persisted(tmp_path / 'relay.sqlite3', issued.invitation)
    _assert_blob_not_persisted(tmp_path / 'relay.sqlite3', secrets.verifier_key)
    _assert_secret_not_persisted(tmp_path / 'relay.sqlite3', _b64(secrets.capability_key))
    assert issued.invitation not in json.dumps(store.audit_records(), sort_keys=True)


def test_relay_invitation_concurrent_claim_yields_exactly_one_host_credential(tmp_path) -> None:
    secrets = _admission_secrets()
    store = RelayAdmissionStore(tmp_path / 'relay.sqlite3', admission_secrets=secrets, now=lambda: 2_000)
    issued = store.issue_invitation(ttl_seconds=600)
    host_private = generate_host_private_key()
    host_public = host_public_key_b64(host_private)

    def claim_once() -> dict[str, object]:
        try:
            credential = RelayAdmissionStore(
                tmp_path / 'relay.sqlite3',
                admission_secrets=secrets,
                now=lambda: 2_000,
            ).claim_invitation(
                issued.invitation,
                host_public_key_b64=host_public,
            )
            return {'ok': credential.to_json()}
        except RelayAdmissionError as exc:
            return {'error': str(exc)}

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _index: claim_once(), range(12)))

    successes = [result['ok'] for result in results if 'ok' in result]
    failures = [result['error'] for result in results if 'error' in result]
    assert len(successes) == 1
    assert len(failures) == 11
    assert all(issued.invitation not in failure for failure in failures)
    credential = successes[0]
    assert credential['type'] == 'ccb_relay_host_credential_v1'
    assert credential['host_public_key_b64'] == host_public
    assert credential['invitation_id'] == issued.invite_id
    assert store.invitation_status(issued.invite_id)['state'] == 'consumed'
    assert len(store.list_hosts()) == 1
    with pytest.raises(RelayAdmissionError, match='not claimable'):
        store.claim_invitation(issued.invitation, host_public_key_b64=host_public)
    _assert_secret_not_persisted(tmp_path / 'relay.sqlite3', issued.invitation)


def test_relay_invitation_restart_expiry_and_revoke_are_persistent(tmp_path) -> None:
    now = [3_000]
    db_path = tmp_path / 'relay.sqlite3'
    secrets = _admission_secrets()
    store = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    expired = store.issue_invitation(ttl_seconds=5)
    revoked = store.issue_invitation(ttl_seconds=120)

    now[0] += 6
    reopened = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    assert reopened.invitation_status(expired.invite_id)['state'] == 'expired'
    with pytest.raises(RelayAdmissionError, match='not claimable'):
        reopened.claim_invitation(
            expired.invitation,
            host_public_key_b64=host_public_key_b64(generate_host_private_key()),
        )

    revoked_status = reopened.revoke_invitation(revoked.invite_id, reason='operator rotation')
    assert revoked_status['state'] == 'revoked'
    with pytest.raises(RelayAdmissionError, match='not claimable'):
        reopened.claim_invitation(
            revoked.invitation,
            host_public_key_b64=host_public_key_b64(generate_host_private_key()),
        )
    states = {item['invite_id']: item['state'] for item in reopened.list_invitations()}
    assert states == {expired.invite_id: 'expired', revoked.invite_id: 'revoked'}


def test_relay_host_pop_session_capability_and_revocation(tmp_path) -> None:
    now = [4_000]
    store = RelayAdmissionStore(
        tmp_path / 'relay.sqlite3',
        admission_secrets=_admission_secrets(),
        now=lambda: now[0],
    )
    invitation = store.issue_invitation(ttl_seconds=120)
    host_private = generate_host_private_key()
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(host_private),
    )
    nonce_b64 = _b64(b'session nonce 1')
    proof_expires_at = now[0] + 30
    signature = sign_host_session_proof(
        host_private,
        host_id=credential.host_id,
        nonce_b64=nonce_b64,
        expires_at=proof_expires_at,
    )

    capability = store.issue_session_capability(
        host_id=credential.host_id,
        nonce_b64=nonce_b64,
        proof_expires_at=proof_expires_at,
        signature_b64=signature,
        ttl_seconds=60,
        scopes=('relay.connect', 'relay.forward'),
    )

    verified = store.verify_session_capability(str(capability['capability']))
    assert verified['host_id'] == credential.host_id
    assert verified['scopes'] == ['relay.connect', 'relay.forward']
    capability_text = str(capability['capability'])
    tampered = capability_text[:-1] + ('A' if capability_text[-1] != 'A' else 'B')
    with pytest.raises(RelayAdmissionError, match='signature rejected'):
        store.verify_session_capability(tampered)
    bad_signature = sign_host_session_proof(
        generate_host_private_key(),
        host_id=credential.host_id,
        nonce_b64=nonce_b64,
        expires_at=proof_expires_at,
    )
    with pytest.raises(RelayAdmissionError, match='proof rejected'):
        store.issue_session_capability(
            host_id=credential.host_id,
            nonce_b64=nonce_b64,
            proof_expires_at=proof_expires_at,
            signature_b64=bad_signature,
        )

    assert store.revoke_host(credential.host_id, reason='operator rotation')['state'] == 'revoked'
    with pytest.raises(RelayAdmissionError, match='not active'):
        store.verify_session_capability(str(capability['capability']))


def test_relay_operator_cli_json_and_human_outputs_redact_except_issue(tmp_path) -> None:
    db_path = tmp_path / 'relay.sqlite3'
    secrets_path = _write_secret_file(tmp_path / 'relay-secrets.json', _admission_secrets())
    context = SimpleNamespace(paths=SimpleNamespace(ccbd_mobile_dir=tmp_path / 'mobile'))
    issue_command = CliParser().parse(
        [
            'relay',
            'invite',
            'issue',
            '--db',
            str(db_path),
            '--secrets',
            str(secrets_path),
            '--ttl-seconds',
            '120',
            '--json',
        ]
    )
    assert issue_command.max_bytes_per_day == 1024 * 1024 * 1024

    issue_payload = relay_operator_command(context, issue_command)
    assert issue_payload['quota']['max_bytes_per_day'] == 1024 * 1024 * 1024
    issue_lines = render_relay_operator(issue_payload)

    raw_invitation = str(issue_payload['invitation'])
    assert sum(1 for line in issue_lines if line.startswith('invitation: ')) == 1
    assert raw_invitation in '\n'.join(issue_lines)

    invite_id = str(issue_payload['invite_id'])
    status_command = CliParser().parse(
        ['relay', 'invite', 'status', '--db', str(db_path), '--secrets', str(secrets_path), invite_id, '--json']
    )
    status_payload = relay_operator_command(context, status_command)
    list_command = CliParser().parse(['relay', 'invite', 'list', '--db', str(db_path), '--secrets', str(secrets_path)])
    list_payload = relay_operator_command(context, list_command)
    list_lines = render_relay_operator(list_payload)

    assert 'invitation' not in status_payload
    assert raw_invitation not in json.dumps(status_payload, sort_keys=True)
    assert raw_invitation not in '\n'.join(list_lines)
    assert raw_invitation not in json.dumps(list_payload, sort_keys=True)
    _assert_secret_not_persisted(db_path, raw_invitation)


def test_relay_host_activate_parser_and_render_surface_only_public_metadata() -> None:
    command = CliParser().parse(
        [
            'relay',
            'host',
            'activate',
            '--relay-origin',
            'wss://relay.example.test',
            '--invitation-file',
            '/tmp/relay-invitation',
            '--credentials',
            '/tmp/relay-credentials.json',
            '--json',
        ]
    )
    assert command.target == 'host'
    assert command.action == 'activate'
    assert command.relay_origin == 'wss://relay.example.test'
    assert command.invitation_file == '/tmp/relay-invitation'
    assert command.credential_path == '/tmp/relay-credentials.json'
    assert command.json_output is True
    assert command.relay_mode is None

    official = CliParser().parse(
        ['relay', 'host', 'activate', '--mode', 'official', '--invitation-file', '/tmp/key']
    )
    self_hosted = CliParser().parse(
        ['relay', 'host', 'activate', '--mode', 'self-hosted', '--relay-origin', 'wss://relay.example.test', '--invitation-file', '/tmp/key']
    )
    assert official.relay_mode == 'official'
    assert self_hosted.relay_mode == 'self-hosted'

    lines = render_relay_operator(
        {
            'relay_status': 'host_activated',
            'relay_origin': 'wss://relay.example.test',
            'host_id': 'host-1',
            'invitation_id': 'invite-1',
            'host_fingerprint': 'sha256:public',
            'credential_path': '/tmp/relay-credentials.json',
            'activated_at': '2026-07-22T00:00:00+00:00',
        }
    )
    rendered = '\n'.join(lines)
    assert 'relay_status: host_activated' in rendered
    assert 'host_id: host-1' in rendered
    assert 'db_path:' not in rendered


def test_relay_admission_secrets_are_external_and_restart_fail_closed(tmp_path) -> None:
    db_path = tmp_path / 'relay.sqlite3'
    secrets = _admission_secrets()
    store = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: 5_000)
    issued = store.issue_invitation(ttl_seconds=120)

    with pytest.raises(RelayAdmissionError, match='secrets are required'):
        RelayAdmissionStore(db_path)
    with pytest.raises(RelayAdmissionError, match='secrets changed'):
        RelayAdmissionStore(
            db_path,
            admission_secrets=RelayAdmissionSecrets(
                verifier_key=b'v' * 32,
                capability_key=b'c' * 32,
            ),
        )
    reopened = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: 5_000)
    assert reopened.invitation_status(issued.invite_id)['state'] == 'unused'


def test_relay_admission_db_wal_and_shm_are_owner_only(tmp_path) -> None:
    db_path = tmp_path / 'relay.sqlite3'
    store = RelayAdmissionStore(db_path, admission_secrets=_admission_secrets(), now=lambda: 6_000)
    store.issue_invitation(ttl_seconds=120)
    storage_paths = [db_path, db_path.with_name(db_path.name + '-wal'), db_path.with_name(db_path.name + '-shm')]

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS relay_mode_probe(value INTEGER)')
        conn.execute('INSERT INTO relay_mode_probe(value) VALUES (1)')
        assert all(path.exists() for path in storage_paths)
        for path in storage_paths:
            path.chmod(0o666)

        store.list_invitations()

        for path in storage_paths:
            assert stat_mode(path) == 0o600
    finally:
        conn.close()


def test_relay_host_session_quota_is_atomic_and_restart_safe(tmp_path) -> None:
    now = [7_000]
    db_path = tmp_path / 'relay.sqlite3'
    secrets = _admission_secrets()
    store = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    invitation = store.issue_invitation(ttl_seconds=120, max_sessions=3)
    host_private = generate_host_private_key()
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(host_private),
    )

    def reserve(index: int) -> dict[str, object]:
        try:
            opened = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
            return opened.reserve_host_session(host_id=credential.host_id, session_id=f'session-{index}')
        except RelayAdmissionError as exc:
            return {'error': str(exc)}

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(reserve, range(10)))

    successes = [item for item in results if 'error' not in item]
    failures = [item for item in results if 'error' in item]
    assert len(successes) == 3
    assert len(failures) == 7
    assert all('quota exceeded' in str(item['error']) for item in failures)

    reopened = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    status = reopened.host_status(credential.host_id)
    assert status['quota_usage']['active_sessions'] == 3
    retry = reopened.reserve_host_session(host_id=credential.host_id, session_id=str(successes[0]['session_id']))
    assert retry['idempotent'] is True
    assert retry['quota_usage']['active_sessions'] == 3

    second_invitation = reopened.issue_invitation(ttl_seconds=120, max_sessions=3)
    second_credential = reopened.claim_invitation(
        second_invitation.invitation,
        host_public_key_b64=host_public_key_b64(generate_host_private_key()),
    )
    with pytest.raises(RelayAdmissionError, match='identity conflict'):
        reopened.reserve_host_session(host_id=second_credential.host_id, session_id=str(successes[0]['session_id']))
    assert reopened.host_status(second_credential.host_id)['quota_usage']['active_sessions'] == 0

    released_session_id = str(successes[0]['session_id'])
    reopened.release_host_session(host_id=credential.host_id, session_id=released_session_id)
    with pytest.raises(RelayAdmissionError, match='identity conflict'):
        reopened.reserve_host_session(host_id=credential.host_id, session_id=released_session_id)
    assert reopened.reserve_host_session(host_id=credential.host_id, session_id='session-after-release')['quota_usage'][
        'active_sessions'
    ] == 3

    reopened.revoke_host(credential.host_id, reason='operator rotation')
    with pytest.raises(RelayAdmissionError, match='not active'):
        reopened.reserve_host_session(host_id=credential.host_id, session_id='session-revoked')


def test_relay_host_byte_quota_is_bounded_and_restart_safe(tmp_path) -> None:
    now = [8_000]
    db_path = tmp_path / 'relay.sqlite3'
    secrets = _admission_secrets()
    store = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    invitation = store.issue_invitation(ttl_seconds=120, max_bytes_per_day=10)
    host_private = generate_host_private_key()
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(host_private),
    )

    assert store.record_host_bytes(host_id=credential.host_id, byte_count=6)['quota_usage']['bytes_used'] == 6
    reopened = RelayAdmissionStore(db_path, admission_secrets=secrets, now=lambda: now[0])
    with pytest.raises(RelayAdmissionError, match='byte quota exceeded'):
        reopened.record_host_bytes(host_id=credential.host_id, byte_count=5)
    assert reopened.record_host_bytes(host_id=credential.host_id, byte_count=4)['quota_usage']['bytes_used'] == 10

    now[0] += 24 * 60 * 60
    assert reopened.record_host_bytes(host_id=credential.host_id, byte_count=1)['quota_usage']['bytes_used'] == 1


def test_relay_reconciles_only_stale_active_session_reservations(tmp_path) -> None:
    now = [9_000]
    store = RelayAdmissionStore(
        tmp_path / 'relay.sqlite3',
        admission_secrets=_admission_secrets(),
        now=lambda: now[0],
    )
    invitation = store.issue_invitation(ttl_seconds=120, max_sessions=3)
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(generate_host_private_key()),
    )
    store.reserve_host_session(host_id=credential.host_id, session_id='stale-1')
    store.reserve_host_session(host_id=credential.host_id, session_id='stale-2')

    assert store.reconcile_active_sessions() == 2
    assert store.host_status(credential.host_id)['quota_usage']['active_sessions'] == 0
    assert store.reconcile_active_sessions() == 0
    reconciled = [
        item
        for item in store.audit_records()
        if item['event'] == 'host_sessions_reconciled'
    ]
    assert reconciled == [
        {
            'event': 'host_sessions_reconciled',
            'subject_type': 'host',
            'subject_id': credential.host_id,
            'at': 9_000,
            'detail': {'count': 2, 'reason': 'relay_service_restart'},
        }
    ]


def test_relay_normal_byte_accounting_does_not_append_per_frame_audit(tmp_path) -> None:
    store = RelayAdmissionStore(
        tmp_path / 'relay.sqlite3',
        admission_secrets=_admission_secrets(),
        now=lambda: 10_000,
    )
    invitation = store.issue_invitation(ttl_seconds=120, max_bytes_per_day=100)
    credential = store.claim_invitation(
        invitation.invitation,
        host_public_key_b64=host_public_key_b64(generate_host_private_key()),
    )
    baseline = len(store.audit_records())

    for _ in range(20):
        store.record_host_bytes(host_id=credential.host_id, byte_count=1)

    assert store.host_status(credential.host_id)['quota_usage']['bytes_used'] == 20
    assert len(store.audit_records()) == baseline


def _assert_secret_not_persisted(db_path, secret: str) -> None:
    secret_bytes = secret.encode('utf-8')
    _assert_blob_not_persisted(db_path, secret_bytes)


def _assert_blob_not_persisted(db_path, secret_bytes: bytes) -> None:
    candidates = [db_path, db_path.with_name(db_path.name + '-wal'), db_path.with_name(db_path.name + '-shm')]
    for path in candidates:
        if path.exists():
            assert secret_bytes not in path.read_bytes()


def _admission_secrets() -> RelayAdmissionSecrets:
    return RelayAdmissionSecrets(verifier_key=bytes(range(1, 33)), capability_key=bytes(range(101, 133)))


def _write_secret_file(path, secrets: RelayAdmissionSecrets):
    path.write_text(
        json.dumps(
            {
                'verifier_key_b64': _b64(secrets.verifier_key),
                'capability_key_b64': _b64(secrets.capability_key),
            },
            sort_keys=True,
        ),
        encoding='utf-8',
    )
    path.chmod(0o600)
    return path


def stat_mode(path) -> int:
    return os.stat(path).st_mode & 0o777


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')
