import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('paired terminal navigation uses the selected agent pane', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _TerminalNavigationRepository(
      initialPayload: demoPayloadWithReviewWindow(),
      focusedPayload: _payloadWithProjectId('proj-focused'),
    );
    final terminalTransport = RecordingTerminalTransport();
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => terminalTransport,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('agent-workspace-mode-switch')),
      findsNothing,
    );
    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsOneWidget);
    expect(
      find.byKey(const ValueKey('ccb-live-terminal-view')),
      findsOneWidget,
    );
    expect(terminalTransport.requests, hasLength(1));
    expect(terminalTransport.requests.single.target.projectId, 'proj-demo');
    expect(terminalTransport.requests.single.target.agent, 'lead');
    expect(
      terminalTransport.requests.single.target.kind,
      CcbTerminalTargetKind.agent,
    );

    await tester.tap(find.byKey(const ValueKey('return-to-agent-chat-button')));
    await tester.pumpAndSettle();

    expect(find.byType(TerminalView), findsNothing);
    expect(
      find.byKey(const ValueKey('agent-message-composer')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('project-list-screen')), findsOneWidget);
  });

  testWidgets(
    'paired stale terminal identity does not navigate or open transport',
    (tester) async {
      final profileStore = await _profileStoreWithHost();
      final gatewayRepository = _TerminalNavigationRepository(
        initialPayload: _payloadWithoutNamespaceEpoch(),
      );
      final terminalTransport = RecordingTerminalTransport();
      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository(
              projectViewPayload: demoPayloadWithReviewWindow(),
            ),
            profileStore: profileStore,
            gatewayRepositoryFactory: (_) => gatewayRepository,
            gatewayTerminalTransportFactory: (_) => terminalTransport,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await activateStoredGatewayProfile(tester);

      await tester.tap(
        find.byKey(const ValueKey('open-agent-terminal-button')),
      );
      await tester.pumpAndSettle();

      expect(gatewayRepository.focusAgentCalls, isEmpty);
      expect(find.byType(TerminalView), findsNothing);
      expect(terminalTransport.requests, isEmpty);
      expect(find.text('Project view is stale'), findsNothing);
    },
  );

  testWidgets('paired terminal rejects a pane changed during target reread', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _TerminalNavigationRepository(
      initialPayload: demoPayloadWithReviewWindow(),
      focusedPayload: _payloadWithLeadPane('%9'),
    )..returnFocusedView = false;
    final terminalTransport = RecordingTerminalTransport();
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => terminalTransport,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();
    gatewayRepository.returnFocusedView = true;
    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(terminalTransport.requests, isEmpty);
    expect(
      find.byKey(const ValueKey('agent-terminal-target-error')),
      findsOneWidget,
    );
    expect(find.textContaining('Project view is stale'), findsOneWidget);
  });

  testWidgets('paired terminal navigation does not depend on focus success', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _TerminalNavigationRepository(
      initialPayload: demoPayloadWithReviewWindow(),
      focusError: StateError('focus failed'),
    );
    final terminalTransport = RecordingTerminalTransport();
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => terminalTransport,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsOneWidget);
    expect(terminalTransport.requests, hasLength(1));
    expect(find.text('Bad state: focus failed'), findsNothing);
  });

  testWidgets('fake terminal navigation opens without focus', (tester) async {
    final repository = _TerminalNavigationRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(home: ProjectHomeScreen(repository: repository)),
    );
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(repository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsOneWidget);
    expect(find.text('demo'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('return-to-agent-chat-button')),
      findsOneWidget,
    );

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    expect(find.byType(TerminalView), findsNothing);
    expect(find.byKey(const ValueKey('project-list-screen')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('agent-workspace-mode-switch')),
      findsNothing,
    );
  });
}

Future<GatewayHostProfileStore> _profileStoreWithHost() async {
  final store = GatewayHostProfileStore(secureStore: MemorySecureStore());
  await store.save(
    GatewayPairedHost(
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
    ),
  );
  return store;
}

Map<String, Object?> _payloadWithProjectId(String projectId) {
  final payload =
      jsonDecode(jsonEncode(demoPayloadWithReviewWindow()))
          as Map<String, Object?>;
  final view = payload['view']! as Map<String, Object?>;
  final project = view['project']! as Map<String, Object?>;
  project['id'] = projectId;
  return payload;
}

Map<String, Object?> _payloadWithoutNamespaceEpoch() {
  final payload =
      jsonDecode(jsonEncode(demoPayloadWithReviewWindow()))
          as Map<String, Object?>;
  final view = payload['view']! as Map<String, Object?>;
  final namespace = view['namespace']! as Map<String, Object?>;
  namespace.remove('epoch');
  return payload;
}

Map<String, Object?> _payloadWithLeadPane(String paneId) {
  final payload =
      jsonDecode(jsonEncode(demoPayloadWithReviewWindow()))
          as Map<String, Object?>;
  final view = payload['view']! as Map<String, Object?>;
  final agents = view['agents']! as List<Object?>;
  final lead = agents.cast<Map<String, Object?>>().firstWhere(
    (agent) => agent['name'] == 'lead',
  );
  lead['pane_id'] = paneId;
  return payload;
}

class _TerminalNavigationRepository implements MobileCcbRepository {
  _TerminalNavigationRepository({
    required Map<String, Object?> initialPayload,
    Map<String, Object?>? focusedPayload,
    this.focusError,
  }) : _initial = CcbProjectView.fromProjectViewPayload(initialPayload),
       _focused = CcbProjectView.fromProjectViewPayload(
         focusedPayload ?? initialPayload,
       );

  final CcbProjectView _initial;
  final CcbProjectView _focused;
  final Object? focusError;
  final focusAgentCalls = <(String, String, int)>[];
  bool? returnFocusedView;

  @override
  Future<CcbProjectView> focusAgent({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
  }) async {
    focusAgentCalls.add((projectId, agent, namespaceEpoch));
    final error = focusError;
    if (error != null) {
      throw error;
    }
    return _focused;
  }

  @override
  Future<CcbProjectView> focusWindow({
    required String projectId,
    required String window,
    required int namespaceEpoch,
  }) async {
    return _initial;
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) async {
    final forced = returnFocusedView;
    if (forced != null) {
      return forced ? _focused : _initial;
    }
    if (projectId == _focused.project.id) {
      return _focused;
    }
    return _initial;
  }

  @override
  Future<List<CcbProject>> listProjects() async => [_initial.project];

  @override
  Future<ReadableTerminalHistory?> getReadableTerminalHistory({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int maxLines = 200,
  }) async {
    return _initial.terminalHistoryForAgent(agent);
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) async {
    return CcbAgentConversation(
      projectId: projectId,
      agentName: agent,
      namespaceEpoch: namespaceEpoch,
      items: const [],
      generatedAt: DateTime.utc(2026, 6, 22),
    );
  }

  @override
  Future<CcbAgentMessageSubmitResult> submitAgentMessage(
    CcbAgentMessageSubmitRequest request,
  ) async {
    return CcbAgentMessageSubmitResult(
      accepted: true,
      idempotencyKey: request.idempotencyKey,
      messageId: request.idempotencyKey,
      state: CcbConversationDeliveryState.sent,
    );
  }

  @override
  Future<CcbProjectLifecycleResult> requestLifecycle({
    required String projectId,
    required CcbLifecycleAction action,
  }) async {
    return CcbProjectLifecycleResult(
      projectId: projectId,
      action: action,
      state: 'running',
      effect: 'opened',
      ccbAuthority: true,
      tmuxKillServer: false,
    );
  }

  @override
  Future<GatewayFileUploadResult> uploadFile({
    required String projectId,
    required String agentName,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<List<int>> downloadFile({
    required String projectId,
    required String agentName,
    required String fileId,
  }) async {
    throw UnimplementedError();
  }
}
