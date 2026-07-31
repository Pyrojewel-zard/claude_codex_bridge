import 'dart:convert';
import 'dart:io';

import 'package:ccb_mobile/pairing/gateway_pairing.dart';
import 'package:ccb_mobile/transport/relay_socket_gateway_transport.dart';
import 'package:ccb_mobile/transport/route_provider.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final configPath = Platform.environment['CCB_RELAY_ACCEPTANCE_CONFIG'];

  test(
    'public Relay pairs, transfers a file, and carries a live notification',
    () async {
      final config = _objectMap(
        jsonDecode(await File(configPath!).readAsString()),
        'acceptance config',
      );
      final pairingJson = _objectMap(config['pairing'], 'pairing');
      pairingJson.putIfAbsent(
        'claim_endpoint',
        () => '${pairingJson['gateway_url']}/v1/pairing/claim',
      );
      final pairing = GatewayPairingPayload.fromJson(pairingJson);
      final hostId = pairing.hostId ?? pairing.projectId;
      expect(hostId, isNotNull);
      final provisionalProfile = GatewayHostProfile(
        hostId: hostId!,
        deviceId: 'relay-acceptance-pairing',
        routeProvider: RouteProvider(
          kind: RouteProviderKind.relay,
          gatewayUrl: pairing.gatewayUrl,
          websocketUrl: pairing.websocketUrl,
          hostFingerprint: pairing.hostFingerprint,
          relayBootstrap: pairing.relayBootstrap,
          capabilities: const {'relay.forward', 'relay_reconnect'},
        ),
        scopes: pairing.scopes,
      );
      final provisional = RelaySocketGatewayTransport(
        profile: provisionalProfile,
        deviceToken: '',
      );
      final Map<String, Object?> claim;
      try {
        claim = await provisional.claimPairing(
          pairingCode: pairing.pairingCode,
          deviceName: 'Dart Relay acceptance',
          phoneAuthPublicKeyB64: _requiredText(
            config['phone_auth_public_key_b64'],
            'phone_auth_public_key_b64',
          ),
        );
      } finally {
        await provisional.close(force: true);
      }
      final paired = GatewayPairedHost.fromClaimJson(
        claim,
        pairing: pairing,
        relayPhoneAuthPrivateKeyB64: _requiredText(
          config['phone_auth_private_key_b64'],
          'phone_auth_private_key_b64',
        ),
      );
      final transport = RelaySocketGatewayTransport(
        profile: paired.profile,
        deviceToken: paired.deviceToken,
      );
      addTearDown(() => transport.close(force: true));

      final projectPrefix = _requiredText(
        config['file_project_name_prefix'],
        'file_project_name_prefix',
      );
      final agentName = _requiredText(config['file_agent'], 'file_agent');
      final projects = await transport.listProjects();
      final project = projects.singleWhere(
        (candidate) => candidate.displayName.startsWith(projectPrefix),
      );
      final projectView = await transport.getProjectView(project.id);
      expect(projectView.agentByName(agentName), isNotNull);

      final uploadBytes = List<int>.generate(
        (192 * 1024) + 17,
        (index) => index % 251,
        growable: false,
      );
      final upload = await transport.uploadFile(
        projectId: project.id,
        agentName: agentName,
        fileName: 'relay-public-acceptance.bin',
        mimeType: 'application/octet-stream',
        bytes: uploadBytes,
      );
      expect(upload.fileId, isNotEmpty);
      expect(upload.fileName, 'relay-public-acceptance.bin');
      expect(upload.sizeBytes, uploadBytes.length);
      final downloaded = await transport.downloadFile(
        projectId: project.id,
        agentName: agentName,
        fileId: upload.fileId,
      );
      expect(downloaded, uploadBytes);

      final event = await transport
          .notificationEvents(
            lastEventId: _requiredText(
              config['last_event_id'],
              'last_event_id',
            ),
          )
          .first
          .timeout(const Duration(seconds: 30));

      expect(event['id'], startsWith('mnotif_'));
      expect(_objectMap(event['data'], 'event.data')['kind'], 'task_completed');
    },
    skip:
        configPath == null
            ? 'Set CCB_RELAY_ACCEPTANCE_CONFIG for public Relay acceptance.'
            : false,
    timeout: const Timeout(Duration(seconds: 60)),
  );
}

Map<String, Object?> _objectMap(Object? value, String label) {
  if (value is! Map) {
    throw FormatException('$label must be an object');
  }
  return {for (final entry in value.entries) entry.key.toString(): entry.value};
}

String _requiredText(Object? value, String label) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty) {
    throw FormatException('$label is required');
  }
  return text;
}
