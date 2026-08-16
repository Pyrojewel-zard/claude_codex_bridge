import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets(
    'reconnecting LAN keeps the profile and shows a cellular network notice',
    (tester) async {
      final secureStore = MemorySecureStore();
      final profileStore = GatewayHostProfileStore(secureStore: secureStore);
      final profile = GatewayPairedHost(
        profile: GatewayHostProfile(
          hostId: 'host-lan',
          deviceId: 'phone-lan',
          routeProvider: RouteProvider(
            kind: RouteProviderKind.lan,
            gatewayUrl: Uri.parse('http://192.168.1.20:8787'),
          ),
          scopes: const {'view'},
        ),
        deviceToken: 'device-token',
        projectId: 'host-lan',
      );
      await profileStore.save(profile);
      final networkStatus = _RecordingMobileNetworkStatusPlatform(
        const MobileNetworkStatus(
          supported: true,
          connected: true,
          wifi: false,
          ethernet: false,
          cellular: true,
          vpn: false,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: ProjectHomeScreen(
            repository: FakeMobileCcbRepository.demo(),
            profileStore: profileStore,
            autoActivateStoredProfile: true,
            showOnboardingWhenUnpaired: true,
            mobileNetworkStatusPlatform: networkStatus,
            gatewayRepositoryFactory: (_) => _OfflineGatewayRepository(),
            gatewayTerminalTransportFactory:
                (_) => RecordingTerminalTransport(),
          ),
        ),
      );
      for (var attempt = 0; attempt < 30; attempt += 1) {
        await tester.pump(const Duration(milliseconds: 50));
        if (find
            .byKey(const ValueKey('gateway-lan-network-banner'))
            .evaluate()
            .isNotEmpty) {
          break;
        }
      }

      expect(
        find.byKey(const ValueKey('gateway-lan-network-banner')),
        findsOneWidget,
      );
      expect(find.text('Connect to the computer\'s Wi-Fi'), findsOneWidget);
      expect(find.textContaining('192.168.1.20:8787'), findsOneWidget);
      expect(networkStatus.readCalls, greaterThanOrEqualTo(1));
      expect(
        await profileStore.read(hostId: 'host-lan', deviceId: 'phone-lan'),
        isNotNull,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    },
  );
}

class _RecordingMobileNetworkStatusPlatform
    implements MobileNetworkStatusPlatform {
  _RecordingMobileNetworkStatusPlatform(this.status);

  final MobileNetworkStatus status;
  var readCalls = 0;

  @override
  Future<MobileNetworkStatus> read() async {
    readCalls += 1;
    return status;
  }
}

class _OfflineGatewayRepository extends RecordingGatewayRepository
    implements MobileGatewayProfileHealthProbe {
  @override
  Future<GatewayHealth> health() async {
    throw TimeoutException('LAN gateway unavailable');
  }

  @override
  Future<GatewayDevice> device() {
    throw StateError('device must not be queried after failed health');
  }
}
