import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/project_home_connection_details_panel_host.dart';

import 'support/project_home_test_driver.dart';

void main() {
  testWidgets(
    'renders diagnostics without pairing setup and forwards actions',
    (tester) async {
      final lifecycleResult = ValueNotifier<CcbProjectLifecycleResult?>(null);
      final runningLifecycleAction = ValueNotifier<CcbLifecycleAction?>(null);
      var checkRouteCalls = 0;
      final lifecycleActions = <CcbLifecycleAction>[];

      addTearDown(lifecycleResult.dispose);
      addTearDown(runningLifecycleAction.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ListView(
              children: [
                ProjectHomeConnectionDetailsPanelHost(
                  view: CcbProjectView.fromProjectViewPayload(
                    demoProjectViewFixture,
                  ),
                  mode: AppRuntimeMode.fake,
                  profiles: const [],
                  selectedProfile: null,
                  routeDiagnostics: null,
                  lifecycleResultListenable: lifecycleResult,
                  loadingProfiles: false,
                  checkingRoute: false,
                  runningLifecycleActionListenable: runningLifecycleAction,
                  onModeChanged: (_) {},
                  onProfileSelected: (_) {},
                  onCheckRoute: () async {
                    checkRouteCalls += 1;
                    return null;
                  },
                  onLifecycleAction: lifecycleActions.add,
                ),
              ],
            ),
          ),
        ),
      );

      expect(
        find.byKey(const ValueKey('connection-details-panel')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('project-home-update-panel')),
        findsOneWidget,
      );
      expect(
        find.text('Current version: $ccbMobileDefaultVersion'),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('gateway-pairing-panel')), findsNothing);
      expect(find.byKey(const ValueKey('gateway-url-field')), findsNothing);
      expect(find.byKey(const ValueKey('runtime-mode-panel')), findsOneWidget);
      expect(
        find.byKey(const ValueKey('project-lifecycle-panel')),
        findsOneWidget,
      );

      await expandTile(tester, const ValueKey('runtime-mode-panel'));
      expect(
        find.byKey(const ValueKey('gateway-route-check-button')),
        findsNothing,
      );
      expect(checkRouteCalls, 0);

      await expandTile(tester, const ValueKey('project-lifecycle-panel'));
      final wakeButton = find.byKey(const ValueKey('lifecycle-wake-button'));
      expect(wakeButton, findsOneWidget);
      tester.widget<OutlinedButton>(wakeButton).onPressed?.call();
      await tester.pumpAndSettle();

      expect(lifecycleActions, [CcbLifecycleAction.wake]);
    },
  );

  testWidgets('shows route progress and result without reopening diagnostics', (
    tester,
  ) async {
    final lifecycleResult = ValueNotifier<CcbProjectLifecycleResult?>(null);
    final runningLifecycleAction = ValueNotifier<CcbLifecycleAction?>(null);
    final profile = GatewayPairedHost(
      profile: GatewayHostProfile(
        hostId: 'host-relay',
        deviceId: 'phone-relay',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.relay,
          gatewayUrl: Uri.parse('https://relay.example.com'),
          websocketUrl: Uri.parse('wss://relay.example.com'),
          hostFingerprint: 'sha256:relay-host',
          relayAccess: const RelayPhoneAccessCredentials(
            accessGrant: 'access-grant',
            phoneAuthPrivateKeyB64: 'phone-private-key',
          ),
        ),
        scopes: const {'view'},
      ),
      deviceToken: 'device-token',
    );
    final result = Completer<GatewayRouteDiagnosticReport>();

    addTearDown(lifecycleResult.dispose);
    addTearDown(runningLifecycleAction.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListView(
            children: [
              ProjectHomeConnectionDetailsPanelHost(
                view: CcbProjectView.fromProjectViewPayload(
                  demoProjectViewFixture,
                ),
                mode: AppRuntimeMode.pairedGateway,
                profiles: [profile],
                selectedProfile: profile,
                routeDiagnostics: null,
                lifecycleResultListenable: lifecycleResult,
                loadingProfiles: false,
                checkingRoute: false,
                runningLifecycleActionListenable: runningLifecycleAction,
                onModeChanged: (_) {},
                onProfileSelected: (_) {},
                onCheckRoute: () => result.future,
                onLifecycleAction: (_) {},
              ),
            ],
          ),
        ),
      ),
    );

    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    tester
        .widget<OutlinedButton>(
          find.byKey(const ValueKey('gateway-route-check-button')),
        )
        .onPressed!();
    await tester.pump();

    expect(find.text('Checking route'), findsOneWidget);

    result.complete(
      GatewayRouteDiagnosticReport(
        profile: profile.profile,
        checks: const [
          GatewayRouteDiagnosticCheck(
            code: 'route_ready',
            ok: true,
            message: 'Route ready',
          ),
        ],
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Route ready'), findsOneWidget);
    expect(find.text('Check Route'), findsOneWidget);
  });
}
