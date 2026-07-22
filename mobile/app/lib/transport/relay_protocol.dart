import 'dart:convert';

import 'relay_crypto.dart';
import 'relay_gateway_transport.dart';

enum RelayFrameKind {
  clientHello('client_hello'),
  hostHello('host_hello'),
  gatewayEnvelope('gateway_envelope'),
  ack('ack'),
  close('close');

  const RelayFrameKind(this.wireName);

  final String wireName;

  static RelayFrameKind fromWireName(String value) {
    final normalized = value.trim();
    for (final kind in values) {
      if (kind.wireName == normalized) {
        return kind;
      }
    }
    throw FormatException('unknown relay frame kind: $value');
  }
}

class RelayFrame {
  RelayFrame({
    required this.sessionId,
    required this.sequence,
    required this.kind,
    Map<String, Object?> payload = const {},
    this.schemaVersion = relayProtocolVersion,
  }) : payload = Map.unmodifiable(_map(payload, 'payload')) {
    _validateFrame(
      schemaVersion: schemaVersion,
      sessionId: sessionId,
      sequence: sequence,
      kind: kind,
      payload: this.payload,
    );
  }

  final int schemaVersion;
  final String sessionId;
  final int sequence;
  final RelayFrameKind kind;
  final Map<String, Object?> payload;

  factory RelayFrame.clientHello({
    required String sessionId,
    required int sequence,
    required String hostId,
    required String deviceId,
    required String clientPublicKeyB64,
    Set<int> supportedVersions = const {relayProtocolVersion},
  }) {
    return RelayFrame(
      sessionId: sessionId,
      sequence: sequence,
      kind: RelayFrameKind.clientHello,
      payload: {
        'host_id': hostId,
        'device_id': deviceId,
        'client_pubkey_b64': clientPublicKeyB64,
        'supported_versions': _sortedPositiveInts(
          supportedVersions,
          'supported_versions',
        ),
      },
    );
  }

  factory RelayFrame.hostHello({
    required String sessionId,
    required int sequence,
    required String hostId,
    required String serverFingerprint,
    required String hostPublicKeyB64,
    int acceptedVersion = relayProtocolVersion,
  }) {
    return RelayFrame(
      sessionId: sessionId,
      sequence: sequence,
      kind: RelayFrameKind.hostHello,
      payload: {
        'host_id': hostId,
        'server_fingerprint': serverFingerprint,
        'host_pubkey_b64': hostPublicKeyB64,
        'accepted_version': acceptedVersion,
      },
    );
  }

  factory RelayFrame.gatewayEnvelope({
    required RelayGatewayEnvelope envelope,
    int? sequence,
  }) {
    return RelayFrame(
      sessionId: envelope.sessionId,
      sequence: sequence ?? envelope.sequence,
      kind: RelayFrameKind.gatewayEnvelope,
      payload: {'envelope': envelope.toJson()},
    );
  }

  factory RelayFrame.fromJson(Map<String, Object?> json) {
    return RelayFrame(
      schemaVersion: _int(
        json['schema_version'],
        fallback: relayProtocolVersion,
      ),
      sessionId: _requiredText(json['session_id'], 'session_id'),
      sequence: _requiredPositiveInt(json['seq'], 'seq'),
      kind: RelayFrameKind.fromWireName(_requiredText(json['kind'], 'kind')),
      payload: _map(json['payload'], 'payload'),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'schema_version': schemaVersion,
      'session_id': sessionId,
      'seq': sequence,
      'kind': kind.wireName,
      'payload': payload,
    };
  }

  RelayGatewayEnvelope gatewayEnvelope() {
    if (kind != RelayFrameKind.gatewayEnvelope) {
      throw StateError('relay frame is not a gateway envelope');
    }
    return RelayGatewayEnvelope.fromJson(_map(payload['envelope'], 'envelope'));
  }
}

class RelayHandshakeTranscript {
  RelayHandshakeTranscript._({
    required this.sessionId,
    required this.hostId,
    required this.deviceId,
    required this.protocolVersion,
    required this.clientPublicKeyB64,
    required this.hostPublicKeyB64,
    required this.serverFingerprint,
  });

  final String sessionId;
  final String hostId;
  final String deviceId;
  final int protocolVersion;
  final String clientPublicKeyB64;
  final String hostPublicKeyB64;
  final String serverFingerprint;

  bool get ready => true;

  factory RelayHandshakeTranscript.negotiate({
    required RelayFrame clientHello,
    required RelayFrame hostHello,
  }) {
    if (clientHello.kind != RelayFrameKind.clientHello) {
      throw const FormatException(
        'relay handshake must start with client_hello',
      );
    }
    if (hostHello.kind != RelayFrameKind.hostHello) {
      throw const FormatException('relay handshake requires host_hello');
    }
    if (clientHello.sessionId != hostHello.sessionId) {
      throw const FormatException('relay handshake session mismatch');
    }
    final clientHostId = _requiredText(
      clientHello.payload['host_id'],
      'client_hello.host_id',
    );
    final hostId = _requiredText(
      hostHello.payload['host_id'],
      'host_hello.host_id',
    );
    if (clientHostId != hostId) {
      throw const FormatException('relay handshake host mismatch');
    }
    final supportedVersions = _positiveIntList(
      clientHello.payload['supported_versions'],
      'client_hello.supported_versions',
    );
    final acceptedVersion = _requiredPositiveInt(
      hostHello.payload['accepted_version'],
      'host_hello.accepted_version',
    );
    if (!supportedVersions.contains(relayProtocolVersion) ||
        acceptedVersion != relayProtocolVersion) {
      throw const FormatException('relay handshake downgrade rejected');
    }
    final clientPublicKeyB64 = _requiredBase64Text(
      clientHello.payload['client_pubkey_b64'],
      'client_hello.client_pubkey_b64',
    );
    final hostPublicKeyB64 = _requiredBase64Text(
      hostHello.payload['host_pubkey_b64'],
      'host_hello.host_pubkey_b64',
    );
    return RelayHandshakeTranscript._(
      sessionId: clientHello.sessionId,
      hostId: hostId,
      deviceId: _requiredText(
        clientHello.payload['device_id'],
        'client_hello.device_id',
      ),
      protocolVersion: acceptedVersion,
      clientPublicKeyB64: clientPublicKeyB64,
      hostPublicKeyB64: hostPublicKeyB64,
      serverFingerprint: _requiredText(
        hostHello.payload['server_fingerprint'],
        'host_hello.server_fingerprint',
      ),
    );
  }
}

class RelayHostRegistration {
  RelayHostRegistration({
    required this.hostId,
    required this.serverFingerprint,
    required this.hostPublicKeyB64,
    this.schemaVersion = relayProtocolVersion,
    Set<String> capabilities = const {},
    Map<String, String> diagnostics = const {},
  }) : capabilities = Set.unmodifiable(_stringSet(capabilities)),
       diagnostics = Map.unmodifiable(_stringMap(diagnostics)) {
    _requiredText(hostId, 'host_id');
    _requiredText(serverFingerprint, 'server_fingerprint');
    _requiredBase64Text(hostPublicKeyB64, 'host_pubkey_b64');
    if (schemaVersion != relayProtocolVersion) {
      throw const FormatException(
        'relay host registration requires v2 schema_version',
      );
    }
  }

  final int schemaVersion;
  final String hostId;
  final String serverFingerprint;
  final String hostPublicKeyB64;
  final Set<String> capabilities;
  final Map<String, String> diagnostics;

  factory RelayHostRegistration.fromJson(Map<String, Object?> json) {
    final type = _optionalText(json['type']);
    if (type != null && type != 'relay_host_registration') {
      throw FormatException('unknown relay host registration type: $type');
    }
    _rejectProhibitedCleartextKeys(json, 'relay_host_registration');
    return RelayHostRegistration(
      schemaVersion: _int(
        json['schema_version'],
        fallback: relayProtocolVersion,
      ),
      hostId: _requiredText(json['host_id'], 'host_id'),
      serverFingerprint: _requiredText(
        json['server_fingerprint'],
        'server_fingerprint',
      ),
      hostPublicKeyB64: _requiredBase64Text(
        json['host_pubkey_b64'],
        'host_pubkey_b64',
      ),
      capabilities: _stringSetFromObject(json['capabilities']),
      diagnostics: _stringMapFromObject(json['diagnostics']),
    );
  }

  Map<String, Object?> toJson() {
    return {
      'schema_version': schemaVersion,
      'type': 'relay_host_registration',
      'host_id': hostId,
      'server_fingerprint': serverFingerprint,
      'host_pubkey_b64': hostPublicKeyB64,
      'capabilities': capabilities.toList()..sort(),
      if (diagnostics.isNotEmpty) 'diagnostics': Map.of(diagnostics),
    };
  }
}

void _validateFrame({
  required int schemaVersion,
  required String sessionId,
  required int sequence,
  required RelayFrameKind kind,
  required Map<String, Object?> payload,
}) {
  if (schemaVersion != relayProtocolVersion) {
    throw const FormatException('relay frame requires v2 schema_version');
  }
  _requiredText(sessionId, 'session_id');
  if (sequence < 1) {
    throw const FormatException('relay frame seq must be positive');
  }
  _rejectProhibitedCleartextKeys(payload, '${kind.wireName}.payload');
  switch (kind) {
    case RelayFrameKind.clientHello:
      _requiredText(payload['host_id'], 'client_hello.host_id');
      _requiredText(payload['device_id'], 'client_hello.device_id');
      _requiredBase64Text(
        payload['client_pubkey_b64'],
        'client_hello.client_pubkey_b64',
      );
      final supportedVersions = _positiveIntList(
        payload['supported_versions'],
        'client_hello.supported_versions',
      );
      if (!supportedVersions.contains(relayProtocolVersion)) {
        throw const FormatException(
          'client_hello.supported_versions must include relay v2',
        );
      }
    case RelayFrameKind.hostHello:
      _requiredText(payload['host_id'], 'host_hello.host_id');
      _requiredText(
        payload['server_fingerprint'],
        'host_hello.server_fingerprint',
      );
      _requiredBase64Text(
        payload['host_pubkey_b64'],
        'host_hello.host_pubkey_b64',
      );
      final acceptedVersion = _requiredPositiveInt(
        payload['accepted_version'],
        'host_hello.accepted_version',
      );
      if (acceptedVersion != relayProtocolVersion) {
        throw const FormatException('relay host_hello downgrade rejected');
      }
    case RelayFrameKind.gatewayEnvelope:
      final envelope = RelayGatewayEnvelope.fromJson(
        _map(payload['envelope'], 'envelope'),
      );
      if (envelope.sessionId != sessionId) {
        throw const FormatException('relay gateway envelope session mismatch');
      }
    case RelayFrameKind.ack:
      if (payload.containsKey('ack_seq')) {
        _requiredPositiveInt(payload['ack_seq'], 'ack.ack_seq');
      }
    case RelayFrameKind.close:
      if (payload.containsKey('reason')) {
        _requiredText(payload['reason'], 'close.reason');
      }
  }
}

void _rejectProhibitedCleartextKeys(Object? value, String path) {
  if (value is Map) {
    for (final entry in value.entries) {
      final key = entry.key.toString();
      if (_prohibitedCleartextKeys.contains(key)) {
        throw FormatException(
          'relay cleartext field is prohibited: $path.$key',
        );
      }
      _rejectProhibitedCleartextKeys(entry.value, '$path.$key');
    }
  } else if (value is Iterable && value is! String) {
    var index = 0;
    for (final item in value) {
      _rejectProhibitedCleartextKeys(item, '$path[$index]');
      index += 1;
    }
  }
}

const _prohibitedCleartextKeys = relayProhibitedPlaintextFields;

Map<String, Object?> _map(Object? value, String name) {
  if (value is Map) {
    return {
      for (final entry in value.entries) entry.key.toString(): entry.value,
    };
  }
  if (value == null) {
    return const {};
  }
  throw FormatException('relay field must be an object: $name');
}

String _requiredText(Object? value, String name) {
  final text = _optionalText(value);
  if (!_hasText(text)) {
    throw FormatException('relay field is required: $name');
  }
  return text!;
}

String? _optionalText(Object? value) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? null : text;
}

String _requiredBase64Text(Object? value, String name) {
  final text = _requiredText(value, name);
  try {
    // Relay wire values are unpadded base64url to avoid transport-dependent
    // padding normalization. Dart's decoder expects padding in some builds.
    base64Url.decode(
      text.padRight(text.length + ((4 - text.length % 4) % 4), '='),
    );
  } on FormatException catch (error) {
    throw FormatException('relay field must be base64url: $name', error);
  }
  return text;
}

int _int(Object? value, {required int fallback}) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString()) ?? fallback;
}

int _requiredPositiveInt(Object? value, String name) {
  final parsed = value is int ? value : int.tryParse((value ?? '').toString());
  if (parsed == null || parsed < 1) {
    throw FormatException('relay field must be a positive integer: $name');
  }
  return parsed;
}

List<int> _positiveIntList(Object? value, String name) {
  if (value is! Iterable) {
    throw FormatException('relay field must be an integer list: $name');
  }
  return [for (final item in value) _requiredPositiveInt(item, '$name.item')];
}

List<int> _sortedPositiveInts(Set<int> values, String name) {
  final sorted = values.toList()..sort();
  if (sorted.isEmpty) {
    throw FormatException('relay field must not be empty: $name');
  }
  for (final value in sorted) {
    if (value < 1) {
      throw FormatException(
        'relay field must contain positive integers: $name',
      );
    }
  }
  return sorted;
}

Set<String> _stringSet(Iterable<String> values) {
  return {
    for (final value in values)
      if (_hasText(value)) value.trim(),
  };
}

Set<String> _stringSetFromObject(Object? value) {
  if (value is Iterable) {
    return {
      for (final item in value)
        if (_hasText(item?.toString())) item.toString().trim(),
    };
  }
  return const {};
}

Map<String, String> _stringMap(Map<String, String> values) {
  return {
    for (final entry in values.entries)
      if (_hasText(entry.key) && _hasText(entry.value))
        entry.key.trim(): entry.value.trim(),
  };
}

Map<String, String> _stringMapFromObject(Object? value) {
  final mapped = _map(value, 'diagnostics');
  return {
    for (final entry in mapped.entries)
      if (_hasText(entry.key) && _hasText(entry.value?.toString()))
        entry.key.trim(): entry.value.toString().trim(),
  };
}

bool _hasText(String? value) => value != null && value.trim().isNotEmpty;
