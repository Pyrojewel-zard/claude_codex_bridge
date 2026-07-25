import 'dart:async';
import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:xterm/xterm.dart';

import '../../models/ccb_project_view.dart';
import '../../models/ccb_terminal_target.dart';
import '../../tmux/tmux_command_builder.dart';
import '../../transport/gateway_terminal_transport.dart';
import '../../transport/terminal_transport.dart';
import 'terminal_history_scroll_controller.dart';

class AgentTerminalPane extends StatefulWidget {
  const AgentTerminalPane({
    required this.view,
    required this.target,
    required this.terminalTransport,
    this.gatewayTerminal = false,
    this.showHeader = true,
    this.active = true,
    super.key,
  });

  final CcbProjectView view;
  final CcbTerminalTarget target;
  final TerminalTransport? terminalTransport;
  final bool gatewayTerminal;
  final bool showHeader;
  final bool active;

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
      return _FakeTerminalPane(model: model, showHeader: widget.showHeader);
    }
    return _LiveTerminalPane(
      model: model,
      transport: transport,
      gatewayTerminal: widget.gatewayTerminal,
      showHeader: widget.showHeader,
      active: widget.active,
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
  const _FakeTerminalPane({required this.model, required this.showHeader});

  final AgentTerminalPaneModel model;
  final bool showHeader;

  @override
  State<_FakeTerminalPane> createState() => _FakeTerminalPaneState();
}

class _FakeTerminalPaneState extends State<_FakeTerminalPane> {
  late final Terminal _terminal;

  @override
  void initState() {
    super.initState();
    _terminal = Terminal(maxLines: 2000);
    _writeTranscript();
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
          ),
        ),
      ],
    );
  }
}

class _LiveTerminalPane extends StatefulWidget {
  const _LiveTerminalPane({
    required this.model,
    required this.transport,
    required this.gatewayTerminal,
    required this.showHeader,
    required this.active,
  });

  final AgentTerminalPaneModel model;
  final TerminalTransport transport;
  final bool gatewayTerminal;
  final bool showHeader;
  final bool active;

  @override
  State<_LiveTerminalPane> createState() => _LiveTerminalPaneState();
}

class _LiveTerminalPaneState extends State<_LiveTerminalPane>
    with WidgetsBindingObserver {
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
  TerminalSession? _session;
  StreamSubscription<String>? _outputSubscription;
  Timer? _autoReconnectTimer;
  var _openGeneration = 0;
  var _autoReconnectAttempt = 0;
  var _autoReconnectBlocked = false;
  TerminalGeometry _lastGeometry = const TerminalGeometry(
    columns: 100,
    rows: 30,
    pixelWidth: 960,
    pixelHeight: 640,
  );
  String _controlStatus = 'Connecting';
  bool _terminalInputActive = false;
  bool _terminalKeyboardWasVisible = false;
  int? _terminalTapPointer;
  Offset? _terminalTapOrigin;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _terminalScrollController = TerminalHistoryScrollController(
      debugLabel: 'agent-terminal-history',
    )..addListener(_handleTerminalScrollChanged);
    _terminal = Terminal(
      maxLines: 4000,
      onOutput: (data) {
        if (_isTerminalAutoReportReply(data)) {
          return;
        }
        _writeTerminalBytes(utf8.encode(data));
      },
      onResize: (width, height, pixelWidth, pixelHeight) {
        final geometry = TerminalGeometry(
          columns: width,
          rows: height,
          pixelWidth: pixelWidth,
          pixelHeight: pixelHeight,
        );
        if (_sameGeometry(_lastGeometry, geometry)) {
          return;
        }
        _lastGeometry = geometry;
        _session?.resize(geometry);
      },
    );
    _startSession(clearTerminal: false);
  }

  @override
  void didUpdateWidget(covariant _LiveTerminalPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.active && !widget.active) {
      _deactivateTerminalInput();
    }
    if (oldWidget.transport != widget.transport ||
        oldWidget.gatewayTerminal != widget.gatewayTerminal ||
        !_sameTerminalTargetIdentity(
          oldWidget.model.target,
          widget.model.target,
        )) {
      _startSession(clearTerminal: true);
    }
  }

  void _startSession({
    required bool clearTerminal,
    bool resetReconnect = true,
  }) {
    _openGeneration += 1;
    final generation = _openGeneration;
    if (resetReconnect) {
      _resetAutoReconnect();
    } else {
      _cancelAutoReconnectTimer();
    }
    _setControlStatus('Connecting');
    final rawFuture = _replaceSession(generation, clearTerminal: clearTerminal);
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
    if (!mounted || generation != _openGeneration) {
      throw const TerminalTransportException('stale terminal session');
    }
    if (clearTerminal) {
      _terminal.write('\x1b[2J\x1b[H');
    }
    return _openSession(generation);
  }

  Future<TerminalSession> _openSession(int generation) async {
    final request =
        widget.gatewayTerminal || widget.transport is GatewayTerminalTransport
            ? TerminalOpenRequest.gateway(
              target: widget.model.target,
              geometry: _lastGeometry,
            )
            : TerminalOpenRequest(
              target: widget.model.target,
              geometry: _lastGeometry,
            );
    late final TerminalSession session;
    try {
      session = await widget.transport.open(request);
    } catch (error) {
      if (mounted && generation == _openGeneration) {
        _terminal.write('\r\n\x1b[33m$error\x1b[0m\r\n');
        _handleReconnectFailure(generation, error);
      }
      rethrow;
    }
    if (!mounted || generation != _openGeneration) {
      await session.close();
      throw const TerminalTransportException('stale terminal session');
    }
    _session = session;
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
    _openGeneration += 1;
    _cancelAutoReconnectTimer();
    unawaited(_closeCurrentSession());
    _terminalScrollController.removeListener(_handleTerminalScrollChanged);
    _terminalScrollController.dispose();
    super.dispose();
  }

  Future<void> _closeCurrentSession() async {
    final subscription = _outputSubscription;
    _outputSubscription = null;
    final session = _session;
    _session = null;
    final cancellation = subscription?.cancel();
    await session?.close().catchError((_) {
      // Best-effort route teardown; the gateway may already have closed.
    });
    if (cancellation != null) {
      unawaited(cancellation.catchError((_) {}));
    }
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
    if (!connected || !_terminalScrollController.isAtLatestOutput) {
      _resetTerminalTap();
      return;
    }
    _terminalTapPointer = event.pointer;
    _terminalTapOrigin = event.position;
  }

  void _handleTerminalPointerMove(PointerMoveEvent event) {
    if (_terminalTapPointer != event.pointer || _terminalTapOrigin == null) {
      return;
    }
    if ((event.position - _terminalTapOrigin!).distance > kTouchSlop) {
      _resetTerminalTap();
    }
  }

  void _handleTerminalPointerUp(PointerUpEvent event, bool connected) {
    if (_terminalTapPointer == event.pointer && _terminalTapOrigin != null) {
      _activateTerminalInput(connected);
    }
    _resetTerminalTap();
  }

  void _handleTerminalPointerCancel(PointerCancelEvent event) {
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
    if (data == '\x1b[?1;2c' ||
        data == '\x1b[0n' ||
        data == '\x1bP!|00000000\x1b\\') {
      return true;
    }
    return _secondaryDeviceAttributesPattern.hasMatch(data) ||
        _cursorPositionReportPattern.hasMatch(data) ||
        _windowSizeReportPattern.hasMatch(data);
  }

  static final _secondaryDeviceAttributesPattern = RegExp(
    r'^\x1B\[>\d+;\d+;\d+c$',
  );
  static final _cursorPositionReportPattern = RegExp(r'^\x1B\[\d+;\d+R$');
  static final _windowSizeReportPattern = RegExp(r'^\x1B\[8;\d+;\d+t$');

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
    if (!mounted || generation != _openGeneration || _autoReconnectBlocked) {
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
    if (!mounted || generation != _openGeneration) {
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
    if (!mounted || generation != _openGeneration) {
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
                title: widget.model.title,
                subtitle: widget.model.attachCommand,
                trailing: status,
                onReconnect: disconnected && canReconnect ? _reconnect : null,
              ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return Stack(
                    fit: StackFit.expand,
                    children: [
                      Listener(
                        key: const ValueKey('ccb-live-terminal-view'),
                        behavior: HitTestBehavior.opaque,
                        onPointerDown:
                            (event) =>
                                _handleTerminalPointerDown(event, connected),
                        onPointerMove: _handleTerminalPointerMove,
                        onPointerUp:
                            (event) =>
                                _handleTerminalPointerUp(event, connected),
                        onPointerCancel: _handleTerminalPointerCancel,
                        child: TerminalView(
                          _terminal,
                          key: _terminalViewKey,
                          autofocus: false,
                          readOnly: !connected || !_terminalInputActive,
                          scrollController: _terminalScrollController,
                        ),
                      ),
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
                            onCtrlC: () => _sendKey(const [3], 'Ctrl-C'),
                            onArrowUp: () => _sendKey(const [27, 91, 65], 'Up'),
                            onArrowDown:
                                () => _sendKey(const [27, 91, 66], 'Down'),
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
    required this.onCtrlC,
    required this.onArrowUp,
    required this.onArrowDown,
    super.key,
  });

  final bool enabled;
  final VoidCallback onLatestOutput;
  final VoidCallback onEscape;
  final VoidCallback onTab;
  final VoidCallback onCtrlC;
  final VoidCallback onArrowUp;
  final VoidCallback onArrowDown;

  @override
  State<TerminalControlToolbar> createState() => _TerminalControlToolbarState();
}

class _TerminalControlToolbarState extends State<TerminalControlToolbar> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
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
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Padding(
                  padding:
                      _expanded
                          ? const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 3,
                          )
                          : EdgeInsets.zero,
                  child: Row(
                    key:
                        _expanded
                            ? const ValueKey('terminal-shortcuts-panel')
                            : null,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Opacity(
                        opacity: _expanded ? 0.9 : 0.62,
                        child: IconButton.filledTonal(
                          key: const ValueKey('terminal-shortcuts-toggle'),
                          tooltip:
                              _expanded
                                  ? 'Hide terminal shortcuts'
                                  : 'Show terminal shortcuts',
                          onPressed:
                              () => setState(() => _expanded = !_expanded),
                          icon: Icon(_expanded ? Icons.close : Icons.add),
                        ),
                      ),
                      if (_expanded) ...[
                        const SizedBox(width: 2),
                        _TerminalShortcutIconButton(
                          key: const ValueKey('terminal-key-latest-output'),
                          tooltip: 'Latest output',
                          enabled: true,
                          onPressed: widget.onLatestOutput,
                          icon: Icons.vertical_align_bottom,
                        ),
                        _ToolbarTextButton(
                          key: const ValueKey('terminal-key-escape'),
                          label: 'Esc',
                          enabled: widget.enabled,
                          onPressed: widget.onEscape,
                        ),
                        _ToolbarTextButton(
                          key: const ValueKey('terminal-key-tab'),
                          label: 'Tab',
                          enabled: widget.enabled,
                          onPressed: widget.onTab,
                        ),
                        _ToolbarTextButton(
                          key: const ValueKey('terminal-key-ctrl-c'),
                          label: 'C-c',
                          enabled: widget.enabled,
                          onPressed: widget.onCtrlC,
                        ),
                        _TerminalShortcutIconButton(
                          key: const ValueKey('terminal-key-arrow-up'),
                          tooltip: 'Up',
                          enabled: widget.enabled,
                          onPressed: widget.onArrowUp,
                          icon: Icons.keyboard_arrow_up,
                        ),
                        _TerminalShortcutIconButton(
                          key: const ValueKey('terminal-key-arrow-down'),
                          tooltip: 'Down',
                          enabled: widget.enabled,
                          onPressed: widget.onArrowDown,
                          icon: Icons.keyboard_arrow_down,
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
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

bool _sameTerminalTargetIdentity(CcbTerminalTarget a, CcbTerminalTarget b) {
  return a.projectId == b.projectId &&
      a.namespaceEpoch == b.namespaceEpoch &&
      a.kind == b.kind &&
      a.agent == b.agent &&
      a.window == b.window &&
      a.paneId == b.paneId &&
      a.tmuxSocketPath == b.tmuxSocketPath &&
      a.tmuxSessionName == b.tmuxSessionName;
}
