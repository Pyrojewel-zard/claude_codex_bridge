import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cryptography/cryptography.dart';

import '../models/ccb_agent_conversation.dart';
import '../models/ccb_project.dart';
import '../models/ccb_project_lifecycle.dart';
import '../models/ccb_project_view.dart';
import '../models/readable_terminal_history.dart';
import 'gateway_transport.dart';
import 'relay_crypto.dart';
import 'relay_gateway_transport.dart';
import 'relay_protocol.dart';
import 'route_provider.dart';

class RelayGatewayException implements Exception {
  const RelayGatewayException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() {
    final status = statusCode == null ? '' : '$statusCode ';
    return 'RelayGatewayException($status$message)';
  }
}

class RelaySocketGatewayTransport implements GatewayTransport {
  RelaySocketGatewayTransport({
    required this.profile,
    required String deviceToken,
    HttpClient? httpClient,
    Duration timeout = const Duration(seconds: 8),
    bool allowInsecureLoopbackForTests = false,
  }) : _deviceToken = deviceToken,
       _httpClient = httpClient ?? HttpClient(),
       _timeout = timeout,
       _allowInsecureLoopbackForTests = allowInsecureLoopbackForTests {
    if (profile.routeProvider.kind != RouteProviderKind.relay) {
      throw ArgumentError.value(
        profile.routeProvider.kind.wireName,
        'profile.routeProvider.kind',
        'RelaySocketGatewayTransport requires a relay profile',
      );
    }
    _validatedRelayOrigin(
      profile.routeProvider.websocketUrl,
      allowInsecureLoopbackForTests: allowInsecureLoopbackForTests,
    );
    if (!_hasText(profile.routeProvider.hostFingerprint)) {
      throw ArgumentError.value(
        profile.routeProvider.hostFingerprint,
        'profile.routeProvider.hostFingerprint',
        'RelaySocketGatewayTransport requires a host fingerprint',
      );
    }
    if (profile.routeProvider.relayBootstrap == null) {
      throw ArgumentError.value(
        null,
        'profile.routeProvider.relayBootstrap',
        'RelaySocketGatewayTransport requires relay bootstrap material',
      );
    }
  }

  @override
  final GatewayHostProfile profile;

  final String _deviceToken;
  final HttpClient _httpClient;
  final Duration _timeout;
  final bool _allowInsecureLoopbackForTests;
  final _serial = _SerialExecutor();

  _RelaySocketSession? _session;
  bool _closed = false;

  @override
  Future<GatewayHealth> health() async {
    final body = await _requestBody('health', const {});
    return GatewayHealth(
      status: _text(body['status'], fallback: 'unknown'),
      serverTime: _dateTime(body['server_time']),
      capabilities: _stringSet(body['capabilities']),
    );
  }

  @override
  Future<GatewayDevice> device() async {
    final body = await _requestBody('device', const {});
    return GatewayDevice.fromJson(_objectMap(body['device'], 'device'));
  }

  @override
  Future<List<CcbProject>> listProjects() async {
    final body = await _requestBody('list_projects', const {});
    final projects = body['projects'];
    if (projects is! Iterable) {
      throw const FormatException('relay projects response missing projects');
    }
    return [
      for (final item in projects)
        if (item is Map)
          CcbProject.fromJson({
            for (final entry in item.entries) entry.key.toString(): entry.value,
          }),
    ];
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) async {
    final body = await _requestBody('get_project_view', {
      'project_id': projectId,
    });
    return CcbProjectView.fromProjectViewPayload(body);
  }

  @override
  Future<CcbProjectView> focusAgent({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
  }) async {
    final body = await _requestBody('focus_agent', {
      'project_id': projectId,
      'agent': agent,
      'namespace_epoch': namespaceEpoch,
    });
    return CcbProjectView.fromProjectViewPayload(body);
  }

  @override
  Future<CcbProjectView> focusWindow({
    required String projectId,
    required String window,
    required int namespaceEpoch,
  }) async {
    final body = await _requestBody('focus_window', {
      'project_id': projectId,
      'window': window,
      'namespace_epoch': namespaceEpoch,
    });
    return CcbProjectView.fromProjectViewPayload(body);
  }

  @override
  Future<ReadableTerminalHistory?> getReadableTerminalHistory({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int maxLines = 200,
  }) async {
    final body = await _requestBody('terminal_history', {
      'project_id': projectId,
      'agent': agent,
      'namespace_epoch': namespaceEpoch,
      'max_lines': maxLines,
    });
    return ReadableTerminalHistory.fromJson(
      agentName: agent,
      json: _objectMap(body['terminal_history'], 'terminal_history'),
    );
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) async {
    final body = await _requestBody('agent_conversation', {
      'project_id': projectId,
      'agent': agent,
      'namespace_epoch': namespaceEpoch,
      'limit': limit,
      if (_hasText(cursor)) 'cursor': cursor,
    });
    return CcbAgentConversation.fromJson(body);
  }

  @override
  Future<CcbAgentMessageSubmitResult> submitAgentMessage(
    CcbAgentMessageSubmitRequest request,
  ) async {
    final body = await _requestBody('submit_agent_message', request.toJson());
    return CcbAgentMessageSubmitResult.fromJson(body);
  }

  @override
  Future<CcbProjectLifecycleResult> requestLifecycle({
    required String projectId,
    required CcbLifecycleAction action,
  }) async {
    final body = await _requestBody('lifecycle', {
      'project_id': projectId,
      'action': action.wireName,
    });
    return CcbProjectLifecycleResult.fromJson(body);
  }

  @override
  Future<GatewayTerminalHandle> openTerminal(
    GatewayTerminalOpenRequest request,
  ) async {
    final body = await _requestBody('open_terminal', request.toJson());
    return _terminalHandle(body);
  }

  @override
  Stream<GatewayTerminalFrame> terminalFrames(
    GatewayTerminalHandle handle, {
    int? resumeCursor,
  }) {
    return Stream.fromFuture(
      _requestBody('terminal_frames', {
        'terminal_id': handle.terminalId,
        'terminal_token': handle.terminalToken,
        'websocket_url': handle.websocketUrl.toString(),
        if (resumeCursor != null) 'resume_cursor': resumeCursor,
      }),
    ).asyncExpand((body) {
      final events = body['events'];
      if (events is! Iterable) {
        throw const FormatException('relay terminal response missing events');
      }
      return Stream<GatewayTerminalFrame>.fromIterable([
        for (final event in events)
          if (event is Map)
            GatewayTerminalFrame.fromJson({
              for (final entry in event.entries)
                entry.key.toString(): entry.value,
            }),
      ]);
    });
  }

  @override
  Future<void> sendTerminalFrame(
    GatewayTerminalHandle handle,
    GatewayTerminalFrame frame,
  ) async {
    await _requestBody('send_terminal_frame', {
      'terminal_id': handle.terminalId,
      'frame': frame.toJson(),
    });
  }

  @override
  Future<GatewayFileUploadResult> uploadFile({
    required String projectId,
    required String agentName,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  }) async {
    final body = await _requestBody('upload_file', {
      'project_id': projectId,
      'agent': agentName,
      'file_name': fileName,
      'mime_type': mimeType,
      'body_b64': base64UrlEncode(bytes).replaceAll('=', ''),
    });
    return GatewayFileUploadResult.fromJson(body);
  }

  @override
  Future<List<int>> downloadFile({
    required String projectId,
    required String agentName,
    required String fileId,
  }) async {
    final response = await _request('download_file', {
      'project_id': projectId,
      'agent': agentName,
      'file_id': fileId,
    });
    final bodyB64 = _requiredText(response['body_b64'], 'body_b64');
    return base64Url.decode(
      bodyB64.padRight(bodyB64.length + ((4 - bodyB64.length % 4) % 4), '='),
    );
  }

  Future<List<Map<String, Object?>>> notificationEvents({
    String? lastEventId,
    bool once = false,
    String? projectId,
    String? agent,
    int? namespaceEpoch,
  }) async {
    final body = await _requestBody('notification_events', {
      if (_hasText(lastEventId)) 'last_event_id': lastEventId,
      if (once) 'once': true,
      if (_hasText(projectId)) 'project_id': projectId,
      if (_hasText(agent)) 'agent': agent,
      if (namespaceEpoch != null) 'namespace_epoch': namespaceEpoch,
    });
    final events = body['events'];
    if (events is! Iterable) {
      throw const FormatException('relay notification response missing events');
    }
    return [
      for (final event in events)
        if (event is Map)
          {for (final entry in event.entries) entry.key.toString(): entry.value},
    ];
  }

  Future<Map<String, Object?>> _requestBody(
    String operation,
    Map<String, Object?> payload,
  ) async {
    final response = await _request(operation, payload);
    return _objectMap(response['body'], 'body');
  }

  Future<Map<String, Object?>> _request(
    String operation,
    Map<String, Object?> payload,
  ) {
    return _serial.run(() => _doRequest(operation, payload));
  }

  Future<Map<String, Object?>> _doRequest(
    String operation,
    Map<String, Object?> payload,
  ) async {
    if (_closed) {
      throw const RelayGatewayException('relay transport is closed');
    }
    late final List<int> plaintext;
    try {
      final session = await _ensureSession();
      final requestPayload = {
        ...payload,
        if (_hasText(_deviceToken)) 'device_token': _deviceToken,
      };
      final envelope = await session.crypto.seal(
        operation: operation,
        plaintext: utf8.encode(jsonEncode(requestPayload)),
      );
      final frame = RelayFrame.gatewayEnvelope(
        envelope: RelayGatewayEnvelope(
          schemaVersion: envelope.schemaVersion,
          sessionId: envelope.sessionId,
          sequence: envelope.sequence,
          operation: envelope.operation,
          direction: envelope.direction,
          ciphertextB64: envelope.ciphertextB64,
          nonceB64: envelope.nonceB64,
          keyId: envelope.keyId,
        ),
        sequence: session.nextOuterSequence,
      );
      session.nextOuterSequence += 1;
      session.socket.add(jsonEncode(frame.toJson()));
      final responseFrame = await _receiveGatewayEnvelope(session);
      final responseEnvelope = responseFrame.gatewayEnvelope();
      plaintext = await session.crypto.open(
        RelayV2Envelope.fromJson({
          ...responseEnvelope.toJson(),
          if (responseEnvelope.direction == null)
            'direction': RelayCryptoDirection.hostToPhone.wireName,
        }),
      );
    } on RelayCryptoException {
      await _failClosed();
      rethrow;
    } on RelayGatewayException {
      await _failClosed();
      rethrow;
    } on WebSocketException {
      await _failClosed();
      rethrow;
    }
    final decoded = jsonDecode(utf8.decode(plaintext));
    if (decoded is! Map) {
      throw const FormatException('relay gateway response is not an object');
    }
    final response = {
      for (final entry in decoded.entries) entry.key.toString(): entry.value,
    };
    if (response['ok'] != true) {
      throw RelayGatewayException(
        _text(response['error'], fallback: 'relay gateway request failed'),
        statusCode: _int(response['status']),
      );
    }
    return response;
  }

  Future<_RelaySocketSession> _ensureSession() async {
    final existing = _session;
    if (existing != null && existing.socket.readyState == WebSocket.open) {
      return existing;
    }
    final route = profile.routeProvider;
    final bootstrap = route.relayBootstrap;
    if (bootstrap == null) {
      throw const RelayGatewayException('relay bootstrap is missing');
    }
    final relayOrigin = _validatedRelayOrigin(
      route.websocketUrl,
      allowInsecureLoopbackForTests: _allowInsecureLoopbackForTests,
    );
    final socket = await WebSocket.connect(
      relayOrigin.resolve('/v2/phone').toString(),
      customClient: _httpClient,
    ).timeout(_timeout);
    final clientPrivateKeyBytes = _b64Decode(bootstrap.clientPrivateKeyB64);
    final clientPublicKeyB64 = await _publicKeyB64(clientPrivateKeyBytes);
    socket.add(
      jsonEncode(
        RelayFrame(
          sessionId: bootstrap.sessionId,
          sequence: 1,
          kind: RelayFrameKind.clientHello,
          payload: {
            'host_id': profile.hostId,
            'device_id': profile.deviceId,
            'client_pubkey_b64': clientPublicKeyB64,
            'phone_nonce_b64': bootstrap.phoneNonceB64,
            'supported_versions': [relayProtocolVersion],
            'rendezvous_capability': bootstrap.rendezvousCapability,
          },
        ).toJson(),
      ),
    );
    final reader = StreamIterator<dynamic>(socket);
    final hostHello = await _receiveFrame(reader);
    if (hostHello.kind != RelayFrameKind.hostHello) {
      throw const RelayGatewayException('relay host hello was not received');
    }
    RelayHandshakeTranscript.negotiate(
      clientHello: RelayFrame(
        sessionId: bootstrap.sessionId,
        sequence: 1,
        kind: RelayFrameKind.clientHello,
        payload: {
          'host_id': profile.hostId,
          'device_id': profile.deviceId,
          'client_pubkey_b64': clientPublicKeyB64,
          'phone_nonce_b64': bootstrap.phoneNonceB64,
          'supported_versions': [relayProtocolVersion],
          'rendezvous_capability': bootstrap.rendezvousCapability,
        },
      ),
      hostHello: hostHello,
    );
    final observedFingerprint = _requiredText(
      hostHello.payload['server_fingerprint'],
      'host_hello.server_fingerprint',
    );
    if (observedFingerprint != route.hostFingerprint) {
      await socket.close();
      throw const RelayGatewayException('relay host fingerprint mismatch');
    }
    final hostPublicKeyB64 = _requiredText(
      hostHello.payload['host_pubkey_b64'],
      'host_hello.host_pubkey_b64',
    );
    final schedule = await RelayV2KeySchedule.derive(
      localPrivateKeyBytes: clientPrivateKeyBytes,
      peerPublicKeyB64: hostPublicKeyB64,
      role: 'phone',
      sessionId: bootstrap.sessionId,
      clientPublicKeyB64: clientPublicKeyB64,
      hostPublicKeyB64: hostPublicKeyB64,
      expectedHostFingerprint: route.hostFingerprint!,
    );
    final session = _RelaySocketSession(
      socket: socket,
      reader: reader,
      crypto: schedule.session(role: 'phone'),
    );
    _session = session;
    return session;
  }

  Future<RelayFrame> _receiveGatewayEnvelope(_RelaySocketSession session) async {
    while (session.socket.readyState == WebSocket.open) {
      final frame = await _receiveFrame(session.reader);
      if (frame.kind == RelayFrameKind.gatewayEnvelope) {
        return frame;
      }
      if (frame.kind == RelayFrameKind.close) {
        throw const RelayGatewayException('relay session closed');
      }
    }
    throw const RelayGatewayException('relay socket disconnected');
  }

  Future<RelayFrame> _receiveFrame(StreamIterator<dynamic> reader) async {
    if (!await reader.moveNext().timeout(_timeout)) {
      throw const RelayGatewayException('relay socket disconnected');
    }
    final message = reader.current;
    final decoded = jsonDecode(switch (message) {
      final String value => value,
      final List<int> value => utf8.decode(value),
      _ => throw const FormatException('relay frame message unsupported'),
    });
    if (decoded is! Map) {
      throw const FormatException('relay frame is not an object');
    }
    final json = {
      for (final entry in decoded.entries) entry.key.toString(): entry.value,
    };
    if (json['kind'] == 'error') {
      final payload = _objectMap(json['payload'], 'payload');
      throw RelayGatewayException(
        _text(payload['code'], fallback: 'relay_rejected'),
      );
    }
    return RelayFrame.fromJson(json);
  }

  Future<void> close({bool force = false}) async {
    _closed = true;
    await _closeSession();
    _httpClient.close(force: force);
  }

  Future<void> _failClosed() async {
    _closed = true;
    await _closeSession();
  }

  Future<void> _closeSession() async {
    final session = _session;
    _session = null;
    session?.crypto.close();
    await session?.reader.cancel();
    await session?.socket.close();
  }
}

class _RelaySocketSession {
  _RelaySocketSession({
    required this.socket,
    required this.reader,
    required this.crypto,
  });

  final WebSocket socket;
  final StreamIterator<dynamic> reader;
  final RelayCryptoSession crypto;
  int nextOuterSequence = 2;
}

class _SerialExecutor {
  Future<void> _tail = Future<void>.value();

  Future<T> run<T>(Future<T> Function() action) async {
    final previous = _tail.catchError((_) {});
    final completer = Completer<void>();
    _tail = previous.then((_) => completer.future);
    await previous;
    try {
      return await action();
    } finally {
      completer.complete();
    }
  }
}

Uri _validatedRelayOrigin(
  Uri? uri, {
  required bool allowInsecureLoopbackForTests,
}) {
  if (uri == null) {
    throw ArgumentError.value(uri, 'websocketUrl', 'relay WSS origin required');
  }
  final loopbackTest =
      allowInsecureLoopbackForTests &&
      uri.scheme == 'ws' &&
      _isLoopbackHost(uri.host);
  if (uri.scheme != 'wss' && !loopbackTest) {
    throw ArgumentError.value(uri, 'websocketUrl', 'relay URL must use WSS');
  }
  if (uri.host.isEmpty || uri.hasQuery || uri.hasFragment) {
    throw ArgumentError.value(
      uri,
      'websocketUrl',
      'relay URL must be an origin',
    );
  }
  if (uri.path.isNotEmpty && uri.path != '/') {
    throw ArgumentError.value(
      uri,
      'websocketUrl',
      'relay URL must be an origin',
    );
  }
  return uri.replace(path: '', query: null, fragment: null);
}

bool _isLoopbackHost(String host) {
  return host == 'localhost' ||
      host == '127.0.0.1' ||
      host == '::1' ||
      host.startsWith('127.');
}

Future<String> _publicKeyB64(List<int> privateKeyBytes) async {
  final keyPair = await X25519().newKeyPairFromSeed(privateKeyBytes);
  final publicKey = await keyPair.extractPublicKey();
  return base64UrlEncode(publicKey.bytes).replaceAll('=', '');
}

List<int> _b64Decode(String value) {
  final text = value.trim();
  return base64Url.decode(
    text.padRight(text.length + ((4 - text.length % 4) % 4), '='),
  );
}

DateTime _dateTime(Object? value) {
  final parsed = DateTime.tryParse((value ?? '').toString());
  return parsed?.toUtc() ?? DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
}

int? _int(Object? value) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString());
}

Set<String> _stringSet(Object? value) {
  if (value is Iterable) {
    return {for (final item in value) item.toString()};
  }
  return const {};
}

String _text(Object? value, {String fallback = ''}) {
  final text = (value ?? '').toString().trim();
  return text.isEmpty ? fallback : text;
}

String _requiredText(Object? value, String name) {
  final text = _text(value);
  if (text.isEmpty) {
    throw FormatException('relay response missing text field: $name');
  }
  return text;
}

bool _hasText(String? value) => value != null && value.trim().isNotEmpty;

Map<String, Object?> _objectMap(Object? value, String name) {
  if (value is Map) {
    return {
      for (final entry in value.entries) entry.key.toString(): entry.value,
    };
  }
  throw FormatException('relay response missing object field: $name');
}

GatewayTerminalHandle _terminalHandle(Map<String, Object?> json) {
  final summary = _objectMap(json['target_summary'], 'target_summary');
  return GatewayTerminalHandle(
    terminalId: _requiredText(json['terminal_id'], 'terminal_id'),
    terminalToken: _requiredText(json['terminal_token'], 'terminal_token'),
    expiresAt: _requiredDateTime(json['expires_at'], 'expires_at'),
    websocketUrl: Uri.parse(_requiredText(json['websocket_url'], 'websocket_url')),
    targetEpoch: _requiredInt(json['target_epoch'], 'target_epoch'),
    targetSummary: GatewayTerminalTargetSummary(
      projectId: _requiredText(
        summary['project_id'],
        'target_summary.project_id',
      ),
      agent: _optionalText(summary['agent']),
      window: _optionalText(summary['window']),
    ),
  );
}

DateTime _requiredDateTime(Object? value, String name) {
  final parsed = DateTime.tryParse((value ?? '').toString());
  if (parsed == null) {
    throw FormatException('relay response missing datetime field: $name');
  }
  return parsed.toUtc();
}

int _requiredInt(Object? value, String name) {
  if (value is int) {
    return value;
  }
  final parsed = int.tryParse((value ?? '').toString());
  if (parsed == null) {
    throw FormatException('relay response missing int field: $name');
  }
  return parsed;
}

String? _optionalText(Object? value) {
  final text = _text(value);
  return text.isEmpty ? null : text;
}
