import 'package:ccb_mobile/features/project_home/project_home_pairing_request.dart';
import 'package:ccb_mobile/pairing/gateway_pairing.dart';
import 'package:ccb_mobile/transport/route_provider.dart';
import 'package:test/test.dart';

void main() {
  group('project home pairing request', () {
    test('requires one connection code when there is no scan result', () {
      expect(
        () => buildProjectHomePairingRequest(connectionCodeText: '   '),
        throwsA(
          isA<ProjectHomePairingRequestException>().having(
            (error) => error.message,
            'message',
            'Connection code is required',
          ),
        ),
      );
    });

    test('rejects an invalid connection code with a stable message', () {
      expect(
        () => buildProjectHomePairingRequest(
          connectionCodeText: 'ccb1_not-valid-json',
        ),
        throwsA(
          isA<ProjectHomePairingRequestException>().having(
            (error) => error.message,
            'message',
            'Connection code is invalid',
          ),
        ),
      );
    });

    test('builds a complete Relay request from one connection code', () {
      final pairing = _relayPairing();

      final request = buildProjectHomePairingRequest(
        connectionCodeText: pairing.toConnectionCode(),
      );

      expect(request.deviceName, projectHomePairingDefaultDeviceName);
      expect(request.pairing.pairingCode, 'relay-code');
      expect(request.pairing.routeProvider, RouteProviderKind.relay);
      expect(request.pairing.hostId, 'host-relay');
      expect(request.pairing.relayBootstrap?.sessionId, 'relay-session');
      expect(
        request.pairing.relayBootstrap?.rendezvousCapability,
        'ccb-relay-rv-v1.payload.signature',
      );
    });

    test('scan override is used without a typed connection code', () {
      final override = GatewayPairingPayload(
        pairingCode: 'qr-code',
        claimEndpoint: Uri.parse('https://mobile.example.com/pair/claim'),
        routeProvider: RouteProviderKind.cloudflareTunnel,
        gatewayUrl: Uri.parse('https://mobile.example.com/base'),
        projectId: 'proj-qr',
        expiresAt: DateTime.utc(2026, 6, 18, 0, 10),
        scopes: const {'view', 'focus', 'terminal_input'},
      );

      final request = buildProjectHomePairingRequest(
        connectionCodeText: '',
        pairingOverride: override,
      );

      expect(request.pairing, same(override));
      expect(request.deviceName, 'Phone');
    });
  });
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
