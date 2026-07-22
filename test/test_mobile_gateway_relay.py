from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from cli.services import mobile as mobile_service
from cli.services.mobile import prepare_mobile_gateway
from mobile_gateway.relay import (
    LocalRelayServerHarness,
    MobileGatewayRelayOutboundClient,
    MobileRelayError,
    RelayFrame,
    RelayHandshakeTranscript,
    RelayHostRegistration,
)
from mobile_gateway.relay_host_credentials import RelayHostCredentials


def test_mobile_serve_relay_requires_activated_production_outbound_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    credentials = RelayHostCredentials(
        relay_origin='wss://relay.seemlab.top',
        host_id='host-activated',
        invitation_id='invite-used-once',
        host_signing_private_key_b64=_private_key_b64(
            ed25519.Ed25519PrivateKey.generate()
        ),
        host_crypto_private_key_b64=_private_key_b64(
            x25519.X25519PrivateKey.generate()
        ),
        activated_at='2026-07-22T00:00:00+00:00',
    )
    monkeypatch.setattr(
        mobile_service,
        '_relay_host_credentials',
        lambda: credentials,
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_id='proj-relay', project_root=tmp_path / 'repo'),
        paths=SimpleNamespace(
            ccbd_socket_path=tmp_path / 'ccbd.sock',
            ccbd_mobile_dir=tmp_path / 'mobile',
        ),
    )
    command = SimpleNamespace(
        listen='127.0.0.1:0',
        public_url='https://relay.seemlab.top',
        route_provider='relay',
    )
    handle = prepare_mobile_gateway(context, command)
    try:
        summary = handle.summary
    finally:
        handle.close()

    assert summary['route_provider'] == 'relay'
    assert summary['gateway_url'] == 'https://relay.seemlab.top'
    assert summary['pairing']['route_provider'] == 'relay'
    relay_outbound = summary['relay_outbound']
    assert relay_outbound['status'] == 'configured'
    assert relay_outbound['mode'] == 'production_outbound_wss'
    assert relay_outbound['host_id'] == 'host-activated'
    assert relay_outbound['relay_origin'] == 'wss://relay.seemlab.top'
    outbound_text = json.dumps(relay_outbound)
    assert '127.0.0.1' not in outbound_text
    assert 'gateway_url' not in outbound_text
    assert 'device_token' not in outbound_text


def test_host_outbound_client_registers_without_public_listener_metadata() -> None:
    relay = LocalRelayServerHarness()
    client = MobileGatewayRelayOutboundClient(
        relay=relay,
        host_id='host-relay',
        server_fingerprint='host-fp-demo',
        host_pubkey_b64=_b64('host public key'),
        diagnostics={'relay_region': 'local-test', 'relay_host_id': 'host-relay'},
    )

    result = client.connect()

    assert result == {
        'status': 'registered',
        'host_id': 'host-relay',
        'server_fingerprint': 'host-fp-demo',
        'capabilities': ['http_json', 'project_view', 'relay_tunnel'],
    }
    diagnostics = client.diagnostics()
    assert diagnostics['state'] == 'registered'
    assert diagnostics['ready'] is False
    assert '127.0.0.1' not in json.dumps(result)
    assert 'gateway_url' not in json.dumps(result)
    assert 'device_token' not in json.dumps(result)


def test_local_relay_negotiates_handshake_from_app_frame_shape() -> None:
    relay = _registered_relay()
    client_hello = _client_hello()

    host_hello = RelayFrame.from_json(relay.host_hello_for(client_hello.to_json()))
    transcript = RelayHandshakeTranscript.negotiate(
        client_hello=client_hello,
        host_hello=host_hello,
    )

    assert transcript.session_id == 'relay-session-demo'
    assert transcript.host_id == 'host-relay'
    assert transcript.device_id == 'dev-relay'
    assert transcript.accepted_version == 2
    assert transcript.server_fingerprint == 'host-fp-demo'
    assert relay.diagnostics_for_host('host-relay') == {
        'host_id': 'host-relay',
        'state': 'ready',
        'ready': True,
        'session_count': 1,
        'forwarded_count': 0,
    }


def test_relay_rejects_v1_downgrade_even_when_client_lists_legacy_version() -> None:
    relay = _registered_relay()
    client_hello = RelayFrame(
        session_id='relay-session-demo',
        seq=1,
        kind='client_hello',
        payload={
            'host_id': 'host-relay',
            'device_id': 'dev-relay',
            'client_pubkey_b64': _b64('client public key'),
            'supported_versions': [1, 2],
        },
    )

    host_hello = RelayFrame.from_json(relay.host_hello_for(client_hello.to_json()))

    assert host_hello.payload['accepted_version'] == 2
    with pytest.raises(MobileRelayError, match='downgrade'):
        RelayHandshakeTranscript.negotiate(
            client_hello=client_hello,
            host_hello=RelayFrame(
                session_id='relay-session-demo',
                seq=2,
                kind='host_hello',
                payload={
                    'host_id': 'host-relay',
                    'server_fingerprint': 'host-fp-demo',
                    'host_pubkey_b64': _b64('host public key'),
                    'accepted_version': 1,
                },
            ),
        )


def test_local_relay_forwards_only_opaque_gateway_envelopes() -> None:
    relay = _registered_relay()
    relay.host_hello_for(_client_hello().to_json())
    frame = RelayFrame(
        session_id='relay-session-demo',
        seq=3,
        kind='gateway_envelope',
        payload={
            'envelope': {
                'schema_version': 2,
                'session_id': 'relay-session-demo',
                'seq': 3,
                'op': 'send_terminal_frame',
                'ciphertext_b64': _b64('opaque encrypted gateway request'),
                'nonce_b64': _b64('relay-session-demo:3'),
                'key_id': 'session-key-1',
            }
        },
    )

    ack = relay.forward_from_phone(frame.to_json())

    assert ack == {
        'schema_version': 2,
        'session_id': 'relay-session-demo',
        'seq': 4,
        'kind': 'ack',
        'payload': {'ack_seq': 3},
    }
    assert relay.forwarded[0]['direction'] == 'phone_to_host'
    forwarded_text = json.dumps(relay.forwarded)
    assert 'send_terminal_frame' in forwarded_text
    assert 'secret paste text' not in forwarded_text
    assert 'project_id' not in forwarded_text
    assert 'terminal_id' not in forwarded_text
    assert 'terminal_token' not in forwarded_text
    assert relay.diagnostics_for_host('host-relay')['forwarded_count'] == 1


def test_relay_rejects_cleartext_route_and_terminal_fields() -> None:
    registration = RelayHostRegistration(
        host_id='host-relay',
        server_fingerprint='host-fp-demo',
        host_pubkey_b64=_b64('host public key'),
    ).to_json()
    with pytest.raises(MobileRelayError, match='device_token'):
        RelayHostRegistration.from_json({**registration, 'device_token': 'secret'})

    client_hello = _client_hello().to_json()
    payload = dict(client_hello['payload'])
    payload['gateway_url'] = 'https://relay.seemlab.top'
    with pytest.raises(MobileRelayError, match='gateway_url'):
        RelayFrame.from_json({**client_hello, 'payload': payload})

    envelope_frame = RelayFrame(
        session_id='relay-session-demo',
        seq=3,
        kind='gateway_envelope',
        payload={
            'envelope': {
                'schema_version': 2,
                'session_id': 'relay-session-demo',
                'seq': 3,
                'op': 'open_terminal',
                'ciphertext_b64': _b64('opaque'),
                'nonce_b64': _b64('nonce'),
            }
        },
    ).to_json()
    envelope = dict(envelope_frame['payload']['envelope'])
    envelope['terminal_id'] = 'term-secret'
    with pytest.raises(MobileRelayError, match='terminal_id'):
        RelayFrame.from_json({**envelope_frame, 'payload': {'envelope': envelope}})


def test_relay_reports_disconnected_host_without_stopping_runtime() -> None:
    relay = _registered_relay()
    relay.host_hello_for(_client_hello().to_json())
    relay.disconnect_host('host-relay')

    diagnostics = relay.diagnostics_for_host('host-relay')

    assert diagnostics == {
        'host_id': 'host-relay',
        'state': 'host_disconnected',
        'ready': False,
    }
    with pytest.raises(MobileRelayError, match='host disconnected'):
        relay.forward_from_phone(
            RelayFrame(
                session_id='relay-session-demo',
                seq=3,
                kind='gateway_envelope',
                payload={
                    'envelope': {
                        'schema_version': 2,
                        'session_id': 'relay-session-demo',
                        'seq': 3,
                        'op': 'health',
                        'ciphertext_b64': _b64('opaque'),
                        'nonce_b64': _b64('nonce'),
                    }
                },
            ).to_json()
        )
    assert relay.diagnostics_for_host('unknown') == {
        'host_id': 'unknown',
        'state': 'unknown_host',
        'ready': False,
    }


def test_relay_health_diagnostics_explain_unreachable_stale_and_fingerprint_states() -> None:
    relay = _registered_relay()
    client = MobileGatewayRelayOutboundClient(
        relay=relay,
        host_id='host-relay',
        server_fingerprint='host-fp-demo',
        host_pubkey_b64=_b64('host public key'),
    )

    relay.set_relay_unreachable()
    assert client.diagnostics() == {
        'host_id': 'host-relay',
        'state': 'relay_unreachable',
        'ready': False,
        'reason': 'relay control plane is unreachable from this harness',
    }

    relay.set_relay_unreachable(False)
    relay.mark_device_stale(host_id='host-relay', device_id='dev-relay')
    assert client.diagnostics(device_id='dev-relay') == {
        'host_id': 'host-relay',
        'device_id': 'dev-relay',
        'state': 'stale_device',
        'ready': False,
    }
    assert client.diagnostics(device_id='fresh-device')['state'] == 'registered'

    mismatch = client.diagnostics(expected_host_fingerprint='expected-fp')
    assert mismatch == {
        'host_id': 'host-relay',
        'state': 'host_fingerprint_mismatch',
        'ready': False,
        'expected_host_fingerprint': 'expected-fp',
        'observed_host_fingerprint': 'host-fp-demo',
    }
    assert client.diagnostics(expected_host_fingerprint='host-fp-demo')['state'] == 'registered'


def test_relay_validates_base64_and_handshake_mismatches() -> None:
    with pytest.raises(MobileRelayError, match='base64url'):
        RelayHostRegistration(
            host_id='host-relay',
            server_fingerprint='host-fp-demo',
            host_pubkey_b64='not base64!',
        ).to_json()

    relay = _registered_relay()
    mismatched = RelayFrame(
        session_id='relay-session-demo',
        seq=1,
        kind='client_hello',
        payload={
            'host_id': 'other-host',
            'device_id': 'dev-relay',
            'client_pubkey_b64': _b64('client public key'),
            'supported_versions': [2],
        },
    )
    with pytest.raises(MobileRelayError, match='not registered'):
        relay.host_hello_for(mismatched.to_json())


def _registered_relay() -> LocalRelayServerHarness:
    relay = LocalRelayServerHarness()
    relay.register_host(
        RelayHostRegistration(
            host_id='host-relay',
            server_fingerprint='host-fp-demo',
            host_pubkey_b64=_b64('host public key'),
            capabilities=('http_json', 'project_view', 'relay_tunnel'),
            diagnostics={'relay_region': 'local-test'},
        ).to_json()
    )
    return relay


def _client_hello() -> RelayFrame:
    return RelayFrame(
        session_id='relay-session-demo',
        seq=1,
        kind='client_hello',
        payload={
            'host_id': 'host-relay',
            'device_id': 'dev-relay',
            'client_pubkey_b64': _b64('client public key'),
            'supported_versions': [2],
        },
    )


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode('ascii')


def _private_key_b64(key) -> str:
    raw = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
