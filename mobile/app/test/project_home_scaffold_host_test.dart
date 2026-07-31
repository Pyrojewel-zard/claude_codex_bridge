import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/project_home_scaffold_host.dart';
import 'package:ccb_mobile/features/project_home/wide_sidebar_state.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  group('project home scaffold host', () {
    testWidgets('mobile host renders keys and forwards callbacks', (
      tester,
    ) async {
      final view = _view();
      final selectedAgent = view.agentByName('mobile');
      var backCalls = 0;
      var detailsCalls = 0;
      var collapsed = false;
      var expanded = false;
      var selectedWindowName = '';
      var selectedAgentName = '';
      var scrollDirection = ScrollDirection.idle;

      await _pump(
        tester,
        ProjectHomeMobileChatScaffoldHost(
          view: view,
          selectedAgent: selectedAgent,
          repository: RecordingGatewayRepository(),
          terminalTransport: RecordingTerminalTransport(),
          usePaneInputForMessages: true,
          mobileAgentsCollapsed: false,
          onBack: () {
            backCalls += 1;
          },
          onOpenConnectionDetails: () {
            detailsCalls += 1;
          },
          onCollapseAgents: () {
            collapsed = true;
          },
          onExpandAgents: () {
            expanded = true;
          },
          onWindowSelected: (windowName) {
            selectedWindowName = windowName;
          },
          onAgentSelected: (agentName) {
            selectedAgentName = agentName;
          },
          onRefreshView: () async => null,
          onTimelineScrollDirectionChanged: (direction) {
            scrollDirection = direction;
          },
        ),
      );

      expect(find.byKey(const ValueKey('project-chat-screen')), findsOneWidget);
      expect(find.byKey(const ValueKey('project-chat-header')), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('project-chat-header')),
          matching: find.byKey(
            const ValueKey('agent-conversation-refresh-action'),
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('mobile-agent-switcher-expanded')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('window-tab-main')),
          matching: find.byIcon(Icons.space_dashboard_rounded),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('window-tab-review')),
          matching: find.byIcon(Icons.space_dashboard_outlined),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('agent-mobile')),
          matching: find.byIcon(Icons.auto_awesome_rounded),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('agent-lead')),
          matching: find.byIcon(Icons.auto_awesome_outlined),
        ),
        findsOneWidget,
      );

      tester
          .widget<IconButton>(find.byKey(const ValueKey('project-back-button')))
          .onPressed!();
      tester
          .widget<IconButton>(
            find.byKey(const ValueKey('connection-details-action')),
          )
          .onPressed!();
      await tester.tap(
        find.byKey(const ValueKey('mobile-agent-switcher-collapse-action')),
      );
      await tester.tap(find.byKey(const ValueKey('window-tab-review')));
      await tester.tap(find.byKey(const ValueKey('agent-lead')));
      await tester.drag(
        find.byKey(const ValueKey('agent-chat-timeline-mobile')),
        const Offset(0, -72),
      );

      expect(backCalls, 1);
      expect(detailsCalls, 1);
      expect(collapsed, isTrue);
      expect(expanded, isFalse);
      expect(selectedWindowName, 'review');
      expect(selectedAgentName, 'lead');
      expect(scrollDirection, ScrollDirection.reverse);
    });

    testWidgets('mobile host disables terminal without selected agent', (
      tester,
    ) async {
      await _pump(
        tester,
        ProjectHomeMobileChatScaffoldHost(
          view: _view(),
          selectedAgent: null,
          repository: RecordingGatewayRepository(),
          terminalTransport: RecordingTerminalTransport(),
          usePaneInputForMessages: true,
          mobileAgentsCollapsed: true,
          onBack: () {},
          onOpenConnectionDetails: () {},
          onCollapseAgents: () {},
          onExpandAgents: () {},
          onWindowSelected: (_) {},
          onAgentSelected: (_) {},
          onRefreshView: () async => null,
          onTimelineScrollDirectionChanged: (_) {},
        ),
      );

      expect(
        find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
          matching: find.byIcon(Icons.auto_awesome_rounded),
        ),
        findsOneWidget,
      );
      expect(
        tester
            .widget<IconButton>(
              find.byKey(const ValueKey('open-agent-terminal-button')),
            )
            .onPressed,
        isNull,
      );
    });

    testWidgets('mobile host toggles terminal content from the header', (
      tester,
    ) async {
      final view = _view();
      final terminalTransport = RecordingTerminalTransport();

      await _pump(
        tester,
        ProjectHomeMobileChatScaffoldHost(
          view: view,
          selectedAgent: view.agentByName('mobile'),
          repository: RecordingGatewayRepository(),
          terminalTransport: terminalTransport,
          usePaneInputForMessages: true,
          mobileAgentsCollapsed: false,
          onBack: () {},
          onOpenConnectionDetails: () {},
          onCollapseAgents: () {},
          onExpandAgents: () {},
          onWindowSelected: (_) {},
          onAgentSelected: (_) {},
          onRefreshView: () async => null,
          onTimelineScrollDirectionChanged: (_) {},
        ),
      );

      expect(
        find.byKey(const ValueKey('agent-workspace-mode-switch')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('ccb-live-terminal-view')),
        findsNothing,
      );
      await tester.enterText(
        find.byKey(const ValueKey('agent-message-composer')),
        'preserved draft',
      );

      await tester.tap(
        find.byKey(const ValueKey('open-agent-terminal-button')),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('ccb-live-terminal-view')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('return-to-agent-chat-button')),
        findsOneWidget,
      );
      expect(terminalTransport.requests, hasLength(1));
      expect(terminalTransport.requests.single.target.agent, 'mobile');

      await tester.tap(
        find.byKey(const ValueKey('return-to-agent-chat-button')),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('ccb-live-terminal-view')),
        findsNothing,
      );
      expect(find.text('preserved draft'), findsOneWidget);
    });

    testWidgets('terminal mode follows the shared selected agent in place', (
      tester,
    ) async {
      final view = _view();
      final repository = RecordingGatewayRepository();
      final terminalTransport = RecordingTerminalTransport();
      var selectedAgent = view.agentByName('mobile');
      var windowSelectionCalls = 0;

      await _pump(
        tester,
        StatefulBuilder(
          builder: (context, setState) {
            return ProjectHomeMobileChatScaffoldHost(
              view: view,
              selectedAgent: selectedAgent,
              repository: repository,
              terminalTransport: terminalTransport,
              usePaneInputForMessages: true,
              mobileAgentsCollapsed: false,
              onBack: () {},
              onOpenConnectionDetails: () {},
              onCollapseAgents: () {},
              onExpandAgents: () {},
              onWindowSelected: (_) {
                windowSelectionCalls += 1;
              },
              onAgentSelected: (agentName) {
                setState(() {
                  selectedAgent = view.agentByName(agentName);
                });
              },
              onRefreshView: () async => null,
              onTimelineScrollDirectionChanged: (_) {},
            );
          },
        ),
      );

      await tester.tap(
        find.byKey(const ValueKey('open-agent-terminal-button')),
      );
      await tester.pumpAndSettle();
      expect(terminalTransport.requests, hasLength(1));
      expect(terminalTransport.requests.single.target.agent, 'mobile');

      await tester.tap(find.byKey(const ValueKey('agent-lead')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(milliseconds: 50));

      expect(
        find.byKey(const ValueKey('return-to-agent-chat-button')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsNothing,
      );
      expect(
        tester
            .widget<AgentTerminalPane>(find.byType(AgentTerminalPane))
            .target
            .agent,
        'lead',
      );
      expect(terminalTransport.requests, hasLength(2));
      expect(terminalTransport.requests.last.target.agent, 'lead');
      expect(repository.focusAgentCalls, isEmpty);
      expect(repository.focusWindowCalls, isEmpty);
      expect(terminalTransport.sessions.first.hasOutputListener, isFalse);
      expect(terminalTransport.sessions.last.hasOutputListener, isTrue);

      await tester.tap(find.byKey(const ValueKey('window-tab-review')));
      await tester.pumpAndSettle();

      expect(selectedAgent?.name, 'reviewer');
      expect(windowSelectionCalls, 0);
      expect(repository.focusWindowCalls, isEmpty);
      expect(
        find.byKey(const ValueKey('return-to-agent-chat-button')),
        findsOneWidget,
      );
    });

    testWidgets('mobile host keeps chat inline when selected agent changes', (
      tester,
    ) async {
      final view = _view();
      var selectedAgent = view.agentByName('mobile');

      await _pump(
        tester,
        StatefulBuilder(
          builder: (context, setState) {
            return ProjectHomeMobileChatScaffoldHost(
              view: view,
              selectedAgent: selectedAgent,
              repository: RecordingGatewayRepository(),
              terminalTransport: RecordingTerminalTransport(),
              usePaneInputForMessages: true,
              mobileAgentsCollapsed: false,
              onBack: () {},
              onOpenConnectionDetails: () {},
              onCollapseAgents: () {},
              onExpandAgents: () {},
              onWindowSelected: (_) {},
              onAgentSelected: (agentName) {
                setState(() {
                  selectedAgent = view.agentByName(agentName);
                });
              },
              onRefreshView: () async => null,
              onTimelineScrollDirectionChanged: (_) {},
            );
          },
        ),
      );

      await tester.tap(find.byKey(const ValueKey('agent-lead')));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('agent-workspace-mode-switch')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('ccb-live-terminal-view')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('agent-chat-timeline-lead')),
        findsOneWidget,
      );
    });

    testWidgets('mobile host keeps chat inline when namespace epoch changes', (
      tester,
    ) async {
      var view = _view(namespaceEpoch: 4);
      var selectedAgent = view.agentByName('mobile');

      await _pump(
        tester,
        StatefulBuilder(
          builder: (context, setState) {
            return ProjectHomeMobileChatScaffoldHost(
              view: view,
              selectedAgent: selectedAgent,
              repository: RecordingGatewayRepository(),
              terminalTransport: RecordingTerminalTransport(),
              usePaneInputForMessages: true,
              mobileAgentsCollapsed: false,
              onBack: () {},
              onOpenConnectionDetails: () {},
              onCollapseAgents: () {},
              onExpandAgents: () {},
              onWindowSelected: (_) {},
              onAgentSelected: (_) {},
              onRefreshView: () async {
                setState(() {
                  view = _view(namespaceEpoch: 5);
                  selectedAgent = view.agentByName('mobile');
                });
                return null;
              },
              onTimelineScrollDirectionChanged: (_) {},
            );
          },
        ),
      );

      await tester.tap(
        find.byKey(const ValueKey('agent-conversation-refresh-action')),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('agent-workspace-mode-switch')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('ccb-live-terminal-view')),
        findsNothing,
      );
      expect(
        find.byKey(const ValueKey('agent-message-composer')),
        findsOneWidget,
      );
    });

    testWidgets('mobile collapsed host folds project header into switcher', (
      tester,
    ) async {
      final view = _view();
      var backCalls = 0;
      var detailsCalls = 0;
      var expanded = false;

      await _pump(
        tester,
        ProjectHomeMobileChatScaffoldHost(
          view: view,
          selectedAgent: view.agentByName('mobile'),
          repository: RecordingGatewayRepository(),
          terminalTransport: RecordingTerminalTransport(),
          usePaneInputForMessages: true,
          mobileAgentsCollapsed: true,
          unreadAgentNames: const {'lead'},
          onBack: () {
            backCalls += 1;
          },
          onOpenConnectionDetails: () {
            detailsCalls += 1;
          },
          onCollapseAgents: () {},
          onExpandAgents: () {
            expanded = true;
          },
          onWindowSelected: (_) {},
          onAgentSelected: (_) {},
          onRefreshView: () async => null,
          onTimelineScrollDirectionChanged: (_) {},
        ),
      );

      expect(find.byKey(const ValueKey('project-chat-header')), findsNothing);
      expect(find.byKey(const ValueKey('project-back-button')), findsNothing);
      expect(
        find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
          matching: find.byKey(
            const ValueKey('agent-conversation-refresh-action'),
          ),
        ),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('project-chat-title')), findsOneWidget);
      expect(find.text('demo'), findsOneWidget);
      expect(find.text('main / mobile'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('mobile-agent-switcher-unread-star')),
        findsOneWidget,
      );

      await tester.tap(
        find.byKey(const ValueKey('mobile-agent-switcher-expand-action')),
      );
      await tester.pump();
      tester
          .widget<IconButton>(
            find.byKey(const ValueKey('open-agent-terminal-button')),
          )
          .onPressed!();
      await tester.tap(
        find.byKey(const ValueKey('project-chat-overflow-action')),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('project-chat-projects-menu-item')),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('project-chat-overflow-action')),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('project-chat-diagnostics-menu-item')),
      );
      await tester.pumpAndSettle();

      expect(expanded, isTrue);
      expect(
        find.byKey(const ValueKey('return-to-agent-chat-button')),
        findsOneWidget,
      );
      expect(backCalls, 1);
      expect(detailsCalls, 1);
    });

    testWidgets('wide host renders sidebar surfaces for each state', (
      tester,
    ) async {
      final view = _view();
      final selectedAgent = view.agentByName('mobile');

      await _pump(
        tester,
        _wideHost(view, selectedAgent, WideSidebarState.expanded),
        size: const Size(1200, 800),
      );
      expect(
        find.byKey(const ValueKey('wide-project-workspace')),
        findsOneWidget,
      );
      expect(find.byKey(const ValueKey('wide-project-column')), findsOneWidget);
      expect(
        find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
        findsNothing,
      );
      expect(find.byKey(const ValueKey('project-back-button')), findsNothing);

      await _pump(
        tester,
        _wideHost(view, selectedAgent, WideSidebarState.projectCollapsed),
        size: const Size(1200, 800),
      );
      expect(find.byKey(const ValueKey('wide-project-column')), findsNothing);
      expect(
        find.byKey(const ValueKey('wide-project-expand-action')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
        findsNothing,
      );

      await _pump(
        tester,
        _wideHost(view, selectedAgent, WideSidebarState.allCollapsed),
        size: const Size(1200, 800),
      );
      expect(find.byKey(const ValueKey('wide-project-column')), findsNothing);
      expect(
        find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
          matching: find.byIcon(Icons.auto_awesome_rounded),
        ),
        findsNWidgets(2),
      );
      expect(
        find.byKey(const ValueKey('wide-project-chat-screen')),
        findsOneWidget,
      );
    });
  });
}

ProjectHomeWideScaffoldHost _wideHost(
  CcbProjectView view,
  CcbAgent? selectedAgent,
  WideSidebarState sidebarState,
) {
  return ProjectHomeWideScaffoldHost(
    view: view,
    selectedAgent: selectedAgent,
    repository: RecordingGatewayRepository(),
    terminalTransport: RecordingTerminalTransport(),
    usePaneInputForMessages: true,
    sidebarState: sidebarState,
    onOpenProject: () {},
    onOpenNotifications: () {},
    onOpenConnectionDetails: () {},
    onShowProjects: () {},
    onAgentSelected: (_) {},
    onOpenTerminal: (_) {},
    onToggleSidebar: () {},
    onHorizontalDragStart: (_) {},
    onHorizontalDragUpdate: (_) {},
    onHorizontalDragEnd: (_) {},
    onRefreshView: () async => null,
  );
}

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  Size size = const Size(390, 844),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(home: child));
  await tester.pumpAndSettle();
}

CcbProjectView _view({int namespaceEpoch = 4}) {
  return CcbProjectView(
    project: CcbProject(
      id: 'proj-demo',
      displayName: 'demo',
      root: '/srv/ccb/demo',
    ),
    namespaceEpoch: namespaceEpoch,
    tmuxSocketPath: '/tmp/ccb-demo/tmux.sock',
    tmuxSessionName: 'ccb-demo',
    activeWindow: 'main',
    activePaneId: '%2',
    windows: [
      CcbWindow(
        name: 'main',
        label: 'main',
        kind: 'agents',
        order: 0,
        active: true,
        agents: ['lead', 'mobile'],
      ),
      CcbWindow(
        name: 'review',
        label: 'review',
        kind: 'agents',
        order: 1,
        active: false,
        agents: ['reviewer'],
      ),
    ],
    agents: [
      CcbAgent(
        name: 'lead',
        provider: 'codex',
        window: 'main',
        paneId: '%1',
        order: 0,
        active: false,
        queueDepth: 0,
      ),
      CcbAgent(
        name: 'mobile',
        provider: 'codex',
        window: 'main',
        paneId: '%2',
        order: 1,
        active: true,
        queueDepth: 1,
      ),
      CcbAgent(
        name: 'reviewer',
        provider: 'codex',
        window: 'review',
        paneId: '%3',
        order: 0,
        active: false,
        queueDepth: 0,
      ),
    ],
    contentItems: [],
    notifications: [],
    terminalHistories: {},
  );
}
