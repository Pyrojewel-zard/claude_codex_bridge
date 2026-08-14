import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/mobile_connection_supervisor.dart';
import 'package:ccb_mobile/features/project_home/project_home_runtime_activation.dart';
import 'package:test/test.dart';

void main() {
  late HttpServer server;
  late HttpGatewayTransport transport;
  late GatewayMobileCcbRepository repository;
  final requests = <String>[];
  final queries = <String>[];
  final bodies = <String>[];
  var failDeviceProbe = false;

  setUp(() async {
    requests.clear();
    queries.clear();
    bodies.clear();
    failDeviceProbe = false;
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      if (request.method == 'GET' &&
          request.uri.path ==
              '/v1/projects/proj-demo/agents/mobile/files/file-1') {
        requests.add(request.uri.path);
        queries.add(request.uri.query);
        bodies.add('');
        request.response.headers.contentType = ContentType.binary;
        request.response.add([9, 8, 7]);
        await request.response.close();
        return;
      }
      final body = await utf8.decodeStream(request);
      requests.add(request.uri.path);
      queries.add(request.uri.query);
      bodies.add(body);
      if (request.uri.path == '/v1/health') {
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({'status': 'ok', 'server_time': '2026-07-13T00:00:00Z'}),
        );
        await request.response.close();
        return;
      }
      if (request.uri.path == '/v1/devices/me' && failDeviceProbe) {
        request.response.headers.contentType = ContentType.json;
        request.response.statusCode = HttpStatus.serviceUnavailable;
        request.response.write(jsonEncode({'status': 'error'}));
        await request.response.close();
        return;
      }
      if (request.uri.path == '/v1/devices/me') {
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'device': {
              'device_id': 'device-demo',
              'project_id': 'proj-demo',
              'scopes': ['view'],
              'route_provider': 'lan',
              'revoked': false,
            },
          }),
        );
        await request.response.close();
        return;
      }
      final payload = _payloadForRequest(
        request.method,
        request.uri.path,
        body,
      );
      request.response.headers.contentType = ContentType.json;
      request.response.statusCode = payload.statusCode;
      request.response.write(jsonEncode(payload.body));
      await request.response.close();
    });

    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    transport = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'host-demo',
        deviceId: 'device-demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view', 'focus'},
      ),
      deviceToken: 'device-secret',
    );
    repository = GatewayMobileCcbRepository(transport: transport);
  });

  tearDown(() async {
    transport.close(force: true);
    await server.close(force: true);
  });

  test('lists and loads projects through the G1 gateway shape', () async {
    final projects = await repository.listProjects();
    final view = await repository.getProjectView(projects.single.id);

    expect(projects.single.id, 'proj-demo');
    expect(projects.single.root, '');
    expect(view.project.root, '/srv/demo');
    expect(view.namespaceEpoch, 4);
    expect(view.tmuxSocketPath, isNull);
    expect(view.tmuxSessionName, isNull);
    expect(view.agentByName('mobile')?.active, isTrue);
    expect(requests, ['/v1/projects', '/v1/projects/proj-demo/view']);
  });

  test(
    'core probe does not report online after health succeeds then device fails',
    () async {
      failDeviceProbe = true;
      final states = <MobileConnectionState>[];
      final reconnecting = Completer<void>();
      final supervisor = MobileConnectionSupervisor(
        onChanged: (snapshot) {
          states.add(snapshot.state);
          if (snapshot.state == MobileConnectionState.reconnecting &&
              !reconnecting.isCompleted) {
            reconnecting.complete();
          }
        },
        initialDelay: const Duration(hours: 1),
        maxDelay: const Duration(hours: 1),
      );
      repository.outcomeReporter = MobileConnectionOutcomeAdapter(
        supervisor: supervisor,
        isCurrent: () => true,
      );

      supervisor.start(
        profile: GatewayPairedHost(
          profile: transport.profile,
          deviceToken: 'device-secret',
        ),
        probe: repository,
      );
      await reconnecting.future.timeout(const Duration(seconds: 2));

      expect(states, isNot(contains(MobileConnectionState.online)));
      expect(supervisor.snapshot.state, MobileConnectionState.reconnecting);
      supervisor.dispose();
    },
  );

  test(
    'activation core verification never reports online when device fails',
    () async {
      failDeviceProbe = true;
      final states = <MobileConnectionState>[];
      final supervisor = MobileConnectionSupervisor(
        onChanged: (snapshot) => states.add(snapshot.state),
      );
      repository.outcomeReporter = MobileConnectionOutcomeAdapter(
        supervisor: supervisor,
        isCurrent: () => true,
      );
      supervisor.start(
        profile: GatewayPairedHost(
          profile: transport.profile,
          deviceToken: 'device-secret',
        ),
        probeImmediately: false,
      );

      await expectLater(
        verifyProjectHomeGatewayProfile(repository),
        throwsA(isA<ProjectHomeGatewayActivationException>()),
      );

      expect(states, isNot(contains(MobileConnectionState.online)));
      expect(supervisor.snapshot.state, MobileConnectionState.reconnecting);
      supervisor.dispose();
    },
  );

  test(
    'activation core verification reports one recovery after complete success',
    () async {
      final states = <MobileConnectionState>[];
      final supervisor = MobileConnectionSupervisor(
        onChanged: (snapshot) => states.add(snapshot.state),
      );
      repository.outcomeReporter = MobileConnectionOutcomeAdapter(
        supervisor: supervisor,
        isCurrent: () => true,
      );
      supervisor.start(
        profile: GatewayPairedHost(
          profile: transport.profile,
          deviceToken: 'device-secret',
        ),
        probeImmediately: false,
      );

      await verifyProjectHomeGatewayProfile(repository);

      expect(states, [
        MobileConnectionState.connecting,
        MobileConnectionState.online,
      ]);
      supervisor.dispose();
    },
  );

  test('focuses through authenticated gateway routes', () async {
    final agentView = await repository.focusAgent(
      projectId: 'proj-demo',
      agent: 'mobile',
      namespaceEpoch: 4,
    );
    final windowView = await repository.focusWindow(
      projectId: 'proj-demo',
      window: 'main',
      namespaceEpoch: 4,
    );

    expect(agentView.agentByName('mobile')?.active, isTrue);
    expect(windowView.activeWindow, 'main');
    expect(requests, [
      '/v1/projects/proj-demo/focus-agent',
      '/v1/projects/proj-demo/focus-window',
    ]);
    expect(jsonDecode(bodies.first), {'agent': 'mobile', 'namespace_epoch': 4});
    expect(jsonDecode(bodies.last), {'window': 'main', 'namespace_epoch': 4});
  });

  test(
    'loads readable terminal history through authenticated gateway route',
    () async {
      final history = await repository.getReadableTerminalHistory(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
        maxLines: 120,
      );

      expect(history?.agentName, 'mobile');
      expect(history?.historyScope, 'tmux_scrollback');
      expect(history?.sourcePaneId, '%2');
      expect(history?.blocks.map((item) => item.type), ['command', 'log']);
      expect(requests, ['/v1/projects/proj-demo/terminal-history']);
      expect(queries.single, contains('agent=mobile'));
      expect(queries.single, contains('namespace_epoch=4'));
      expect(queries.single, contains('max_lines=120'));
    },
  );

  test(
    'loads and submits selected-agent conversation through repository',
    () async {
      final conversation = await repository.getAgentConversation(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
        limit: 25,
      );
      final result = await repository.submitAgentMessage(
        CcbAgentMessageSubmitRequest(
          projectId: 'proj-demo',
          agentName: 'mobile',
          namespaceEpoch: 4,
          idempotencyKey: 'mobile-msg-1',
          body: 'continue with the next step',
        ),
      );

      expect(conversation.items.single.body, 'Ready for the next task.');
      expect(result.accepted, isTrue);
      expect(result.messageId, 'msg-1');
      expect(result.message?.state, CcbConversationDeliveryState.sent);
      expect(requests, [
        '/v1/projects/proj-demo/agents/mobile/conversation',
        '/v1/projects/proj-demo/agents/mobile/messages',
      ]);
      expect(queries.first, contains('namespace_epoch=4'));
      expect(queries.first, contains('limit=25'));
      expect(jsonDecode(bodies.last), {
        'schema_version': 1,
        'project_id': 'proj-demo',
        'agent': 'mobile',
        'namespace_epoch': 4,
        'idempotency_key': 'mobile-msg-1',
        'body': 'continue with the next step',
        'format': 'markdown',
      });
      expect(bodies.last, isNot(contains('terminal_input')));
    },
  );

  test('requests lifecycle through authenticated gateway route', () async {
    final result = await repository.requestLifecycle(
      projectId: 'proj-demo',
      action: CcbLifecycleAction.stop,
    );

    expect(result.projectId, 'proj-demo');
    expect(result.action, CcbLifecycleAction.stop);
    expect(result.effect, 'ccbd_stop_requested');
    expect(result.ccbAuthority, isTrue);
    expect(result.tmuxKillServer, isFalse);
    expect(requests, ['/v1/projects/proj-demo/lifecycle']);
    expect(jsonDecode(bodies.single), {
      'project_id': 'proj-demo',
      'action': 'stop',
    });
  });

  test(
    'uploads and downloads report their distinct outcomes through repository',
    () async {
      final reporter = _RecordingOutcomeReporter();
      repository.outcomeReporter = reporter;
      final uploaded = await repository.uploadFile(
        projectId: 'proj-demo',
        agentName: 'mobile',
        fileName: 'notes.txt',
        mimeType: 'text/plain',
        bytes: [1, 2, 3],
      );
      final downloaded = await repository.downloadFile(
        projectId: 'proj-demo',
        agentName: 'mobile',
        fileId: uploaded.fileId,
      );

      expect(uploaded.fileId, 'file-1');
      expect(uploaded.fileName, 'notes.txt');
      expect(downloaded, [9, 8, 7]);
      expect(requests, [
        '/v1/projects/proj-demo/agents/mobile/files',
        '/v1/projects/proj-demo/agents/mobile/files/file-1',
      ]);
      expect(bodies.first, String.fromCharCodes([1, 2, 3]));
      expect(reporter.successes, [
        GatewayConnectionOperation.mutation,
        GatewayConnectionOperation.dataRead,
      ]);
    },
  );
}

class _RecordingOutcomeReporter implements GatewayConnectionOutcomeReporter {
  final successes = <GatewayConnectionOperation>[];
  final failures = <GatewayConnectionOperation>[];

  @override
  void failed(GatewayConnectionOperation operation, Object error) {
    failures.add(operation);
  }

  @override
  void succeeded(GatewayConnectionOperation operation) {
    successes.add(operation);
  }
}

_GatewayResponse _payloadForRequest(String method, String path, String body) {
  if (method == 'POST' &&
      (path == '/v1/projects/proj-demo/focus-agent' ||
          path == '/v1/projects/proj-demo/focus-window')) {
    return _GatewayResponse({
      'focus': {
        'focused': true,
        'kind': path.endsWith('focus-agent') ? 'agent' : 'window',
        'window': 'main',
        'agent': path.endsWith('focus-agent') ? 'mobile' : null,
        'namespace_epoch': 4,
      },
      ..._projectViewBody(),
    });
  }
  if (method == 'POST' && path == '/v1/projects/proj-demo/lifecycle') {
    final decoded = jsonDecode(body);
    final action = decoded is Map ? decoded['action'] : null;
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'project_id': 'proj-demo',
      'lifecycle': {
        'action': action,
        'state': action == 'stop' ? 'stopping' : 'running',
        'effect': action == 'stop' ? 'ccbd_stop_requested' : 'opened',
        'forced': false,
        'ccb_authority': true,
        'tmux_kill_server': false,
        'updated_at': '2026-06-21T00:00:00Z',
      },
    });
  }
  if (method == 'POST' &&
      path == '/v1/projects/proj-demo/agents/mobile/messages') {
    final decoded = jsonDecode(body);
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'message_submit': {
        'accepted': true,
        'idempotency_key': decoded is Map ? decoded['idempotency_key'] : '',
        'message_id': 'msg-1',
        'state': 'sent',
        'message': {
          'id': 'msg-1',
          'agent': 'mobile',
          'kind': 'user_message',
          'title': 'You',
          'body': decoded is Map ? decoded['body'] : '',
          'format': 'markdown',
          'state': 'sent',
          'source': 'mobile',
        },
      },
    });
  }
  if (method == 'POST' &&
      path == '/v1/projects/proj-demo/agents/mobile/files') {
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'file_id': 'file-1',
      'file_name': 'notes.txt',
      'mime_type': 'text/plain',
      'size_bytes': body.length,
    });
  }
  return switch (path) {
    '/v1/projects' => _GatewayResponse({
      'schema_version': 1,
      'projects': [
        {
          'id': 'proj-demo',
          'display_name': 'demo',
          'health': 'healthy',
          'capabilities': ['http_json', 'project_view'],
        },
      ],
    }),
    '/v1/projects/proj-demo/view' => _GatewayResponse(_projectViewBody()),
    '/v1/projects/proj-demo/terminal-history' => _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'project_id': 'proj-demo',
      'terminal_history': {
        'agent': 'mobile',
        'history_scope': 'tmux_scrollback',
        'source_pane_id': '%2',
        'generated_at': '2026-06-20T10:00:00Z',
        'stale': false,
        'blocks': [
          {
            'id': 'history-1',
            'type': 'command',
            'title': 'Command',
            'text': 'flutter test',
          },
          {
            'id': 'history-2',
            'type': 'log',
            'title': 'Log',
            'text': '54 tests passed',
          },
        ],
      },
    }),
    '/v1/projects/proj-demo/agents/mobile/conversation' => _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'conversation': {
        'project_id': 'proj-demo',
        'agent': 'mobile',
        'namespace_epoch': 4,
        'items': [
          {
            'id': 'reply-1',
            'agent': 'mobile',
            'kind': 'agent_reply',
            'title': 'Agent reply',
            'body': 'Ready for the next task.',
            'format': 'markdown',
            'source': 'ccb',
          },
        ],
      },
    }),
    _ => _GatewayResponse({'status': 'error', 'error': 'not found'}, 404),
  };
}

Map<String, Object?> _projectViewBody() {
  return {
    'view': {
      'project': {
        'id': 'proj-demo',
        'root': '/srv/demo',
        'display_name': 'demo',
      },
      'namespace': {
        'epoch': 4,
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
      'comms': [],
    },
    'cache': {'sequence': 1},
  };
}

class _GatewayResponse {
  const _GatewayResponse(this.body, [this.statusCode = 200]);

  final Map<String, Object?> body;
  final int statusCode;
}
