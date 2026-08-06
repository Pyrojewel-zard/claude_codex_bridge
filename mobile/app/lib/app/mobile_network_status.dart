import 'package:flutter/services.dart';

/// Coarse, non-identifying network evidence used only for LAN guidance.
///
/// CCB Mobile deliberately does not read SSID, BSSID, addresses, or any other
/// network identity. Gateway reachability and the paired device token remain
/// authoritative.
class MobileNetworkStatus {
  const MobileNetworkStatus({
    required this.supported,
    required this.connected,
    required this.wifi,
    required this.ethernet,
    required this.cellular,
    required this.vpn,
  });

  const MobileNetworkStatus.unsupported()
    : supported = false,
      connected = false,
      wifi = false,
      ethernet = false,
      cellular = false,
      vpn = false;

  factory MobileNetworkStatus.fromMap(Map<Object?, Object?> value) {
    return MobileNetworkStatus(
      supported: value['supported'] == true,
      connected: value['connected'] == true,
      wifi: value['wifi'] == true,
      ethernet: value['ethernet'] == true,
      cellular: value['cellular'] == true,
      vpn: value['vpn'] == true,
    );
  }

  final bool supported;
  final bool connected;
  final bool wifi;
  final bool ethernet;
  final bool cellular;
  final bool vpn;

  bool get hasLocalNetworkTransport => wifi || ethernet;
}

abstract interface class MobileNetworkStatusPlatform {
  Future<MobileNetworkStatus> read();
}

class MethodChannelMobileNetworkStatusPlatform
    implements MobileNetworkStatusPlatform {
  const MethodChannelMobileNetworkStatusPlatform();

  static const _channel = MethodChannel('io.ccb.mobile/network_status');

  @override
  Future<MobileNetworkStatus> read() async {
    try {
      final value = await _channel.invokeMethod<Map<Object?, Object?>>(
        'readNetworkStatus',
      );
      return value == null
          ? const MobileNetworkStatus.unsupported()
          : MobileNetworkStatus.fromMap(value);
    } on PlatformException {
      return const MobileNetworkStatus.unsupported();
    } on MissingPluginException {
      return const MobileNetworkStatus.unsupported();
    }
  }
}
