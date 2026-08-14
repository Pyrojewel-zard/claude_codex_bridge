import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'gateway_transport.dart';
import 'gateway_connection_outcome.dart';
import 'terminal_transport.dart';

class GatewayTerminalTransport
    implements
        TerminalTransport,
        HostTerminalTransport,
        GatewayConnectionOutcomeReportable {
  GatewayTerminalTransport({
    required GatewayTransport transport,
    Duration connectionTimeout = const Duration(seconds: 5),
  }) : _transport = transport,
       _connectionTimeout = connectionTimeout;

  final GatewayTransport _transport;
  final Duration _connectionTimeout;
  GatewayConnectionOutcomeReporter? _outcomeReporter;
  final _sessions = <_GatewayTerminalSession>{};

  @override
  set outcomeReporter(GatewayConnectionOutcomeReporter? reporter) {
    _outcomeReporter = reporter;
    for (final session in _sessions) {
      session.outcomeReporter = reporter;
    }
  }

  @override
  Future<TerminalSession> open(TerminalOpenRequest request) async {
    try {
      final handle = await _transport.openTerminal(
        GatewayTerminalOpenRequest.fromCcbTarget(
          request.target,
          geometry: request.geometry,
        ),
      );
      final session = _GatewayTerminalSession(
        transport: _transport,
        handle: handle,
        geometry: request.geometry,
        launchedCommand: request.attachCommand,
        handleOpener:
            (geometry) => _transport.openTerminal(
              GatewayTerminalOpenRequest.fromCcbTarget(
                request.target,
                geometry: geometry,
              ),
            ),
        outcomeReporter: _outcomeReporter,
        onClosed: _sessions.remove,
        connectionTimeout: _connectionTimeout,
      );
      _sessions.add(session);
      return session;
    } catch (error) {
      _outcomeReporter?.failed(GatewayConnectionOperation.terminal, error);
      rethrow;
    }
  }

  @override
  Future<TerminalSession> openHostTerminal(
    HostTerminalOpenRequest request,
  ) async {
    final transport = _transport;
    if (transport is! GatewayHostTerminalTransport) {
      throw const TerminalTransportException(
        'gateway does not support host terminals',
      );
    }
    final hostTransport = transport as GatewayHostTerminalTransport;
    try {
      final handle = await hostTransport.openHostTerminal(
        GatewayHostTerminalOpenRequest(
          clientSessionId: request.clientSessionId,
          displayName: request.displayName,
          geometry: request.geometry,
        ),
      );
      final session = _GatewayTerminalSession(
        transport: _transport,
        handle: handle,
        geometry: request.geometry,
        launchedCommand: request.attachCommand,
        handleOpener:
            (geometry) => hostTransport.openHostTerminal(
              GatewayHostTerminalOpenRequest(
                clientSessionId: request.clientSessionId,
                displayName: request.displayName,
                geometry: geometry,
              ),
            ),
        outcomeReporter: _outcomeReporter,
        onClosed: _sessions.remove,
        connectionTimeout: _connectionTimeout,
      );
      _sessions.add(session);
      return session;
    } catch (error) {
      _outcomeReporter?.failed(GatewayConnectionOperation.terminal, error);
      rethrow;
    }
  }

  @override
  Future<void> terminateHostTerminal(String clientSessionId) async {
    final transport = _transport;
    if (transport is! GatewayHostTerminalTransport) {
      throw const TerminalTransportException(
        'gateway does not support host terminals',
      );
    }
    await (transport as GatewayHostTerminalTransport).terminateHostTerminal(
      clientSessionId: clientSessionId,
    );
  }
}

class _GatewayTerminalSession
    implements TerminalSession, TerminalViewportSession {
  _GatewayTerminalSession({
    required GatewayTransport transport,
    required GatewayTerminalHandle handle,
    required TerminalGeometry geometry,
    required String launchedCommand,
    required Future<GatewayTerminalHandle> Function(TerminalGeometry geometry)
    handleOpener,
    GatewayConnectionOutcomeReporter? outcomeReporter,
    required void Function(_GatewayTerminalSession session) onClosed,
    required Duration connectionTimeout,
  }) : _transport = transport,
       _handle = handle,
       _launchedCommand = launchedCommand,
       _handleOpener = handleOpener,
       _outcomeReporter = outcomeReporter,
       _onClosed = onClosed,
       _connectionTimeout = connectionTimeout,
       _geometry = geometry,
       _viewport = TerminalViewport(
         geometry: geometry,
         resizePolicy:
             handle.targetSummary.projectId == '@host'
                 ? TerminalResizePolicy.client
                 : TerminalResizePolicy.fixedSource,
       ) {
    unawaited(
      _connect().catchError((Object error, StackTrace stackTrace) {
        if (!_closed) {
          _output.addError(error, stackTrace);
        }
      }),
    );
  }

  final GatewayTransport _transport;
  final String _launchedCommand;
  final Future<GatewayTerminalHandle> Function(TerminalGeometry geometry)
  _handleOpener;
  GatewayTerminalHandle _handle;
  TerminalGeometry _geometry;
  TerminalViewport _viewport;
  final _output = StreamController<Uint8List>.broadcast();
  final _viewportChanges = StreamController<TerminalViewport>.broadcast();
  StreamSubscription<GatewayTerminalFrame>? _subscription;
  Future<void>? _reconnection;
  Future<void>? _renewal;
  Completer<void>? _connectionReady;
  var _connectionGeneration = 0;
  int? _settledConnectionGeneration;
  int _nextInputSequence = 1;
  int _resumeCursor = 0;
  bool _closed = false;
  GatewayConnectionOutcomeReporter? _outcomeReporter;
  final void Function(_GatewayTerminalSession session) _onClosed;
  final Duration _connectionTimeout;

  set outcomeReporter(GatewayConnectionOutcomeReporter? reporter) {
    _outcomeReporter = reporter;
  }

  @override
  String get launchedCommand => _launchedCommand;

  @override
  Stream<Uint8List> get output => _output.stream;

  @override
  TerminalViewport get viewport => _viewport;

  @override
  Stream<TerminalViewport> get viewportChanges => _viewportChanges.stream;

  @override
  Future<void> writeBytes(List<int> bytes) {
    return _sendSequenced(
      GatewayTerminalFrame.input(
        sequence: _nextInputSequence++,
        bytes: List<int>.from(bytes),
      ),
    );
  }

  @override
  Future<void> paste(String text) {
    return _sendSequenced(
      GatewayTerminalFrame.paste(sequence: _nextInputSequence++, text: text),
    );
  }

  @override
  Future<void> resize(TerminalGeometry geometry) {
    if (!_viewport.acceptsClientResize) {
      return Future<void>.value();
    }
    _geometry = geometry;
    _applyViewport(
      TerminalViewport(
        geometry: geometry,
        resizePolicy: _viewport.resizePolicy,
        revision: _viewport.revision + 1,
      ),
    );
    return _sendMutation(GatewayTerminalFrame.resize(geometry));
  }

  @override
  Future<void> reconnect() {
    if (_closed) {
      return Future<void>.error(
        const TerminalTransportException('gateway terminal is closed'),
      );
    }
    final existing = _reconnection;
    if (existing != null) {
      return existing;
    }
    late final Future<void> operation;
    operation = _performReconnect().whenComplete(() {
      if (identical(_reconnection, operation)) {
        _reconnection = null;
      }
    });
    _reconnection = operation;
    return operation;
  }

  Future<void> _performReconnect() async {
    final renewal = _renewal;
    if (renewal != null) {
      await renewal;
      return;
    }
    _connectionGeneration += 1;
    await _cancelSubscription();
    await _connect(resumeCursor: _resumeCursor);
  }

  @override
  Future<void> close() async {
    if (_closed) {
      return;
    }
    _closed = true;
    final pendingRenewal = _renewal;
    Object? primaryError;
    StackTrace? primaryStackTrace;
    Object? cleanupError;
    StackTrace? cleanupStackTrace;
    try {
      await _sendMutation(GatewayTerminalFrame.closed('client_closed'));
    } catch (error, stackTrace) {
      primaryError = error;
      primaryStackTrace = stackTrace;
    } finally {
      _connectionGeneration += 1;
      _outcomeReporter = null;
      try {
        await _cancelSubscription();
      } catch (error, stackTrace) {
        cleanupError = error;
        cleanupStackTrace = stackTrace;
      } finally {
        try {
          await _closeOutput();
        } catch (error, stackTrace) {
          cleanupError ??= error;
          cleanupStackTrace ??= stackTrace;
        } finally {
          _onClosed(this);
        }
      }
    }
    if (pendingRenewal != null) {
      try {
        await pendingRenewal;
      } catch (error, stackTrace) {
        cleanupError ??= error;
        cleanupStackTrace ??= stackTrace;
      }
    }
    if (primaryError != null) {
      Error.throwWithStackTrace(primaryError, primaryStackTrace!);
    }
    if (cleanupError != null) {
      Error.throwWithStackTrace(cleanupError, cleanupStackTrace!);
    }
  }

  Future<void> _sendSequenced(GatewayTerminalFrame frame) async {
    final renewal = _renewal;
    if (renewal != null) {
      await renewal;
    }
    return _sendMutation(frame);
  }

  Future<void> _sendMutation(GatewayTerminalFrame frame) async {
    try {
      await _transport.sendTerminalFrame(_handle, frame);
    } catch (error) {
      _outcomeReporter?.failed(GatewayConnectionOperation.mutation, error);
      rethrow;
    }
  }

  Future<void> _connect({int? resumeCursor}) async {
    final ready = Completer<void>();
    final generation = ++_connectionGeneration;
    _connectionReady = ready;
    _subscription = _transport
        .terminalFrames(_handle, resumeCursor: resumeCursor)
        .listen(
          (frame) => _handleFrame(generation, frame),
          onError:
              (Object error, StackTrace stackTrace) =>
                  _handleTransportError(generation, error, stackTrace),
          onDone: () => _handleDone(generation),
        );
    try {
      await ready.future.timeout(
        _connectionTimeout,
        onTimeout:
            () =>
                throw const TerminalTransportException(
                  'terminal stream connect timeout',
                ),
      );
    } catch (error, stackTrace) {
      // Frame/transport errors already completed the readiness completer and
      // reported themselves. A timeout has not, so report it structurally.
      if (!ready.isCompleted) {
        _completeConnectionError(generation, error, stackTrace);
        if (generation == _connectionGeneration) {
          await _cancelSubscription();
        }
      }
      rethrow;
    }
  }

  void _handleFrame(int generation, GatewayTerminalFrame frame) {
    if (!_isCurrentConnection(generation)) return;
    switch (frame.type) {
      case GatewayTerminalFrameType.output:
        final sequence = _int(frame.payload['seq']);
        if (sequence > _resumeCursor) {
          _resumeCursor = sequence;
        }
        final bytes = base64Decode(
          (frame.payload['bytes_b64'] ?? '').toString(),
        );
        _output.add(Uint8List.fromList(bytes));
      case GatewayTerminalFrameType.error:
        final code =
            (frame.payload['code'] ?? 'gateway terminal error').toString();
        if (_isRenewableTerminalError(code)) {
          _scheduleRenewTerminalHandle();
          return;
        }
        _completeConnectionError(generation, TerminalTransportException(code));
        _output.addError(TerminalTransportException(code));
      case GatewayTerminalFrameType.closed:
        _completeConnectionError(
          generation,
          const TerminalTransportException('terminal stream closed'),
        );
        _closeOutput();
      case GatewayTerminalFrameType.open:
        final viewport = _viewportFromFrame(frame);
        if (viewport != null) {
          _applyViewport(viewport);
        }
        final sequence = _int(frame.payload['last_input_seq']);
        if (sequence >= _nextInputSequence) {
          _nextInputSequence = sequence + 1;
        }
        _completeConnectionReady(generation);
      case GatewayTerminalFrameType.input:
      case GatewayTerminalFrameType.paste:
      case GatewayTerminalFrameType.resize:
      case GatewayTerminalFrameType.geometry:
        final viewport = _viewportFromFrame(frame);
        if (viewport != null) {
          _applyViewport(viewport);
        }
    }
  }

  TerminalViewport? _viewportFromFrame(GatewayTerminalFrame frame) {
    final geometryValue = frame.payload['geometry'];
    final geometryPayload =
        geometryValue is Map
            ? {
              for (final entry in geometryValue.entries)
                entry.key.toString(): entry.value,
            }
            : frame.payload;
    final policy = (frame.payload['resize_policy'] ?? '').toString().trim();
    if (policy.isEmpty ||
        geometryPayload['columns'] == null ||
        geometryPayload['rows'] == null) {
      return null;
    }
    return TerminalViewport(
      geometry: TerminalGeometry(
        columns: _int(geometryPayload['columns']),
        rows: _int(geometryPayload['rows']),
        pixelWidth: _int(geometryPayload['pixel_width']),
        pixelHeight: _int(geometryPayload['pixel_height']),
      ),
      resizePolicy: TerminalResizePolicy.fromWireName(policy),
      revision: _int(
        frame.payload[frame.type == GatewayTerminalFrameType.open
            ? 'geometry_revision'
            : 'revision'],
      ),
    );
  }

  void _applyViewport(TerminalViewport viewport) {
    if (_viewport.geometry == viewport.geometry &&
        _viewport.resizePolicy == viewport.resizePolicy &&
        _viewport.revision == viewport.revision) {
      return;
    }
    _viewport = viewport;
    _geometry = viewport.geometry;
    if (!_viewportChanges.isClosed) {
      _viewportChanges.add(viewport);
    }
  }

  void _handleDone(int generation) {
    if (!_isCurrentConnection(generation)) return;
    if (!_closed && !_output.isClosed) {
      const error = TerminalTransportException('terminal stream disconnected');
      _completeConnectionError(generation, error);
      _output.addError(error);
    }
  }

  void _handleTransportError(
    int generation,
    Object error,
    StackTrace stackTrace,
  ) {
    if (!_isCurrentConnection(generation)) return;
    if (_isRenewableTerminalException(error)) {
      _scheduleRenewTerminalHandle();
      return;
    }
    _completeConnectionError(generation, error, stackTrace);
    _output.addError(error, stackTrace);
  }

  void _scheduleRenewTerminalHandle() {
    final connection = _connectionReady;
    final renewal = _renewTerminalHandle();
    renewal
        .then((_) {
          if (connection != null && !connection.isCompleted) {
            connection.complete();
          }
        })
        .catchError((Object error, StackTrace stackTrace) {
          _outcomeReporter?.failed(GatewayConnectionOperation.terminal, error);
          if (connection != null && !connection.isCompleted) {
            connection.completeError(error, stackTrace);
          }
          if (!_closed) {
            _output.addError(error, stackTrace);
          }
        });
  }

  Future<void> _renewTerminalHandle() {
    if (_closed) {
      return Future<void>.value();
    }
    final existing = _renewal;
    if (existing != null) {
      return existing;
    }
    final renewal = _doRenewTerminalHandle();
    _renewal = renewal;
    return renewal.whenComplete(() {
      if (identical(_renewal, renewal)) {
        _renewal = null;
      }
    });
  }

  Future<void> _doRenewTerminalHandle() async {
    _connectionGeneration += 1;
    await _cancelSubscription();
    final handle = await _handleOpener(_geometry);
    if (_closed) {
      try {
        await _transport.sendTerminalFrame(
          handle,
          GatewayTerminalFrame.closed('client_closed'),
        );
      } catch (_) {
        // The session is already closing; token cleanup is best effort.
      }
      return;
    }
    _handle = handle;
    _resumeCursor = 0;
    await _connect();
  }

  void _completeConnectionReady(int generation) {
    if (!_isCurrentConnection(generation) ||
        _settledConnectionGeneration == generation) {
      return;
    }
    _settledConnectionGeneration = generation;
    _outcomeReporter?.succeeded(GatewayConnectionOperation.terminal);
    final connection = _connectionReady;
    if (connection != null && !connection.isCompleted) {
      connection.complete();
    }
  }

  void _completeConnectionError(
    int generation,
    Object error, [
    StackTrace? stackTrace,
  ]) {
    if (!_isCurrentConnection(generation) ||
        _settledConnectionGeneration == generation) {
      return;
    }
    _settledConnectionGeneration = generation;
    _outcomeReporter?.failed(GatewayConnectionOperation.terminal, error);
    final connection = _connectionReady;
    if (connection != null && !connection.isCompleted) {
      if (stackTrace == null) {
        connection.completeError(error);
      } else {
        connection.completeError(error, stackTrace);
      }
    }
  }

  Future<void> _closeOutput() async {
    if (!_output.isClosed) {
      await _output.close();
    }
    if (!_viewportChanges.isClosed) {
      await _viewportChanges.close();
    }
  }

  Future<void> _cancelSubscription() async {
    final subscription = _subscription;
    _subscription = null;
    if (subscription == null) {
      return;
    }
    try {
      await subscription.cancel().timeout(const Duration(seconds: 2));
    } on TimeoutException {
      // Reconnect and renewal must not hang forever on a stalled socket close.
    }
  }

  bool _isCurrentConnection(int generation) =>
      !_closed && generation == _connectionGeneration;
}

bool _isRenewableTerminalException(Object error) {
  if (error is TerminalTransportException) {
    return _isRenewableTerminalError(error.message);
  }
  final text = error.toString().toLowerCase();
  return text.contains('connection closed before full header') ||
      (text.contains('websocket') && text.contains('/v1/terminals/'));
}

bool _isRenewableTerminalError(String code) {
  final normalized = code.trim().toLowerCase();
  return normalized == 'expired' ||
      normalized == 'terminal_token_expired' ||
      normalized == 'token_expired' ||
      normalized == 'stale_resume_cursor' ||
      normalized == 'invalid_token' ||
      normalized == 'closed' ||
      normalized == 'terminal_output_error' ||
      normalized == 'terminal_stream_error' ||
      normalized == 'terminal_token_denied';
}

int _int(Object? value) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString()) ?? 0;
}
