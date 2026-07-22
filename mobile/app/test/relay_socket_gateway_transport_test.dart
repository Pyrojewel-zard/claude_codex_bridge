import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

void main() {
  test(
    'socket relay transport handshakes and opens encrypted project view',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      final view = await transport.getProjectView('proj-demo');

      expect(view.project.id, 'proj-demo');
      expect(relay.requests.single['operation'], 'get_project_view');
      expect(relay.requests.single['payload'], {
        'project_id': 'proj-demo',
        'device_token': 'device-secret',
      });
      final relayVisibleText = relay.visibleFrames.join('\n');
      expect(relayVisibleText, isNot(contains('proj-demo')));
      expect(relayVisibleText, isNot(contains('device-secret')));
      expect(relayVisibleText, contains('gateway_envelope'));
      expect(relayVisibleText, contains('ciphertext_b64'));
    },
  );

  test('requires production WSS origin outside explicit loopback test mode', () async {
    expect(
      () => RelaySocketGatewayTransport(
        profile: _profileSync(
          relayOrigin: Uri.parse('ws://relay.example'),
          hostFingerprint: 'sha256:host',
        ),
        deviceToken: 'device-secret',
      ),
      throwsArgumentError,
    );
    expect(
      () => RelaySocketGatewayTransport(
        profile: _profileSync(
          relayOrigin: Uri.parse('wss://relay.example/v2/phone'),
          hostFingerprint: 'sha256:host',
        ),
        deviceToken: 'device-secret',
      ),
      throwsArgumentError,
    );
  });

  test('fails closed on host fingerprint mismatch', () async {
    final hostSeed = List<int>.generate(32, (index) => index + 101);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostFingerprint = await hostFingerprintForPublicKey(hostPublicKeyB64);
    final relay = await _RelaySocketHarness.start(
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    addTearDown(relay.stop);
    final transport = RelaySocketGatewayTransport(
      profile: await _profile(
        relayOrigin: relay.origin,
        hostFingerprint: 'sha256:wrong',
      ),
      deviceToken: 'device-secret',
      allowInsecureLoopbackForTests: true,
    );
    addTearDown(() => transport.close(force: true));

    await expectLater(
      transport.getProjectView('proj-demo'),
      throwsA(isA<RelayGatewayException>()),
    );
    expect(relay.requests, isEmpty);
  });

  test('route profile stores relay bootstrap separately from pairing identity', () {
    final profile = _profileSync(
      relayOrigin: Uri.parse('wss://relay.seemlab.top'),
      hostFingerprint: 'sha256:host',
    );

    expect(profile.routeProvider.toPairingJson(), contains('relay_session_id'));
    expect(
      RelayPhoneSessionBootstrap.maybeFromJson(
        profile.routeProvider.toPairingJson(),
      )?.sessionId,
      'relay-session-demo',
    );
  });
}

class _RelaySocketHarness {
  _RelaySocketHarness._({
    required this.server,
    required this.origin,
    required this.hostSeed,
    required this.hostFingerprint,
  });

  final HttpServer server;
  final Uri origin;
  final List<int> hostSeed;
  final String hostFingerprint;
  final visibleFrames = <String>[];
  final requests = <Map<String, Object?>>[];

  static Future<_RelaySocketHarness> start({
    required List<int> hostSeed,
    required String hostFingerprint,
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final harness = _RelaySocketHarness._(
      server: server,
      origin: Uri.parse('ws://127.0.0.1:${server.port}'),
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    server.listen(harness._handle);
    return harness;
  }

  Future<void> stop() {
    return server.close(force: true);
  }

  Future<void> _handle(HttpRequest request) async {
    if (request.uri.path != '/v2/phone') {
      request.response.statusCode = HttpStatus.notFound;
      await request.response.close();
      return;
    }
    final socket = await WebSocketTransformer.upgrade(request);
    final reader = StreamIterator<dynamic>(socket);
    if (!await reader.moveNext()) {
      await socket.close();
      return;
    }
    final clientHelloJson = _jsonMap(reader.current);
    visibleFrames.add(jsonEncode(clientHelloJson));
    final clientHello = RelayFrame.fromJson(clientHelloJson);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostHello = RelayFrame.hostHello(
      sessionId: clientHello.sessionId,
      sequence: clientHello.sequence + 1,
      hostId: _text(clientHello.payload['host_id']),
      serverFingerprint: hostFingerprint,
      hostPublicKeyB64: hostPublicKeyB64,
    );
    final schedule = await RelayV2KeySchedule.derive(
      localPrivateKeyBytes: hostSeed,
      peerPublicKeyB64: _text(clientHello.payload['client_pubkey_b64']),
      role: 'host',
      sessionId: clientHello.sessionId,
      clientPublicKeyB64: _text(clientHello.payload['client_pubkey_b64']),
      hostPublicKeyB64: hostPublicKeyB64,
      expectedHostFingerprint: hostFingerprint,
    );
    final hostCrypto = schedule.session(role: 'host');
    socket.add(jsonEncode(hostHello.toJson()));

    var outerSeq = 3;
    while (await reader.moveNext()) {
      final frameJson = _jsonMap(reader.current);
      visibleFrames.add(jsonEncode(frameJson));
      final frame = RelayFrame.fromJson(frameJson);
      final envelope = frame.gatewayEnvelope();
      final plaintext = await hostCrypto.open(
        RelayV2Envelope.fromJson({
          ...envelope.toJson(),
          'direction': RelayCryptoDirection.phoneToHost.wireName,
        }),
      );
      final payload = _jsonMap(utf8.decode(plaintext));
      requests.add({'operation': envelope.operation, 'payload': payload});
      final responseEnvelope = await hostCrypto.seal(
        operation: '${envelope.operation}.response',
        plaintext: utf8.encode(
          jsonEncode({
            'ok': true,
            'status': 200,
            'body': switch (envelope.operation) {
              'get_project_view' => demoProjectViewFixture,
              'health' => {
                'schema_version': 1,
                'status': 'ok',
                'server_time': '2026-07-22T00:00:00Z',
                'capabilities': ['http_json', 'project_view'],
              },
              _ => {'schema_version': 1, 'status': 'ok'},
            },
          }),
        ),
      );
      socket.add(
        jsonEncode(
          RelayFrame.gatewayEnvelope(
            envelope: RelayGatewayEnvelope(
              schemaVersion: responseEnvelope.schemaVersion,
              sessionId: responseEnvelope.sessionId,
              sequence: responseEnvelope.sequence,
              operation: responseEnvelope.operation,
              direction: responseEnvelope.direction,
              ciphertextB64: responseEnvelope.ciphertextB64,
              nonceB64: responseEnvelope.nonceB64,
              keyId: responseEnvelope.keyId,
            ),
            sequence: outerSeq,
          ).toJson(),
        ),
      );
      outerSeq += 1;
    }
  }
}

Future<GatewayHostProfile> _profile({
  required Uri relayOrigin,
  required String hostFingerprint,
}) async {
  return _profileSync(
    relayOrigin: relayOrigin,
    hostFingerprint: hostFingerprint,
  );
}

GatewayHostProfile _profileSync({
  required Uri relayOrigin,
  required String hostFingerprint,
}) {
  return GatewayHostProfile(
    hostId: 'rhost-demo',
    deviceId: 'dev-demo',
    routeProvider: RouteProvider(
      kind: RouteProviderKind.relay,
      gatewayUrl: Uri.parse('https://relay.seemlab.top'),
      websocketUrl: relayOrigin,
      hostFingerprint: hostFingerprint,
      relayBootstrap: RelayPhoneSessionBootstrap(
        sessionId: 'relay-session-demo',
        clientPrivateKeyB64: _b64(
          List<int>.generate(32, (index) => index + 1),
        ),
        phoneNonceB64: _b64(utf8.encode('fresh phone nonce')),
        rendezvousCapability: 'ccb-relay-rv-v1.fake',
      ),
      capabilities: const {'relay.forward'},
    ),
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle'},
  );
}

Future<String> _publicKeyB64(List<int> privateKeyBytes) async {
  final keyPair = await X25519().newKeyPairFromSeed(privateKeyBytes);
  final publicKey = await keyPair.extractPublicKey();
  return _b64(publicKey.bytes);
}

Map<String, Object?> _jsonMap(Object? message) {
  final text = switch (message) {
    final String value => value,
    final List<int> value => utf8.decode(value),
    _ => message.toString(),
  };
  final decoded = jsonDecode(text);
  if (decoded is Map) {
    return {
      for (final entry in decoded.entries) entry.key.toString(): entry.value,
    };
  }
  throw const FormatException('test relay frame is not an object');
}

String _text(Object? value) => (value ?? '').toString();

String _b64(List<int> value) => base64UrlEncode(value).replaceAll('=', '');
