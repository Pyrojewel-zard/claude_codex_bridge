import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  group('project home pairing scan widget flow', () {
    testWidgets('scan cancel does not claim and leaves manual fields', (
      tester,
    ) async {
      var scanCalls = 0;
      var claimCalls = 0;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async {
          scanCalls += 1;
          return null;
        },
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          throw StateError('claim should not run');
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        find.byKey(const ValueKey('gateway-url-field')),
        'http://manual.example.com',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        'manual-code',
      );
      _routeKindField(tester).onChanged?.call(RouteProviderKind.relay);
      await tester.pump();

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(scanCalls, 1);
      expect(claimCalls, 0);
      expect(find.text('Gateway paired'), findsNothing);
      expect(
        _textField(
          tester,
          const ValueKey('gateway-url-field'),
        ).controller?.text,
        'http://manual.example.com',
      );
      expect(
        _textField(
          tester,
          const ValueKey('pairing-code-field'),
        ).controller?.text,
        'manual-code',
      );
      expect(_routeKindValue(tester), RouteProviderKind.relay);
    });

    testWidgets('scan failure shows error and does not claim', (tester) async {
      var scanCalls = 0;
      var claimCalls = 0;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async {
          scanCalls += 1;
          throw StateError('scan failed');
        },
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          throw StateError('claim should not run');
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        find.byKey(const ValueKey('gateway-url-field')),
        'http://manual.example.com',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        'manual-code',
      );
      _routeKindField(tester).onChanged?.call(RouteProviderKind.relay);
      await tester.pump();

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(scanCalls, 1);
      expect(claimCalls, 0);
      expect(find.text('Bad state: scan failed'), findsOneWidget);
      expect(find.text('Gateway paired'), findsNothing);
      expect(
        _textField(
          tester,
          const ValueKey('gateway-url-field'),
        ).controller?.text,
        'http://manual.example.com',
      );
      expect(
        _textField(
          tester,
          const ValueKey('pairing-code-field'),
        ).controller?.text,
        'manual-code',
      );
      expect(_routeKindValue(tester), RouteProviderKind.relay);
    });

    testWidgets('scan success updates UI before pending claim completes', (
      tester,
    ) async {
      final pendingClaim = Completer<GatewayPairedHost>();
      final qrPairing = _qrPairing();
      var claimCalls = 0;
      late GatewayPairingPayload seenPairing;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async => qrPairing,
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          seenPairing = pairing;
          final paired = _pairedHost(pairing);
          await pendingClaim.future;
          await store.save(paired);
          return paired;
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        find.byKey(const ValueKey('gateway-url-field')),
        'not a gateway URL',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        '',
      );

      _scanButton(tester).onPressed!();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(claimCalls, 1);
      expect(seenPairing, same(qrPairing));
      expect(
        _textField(
          tester,
          const ValueKey('gateway-url-field'),
        ).controller?.text,
        'https://mobile.example.com',
      );
      expect(
        _textField(
          tester,
          const ValueKey('pairing-code-field'),
        ).controller?.text,
        'qr-code',
      );
      expect(_routeKindValue(tester), RouteProviderKind.cloudflareTunnel);
      expect(find.text('Gateway paired'), findsNothing);

      pendingClaim.complete(_pairedHost(qrPairing));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Gateway paired'), findsOneWidget);
    });

    testWidgets('failed relay scan claim retries with complete QR payload', (
      tester,
    ) async {
      final qrPairing = _relayQrPairing();
      final seenPairings = <GatewayPairingPayload>[];

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async => qrPairing,
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          seenPairings.add(pairing);
          if (seenPairings.length == 1) {
            throw StateError('temporary relay failure');
          }
          final paired = _pairedHost(pairing);
          await store.save(paired);
          return paired;
        },
      );
      await _openPairingPanel(tester);

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(seenPairings, hasLength(1));
      expect(find.text('Bad state: temporary relay failure'), findsOneWidget);

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(seenPairings, hasLength(2));
      expect(seenPairings[0], same(qrPairing));
      expect(seenPairings[1], same(qrPairing));
      expect(seenPairings[1].relayBootstrap?.sessionId, 'relay-session');
      expect(find.text('Gateway paired'), findsOneWidget);
    });

    testWidgets('claiming scan path does not call scanner', (tester) async {
      final pendingClaim = Completer<GatewayPairedHost>();
      var scanCalls = 0;
      var claimCalls = 0;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async {
          scanCalls += 1;
          return _qrPairing();
        },
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          final paired = _pairedHost(pairing);
          await pendingClaim.future;
          await store.save(paired);
          return paired;
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        find.byKey(const ValueKey('gateway-url-field')),
        'http://127.0.0.1:8787',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        'manual-code',
      );

      _claimButton(tester).onPressed!();
      await tester.pump();

      expect(claimCalls, 1);
      expect(_scanButton(tester).onPressed, isNull);

      expect(scanCalls, 0);
      expect(find.text('Gateway paired'), findsNothing);
      expect(
        _textField(
          tester,
          const ValueKey('gateway-url-field'),
        ).controller?.text,
        'http://127.0.0.1:8787',
      );
      expect(
        _textField(
          tester,
          const ValueKey('pairing-code-field'),
        ).controller?.text,
        'manual-code',
      );

      pendingClaim.complete(_pairedHost(_qrPairing()));
      await tester.pumpAndSettle();
    });
  });
}

GatewayPairingPayload _relayQrPairing() {
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

Future<void> _pumpProjectHome(
  WidgetTester tester, {
  GatewayPairingScanner? pairingScanner,
  required GatewayPairingClaimAndStore pairingClaimAndStore,
}) async {
  final secureStore = MemorySecureStore();
  final profileStore = GatewayHostProfileStore(secureStore: secureStore);
  await tester.pumpWidget(
    MaterialApp(
      home: ProjectHomeScreen(
        repository: FakeMobileCcbRepository.demo(),
        profileStore: profileStore,
        pairingScanner: pairingScanner ?? (_) async => null,
        pairingClaimAndStore: pairingClaimAndStore,
        gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
        gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        showOnboardingWhenUnpaired: true,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _openPairingPanel(WidgetTester tester) async {
  await expandTile(tester, const ValueKey('gateway-pairing-panel'));
}

OutlinedButton _scanButton(WidgetTester tester) {
  return tester.widget<OutlinedButton>(
    find.byKey(const ValueKey('gateway-pairing-scan-button')),
  );
}

FilledButton _claimButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('gateway-pairing-claim-button')),
  );
}

TextField _textField(WidgetTester tester, ValueKey<String> key) {
  return tester.widget<TextField>(find.byKey(key));
}

DropdownButtonFormField<RouteProviderKind> _routeKindField(
  WidgetTester tester,
) {
  return tester.widget<DropdownButtonFormField<RouteProviderKind>>(
    find.byType(DropdownButtonFormField<RouteProviderKind>),
  );
}

RouteProviderKind? _routeKindValue(WidgetTester tester) {
  return tester
      .state<FormFieldState<RouteProviderKind>>(
        find.byType(DropdownButtonFormField<RouteProviderKind>),
      )
      .value;
}

GatewayPairingPayload _qrPairing() {
  return GatewayPairingPayload(
    pairingCode: 'qr-code',
    claimEndpoint: Uri.parse('https://mobile.example.com/v1/pairing/claim'),
    routeProvider: RouteProviderKind.cloudflareTunnel,
    gatewayUrl: Uri.parse('https://mobile.example.com'),
    projectId: 'proj-demo',
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle', 'notify'},
  );
}

GatewayPairedHost _pairedHost(GatewayPairingPayload pairing) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: pairing.projectId ?? 'proj-demo',
      deviceId: 'dev-qr',
      routeProvider: RouteProvider(
        kind: pairing.routeProvider,
        gatewayUrl: pairing.gatewayUrl,
      ),
      scopes: pairing.scopes,
    ),
    deviceToken: 'device-secret',
    projectId: pairing.projectId,
  );
}
