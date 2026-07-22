import 'package:flutter/material.dart';

import '../pairing/gateway_pairing.dart';
import '../pairing/gateway_pairing_scanner_screen.dart';
import '../repository/gateway_mobile_ccb_repository.dart';
import '../repository/mobile_ccb_repository.dart';
import '../transport/gateway_route_diagnostics.dart';
import '../transport/gateway_terminal_transport.dart';
import '../transport/gateway_transport.dart';
import '../transport/http_gateway_transport.dart';
import '../transport/relay_socket_gateway_transport.dart';
import '../transport/route_provider.dart';
import '../transport/terminal_transport.dart';

typedef GatewayPairingClaimAndStore =
    Future<GatewayPairedHost> Function({
      required GatewayPairingPayload pairing,
      required String deviceName,
      required GatewayHostProfileStore store,
      String? deviceId,
    });

typedef GatewayRepositoryFactory =
    MobileCcbRepository Function(GatewayPairedHost host);

typedef GatewayPairingScanner =
    Future<GatewayPairingPayload?> Function(BuildContext context);

typedef GatewayTerminalTransportFactory =
    TerminalTransport Function(GatewayPairedHost host);

typedef GatewayRouteDiagnosticsFactory =
    Future<GatewayRouteDiagnosticReport> Function(GatewayPairedHost host);

Future<GatewayPairedHost> defaultPairingClaimAndStore({
  required GatewayPairingPayload pairing,
  required String deviceName,
  required GatewayHostProfileStore store,
  String? deviceId,
}) async {
  final client = GatewayPairingClient();
  try {
    return client.claimAndStore(
      pairing: pairing,
      deviceName: deviceName,
      store: store,
      deviceId: deviceId,
    );
  } finally {
    client.close(force: true);
  }
}

Future<GatewayPairingPayload?> defaultPairingScanner(BuildContext context) {
  return Navigator.of(context).push<GatewayPairingPayload>(
    MaterialPageRoute(
      builder: (context) => const GatewayPairingScannerScreen(),
    ),
  );
}

MobileCcbRepository defaultGatewayRepositoryFactory(GatewayPairedHost host) {
  return GatewayMobileCcbRepository(
    transport: _gatewayTransportFor(host),
  );
}

TerminalTransport defaultGatewayTerminalTransportFactory(
  GatewayPairedHost host,
) {
  return GatewayTerminalTransport(
    transport: _gatewayTransportFor(host),
  );
}

Future<GatewayRouteDiagnosticReport> defaultGatewayRouteDiagnostics(
  GatewayPairedHost host,
) async {
  final transport = _gatewayTransportFor(host);
  try {
    return await GatewayRouteDiagnostics(
      transport: transport,
    ).check(projectId: host.projectId);
  } finally {
    if (transport is HttpGatewayTransport) {
      transport.close(force: true);
    } else if (transport is RelaySocketGatewayTransport) {
      await transport.close(force: true);
    }
  }
}

GatewayTransport _gatewayTransportFor(GatewayPairedHost host) {
  if (host.profile.routeProvider.kind == RouteProviderKind.relay) {
    return RelaySocketGatewayTransport(
      profile: host.profile,
      deviceToken: host.deviceToken,
    );
  }
  return HttpGatewayTransport(
    profile: host.profile,
    deviceToken: host.deviceToken,
  );
}
