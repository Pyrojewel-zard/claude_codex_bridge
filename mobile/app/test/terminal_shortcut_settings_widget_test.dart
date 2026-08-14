import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('settings can disable, reorder, restore, and persist shortcuts', (
    tester,
  ) async {
    final store = MemoryTerminalShortcutPreferenceStore();

    await tester.pumpWidget(
      CcbMobileApp(
        enableProductOnboarding: true,
        terminalShortcutPreferenceStore: store,
        profileStore: GatewayHostProfileStore(secureStore: MemorySecureStore()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    final entry = find.byKey(
      const ValueKey('terminal-shortcut-settings-entry'),
    );
    await tester.ensureVisible(entry);
    await tester.tap(entry);
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('terminal-font-size-value')), findsOne);
    await tester.tap(
      find.byKey(const ValueKey('terminal-settings-font-increase')),
    );
    await tester.pump();
    expect(store.value.fontSize, 14);

    final escapeSetting = find.byKey(
      const ValueKey('terminal-shortcut-setting-escape'),
    );
    await tester.tap(
      find.descendant(of: escapeSetting, matching: find.byType(Checkbox)),
    );
    await tester.pump();

    final list = tester.widget<ReorderableListView>(
      find.byKey(const ValueKey('terminal-shortcut-settings-list')),
    );
    list.onReorderItem!.call(0, 2);
    await tester.pump();

    expect(store.value.enabled, isNot(contains(CcbTerminalShortcut.escape)));
    expect(store.value.order.take(3), const [
      CcbTerminalShortcut.tab,
      CcbTerminalShortcut.ctrlC,
      CcbTerminalShortcut.escape,
    ]);
    expect(store.value.fontSize, 14);

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(
      CcbMobileApp(
        enableProductOnboarding: true,
        terminalShortcutPreferenceStore: store,
        profileStore: GatewayHostProfileStore(secureStore: MemorySecureStore()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    final restoredEntry = find.byKey(
      const ValueKey('terminal-shortcut-settings-entry'),
    );
    await tester.ensureVisible(restoredEntry);
    await tester.tap(restoredEntry);
    await tester.pumpAndSettle();

    final restoredEscape = tester.widget<CheckboxListTile>(
      find.descendant(
        of: find.byKey(const ValueKey('terminal-shortcut-setting-escape')),
        matching: find.byType(CheckboxListTile),
      ),
    );
    expect(restoredEscape.value, isFalse);
    expect(find.text('14 pt'), findsOneWidget);
    final tabTop = tester.getTopLeft(
      find.byKey(const ValueKey('terminal-shortcut-setting-tab')),
    );
    final ctrlCTop = tester.getTopLeft(
      find.byKey(const ValueKey('terminal-shortcut-setting-ctrl-c')),
    );
    expect(tabTop.dy, lessThan(ctrlCTop.dy));

    await tester.tap(
      find.byKey(const ValueKey('terminal-shortcuts-restore-defaults')),
    );
    await tester.pump();
    expect(store.value, CcbTerminalShortcutPreferences.defaults);
    expect(find.text('13 pt'), findsOneWidget);
  });

  testWidgets('terminal toolbar follows configured enabled order', (
    tester,
  ) async {
    final preferences = CcbTerminalShortcutPreferences(
      order: const [
        CcbTerminalShortcut.ctrlC,
        CcbTerminalShortcut.escape,
        CcbTerminalShortcut.tab,
      ],
      enabled: const {
        CcbTerminalShortcut.ctrlC,
        CcbTerminalShortcut.escape,
        CcbTerminalShortcut.tab,
      },
    );

    await tester.pumpWidget(
      CcbTerminalShortcutPreferencesScope(
        preferences: preferences,
        onChanged: (_) {},
        child: MaterialApp(
          home: Scaffold(
            body: TerminalControlToolbar(
              enabled: true,
              onLatestOutput: () {},
              onEscape: () {},
              onTab: () {},
              onCtrlC: () {},
              onCtrlD: () {},
              onCtrlU: () {},
              onCtrlL: () {},
              onDelete: () {},
              onHome: () {},
              onEnd: () {},
              onPageUp: () {},
              onPageDown: () {},
              onArrowLeft: () {},
              onArrowUp: () {},
              onArrowDown: () {},
              onArrowRight: () {},
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('terminal-shortcuts-toggle')));
    await tester.pumpAndSettle();

    final ctrlC = find.byKey(const ValueKey('terminal-key-ctrl-c'));
    final escape = find.byKey(const ValueKey('terminal-key-escape'));
    final tab = find.byKey(const ValueKey('terminal-key-tab'));
    expect(ctrlC, findsOneWidget);
    expect(escape, findsOneWidget);
    expect(tab, findsOneWidget);
    expect(find.byKey(const ValueKey('terminal-key-ctrl-d')), findsNothing);
    expect(tester.getTopLeft(ctrlC).dy, tester.getTopLeft(escape).dy);
    expect(tester.getTopLeft(ctrlC).dx, lessThan(tester.getTopLeft(escape).dx));
    expect(tester.getTopLeft(escape).dx, lessThan(tester.getTopLeft(tab).dx));
  });
}

class MemoryTerminalShortcutPreferenceStore
    implements CcbTerminalShortcutPreferenceStore {
  CcbTerminalShortcutPreferences value =
      CcbTerminalShortcutPreferences.defaults;

  @override
  Future<CcbTerminalShortcutPreferences> read() async => value;

  @override
  Future<void> write(CcbTerminalShortcutPreferences preferences) async {
    value = preferences;
  }
}
