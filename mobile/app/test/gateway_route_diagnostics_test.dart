import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test(
    'checks Cloudflare route readiness without route-specific schemas',
    () async {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.cloudflareTunnel,
          gatewayUrl: Uri.parse('https://mobile.example.com'),
          websocketUrl: Uri.parse('wss://mobile.example.com/v1/terminals/demo'),
        ),
      );

      final report =
          await GatewayRouteDiagnostics(transport: transport).check();

      expect(report.ready, isTrue);
      expect(report.summary, 'Route ready');
      expect(report.checkedProjectId, 'proj-demo');
      expect(report.toJson(), {
        'ready': true,
        'route_provider': 'cloudflare_tunnel',
        'gateway_url': 'https://mobile.example.com',
        'project_id': 'proj-demo',
        'checks': [
          {
            'code': 'gateway_url',
            'ok': true,
            'message': 'Gateway URL https://mobile.example.com',
          },
          {
            'code': 'cloudflare_origin',
            'ok': true,
            'message':
                'Cloudflare gateway URL must be an HTTPS origin without path, '
                'query, fragment, or credentials',
          },
          {
            'code': 'cloudflare_https',
            'ok': true,
            'message': 'Cloudflare gateway URL must use HTTPS',
          },
          {
            'code': 'cloudflare_wss',
            'ok': true,
            'message': 'Cloudflare WebSocket URL must use WSS',
          },
          {'code': 'gateway_health', 'ok': true, 'message': 'Gateway healthy'},
          {
            'code': 'gateway_capabilities',
            'ok': true,
            'message':
                'Gateway capabilities: http_json, project_view, websocket_terminal',
          },
          {
            'code': 'device_auth',
            'ok': true,
            'message': 'Device authenticated as dev-demo',
          },
          {
            'code': 'route_provider_scope',
            'ok': true,
            'message': 'Route provider cloudflare_tunnel for device',
          },
          {
            'code': 'device_gateway_url',
            'ok': true,
            'message': 'Device gateway URL matches profile route',
          },
          {'code': 'project_list', 'ok': true, 'message': 'Projects reachable'},
          {
            'code': 'project_view_redacted',
            'ok': true,
            'message': 'ProjectView redacted',
          },
        ],
      });
      expect(transport.calls, [
        'health',
        'device',
        'listProjects',
        'getProjectView:proj-demo',
      ]);
    },
  );

  test('checks relay route readiness through fake local transport', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.relay,
        gatewayUrl: Uri.parse('https://relay.seemlab.top'),
        websocketUrl: Uri.parse('wss://relay.seemlab.top'),
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isTrue);
    expect(report.summary, 'Route ready');
    expect(report.checkedProjectId, 'proj-demo');
    expect(report.toJson(), {
      'ready': true,
      'route_provider': 'relay',
      'gateway_url': 'https://relay.seemlab.top',
      'project_id': 'proj-demo',
      'checks': [
        {
          'code': 'gateway_url',
          'ok': true,
          'message': 'Gateway URL https://relay.seemlab.top',
        },
        {
          'code': 'relay_origin',
          'ok': true,
          'message':
              'Relay gateway URL must be an HTTPS origin without path, query, '
              'fragment, or credentials',
        },
        {
          'code': 'relay_https',
          'ok': true,
          'message': 'Relay gateway URL must use HTTPS',
        },
        {
          'code': 'relay_wss',
          'ok': true,
          'message':
              'Relay WebSocket URL must be a WSS origin without path, query, '
              'fragment, or credentials',
        },
        {'code': 'gateway_health', 'ok': true, 'message': 'Gateway healthy'},
        {
          'code': 'gateway_capabilities',
          'ok': true,
          'message':
              'Gateway capabilities: http_json, project_view, websocket_terminal',
        },
        {
          'code': 'device_auth',
          'ok': true,
          'message': 'Device authenticated as dev-demo',
        },
        {
          'code': 'route_provider_scope',
          'ok': true,
          'message': 'Route provider relay for device',
        },
        {
          'code': 'device_gateway_url',
          'ok': true,
          'message': 'Device gateway URL matches profile route',
        },
        {'code': 'project_list', 'ok': true, 'message': 'Projects reachable'},
        {
          'code': 'project_view_redacted',
          'ok': true,
          'message': 'ProjectView redacted',
        },
      ],
    });
    expect(transport.calls, [
      'health',
      'device',
      'listProjects',
      'getProjectView:proj-demo',
    ]);
  });

  test(
    'uses a listed project when server-wide host id is not a project',
    () async {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.relay,
          gatewayUrl: Uri.parse('https://relay.seemlab.top'),
          websocketUrl: Uri.parse('wss://relay.seemlab.top'),
        ),
      );

      final report = await GatewayRouteDiagnostics(
        transport: transport,
      ).check(projectId: 'host-server-wide');

      expect(report.ready, isTrue);
      expect(report.checkedProjectId, 'proj-demo');
      expect(transport.calls, [
        'health',
        'device',
        'listProjects',
        'getProjectView:proj-demo',
      ]);
    },
  );

  test('fails closed when paired device is revoked', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.lan,
        gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
      ),
      deviceRevoked: true,
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks.singleWhere((check) => check.code == 'device_auth'),
      isA<GatewayRouteDiagnosticCheck>()
          .having((check) => check.ok, 'ok', isFalse)
          .having((check) => check.message, 'message', 'Device is revoked'),
    );
  });

  test('accepts source-compatible relay health diagnostics', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.relay,
        gatewayUrl: Uri.parse('https://relay.seemlab.top'),
        websocketUrl: Uri.parse('wss://relay.seemlab.top'),
        hostFingerprint: 'host-fp-demo',
        diagnostics: const {
          'state': 'registered',
          'observed_host_fingerprint': 'host-fp-demo',
        },
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isTrue);
    expect(
      report.checks.singleWhere((check) => check.code == 'relay_host_state'),
      isA<GatewayRouteDiagnosticCheck>()
          .having((check) => check.ok, 'ok', isTrue)
          .having((check) => check.message, 'message', 'Relay host registered'),
    );
    expect(
      report.checks.singleWhere(
        (check) => check.code == 'relay_host_fingerprint',
      ),
      isA<GatewayRouteDiagnosticCheck>()
          .having((check) => check.ok, 'ok', isTrue)
          .having(
            (check) => check.message,
            'message',
            'Relay host fingerprint matches profile',
          ),
    );
  });

  test('fails relay readiness for blocking relay health states', () async {
    const states = {
      'host_disconnected': 'Relay host is disconnected',
      'unknown_host': 'Relay host is unknown to the relay',
      'relay_unreachable': 'Relay control plane is unreachable',
      'stale_device': 'Relay device authorization is stale',
      'host_fingerprint_mismatch': 'Relay host fingerprint mismatch',
    };

    for (final entry in states.entries) {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.relay,
          gatewayUrl: Uri.parse('https://relay.seemlab.top'),
          websocketUrl: Uri.parse('wss://relay.seemlab.top'),
          diagnostics: {'relay_state': entry.key},
        ),
      );

      final report =
          await GatewayRouteDiagnostics(transport: transport).check();

      expect(report.ready, isFalse, reason: entry.key);
      expect(report.summary, entry.value, reason: entry.key);
      expect(
        report.checks.singleWhere((check) => check.code == 'relay_host_state'),
        isA<GatewayRouteDiagnosticCheck>()
            .having((check) => check.ok, 'ok', isFalse)
            .having((check) => check.message, 'message', entry.value),
        reason: entry.key,
      );
    }
  });

  test('fails relay readiness for host fingerprint mismatch', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.relay,
        gatewayUrl: Uri.parse('https://relay.seemlab.top'),
        websocketUrl: Uri.parse('wss://relay.seemlab.top'),
        hostFingerprint: 'expected-fp',
        diagnostics: const {
          'state': 'ready',
          'observed_host_fingerprint': 'observed-fp',
        },
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks.where((check) => !check.ok).map((check) => check.code),
      ['relay_host_fingerprint'],
    );
    expect(
      report.summary,
      'Relay host fingerprint observed-fp does not match expected expected-fp',
    );
  });

  test('fails relay readiness for unsafe route URLs', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.relay,
        gatewayUrl: Uri.parse('http://relay.seemlab.top/pair?debug=1'),
        websocketUrl: Uri.parse('ws://relay.seemlab.top/v1/relay'),
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks.where((check) => !check.ok).map((check) => check.code),
      ['relay_origin', 'relay_https', 'relay_wss', 'device_gateway_url'],
    );
    expect(
      report.checks
          .singleWhere((check) => check.code == 'device_gateway_url')
          .message,
      'Device relay gateway URL must be an HTTPS origin without path, query, '
      'fragment, or credentials',
    );
  });

  test('fails relay readiness without a WSS relay endpoint', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.relay,
        gatewayUrl: Uri.parse('https://relay.seemlab.top'),
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks.singleWhere((check) => check.code == 'relay_wss'),
      isA<GatewayRouteDiagnosticCheck>()
          .having((check) => check.ok, 'ok', isFalse)
          .having(
            (check) => check.message,
            'message',
            'Relay WebSocket URL must be a WSS origin without path, query, '
                'fragment, or credentials',
          ),
    );
  });

  test('fails Cloudflare readiness for non-origin gateway URL', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.cloudflareTunnel,
        gatewayUrl: Uri.parse(
          'https://user:pass@mobile.example.com/pair?debug=1#token',
        ),
        websocketUrl: Uri.parse('wss://mobile.example.com/v1/terminals/demo'),
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks
          .singleWhere((check) => check.code == 'cloudflare_origin')
          .message,
      'Cloudflare gateway URL must be an HTTPS origin without path, query, '
      'fragment, or credentials',
    );
  });

  test(
    'fails readiness when device gateway URL differs from profile',
    () async {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.cloudflareTunnel,
          gatewayUrl: Uri.parse('https://mobile.example.com'),
          websocketUrl: Uri.parse('wss://mobile.example.com/v1/terminals/demo'),
        ),
        deviceGatewayUrl: Uri.parse('https://other.example.com'),
      );

      final report =
          await GatewayRouteDiagnostics(transport: transport).check();

      expect(report.ready, isFalse);
      expect(
        report.checks.singleWhere(
          (check) => check.code == 'device_gateway_url',
        ),
        isA<GatewayRouteDiagnosticCheck>()
            .having((check) => check.ok, 'ok', isFalse)
            .having(
              (check) => check.message,
              'message',
              'Device gateway URL https://other.example.com does not match '
                  'profile route https://mobile.example.com',
            ),
      );
    },
  );

  test(
    'fails readiness when device Cloudflare URL is not origin-only',
    () async {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.cloudflareTunnel,
          gatewayUrl: Uri.parse('https://mobile.example.com'),
          websocketUrl: Uri.parse('wss://mobile.example.com/v1/terminals/demo'),
        ),
        deviceGatewayUrl: Uri.parse('https://mobile.example.com/pair?debug=1'),
      );

      final report =
          await GatewayRouteDiagnostics(transport: transport).check();

      expect(report.ready, isFalse);
      expect(
        report.checks
            .singleWhere((check) => check.code == 'device_gateway_url')
            .message,
        'Device Cloudflare gateway URL must be an HTTPS origin without path, '
        'query, fragment, or credentials',
      );
    },
  );

  test('fails Cloudflare readiness for insecure route URLs', () async {
    final transport = _FakeGatewayTransport(
      RouteProvider(
        kind: RouteProviderKind.cloudflareTunnel,
        gatewayUrl: Uri.parse('http://mobile.example.com'),
        websocketUrl: Uri.parse('ws://mobile.example.com/v1/terminals/demo'),
      ),
    );

    final report = await GatewayRouteDiagnostics(transport: transport).check();

    expect(report.ready, isFalse);
    expect(
      report.checks.where((check) => !check.ok).map((check) => check.code),
      ['cloudflare_https', 'cloudflare_wss'],
    );
  });

  test(
    'fails readiness when ProjectView exposes tmux attach evidence',
    () async {
      final transport = _FakeGatewayTransport(
        RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
        ),
        exposeTmuxEvidence: true,
      );

      final report =
          await GatewayRouteDiagnostics(transport: transport).check();

      expect(report.ready, isFalse);
      expect(
        report.checks
            .singleWhere((check) => check.code == 'project_view_redacted')
            .message,
        'ProjectView exposes tmux attach evidence',
      );
    },
  );
}

class _FakeGatewayTransport implements GatewayTransport {
  _FakeGatewayTransport(
    this.routeProvider, {
    this.exposeTmuxEvidence = false,
    this.deviceGatewayUrl,
    this.deviceRevoked = false,
  });

  @override
  Future<GatewayFileUploadResult> uploadFile({
    required String projectId,
    required String agentName,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  }) => throw UnimplementedError();

  @override
  Future<List<int>> downloadFile({
    required String projectId,
    required String agentName,
    required String fileId,
  }) => throw UnimplementedError();

  final RouteProvider routeProvider;
  final bool exposeTmuxEvidence;
  final Uri? deviceGatewayUrl;
  final bool deviceRevoked;
  final calls = <String>[];

  @override
  GatewayHostProfile get profile {
    return GatewayHostProfile(
      hostId: 'host-demo',
      deviceId: 'dev-demo',
      routeProvider: routeProvider,
      scopes: const {'view', 'focus', 'terminal_input'},
    );
  }

  @override
  Future<GatewayHealth> health() async {
    calls.add('health');
    return GatewayHealth(
      status: 'ok',
      serverTime: DateTime.utc(2026, 6, 18),
      capabilities: const {'http_json', 'project_view', 'websocket_terminal'},
    );
  }

  @override
  Future<GatewayDevice> device() async {
    calls.add('device');
    return GatewayDevice(
      deviceId: 'dev-demo',
      projectId: 'proj-demo',
      scopes: const {'view', 'focus', 'terminal_input'},
      routeProvider: routeProvider.kind,
      gatewayUrl: deviceGatewayUrl ?? routeProvider.gatewayUrl,
      revoked: deviceRevoked,
    );
  }

  @override
  Future<List<CcbProject>> listProjects() async {
    calls.add('listProjects');
    return [_project()];
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) async {
    calls.add('getProjectView:$projectId');
    return _view(exposeTmuxEvidence: exposeTmuxEvidence);
  }

  @override
  Future<CcbProjectView> focusAgent({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
  }) {
    throw UnimplementedError();
  }

  @override
  Future<CcbProjectView> focusWindow({
    required String projectId,
    required String window,
    required int namespaceEpoch,
  }) {
    throw UnimplementedError();
  }

  @override
  Future<ReadableTerminalHistory?> getReadableTerminalHistory({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int maxLines = 200,
  }) {
    throw UnimplementedError();
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) {
    throw UnimplementedError();
  }

  @override
  Future<CcbAgentMessageSubmitResult> submitAgentMessage(
    CcbAgentMessageSubmitRequest request,
  ) {
    throw UnimplementedError();
  }

  @override
  Future<CcbProjectLifecycleResult> requestLifecycle({
    required String projectId,
    required CcbLifecycleAction action,
  }) {
    throw UnimplementedError();
  }

  @override
  Future<GatewayTerminalHandle> openTerminal(
    GatewayTerminalOpenRequest request,
  ) {
    throw UnimplementedError();
  }

  @override
  Future<void> sendTerminalFrame(
    GatewayTerminalHandle handle,
    GatewayTerminalFrame frame,
  ) {
    throw UnimplementedError();
  }

  @override
  Stream<GatewayTerminalFrame> terminalFrames(
    GatewayTerminalHandle handle, {
    int? resumeCursor,
  }) {
    throw UnimplementedError();
  }
}

CcbProject _project() => _view().project;

CcbProjectView _view({bool exposeTmuxEvidence = false}) {
  return CcbProjectView.fromProjectViewPayload({
    'view': {
      'project': {
        'id': 'proj-demo',
        'root': '/srv/ccb/demo',
        'display_name': 'demo',
      },
      'namespace': {
        'epoch': 4,
        if (exposeTmuxEvidence) 'socket_path': '/tmp/ccb-demo/tmux.sock',
        if (exposeTmuxEvidence) 'session_name': 'ccb-demo',
        'active_window': 'main',
        'active_pane_id': '%2',
      },
      'windows': [
        {
          'name': 'main',
          'label': 'main',
          'kind': 'agents',
          'order': 0,
          'active': true,
          'agents': ['mobile'],
        },
      ],
      'agents': [
        {
          'name': 'mobile',
          'provider': 'codex',
          'window': 'main',
          'order': 0,
          'pane_id': '%2',
          'active': true,
        },
      ],
    },
  });
}
