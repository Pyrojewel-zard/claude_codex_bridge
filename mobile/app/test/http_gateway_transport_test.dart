import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  late HttpServer server;
  late HttpGatewayTransport transport;
  final requests = <String>[];
  final queries = <String>[];
  final bodies = <String>[];
  final authorizations = <String?>[];
  final contentLengths = <int>[];
  final fileNameHeaders = <String?>[];
  final contentTypes = <String?>[];
  final terminalMessages = <Map<String, Object?>>[];
  final projectListPayloads = <Map<String, Object?>>[];

  setUp(() async {
    requests.clear();
    queries.clear();
    bodies.clear();
    authorizations.clear();
    contentLengths.clear();
    fileNameHeaders.clear();
    contentTypes.clear();
    terminalMessages.clear();
    projectListPayloads.clear();
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      requests.add(request.uri.path);
      queries.add(request.uri.query);
      final authorization = request.headers.value(
        HttpHeaders.authorizationHeader,
      );
      authorizations.add(authorization);
      contentLengths.add(request.headers.contentLength);
      fileNameHeaders.add(request.headers.value('X-Ccb-File-Name'));
      contentTypes.add(request.headers.contentType?.mimeType);
      if (request.uri.path == '/v1/terminals/term_demo_mobile') {
        bodies.add('');
        final socket = await WebSocketTransformer.upgrade(request);
        socket.listen((message) {
          final decoded = jsonDecode(message.toString());
          if (decoded is Map) {
            terminalMessages.add({
              for (final entry in decoded.entries)
                entry.key.toString(): entry.value,
            });
          }
          if (decoded is Map && decoded['type'] == 'open') {
            socket.add(
              jsonEncode(
                GatewayTerminalFrame.output(
                  sequence: 1,
                  bytes: utf8.encode('hello'),
                ).toJson(),
              ),
            );
          }
          if (decoded is Map && decoded['type'] == 'closed') {
            socket.add(
              jsonEncode(GatewayTerminalFrame.closed('client_closed').toJson()),
            );
            unawaited(socket.close());
          }
        });
        return;
      }
      if (request.method == 'GET' &&
          request.uri.path ==
              '/v1/projects/proj-demo/agents/mobile/files/file-1') {
        bodies.add('');
        request.response.headers.contentType = ContentType.binary;
        request.response.add([1, 2, 3, 4]);
        await request.response.close();
        return;
      }
      final body = await utf8.decodeStream(request);
      bodies.add(body);
      final payload =
          request.uri.path == '/v1/projects' && projectListPayloads.isNotEmpty
          ? _GatewayResponse(projectListPayloads.removeAt(0))
          : _payloadForRequest(
              request.method,
              request.uri.path,
              body,
              authorization,
              request.headers.value(HttpHeaders.hostHeader),
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
        scopes: {'view'},
      ),
    );
  });

  tearDown(() async {
    transport.close(force: true);
    await server.close(force: true);
  });

  test('reads G1 health from loopback gateway JSON', () async {
    final health = await transport.health();

    expect(health.status, 'ok');
    expect(health.serverTime, DateTime.utc(2026, 6, 18));
    expect(health.capabilities, {'http_json', 'project_view'});
    expect(requests, ['/v1/health']);
  });

  test('terminal WebSocket heartbeat is enabled by default', () {
    expect(transport.terminalPingInterval, const Duration(seconds: 15));
  });

  test(
    'reads paired device identity through authenticated gateway route',
    () async {
      final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
      final authed = HttpGatewayTransport(
        profile: GatewayHostProfile(
          hostId: 'host-demo',
          deviceId: 'dev-demo',
          routeProvider: RouteProvider(
            kind: RouteProviderKind.cloudflareTunnel,
            gatewayUrl: baseUrl,
          ),
          scopes: {'view', 'focus', 'terminal_input', 'lifecycle'},
        ),
        deviceToken: 'device-secret',
      );
      try {
        final device = await authed.device();

        expect(device.deviceId, 'dev-demo');
        expect(device.projectId, 'proj-demo');
        expect(device.routeProvider, RouteProviderKind.cloudflareTunnel);
        expect(device.gatewayUrl, baseUrl);
        expect(device.scopes, {'view', 'focus', 'terminal_input', 'lifecycle'});
        expect(device.revoked, isFalse);
        expect(requests, ['/v1/devices/me']);
        expect(authorizations, ['Bearer device-secret']);
      } finally {
        authed.close(force: true);
      }
    },
  );

  test('reports redacted device presence with bearer identity', () async {
    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    final authed = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'host-demo',
        deviceId: 'dev-demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view'},
      ),
      deviceToken: 'device-secret',
    );
    addTearDown(() => authed.close(force: true));

    await authed.reportPresence(
      visible: true,
      focusedProjectId: 'proj-demo',
      focusedAgent: 'mobile',
      userActivity: true,
    );

    expect(requests, ['/v1/devices/me/presence']);
    expect(authorizations, ['Bearer device-secret']);
    expect(jsonDecode(bodies.single), {
      'visible': true,
      'focused_project_id': 'proj-demo',
      'focused_agent': 'mobile',
      'user_activity': true,
    });
  });

  test('reads current-project list from G1 gateway JSON', () async {
    final projects = await transport.listProjects();

    expect(projects, hasLength(1));
    expect(projects.single.id, 'proj-demo');
    expect(projects.single.displayName, 'demo');
    expect(projects.single.root, '');
    expect(projects.single.health, 'healthy');
    expect(projects.single.lastOpenedAt, DateTime.utc(2026, 7, 4, 9));
    expect(projects.single.lastActivityAt, DateTime.utc(2026, 7, 4, 9, 2));
    expect(requests, ['/v1/projects']);
  });

  test(
    'waits for server-wide project health warmup before returning',
    () async {
      projectListPayloads.addAll([
        {
          'schema_version': 1,
          'projects': <Object?>[],
          'health_warming': true,
          'health_unknown_project_count': 1,
        },
        {
          'schema_version': 1,
          'projects': [
            {
              'id': 'proj-live',
              'display_name': 'live',
              'health': 'healthy',
              'capabilities': ['http_json', 'project_view'],
            },
          ],
          'health_warming': false,
          'health_unknown_project_count': 0,
        },
      ]);
      final warmupTransport = HttpGatewayTransport(
        profile: transport.profile,
        projectListWarmupRetryDelay: Duration.zero,
        projectListWarmupMaxAttempts: 3,
      );
      addTearDown(() => warmupTransport.close(force: true));

      final projects = await warmupTransport.listProjects();

      expect(projects.map((project) => project.id), ['proj-live']);
      expect(requests, ['/v1/projects', '/v1/projects']);
    },
  );

  test(
    'reads redacted ProjectView without route or tmux attach evidence',
    () async {
      final view = await transport.getProjectView('proj-demo');

      expect(view.project.id, 'proj-demo');
      expect(view.namespaceEpoch, 4);
      expect(view.tmuxSocketPath, isNull);
      expect(view.tmuxSessionName, isNull);
      expect(view.agentByName('mobile')?.paneId, '%2');

      final target = view.terminalTargetForAgent('mobile');
      expect(target.canAcceptTerminalInput, isTrue);
      expect(target.hasDirectTmuxAttachEvidence, isFalse);
      expect(
        GatewayTerminalOpenRequest.fromCcbTarget(target).toJson().toString(),
        isNot(contains('tmux.sock')),
      );
      expect(requests, ['/v1/projects/proj-demo/view']);
    },
  );

  test('focuses agent and window through G2 authenticated routes', () async {
    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    final authed = HttpGatewayTransport(
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
    try {
      final agentView = await authed.focusAgent(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
      );
      final windowView = await authed.focusWindow(
        projectId: 'proj-demo',
        window: 'main',
        namespaceEpoch: 4,
      );

      expect(agentView.project.id, 'proj-demo');
      expect(windowView.activeWindow, 'main');
      expect(requests, [
        '/v1/projects/proj-demo/focus-agent',
        '/v1/projects/proj-demo/focus-window',
      ]);
      expect(authorizations, ['Bearer device-secret', 'Bearer device-secret']);
      expect(contentLengths, everyElement(greaterThan(0)));
      expect(jsonDecode(bodies.first), {
        'agent': 'mobile',
        'namespace_epoch': 4,
      });
      expect(jsonDecode(bodies.last), {'window': 'main', 'namespace_epoch': 4});
    } finally {
      authed.close(force: true);
    }
  });

  test(
    'requests project lifecycle through authenticated gateway route',
    () async {
      final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
      final authed = HttpGatewayTransport(
        profile: GatewayHostProfile(
          hostId: 'host-demo',
          deviceId: 'device-demo',
          routeProvider: RouteProvider(
            kind: RouteProviderKind.lan,
            gatewayUrl: baseUrl,
          ),
          scopes: {'view', 'focus', 'terminal_input', 'lifecycle'},
        ),
        deviceToken: 'device-secret',
      );
      try {
        final opened = await authed.requestLifecycle(
          projectId: 'proj-demo',
          action: CcbLifecycleAction.open,
        );
        final stopped = await authed.requestLifecycle(
          projectId: 'proj-demo',
          action: CcbLifecycleAction.stop,
        );

        expect(opened.action, CcbLifecycleAction.open);
        expect(opened.effect, 'opened');
        expect(opened.view?.project.id, 'proj-demo');
        expect(stopped.action, CcbLifecycleAction.stop);
        expect(stopped.effect, 'ccbd_stop_requested');
        expect(stopped.ccbAuthority, isTrue);
        expect(stopped.tmuxKillServer, isFalse);
        expect(requests, [
          '/v1/projects/proj-demo/lifecycle',
          '/v1/projects/proj-demo/lifecycle',
        ]);
        expect(authorizations, [
          'Bearer device-secret',
          'Bearer device-secret',
        ]);
        expect(jsonDecode(bodies.first), {
          'project_id': 'proj-demo',
          'action': 'open',
        });
        expect(jsonDecode(bodies.last), {
          'project_id': 'proj-demo',
          'action': 'stop',
        });
      } finally {
        authed.close(force: true);
      }
    },
  );

  test(
    'reads and submits selected-agent conversation over HTTP routes',
    () async {
      final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
      final authed = HttpGatewayTransport(
        profile: GatewayHostProfile(
          hostId: 'host-demo',
          deviceId: 'device-demo',
          routeProvider: RouteProvider(
            kind: RouteProviderKind.lan,
            gatewayUrl: baseUrl,
          ),
          scopes: {'view', 'focus', 'message_submit'},
        ),
        deviceToken: 'device-secret',
      );
      try {
        final conversation = await authed.getAgentConversation(
          projectId: 'proj-demo',
          agent: 'mobile',
          namespaceEpoch: 4,
          limit: 25,
          cursor: 'cursor-1',
        );
        final result = await authed.submitAgentMessage(
          CcbAgentMessageSubmitRequest(
            projectId: 'proj-demo',
            agentName: 'mobile',
            namespaceEpoch: 4,
            idempotencyKey: 'mobile-msg-1',
            body: 'continue with the next step',
          ),
        );

        expect(conversation.projectId, 'proj-demo');
        expect(conversation.agentName, 'mobile');
        expect(
          conversation.items.single.kind,
          CcbConversationItemKind.agentReply,
        );
        expect(conversation.items.single.body, 'Ready for the next task.');
        expect(result.accepted, isTrue);
        expect(result.messageId, 'msg-1');
        expect(result.state, CcbConversationDeliveryState.sent);
        expect(result.message?.body, 'continue with the next step');
        expect(requests, [
          '/v1/projects/proj-demo/agents/mobile/conversation',
          '/v1/projects/proj-demo/agents/mobile/messages',
        ]);
        expect(queries.first, contains('namespace_epoch=4'));
        expect(queries.first, contains('limit=25'));
        expect(queries.first, contains('cursor=cursor-1'));
        expect(authorizations, [
          'Bearer device-secret',
          'Bearer device-secret',
        ]);
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
        expect(bodies.last, isNot(contains('tmux')));
      } finally {
        authed.close(force: true);
      }
    },
  );

  test(
    'uploads and downloads selected-agent attachments over HTTP routes',
    () async {
      final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
      final authed = HttpGatewayTransport(
        profile: GatewayHostProfile(
          hostId: 'host-demo',
          deviceId: 'device-demo',
          routeProvider: RouteProvider(
            kind: RouteProviderKind.lan,
            gatewayUrl: baseUrl,
          ),
          scopes: {'view', 'focus', 'message_submit', 'file_upload'},
        ),
        deviceToken: 'device-secret',
      );
      try {
        final uploaded = await authed.uploadFile(
          projectId: 'proj-demo',
          agentName: 'mobile',
          fileName: 'notes.txt',
          mimeType: 'text/plain',
          bytes: 'hello'.codeUnits,
        );
        final downloaded = await authed.downloadFile(
          projectId: 'proj-demo',
          agentName: 'mobile',
          fileId: 'file-1',
        );

        expect(uploaded.fileId, 'file-1');
        expect(uploaded.fileName, 'notes.txt');
        expect(uploaded.mimeType, 'text/plain');
        expect(uploaded.sizeBytes, 5);
        expect(downloaded, [1, 2, 3, 4]);
        expect(requests, [
          '/v1/projects/proj-demo/agents/mobile/files',
          '/v1/projects/proj-demo/agents/mobile/files/file-1',
        ]);
        expect(authorizations, [
          'Bearer device-secret',
          'Bearer device-secret',
        ]);
        expect(fileNameHeaders.first, Uri.encodeComponent('notes.txt'));
        expect(contentTypes.first, 'text/plain');
        expect(bodies.first, 'hello');
      } finally {
        authed.close(force: true);
      }
    },
  );

  test('opens terminal through gateway terminal-open route', () async {
    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    final authed = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'host-demo',
        deviceId: 'device-demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view', 'focus', 'terminal_input'},
      ),
      deviceToken: 'device-secret',
    );
    try {
      final view = CcbProjectView.fromProjectViewPayload(_projectViewBody());
      final request = GatewayTerminalOpenRequest.fromCcbTarget(
        view.terminalTargetForAgent('mobile'),
        geometry: const TerminalGeometry(
          columns: 100,
          rows: 30,
          pixelWidth: 960,
          pixelHeight: 640,
        ),
      );

      final handle = await authed.openTerminal(request);

      expect(handle.terminalId, 'term_demo_mobile');
      expect(handle.terminalToken, 'terminal-secret');
      expect(handle.expiresAt, DateTime.utc(2026, 6, 18, 0, 5));
      expect(
        handle.websocketUrl,
        Uri.parse(
          'ws://127.0.0.1:${server.port}/v1/terminals/term_demo_mobile',
        ),
      );
      expect(handle.targetEpoch, 4);
      expect(handle.targetSummary.toJson(), {
        'project_id': 'proj-demo',
        'agent': 'mobile',
        'window': 'main',
      });
      expect(requests, ['/v1/projects/proj-demo/terminals']);
      expect(authorizations, ['Bearer device-secret']);
      expect(contentLengths.single, greaterThan(0));
      expect(jsonDecode(bodies.single), request.toJson());
      expect(bodies.single, isNot(contains('tmux.sock')));
      expect(bodies.single, isNot(contains('ccb-demo')));
    } finally {
      authed.close(force: true);
    }
  });

  test('streams terminal frames through gateway websocket', () async {
    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    final authed = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'host-demo',
        deviceId: 'device-demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view', 'focus', 'terminal_input'},
      ),
      deviceToken: 'device-secret',
    );
    final output = Completer<GatewayTerminalFrame>();
    final closed = Completer<GatewayTerminalFrame>();
    StreamSubscription<GatewayTerminalFrame>? subscription;
    try {
      final handle = await authed.openTerminal(
        GatewayTerminalOpenRequest(
          target: GatewayTerminalTarget(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            kind: CcbTerminalTargetKind.agent,
            agent: 'mobile',
            window: 'main',
          ),
        ),
      );
      subscription = authed.terminalFrames(handle).listen((frame) {
        if (frame.type == GatewayTerminalFrameType.output &&
            !output.isCompleted) {
          output.complete(frame);
        }
        if (frame.type == GatewayTerminalFrameType.closed &&
            !closed.isCompleted) {
          closed.complete(frame);
        }
      });

      final outputFrame = await output.future.timeout(
        const Duration(seconds: 2),
      );
      expect(outputFrame.toJson(), {
        'type': 'output',
        'seq': 1,
        'bytes_b64': base64Encode(utf8.encode('hello')),
      });
      expect(terminalMessages.first, {
        'type': 'open',
        'terminal_id': 'term_demo_mobile',
        'token': 'terminal-secret',
      });

      await authed.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.input(sequence: 1, bytes: [0x61]),
      );
      await authed.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.paste(sequence: 2, text: 'paste me'),
      );
      await authed.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.resize(
          const TerminalGeometry(columns: 120, rows: 36),
        ),
      );
      await authed.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.closed('client_closed'),
      );

      final closedFrame = await closed.future.timeout(
        const Duration(seconds: 2),
      );
      expect(closedFrame.toJson(), {
        'type': 'closed',
        'reason': 'client_closed',
      });
      await _waitFor(() => terminalMessages.length >= 5);
      expect(terminalMessages[1], {
        'type': 'input',
        'seq': 1,
        'bytes_b64': base64Encode([0x61]),
      });
      expect(terminalMessages[2], {
        'type': 'paste',
        'seq': 2,
        'text': 'paste me',
      });
      expect(terminalMessages[3], {
        'type': 'resize',
        'columns': 120,
        'rows': 36,
        'pixel_width': 0,
        'pixel_height': 0,
      });
    } finally {
      await subscription?.cancel();
      authed.close(force: true);
    }
  });

  test('sends terminal resume cursor on websocket open', () async {
    final baseUrl = Uri.parse('http://127.0.0.1:${server.port}');
    final authed = HttpGatewayTransport(
      profile: GatewayHostProfile(
        hostId: 'host-demo',
        deviceId: 'device-demo',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.lan,
          gatewayUrl: baseUrl,
        ),
        scopes: {'view', 'focus', 'terminal_input'},
      ),
      deviceToken: 'device-secret',
    );
    final output = Completer<GatewayTerminalFrame>();
    StreamSubscription<GatewayTerminalFrame>? subscription;
    try {
      final handle = await authed.openTerminal(
        GatewayTerminalOpenRequest(
          target: GatewayTerminalTarget(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            kind: CcbTerminalTargetKind.agent,
            agent: 'mobile',
            window: 'main',
          ),
        ),
      );
      subscription = authed.terminalFrames(handle, resumeCursor: 7).listen((
        frame,
      ) {
        if (frame.type == GatewayTerminalFrameType.output &&
            !output.isCompleted) {
          output.complete(frame);
        }
      });

      await output.future.timeout(const Duration(seconds: 2));
      expect(terminalMessages.first, {
        'type': 'open',
        'terminal_id': 'term_demo_mobile',
        'token': 'terminal-secret',
        'resume_cursor': 7,
      });
    } finally {
      await subscription?.cancel();
      authed.close(force: true);
    }
  });

  test(
    'fails closed for missing routes and disconnected terminal sends',
    () async {
      await expectLater(
        transport.getProjectView('missing'),
        throwsA(isA<GatewayHttpException>()),
      );
      await expectLater(
        transport.openTerminal(
          GatewayTerminalOpenRequest(
            target: GatewayTerminalTarget(
              projectId: 'proj-demo',
              namespaceEpoch: 4,
              kind: CcbTerminalTargetKind.agent,
              agent: 'mobile',
            ),
          ),
        ),
        throwsA(isA<GatewayHttpException>()),
      );
      final handle = GatewayTerminalHandle(
        terminalId: 'term_demo_mobile',
        terminalToken: 'terminal-secret',
        expiresAt: DateTime.utc(2026, 6, 18, 0, 5),
        websocketUrl: Uri.parse(
          'ws://127.0.0.1:8787/v1/terminals/term_demo_mobile',
        ),
        targetEpoch: 4,
        targetSummary: const GatewayTerminalTargetSummary(
          projectId: 'proj-demo',
          agent: 'mobile',
          window: 'main',
        ),
      );
      await expectLater(
        transport.sendTerminalFrame(
          handle,
          GatewayTerminalFrame.input(sequence: 1, bytes: [0x61]),
        ),
        throwsStateError,
      );
      await expectLater(
        transport.focusAgent(
          projectId: 'proj-demo',
          agent: 'mobile',
          namespaceEpoch: 4,
        ),
        throwsA(isA<GatewayHttpException>()),
      );
    },
  );
}

_GatewayResponse _payloadForRequest(
  String method,
  String path,
  String body,
  String? authorization,
  String? host,
) {
  if (method == 'POST' &&
      (path == '/v1/projects/proj-demo/focus-agent' ||
          path == '/v1/projects/proj-demo/focus-window')) {
    if (authorization != 'Bearer device-secret') {
      return _GatewayResponse({
        'status': 'error',
        'error': 'device scope denied',
      }, 403);
    }
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
  if (method == 'POST' && path == '/v1/projects/proj-demo/terminals') {
    if (authorization != 'Bearer device-secret') {
      return _GatewayResponse({
        'status': 'error',
        'error': 'device scope denied',
      }, 403);
    }
    final decoded = jsonDecode(body);
    if (decoded is! Map ||
        decoded['project_id'] != 'proj-demo' ||
        decoded['namespace_epoch'] != 4) {
      return _GatewayResponse({
        'status': 'error',
        'error': 'invalid terminal target',
      }, 400);
    }
    return _GatewayResponse({
      'schema_version': 1,
      'terminal_id': 'term_demo_mobile',
      'terminal_token': 'terminal-secret',
      'expires_at': '2026-06-18T00:05:00Z',
      'websocket_url':
          'ws://${host ?? "127.0.0.1:8787"}/v1/terminals/term_demo_mobile',
      'target_epoch': 4,
      'target_summary': {
        'project_id': 'proj-demo',
        'agent': 'mobile',
        'window': 'main',
      },
    });
  }
  if (method == 'POST' && path == '/v1/projects/proj-demo/lifecycle') {
    if (authorization != 'Bearer device-secret') {
      return _GatewayResponse({
        'status': 'error',
        'error': 'device scope denied',
      }, 403);
    }
    final decoded = jsonDecode(body);
    final action = decoded is Map ? decoded['action'] : null;
    final lifecycle = {
      'action': action,
      'state': action == 'stop' ? 'stopping' : 'running',
      'effect': action == 'stop' ? 'ccbd_stop_requested' : 'opened',
      'forced': false,
      'ccb_authority': true,
      'tmux_kill_server': false,
      'updated_at': '2026-06-21T00:00:00Z',
      if (action == 'stop') 'result': {'stopped': true, 'force': false},
    };
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'project_id': 'proj-demo',
      'lifecycle': lifecycle,
      if (action == 'open') ..._projectViewBody(),
    });
  }
  if (method == 'POST' &&
      path == '/v1/projects/proj-demo/agents/mobile/messages') {
    if (authorization != 'Bearer device-secret') {
      return _GatewayResponse({
        'status': 'error',
        'error': 'device scope denied',
      }, 403);
    }
    final decoded = jsonDecode(body);
    if (decoded is! Map ||
        decoded['project_id'] != 'proj-demo' ||
        decoded['agent'] != 'mobile' ||
        decoded['namespace_epoch'] != 4 ||
        decoded['idempotency_key'] != 'mobile-msg-1') {
      return _GatewayResponse({
        'status': 'error',
        'error': 'invalid message submit',
      }, 400);
    }
    return _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'message_submit': {
        'accepted': true,
        'idempotency_key': 'mobile-msg-1',
        'message_id': 'msg-1',
        'state': 'sent',
        'message': {
          'id': 'msg-1',
          'agent': 'mobile',
          'kind': 'user_message',
          'title': 'You',
          'body': decoded['body'],
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
    '/v1/health' => _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'server_time': '2026-06-18T00:00:00Z',
      'mode': 'loopback_current_project',
      'project_id': 'proj-demo',
      'capabilities': ['http_json', 'project_view'],
    }),
    '/v1/devices/me' =>
      authorization == 'Bearer device-secret'
          ? _GatewayResponse({
              'schema_version': 1,
              'status': 'ok',
              'device': {
                'device_id': 'dev-demo',
                'name': 'Pixel Fold',
                'project_id': 'proj-demo',
                'pairing_id': 'pair-demo',
                'scopes': ['view', 'focus', 'terminal_input', 'lifecycle'],
                'route_provider': 'cloudflare_tunnel',
                'gateway_url': 'http://${host ?? "127.0.0.1:8787"}',
                'created_at': '2026-06-18T00:00:00Z',
                'last_seen_at': '2026-06-18T00:01:00Z',
                'revoked': false,
                'revoked_at': null,
              },
            })
          : _GatewayResponse({
              'schema_version': 1,
              'status': 'error',
              'error': 'device token required',
            }, 401),
    '/v1/devices/me/presence' =>
      authorization == 'Bearer device-secret'
          ? _GatewayResponse({
              'schema_version': 1,
              'status': 'ok',
              'presence': {
                'device_id': 'dev-demo',
                'visible': true,
                'freshness': 'fresh',
              },
            })
          : _GatewayResponse({
              'schema_version': 1,
              'status': 'error',
              'error': 'device token required',
            }, 401),
    '/v1/projects' => _GatewayResponse({
      'schema_version': 1,
      'projects': [
        {
          'id': 'proj-demo',
          'display_name': 'demo',
          'health': 'healthy',
          'last_opened_at': '2026-07-04T09:00:00Z',
          'last_activity_at': '2026-07-04T09:02:00Z',
          'capabilities': ['http_json', 'project_view'],
        },
      ],
    }),
    '/v1/projects/proj-demo/view' => _GatewayResponse(_projectViewBody()),
    '/v1/projects/proj-demo/agents/mobile/conversation' => _GatewayResponse({
      'schema_version': 1,
      'status': 'ok',
      'conversation': {
        'project_id': 'proj-demo',
        'agent': 'mobile',
        'namespace_epoch': 4,
        'generated_at': '2026-06-21T00:00:00Z',
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

Future<void> _waitFor(bool Function() predicate) async {
  final deadline = DateTime.now().add(const Duration(seconds: 2));
  while (DateTime.now().isBefore(deadline)) {
    if (predicate()) {
      return;
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  throw StateError('condition was not reached');
}
