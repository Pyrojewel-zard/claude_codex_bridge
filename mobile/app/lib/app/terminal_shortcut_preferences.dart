import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

enum CcbTerminalShortcut {
  escape('escape'),
  tab('tab'),
  ctrlC('ctrl-c'),
  ctrlD('ctrl-d'),
  ctrlU('ctrl-u'),
  ctrlL('ctrl-l'),
  delete('delete'),
  home('home'),
  pageUp('page-up'),
  arrowLeft('arrow-left'),
  arrowUp('arrow-up'),
  arrowDown('arrow-down'),
  arrowRight('arrow-right'),
  pageDown('page-down'),
  end('end'),
  enter('enter'),
  backspace('backspace'),
  ctrlA('ctrl-a'),
  ctrlE('ctrl-e'),
  ctrlK('ctrl-k'),
  ctrlR('ctrl-r'),
  ctrlW('ctrl-w'),
  ctrlZ('ctrl-z');

  const CcbTerminalShortcut(this.wireName);

  final String wireName;
}

const ccbTerminalMinimumFontSize = 10.0;
const ccbTerminalMaximumFontSize = 22.0;
const ccbTerminalDefaultFontSize = 13.0;
const _terminalShortcutPreferencesVersion = 3;
const _terminalExpandedShortcutsVersion = 2;
const _terminalShortcutsAddedInVersion2 = <CcbTerminalShortcut>{
  CcbTerminalShortcut.enter,
  CcbTerminalShortcut.backspace,
  CcbTerminalShortcut.ctrlA,
  CcbTerminalShortcut.ctrlE,
  CcbTerminalShortcut.ctrlK,
  CcbTerminalShortcut.ctrlR,
  CcbTerminalShortcut.ctrlW,
  CcbTerminalShortcut.ctrlZ,
};

@immutable
class CcbTerminalShortcutPreferences {
  CcbTerminalShortcutPreferences({
    Iterable<CcbTerminalShortcut>? order,
    Iterable<CcbTerminalShortcut>? enabled,
    double fontSize = ccbTerminalDefaultFontSize,
  }) : order = List.unmodifiable(_normalizeOrder(order)),
       enabled = Set.unmodifiable(enabled ?? CcbTerminalShortcut.values),
       fontSize = _normalizeFontSize(fontSize);

  static final defaults = CcbTerminalShortcutPreferences();

  final List<CcbTerminalShortcut> order;
  final Set<CcbTerminalShortcut> enabled;
  final double fontSize;

  List<CcbTerminalShortcut> get enabledInOrder =>
      List.unmodifiable(order.where(enabled.contains));

  CcbTerminalShortcutPreferences withEnabled(
    CcbTerminalShortcut shortcut,
    bool value,
  ) {
    final nextEnabled = enabled.toSet();
    if (value) {
      nextEnabled.add(shortcut);
    } else {
      nextEnabled.remove(shortcut);
    }
    return CcbTerminalShortcutPreferences(
      order: order,
      enabled: nextEnabled,
      fontSize: fontSize,
    );
  }

  CcbTerminalShortcutPreferences reordered(int oldIndex, int newIndex) {
    if (oldIndex < 0 || oldIndex >= order.length) {
      return this;
    }
    final nextOrder = order.toList();
    final shortcut = nextOrder.removeAt(oldIndex);
    nextOrder.insert(newIndex.clamp(0, nextOrder.length), shortcut);
    return CcbTerminalShortcutPreferences(
      order: nextOrder,
      enabled: enabled,
      fontSize: fontSize,
    );
  }

  CcbTerminalShortcutPreferences withFontSize(double value) {
    return CcbTerminalShortcutPreferences(
      order: order,
      enabled: enabled,
      fontSize: value,
    );
  }

  Map<String, Object> toJson() => <String, Object>{
    'version': _terminalShortcutPreferencesVersion,
    'order': order.map((shortcut) => shortcut.wireName).toList(),
    'enabled': enabled.map((shortcut) => shortcut.wireName).toList(),
    'font_size': fontSize,
  };

  String toJsonString() => jsonEncode(toJson());

  static CcbTerminalShortcutPreferences fromJsonString(String? source) {
    if (source == null || source.trim().isEmpty) {
      return defaults;
    }
    try {
      final decoded = jsonDecode(source);
      if (decoded is! Map<String, dynamic>) {
        return defaults;
      }
      return fromJson(decoded);
    } on FormatException {
      return defaults;
    }
  }

  static CcbTerminalShortcutPreferences fromJson(Map<String, dynamic> json) {
    final parsedOrder = _parseShortcutList(json['order']);
    final rawEnabled = json['enabled'];
    final parsedEnabled =
        rawEnabled is List<Object?> ? _parseShortcutList(rawEnabled) : null;
    final version = json['version'] is int ? json['version'] as int : 1;
    final migratedEnabled = parsedEnabled?.toSet();
    if (migratedEnabled != null &&
        version < _terminalExpandedShortcutsVersion) {
      migratedEnabled.addAll(_terminalShortcutsAddedInVersion2);
    }
    return CcbTerminalShortcutPreferences(
      order: parsedOrder,
      enabled: migratedEnabled,
      fontSize:
          json['font_size'] is num
              ? (json['font_size'] as num).toDouble()
              : ccbTerminalDefaultFontSize,
    );
  }

  static double _normalizeFontSize(double value) {
    if (!value.isFinite) {
      return ccbTerminalDefaultFontSize;
    }
    return value
        .clamp(ccbTerminalMinimumFontSize, ccbTerminalMaximumFontSize)
        .toDouble();
  }

  static List<CcbTerminalShortcut> _normalizeOrder(
    Iterable<CcbTerminalShortcut>? value,
  ) {
    final seen = <CcbTerminalShortcut>{};
    final result = <CcbTerminalShortcut>[];
    for (final shortcut in value ?? const <CcbTerminalShortcut>[]) {
      if (seen.add(shortcut)) {
        result.add(shortcut);
      }
    }
    for (final shortcut in CcbTerminalShortcut.values) {
      if (seen.add(shortcut)) {
        result.add(shortcut);
      }
    }
    return result;
  }

  static List<CcbTerminalShortcut> _parseShortcutList(Object? value) {
    if (value is! List<Object?>) {
      return const [];
    }
    final byWireName = <String, CcbTerminalShortcut>{
      for (final shortcut in CcbTerminalShortcut.values)
        shortcut.wireName: shortcut,
    };
    return value
        .whereType<String>()
        .map((wireName) => byWireName[wireName])
        .whereType<CcbTerminalShortcut>()
        .toList();
  }

  @override
  bool operator ==(Object other) {
    return other is CcbTerminalShortcutPreferences &&
        listEquals(order, other.order) &&
        setEquals(enabled, other.enabled) &&
        fontSize == other.fontSize;
  }

  @override
  int get hashCode => Object.hash(
    Object.hashAll(order),
    Object.hashAllUnordered(enabled),
    fontSize,
  );
}

abstract class CcbTerminalShortcutPreferenceStore {
  Future<CcbTerminalShortcutPreferences> read();

  Future<void> write(CcbTerminalShortcutPreferences preferences);
}

class FlutterCcbTerminalShortcutPreferenceStore
    implements CcbTerminalShortcutPreferenceStore {
  FlutterCcbTerminalShortcutPreferenceStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'ccb_mobile.terminal.shortcuts';

  final FlutterSecureStorage _storage;

  @override
  Future<CcbTerminalShortcutPreferences> read() async {
    return CcbTerminalShortcutPreferences.fromJsonString(
      await _storage.read(key: _key),
    );
  }

  @override
  Future<void> write(CcbTerminalShortcutPreferences preferences) {
    return _storage.write(key: _key, value: preferences.toJsonString());
  }
}

class CcbTerminalShortcutPreferencesScope extends InheritedWidget {
  const CcbTerminalShortcutPreferencesScope({
    required this.preferences,
    required this.onChanged,
    required super.child,
    super.key,
  });

  final CcbTerminalShortcutPreferences preferences;
  final ValueChanged<CcbTerminalShortcutPreferences>? onChanged;

  static CcbTerminalShortcutPreferencesScope? maybeOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<
          CcbTerminalShortcutPreferencesScope
        >();
  }

  @override
  bool updateShouldNotify(CcbTerminalShortcutPreferencesScope oldWidget) {
    return preferences != oldWidget.preferences ||
        onChanged != oldWidget.onChanged;
  }
}
