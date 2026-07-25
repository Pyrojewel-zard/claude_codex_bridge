import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('checks selected gateway route diagnostics', (tester) async {
    final secureStore = MemorySecureStore();
    final profileStore = GatewayHostProfileStore(secureStore: secureStore);
    final host = GatewayPairedHost(
      profile: GatewayHostProfile(
        hostId: 'proj-demo',
        deviceId: 'dev-cloudflare',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.cloudflareTunnel,
          gatewayUrl: Uri.parse('https://mobile.example.com'),
        ),
        scopes: const {'view', 'focus', 'terminal_input'},
      ),
      deviceToken: 'device-secret',
      projectId: 'proj-demo',
    );
    await profileStore.save(host);
    GatewayPairedHost? checkedHost;
    var diagnosticsCalls = 0;
    final diagnostics = Completer<GatewayRouteDiagnosticReport>();

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          gatewayRouteDiagnostics: (profile) async {
            diagnosticsCalls += 1;
            checkedHost = profile;
            return diagnostics.future;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    tester
        .widget<OutlinedButton>(
          find.byKey(const ValueKey('gateway-route-check-button')),
        )
        .onPressed!();
    await tester.pump();

    expect(checkedHost?.profile.deviceId, 'dev-cloudflare');
    expect(diagnosticsCalls, 1);

    expect(
      tester
          .widget<OutlinedButton>(
            find.byKey(const ValueKey('gateway-route-check-button')),
          )
          .onPressed,
      isNull,
    );
    expect(diagnosticsCalls, 1);

    diagnostics.complete(
      GatewayRouteDiagnosticReport(
        profile: host.profile,
        checkedProjectId: host.projectId,
        checks: const [
          GatewayRouteDiagnosticCheck(
            code: 'route_ready',
            ok: true,
            message: 'Route ready',
          ),
        ],
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 750));

    expect(checkedHost?.profile.deviceId, 'dev-cloudflare');
    expect(
      find.byKey(const ValueKey('gateway-route-diagnostics-status')),
      findsOneWidget,
    );
    expect(
      tester
          .widget<Text>(
            find.byKey(const ValueKey('gateway-route-diagnostics-status')),
          )
          .data,
      'Route ready',
    );
    expect(
      find.descendant(
        of: find.byType(SnackBar, skipOffstage: false),
        matching: find.text('Route ready', skipOffstage: false),
      ),
      findsAtLeastNWidgets(1),
    );
  });

  testWidgets('failed gateway route check preserves previous diagnostics', (
    tester,
  ) async {
    final secureStore = MemorySecureStore();
    final profileStore = GatewayHostProfileStore(secureStore: secureStore);
    final host = GatewayPairedHost(
      profile: GatewayHostProfile(
        hostId: 'proj-demo',
        deviceId: 'dev-cloudflare',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.cloudflareTunnel,
          gatewayUrl: Uri.parse('https://mobile.example.com'),
        ),
        scopes: const {'view', 'focus', 'terminal_input'},
      ),
      deviceToken: 'device-secret',
      projectId: 'proj-demo',
    );
    await profileStore.save(host);
    var calls = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          gatewayRouteDiagnostics: (profile) async {
            calls += 1;
            if (calls == 2) {
              throw StateError('route failed');
            }
            return GatewayRouteDiagnosticReport(
              profile: profile.profile,
              checkedProjectId: profile.projectId,
              checks: const [
                GatewayRouteDiagnosticCheck(
                  code: 'route_ready',
                  ok: true,
                  message: 'Route ready',
                ),
              ],
            );
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    await tapVisible(tester, const ValueKey('gateway-route-check-button'));

    await dismissConnectionDetails(tester);
    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    final readyStatus = tester.widget<Text>(
      find.byKey(const ValueKey('gateway-route-diagnostics-status')),
    );
    expect(readyStatus.data, 'Route ready');

    await tester.pump(const Duration(seconds: 4));
    tester
        .widget<OutlinedButton>(
          find.byKey(const ValueKey('gateway-route-check-button')),
        )
        .onPressed!();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 750));

    expect(calls, 2);
    expect(
      find.descendant(
        of: find.byType(SnackBar, skipOffstage: false),
        matching: find.text('Bad state: route failed', skipOffstage: false),
      ),
      findsAtLeastNWidgets(1),
    );
    final status = tester.widget<Text>(
      find.byKey(const ValueKey('gateway-route-diagnostics-status')),
    );
    expect(status.data, 'Route ready');
    expect(find.text('Check Route'), findsOneWidget);
  });
}
