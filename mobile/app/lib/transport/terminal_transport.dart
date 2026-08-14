import 'dart:typed_data';

import '../models/ccb_terminal_target.dart';
import '../tmux/tmux_command_builder.dart';

class TerminalGeometry {
  const TerminalGeometry({
    this.columns = 80,
    this.rows = 24,
    this.pixelWidth = 0,
    this.pixelHeight = 0,
  }) : assert(columns > 0),
       assert(rows > 0),
       assert(pixelWidth >= 0),
       assert(pixelHeight >= 0);

  final int columns;
  final int rows;
  final int pixelWidth;
  final int pixelHeight;

  @override
  bool operator ==(Object other) {
    return other is TerminalGeometry &&
        other.columns == columns &&
        other.rows == rows &&
        other.pixelWidth == pixelWidth &&
        other.pixelHeight == pixelHeight;
  }

  @override
  int get hashCode => Object.hash(columns, rows, pixelWidth, pixelHeight);
}

enum TerminalResizePolicy {
  adaptivePane('adaptive_pane'),
  fixedSource('fixed_source'),
  client('client');

  const TerminalResizePolicy(this.wireName);

  final String wireName;

  static TerminalResizePolicy fromWireName(String value) {
    return values.firstWhere(
      (candidate) => candidate.wireName == value,
      orElse:
          () => throw FormatException('unknown terminal resize policy: $value'),
    );
  }
}

class TerminalViewport {
  const TerminalViewport({
    required this.geometry,
    required this.resizePolicy,
    this.revision = 0,
  }) : assert(revision >= 0);

  final TerminalGeometry geometry;
  final TerminalResizePolicy resizePolicy;
  final int revision;

  bool get hasFixedSourceGeometry =>
      resizePolicy == TerminalResizePolicy.fixedSource ||
      resizePolicy == TerminalResizePolicy.adaptivePane;

  bool get acceptsClientResize => resizePolicy == TerminalResizePolicy.client;
}

class TerminalOpenRequest {
  TerminalOpenRequest({
    required this.target,
    this.geometry = const TerminalGeometry(),
    this.terminalType = 'xterm-256color',
  }) : attachCommand = _buildAttachCommand(target, requireDirectAttach: true) {
    _validateTerminalType(terminalType);
  }

  TerminalOpenRequest.gateway({
    required this.target,
    this.geometry = const TerminalGeometry(),
    this.terminalType = 'xterm-256color',
  }) : attachCommand = _buildAttachCommand(target, requireDirectAttach: false) {
    _validateTerminalType(terminalType);
  }

  static void _validateTerminalType(String terminalType) {
    if (terminalType.trim().isEmpty) {
      throw ArgumentError.value(terminalType, 'terminalType', 'required');
    }
  }

  final CcbTerminalTarget target;
  final TerminalGeometry geometry;
  final String terminalType;
  final String attachCommand;

  static String _buildAttachCommand(
    CcbTerminalTarget target, {
    required bool requireDirectAttach,
  }) {
    if (!target.canAcceptTerminalInput) {
      throw StateError(
        'terminal target requires project identity, namespace epoch, stable '
        'agent/window identity, and terminal_input scope',
      );
    }
    if (!requireDirectAttach) {
      final identity =
          target.agent ?? target.window ?? target.paneId ?? 'terminal';
      return 'gateway terminal stream ${target.projectId}/$identity';
    }
    final builder = TmuxCommandBuilder.forTarget(target);
    return TmuxCommandBuilder.shellCommand(builder.attachSession());
  }
}

abstract interface class TerminalTransport {
  Future<TerminalSession> open(TerminalOpenRequest request);
}

class HostTerminalOpenRequest {
  HostTerminalOpenRequest({
    required this.clientSessionId,
    required this.displayName,
    this.geometry = const TerminalGeometry(),
    this.terminalType = 'xterm-256color',
  }) {
    if (!RegExp(r'^shell-[1-9][0-9]*$').hasMatch(clientSessionId)) {
      throw ArgumentError.value(
        clientSessionId,
        'clientSessionId',
        'expected shell-N',
      );
    }
    TerminalOpenRequest._validateTerminalType(terminalType);
  }

  final String clientSessionId;
  final String displayName;
  final TerminalGeometry geometry;
  final String terminalType;

  String get attachCommand => 'host shell $clientSessionId (~)';
}

abstract interface class HostTerminalTransport {
  Future<TerminalSession> openHostTerminal(HostTerminalOpenRequest request);

  Future<void> terminateHostTerminal(String clientSessionId);
}

abstract interface class TerminalSession {
  String get launchedCommand;

  Stream<Uint8List> get output;

  Future<void> writeBytes(List<int> bytes);

  Future<void> paste(String text);

  Future<void> resize(TerminalGeometry geometry);

  Future<void> reconnect();

  Future<void> close();
}

abstract interface class TerminalViewportSession {
  TerminalViewport get viewport;

  Stream<TerminalViewport> get viewportChanges;
}

class TerminalTransportException implements Exception {
  const TerminalTransportException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() {
    final causeText = cause == null ? '' : ': $cause';
    return 'TerminalTransportException($message$causeText)';
  }
}
