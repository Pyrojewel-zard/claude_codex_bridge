import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/ccb_mobile.dart';

import 'support/project_home_test_fakes.dart';

void main() {
  testWidgets('Android startup check prompts when a new release is available', (
    tester,
  ) async {
    final service = _StartupUpdateService();
    File? installed;
    await tester.pumpWidget(
      CcbMobileApp(
        androidPlatformOverride: true,
        updateService: service,
        installApk: (apk) async {
          installed = apk;
        },
        themePreferenceStore: _ThemeStore(),
        backgroundConnectionPreferenceStore: _BackgroundStore(),
        profileStore: GatewayHostProfileStore(secureStore: MemorySecureStore()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('CCB Mobile update available'), findsOneWidget);
    expect(find.text('Version 9.0.0 is available.'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('startup-update-install-button')));
    await tester.pumpAndSettle();

    expect(installed?.path, '/tmp/ccb-mobile-v9.0.0.apk');
    expect(find.text('CCB Mobile update available'), findsNothing);
  });
}

class _StartupUpdateService extends CcbMobileUpdateService {
  static const release = CcbMobileRelease(
    version: '9.0.0',
    versionCode: 9000000,
    apkDownloadUrl:
        'https://github.com/SeemSeam/claude_codex_bridge/releases/download/v9.0.0/ccb-mobile-v9.0.0.apk',
    sha256:
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    sizeBytes: 10,
    releasePageUrl:
        'https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v9.0.0',
  );

  @override
  Future<CcbMobileUpdateCheckResult> checkForUpdate() async =>
      const CcbMobileUpdateCheckResult(
        currentVersion: ccbMobileCurrentVersion,
        release: release,
      );

  @override
  Future<File> downloadApk(CcbMobileRelease release) async =>
      File('/tmp/ccb-mobile-v${release.version}.apk');
}

class _ThemeStore implements CcbThemePreferenceStore {
  @override
  Future<CcbThemePreference> read() async => CcbThemePreference.system;

  @override
  Future<void> write(CcbThemePreference preference) async {}
}

class _BackgroundStore implements CcbBackgroundConnectionPreferenceStore {
  @override
  Future<bool> read() async => false;

  @override
  Future<void> write(bool enabled) async {}
}
