import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  late HttpServer server;
  late GatewayPairingClient client;
  late Uri baseUrl;
  final requests = <Map<String, Object?>>[];

  setUp(() async {
    requests.clear();
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      final body = await utf8.decodeStream(request);
      requests.add({
        'path': request.uri.path,
        'authorization': request.headers.value(HttpHeaders.authorizationHeader),
        'content_length': request.headers.contentLength,
        'body': body,
      });
      final payload = _payloadForRequest(request.uri.path, body);
      request.response.headers.contentType = ContentType.json;
      request.response.statusCode = payload.statusCode;
      request.response.write(jsonEncode(payload.body));
      await request.response.close();
    });
    baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    client = GatewayPairingClient();
  });

  tearDown(() async {
    client.close(force: true);
    await server.close(force: true);
  });

  test('accepts official Relay QR only for the official endpoint', () {
    final pairing = GatewayPairingPayload.fromJson({
      'pairing_code': 'official-code',
      'claim_endpoint': 'https://47.120.71.142/v1/pairing/claim',
      'route_provider': 'relay',
      'relay_mode': 'official',
      'gateway_url': 'https://47.120.71.142',
      'websocket_url': 'wss://47.120.71.142',
      'scopes': ['view'],
    });
    expect(pairing.relayMode, RelayDeploymentMode.official);

    expect(
      () => GatewayPairingPayload.fromJson({
        'pairing_code': 'spoofed-code',
        'claim_endpoint': 'https://relay.example.test/v1/pairing/claim',
        'route_provider': 'relay',
        'relay_mode': 'official',
        'gateway_url': 'https://relay.example.test',
        'websocket_url': 'wss://relay.example.test',
        'scopes': ['view'],
      }),
      throwsFormatException,
    );
  });

  test('claims pairing payload and stores host profile securely', () async {
    final secureStore = _MemorySecureStore();
    final store = GatewayHostProfileStore(secureStore: secureStore);
    final pairing = GatewayPairingPayload.fromJson({
      'pairing_code': 'one-time-code',
      'claim_endpoint': '$baseUrl/v1/pairing/claim',
      'route_provider': 'lan',
      'gateway_url': baseUrl.toString(),
      'project_id': 'proj-demo',
      'scopes': ['view'],
      'expires_at': '2026-06-18T00:10:00Z',
    });

    final paired = await client.claimAndStore(
      pairing: pairing,
      deviceName: 'Pixel Fold',
      store: store,
    );
    final loaded = await store.read(
      hostId: paired.profile.hostId,
      deviceId: paired.profile.deviceId,
    );

    expect(paired.profile.hostId, 'proj-demo');
    expect(paired.profile.deviceId, 'dev_demo');
    expect(paired.profile.routeProvider.kind, RouteProviderKind.lan);
    expect(paired.profile.routeProvider.gatewayUrl, baseUrl);
    expect(paired.profile.scopes, {'view'});
    expect(paired.deviceToken, 'device-secret');
    expect(loaded?.deviceToken, 'device-secret');
    expect(
      (await store.resolvePreferred(await store.list()))?.profile.deviceId,
      'dev_demo',
    );
    expect(
      loaded?.profile.toJson().toString(),
      isNot(contains('device-secret')),
    );
    expect(secureStore.rawValues.join('\n'), isNot(contains('one-time-code')));
    expect(requests.single['path'], '/v1/pairing/claim');
    expect(requests.single['content_length'], greaterThan(0));
    expect(jsonDecode(requests.single['body'] as String), {
      'pairing_code': 'one-time-code',
      'device_name': 'Pixel Fold',
    });
  });

  test('injects stored device token into gateway HTTP requests', () async {
    final transport = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'proj-demo',
        deviceId: 'dev_demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view'},
      ),
      deviceToken: 'device-secret',
    );
    try {
      final health = await transport.health();

      expect(health.status, 'ok');
      expect(requests.single['path'], '/v1/health');
      expect(requests.single['authorization'], 'Bearer device-secret');
    } finally {
      transport.close(force: true);
    }
  });

  test(
    'claim may reuse a device id without sending the stored device token',
    () async {
      final pairing = GatewayPairingPayload.fromJson({
        'pairing_code': 'one-time-code',
        'claim_endpoint': '$baseUrl/v1/pairing/claim',
        'route_provider': 'lan',
        'gateway_url': baseUrl.toString(),
        'project_id': 'proj-demo',
        'scopes': ['view'],
      });

      await client.claim(
        pairing: pairing,
        deviceName: 'Pixel Fold',
        deviceId: 'dev_previous',
      );

      expect(jsonDecode(requests.single['body'] as String), {
        'pairing_code': 'one-time-code',
        'device_name': 'Pixel Fold',
        'device_id': 'dev_previous',
      });
      expect(requests.single['body'], isNot(contains('device-secret')));
    },
  );

  test('rejects claim responses that omit the device token', () async {
    final pairing = GatewayPairingPayload.fromJson({
      'pairing_code': 'missing-token',
      'claim_endpoint': '$baseUrl/v1/pairing/claim',
      'route_provider': 'lan',
      'gateway_url': baseUrl.toString(),
      'scopes': ['view'],
    });

    await expectLater(
      client.claim(pairing: pairing, deviceName: 'Pixel Fold'),
      throwsA(isA<FormatException>()),
    );
  });

  test('parses source pairing QR payload JSON', () {
    final payload = GatewayPairingPayload.fromQrText(
      jsonEncode({
        'schema_version': 1,
        'pairing_id': 'pair_demo',
        'pairing_code': 'qr-code',
        'project_id': 'proj-demo',
        'route_provider': 'cloudflare_tunnel',
        'gateway_url': 'https://mobile.example.com',
        'claim_endpoint': 'https://mobile.example.com/v1/pairing/claim',
        'scopes': ['view', 'focus', 'terminal_input'],
        'expires_at': '2026-06-18T00:10:00Z',
      }),
    );

    expect(payload.pairingCode, 'qr-code');
    expect(payload.projectId, 'proj-demo');
    expect(payload.routeProvider, RouteProviderKind.cloudflareTunnel);
    expect(payload.gatewayUrl, Uri.parse('https://mobile.example.com'));
    expect(
      payload.claimEndpoint,
      Uri.parse('https://mobile.example.com/v1/pairing/claim'),
    );
    expect(payload.scopes, {'view', 'focus', 'terminal_input'});
    expect(
      payload.expiresAt?.toUtc().toIso8601String(),
      '2026-06-18T00:10:00.000Z',
    );
  });

  test(
    'connection code round trips complete Relay bootstrap without padding',
    () {
      final original = GatewayPairingPayload.fromJson({
        'pairing_code': 'relay-code',
        'claim_endpoint': 'https://relay.example.com/v1/pairing/claim',
        'route_provider': 'relay',
        'gateway_url': 'https://relay.example.com',
        'scopes': ['view', 'notify'],
        'project_id': 'host-relay',
        'host_id': 'host-relay',
        'websocket_url': 'wss://relay.example.com',
        'server_fingerprint': 'sha256:relay-host',
        'relay_session_id': 'relay-session',
        'relay_client_private_key_b64': 'bootstrap-private-key',
        'relay_phone_nonce_b64': 'bootstrap-phone-nonce',
        'relay_rendezvous_capability': 'ccb-relay-rv-v1.payload.signature',
        'relay_bootstrap_expires_at': '2026-07-25T00:00:00Z',
        'relay_bootstrap_single_use': true,
      });

      final code = original.toConnectionCode();
      final decoded = GatewayPairingPayload.fromConnectionText(code);

      expect(code, startsWith(gatewayPairingConnectionCodePrefix));
      expect(code, isNot(contains('=')));
      expect(decoded.toJson(), original.toJson());
      expect(decoded.relayBootstrap?.sessionId, 'relay-session');
      expect(decoded.relayBootstrapSingleUse, isTrue);
    },
  );

  test('parses compact Relay terminal QR from signed capability fields', () {
    const expiresAtSeconds = 1785124800;
    final capabilityPayload = base64Url
        .encode(
          utf8.encode(
            jsonEncode({
              'typ': 'ccb-relay-rv-v1',
              'schema_version': 2,
              'host_id': 'relay-host-compact',
              'session_id': 'relay-session-compact',
              'phone_nonce_b64': 'phone-nonce-compact',
              'aud': 'wss://47.120.71.142',
              'exp': expiresAtSeconds,
            }),
          ),
        )
        .replaceAll('=', '');
    final capability = 'header.$capabilityPayload.signature';
    final compactQr =
        '$gatewayCompactRelayQrPrefix'
        'pair-code|client-private|sha256:host-fingerprint|o|$capability';

    final pairing = GatewayPairingPayload.fromQrText(compactQr);

    expect(pairing.pairingCode, 'pair-code');
    expect(pairing.routeProvider, RouteProviderKind.relay);
    expect(pairing.relayMode, RelayDeploymentMode.official);
    expect(pairing.gatewayUrl, Uri.parse('https://47.120.71.142'));
    expect(
      pairing.claimEndpoint,
      Uri.parse('https://47.120.71.142/v1/pairing/claim'),
    );
    expect(pairing.websocketUrl, Uri.parse('wss://47.120.71.142'));
    expect(pairing.hostId, 'relay-host-compact');
    expect(pairing.hostFingerprint, 'sha256:host-fingerprint');
    expect(pairing.scopes, isEmpty);
    expect(pairing.relayBootstrap?.sessionId, 'relay-session-compact');
    expect(pairing.relayBootstrap?.clientPrivateKeyB64, 'client-private');
    expect(pairing.relayBootstrap?.phoneNonceB64, 'phone-nonce-compact');
    expect(pairing.relayBootstrap?.rendezvousCapability, capability);
    expect(
      pairing.relayBootstrapExpiresAt,
      DateTime.fromMillisecondsSinceEpoch(
        expiresAtSeconds * Duration.millisecondsPerSecond,
        isUtc: true,
      ),
    );
    expect(pairing.relayBootstrapSingleUse, isTrue);
  });

  test('rejects malformed or spoofed compact Relay terminal QR', () {
    String capabilityFor(String audience) {
      final payload = base64Url
          .encode(
            utf8.encode(
              jsonEncode({
                'typ': 'ccb-relay-rv-v1',
                'host_id': 'relay-host',
                'session_id': 'relay-session',
                'phone_nonce_b64': 'phone-nonce',
                'aud': audience,
                'exp': 1785124800,
              }),
            ),
          )
          .replaceAll('=', '');
      return 'header.$payload.signature';
    }

    expect(
      () => GatewayPairingPayload.fromQrText(
        '${gatewayCompactRelayQrPrefix}too|few|fields',
      ),
      throwsFormatException,
    );
    expect(
      () => GatewayPairingPayload.fromQrText(
        '$gatewayCompactRelayQrPrefix'
        'code|private|fingerprint|x|${capabilityFor('wss://47.120.71.142')}',
      ),
      throwsFormatException,
    );
    expect(
      () => GatewayPairingPayload.fromQrText(
        '$gatewayCompactRelayQrPrefix'
        'code|private|fingerprint|o|'
        '${capabilityFor('wss://relay.example.test')}',
      ),
      throwsFormatException,
    );
  });

  test('connection parser retains raw QR JSON compatibility', () {
    final rawJson = jsonEncode({
      'pairing_code': 'lan-code',
      'claim_endpoint': '$baseUrl/v1/pairing/claim',
      'route_provider': 'lan',
      'gateway_url': baseUrl.toString(),
      'scopes': ['view'],
    });

    final decoded = GatewayPairingPayload.fromConnectionText(rawJson);

    expect(decoded.pairingCode, 'lan-code');
    expect(decoded.routeProvider, RouteProviderKind.lan);
  });

  test('connection parser rejects malformed and oversized input', () {
    expect(
      () => GatewayPairingPayload.fromConnectionText('ccb1_%%%'),
      throwsFormatException,
    );
    expect(
      () => GatewayPairingPayload.fromConnectionText('ccb1__w'),
      throwsFormatException,
    );
    expect(
      () => GatewayPairingPayload.fromConnectionText('[]'),
      throwsFormatException,
    );
    expect(
      () => GatewayPairingPayload.fromConnectionText(
        List.filled(16 * 1024 + 1, 'x').join(),
      ),
      throwsFormatException,
    );
  });

  test('parses mobile update pairing QR payload JSON', () {
    final payload = GatewayPairingPayload.fromQrText(
      jsonEncode({
        'claim_endpoint':
            'https://desktop.tailnet.ts.net:8787/v1/pairing/claim',
        'gateway_url': 'https://desktop.tailnet.ts.net:8787',
        'pairing_code': 'stable-code',
        'route_provider': 'tailnet',
        'scopes': [
          'view',
          'message_submit',
          'terminal_input',
          'file_upload',
          'file_download',
        ],
      }),
    );

    expect(payload.pairingCode, 'stable-code');
    expect(payload.routeProvider, RouteProviderKind.tailnet);
    expect(
      payload.gatewayUrl,
      Uri.parse('https://desktop.tailnet.ts.net:8787'),
    );
    expect(
      payload.claimEndpoint,
      Uri.parse('https://desktop.tailnet.ts.net:8787/v1/pairing/claim'),
    );
    expect(payload.scopes, {
      'view',
      'message_submit',
      'terminal_input',
      'file_upload',
      'file_download',
    });
  });

  test('durable relay profile does not retain one-time QR bootstrap', () {
    final pairing = GatewayPairingPayload.fromQrText(
      jsonEncode({
        'pairing_code': 'one-time-relay-code',
        'claim_endpoint': 'https://relay.seemlab.top/v1/pairing/claim',
        'route_provider': 'relay',
        'gateway_url': 'https://relay.seemlab.top',
        'host_id': 'rhost-demo',
        'websocket_url': 'wss://relay.seemlab.top',
        'server_fingerprint': 'sha256:host-demo',
        'relay_session_id': 'pair-session-demo',
        'relay_client_private_key_b64': 'bootstrap-private-key',
        'relay_phone_nonce_b64': 'bootstrap-phone-nonce',
        'relay_rendezvous_capability': 'ccb-relay-rv-v1.payload.signature',
        'relay_bootstrap_expires_at': '2026-07-23T00:00:00Z',
        'relay_bootstrap_single_use': true,
        'scopes': ['view', 'notify'],
      }),
    );
    final paired = GatewayPairedHost.fromClaimJson(
      {
        'device_token': 'device-secret',
        'device': {'device_id': 'device-demo', 'project_id': 'project-demo'},
        'host_profile': {
          'host_id': 'rhost-demo',
          'device_id': 'device-demo',
          'project_id': 'project-demo',
          'route_provider': 'relay',
          'gateway_url': 'https://relay.seemlab.top',
          'websocket_url': 'wss://relay.seemlab.top',
          'server_fingerprint': 'sha256:host-demo',
          'relay_access_grant': 'ccb-relay-access-v1.payload.signature',
          'scopes': ['view', 'notify'],
          'capabilities': ['relay_tunnel', 'relay_reconnect'],
        },
      },
      pairing: pairing,
      relayPhoneAuthPrivateKeyB64: 'phone-auth-private-key',
    );

    final secureJson = jsonEncode(paired.toSecureJson());
    final restored = GatewayPairedHost.fromSecureJson(
      jsonDecode(secureJson) as Map<String, Object?>,
    );

    expect(restored.profile.routeProvider.relayAccess, isNotNull);
    expect(restored.profile.routeProvider.relayBootstrap, isNull);
    expect(secureJson, contains('ccb-relay-access-v1.payload.signature'));
    expect(secureJson, contains('phone-auth-private-key'));
    expect(secureJson, isNot(contains('one-time-relay-code')));
    expect(secureJson, isNot(contains('pair-session-demo')));
    expect(secureJson, isNot(contains('bootstrap-private-key')));
    expect(secureJson, isNot(contains('bootstrap-phone-nonce')));
    expect(secureJson, isNot(contains('ccb-relay-rv-v1.payload.signature')));
  });

  test('claims relay pairing and stores relay route metadata', () async {
    final secureStore = _MemorySecureStore();
    final store = GatewayHostProfileStore(secureStore: secureStore);
    final pairing = GatewayPairingPayload.fromJson({
      'pairing_code': 'relay-code',
      'claim_endpoint': '$baseUrl/v1/pairing/claim',
      'route_provider': 'relay',
      'gateway_url': 'https://relay.seemlab.top',
      'project_id': 'proj-relay',
      'scopes': ['view', 'focus', 'terminal_input', 'lifecycle'],
    });

    final paired = await client.claimAndStore(
      pairing: pairing,
      deviceName: 'Android Emulator Relay',
      store: store,
    );
    final loaded = await store.read(
      hostId: paired.profile.hostId,
      deviceId: paired.profile.deviceId,
    );

    expect(paired.profile.hostId, 'host-relay');
    expect(paired.projectId, 'proj-relay');
    expect(paired.profile.routeProvider.kind, RouteProviderKind.relay);
    expect(
      paired.profile.routeProvider.gatewayUrl,
      Uri.parse('https://relay.seemlab.top'),
    );
    expect(
      paired.profile.routeProvider.websocketUrl,
      Uri.parse('wss://relay.seemlab.top'),
    );
    expect(paired.profile.routeProvider.hostFingerprint, 'relay-host-fp');
    expect(paired.profile.routeProvider.capabilities, {
      'http_json',
      'project_view',
      'websocket_terminal',
      'relay_tunnel',
    });
    expect(paired.profile.routeProvider.diagnostics, {
      'relay_region': 'local-test',
      'relay_host_id': 'host-relay',
    });
    expect(paired.profile.scopes, {
      'view',
      'focus',
      'terminal_input',
      'lifecycle',
    });
    expect(loaded?.profile.routeProvider.kind, RouteProviderKind.relay);
    expect(
      loaded?.profile.routeProvider.websocketUrl,
      Uri.parse('wss://relay.seemlab.top'),
    );
    expect(secureStore.rawValues.join('\n'), isNot(contains('relay-code')));
  });

  test('rejects malformed pairing QR payload text', () {
    expect(
      () => GatewayPairingPayload.fromQrText('not json'),
      throwsA(isA<FormatException>()),
    );
  });
}

_GatewayResponse _payloadForRequest(String path, String body) {
  if (path == '/v1/health') {
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'server_time': '2026-06-18T00:00:00Z',
      'capabilities': ['http_json', 'project_view', 'pairing'],
    });
  }
  if (path == '/v1/pairing/claim') {
    final request = jsonDecode(body) as Map<String, Object?>;
    if (request['pairing_code'] == 'missing-token') {
      return _GatewayResponse({
        'schema_version': 1,
        'status': 'ok',
        'device': {'device_id': 'dev_demo', 'project_id': 'proj-demo'},
        'host_profile': {
          'host_id': 'proj-demo',
          'project_id': 'proj-demo',
          'device_id': 'dev_demo',
          'route_provider': 'lan',
          'scopes': ['view'],
        },
      });
    }
    if (request['pairing_code'] == 'relay-code') {
      return _GatewayResponse({
        'schema_version': 1,
        'status': 'ok',
        'device_token': 'device-secret',
        'device': {
          'device_id': 'dev_relay',
          'name': request['device_name'],
          'project_id': 'proj-relay',
          'scopes': ['view', 'focus', 'terminal_input', 'lifecycle'],
          'created_at': '2026-06-21T00:00:00Z',
          'revoked': false,
        },
        'host_profile': {
          'host_id': 'host-relay',
          'project_id': 'proj-relay',
          'device_id': 'dev_relay',
          'route_provider': 'relay',
          'gateway_url': 'https://relay.seemlab.top',
          'websocket_url': 'wss://relay.seemlab.top',
          'server_fingerprint': 'relay-host-fp',
          'capabilities': [
            'http_json',
            'project_view',
            'websocket_terminal',
            'relay_tunnel',
          ],
          'diagnostics': {
            'relay_region': 'local-test',
            'relay_host_id': 'host-relay',
          },
          'scopes': ['view', 'focus', 'terminal_input', 'lifecycle'],
        },
      }, 201);
    }
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'device_token': 'device-secret',
      'device': {
        'device_id': 'dev_demo',
        'name': request['device_name'],
        'project_id': 'proj-demo',
        'scopes': ['view'],
        'created_at': '2026-06-18T00:00:00Z',
        'revoked': false,
      },
      'host_profile': {
        'host_id': 'proj-demo',
        'project_id': 'proj-demo',
        'device_id': 'dev_demo',
        'route_provider': 'lan',
        'scopes': ['view'],
      },
    }, 201);
  }
  return _GatewayResponse({'status': 'error', 'error': 'not found'}, 404);
}

class _GatewayResponse {
  const _GatewayResponse(this.body, [this.statusCode = 200]);

  final Map<String, Object?> body;
  final int statusCode;
}

class _MemorySecureStore implements GatewaySecureStore {
  final Map<String, String> values = {};

  Iterable<String> get rawValues => values.values;

  @override
  Future<void> delete({required String key}) async {
    values.remove(key);
  }

  @override
  Future<String?> read({required String key}) async {
    return values[key];
  }

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }
}
