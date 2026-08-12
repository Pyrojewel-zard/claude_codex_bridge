import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'gateway pane snapshot replacement does not accumulate screen copies',
    () {
      final terminal = Terminal(maxLines: 100);
      terminal.resize(24, 3);

      terminal.write(
        '\x1b[?25l\x1b[3J\x1b[H\x1b[2J'
        'real history\r\nolder output\r\npane only\r\nprompt\$ ',
      );
      terminal.write('\x1b[?25l\x1b[H\x1b[2Jpane changed\r\nprompt\$ ');

      final text = terminal.buffer.getText();
      expect('real history'.allMatches(text), hasLength(1));
      expect('pane changed'.allMatches(text), hasLength(1));
      expect('pane only'.allMatches(text), isEmpty);
    },
  );

  testWidgets('terminal shortcuts stay collapsed under a floating plus', (
    tester,
  ) async {
    final calls = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 390,
            child: TerminalControlToolbar(
              enabled: true,
              onLatestOutput: () => calls.add('latest'),
              onEscape: () => calls.add('esc'),
              onTab: () => calls.add('tab'),
              onCtrlC: () => calls.add('ctrl-c'),
              onCtrlD: () => calls.add('ctrl-d'),
              onCtrlU: () => calls.add('ctrl-u'),
              onCtrlL: () => calls.add('ctrl-l'),
              onDelete: () => calls.add('delete'),
              onHome: () => calls.add('home'),
              onEnd: () => calls.add('end'),
              onPageUp: () => calls.add('page-up'),
              onPageDown: () => calls.add('page-down'),
              onArrowLeft: () => calls.add('left'),
              onArrowUp: () => calls.add('up'),
              onArrowDown: () => calls.add('down'),
              onArrowRight: () => calls.add('right'),
            ),
          ),
        ),
      ),
    );

    expect(find.byKey(const ValueKey('terminal-shortcut-surface')), findsOne);
    expect(find.byIcon(Icons.add), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-escape')), findsNothing);

    await _expandTerminalShortcuts(tester);

    expect(find.byKey(const ValueKey('terminal-key-escape')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-keyboard')), findsNothing);
    expect(find.byKey(const ValueKey('terminal-key-tab')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-ctrl-c')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-ctrl-d')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-ctrl-u')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-ctrl-l')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-delete')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-home')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-end')), findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-page-up')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('terminal-key-page-down')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('terminal-key-latest-output')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('terminal-key-arrow-up')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('terminal-key-arrow-down')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('terminal-key-arrow-left')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('terminal-key-arrow-right')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('terminal-paste-button')), findsNothing);
    expect(find.byKey(const ValueKey('terminal-resize-button')), findsNothing);
    expect(
      find.byKey(const ValueKey('terminal-reconnect-button')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('terminal-ctrl-menu')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('terminal-key-escape')));
    await tester.tap(find.byKey(const ValueKey('terminal-key-tab')));
    await tester.tap(find.byKey(const ValueKey('terminal-key-ctrl-c')));
    await tester.tap(find.byKey(const ValueKey('terminal-key-latest-output')));
    await tester.pump();

    expect(calls, ['esc', 'tab', 'ctrl-c', 'latest']);

    await tester.tap(find.byKey(const ValueKey('terminal-shortcuts-toggle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('terminal-key-escape')), findsNothing);
  });

  testWidgets('terminal toolbar disables controls while disconnected', (
    tester,
  ) async {
    var called = false;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TerminalControlToolbar(
            enabled: false,
            onLatestOutput: () => called = true,
            onEscape: () => called = true,
            onTab: () => called = true,
            onCtrlC: () => called = true,
            onCtrlD: () => called = true,
            onCtrlU: () => called = true,
            onCtrlL: () => called = true,
            onDelete: () => called = true,
            onHome: () => called = true,
            onEnd: () => called = true,
            onPageUp: () => called = true,
            onPageDown: () => called = true,
            onArrowLeft: () => called = true,
            onArrowUp: () => called = true,
            onArrowDown: () => called = true,
            onArrowRight: () => called = true,
          ),
        ),
      ),
    );
    await _expandTerminalShortcuts(tester);

    final escape = tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-escape')),
        matching: find.byType(TextButton),
      ),
    );
    final up = tester.widget<IconButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-arrow-up')),
        matching: find.byType(IconButton),
      ),
    );

    expect(escape.onPressed, isNull);
    expect(up.onPressed, isNull);
    final latest = tester.widget<IconButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-latest-output')),
        matching: find.byType(IconButton),
      ),
    );
    expect(latest.onPressed, isNotNull);
    expect(called, isFalse);
  });

  testWidgets('terminal keyboard opens by tapping latest output only', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final terminal = find.byKey(const ValueKey('ccb-live-terminal-view'));
    expect(binding.testTextInput.isVisible, isFalse);

    transport.sessions.single.addOutput(
      List.generate(240, (index) => 'history line $index\r\n').join(),
    );
    await tester.pumpAndSettle();

    await tester.drag(terminal, const Offset(0, 260));
    await tester.pumpAndSettle();
    await tester.tap(terminal);
    await tester.pump(const Duration(milliseconds: 350));
    expect(binding.testTextInput.isVisible, isFalse);

    final scrollable = find.descendant(
      of: terminal,
      matching: find.byType(Scrollable),
    );
    final position = tester.state<ScrollableState>(scrollable).position;
    await tester.drag(terminal, const Offset(0, -260));
    await tester.pumpAndSettle();
    expect(position.pixels, closeTo(position.maxScrollExtent, 0.1));

    await tester.tap(terminal);
    await tester.pump(const Duration(milliseconds: 350));
    expect(binding.testTextInput.isVisible, isTrue);
  });

  testWidgets('live terminal pane does not echo terminal report replies', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final session = transport.sessions.single;
    session.addOutput('\x1b[>c');
    session.addOutput('\x1b[c');
    session.addOutput('\x1b[5n');
    session.addOutput('\x1b[6n');
    await tester.pump();

    expect(session.written, isEmpty);
  });

  testWidgets('live terminal pane still sends explicit terminal controls', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final session = transport.sessions.single;
    await _expandTerminalShortcuts(tester);
    for (final id in [
      'tab',
      'escape',
      'enter',
      'backspace',
      'ctrl-a',
      'ctrl-d',
      'ctrl-e',
      'ctrl-k',
      'ctrl-u',
      'ctrl-l',
      'ctrl-r',
      'ctrl-w',
      'ctrl-z',
      'delete',
      'home',
      'page-up',
      'arrow-left',
      'arrow-right',
      'page-down',
      'end',
    ]) {
      final shortcut = find.byKey(ValueKey('terminal-key-$id'));
      await tester.ensureVisible(shortcut);
      await tester.tap(shortcut);
    }
    await tester.pump();

    expect(session.written, [
      [9],
      [27],
      [13],
      [127],
      [1],
      [4],
      [5],
      [11],
      [21],
      [12],
      [18],
      [23],
      [26],
      [27, 91, 51, 126],
      [27, 91, 72],
      [27, 91, 53, 126],
      [27, 91, 68],
      [27, 91, 67],
      [27, 91, 54, 126],
      [27, 91, 70],
    ]);
  });

  testWidgets('live terminal pane sends alphabetic and Chinese text', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final session = transport.sessions.single;
    await tester.tap(find.byKey(const ValueKey('ccb-live-terminal-view')));
    await tester.pump(const Duration(milliseconds: 350));
    binding.testTextInput.enterText('Alpha中文123');
    await binding.idle();

    expect(session.written.map(utf8.decode), contains('Alpha中文123'));
  });

  testWidgets('history stays read-only until returning to latest output', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final terminal = find.byKey(const ValueKey('ccb-live-terminal-view'));
    transport.sessions.single.addOutput(
      List.generate(240, (index) => 'history line $index\r\n').join(),
    );
    await tester.pumpAndSettle();

    final scrollable = find.descendant(
      of: terminal,
      matching: find.byType(Scrollable),
    );
    final position = tester.state<ScrollableState>(scrollable).position;
    expect(position.pixels, closeTo(position.maxScrollExtent, 0.1));

    await tester.drag(terminal, const Offset(0, 260));
    await tester.pumpAndSettle();
    final historyOffset = position.pixels;
    expect(historyOffset, lessThan(position.maxScrollExtent - 40));

    await tester.tap(terminal);
    await tester.pump(const Duration(milliseconds: 350));

    expect(position.pixels, closeTo(historyOffset, 0.1));
    expect(binding.testTextInput.isVisible, isFalse);

    await _expandTerminalShortcuts(tester);
    await tester.tap(find.byKey(const ValueKey('terminal-key-latest-output')));
    await tester.pump(const Duration(milliseconds: 350));

    expect(position.pixels, closeTo(position.maxScrollExtent, 0.1));

    await tester.tap(terminal);
    await tester.pump(const Duration(milliseconds: 350));
    expect(binding.testTextInput.isVisible, isTrue);

    binding.testTextInput.enterText('stay-here');
    await binding.idle();
    expect(
      transport.sessions.single.written.map(utf8.decode),
      contains('stay-here'),
    );
  });

  testWidgets('live terminal pane reopens when target epoch changes', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    var view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, setState) {
              return Column(
                children: [
                  TextButton(
                    key: const ValueKey('advance-epoch'),
                    onPressed: () {
                      setState(() {
                        view = _view(namespaceEpoch: 5);
                      });
                    },
                    child: const Text('advance'),
                  ),
                  Expanded(
                    child: AgentTerminalPane(
                      view: view,
                      target: view.terminalTargetForAgent('mobile'),
                      terminalTransport: transport,
                      gatewayTerminal: true,
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(transport.requests, hasLength(1));
    expect(transport.requests.single.target.namespaceEpoch, 4);
    expect(
      find.byKey(const ValueKey('ccb-live-terminal-view')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('advance-epoch')));
    await tester.pumpAndSettle();

    expect(transport.requests, hasLength(2));
    expect(transport.requests.last.target.namespaceEpoch, 5);
    expect(
      find.byKey(const ValueKey('ccb-live-terminal-view')),
      findsOneWidget,
    );
  });

  testWidgets('live terminal pane auto reconnects after output stream error', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _expandTerminalShortcuts(tester);

    final session = transport.sessions.single;
    session.addOutput('before');
    await tester.pump();
    expect(session.hasOutputListener, isTrue);

    session.addOutputError(
      const TerminalTransportException('terminal stream disconnected'),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('Reconnecting'), findsWidgets);
    final ctrlC = tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-ctrl-c')),
        matching: find.byType(TextButton),
      ),
    );
    final reconnect = tester.widget<TextButton>(
      find.byKey(const ValueKey('terminal-header-reconnect')),
    );
    expect(ctrlC.onPressed, isNull);
    expect(reconnect.onPressed, isNotNull);

    await tester.pump(const Duration(seconds: 1));
    await tester.pump();

    expect(session.reconnectCount, 1);
    expect(find.text('Reconnected'), findsWidgets);

    session.addOutput('after');
    await tester.pump();
    expect(session.hasOutputListener, isTrue);
  });

  testWidgets(
    'live terminal pane keeps retrying transient reconnect failures',
    (tester) async {
      final transport = RecordingTerminalTransport();
      final view = _view(namespaceEpoch: 4);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AgentTerminalPane(
              view: view,
              target: view.terminalTargetForAgent('mobile'),
              terminalTransport: transport,
              gatewayTerminal: true,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final session = transport.sessions.single;
      transport.openErrors.addAll([
        const TerminalTransportException('gateway unreachable'),
        const TerminalTransportException('gateway unreachable'),
      ]);
      await session.endOutput();
      await tester.pump();

      expect(find.text('Reconnecting'), findsWidgets);
      await tester.pump(const Duration(seconds: 1));
      await tester.pump();

      expect(transport.requests, hasLength(2));
      expect(find.text('Reconnecting'), findsWidgets);
      expect(find.text('Failed'), findsNothing);

      await tester.pump(const Duration(seconds: 2));
      await tester.pump();

      expect(transport.requests, hasLength(3));
      expect(find.text('Reconnecting'), findsWidgets);
      expect(find.text('Failed'), findsNothing);

      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      expect(transport.requests, hasLength(4));
      expect(transport.sessions, hasLength(2));
      expect(find.text('Connected'), findsWidgets);
    },
  );

  testWidgets('live terminal pane can still reconnect manually while pending', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _expandTerminalShortcuts(tester);

    final session = transport.sessions.single;
    session.addOutputError(
      const TerminalTransportException('terminal stream disconnected'),
    );
    await tester.pump();
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('terminal-header-reconnect')));
    await tester.pump();

    expect(session.reconnectCount, 1);
    expect(find.text('Reconnected'), findsWidgets);

    await tester.pump(const Duration(seconds: 2));
    expect(session.reconnectCount, 1);
  });

  testWidgets('live terminal pane auto reopens after output stream closes', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _expandTerminalShortcuts(tester);

    await transport.sessions.single.endOutput();
    await tester.pump();

    expect(find.text('Reconnecting'), findsWidgets);
    final ctrlC = tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-ctrl-c')),
        matching: find.byType(TextButton),
      ),
    );
    final reconnect = tester.widget<TextButton>(
      find.byKey(const ValueKey('terminal-header-reconnect')),
    );
    expect(ctrlC.onPressed, isNull);
    expect(reconnect.onPressed, isNotNull);

    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();

    expect(transport.sessions, hasLength(2));
    expect(transport.requests, hasLength(2));
    transport.sessions.last.addOutput('after reopen');
    await tester.pump();
    expect(transport.sessions.last.hasOutputListener, isTrue);
  });

  testWidgets('live terminal pane stops reconnecting on stale target errors', (
    tester,
  ) async {
    final transport = RecordingTerminalTransport();
    final view = _view(namespaceEpoch: 4);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AgentTerminalPane(
            view: view,
            target: view.terminalTargetForAgent('mobile'),
            terminalTransport: transport,
            gatewayTerminal: true,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _expandTerminalShortcuts(tester);

    final session = transport.sessions.single;
    session.addOutputError(
      const TerminalTransportException('stale namespace epoch'),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('Failed'), findsWidgets);
    final ctrlC = tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-key-ctrl-c')),
        matching: find.byType(TextButton),
      ),
    );
    expect(ctrlC.onPressed, isNull);
    expect(
      find.byKey(const ValueKey('terminal-header-reconnect')),
      findsNothing,
    );

    await tester.pump(const Duration(seconds: 9));
    expect(session.reconnectCount, 0);
    expect(transport.sessions, hasLength(1));
  });
}

Future<void> _expandTerminalShortcuts(WidgetTester tester) async {
  if (find
      .byKey(const ValueKey('terminal-shortcuts-panel'))
      .evaluate()
      .isNotEmpty) {
    return;
  }
  await tester.tap(find.byKey(const ValueKey('terminal-shortcuts-toggle')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 220));
}

CcbProjectView _view({required int namespaceEpoch}) {
  return CcbProjectView(
    project: const CcbProject(
      id: 'proj-demo',
      displayName: 'demo',
      root: '/srv/ccb/demo',
    ),
    namespaceEpoch: namespaceEpoch,
    tmuxSocketPath: '/tmp/ccb-demo/tmux.sock',
    tmuxSessionName: 'ccb-demo',
    activeWindow: 'main',
    activePaneId: '%2',
    windows: const [
      CcbWindow(
        name: 'main',
        label: 'main',
        kind: 'agents',
        order: 0,
        active: true,
        agents: ['mobile'],
      ),
    ],
    agents: const [
      CcbAgent(
        name: 'mobile',
        provider: 'codex',
        window: 'main',
        order: 0,
        active: true,
        queueDepth: 0,
      ),
    ],
    contentItems: const [],
    notifications: const [],
    terminalHistories: const {},
  );
}
