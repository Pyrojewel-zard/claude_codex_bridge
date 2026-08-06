import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('unpaired product home shows mobile onboarding instead of demo', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: GatewayHostProfileStore(
            secureStore: MemorySecureStore(),
          ),
          showOnboardingWhenUnpaired: true,
          autoActivateStoredProfile: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('project-home-onboarding')),
      findsOneWidget,
    );
    expect(find.text('Connect CCB Mobile'), findsOneWidget);
    expect(find.text('ccb update mobile'), findsOneWidget);
    expect(find.text('Enter connection code'), findsOneWidget);
    expect(find.text('CCB official'), findsNothing);
    expect(find.text('ccb update mobile --route-provider relay'), findsNothing);
    expect(
      find.byKey(const ValueKey('project-home-update-panel')),
      findsOneWidget,
    );
    expect(
      find.text('Current version: $ccbMobileDefaultVersion'),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('project-home-onboarding-scan-button')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('project-list')), findsNothing);
    expect(find.byKey(const ValueKey('project-open-current')), findsNothing);
    expect(find.text('demo'), findsNothing);
  });

  testWidgets('stored product profile opens server project list on launch', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'server-host', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final gatewayRepository = _ProjectListRepository([
      const CcbProject(
        id: 'test_ccb2',
        displayName: 'test_ccb2',
        root: '/srv/ccb/test_ccb2',
        health: 'healthy',
      ),
      const CcbProject(
        id: 'ccb_mobile',
        displayName: 'ccb_mobile',
        root: '/home/bfly/yunwei/ccb_mobile',
        health: 'healthy',
      ),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          showOnboardingWhenUnpaired: true,
          autoActivateStoredProfile: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(gatewayRepository.listProjectsCalls, 1);
    expect(find.byKey(const ValueKey('project-home-onboarding')), findsNothing);
    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('project-open-test_ccb2')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('project-open-ccb_mobile')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('project-open-current')), findsNothing);
    expect(find.text('demo'), findsNothing);
  });

  testWidgets('stored profile project list failure can return to setup', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'server-host', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final gatewayRepository = _ProjectListRepository(
      const [],
      listProjectsError: StateError('dns lookup failed'),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          showOnboardingWhenUnpaired: true,
          autoActivateStoredProfile: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(gatewayRepository.listProjectsCalls, 1);
    expect(
      find.byKey(const ValueKey('project-list-load-error')),
      findsOneWidget,
    );
    expect(find.textContaining('dns lookup failed'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('project-list-back-to-setup-button')),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('project-home-onboarding')),
      findsOneWidget,
    );
    expect(find.text('Connect CCB Mobile'), findsOneWidget);
    expect(find.byKey(const ValueKey('project-list-load-error')), findsNothing);
    expect(
      find.byKey(const ValueKey('project-home-onboarding-scan-button')),
      findsOneWidget,
    );
  });

  testWidgets('onboarding scan claims profile and opens server projects', (
    tester,
  ) async {
    final profileStore = GatewayHostProfileStore(
      secureStore: MemorySecureStore(),
    );
    final gatewayRepository = _ProjectListRepository([
      const CcbProject(
        id: 'test_ccb2',
        displayName: 'test_ccb2',
        root: '/srv/ccb/test_ccb2',
        health: 'healthy',
      ),
    ]);
    var scanCalls = 0;
    var claimCalls = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          pairingScanner: (context) async {
            scanCalls += 1;
            return _pairingPayload();
          },
          pairingClaimAndStore: ({
            required pairing,
            required deviceName,
            required store,
            deviceId,
          }) async {
            claimCalls += 1;
            final paired = GatewayPairedHost(
              profile: GatewayHostProfile(
                hostId: 'server-host',
                deviceId: deviceId ?? 'phone',
                routeProvider: RouteProvider(
                  kind: pairing.routeProvider,
                  gatewayUrl: pairing.gatewayUrl,
                ),
                scopes: pairing.scopes,
              ),
              deviceToken: 'token',
              projectId: 'server-host',
            );
            await store.save(paired);
            return paired;
          },
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          showOnboardingWhenUnpaired: true,
          autoActivateStoredProfile: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final scanButton = find.byKey(
      const ValueKey('project-home-onboarding-scan-button'),
    );
    await tester.ensureVisible(scanButton);
    await tester.tap(scanButton);
    await tester.pumpAndSettle();

    expect(scanCalls, 1);
    expect(claimCalls, 1);
    expect(gatewayRepository.listProjectsCalls, 1);
    expect(find.text('Gateway paired'), findsOneWidget);
    expect(find.byKey(const ValueKey('project-home-onboarding')), findsNothing);
    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('project-open-test_ccb2')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('project-open-current')), findsNothing);
  });
}

GatewayPairingPayload _pairingPayload() {
  return GatewayPairingPayload(
    pairingCode: 'qr-code',
    claimEndpoint: Uri.parse('https://desktop.tailnet.ts.net/v1/pairing/claim'),
    routeProvider: RouteProviderKind.tailnet,
    gatewayUrl: Uri.parse('https://desktop.tailnet.ts.net'),
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle', 'notify'},
  );
}

Future<GatewayHostProfileStore> _profileStoreWith(
  List<GatewayPairedHost> profiles,
) async {
  final store = GatewayHostProfileStore(secureStore: MemorySecureStore());
  for (final profile in profiles) {
    await store.save(profile);
  }
  return store;
}

GatewayPairedHost _pairedHost({
  required String hostId,
  required String deviceId,
}) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: hostId,
      deviceId: deviceId,
      routeProvider: RouteProvider(
        kind: RouteProviderKind.tailnet,
        gatewayUrl: Uri.parse('https://desktop.tailnet.ts.net'),
      ),
      scopes: const {'view', 'focus', 'terminal_input', 'lifecycle', 'notify'},
    ),
    deviceToken: 'token-$hostId-$deviceId',
    projectId: hostId,
  );
}

class _ProjectListRepository extends RecordingGatewayRepository {
  _ProjectListRepository(this.projects, {this.listProjectsError});

  final List<CcbProject> projects;
  Object? listProjectsError;
  var listProjectsCalls = 0;

  @override
  Future<List<CcbProject>> listProjects() async {
    listProjectsCalls += 1;
    final error = listProjectsError;
    if (error != null) {
      throw error;
    }
    return projects;
  }
}
