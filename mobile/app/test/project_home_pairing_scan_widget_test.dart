import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  group('project home pairing scan widget flow', () {
    testWidgets('scan cancel retains a pasted connection code', (tester) async {
      var scanCalls = 0;
      var claimCalls = 0;
      final code = _lanPairing().toConnectionCode();

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
      await tester.enterText(_connectionCodeFinder, code);

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(scanCalls, 1);
      expect(claimCalls, 0);
      expect(_connectionCodeField(tester).controller?.text, code);
      expect(find.text('Gateway paired'), findsNothing);
    });

    testWidgets('scan failure retains code and shows an error', (tester) async {
      var claimCalls = 0;
      final code = _lanPairing().toConnectionCode();

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async => throw StateError('scan failed'),
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
      await tester.enterText(_connectionCodeFinder, code);

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(claimCalls, 0);
      expect(find.text('Bad state: scan failed'), findsOneWidget);
      expect(_connectionCodeField(tester).controller?.text, code);
    });

    testWidgets(
      'scan success clears pasted code before pending claim completes',
      (tester) async {
        final pendingClaim = Completer<void>();
        final qrPairing = _cloudflarePairing();
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
            await pendingClaim.future;
            final paired = _pairedHost(pairing);
            await store.save(paired);
            return paired;
          },
        );
        await _openPairingPanel(tester);
        await tester.enterText(
          _connectionCodeFinder,
          _lanPairing().toConnectionCode(),
        );

        _scanButton(tester).onPressed!();
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));

        expect(claimCalls, 1);
        expect(seenPairing, same(qrPairing));
        expect(_connectionCodeField(tester).controller?.text, isEmpty);
        expect(_scanButton(tester).onPressed, isNull);
        expect(find.text('Gateway paired'), findsNothing);

        pendingClaim.complete();
        await tester.pumpAndSettle();
        expect(find.text('Gateway paired'), findsOneWidget);
      },
    );

    testWidgets('failed Relay scan retries with the complete scanned payload', (
      tester,
    ) async {
      final qrPairing = _relayPairing();
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
          final paired = _pairedHost(pairing, routeKind: RouteProviderKind.lan);
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

    testWidgets('connection-code claim disables scanner until it completes', (
      tester,
    ) async {
      final pendingClaim = Completer<void>();
      var scanCalls = 0;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async {
          scanCalls += 1;
          return _cloudflarePairing();
        },
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          await pendingClaim.future;
          final paired = _pairedHost(pairing);
          await store.save(paired);
          return paired;
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        _connectionCodeFinder,
        _lanPairing().toConnectionCode(),
      );

      _claimButton(tester).onPressed!();
      await tester.pump();

      expect(_scanButton(tester).onPressed, isNull);
      expect(_claimButton(tester).onPressed, isNull);
      expect(scanCalls, 0);

      pendingClaim.complete();
      await tester.pumpAndSettle();
    });
  });
}

final Finder _connectionCodeFinder = find.byKey(
  const ValueKey('connection-code-field'),
);

Future<void> _pumpProjectHome(
  WidgetTester tester, {
  GatewayPairingScanner? pairingScanner,
  required GatewayPairingClaimAndStore pairingClaimAndStore,
}) async {
  final profileStore = GatewayHostProfileStore(
    secureStore: MemorySecureStore(),
  );
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

FilledButton _scanButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('project-home-onboarding-scan-button')),
  );
}

FilledButton _claimButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('gateway-pairing-claim-button')),
  );
}

TextField _connectionCodeField(WidgetTester tester) {
  return tester.widget<TextField>(_connectionCodeFinder);
}

GatewayPairingPayload _lanPairing() {
  return GatewayPairingPayload(
    pairingCode: 'lan-code',
    claimEndpoint: Uri.parse('http://gateway.local:8787/v1/pairing/claim'),
    routeProvider: RouteProviderKind.lan,
    gatewayUrl: Uri.parse('http://gateway.local:8787'),
    projectId: 'proj-demo',
    scopes: const {'view', 'notify'},
  );
}

GatewayPairingPayload _cloudflarePairing() {
  return GatewayPairingPayload(
    pairingCode: 'qr-code',
    claimEndpoint: Uri.parse('https://mobile.example.com/v1/pairing/claim'),
    routeProvider: RouteProviderKind.cloudflareTunnel,
    gatewayUrl: Uri.parse('https://mobile.example.com'),
    projectId: 'proj-demo',
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle', 'notify'},
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

GatewayPairedHost _pairedHost(
  GatewayPairingPayload pairing, {
  RouteProviderKind? routeKind,
}) {
  final effectiveRoute = routeKind ?? pairing.routeProvider;
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: pairing.projectId ?? 'proj-demo',
      deviceId: 'dev-qr',
      routeProvider: RouteProvider(
        kind: effectiveRoute,
        gatewayUrl:
            effectiveRoute == RouteProviderKind.lan
                ? Uri.parse('http://gateway.local:8787')
                : pairing.gatewayUrl,
      ),
      scopes: pairing.scopes,
    ),
    deviceToken: 'device-secret',
    projectId: pairing.projectId,
  );
}
