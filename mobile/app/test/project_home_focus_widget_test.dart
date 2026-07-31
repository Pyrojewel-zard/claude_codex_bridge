import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('fake window switch filters locally without focusWindow', (
    tester,
  ) async {
    final repository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(home: ProjectHomeScreen(repository: repository)),
    );
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pumpAndSettle();

    expect(repository.focusWindowCalls, isEmpty);
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');
  });

  testWidgets('paired window switch calls focusWindow with epoch', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusWindowCalls, [('proj-demo', 'review', 4)]);
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');
  });

  testWidgets('stale view refresh cannot revert a newer agent selection', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    gatewayRepository.deferNextProjectView();
    await tester.tap(
      find.byKey(const ValueKey('agent-conversation-refresh-action')),
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pump();
    expectAgentSelected(tester, 'lead');

    await gatewayRepository.completeDeferredProjectView();
    await tester.pumpAndSettle();

    expectAgentSelected(tester, 'lead');
  });

  testWidgets('stale view refresh cannot revert a newer window focus', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    gatewayRepository.deferNextProjectView();
    await tester.tap(
      find.byKey(const ValueKey('agent-conversation-refresh-action')),
    );
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pump();
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');

    await gatewayRepository.completeDeferredProjectView();
    await tester.pumpAndSettle();

    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');
  });

  testWidgets('window selection is optimistic while focus is in flight', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    gatewayRepository.deferNextWindowFocus();
    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pump();
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');

    await tester.tap(
      find.byKey(const ValueKey('agent-conversation-refresh-action')),
    );
    await tester.pumpAndSettle();
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');

    await gatewayRepository.completeDeferredWindowFocus();
    await tester.pumpAndSettle();
    expectWindowSelected(tester, 'review');
    expectAgentSelected(tester, 'reviewer');
  });

  testWidgets('paired stale window switch does not focus or change selection', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: _payloadWithoutNamespaceEpoch(),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusWindowCalls, isEmpty);
    expectWindowSelected(tester, 'main');
    expectAgentSelected(tester, 'mobile');
    expect(find.byKey(const ValueKey('agent-reviewer')), findsNothing);
    expect(find.text('Project view is stale'), findsOneWidget);
  });

  testWidgets('paired open terminal does not focus agent before navigation', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final focusedPayload = _payloadWithProjectId('proj-focused');
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
      focusedPayload: focusedPayload,
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
    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsOneWidget);
    expect(terminalTransport.requests, hasLength(1));
    expect(terminalTransport.requests.single.target.projectId, 'proj-demo');
    expect(terminalTransport.requests.single.target.agent, 'lead');
    expect(
      terminalTransport.requests.single.target.kind,
      CcbTerminalTargetKind.agent,
    );
    expect(terminalTransport.requests.single.target.window, 'main');
    expect(terminalTransport.requests.single.target.paneId, '%1');
  });

  testWidgets('paired stale terminal open does not focus or navigate', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
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

    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsNothing);
    expect(terminalTransport.requests, isEmpty);
    expect(find.text('Project view is stale'), findsNothing);
  });

  testWidgets('fake open terminal opens without focus', (tester) async {
    final repository = _FocusWidgetRepository(
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
  });

  testWidgets('focus failure preserves previous view and shows error', (
    tester,
  ) async {
    final profileStore = await _profileStoreWithHost();
    final gatewayRepository = _FocusWidgetRepository(
      initialPayload: demoPayloadWithReviewWindow(),
      focusError: StateError('focus failed'),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository(
            projectViewPayload: demoPayloadWithReviewWindow(),
          ),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await activateStoredGatewayProfile(tester);

    await tester.tap(find.byKey(const ValueKey('window-tab-review')));
    await tester.pumpAndSettle();

    expect(gatewayRepository.focusWindowCalls, [('proj-demo', 'review', 4)]);
    expect(find.byKey(const ValueKey('agent-lead')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-mobile')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-reviewer')), findsNothing);
    expectAgentSelected(tester, 'mobile');
    expect(find.text('Bad state: focus failed'), findsOneWidget);
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

class _FocusWidgetRepository implements MobileCcbRepository {
  _FocusWidgetRepository({
    required Map<String, Object?> initialPayload,
    Map<String, Object?>? focusedPayload,
    this.focusError,
  }) : _initial = FakeMobileCcbRepository(projectViewPayload: initialPayload),
       _focused = FakeMobileCcbRepository(
         projectViewPayload: focusedPayload ?? initialPayload,
       );

  final FakeMobileCcbRepository _initial;
  final FakeMobileCcbRepository _focused;
  final Object? focusError;
  final focusAgentCalls = <(String, String, int)>[];
  final focusWindowCalls = <(String, String, int)>[];
  var _focusedOnce = false;
  Completer<CcbProjectView>? _deferredProjectView;
  Completer<CcbProjectView>? _deferredWindowFocus;

  FakeMobileCcbRepository get _current => _focusedOnce ? _focused : _initial;

  void deferNextProjectView() {
    _deferredProjectView = Completer<CcbProjectView>();
  }

  Future<void> completeDeferredProjectView() async {
    final completer = _deferredProjectView;
    if (completer == null) {
      throw StateError('No deferred project view');
    }
    final project = (await _current.listProjects()).single;
    _deferredProjectView = null;
    completer.complete(await _current.getProjectView(project.id));
  }

  void deferNextWindowFocus() {
    _deferredWindowFocus = Completer<CcbProjectView>();
  }

  Future<void> completeDeferredWindowFocus() async {
    final completer = _deferredWindowFocus;
    if (completer == null) {
      throw StateError('No deferred window focus');
    }
    _focusedOnce = true;
    _deferredWindowFocus = null;
    completer.complete(await _focusedProjectView());
  }

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
    _focusedOnce = true;
    return _focusedProjectView();
  }

  @override
  Future<CcbProjectView> focusWindow({
    required String projectId,
    required String window,
    required int namespaceEpoch,
  }) async {
    focusWindowCalls.add((projectId, window, namespaceEpoch));
    final error = focusError;
    if (error != null) {
      throw error;
    }
    final deferred = _deferredWindowFocus;
    if (deferred != null) {
      return deferred.future;
    }
    _focusedOnce = true;
    return _focusedProjectView();
  }

  Future<CcbProjectView> _focusedProjectView() async {
    final project = (await _focused.listProjects()).single;
    return _focused.getProjectView(project.id);
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) {
    final deferred = _deferredProjectView;
    if (deferred != null) {
      return deferred.future;
    }
    return _current.getProjectView(projectId);
  }

  @override
  Future<List<CcbProject>> listProjects() {
    return _current.listProjects();
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) {
    return _current.getAgentConversation(
      projectId: projectId,
      agent: agent,
      namespaceEpoch: namespaceEpoch,
      limit: limit,
      cursor: cursor,
    );
  }

  @override
  Future<ReadableTerminalHistory?> getReadableTerminalHistory({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int maxLines = 200,
  }) {
    return _current.getReadableTerminalHistory(
      projectId: projectId,
      agent: agent,
      namespaceEpoch: namespaceEpoch,
      maxLines: maxLines,
    );
  }

  @override
  Future<CcbProjectLifecycleResult> requestLifecycle({
    required String projectId,
    required CcbLifecycleAction action,
  }) {
    return _current.requestLifecycle(projectId: projectId, action: action);
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

  @override
  Future<CcbAgentMessageSubmitResult> submitAgentMessage(
    CcbAgentMessageSubmitRequest request,
  ) {
    return _current.submitAgentMessage(request);
  }
}
