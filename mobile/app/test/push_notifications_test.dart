import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('push route requires a complete completion target', () {
    expect(
      () => PushNotificationRoute.fromData(const {'project_id': 'demo'}),
      throwsFormatException,
    );
    expect(
      () => PushNotificationRoute.fromData(const {
        'project_id': 'proj-demo',
        'agent': 'mobile',
      }),
      throwsFormatException,
    );

    final route = PushNotificationRoute.fromData(const {
      'project_id': 'proj-demo',
      'agent': 'mobile',
      'dedupe_key': 'proj-demo:mobile:42',
      'host_id': 'host-demo',
      'device_id': 'device-demo',
    });

    expect(route.dedupeKey, 'proj-demo:mobile:42');
    expect(route.matches(_host()), isTrue);
    expect(route.matches(_host(deviceId: 'other-device')), isFalse);
  });

  test('permission denial leaves push unregistered and route-free', () async {
    final messaging = _FakePushMessagingClient(permissionGranted: false);
    final routes = <PushNotificationRoute>[];
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: GatewayPushRegistrationClient(isEnabled: () => true),
      onRouteOpened: (route) async => routes.add(route),
      isEnabled: () => true,
    );

    expect(await runtime.start(_host()), isFalse);
    expect(messaging.tokenReads, 0);
    expect(routes, isEmpty);

    await runtime.dispose();
  });

  test('missing native Firebase configuration fails closed', () async {
    final messaging = FirebasePushMessagingClient();

    expect(await messaging.initializeAndRequestPermission(), isFalse);
  });

  test(
    'token refresh stays bound to the paired device and opens matching route',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final requests = <Map<String, Object?>>[];
      final subscription = server.listen((request) async {
        requests.add({
          'path': request.uri.path,
          'authorization': request.headers.value(
            HttpHeaders.authorizationHeader,
          ),
          'body':
              request.method == 'DELETE'
                  ? null
                  : jsonDecode(await utf8.decodeStream(request)),
        });
        request.response.statusCode = HttpStatus.ok;
        await request.response.close();
      });
      final messaging = _FakePushMessagingClient(token: 'first-token');
      final routes = <PushNotificationRoute>[];
      final runtime = PushNotificationRuntime(
        messaging: messaging,
        registration: GatewayPushRegistrationClient(isEnabled: () => true),
        onRouteOpened: (route) async => routes.add(route),
        isEnabled: () => true,
      );
      final host = _host(port: server.port);

      expect(await runtime.start(host), isTrue);
      messaging.refresh('second-token');
      messaging.open(
        const PushNotificationRoute(
          projectId: 'proj-demo',
          agent: 'mobile',
          dedupeKey: 'first-dedupe',
          hostId: 'host-demo',
          deviceId: 'device-demo',
        ),
      );
      messaging.open(
        const PushNotificationRoute(
          projectId: 'proj-demo',
          agent: 'other',
          dedupeKey: 'wrong-device-dedupe',
          deviceId: 'wrong-device',
        ),
      );
      await _drain();
      await _waitFor(() => requests.length == 2);

      expect(requests, hasLength(2));
      expect(requests.first['path'], '/v1/devices/me/push-token');
      expect(requests.first['authorization'], 'Bearer paired-device-token');
      expect(requests.first['body'], {'token': 'first-token'});
      expect(routes.map((route) => route.agent), ['mobile']);

      await runtime.dispose();
      await subscription.cancel();
      await server.close(force: true);
    },
  );

  test('push open marks dedupe before opening route', () async {
    final messaging = _FakePushMessagingClient(token: 'token');
    final order = <String>[];
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: _AlwaysRegisteredPushRegistrationClient(),
      markSeenIfNew: (dedupeKey) async {
        order.add('seen:$dedupeKey');
        return true;
      },
      onRouteOpened: (route) async {
        order.add('open:${route.dedupeKey}');
      },
      isEnabled: () => true,
    );

    expect(await runtime.start(_host()), isTrue);
    messaging.open(
      const PushNotificationRoute(
        projectId: 'proj-demo',
        agent: 'mobile',
        dedupeKey: 'same-as-sse',
      ),
    );
    await _drain();

    expect(order, ['seen:same-as-sse', 'open:same-as-sse']);

    await runtime.dispose();
  });

  test('already seen push route is not opened again', () async {
    final messaging = _FakePushMessagingClient(token: 'token');
    final order = <String>[];
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: _AlwaysRegisteredPushRegistrationClient(),
      markSeenIfNew: (dedupeKey) async {
        order.add('seen:$dedupeKey');
        return false;
      },
      onRouteOpened: (route) async {
        order.add('open:${route.dedupeKey}');
      },
      isEnabled: () => true,
    );

    expect(await runtime.start(_host()), isTrue);
    messaging.open(
      const PushNotificationRoute(
        projectId: 'proj-demo',
        agent: 'mobile',
        dedupeKey: 'duplicate',
      ),
    );
    await _drain();

    expect(order, ['seen:duplicate']);

    await runtime.dispose();
  });

  test('foreground push reconciles without consuming SSE dedupe', () async {
    final messaging = _FakePushMessagingClient(token: 'token');
    final opened = <PushNotificationRoute>[];
    final seen = <String>[];
    final reconciled = <String>[];
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: _AlwaysRegisteredPushRegistrationClient(),
      markSeenIfNew: (dedupeKey) async {
        seen.add(dedupeKey);
        return true;
      },
      onForegroundRoute: (route) async {
        reconciled.add(route.dedupeKey);
      },
      onRouteOpened: (route) async => opened.add(route),
      isEnabled: () => true,
    );

    expect(await runtime.start(_host()), isTrue);
    messaging.foreground(
      const PushNotificationRoute(
        projectId: 'proj-demo',
        agent: 'mobile',
        dedupeKey: 'foreground',
      ),
    );
    messaging.foreground(
      const PushNotificationRoute(
        projectId: 'proj-demo',
        agent: 'mobile',
        dedupeKey: 'wrong-device',
        deviceId: 'other-device',
      ),
    );
    await _drain();

    expect(seen, isEmpty);
    expect(reconciled, ['foreground']);
    expect(opened, isEmpty);

    await runtime.dispose();
  });

  test('duplicate foreground push reconciles once in memory', () async {
    final messaging = _FakePushMessagingClient(token: 'token');
    final order = <String>[];
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: _AlwaysRegisteredPushRegistrationClient(),
      markSeenIfNew: (dedupeKey) async {
        order.add('seen:$dedupeKey');
        return true;
      },
      onForegroundRoute: (route) async {
        order.add('reconcile:${route.dedupeKey}');
      },
      onRouteOpened: (route) async {
        order.add('open:${route.dedupeKey}');
      },
      isEnabled: () => true,
    );

    expect(await runtime.start(_host()), isTrue);
    const route = PushNotificationRoute(
      projectId: 'proj-demo',
      agent: 'mobile',
      dedupeKey: 'foreground',
    );
    messaging.foreground(route);
    messaging.foreground(route);
    await _drain();

    expect(order, ['reconcile:foreground']);

    await runtime.dispose();
  });

  test(
    'identity-free route is rejected when stored profiles are ambiguous',
    () async {
      final messaging = _FakePushMessagingClient(token: 'token');
      final routes = <PushNotificationRoute>[];
      final seen = <String>[];
      final runtime = PushNotificationRuntime(
        messaging: messaging,
        registration: _AlwaysRegisteredPushRegistrationClient(),
        markSeenIfNew: (dedupeKey) async {
          seen.add(dedupeKey);
          return true;
        },
        onRouteOpened: (route) async => routes.add(route),
        isRouteProfileAmbiguous: (_) => true,
        isEnabled: () => true,
      );

      expect(await runtime.start(_host()), isTrue);
      messaging.open(
        const PushNotificationRoute(
          projectId: 'proj-demo',
          agent: 'mobile',
          dedupeKey: 'ambiguous',
        ),
      );
      await _drain();

      expect(seen, isEmpty);
      expect(routes, isEmpty);

      await runtime.dispose();
    },
  );

  test('profile switch deletes the prior registered push token', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final requests = <Map<String, Object?>>[];
    final subscription = server.listen((request) async {
      requests.add({
        'method': request.method,
        'path': request.uri.path,
        'authorization': request.headers.value(HttpHeaders.authorizationHeader),
        'body':
            request.method == 'DELETE'
                ? null
                : jsonDecode(await utf8.decodeStream(request)),
      });
      request.response.statusCode = HttpStatus.ok;
      await request.response.close();
    });
    final messaging = _FakePushMessagingClient(token: 'same-fcm-token');
    final runtime = PushNotificationRuntime(
      messaging: messaging,
      registration: GatewayPushRegistrationClient(isEnabled: () => true),
      onRouteOpened: (_) async {},
      isEnabled: () => true,
    );

    expect(await runtime.start(_host(port: server.port)), isTrue);
    expect(
      await runtime.start(
        _host(
          deviceId: 'second-device',
          deviceToken: 'second-device-token',
          port: server.port,
        ),
      ),
      isTrue,
    );
    await _drain();

    expect(
      requests.map(
        (request) => [
          request['method'],
          request['authorization'],
          request['body'],
        ],
      ),
      [
        [
          'PUT',
          'Bearer paired-device-token',
          {'token': 'same-fcm-token'},
        ],
        ['DELETE', 'Bearer paired-device-token', null],
        [
          'PUT',
          'Bearer second-device-token',
          {'token': 'same-fcm-token'},
        ],
      ],
    );

    await runtime.dispose();
    await subscription.cancel();
    await server.close(force: true);
  });
}

GatewayPairedHost _host({
  String deviceId = 'device-demo',
  String deviceToken = 'paired-device-token',
  int? port,
}) {
  return GatewayPairedHost(
    profile: GatewayHostProfile(
      hostId: 'host-demo',
      deviceId: deviceId,
      routeProvider: RouteProvider(
        kind: RouteProviderKind.lan,
        gatewayUrl: Uri.parse('http://127.0.0.1:${port ?? 8787}'),
      ),
      scopes: const {'notify'},
    ),
    deviceToken: deviceToken,
  );
}

Future<void> _drain() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

Future<void> _waitFor(bool Function() predicate) async {
  final deadline = DateTime.now().add(const Duration(seconds: 2));
  while (!predicate()) {
    if (DateTime.now().isAfter(deadline)) {
      throw TimeoutException('condition was not met before the deadline');
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

class _FakePushMessagingClient implements PushMessagingClient {
  _FakePushMessagingClient({this.permissionGranted = true, this.token});

  final bool permissionGranted;
  final String? token;
  final _refreshes = StreamController<String>.broadcast();
  final _routes = StreamController<PushNotificationRoute>.broadcast();
  final _foregroundRoutes = StreamController<PushNotificationRoute>.broadcast();
  int tokenReads = 0;

  @override
  Future<PushNotificationRoute?> getInitialRoute() async => null;

  @override
  Future<String?> getToken() async {
    tokenReads += 1;
    return token;
  }

  @override
  Future<bool> initializeAndRequestPermission() async => permissionGranted;

  @override
  Stream<PushNotificationRoute> get onRouteOpened => _routes.stream;

  @override
  Stream<PushNotificationRoute> get onForegroundRoute =>
      _foregroundRoutes.stream;

  @override
  Stream<String> get onTokenRefresh => _refreshes.stream;

  void refresh(String token) => _refreshes.add(token);

  void open(PushNotificationRoute route) => _routes.add(route);

  void foreground(PushNotificationRoute route) => _foregroundRoutes.add(route);
}

class _AlwaysRegisteredPushRegistrationClient
    implements GatewayPushRegistrationClient {
  @override
  Duration get timeout => const Duration(seconds: 10);

  @override
  Future<bool> delete({required GatewayPairedHost host}) async => true;

  @override
  Future<bool> register({
    required GatewayPairedHost host,
    required String token,
  }) async => true;

  @override
  void close({bool force = false}) {}
}
