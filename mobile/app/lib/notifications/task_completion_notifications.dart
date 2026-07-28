import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import '../pairing/gateway_pairing.dart';

const taskCompletionNotificationChannelId = 'ccb_task_completion';
const defaultGatewayTaskCompletionNotificationStreamPath =
    '/v1/mobile/notifications';
const taskCompletionMissingNotifyScopeMessage =
    'Re-pair gateway to enable task completion notifications';

class GatewayInvalidationWatch {
  const GatewayInvalidationWatch({
    required this.projectId,
    required this.agent,
    this.namespaceEpoch,
    this.provider,
  });

  final String projectId;
  final String agent;
  final int? namespaceEpoch;
  final String? provider;

  Map<String, String> get queryParameters => {
    'watch_project_id': projectId,
    'watch_agent': agent,
    if (namespaceEpoch != null) 'watch_namespace_epoch': '$namespaceEpoch',
    if (provider != null && provider!.trim().isNotEmpty)
      'watch_provider': provider!,
  };

  @override
  bool operator ==(Object other) =>
      other is GatewayInvalidationWatch &&
      projectId == other.projectId &&
      agent == other.agent &&
      namespaceEpoch == other.namespaceEpoch &&
      provider == other.provider;

  @override
  int get hashCode => Object.hash(projectId, agent, namespaceEpoch, provider);
}

class TaskCompletionNotificationEvent {
  const TaskCompletionNotificationEvent({
    required this.id,
    required this.kind,
    required this.projectId,
    required this.projectShortName,
    required this.agent,
    required this.completedAt,
    required this.dedupeKey,
    this.namespaceEpoch,
    this.scope,
    this.activityState,
  });

  static const taskCompletedKind = 'task_completed';
  static const projectSummaryChangedKind = 'project_summary_changed';
  static const agentActivityChangedKind = 'agent_activity_changed';
  static const conversationChangedKind = 'conversation_changed';
  static const resyncRequiredKind = 'resync_required';

  final String id;
  final String kind;
  final String projectId;
  final String projectShortName;
  final String agent;
  final DateTime completedAt;
  final String dedupeKey;
  final int? namespaceEpoch;
  final String? scope;
  final String? activityState;

  bool get isTaskCompleted => kind == taskCompletedKind;

  bool get isInvalidation => switch (kind) {
    projectSummaryChangedKind ||
    agentActivityChangedKind ||
    conversationChangedKind => true,
    resyncRequiredKind => true,
    _ => false,
  };

  bool get isResyncRequired => kind == resyncRequiredKind;

  int get notificationId => stableTaskCompletionNotificationId(dedupeKey);

  String get title => 'CCB Mobile';

  String get body => '$projectShortName / $agent 任务完成';

  TaskCompletionNotificationTap get tap {
    return TaskCompletionNotificationTap(projectId: projectId, agent: agent);
  }

  factory TaskCompletionNotificationEvent.fromJson(Map<String, Object?> json) {
    return TaskCompletionNotificationEvent(
      id: _requiredText(json['id'], 'id'),
      kind: _requiredText(json['kind'], 'kind'),
      projectId: _requiredText(json['project_id'], 'project_id'),
      projectShortName: _requiredText(
        json['project_short_name'],
        'project_short_name',
      ),
      agent: _optionalText(json['agent']) ?? '',
      completedAt: _requiredDateTime(json['completed_at'], 'completed_at'),
      dedupeKey: _requiredText(json['dedupe_key'], 'dedupe_key'),
      namespaceEpoch: _optionalInt(json['namespace_epoch']),
      scope: _optionalText(json['scope']),
      activityState: _optionalText(json['activity_state']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'id': id,
      'kind': kind,
      'project_id': projectId,
      'project_short_name': projectShortName,
      'agent': agent,
      'completed_at': completedAt.toUtc().toIso8601String(),
      'dedupe_key': dedupeKey,
      if (namespaceEpoch != null) 'namespace_epoch': namespaceEpoch,
      if (scope != null) 'scope': scope,
      if (activityState != null) 'activity_state': activityState,
    };
  }
}

class GatewayInvalidationCursorStore {
  GatewayInvalidationCursorStore({
    GatewaySecureStore? secureStore,
    String keyPrefix = _defaultKeyPrefix,
  }) : _secureStore = secureStore ?? FlutterGatewaySecureStore(),
       _keyPrefix = keyPrefix;

  static const _defaultKeyPrefix = 'ccb_mobile.invalidation.last_event_id';
  final GatewaySecureStore _secureStore;
  final String _keyPrefix;

  String _key(GatewayPairedHost host) =>
      '$_keyPrefix.${host.profile.hostId}.${host.profile.deviceId}';

  Future<String?> read(GatewayPairedHost host) async {
    try {
      final value = await _secureStore.read(key: _key(host));
      return value == null || value.trim().isEmpty ? null : value.trim();
    } catch (_) {
      return null;
    }
  }

  Future<void> write(GatewayPairedHost host, String eventId) async {
    final id = eventId.trim();
    if (id.isEmpty) return;
    try {
      await _secureStore.write(key: _key(host), value: id);
    } catch (_) {
      return;
    }
  }

  Future<void> clear(GatewayPairedHost host) async {
    try {
      await _secureStore.delete(key: _key(host));
    } catch (_) {
      return;
    }
  }
}

class TaskCompletionNotificationTap {
  const TaskCompletionNotificationTap({
    required this.projectId,
    required this.agent,
  });

  final String projectId;
  final String agent;

  factory TaskCompletionNotificationTap.fromJson(Map<String, Object?> json) {
    return TaskCompletionNotificationTap(
      projectId: _requiredText(json['project_id'], 'project_id'),
      agent: _requiredText(json['agent'], 'agent'),
    );
  }

  Map<String, Object?> toJson() {
    return {'project_id': projectId, 'agent': agent};
  }
}

int stableTaskCompletionNotificationId(String dedupeKey) {
  var hash = 0x811c9dc5;
  for (final byte in utf8.encode(dedupeKey)) {
    hash ^= byte;
    hash = (hash * 0x01000193) & 0xffffffff;
  }
  return hash >= 0x80000000 ? hash - 0x100000000 : hash;
}

class TaskCompletionSeenDedupeStore {
  TaskCompletionSeenDedupeStore({
    GatewaySecureStore? secureStore,
    int maxKeys = 256,
    String key = _defaultKey,
  }) : _secureStore = secureStore ?? FlutterGatewaySecureStore(),
       _maxKeys = maxKeys < 1 ? 1 : maxKeys,
       _key = key;

  static const _defaultKey = 'ccb_mobile.task_completion.seen_dedupe_keys';

  final GatewaySecureStore _secureStore;
  final int _maxKeys;
  final String _key;

  Future<bool> markSeenIfNew(String dedupeKey) async {
    final keys = await readSeenKeys();
    if (keys.contains(dedupeKey)) {
      return false;
    }
    final next = [...keys, dedupeKey];
    final bounded =
        next.length <= _maxKeys ? next : next.sublist(next.length - _maxKeys);
    await _secureStore.write(key: _key, value: jsonEncode(bounded));
    return true;
  }

  Future<List<String>> readSeenKeys() async {
    final raw = await _secureStore.read(key: _key);
    if (raw == null || raw.trim().isEmpty) {
      return [];
    }
    final Object? decoded;
    try {
      decoded = jsonDecode(raw);
    } on FormatException {
      return [];
    }
    if (decoded is Iterable) {
      return [for (final item in decoded) item.toString()];
    }
    return [];
  }
}

class TaskCompletionUnreadItem {
  const TaskCompletionUnreadItem({
    required this.projectId,
    required this.projectShortName,
    required this.agent,
    required this.completedAt,
    required this.dedupeKey,
  });

  final String projectId;
  final String projectShortName;
  final String agent;
  final DateTime completedAt;
  final String dedupeKey;

  factory TaskCompletionUnreadItem.fromEvent(
    TaskCompletionNotificationEvent event,
  ) {
    return TaskCompletionUnreadItem(
      projectId: event.projectId,
      projectShortName: event.projectShortName,
      agent: event.agent,
      completedAt: event.completedAt,
      dedupeKey: event.dedupeKey,
    );
  }

  factory TaskCompletionUnreadItem.fromJson(Map<String, Object?> json) {
    return TaskCompletionUnreadItem(
      projectId: _requiredText(json['project_id'], 'project_id'),
      projectShortName: _requiredText(
        json['project_short_name'],
        'project_short_name',
      ),
      agent: _requiredText(json['agent'], 'agent'),
      completedAt: _requiredDateTime(json['completed_at'], 'completed_at'),
      dedupeKey: _requiredText(json['dedupe_key'], 'dedupe_key'),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'project_id': projectId,
      'project_short_name': projectShortName,
      'agent': agent,
      'completed_at': completedAt.toUtc().toIso8601String(),
      'dedupe_key': dedupeKey,
    };
  }
}

class TaskCompletionUnreadStore {
  TaskCompletionUnreadStore({
    GatewaySecureStore? secureStore,
    int maxItems = 256,
    String key = _defaultKey,
  }) : _secureStore = secureStore ?? FlutterGatewaySecureStore(),
       _maxItems = maxItems < 1 ? 1 : maxItems,
       _key = key;

  static const _defaultKey = 'ccb_mobile.task_completion.unread_items';

  final GatewaySecureStore _secureStore;
  final int _maxItems;
  final String _key;

  Future<List<TaskCompletionUnreadItem>> addIfNew(
    TaskCompletionNotificationEvent event,
  ) async {
    final items = await readUnreadItems();
    if (items.any((item) => item.dedupeKey == event.dedupeKey)) {
      return items;
    }
    final next = [...items, TaskCompletionUnreadItem.fromEvent(event)];
    final bounded =
        next.length <= _maxItems ? next : next.sublist(next.length - _maxItems);
    await _writeItems(bounded);
    return bounded;
  }

  Future<List<TaskCompletionUnreadItem>> clearAgent({
    required String projectId,
    required String agent,
  }) async {
    final wantedProject = projectId.trim();
    final wantedAgent = agent.trim();
    final next = [
      for (final item in await readUnreadItems())
        if (item.projectId != wantedProject || item.agent != wantedAgent) item,
    ];
    await _writeItems(next);
    return next;
  }

  Future<List<TaskCompletionUnreadItem>> readUnreadItems() async {
    final String? raw;
    try {
      raw = await _secureStore.read(key: _key);
    } on MissingPluginException {
      return [];
    } on PlatformException {
      return [];
    }
    if (raw == null || raw.trim().isEmpty) {
      return [];
    }
    final decoded = jsonDecode(raw);
    if (decoded is! Iterable) {
      return [];
    }
    final items = <TaskCompletionUnreadItem>[];
    for (final item in decoded) {
      if (item is! Map) {
        continue;
      }
      try {
        items.add(
          TaskCompletionUnreadItem.fromJson({
            for (final entry in item.entries) entry.key.toString(): entry.value,
          }),
        );
      } on FormatException {
        continue;
      }
    }
    return items;
  }

  Future<void> _writeItems(List<TaskCompletionUnreadItem> items) async {
    try {
      await _secureStore.write(
        key: _key,
        value: jsonEncode([for (final item in items) item.toJson()]),
      );
    } on MissingPluginException {
      return;
    } on PlatformException {
      return;
    }
  }
}

enum TaskCompletionLocalNotificationPermissionStatus {
  granted,
  denied,
  unsupported,
}

abstract interface class TaskCompletionLocalNotifications {
  Stream<TaskCompletionNotificationTap> get taps;

  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded();

  Future<bool> showTaskCompletion(TaskCompletionNotificationEvent event);
}

class MethodChannelTaskCompletionLocalNotifications
    implements TaskCompletionLocalNotifications {
  MethodChannelTaskCompletionLocalNotifications({
    MethodChannel channel = const MethodChannel(
      'io.ccb.mobile/local_notifications',
    ),
  }) : _channel = channel {
    _channel.setMethodCallHandler(_handleMethodCall);
    unawaited(_registerNotificationTapHandler());
  }

  final MethodChannel _channel;
  final _taps = StreamController<TaskCompletionNotificationTap>.broadcast();

  @override
  Stream<TaskCompletionNotificationTap> get taps => _taps.stream;

  @override
  Future<TaskCompletionLocalNotificationPermissionStatus>
  requestPermissionIfNeeded() async {
    try {
      final granted = await _channel.invokeMethod<bool>(
        'requestPostNotificationsPermission',
      );
      return granted == true
          ? TaskCompletionLocalNotificationPermissionStatus.granted
          : TaskCompletionLocalNotificationPermissionStatus.denied;
    } on MissingPluginException {
      return TaskCompletionLocalNotificationPermissionStatus.unsupported;
    } on PlatformException {
      return TaskCompletionLocalNotificationPermissionStatus.denied;
    }
  }

  @override
  Future<bool> showTaskCompletion(TaskCompletionNotificationEvent event) async {
    try {
      return await _channel.invokeMethod<bool>('showTaskCompletion', {
            'channel_id': taskCompletionNotificationChannelId,
            'notification_id': event.notificationId,
            'title': event.title,
            'body': event.body,
            'payload': jsonEncode(event.tap.toJson()),
          }) ??
          false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  Future<void> dispose() async {
    await _taps.close();
  }

  Future<void> _registerNotificationTapHandler() async {
    try {
      await _channel.invokeMethod<bool>('registerNotificationTapHandler');
    } on MissingPluginException {
      // The web/desktop test fallback has no Android local notification plugin.
    } on PlatformException {
      // Notification taps are best effort; event delivery still works on Android.
    }
  }

  Future<void> _handleMethodCall(MethodCall call) async {
    if (call.method != 'notificationTap') {
      return;
    }
    final payload = call.arguments;
    if (payload is! String || payload.trim().isEmpty) {
      return;
    }
    final decoded = jsonDecode(payload);
    if (decoded is Map) {
      _taps.add(
        TaskCompletionNotificationTap.fromJson({
          for (final entry in decoded.entries)
            entry.key.toString(): entry.value,
        }),
      );
    }
  }
}

abstract interface class GatewayTaskCompletionNotificationStreamClient {
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]);
}

class HttpGatewayTaskCompletionNotificationStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  HttpGatewayTaskCompletionNotificationStreamClient({
    HttpClient? httpClient,
    this.streamPath = defaultGatewayTaskCompletionNotificationStreamPath,
    this.timeout = const Duration(seconds: 10),
  }) : _sharedHttpClient = httpClient;

  final HttpClient? _sharedHttpClient;
  final Set<HttpClient> _activeHttpClients = <HttpClient>{};
  final String streamPath;
  final Duration timeout;

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    late final StreamController<TaskCompletionNotificationEvent> controller;
    StreamSubscription<TaskCompletionNotificationEvent>? eventSubscription;
    HttpClientRequest? request;
    HttpClient? httpClient;
    var canceled = false;

    void releaseOwnedClient() {
      final client = httpClient;
      if (_sharedHttpClient == null &&
          client != null &&
          _activeHttpClients.remove(client)) {
        client.close(force: true);
      }
    }

    Future<void> cancel() async {
      canceled = true;
      request?.abort();
      releaseOwnedClient();
      final subscription = eventSubscription;
      eventSubscription = null;
      await subscription?.cancel();
      // Cancellation closes the owned socket synchronously, but the peer
      // observes that close on its next I/O turn. Keep replacement streams
      // serialized across that short transport handoff as well.
      await Future<void>.delayed(const Duration(milliseconds: 25));
    }

    Future<void> connect() async {
      final client = _sharedHttpClient ?? HttpClient();
      httpClient = client;
      if (_sharedHttpClient == null) {
        _activeHttpClients.add(client);
      }
      final base = host.profile.routeProvider.gatewayUrl.resolve(streamPath);
      final uri = base.replace(
        queryParameters: {...base.queryParameters, ...?watch?.queryParameters},
      );
      try {
        request = await client.getUrl(uri).timeout(timeout);
        if (canceled) {
          request?.abort();
          releaseOwnedClient();
          return;
        }
        request!.headers.set(
          HttpHeaders.acceptHeader,
          'application/x-ndjson, text/event-stream, application/json',
        );
        request!.headers.set(
          HttpHeaders.authorizationHeader,
          'Bearer ${host.deviceToken}',
        );
        if (lastEventId != null && lastEventId.trim().isNotEmpty) {
          request!.headers.set('Last-Event-ID', lastEventId.trim());
        }
        final response = await request!.close().timeout(timeout);
        if (canceled) {
          releaseOwnedClient();
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          final body = await utf8
              .decodeStream(response)
              .timeout(timeout)
              .catchError((_) => '');
          throw GatewayTaskCompletionNotificationStreamException(
            uri,
            response.statusCode,
            body,
          );
        }
        eventSubscription = _eventsFromSseLines(
          response.transform(utf8.decoder).transform(const LineSplitter()),
        ).listen(
          controller.add,
          onError: controller.addError,
          onDone: () {
            releaseOwnedClient();
            unawaited(controller.close());
          },
        );
        onConnected?.call();
      } catch (error, stackTrace) {
        releaseOwnedClient();
        if (!canceled) {
          controller.addError(error, stackTrace);
          await controller.close();
        }
      }
    }

    controller = StreamController<TaskCompletionNotificationEvent>(
      onListen: () => unawaited(connect()),
      onPause: () => eventSubscription?.pause(),
      onResume: () => eventSubscription?.resume(),
      onCancel: cancel,
    );
    return controller.stream;
  }

  void close({bool force = false}) {
    _sharedHttpClient?.close(force: force);
    for (final client in _activeHttpClients.toList(growable: false)) {
      client.close(force: force);
    }
    _activeHttpClients.clear();
  }
}

class GatewayTaskCompletionNotificationStreamException implements Exception {
  const GatewayTaskCompletionNotificationStreamException(
    this.uri,
    this.statusCode,
    this.message,
  );

  final Uri uri;
  final int statusCode;
  final String message;

  @override
  String toString() {
    return 'GatewayTaskCompletionNotificationStreamException'
        '($statusCode $uri: $message)';
  }
}

enum TaskCompletionNotificationSubscriptionStatus {
  subscribed,
  missingNotifyScope,
  permissionDenied,
}

enum GatewayInvalidationConnectionState { connected, reconnecting, stopped }

typedef TaskCompletionNotificationEventHandler =
    FutureOr<void> Function(TaskCompletionNotificationEvent event);

typedef TaskCompletionNotificationPredicate =
    bool Function(TaskCompletionNotificationEvent event);
typedef GatewayInvalidationConnectionStateHandler =
    void Function(GatewayInvalidationConnectionState state, Duration? retryIn);
typedef GatewayInvalidationStreamErrorHandler = void Function(Object error);

class TaskCompletionNotificationController {
  TaskCompletionNotificationController({
    required GatewayTaskCompletionNotificationStreamClient streamClient,
    required TaskCompletionLocalNotifications localNotifications,
    required TaskCompletionSeenDedupeStore seenStore,
    GatewayInvalidationCursorStore? cursorStore,
    required void Function(TaskCompletionNotificationTap tap) onTap,
    TaskCompletionNotificationEventHandler? onLiveEvent,
    TaskCompletionNotificationEventHandler? onInvalidationEvent,
    TaskCompletionNotificationPredicate? shouldShowNotification,
    GatewayInvalidationConnectionStateHandler? onConnectionStateChanged,
    GatewayInvalidationStreamErrorHandler? onStreamError,
    DateTime Function()? clock,
    Duration initialReconnectDelay = const Duration(seconds: 1),
    Duration maxReconnectDelay = const Duration(seconds: 30),
    int maxSeenEventIds = 256,
  }) : _streamClient = streamClient,
       _localNotifications = localNotifications,
       _seenStore = seenStore,
       _cursorStore = cursorStore ?? GatewayInvalidationCursorStore(),
       _onLiveEvent = onLiveEvent,
       _onInvalidationEvent = onInvalidationEvent,
       _shouldShowNotification = shouldShowNotification,
       _onConnectionStateChanged = onConnectionStateChanged,
       _onStreamError = onStreamError,
       _clock = clock ?? DateTime.now,
       _initialReconnectDelay = initialReconnectDelay,
       _maxReconnectDelay = maxReconnectDelay,
       _maxSeenEventIds = maxSeenEventIds < 1 ? 1 : maxSeenEventIds {
    _tapSubscription = _localNotifications.taps.listen(onTap);
  }

  final GatewayTaskCompletionNotificationStreamClient _streamClient;
  final TaskCompletionLocalNotifications _localNotifications;
  final TaskCompletionSeenDedupeStore _seenStore;
  final GatewayInvalidationCursorStore _cursorStore;
  final TaskCompletionNotificationEventHandler? _onLiveEvent;
  final TaskCompletionNotificationEventHandler? _onInvalidationEvent;
  final TaskCompletionNotificationPredicate? _shouldShowNotification;
  final GatewayInvalidationConnectionStateHandler? _onConnectionStateChanged;
  final GatewayInvalidationStreamErrorHandler? _onStreamError;
  final DateTime Function() _clock;
  final Duration _initialReconnectDelay;
  final Duration _maxReconnectDelay;
  final int _maxSeenEventIds;
  StreamSubscription<TaskCompletionNotificationEvent>? _eventSubscription;
  late final StreamSubscription<TaskCompletionNotificationTap> _tapSubscription;
  TaskCompletionLocalNotificationPermissionStatus? _permissionStatus;
  GatewayPairedHost? _activeHost;
  GatewayInvalidationWatch? _watch;
  String? _lastConfirmedEventId;
  DateTime? _liveBaselineCompletedAt;
  Timer? _reconnectTimer;
  late Duration _nextReconnectDelay = _initialReconnectDelay;
  bool _started = false;
  int _reconnectAttempt = 0;
  int _lifecycleGeneration = 0;
  int _desiredSubscriptionGeneration = 0;
  Future<void>? _subscriptionReconcileFuture;
  bool _subscriptionReconcileRequested = false;
  bool _subscriptionDesiredConnected = false;
  bool _startInitializing = false;
  GatewayInvalidationConnectionState? _connectionState;
  final LinkedHashSet<String> _seenEventIds = LinkedHashSet<String>();
  Future<void> _eventHandlingTail = Future<void>.value();

  Future<TaskCompletionNotificationSubscriptionStatus> start(
    GatewayPairedHost host, [
    GatewayInvalidationWatch? watch,
  ]) async {
    final generation = ++_lifecycleGeneration;
    await _stopCurrentSubscription();
    if (generation != _lifecycleGeneration) {
      return TaskCompletionNotificationSubscriptionStatus.subscribed;
    }
    if (!host.profile.scopes.contains('notify')) {
      return TaskCompletionNotificationSubscriptionStatus.missingNotifyScope;
    }
    _started = true;
    _startInitializing = true;
    _subscriptionDesiredConnected = false;
    _activeHost = host;
    _watch = watch;
    // Secure storage is normally immediate. Keep subscription recovery
    // non-blocking when a platform plugin is unavailable/misconfigured; a
    // later reconnect still carries the persisted cursor once available.
    _lastConfirmedEventId = await _cursorStore
        .read(host)
        .timeout(const Duration(milliseconds: 100), onTimeout: () => null);
    if (generation != _lifecycleGeneration) {
      return TaskCompletionNotificationSubscriptionStatus.subscribed;
    }
    _liveBaselineCompletedAt = _clock().toUtc();
    _nextReconnectDelay = _initialReconnectDelay;
    _reconnectAttempt = 0;
    _permissionStatus = await _localNotifications.requestPermissionIfNeeded();
    if (generation != _lifecycleGeneration) {
      return TaskCompletionNotificationSubscriptionStatus.subscribed;
    }
    _startInitializing = false;
    _subscriptionDesiredConnected = true;
    await _requestSubscriptionReconcile();
    return _permissionStatus ==
            TaskCompletionLocalNotificationPermissionStatus.granted
        ? TaskCompletionNotificationSubscriptionStatus.subscribed
        : TaskCompletionNotificationSubscriptionStatus.permissionDenied;
  }

  void updateWatch(GatewayInvalidationWatch? watch) {
    if (!_started || _watch == watch) {
      return;
    }
    _watch = watch;
    if (_startInitializing) {
      return;
    }
    retryNow();
  }

  Future<void> stop() async {
    _lifecycleGeneration += 1;
    await _stopCurrentSubscription();
  }

  Future<void> _stopCurrentSubscription() async {
    _setStoppedDesiredState();
    await _requestSubscriptionReconcile();
  }

  void _setStoppedDesiredState() {
    _started = false;
    _startInitializing = false;
    _subscriptionDesiredConnected = false;
    _activeHost = null;
    _watch = null;
    _lastConfirmedEventId = null;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _seenEventIds.clear();
    _emitConnectionState(GatewayInvalidationConnectionState.stopped, null);
  }

  Future<void> dispose() async {
    await stop();
    await _tapSubscription.cancel();
  }

  Future<void> _requestSubscriptionReconcile() {
    _desiredSubscriptionGeneration += 1;
    _subscriptionReconcileRequested = true;
    final running = _subscriptionReconcileFuture;
    if (running != null) {
      return running;
    }
    final completer = Completer<void>();
    _subscriptionReconcileFuture = completer.future;
    unawaited(_drainSubscriptionReconcile(completer));
    return completer.future;
  }

  Future<void> _drainSubscriptionReconcile(Completer<void> completer) async {
    try {
      while (_subscriptionReconcileRequested) {
        _subscriptionReconcileRequested = false;
        final desiredGeneration = _desiredSubscriptionGeneration;
        final previousSubscription = _eventSubscription;
        _eventSubscription = null;
        if (previousSubscription != null) {
          await previousSubscription.cancel();
        }
        if (_subscriptionReconcileRequested) {
          continue;
        }
        if (_isCurrentDesiredSubscription(desiredGeneration)) {
          _connect(desiredGeneration);
        }
      }
      _subscriptionReconcileFuture = null;
      completer.complete();
    } catch (error, stackTrace) {
      _subscriptionReconcileFuture = null;
      completer.completeError(error, stackTrace);
    }
  }

  bool _isCurrentDesiredSubscription(int desiredGeneration) {
    return _started &&
        _subscriptionDesiredConnected &&
        desiredGeneration == _desiredSubscriptionGeneration;
  }

  void _connect(int desiredGeneration) {
    final host = _activeHost;
    if (host == null || !_isCurrentDesiredSubscription(desiredGeneration)) {
      return;
    }
    var terminalStreamError = false;
    try {
      _eventSubscription = _streamClient
          .subscribe(host, _lastConfirmedEventId, _watch, () {
            if (!_isCurrentConnection(host, desiredGeneration)) {
              return;
            }
            _nextReconnectDelay = _initialReconnectDelay;
            _reconnectAttempt = 0;
            _emitConnectionState(
              GatewayInvalidationConnectionState.connected,
              null,
            );
          })
          .listen(
            _enqueueEvent,
            onError: (Object error, StackTrace _) {
              if (!_isCurrentConnection(host, desiredGeneration)) {
                return;
              }
              _onStreamError?.call(error);
              terminalStreamError =
                  error is GatewayTaskCompletionNotificationStreamException &&
                  error.statusCode >= 400 &&
                  error.statusCode < 500;
              if (!terminalStreamError) {
                _scheduleReconnect(host, desiredGeneration);
              }
            },
            onDone: () {
              if (_isCurrentConnection(host, desiredGeneration) &&
                  !terminalStreamError) {
                _scheduleReconnect(host, desiredGeneration);
              }
            },
          );
    } catch (_) {
      _scheduleReconnect(host, desiredGeneration);
    }
  }

  void _scheduleReconnect(GatewayPairedHost host, int desiredGeneration) {
    if (!_isCurrentConnection(host, desiredGeneration) ||
        _reconnectTimer != null) {
      return;
    }
    _subscriptionDesiredConnected = false;
    unawaited(_requestSubscriptionReconcile());
    final reconnectGeneration = _desiredSubscriptionGeneration;
    final delay = _nextReconnectDelay;
    _nextReconnectDelay = _nextDelayAfter(delay);
    _reconnectAttempt += 1;
    _emitConnectionState(
      GatewayInvalidationConnectionState.reconnecting,
      delay,
    );
    _reconnectTimer = Timer(delay, () {
      if (!_isCurrentHost(host) ||
          _subscriptionDesiredConnected ||
          reconnectGeneration != _desiredSubscriptionGeneration) {
        return;
      }
      _reconnectTimer = null;
      _subscriptionDesiredConnected = true;
      unawaited(_requestSubscriptionReconcile());
    });
  }

  Duration _nextDelayAfter(Duration current) {
    if (_maxReconnectDelay <= Duration.zero) {
      return Duration.zero;
    }
    final doubled = current * 2;
    final capped = doubled > _maxReconnectDelay ? _maxReconnectDelay : doubled;
    // A small deterministic jitter avoids a fleet of clients repeatedly
    // reconnecting in lockstep while retaining reproducible focused tests.
    final direction = (_reconnectAttempt % 3) - 1;
    final millis = capped.inMilliseconds;
    final jittered = millis + (millis * direction ~/ 10);
    return Duration(
      milliseconds:
          jittered.clamp(1, _maxReconnectDelay.inMilliseconds).toInt(),
    );
  }

  void retryNow() {
    if (!_started || _startInitializing) {
      return;
    }
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _nextReconnectDelay = _initialReconnectDelay;
    _reconnectAttempt = 0;
    _subscriptionDesiredConnected = true;
    unawaited(_requestSubscriptionReconcile());
  }

  /// Reconnects the existing cursor-based stream without starting any
  /// background transport. Callers may await the subscription handoff before
  /// selecting a notification target.
  Future<void> catchUpNow() {
    if (!_started || _startInitializing) {
      return Future<void>.value();
    }
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _nextReconnectDelay = _initialReconnectDelay;
    _reconnectAttempt = 0;
    _subscriptionDesiredConnected = true;
    return _requestSubscriptionReconcile();
  }

  Future<void> _handleEvent(TaskCompletionNotificationEvent event) async {
    final hostAtStart = _activeHost;
    if (!_started || hostAtStart == null) {
      return;
    }
    if (!_rememberEventId(event.id)) {
      return;
    }
    _nextReconnectDelay = _initialReconnectDelay;
    _reconnectAttempt = 0;
    _emitConnectionState(GatewayInvalidationConnectionState.connected, null);
    final retainedBaseline = _isBaselineEvent(event) && !event.isResyncRequired;
    if (!retainedBaseline) {
      await _onInvalidationEvent?.call(event);
    }
    if (!_isCurrentHost(hostAtStart)) {
      return;
    }
    _lastConfirmedEventId = event.id;
    await _cursorStore.write(hostAtStart, event.id);
    if (retainedBaseline) {
      if (event.isTaskCompleted) {
        await _seenStore.markSeenIfNew(event.dedupeKey);
      }
      return;
    }
    if (!event.isTaskCompleted) {
      return;
    }
    final fresh = await _seenStore.markSeenIfNew(event.dedupeKey);
    if (!fresh) {
      return;
    }
    if (!_isCurrentHost(hostAtStart)) {
      return;
    }
    await _onLiveEvent?.call(event);
    if (!_isCurrentHost(hostAtStart)) {
      return;
    }
    if (_permissionStatus !=
            TaskCompletionLocalNotificationPermissionStatus.granted ||
        _shouldShowNotification?.call(event) == false) {
      return;
    }
    await _localNotifications.showTaskCompletion(event);
  }

  bool _isBaselineEvent(TaskCompletionNotificationEvent event) {
    final baseline = _liveBaselineCompletedAt;
    return baseline != null && !event.completedAt.isAfter(baseline);
  }

  bool _rememberEventId(String value) {
    final id = value.trim();
    if (id.isEmpty || !_seenEventIds.add(id)) {
      return false;
    }
    while (_seenEventIds.length > _maxSeenEventIds) {
      _seenEventIds.remove(_seenEventIds.first);
    }
    return true;
  }

  bool _isCurrentHost(GatewayPairedHost host) =>
      _started && identical(_activeHost, host);

  bool _isCurrentConnection(GatewayPairedHost host, int generation) =>
      _isCurrentHost(host) && generation == _desiredSubscriptionGeneration;

  void _enqueueEvent(TaskCompletionNotificationEvent event) {
    _eventHandlingTail = _eventHandlingTail
        .catchError((_) {})
        .then((_) => _handleEvent(event))
        .catchError((Object error, StackTrace stackTrace) {
          _onStreamError?.call(error);
        });
  }

  void _emitConnectionState(
    GatewayInvalidationConnectionState state,
    Duration? retryIn,
  ) {
    // Connected is an edge for consumers that use it to verify core routes.
    // Events arriving on an established SSE connection are not reconnections.
    if (state == GatewayInvalidationConnectionState.connected &&
        _connectionState == state) {
      return;
    }
    _connectionState = state;
    _onConnectionStateChanged?.call(state, retryIn);
  }
}

Stream<TaskCompletionNotificationEvent> _eventsFromSseLines(
  Stream<String> lines,
) async* {
  String? eventId;
  final dataLines = <String>[];
  await for (final line in lines) {
    if (line.isEmpty) {
      final event = _eventFromSsePayload(
        dataLines.join('\n'),
        eventId: eventId,
      );
      if (event != null) yield event;
      eventId = null;
      dataLines.clear();
      continue;
    }
    if (line.startsWith(':')) continue;
    if (line.startsWith('id:')) {
      eventId = line.substring(3).trim();
    } else if (line.startsWith('data:')) {
      dataLines.add(line.substring(5).trimLeft());
    } else if (!line.startsWith('event:') && !line.startsWith('retry:')) {
      // Keep NDJSON compatibility for older gateways and focused fakes.
      final event = _eventFromSsePayload(line.trim());
      if (event != null) yield event;
    }
  }
  final event = _eventFromSsePayload(dataLines.join('\n'), eventId: eventId);
  if (event != null) yield event;
}

TaskCompletionNotificationEvent? _eventFromSsePayload(
  String payload, {
  String? eventId,
}) {
  final trimmed = payload.trim();
  if (trimmed.isEmpty || trimmed == '[DONE]') return null;
  final decoded = jsonDecode(trimmed);
  if (decoded is! Map) {
    throw const FormatException(
      'notification stream event is not a JSON object',
    );
  }
  final normalized = {
    for (final entry in decoded.entries) entry.key.toString(): entry.value,
    if ((decoded['id'] ?? '').toString().trim().isEmpty && eventId != null)
      'id': eventId,
  };
  return TaskCompletionNotificationEvent.fromJson(normalized);
}

String _requiredText(Object? value, String field) {
  final text = (value ?? '').toString().trim();
  if (text.isEmpty) {
    throw FormatException('notification payload missing text field: $field');
  }
  return text;
}

DateTime _requiredDateTime(Object? value, String field) {
  final parsed = DateTime.tryParse((value ?? '').toString());
  if (parsed == null) {
    throw FormatException(
      'notification payload missing datetime field: $field',
    );
  }
  return parsed.toUtc();
}

int? _optionalInt(Object? value) => int.tryParse((value ?? '').toString());

String? _optionalText(Object? value) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? null : text;
}
