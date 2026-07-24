import 'package:ccb_mobile/features/project_home/project_home_pairing_form_controller.dart';
import 'package:ccb_mobile/features/project_home/project_home_pairing_request.dart';
import 'package:ccb_mobile/pairing/gateway_pairing.dart';
import 'package:ccb_mobile/transport/route_provider.dart';
import 'package:test/test.dart';

void main() {
  test('defaults expose initial text and route kind', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);

    expect(controller.gatewayUrlController.text, 'http://127.0.0.1:8787');
    expect(controller.pairingCodeController.text, isEmpty);
    expect(controller.deviceNameController.text, 'Phone');
    expect(controller.routeKind, RouteProviderKind.lan);
    expect(controller.routeKindListenable.value, RouteProviderKind.lan);
  });

  test('setRouteKind updates getter and listenable', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    final changes = <RouteProviderKind>[];
    controller.routeKindListenable.addListener(() {
      changes.add(controller.routeKindListenable.value);
    });

    controller.setRouteKind(RouteProviderKind.relay);

    expect(controller.routeKind, RouteProviderKind.relay);
    expect(controller.routeKindListenable.value, RouteProviderKind.relay);
    expect(changes, [RouteProviderKind.relay]);
  });

  test('manual request uses current route and trimmed fields', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.gatewayUrlController.text = ' https://gateway.example.com/base ';
    controller.pairingCodeController.text = ' code-123 ';
    controller.deviceNameController.text = ' Pixel ';
    controller.setRouteKind(RouteProviderKind.cloudflareTunnel);

    final request = controller.buildRequest();

    expect(request.deviceName, 'Pixel');
    expect(request.pairing.pairingCode, 'code-123');
    expect(
      request.pairing.gatewayUrl,
      Uri.parse('https://gateway.example.com/base'),
    );
    expect(
      request.pairing.claimEndpoint,
      Uri.parse('https://gateway.example.com/v1/pairing/claim'),
    );
    expect(request.pairing.routeProvider, RouteProviderKind.cloudflareTunnel);
    expect(request.pairing.scopes, projectHomeManualPairingScopes);
  });

  test('manual request defaults empty device name', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.gatewayUrlController.text = 'http://gateway.local:8787';
    controller.pairingCodeController.text = 'abc';
    controller.deviceNameController.text = '   ';

    final request = controller.buildRequest();

    expect(request.deviceName, projectHomePairingDefaultDeviceName);
  });

  test('invalid manual URL throws existing message', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.gatewayUrlController.text = 'not a url';
    controller.pairingCodeController.text = 'abc';

    expect(
      controller.buildRequest,
      throwsA(
        isA<ProjectHomePairingRequestException>().having(
          (error) => error.message,
          'message',
          'Gateway URL is required',
        ),
      ),
    );
  });

  test('missing manual code throws existing message', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.gatewayUrlController.text = 'http://gateway.local:8787';
    controller.pairingCodeController.text = '   ';

    expect(
      controller.buildRequest,
      throwsA(
        isA<ProjectHomePairingRequestException>().having(
          (error) => error.message,
          'message',
          'Pairing code is required',
        ),
      ),
    );
  });

  test(
    'override request returns same payload and ignores invalid manual fields',
    () {
      final controller = ProjectHomePairingFormController();
      addTearDown(controller.dispose);
      final payload = _pairingPayload(
        code: 'scan-code',
        routeKind: RouteProviderKind.cloudflareTunnel,
      );
      controller.gatewayUrlController.text = 'not a url';
      controller.pairingCodeController.text = '';
      controller.deviceNameController.text = ' Scanner ';

      final request = controller.buildRequest(pairingOverride: payload);

      expect(request.pairing, same(payload));
      expect(request.deviceName, 'Scanner');
    },
  );

  test('scanned payload applies URL code route and notifies', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    final changes = <RouteProviderKind>[];
    controller.routeKindListenable.addListener(() {
      changes.add(controller.routeKindListenable.value);
    });
    final payload = _pairingPayload(
      gatewayUrl: Uri.parse('https://scan.example.com'),
      code: 'scan-code',
      routeKind: RouteProviderKind.cloudflareTunnel,
    );

    controller.applyScannedPairing(payload);

    expect(controller.gatewayUrlController.text, 'https://scan.example.com');
    expect(controller.pairingCodeController.text, 'scan-code');
    expect(controller.routeKind, RouteProviderKind.cloudflareTunnel);
    expect(changes, [RouteProviderKind.cloudflareTunnel]);
  });

  test('scanned relay payload survives a claim retry', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    final payload = _relayPairingPayload();

    controller.applyScannedPairing(payload);

    final request = controller.buildRequest();

    expect(request.pairing, same(payload));
    expect(request.pairing.hostId, 'host-relay');
    expect(request.pairing.relayBootstrap?.sessionId, 'relay-session');
    expect(
      request.pairing.relayBootstrap?.rendezvousCapability,
      'ccb-relay-rv-v1.payload.signature',
    );
  });

  test('editing a scanned relay identity discards its one-time bootstrap', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    final payload = _relayPairingPayload();
    controller.applyScannedPairing(payload);

    controller.pairingCodeController.text = 'replacement-code';
    final request = controller.buildRequest();

    expect(request.pairing, isNot(same(payload)));
    expect(request.pairing.pairingCode, 'replacement-code');
    expect(request.pairing.relayBootstrap, isNull);
  });

  test('activation applies URL and route without clearing code or device', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.pairingCodeController.text = 'keep-code';
    controller.deviceNameController.text = 'Keep Device';

    controller.applyGatewayActivation(
      gatewayUrlText: 'https://activated.example.com',
      routeKind: RouteProviderKind.relay,
    );

    expect(
      controller.gatewayUrlController.text,
      'https://activated.example.com',
    );
    expect(controller.routeKind, RouteProviderKind.relay);
    expect(controller.pairingCodeController.text, 'keep-code');
    expect(controller.deviceNameController.text, 'Keep Device');
  });

  test('clearPairingCode only clears code', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.gatewayUrlController.text = 'https://gateway.example.com';
    controller.pairingCodeController.text = 'clear-me';
    controller.deviceNameController.text = 'Device';
    controller.setRouteKind(RouteProviderKind.tailnet);

    controller.clearPairingCode();

    expect(controller.gatewayUrlController.text, 'https://gateway.example.com');
    expect(controller.pairingCodeController.text, isEmpty);
    expect(controller.deviceNameController.text, 'Device');
    expect(controller.routeKind, RouteProviderKind.tailnet);
  });
}

GatewayPairingPayload _pairingPayload({
  String code = 'code',
  Uri? gatewayUrl,
  RouteProviderKind routeKind = RouteProviderKind.lan,
}) {
  final url = gatewayUrl ?? Uri.parse('http://gateway.local:8787');
  return GatewayPairingPayload(
    pairingCode: code,
    claimEndpoint: url.resolve('/v1/pairing/claim'),
    routeProvider: routeKind,
    gatewayUrl: url,
    scopes: const {'view', 'focus'},
  );
}

GatewayPairingPayload _relayPairingPayload() {
  return GatewayPairingPayload.fromJson({
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
}
