import 'dart:async';
import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:xterm/xterm.dart';

import '../../app/terminal_shortcut_preferences.dart';
import '../../models/ccb_project_view.dart';
import '../../models/ccb_terminal_target.dart';
import '../../tmux/tmux_command_builder.dart';
import '../../transport/gateway_terminal_transport.dart';
import '../../transport/terminal_transport.dart';
import 'terminal_history_scroll_controller.dart';
import 'terminal_shortcut_settings.dart';

class AgentTerminalPane extends StatefulWidget {
  const AgentTerminalPane({
    required this.view,
    required this.target,
    required this.terminalTransport,
    this.gatewayTerminal = false,
    this.showHeader = true,
    this.active = true,
    this.onUserScrollDirectionChanged,
    super.key,
  });

  final CcbProjectView view;
  final CcbTerminalTarget target;
  final TerminalTransport? terminalTransport;
  final bool gatewayTerminal;
  final bool showHeader;
  final bool active;
  final ValueChanged<ScrollDirection>? onUserScrollDirectionChanged;

  @override
  State<AgentTerminalPane> createState() => _AgentTerminalPaneState();
}

class _AgentTerminalPaneState extends State<AgentTerminalPane> {
  @override
  Widget build(BuildContext context) {
    final model = AgentTerminalPaneModel.fromViewAndTarget(
      view: widget.view,
      target: widget.target,
    );
    final transport = widget.terminalTransport;
    if (transport == null) {
      return _FakeTerminalPane(
        model: model,
        showHeader: widget.showHeader,
        onUserScrollDirectionChanged: widget.onUserScrollDirectionChanged,
      );
    }
    return LiveTerminalPane(
      title: model.title,
      subtitle: model.attachCommand,
      sessionIdentity: _terminalTargetIdentity(widget.target),
      openSession: (geometry) {
        final request =
            widget.gatewayTerminal || transport is GatewayTerminalTransport
                ? TerminalOpenRequest.gateway(
                  target: widget.target,
                  geometry: geometry,
                )
                : TerminalOpenRequest(
                  target: widget.target,
                  geometry: geometry,
                );
        return transport.open(request);
      },
      showHeader: widget.showHeader,
      active: widget.active,
      sourcePaneMirror: true,
      onUserScrollDirectionChanged: widget.onUserScrollDirectionChanged,
    );
  }
}

class AgentTerminalPaneModel {
  const AgentTerminalPaneModel({
    required this.view,
    required this.target,
    required this.attachCommand,
  });

  final CcbProjectView view;
  final CcbTerminalTarget target;
  final String attachCommand;

  factory AgentTerminalPaneModel.fromViewAndTarget({
    required CcbProjectView view,
    required CcbTerminalTarget target,
  }) {
    final attachCommand =
        target.hasDirectTmuxAttachEvidence
            ? TmuxCommandBuilder.shellCommand(
              TmuxCommandBuilder.forTarget(target).attachSession(),
            )
            : 'gateway terminal stream ${target.projectId}/${target.agent ?? target.window ?? 'terminal'}';
    return AgentTerminalPaneModel(
      view: view,
      target: target,
      attachCommand: attachCommand,
    );
  }

  String get title {
    return '${view.project.displayName} / ${target.agent ?? target.window ?? 'terminal'}';
  }
}

class _FakeTerminalPane extends StatefulWidget {
  const _FakeTerminalPane({
    required this.model,
    required this.showHeader,
    this.onUserScrollDirectionChanged,
  });

  final AgentTerminalPaneModel model;
  final bool showHeader;
  final ValueChanged<ScrollDirection>? onUserScrollDirectionChanged;

  @override
  State<_FakeTerminalPane> createState() => _FakeTerminalPaneState();
}

class _FakeTerminalPaneState extends State<_FakeTerminalPane> {
  late final Terminal _terminal;
  late final TerminalHistoryScrollController _scrollController;

  @override
  void initState() {
    super.initState();
    _scrollController = TerminalHistoryScrollController(
      debugLabel: 'fake-terminal-history',
      onUserScrollDirectionChanged: widget.onUserScrollDirectionChanged,
    );
    _terminal = Terminal(maxLines: 2000);
    _writeTranscript();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _writeTranscript() {
    final target = widget.model.target;
    _terminal.write('\x1b[32mCCB Mobile fake terminal\x1b[0m\r\n');
    _terminal.write('project: ${target.projectId}\r\n');
    _terminal.write('agent: ${target.agent ?? ''}\r\n');
    _terminal.write('window: ${target.window ?? ''}\r\n');
    _terminal.write('pane evidence: ${target.paneId ?? ''}\r\n');
    _terminal.write('namespace epoch: ${target.namespaceEpoch}\r\n');
    _terminal.write('\r\n');
    _terminal.write('\$ ${widget.model.attachCommand}\r\n');
    _terminal.write('\r\n');
    _terminal.write('fake transport only; live PTY is not connected yet\r\n');
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (widget.showHeader)
          AgentTerminalHeader(
            title: widget.model.title,
            subtitle: widget.model.attachCommand,
            trailing: 'Fake',
          ),
        Expanded(
          child: TerminalView(
            _terminal,
            key: const ValueKey('ccb-terminal-view'),
            autofocus: false,
            readOnly: true,
            scrollController: _scrollController,
            padding: const EdgeInsets.fromLTRB(6, 4, 6, 4),
          ),
        ),
      ],
    );
  }
}

typedef TerminalSessionOpener =
    Future<TerminalSession> Function(TerminalGeometry geometry);

class LiveTerminalPaneController {
  _LiveTerminalPaneState? _state;

  Future<void> closeSession() async {
    await _state?._closeForRemoval();
  }

  void _attach(_LiveTerminalPaneState state) {
    assert(_state == null || identical(_state, state));
    _state = state;
  }

  void _detach(_LiveTerminalPaneState state) {
    if (identical(_state, state)) {
      _state = null;
    }
  }
}

class LiveTerminalPane extends StatefulWidget {
  const LiveTerminalPane({
    required this.title,
    required this.subtitle,
    required this.sessionIdentity,
    required this.openSession,
    required this.showHeader,
    required this.active,
    this.sourcePaneMirror = false,
    this.onUserScrollDirectionChanged,
    this.controller,
    this.terminalViewKey = const ValueKey('ccb-live-terminal-view'),
    this.scrollDebugLabel = 'terminal-history',
    super.key,
  });

  final String title;
  final String subtitle;
  final String sessionIdentity;
  final TerminalSessionOpener openSession;
  final bool showHeader;
  final bool active;
  final bool sourcePaneMirror;
  final ValueChanged<ScrollDirection>? onUserScrollDirectionChanged;
  final LiveTerminalPaneController? controller;
  final Key terminalViewKey;
  final String scrollDebugLabel;

  @override
  State<LiveTerminalPane> createState() => _LiveTerminalPaneState();
}

class _LiveTerminalPaneState extends State<LiveTerminalPane>
    with WidgetsBindingObserver {
  static const _terminalPadding = EdgeInsets.fromLTRB(6, 4, 6, 4);
  static const _autoReconnectBackoff = <Duration>[
    Duration(seconds: 1),
    Duration(seconds: 2),
    Duration(seconds: 4),
    Duration(seconds: 8),
  ];

  late final Terminal _terminal;
  late final TerminalHistoryScrollController _terminalScrollController;
  final _terminalViewKey = GlobalKey<TerminalViewState>();
  Future<TerminalSession>? _sessionFuture;
  Future<TerminalSession>? _openingFuture;
  TerminalSession? _session;
  StreamSubscription<String>? _outputSubscription;
  StreamSubscription<TerminalViewport>? _viewportSubscription;
  Timer? _autoReconnectTimer;
  Timer? _resizeDebounce;
  var _openGeneration = 0;
  var _autoReconnectAttempt = 0;
  var _autoReconnectBlocked = false;
  var _closingForRemoval = false;
  TerminalGeometry _lastGeometry = const TerminalGeometry(
    columns: 100,
    rows: 30,
    pixelWidth: 960,
    pixelHeight: 640,
  );
  TerminalViewport _viewport = const TerminalViewport(
    geometry: TerminalGeometry(columns: 100, rows: 30),
    resizePolicy: TerminalResizePolicy.fixedSource,
  );
  double _readableFontSize = ccbTerminalDefaultFontSize;
  final Set<int> _activePointers = <int>{};
  String _controlStatus = 'Connecting';
  bool _terminalInputActive = false;
  bool _terminalKeyboardWasVisible = false;
  int? _terminalTapPointer;
  Offset? _terminalTapOrigin;

  @override
  void initState() {
    super.initState();
    widget.controller?._attach(this);
    WidgetsBinding.instance.addObserver(this);
    _terminalScrollController = TerminalHistoryScrollController(
      debugLabel: widget.scrollDebugLabel,
      onUserScrollDirectionChanged: widget.onUserScrollDirectionChanged,
    )..addListener(_handleTerminalScrollChanged);
    _viewport = TerminalViewport(
      geometry: _lastGeometry,
      resizePolicy:
          widget.sourcePaneMirror
              ? TerminalResizePolicy.fixedSource
              : TerminalResizePolicy.client,
    );
    _terminal = Terminal(
      maxLines: 4000,
      onOutput: (data) {
        if (_isTerminalAutoReportReply(data)) {
          return;
        }
        _writeTerminalBytes(utf8.encode(data));
      },
      onResize: (width, height, pixelWidth, pixelHeight) {
        _handleTerminalResize(
          TerminalGeometry(
            columns: width,
            rows: height,
            pixelWidth: pixelWidth,
            pixelHeight: pixelHeight,
          ),
        );
      },
    );
    _startSession(clearTerminal: false);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _readableFontSize =
        CcbTerminalShortcutPreferencesScope.maybeOf(
          context,
        )?.preferences.fontSize ??
        ccbTerminalDefaultFontSize;
  }

  @override
  void didUpdateWidget(covariant LiveTerminalPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.controller, widget.controller)) {
      oldWidget.controller?._detach(this);
      widget.controller?._attach(this);
    }
    if (oldWidget.active && !widget.active) {
      _deactivateTerminalInput();
    }
    if (oldWidget.sessionIdentity != widget.sessionIdentity) {
      _closingForRemoval = false;
      _startSession(clearTerminal: true);
    }
  }

  void _startSession({
    required bool clearTerminal,
    bool resetReconnect = true,
  }) {
    if (_closingForRemoval) {
      return;
    }
    _openGeneration += 1;
    final generation = _openGeneration;
    if (resetReconnect) {
      _resetAutoReconnect();
    } else {
      _cancelAutoReconnectTimer();
    }
    _setControlStatus('Connecting');
    final rawFuture = _replaceSession(generation, clearTerminal: clearTerminal);
    _openingFuture = rawFuture;
    unawaited(
      rawFuture.then<void>(
        (_) {
          if (identical(_openingFuture, rawFuture)) {
            _openingFuture = null;
          }
        },
        onError: (Object _, StackTrace _) {
          if (identical(_openingFuture, rawFuture)) {
            _openingFuture = null;
          }
        },
      ),
    );
    final future =
        resetReconnect
            ? rawFuture
            : rawFuture.catchError((_) => Completer<TerminalSession>().future);
    setState(() {
      _sessionFuture = future;
    });
  }

  Future<TerminalSession> _replaceSession(
    int generation, {
    required bool clearTerminal,
  }) async {
    await _closeCurrentSession();
    if (!mounted || _closingForRemoval || generation != _openGeneration) {
      throw const TerminalTransportException('stale terminal session');
    }
    if (clearTerminal) {
      _terminal.write('\x1b[2J\x1b[H');
    }
    return _openSession(generation);
  }

  Future<TerminalSession> _openSession(int generation) async {
    late final TerminalSession session;
    try {
      session = await widget.openSession(_lastGeometry);
    } catch (error) {
      if (mounted && generation == _openGeneration) {
        _terminal.write('\r\n\x1b[33m$error\x1b[0m\r\n');
        _handleReconnectFailure(generation, error);
      }
      rethrow;
    }
    if (!mounted || _closingForRemoval || generation != _openGeneration) {
      await session.close();
      throw const TerminalTransportException('stale terminal session');
    }
    _session = session;
    _observeViewport(session);
    _resetAutoReconnect();
    _setControlStatus('Connected');
    _outputSubscription = session.output
        .map<List<int>>((bytes) => bytes)
        .transform(utf8.decoder)
        .listen(
          _terminal.write,
          onError: (Object error) {
            if (generation != _openGeneration) {
              return;
            }
            _terminal.write('\r\n\x1b[31m$error\x1b[0m\r\n');
            _scheduleAutoReconnect(generation, error: error);
          },
          onDone: () {
            if (generation != _openGeneration) {
              return;
            }
            _session = null;
            _scheduleAutoReconnect(generation);
          },
        );
    return session;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && _terminalInputActive) {
      _deactivateTerminalInput();
    }
    if (state == AppLifecycleState.resumed &&
        _isReconnectableStatus(_controlStatus) &&
        !_closingForRemoval &&
        !_autoReconnectBlocked) {
      unawaited(_reconnect());
    }
  }

  @override
  void didChangeMetrics() {
    super.didChangeMetrics();
    if (!mounted || !_terminalInputActive) {
      return;
    }
    final keyboardVisible = View.of(context).viewInsets.bottom > 0;
    if (keyboardVisible) {
      _terminalKeyboardWasVisible = true;
      return;
    }
    if (_terminalKeyboardWasVisible) {
      _deactivateTerminalInput(closeKeyboard: false);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.controller?._detach(this);
    _openGeneration += 1;
    _closingForRemoval = true;
    _cancelAutoReconnectTimer();
    _resizeDebounce?.cancel();
    unawaited(_closeCurrentSession());
    _terminalScrollController.removeListener(_handleTerminalScrollChanged);
    _terminalScrollController.dispose();
    super.dispose();
  }

  Future<void> _closeForRemoval() async {
    if (_closingForRemoval) {
      final pendingOpen = _openingFuture;
      if (pendingOpen != null) {
        await pendingOpen.then<void>((_) {}, onError: (Object _) {});
      }
      return;
    }
    _closingForRemoval = true;
    _openGeneration += 1;
    _autoReconnectBlocked = true;
    _cancelAutoReconnectTimer();
    _deactivateTerminalInput();
    _setControlStatus('Closing');

    final pendingOpen = _openingFuture;
    await _closeCurrentSession();
    if (pendingOpen != null) {
      await pendingOpen.then<void>((_) {}, onError: (Object _) {});
    }
    await _closeCurrentSession();
  }

  Future<void> _closeCurrentSession() async {
    final subscription = _outputSubscription;
    _outputSubscription = null;
    final viewportSubscription = _viewportSubscription;
    _viewportSubscription = null;
    final session = _session;
    _session = null;
    final cancellation = subscription?.cancel();
    final viewportCancellation = viewportSubscription?.cancel();
    await session?.close().catchError((_) {
      // Best-effort route teardown; the gateway may already have closed.
    });
    if (cancellation != null) {
      unawaited(cancellation.catchError((_) {}));
    }
    if (viewportCancellation != null) {
      unawaited(viewportCancellation.catchError((_) {}));
    }
  }

  void _observeViewport(TerminalSession session) {
    if (session is! TerminalViewportSession) {
      return;
    }
    final viewportSession = session as TerminalViewportSession;
    _applyViewport(viewportSession.viewport);
    _viewportSubscription = viewportSession.viewportChanges.listen(
      _applyViewport,
      onError: (_) {
        // Output owns connection errors. Retain the last valid source grid.
      },
    );
  }

  void _applyViewport(TerminalViewport viewport) {
    if (!mounted) {
      return;
    }
    _viewport = viewport;
    setState(() {});
  }

  void _handleTerminalResize(TerminalGeometry geometry) {
    if (_sameGeometry(_lastGeometry, geometry)) {
      return;
    }
    _lastGeometry = geometry;
    if (!_viewport.acceptsClientResize) {
      // Agent Terminal owns only its local render geometry. The source tmux
      // pane keeps the desktop geometry reported by the gateway.
      return;
    }
    _viewport = TerminalViewport(
      geometry: geometry,
      resizePolicy: _viewport.resizePolicy,
      revision: _viewport.revision + 1,
    );
    _resizeDebounce?.cancel();
    _resizeDebounce = Timer(const Duration(milliseconds: 140), () {
      _session?.resize(geometry);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        setState(() {});
      }
    });
  }

  void _writeTerminalBytes(List<int> bytes) {
    final session = _session;
    if (session == null) {
      return;
    }
    session.writeBytes(bytes).catchError((Object error) {
      // TerminalView can emit control responses while a WebSocket reconnects.
      // Keep those best-effort writes from replacing explicit toolbar status.
    });
  }

  void _activateTerminalInput(bool connected) {
    if (!connected ||
        _terminalInputActive ||
        !_terminalScrollController.isAtLatestOutput) {
      return;
    }
    setState(() {
      _terminalInputActive = true;
      _terminalKeyboardWasVisible = false;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_terminalInputActive) {
        return;
      }
      _terminalViewKey.currentState?.requestKeyboard();
    });
  }

  void _handleTerminalPointerDown(PointerDownEvent event, bool connected) {
    _activePointers.add(event.pointer);
    if (_activePointers.length > 1) {
      _resetTerminalTap();
      return;
    }
    if (!connected || !_terminalScrollController.isAtLatestOutput) {
      _resetTerminalTap();
      return;
    }
    _terminalTapPointer = event.pointer;
    _terminalTapOrigin = event.position;
  }

  void _handleTerminalPointerMove(PointerMoveEvent event) {
    if (_activePointers.length >= 2) {
      _resetTerminalTap();
      return;
    }
    if (_terminalTapPointer != event.pointer || _terminalTapOrigin == null) {
      return;
    }
    if ((event.position - _terminalTapOrigin!).distance > kTouchSlop) {
      _resetTerminalTap();
    }
  }

  void _handleTerminalPointerUp(PointerUpEvent event, bool connected) {
    final hadMultiplePointers = _activePointers.length > 1;
    _activePointers.remove(event.pointer);
    if (!hadMultiplePointers &&
        _terminalTapPointer == event.pointer &&
        _terminalTapOrigin != null) {
      _activateTerminalInput(connected);
    }
    _resetTerminalTap();
  }

  void _handleTerminalPointerCancel(PointerCancelEvent event) {
    _activePointers.remove(event.pointer);
    if (_terminalTapPointer == event.pointer) {
      _resetTerminalTap();
    }
  }

  void _resetTerminalTap() {
    _terminalTapPointer = null;
    _terminalTapOrigin = null;
  }

  void _handleTerminalScrollChanged() {
    if (_terminalInputActive && _terminalScrollController.isReadingHistory) {
      _deactivateTerminalInput();
    }
  }

  void _deactivateTerminalInput({bool closeKeyboard = true}) {
    if (closeKeyboard) {
      _terminalViewKey.currentState?.closeKeyboard();
    }
    _terminalKeyboardWasVisible = false;
    if (!mounted || !_terminalInputActive) {
      return;
    }
    setState(() {
      _terminalInputActive = false;
    });
  }

  static bool _isTerminalAutoReportReply(String data) {
    if (data.isEmpty) {
      return false;
    }
    var offset = 0;
    while (offset < data.length) {
      Match? report;
      for (final pattern in _terminalAutoReportPatterns) {
        report = pattern.matchAsPrefix(data, offset);
        if (report != null) {
          break;
        }
      }
      if (report == null) {
        return false;
      }
      offset = report.end;
    }
    return true;
  }

  static final _terminalAutoReportPatterns = <RegExp>[
    RegExp(r'\x1B\[\?[0-9;]*c'),
    RegExp(r'\x1B\[>[0-9;]*c'),
    RegExp(r'\x1BP!\|[0-9A-Fa-f]*\x1B\\'),
    RegExp(r'\x1B\[0n'),
    RegExp(r'\x1B\[[0-9;]*R'),
    RegExp(r'\x1B\[8;[0-9]+;[0-9]+t'),
    RegExp(r'\x1B\[[IO]'),
    RegExp(r'\x1B\[<[0-9;]+[mM]'),
    RegExp(r'\x1B\]1[01];(?:rgb:)?[0-9A-Fa-f/]+(?:\x07|\x1B\\)'),
  ];

  Future<void> _sendKey(List<int> bytes, String status) async {
    final session = _session;
    if (session == null) {
      _setControlStatus('Connecting');
      return;
    }
    try {
      await session.writeBytes(bytes);
      _setControlStatus(status);
    } catch (error) {
      _setControlStatus('Key failed');
      _terminal.write('\r\n\x1b[31m$error\x1b[0m\r\n');
    }
  }

  Future<void> _reconnect() async {
    if (_closingForRemoval) {
      return;
    }
    _cancelAutoReconnectTimer();
    final session = _session;
    if (session == null) {
      _startSession(clearTerminal: false);
      return;
    }
    try {
      _setControlStatus('Reconnecting');
      await session.reconnect();
      _resetAutoReconnect();
      _setControlStatus('Reconnected');
    } catch (error) {
      _terminal.write('\r\n\x1b[33m$error\x1b[0m\r\n');
      _handleReconnectFailure(_openGeneration, error);
    }
  }

  void _scheduleAutoReconnect(int generation, {Object? error}) {
    if (!mounted ||
        _closingForRemoval ||
        generation != _openGeneration ||
        _autoReconnectBlocked) {
      return;
    }
    final failure = error;
    if (failure != null && _isTerminalTargetStaleError(failure)) {
      _failTerminalReconnect(failure);
      return;
    }
    final attemptIndex =
        _autoReconnectAttempt < _autoReconnectBackoff.length
            ? _autoReconnectAttempt
            : _autoReconnectBackoff.length - 1;
    final delay = _autoReconnectBackoff[attemptIndex];
    if (_autoReconnectAttempt < _autoReconnectBackoff.length - 1) {
      _autoReconnectAttempt += 1;
    }
    _cancelAutoReconnectTimer();
    _setControlStatus('Reconnecting');
    _autoReconnectTimer = Timer(delay, () {
      if (!mounted || generation != _openGeneration || _autoReconnectBlocked) {
        return;
      }
      unawaited(_runAutoReconnect(generation));
    });
  }

  Future<void> _runAutoReconnect(int generation) async {
    if (!mounted || _closingForRemoval || generation != _openGeneration) {
      return;
    }
    final session = _session;
    if (session == null) {
      _startSession(clearTerminal: false, resetReconnect: false);
      return;
    }
    try {
      _setControlStatus('Reconnecting');
      await session.reconnect();
      if (!mounted || generation != _openGeneration) {
        return;
      }
      _resetAutoReconnect();
      _setControlStatus('Reconnected');
    } catch (error) {
      _terminal.write('\r\n\x1b[33m$error\x1b[0m\r\n');
      _handleReconnectFailure(generation, error);
    }
  }

  void _handleReconnectFailure(int generation, Object error) {
    if (!mounted || _closingForRemoval || generation != _openGeneration) {
      return;
    }
    if (_isTerminalTargetStaleError(error)) {
      _failTerminalReconnect(error);
      return;
    }
    _scheduleAutoReconnect(generation, error: error);
  }

  void _failTerminalReconnect(Object error) {
    _autoReconnectBlocked = true;
    _cancelAutoReconnectTimer();
    _terminal.write(
      '\r\n\x1b[33mTerminal target changed. Reopen Terminal from the project header.\x1b[0m\r\n',
    );
    _setControlStatus('Failed');
  }

  void _resetAutoReconnect() {
    _autoReconnectAttempt = 0;
    _autoReconnectBlocked = false;
    _cancelAutoReconnectTimer();
  }

  void _cancelAutoReconnectTimer() {
    _autoReconnectTimer?.cancel();
    _autoReconnectTimer = null;
  }

  bool _isReconnectableStatus(String status) {
    return status == 'Closed' ||
        status == 'Stream error' ||
        status == 'Reconnect failed' ||
        status == 'Failed' ||
        status == 'Reconnecting';
  }

  bool _isTerminalControlsDisabled(String status) {
    return status == 'Connecting' ||
        status == 'Closing' ||
        status == 'Closed' ||
        status == 'Stream error' ||
        status == 'Reconnect failed' ||
        status == 'Failed' ||
        status == 'Reconnecting';
  }

  bool _isTerminalTargetStaleError(Object error) {
    final text = error.toString().toLowerCase();
    return text.contains('stale namespace') ||
        text.contains('namespace epoch') ||
        text.contains('pane evidence') ||
        text.contains('unknown terminal target') ||
        (text.contains('terminal target') && text.contains('not found')) ||
        text.contains('stale terminal session');
  }

  void _setControlStatus(String status) {
    if (!mounted) {
      return;
    }
    final disableInput = _isTerminalControlsDisabled(status);
    if (disableInput) {
      _terminalViewKey.currentState?.closeKeyboard();
      _terminalKeyboardWasVisible = false;
    }
    setState(() {
      _controlStatus = status;
      if (disableInput) {
        _terminalInputActive = false;
      }
    });
  }

  Widget _terminalSurface({required bool connected}) {
    final terminalView = TerminalView(
      _terminal,
      key: _terminalViewKey,
      autofocus: false,
      readOnly: !connected || !_terminalInputActive,
      scrollController: _terminalScrollController,
      autoResize: true,
      textStyle: TerminalStyle(fontSize: _readableFontSize),
      padding: _terminalPadding,
    );

    return Listener(
      key: widget.terminalViewKey,
      behavior: HitTestBehavior.opaque,
      onPointerDown: (event) => _handleTerminalPointerDown(event, connected),
      onPointerMove: _handleTerminalPointerMove,
      onPointerUp: (event) => _handleTerminalPointerUp(event, connected),
      onPointerCancel: _handleTerminalPointerCancel,
      child: terminalView,
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<TerminalSession>(
      future: _sessionFuture,
      builder: (context, snapshot) {
        final disconnected = _isTerminalControlsDisabled(_controlStatus);
        final connected =
            widget.active &&
            snapshot.connectionState == ConnectionState.done &&
            snapshot.hasData &&
            _session != null &&
            !disconnected;
        final opened =
            snapshot.connectionState == ConnectionState.done &&
                snapshot.hasData ||
            _session != null ||
            disconnected;
        final canReconnect = opened && !_autoReconnectBlocked;
        final status = _controlStatus;
        return Column(
          children: [
            if (widget.showHeader)
              AgentTerminalHeader(
                title: widget.title,
                subtitle: widget.subtitle,
                trailing: status,
                onReconnect: disconnected && canReconnect ? _reconnect : null,
              ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return Stack(
                    fit: StackFit.expand,
                    children: [
                      _terminalSurface(connected: connected),
                      if (!widget.showHeader && disconnected)
                        Positioned(
                          top: 8,
                          left: 12,
                          right: 12,
                          child: _CompactTerminalConnectionStatus(
                            status: status,
                            onReconnect: canReconnect ? _reconnect : null,
                          ),
                        ),
                      Positioned(
                        left: 12,
                        bottom: 12,
                        child: ConstrainedBox(
                          constraints: BoxConstraints(
                            maxWidth: constraints.maxWidth - 24,
                          ),
                          child: TerminalControlToolbar(
                            enabled: connected,
                            onLatestOutput:
                                _terminalScrollController.jumpToLatestOutput,
                            onEscape: () => _sendKey(const [27], 'Esc'),
                            onTab: () => _sendKey(const [9], 'Tab'),
                            onEnter: () => _sendKey(const [13], 'Enter'),
                            onBackspace:
                                () => _sendKey(const [127], 'Backspace'),
                            onCtrlA: () => _sendKey(const [1], 'Ctrl-A'),
                            onCtrlC: () => _sendKey(const [3], 'Ctrl-C'),
                            onCtrlD: () => _sendKey(const [4], 'Ctrl-D'),
                            onCtrlE: () => _sendKey(const [5], 'Ctrl-E'),
                            onCtrlK: () => _sendKey(const [11], 'Ctrl-K'),
                            onCtrlU: () => _sendKey(const [21], 'Ctrl-U'),
                            onCtrlL: () => _sendKey(const [12], 'Ctrl-L'),
                            onCtrlR: () => _sendKey(const [18], 'Ctrl-R'),
                            onCtrlW: () => _sendKey(const [23], 'Ctrl-W'),
                            onCtrlZ: () => _sendKey(const [26], 'Ctrl-Z'),
                            onDelete:
                                () =>
                                    _sendKey(const [27, 91, 51, 126], 'Delete'),
                            onHome: () => _sendKey(const [27, 91, 72], 'Home'),
                            onEnd: () => _sendKey(const [27, 91, 70], 'End'),
                            onPageUp:
                                () =>
                                    _sendKey(const [27, 91, 53, 126], 'PageUp'),
                            onPageDown:
                                () => _sendKey(const [
                                  27,
                                  91,
                                  54,
                                  126,
                                ], 'PageDown'),
                            onArrowLeft:
                                () => _sendKey(const [27, 91, 68], 'Left'),
                            onArrowUp: () => _sendKey(const [27, 91, 65], 'Up'),
                            onArrowDown:
                                () => _sendKey(const [27, 91, 66], 'Down'),
                            onArrowRight:
                                () => _sendKey(const [27, 91, 67], 'Right'),
                          ),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }
}

class _CompactTerminalConnectionStatus extends StatelessWidget {
  const _CompactTerminalConnectionStatus({
    required this.status,
    required this.onReconnect,
  });

  final String status;
  final VoidCallback? onReconnect;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.topRight,
      child: Material(
        key: const ValueKey('terminal-compact-connection-status'),
        color: colorScheme.surfaceContainerHighest.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(6),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(status),
              if (onReconnect != null) ...[
                const SizedBox(width: 8),
                TextButton(
                  key: const ValueKey('terminal-compact-reconnect'),
                  onPressed: onReconnect,
                  style: TextButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 32),
                  ),
                  child: const Text('Reconnect'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class AgentTerminalHeader extends StatelessWidget {
  const AgentTerminalHeader({
    required this.title,
    required this.subtitle,
    required this.trailing,
    this.onReconnect,
    super.key,
  });

  final String title;
  final String subtitle;
  final String trailing;
  final VoidCallback? onReconnect;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Material(
      color: colorScheme.surfaceContainerHighest,
      child: ListTile(
        dense: true,
        leading: const Icon(Icons.terminal),
        title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
        trailing:
            onReconnect == null
                ? Text(
                  trailing,
                  key: const ValueKey('terminal-connection-status'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                )
                : TextButton(
                  key: const ValueKey('terminal-header-reconnect'),
                  onPressed: onReconnect,
                  child: Text(trailing),
                ),
      ),
    );
  }
}

class TerminalControlToolbar extends StatefulWidget {
  const TerminalControlToolbar({
    required this.enabled,
    required this.onLatestOutput,
    required this.onEscape,
    required this.onTab,
    this.onEnter = _noopTerminalShortcut,
    this.onBackspace = _noopTerminalShortcut,
    this.onCtrlA = _noopTerminalShortcut,
    required this.onCtrlC,
    required this.onCtrlD,
    this.onCtrlE = _noopTerminalShortcut,
    this.onCtrlK = _noopTerminalShortcut,
    required this.onCtrlU,
    required this.onCtrlL,
    this.onCtrlR = _noopTerminalShortcut,
    this.onCtrlW = _noopTerminalShortcut,
    this.onCtrlZ = _noopTerminalShortcut,
    required this.onDelete,
    required this.onHome,
    required this.onEnd,
    required this.onPageUp,
    required this.onPageDown,
    required this.onArrowLeft,
    required this.onArrowUp,
    required this.onArrowDown,
    required this.onArrowRight,
    super.key,
  });

  final bool enabled;
  final VoidCallback onLatestOutput;
  final VoidCallback onEscape;
  final VoidCallback onTab;
  final VoidCallback onEnter;
  final VoidCallback onBackspace;
  final VoidCallback onCtrlA;
  final VoidCallback onCtrlC;
  final VoidCallback onCtrlD;
  final VoidCallback onCtrlE;
  final VoidCallback onCtrlK;
  final VoidCallback onCtrlU;
  final VoidCallback onCtrlL;
  final VoidCallback onCtrlR;
  final VoidCallback onCtrlW;
  final VoidCallback onCtrlZ;
  final VoidCallback onDelete;
  final VoidCallback onHome;
  final VoidCallback onEnd;
  final VoidCallback onPageUp;
  final VoidCallback onPageDown;
  final VoidCallback onArrowLeft;
  final VoidCallback onArrowUp;
  final VoidCallback onArrowDown;
  final VoidCallback onArrowRight;

  @override
  State<TerminalControlToolbar> createState() => _TerminalControlToolbarState();
}

class _TerminalControlToolbarState extends State<TerminalControlToolbar> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final preferences =
        CcbTerminalShortcutPreferencesScope.maybeOf(context)?.preferences ??
        CcbTerminalShortcutPreferences.defaults;
    final shortcutWidgets =
        preferences.enabledInOrder.map(_configuredKey).toList();
    final firstRowLength =
        shortcutWidgets.length > 7 ? 7 : shortcutWidgets.length;
    return LayoutBuilder(
      builder: (context, constraints) {
        final width =
            _expanded && constraints.hasBoundedWidth
                ? constraints.maxWidth
                : 48.0;
        return AnimatedSize(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
          alignment: Alignment.bottomLeft,
          child: SizedBox(
            width: width,
            child: Material(
              key: const ValueKey('terminal-shortcut-surface'),
              color:
                  _expanded
                      ? colorScheme.surface.withValues(alpha: 0.92)
                      : Colors.transparent,
              elevation: _expanded ? 4 : 0,
              borderRadius: BorderRadius.circular(24),
              clipBehavior: Clip.antiAlias,
              child: Padding(
                padding:
                    _expanded
                        ? const EdgeInsets.symmetric(horizontal: 4, vertical: 3)
                        : EdgeInsets.zero,
                child:
                    _expanded
                        ? Column(
                          key: const ValueKey('terminal-shortcuts-panel'),
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _TerminalShortcutRow(
                              children: [
                                _shortcutToggle(),
                                _TerminalShortcutIconButton(
                                  key: const ValueKey(
                                    'terminal-key-latest-output',
                                  ),
                                  tooltip: 'Latest output',
                                  enabled: true,
                                  onPressed: widget.onLatestOutput,
                                  icon: Icons.vertical_align_bottom,
                                ),
                                ...shortcutWidgets.take(firstRowLength),
                              ],
                            ),
                            if (shortcutWidgets.length > firstRowLength)
                              _TerminalShortcutRow(
                                children:
                                    shortcutWidgets
                                        .skip(firstRowLength)
                                        .toList(),
                              ),
                          ],
                        )
                        : _shortcutToggle(),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _shortcutToggle() {
    return Opacity(
      opacity: _expanded ? 0.9 : 0.62,
      child: IconButton.filledTonal(
        key: const ValueKey('terminal-shortcuts-toggle'),
        tooltip:
            _expanded ? 'Hide terminal shortcuts' : 'Show terminal shortcuts',
        onPressed: () => setState(() => _expanded = !_expanded),
        icon: Icon(_expanded ? Icons.close : Icons.add),
      ),
    );
  }

  Widget _textKey(String id, String label, VoidCallback callback) {
    return _ToolbarTextButton(
      key: ValueKey('terminal-key-$id'),
      label: label,
      enabled: widget.enabled,
      onPressed: callback,
    );
  }

  Widget _iconKey(
    String id,
    String tooltip,
    IconData icon,
    VoidCallback callback,
  ) {
    return _TerminalShortcutIconButton(
      key: ValueKey('terminal-key-$id'),
      tooltip: tooltip,
      enabled: widget.enabled,
      onPressed: callback,
      icon: icon,
    );
  }

  Widget _configuredKey(CcbTerminalShortcut shortcut) {
    final icon = terminalShortcutIcon(shortcut);
    final callback = switch (shortcut) {
      CcbTerminalShortcut.escape => widget.onEscape,
      CcbTerminalShortcut.tab => widget.onTab,
      CcbTerminalShortcut.enter => widget.onEnter,
      CcbTerminalShortcut.backspace => widget.onBackspace,
      CcbTerminalShortcut.ctrlA => widget.onCtrlA,
      CcbTerminalShortcut.ctrlC => widget.onCtrlC,
      CcbTerminalShortcut.ctrlD => widget.onCtrlD,
      CcbTerminalShortcut.ctrlE => widget.onCtrlE,
      CcbTerminalShortcut.ctrlK => widget.onCtrlK,
      CcbTerminalShortcut.ctrlU => widget.onCtrlU,
      CcbTerminalShortcut.ctrlL => widget.onCtrlL,
      CcbTerminalShortcut.ctrlR => widget.onCtrlR,
      CcbTerminalShortcut.ctrlW => widget.onCtrlW,
      CcbTerminalShortcut.ctrlZ => widget.onCtrlZ,
      CcbTerminalShortcut.delete => widget.onDelete,
      CcbTerminalShortcut.home => widget.onHome,
      CcbTerminalShortcut.end => widget.onEnd,
      CcbTerminalShortcut.pageUp => widget.onPageUp,
      CcbTerminalShortcut.pageDown => widget.onPageDown,
      CcbTerminalShortcut.arrowLeft => widget.onArrowLeft,
      CcbTerminalShortcut.arrowUp => widget.onArrowUp,
      CcbTerminalShortcut.arrowDown => widget.onArrowDown,
      CcbTerminalShortcut.arrowRight => widget.onArrowRight,
    };
    if (icon != null) {
      return _iconKey(
        shortcut.wireName,
        terminalShortcutLabel(shortcut),
        icon,
        callback,
      );
    }
    final compactLabel = switch (shortcut) {
      CcbTerminalShortcut.ctrlC => 'C-c',
      CcbTerminalShortcut.ctrlD => 'C-d',
      CcbTerminalShortcut.ctrlA => 'C-a',
      CcbTerminalShortcut.ctrlE => 'C-e',
      CcbTerminalShortcut.ctrlK => 'C-k',
      CcbTerminalShortcut.ctrlU => 'C-u',
      CcbTerminalShortcut.ctrlL => 'C-l',
      CcbTerminalShortcut.ctrlR => 'C-r',
      CcbTerminalShortcut.ctrlW => 'C-w',
      CcbTerminalShortcut.ctrlZ => 'C-z',
      CcbTerminalShortcut.backspace => 'Bksp',
      CcbTerminalShortcut.enter => 'Enter',
      CcbTerminalShortcut.delete => 'Del',
      _ => terminalShortcutLabel(shortcut),
    };
    return _textKey(shortcut.wireName, compactLabel, callback);
  }
}

void _noopTerminalShortcut() {}

class _TerminalShortcutRow extends StatelessWidget {
  const _TerminalShortcutRow({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(mainAxisSize: MainAxisSize.min, children: children),
    );
  }
}

class _TerminalShortcutIconButton extends StatelessWidget {
  const _TerminalShortcutIconButton({
    required this.tooltip,
    required this.enabled,
    required this.onPressed,
    required this.icon,
    super.key,
  });

  final String tooltip;
  final bool enabled;
  final VoidCallback onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      visualDensity: VisualDensity.compact,
      constraints: const BoxConstraints.tightFor(width: 40, height: 40),
      onPressed: enabled ? onPressed : null,
      icon: Icon(icon),
    );
  }
}

class _ToolbarTextButton extends StatelessWidget {
  const _ToolbarTextButton({
    required this.label,
    required this.enabled,
    required this.onPressed,
    super.key,
  });

  final String label;
  final bool enabled;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: enabled ? onPressed : null,
      style: TextButton.styleFrom(
        minimumSize: const Size(44, 36),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      child: Text(label),
    );
  }
}

bool _sameGeometry(TerminalGeometry a, TerminalGeometry b) {
  return a.columns == b.columns &&
      a.rows == b.rows &&
      a.pixelWidth == b.pixelWidth &&
      a.pixelHeight == b.pixelHeight;
}

String _terminalTargetIdentity(CcbTerminalTarget target) {
  return [
    target.projectId,
    target.namespaceEpoch,
    target.kind.wireName,
    target.agent,
    target.window,
    target.paneId,
    target.tmuxSocketPath,
    target.tmuxSessionName,
  ].join('|');
}
