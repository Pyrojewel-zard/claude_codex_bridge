import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  group('project home pairing widget validation', () {
    testWidgets('manual pairing shows a route reference and fills it only on request', (
      tester,
    ) async {
      await _pumpProjectHome(
        tester,
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async => throw StateError('not claimed'),
      );
      await _openPairingPanel(tester);

      expect(
        find.text('Same private LAN only. The computer must listen on a specific private IP.'),
        findsOneWidget,
      );
      expect(find.text('http://192.168.1.20:8787'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('gateway-url-field')),
            )
            .controller
            ?.text,
        'http://127.0.0.1:8787',
      );

      await tester.tap(
        find.byKey(const ValueKey('gateway-route-use-example-button')),
      );
      await tester.pump();

      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('gateway-url-field')),
            )
            .controller
            ?.text,
        'http://192.168.1.20:8787',
      );
    });

    testWidgets('manual invalid gateway URL does not claim or enter loading', (
      tester,
    ) async {
      var claimCalls = 0;

      await _pumpProjectHome(
        tester,
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
        'not a gateway URL',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        'pair-code',
      );

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(find.text('Gateway URL is required'), findsOneWidget);
      expect(claimCalls, 0);
      expect(_claimButton(tester).onPressed, isNotNull);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('manual missing pairing code does not claim', (tester) async {
      var claimCalls = 0;

      await _pumpProjectHome(
        tester,
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
        'http://127.0.0.1:8787',
      );

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(find.text('Pairing code is required'), findsOneWidget);
      expect(claimCalls, 0);
      expect(_claimButton(tester).onPressed, isNotNull);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('QR scan payload claims even when manual fields are invalid', (
      tester,
    ) async {
      final qrPairing = GatewayPairingPayload(
        pairingCode: 'qr-code',
        claimEndpoint: Uri.parse('https://mobile.example.com/v1/pairing/claim'),
        routeProvider: RouteProviderKind.cloudflareTunnel,
        gatewayUrl: Uri.parse('https://mobile.example.com'),
        projectId: 'proj-demo',
        scopes: const {
          'view',
          'focus',
          'terminal_input',
          'lifecycle',
          'notify',
        },
      );
      var scanCalls = 0;
      var claimCalls = 0;
      late GatewayPairingPayload seenPairing;

      await _pumpProjectHome(
        tester,
        pairingScanner: (context) async {
          scanCalls += 1;
          return qrPairing;
        },
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          seenPairing = pairing;
          final paired = GatewayPairedHost(
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
      await tester.pumpAndSettle();

      expect(scanCalls, 1);
      expect(claimCalls, 1);
      expect(seenPairing, same(qrPairing));
      expect(seenPairing.projectId, 'proj-demo');
      expect(seenPairing.gatewayUrl, Uri.parse('https://mobile.example.com'));
      expect(seenPairing.routeProvider, RouteProviderKind.cloudflareTunnel);
      expect(
        seenPairing.claimEndpoint,
        Uri.parse('https://mobile.example.com/v1/pairing/claim'),
      );
      expect(seenPairing.scopes, {
        'view',
        'focus',
        'terminal_input',
        'lifecycle',
        'notify',
      });
      expect(find.text('Gateway paired'), findsOneWidget);
    });

    testWidgets(
      'manual claim failure keeps code and does not activate gateway',
      (tester) async {
        var claimCalls = 0;
        var gatewayRepositoryActivations = 0;

        await _pumpProjectHome(
          tester,
          pairingClaimAndStore: ({
            required pairing,
            required deviceName,
            required store,
            deviceId,
          }) async {
            claimCalls += 1;
            throw StateError('claim failed');
          },
          gatewayRepositoryFactory: (_) {
            gatewayRepositoryActivations += 1;
            return RecordingGatewayRepository();
          },
        );
        await _openPairingPanel(tester);
        await tester.enterText(
          find.byKey(const ValueKey('gateway-url-field')),
          'http://127.0.0.1:8787',
        );
        await tester.enterText(
          find.byKey(const ValueKey('pairing-code-field')),
          'pair-code',
        );
        await tester.enterText(
          find.byKey(const ValueKey('pairing-device-name-field')),
          'Pixel Fold',
        );

        _claimButton(tester).onPressed!();
        await tester.pumpAndSettle();

        expect(claimCalls, 1);
        expect(gatewayRepositoryActivations, 0);
        expect(find.text('Bad state: claim failed'), findsOneWidget);
        expect(find.text('Gateway paired'), findsNothing);
        expect(
          tester
              .widget<TextField>(
                find.byKey(const ValueKey('pairing-code-field')),
              )
              .controller
              ?.text,
          'pair-code',
        );
        expect(_claimButton(tester).onPressed, isNotNull);
        expect(find.byType(CircularProgressIndicator), findsNothing);
      },
    );

    testWidgets('manual claim success clears only code and activates gateway', (
      tester,
    ) async {
      var claimCalls = 0;
      var gatewayRepositoryActivations = 0;

      await _pumpProjectHome(
        tester,
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          final paired = GatewayPairedHost(
            profile: GatewayHostProfile(
              hostId: pairing.projectId ?? 'proj-demo',
              deviceId: 'dev-manual',
              routeProvider: RouteProvider(
                kind: pairing.routeProvider,
                gatewayUrl: pairing.gatewayUrl,
              ),
              scopes: pairing.scopes,
            ),
            deviceToken: 'device-secret',
            projectId: pairing.projectId,
          );
          await store.save(paired);
          return paired;
        },
        gatewayRepositoryFactory: (_) {
          gatewayRepositoryActivations += 1;
          return RecordingGatewayRepository();
        },
      );
      await _openPairingPanel(tester);
      await tester.enterText(
        find.byKey(const ValueKey('gateway-url-field')),
        'http://127.0.0.1:8787',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-code-field')),
        'pair-code',
      );
      await tester.enterText(
        find.byKey(const ValueKey('pairing-device-name-field')),
        'Pixel Fold',
      );

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(claimCalls, 1);
      expect(gatewayRepositoryActivations, 1);
      expect(find.text('Gateway paired'), findsOneWidget);
      expect(find.byKey(const ValueKey('project-list')), findsOneWidget);

      await tester.tap(
        find.byKey(const ValueKey('project-list-settings-action')),
      );
      await tester.pumpAndSettle();
      await expandTile(tester, const ValueKey('gateway-pairing-panel'));

      expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('gateway-url-field')))
            .controller
            ?.text,
        'http://127.0.0.1:8787',
      );
      expect(
        tester
            .widget<TextField>(find.byKey(const ValueKey('pairing-code-field')))
            .controller
            ?.text,
        isEmpty,
      );
      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('pairing-device-name-field')),
            )
            .controller
            ?.text,
        'Pixel Fold',
      );
    });
  });
}

Future<void> _pumpProjectHome(
  WidgetTester tester, {
  GatewayPairingScanner? pairingScanner,
  required GatewayPairingClaimAndStore pairingClaimAndStore,
  GatewayRepositoryFactory? gatewayRepositoryFactory,
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
        gatewayRepositoryFactory:
            gatewayRepositoryFactory ?? (_) => RecordingGatewayRepository(),
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

FilledButton _claimButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('gateway-pairing-claim-button')),
  );
}

OutlinedButton _scanButton(WidgetTester tester) {
  return tester.widget<OutlinedButton>(
    find.byKey(const ValueKey('gateway-pairing-scan-button')),
  );
}
