import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test(
    'terminal reports success only after open frame and timeout as failure',
    () async {
      final gateway = _FakeGatewayTransport()..emitOpenFrame = false;
      final reporter = _RecordingOutcomeReporter();
      final transport = GatewayTerminalTransport(transport: gateway)
        ..outcomeReporter = reporter;

      final readySession = await transport.open(_request());
      expect(reporter.successes, isEmpty);
      gateway.emit(GatewayTerminalFrame.open(terminalId: 'term', token: ''));
      await pumpEventQueue();
      expect(reporter.successes, [GatewayConnectionOperation.terminal]);
      await readySession.close();

      final timeoutGateway = _FakeGatewayTransport()..emitOpenFrame = false;
      final timeoutReporter = _RecordingOutcomeReporter();
      final timeoutTransport = GatewayTerminalTransport(
        transport: timeoutGateway,
        connectionTimeout: const Duration(milliseconds: 10),
      )..outcomeReporter = timeoutReporter;
      final timedOutSession = await timeoutTransport.open(_request());
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(timeoutReporter.failures, [GatewayConnectionOperation.terminal]);
      timeoutGateway.emit(
        GatewayTerminalFrame.open(terminalId: 'late', token: ''),
      );
      await pumpEventQueue();
      expect(timeoutReporter.successes, isEmpty);
      await timedOutSession.close();
    },
  );

  test(
    'terminal close cleans up after closed frame mutation failure',
    () async {
      final gateway = _FakeGatewayTransport()..failClosedFrame = true;
      final firstReporter = _RecordingOutcomeReporter();
      final transport = GatewayTerminalTransport(transport: gateway)
        ..outcomeReporter = firstReporter;
      final session = await transport.open(_request());
      final outputDone = Completer<void>();
      final outputSubscription = session.output.listen(
        (_) {},
        onDone: outputDone.complete,
      );

      await expectLater(session.close(), throwsA(isA<StateError>()));
      await outputDone.future;
      expect(gateway.activeFrameSubscriptions, 0);

      final secondReporter = _RecordingOutcomeReporter();
      transport.outcomeReporter = secondReporter;
      gateway.emit(GatewayTerminalFrame.open(terminalId: 'late', token: ''));
      await pumpEventQueue();
      expect(firstReporter.successes, isEmpty);
      expect(firstReporter.failures, [GatewayConnectionOperation.mutation]);
      expect(secondReporter.successes, isEmpty);
      await outputSubscription.cancel();
    },
  );

  test(
    'old terminal session reporter is detached on profile replacement',
    () async {
      final gateway = _FakeGatewayTransport()..emitOpenFrame = false;
      final oldReporter = _RecordingOutcomeReporter();
      final transport = GatewayTerminalTransport(transport: gateway)
        ..outcomeReporter = oldReporter;
      await transport.open(_request());
      transport.outcomeReporter = null;
      gateway.emit(GatewayTerminalFrame.open(terminalId: 'term', token: ''));
      await pumpEventQueue();
      expect(oldReporter.successes, isEmpty);
    },
  );

  test(
    'opens gateway terminal and forwards frames as terminal session',
    () async {
      final gateway = _FakeGatewayTransport();
      final transport = GatewayTerminalTransport(transport: gateway);

      final session = await transport.open(
        TerminalOpenRequest.gateway(
          target: CcbTerminalTarget.agent(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            agent: 'mobile',
            window: 'main',
            paneId: '%2',
            scopes: {CcbScope.view, CcbScope.terminalInput},
          ),
          geometry: const TerminalGeometry(columns: 100, rows: 30),
        ),
      );

      expect(gateway.openRequests.single.target.toJson(), {
        'kind': 'agent',
        'agent': 'mobile',
        'window': 'main',
        'pane_id': '%2',
      });
      expect(
        session.launchedCommand,
        'gateway terminal stream proj-demo/mobile',
      );

      final output = <String>[];
      final subscription = session.output.map(utf8.decode).listen(output.add);
      gateway.emit(
        GatewayTerminalFrame.output(sequence: 1, bytes: utf8.encode('hello')),
      );
      await pumpEventQueue();
      expect(output, ['hello']);

      await session.writeBytes([0x61]);
      await session.paste('paste me');
      await session.resize(const TerminalGeometry(columns: 120, rows: 36));
      await session.close();

      expect(gateway.sentFrames.map((frame) => frame.toJson()), [
        {
          'type': 'input',
          'seq': 1,
          'bytes_b64': base64Encode([0x61]),
        },
        {'type': 'paste', 'seq': 2, 'text': 'paste me'},
        {
          'type': 'resize',
          'columns': 120,
          'rows': 36,
          'pixel_width': 0,
          'pixel_height': 0,
        },
        {'type': 'closed', 'reason': 'client_closed'},
      ]);
      await subscription.cancel();
    },
  );

  test('gateway terminal reconnect uses latest output resume cursor', () async {
    final gateway = _FakeGatewayTransport();
    final session = await GatewayTerminalTransport(transport: gateway).open(
      TerminalOpenRequest.gateway(
        target: CcbTerminalTarget.agent(
          projectId: 'proj-demo',
          namespaceEpoch: 4,
          agent: 'mobile',
          scopes: {CcbScope.view, CcbScope.terminalInput},
        ),
      ),
    );

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 7, bytes: utf8.encode('hello')),
    );
    await pumpEventQueue();

    await session.reconnect();

    expect(gateway.resumeCursors, [null, 7]);
  });

  test('gateway terminal reconnects after stream disconnect', () async {
    final gateway = _FakeGatewayTransport();
    final session = await GatewayTerminalTransport(transport: gateway).open(
      TerminalOpenRequest.gateway(
        target: CcbTerminalTarget.agent(
          projectId: 'proj-demo',
          namespaceEpoch: 4,
          agent: 'mobile',
          scopes: {CcbScope.view, CcbScope.terminalInput},
        ),
      ),
    );
    final output = <String>[];
    final errors = <Object>[];
    final subscription = session.output
        .map(utf8.decode)
        .listen(output.add, onError: errors.add);

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 7, bytes: utf8.encode('before')),
    );
    await pumpEventQueue();
    await gateway.closeCurrentStream();
    await pumpEventQueue();

    expect(output, ['before']);
    expect(
      errors,
      contains(
        isA<TerminalTransportException>().having(
          (error) => error.message,
          'message',
          'terminal stream disconnected',
        ),
      ),
    );

    await session.reconnect();
    expect(gateway.resumeCursors, [null, 7]);

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 8, bytes: utf8.encode('after')),
    );
    await pumpEventQueue();

    expect(output, ['before', 'after']);
    await session.writeBytes([0x03]);
    expect(gateway.sentFrames.last.toJson(), {
      'type': 'input',
      'seq': 1,
      'bytes_b64': base64Encode([0x03]),
    });

    await subscription.cancel();
  });

  test('gateway terminal renews handle when token expires', () async {
    final gateway = _FakeGatewayTransport();
    final session = await GatewayTerminalTransport(transport: gateway).open(
      TerminalOpenRequest.gateway(
        target: CcbTerminalTarget.agent(
          projectId: 'proj-demo',
          namespaceEpoch: 4,
          agent: 'mobile',
          scopes: {CcbScope.view, CcbScope.terminalInput},
        ),
      ),
    );
    final output = <String>[];
    final errors = <Object>[];
    final subscription = session.output
        .map(utf8.decode)
        .listen(output.add, onError: errors.add);

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 7, bytes: utf8.encode('before')),
    );
    await pumpEventQueue();
    await session.resize(
      const TerminalGeometry(
        columns: 132,
        rows: 43,
        pixelWidth: 1000,
        pixelHeight: 700,
      ),
    );

    gateway.emit(GatewayTerminalFrame.error('expired'));
    await _waitFor(
      () =>
          gateway.openRequests.length == 2 && gateway.resumeCursors.length == 2,
    );

    expect(gateway.resumeCursors, [null, null]);
    expect(gateway.rejectedResumeCursors, isEmpty);
    expect(gateway.openRequests.last.geometry.columns, 132);
    expect(gateway.openRequests.last.geometry.rows, 43);
    expect(gateway.openRequests.last.geometry.pixelWidth, 1000);
    expect(gateway.openRequests.last.geometry.pixelHeight, 700);

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 1, bytes: utf8.encode('after')),
    );
    await pumpEventQueue();

    expect(output, ['before', 'after']);
    expect(errors, isEmpty);
    await subscription.cancel();
  });

  test(
    'gateway terminal renews handle after terminal output failure',
    () async {
      final gateway = _FakeGatewayTransport();
      final session = await GatewayTerminalTransport(transport: gateway).open(
        TerminalOpenRequest.gateway(
          target: CcbTerminalTarget.agent(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            agent: 'mobile',
            scopes: {CcbScope.view, CcbScope.terminalInput},
          ),
        ),
      );
      final errors = <Object>[];
      final subscription = session.output.listen((_) {}, onError: errors.add);

      gateway.emit(GatewayTerminalFrame.error('terminal_output_error'));
      await _waitFor(
        () =>
            gateway.openRequests.length == 2 &&
            gateway.resumeCursors.length == 2,
      );

      expect(gateway.resumeCursors, [null, null]);
      expect(gateway.frameHandles.last.terminalId, 'term_demo_mobile_2');
      expect(errors, isEmpty);

      await session.writeBytes([0x61]);
      expect(gateway.sentFrameHandles.last.terminalId, 'term_demo_mobile_2');
      await subscription.cancel();
    },
  );

  test('gateway terminal renews handle when resume cursor is stale', () async {
    final gateway = _FakeGatewayTransport();
    final session = await GatewayTerminalTransport(transport: gateway).open(
      TerminalOpenRequest.gateway(
        target: CcbTerminalTarget.agent(
          projectId: 'proj-demo',
          namespaceEpoch: 4,
          agent: 'mobile',
          scopes: {CcbScope.view, CcbScope.terminalInput},
        ),
      ),
    );
    final output = <String>[];
    final errors = <Object>[];
    final subscription = session.output
        .map(utf8.decode)
        .listen(output.add, onError: errors.add);

    gateway.emit(
      GatewayTerminalFrame.output(sequence: 7, bytes: utf8.encode('before')),
    );
    await pumpEventQueue();

    gateway.emit(GatewayTerminalFrame.error('stale_resume_cursor'));
    await _waitFor(
      () =>
          gateway.openRequests.length == 2 && gateway.resumeCursors.length == 2,
    );

    expect(gateway.resumeCursors, [null, null]);
    expect(gateway.rejectedResumeCursors, isEmpty);
    gateway.emit(
      GatewayTerminalFrame.output(sequence: 1, bytes: utf8.encode('after')),
    );
    await pumpEventQueue();

    expect(output, ['before', 'after']);
    expect(errors, isEmpty);
    await subscription.cancel();
  });

  test(
    'gateway terminal renews handle when reconnect token is invalid',
    () async {
      final gateway = _FakeGatewayTransport();
      final session = await GatewayTerminalTransport(transport: gateway).open(
        TerminalOpenRequest.gateway(
          target: CcbTerminalTarget.agent(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            agent: 'mobile',
            scopes: {CcbScope.view, CcbScope.terminalInput},
          ),
        ),
      );

      gateway.emit(
        GatewayTerminalFrame.output(sequence: 7, bytes: utf8.encode('before')),
      );
      await pumpEventQueue();
      gateway.invalidTerminalIds.add(gateway.frameHandles.last.terminalId);

      await session.reconnect();

      expect(gateway.resumeCursors, [null, 7, null]);
      expect(gateway.openRequests, hasLength(2));
      expect(gateway.frameHandles.last.terminalId, 'term_demo_mobile_2');

      await session.writeBytes([0x7a]);
      expect(gateway.sentFrameHandles.last.terminalId, 'term_demo_mobile_2');
      expect(gateway.sentFrames.last.toJson(), {
        'type': 'input',
        'seq': 1,
        'bytes_b64': base64Encode([0x7a]),
      });
    },
  );

  test(
    'gateway terminal renews handle after websocket handshake closes',
    () async {
      final gateway = _FakeGatewayTransport();
      final session = await GatewayTerminalTransport(transport: gateway).open(
        TerminalOpenRequest.gateway(
          target: CcbTerminalTarget.agent(
            projectId: 'proj-demo',
            namespaceEpoch: 4,
            agent: 'mobile',
            scopes: {CcbScope.view, CcbScope.terminalInput},
          ),
        ),
      );

      gateway.emit(
        GatewayTerminalFrame.output(sequence: 3, bytes: utf8.encode('before')),
      );
      await pumpEventQueue();
      gateway.handshakeClosedTerminalIds.add(
        gateway.frameHandles.last.terminalId,
      );

      await session.reconnect();

      expect(gateway.resumeCursors, [null, 3, null]);
      expect(gateway.openRequests, hasLength(2));
      await session.writeBytes([0x6b]);
      expect(gateway.sentFrameHandles.last.terminalId, 'term_demo_mobile_2');
    },
  );

  test(
    'host terminal opens, renews, and terminates the same shell slot',
    () async {
      final gateway = _FakeGatewayTransport();
      final transport = GatewayTerminalTransport(transport: gateway);
      final session = await transport.openHostTerminal(
        HostTerminalOpenRequest(
          clientSessionId: 'shell-2',
          displayName: 'Shell 2',
          geometry: const TerminalGeometry(columns: 90, rows: 24),
        ),
      );

      expect(gateway.hostOpenRequests.single.clientSessionId, 'shell-2');
      expect(session.launchedCommand, 'host shell shell-2 (~)');
      gateway.invalidTerminalIds.add(gateway.frameHandles.last.terminalId);
      await session.reconnect();
      await _waitFor(() => gateway.hostOpenRequests.length == 2);
      expect(gateway.hostOpenRequests.last.clientSessionId, 'shell-2');

      await transport.terminateHostTerminal('shell-2');
      expect(gateway.terminatedHostSessions, ['shell-2']);
      await session.close();
    },
  );

  test('closing host terminal drains an in-flight handle renewal', () async {
    final gateway = _FakeGatewayTransport();
    final transport = GatewayTerminalTransport(transport: gateway);
    final session = await transport.openHostTerminal(
      HostTerminalOpenRequest(
        clientSessionId: 'shell-1',
        displayName: 'Shell 1',
      ),
    );
    gateway.invalidTerminalIds.add(gateway.frameHandles.last.terminalId);
    final renewalGate = Completer<void>();
    gateway.nextHostOpenGate = renewalGate;

    final reconnect = session.reconnect();
    await _waitFor(() => gateway.hostOpenRequests.length == 2);
    final close = session.close();
    renewalGate.complete();
    await reconnect.catchError((_) {});
    await close;
    await transport.terminateHostTerminal('shell-1');

    expect(gateway.hostOpenRequests, hasLength(2));
    final closedTerminalIds = <String>[
      for (var index = 0; index < gateway.sentFrames.length; index += 1)
        if (gateway.sentFrames[index].type == GatewayTerminalFrameType.closed)
          gateway.sentFrameHandles[index].terminalId,
    ];
    expect(
      closedTerminalIds,
      containsAll(<String>['term_host_1', 'term_host_2']),
    );
    expect(gateway.terminatedHostSessions, ['shell-1']);
  });
}

class _FakeGatewayTransport
    implements GatewayTransport, GatewayHostTerminalTransport {
  _FakeGatewayTransport();

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

  final openRequests = <GatewayTerminalOpenRequest>[];
  final hostOpenRequests = <GatewayHostTerminalOpenRequest>[];
  final terminatedHostSessions = <String>[];
  final sentFrames = <GatewayTerminalFrame>[];
  final sentFrameHandles = <GatewayTerminalHandle>[];
  final resumeCursors = <int?>[];
  final rejectedResumeCursors = <int>[];
  final invalidTerminalIds = <String>{};
  final handshakeClosedTerminalIds = <String>{};
  bool emitOpenFrame = true;
  bool failClosedFrame = false;
  Completer<void>? nextHostOpenGate;
  var activeFrameSubscriptions = 0;
  final _frameControllers = <StreamController<GatewayTerminalFrame>>[];
  final _frameHandles = <GatewayTerminalHandle>[];
  final _lastOutputByTerminalId = <String, int>{};

  @override
  final GatewayHostProfile profile = GatewayHostProfile(
    hostId: 'proj-demo',
    deviceId: 'dev-demo',
    routeProvider: RouteProvider(
      kind: RouteProviderKind.lan,
      gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
    ),
    scopes: {'view', 'focus', 'terminal_input'},
  );

  void emit(GatewayTerminalFrame frame) {
    final handle = _frameHandles.last;
    if (frame.type == GatewayTerminalFrameType.output) {
      _lastOutputByTerminalId[handle.terminalId] = _jsonInt(
        frame.payload['seq'],
      );
    }
    _frameControllers.last.add(frame);
  }

  List<GatewayTerminalHandle> get frameHandles =>
      List.unmodifiable(_frameHandles);

  Future<void> closeCurrentStream() {
    return _frameControllers.last.close();
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
  Future<CcbProjectView> getProjectView(String projectId) {
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
  Future<GatewayHealth> health() {
    throw UnimplementedError();
  }

  @override
  Future<GatewayDevice> device() {
    throw UnimplementedError();
  }

  @override
  Future<List<CcbProject>> listProjects() {
    throw UnimplementedError();
  }

  @override
  Future<GatewayTerminalHandle> openTerminal(
    GatewayTerminalOpenRequest request,
  ) async {
    final sequence = openRequests.length + 1;
    openRequests.add(request);
    return GatewayTerminalHandle(
      terminalId: 'term_demo_mobile_$sequence',
      terminalToken: 'terminal-secret-$sequence',
      expiresAt: DateTime.utc(2026, 6, 18, 0, 5),
      websocketUrl: Uri.parse(
        'ws://127.0.0.1:8787/v1/terminals/term_demo_mobile_$sequence',
      ),
      targetEpoch: request.target.namespaceEpoch,
      targetSummary: GatewayTerminalTargetSummary(
        projectId: request.target.projectId,
        agent: request.target.agent,
        window: request.target.window,
      ),
    );
  }

  @override
  Future<GatewayTerminalHandle> openHostTerminal(
    GatewayHostTerminalOpenRequest request,
  ) async {
    final sequence = hostOpenRequests.length + 1;
    hostOpenRequests.add(request);
    final gate = nextHostOpenGate;
    nextHostOpenGate = null;
    await gate?.future;
    return GatewayTerminalHandle(
      terminalId: 'term_host_$sequence',
      terminalToken: 'host-terminal-secret-$sequence',
      expiresAt: DateTime.utc(2026, 6, 18, 0, 5),
      websocketUrl: Uri.parse(
        'ws://127.0.0.1:8787/v1/terminals/term_host_$sequence',
      ),
      targetEpoch: 0,
      targetSummary: const GatewayTerminalTargetSummary(projectId: '@host'),
    );
  }

  @override
  Future<void> terminateHostTerminal({required String clientSessionId}) async {
    terminatedHostSessions.add(clientSessionId);
  }

  @override
  Future<void> sendTerminalFrame(
    GatewayTerminalHandle handle,
    GatewayTerminalFrame frame,
  ) async {
    if (frame.type == GatewayTerminalFrameType.closed && failClosedFrame) {
      throw StateError('closed frame rejected');
    }
    sentFrameHandles.add(handle);
    sentFrames.add(frame);
  }

  @override
  Stream<GatewayTerminalFrame> terminalFrames(
    GatewayTerminalHandle handle, {
    int? resumeCursor,
  }) {
    resumeCursors.add(resumeCursor);
    final controller = StreamController<GatewayTerminalFrame>.broadcast(
      onListen: () => activeFrameSubscriptions += 1,
      onCancel: () => activeFrameSubscriptions -= 1,
    );
    _frameControllers.add(controller);
    _frameHandles.add(handle);
    final lastOutput = _lastOutputByTerminalId[handle.terminalId] ?? 0;
    if (handshakeClosedTerminalIds.contains(handle.terminalId)) {
      scheduleMicrotask(() {
        if (!controller.isClosed) {
          controller.addError(
            HttpException(
              'Connection closed before full header was received',
              uri: Uri.parse(
                'http://127.0.0.1:8787/v1/terminals/${handle.terminalId}',
              ),
            ),
          );
          controller.close();
        }
      });
    } else if (invalidTerminalIds.contains(handle.terminalId)) {
      scheduleMicrotask(() {
        if (!controller.isClosed) {
          controller.add(GatewayTerminalFrame.error('invalid_token'));
          controller.close();
        }
      });
    } else if (resumeCursor != null && resumeCursor > lastOutput) {
      rejectedResumeCursors.add(resumeCursor);
      scheduleMicrotask(() {
        if (!controller.isClosed) {
          controller.add(GatewayTerminalFrame.error('stale_resume_cursor'));
          controller.close();
        }
      });
    } else if (emitOpenFrame) {
      scheduleMicrotask(() {
        if (!controller.isClosed) {
          controller.add(
            GatewayTerminalFrame.open(
              terminalId: handle.terminalId,
              token: '',
              lastInputSequence: 0,
            ),
          );
        }
      });
    }
    return controller.stream;
  }
}

TerminalOpenRequest _request() => TerminalOpenRequest.gateway(
  target: CcbTerminalTarget.agent(
    projectId: 'proj-demo',
    namespaceEpoch: 4,
    agent: 'mobile',
    scopes: {CcbScope.view, CcbScope.terminalInput},
  ),
);

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

Future<void> _waitFor(
  bool Function() predicate, {
  Duration timeout = const Duration(seconds: 2),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    if (predicate()) {
      return;
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  fail('condition was not met within $timeout');
}

int _jsonInt(Object? value) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString()) ?? 0;
}
