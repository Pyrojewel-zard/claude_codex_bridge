import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Android exposes coarse LAN network status without Wi-Fi identity', () {
    final manifest =
        File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    final activity =
        File(
          'android/app/src/main/kotlin/io/ccb/mobile/ccb_mobile/MainActivity.kt',
        ).readAsStringSync();

    expect(manifest, contains('android.permission.ACCESS_NETWORK_STATE'));
    expect(activity, contains('io.ccb.mobile/network_status'));
    expect(activity, contains('readNetworkStatus'));
    expect(activity, contains('ConnectivityManager'));
    expect(activity, contains('NetworkCapabilities.TRANSPORT_WIFI'));
    expect(activity, contains('NetworkCapabilities.TRANSPORT_ETHERNET'));
    expect(activity, contains('NetworkCapabilities.TRANSPORT_CELLULAR'));
    expect(activity, contains('NetworkCapabilities.TRANSPORT_VPN'));
    expect(activity, isNot(contains('WifiManager')));
    expect(activity, isNot(contains('SSID')));
    expect(activity, isNot(contains('BSSID')));
  });
}
