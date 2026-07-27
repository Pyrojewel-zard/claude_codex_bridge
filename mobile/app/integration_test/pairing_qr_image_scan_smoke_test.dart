import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'package:ccb_mobile/app/app_factories.dart';
import 'package:ccb_mobile/pairing/gateway_pairing.dart';
import 'package:ccb_mobile/pairing/gateway_pairing_scanner_screen.dart';
import 'package:ccb_mobile/transport/relay_socket_gateway_transport.dart';
import 'package:ccb_mobile/transport/route_provider.dart';

const _qrPngBase64 = String.fromEnvironment('CCB_MOBILE_PAIRING_QR_PNG_BASE64');
const _expectedQrText = String.fromEnvironment('CCB_MOBILE_PAIRING_QR_TEXT');
const _claimRelayPairing = bool.fromEnvironment(
  'CCB_MOBILE_CLAIM_RELAY_PAIRING',
);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('ML Kit image scanner decodes generated pairing QR payload', (
    tester,
  ) async {
    expect(
      _qrPngBase64,
      isNotEmpty,
      reason: 'Pass CCB_MOBILE_PAIRING_QR_PNG_BASE64 for this smoke test.',
    );
    expect(
      _expectedQrText,
      isNotEmpty,
      reason: 'Pass CCB_MOBILE_PAIRING_QR_TEXT for this smoke test.',
    );

    final directory = await Directory.systemTemp.createTemp('ccb-pairing-qr-');
    addTearDown(() => directory.delete(recursive: true));
    final qrFile = File('${directory.path}/pairing.png');
    await qrFile.writeAsBytes(base64Decode(_qrPngBase64), flush: true);

    final scanner = MobileScannerController(autoStart: false);
    addTearDown(scanner.dispose);
    final capture = await scanner.analyzeImage(
      qrFile.path,
      formats: const [BarcodeFormat.qrCode],
    );
    final decoded = gatewayPairingQrTextFromCapture(capture);

    expect(decoded, isNotNull);
    final decodedText = decoded!;
    if (_expectedQrText.trimLeft().startsWith('{')) {
      expect(jsonDecode(decodedText), jsonDecode(_expectedQrText));
    } else {
      expect(decodedText, _expectedQrText);
    }

    final payload = GatewayPairingPayload.fromQrText(decodedText);
    expect(payload.pairingCode, isNotEmpty);
    expect(payload.gatewayUrl.scheme, isNotEmpty);
    expect(payload.claimEndpoint.path, '/v1/pairing/claim');
    expect(payload.toJson()['scopes'], isA<List<String>>());
    if (_claimRelayPairing) {
      expect(payload.routeProvider, RouteProviderKind.relay);
      final paired = await defaultPairingClaimAndStore(
        pairing: payload,
        deviceName: 'CCB compact QR acceptance',
        store: GatewayHostProfileStore(secureStore: _MemorySecureStore()),
      );
      expect(paired.profile.routeProvider.relayAccess, isNotNull);
      expect(paired.profile.routeProvider.relayBootstrap, isNull);
      expect(paired.profile.scopes, isNotEmpty);

      final transport = RelaySocketGatewayTransport(
        profile: paired.profile,
        deviceToken: paired.deviceToken,
      );
      try {
        expect(await transport.listProjects(), isNotEmpty);
      } finally {
        await transport.close(force: true);
      }
    }
  });
}

class _MemorySecureStore implements GatewaySecureStore {
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
