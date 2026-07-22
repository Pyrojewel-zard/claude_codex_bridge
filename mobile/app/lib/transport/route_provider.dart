enum RouteProviderKind {
  lan('lan'),
  tailnet('tailnet'),
  cloudflareTunnel('cloudflare_tunnel'),
  relay('relay');

  const RouteProviderKind(this.wireName);

  final String wireName;

  static RouteProviderKind fromWireName(String value) {
    final normalized = value.trim();
    for (final kind in values) {
      if (kind.wireName == normalized) {
        return kind;
      }
    }
    throw ArgumentError.value(value, 'value', 'unknown route provider');
  }
}

class RouteProvider {
  const RouteProvider({
    required this.kind,
    required this.gatewayUrl,
    this.websocketUrl,
    this.hostFingerprint,
    this.relayBootstrap,
    this.capabilities = const {},
    this.diagnostics = const {},
  });

  final RouteProviderKind kind;
  final Uri gatewayUrl;
  final Uri? websocketUrl;
  final String? hostFingerprint;
  final RelayPhoneSessionBootstrap? relayBootstrap;
  final Set<String> capabilities;
  final Map<String, String> diagnostics;

  Map<String, Object?> toPairingJson() {
    return {
      'route_provider': kind.wireName,
      'gateway_url': gatewayUrl.toString(),
      if (websocketUrl != null) 'websocket_url': websocketUrl.toString(),
      if (_hasText(hostFingerprint)) 'server_fingerprint': hostFingerprint,
      if (relayBootstrap != null) ...relayBootstrap!.toJson(),
      'capabilities': capabilities.toList()..sort(),
      if (diagnostics.isNotEmpty) 'diagnostics': Map.of(diagnostics),
    };
  }
}

class RelayPhoneSessionBootstrap {
  const RelayPhoneSessionBootstrap({
    required this.sessionId,
    required this.clientPrivateKeyB64,
    required this.phoneNonceB64,
    required this.rendezvousCapability,
  });

  final String sessionId;
  final String clientPrivateKeyB64;
  final String phoneNonceB64;
  final String rendezvousCapability;

  factory RelayPhoneSessionBootstrap.fromJson(Map<String, Object?> json) {
    final sessionId = _optionalText(json['relay_session_id']);
    final clientPrivateKeyB64 = _optionalText(
      json['relay_client_private_key_b64'],
    );
    final phoneNonceB64 = _optionalText(json['relay_phone_nonce_b64']);
    final rendezvousCapability = _optionalText(
      json['relay_rendezvous_capability'],
    );
    if (!_hasText(sessionId) &&
        !_hasText(clientPrivateKeyB64) &&
        !_hasText(phoneNonceB64) &&
        !_hasText(rendezvousCapability)) {
      throw const FormatException('relay bootstrap is absent');
    }
    if (!_hasText(sessionId) ||
        !_hasText(clientPrivateKeyB64) ||
        !_hasText(phoneNonceB64) ||
        !_hasText(rendezvousCapability)) {
      throw const FormatException('relay bootstrap is incomplete');
    }
    return RelayPhoneSessionBootstrap(
      sessionId: sessionId!,
      clientPrivateKeyB64: clientPrivateKeyB64!,
      phoneNonceB64: phoneNonceB64!,
      rendezvousCapability: rendezvousCapability!,
    );
  }

  static RelayPhoneSessionBootstrap? maybeFromJson(
    Map<String, Object?> json,
  ) {
    try {
      return RelayPhoneSessionBootstrap.fromJson(json);
    } on FormatException catch (error) {
      if (error.message == 'relay bootstrap is absent') {
        return null;
      }
      rethrow;
    }
  }

  Map<String, Object?> toJson() {
    return {
      'relay_session_id': sessionId,
      'relay_client_private_key_b64': clientPrivateKeyB64,
      'relay_phone_nonce_b64': phoneNonceB64,
      'relay_rendezvous_capability': rendezvousCapability,
    };
  }
}

class GatewayHostProfile {
  const GatewayHostProfile({
    required this.hostId,
    required this.deviceId,
    required this.routeProvider,
    required this.scopes,
  });

  final String hostId;
  final String deviceId;
  final RouteProvider routeProvider;
  final Set<String> scopes;

  Map<String, Object?> toJson() {
    return {
      'host_id': hostId,
      'device_id': deviceId,
      'scopes': scopes.toList()..sort(),
      ...routeProvider.toPairingJson(),
    };
  }
}

bool _hasText(String? value) => value != null && value.trim().isNotEmpty;
