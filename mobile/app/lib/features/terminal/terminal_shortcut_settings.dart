import 'package:flutter/material.dart';

import '../../app/terminal_shortcut_preferences.dart';
import '../../l10n/ccb_mobile_localizations.dart';

String terminalShortcutLabel(CcbTerminalShortcut shortcut) {
  return switch (shortcut) {
    CcbTerminalShortcut.escape => 'Esc',
    CcbTerminalShortcut.tab => 'Tab',
    CcbTerminalShortcut.enter => 'Enter',
    CcbTerminalShortcut.backspace => 'Backspace',
    CcbTerminalShortcut.ctrlA => 'Ctrl-A',
    CcbTerminalShortcut.ctrlC => 'Ctrl-C',
    CcbTerminalShortcut.ctrlD => 'Ctrl-D',
    CcbTerminalShortcut.ctrlE => 'Ctrl-E',
    CcbTerminalShortcut.ctrlK => 'Ctrl-K',
    CcbTerminalShortcut.ctrlU => 'Ctrl-U',
    CcbTerminalShortcut.ctrlL => 'Ctrl-L',
    CcbTerminalShortcut.ctrlR => 'Ctrl-R',
    CcbTerminalShortcut.ctrlW => 'Ctrl-W',
    CcbTerminalShortcut.ctrlZ => 'Ctrl-Z',
    CcbTerminalShortcut.delete => 'Delete',
    CcbTerminalShortcut.home => 'Home',
    CcbTerminalShortcut.pageUp => 'Page up',
    CcbTerminalShortcut.arrowLeft => 'Left',
    CcbTerminalShortcut.arrowUp => 'Up',
    CcbTerminalShortcut.arrowDown => 'Down',
    CcbTerminalShortcut.arrowRight => 'Right',
    CcbTerminalShortcut.pageDown => 'Page down',
    CcbTerminalShortcut.end => 'End',
  };
}

IconData? terminalShortcutIcon(CcbTerminalShortcut shortcut) {
  return switch (shortcut) {
    CcbTerminalShortcut.pageUp => Icons.keyboard_double_arrow_up,
    CcbTerminalShortcut.arrowLeft => Icons.keyboard_arrow_left,
    CcbTerminalShortcut.arrowUp => Icons.keyboard_arrow_up,
    CcbTerminalShortcut.arrowDown => Icons.keyboard_arrow_down,
    CcbTerminalShortcut.arrowRight => Icons.keyboard_arrow_right,
    CcbTerminalShortcut.pageDown => Icons.keyboard_double_arrow_down,
    _ => null,
  };
}

class TerminalShortcutSettingsSection extends StatelessWidget {
  const TerminalShortcutSettingsSection({super.key});

  @override
  Widget build(BuildContext context) {
    final scope = CcbTerminalShortcutPreferencesScope.maybeOf(context);
    final preferences =
        scope?.preferences ?? CcbTerminalShortcutPreferences.defaults;
    final onChanged = scope?.onChanged;
    final colorScheme = Theme.of(context).colorScheme;
    final strings = CcbMobileLocalizations.of(context);
    return Material(
      color: colorScheme.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      clipBehavior: Clip.antiAlias,
      child: ListTile(
        key: const ValueKey('terminal-shortcut-settings-entry'),
        enabled: onChanged != null,
        onTap:
            onChanged == null
                ? null
                : () => Navigator.of(context).push<void>(
                  MaterialPageRoute<void>(
                    builder:
                        (_) => TerminalShortcutSettingsScreen(
                          initialPreferences: preferences,
                          onChanged: onChanged,
                        ),
                  ),
                ),
        leading: Icon(Icons.terminal, color: colorScheme.primary),
        title: Text(strings.terminalSettings),
        subtitle: Text(
          '${preferences.fontSize.round()} pt · '
          '${preferences.enabled.length}/${CcbTerminalShortcut.values.length}',
        ),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }
}

class TerminalShortcutSettingsScreen extends StatefulWidget {
  const TerminalShortcutSettingsScreen({
    required this.initialPreferences,
    required this.onChanged,
    super.key,
  });

  final CcbTerminalShortcutPreferences initialPreferences;
  final ValueChanged<CcbTerminalShortcutPreferences> onChanged;

  @override
  State<TerminalShortcutSettingsScreen> createState() =>
      _TerminalShortcutSettingsScreenState();
}

class _TerminalShortcutSettingsScreenState
    extends State<TerminalShortcutSettingsScreen> {
  late CcbTerminalShortcutPreferences _preferences = widget.initialPreferences;

  void _apply(CcbTerminalShortcutPreferences preferences) {
    if (preferences == _preferences) {
      return;
    }
    setState(() {
      _preferences = preferences;
    });
    widget.onChanged(preferences);
  }

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(strings.terminalSettings),
        actions: [
          IconButton(
            key: const ValueKey('terminal-shortcuts-restore-defaults'),
            tooltip: strings.restoreDefaults,
            onPressed:
                _preferences == CcbTerminalShortcutPreferences.defaults
                    ? null
                    : () => _apply(CcbTerminalShortcutPreferences.defaults),
            icon: const Icon(Icons.restore),
          ),
        ],
      ),
      body: Column(
        children: [
          _TerminalFontSizeSetting(
            value: _preferences.fontSize,
            onChanged: (value) => _apply(_preferences.withFontSize(value)),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 6),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                strings.terminalShortcuts,
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
          ),
          Expanded(
            child: ReorderableListView.builder(
              key: const ValueKey('terminal-shortcut-settings-list'),
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
              buildDefaultDragHandles: false,
              itemCount: _preferences.order.length,
              onReorderItem: (oldIndex, newIndex) {
                _apply(_preferences.reordered(oldIndex, newIndex));
              },
              proxyDecorator: (child, index, animation) {
                return AnimatedBuilder(
                  animation: animation,
                  builder: (context, _) {
                    return Material(
                      color: colorScheme.surfaceContainerHigh,
                      elevation: 4 * animation.value,
                      borderRadius: BorderRadius.circular(6),
                      child: child,
                    );
                  },
                );
              },
              itemBuilder: (context, index) {
                final shortcut = _preferences.order[index];
                return Material(
                  key: ValueKey(
                    'terminal-shortcut-setting-${shortcut.wireName}',
                  ),
                  color: colorScheme.surface,
                  child: CheckboxListTile(
                    value: _preferences.enabled.contains(shortcut),
                    controlAffinity: ListTileControlAffinity.leading,
                    onChanged: (value) {
                      _apply(
                        _preferences.withEnabled(shortcut, value ?? false),
                      );
                    },
                    title: Text(terminalShortcutLabel(shortcut)),
                    secondary: ReorderableDragStartListener(
                      index: index,
                      child: Tooltip(
                        message: strings.reorder,
                        child: const SizedBox.square(
                          dimension: 48,
                          child: Icon(Icons.drag_handle),
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _TerminalFontSizeSetting extends StatelessWidget {
  const _TerminalFontSizeSetting({
    required this.value,
    required this.onChanged,
  });

  final double value;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    final roundedValue = value.roundToDouble();
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Column(
          children: [
            ListTile(
              leading: const Icon(Icons.text_fields),
              title: Text(strings.terminalTextSize),
              trailing: Text(
                '${roundedValue.round()} pt',
                key: const ValueKey('terminal-font-size-value'),
              ),
            ),
            Row(
              children: [
                IconButton(
                  key: const ValueKey('terminal-settings-font-decrease'),
                  tooltip: strings.terminalTextSize,
                  onPressed:
                      roundedValue <= ccbTerminalMinimumFontSize
                          ? null
                          : () => onChanged(roundedValue - 1),
                  icon: const Icon(Icons.remove),
                ),
                Expanded(
                  child: Slider(
                    key: const ValueKey('terminal-font-size-slider'),
                    min: ccbTerminalMinimumFontSize,
                    max: ccbTerminalMaximumFontSize,
                    divisions:
                        (ccbTerminalMaximumFontSize -
                                ccbTerminalMinimumFontSize)
                            .round(),
                    value: roundedValue,
                    label: '${roundedValue.round()} pt',
                    onChanged: onChanged,
                  ),
                ),
                IconButton(
                  key: const ValueKey('terminal-settings-font-increase'),
                  tooltip: strings.terminalTextSize,
                  onPressed:
                      roundedValue >= ccbTerminalMaximumFontSize
                          ? null
                          : () => onChanged(roundedValue + 1),
                  icon: const Icon(Icons.add),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
