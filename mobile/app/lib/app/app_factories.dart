import 'dart:async';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
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

typedef RelayPairingTransportFactory =
    RelaySocketGatewayTransport Function(GatewayHostProfile profile);

Future<GatewayPairedHost> defaultPairingClaimAndStore({
  required GatewayPairingPayload pairing,
  required String deviceName,
  required GatewayHostProfileStore store,
  String? deviceId,
  RelayPairingTransportFactory? relayTransportFactory,
}) async {
  if (pairing.routeProvider == RouteProviderKind.relay) {
    return _claimRelayPairing(
      pairing: pairing,
      deviceName: deviceName,
      store: store,
      deviceId: deviceId,
      relayTransportFactory: relayTransportFactory,
    );
  }
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

Future<GatewayPairedHost> _claimRelayPairing({
  required GatewayPairingPayload pairing,
  required String deviceName,
  required GatewayHostProfileStore store,
  String? deviceId,
  RelayPairingTransportFactory? relayTransportFactory,
}) async {
  final hostId = pairing.hostId?.trim() ?? '';
  final websocketUrl = pairing.websocketUrl;
  final hostFingerprint = pairing.hostFingerprint?.trim() ?? '';
  final bootstrap = pairing.relayBootstrap;
  if (hostId.isEmpty ||
      websocketUrl == null ||
      hostFingerprint.isEmpty ||
      bootstrap == null) {
    throw const FormatException('relay pairing QR payload is incomplete');
  }
  final bootstrapExpiresAt = pairing.relayBootstrapExpiresAt;
  if (bootstrapExpiresAt != null &&
      !bootstrapExpiresAt.isAfter(DateTime.now().toUtc())) {
    throw const FormatException('relay pairing QR payload has expired');
  }
  final authKeyPair = await Ed25519().newKeyPair();
  final authPrivateKey = await authKeyPair.extractPrivateKeyBytes();
  final authPublicKey = await authKeyPair.extractPublicKey();
  final privateKeyB64 = base64UrlEncode(authPrivateKey).replaceAll('=', '');
  final publicKeyB64 = base64UrlEncode(authPublicKey.bytes).replaceAll('=', '');
  final provisionalDeviceId =
      deviceId?.trim().isNotEmpty == true
          ? deviceId!.trim()
          : 'pairing-${DateTime.now().microsecondsSinceEpoch}';
  final provisionalProfile = GatewayHostProfile(
    hostId: hostId,
    deviceId: provisionalDeviceId,
    routeProvider: RouteProvider(
      kind: RouteProviderKind.relay,
      gatewayUrl: pairing.gatewayUrl,
      websocketUrl: websocketUrl,
      relayMode: pairing.relayMode,
      hostFingerprint: hostFingerprint,
      relayBootstrap: bootstrap,
      capabilities: const {'relay_tunnel'},
    ),
    scopes: pairing.scopes,
  );
  final transport =
      relayTransportFactory?.call(provisionalProfile) ??
      RelaySocketGatewayTransport(profile: provisionalProfile, deviceToken: '');
  try {
    final claim = await transport.claimPairing(
      pairingCode: pairing.pairingCode,
      deviceName: deviceName,
      deviceId: deviceId,
      phoneAuthPublicKeyB64: publicKeyB64,
    );
    final paired = GatewayPairedHost.fromClaimJson(
      claim,
      pairing: pairing,
      relayPhoneAuthPrivateKeyB64: privateKeyB64,
    );
    if (paired.profile.routeProvider.relayAccess == null) {
      throw const FormatException(
        'relay pairing response is missing reconnect credentials',
      );
    }
    await store.save(paired);
    return paired;
  } finally {
    await transport.close(force: true);
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
    transport: defaultGatewayTransportFor(host),
  );
}

TerminalTransport defaultGatewayTerminalTransportFactory(
  GatewayPairedHost host,
) {
  return GatewayTerminalTransport(transport: defaultGatewayTransportFor(host));
}

Future<GatewayRouteDiagnosticReport> defaultGatewayRouteDiagnostics(
  GatewayPairedHost host,
) async {
  final transport = _newGatewayTransport(host);
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

final _defaultGatewayTransportPool = DefaultGatewayTransportPool();

GatewayTransport defaultGatewayTransportFor(GatewayPairedHost host) {
  return _defaultGatewayTransportPool.forHost(host);
}

Future<void> closeDefaultGatewayTransports({bool force = false}) {
  return _defaultGatewayTransportPool.closeAll(force: force);
}

class DefaultGatewayTransportPool {
  final _entries = <String, _GatewayTransportPoolEntry>{};

  GatewayTransport forHost(GatewayPairedHost host) {
    final key = '${host.profile.hostId}\u0000${host.profile.deviceId}';
    final signature = _transportSignature(host);
    final existing = _entries[key];
    if (existing != null && existing.signature == signature) {
      return existing.transport;
    }
    if (existing != null) {
      unawaited(_closeTransport(existing.transport, force: true));
    }
    final transport = _newGatewayTransport(host);
    _entries[key] = _GatewayTransportPoolEntry(
      signature: signature,
      transport: transport,
    );
    return transport;
  }

  Future<void> closeAll({bool force = false}) async {
    final transports = [for (final entry in _entries.values) entry.transport];
    _entries.clear();
    await Future.wait([
      for (final transport in transports)
        _closeTransport(transport, force: force),
    ]);
  }
}

class _GatewayTransportPoolEntry {
  const _GatewayTransportPoolEntry({
    required this.signature,
    required this.transport,
  });

  final int signature;
  final GatewayTransport transport;
}

int _transportSignature(GatewayPairedHost host) {
  final route = host.profile.routeProvider;
  return Object.hashAll([
    host.profile.hostId,
    host.profile.deviceId,
    host.deviceToken,
    route.kind,
    route.gatewayUrl,
    route.websocketUrl,
    route.hostFingerprint,
    route.relayAccess?.accessGrant,
    route.relayAccess?.phoneAuthPrivateKeyB64,
    route.relayBootstrap?.sessionId,
  ]);
}

Future<void> _closeTransport(
  GatewayTransport transport, {
  required bool force,
}) async {
  if (transport is HttpGatewayTransport) {
    transport.close(force: force);
  } else if (transport is RelaySocketGatewayTransport) {
    await transport.close(force: force);
  }
}

GatewayTransport _newGatewayTransport(GatewayPairedHost host) {
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
