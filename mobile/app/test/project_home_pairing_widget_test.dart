import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  group('project home pairing widget validation', () {
    testWidgets('phone onboarding exposes only QR scan and connection code', (
      tester,
    ) async {
      await _pumpProjectHome(
        tester,
        pairingClaimAndStore:
            ({
              required pairing,
              required deviceName,
              required store,
              deviceId,
            }) async => throw StateError('not claimed'),
      );

      expect(
        find.byKey(const ValueKey('project-home-onboarding-scan-button')),
        findsOneWidget,
      );
      expect(find.text('ccb update mobile'), findsOneWidget);
      await _openPairingPanel(tester);

      expect(
        find.byKey(const ValueKey('connection-code-field')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('gateway-pairing-claim-button')),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('gateway-url-field')), findsNothing);
      expect(find.byKey(const ValueKey('pairing-code-field')), findsNothing);
      expect(
        find.byKey(const ValueKey('pairing-device-name-field')),
        findsNothing,
      );
      expect(
        find.byType(DropdownButtonFormField<RouteProviderKind>),
        findsNothing,
      );
      expect(find.text('Official Relay'), findsNothing);
      expect(find.text('Self-hosted Relay'), findsNothing);
    });

    testWidgets('invalid connection code does not claim or enter loading', (
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
        find.byKey(const ValueKey('connection-code-field')),
        'ccb1_not-valid-json',
      );

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(find.text('Connection code is invalid'), findsOneWidget);
      expect(claimCalls, 0);
      expect(_claimButton(tester).onPressed, isNotNull);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('QR scan claims the complete scanned payload directly', (
      tester,
    ) async {
      final qrPairing = _cloudflarePairing();
      var scanCalls = 0;
      var claimCalls = 0;
      late GatewayPairingPayload seenPairing;
      late String seenDeviceName;

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
          seenDeviceName = deviceName;
          final paired = _pairedHost(pairing);
          await store.save(paired);
          return paired;
        },
      );

      _scanButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(scanCalls, 1);
      expect(claimCalls, 1);
      expect(seenPairing, same(qrPairing));
      expect(seenDeviceName, 'Phone');
      expect(find.text('Gateway paired'), findsOneWidget);
    });

    testWidgets(
      'failed connection-code claim retains code and stays unpaired',
      (tester) async {
        var claimCalls = 0;
        var gatewayRepositoryActivations = 0;
        final connectionCode = _lanPairing().toConnectionCode();

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
          find.byKey(const ValueKey('connection-code-field')),
          connectionCode,
        );

        _claimButton(tester).onPressed!();
        await tester.pumpAndSettle();

        expect(claimCalls, 1);
        expect(gatewayRepositoryActivations, 0);
        expect(find.text('Bad state: claim failed'), findsOneWidget);
        expect(_connectionCodeField(tester).controller?.text, connectionCode);
        expect(_claimButton(tester).onPressed, isNotNull);
        expect(find.byType(CircularProgressIndicator), findsNothing);
      },
    );

    testWidgets(
      'LAN claim warns on cellular and continues only after confirmation',
      (tester) async {
        var claimCalls = 0;
        await _pumpProjectHome(
          tester,
          mobileNetworkStatusPlatform: _FixedMobileNetworkStatusPlatform(
            const MobileNetworkStatus(
              supported: true,
              connected: true,
              wifi: false,
              ethernet: false,
              cellular: true,
              vpn: false,
            ),
          ),
          pairingClaimAndStore: ({
            required pairing,
            required deviceName,
            required store,
            deviceId,
          }) async {
            claimCalls += 1;
            final paired = _pairedHost(pairing);
            await store.save(paired);
            return paired;
          },
        );
        await _openPairingPanel(tester);
        await tester.enterText(
          find.byKey(const ValueKey('connection-code-field')),
          _lanPairing().toConnectionCode(),
        );

        _claimButton(tester).onPressed!();
        await tester.pumpAndSettle();

        expect(claimCalls, 0);
        expect(
          find.byKey(const ValueKey('lan-pairing-network-warning')),
          findsOneWidget,
        );
        expect(
          find.textContaining('Mobile data normally cannot reach'),
          findsOneWidget,
        );

        await tester.tap(
          find.byKey(const ValueKey('lan-pairing-continue-anyway')),
        );
        await tester.pumpAndSettle();

        expect(claimCalls, 1);
        expect(find.text('Gateway paired'), findsOneWidget);
      },
    );

    testWidgets('successful connection-code claim clears code and activates', (
      tester,
    ) async {
      var claimCalls = 0;
      var gatewayRepositoryActivations = 0;
      late GatewayPairingPayload seenPairing;
      late String seenDeviceName;

      await _pumpProjectHome(
        tester,
        pairingClaimAndStore: ({
          required pairing,
          required deviceName,
          required store,
          deviceId,
        }) async {
          claimCalls += 1;
          seenPairing = pairing;
          seenDeviceName = deviceName;
          final paired = _pairedHost(pairing);
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
        find.byKey(const ValueKey('connection-code-field')),
        _lanPairing().toConnectionCode(),
      );

      _claimButton(tester).onPressed!();
      await tester.pumpAndSettle();

      expect(claimCalls, 1);
      expect(gatewayRepositoryActivations, 1);
      expect(seenPairing.routeProvider, RouteProviderKind.lan);
      expect(seenDeviceName, 'Phone');
      expect(find.text('Gateway paired'), findsOneWidget);
      expect(find.byKey(const ValueKey('project-list')), findsOneWidget);

      await tester.tap(
        find.byKey(const ValueKey('project-list-settings-action')),
      );
      await tester.pumpAndSettle();
      await _openPairingPanel(tester);

      expect(_connectionCodeField(tester).controller?.text, isEmpty);
      expect(find.byKey(const ValueKey('gateway-url-field')), findsNothing);
    });
  });
}

Future<void> _pumpProjectHome(
  WidgetTester tester, {
  GatewayPairingScanner? pairingScanner,
  required GatewayPairingClaimAndStore pairingClaimAndStore,
  GatewayRepositoryFactory? gatewayRepositoryFactory,
  MobileNetworkStatusPlatform? mobileNetworkStatusPlatform,
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
        gatewayRepositoryFactory:
            gatewayRepositoryFactory ?? (_) => RecordingGatewayRepository(),
        gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        mobileNetworkStatusPlatform:
            mobileNetworkStatusPlatform ??
            const _FixedMobileNetworkStatusPlatform(
              MobileNetworkStatus.unsupported(),
            ),
        showOnboardingWhenUnpaired: true,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

class _FixedMobileNetworkStatusPlatform implements MobileNetworkStatusPlatform {
  const _FixedMobileNetworkStatusPlatform(this.status);

  final MobileNetworkStatus status;

  @override
  Future<MobileNetworkStatus> read() async => status;
}

Future<void> _openPairingPanel(WidgetTester tester) async {
  await expandTile(tester, const ValueKey('gateway-pairing-panel'));
}

FilledButton _claimButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('gateway-pairing-claim-button')),
  );
}

FilledButton _scanButton(WidgetTester tester) {
  return tester.widget<FilledButton>(
    find.byKey(const ValueKey('project-home-onboarding-scan-button')),
  );
}

TextField _connectionCodeField(WidgetTester tester) {
  return tester.widget<TextField>(
    find.byKey(const ValueKey('connection-code-field')),
  );
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

GatewayPairedHost _pairedHost(GatewayPairingPayload pairing) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: pairing.projectId ?? 'proj-demo',
      deviceId: 'dev-paired',
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
