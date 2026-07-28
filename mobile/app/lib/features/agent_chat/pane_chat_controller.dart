import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import '../../models/ccb_agent.dart';
import '../../models/ccb_project_view.dart';
import '../../transport/terminal_transport.dart';

enum PaneChatEventKind { output, notice }

enum PaneChatSendFailureStage { open, paste, enter }

class PaneChatEvent {
  const PaneChatEvent({
    required this.agentName,
    required this.kind,
    required this.body,
  });

  final String agentName;
  final PaneChatEventKind kind;
  final String body;
}

class PaneChatSendException implements Exception {
  const PaneChatSendException({
    required this.stage,
    required this.cause,
    required this.inputMayHaveReachedPane,
  });

  final PaneChatSendFailureStage stage;
  final Object cause;
  final bool inputMayHaveReachedPane;

  @override
  String toString() {
    return 'PaneChatSendException(stage: ${stage.name}, '
        'inputMayHaveReachedPane: $inputMayHaveReachedPane, cause: $cause)';
  }
}

class PaneChatController {
  PaneChatController({
    required TerminalTransport transport,
    Duration operationTimeout = const Duration(seconds: 8),
  }) : _transport = transport,
       _operationTimeout = operationTimeout;

  final TerminalTransport _transport;
  final Duration _operationTimeout;
  final _events = StreamController<PaneChatEvent>.broadcast();
  final _sessions = <String, TerminalSession>{};
  final _outputStreams = <String, StreamSubscription<Uint8List>>{};
  final _pendingEchoes = <String, List<String>>{};
  final _writeQueues = <String, Future<void>>{};
  var _disposed = false;

  Stream<PaneChatEvent> get events => _events.stream;

  Future<void> send({
    required CcbAgent agent,
    required CcbProjectView view,
    required String body,
    List<int> submitBytes = const [13],
  }) {
    return _enqueueWrite(agent.name, () async {
      await _sendNow(
        agent: agent,
        view: view,
        body: body,
        submitBytes: submitBytes,
      );
    });
  }

  Future<void> _sendNow({
    required CcbAgent agent,
    required CcbProjectView view,
    required String body,
    required List<int> submitBytes,
  }) async {
    if (_disposed) {
      throw const TerminalTransportException('pane chat controller is closed');
    }
    late final TerminalSession session;
    try {
      session = await _sessionFor(
        agent: agent,
        view: view,
      ).timeout(_operationTimeout);
    } catch (error) {
      throw PaneChatSendException(
        stage: PaneChatSendFailureStage.open,
        cause: error,
        inputMayHaveReachedPane: false,
      );
    }
    final pendingEcho = _normalizedEchoText(body);
    if (pendingEcho != null) {
      _pendingEchoes.update(
        agent.name,
        (items) => [...items, pendingEcho],
        ifAbsent: () => [pendingEcho],
      );
    }
    try {
      try {
        await session.paste(body).timeout(_operationTimeout);
      } catch (error) {
        throw PaneChatSendException(
          stage: PaneChatSendFailureStage.paste,
          cause: error,
          inputMayHaveReachedPane: true,
        );
      }
      try {
        await session.writeBytes(submitBytes).timeout(_operationTimeout);
      } catch (error) {
        throw PaneChatSendException(
          stage: PaneChatSendFailureStage.enter,
          cause: error,
          inputMayHaveReachedPane: true,
        );
      }
    } catch (_) {
      if (pendingEcho != null) {
        _consumePendingEcho(agent.name, pendingEcho);
      }
      _discardSession(agent.name, session);
      rethrow;
    }
  }

  Future<void> sendKey({
    required CcbAgent agent,
    required CcbProjectView view,
    required List<int> bytes,
  }) {
    return _enqueueWrite(agent.name, () async {
      await _sendKeyNow(agent: agent, view: view, bytes: bytes);
    });
  }

  Future<void> sendTextThenKey({
    required CcbAgent agent,
    required CcbProjectView view,
    required String body,
    required List<int> bytes,
  }) {
    return _enqueueWrite(agent.name, () async {
      await _sendTextThenKeyNow(
        agent: agent,
        view: view,
        body: body,
        bytes: bytes,
      );
    });
  }

  Future<void> _sendKeyNow({
    required CcbAgent agent,
    required CcbProjectView view,
    required List<int> bytes,
  }) async {
    if (_disposed) {
      throw const TerminalTransportException('pane chat controller is closed');
    }
    if (bytes.isEmpty) {
      return;
    }
    late final TerminalSession session;
    try {
      session = await _sessionFor(
        agent: agent,
        view: view,
      ).timeout(_operationTimeout);
    } catch (error) {
      throw PaneChatSendException(
        stage: PaneChatSendFailureStage.open,
        cause: error,
        inputMayHaveReachedPane: false,
      );
    }
    try {
      await session.writeBytes(bytes).timeout(_operationTimeout);
    } catch (error) {
      _discardSession(agent.name, session);
      throw PaneChatSendException(
        stage: PaneChatSendFailureStage.enter,
        cause: error,
        inputMayHaveReachedPane: false,
      );
    }
  }

  Future<void> _sendTextThenKeyNow({
    required CcbAgent agent,
    required CcbProjectView view,
    required String body,
    required List<int> bytes,
  }) async {
    if (_disposed) {
      throw const TerminalTransportException('pane chat controller is closed');
    }
    if (body.isEmpty) {
      await _sendKeyNow(agent: agent, view: view, bytes: bytes);
      return;
    }
    late final TerminalSession session;
    try {
      session = await _sessionFor(
        agent: agent,
        view: view,
      ).timeout(_operationTimeout);
    } catch (error) {
      throw PaneChatSendException(
        stage: PaneChatSendFailureStage.open,
        cause: error,
        inputMayHaveReachedPane: false,
      );
    }
    final pendingEcho = _normalizedEchoText(body);
    if (pendingEcho != null) {
      _pendingEchoes.update(
        agent.name,
        (items) => [...items, pendingEcho],
        ifAbsent: () => [pendingEcho],
      );
    }
    try {
      try {
        await session.paste(body).timeout(_operationTimeout);
      } catch (error) {
        throw PaneChatSendException(
          stage: PaneChatSendFailureStage.paste,
          cause: error,
          inputMayHaveReachedPane: true,
        );
      }
      try {
        await session.writeBytes(bytes).timeout(_operationTimeout);
      } catch (error) {
        throw PaneChatSendException(
          stage: PaneChatSendFailureStage.enter,
          cause: error,
          inputMayHaveReachedPane: true,
        );
      }
    } catch (_) {
      if (pendingEcho != null) {
        _consumePendingEcho(agent.name, pendingEcho);
      }
      _discardSession(agent.name, session);
      rethrow;
    }
  }

  Future<T> _enqueueWrite<T>(String agentName, Future<T> Function() operation) {
    final previous = _writeQueues[agentName] ?? Future<void>.value();
    final result = previous.onError((_, _) {}).then((_) => operation());
    final marker = result.then<void>((_) {}, onError: (_, _) {});
    _writeQueues[agentName] = marker;
    unawaited(
      marker.whenComplete(() {
        if (identical(_writeQueues[agentName], marker)) {
          _writeQueues.remove(agentName);
        }
      }),
    );
    return result;
  }

  Future<void> closeSessions() async {
    final subscriptions = _outputStreams.values.toList();
    _outputStreams.clear();
    await Future.wait<void>([
      for (final subscription in subscriptions) subscription.cancel(),
    ]);

    final sessions = _sessions.values.toList();
    _sessions.clear();
    _pendingEchoes.clear();
    await Future.wait<void>([
      for (final session in sessions) _closeSession(session),
    ]);
  }

  Future<void> dispose() async {
    if (_disposed) {
      return;
    }
    _disposed = true;
    await closeSessions();
    await _events.close();
  }

  Future<TerminalSession> _sessionFor({
    required CcbAgent agent,
    required CcbProjectView view,
  }) async {
    final existing = _sessions[agent.name];
    if (existing != null) {
      return existing;
    }
    final session = await _transport.open(
      TerminalOpenRequest.gateway(
        target: view.terminalTargetForAgent(agent.name),
      ),
    );
    _sessions[agent.name] = session;
    late final StreamSubscription<Uint8List> subscription;
    subscription = session.output.listen(
      (bytes) => _appendOutput(agent.name, bytes),
      onError:
          (Object error) => _handleStreamError(
            agentName: agent.name,
            session: session,
            subscription: subscription,
            error: error,
          ),
      onDone:
          () => _handleStreamDone(
            agentName: agent.name,
            session: session,
            subscription: subscription,
          ),
    );
    _outputStreams[agent.name] = subscription;
    return session;
  }

  void _appendOutput(String agentName, Uint8List bytes) {
    if (_disposed || _events.isClosed) {
      return;
    }
    final body = utf8.decode(bytes, allowMalformed: true).trim();
    if (body.isEmpty) {
      return;
    }
    final echoText = _normalizedEchoText(body);
    if (echoText != null && _consumePendingEcho(agentName, echoText)) {
      return;
    }
    _events.add(
      PaneChatEvent(
        agentName: agentName,
        kind: PaneChatEventKind.output,
        body: body,
      ),
    );
  }

  void _appendNotice(String agentName, String body) {
    if (_disposed || _events.isClosed) {
      return;
    }
    _events.add(
      PaneChatEvent(
        agentName: agentName,
        kind: PaneChatEventKind.notice,
        body: body,
      ),
    );
  }

  void _handleStreamError({
    required String agentName,
    required TerminalSession session,
    required StreamSubscription<Uint8List> subscription,
    required Object error,
  }) {
    _dropSession(
      agentName: agentName,
      session: session,
      subscription: subscription,
    );
    _appendNotice(agentName, error.toString());
  }

  void _handleStreamDone({
    required String agentName,
    required TerminalSession session,
    required StreamSubscription<Uint8List> subscription,
  }) {
    _dropSession(
      agentName: agentName,
      session: session,
      subscription: subscription,
    );
    _appendNotice(agentName, 'Terminal stream closed');
  }

  void _dropSession({
    required String agentName,
    required TerminalSession session,
    required StreamSubscription<Uint8List> subscription,
  }) {
    if (identical(_sessions[agentName], session)) {
      _sessions.remove(agentName);
      _pendingEchoes.remove(agentName);
    }
    if (identical(_outputStreams[agentName], subscription)) {
      _outputStreams.remove(agentName);
    }
    unawaited(subscription.cancel());
    unawaited(_closeSession(session));
  }

  void _discardSession(String agentName, TerminalSession session) {
    if (identical(_sessions[agentName], session)) {
      _sessions.remove(agentName);
      _pendingEchoes.remove(agentName);
    }
    final subscription = _outputStreams.remove(agentName);
    if (subscription != null) {
      unawaited(subscription.cancel());
    }
    unawaited(_closeSession(session));
  }

  String? _normalizedEchoText(String text) {
    final normalized = text.trim();
    return normalized.isEmpty ? null : normalized;
  }

  bool _consumePendingEcho(String agentName, String text) {
    final items = _pendingEchoes[agentName];
    if (items == null) {
      return false;
    }
    final index = items.indexOf(text);
    if (index == -1) {
      _pendingEchoes.remove(agentName);
      return false;
    }
    items.removeAt(index);
    if (items.isEmpty) {
      _pendingEchoes.remove(agentName);
    }
    return true;
  }

  Future<void> _closeSession(TerminalSession session) async {
    try {
      await session.close();
    } catch (_) {
      // Disposal is best-effort; close errors should not mask UI teardown.
    }
  }
}
