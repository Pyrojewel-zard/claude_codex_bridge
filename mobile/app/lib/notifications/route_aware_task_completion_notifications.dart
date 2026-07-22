import 'dart:async';

import '../pairing/gateway_pairing.dart';
import '../transport/relay_socket_gateway_transport.dart';
import '../transport/route_provider.dart';
import 'task_completion_notifications.dart';

class RouteAwareGatewayTaskCompletionNotificationStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  RouteAwareGatewayTaskCompletionNotificationStreamClient({
    HttpGatewayTaskCompletionNotificationStreamClient? httpClient,
  }) : _httpClient =
           httpClient ?? HttpGatewayTaskCompletionNotificationStreamClient();

  final HttpGatewayTaskCompletionNotificationStreamClient _httpClient;

  @override
  Stream<TaskCompletionNotificationEvent> subscribe(
    GatewayPairedHost host, [
    String? lastEventId,
    GatewayInvalidationWatch? watch,
    void Function()? onConnected,
  ]) {
    if (host.profile.routeProvider.kind != RouteProviderKind.relay) {
      return _httpClient.subscribe(host, lastEventId, watch, onConnected);
    }

    late final StreamController<TaskCompletionNotificationEvent> controller;
    RelaySocketGatewayTransport? transport;
    StreamSubscription<TaskCompletionNotificationEvent>? subscription;
    var canceled = false;

    Future<void> cancel() async {
      canceled = true;
      await subscription?.cancel();
      subscription = null;
      await transport?.close(force: true);
      transport = null;
    }

    Future<void> connect() async {
      final relay = RelaySocketGatewayTransport(
        profile: host.profile,
        deviceToken: host.deviceToken,
      );
      transport = relay;
      try {
        subscription = relay
            .notificationEvents(
              lastEventId: lastEventId,
              watchQuery: watch?.queryParameters ?? const {},
              onConnected: onConnected,
            )
            .map(_taskCompletionEvent)
            .listen(
              controller.add,
              onError: controller.addError,
              onDone: () async {
                await relay.close(force: true);
                if (!controller.isClosed) {
                  await controller.close();
                }
              },
            );
      } catch (error, stackTrace) {
        await relay.close(force: true);
        if (!canceled && !controller.isClosed) {
          controller.addError(error, stackTrace);
          await controller.close();
        }
      }
    }

    controller = StreamController<TaskCompletionNotificationEvent>(
      onListen: () => unawaited(connect()),
      onPause: () => subscription?.pause(),
      onResume: () => subscription?.resume(),
      onCancel: cancel,
    );
    return controller.stream;
  }

  void close({bool force = false}) => _httpClient.close(force: force);
}

TaskCompletionNotificationEvent _taskCompletionEvent(
  Map<String, Object?> event,
) {
  final dataValue = event['data'];
  if (dataValue is! Map) {
    throw const FormatException('relay notification event data is missing');
  }
  final normalized = <String, Object?>{
    for (final entry in dataValue.entries) entry.key.toString(): entry.value,
  };
  final eventId = (event['id'] ?? '').toString().trim();
  final eventKind = (event['event'] ?? '').toString().trim();
  if (eventId.isNotEmpty &&
      !normalized.containsKey('event_id') &&
      !normalized.containsKey('id')) {
    normalized['event_id'] = eventId;
  }
  if (eventKind.isNotEmpty && !normalized.containsKey('kind')) {
    normalized['kind'] = eventKind;
  }
  return TaskCompletionNotificationEvent.fromJson(normalized);
}
