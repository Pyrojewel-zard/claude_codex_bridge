import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/project_home_task_completion_notifications.dart';
import 'package:test/test.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  group('task completion notifications', () {
    test('event shows local notification with stable id and copy', () async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final localNotifications = _FakeTaskCompletionLocalNotifications();
      final controller = _controller(
        streamClient: streamClient,
        localNotifications: localNotifications,
      );
      final event = _event(dedupeKey: 'proj-demo:mobile:1');

      final status = await controller.start(_host(scopes: const {'notify'}));
      streamClient.add(event);
      await _drain();

      expect(status, TaskCompletionNotificationSubscriptionStatus.subscribed);
      expect(localNotifications.permissionRequests, 1);
      expect(localNotifications.shown, hasLength(1));
      expect(
        localNotifications.shown.single.notificationId,
        event.notificationId,
      );
      expect(localNotifications.shown.single.title, 'CCB Mobile');
      expect(localNotifications.shown.single.body, 'demo / mobile 任务完成');

      await controller.dispose();
    });

    test(
      'dedupe key is persisted and suppresses duplicate notifications',
      () async {
        final secureStore = MemorySecureStore();
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
          seenStore: TaskCompletionSeenDedupeStore(secureStore: secureStore),
        );
        final event = _event(dedupeKey: 'same-key');

        await controller.start(_host(scopes: const {'notify'}));
        streamClient
          ..add(event)
          ..add(event);
        await _drain();

        expect(localNotifications.shown, hasLength(1));
        expect(
          await TaskCompletionSeenDedupeStore(
            secureStore: secureStore,
          ).readSeenKeys(),
          ['same-key'],
        );

        await controller.dispose();
      },
    );

    test('seen store keeps a bounded recent dedupe set', () async {
      final store = TaskCompletionSeenDedupeStore(
        secureStore: MemorySecureStore(),
        maxKeys: 2,
      );

      expect(await store.markSeenIfNew('a'), isTrue);
      expect(await store.markSeenIfNew('b'), isTrue);
      expect(await store.markSeenIfNew('c'), isTrue);

      expect(await store.readSeenKeys(), ['b', 'c']);
      expect(await store.markSeenIfNew('a'), isTrue);
    });

    test('stable notification id is deterministic signed 32-bit hash', () {
      final first = stableTaskCompletionNotificationId('proj-demo:mobile:1');
      final second = stableTaskCompletionNotificationId('proj-demo:mobile:1');
      final different = stableTaskCompletionNotificationId('proj-demo:lead:1');

      expect(first, second);
      expect(first, isNot(different));
      expect(first, inInclusiveRange(-0x80000000, 0x7fffffff));
      expect(first, 1840802715);
    });

    test('agent activity invalidation preserves its low-sensitive state', () {
      final event = TaskCompletionNotificationEvent.fromJson({
        'id': 'mnotif_42',
        'kind': TaskCompletionNotificationEvent.agentActivityChangedKind,
        'project_id': 'proj-demo',
        'project_short_name': 'demo',
        'agent': 'mobile',
        'completed_at': '2026-06-30T12:00:00Z',
        'dedupe_key': 'activity:42',
        'namespace_epoch': 4,
        'scope': 'agent',
        'activity_state': 'active',
      });

      expect(event.activityState, 'active');
      expect(event.toJson()['activity_state'], 'active');
    });

    test(
      'missing notify scope does not request permission or subscribe',
      () async {
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
        );

        final status = await controller.start(_host(scopes: const {'view'}));

        expect(
          status,
          TaskCompletionNotificationSubscriptionStatus.missingNotifyScope,
        );
        expect(localNotifications.permissionRequests, 0);
        expect(streamClient.subscribeCalls, 0);

        await controller.dispose();
      },
    );

    test(
      'permission denied still consumes stream without showing OS notification',
      () async {
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications(
          permissionStatus:
              TaskCompletionLocalNotificationPermissionStatus.denied,
        );
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
        );

        final status = await controller.start(_host(scopes: const {'notify'}));
        streamClient.add(_event(dedupeKey: 'denied'));
        await _drain();

        expect(
          status,
          TaskCompletionNotificationSubscriptionStatus.permissionDenied,
        );
        expect(localNotifications.shown, isEmpty);
        expect(streamClient.subscribeCalls, 1);

        await controller.dispose();
      },
    );

    test(
      'baseline events are marked seen without notification or live event',
      () async {
        final secureStore = MemorySecureStore();
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final liveEvents = <TaskCompletionNotificationEvent>[];
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
          seenStore: TaskCompletionSeenDedupeStore(secureStore: secureStore),
          clock: () => DateTime.utc(2026, 6, 30, 12, 0, 1),
          onLiveEvent: liveEvents.add,
        );
        final oldEvent = _event(dedupeKey: 'old');

        await controller.start(_host(scopes: const {'notify'}));
        streamClient.add(oldEvent);
        await _drain();

        expect(localNotifications.shown, isEmpty);
        expect(liveEvents, isEmpty);
        expect(
          await TaskCompletionSeenDedupeStore(
            secureStore: secureStore,
          ).readSeenKeys(),
          ['old'],
        );

        await controller.dispose();
      },
    );

    test('live event callback fires before optional OS notification', () async {
      final streamClient = _FakeTaskCompletionStreamClient();
      final localNotifications = _FakeTaskCompletionLocalNotifications();
      final liveEvents = <TaskCompletionNotificationEvent>[];
      final controller = _controller(
        streamClient: streamClient,
        localNotifications: localNotifications,
        onLiveEvent: liveEvents.add,
        shouldShowNotification: (_) => false,
      );
      final event = _event(dedupeKey: 'live-callback');

      await controller.start(_host(scopes: const {'notify'}));
      streamClient.add(event);
      await _drain();

      expect(liveEvents.map((event) => event.dedupeKey), ['live-callback']);
      expect(localNotifications.shown, isEmpty);

      await controller.dispose();
    });

    test(
      'unified stream dispatches redacted invalidations without an OS alert',
      () async {
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final invalidations = <TaskCompletionNotificationEvent>[];
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
          onInvalidationEvent: invalidations.add,
        );
        final event = _invalidation(
          id: 'conversation-7',
          kind: TaskCompletionNotificationEvent.conversationChangedKind,
        );

        await controller.start(_host(scopes: const {'notify'}));
        streamClient
          ..add(event)
          ..add(event);
        await _drain();

        expect(invalidations, [event]);
        expect(localNotifications.shown, isEmpty);

        await controller.dispose();
      },
    );

    test(
      'retained invalidation baseline advances cursor without replay refreshes',
      () async {
        final secureStore = MemorySecureStore();
        final cursorStore = GatewayInvalidationCursorStore(
          secureStore: secureStore,
        );
        final streamClient = _FakeTaskCompletionStreamClient();
        final invalidations = <TaskCompletionNotificationEvent>[];
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          cursorStore: cursorStore,
          onInvalidationEvent: invalidations.add,
          clock: () => DateTime.utc(2026, 6, 30, 12),
        );
        final host = _host(scopes: const {'notify'});

        await controller.start(host);
        streamClient
          ..add(
            _invalidation(
              id: 'mnotif_000000000010',
              kind: TaskCompletionNotificationEvent.conversationChangedKind,
              completedAt: DateTime.utc(2026, 6, 30, 11, 59, 58),
            ),
          )
          ..add(
            _invalidation(
              id: 'mnotif_000000000011',
              kind: TaskCompletionNotificationEvent.agentActivityChangedKind,
              completedAt: DateTime.utc(2026, 6, 30, 11, 59, 59),
            ),
          );
        await _drain();
        await _drain();

        expect(invalidations, isEmpty);
        expect(await cursorStore.read(host), 'mnotif_000000000011');

        final live = _invalidation(
          id: 'mnotif_000000000012',
          kind: TaskCompletionNotificationEvent.conversationChangedKind,
          completedAt: DateTime.utc(2026, 6, 30, 12, 0, 1),
        );
        streamClient.add(live);
        await _drain();

        expect(invalidations, [live]);

        await controller.dispose();
      },
    );

    test(
      'stream completion reconnects and keeps future notifications alive',
      () async {
        final streamClient = _ReconnectTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final controller = TaskCompletionNotificationController(
          streamClient: streamClient,
          localNotifications: localNotifications,
          seenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          onTap: (_) {},
          clock: () => DateTime.utc(2026, 6, 30, 11, 59),
          initialReconnectDelay: Duration.zero,
          maxReconnectDelay: Duration.zero,
        );

        await controller.start(_host(scopes: const {'notify'}));
        expect(streamClient.subscribeCalls, 1);

        await streamClient.closeLatest();
        await _drain();
        expect(streamClient.subscribeCalls, 2);

        streamClient.add(_event(dedupeKey: 'after-reconnect'));
        await _drain();

        expect(localNotifications.shown.map((event) => event.dedupeKey), [
          'after-reconnect',
        ]);

        await controller.dispose();
      },
    );

    test(
      'connection state waits for the notification HTTP handshake',
      () async {
        final streamClient = _DelayedConnectionTaskCompletionStreamClient();
        final states = <GatewayInvalidationConnectionState>[];
        final controller = TaskCompletionNotificationController(
          streamClient: streamClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          seenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          onTap: (_) {},
          onConnectionStateChanged: (state, _) => states.add(state),
          initialReconnectDelay: const Duration(hours: 1),
        );

        await controller.start(_host(scopes: const {'notify'}));
        expect(
          states.where(
            (state) => state == GatewayInvalidationConnectionState.connected,
          ),
          isEmpty,
        );

        streamClient.markConnected();
        await _drain();
        expect(states.last, GatewayInvalidationConnectionState.connected);

        streamClient.addError(StateError('connection lost'));
        await _drain();
        expect(states.last, GatewayInvalidationConnectionState.reconnecting);

        await controller.dispose();
      },
    );

    test(
      'many live events keep connected notification state edge-bounded',
      () async {
        final streamClient = _DelayedConnectionTaskCompletionStreamClient();
        final states = <GatewayInvalidationConnectionState>[];
        var coreProbeCalls = 0;
        final controller = TaskCompletionNotificationController(
          streamClient: streamClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          seenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          onTap: (_) {},
          onConnectionStateChanged: (state, _) {
            states.add(state);
            if (state == GatewayInvalidationConnectionState.connected) {
              coreProbeCalls += 1;
            }
          },
        );

        await controller.start(_host(scopes: const {'notify'}));
        streamClient.markConnected();
        for (var index = 0; index < 40; index += 1) {
          streamClient.add(_event(dedupeKey: 'burst-$index'));
        }
        await _drain();

        expect(
          states.where(
            (state) => state == GatewayInvalidationConnectionState.connected,
          ),
          hasLength(1),
        );
        expect(coreProbeCalls, 1);
        await controller.dispose();
      },
    );

    test(
      'persists SSE id and resumes it after a normal controller restart',
      () async {
        final secureStore = MemorySecureStore();
        final cursorStore = GatewayInvalidationCursorStore(
          secureStore: secureStore,
        );
        final host = _host(scopes: const {'notify'});
        final firstClient = _FakeTaskCompletionStreamClient();
        final first = _controller(
          streamClient: firstClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          cursorStore: cursorStore,
        );
        await first.start(host);
        firstClient.add(_event(id: 'mnotif_000000000042', dedupeKey: 'cursor'));
        await _drain();
        expect(await cursorStore.read(host), 'mnotif_000000000042');
        await first.dispose();

        final resumedClient = _FakeTaskCompletionStreamClient();
        final resumed = _controller(
          streamClient: resumedClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          cursorStore: cursorStore,
        );
        await resumed.start(host);
        expect(resumedClient.lastEventIds, ['mnotif_000000000042']);
        await resumed.dispose();
      },
    );

    test(
      'handles streamed events sequentially before confirming the cursor',
      () async {
        final secureStore = MemorySecureStore();
        final cursorStore = GatewayInvalidationCursorStore(
          secureStore: secureStore,
        );
        final streamClient = _FakeTaskCompletionStreamClient();
        final handled = <String>[];
        final releaseFirst = Completer<void>();
        var blockedFirst = false;
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          cursorStore: cursorStore,
          onInvalidationEvent: (event) async {
            handled.add(event.id);
            if (event.id == 'mnotif_000000000001' && !blockedFirst) {
              blockedFirst = true;
              await releaseFirst.future;
            }
          },
        );
        final host = _host(scopes: const {'notify'});

        await controller.start(host);
        streamClient
          ..add(
            _invalidation(
              id: 'mnotif_000000000001',
              kind: TaskCompletionNotificationEvent.conversationChangedKind,
            ),
          )
          ..add(
            _invalidation(
              id: 'mnotif_000000000002',
              kind: TaskCompletionNotificationEvent.conversationChangedKind,
            ),
          );
        await _drain();
        releaseFirst.complete();
        await _drain();
        await _drain();

        expect(handled, ['mnotif_000000000001', 'mnotif_000000000002']);
        expect(await cursorStore.read(host), 'mnotif_000000000002');

        await controller.dispose();
      },
    );

    test(
      'stopped controller drops queued events before cursor or notification side effects',
      () async {
        final secureStore = MemorySecureStore();
        final cursorStore = GatewayInvalidationCursorStore(
          secureStore: secureStore,
        );
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final releaseEvent = Completer<void>();
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
          cursorStore: cursorStore,
          onInvalidationEvent: (_) => releaseEvent.future,
        );
        final host = _host(scopes: const {'notify'});

        await controller.start(host);
        streamClient.add(
          _event(id: 'mnotif_000000000099', dedupeKey: 'stopped'),
        );
        await _drain();

        await controller.stop();
        releaseEvent.complete();
        await _drain();
        await _drain();

        expect(await cursorStore.read(host), isNull);
        expect(localNotifications.shown, isEmpty);

        await controller.dispose();
      },
    );

    test('invalidation handler failure leaves cursor unconfirmed', () async {
      final secureStore = MemorySecureStore();
      final cursorStore = GatewayInvalidationCursorStore(
        secureStore: secureStore,
      );
      final streamClient = _FakeTaskCompletionStreamClient();
      final errors = <Object>[];
      final controller = _controller(
        streamClient: streamClient,
        localNotifications: _FakeTaskCompletionLocalNotifications(),
        cursorStore: cursorStore,
        onInvalidationEvent:
            (_) => Future<void>.error(StateError('resync failed')),
        onStreamError: errors.add,
      );
      final host = _host(scopes: const {'notify'});

      await controller.start(host);
      streamClient.add(
        _invalidation(
          id: 'mnotif_000000000123',
          kind: TaskCompletionNotificationEvent.resyncRequiredKind,
          completedAt: DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
        ),
      );
      await _drain();
      await _drain();

      expect(await cursorStore.read(host), isNull);
      expect(errors, hasLength(1));

      await controller.dispose();
    });

    test('HTTP client uses gateway notification SSE contract', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final requestSeen = Completer<HttpRequest>();
      unawaited(
        server.first.then((request) async {
          requestSeen.complete(request);
          request.response
            ..statusCode = HttpStatus.ok
            ..headers.contentType = ContentType(
              'text',
              'event-stream',
              charset: 'utf-8',
            )
            ..write('id: event-demo\n')
            ..write('event: task_completed\n')
            ..write('data: ${jsonEncode(_event(dedupeKey: 'sse').toJson())}\n')
            ..write('\n');
          await request.response.close();
        }),
      );
      final client = HttpGatewayTaskCompletionNotificationStreamClient(
        timeout: const Duration(seconds: 2),
      );
      addTearDown(client.close);

      final event =
          await client
              .subscribe(
                GatewayPairedHost(
                  profile: GatewayHostProfile(
                    hostId: 'host-demo',
                    deviceId: 'device-demo',
                    routeProvider: RouteProvider(
                      kind: RouteProviderKind.lan,
                      gatewayUrl: Uri.parse(
                        'http://${server.address.address}:${server.port}',
                      ),
                    ),
                    scopes: const {'notify'},
                  ),
                  deviceToken: 'device-token',
                  projectId: 'proj-demo',
                ),
                'mnotif_000000000041',
                const GatewayInvalidationWatch(
                  projectId: 'proj-demo',
                  agent: 'mobile',
                  namespaceEpoch: 7,
                  provider: 'codex',
                ),
              )
              .first;
      final request = await requestSeen.future;

      expect(request.uri.path, '/v1/mobile/notifications');
      expect(
        request.headers.value(HttpHeaders.authorizationHeader),
        'Bearer device-token',
      );
      expect(request.headers.value('last-event-id'), 'mnotif_000000000041');
      expect(request.uri.queryParameters['watch_project_id'], 'proj-demo');
      expect(request.uri.queryParameters['watch_agent'], 'mobile');
      expect(event.dedupeKey, 'sse');
    });

    test('HTTP client accepts raw NDJSON event streams line by line', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      unawaited(
        server.first.then((request) async {
          request.response
            ..statusCode = HttpStatus.ok
            ..headers.contentType = ContentType(
              'application',
              'x-ndjson',
              charset: 'utf-8',
            )
            ..write('${jsonEncode(_event(dedupeKey: 'raw-1').toJson())}\n')
            ..write('${jsonEncode(_event(dedupeKey: 'raw-2').toJson())}\n');
          await request.response.close();
        }),
      );
      final client = HttpGatewayTaskCompletionNotificationStreamClient(
        timeout: const Duration(seconds: 2),
      );
      addTearDown(client.close);

      final events =
          await client
              .subscribe(
                GatewayPairedHost(
                  profile: GatewayHostProfile(
                    hostId: 'host-demo',
                    deviceId: 'device-demo',
                    routeProvider: RouteProvider(
                      kind: RouteProviderKind.lan,
                      gatewayUrl: Uri.parse(
                        'http://${server.address.address}:${server.port}',
                      ),
                    ),
                    scopes: const {'notify'},
                  ),
                  deviceToken: 'device-token',
                  projectId: 'proj-demo',
                ),
              )
              .toList();

      expect(events.map((event) => event.dedupeKey), ['raw-1', 'raw-2']);
    });

    test(
      'canceling an HTTP subscription completes without SSE deadlock',
      () async {
        final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
        addTearDown(() => server.close(force: true));
        final requestSeen = Completer<void>();
        final connected = Completer<void>();
        final releaseResponse = Completer<void>();
        addTearDown(() {
          if (!releaseResponse.isCompleted) releaseResponse.complete();
        });
        unawaited(
          server.first.then((request) async {
            request.response
              ..statusCode = HttpStatus.ok
              ..headers.contentType = ContentType(
                'text',
                'event-stream',
                charset: 'utf-8',
              )
              ..write(': connected\n\n');
            await request.response.flush();
            requestSeen.complete();
            try {
              await releaseResponse.future;
              await request.response.close();
            } on Object {
              // The client intentionally tears down the long-lived response.
            }
          }),
        );
        final client = HttpGatewayTaskCompletionNotificationStreamClient(
          timeout: const Duration(seconds: 2),
        );
        addTearDown(client.close);
        final subscription = client
            .subscribe(
              GatewayPairedHost(
                profile: GatewayHostProfile(
                  hostId: 'host-demo',
                  deviceId: 'device-demo',
                  routeProvider: RouteProvider(
                    kind: RouteProviderKind.lan,
                    gatewayUrl: Uri.parse(
                      'http://${server.address.address}:${server.port}',
                    ),
                  ),
                  scopes: const {'notify'},
                ),
                deviceToken: 'device-token',
                projectId: 'proj-demo',
              ),
              null,
              null,
              connected.complete,
            )
            .listen((_) {});

        await requestSeen.future;
        await connected.future;
        await subscription.cancel().timeout(const Duration(milliseconds: 500));
      },
    );

    test(
      'start initialization coalesces watch changes before one cursor resume',
      () async {
        final secureStore = _DelayedReadSecureStore();
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications = _FakeTaskCompletionLocalNotifications();
        final liveEvents = <TaskCompletionNotificationEvent>[];
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
          cursorStore: GatewayInvalidationCursorStore(secureStore: secureStore),
          onLiveEvent: liveEvents.add,
        );
        final host = _host(scopes: const {'notify'});
        const initialWatch = GatewayInvalidationWatch(
          projectId: 'proj-demo',
          agent: 'mobile',
          namespaceEpoch: 4,
        );
        const latestWatch = GatewayInvalidationWatch(
          projectId: 'proj-demo',
          agent: 'lead',
          namespaceEpoch: 5,
        );

        final start = controller.start(host, initialWatch);
        await secureStore.readStarted.future;
        controller
          ..updateWatch(latestWatch)
          ..retryNow();
        streamClient.add(_event(dedupeKey: 'before-baseline'));
        await _drain();

        expect(streamClient.subscribeCalls, 0);
        expect(localNotifications.shown, isEmpty);
        expect(liveEvents, isEmpty);

        secureStore.completeRead('mnotif_000000000077');
        await start;

        expect(streamClient.subscribeCalls, 1);
        expect(streamClient.lastEventIds, ['mnotif_000000000077']);
        expect(streamClient.watches, [latestWatch]);
        await controller.dispose();
      },
    );

    test(
      'stale start completion cannot replace a newer subscription',
      () async {
        final streamClient = _FakeTaskCompletionStreamClient();
        final localNotifications =
            _SequencedPermissionTaskCompletionLocalNotifications();
        final controller = _controller(
          streamClient: streamClient,
          localNotifications: localNotifications,
        );
        const firstWatch = GatewayInvalidationWatch(
          projectId: 'proj-demo',
          agent: 'mobile',
          namespaceEpoch: 4,
        );
        const latestWatch = GatewayInvalidationWatch(
          projectId: 'proj-demo',
          agent: 'lead',
          namespaceEpoch: 5,
        );

        final firstStart = controller.start(
          _host(scopes: const {'notify'}),
          firstWatch,
        );
        await _waitFor(() => localNotifications.requests.length == 1);
        final latestStart = controller.start(
          _host(scopes: const {'notify'}),
          latestWatch,
        );
        await _waitFor(() => localNotifications.requests.length == 2);

        localNotifications.requests[1].complete(
          TaskCompletionLocalNotificationPermissionStatus.granted,
        );
        await latestStart;
        localNotifications.requests[0].complete(
          TaskCompletionLocalNotificationPermissionStatus.granted,
        );
        await firstStart;

        expect(streamClient.subscribeCalls, 1);
        expect(streamClient.watches, [latestWatch]);
        await controller.dispose();
      },
    );

    test(
      'HTTP SSE replacement coalesces watch changes and awaits cancellation',
      () async {
        final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
        var requestCount = 0;
        var serverActive = 0;
        var serverPeak = 0;
        final sockets = <Socket>[];
        server.listen((socket) {
          requestCount += 1;
          serverActive += 1;
          serverPeak = serverPeak > serverActive ? serverPeak : serverActive;
          sockets.add(socket);
          var responded = false;
          var closed = false;
          final requestBytes = BytesBuilder(copy: false);
          void markClosed() {
            if (closed) {
              return;
            }
            closed = true;
            serverActive -= 1;
          }

          socket.listen(
            (bytes) {
              if (responded) {
                return;
              }
              requestBytes.add(bytes);
              if (!ascii
                  .decode(requestBytes.toBytes(), allowInvalid: true)
                  .contains('\r\n\r\n')) {
                return;
              }
              responded = true;
              socket.add(
                ascii.encode(
                  'HTTP/1.1 200 OK\r\n'
                  'Content-Type: text/event-stream; charset=utf-8\r\n'
                  'Cache-Control: no-cache\r\n'
                  'Transfer-Encoding: chunked\r\n'
                  'Connection: keep-alive\r\n'
                  '\r\n'
                  'd\r\n: connected\n\n\r\n',
                ),
              );
            },
            onDone: markClosed,
            onError: (_) => markClosed(),
          );
        });
        addTearDown(() async {
          for (final socket in sockets) {
            socket.destroy();
          }
          await server.close();
        });
        final httpClient = HttpGatewayTaskCompletionNotificationStreamClient(
          timeout: const Duration(seconds: 2),
        );
        final streamClient = _CountingTaskCompletionStreamClient(httpClient);
        final controller = TaskCompletionNotificationController(
          streamClient: streamClient,
          localNotifications: _FakeTaskCompletionLocalNotifications(),
          seenStore: TaskCompletionSeenDedupeStore(
            secureStore: MemorySecureStore(),
          ),
          onTap: (_) {},
        );
        final host = GatewayPairedHost(
          profile: GatewayHostProfile(
            hostId: 'host-http',
            deviceId: 'device-http',
            routeProvider: RouteProvider(
              kind: RouteProviderKind.lan,
              gatewayUrl: Uri.parse(
                'http://${server.address.address}:${server.port}',
              ),
            ),
            scopes: const {'notify'},
          ),
          deviceToken: 'device-token',
          projectId: 'proj-demo',
        );

        await controller.start(host);
        await _waitFor(() => requestCount == 1 && streamClient.active == 1);
        controller
          ..updateWatch(
            const GatewayInvalidationWatch(
              projectId: 'proj-demo',
              agent: 'mobile',
              namespaceEpoch: 4,
            ),
          )
          ..updateWatch(
            const GatewayInvalidationWatch(
              projectId: 'proj-demo',
              agent: 'lead',
              namespaceEpoch: 4,
            ),
          )
          ..retryNow();
        await _waitFor(
          () =>
              requestCount == 2 &&
              streamClient.active == 1 &&
              serverActive == 1,
          description:
              () =>
                  'requestCount=$requestCount active=${streamClient.active} peak=${streamClient.peak} serverActive=$serverActive serverPeak=$serverPeak',
        );
        expect(streamClient.peak, lessThanOrEqualTo(1));
        expect(serverPeak, lessThanOrEqualTo(1));

        controller.updateWatch(
          const GatewayInvalidationWatch(
            projectId: 'proj-demo',
            agent: 'lead',
            namespaceEpoch: 4,
          ),
        );
        await Future<void>.delayed(const Duration(milliseconds: 100));
        expect(streamClient.peak, lessThanOrEqualTo(1));

        await controller.stop();
        await _waitFor(
          () => streamClient.active == 0,
          timeout: const Duration(seconds: 5),
        );
        await controller.start(
          host,
          const GatewayInvalidationWatch(
            projectId: 'proj-demo',
            agent: 'lead',
            namespaceEpoch: 4,
          ),
        );
        await _waitFor(() => requestCount == 3 && streamClient.active == 1);
        expect(streamClient.peak, lessThanOrEqualTo(1));
        await controller.dispose();
        httpClient.close(force: true);
      },
    );

    test(
      'tap routing opens target agent when project view still contains it',
      () {
        final route = resolveProjectHomeTaskCompletionNotificationTap(
          tap: const TaskCompletionNotificationTap(
            projectId: 'proj-demo',
            agent: 'mobile',
          ),
          targetView: _view(),
        );

        expect(
          route.kind,
          ProjectHomeTaskCompletionNotificationRouteKind.openProjectAgent,
        );
        expect(route.projectId, 'proj-demo');
        expect(route.agentName, 'mobile');
        expect(route.view?.project.id, 'proj-demo');
      },
    );

    test('tap routing falls back to project list for missing target', () {
      final route = resolveProjectHomeTaskCompletionNotificationTap(
        tap: const TaskCompletionNotificationTap(
          projectId: 'proj-demo',
          agent: 'missing',
        ),
        targetView: _view(),
      );
      final missingProjectRoute =
          resolveProjectHomeTaskCompletionNotificationTap(
            tap: const TaskCompletionNotificationTap(
              projectId: 'missing',
              agent: 'mobile',
            ),
            targetView: null,
          );

      expect(
        route.kind,
        ProjectHomeTaskCompletionNotificationRouteKind.projectList,
      );
      expect(
        missingProjectRoute.kind,
        ProjectHomeTaskCompletionNotificationRouteKind.projectList,
      );
    });
  });
}

TaskCompletionNotificationController _controller({
  required _FakeTaskCompletionStreamClient streamClient,
  required _FakeTaskCompletionLocalNotifications localNotifications,
  TaskCompletionSeenDedupeStore? seenStore,
  TaskCompletionNotificationEventHandler? onLiveEvent,
  TaskCompletionNotificationEventHandler? onInvalidationEvent,
  TaskCompletionNotificationPredicate? shouldShowNotification,
  GatewayInvalidationStreamErrorHandler? onStreamError,
  GatewayInvalidationCursorStore? cursorStore,
  DateTime Function()? clock,
}) {
  return TaskCompletionNotificationController(
    streamClient: streamClient,
    localNotifications: localNotifications,
    seenStore:
        seenStore ??
        TaskCompletionSeenDedupeStore(secureStore: MemorySecureStore()),
    cursorStore: cursorStore,
    onTap: (_) {},
    onLiveEvent: onLiveEvent,
    onInvalidationEvent: onInvalidationEvent,
    shouldShowNotification: shouldShowNotification,
    onStreamError: onStreamError,
    clock: clock ?? () => DateTime.utc(2026, 6, 30, 11, 59),
  );
}

TaskCompletionNotificationEvent _event({
  required String dedupeKey,
  String? id,
  DateTime? completedAt,
}) {
  return TaskCompletionNotificationEvent(
    id: id ?? 'event-$dedupeKey',
    kind: TaskCompletionNotificationEvent.taskCompletedKind,
    projectId: 'proj-demo',
    projectShortName: 'demo',
    agent: 'mobile',
    completedAt: completedAt ?? DateTime.utc(2026, 6, 30, 12),
    dedupeKey: dedupeKey,
  );
}

TaskCompletionNotificationEvent _invalidation({
  required String id,
  required String kind,
  DateTime? completedAt,
}) {
  return TaskCompletionNotificationEvent(
    id: id,
    kind: kind,
    projectId: 'proj-demo',
    projectShortName: 'demo',
    agent: 'mobile',
    completedAt: completedAt ?? DateTime.utc(2026, 6, 30, 12),
    dedupeKey: 'invalidation:$id',
    namespaceEpoch: 4,
    scope: 'conversation',
  );
}

GatewayPairedHost _host({required Set<String> scopes}) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: 'host-demo',
      deviceId: 'device-demo',
      routeProvider: RouteProvider(
        kind: RouteProviderKind.lan,
        gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
      ),
      scopes: scopes,
    ),
    deviceToken: 'device-token',
    projectId: 'proj-demo',
  );
}

CcbProjectView _view() {
  return const CcbProjectView(
    project: CcbProject(
      id: 'proj-demo',
      displayName: 'demo',
      root: '/srv/demo',
    ),
    namespaceEpoch: 4,
    tmuxSocketPath: '/tmp/tmux.sock',
    tmuxSessionName: 'ccb-demo',
    activeWindow: 'main',
    activePaneId: '%1',
    windows: [
      CcbWindow(
        name: 'main',
        label: 'main',
        kind: 'agents',
        order: 0,
        active: true,
        agents: ['mobile'],
      ),
    ],
    agents: [
      CcbAgent(
        name: 'mobile',
        provider: 'codex',
        window: 'main',
        order: 0,
        active: true,
        queueDepth: 0,
      ),
    ],
    contentItems: [],
    notifications: [],
    terminalHistories: {},
  );
}

Future<void> _drain() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

Future<void> _waitFor(
  bool Function() condition, {
  Duration timeout = const Duration(seconds: 2),
  String Function()? description,
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      throw TimeoutException(
        'condition was not met within $timeout${description == null ? '' : ': ${description()}'}',
      );
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

class _FakeTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  final _controller =
      StreamController<TaskCompletionNotificationEvent>.broadcast();
  var subscribeCalls = 0;
  final lastEventIds = <String?>[];
  final watches = <GatewayInvalidationWatch?>[];

  void add(TaskCompletionNotificationEvent event) {
    _controller.add(event);
  }

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    subscribeCalls += 1;
    lastEventIds.add(lastEventId);
    watches.add(watch);
    return _controller.stream;
  }
}

class _DelayedReadSecureStore implements GatewaySecureStore {
  final readStarted = Completer<void>();
  final _readResult = Completer<String?>();
  final values = <String, String>{};

  void completeRead(String? value) {
    if (!_readResult.isCompleted) {
      _readResult.complete(value);
    }
  }

  @override
  Future<String?> read({required String key}) {
    if (!readStarted.isCompleted) {
      readStarted.complete();
    }
    return _readResult.future;
  }

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }

  @override
  Future<void> delete({required String key}) async {
    values.remove(key);
  }
}

class _CountingTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  _CountingTaskCompletionStreamClient(this._delegate);

  final GatewayTaskCompletionNotificationStreamClient _delegate;
  var active = 0;
  var peak = 0;

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    return Stream<TaskCompletionNotificationEvent>.multi((controller) {
      active += 1;
      peak = peak > active ? peak : active;
      var closed = false;
      void markClosed() {
        if (closed) return;
        closed = true;
        active -= 1;
      }

      final subscription = _delegate
          .subscribe(host, lastEventId, watch, onConnected)
          .listen(
            controller.add,
            onError: controller.addError,
            onDone: () {
              markClosed();
              controller.close();
            },
          );
      controller.onCancel = () async {
        await subscription.cancel();
        markClosed();
      };
    });
  }
}

class _ReconnectTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  final _controllers = <StreamController<TaskCompletionNotificationEvent>>[];
  var subscribeCalls = 0;

  void add(TaskCompletionNotificationEvent event) {
    _controllers.last.add(event);
  }

  Future<void> closeLatest() {
    return _controllers.last.close();
  }

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    subscribeCalls += 1;
    final controller = StreamController<TaskCompletionNotificationEvent>();
    _controllers.add(controller);
    return controller.stream;
  }
}

class _DelayedConnectionTaskCompletionStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  final _controller = StreamController<TaskCompletionNotificationEvent>();
  void Function()? _onConnected;

  void markConnected() {
    _onConnected?.call();
  }

  void addError(Object error) {
    _controller.addError(error);
  }

  void add(TaskCompletionNotificationEvent event) {
    _controller.add(event);
  }

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    _onConnected = onConnected;
    return _controller.stream;
  }
}

class _FakeTaskCompletionLocalNotifications
    implements TaskCompletionLocalNotifications {
  _FakeTaskCompletionLocalNotifications({
    this.permissionStatus =
        TaskCompletionLocalNotificationPermissionStatus.granted,
  });

  final TaskCompletionLocalNotificationPermissionStatus permissionStatus;
  final shown = <TaskCompletionNotificationEvent>[];
  final _taps = StreamController<TaskCompletionNotificationTap>.broadcast();
  var permissionRequests = 0;

  @override
  Stream<TaskCompletionNotificationTap> get taps => _taps.stream;

  @override
  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded() async {
    permissionRequests += 1;
    return permissionStatus;
  }

  @override
  Future<bool> showTaskCompletion(TaskCompletionNotificationEvent event) async {
    shown.add(event);
    return true;
  }
}

class _SequencedPermissionTaskCompletionLocalNotifications
    extends _FakeTaskCompletionLocalNotifications {
  final requests =
      <Completer<TaskCompletionLocalNotificationPermissionStatus>>[];

  @override
  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded() {
    final request =
        Completer<TaskCompletionLocalNotificationPermissionStatus>();
    requests.add(request);
    return request.future;
  }
}
