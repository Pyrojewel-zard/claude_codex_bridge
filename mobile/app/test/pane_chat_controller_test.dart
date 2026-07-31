import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('sends pane-backed chat through paste plus enter', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);

    await controller.send(agent: agent, view: view, body: 'hello pane');
    await controller.send(agent: agent, view: view, body: 'again');

    expect(transport.requests, hasLength(1));
    expect(
      transport.requests.single.attachCommand,
      'gateway terminal stream proj-demo/mobile',
    );
    final session = transport.sessions.single;
    expect(session.pasted, ['hello pane', 'again']);
    expect(session.written, [
      [13],
      [13],
    ]);

    await controller.dispose();
    expect(session.closed, isTrue);
  });

  test('emits selected-agent output and error notices', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);
    final events = <PaneChatEvent>[];
    final subscription = controller.events.listen(events.add);

    await controller.send(agent: agent, view: view, body: 'prompt');
    final session = transport.sessions.single;
    session.addOutput('  pane reply\n');
    session.addOutput('   ');
    session.addError(const TerminalTransportException('expired'));
    await pumpEventQueue();

    expect(events, hasLength(2));
    expect(events.first.agentName, 'mobile');
    expect(events.first.kind, PaneChatEventKind.output);
    expect(events.first.body, 'pane reply');
    expect(events.last.kind, PaneChatEventKind.notice);
    expect(events.last.body, contains('TerminalTransportException(expired)'));

    await subscription.cancel();
    await controller.dispose();
  });

  test('sends Tab key without paste or enter', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);

    await controller.sendKey(agent: agent, view: view, bytes: const [9]);

    expect(transport.requests, hasLength(1));
    final session = transport.sessions.single;
    expect(session.pasted, isEmpty);
    expect(session.written, [
      [9],
    ]);

    await controller.dispose();
  });

  test('types text then sends Tab key without Enter', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);

    await controller.sendTextThenKey(
      agent: agent,
      view: view,
      body: 'queue this',
      bytes: const [9],
    );

    expect(transport.requests, hasLength(1));
    final session = transport.sessions.single;
    expect(session.pasted, ['queue this']);
    expect(session.written, [
      [9],
    ]);

    await controller.dispose();
  });

  test('suppresses exact terminal echo while preserving real output', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);
    final events = <PaneChatEvent>[];
    final subscription = controller.events.listen(events.add);

    await controller.send(agent: agent, view: view, body: 'echo me');
    final session = transport.sessions.single;
    session.addOutput(' echo me\n');
    session.addOutput('actual answer');
    await pumpEventQueue();

    expect(events, hasLength(1));
    expect(events.single.kind, PaneChatEventKind.output);
    expect(events.single.body, 'actual answer');

    await controller.send(agent: agent, view: view, body: 'not echoed');
    session.addOutput('different first output');
    session.addOutput('not echoed');
    await pumpEventQueue();

    expect(events.map((event) => event.body), [
      'actual answer',
      'different first output',
      'not echoed',
    ]);

    await subscription.cancel();
    await controller.dispose();
  });

  test('opens a fresh session after terminal stream errors', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport();
    final controller = PaneChatController(transport: transport);
    final events = <PaneChatEvent>[];
    final subscription = controller.events.listen(events.add);

    await controller.send(agent: agent, view: view, body: 'first');
    final firstSession = transport.sessions.single;
    firstSession.addError(const TerminalTransportException('expired'));
    await pumpEventQueue();

    expect(events.single.kind, PaneChatEventKind.notice);
    expect(firstSession.closed, isTrue);

    await controller.send(agent: agent, view: view, body: 'second');
    expect(transport.requests, hasLength(2));
    expect(transport.sessions.last, isNot(same(firstSession)));
    expect(transport.sessions.last.pasted.single, 'second');

    await subscription.cancel();
    await controller.dispose();
  });

  test('classifies open failures as safe to retry', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final transport = _RecordingTerminalTransport(
      openError: const TerminalTransportException('open failed'),
    );
    final controller = PaneChatController(transport: transport);

    await expectLater(
      controller.send(agent: agent, view: view, body: 'hello'),
      throwsA(
        isA<PaneChatSendException>()
            .having(
              (error) => error.stage,
              'stage',
              PaneChatSendFailureStage.open,
            )
            .having(
              (error) => error.inputMayHaveReachedPane,
              'inputMayHaveReachedPane',
              isFalse,
            ),
      ),
    );

    await controller.dispose();
  });

  test(
    'classifies paste and enter failures as possible partial input',
    () async {
      final view = CcbProjectView.fromProjectViewPayload(
        demoProjectViewFixture,
      );
      final agent = view.agentByName('mobile')!;
      final pasteTransport = _RecordingTerminalTransport(
        pasteError: const TerminalTransportException('paste failed'),
      );
      final pasteController = PaneChatController(transport: pasteTransport);

      await expectLater(
        pasteController.send(agent: agent, view: view, body: 'paste body'),
        throwsA(
          isA<PaneChatSendException>()
              .having(
                (error) => error.stage,
                'stage',
                PaneChatSendFailureStage.paste,
              )
              .having(
                (error) => error.inputMayHaveReachedPane,
                'inputMayHaveReachedPane',
                isTrue,
              ),
        ),
      );
      expect(pasteTransport.sessions.single.written, isEmpty);
      await pasteController.dispose();

      final enterTransport = _RecordingTerminalTransport(
        writeError: const TerminalTransportException('enter failed'),
      );
      final enterController = PaneChatController(transport: enterTransport);

      await expectLater(
        enterController.send(agent: agent, view: view, body: 'enter body'),
        throwsA(
          isA<PaneChatSendException>()
              .having(
                (error) => error.stage,
                'stage',
                PaneChatSendFailureStage.enter,
              )
              .having(
                (error) => error.inputMayHaveReachedPane,
                'inputMayHaveReachedPane',
                isTrue,
              ),
        ),
      );
      expect(enterTransport.sessions.single.pasted, ['enter body']);
      await enterController.dispose();
    },
  );

  test('times out a stuck paste and opens a fresh session next time', () async {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);
    final agent = view.agentByName('mobile')!;
    final pasteGate = Completer<void>();
    final transport = _RecordingTerminalTransport(pasteGate: pasteGate.future);
    final controller = PaneChatController(
      transport: transport,
      operationTimeout: const Duration(milliseconds: 20),
    );

    await expectLater(
      controller.send(agent: agent, view: view, body: 'stuck'),
      throwsA(
        isA<PaneChatSendException>()
            .having(
              (error) => error.stage,
              'stage',
              PaneChatSendFailureStage.paste,
            )
            .having(
              (error) => error.inputMayHaveReachedPane,
              'inputMayHaveReachedPane',
              isTrue,
            ),
      ),
    );
    expect(transport.sessions.single.closed, isTrue);

    transport.pasteGate = null;
    await controller.send(agent: agent, view: view, body: 'fresh');

    expect(transport.sessions, hasLength(2));
    expect(transport.sessions.last.pasted, ['fresh']);
    expect(transport.sessions.last.written, [
      [13],
    ]);

    pasteGate.complete();
    await controller.dispose();
  });
}

class _RecordingTerminalTransport implements TerminalTransport {
  _RecordingTerminalTransport({
    this.openError,
    this.pasteError,
    this.writeError,
    this.pasteGate,
  });

  final Object? openError;
  final Object? pasteError;
  final Object? writeError;
  Future<void>? pasteGate;
  final requests = <TerminalOpenRequest>[];
  final sessions = <_RecordingTerminalSession>[];

  @override
  Future<TerminalSession> open(TerminalOpenRequest request) async {
    final error = openError;
    if (error != null) {
      throw error;
    }
    requests.add(request);
    final session = _RecordingTerminalSession(
      request.attachCommand,
      pasteError: pasteError,
      writeError: writeError,
      pasteGate: pasteGate,
    );
    sessions.add(session);
    return session;
  }
}

class _RecordingTerminalSession implements TerminalSession {
  _RecordingTerminalSession(
    this.launchedCommand, {
    this.pasteError,
    this.writeError,
    this.pasteGate,
  });

  final _output = StreamController<Uint8List>.broadcast();
  final Object? pasteError;
  final Object? writeError;
  final Future<void>? pasteGate;
  final written = <List<int>>[];
  final pasted = <String>[];
  var closed = false;

  @override
  final String launchedCommand;

  @override
  Stream<Uint8List> get output => _output.stream;

  void addOutput(String text) {
    _output.add(Uint8List.fromList(utf8.encode(text)));
  }

  void addError(Object error) {
    _output.addError(error);
  }

  @override
  Future<void> close() async {
    closed = true;
    await _output.close();
  }

  @override
  Future<void> paste(String text) async {
    final error = pasteError;
    if (error != null) {
      throw error;
    }
    pasted.add(text);
    await pasteGate;
  }

  @override
  Future<void> reconnect() async {}

  @override
  Future<void> resize(TerminalGeometry geometry) async {}

  @override
  Future<void> writeBytes(List<int> bytes) async {
    final error = writeError;
    if (error != null) {
      throw error;
    }
    written.add(bytes);
  }
}
