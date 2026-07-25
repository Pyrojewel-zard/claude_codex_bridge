import 'package:ccb_mobile/features/project_home/project_home_pairing_form_controller.dart';
import 'package:ccb_mobile/features/project_home/project_home_pairing_request.dart';
import 'package:ccb_mobile/pairing/gateway_pairing.dart';
import 'package:ccb_mobile/transport/route_provider.dart';
import 'package:test/test.dart';

void main() {
  test('defaults expose only an empty connection code', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);

    expect(controller.connectionCodeController.text, isEmpty);
  });

  test('typed connection code owns route and defaults device name', () {
    final pairing = _relayPairing();
    final controller = ProjectHomePairingFormController(
      connectionCodeText: pairing.toConnectionCode(),
    );
    addTearDown(controller.dispose);

    final request = controller.buildRequest();

    expect(request.deviceName, projectHomePairingDefaultDeviceName);
    expect(request.pairing.routeProvider, RouteProviderKind.relay);
    expect(request.pairing.relayBootstrap?.sessionId, 'relay-session');
  });

  test('scanned payload is retained for retry after a failed claim', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    final pairing = _relayPairing();

    controller.applyScannedPairing(pairing);
    final request = controller.buildRequest();

    expect(controller.connectionCodeController.text, isEmpty);
    expect(request.pairing, same(pairing));
    expect(request.pairing.relayBootstrap?.sessionId, 'relay-session');
  });

  test('typed code replaces a retained scanned payload', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.applyScannedPairing(_relayPairing());
    final typed = _lanPairing();
    controller.connectionCodeController.text = typed.toConnectionCode();

    final request = controller.buildRequest();

    expect(request.pairing.pairingCode, 'lan-code');
    expect(request.pairing.routeProvider, RouteProviderKind.lan);
    expect(request.pairing.relayBootstrap, isNull);
  });

  test('explicit scan override wins during the immediate scan claim', () {
    final controller = ProjectHomePairingFormController(
      connectionCodeText: _lanPairing().toConnectionCode(),
    );
    addTearDown(controller.dispose);
    final scanned = _relayPairing();

    final request = controller.buildRequest(pairingOverride: scanned);

    expect(request.pairing, same(scanned));
  });

  test('clearing pairing removes typed and retained scan state', () {
    final controller = ProjectHomePairingFormController();
    addTearDown(controller.dispose);
    controller.applyScannedPairing(_relayPairing());
    controller.connectionCodeController.text = _lanPairing().toConnectionCode();

    controller.clearPairingCode();

    expect(controller.connectionCodeController.text, isEmpty);
    expect(
      controller.buildRequest,
      throwsA(isA<ProjectHomePairingRequestException>()),
    );
  });
}

GatewayPairingPayload _lanPairing() {
  return GatewayPairingPayload(
    pairingCode: 'lan-code',
    claimEndpoint: Uri.parse('http://gateway.local:8787/v1/pairing/claim'),
    routeProvider: RouteProviderKind.lan,
    gatewayUrl: Uri.parse('http://gateway.local:8787'),
    scopes: const {'view', 'notify'},
  );
}

GatewayPairingPayload _relayPairing() {
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
