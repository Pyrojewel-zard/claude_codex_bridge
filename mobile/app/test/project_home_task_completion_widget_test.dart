import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets(
    'missing notify scope shows re-pair prompt and does not subscribe',
    (tester) async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final localNotifications = _FakeTaskCompletionLocalNotifications();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications: localNotifications,
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.text(taskCompletionMissingNotifyScopeMessage),
        findsOneWidget,
      );
      expect(localNotifications.permissionRequests, 0);
      expect(streamClient.subscribeCalls, 0);
    },
  );

  testWidgets('notification tap opens target project agent when present', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(streamClient.subscribeCalls, 1);
    expect(localNotifications.permissionRequests, 1);
    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);

    localNotifications.addTap(
      const TaskCompletionNotificationTap(
        projectId: 'proj-demo',
        agent: 'mobile',
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsOneWidget,
    );
  });

  testWidgets(
    'notification stream stops in background and resumes once in foreground',
    (tester) async {
      final streamClient = _LifecycleTaskCompletionStreamClient();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications:
                _FakeTaskCompletionLocalNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(streamClient.subscribeCalls, 1);
      expect(streamClient.hasListener, isTrue);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(streamClient.hasListener, isFalse);
      await tester.pump(const Duration(seconds: 2));
      expect(streamClient.subscribeCalls, 1);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await _pumpUntilLifecycleSubscribed(tester, streamClient, 2);

      expect(streamClient.subscribeCalls, 2);
      expect(streamClient.hasListener, isTrue);
    },
  );

  testWidgets(
    'opt-in background connection keeps one notification stream alive',
    (tester) async {
      final streamClient = _LifecycleTaskCompletionStreamClient();
      final backgroundConnection = _RecordingBackgroundConnectionPlatform();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            backgroundConnectionEnabled: true,
            backgroundConnectionPlatform: backgroundConnection,
            gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications:
                _FakeTaskCompletionLocalNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(backgroundConnection.startCalls, 1);
      expect(backgroundConnection.running, isTrue);
      expect(streamClient.subscribeCalls, 1);
      expect(streamClient.hasListener, isTrue);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      await tester.pump(const Duration(seconds: 2));

      expect(streamClient.hasListener, isTrue);
      expect(streamClient.subscribeCalls, 1);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(streamClient.hasListener, isTrue);
      expect(streamClient.subscribeCalls, 1);

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(backgroundConnection.stopCalls, 1);
    },
  );

  testWidgets(
    'opt-in background connection starts while the paired route reconnects',
    (tester) async {
      final backgroundConnection = _RecordingBackgroundConnectionPlatform();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            backgroundConnectionEnabled: true,
            backgroundConnectionPlatform: backgroundConnection,
            gatewayRepositoryFactory:
                (_) => _UnavailableProjectListRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient:
                _LifecycleTaskCompletionStreamClient(),
            taskCompletionLocalNotifications:
                _FakeTaskCompletionLocalNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(backgroundConnection.startCalls, 1);
      expect(backgroundConnection.running, isTrue);
    },
  );

  testWidgets(
    'notification stream retry does not reflow or disable the active chat',
    (tester) async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications:
                _FakeTaskCompletionLocalNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await _pumpUntilSubscribed(tester, streamClient);
      await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
      await tester.pumpAndSettle();

      final workspace = find.byKey(const ValueKey('selected-agent-workspace'));
      final topBefore = tester.getTopLeft(workspace).dy;
      streamClient.addError(StateError('temporary notification disconnect'));
      await tester.pump();
      await tester.pump();

      expect(
        find.byKey(const ValueKey('gateway-reconnecting-banner')),
        findsNothing,
      );
      expect(tester.getTopLeft(workspace).dy, topBefore);
      final sendButton = tester.widget<IconButton>(
        find.byKey(const ValueKey('agent-message-send-button')),
      );
      expect(sendButton.onPressed, isNotNull);
    },
  );

  testWidgets(
    'retained old completion does not notify or mark project unread',
    (tester) async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final localNotifications = _FakeTaskCompletionLocalNotifications();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications: localNotifications,
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await _pumpUntilSubscribed(tester, streamClient);

      streamClient.add(
        _completionEvent(
          dedupeKey: 'old-lead',
          agent: 'lead',
          completedAt: DateTime.utc(2020),
        ),
      );
      await _pumpNotificationEvent(tester);

      expect(localNotifications.shown, isEmpty);
      expect(
        find.byKey(const ValueKey('project-unread-star-proj-demo')),
        findsNothing,
      );
    },
  );

  testWidgets('live completion marks project unread and shows notification', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _pumpUntilSubscribed(tester, streamClient);

    streamClient.add(_completionEvent(dedupeKey: 'live-lead', agent: 'lead'));
    await _pumpNotificationEvent(tester);

    expect(streamClient.delivered.map((event) => event.dedupeKey), [
      'live-lead',
    ]);
    expect(localNotifications.shown.map((event) => event.dedupeKey), [
      'live-lead',
    ]);
    expect(
      find.byKey(const ValueKey('project-unread-star-proj-demo')),
      findsOneWidget,
    );
  });

  testWidgets('resync invalidation refreshes the server project list', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final repository = _ResyncRecordingGatewayRepository();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => repository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _pumpUntilSubscribed(tester, streamClient);
    final callsBefore = repository.listProjectsCalls;

    streamClient.add(
      _invalidationEvent(
        kind: TaskCompletionNotificationEvent.resyncRequiredKind,
      ),
    );
    await _pumpNotificationEvent(tester);
    await tester.idle();
    await tester.pump();
    await tester.idle();
    await tester.pump();

    expect(repository.listProjectsCalls, greaterThan(callsBefore));
    expect(localNotifications.shown, isEmpty);
  });

  testWidgets('resync invalidation refreshes the active project view', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final repository = _ResyncRecordingGatewayRepository();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => repository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _pumpUntilSubscribed(tester, streamClient);
    await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
    await tester.pumpAndSettle();
    await _pumpUntilSubscribeCalls(tester, streamClient, 2);
    final callsBefore = repository.getProjectViewCalls;

    streamClient.add(
      _invalidationEvent(
        kind: TaskCompletionNotificationEvent.resyncRequiredKind,
      ),
    );
    await _pumpNotificationEvent(tester);

    expect(repository.getProjectViewCalls, greaterThan(callsBefore));
    expect(localNotifications.shown, isEmpty);
  });

  testWidgets(
    'agent activity invalidation settles the visible working agent to idle',
    (tester) async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final repository = _ActivityTransitionGatewayRepository();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => repository,
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications:
                _FakeTaskCompletionLocalNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
      await tester.pumpAndSettle();
      await _pumpUntilSubscribeCalls(tester, streamClient, 2);

      expect(find.text('Working...'), findsOneWidget);
      final callsBefore = repository.getProjectViewCalls;
      streamClient.add(
        _invalidationEvent(
          kind: TaskCompletionNotificationEvent.agentActivityChangedKind,
          projectId: 'proj-demo',
          agent: 'mobile',
          activityState: 'idle',
        ),
      );
      await _pumpNotificationEvent(tester);

      expect(repository.getProjectViewCalls, greaterThan(callsBefore));
      expect(repository.idle, isFalse);
      expect(find.text('Working...'), findsNothing);
    },
  );

  testWidgets('visible target completion is consumed without notification', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
    await tester.pumpAndSettle();

    streamClient.add(
      _completionEvent(dedupeKey: 'visible-mobile', agent: 'mobile'),
    );
    await _pumpNotificationEvent(tester);

    expect(localNotifications.shown, isEmpty);
    expect(
      find.byKey(const ValueKey('agent-unread-star-mobile')),
      findsNothing,
    );
  });

  testWidgets('unread agent marker clears when target agent is selected', (
    tester,
  ) async {
    final streamClient = _FakeTaskCompletionStreamClient();
    final localNotifications = _FakeTaskCompletionLocalNotifications();
    final profileStore = await _profileStoreWith([
      _pairedHost(scopes: const {'view', 'focus', 'notify'}),
    ]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: FakeMobileCcbRepository.demo(),
          profileStore: profileStore,
          autoActivateStoredProfile: true,
          gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
          taskNotificationStreamClient: streamClient,
          taskCompletionLocalNotifications: localNotifications,
          taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          taskCompletionUnreadStore: TaskCompletionUnreadStore(
            secureStore: MemorySecureStore(),
          ),
          invalidationCursorStore: _cursorStore(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _pumpUntilSubscribed(tester, streamClient);
    await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
    await tester.pumpAndSettle();
    await _pumpUntilSubscribed(tester, streamClient);

    streamClient.add(_completionEvent(dedupeKey: 'lead-unread', agent: 'lead'));
    await _pumpNotificationEvent(tester);

    expect(streamClient.delivered.map((event) => event.dedupeKey), [
      'lead-unread',
    ]);
    expect(localNotifications.shown.map((event) => event.dedupeKey), [
      'lead-unread',
    ]);
    expect(
      find.byKey(const ValueKey('agent-unread-star-lead')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-unread-star-lead')), findsNothing);
  });

  testWidgets(
    'default selected agent unread marker clears when project opens',
    (tester) async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final localNotifications = _FakeTaskCompletionLocalNotifications();
      final profileStore = await _profileStoreWith([
        _pairedHost(scopes: const {'view', 'focus', 'notify'}),
      ]);

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications: localNotifications,
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: _cursorStore(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await _pumpUntilSubscribed(tester, streamClient);

      streamClient.add(
        _completionEvent(dedupeKey: 'mobile-unread', agent: 'mobile'),
      );
      await _pumpNotificationEvent(tester);

      expect(
        find.byKey(const ValueKey('project-unread-star-proj-demo')),
        findsOneWidget,
      );

      await tester.tap(find.byKey(const ValueKey('project-open-proj-demo')));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('agent-unread-star-mobile')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('project-unread-star-proj-demo')),
        findsNothing,
      );
    },
  );
}

Future<void> _pumpNotificationEvent(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
  await tester.pumpAndSettle();
}

GatewayInvalidationCursorStore _cursorStore() =>
    GatewayInvalidationCursorStore(secureStore: MemorySecureStore());

Future<void> _pumpUntilSubscribed(
  WidgetTester tester,
  _FakeTaskCompletionStreamClient streamClient,
) async {
  for (
    var attempt = 0;
    attempt < 8 && !streamClient.hasListener;
    attempt += 1
  ) {
    await tester.pump();
  }
  expect(streamClient.subscribeCalls, greaterThan(0));
  expect(streamClient.hasListener, isTrue);
}

Future<void> _pumpUntilSubscribeCalls(
  WidgetTester tester,
  _FakeTaskCompletionStreamClient streamClient,
  int count,
) async {
  for (
    var attempt = 0;
    attempt < 50 && streamClient.subscribeCalls < count;
    attempt += 1
  ) {
    await tester.idle();
    await tester.pump(const Duration(milliseconds: 1));
  }
  expect(streamClient.subscribeCalls, greaterThanOrEqualTo(count));
  expect(streamClient.hasListener, isTrue);
}

Future<void> _pumpUntilLifecycleSubscribed(
  WidgetTester tester,
  _LifecycleTaskCompletionStreamClient streamClient,
  int count,
) async {
  for (
    var attempt = 0;
    attempt < 50 && streamClient.subscribeCalls < count;
    attempt += 1
  ) {
    await tester.idle();
    await tester.pump(const Duration(milliseconds: 1));
  }
  expect(streamClient.subscribeCalls, greaterThanOrEqualTo(count));
  expect(streamClient.hasListener, isTrue);
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

GatewayPairedHost _pairedHost({required Set<String> scopes}) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: 'proj-demo',
      deviceId: 'phone',
      routeProvider: RouteProvider(
        kind: RouteProviderKind.lan,
        gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
      ),
      scopes: scopes,
    ),
    deviceToken: 'token-proj-demo-phone',
    projectId: 'proj-demo',
  );
}

class _FakeTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  final _controller =
      StreamController<TaskCompletionNotificationEvent>.broadcast();
  var subscribeCalls = 0;
  final delivered = <TaskCompletionNotificationEvent>[];
  bool get hasListener => _controller.hasListener;

  void add(TaskCompletionNotificationEvent event) {
    _controller.add(event);
  }

  void addError(Object error) {
    _controller.addError(error);
  }

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    subscribeCalls += 1;
    return _ImmediateCancelStream(
      _controller.stream.map((event) {
        delivered.add(event);
        return event;
      }),
    );
  }
}

class _LifecycleTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  final _controller =
      StreamController<TaskCompletionNotificationEvent>.broadcast(sync: true);
  var subscribeCalls = 0;
  bool get hasListener => _controller.hasListener;

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    subscribeCalls += 1;
    return _ImmediateCancelStream(_controller.stream);
  }
}

class _RecordingBackgroundConnectionPlatform
    implements BackgroundConnectionPlatform {
  var startCalls = 0;
  var stopCalls = 0;
  var running = false;

  @override
  Future<bool> start() async {
    startCalls += 1;
    running = true;
    return true;
  }

  @override
  Future<void> stop() async {
    stopCalls += 1;
    running = false;
  }

  @override
  Future<BackgroundConnectionSystemStatus> readSystemStatus() async {
    return const BackgroundConnectionSystemStatus(
      backgroundRestricted: false,
      batteryOptimizationExempt: true,
      lowPowerStandbyRestricted: false,
    );
  }

  @override
  Future<bool> openSystemSettings() async => true;
}

class _UnavailableProjectListRepository extends RecordingGatewayRepository {
  @override
  Future<List<CcbProject>> listProjects() {
    return Future<List<CcbProject>>.error(
      TimeoutException('paired route is reconnecting'),
    );
  }
}

class _ImmediateCancelStream extends Stream<TaskCompletionNotificationEvent> {
  _ImmediateCancelStream(this._delegate);

  final Stream<TaskCompletionNotificationEvent> _delegate;

  @override
  StreamSubscription<TaskCompletionNotificationEvent> listen(
    void Function(TaskCompletionNotificationEvent event)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) => _ImmediateCancelSubscription(
    _delegate.listen(
      onData,
      onError: onError,
      onDone: onDone,
      cancelOnError: cancelOnError,
    ),
  );
}

class _ImmediateCancelSubscription
    implements StreamSubscription<TaskCompletionNotificationEvent> {
  _ImmediateCancelSubscription(this._delegate);

  final StreamSubscription<TaskCompletionNotificationEvent> _delegate;

  @override
  Future<void> cancel() {
    unawaited(_delegate.cancel());
    return SynchronousFuture<void>(null);
  }

  @override
  void onData(void Function(TaskCompletionNotificationEvent data)? handleData) {
    _delegate.onData(handleData);
  }

  @override
  void onError(Function? handleError) => _delegate.onError(handleError);

  @override
  void onDone(void Function()? handleDone) => _delegate.onDone(handleDone);

  @override
  void pause([Future<void>? resumeSignal]) => _delegate.pause(resumeSignal);

  @override
  void resume() => _delegate.resume();

  @override
  bool get isPaused => _delegate.isPaused;

  @override
  Future<E> asFuture<E>([E? futureValue]) => _delegate.asFuture(futureValue);
}

class _FakeTaskCompletionLocalNotifications
    implements TaskCompletionLocalNotifications {
  final _taps = StreamController<TaskCompletionNotificationTap>.broadcast();
  final shown = <TaskCompletionNotificationEvent>[];
  var permissionRequests = 0;

  void addTap(TaskCompletionNotificationTap tap) {
    _taps.add(tap);
  }

  @override
  Stream<TaskCompletionNotificationTap> get taps => _taps.stream;

  @override
  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded() async {
    permissionRequests += 1;
    return TaskCompletionLocalNotificationPermissionStatus.granted;
  }

  @override
  Future<bool> showTaskCompletion(TaskCompletionNotificationEvent event) async {
    shown.add(event);
    return true;
  }
}

class _ResyncRecordingGatewayRepository extends RecordingGatewayRepository {
  var listProjectsCalls = 0;
  var getProjectViewCalls = 0;

  @override
  Future<List<CcbProject>> listProjects() {
    listProjectsCalls += 1;
    return super.listProjects();
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) {
    getProjectViewCalls += 1;
    return super.getProjectView(projectId);
  }
}

class _ActivityTransitionGatewayRepository extends RecordingGatewayRepository {
  var getProjectViewCalls = 0;
  var idle = false;

  @override
  Future<CcbProjectView> getProjectView(String projectId) async {
    getProjectViewCalls += 1;
    final payload =
        jsonDecode(jsonEncode(demoPayloadWithEpoch(4))) as Map<String, Object?>;
    final view = payload['view']! as Map<String, Object?>;
    final agents = view['agents']! as List<Object?>;
    final mobile = agents
        .map((item) => item! as Map<String, Object?>)
        .firstWhere((agent) => agent['name'] == 'mobile');
    mobile['activity_state'] = idle ? 'idle' : 'active';
    mobile['activity_source'] = 'claude_runtime';
    mobile['activity_reason'] =
        idle ? 'claude_pane_idle_prompt' : 'claude_pane_tool_running';
    return CcbProjectView.fromProjectViewPayload(payload);
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) async {
    conversationCalls.add((projectId, agent, namespaceEpoch));
    return CcbAgentConversation(
      projectId: projectId,
      agentName: agent,
      namespaceEpoch: namespaceEpoch,
      items: const [],
      generatedAt: DateTime.utc(2026, 7, 28),
    );
  }
}

TaskCompletionNotificationEvent _completionEvent({
  required String dedupeKey,
  required String agent,
  DateTime? completedAt,
}) {
  return TaskCompletionNotificationEvent(
    id: 'event-$dedupeKey',
    kind: TaskCompletionNotificationEvent.taskCompletedKind,
    projectId: 'proj-demo',
    projectShortName: 'demo',
    agent: agent,
    completedAt: completedAt ?? DateTime.utc(2099),
    dedupeKey: dedupeKey,
  );
}

TaskCompletionNotificationEvent _invalidationEvent({
  required String kind,
  String projectId = '',
  String agent = '',
  String? activityState,
}) {
  return TaskCompletionNotificationEvent(
    id: 'event-$kind',
    kind: kind,
    projectId: projectId,
    projectShortName: '',
    agent: agent,
    completedAt: DateTime.utc(2099),
    dedupeKey: 'invalidation:$kind',
    activityState: activityState,
  );
}
