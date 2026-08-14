import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

void main() {
  test('terminal shortcut preferences round-trip order and enabled keys', () {
    final preferences = CcbTerminalShortcutPreferences(
      order: const [
        CcbTerminalShortcut.ctrlC,
        CcbTerminalShortcut.escape,
        CcbTerminalShortcut.tab,
      ],
      enabled: const {CcbTerminalShortcut.ctrlC, CcbTerminalShortcut.tab},
    );

    final decoded = CcbTerminalShortcutPreferences.fromJsonString(
      preferences.toJsonString(),
    );

    expect(decoded, preferences);
    expect(decoded.order.take(3), const [
      CcbTerminalShortcut.ctrlC,
      CcbTerminalShortcut.escape,
      CcbTerminalShortcut.tab,
    ]);
    expect(decoded.enabledInOrder, const [
      CcbTerminalShortcut.ctrlC,
      CcbTerminalShortcut.tab,
    ]);
    expect(decoded.fontSize, ccbTerminalDefaultFontSize);
  });

  test('terminal shortcut preferences tolerate old and unknown values', () {
    final preferences = CcbTerminalShortcutPreferences.fromJsonString('''
      {
        "version": 2,
        "order": ["tab", "future-key", "tab", "escape"],
        "enabled": ["escape", "future-key"]
      }
    ''');

    expect(preferences.order.take(2), const [
      CcbTerminalShortcut.tab,
      CcbTerminalShortcut.escape,
    ]);
    expect(preferences.order.toSet(), CcbTerminalShortcut.values.toSet());
    expect(preferences.enabled, const {CcbTerminalShortcut.escape});
    expect(preferences.fontSize, ccbTerminalDefaultFontSize);
    expect(
      CcbTerminalShortcutPreferences.fromJsonString('{not-json'),
      CcbTerminalShortcutPreferences.defaults,
    );
  });

  test('version 1 preferences enable newly introduced terminal keys', () {
    final preferences = CcbTerminalShortcutPreferences.fromJsonString('''
      {
        "version": 1,
        "order": ["tab", "escape", "ctrl-c"],
        "enabled": ["tab", "ctrl-c"]
      }
    ''');

    expect(
      preferences.enabled,
      containsAll(const [
        CcbTerminalShortcut.tab,
        CcbTerminalShortcut.ctrlC,
        CcbTerminalShortcut.enter,
        CcbTerminalShortcut.backspace,
        CcbTerminalShortcut.ctrlA,
        CcbTerminalShortcut.ctrlE,
        CcbTerminalShortcut.ctrlK,
        CcbTerminalShortcut.ctrlR,
        CcbTerminalShortcut.ctrlW,
        CcbTerminalShortcut.ctrlZ,
      ]),
    );
    expect(preferences.enabled, isNot(contains(CcbTerminalShortcut.escape)));
  });

  test('terminal shortcut preferences reorder and toggle independently', () {
    final defaults = CcbTerminalShortcutPreferences.defaults;
    final reordered = defaults.reordered(0, 2);
    final disabled = reordered.withEnabled(CcbTerminalShortcut.tab, false);

    expect(reordered.order.take(3), const [
      CcbTerminalShortcut.tab,
      CcbTerminalShortcut.ctrlC,
      CcbTerminalShortcut.escape,
    ]);
    expect(disabled.enabled, isNot(contains(CcbTerminalShortcut.tab)));
    expect(disabled.order, reordered.order);
  });

  test('terminal font preference persists and clamps to readable bounds', () {
    final preferences = CcbTerminalShortcutPreferences(fontSize: 17);
    final decoded = CcbTerminalShortcutPreferences.fromJsonString(
      preferences.toJsonString(),
    );

    expect(decoded.fontSize, 17);
    expect(
      CcbTerminalShortcutPreferences(fontSize: 2).fontSize,
      ccbTerminalMinimumFontSize,
    );
    expect(
      CcbTerminalShortcutPreferences(fontSize: 50).fontSize,
      ccbTerminalMaximumFontSize,
    );
    expect(
      CcbTerminalShortcutPreferences(fontSize: double.nan).fontSize,
      ccbTerminalDefaultFontSize,
    );
  });
}
