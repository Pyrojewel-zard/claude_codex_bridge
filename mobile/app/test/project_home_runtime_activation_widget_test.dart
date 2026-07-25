import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';
import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('paired no-profile shows snack and does not call factories', (
    tester,
  ) async {
    var repositoryFactoryCalls = 0;
    var terminalFactoryCalls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: GatewayHostProfileStore(
            secureStore: MemorySecureStore(),
          ),
          gatewayRepositoryFactory: (_) {
            repositoryFactoryCalls += 1;
            return RecordingGatewayRepository();
          },
          gatewayTerminalTransportFactory: (_) {
            terminalFactoryCalls += 1;
            return RecordingTerminalTransport();
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();

    expect(find.text('Pair a gateway profile first'), findsOneWidget);
    expect(repositoryFactoryCalls, 0);
    expect(terminalFactoryCalls, 0);
    expect(find.byKey(const ValueKey('runtime-mode-status')), findsOneWidget);
    expect(find.text('Fake'), findsWidgets);
  });

  testWidgets('profile load failure clears loading state', (tester) async {
    var repositoryFactoryCalls = 0;
    var terminalFactoryCalls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: _FailingProfileStore(),
          gatewayRepositoryFactory: (_) {
            repositoryFactoryCalls += 1;
            return RecordingGatewayRepository();
          },
          gatewayTerminalTransportFactory: (_) {
            terminalFactoryCalls += 1;
            return RecordingTerminalTransport();
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(_profileValue(tester), isNull);
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();

    expect(find.text('Pair a gateway profile first'), findsOneWidget);
    expect(repositoryFactoryCalls, 0);
    expect(terminalFactoryCalls, 0);
  });

  testWidgets('stored profile activation calls factories with same profile', (
    tester,
  ) async {
    final profile = _pairedHost(
      hostId: 'proj-demo',
      deviceId: 'phone',
      routeKind: RouteProviderKind.cloudflareTunnel,
    );
    final profileStore = await _profileStoreWith([profile]);
    final seenRepositoryProfiles = <GatewayPairedHost>[];
    final seenTerminalProfiles = <GatewayPairedHost>[];

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (profile) {
            seenRepositoryProfiles.add(profile);
            return RecordingGatewayRepository();
          },
          gatewayTerminalTransportFactory: (profile) {
            seenTerminalProfiles.add(profile);
            return RecordingTerminalTransport();
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    final loadedProfile = _profileValue(tester)!;
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();

    expect(loadedProfile.profile.hostId, profile.profile.hostId);
    expect(loadedProfile.profile.deviceId, profile.profile.deviceId);
    expect(seenRepositoryProfiles, [same(loadedProfile)]);
    expect(seenTerminalProfiles, [same(loadedProfile)]);
    expect(find.text('Pair a gateway profile first'), findsNothing);
  });

  testWidgets(
    'temporary activation failure preserves the token and Retry verifies it again',
    (tester) async {
      final successful = _pairedHost(hostId: 'proj-demo', deviceId: 'phone');
      final recovering = _pairedHost(
        hostId: 'proj-demo',
        deviceId: 'tablet',
        gatewayUrl: Uri.parse('https://recovering.example.test'),
      );
      final profileStore = await _profileStoreWith([successful, recovering]);
      await profileStore.markSuccessful(successful);
      final recoveringRepository =
          _HealthCheckedGatewayRepository()
            ..healthError = TimeoutException('gateway warming');
      final factoryProfiles = <GatewayPairedHost>[];

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: RecordingGatewayRepository(),
            profileStore: profileStore,
            gatewayRepositoryFactory: (profile) {
              factoryProfiles.add(profile);
              return profile.profile.deviceId == recovering.profile.deviceId
                  ? recoveringRepository
                  : _HealthCheckedGatewayRepository();
            },
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await openConnectionDetails(tester);
      await expandTile(tester, const ValueKey('runtime-mode-panel'));
      _runtimeSegments(
        tester,
      ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<GatewayPairedHost>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('proj-demo / tablet / lan').last);
      await tester.pumpAndSettle();
      await dismissConnectionDetails(tester);

      expect(
        find.byKey(const ValueKey('project-list-load-error')),
        findsOneWidget,
      );
      expect(
        (await profileStore.read(
          hostId: 'proj-demo',
          deviceId: 'tablet',
        ))?.deviceToken,
        recovering.deviceToken,
      );
      expect(
        (await profileStore.resolvePreferred(
          await profileStore.list(),
        ))?.profile.deviceId,
        'phone',
      );

      recoveringRepository.healthError = null;
      await tester.tap(find.byKey(const ValueKey('project-list-retry-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
      expect(
        factoryProfiles
            .where(
              (profile) =>
                  profile.profile.deviceId == recovering.profile.deviceId,
            )
            .map((profile) => profile.deviceToken),
        [recovering.deviceToken, recovering.deviceToken],
      );
      expect(
        (await profileStore.resolvePreferred(
          await profileStore.list(),
        ))?.profile.deviceId,
        'tablet',
      );
    },
  );

  testWidgets('revoked profile fails closed and directs the user to Re-pair', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'proj-demo', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final repository = _HealthCheckedGatewayRepository()..revoked = true;

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => repository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();
    await dismissConnectionDetails(tester);

    expect(
      find.byKey(const ValueKey('project-list-repair-button')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('project-list-retry-button')),
      findsNothing,
    );
    expect(find.text('Re-pair'), findsOneWidget);
    expect(
      await profileStore.read(hostId: 'proj-demo', deviceId: 'phone'),
      isNull,
    );

    await tester.tap(find.byKey(const ValueKey('project-list-repair-button')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('project-home-onboarding')),
      findsOneWidget,
    );
  });

  testWidgets('403 scope denial keeps profile and offers Retry', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'proj-demo', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final repository =
        _HealthCheckedGatewayRepository()
          ..deviceError = GatewayHttpException(
            Uri.parse('http://proj-demo.local:8787/v1/devices/me'),
            403,
            'scope denied',
          );

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => repository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();
    await dismissConnectionDetails(tester);

    expect(find.byKey(const ValueKey('project-list-retry-button')), findsOne);
    expect(
      find.byKey(const ValueKey('project-list-repair-button')),
      findsNothing,
    );
    expect(
      await profileStore.read(hostId: 'proj-demo', deviceId: 'phone'),
      isNotNull,
    );
  });

  testWidgets(
    'SSE connected keeps reconnect visible until a core HTTP probe succeeds',
    (tester) async {
      final profile = _pairedHost(
        hostId: 'proj-demo',
        deviceId: 'phone',
        scopes: const {'view', 'focus', 'notify'},
      );
      final profileStore = await _profileStoreWith([profile]);
      final repository =
          _HealthCheckedGatewayRepository()
            ..listProjectsError = TimeoutException('core HTTP unavailable')
            ..healthError = TimeoutException('core HTTP unavailable');
      final streamClient = _ConnectedTaskCompletionStreamClient();

      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: RecordingGatewayRepository(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            gatewayRepositoryFactory: (_) => repository,
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
            taskNotificationStreamClient: streamClient,
            taskCompletionLocalNotifications:
                _NoopTaskCompletionNotifications(),
            taskCompletionSeenStore: TaskCompletionSeenDedupeStore(
              secureStore: MemorySecureStore(),
            ),
            taskCompletionUnreadStore: TaskCompletionUnreadStore(
              secureStore: MemorySecureStore(),
            ),
            invalidationCursorStore: GatewayInvalidationCursorStore(
              secureStore: MemorySecureStore(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(streamClient.subscribeCalls, 1);
      expect(repository.healthCalls, greaterThan(0));
      expect(find.byKey(const ValueKey('project-list-retry-button')), findsOne);
      expect(
        find.byKey(const ValueKey('project-list-repair-button')),
        findsNothing,
      );
    },
  );

  testWidgets('paired lifecycle publishes visible presence transitions', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'proj-demo', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final repository = _HealthCheckedGatewayRepository();

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => repository,
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();

    expect(repository.presenceVisible, containsAllInOrder([true, false, true]));
  });

  testWidgets('activation syncs gateway settings on project list', (
    tester,
  ) async {
    final profile = _pairedHost(
      hostId: 'proj-demo',
      deviceId: 'phone',
      gatewayUrl: Uri.parse('https://mobile.example.com'),
      routeKind: RouteProviderKind.cloudflareTunnel,
    );
    final profileStore = await _profileStoreWith([profile]);

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => RecordingGatewayRepository(),
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();
    await dismissConnectionDetails(tester);

    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('project-list-settings-action')),
      findsOneWidget,
    );
    await tester.tap(
      find.byKey(const ValueKey('project-list-settings-action')),
    );
    await tester.pumpAndSettle();
    await expandTile(tester, const ValueKey('gateway-pairing-panel'));
    expect(find.byKey(const ValueKey('connection-code-field')), findsOneWidget);
    expect(find.byKey(const ValueKey('gateway-url-field')), findsNothing);
  });

  testWidgets('profile dropdown selection activates without snack', (
    tester,
  ) async {
    final first = _pairedHost(
      hostId: 'proj-demo',
      deviceId: 'phone',
      routeKind: RouteProviderKind.lan,
    );
    final second = _pairedHost(
      hostId: 'proj-demo',
      deviceId: 'tablet',
      gatewayUrl: Uri.parse('https://other.example.com'),
      routeKind: RouteProviderKind.relay,
    );
    final profileStore = await _profileStoreWith([first, second]);
    await profileStore.markSelected(first);
    final seenRepositoryProfiles = <GatewayPairedHost>[];

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: RecordingGatewayRepository(),
          profileStore: profileStore,
          gatewayRepositoryFactory: (profile) {
            seenRepositoryProfiles.add(profile);
            return RecordingGatewayRepository();
          },
          gatewayTerminalTransportFactory: (_) => RecordingTerminalTransport(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();
    final loadedFirst = _profileValue(tester)!;
    await tester.tap(find.byType(DropdownButtonFormField<GatewayPairedHost>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('proj-demo / tablet / relay').last);
    await tester.pumpAndSettle();
    final loadedSecond = _profileValue(tester)!;

    expect(loadedFirst.profile.deviceId, first.profile.deviceId);
    expect(loadedSecond.profile.deviceId, second.profile.deviceId);
    expect(seenRepositoryProfiles.first, same(loadedFirst));
    expect(seenRepositoryProfiles.last, same(loadedSecond));
    expect(
      (await profileStore.resolvePreferred(
        await profileStore.list(),
      ))?.profile.deviceId,
      'tablet',
    );
    expect(find.text('Pair a gateway profile first'), findsNothing);
    expect(find.text('proj-demo / tablet / relay'), findsWidgets);
  });

  testWidgets('switching back fake clears gateway terminal path', (
    tester,
  ) async {
    final profile = _pairedHost(hostId: 'proj-demo', deviceId: 'phone');
    final profileStore = await _profileStoreWith([profile]);
    final fakeRepository = RecordingGatewayRepository();
    final gatewayRepository = RecordingGatewayRepository();
    final gatewayTerminalTransport = RecordingTerminalTransport();

    await tester.pumpWidget(
      MaterialApp(
        home: ProjectHomeScreen(
          repository: fakeRepository,
          profileStore: profileStore,
          gatewayRepositoryFactory: (_) => gatewayRepository,
          gatewayTerminalTransportFactory: (_) => gatewayTerminalTransport,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openConnectionDetails(tester);
    await expandTile(tester, const ValueKey('runtime-mode-panel'));
    _runtimeSegments(
      tester,
    ).onSelectionChanged?.call({AppRuntimeMode.pairedGateway});
    await tester.pumpAndSettle();
    _runtimeSegments(tester).onSelectionChanged?.call({AppRuntimeMode.fake});
    await tester.pumpAndSettle();
    await dismissConnectionDetails(tester);
    await openCurrentProject(tester);

    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(gatewayTerminalTransport.requests, isEmpty);
    expect(gatewayRepository.focusAgentCalls, isEmpty);
    expect(find.byType(TerminalView), findsOneWidget);
    expect(fakeRepository.conversationCalls, isNotEmpty);
  });
}

SegmentedButton<AppRuntimeMode> _runtimeSegments(WidgetTester tester) {
  return tester.widget<SegmentedButton<AppRuntimeMode>>(
    find.byKey(const ValueKey('runtime-mode-segments')),
  );
}

GatewayPairedHost? _profileValue(WidgetTester tester) {
  return tester
      .state<FormFieldState<GatewayPairedHost>>(
        find.byType(DropdownButtonFormField<GatewayPairedHost>),
      )
      .value;
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

class _FailingProfileStore extends GatewayHostProfileStore {
  _FailingProfileStore() : super(secureStore: MemorySecureStore());

  @override
  Future<List<GatewayPairedHost>> list() {
    throw StateError('profile load failed');
  }
}

class _HealthCheckedGatewayRepository extends RecordingGatewayRepository
    implements
        MobileGatewayProfileHealthProbe,
        MobileGatewayCoreRouteVerifier,
        MobileGatewayPresenceReporter {
  Object? healthError;
  Object? deviceError;
  Object? listProjectsError;
  bool revoked = false;
  final presenceVisible = <bool>[];
  var healthCalls = 0;

  @override
  Future<List<CcbProject>> listProjects() async {
    final error = listProjectsError;
    if (error != null) throw error;
    return super.listProjects();
  }

  @override
  Future<GatewayHealth> health() async {
    healthCalls += 1;
    final error = healthError;
    if (error != null) {
      throw error;
    }
    return GatewayHealth(status: 'ok', serverTime: DateTime.utc(2026, 7, 10));
  }

  @override
  Future<GatewayDevice> device() async {
    final error = deviceError;
    if (error != null) throw error;
    return GatewayDevice(
      deviceId: 'phone',
      projectId: 'proj-demo',
      scopes: const {'view'},
      routeProvider: RouteProviderKind.lan,
      revoked: revoked,
    );
  }

  @override
  Future<void> verifyCoreRoutes() async {
    final health = await this.health();
    if (health.status.toLowerCase() != 'ok') {
      throw GatewayHttpException(Uri(), 503, 'gateway health is degraded');
    }
    final device = await this.device();
    if (device.revoked) {
      throw GatewayHttpException(Uri(), 401, 'device revoked');
    }
  }

  @override
  Future<void> reportPresence({
    required bool visible,
    String? focusedProjectId,
    String? focusedAgent,
    bool userActivity = false,
  }) async {
    presenceVisible.add(visible);
  }
}

GatewayPairedHost _pairedHost({
  required String hostId,
  required String deviceId,
  Uri? gatewayUrl,
  RouteProviderKind routeKind = RouteProviderKind.lan,
  Set<String> scopes = const {'view', 'focus', 'terminal_input', 'lifecycle'},
}) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: hostId,
      deviceId: deviceId,
      routeProvider: RouteProvider(
        kind: routeKind,
        gatewayUrl: gatewayUrl ?? Uri.parse('http://$hostId.local:8787'),
      ),
      scopes: scopes,
    ),
    deviceToken: 'token-$hostId-$deviceId',
    projectId: hostId,
  );
}

class _ConnectedTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  var subscribeCalls = 0;

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    subscribeCalls += 1;
    onConnected?.call();
    return const Stream<TaskCompletionNotificationEvent>.empty();
  }
}

class _NoopTaskCompletionNotifications
    implements TaskCompletionLocalNotifications {
  @override
  Stream<TaskCompletionNotificationTap> get taps =>
      const Stream<TaskCompletionNotificationTap>.empty();

  @override
  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded() async =>
      TaskCompletionLocalNotificationPermissionStatus.granted;

  @override
  Future<bool> showTaskCompletion(
    TaskCompletionNotificationEvent event,
  ) async => true;
}
