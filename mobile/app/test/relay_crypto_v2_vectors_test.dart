import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('derives v2 key schedule and decrypts Python vector', () async {
    final vector = await _fixture();

    final phoneSchedule = await RelayV2KeySchedule.derive(
      localPrivateKeyBytes: _b64Decode(vector['client_seed_b64']),
      peerPublicKeyB64: vector['host_public_key_b64'] as String,
      role: 'phone',
      sessionId: vector['session_id'] as String,
      clientPublicKeyB64: vector['client_public_key_b64'] as String,
      hostPublicKeyB64: vector['host_public_key_b64'] as String,
      expectedHostFingerprint: vector['host_fingerprint'] as String,
    );
    final hostSchedule = await RelayV2KeySchedule.derive(
      localPrivateKeyBytes: _b64Decode(vector['host_seed_b64']),
      peerPublicKeyB64: vector['client_public_key_b64'] as String,
      role: 'host',
      sessionId: vector['session_id'] as String,
      clientPublicKeyB64: vector['client_public_key_b64'] as String,
      hostPublicKeyB64: vector['host_public_key_b64'] as String,
      expectedHostFingerprint: vector['host_fingerprint'] as String,
    );

    expect(phoneSchedule.toPublicJson(), hostSchedule.toPublicJson());
    expect(phoneSchedule.transcriptHashB64, vector['transcript_hash_b64']);
    final confirmation = vector['key_confirmation'] as Map<String, Object?>;
    expect(phoneSchedule.phoneKeyConfirmationB64, confirmation['phone_b64']);
    expect(phoneSchedule.hostKeyConfirmationB64, confirmation['host_b64']);
    final host = hostSchedule.session(role: 'host');
    final plaintext = await host.open(
      RelayV2Envelope.fromJson(
        Map<String, Object?>.from(vector['frame'] as Map),
      ),
    );
    expect(_b64(plaintext), vector['plaintext_b64']);
  });

  test(
    'rejects replay, corruption, downgrade, and fingerprint mismatch',
    () async {
      final vector = await _fixture();
      final sessions = await _sessions(vector);
      final first = await sessions.phone.seal(
        operation: 'first',
        plaintext: utf8.encode('one'),
      );
      final second = await sessions.phone.seal(
        operation: 'second',
        plaintext: utf8.encode('two'),
      );

      expect(
        () => sessions.host.open(second),
        throwsA(isA<RelayCryptoException>()),
      );
      expect(await sessions.host.open(first), utf8.encode('one'));
      expect(
        () => sessions.host.open(first),
        throwsA(isA<RelayCryptoException>()),
      );
      expect(await sessions.host.open(second), utf8.encode('two'));

      final corruptedSessions = await _sessions(vector);
      final sealed = await corruptedSessions.phone.seal(
        operation: 'tamper',
        plaintext: utf8.encode('payload'),
      );
      final tampered = sealed.toJson();
      final ciphertext = tampered['ciphertext_b64'] as String;
      tampered['ciphertext_b64'] =
          '${ciphertext.substring(0, ciphertext.length - 1)}${ciphertext.endsWith('A') ? 'B' : 'A'}';
      expect(
        () => corruptedSessions.host.open(RelayV2Envelope.fromJson(tampered)),
        throwsA(isA<RelayCryptoException>()),
      );

      expect(
        () => negotiateRelayV2(const [1]),
        throwsA(isA<RelayCryptoException>()),
      );
      expect(
        negotiateRelayV2(const [1, relayProtocolVersion]),
        relayProtocolVersion,
      );
      expect(
        () => RelayV2KeySchedule.derive(
          localPrivateKeyBytes: _b64Decode(vector['client_seed_b64']),
          peerPublicKeyB64: vector['host_public_key_b64'] as String,
          role: 'phone',
          sessionId: vector['session_id'] as String,
          clientPublicKeyB64: vector['client_public_key_b64'] as String,
          hostPublicKeyB64: vector['host_public_key_b64'] as String,
          expectedHostFingerprint: 'sha256:wrong',
        ),
        throwsA(isA<RelayCryptoException>()),
      );
    },
  );

  test(
    'rejects prohibited plaintext fields and zeroizes session keys',
    () async {
      final vector = await _fixture();
      expect(
        () => RelayV2Envelope.fromJson({
          ...Map<String, Object?>.from(vector['frame'] as Map),
          'project_id': 'proj-secret',
        }),
        throwsFormatException,
      );
      expect(
        () => assertNoProhibitedRelayPlaintext({
          'payload': {'prompt': 'secret'},
        }),
        throwsFormatException,
      );
      final sessions = await _sessions(vector);
      sessions.phone.close();
      expect(sessions.phone.closed, isTrue);
      expect(sessions.phone.keyMaterialErased(), isTrue);
      expect(
        () => sessions.phone.seal(operation: 'closed', plaintext: const []),
        throwsA(isA<RelayCryptoException>()),
      );
    },
  );

  test('rejects sequence above uint64 and closes exhausted sessions', () async {
    final vector = await _fixture();
    final sessions = await _sessions(vector);
    final phone = RelayCryptoSession(
      sessionId: sessions.phone.sessionId,
      sendDirection: sessions.phone.sendDirection,
      receiveDirection: sessions.phone.receiveDirection,
      sendKey: List<int>.filled(32, 1),
      receiveKey: List<int>.filled(32, 2),
      sendNoncePrefix: const [1, 2, 3, 4],
      receiveNoncePrefix: const [5, 6, 7, 8],
      initialSendSequence: relayMaxSequence + BigInt.one,
    );

    expect(
      () => phone.seal(operation: 'overflow', plaintext: const []),
      throwsA(isA<RelayCryptoException>()),
    );
    expect(phone.closed, isTrue);

    final host = RelayCryptoSession(
      sessionId: sessions.host.sessionId,
      sendDirection: sessions.host.sendDirection,
      receiveDirection: sessions.host.receiveDirection,
      sendKey: List<int>.filled(32, 2),
      receiveKey: List<int>.filled(32, 1),
      sendNoncePrefix: const [5, 6, 7, 8],
      receiveNoncePrefix: const [1, 2, 3, 4],
      initialReceiveSequence: relayMaxSequence + BigInt.one,
    );
    expect(
      () => host.open(
        RelayV2Envelope(
          sessionId: sessions.host.sessionId,
          sequence: 1,
          direction: RelayCryptoDirection.phoneToHost,
          operation: 'overflow',
          nonceB64: _b64(List<int>.filled(12, 0)),
          ciphertextB64: _b64(List<int>.filled(16, 0)),
        ),
      ),
      throwsA(isA<RelayCryptoException>()),
    );
    expect(host.closed, isTrue);
    expect(
      () => RelayV2Envelope.fromJson({
        'schema_version': relayProtocolVersion,
        'session_id': 'relay-session-demo',
        'seq': (relayMaxSequence + BigInt.one).toString(),
        'direction': RelayCryptoDirection.phoneToHost.wireName,
        'op': 'overflow',
        'nonce_b64': _b64(List<int>.filled(12, 0)),
        'ciphertext_b64': _b64(List<int>.filled(16, 0)),
        'key_id': relayKeyId,
      }),
      throwsFormatException,
    );
  });
}

Future<Map<String, Object?>> _fixture() async {
  return Map<String, Object?>.from(
    jsonDecode(
          await File(
            'test/fixtures/relay_crypto_v2_vectors.json',
          ).readAsString(),
        )
        as Map,
  );
}

Future<({RelayCryptoSession phone, RelayCryptoSession host})> _sessions(
  Map<String, Object?> vector,
) async {
  final phoneSchedule = await RelayV2KeySchedule.derive(
    localPrivateKeyBytes: _b64Decode(vector['client_seed_b64']),
    peerPublicKeyB64: vector['host_public_key_b64'] as String,
    role: 'phone',
    sessionId: vector['session_id'] as String,
    clientPublicKeyB64: vector['client_public_key_b64'] as String,
    hostPublicKeyB64: vector['host_public_key_b64'] as String,
    expectedHostFingerprint: vector['host_fingerprint'] as String,
  );
  final hostSchedule = await RelayV2KeySchedule.derive(
    localPrivateKeyBytes: _b64Decode(vector['host_seed_b64']),
    peerPublicKeyB64: vector['client_public_key_b64'] as String,
    role: 'host',
    sessionId: vector['session_id'] as String,
    clientPublicKeyB64: vector['client_public_key_b64'] as String,
    hostPublicKeyB64: vector['host_public_key_b64'] as String,
    expectedHostFingerprint: vector['host_fingerprint'] as String,
  );
  return (
    phone: phoneSchedule.session(role: 'phone'),
    host: hostSchedule.session(role: 'host'),
  );
}

List<int> _b64Decode(Object? value) {
  final text = value.toString();
  return base64Url.decode(
    text.padRight(text.length + ((4 - text.length % 4) % 4), '='),
  );
}

String _b64(List<int> value) {
  return base64UrlEncode(value).replaceAll('=', '');
}
