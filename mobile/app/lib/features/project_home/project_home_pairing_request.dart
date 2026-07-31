import '../../pairing/gateway_pairing.dart';

const projectHomePairingDefaultDeviceName = 'Phone';

class ProjectHomePairingRequest {
  const ProjectHomePairingRequest({
    required this.pairing,
    required this.deviceName,
  });

  final GatewayPairingPayload pairing;
  final String deviceName;
}

class ProjectHomePairingRequestException implements Exception {
  const ProjectHomePairingRequestException(this.message);

  final String message;

  @override
  String toString() {
    return message;
  }
}

ProjectHomePairingRequest buildProjectHomePairingRequest({
  required String connectionCodeText,
  GatewayPairingPayload? pairingOverride,
}) {
  if (pairingOverride != null) {
    return ProjectHomePairingRequest(
      pairing: pairingOverride,
      deviceName: projectHomePairingDefaultDeviceName,
    );
  }

  final connectionCode = connectionCodeText.trim();
  if (connectionCode.isEmpty) {
    throw const ProjectHomePairingRequestException(
      'Connection code is required',
    );
  }
  try {
    return ProjectHomePairingRequest(
      pairing: GatewayPairingPayload.fromConnectionText(connectionCode),
      deviceName: projectHomePairingDefaultDeviceName,
    );
  } on FormatException {
    throw const ProjectHomePairingRequestException(
      'Connection code is invalid',
    );
  }
}
