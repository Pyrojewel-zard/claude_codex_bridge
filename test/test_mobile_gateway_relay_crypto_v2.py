from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from mobile_gateway.relay_crypto import (
    RELAY_MAX_SEQUENCE,
    RelayCryptoError,
    RelayV2Envelope,
    assert_no_prohibited_plaintext,
    derive_relay_v2_key_schedule,
    deterministic_test_vector,
    key_pair_from_private_bytes,
    negotiate_relay_v2,
)


VECTOR_PATH = Path('mobile/app/test/fixtures/relay_crypto_v2_vectors.json')


def test_relay_v2_deterministic_vector_matches_shared_fixture() -> None:
    vector = _fixture()

    assert deterministic_test_vector() == vector


def test_relay_v2_python_derives_and_decrypts_shared_vector() -> None:
    vector = _fixture()
    client_private = key_pair_from_private_bytes(_b64decode(vector['client_seed_b64']))
    host_private = key_pair_from_private_bytes(_b64decode(vector['host_seed_b64']))

    phone_schedule = derive_relay_v2_key_schedule(
        local_private_key=client_private,
        peer_public_key_b64=vector['host_public_key_b64'],
        role='phone',
        session_id=vector['session_id'],
        client_public_key_b64=vector['client_public_key_b64'],
        host_public_key_b64=vector['host_public_key_b64'],
        expected_host_fingerprint=vector['host_fingerprint'],
    )
    host_schedule = derive_relay_v2_key_schedule(
        local_private_key=host_private,
        peer_public_key_b64=vector['client_public_key_b64'],
        role='host',
        session_id=vector['session_id'],
        client_public_key_b64=vector['client_public_key_b64'],
        host_public_key_b64=vector['host_public_key_b64'],
        expected_host_fingerprint=vector['host_fingerprint'],
    )

    assert phone_schedule.to_public_json() == host_schedule.to_public_json()
    assert phone_schedule.transcript_hash_b64 == vector['transcript_hash_b64']
    assert phone_schedule.key_confirmation.phone_b64 == vector['key_confirmation']['phone_b64']
    assert phone_schedule.key_confirmation.host_b64 == vector['key_confirmation']['host_b64']
    plaintext = host_schedule.session(role='host').open(RelayV2Envelope.from_json(vector['frame']))
    assert plaintext == _b64decode(vector['plaintext_b64'])


def test_relay_v2_rejects_replay_reorder_corruption_and_aad_mismatch() -> None:
    vector = _fixture()
    phone, host = _sessions(vector)
    first = phone.seal(op='first', plaintext=b'one')
    second = phone.seal(op='second', plaintext=b'two')

    with pytest.raises(RelayCryptoError, match='sequence'):
        host.open(second)

    assert host.open(first) == b'one'
    with pytest.raises(RelayCryptoError, match='sequence'):
        host.open(first)
    assert host.open(second) == b'two'

    phone, host = _sessions(vector)
    corrupted = phone.seal(op='corrupt', plaintext=b'payload')
    tampered = dict(corrupted.to_json())
    tampered['ciphertext_b64'] = tampered['ciphertext_b64'][:-1] + ('A' if tampered['ciphertext_b64'][-1] != 'A' else 'B')
    with pytest.raises(RelayCryptoError, match='authentication failed'):
        host.open(tampered)

    phone, host = _sessions(vector)
    mismatched = phone.seal(op='aad', plaintext=b'payload').to_json()
    mismatched['op'] = 'other-op'
    with pytest.raises(RelayCryptoError, match='authentication failed'):
        host.open(mismatched)


def test_relay_v2_rejects_downgrade_fingerprint_and_plaintext_fields() -> None:
    vector = _fixture()
    with pytest.raises(RelayCryptoError, match='failed closed'):
        negotiate_relay_v2([1])
    assert negotiate_relay_v2([1, 2]) == 2

    with pytest.raises(RelayCryptoError, match='fingerprint'):
        derive_relay_v2_key_schedule(
            local_private_key=key_pair_from_private_bytes(_b64decode(vector['client_seed_b64'])),
            peer_public_key_b64=vector['host_public_key_b64'],
            role='phone',
            session_id=vector['session_id'],
            client_public_key_b64=vector['client_public_key_b64'],
            host_public_key_b64=vector['host_public_key_b64'],
            expected_host_fingerprint='sha256:wrong',
        )

    with pytest.raises(RelayCryptoError, match='non-envelope fields'):
        RelayV2Envelope.from_json({**vector['frame'], 'project_id': 'proj-secret'})
    with pytest.raises(RelayCryptoError, match='prohibited plaintext'):
        assert_no_prohibited_plaintext({'payload': {'prompt': 'secret'}})
    frame_text = json.dumps(vector['frame'], sort_keys=True)
    for prohibited in ('project_id', 'agent', 'prompt', 'reply', 'path', 'terminal_token', 'file_name'):
        assert prohibited not in frame_text


def test_relay_v2_best_effort_zeroizes_session_keys() -> None:
    vector = _fixture()
    phone, _host = _sessions(vector)

    phone.close()

    assert phone.closed is True
    assert phone.key_material_erased() is True
    with pytest.raises(RelayCryptoError, match='closed'):
        phone.seal(op='closed', plaintext=b'payload')


def test_relay_v2_sequence_limit_is_explicit_and_closes_session() -> None:
    vector = _fixture()
    phone, host = _sessions(vector)
    phone._next_send_seq = RELAY_MAX_SEQUENCE

    final_frame = phone.seal(op='last', plaintext=b'last')

    assert final_frame.seq == RELAY_MAX_SEQUENCE
    with pytest.raises(RelayCryptoError, match='sequence exhausted'):
        phone.seal(op='overflow', plaintext=b'overflow')
    assert phone.closed is True

    host._next_receive_seq = RELAY_MAX_SEQUENCE + 1
    with pytest.raises(RelayCryptoError, match='sequence exhausted'):
        host.open(final_frame)
    assert host.closed is True

    with pytest.raises(RelayCryptoError, match='uint64'):
        RelayV2Envelope.from_json({**final_frame.to_json(), 'seq': RELAY_MAX_SEQUENCE + 1})


def _sessions(vector: dict[str, object]):
    client_private = key_pair_from_private_bytes(_b64decode(vector['client_seed_b64']))
    host_private = key_pair_from_private_bytes(_b64decode(vector['host_seed_b64']))
    phone_schedule = derive_relay_v2_key_schedule(
        local_private_key=client_private,
        peer_public_key_b64=str(vector['host_public_key_b64']),
        role='phone',
        session_id=str(vector['session_id']),
        client_public_key_b64=str(vector['client_public_key_b64']),
        host_public_key_b64=str(vector['host_public_key_b64']),
        expected_host_fingerprint=str(vector['host_fingerprint']),
    )
    host_schedule = derive_relay_v2_key_schedule(
        local_private_key=host_private,
        peer_public_key_b64=str(vector['client_public_key_b64']),
        role='host',
        session_id=str(vector['session_id']),
        client_public_key_b64=str(vector['client_public_key_b64']),
        host_public_key_b64=str(vector['host_public_key_b64']),
        expected_host_fingerprint=str(vector['host_fingerprint']),
    )
    return phone_schedule.session(role='phone'), host_schedule.session(role='host')


def _fixture() -> dict[str, object]:
    return json.loads(VECTOR_PATH.read_text(encoding='utf-8'))


def _b64decode(value: object) -> bytes:
    text = str(value)
    return base64.urlsafe_b64decode((text + '=' * (-len(text) % 4)).encode('ascii'))
