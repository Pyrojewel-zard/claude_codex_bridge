import '../../pairing/gateway_pairing.dart';

String projectHomeGatewayProfileKey(GatewayPairedHost profile) {
  return '${profile.profile.hostId}/${profile.profile.deviceId}';
}

String projectHomeGatewayProfileLabel(GatewayPairedHost profile) {
  final route = profile.profile.routeProvider.kind.wireName;
  final relayMode = profile.profile.routeProvider.relayMode;
  final routeLabel = route == 'relay' && relayMode != null
      ? '$route/${relayMode.wireName}'
      : route;
  return '${profile.profile.hostId} / ${profile.profile.deviceId} / $routeLabel';
}

List<GatewayPairedHost> sortProjectHomeGatewayProfiles(
  Iterable<GatewayPairedHost> profiles,
) {
  return [...profiles]..sort(
    (a, b) => projectHomeGatewayProfileLabel(
      a,
    ).compareTo(projectHomeGatewayProfileLabel(b)),
  );
}

List<GatewayPairedHost> mergeProjectHomeGatewayProfiles(
  Iterable<GatewayPairedHost> profiles,
  GatewayPairedHost paired,
) {
  final key = projectHomeGatewayProfileKey(paired);
  return sortProjectHomeGatewayProfiles([
    for (final profile in profiles)
      if (projectHomeGatewayProfileKey(profile) != key) profile,
    paired,
  ]);
}
