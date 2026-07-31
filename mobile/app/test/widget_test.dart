import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('connection lifecycle actions use confirmation for stop', (
    tester,
  ) async {
    final repository = RecordingGatewayRepository();
    await tester.pumpWidget(
      MaterialApp(home: ProjectHomeScreen(repository: repository)),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('project-lifecycle-panel'));
    await tapVisible(tester, const ValueKey('lifecycle-open-button'));

    expect(repository.lifecycleCalls, [('proj-demo', CcbLifecycleAction.open)]);
    expect(find.text('Lifecycle open: opened'), findsOneWidget);
    expect(find.text('running / opened / ccb / no raw tmux'), findsOneWidget);

    await tapVisible(tester, const ValueKey('lifecycle-stop-button'));
    expect(find.text('Stop project'), findsOneWidget);
    expect(repository.lifecycleCalls, [('proj-demo', CcbLifecycleAction.open)]);

    await tester.tap(
      find.byKey(const ValueKey('confirm-lifecycle-stop-button')),
    );
    await tester.pumpAndSettle();

    expect(repository.lifecycleCalls, [
      ('proj-demo', CcbLifecycleAction.open),
      ('proj-demo', CcbLifecycleAction.stop),
    ]);
    expect(find.text('Lifecycle stop: ccbd_stop_requested'), findsOneWidget);
    expect(
      find.text('stopping / ccbd_stop_requested / ccb / no raw tmux'),
      findsOneWidget,
    );
  });

  testWidgets('mobile window switcher filters agents by selected window', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    expect(find.byKey(const ValueKey('window-switcher')), findsOneWidget);
    expectWindowSelected(tester, 'main');
    expect(find.byKey(const ValueKey('agent-lead')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-mobile')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-reviewer')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pumpAndSettle();

    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');
    expect(find.byKey(const ValueKey('agent-reviewer')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-lead')), findsNothing);
    expect(find.byKey(const ValueKey('agent-mobile')), findsNothing);
  });

  testWidgets('runtime modes expose only fake and paired gateway', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(repository: FakeMobileCcbRepository.demo()),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('developer-ssh-profile-panel')),
      findsNothing,
    );

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Fake'), findsWidgets);
    expect(find.text('Paired'), findsOneWidget);
    expect(find.text('SSH'), findsNothing);
  });

  testWidgets('scans gateway QR payload and claims profile', (tester) async {
    final secureStore = MemorySecureStore();
    final profileStore = GatewayHostProfileStore(secureStore: secureStore);
    var scanCount = 0;
    late GatewayPairingPayload seenPairing;
    late String seenDeviceName;

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          pairingScanner: (context) async {
            scanCount += 1;
            return GatewayPairingPayload.fromQrText(
              jsonEncode({
                'schema_version': 1,
                'pairing_id': 'pair_qr',
                'pairing_code': 'qr-code',
                'project_id': 'proj-demo',
                'route_provider': 'cloudflare_tunnel',
                'gateway_url': 'https://mobile.example.com',
                'claim_endpoint': 'https://mobile.example.com/v1/pairing/claim',
                'scopes': [
                  'view',
                  'focus',
                  'terminal_input',
                  'lifecycle',
                  'notify',
                ],
                'expires_at': '2026-06-18T00:10:00Z',
              }),
            );
          },
          pairingClaimAndStore: ({
            required pairing,
            required deviceName,
            required store,
            deviceId,
          }) async {
            seenPairing = pairing;
            seenDeviceName = deviceName;
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
          gatewayRepositoryFactory: (profile) {
            return RecordingGatewayRepository();
          },
          gatewayTerminalTransportFactory: (profile) {
            return RecordingTerminalTransport();
          },
          showOnboardingWhenUnpaired: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    tester
        .widget<FilledButton>(
          find.byKey(const ValueKey('project-home-onboarding-scan-button')),
        )
        .onPressed!();
    await tester.pumpAndSettle();

    expect(scanCount, 1);
    expect(seenPairing.pairingCode, 'qr-code');
    expect(seenPairing.projectId, 'proj-demo');
    expect(seenPairing.routeProvider, RouteProviderKind.cloudflareTunnel);
    expect(seenPairing.scopes, {
      'view',
      'focus',
      'terminal_input',
      'lifecycle',
      'notify',
    });
    expect(seenDeviceName, 'Phone');
    final stored = await profileStore.read(
      hostId: 'proj-demo',
      deviceId: 'dev-qr',
    );
    expect(
      stored?.profile.routeProvider.kind,
      RouteProviderKind.cloudflareTunnel,
    );
    expect(stored?.deviceToken, 'device-secret');
  });

  testWidgets('claims gateway profile and opens agent/window in paired mode', (
    tester,
  ) async {
    final secureStore = MemorySecureStore();
    final profileStore = GatewayHostProfileStore(secureStore: secureStore);
    late GatewayPairingPayload seenPairing;
    late String seenDeviceName;
    late RecordingGatewayRepository gatewayRepository;
    late RecordingTerminalTransport gatewayTerminalTransport;

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          pairingClaimAndStore: ({
            required pairing,
            required deviceName,
            required store,
            deviceId,
          }) async {
            seenPairing = pairing;
            seenDeviceName = deviceName;
            final paired = GatewayPairedHost(
              profile: GatewayHostProfile(
                hostId: 'proj-demo',
                deviceId: 'dev-demo',
                routeProvider: RouteProvider(
                  kind: RouteProviderKind.lan,
                  gatewayUrl: pairing.gatewayUrl,
                ),
                scopes: const {
                  'view',
                  'content',
                  'focus',
                  'message_submit',
                  'file_upload',
                  'file_download',
                  'terminal_input',
                  'lifecycle',
                  'notify',
                },
              ),
              deviceToken: 'device-secret',
              projectId: 'proj-demo',
            );
            await store.save(paired);
            return paired;
          },
          gatewayRepositoryFactory: (profile) {
            gatewayRepository = RecordingGatewayRepository();
            gatewayRepository
                .terminalHistoryOverride = const ReadableTerminalHistory(
              agentName: 'lead',
              historyScope: 'tmux_scrollback',
              blocks: [
                ReadableTerminalBlock(
                  id: 'lead-refreshed-after-send',
                  type: 'log',
                  text: 'refreshed-history-after-send',
                ),
              ],
            );
            return gatewayRepository;
          },
          gatewayTerminalTransportFactory: (profile) {
            gatewayTerminalTransport = RecordingTerminalTransport();
            return gatewayTerminalTransport;
          },
          showOnboardingWhenUnpaired: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await expandTile(tester, const ValueKey('gateway-pairing-panel'));
    final connectionPairing = GatewayPairingPayload(
      pairingCode: 'pair-code',
      claimEndpoint: Uri.parse('http://127.0.0.1:8787/v1/pairing/claim'),
      routeProvider: RouteProviderKind.lan,
      gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
      scopes: const {
        'view',
        'content',
        'focus',
        'message_submit',
        'file_upload',
        'file_download',
        'terminal_input',
        'lifecycle',
        'notify',
      },
    );
    await tester.enterText(
      find.byKey(const ValueKey('connection-code-field')),
      connectionPairing.toConnectionCode(),
    );
    tester
        .widget<FilledButton>(
          find.byKey(const ValueKey('gateway-pairing-claim-button')),
        )
        .onPressed!();
    await tester.pumpAndSettle();

    expect(seenPairing.pairingCode, 'pair-code');
    expect(
      seenPairing.claimEndpoint.toString(),
      'http://127.0.0.1:8787/v1/pairing/claim',
    );
    expect(seenPairing.scopes, {
      'view',
      'content',
      'focus',
      'message_submit',
      'file_upload',
      'file_download',
      'terminal_input',
      'lifecycle',
      'notify',
    });
    expect(seenDeviceName, 'Phone');
    await openCurrentProject(tester);

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(
      gatewayRepository.conversationCalls,
      contains(('proj-demo', 'lead', 4)),
    );
    expect(find.byType(TerminalView), findsNothing);
    expectAgentSelected(tester, 'lead');

    await tester.enterText(
      find.byKey(const ValueKey('agent-message-composer')),
      'paired gateway chat',
    );
    await tester.pump();
    final sendButton = tester.widget<IconButton>(
      find.byKey(const ValueKey('agent-message-send-button')),
    );
    expect(sendButton.onPressed, isNotNull);
    sendButton.onPressed!();
    await tester.pumpAndSettle();

    expect(gatewayRepository.submittedMessages, isEmpty);
    expect(gatewayTerminalTransport.requests, hasLength(1));
    expect(
      gatewayTerminalTransport.requests.single.attachCommand,
      'gateway terminal stream proj-demo/lead',
    );
    expect(gatewayTerminalTransport.sessions.single.pasted, [
      'paired gateway chat',
    ]);
    expect(gatewayTerminalTransport.sessions.single.written, [
      [13],
    ]);
    expect(find.text('paired gateway chat'), findsOneWidget);
    expect(gatewayRepository.conversationCalls, isNotEmpty);

    await openConnectionDetails(tester);

    expect(find.text('Diagnostics'), findsWidgets);
    expect(find.byKey(const ValueKey('window-details-panel')), findsNothing);
    expect(gatewayRepository.focusWindowCalls, isEmpty);
  });
}
