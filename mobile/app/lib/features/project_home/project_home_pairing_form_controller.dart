import 'package:flutter/widgets.dart';

import '../../pairing/gateway_pairing.dart';
import 'project_home_pairing_request.dart';

class ProjectHomePairingFormController {
  ProjectHomePairingFormController({String connectionCodeText = ''})
    : connectionCodeController = TextEditingController(
        text: connectionCodeText,
      );

  final TextEditingController connectionCodeController;
  GatewayPairingPayload? _scannedPairing;

  ProjectHomePairingRequest buildRequest({
    GatewayPairingPayload? pairingOverride,
  }) {
    final typedCode = connectionCodeController.text.trim();
    return buildProjectHomePairingRequest(
      connectionCodeText: typedCode,
      pairingOverride:
          pairingOverride ?? (typedCode.isEmpty ? _scannedPairing : null),
    );
  }

  void applyScannedPairing(GatewayPairingPayload pairing) {
    connectionCodeController.clear();
    _scannedPairing = pairing;
  }

  void clearPairingCode() {
    _scannedPairing = null;
    connectionCodeController.clear();
  }

  void dispose() {
    connectionCodeController.dispose();
  }
}
