import '../app/app_factories.dart';
import '../pairing/gateway_pairing.dart';
import '../transport/relay_socket_gateway_transport.dart';
import '../transport/route_provider.dart';
import 'task_completion_notifications.dart';

typedef GatewayTransportForNotificationHost =
    RelaySocketGatewayTransport Function(GatewayPairedHost host);

class RouteAwareGatewayTaskCompletionNotificationStreamClient
    implements GatewayTaskCompletionNotificationStreamClient {
  RouteAwareGatewayTaskCompletionNotificationStreamClient({
    HttpGatewayTaskCompletionNotificationStreamClient? httpClient,
    GatewayTransportForNotificationHost? relayTransportForHost,
  }) : _httpClient =
           httpClient ?? HttpGatewayTaskCompletionNotificationStreamClient(),
       _relayTransportForHost =
           relayTransportForHost ??
           ((host) {
             final transport = defaultGatewayTransportFor(host);
             if (transport is! RelaySocketGatewayTransport) {
               throw StateError('relay notification route is unavailable');
             }
             return transport;
           });

  final HttpGatewayTaskCompletionNotificationStreamClient _httpClient;
  final GatewayTransportForNotificationHost _relayTransportForHost;

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
    return _relayTransportForHost(host)
        .notificationEvents(
          lastEventId: lastEventId,
          watchQuery: watch?.queryParameters ?? const {},
          onConnected: onConnected,
        )
        .map(_taskCompletionEvent);
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
