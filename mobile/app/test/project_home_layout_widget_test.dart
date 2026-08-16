import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_driver.dart';

void main() {
  testWidgets('renders CCB project and agent fixture', (tester) async {
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();

    expect(find.text('CCB Mobile'), findsNothing);
    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
    expect(find.byKey(const ValueKey('project-open-current')), findsOneWidget);
    expect(find.text('demo'), findsOneWidget);
    await openCurrentProject(tester);

    expect(find.byKey(const ValueKey('project-chat-header')), findsOneWidget);
    expect(find.byKey(const ValueKey('project-chat-title')), findsOneWidget);
    expect(find.byKey(const ValueKey('window-switcher')), findsOneWidget);
    expect(find.byKey(const ValueKey('window-tab-main')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-switcher')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('connection-details-action')),
      findsOneWidget,
    );
    expect(find.text('lead'), findsOneWidget);
    expect(find.text('mobile'), findsWidgets);
    expectAgentSelected(tester, 'mobile');
    await tapVisible(
      tester,
      const ValueKey('conversation-expand-reply-content-mobile-emulator'),
    );
    expect(
      find.byKey(const ValueKey('structured-content-reader')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('markdown-body-content-mobile-emulator')),
      findsOneWidget,
    );
    expect(find.text('Emulator landing status'), findsWidgets);
    await tapVisible(
      tester,
      const ValueKey('conversation-expand-terminal-history-mobile'),
    );
    expect(
      find.byKey(const ValueKey('readable-terminal-history')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('readable-terminal-history-scroll')),
      findsOneWidget,
    );
    expect(find.text('tmux scrollback'), findsOneWidget);
    expect(find.byKey(const ValueKey('runtime-mode-panel')), findsNothing);
    expect(find.byKey(const ValueKey('gateway-pairing-panel')), findsNothing);
    expect(find.byKey(const ValueKey('window-details-panel')), findsNothing);
  });

  testWidgets('wide layout shows project and agent sidebars', (tester) async {
    await setTestSurfaceSize(tester, const Size(1200, 800));
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('wide-project-workspace')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('wide-project-column')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('wide-window-group-main')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('wide-project-chat-screen')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('project-list')), findsOneWidget);
    expect(find.byKey(const ValueKey('project-open-current')), findsOneWidget);
    expect(find.byKey(const ValueKey('project-back-button')), findsNothing);
    expect(find.byKey(const ValueKey('agent-switcher')), findsNothing);
    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsOneWidget,
    );
    expectAgentTileSelected(tester, 'mobile');

    await tester.tap(find.byKey(const ValueKey('agent-lead')));
    await tester.pumpAndSettle();

    expectAgentTileSelected(tester, 'lead');
    expect(
      find.byKey(const ValueKey('agent-message-composer')),
      findsOneWidget,
    );
  });

  testWidgets('agent terminal mode survives narrow and wide layout changes', (
    tester,
  ) async {
    await setTestSurfaceSize(tester, const Size(430, 900));
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    await tester.tap(find.byKey(const ValueKey('open-agent-terminal-button')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('project-agent-terminal-mode')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('return-to-agent-chat-button')),
      findsOneWidget,
    );

    await setTestSurfaceSize(tester, const Size(1200, 800));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('wide-project-agent-terminal-mode')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('return-to-agent-chat-button')),
      findsOneWidget,
    );

    await setTestSurfaceSize(tester, const Size(430, 900));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('project-agent-terminal-mode')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('agent-message-composer')), findsNothing);
  });

  testWidgets('mobile layout collapses agents and composer independently', (
    tester,
  ) async {
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-expanded')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('agent-switcher')), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('mobile-agent-switcher-expanded')),
      const Offset(0, -80),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-switcher')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-expanded')),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey('mobile-agent-switcher-collapse-action')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-switcher')), findsNothing);
    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
      findsOneWidget,
    );
    expect(find.text('main / mobile · Codex'), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
      const Offset(0, 80),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-switcher')), findsNothing);
    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
      findsOneWidget,
    );

    await tester.drag(
      find.byKey(const ValueKey('agent-chat-timeline')),
      const Offset(0, 480),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-switcher')), findsNothing);
    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey('mobile-agent-switcher-expand-action')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-switcher')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('mobile-agent-switcher-collapsed')),
      findsNothing,
    );

    await tester.enterText(
      find.byKey(const ValueKey('agent-message-composer')),
      'draft ping',
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('agent-composer-collapse-action')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('agent-message-composer')), findsNothing);
    expect(
      find.byKey(const ValueKey('agent-chat-composer-collapsed')),
      findsOneWidget,
    );
    expect(find.text('draft ping'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('agent-composer-expand-action')),
    );
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(
      find.byKey(const ValueKey('agent-message-composer')),
    );
    expect(field.controller?.text, 'draft ping');
  });

  testWidgets('mobile composer stays compact with keyboard insets', (
    tester,
  ) async {
    await setTestSurfaceSize(tester, const Size(844, 390));
    setTestViewInsets(tester, const EdgeInsets.only(bottom: 120));
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();
    await openCurrentProject(tester);

    await tester.enterText(
      find.byKey(const ValueKey('agent-message-composer')),
      'keyboard draft',
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    await tester.tap(
      find.byKey(const ValueKey('agent-composer-collapse-action')),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('keyboard draft'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('agent-chat-composer-collapsed')),
      findsOneWidget,
    );
  });

  testWidgets('wide layout snaps drag to project and agent sidebar stops', (
    tester,
  ) async {
    await setTestSurfaceSize(tester, const Size(1200, 800));
    await tester.pumpWidget(const CcbMobileApp(enableProductOnboarding: false));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wide-project-column')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('wide-sidebar-drag-handle')),
      const Offset(-160, 0),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wide-project-column')), findsNothing);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('wide-project-expand-action')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('agent-message-composer')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const ValueKey('wide-project-expand-action')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wide-project-column')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('wide-sidebar-drag-handle')),
      const Offset(-360, 0),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('wide-project-column')), findsNothing);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsNothing);
    expect(
      find.byKey(const ValueKey('selected-agent-workspace')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('agent-message-composer')),
      findsOneWidget,
    );

    await tester.drag(
      find.byKey(const ValueKey('wide-sidebar-drag-handle')),
      const Offset(160, 0),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('wide-collapsed-sidebar-rail')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('wide-project-column')), findsNothing);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);

    await tester.drag(
      find.byKey(const ValueKey('wide-sidebar-drag-handle')),
      const Offset(160, 0),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wide-project-column')), findsOneWidget);
    expect(find.byKey(const ValueKey('agent-secondary-list')), findsOneWidget);
  });
}
