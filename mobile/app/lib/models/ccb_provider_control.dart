// Provider snapshot, model, usage, and quota semantics align with Paseo at
// pinned commit b599d38. See mobile/THIRD_PARTY_NOTICES.md.
class CcbProviderControl {
  const CcbProviderControl({
    required this.provider,
    this.configuredModel,
    this.configuredThinking,
    this.activeModel,
    this.activeThinking,
    this.pendingModel,
    this.pendingThinking,
    this.restartPending = false,
    this.sessionId,
    this.runtimeSource,
    this.runtimeRevision,
    this.usage,
    this.capabilities = const CcbProviderCapabilities(),
    this.thinkingOptions = const [],
    this.mutationMode = 'unsupported',
  });

  final String provider;
  final String? configuredModel;
  final String? configuredThinking;
  final String? activeModel;
  final String? activeThinking;
  final String? pendingModel;
  final String? pendingThinking;
  final bool restartPending;
  final String? sessionId;
  final String? runtimeSource;
  final String? runtimeRevision;
  final CcbAgentUsage? usage;
  final CcbProviderCapabilities capabilities;
  final List<String> thinkingOptions;
  final String mutationMode;

  String? get displayModel => activeModel ?? configuredModel;
  String? get displayThinking => activeThinking ?? configuredThinking;
  bool get hasPendingChange =>
      restartPending || pendingModel != null || pendingThinking != null;

  factory CcbProviderControl.fromJson(Map<String, Object?> json) {
    return CcbProviderControl(
      provider: _text(json['provider']),
      configuredModel: _optionalText(json['configured_model']),
      configuredThinking: _optionalText(json['configured_thinking']),
      activeModel: _optionalText(json['active_model']),
      activeThinking: _optionalText(json['active_thinking']),
      pendingModel: _optionalText(json['pending_model']),
      pendingThinking: _optionalText(json['pending_thinking']),
      restartPending: json['restart_pending'] == true,
      sessionId: _optionalText(json['session_id']),
      runtimeSource: _optionalText(json['runtime_source']),
      runtimeRevision: _optionalText(json['runtime_revision']),
      usage:
          json['usage'] is Map
              ? CcbAgentUsage.fromJson(_map(json['usage']))
              : null,
      capabilities: CcbProviderCapabilities.fromJson(
        _map(json['capabilities']),
      ),
      thinkingOptions: _strings(json['thinking_options']),
      mutationMode: _text(json['mutation_mode'], fallback: 'unsupported'),
    );
  }
}

class CcbProviderCapabilities {
  const CcbProviderCapabilities({
    this.modelCatalog = false,
    this.modelSelect = false,
    this.thinkingSelect = false,
    this.sessionUsage = false,
    this.accountQuota = false,
  });

  final bool modelCatalog;
  final bool modelSelect;
  final bool thinkingSelect;
  final bool sessionUsage;
  final bool accountQuota;

  factory CcbProviderCapabilities.fromJson(Map<String, Object?> json) {
    return CcbProviderCapabilities(
      modelCatalog: json['model_catalog'] == true,
      modelSelect: json['model_select'] == true,
      thinkingSelect: json['thinking_select'] == true,
      sessionUsage: json['session_usage'] == true,
      accountQuota: json['account_quota'] == true,
    );
  }
}

class CcbAgentUsage {
  const CcbAgentUsage({
    this.inputTokens,
    this.cachedInputTokens,
    this.outputTokens,
    this.reasoningOutputTokens,
    this.totalTokens,
    this.contextWindowMaxTokens,
    this.contextWindowUsedTokens,
    this.scope = 'unknown',
  });

  final int? inputTokens;
  final int? cachedInputTokens;
  final int? outputTokens;
  final int? reasoningOutputTokens;
  final int? totalTokens;
  final int? contextWindowMaxTokens;
  final int? contextWindowUsedTokens;
  final String scope;

  double? get contextUtilization {
    final used = contextWindowUsedTokens;
    final maximum = contextWindowMaxTokens;
    if (used == null || maximum == null || maximum <= 0) {
      return null;
    }
    return (used / maximum).clamp(0.0, 1.0).toDouble();
  }

  factory CcbAgentUsage.fromJson(Map<String, Object?> json) {
    return CcbAgentUsage(
      inputTokens: _optionalInt(json['input_tokens']),
      cachedInputTokens: _optionalInt(json['cached_input_tokens']),
      outputTokens: _optionalInt(json['output_tokens']),
      reasoningOutputTokens: _optionalInt(json['reasoning_output_tokens']),
      totalTokens: _optionalInt(json['total_tokens']),
      contextWindowMaxTokens: _optionalInt(json['context_window_max_tokens']),
      contextWindowUsedTokens: _optionalInt(json['context_window_used_tokens']),
      scope: _text(json['scope'], fallback: 'unknown'),
    );
  }
}

class CcbProviderControlDetails {
  const CcbProviderControlDetails({
    required this.projectId,
    required this.agent,
    required this.namespaceEpoch,
    required this.control,
    required this.catalog,
    this.configRevision,
    this.accountUsage,
  });

  final String projectId;
  final String agent;
  final int namespaceEpoch;
  final CcbProviderControl control;
  final CcbProviderCatalog catalog;
  final String? configRevision;
  final CcbProviderAccountUsage? accountUsage;

  factory CcbProviderControlDetails.fromJson(Map<String, Object?> json) {
    return CcbProviderControlDetails(
      projectId: _text(json['project_id']),
      agent: _text(json['agent']),
      namespaceEpoch: _optionalInt(json['namespace_epoch']) ?? 0,
      control: CcbProviderControl.fromJson(_map(json['provider_control'])),
      catalog: CcbProviderCatalog.fromJson(_map(json['provider_catalog'])),
      configRevision: _optionalText(json['config_revision']),
      accountUsage:
          json['account_usage'] is Map
              ? CcbProviderAccountUsage.fromJson(_map(json['account_usage']))
              : null,
    );
  }
}

class CcbProviderSettingsResult {
  const CcbProviderSettingsResult({
    required this.status,
    required this.agent,
    required this.provider,
    required this.configuredModel,
    required this.configRevision,
    required this.changed,
    required this.restartRequired,
    required this.idempotencyKey,
    required this.namespaceEpoch,
    this.configuredThinking,
  });

  final String status;
  final String agent;
  final String provider;
  final String configuredModel;
  final String? configuredThinking;
  final String configRevision;
  final bool changed;
  final bool restartRequired;
  final String idempotencyKey;
  final int namespaceEpoch;

  factory CcbProviderSettingsResult.fromJson(Map<String, Object?> json) {
    return CcbProviderSettingsResult(
      status: _text(json['status']),
      agent: _text(json['agent']),
      provider: _text(json['provider']),
      configuredModel: _text(json['configured_model']),
      configuredThinking: _optionalText(json['configured_thinking']),
      configRevision: _text(json['config_revision']),
      changed: json['changed'] == true,
      restartRequired: json['restart_required'] == true,
      idempotencyKey: _text(json['idempotency_key']),
      namespaceEpoch: _optionalInt(json['namespace_epoch']) ?? 0,
    );
  }
}

class CcbProviderCatalog {
  const CcbProviderCatalog({
    required this.provider,
    this.models = const [],
    this.modelSource = 'none',
    this.modelSelectable = false,
    this.customModel = false,
    this.staticThinking = false,
  });

  final String provider;
  final List<CcbProviderModel> models;
  final String modelSource;
  final bool modelSelectable;
  final bool customModel;
  final bool staticThinking;

  factory CcbProviderCatalog.fromJson(Map<String, Object?> json) {
    return CcbProviderCatalog(
      provider: _text(json['id']),
      models: [
        for (final item in _mapList(json['models']))
          CcbProviderModel.fromJson(item),
      ],
      modelSource: _text(json['model_source'], fallback: 'none'),
      modelSelectable: json['model_shortcut'] == true,
      customModel: json['custom_model'] == true,
      staticThinking: json['static_thinking'] == true,
    );
  }
}

class CcbProviderModel {
  const CcbProviderModel({
    required this.id,
    required this.label,
    this.description,
    this.reasoningLevels = const [],
    this.defaultReasoningLevel,
    this.contextWindowMaxTokens,
  });

  final String id;
  final String label;
  final String? description;
  final List<String> reasoningLevels;
  final String? defaultReasoningLevel;
  final int? contextWindowMaxTokens;

  factory CcbProviderModel.fromJson(Map<String, Object?> json) {
    return CcbProviderModel(
      id: _text(json['id']),
      label: _text(json['label'], fallback: _text(json['id'])),
      description: _optionalText(json['description']),
      reasoningLevels: _strings(json['reasoning_levels']),
      defaultReasoningLevel: _optionalText(json['default_reasoning_level']),
      contextWindowMaxTokens: _optionalInt(json['context_window_max_tokens']),
    );
  }
}

class CcbProviderAccountUsage {
  const CcbProviderAccountUsage({
    required this.provider,
    required this.status,
    this.planLabel,
    this.windows = const [],
    this.balances = const [],
    this.details = const [],
    this.fetchedAt,
    this.nextRefreshAt,
    this.error,
  });

  final String provider;
  final String status;
  final String? planLabel;
  final List<CcbProviderUsageWindow> windows;
  final List<CcbProviderUsageBalance> balances;
  final List<CcbProviderUsageDetail> details;
  final DateTime? fetchedAt;
  final DateTime? nextRefreshAt;
  final String? error;

  factory CcbProviderAccountUsage.fromJson(Map<String, Object?> json) {
    return CcbProviderAccountUsage(
      provider: _text(json['provider_id'] ?? json['provider']),
      status: _text(json['status'], fallback: 'unavailable'),
      planLabel: _optionalText(json['plan_label']),
      windows: [
        for (final item in _mapList(json['windows']))
          CcbProviderUsageWindow.fromJson(item),
      ],
      balances: [
        for (final item in _mapList(json['balances']))
          CcbProviderUsageBalance.fromJson(item),
      ],
      details: [
        for (final item in _mapList(json['details']))
          CcbProviderUsageDetail.fromJson(item),
      ],
      fetchedAt: DateTime.tryParse(_text(json['fetched_at'])),
      nextRefreshAt: DateTime.tryParse(_text(json['next_refresh_at'])),
      error: _optionalText(json['error']),
    );
  }
}

class CcbProviderUsageWindow {
  const CcbProviderUsageWindow({
    required this.id,
    required this.label,
    this.usedPct,
    this.remainingPct,
    this.resetsAt,
    this.tone = 'default',
  });

  final String id;
  final String label;
  final double? usedPct;
  final double? remainingPct;
  final DateTime? resetsAt;
  final String tone;

  factory CcbProviderUsageWindow.fromJson(Map<String, Object?> json) {
    return CcbProviderUsageWindow(
      id: _text(json['id']),
      label: _text(json['label']),
      usedPct: _optionalDouble(json['used_pct']),
      remainingPct: _optionalDouble(json['remaining_pct']),
      resetsAt: DateTime.tryParse(_text(json['resets_at'])),
      tone: _text(json['tone'], fallback: 'default'),
    );
  }
}

class CcbProviderUsageBalance {
  const CcbProviderUsageBalance({
    required this.id,
    required this.label,
    this.remaining,
    this.unit,
    this.tone = 'default',
  });

  final String id;
  final String label;
  final double? remaining;
  final String? unit;
  final String tone;

  factory CcbProviderUsageBalance.fromJson(Map<String, Object?> json) {
    return CcbProviderUsageBalance(
      id: _text(json['id']),
      label: _text(json['label']),
      remaining: _optionalDouble(json['remaining']),
      unit: _optionalText(json['unit']),
      tone: _text(json['tone'], fallback: 'default'),
    );
  }
}

class CcbProviderUsageDetail {
  const CcbProviderUsageDetail({
    required this.id,
    required this.label,
    required this.value,
  });

  final String id;
  final String label;
  final String value;

  factory CcbProviderUsageDetail.fromJson(Map<String, Object?> json) {
    return CcbProviderUsageDetail(
      id: _text(json['id']),
      label: _text(json['label']),
      value: _text(json['value']),
    );
  }
}

Map<String, Object?> _map(Object? value) =>
    value is Map
        ? {for (final entry in value.entries) entry.key.toString(): entry.value}
        : const {};

List<Map<String, Object?>> _mapList(Object? value) =>
    value is Iterable
        ? [
          for (final item in value)
            if (item is Map) _map(item),
        ]
        : const [];

List<String> _strings(Object? value) =>
    value is Iterable
        ? [
          for (final item in value)
            if (_text(item).isNotEmpty) _text(item),
        ]
        : const [];

String _text(Object? value, {String fallback = ''}) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? fallback : text;
}

String? _optionalText(Object? value) {
  final text = _text(value);
  return text.isEmpty ? null : text;
}

int? _optionalInt(Object? value) =>
    value is int ? value : int.tryParse(_text(value));

double? _optionalDouble(Object? value) =>
    value is num ? value.toDouble() : double.tryParse(_text(value));
