import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:ccb_mobile/features/project_home/gateway_lan_network_banner.dart';

void main() {
  const wifi = MobileNetworkStatus(
    supported: true,
    connected: true,
    wifi: true,
    ethernet: false,
    cellular: false,
    vpn: false,
  );
  const cellular = MobileNetworkStatus(
    supported: true,
    connected: true,
    wifi: false,
    ethernet: false,
    cellular: true,
    vpn: false,
  );

  test('LAN notice is route scoped and shown only while reconnecting', () {
    expect(
      gatewayLanNetworkNoticeFor(
        routeKind: RouteProviderKind.relay,
        reconnecting: true,
        status: cellular,
      ),
      isNull,
    );
    expect(
      gatewayLanNetworkNoticeFor(
        routeKind: RouteProviderKind.lan,
        reconnecting: false,
        status: cellular,
      ),
      isNull,
    );
    expect(
      gatewayLanNetworkNoticeFor(
        routeKind: RouteProviderKind.lan,
        reconnecting: true,
        status: cellular,
      ),
      GatewayLanNetworkNoticeKind.localNetworkRequired,
    );
    expect(
      gatewayLanNetworkNoticeFor(
        routeKind: RouteProviderKind.lan,
        reconnecting: true,
        status: wifi,
      ),
      GatewayLanNetworkNoticeKind.gatewayUnreachable,
    );
    expect(
      gatewayLanNetworkNoticeFor(
        routeKind: RouteProviderKind.lan,
        reconnecting: true,
        status: const MobileNetworkStatus(
          supported: true,
          connected: true,
          wifi: true,
          ethernet: false,
          cellular: false,
          vpn: true,
        ),
      ),
      GatewayLanNetworkNoticeKind.vpnMayBlock,
    );
  });

  test(
    'pairing warning preserves hotspot override and skips healthy Wi-Fi',
    () {
      expect(gatewayLanPairingWarningFor(wifi), isNull);
      expect(
        gatewayLanPairingWarningFor(cellular),
        GatewayLanNetworkNoticeKind.localNetworkRequired,
      );
      expect(
        gatewayLanPairingWarningFor(const MobileNetworkStatus.unsupported()),
        isNull,
      );
    },
  );

  testWidgets('LAN banner is localized and fits a narrow phone', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('zh'),
        supportedLocales: CcbMobileLocalizations.supportedLocales,
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: Scaffold(
          body: GatewayLanNetworkBanner(
            kind: GatewayLanNetworkNoticeKind.gatewayUnreachable,
            gatewayHost: '192.168.1.20:8787',
            onRetry: () {},
            onDiagnostics: () {},
          ),
        ),
      ),
    );

    expect(find.text('已连接本地网络，但电脑端不可达'), findsOneWidget);
    expect(find.textContaining('访客/设备隔离网络'), findsOneWidget);
    expect(find.textContaining('ccb update mobile'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
    expect(find.text('诊断'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
