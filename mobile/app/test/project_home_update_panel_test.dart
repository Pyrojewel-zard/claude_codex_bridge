import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/app/app_update.dart';
import 'package:ccb_mobile/features/project_home/project_home_update_panel.dart';

void main() {
  test('default update info exposes current version and release URL', () {
    const info = CcbMobileUpdateInfo();

    expect(info.version, ccbMobileDefaultVersion);
    expect(info.apkDownloadUrl, ccbMobileDefaultApkDownloadUrl);
    expect(Uri.parse(info.apkDownloadUrl).scheme, 'https');
  });

  testWidgets('update panel shows version and opens configured download URL', (
    tester,
  ) async {
    final openedUrls = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProjectHomeUpdatePanel(
            updateInfo: const CcbMobileUpdateInfo(
              version: '9.1.0+9010000',
              apkDownloadUrl: 'https://example.com/ccb-mobile.apk',
            ),
            openUpdateUrl: (url) async {
              openedUrls.add(url);
              return true;
            },
          ),
        ),
      ),
    );

    expect(
      find.byKey(const ValueKey('project-home-update-panel')),
      findsOneWidget,
    );
    expect(find.text('Current version: 9.1.0+9010000'), findsOneWidget);
    expect(find.text('Open release page'), findsOneWidget);
    expect(find.text('Check for updates'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('project-home-update-open-apk-button')),
    );
    await tester.pumpAndSettle();

    expect(openedUrls, ['https://example.com/ccb-mobile.apk']);
  });

  testWidgets('manual check opens the update dialog and installs from it', (
    tester,
  ) async {
    final service = _FakeUpdateService(updateAvailable: true);
    File? installed;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProjectHomeUpdatePanel(
            updateService: service,
            installApk: (apk) async {
              installed = apk;
            },
          ),
        ),
      ),
    );

    await tester.tap(
      find.byKey(const ValueKey('project-home-update-check-button')),
    );
    await tester.pumpAndSettle();
    expect(find.text('CCB Mobile update available'), findsOneWidget);
    expect(find.text('Version 9.0.0 is available.'), findsNWidgets(2));

    await tester.tap(
      find.byKey(const ValueKey('manual-update-dialog-install-button')),
    );
    await tester.pumpAndSettle();
    expect(installed?.path, '/tmp/ccb-mobile-v9.0.0.apk');
    expect(
      find.text('APK verified. Android installer opened.'),
      findsOneWidget,
    );
  });

  testWidgets('manual check reports that the installed version is current', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProjectHomeUpdatePanel(
            updateService: _FakeUpdateService(updateAvailable: false),
          ),
        ),
      ),
    );

    await tester.tap(
      find.byKey(const ValueKey('project-home-update-check-button')),
    );
    await tester.pumpAndSettle();
    expect(find.text('You are up to date.'), findsOneWidget);
  });

  testWidgets('update panel reports failed browser handoff', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ProjectHomeUpdatePanel(
            updateInfo: const CcbMobileUpdateInfo(
              apkDownloadUrl: 'https://example.com/ccb-mobile.apk',
            ),
            openUpdateUrl: (_) async => false,
          ),
        ),
      ),
    );

    await tester.tap(
      find.byKey(const ValueKey('project-home-update-open-apk-button')),
    );
    await tester.pumpAndSettle();

    expect(find.text('Could not open update download'), findsOneWidget);
  });
}

const _release = CcbMobileRelease(
  version: '9.0.0',
  versionCode: 9000000,
  apkDownloadUrl:
      'https://github.com/SeemSeam/claude_codex_bridge/releases/download/v9.0.0/ccb-mobile-v9.0.0.apk',
  sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  sizeBytes: 10,
  releasePageUrl:
      'https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v9.0.0',
);

class _FakeUpdateService extends CcbMobileUpdateService {
  _FakeUpdateService({required this.updateAvailable});

  final bool updateAvailable;

  @override
  Future<CcbMobileUpdateCheckResult> checkForUpdate() async =>
      CcbMobileUpdateCheckResult(
        currentVersion: ccbMobileCurrentVersion,
        release: updateAvailable ? _release : null,
      );

  @override
  Future<File> downloadApk(CcbMobileRelease release) async =>
      File('/tmp/ccb-mobile-v${release.version}.apk');
}
