import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late MobileScannerPlatform originalPlatform;

  setUp(() {
    originalPlatform = MobileScannerPlatform.instance;
  });

  tearDown(() {
    MobileScannerPlatform.instance = originalPlatform;
  });

  test('scanner controller uses one managed QR-only camera lifecycle', () {
    final controller = gatewayPairingScannerController();
    addTearDown(controller.dispose);

    expect(controller.autoStart, isFalse);
    expect(controller.detectionSpeed, DetectionSpeed.noDuplicates);
    expect(controller.formats, [BarcodeFormat.qrCode]);
  });

  test('scanner lifecycle ignores permission and startup transitions', () {
    expect(
      gatewayPairingScannerLifecycleAction(
        state: AppLifecycleState.inactive,
        isStarting: true,
        hasCameraPermission: false,
      ),
      GatewayPairingScannerLifecycleAction.ignore,
    );
    expect(
      gatewayPairingScannerLifecycleAction(
        state: AppLifecycleState.inactive,
        isStarting: false,
        hasCameraPermission: false,
      ),
      GatewayPairingScannerLifecycleAction.ignore,
    );
    expect(
      gatewayPairingScannerLifecycleAction(
        state: AppLifecycleState.resumed,
        isStarting: false,
        hasCameraPermission: true,
      ),
      GatewayPairingScannerLifecycleAction.start,
    );
    expect(
      gatewayPairingScannerLifecycleAction(
        state: AppLifecycleState.inactive,
        isStarting: false,
        hasCameraPermission: true,
      ),
      GatewayPairingScannerLifecycleAction.stop,
    );
  });

  test('capture extraction skips empty barcode values', () {
    const capture = BarcodeCapture(
      barcodes: [
        Barcode(rawValue: '  '),
        Barcode(rawValue: '  pairing payload  '),
      ],
    );

    expect(gatewayPairingQrTextFromCapture(capture), 'pairing payload');
    expect(gatewayPairingQrTextFromCapture(null), isNull);
  });

  testWidgets('embedded scanner returns a valid pairing payload', (
    tester,
  ) async {
    final platform = _FakeMobileScannerPlatform();
    MobileScannerPlatform.instance = platform;
    GatewayPairingPayload? seenPairing;

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            return ElevatedButton(
              onPressed: () async {
                seenPairing = await Navigator.of(context).push(
                  MaterialPageRoute<GatewayPairingPayload>(
                    builder: (context) => const GatewayPairingScannerScreen(),
                  ),
                );
              },
              child: const Text('scan'),
            );
          },
        ),
      ),
    );

    await tester.tap(find.text('scan'));
    await tester.pumpAndSettle();

    expect(find.byType(MobileScanner), findsOneWidget);
    expect(
      find.byKey(const ValueKey('gateway-pairing-image-scan-button')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('gateway-pairing-scan-manual-button')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('gateway-pairing-native-scan-button')),
      findsNothing,
    );

    platform.addBarcode(
      BarcodeCapture(barcodes: [Barcode(rawValue: _validPairingQrText())]),
    );
    await tester.pumpAndSettle();

    expect(platform.startCalls, 1);
    expect(seenPairing?.pairingCode, 'qr-code');
    expect(seenPairing?.gatewayUrl.toString(), 'http://127.0.0.1:8787');
  });

  testWidgets(
    'camera error panel keeps image and connection code paths available',
    (tester) async {
      var retried = false;
      var imageSelected = false;
      var manualSelected = false;

      await tester.pumpWidget(
        MaterialApp(
          home: GatewayPairingCameraErrorPanel(
            message:
                'Camera permission denied. Enable camera access for CCB Mobile, scan an image, or enter a connection code.',
            onRetry: () {
              retried = true;
            },
            onScanImage: () {
              imageSelected = true;
            },
            onUseManualSetup: () {
              manualSelected = true;
            },
          ),
        ),
      );

      expect(find.text('Camera unavailable'), findsOneWidget);
      await tester.tap(
        find.byKey(const ValueKey('gateway-pairing-scan-retry-button')),
      );
      await tester.tap(
        find.byKey(const ValueKey('gateway-pairing-image-scan-button')),
      );
      await tester.tap(
        find.byKey(const ValueKey('gateway-pairing-scan-manual-button')),
      );

      expect(retried, isTrue);
      expect(imageSelected, isTrue);
      expect(manualSelected, isTrue);
      expect(find.text('Enter connection code'), findsOneWidget);
    },
  );

  test(
    'camera permission error has image and connection code alternatives',
    () {
      final message = gatewayPairingCameraErrorMessage(
        const MobileScannerException(
          errorCode: MobileScannerErrorCode.permissionDenied,
        ),
      );

      expect(message, contains('Camera permission denied'));
      expect(message, contains('enter a connection code'));
    },
  );

  test('image scanner errors do not expose implementation details', () {
    final message = gatewayPairingImageScannerErrorMessage(
      const MobileScannerBarcodeException('ML Kit internal failure'),
    );

    expect(message, 'That image could not be decoded as a QR code.');
    expect(message, isNot(contains('ML Kit')));
  });
}

class _FakeMobileScannerPlatform extends MobileScannerPlatform {
  final StreamController<BarcodeCapture> _barcodeController =
      StreamController<BarcodeCapture>.broadcast();
  var startCalls = 0;

  @override
  Stream<BarcodeCapture?> get barcodesStream => _barcodeController.stream;

  @override
  Stream<TorchState> get torchStateStream =>
      Stream.value(TorchState.unavailable);

  @override
  Stream<double> get zoomScaleStateStream => Stream.value(1);

  @override
  Future<MobileScannerViewAttributes> start(StartOptions startOptions) async {
    startCalls += 1;
    expect(startOptions.formats, [BarcodeFormat.qrCode]);
    return const MobileScannerViewAttributes(
      cameraDirection: CameraFacing.back,
      currentTorchMode: TorchState.unavailable,
      size: Size(1080, 1920),
      numberOfCameras: 1,
    );
  }

  @override
  Future<void> stop() async {}

  @override
  Widget buildCameraView() {
    return const ColoredBox(
      key: ValueKey('fake-camera-preview'),
      color: Colors.black,
    );
  }

  void addBarcode(BarcodeCapture capture) {
    _barcodeController.add(capture);
  }

  @override
  Future<void> dispose() async {
    await _barcodeController.close();
  }
}

String _validPairingQrText() {
  return jsonEncode({
    'pairing_code': 'qr-code',
    'claim_endpoint': 'http://127.0.0.1:8787/v1/pairing/claim',
    'route_provider': 'lan',
    'gateway_url': 'http://127.0.0.1:8787',
    'scopes': ['view', 'message_submit'],
  });
}
