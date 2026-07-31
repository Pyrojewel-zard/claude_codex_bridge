import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../l10n/ccb_mobile_localizations.dart';
import 'gateway_pairing.dart';

class GatewayPairingScannerScreen extends StatefulWidget {
  const GatewayPairingScannerScreen({super.key});

  @override
  State<GatewayPairingScannerScreen> createState() =>
      _GatewayPairingScannerScreenState();
}

@visibleForTesting
MobileScannerController gatewayPairingScannerController() {
  return MobileScannerController(
    autoStart: false,
    detectionSpeed: DetectionSpeed.noDuplicates,
    formats: const [BarcodeFormat.qrCode],
  );
}

@visibleForTesting
String? gatewayPairingQrTextFromCapture(BarcodeCapture? capture) {
  if (capture == null) {
    return null;
  }
  for (final barcode in capture.barcodes) {
    final raw = barcode.rawValue?.trim();
    if (raw != null && raw.isNotEmpty) {
      return raw;
    }
  }
  return null;
}

class _GatewayPairingScannerScreenState
    extends State<GatewayPairingScannerScreen>
    with WidgetsBindingObserver {
  final MobileScannerController _controller = gatewayPairingScannerController();
  StreamSubscription<BarcodeCapture>? _barcodeSubscription;
  bool _handled = false;
  bool _scanningImage = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _listenForBarcodes();
    unawaited(_startCamera());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_disposeScanner());
    super.dispose();
  }

  Future<void> _disposeScanner() async {
    await _barcodeSubscription?.cancel();
    _barcodeSubscription = null;
    await _controller.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (gatewayPairingScannerLifecycleAction(
      state: state,
      isStarting: _controller.value.isStarting,
      hasCameraPermission: _controller.value.hasCameraPermission,
    )) {
      case GatewayPairingScannerLifecycleAction.start:
        _listenForBarcodes();
        unawaited(_startCamera());
      case GatewayPairingScannerLifecycleAction.stop:
        unawaited(_stopCamera());
      case GatewayPairingScannerLifecycleAction.ignore:
        return;
    }
  }

  void _listenForBarcodes() {
    _barcodeSubscription ??= _controller.barcodes.listen(
      _handleDetect,
      onError: (Object error, StackTrace stackTrace) {
        if (!mounted || _handled) {
          return;
        }
        setState(() {
          _error = gatewayPairingCameraErrorMessage(error);
        });
      },
      cancelOnError: false,
    );
  }

  Future<void> _startCamera() async {
    try {
      await _controller.start();
    } on MobileScannerException catch (error) {
      if (!mounted || _handled) {
        return;
      }
      setState(() {
        _error = gatewayPairingCameraErrorMessage(error);
      });
    }
  }

  Future<void> _stopCamera() async {
    await _barcodeSubscription?.cancel();
    _barcodeSubscription = null;
    await _controller.stop();
  }

  void _retryScanner() {
    setState(() {
      _error = null;
    });
    _listenForBarcodes();
    unawaited(_startCamera());
  }

  void _handleDetect(BarcodeCapture capture) {
    final raw = gatewayPairingQrTextFromCapture(capture);
    if (raw == null) {
      return;
    }
    _handleRawQrText(raw);
  }

  void _handleRawQrText(String raw) {
    if (_handled) {
      return;
    }
    try {
      final pairing = GatewayPairingPayload.fromQrText(raw.trim());
      _handled = true;
      unawaited(_controller.stop());
      Navigator.of(context).pop(pairing);
    } on FormatException catch (error) {
      setState(() {
        _error = error.message;
      });
    } catch (error) {
      setState(() {
        _error = error.toString();
      });
    }
  }

  Future<void> _scanFromImage() async {
    if (_scanningImage) {
      return;
    }
    setState(() {
      _error = null;
      _scanningImage = true;
    });
    try {
      final result = await FilePicker.pickFiles(
        allowMultiple: false,
        type: FileType.image,
      );
      final file =
          result == null || result.files.isEmpty ? null : result.files.single;
      final path = file?.path;
      if (path == null || path.isEmpty) {
        return;
      }
      final capture = await _controller.analyzeImage(
        path,
        formats: const [BarcodeFormat.qrCode],
      );
      if (!mounted || _handled) {
        return;
      }
      final raw = gatewayPairingQrTextFromCapture(capture);
      if (raw == null) {
        setState(() {
          _error = 'No pairing QR code was found in that image.';
        });
        return;
      }
      _handleRawQrText(raw);
    } on MobileScannerBarcodeException {
      if (!mounted || _handled) {
        return;
      }
      setState(() {
        _error = 'That image could not be decoded as a QR code.';
      });
    } on UnsupportedError {
      if (!mounted || _handled) {
        return;
      }
      setState(() {
        _error = 'Image QR scanning is not supported on this device.';
      });
    } catch (error) {
      if (!mounted || _handled) {
        return;
      }
      setState(() {
        _error = gatewayPairingImageScannerErrorMessage(error);
      });
    } finally {
      if (mounted) {
        setState(() {
          _scanningImage = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final strings = CcbMobileLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Scan Pairing QR')),
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(
            controller: _controller,
            useAppLifecycleState: false,
            tapToFocus: true,
            errorBuilder: _buildScannerError,
            placeholderBuilder:
                (context) => const ColoredBox(color: Colors.black),
          ),
          Align(
            alignment: Alignment.topCenter,
            child: SafeArea(
              child: Container(
                margin: const EdgeInsets.all(16),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: colorScheme.surface.withValues(alpha: 0.92),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  _error ?? 'Scan the CCB mobile pairing QR code',
                  key: const ValueKey('gateway-pairing-scan-status'),
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color:
                        _error == null
                            ? colorScheme.onSurface
                            : colorScheme.error,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          ),
          Center(child: IgnorePointer(child: _ScannerFrame(colorScheme))),
          Align(
            alignment: Alignment.bottomCenter,
            child: SafeArea(
              minimum: const EdgeInsets.all(16),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: colorScheme.surface.withValues(alpha: 0.92),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    alignment: WrapAlignment.center,
                    children: [
                      TextButton.icon(
                        key: const ValueKey(
                          'gateway-pairing-image-scan-button',
                        ),
                        onPressed: _scanningImage ? null : _scanFromImage,
                        icon:
                            _scanningImage
                                ? const SizedBox.square(
                                  dimension: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                                : const Icon(Icons.image_search),
                        label: Text(
                          _scanningImage ? 'Reading image' : 'From image',
                        ),
                      ),
                      TextButton.icon(
                        key: const ValueKey(
                          'gateway-pairing-scan-manual-button',
                        ),
                        onPressed: () => Navigator.of(context).pop(),
                        icon: const Icon(Icons.keyboard_outlined),
                        label: Text(strings.enterConnectionCode),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScannerError(
    BuildContext context,
    MobileScannerException error,
  ) {
    return GatewayPairingCameraErrorPanel(
      message: gatewayPairingCameraErrorMessage(error),
      onRetry: _retryScanner,
      onScanImage: _scanFromImage,
      onUseManualSetup: () => Navigator.of(context).pop(),
    );
  }
}

class _ScannerFrame extends StatelessWidget {
  const _ScannerFrame(this.colorScheme);

  final ColorScheme colorScheme;

  @override
  Widget build(BuildContext context) {
    const side = 260.0;
    const width = 4.0;
    return SizedBox.square(
      dimension: side,
      child: Stack(
        children: [
          _ScannerCorner(
            alignment: Alignment.topLeft,
            border: Border(
              left: BorderSide(color: colorScheme.primary, width: width),
              top: BorderSide(color: colorScheme.primary, width: width),
            ),
          ),
          _ScannerCorner(
            alignment: Alignment.topRight,
            border: Border(
              right: BorderSide(color: colorScheme.primary, width: width),
              top: BorderSide(color: colorScheme.primary, width: width),
            ),
          ),
          _ScannerCorner(
            alignment: Alignment.bottomLeft,
            border: Border(
              left: BorderSide(color: colorScheme.primary, width: width),
              bottom: BorderSide(color: colorScheme.primary, width: width),
            ),
          ),
          _ScannerCorner(
            alignment: Alignment.bottomRight,
            border: Border(
              right: BorderSide(color: colorScheme.primary, width: width),
              bottom: BorderSide(color: colorScheme.primary, width: width),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScannerCorner extends StatelessWidget {
  const _ScannerCorner({required this.alignment, required this.border});

  final Alignment alignment;
  final Border border;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: alignment,
      child: SizedBox.square(
        dimension: 36,
        child: DecoratedBox(
          decoration: BoxDecoration(
            border: border,
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }
}

@visibleForTesting
enum GatewayPairingScannerLifecycleAction { start, stop, ignore }

@visibleForTesting
GatewayPairingScannerLifecycleAction gatewayPairingScannerLifecycleAction({
  required AppLifecycleState state,
  required bool isStarting,
  required bool hasCameraPermission,
}) {
  if (isStarting || !hasCameraPermission) {
    return GatewayPairingScannerLifecycleAction.ignore;
  }
  return switch (state) {
    AppLifecycleState.resumed => GatewayPairingScannerLifecycleAction.start,
    AppLifecycleState.inactive => GatewayPairingScannerLifecycleAction.stop,
    AppLifecycleState.detached ||
    AppLifecycleState.hidden ||
    AppLifecycleState.paused => GatewayPairingScannerLifecycleAction.ignore,
  };
}

@visibleForTesting
String gatewayPairingCameraErrorMessage(Object error) {
  if (error is MobileScannerException) {
    return switch (error.errorCode) {
      MobileScannerErrorCode.permissionDenied =>
        'Camera permission denied. Enable camera access for CCB Mobile, scan an image, or enter a connection code.',
      MobileScannerErrorCode.unsupported =>
        'This device does not expose a usable camera. Scan an image or enter a connection code instead.',
      MobileScannerErrorCode.controllerInitializing =>
        'Camera is still starting. Try again, scan an image, or enter a connection code.',
      _ =>
        'Camera could not be opened. Try again, scan an image, or enter a connection code.',
    };
  }
  return 'Scanner could not start. Try again, scan an image, or enter a connection code.';
}

@visibleForTesting
String gatewayPairingImageScannerErrorMessage(Object error) {
  if (error is MobileScannerBarcodeException) {
    return 'That image could not be decoded as a QR code.';
  }
  return 'Image QR scanning failed. Choose another image or enter a connection code.';
}

class GatewayPairingCameraErrorPanel extends StatelessWidget {
  const GatewayPairingCameraErrorPanel({
    required this.message,
    this.onRetry,
    this.onScanImage,
    required this.onUseManualSetup,
    super.key,
  });

  final String message;
  final VoidCallback? onRetry;
  final VoidCallback? onScanImage;
  final VoidCallback onUseManualSetup;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final strings = CcbMobileLocalizations.of(context);
    final mediaQuery = MediaQuery.of(context);
    return ColoredBox(
      color: Colors.black,
      child: Center(
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: 360,
                maxHeight: mediaQuery.size.height - 48,
              ),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: colorScheme.surface,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: SingleChildScrollView(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.no_photography_outlined,
                          color: colorScheme.error,
                          size: 44,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Camera unavailable',
                          key: const ValueKey(
                            'gateway-pairing-scan-camera-error',
                          ),
                          style: Theme.of(context).textTheme.titleMedium,
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          message,
                          key: const ValueKey(
                            'gateway-pairing-scan-camera-message',
                          ),
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(color: colorScheme.onSurfaceVariant),
                        ),
                        const SizedBox(height: 16),
                        Wrap(
                          spacing: 12,
                          runSpacing: 8,
                          alignment: WrapAlignment.center,
                          children: [
                            if (onRetry != null)
                              OutlinedButton.icon(
                                key: const ValueKey(
                                  'gateway-pairing-scan-retry-button',
                                ),
                                onPressed: onRetry,
                                icon: const Icon(Icons.refresh),
                                label: const Text('Try camera again'),
                              ),
                            if (onScanImage != null)
                              OutlinedButton.icon(
                                key: const ValueKey(
                                  'gateway-pairing-image-scan-button',
                                ),
                                onPressed: onScanImage,
                                icon: const Icon(Icons.image_search),
                                label: const Text('From image'),
                              ),
                            FilledButton.icon(
                              key: const ValueKey(
                                'gateway-pairing-scan-manual-button',
                              ),
                              onPressed: onUseManualSetup,
                              icon: const Icon(Icons.keyboard_outlined),
                              label: Text(strings.enterConnectionCode),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
