import 'dart:convert';

import 'package:cryptography/cryptography.dart';

const relayProtocolVersion = 2;
const relayProtocolName = 'ccb-relay-v2';
const relayKeyId = 'ccb-relay-v2-session';
final BigInt relayMaxSequence = BigInt.parse('18446744073709551615');
final BigInt _relayMaxDartIntSequence = BigInt.parse('9223372036854775807');

const relayClearEnvelopeFields = {
  'schema_version',
  'session_id',
  'seq',
  'direction',
  'op',
  'nonce_b64',
  'ciphertext_b64',
  'key_id',
};

const relayProhibitedPlaintextFields = {
  'agent',
  'args',
  'authorization',
  'bearer_token',
  'body',
  'command',
  'content',
  'device_token',
  'file',
  'file_content',
  'file_name',
  'gateway_url',
  'message',
  'pairing_code',
  'paste_text',
  'path',
  'payload',
  'project_id',
  'project_name',
  'prompt',
  'reply',
  'route_provider',
  'terminal_id',
  'terminal_token',
  'text',
  'websocket_url',
};

enum RelayCryptoDirection {
  phoneToHost('phone_to_host'),
  hostToPhone('host_to_phone');

  const RelayCryptoDirection(this.wireName);

  final String wireName;

  static RelayCryptoDirection fromWireName(String value) {
    for (final direction in values) {
      if (direction.wireName == value.trim()) {
        return direction;
      }
    }
    throw const FormatException('relay v2 direction invalid');
  }
}

class RelayCryptoException implements Exception {
  const RelayCryptoException(this.message);

  final String message;

  @override
  String toString() => message;
}

class RelayV2Envelope {
  RelayV2Envelope({
    required this.sessionId,
    required this.sequence,
    required this.direction,
    required this.operation,
    required this.nonceB64,
    required this.ciphertextB64,
    this.keyId = relayKeyId,
    this.schemaVersion = relayProtocolVersion,
  }) {
    _validate();
  }

  final int schemaVersion;
  final String sessionId;
  final int sequence;
  final RelayCryptoDirection direction;
  final String operation;
  final String nonceB64;
  final String ciphertextB64;
  final String keyId;

  factory RelayV2Envelope.fromJson(Map<String, Object?> json) {
    final unknown = {
      for (final key in json.keys)
        if (!relayClearEnvelopeFields.contains(key)) key,
    };
    if (unknown.isNotEmpty) {
      throw FormatException(
        'relay v2 envelope contains non-envelope fields: ${unknown.first}',
      );
    }
    return RelayV2Envelope(
      schemaVersion: _int(json['schema_version'], fallback: 0),
      sessionId: _requiredText(json['session_id'], 'session_id'),
      sequence: _requiredSequence(json['seq'], 'seq'),
      direction: RelayCryptoDirection.fromWireName(
        _requiredText(json['direction'], 'direction'),
      ),
      operation: _requiredText(json['op'], 'op'),
      nonceB64: _requiredBase64Text(json['nonce_b64'], 'nonce_b64'),
      ciphertextB64: _requiredBase64Text(
        json['ciphertext_b64'],
        'ciphertext_b64',
      ),
      keyId: _requiredText(json['key_id'], 'key_id'),
    );
  }

  Map<String, Object?> toJson() {
    _validate();
    return {
      'schema_version': schemaVersion,
      'session_id': sessionId,
      'seq': sequence,
      'direction': direction.wireName,
      'op': operation,
      'nonce_b64': nonceB64,
      'ciphertext_b64': ciphertextB64,
      'key_id': keyId,
    };
  }

  void _validate() {
    if (schemaVersion != relayProtocolVersion) {
      throw const FormatException('relay v2 envelope schema_version mismatch');
    }
    _requiredText(sessionId, 'session_id');
    _requiredSequence(sequence, 'seq');
    _requiredText(operation, 'op');
    _requiredBase64Text(nonceB64, 'nonce_b64');
    _requiredBase64Text(ciphertextB64, 'ciphertext_b64');
    if (keyId != relayKeyId) {
      throw const FormatException('relay v2 envelope key_id mismatch');
    }
  }
}

class RelayV2KeySchedule {
  RelayV2KeySchedule._({
    required this.sessionId,
    required this.clientPublicKeyB64,
    required this.hostPublicKeyB64,
    required this.hostFingerprint,
    required this.transcriptHashB64,
    required this.phoneKeyConfirmationB64,
    required this.hostKeyConfirmationB64,
    required List<int> phoneToHostKey,
    required List<int> hostToPhoneKey,
    required List<int> phoneToHostNoncePrefix,
    required List<int> hostToPhoneNoncePrefix,
  }) : _phoneToHostKey = List<int>.of(phoneToHostKey),
       _hostToPhoneKey = List<int>.of(hostToPhoneKey),
       _phoneToHostNoncePrefix = List<int>.of(phoneToHostNoncePrefix),
       _hostToPhoneNoncePrefix = List<int>.of(hostToPhoneNoncePrefix);

  final String sessionId;
  final String clientPublicKeyB64;
  final String hostPublicKeyB64;
  final String hostFingerprint;
  final String transcriptHashB64;
  final String phoneKeyConfirmationB64;
  final String hostKeyConfirmationB64;
  final List<int> _phoneToHostKey;
  final List<int> _hostToPhoneKey;
  final List<int> _phoneToHostNoncePrefix;
  final List<int> _hostToPhoneNoncePrefix;

  static Future<RelayV2KeySchedule> derive({
    required List<int> localPrivateKeyBytes,
    required String peerPublicKeyB64,
    required String role,
    required String sessionId,
    required String clientPublicKeyB64,
    required String hostPublicKeyB64,
    required String expectedHostFingerprint,
  }) async {
    if (role != 'phone' && role != 'host') {
      throw const RelayCryptoException('relay v2 role must be phone or host');
    }
    final observed = await hostFingerprintForPublicKey(hostPublicKeyB64);
    if (observed != expectedHostFingerprint) {
      throw const RelayCryptoException(
        'relay v2 host fingerprint confirmation failed',
      );
    }
    negotiateRelayV2(const [relayProtocolVersion]);
    final x25519 = X25519();
    final keyPair = await x25519.newKeyPairFromSeed(localPrivateKeyBytes);
    final peerPublicKey = SimplePublicKey(
      _b64Decode(peerPublicKeyB64),
      type: KeyPairType.x25519,
    );
    final shared = await x25519.sharedSecretKey(
      keyPair: keyPair,
      remotePublicKey: peerPublicKey,
    );
    final transcript = utf8.encode(
      _transcriptJson(
        sessionId: sessionId,
        clientPublicKeyB64: clientPublicKeyB64,
        hostPublicKeyB64: hostPublicKeyB64,
        hostFingerprint: expectedHostFingerprint,
      ),
    );
    final transcriptHash = (await Sha256().hash(transcript)).bytes;
    final derived = await Hkdf(
      hmac: Hmac.sha256(),
      outputLength: 104,
    ).deriveKey(
      secretKey: SecretKey(await shared.extractBytes()),
      nonce: transcriptHash,
      info: utf8.encode('ccb-relay-v2 key schedule'),
    );
    final bytes = derived.bytes;
    final confirmKey = bytes.sublist(72, 104);
    final phoneConfirmation = await Hmac.sha256().calculateMac([
      ...utf8.encode('phone'),
      ...transcriptHash,
    ], secretKey: SecretKey(confirmKey));
    final hostConfirmation = await Hmac.sha256().calculateMac([
      ...utf8.encode('host'),
      ...transcriptHash,
    ], secretKey: SecretKey(confirmKey));
    return RelayV2KeySchedule._(
      sessionId: sessionId,
      clientPublicKeyB64: clientPublicKeyB64,
      hostPublicKeyB64: hostPublicKeyB64,
      hostFingerprint: expectedHostFingerprint,
      transcriptHashB64: _b64(transcriptHash),
      phoneKeyConfirmationB64: _b64(phoneConfirmation.bytes),
      hostKeyConfirmationB64: _b64(hostConfirmation.bytes),
      phoneToHostKey: bytes.sublist(0, 32),
      hostToPhoneKey: bytes.sublist(32, 64),
      phoneToHostNoncePrefix: bytes.sublist(64, 68),
      hostToPhoneNoncePrefix: bytes.sublist(68, 72),
    );
  }

  Map<String, Object?> toPublicJson() {
    return {
      'protocol': relayProtocolName,
      'schema_version': relayProtocolVersion,
      'session_id': sessionId,
      'client_public_key_b64': clientPublicKeyB64,
      'host_public_key_b64': hostPublicKeyB64,
      'host_fingerprint': hostFingerprint,
      'transcript_hash_b64': transcriptHashB64,
      'key_confirmation': {
        'phone_b64': phoneKeyConfirmationB64,
        'host_b64': hostKeyConfirmationB64,
      },
    };
  }

  RelayCryptoSession session({required String role}) {
    if (role == 'phone') {
      return RelayCryptoSession(
        sessionId: sessionId,
        sendDirection: RelayCryptoDirection.phoneToHost,
        receiveDirection: RelayCryptoDirection.hostToPhone,
        sendKey: _phoneToHostKey,
        receiveKey: _hostToPhoneKey,
        sendNoncePrefix: _phoneToHostNoncePrefix,
        receiveNoncePrefix: _hostToPhoneNoncePrefix,
      );
    }
    if (role == 'host') {
      return RelayCryptoSession(
        sessionId: sessionId,
        sendDirection: RelayCryptoDirection.hostToPhone,
        receiveDirection: RelayCryptoDirection.phoneToHost,
        sendKey: _hostToPhoneKey,
        receiveKey: _phoneToHostKey,
        sendNoncePrefix: _hostToPhoneNoncePrefix,
        receiveNoncePrefix: _phoneToHostNoncePrefix,
      );
    }
    throw const RelayCryptoException('relay v2 role must be phone or host');
  }
}

class RelayCryptoSession {
  RelayCryptoSession({
    required this.sessionId,
    required this.sendDirection,
    required this.receiveDirection,
    required List<int> sendKey,
    required List<int> receiveKey,
    required List<int> sendNoncePrefix,
    required List<int> receiveNoncePrefix,
    Object? initialSendSequence = 1,
    Object? initialReceiveSequence = 1,
  }) : _sendKey = List<int>.of(sendKey),
       _receiveKey = List<int>.of(receiveKey),
       _sendNoncePrefix = List<int>.of(sendNoncePrefix),
       _receiveNoncePrefix = List<int>.of(receiveNoncePrefix),
       _nextSendSequence = _requiredPositiveBigInt(
         initialSendSequence,
         'initial_send_sequence',
       ),
       _nextReceiveSequence = _requiredPositiveBigInt(
         initialReceiveSequence,
         'initial_receive_sequence',
       );

  final String sessionId;
  final RelayCryptoDirection sendDirection;
  final RelayCryptoDirection receiveDirection;
  final List<int> _sendKey;
  final List<int> _receiveKey;
  final List<int> _sendNoncePrefix;
  final List<int> _receiveNoncePrefix;
  BigInt _nextSendSequence;
  BigInt _nextReceiveSequence;
  bool _closed = false;

  bool get closed => _closed;

  Future<RelayV2Envelope> seal({
    required String operation,
    required List<int> plaintext,
  }) async {
    _requireOpen();
    if (_nextSendSequence > relayMaxSequence) {
      close();
      throw const RelayCryptoException('relay v2 sequence exhausted');
    }
    if (_nextSendSequence > _relayMaxDartIntSequence) {
      close();
      throw const RelayCryptoException(
        'relay v2 sequence exceeds Dart int range',
      );
    }
    final sequence = _nextSendSequence.toInt();
    _nextSendSequence += BigInt.one;
    final nonce = _nonce(_sendNoncePrefix, sequence);
    final secretBox = await Chacha20.poly1305Aead().encrypt(
      plaintext,
      secretKey: SecretKey(_sendKey),
      nonce: nonce,
      aad: relayV2Aad(
        sessionId: sessionId,
        sequence: sequence,
        direction: sendDirection,
        operation: operation,
        keyId: relayKeyId,
      ),
    );
    return RelayV2Envelope(
      sessionId: sessionId,
      sequence: sequence,
      direction: sendDirection,
      operation: operation,
      nonceB64: _b64(nonce),
      ciphertextB64: _b64([...secretBox.cipherText, ...secretBox.mac.bytes]),
    );
  }

  Future<List<int>> open(RelayV2Envelope envelope) async {
    _requireOpen();
    if (_nextReceiveSequence > relayMaxSequence) {
      close();
      throw const RelayCryptoException('relay v2 sequence exhausted');
    }
    if (envelope.sessionId != sessionId) {
      throw const RelayCryptoException('relay v2 session mismatch');
    }
    if (envelope.direction != receiveDirection) {
      throw const RelayCryptoException('relay v2 direction mismatch');
    }
    if (BigInt.from(envelope.sequence) != _nextReceiveSequence) {
      throw const RelayCryptoException(
        'relay v2 sequence replay or reorder rejected',
      );
    }
    final nonce = _b64Decode(envelope.nonceB64);
    final expectedNonce = _nonce(_receiveNoncePrefix, envelope.sequence);
    if (!_constantTimeEquals(nonce, expectedNonce)) {
      throw const RelayCryptoException('relay v2 nonce mismatch');
    }
    final combined = _b64Decode(envelope.ciphertextB64);
    if (combined.length < 16) {
      throw const RelayCryptoException(
        'relay v2 ciphertext authentication failed',
      );
    }
    final secretBox = SecretBox(
      combined.sublist(0, combined.length - 16),
      nonce: nonce,
      mac: Mac(combined.sublist(combined.length - 16)),
    );
    try {
      final plaintext = await Chacha20.poly1305Aead().decrypt(
        secretBox,
        secretKey: SecretKey(_receiveKey),
        aad: relayV2Aad(
          sessionId: envelope.sessionId,
          sequence: envelope.sequence,
          direction: envelope.direction,
          operation: envelope.operation,
          keyId: envelope.keyId,
        ),
      );
      _nextReceiveSequence += BigInt.one;
      return plaintext;
    } on SecretBoxAuthenticationError catch (error) {
      throw RelayCryptoException(
        'relay v2 ciphertext authentication failed: $error',
      );
    }
  }

  void close() {
    _wipe(_sendKey);
    _wipe(_receiveKey);
    _closed = true;
  }

  bool keyMaterialErased() {
    return _sendKey.every((value) => value == 0) &&
        _receiveKey.every((value) => value == 0);
  }

  void _requireOpen() {
    if (_closed) {
      throw const RelayCryptoException('relay v2 session is closed');
    }
  }
}

int negotiateRelayV2(Iterable<int> supportedVersions) {
  if (!supportedVersions.contains(relayProtocolVersion)) {
    throw const RelayCryptoException('relay v2 negotiation failed closed');
  }
  return relayProtocolVersion;
}

List<int> relayV2Aad({
  required String sessionId,
  required int sequence,
  required RelayCryptoDirection direction,
  required String operation,
  required String keyId,
}) {
  return utf8.encode(
    '{"direction":${jsonEncode(direction.wireName)}'
    ',"key_id":${jsonEncode(keyId)}'
    ',"op":${jsonEncode(operation)}'
    ',"schema_version":2'
    ',"seq":$sequence'
    ',"session_id":${jsonEncode(sessionId)}}',
  );
}

Future<String> hostFingerprintForPublicKey(String hostPublicKeyB64) async {
  final digest = await Sha256().hash(_b64Decode(hostPublicKeyB64));
  return 'sha256:${_b64(digest.bytes)}';
}

void assertNoProhibitedRelayPlaintext(Object? value, [String path = 'relay']) {
  if (value is Map) {
    for (final entry in value.entries) {
      final key = entry.key.toString();
      if (relayProhibitedPlaintextFields.contains(key)) {
        throw FormatException('relay prohibited plaintext field: $path.$key');
      }
      assertNoProhibitedRelayPlaintext(entry.value, '$path.$key');
    }
  } else if (value is Iterable && value is! String) {
    var index = 0;
    for (final item in value) {
      assertNoProhibitedRelayPlaintext(item, '$path[$index]');
      index += 1;
    }
  }
}

String _transcriptJson({
  required String sessionId,
  required String clientPublicKeyB64,
  required String hostPublicKeyB64,
  required String hostFingerprint,
}) {
  return '{"client_public_key_b64":${jsonEncode(clientPublicKeyB64)}'
      ',"host_fingerprint":${jsonEncode(hostFingerprint)}'
      ',"host_public_key_b64":${jsonEncode(hostPublicKeyB64)}'
      ',"protocol":${jsonEncode(relayProtocolName)}'
      ',"schema_version":2'
      ',"session_id":${jsonEncode(sessionId)}}';
}

List<int> _nonce(List<int> prefix, int sequence) {
  if (prefix.length != 4) {
    throw const RelayCryptoException('relay v2 nonce prefix invalid');
  }
  _requiredSequence(sequence, 'seq');
  final suffix = List<int>.filled(8, 0);
  var value = sequence;
  for (var index = 7; index >= 0; index -= 1) {
    suffix[index] = value & 0xff;
    value = value >> 8;
  }
  return [...prefix, ...suffix];
}

String _requiredText(Object? value, String name) {
  final text = (value ?? '').toString().trim();
  if (text.isEmpty) {
    throw FormatException('relay v2 field is required: $name');
  }
  return text;
}

String _requiredBase64Text(Object? value, String name) {
  final text = _requiredText(value, name);
  _b64Decode(text);
  return text;
}

int _int(Object? value, {required int fallback}) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString()) ?? fallback;
}

int _requiredSequence(Object? value, String name) {
  final parsed = _requiredPositiveBigInt(value, name);
  if (parsed > relayMaxSequence) {
    throw FormatException('relay v2 sequence exceeds uint64: $name');
  }
  if (parsed > _relayMaxDartIntSequence) {
    throw FormatException('relay v2 sequence exceeds Dart int range: $name');
  }
  return parsed.toInt();
}

BigInt _requiredPositiveBigInt(Object? value, String name) {
  BigInt? parsed;
  if (value is BigInt) {
    parsed = value;
  } else if (value is int) {
    parsed = BigInt.from(value);
  } else {
    parsed = BigInt.tryParse((value ?? '').toString());
  }
  if (parsed == null || parsed < BigInt.one) {
    throw FormatException('relay v2 field must be positive integer: $name');
  }
  return parsed;
}

String _b64(List<int> value) {
  return base64UrlEncode(value).replaceAll('=', '');
}

List<int> _b64Decode(String value) {
  final text = value.trim();
  return base64Url.decode(
    text.padRight(text.length + ((4 - text.length % 4) % 4), '='),
  );
}

bool _constantTimeEquals(List<int> left, List<int> right) {
  if (left.length != right.length) {
    return false;
  }
  var diff = 0;
  for (var index = 0; index < left.length; index += 1) {
    diff |= left[index] ^ right[index];
  }
  return diff == 0;
}

void _wipe(List<int> value) {
  for (var index = 0; index < value.length; index += 1) {
    value[index] = 0;
  }
}
