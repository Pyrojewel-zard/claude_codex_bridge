import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ccb_mobile/app/app_update.dart';

void main() {
  test('compiled update version stays aligned with pubspec', () {
    final pubspec = File('pubspec.yaml').readAsLinesSync();
    final versionLine = pubspec.singleWhere(
      (line) => line.startsWith('version:'),
    );
    expect(versionLine.split(':').last.trim(), ccbMobileDefaultVersion);
  });

  test('compares numeric mobile versions without lexical ordering bugs', () {
    expect(compareCcbMobileVersions('8.10.0', '8.9.9'), greaterThan(0));
    expect(compareCcbMobileVersions('8.3.1+99', '8.3.1+1'), 0);
    expect(compareCcbMobileVersions('8.3', '8.3.0'), 0);
  });

  test('checks a proxy after the official GitHub API fails', () async {
    final calls = <Uri>[];
    final service = CcbMobileUpdateService(
      currentVersion: '8.3.1+8030001',
      proxyPrefixes: const ['https://proxy.example/'],
      fetchBytes: (uri, _) async {
        calls.add(uri);
        if (uri.toString() == ccbMobileReleaseApiUrl) {
          throw const SocketException('blocked');
        }
        if (uri.toString() == ccbMobileLatestManifestUrl) {
          throw const SocketException('github blocked');
        }
        if (uri.path.endsWith('.json')) {
          return utf8.encode(jsonEncode(_manifest));
        }
        return utf8.encode(jsonEncode(_githubRelease));
      },
    );

    final result = await service.checkForUpdate();

    expect(result.release?.version, '9.0.0');
    expect(calls.first.toString(), ccbMobileReleaseApiUrl);
    expect(calls[1].toString(), ccbMobileLatestManifestUrl);
    expect(
      calls[2].toString(),
      'https://proxy.example/$ccbMobileLatestManifestUrl',
    );
  });

  test('does not offer a release with an older Android version code', () async {
    final service = CcbMobileUpdateService(
      currentVersion: '9.0.0+9000001',
      proxyPrefixes: const [],
      fetchBytes: (uri, _) async => utf8.encode(
        jsonEncode(uri.path.endsWith('.json') ? _manifest : _githubRelease),
      ),
    );

    final result = await service.checkForUpdate();

    expect(result.updateAvailable, isFalse);
  });

  test('discovers a tagged manifest through jsDelivr and a proxy', () async {
    final calls = <Uri>[];
    final service = CcbMobileUpdateService(
      currentVersion: '8.3.1+8030001',
      proxyPrefixes: const ['https://proxy.example/'],
      fetchBytes: (uri, _) async {
        calls.add(uri);
        if (uri.toString() == ccbMobileJsdelivrVersionsUrl) {
          return utf8.encode(
            jsonEncode(<String, Object?>{
              'versions': <String>['next', '9.0.0', '8.3.0'],
            }),
          );
        }
        if (uri.toString() == 'https://proxy.example/$_manifestUrl') {
          return utf8.encode(jsonEncode(_manifest));
        }
        throw const SocketException('blocked');
      },
    );

    final result = await service.checkForUpdate();

    expect(result.release?.version, '9.0.0');
    expect(calls, contains(Uri.parse(ccbMobileJsdelivrVersionsUrl)));
    expect(calls, contains(Uri.parse(_manifestUrl)));
    expect(calls, contains(Uri.parse('https://proxy.example/$_manifestUrl')));
  });

  test('rejects an unsafe version from a fallback manifest', () async {
    final unsafeManifest = <String, Object?>{
      ..._manifest,
      'version': '../../update',
    };
    final service = CcbMobileUpdateService(
      proxyPrefixes: const [],
      fetchBytes: (uri, _) async {
        if (uri.toString() == ccbMobileReleaseApiUrl) {
          throw const SocketException('blocked');
        }
        return utf8.encode(jsonEncode(unsafeManifest));
      },
    );

    await expectLater(
      service.checkForUpdate(),
      throwsA(isA<CcbMobileUpdateException>()),
    );
  });

  test('rejects a bad APK checksum then downloads from a proxy', () async {
    final temp = await Directory.systemTemp.createTemp('ccb-update-test-');
    addTearDown(() => temp.delete(recursive: true));
    final apkBytes = utf8.encode('signed-apk-fixture');
    final release = CcbMobileRelease(
      version: '9.0.0',
      versionCode: 9000000,
      apkDownloadUrl: _apkUrl,
      sha256: sha256.convert(apkBytes).toString(),
      sizeBytes: apkBytes.length,
      releasePageUrl: _releasePageUrl,
    );
    final calls = <Uri>[];
    final service = CcbMobileUpdateService(
      proxyPrefixes: const ['https://proxy.example/'],
      downloadDirectory: () async => temp,
      downloadFile: (uri, target, _) async {
        calls.add(uri);
        final bytes = uri.host == 'github.com'
            ? utf8.encode('tampered-apk-data')
            : apkBytes;
        await target.writeAsBytes(bytes);
      },
    );

    final file = await service.downloadApk(release);

    expect(await file.readAsBytes(), apkBytes);
    expect(calls.map((uri) => uri.host), ['github.com', 'proxy.example']);
  });
}

const _apkUrl =
    'https://github.com/SeemSeam/claude_codex_bridge/releases/download/v9.0.0/ccb-mobile-v9.0.0.apk';
const _manifestUrl =
    'https://github.com/SeemSeam/claude_codex_bridge/releases/download/v9.0.0/ccb-mobile-v9.0.0.json';
const _releasePageUrl =
    'https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v9.0.0';

const _githubRelease = <String, Object?>{
  'tag_name': 'v9.0.0',
  'html_url': _releasePageUrl,
  'assets': <Object?>[
    <String, Object?>{
      'name': 'ccb-mobile-v9.0.0.json',
      'browser_download_url': _manifestUrl,
    },
  ],
};

const _manifest = <String, Object?>{
  'schema_version': 1,
  'version': '9.0.0',
  'android': <String, Object?>{
    'application_id': 'io.ccb.mobile.ccb_mobile',
    'version_code': 9000000,
    'version_name': '9.0.0',
    'download_url': _apkUrl,
    'sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'size_bytes': 10,
  },
};
