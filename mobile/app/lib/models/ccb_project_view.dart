import 'ccb_agent.dart';
import 'ccb_content_item.dart';
import 'ccb_notification.dart';
import 'ccb_project.dart';
import 'ccb_scope.dart';
import 'ccb_terminal_target.dart';
import 'ccb_window.dart';
import 'readable_terminal_history.dart';

class CcbProjectView {
  const CcbProjectView({
    required this.project,
    required this.namespaceEpoch,
    required this.tmuxSocketPath,
    required this.tmuxSessionName,
    required this.activeWindow,
    required this.activePaneId,
    required this.windows,
    required this.agents,
    this.comms = const [],
    required this.contentItems,
    required this.notifications,
    required this.terminalHistories,
  });

  final CcbProject project;
  final int? namespaceEpoch;
  final String? tmuxSocketPath;
  final String? tmuxSessionName;
  final String? activeWindow;
  final String? activePaneId;
  final List<CcbWindow> windows;
  final List<CcbAgent> agents;
  final List<CcbCommsItem> comms;
  final List<CcbContentItem> contentItems;
  final List<CcbNotification> notifications;
  final Map<String, ReadableTerminalHistory> terminalHistories;

  factory CcbProjectView.fromProjectViewPayload(Map<String, Object?> payload) {
    final view = _map(payload['view']);
    final source = view.isEmpty ? payload : view;
    final namespace = _map(source['namespace']);
    final project = CcbProject.fromJson(_map(source['project']));
    final agents = [
      for (final item in _mapList(source['agents'])) CcbAgent.fromJson(item),
    ];
    final contentItems = _contentItems(source['content']);
    return CcbProjectView(
      project: project,
      namespaceEpoch: _optionalInt(namespace['epoch']),
      tmuxSocketPath: _optionalText(namespace['socket_path']),
      tmuxSessionName: _optionalText(namespace['session_name']),
      activeWindow: _optionalText(namespace['active_window']),
      activePaneId: _optionalText(namespace['active_pane_id']),
      windows: [
        for (final item in _mapList(source['windows']))
          CcbWindow.fromJson(item),
      ],
      agents: agents,
      comms: [
        for (final item in _mapList(source['comms']))
          CcbCommsItem.fromJson(item),
      ],
      contentItems: contentItems,
      notifications: _notifications(
        projectId: project.id,
        agents: agents,
        contentItems: contentItems,
        comms: source['comms'],
      ),
      terminalHistories: _terminalHistories(source['terminal_history']),
    );
  }

  CcbAgent? agentByName(String name) {
    final wanted = name.trim();
    for (final agent in agents) {
      if (agent.name == wanted) {
        return agent;
      }
    }
    return null;
  }

  CcbWindow? windowByName(String name) {
    final wanted = name.trim();
    for (final window in windows) {
      if (window.name == wanted) {
        return window;
      }
    }
    return null;
  }

  List<CcbContentItem> contentForAgent(String name) {
    return [
      for (final item in contentItems)
        if (item.belongsToAgent(name)) item,
    ];
  }

  ReadableTerminalHistory? terminalHistoryForAgent(String name) {
    return terminalHistories[name];
  }

  CcbTerminalTarget terminalTargetForAgent(
    String name, {
    Set<CcbScope> scopes = const {CcbScope.view, CcbScope.terminalInput},
  }) {
    final agent = agentByName(name);
    if (agent == null) {
      throw ArgumentError.value(name, 'name', 'unknown CCB agent');
    }
    final epoch = namespaceEpoch;
    if (epoch == null) {
      throw StateError('ProjectView namespace epoch is required');
    }
    return CcbTerminalTarget.agent(
      projectId: project.id,
      namespaceEpoch: epoch,
      agent: agent.name,
      window: agent.window,
      paneId: agent.paneId,
      tmuxSocketPath: tmuxSocketPath,
      tmuxSessionName: tmuxSessionName,
      scopes: scopes,
    );
  }

  CcbTerminalTarget terminalTargetForWindow(
    String name, {
    Set<CcbScope> scopes = const {CcbScope.view, CcbScope.terminalInput},
  }) {
    final window = windowByName(name);
    if (window == null) {
      throw ArgumentError.value(name, 'name', 'unknown CCB window');
    }
    final epoch = namespaceEpoch;
    if (epoch == null) {
      throw StateError('ProjectView namespace epoch is required');
    }
    return CcbTerminalTarget.windowActivePane(
      projectId: project.id,
      namespaceEpoch: epoch,
      window: window.name,
      paneId: activeWindow == window.name ? activePaneId : null,
      tmuxSocketPath: tmuxSocketPath,
      tmuxSessionName: tmuxSessionName,
      scopes: scopes,
    );
  }
}

class CcbCommsItem {
  const CcbCommsItem({
    required this.id,
    required this.status,
    required this.businessStatus,
    required this.statusLabel,
    this.executionPhase,
    this.executionPhaseReason,
  });

  final String id;
  final String status;
  final String businessStatus;
  final String statusLabel;
  final String? executionPhase;
  final String? executionPhaseReason;

  String get displayPhase =>
      executionPhase ??
      _firstText(<String?>[statusLabel, businessStatus, status]) ??
      'unknown';

  factory CcbCommsItem.fromJson(Map<String, Object?> json) {
    return CcbCommsItem(
      id: _text(json['id'], fallback: 'comms-item'),
      status: _text(json['status']),
      businessStatus: _text(json['business_status']),
      statusLabel: _text(json['status_label']),
      executionPhase: _optionalText(json['execution_phase']),
      executionPhaseReason: _optionalText(json['execution_phase_reason']),
    );
  }
}

Map<String, Object?> _map(Object? value) {
  if (value is Map) {
    return {
      for (final entry in value.entries) entry.key.toString(): entry.value,
    };
  }
  return const {};
}

List<Map<String, Object?>> _mapList(Object? value) {
  if (value is Iterable) {
    return [for (final item in value) _map(item)];
  }
  return const [];
}

List<CcbContentItem> _contentItems(Object? value) {
  final content = _map(value);
  return [
    for (final item in _mapList(content['items']))
      CcbContentItem.fromJson(item),
  ];
}

Map<String, ReadableTerminalHistory> _terminalHistories(Object? value) {
  final terminalHistory = _map(value);
  final byAgent = _map(terminalHistory['by_agent']);
  return {
    for (final entry in byAgent.entries)
      entry.key: ReadableTerminalHistory.fromJson(
        agentName: entry.key,
        json: _map(entry.value),
      ),
  };
}

List<CcbNotification> _notifications({
  required String projectId,
  required List<CcbAgent> agents,
  required List<CcbContentItem> contentItems,
  required Object? comms,
}) {
  return [
    for (final agent in agents)
      ..._notificationsForAgent(
        projectId: projectId,
        agent: agent,
        contentItems: contentItems,
      ),
    ..._notificationsFromComms(projectId: projectId, comms: comms),
  ];
}

List<CcbNotification> _notificationsForAgent({
  required String projectId,
  required CcbAgent agent,
  required List<CcbContentItem> contentItems,
}) {
  final state = _normalized(agent.activityState);
  final matchingContent = [
    for (final item in contentItems)
      if (item.belongsToAgent(agent.name)) item,
  ];
  final contentId = matchingContent.isEmpty ? null : matchingContent.first.id;
  final baseTarget = CcbNotificationTarget(
    projectId: projectId,
    agentName: agent.name,
    windowName: agent.window,
    contentId: contentId,
  );
  final notifications = <CcbNotification>[];
  if (state == 'completed' || state == 'complete' || state == 'done') {
    notifications.add(
      CcbNotification(
        id: 'agent-${agent.name}-completed',
        kind: CcbNotificationKind.taskCompleted,
        severity: CcbNotificationSeverity.info,
        title: '${agent.name} completed',
        body: 'Task completed for ${agent.name}.',
        target: baseTarget,
      ),
    );
  } else if (state == 'failed' ||
      state == 'incomplete' ||
      state == 'cancelled') {
    notifications.add(
      CcbNotification(
        id: 'agent-${agent.name}-failed',
        kind: CcbNotificationKind.taskFailed,
        severity: CcbNotificationSeverity.critical,
        title: '${agent.name} failed',
        body: 'Task needs review before continuing.',
        target: baseTarget,
      ),
    );
  } else if (state == 'blocked') {
    notifications.add(
      CcbNotification(
        id: 'agent-${agent.name}-blocked',
        kind: CcbNotificationKind.taskBlocked,
        severity: CcbNotificationSeverity.warning,
        title: '${agent.name} is blocked',
        body: 'Agent is waiting on a blocker.',
        target: baseTarget,
      ),
    );
  } else if (state == 'callback' ||
      state == 'callback_needed' ||
      state == 'waiting') {
    notifications.add(
      CcbNotification(
        id: 'agent-${agent.name}-callback',
        kind: CcbNotificationKind.callbackWaiting,
        severity: CcbNotificationSeverity.warning,
        title: '${agent.name} needs callback',
        body: 'Callback or user input is waiting.',
        target: baseTarget,
      ),
    );
  }

  final health = _normalized(agent.runtimeHealth);
  if (health == 'unhealthy' ||
      health == 'missing' ||
      health == 'offline' ||
      health == 'degraded') {
    notifications.add(
      CcbNotification(
        id: 'agent-${agent.name}-health',
        kind: CcbNotificationKind.agentUnhealthy,
        severity:
            health == 'degraded'
                ? CcbNotificationSeverity.warning
                : CcbNotificationSeverity.critical,
        title: '${agent.name} health: $health',
        body: 'Agent runtime health needs attention.',
        target: baseTarget,
      ),
    );
  }
  return notifications;
}

List<CcbNotification> _notificationsFromComms({
  required String projectId,
  required Object? comms,
}) {
  final commsMap = _map(comms);
  return [
    for (final item in _mapList(commsMap['items']))
      if (_isAttentionComms(item))
        CcbNotification(
          id: 'comms-${_text(item['id'], fallback: 'mention')}',
          kind: CcbNotificationKind.commsMention,
          severity: CcbNotificationSeverity.warning,
          title: _text(item['title'], fallback: 'Comms mention'),
          body: _text(
            item['preview'] ?? item['body'] ?? item['text'],
            fallback: 'Comms item needs attention.',
          ),
          target: CcbNotificationTarget(
            projectId: projectId,
            agentName:
                _optionalText(item['agent']) ??
                _optionalText(item['agent_name']),
            windowName: _optionalText(item['window']),
            commsId: _optionalText(item['id']),
          ),
        ),
  ];
}

bool _isAttentionComms(Map<String, Object?> item) {
  final kind = _normalized(item['kind']);
  return item['mention'] == true ||
      item['requires_attention'] == true ||
      kind == 'mention' ||
      kind == 'callback';
}

String _normalized(Object? value) =>
    (value ?? '').toString().trim().toLowerCase();

String? _optionalText(Object? value) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? null : text;
}

int? _optionalInt(Object? value) => int.tryParse((value ?? '').toString());

String? _firstText(Iterable<String?> values) {
  for (final value in values) {
    final text = (value ?? '').trim();
    if (text.isNotEmpty) return text;
  }
  return null;
}

String _text(Object? value, {String fallback = ''}) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? fallback : text;
}
