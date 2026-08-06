import 'dart:convert';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('negotiates relay handshake with public key material only', () {
    final clientHello = RelayFrame.clientHello(
      sessionId: 'relay-session-demo',
      sequence: 1,
      hostId: 'host-relay',
      deviceId: 'dev-relay',
      clientPublicKeyB64: _b64('client ephemeral public key'),
      supportedVersions: const {relayProtocolVersion},
    );
    final hostHello = RelayFrame.hostHello(
      sessionId: 'relay-session-demo',
      sequence: 2,
      hostId: 'host-relay',
      serverFingerprint: 'host-fp-demo',
      hostPublicKeyB64: _b64('host ephemeral public key'),
    );

    final transcript = RelayHandshakeTranscript.negotiate(
      clientHello: RelayFrame.fromJson(clientHello.toJson()),
      hostHello: RelayFrame.fromJson(hostHello.toJson()),
    );

    expect(transcript.ready, isTrue);
    expect(transcript.sessionId, 'relay-session-demo');
    expect(transcript.hostId, 'host-relay');
    expect(transcript.deviceId, 'dev-relay');
    expect(transcript.protocolVersion, relayProtocolVersion);
    expect(transcript.serverFingerprint, 'host-fp-demo');
    _expectNoRelaySecrets(clientHello.toJson());
    _expectNoRelaySecrets(hostHello.toJson());
  });

  test('rejects invalid relay handshake order and mismatches', () {
    final clientHello = RelayFrame.clientHello(
      sessionId: 'relay-session-demo',
      sequence: 1,
      hostId: 'host-relay',
      deviceId: 'dev-relay',
      clientPublicKeyB64: _b64('client ephemeral public key'),
      supportedVersions: const {relayProtocolVersion},
    );
    final hostHello = RelayFrame.hostHello(
      sessionId: 'relay-session-demo',
      sequence: 2,
      hostId: 'host-relay',
      serverFingerprint: 'host-fp-demo',
      hostPublicKeyB64: _b64('host ephemeral public key'),
    );

    expect(
      () => RelayHandshakeTranscript.negotiate(
        clientHello: hostHello,
        hostHello: clientHello,
      ),
      throwsFormatException,
    );
    expect(
      () => RelayHandshakeTranscript.negotiate(
        clientHello: clientHello,
        hostHello: RelayFrame.hostHello(
          sessionId: 'other-session',
          sequence: 2,
          hostId: 'host-relay',
          serverFingerprint: 'host-fp-demo',
          hostPublicKeyB64: _b64('host ephemeral public key'),
        ),
      ),
      throwsFormatException,
    );
    expect(
      () => RelayHandshakeTranscript.negotiate(
        clientHello: clientHello,
        hostHello: RelayFrame.hostHello(
          sessionId: 'relay-session-demo',
          sequence: 2,
          hostId: 'other-host',
          serverFingerprint: 'host-fp-demo',
          hostPublicKeyB64: _b64('host ephemeral public key'),
        ),
      ),
      throwsFormatException,
    );
    expect(
      () => RelayHandshakeTranscript.negotiate(
        clientHello: clientHello,
        hostHello: RelayFrame.hostHello(
          sessionId: 'relay-session-demo',
          sequence: 2,
          hostId: 'host-relay',
          serverFingerprint: 'host-fp-demo',
          hostPublicKeyB64: _b64('host ephemeral public key'),
          acceptedVersion: 1,
        ),
      ),
      throwsFormatException,
    );
  });

  test('rejects relay v1 downgrade when legacy version is also listed', () {
    final clientHello = RelayFrame.clientHello(
      sessionId: 'relay-session-demo',
      sequence: 1,
      hostId: 'host-relay',
      deviceId: 'dev-relay',
      clientPublicKeyB64: _b64('client ephemeral public key'),
      supportedVersions: const {1, relayProtocolVersion},
    );

    expect(
      () => RelayHandshakeTranscript.negotiate(
        clientHello: clientHello,
        hostHello: RelayFrame.hostHello(
          sessionId: 'relay-session-demo',
          sequence: 2,
          hostId: 'host-relay',
          serverFingerprint: 'host-fp-demo',
          hostPublicKeyB64: _b64('host ephemeral public key'),
          acceptedVersion: 1,
        ),
      ),
      throwsFormatException,
    );
  });

  test('wraps gateway envelopes as opaque relay frames', () {
    final envelope = RelayGatewayEnvelope(
      sessionId: 'relay-session-demo',
      sequence: 3,
      operation: 'send_terminal_frame',
      ciphertextB64: _b64('opaque encrypted gateway request'),
      nonceB64: _b64('relay-session-demo:3'),
      keyId: 'session-key-1',
    );
    final frame = RelayFrame.gatewayEnvelope(envelope: envelope);
    final roundTrip = RelayFrame.fromJson(frame.toJson());

    expect(roundTrip.kind, RelayFrameKind.gatewayEnvelope);
    expect(roundTrip.gatewayEnvelope().toJson(), envelope.toJson());
    _expectNoRelaySecrets(roundTrip.toJson());
    expect(roundTrip.toJson().toString(), isNot(contains('secret paste text')));
  });

  test('rejects cleartext gateway metadata in relay frames', () {
    expect(
      () => RelayFrame(
        sessionId: 'relay-session-demo',
        sequence: 1,
        kind: RelayFrameKind.clientHello,
        payload: {
          'host_id': 'host-relay',
          'device_id': 'dev-relay',
          'client_pubkey_b64': _b64('client key'),
          'supported_versions': [relayProtocolVersion],
          'gateway_url': 'https://relay.seemlab.top',
        },
      ),
      throwsFormatException,
    );
    expect(
      () => RelayFrame(
        sessionId: 'relay-session-demo',
        sequence: 1,
        kind: RelayFrameKind.gatewayEnvelope,
        payload: {
          'envelope': {
            'schema_version': relayProtocolVersion,
            'session_id': 'relay-session-demo',
            'seq': 1,
            'op': 'open_terminal',
            'ciphertext_b64': _b64('opaque'),
            'nonce_b64': _b64('nonce'),
            'project_id': 'proj-demo',
          },
        },
      ),
      throwsFormatException,
    );
  });

  test('defines outbound host registration without local gateway secrets', () {
    final registration = RelayHostRegistration(
      hostId: 'host-relay',
      serverFingerprint: 'host-fp-demo',
      hostPublicKeyB64: _b64('host long lived public key'),
      capabilities: const {'http_json', 'project_view', 'relay_tunnel'},
      diagnostics: const {
        'relay_region': 'local-test',
        'relay_host_id': 'host-relay',
      },
    );

    final roundTrip = RelayHostRegistration.fromJson(registration.toJson());

    expect(roundTrip.hostId, 'host-relay');
    expect(roundTrip.serverFingerprint, 'host-fp-demo');
    expect(roundTrip.capabilities, contains('relay_tunnel'));
    expect(roundTrip.diagnostics['relay_region'], 'local-test');
    _expectNoRelaySecrets(roundTrip.toJson());
    expect(roundTrip.toJson().toString(), isNot(contains('127.0.0.1')));

    expect(
      () => RelayHostRegistration.fromJson({
        ...registration.toJson(),
        'device_token': 'secret-device-token',
      }),
      throwsFormatException,
    );
  });
}

String _b64(String value) {
  return base64UrlEncode(utf8.encode(value));
}

void _expectNoRelaySecrets(Map<String, Object?> json) {
  final text = json.toString();
  expect(text, isNot(contains('pairing_code')));
  expect(text, isNot(contains('device_token')));
  expect(text, isNot(contains('terminal_token')));
  expect(text, isNot(contains('project_id')));
  expect(text, isNot(contains('terminal_id')));
  expect(text, isNot(contains('route_provider')));
  expect(text, isNot(contains('gateway_url')));
  expect(text, isNot(contains('websocket_url')));
  expect(text, isNot(contains('Authorization')));
}
