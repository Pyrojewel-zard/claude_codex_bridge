import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('parses only coarse Android network transport evidence', () {
    final status = MobileNetworkStatus.fromMap(const {
      'supported': true,
      'connected': true,
      'wifi': true,
      'ethernet': false,
      'cellular': true,
      'vpn': true,
      'ssid': 'must be ignored',
    });

    expect(status.supported, isTrue);
    expect(status.connected, isTrue);
    expect(status.wifi, isTrue);
    expect(status.ethernet, isFalse);
    expect(status.cellular, isTrue);
    expect(status.vpn, isTrue);
    expect(status.hasLocalNetworkTransport, isTrue);
  });

  test(
    'method channel returns unsupported when native status is unavailable',
    () async {
      const channel = MethodChannel('io.ccb.mobile/network_status');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async => null);
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );

      final status =
          await const MethodChannelMobileNetworkStatusPlatform().read();

      expect(status.supported, isFalse);
      expect(status.hasLocalNetworkTransport, isFalse);
    },
  );
}
