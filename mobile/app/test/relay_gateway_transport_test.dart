import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test(
    'delegates gateway operations while sealing v2 AEAD relay envelopes',
    () async {
      final sessions = _relaySessions();
      final inner = _RecordingGatewayTransport(_relayProfile());
      final transport = RelayGatewayTransport(
        inner: inner,
        sessionId: 'relay-session-demo',
        cryptoSession: sessions.phone,
      );

      final health = await transport.health();
      final device = await transport.device();
      final projects = await transport.listProjects();
      final view = await transport.getProjectView('proj-demo');
      final provider = await transport.getAgentProviderControl(
        projectId: 'proj-demo',
        agentName: 'mobile',
      );
      final quota = await transport.getAgentProviderQuota(
        projectId: 'proj-demo',
        agentName: 'mobile',
      );
      final providerUpdate = await transport.updateAgentProviderSettings(
        projectId: 'proj-demo',
        agentName: 'mobile',
        model: 'gpt-5.6-sol',
        thinking: 'xhigh',
        expectedRevision: 'config-r1',
        expectedNamespaceEpoch: 4,
        expectedProvider: 'codex',
        expectedRuntimeRevision: 'runtime-r1',
        idempotencyKey: 'provider-idempotency-0001',
      );
      final focusedAgent = await transport.focusAgent(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
      );
      final focusedWindow = await transport.focusWindow(
        projectId: 'proj-demo',
        window: 'main',
        namespaceEpoch: 4,
      );
      final history = await transport.getReadableTerminalHistory(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
        maxLines: 120,
      );
      final conversation = await transport.getAgentConversation(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 4,
        limit: 25,
      );
      final submitted = await transport.submitAgentMessage(
        CcbAgentMessageSubmitRequest(
          projectId: 'proj-demo',
          agentName: 'mobile',
          namespaceEpoch: 4,
          idempotencyKey: 'mobile-msg-1',
          body: 'secret chat text',
        ),
      );
      final lifecycle = await transport.requestLifecycle(
        projectId: 'proj-demo',
        action: CcbLifecycleAction.open,
      );
      final handle = await transport.openTerminal(
        GatewayTerminalOpenRequest.fromCcbTarget(
          view.terminalTargetForAgent('mobile'),
        ),
      );
      final frames =
          await transport.terminalFrames(handle, resumeCursor: 7).toList();
      await transport.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.paste(sequence: 2, text: 'secret paste text'),
      );

      expect(health.status, 'ok');
      expect(device.routeProvider, RouteProviderKind.relay);
      expect(projects.single.id, 'proj-demo');
      expect(provider.control.activeModel, 'gpt-5.5');
      expect(quota.windows.single.usedPct, 25);
      expect(providerUpdate.configuredModel, 'gpt-5.6-sol');
      expect(focusedAgent.project.id, 'proj-demo');
      expect(focusedWindow.activeWindow, 'main');
      expect(history?.blocks.single.text, 'local relay adapter smoke');
      expect(conversation.items.single.body, 'ready');
      expect(submitted.accepted, isTrue);
      expect(lifecycle.effect, 'opened');
      expect(handle.terminalId, 'term_proj-demo_mobile');
      expect(frames.single.toJson()['type'], 'open');
      expect(inner.calls, [
        'health',
        'device',
        'listProjects',
        'getProjectView:proj-demo',
        'getProviderControl:proj-demo/mobile',
        'getProviderQuota:proj-demo/mobile',
        'updateProviderSettings:proj-demo/mobile/gpt-5.6-sol/xhigh',
        'focusAgent:proj-demo/mobile/4',
        'focusWindow:proj-demo/main/4',
        'terminalHistory:proj-demo/mobile/4/120',
        'agentConversation:proj-demo/mobile/4/25/null',
        'submitAgentMessage:proj-demo/mobile/mobile-msg-1',
        'lifecycle:proj-demo/open',
        'openTerminal:proj-demo/mobile',
        'terminalFrames:term_proj-demo_mobile/7',
        'sendTerminalFrame:term_proj-demo_mobile/paste',
      ]);

      expect(transport.sealedRequests.map((envelope) => envelope.operation), [
        'health',
        'device',
        'list_projects',
        'get_project_view',
        'get_agent_provider_control',
        'get_agent_provider_quota',
        'update_agent_provider_settings',
        'focus_agent',
        'focus_window',
        'terminal_history',
        'agent_conversation',
        'submit_agent_message',
        'lifecycle',
        'open_terminal',
        'terminal_frames',
        'send_terminal_frame',
      ]);
      expect(
        transport.sealedRequests.map((envelope) => envelope.sequence),
        List<int>.generate(16, (index) => index + 1),
      );
      for (final envelope in transport.sealedRequests) {
        final json = envelope.toJson();
        expect(envelope.schemaVersion, relayProtocolVersion);
        expect(envelope.keyId, relayKeyId);
        expect(json['session_id'], 'relay-session-demo');
        expect(json, containsPair('ciphertext_b64', isA<String>()));
        expect(json, containsPair('nonce_b64', isA<String>()));
        _expectOpaqueRelayEnvelope(json);
      }
      final openedPayloads = <Map<String, Object?>>[];
      for (final envelope in transport.sealedRequests) {
        final plaintext = utf8.decode(
          await sessions.host.open(_asPhoneToHostFrame(envelope)),
        );
        openedPayloads.add(Map<String, Object?>.from(jsonDecode(plaintext)));
      }
      expect(openedPayloads[3], containsPair('project_id', 'proj-demo'));
      expect(
        openedPayloads[6],
        allOf(
          containsPair('model', 'gpt-5.6-sol'),
          containsPair('expected_namespace_epoch', 4),
          containsPair('expected_revision', 'config-r1'),
          containsPair('expected_runtime_revision', 'runtime-r1'),
          containsPair('idempotency_key', 'provider-idempotency-0001'),
        ),
      );
      expect(
        openedPayloads[15],
        containsPair('terminal_id', handle.terminalId),
      );
    },
  );

  test('rejects non-relay profiles', () {
    final sessions = _relaySessions();
    expect(
      () => RelayGatewayTransport(
        inner: _RecordingGatewayTransport(
          GatewayHostProfile(
            hostId: 'host-demo',
            deviceId: 'dev-demo',
            routeProvider: RouteProvider(
              kind: RouteProviderKind.lan,
              gatewayUrl: Uri.parse('http://127.0.0.1:8787'),
            ),
            scopes: const {'view'},
          ),
        ),
        sessionId: 'relay-session-demo',
        cryptoSession: sessions.phone,
      ),
      throwsA(isA<ArgumentError>()),
    );
  });

  test(
    'production relay transport exposes no fake codec construction path',
    () {
      final source =
          File('lib/transport/relay_gateway_transport.dart').readAsStringSync();
      final export = File('lib/ccb_mobile.dart').readAsStringSync();

      expect(source, contains('required RelayCryptoSession cryptoSession'));
      expect(source, isNot(contains('TestOnlyLocalOpaqueRelayEnvelopeCodec')));
      expect(source, isNot(contains('RelayGatewayEnvelopeCodec codec')));
      expect(
        export,
        contains("export 'transport/relay_gateway_transport.dart';"),
      );
    },
  );

  test(
    'production constructor seals a single gateway operation as v2 AEAD',
    () async {
      final sessions = _relaySessions();
      final transport = RelayGatewayTransport(
        inner: _RecordingGatewayTransport(_relayProfile()),
        sessionId: 'relay-session-demo',
        cryptoSession: sessions.phone,
      );

      await transport.getProjectView('proj-demo');

      final envelope = transport.sealedRequests.single;
      final envelopeJson = envelope.toJson();
      expect(envelope.schemaVersion, relayProtocolVersion);
      expect(envelope.keyId, relayKeyId);
      expect(envelopeJson.toString(), isNot(contains('proj-demo')));
      final plaintext = utf8.decode(
        await sessions.host.open(_asPhoneToHostFrame(envelope)),
      );
      expect(jsonDecode(plaintext), containsPair('project_id', 'proj-demo'));
    },
  );

  test('parses relay envelope and rejects malformed opaque fields', () {
    final envelope = RelayGatewayEnvelope.fromJson({
      'schema_version': relayProtocolVersion,
      'session_id': 'relay-session-demo',
      'seq': 3,
      'op': 'get_project_view',
      'ciphertext_b64': 'b3BhcXVl',
      'nonce_b64': 'bm9uY2U=',
      'key_id': 'key-demo',
    });

    expect(envelope.toJson(), {
      'schema_version': relayProtocolVersion,
      'session_id': 'relay-session-demo',
      'seq': 3,
      'op': 'get_project_view',
      'ciphertext_b64': 'b3BhcXVl',
      'nonce_b64': 'bm9uY2U=',
      'key_id': 'key-demo',
    });
    expect(
      () => RelayGatewayEnvelope.fromJson({
        'session_id': 'relay-session-demo',
        'seq': 0,
        'op': 'get_project_view',
        'ciphertext_b64': 'not base64!',
        'nonce_b64': 'bm9uY2U',
      }),
      throwsFormatException,
    );
    expect(
      () => RelayGatewayEnvelope.fromJson({
        'schema_version': 1,
        'session_id': 'relay-session-demo',
        'seq': 1,
        'op': 'get_project_view',
        'ciphertext_b64': 'b3BhcXVl',
        'nonce_b64': 'bm9uY2U=',
      }),
      throwsFormatException,
    );
    expect(
      () => RelayGatewayEnvelope.fromJson({
        'schema_version': relayProtocolVersion,
        'session_id': 'relay-session-demo',
        'seq': (relayMaxSequence + BigInt.one).toString(),
        'op': 'get_project_view',
        'ciphertext_b64': 'b3BhcXVl',
        'nonce_b64': 'bm9uY2U=',
      }),
      throwsFormatException,
    );
  });
}

({RelayCryptoSession phone, RelayCryptoSession host}) _relaySessions() {
  return (
    phone: RelayCryptoSession(
      sessionId: 'relay-session-demo',
      sendDirection: RelayCryptoDirection.phoneToHost,
      receiveDirection: RelayCryptoDirection.hostToPhone,
      sendKey: List<int>.filled(32, 7),
      receiveKey: List<int>.filled(32, 9),
      sendNoncePrefix: const [1, 2, 3, 4],
      receiveNoncePrefix: const [5, 6, 7, 8],
    ),
    host: RelayCryptoSession(
      sessionId: 'relay-session-demo',
      sendDirection: RelayCryptoDirection.hostToPhone,
      receiveDirection: RelayCryptoDirection.phoneToHost,
      sendKey: List<int>.filled(32, 9),
      receiveKey: List<int>.filled(32, 7),
      sendNoncePrefix: const [5, 6, 7, 8],
      receiveNoncePrefix: const [1, 2, 3, 4],
    ),
  );
}

RelayV2Envelope _asPhoneToHostFrame(RelayGatewayEnvelope envelope) {
  return RelayV2Envelope.fromJson({
    ...envelope.toJson(),
    'direction': RelayCryptoDirection.phoneToHost.wireName,
  });
}

GatewayHostProfile _relayProfile() {
  return GatewayHostProfile(
    hostId: 'host-relay',
    deviceId: 'dev-relay',
    routeProvider: RouteProvider(
      kind: RouteProviderKind.relay,
      gatewayUrl: Uri.parse('https://relay.seemlab.top'),
      websocketUrl: Uri.parse('wss://relay.seemlab.top'),
      hostFingerprint: 'host-fp-demo',
      capabilities: const {'http_json', 'project_view', 'relay_tunnel'},
    ),
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle'},
  );
}

void _expectOpaqueRelayEnvelope(Map<String, Object?> json) {
  final text = json.toString();
  expect(text, isNot(contains('proj-demo')));
  expect(text, isNot(contains('mobile')));
  expect(text, isNot(contains('main')));
  expect(text, isNot(contains('terminal-secret')));
  expect(text, isNot(contains('secret paste text')));
  expect(text, isNot(contains('secret chat text')));
  expect(text, isNot(contains('route_provider')));
  expect(text, isNot(contains('gateway_url')));
  expect(text, isNot(contains('websocket_url')));
  expect(json, isNot(containsPair('project_id', anything)));
  expect(json, isNot(containsPair('terminal_id', anything)));
  expect(json, isNot(containsPair('token', anything)));
}

class _RecordingGatewayTransport
    implements GatewayTransport, GatewayProviderControlTransport {
  _RecordingGatewayTransport(this.profile);

  @override
  final GatewayHostProfile profile;

  final calls = <String>[];

  @override
  Future<GatewayFileUploadResult> uploadFile({
    required String projectId,
    required String agentName,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
  }) async {
    calls.add('uploadFile');
    return GatewayFileUploadResult(fileId: 'file-1', fileName: fileName);
  }

  @override
  Future<List<int>> downloadFile({
    required String projectId,
    required String agentName,
    required String fileId,
  }) async {
    calls.add('downloadFile');
    return [1, 2, 3];
  }

  @override
  Future<GatewayHealth> health() async {
    calls.add('health');
    return GatewayHealth(
      status: 'ok',
      serverTime: DateTime.utc(2026, 6, 21),
      capabilities: const {'http_json', 'project_view', 'websocket_terminal'},
    );
  }

  @override
  Future<GatewayDevice> device() async {
    calls.add('device');
    return GatewayDevice(
      deviceId: profile.deviceId,
      projectId: 'proj-demo',
      scopes: profile.scopes,
      routeProvider: profile.routeProvider.kind,
      gatewayUrl: profile.routeProvider.gatewayUrl,
      revoked: false,
    );
  }

  @override
  Future<List<CcbProject>> listProjects() async {
    calls.add('listProjects');
    return [_view().project];
  }

  @override
  Future<CcbProjectView> getProjectView(String projectId) async {
    calls.add('getProjectView:$projectId');
    return _view();
  }

  @override
  Future<CcbProviderControlDetails> getAgentProviderControl({
    required String projectId,
    required String agentName,
  }) async {
    calls.add('getProviderControl:$projectId/$agentName');
    return const CcbProviderControlDetails(
      projectId: 'proj-demo',
      agent: 'mobile',
      namespaceEpoch: 4,
      control: CcbProviderControl(
        provider: 'codex',
        activeModel: 'gpt-5.5',
        activeThinking: 'medium',
        runtimeRevision: 'runtime-r1',
      ),
      catalog: CcbProviderCatalog(provider: 'codex'),
      configRevision: 'config-r1',
    );
  }

  @override
  Future<CcbProviderAccountUsage> getAgentProviderQuota({
    required String projectId,
    required String agentName,
  }) async {
    calls.add('getProviderQuota:$projectId/$agentName');
    return const CcbProviderAccountUsage(
      provider: 'codex',
      status: 'available',
      windows: [
        CcbProviderUsageWindow(id: 'weekly', label: 'Weekly', usedPct: 25),
      ],
    );
  }

  @override
  Future<CcbProviderSettingsResult> updateAgentProviderSettings({
    required String projectId,
    required String agentName,
    required String model,
    String? thinking,
    required String expectedRevision,
    required int expectedNamespaceEpoch,
    required String expectedProvider,
    String? expectedRuntimeRevision,
    required String idempotencyKey,
  }) async {
    calls.add('updateProviderSettings:$projectId/$agentName/$model/$thinking');
    return CcbProviderSettingsResult(
      status: 'pending_restart',
      agent: agentName,
      provider: expectedProvider,
      configuredModel: model,
      configuredThinking: thinking,
      configRevision: 'config-r2',
      changed: true,
      restartRequired: true,
      idempotencyKey: idempotencyKey,
      namespaceEpoch: expectedNamespaceEpoch,
    );
  }

  @override
  Future<CcbProjectView> focusAgent({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
  }) async {
    calls.add('focusAgent:$projectId/$agent/$namespaceEpoch');
    return _view();
  }

  @override
  Future<CcbProjectView> focusWindow({
    required String projectId,
    required String window,
    required int namespaceEpoch,
  }) async {
    calls.add('focusWindow:$projectId/$window/$namespaceEpoch');
    return _view();
  }

  @override
  Future<ReadableTerminalHistory?> getReadableTerminalHistory({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int maxLines = 200,
  }) async {
    calls.add('terminalHistory:$projectId/$agent/$namespaceEpoch/$maxLines');
    return _view().terminalHistoryForAgent(agent);
  }

  @override
  Future<CcbAgentConversation> getAgentConversation({
    required String projectId,
    required String agent,
    required int namespaceEpoch,
    int limit = 50,
    String? cursor,
  }) async {
    calls.add(
      'agentConversation:$projectId/$agent/$namespaceEpoch/$limit/$cursor',
    );
    return CcbAgentConversation(
      projectId: projectId,
      agentName: agent,
      namespaceEpoch: namespaceEpoch,
      items: [
        CcbConversationItem.status(
          id: 'status-$agent',
          agentName: agent,
          title: 'Status',
          body: 'ready',
        ),
      ],
    );
  }

  @override
  Future<CcbAgentMessageSubmitResult> submitAgentMessage(
    CcbAgentMessageSubmitRequest request,
  ) async {
    calls.add(
      'submitAgentMessage:${request.projectId}/${request.agentName}/'
      '${request.idempotencyKey}',
    );
    final message = CcbConversationItem.userMessage(
      id: request.idempotencyKey,
      agentName: request.agentName,
      body: request.body,
      state: CcbConversationDeliveryState.sent,
    );
    return CcbAgentMessageSubmitResult(
      accepted: true,
      idempotencyKey: request.idempotencyKey,
      messageId: request.idempotencyKey,
      state: CcbConversationDeliveryState.sent,
      message: message,
    );
  }

  @override
  Future<CcbProjectLifecycleResult> requestLifecycle({
    required String projectId,
    required CcbLifecycleAction action,
  }) async {
    calls.add('lifecycle:$projectId/${action.wireName}');
    return CcbProjectLifecycleResult(
      projectId: projectId,
      action: action,
      state: 'running',
      effect: 'opened',
      ccbAuthority: true,
      tmuxKillServer: false,
    );
  }

  @override
  Future<GatewayTerminalHandle> openTerminal(
    GatewayTerminalOpenRequest request,
  ) async {
    calls.add(
      'openTerminal:${request.target.projectId}/${request.target.agent}',
    );
    return GatewayTerminalHandle(
      terminalId: 'term_${request.target.projectId}_${request.target.agent}',
      terminalToken: 'terminal-secret',
      expiresAt: DateTime.utc(2026, 6, 21, 12, 5),
      websocketUrl: Uri.parse('wss://relay.seemlab.top'),
      targetEpoch: request.target.namespaceEpoch,
      targetSummary: GatewayTerminalTargetSummary(
        projectId: request.target.projectId,
        agent: request.target.agent,
        window: request.target.window,
      ),
    );
  }

  @override
  Stream<GatewayTerminalFrame> terminalFrames(
    GatewayTerminalHandle handle, {
    int? resumeCursor,
  }) {
    calls.add('terminalFrames:${handle.terminalId}/$resumeCursor');
    return Stream<GatewayTerminalFrame>.fromIterable([
      GatewayTerminalFrame.open(
        terminalId: handle.terminalId,
        token: handle.terminalToken,
        resumeCursor: resumeCursor,
      ),
    ]);
  }

  @override
  Future<void> sendTerminalFrame(
    GatewayTerminalHandle handle,
    GatewayTerminalFrame frame,
  ) async {
    calls.add('sendTerminalFrame:${handle.terminalId}/${frame.type.wireName}');
  }
}

CcbProjectView _view() {
  return CcbProjectView.fromProjectViewPayload({
    'view': {
      'project': {
        'id': 'proj-demo',
        'root': '/srv/demo',
        'display_name': 'demo',
      },
      'namespace': {
        'epoch': 4,
        'active_window': 'main',
        'active_pane_id': '%2',
      },
      'windows': [
        {
          'name': 'main',
          'label': 'main',
          'kind': 'agents',
          'order': 0,
          'active': true,
          'agents': ['mobile'],
        },
      ],
      'agents': [
        {
          'name': 'mobile',
          'provider': 'codex',
          'window': 'main',
          'order': 0,
          'pane_id': '%2',
          'active': true,
        },
      ],
      'terminal_history': {
        'by_agent': {
          'mobile': {
            'history_scope': 'tmux_scrollback',
            'source_pane_id': '%2',
            'generated_at': '2026-06-21T00:00:00Z',
            'stale': false,
            'blocks': [
              {
                'id': 'history-1',
                'type': 'log',
                'title': 'Log',
                'text': 'local relay adapter smoke',
              },
            ],
          },
        },
      },
    },
  });
}
