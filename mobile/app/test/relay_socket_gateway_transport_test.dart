import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:cryptography/cryptography.dart';
import 'package:test/test.dart';

const _relayHarnessUnaryOperations = {
  'pair_claim',
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
  'open_host_terminal',
  'terminate_host_terminal',
};

const _relayHarnessStreamOperations = {
  'terminal',
  'notifications',
  'file_upload',
  'file_download',
};

void main() {
  test(
    'socket relay transport handshakes and opens encrypted project view',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      final view = await transport.getProjectView('proj-demo');

      expect(view.project.id, 'proj-demo');
      expect(relay.requests.single['operation'], 'get_project_view');
      expect(relay.requests.single['payload'], {
        'project_id': 'proj-demo',
        'device_token': 'device-secret',
      });
      final relayVisibleText = relay.visibleFrames.join('\n');
      expect(relayVisibleText, isNot(contains('proj-demo')));
      expect(relayVisibleText, isNot(contains('device-secret')));
      expect(relayVisibleText, contains('gateway_envelope'));
      expect(relayVisibleText, contains('ciphertext_b64'));
    },
  );

  test(
    'requires production WSS origin outside explicit loopback test mode',
    () async {
      expect(
        () => RelaySocketGatewayTransport(
          profile: _profileSync(
            relayOrigin: Uri.parse('ws://relay.example'),
            hostFingerprint: 'sha256:host',
          ),
          deviceToken: 'device-secret',
        ),
        throwsArgumentError,
      );
      expect(
        () => RelaySocketGatewayTransport(
          profile: _profileSync(
            relayOrigin: Uri.parse('wss://relay.example/v2/phone'),
            hostFingerprint: 'sha256:host',
          ),
          deviceToken: 'device-secret',
        ),
        throwsArgumentError,
      );
    },
  );

  test(
    'waits for server-wide project health warmup before returning',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      relay.projectListBodies.addAll([
        {
          'schema_version': 1,
          'projects': <Object?>[],
          'health_warming': true,
          'health_unknown_project_count': 1,
        },
        {
          'schema_version': 1,
          'projects': [
            {
              'id': 'proj-live',
              'display_name': 'live',
              'health': 'healthy',
              'capabilities': ['http_json', 'project_view'],
            },
          ],
          'health_warming': false,
          'health_unknown_project_count': 0,
        },
      ]);
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        projectListWarmupRetryDelay: Duration.zero,
        projectListWarmupMaxAttempts: 3,
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      final projects = await transport.listProjects();

      expect(projects.map((project) => project.id), ['proj-live']);
      expect(relay.requests.map((request) => request['operation']), [
        'list_projects',
        'list_projects',
      ]);
    },
  );

  test(
    'provider control preserves fenced settings over encrypted relay',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      final details = await transport.getAgentProviderControl(
        projectId: 'proj-demo',
        agentName: 'worker1',
      );
      final quota = await transport.getAgentProviderQuota(
        projectId: 'proj-demo',
        agentName: 'worker1',
      );
      final result = await transport.updateAgentProviderSettings(
        projectId: 'proj-demo',
        agentName: 'worker1',
        model: 'gpt-5.6-sol',
        thinking: 'xhigh',
        expectedRevision: 'config-r1',
        expectedNamespaceEpoch: 7,
        expectedProvider: 'codex',
        expectedRuntimeRevision: 'runtime-r1',
        idempotencyKey: 'provider-idempotency-0001',
      );

      expect(details.control.activeModel, 'gpt-5.5');
      expect(details.accountUsage, isNull);
      expect(quota.windows.single.usedPct, 25);
      expect(result.status, 'pending_restart');
      expect(relay.requests.map((request) => request['operation']), [
        'get_agent_provider_control',
        'get_agent_provider_quota',
        'update_agent_provider_settings',
      ]);
      expect(relay.requests.last['payload'], {
        'project_id': 'proj-demo',
        'agent': 'worker1',
        'model': 'gpt-5.6-sol',
        'thinking': 'xhigh',
        'expected_revision': 'config-r1',
        'expected_namespace_epoch': 7,
        'expected_provider': 'codex',
        'expected_runtime_revision': 'runtime-r1',
        'idempotency_key': 'provider-idempotency-0001',
        'device_token': 'device-secret',
      });
    },
  );

  test(
    'rejects provider controls before sending to an older relay host',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
        unaryOperations: const {'health', 'get_project_view'},
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      await expectLater(
        transport.getAgentProviderControl(
          projectId: 'proj-demo',
          agentName: 'worker1',
        ),
        throwsA(
          isA<RelayGatewayException>().having(
            (error) => error.message,
            'message',
            'operation_not_allowed',
          ),
        ),
      );
      expect(relay.requests, isEmpty);
    },
  );

  test('fails closed on host fingerprint mismatch', () async {
    final hostSeed = List<int>.generate(32, (index) => index + 101);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostFingerprint = await hostFingerprintForPublicKey(hostPublicKeyB64);
    final relay = await _RelaySocketHarness.start(
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    addTearDown(relay.stop);
    final transport = RelaySocketGatewayTransport(
      profile: await _profile(
        relayOrigin: relay.origin,
        hostFingerprint: 'sha256:wrong',
      ),
      deviceToken: 'device-secret',
      allowInsecureLoopbackForTests: true,
    );
    addTearDown(() => transport.close(force: true));

    await expectLater(
      transport.getProjectView('proj-demo'),
      throwsA(isA<RelayGatewayException>()),
    );
    expect(relay.requests, isEmpty);
  });

  test(
    'route profile stores relay bootstrap separately from pairing identity',
    () {
      final profile = _profileSync(
        relayOrigin: Uri.parse('wss://relay.seemlab.top'),
        hostFingerprint: 'sha256:host',
      );

      expect(
        profile.routeProvider.toPairingJson(),
        contains('relay_session_id'),
      );
      expect(
        RelayPhoneSessionBootstrap.maybeFromJson(
          profile.routeProvider.toPairingJson(),
        )?.sessionId,
        'relay-session-demo',
      );
    },
  );

  test('terminal input and output use one encrypted relay stream', () async {
    final hostSeed = List<int>.generate(32, (index) => index + 101);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostFingerprint = await hostFingerprintForPublicKey(hostPublicKeyB64);
    final relay = await _RelaySocketHarness.start(
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    addTearDown(relay.stop);
    final transport = RelaySocketGatewayTransport(
      profile: await _profile(
        relayOrigin: relay.origin,
        hostFingerprint: hostFingerprint,
      ),
      deviceToken: 'device-secret',
      allowInsecureLoopbackForTests: true,
    );
    addTearDown(() => transport.close(force: true));
    final handle = await transport.openTerminal(
      GatewayTerminalOpenRequest(
        target: GatewayTerminalTarget(
          projectId: 'proj-demo',
          namespaceEpoch: 7,
          kind: CcbTerminalTargetKind.agent,
          agent: 'worker1',
          window: 'main',
          paneId: '%7',
        ),
      ),
    );
    final frames = <GatewayTerminalFrame>[];
    final outputSeen = Completer<void>();
    final subscription = transport.terminalFrames(handle).listen((frame) {
      frames.add(frame);
      if (frame.type == GatewayTerminalFrameType.output &&
          !outputSeen.isCompleted) {
        outputSeen.complete();
      }
    });
    addTearDown(subscription.cancel);
    while (frames.isEmpty) {
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }

    await transport.sendTerminalFrame(
      handle,
      GatewayTerminalFrame.input(
        sequence: 1,
        bytes: utf8.encode('relay-input'),
      ),
    );
    await outputSeen.future.timeout(const Duration(seconds: 2));

    expect(frames.first.type, GatewayTerminalFrameType.open);
    expect(frames.last.type, GatewayTerminalFrameType.output);
    expect(
      utf8.decode(base64Decode(frames.last.payload['bytes_b64']! as String)),
      'relay-input',
    );
    expect(relay.terminalFrames, [
      {
        'type': 'input',
        'seq': 1,
        'bytes_b64': base64Encode(utf8.encode('relay-input')),
      },
    ]);
  });

  test(
    'canceling a superseded relay terminal stream keeps the current stream',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));
      final handle = await transport.openTerminal(
        GatewayTerminalOpenRequest(
          target: GatewayTerminalTarget(
            projectId: 'proj-demo',
            namespaceEpoch: 7,
            kind: CcbTerminalTargetKind.agent,
            agent: 'worker1',
            window: 'main',
            paneId: '%7',
          ),
        ),
      );
      final first = transport.terminalFrames(handle).listen((_) {});
      addTearDown(first.cancel);
      await _waitFor(
        () =>
            relay.streamOpens
                .where((item) => item['operation'] == 'terminal')
                .length ==
            1,
      );
      final second = transport
          .terminalFrames(handle, resumeCursor: 1)
          .listen((_) {});
      addTearDown(second.cancel);
      await _waitFor(
        () =>
            relay.streamOpens
                .where((item) => item['operation'] == 'terminal')
                .length ==
            2,
      );

      await first.cancel();
      await transport.sendTerminalFrame(
        handle,
        GatewayTerminalFrame.input(
          sequence: 9,
          bytes: utf8.encode('current-relay-stream'),
        ),
      );
      await _waitFor(
        () => relay.terminalFrames.any(
          (frame) => frame['type'] == 'input' && frame['seq'] == 9,
        ),
      );

      expect(relay.terminalFrames.last, {
        'type': 'input',
        'seq': 9,
        'bytes_b64': base64Encode(utf8.encode('current-relay-stream')),
      });
    },
  );

  test('host terminal open and terminate use relay unary operations', () async {
    final hostSeed = List<int>.generate(32, (index) => index + 101);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostFingerprint = await hostFingerprintForPublicKey(hostPublicKeyB64);
    final relay = await _RelaySocketHarness.start(
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    addTearDown(relay.stop);
    final transport = RelaySocketGatewayTransport(
      profile: await _profile(
        relayOrigin: relay.origin,
        hostFingerprint: hostFingerprint,
      ),
      deviceToken: 'device-secret',
      allowInsecureLoopbackForTests: true,
    );
    addTearDown(() => transport.close(force: true));

    final handle = await transport.openHostTerminal(
      const GatewayHostTerminalOpenRequest(
        clientSessionId: 'shell-2',
        displayName: 'Shell 2',
      ),
    );
    await transport.terminateHostTerminal(clientSessionId: 'shell-2');

    expect(handle.targetSummary.projectId, '@host');
    expect(
      relay.requests.map((request) => request['operation']),
      containsAllInOrder(['open_host_terminal', 'terminate_host_terminal']),
    );
  });

  test(
    'notification SSE events use a cancelable encrypted relay stream',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));
      var connected = 0;

      final event =
          await transport
              .notificationEvents(
                lastEventId: 'event-before',
                watchQuery: const {'watch_project_id': 'proj-demo'},
                onConnected: () => connected += 1,
              )
              .first;

      expect(connected, 1);
      expect(event['id'], 'event-live-1');
      expect((event['data']! as Map)['kind'], 'task_completed');
      expect(relay.streamOpens.single['operation'], 'notifications');
      expect(relay.streamOpens.single['payload'], {
        'last_event_id': 'event-before',
        'watch_project_id': 'proj-demo',
        'device_token': 'device-secret',
      });
    },
  );

  test('file upload and download stay below the relay frame limit', () async {
    final hostSeed = List<int>.generate(32, (index) => index + 101);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostFingerprint = await hostFingerprintForPublicKey(hostPublicKeyB64);
    final relay = await _RelaySocketHarness.start(
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
    );
    addTearDown(relay.stop);
    final transport = RelaySocketGatewayTransport(
      profile: await _profile(
        relayOrigin: relay.origin,
        hostFingerprint: hostFingerprint,
      ),
      deviceToken: 'device-secret',
      allowInsecureLoopbackForTests: true,
    );
    addTearDown(() => transport.close(force: true));
    final content = List<int>.generate(160 * 1024, (index) => index % 251);

    final uploaded = await transport.uploadFile(
      projectId: 'proj-demo',
      agentName: 'worker1',
      fileName: 'large.bin',
      mimeType: 'application/octet-stream',
      bytes: content,
    );
    final downloaded = await transport.downloadFile(
      projectId: 'proj-demo',
      agentName: 'worker1',
      fileId: uploaded.fileId,
    );

    expect(uploaded.fileId, 'file-demo');
    expect(uploaded.fileName, 'large.bin');
    expect(uploaded.sizeBytes, content.length);
    expect(relay.uploadedFiles['file-demo'], content);
    expect(downloaded, content);
    expect(
      relay.streamOpens.map((item) => item['operation']),
      containsAllInOrder(['file_upload', 'file_download']),
    );
    expect(
      relay.visibleFrames.map((frame) => utf8.encode(frame).length),
      everyElement(lessThan(64 * 1024)),
    );
  });

  test(
    'file upload rejects bytes above the configured limit before connect',
    () async {
      final transport = RelaySocketGatewayTransport(
        profile: await _profile(
          relayOrigin: Uri.parse('ws://127.0.0.1:1'),
          hostFingerprint: 'sha256:test-host',
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      await expectLater(
        transport.uploadFile(
          projectId: 'proj-demo',
          agentName: 'worker1',
          fileName: 'too-large.bin',
          mimeType: 'application/octet-stream',
          bytes: List<int>.filled((25 * 1024 * 1024) + 1, 0),
        ),
        throwsA(
          isA<RelayGatewayException>().having(
            (error) => error.message,
            'message',
            'relay upload exceeds size limit',
          ),
        ),
      );
    },
  );

  test(
    'compact relay QR pairing replaces one-time bootstrap with access',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final secureStore = _RelayMemorySecureStore();
      final store = GatewayHostProfileStore(secureStore: secureStore);
      final clientPrivateKeyB64 = _b64(
        List<int>.generate(32, (index) => index + 1),
      );
      final phoneNonceB64 = _b64(utf8.encode('fresh phone nonce'));
      final capabilityPayload = _b64(
        utf8.encode(
          jsonEncode({
            'typ': 'ccb-relay-rv-v1',
            'host_id': 'rhost-demo',
            'session_id': 'relay-session-demo',
            'phone_nonce_b64': phoneNonceB64,
            'aud': relay.origin.toString(),
            'exp':
                DateTime.now()
                    .toUtc()
                    .add(const Duration(minutes: 5))
                    .millisecondsSinceEpoch ~/
                Duration.millisecondsPerSecond,
          }),
        ),
      );
      final rendezvousCapability = 'header.$capabilityPayload.signature';
      final pairing = GatewayPairingPayload.fromQrText(
        '$gatewayCompactRelayQrPrefix'
        'pair-once-secret|$clientPrivateKeyB64|$hostFingerprint|s|'
        '$rendezvousCapability',
      );

      final paired = await defaultPairingClaimAndStore(
        pairing: pairing,
        deviceName: 'Relay Test Phone',
        store: store,
        relayTransportFactory:
            (profile) => RelaySocketGatewayTransport(
              profile: profile,
              deviceToken: '',
              allowInsecureLoopbackForTests: true,
            ),
      );
      final restored = await store.read(
        hostId: paired.profile.hostId,
        deviceId: paired.profile.deviceId,
      );
      final persisted = secureStore.values.values.join('\n');

      expect(paired.profile.routeProvider.relayAccess, isNotNull);
      expect(paired.profile.routeProvider.relayBootstrap, isNull);
      expect(restored?.profile.routeProvider.relayAccess, isNotNull);
      expect(relay.requests.single['operation'], 'pair_claim');
      final claimPayload = Map<String, Object?>.from(
        relay.requests.single['payload']! as Map,
      );
      expect(claimPayload['pairing_code'], 'pair-once-secret');
      expect(claimPayload['device_name'], 'Relay Test Phone');
      expect(claimPayload['phone_auth_pubkey_b64'], isNotEmpty);
      expect(persisted, contains('ccb-relay-access-v1.test.test'));
      expect(persisted, isNot(contains('pair-once-secret')));
      expect(persisted, isNot(contains('relay-session-demo')));
      expect(persisted, isNot(contains(rendezvousCapability)));
    },
  );

  test(
    'durable relay access reconnects with fresh signed session proof',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
        closeAfterFirstUnaryResponse: true,
      );
      addTearDown(relay.stop);
      final phoneAuthSeed = List<int>.generate(32, (index) => index + 41);
      final accessGrant = 'ccb-relay-access-v1.test-payload.test-signature';
      final transport = RelaySocketGatewayTransport(
        profile: _accessProfile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
          phoneAuthSeed: phoneAuthSeed,
          accessGrant: accessGrant,
        ),
        deviceToken: 'device-secret',
        allowInsecureLoopbackForTests: true,
      );
      addTearDown(() => transport.close(force: true));

      expect((await transport.health()).status, 'ok');
      await Future<void>.delayed(const Duration(milliseconds: 80));
      expect((await transport.health()).status, 'ok');

      expect(relay.clientHellos, hasLength(2));
      final first = relay.clientHellos[0];
      final second = relay.clientHellos[1];
      expect(first.sessionId, isNot(second.sessionId));
      expect(
        first.payload['client_pubkey_b64'],
        isNot(second.payload['client_pubkey_b64']),
      );
      expect(
        first.payload['phone_nonce_b64'],
        isNot(second.payload['phone_nonce_b64']),
      );
      await _verifyPhoneProof(first, phoneAuthSeed, accessGrant);
      await _verifyPhoneProof(second, phoneAuthSeed, accessGrant);
    },
  );

  test('default relay routes share one transport per paired host', () async {
    final profile = _accessProfile(
      relayOrigin: Uri.parse('wss://relay.seemlab.top'),
      hostFingerprint: 'sha256:test-host',
      phoneAuthSeed: List<int>.filled(32, 7),
      accessGrant: 'ccb-relay-access-v1.test.test',
    );
    final host = GatewayPairedHost(
      profile: profile,
      deviceToken: 'device-secret',
    );

    final first = defaultGatewayTransportFor(host);
    final second = defaultGatewayTransportFor(host);

    expect(first, same(second));
    await closeDefaultGatewayTransports(force: true);
  });

  test(
    'notification cancellation keeps the shared relay socket alive',
    () async {
      final hostSeed = List<int>.generate(32, (index) => index + 101);
      final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
      final hostFingerprint = await hostFingerprintForPublicKey(
        hostPublicKeyB64,
      );
      final relay = await _RelaySocketHarness.start(
        hostSeed: hostSeed,
        hostFingerprint: hostFingerprint,
      );
      addTearDown(relay.stop);
      final host = GatewayPairedHost(
        profile: _accessProfile(
          relayOrigin: relay.origin,
          hostFingerprint: hostFingerprint,
          phoneAuthSeed: List<int>.filled(32, 7),
          accessGrant: 'ccb-relay-access-v1.test.test',
        ),
        deviceToken: 'device-secret',
      );
      final transport = RelaySocketGatewayTransport(
        profile: host.profile,
        deviceToken: host.deviceToken,
        allowInsecureLoopbackForTests: true,
      );
      final notifications =
          RouteAwareGatewayTaskCompletionNotificationStreamClient(
            relayTransportForHost: (_) => transport,
          );
      addTearDown(() async {
        notifications.close(force: true);
        await transport.close(force: true);
      });

      final event = await notifications.subscribe(host).first;
      final health = await transport.health();

      expect(event.isTaskCompleted, isTrue);
      expect(health.status, 'ok');
      expect(relay.clientHellos, hasLength(1));
    },
  );
}

class _RelaySocketHarness {
  _RelaySocketHarness._({
    required this.server,
    required this.origin,
    required this.hostSeed,
    required this.hostFingerprint,
    required this.closeAfterFirstUnaryResponse,
    required this.unaryOperations,
    required this.streamOperations,
  });

  final HttpServer server;
  final Uri origin;
  final List<int> hostSeed;
  final String hostFingerprint;
  final bool closeAfterFirstUnaryResponse;
  final Set<String> unaryOperations;
  final Set<String> streamOperations;
  final visibleFrames = <String>[];
  final requests = <Map<String, Object?>>[];
  final streamOpens = <Map<String, Object?>>[];
  final terminalFrames = <Map<String, Object?>>[];
  final clientHellos = <RelayFrame>[];
  final uploadedFiles = <String, List<int>>{};
  final projectListBodies = <Map<String, Object?>>[];
  final _streamOperations = <String, String>{};
  final _uploadBuffers = <String, BytesBuilder>{};

  static Future<_RelaySocketHarness> start({
    required List<int> hostSeed,
    required String hostFingerprint,
    bool closeAfterFirstUnaryResponse = false,
    Set<String> unaryOperations = _relayHarnessUnaryOperations,
    Set<String> streamOperations = _relayHarnessStreamOperations,
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final harness = _RelaySocketHarness._(
      server: server,
      origin: Uri.parse('ws://127.0.0.1:${server.port}'),
      hostSeed: hostSeed,
      hostFingerprint: hostFingerprint,
      closeAfterFirstUnaryResponse: closeAfterFirstUnaryResponse,
      unaryOperations: unaryOperations,
      streamOperations: streamOperations,
    );
    server.listen(harness._handle);
    return harness;
  }

  Future<void> stop() {
    return server.close(force: true);
  }

  Future<void> _handle(HttpRequest request) async {
    if (request.uri.path != '/v2/phone') {
      request.response.statusCode = HttpStatus.notFound;
      await request.response.close();
      return;
    }
    final socket = await WebSocketTransformer.upgrade(request);
    final reader = StreamIterator<dynamic>(socket);
    if (!await reader.moveNext()) {
      await socket.close();
      return;
    }
    final clientHelloJson = _jsonMap(reader.current);
    visibleFrames.add(jsonEncode(clientHelloJson));
    final clientHello = RelayFrame.fromJson(clientHelloJson);
    clientHellos.add(clientHello);
    final hostPublicKeyB64 = await _publicKeyB64(hostSeed);
    final hostHello = RelayFrame.hostHello(
      sessionId: clientHello.sessionId,
      sequence: clientHello.sequence + 1,
      hostId: _text(clientHello.payload['host_id']),
      serverFingerprint: hostFingerprint,
      hostPublicKeyB64: hostPublicKeyB64,
      unaryOperations: unaryOperations,
      streamOperations: streamOperations,
    );
    final schedule = await RelayV2KeySchedule.derive(
      localPrivateKeyBytes: hostSeed,
      peerPublicKeyB64: _text(clientHello.payload['client_pubkey_b64']),
      role: 'host',
      sessionId: clientHello.sessionId,
      clientPublicKeyB64: _text(clientHello.payload['client_pubkey_b64']),
      hostPublicKeyB64: hostPublicKeyB64,
      expectedHostFingerprint: hostFingerprint,
    );
    final hostCrypto = schedule.session(role: 'host');
    socket.add(jsonEncode(hostHello.toJson()));

    var outerSeq = 3;
    Future<void> sendInner(RelayInnerMessage message) async {
      final responseEnvelope = await hostCrypto.seal(
        operation: 'relay.inner.v1',
        plaintext: message.encode(),
      );
      socket.add(
        jsonEncode(
          RelayFrame.gatewayEnvelope(
            envelope: RelayGatewayEnvelope(
              schemaVersion: responseEnvelope.schemaVersion,
              sessionId: responseEnvelope.sessionId,
              sequence: responseEnvelope.sequence,
              operation: responseEnvelope.operation,
              direction: responseEnvelope.direction,
              ciphertextB64: responseEnvelope.ciphertextB64,
              nonceB64: responseEnvelope.nonceB64,
              keyId: responseEnvelope.keyId,
            ),
            sequence: outerSeq,
          ).toJson(),
        ),
      );
      outerSeq += 1;
    }

    while (await reader.moveNext()) {
      final frameJson = _jsonMap(reader.current);
      visibleFrames.add(jsonEncode(frameJson));
      final frame = RelayFrame.fromJson(frameJson);
      final envelope = frame.gatewayEnvelope();
      final plaintext = await hostCrypto.open(
        RelayV2Envelope.fromJson({
          ...envelope.toJson(),
          'direction': RelayCryptoDirection.phoneToHost.wireName,
        }),
      );
      expect(envelope.operation, 'relay.inner.v1');
      final message = RelayInnerMessage.decode(plaintext);
      switch (message.kind) {
        case RelayInnerKind.request:
          final payload = message.payload;
          requests.add({'operation': message.operation, 'payload': payload});
          await sendInner(
            RelayInnerMessage(
              kind: RelayInnerKind.response,
              requestId: message.requestId,
              payload: {
                'ok': true,
                'status': 200,
                'body': switch (message.operation) {
                  'get_project_view' => demoProjectViewFixture,
                  'get_agent_provider_control' => {
                    'project_id': 'proj-demo',
                    'agent': 'worker1',
                    'namespace_epoch': 7,
                    'config_revision': 'config-r1',
                    'provider_control': {
                      'provider': 'codex',
                      'configured_model': 'gpt-5.5',
                      'configured_thinking': 'medium',
                      'active_model': 'gpt-5.5',
                      'active_thinking': 'medium',
                      'runtime_revision': 'runtime-r1',
                      'mutation_mode': 'restart_required',
                      'capabilities': {
                        'model_catalog': true,
                        'model_select': true,
                        'thinking_select': true,
                        'session_usage': true,
                        'account_quota': true,
                      },
                    },
                    'provider_catalog': {
                      'id': 'codex',
                      'model_shortcut': true,
                      'models': [
                        {
                          'id': 'gpt-5.5',
                          'label': 'GPT-5.5',
                          'reasoning_levels': ['low', 'medium', 'xhigh'],
                        },
                      ],
                    },
                  },
                  'get_agent_provider_quota' => {
                    'project_id': 'proj-demo',
                    'agent': 'worker1',
                    'account_usage': {
                      'provider_id': 'codex',
                      'status': 'available',
                      'windows': [
                        {'id': 'weekly', 'label': 'Weekly', 'used_pct': 25},
                      ],
                    },
                  },
                  'update_agent_provider_settings' => {
                    'status': 'pending_restart',
                    'agent': 'worker1',
                    'provider': 'codex',
                    'configured_model': 'gpt-5.6-sol',
                    'configured_thinking': 'xhigh',
                    'config_revision': 'config-r2',
                    'changed': true,
                    'restart_required': true,
                    'idempotency_key': 'provider-idempotency-0001',
                    'namespace_epoch': 7,
                  },
                  'health' => {
                    'schema_version': 1,
                    'status': 'ok',
                    'server_time': '2026-07-22T00:00:00Z',
                    'capabilities': ['http_json', 'project_view'],
                  },
                  'list_projects' =>
                    projectListBodies.isEmpty
                        ? {
                          'schema_version': 1,
                          'projects': <Object?>[],
                          'health_warming': false,
                        }
                        : projectListBodies.removeAt(0),
                  'open_terminal' => {
                    'terminal_id': 'terminal-demo',
                    'terminal_token': 'terminal-token-demo',
                    'expires_at': '2026-07-22T01:00:00Z',
                    'websocket_url':
                        'wss://loopback.invalid/v1/terminals/terminal-demo',
                    'target_epoch': 7,
                    'target_summary': {
                      'project_id': 'proj-demo',
                      'agent': 'worker1',
                      'window': 'main',
                    },
                  },
                  'open_host_terminal' => {
                    'terminal_id': 'terminal-host-demo',
                    'terminal_token': 'terminal-host-token-demo',
                    'expires_at': '2026-07-22T01:00:00Z',
                    'websocket_url':
                        'wss://loopback.invalid/v1/terminals/terminal-host-demo',
                    'target_epoch': 0,
                    'target_summary': {'project_id': '@host'},
                  },
                  'terminate_host_terminal' => {
                    'schema_version': 1,
                    'status': 'ok',
                    'client_session_id': 'shell-2',
                    'terminated': true,
                  },
                  'pair_claim' => {
                    'device_token': 'paired-device-secret',
                    'device': {
                      'device_id': 'device-paired',
                      'project_id': 'project-demo',
                      'scopes': ['view', 'notify', 'terminal_input'],
                    },
                    'host_profile': {
                      'host_id': 'rhost-demo',
                      'device_id': 'device-paired',
                      'project_id': 'project-demo',
                      'route_provider': 'relay',
                      'gateway_url': 'https://relay.invalid',
                      'websocket_url': origin.toString(),
                      'server_fingerprint': hostFingerprint,
                      'relay_access_grant': 'ccb-relay-access-v1.test.test',
                      'scopes': ['view', 'notify', 'terminal_input'],
                      'capabilities': ['relay_tunnel', 'relay_reconnect'],
                    },
                  },
                  _ => {'schema_version': 1, 'status': 'ok'},
                },
              },
            ),
          );
          if (closeAfterFirstUnaryResponse && requests.length == 1) {
            await Future<void>.delayed(const Duration(milliseconds: 10));
            await socket.close();
            return;
          }
        case RelayInnerKind.streamOpen:
          _streamOperations[message.streamId!] = message.operation!;
          streamOpens.add({
            'stream_id': message.streamId,
            'operation': message.operation,
            'payload': message.payload,
          });
          await sendInner(
            RelayInnerMessage.streamWindow(
              streamId: message.streamId!,
              creditBytes: relayStreamInitialWindowBytes,
            ),
          );
          if (message.operation == 'terminal') {
            await sendInner(
              RelayInnerMessage.streamData(
                streamId: message.streamId!,
                payload: const {
                  'frame': {
                    'type': 'open',
                    'terminal_id': 'terminal-demo',
                    'token': '',
                    'resume_cursor': 0,
                    'last_input_seq': 0,
                  },
                },
              ),
            );
          } else if (message.operation == 'notifications') {
            await sendInner(
              RelayInnerMessage.streamData(
                streamId: message.streamId!,
                payload: const {
                  'event': {
                    'id': 'event-live-1',
                    'event': 'task_completed',
                    'data': {
                      'id': 'event-live-1',
                      'kind': 'task_completed',
                      'project_id': 'proj-demo',
                      'project_short_name': 'demo',
                      'agent': 'worker1',
                      'completed_at': '2026-07-22T00:00:00Z',
                      'dedupe_key': 'proj-demo:worker1:event-live-1',
                    },
                  },
                },
              ),
            );
          } else if (message.operation == 'file_upload') {
            _uploadBuffers[message.streamId!] = BytesBuilder(copy: false);
          } else if (message.operation == 'file_download') {
            final content = uploadedFiles['file-demo'] ?? const <int>[];
            for (var offset = 0; offset < content.length; offset += 32 * 1024) {
              final end = min(offset + 32 * 1024, content.length);
              await sendInner(
                RelayInnerMessage.streamData(
                  streamId: message.streamId!,
                  payload: {'chunk_b64': _b64(content.sublist(offset, end))},
                ),
              );
            }
            await sendInner(
              RelayInnerMessage.streamData(
                streamId: message.streamId!,
                payload: const {
                  'eof': true,
                  'content_type': 'application/octet-stream',
                },
              ),
            );
            await sendInner(
              RelayInnerMessage(
                kind: RelayInnerKind.streamClose,
                streamId: message.streamId,
                payload: const {'code': 'completed'},
              ),
            );
          }
        case RelayInnerKind.streamData:
          final operation = _streamOperations[message.streamId];
          await sendInner(
            RelayInnerMessage.streamWindow(
              streamId: message.streamId!,
              creditBytes: relayInnerPayloadSize(message.payload),
            ),
          );
          if (operation == 'file_upload') {
            final chunk = message.payload['chunk_b64'];
            if (chunk is String && chunk.isNotEmpty) {
              _uploadBuffers[message.streamId]!.add(_decodeB64(chunk));
            }
            if (message.payload['eof'] == true) {
              final bytes =
                  _uploadBuffers.remove(message.streamId)!.takeBytes();
              uploadedFiles['file-demo'] = bytes;
              final open = streamOpens.lastWhere(
                (item) => item['stream_id'] == message.streamId,
              );
              final metadata = Map<String, Object?>.from(
                open['payload']! as Map,
              );
              await sendInner(
                RelayInnerMessage.streamData(
                  streamId: message.streamId!,
                  payload: {
                    'result': {
                      'ok': true,
                      'status': 201,
                      'body': {
                        'file_id': 'file-demo',
                        'file_name': metadata['file_name'],
                        'mime_type': metadata['mime_type'],
                        'size_bytes': bytes.length,
                      },
                    },
                  },
                ),
              );
              await sendInner(
                RelayInnerMessage(
                  kind: RelayInnerKind.streamClose,
                  streamId: message.streamId,
                  payload: const {'code': 'completed'},
                ),
              );
            }
            break;
          }
          final frame = Map<String, Object?>.from(
            message.payload['frame']! as Map,
          );
          terminalFrames.add(frame);
          if (frame['type'] == 'input') {
            await sendInner(
              RelayInnerMessage.streamData(
                streamId: message.streamId!,
                payload: {
                  'frame': {
                    'type': 'output',
                    'seq': frame['seq'],
                    'bytes_b64': frame['bytes_b64'],
                  },
                },
              ),
            );
          }
        case RelayInnerKind.streamCancel:
          await sendInner(
            RelayInnerMessage(
              kind: RelayInnerKind.streamClose,
              streamId: message.streamId,
              payload: const {'code': 'stream_not_found'},
            ),
          );
        case RelayInnerKind.streamWindow:
        case RelayInnerKind.response:
        case RelayInnerKind.streamClose:
        case RelayInnerKind.error:
          break;
      }
    }
  }
}

class _RelayMemorySecureStore implements GatewaySecureStore {
  final values = <String, String>{};

  @override
  Future<void> delete({required String key}) async {
    values.remove(key);
  }

  @override
  Future<String?> read({required String key}) async => values[key];

  @override
  Future<void> write({required String key, required String value}) async {
    values[key] = value;
  }
}

Future<GatewayHostProfile> _profile({
  required Uri relayOrigin,
  required String hostFingerprint,
}) async {
  return _profileSync(
    relayOrigin: relayOrigin,
    hostFingerprint: hostFingerprint,
  );
}

GatewayHostProfile _profileSync({
  required Uri relayOrigin,
  required String hostFingerprint,
}) {
  return GatewayHostProfile(
    hostId: 'rhost-demo',
    deviceId: 'dev-demo',
    routeProvider: RouteProvider(
      kind: RouteProviderKind.relay,
      gatewayUrl: Uri.parse('https://relay.seemlab.top'),
      websocketUrl: relayOrigin,
      hostFingerprint: hostFingerprint,
      relayBootstrap: RelayPhoneSessionBootstrap(
        sessionId: 'relay-session-demo',
        clientPrivateKeyB64: _b64(List<int>.generate(32, (index) => index + 1)),
        phoneNonceB64: _b64(utf8.encode('fresh phone nonce')),
        rendezvousCapability: 'ccb-relay-rv-v1.fake',
      ),
      capabilities: const {'relay.forward'},
    ),
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle'},
  );
}

GatewayHostProfile _accessProfile({
  required Uri relayOrigin,
  required String hostFingerprint,
  required List<int> phoneAuthSeed,
  required String accessGrant,
}) {
  return GatewayHostProfile(
    hostId: 'rhost-demo',
    deviceId: 'dev-demo',
    routeProvider: RouteProvider(
      kind: RouteProviderKind.relay,
      gatewayUrl: Uri.parse('https://relay.seemlab.top'),
      websocketUrl: relayOrigin,
      hostFingerprint: hostFingerprint,
      relayAccess: RelayPhoneAccessCredentials(
        accessGrant: accessGrant,
        phoneAuthPrivateKeyB64: _b64(phoneAuthSeed),
      ),
      capabilities: const {'relay.forward', 'relay_reconnect'},
    ),
    scopes: const {'view', 'focus', 'terminal_input', 'lifecycle'},
  );
}

Future<void> _verifyPhoneProof(
  RelayFrame hello,
  List<int> phoneAuthSeed,
  String accessGrant,
) async {
  final token = _text(hello.payload['phone_session_proof']);
  final parts = token.split('.');
  expect(parts, hasLength(3));
  expect(parts.first, 'ccb-relay-phone-proof-v1');
  final payloadBytes = _decodeB64(parts[1]);
  final payload = _jsonMap(utf8.decode(payloadBytes));
  expect(payload['session_id'], hello.sessionId);
  expect(payload['host_id'], hello.payload['host_id']);
  expect(payload['device_id'], hello.payload['device_id']);
  expect(payload['client_pubkey_b64'], hello.payload['client_pubkey_b64']);
  expect(payload['phone_nonce_b64'], hello.payload['phone_nonce_b64']);
  expect(hello.payload['access_grant'], accessGrant);
  final grantDigest = await Sha256().hash(utf8.encode(accessGrant));
  expect(payload['grant_sha256_b64'], _b64(grantDigest.bytes));
  final keyPair = await Ed25519().newKeyPairFromSeed(phoneAuthSeed);
  final publicKey = await keyPair.extractPublicKey();
  expect(
    await Ed25519().verify(
      utf8.encode('ccb-relay-phone-proof-v1\n${utf8.decode(payloadBytes)}'),
      signature: Signature(_decodeB64(parts[2]), publicKey: publicKey),
    ),
    isTrue,
  );
}

Future<void> _waitFor(
  bool Function() predicate, {
  Duration timeout = const Duration(seconds: 2),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!predicate()) {
    if (DateTime.now().isAfter(deadline)) {
      throw TimeoutException('condition was not met', timeout);
    }
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

Future<String> _publicKeyB64(List<int> privateKeyBytes) async {
  final keyPair = await X25519().newKeyPairFromSeed(privateKeyBytes);
  final publicKey = await keyPair.extractPublicKey();
  return _b64(publicKey.bytes);
}

Map<String, Object?> _jsonMap(Object? message) {
  final text = switch (message) {
    final String value => value,
    final List<int> value => utf8.decode(value),
    _ => message.toString(),
  };
  final decoded = jsonDecode(text);
  if (decoded is Map) {
    return {
      for (final entry in decoded.entries) entry.key.toString(): entry.value,
    };
  }
  throw const FormatException('test relay frame is not an object');
}

String _text(Object? value) => (value ?? '').toString();

String _b64(List<int> value) => base64UrlEncode(value).replaceAll('=', '');

List<int> _decodeB64(String value) {
  return base64Url.decode(
    value.padRight(value.length + ((4 - value.length % 4) % 4), '='),
  );
}
