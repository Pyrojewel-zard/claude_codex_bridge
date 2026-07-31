import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('release manifest permits network access and signed APK installation', () {
    final manifest = File(
      'android/app/src/main/AndroidManifest.xml',
    ).readAsStringSync();

    expect(manifest, contains('android.permission.INTERNET'));
    expect(manifest, contains('android.permission.REQUEST_INSTALL_PACKAGES'));
  });
}
