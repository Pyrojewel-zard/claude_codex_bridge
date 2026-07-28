class CcbAgent {
  const CcbAgent({
    required this.name,
    required this.provider,
    required this.window,
    required this.order,
    required this.active,
    required this.queueDepth,
    this.paneId,
    this.runtimeHealth,
    this.activityState,
    this.activitySymbol,
    this.activityColor,
    this.activitySource,
    this.activityReason,
    this.lastProgressAt,
  });

  final String name;
  final String provider;
  final String window;
  final int order;
  final bool active;
  final int queueDepth;
  final String? paneId;
  final String? runtimeHealth;
  final String? activityState;
  final String? activitySymbol;
  final String? activityColor;
  final String? activitySource;
  final String? activityReason;
  final String? lastProgressAt;

  CcbAgent copyWith({
    String? activityState,
    String? activitySymbol,
    String? activityColor,
    String? activitySource,
    String? activityReason,
    String? lastProgressAt,
  }) {
    return CcbAgent(
      name: name,
      provider: provider,
      window: window,
      order: order,
      active: active,
      queueDepth: queueDepth,
      paneId: paneId,
      runtimeHealth: runtimeHealth,
      activityState: activityState ?? this.activityState,
      activitySymbol: activitySymbol ?? this.activitySymbol,
      activityColor: activityColor ?? this.activityColor,
      activitySource: activitySource ?? this.activitySource,
      activityReason: activityReason ?? this.activityReason,
      lastProgressAt: lastProgressAt ?? this.lastProgressAt,
    );
  }

  factory CcbAgent.fromJson(Map<String, Object?> json) {
    return CcbAgent(
      name: _text(json['name']),
      provider: _text(json['provider']),
      window: _text(json['window']),
      order: _int(json['order']),
      active: json['active'] == true,
      queueDepth: _int(json['queue_depth']),
      paneId: _optionalText(json['pane_id']),
      runtimeHealth: _optionalText(json['runtime_health']),
      activityState:
          _optionalText(json['activity_state']) ?? _optionalText(json['state']),
      activitySymbol: _optionalText(json['activity_symbol']),
      activityColor: _optionalText(json['activity_color']),
      activitySource: _optionalText(json['activity_source']),
      activityReason: _optionalText(json['activity_reason']),
      lastProgressAt: _optionalText(json['last_progress_at']),
    );
  }
}

String _text(Object? value, {String fallback = ''}) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? fallback : text;
}

String? _optionalText(Object? value) {
  final text = _text(value);
  return text.isEmpty ? null : text;
}

int _int(Object? value) => int.tryParse((value ?? '').toString()) ?? 0;
