import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

const ccbMobileDefaultVersion = '8.3.1+8030001';
const ccbMobileDefaultApkDownloadUrl =
    'https://github.com/SeemSeam/claude_codex_bridge/releases/latest';
const ccbMobileReleaseApiUrl =
    'https://api.github.com/repos/SeemSeam/claude_codex_bridge/releases/latest';
const ccbMobileLatestManifestUrl =
    'https://github.com/SeemSeam/claude_codex_bridge/releases/latest/download/ccb-mobile-latest.json';
const ccbMobileJsdelivrVersionsUrl =
    'https://data.jsdelivr.com/v1/package/gh/SeemSeam/claude_codex_bridge';
const _ccbMobileGithubReleasePath =
    '/SeemSeam/claude_codex_bridge/releases/';

const ccbMobileCurrentVersion = String.fromEnvironment(
  'CCB_MOBILE_VERSION',
  defaultValue: ccbMobileDefaultVersion,
);

const ccbMobileApkDownloadUrl = String.fromEnvironment(
  'CCB_MOBILE_APK_URL',
  defaultValue: ccbMobileDefaultApkDownloadUrl,
);

const ccbMobileGithubProxyPrefixes = <String>[
  'https://gh-proxy.com/',
  'https://ghfast.top/',
  'https://ghproxy.net/',
];

class CcbMobileUpdateInfo {
  const CcbMobileUpdateInfo({
    this.version = ccbMobileCurrentVersion,
    this.apkDownloadUrl = ccbMobileApkDownloadUrl,
  });

  final String version;
  final String apkDownloadUrl;
}

class CcbMobileRelease {
  const CcbMobileRelease({
    required this.version,
    required this.versionCode,
    required this.apkDownloadUrl,
    required this.sha256,
    required this.sizeBytes,
    required this.releasePageUrl,
  });

  final String version;
  final int versionCode;
  final String apkDownloadUrl;
  final String sha256;
  final int sizeBytes;
  final String releasePageUrl;
}

class CcbMobileUpdateCheckResult {
  const CcbMobileUpdateCheckResult({required this.currentVersion, this.release});

  final String currentVersion;
  final CcbMobileRelease? release;

  bool get updateAvailable => release != null;
}

class CcbMobileUpdateException implements Exception {
  const CcbMobileUpdateException(this.message);

  final String message;

  @override
  String toString() => message;
}

typedef CcbMobileUpdateBytesFetcher = Future<List<int>> Function(
  Uri uri,
  int maxBytes,
);
typedef CcbMobileUpdateFileDownloader = Future<void> Function(
  Uri uri,
  File target,
  int maxBytes,
);

class CcbMobileUpdateService {
  CcbMobileUpdateService({
    this.currentVersion = ccbMobileCurrentVersion,
    List<String>? proxyPrefixes,
    CcbMobileUpdateBytesFetcher? fetchBytes,
    CcbMobileUpdateFileDownloader? downloadFile,
    Future<Directory> Function()? downloadDirectory,
  }) : proxyPrefixes = proxyPrefixes ?? ccbMobileGithubProxyPrefixes,
       _fetchBytes = fetchBytes ?? _httpGetBytes,
       _downloadFile = downloadFile ?? _httpDownloadFile,
       _downloadDirectory = downloadDirectory ?? getTemporaryDirectory;

  final String currentVersion;
  final List<String> proxyPrefixes;
  final CcbMobileUpdateBytesFetcher _fetchBytes;
  final CcbMobileUpdateFileDownloader _downloadFile;
  final Future<Directory> Function() _downloadDirectory;

  Future<CcbMobileUpdateCheckResult> checkForUpdate() async {
    Object? lastError;
    try {
      final uri = Uri.parse(ccbMobileReleaseApiUrl);
      final releasePayload = _jsonObject(
        await _fetchBytes(uri, 2 * 1024 * 1024),
        source: uri,
      );
      _validateGithubReleasePayload(releasePayload);
      final release = await _releaseFromGithubPayload(releasePayload);
      return _checkResult(release);
    } catch (error) {
      lastError = error;
    }
    for (final uri in _sourceUris(ccbMobileLatestManifestUrl)) {
      try {
        final manifest = _jsonObject(
          await _fetchBytes(uri, 256 * 1024),
          source: uri,
        );
        final version = _requiredVersion(
          manifest['version'],
          'release version',
        );
        final release = _parseManifest(
          manifest,
          expectedVersion: version,
          releasePageUrl: ccbMobileDefaultApkDownloadUrl,
        );
        return _checkResult(release);
      } catch (error) {
        lastError = error;
      }
    }
    try {
      final versionsUri = Uri.parse(ccbMobileJsdelivrVersionsUrl);
      final versionsPayload = _jsonObject(
        await _fetchBytes(versionsUri, 256 * 1024),
        source: versionsUri,
      );
      final version = _latestReleaseVersion(versionsPayload);
      final manifestUrl =
          'https://github.com/SeemSeam/claude_codex_bridge/releases/download/v$version/ccb-mobile-v$version.json';
      for (final uri in _sourceUris(manifestUrl)) {
        try {
          final manifest = _jsonObject(
            await _fetchBytes(uri, 256 * 1024),
            source: uri,
          );
          final release = _parseManifest(
            manifest,
            expectedVersion: version,
            releasePageUrl:
                'https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v$version',
          );
          return _checkResult(release);
        } catch (error) {
          lastError = error;
        }
      }
    } catch (error) {
      lastError = error;
    }
    throw CcbMobileUpdateException(
      'Unable to check the CCB Mobile release: ${lastError ?? 'no update source available'}',
    );
  }

  Future<File> downloadApk(CcbMobileRelease release) async {
    Object? lastError;
    final directory = await _downloadDirectory();
    await directory.create(recursive: true);
    final file = File(
      p.join(directory.path, 'ccb-mobile-v${release.version}.apk'),
    );
    for (final uri in _sourceUris(release.apkDownloadUrl)) {
      try {
        await _downloadFile(uri, file, _maximumApkBytes(release));
        if (release.sizeBytes > 0 && await file.length() != release.sizeBytes) {
          throw const CcbMobileUpdateException('Downloaded APK size mismatch');
        }
        final actualDigest = (await sha256.bind(file.openRead()).first).toString();
        if (actualDigest.toLowerCase() != release.sha256.toLowerCase()) {
          throw const CcbMobileUpdateException('Downloaded APK checksum mismatch');
        }
        return file;
      } catch (error) {
        lastError = error;
        if (await file.exists()) {
          await file.delete();
        }
      }
    }
    throw CcbMobileUpdateException(
      'Unable to download the CCB Mobile APK: ${lastError ?? 'no download source available'}',
    );
  }

  Future<CcbMobileRelease> _releaseFromGithubPayload(
    Map<String, Object?> payload,
  ) async {
    final tag = _requiredText(payload['tag_name'], 'release tag');
    final version = _requiredVersion(
      tag.startsWith('v') ? tag.substring(1) : tag,
      'release version',
    );
    final assets = payload['assets'];
    if (assets is! List) {
      throw const FormatException('release assets are missing');
    }
    final manifestName = 'ccb-mobile-$tag.json';
    final manifestUrl = _assetUrl(assets, manifestName);
    Object? lastError;
    for (final uri in _sourceUris(manifestUrl)) {
      try {
        final manifest = _jsonObject(
          await _fetchBytes(uri, 256 * 1024),
          source: uri,
        );
        return _parseManifest(
          manifest,
          expectedVersion: version,
          releasePageUrl:
              _optionalGithubUrl(payload['html_url']) ??
              ccbMobileDefaultApkDownloadUrl,
        );
      } catch (error) {
        lastError = error;
      }
    }
    throw CcbMobileUpdateException(
      'Unable to load the mobile release manifest: $lastError',
    );
  }

  CcbMobileRelease _parseManifest(
    Map<String, Object?> manifest, {
    required String expectedVersion,
    required String releasePageUrl,
  }) {
    if (manifest['schema_version'] != 1 ||
        manifest['version']?.toString() != expectedVersion) {
      throw const FormatException('mobile release manifest version mismatch');
    }
    final android = manifest['android'];
    if (android is! Map ||
        android['application_id'] != 'io.ccb.mobile.ccb_mobile') {
      throw const FormatException('mobile release manifest is not for this app');
    }
    final sha = _requiredText(android['sha256'], 'APK checksum').toLowerCase();
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(sha)) {
      throw const FormatException('invalid APK checksum');
    }
    final versionName = _requiredText(
      android['version_name'],
      'Android version',
    );
    if (versionName != expectedVersion) {
      throw const FormatException('Android version does not match release tag');
    }
    final apkUrl = _requiredCcbReleaseUrl(android['download_url'], 'APK URL');
    if (!Uri.parse(apkUrl).path.endsWith('/ccb-mobile-v$expectedVersion.apk')) {
      throw const FormatException('APK URL does not match release tag');
    }
    return CcbMobileRelease(
      version: versionName,
      versionCode: _requiredInt(android['version_code'], 'Android version code'),
      apkDownloadUrl: apkUrl,
      sha256: sha,
      sizeBytes: _requiredInt(android['size_bytes'], 'APK size'),
      releasePageUrl: releasePageUrl,
    );
  }

  bool _isNewer(CcbMobileRelease release) {
    final currentCode = _buildCode(currentVersion);
    if (currentCode != null) {
      return release.versionCode > currentCode;
    }
    return compareCcbMobileVersions(release.version, currentVersion) > 0;
  }

  CcbMobileUpdateCheckResult _checkResult(CcbMobileRelease release) =>
      CcbMobileUpdateCheckResult(
        currentVersion: currentVersion,
        release: _isNewer(release) ? release : null,
      );

  Iterable<Uri> _sourceUris(String original) sync* {
    final uri = Uri.parse(original);
    if (!_isAllowedGithubUri(uri)) {
      throw FormatException('update URL is not an allowed GitHub URL: $uri');
    }
    yield uri;
    for (final prefix in proxyPrefixes) {
      final normalized = prefix.endsWith('/') ? prefix : '$prefix/';
      final proxyUri = Uri.parse('$normalized$original');
      if (proxyUri.scheme != 'https' || proxyUri.userInfo.isNotEmpty) {
        throw FormatException('update proxy must use HTTPS: $prefix');
      }
      yield proxyUri;
    }
  }
}

String _latestReleaseVersion(Map<String, Object?> payload) {
  final versions = payload['versions'];
  if (versions is! List) {
    throw const FormatException('jsDelivr release versions are missing');
  }
  for (final value in versions) {
    final version = value?.toString().trim() ?? '';
    if (RegExp(r'^\d+\.\d+\.\d+$').hasMatch(version)) {
      return version;
    }
  }
  throw const FormatException('jsDelivr has no valid release version');
}

void _validateGithubReleasePayload(Map<String, Object?> payload) {
  final tag = _requiredText(payload['tag_name'], 'release tag');
  final assets = payload['assets'];
  if (assets is! List) {
    throw const FormatException('release assets are missing');
  }
  _assetUrl(assets, 'ccb-mobile-$tag.json');
}

Future<void> installCcbMobileApk(File apk) async {
  final result = await OpenFilex.open(
    apk.path,
    type: 'application/vnd.android.package-archive',
  );
  if (result.type != ResultType.done) {
    throw CcbMobileUpdateException(result.message);
  }
}

int compareCcbMobileVersions(String left, String right) {
  final leftParts = _versionParts(left);
  final rightParts = _versionParts(right);
  final length = leftParts.length > rightParts.length
      ? leftParts.length
      : rightParts.length;
  for (var index = 0; index < length; index += 1) {
    final leftValue = index < leftParts.length ? leftParts[index] : 0;
    final rightValue = index < rightParts.length ? rightParts[index] : 0;
    if (leftValue != rightValue) {
      return leftValue.compareTo(rightValue);
    }
  }
  return 0;
}

List<int> _versionParts(String value) => value
    .split('+')
    .first
    .split('.')
    .map((part) => int.tryParse(part) ?? 0)
    .toList(growable: false);

int? _buildCode(String value) {
  final parts = value.split('+');
  return parts.length == 2 ? int.tryParse(parts.last) : null;
}

int _maximumApkBytes(CcbMobileRelease release) {
  const hardLimit = 256 * 1024 * 1024;
  if (release.sizeBytes <= 0 || release.sizeBytes > hardLimit) {
    throw const FormatException('APK size is outside the allowed range');
  }
  return release.sizeBytes + 1;
}

Map<String, Object?> _jsonObject(List<int> bytes, {required Uri source}) {
  final decoded = jsonDecode(utf8.decode(bytes));
  if (decoded is! Map) {
    throw FormatException('expected a JSON object from $source');
  }
  return {for (final entry in decoded.entries) entry.key.toString(): entry.value};
}

String _assetUrl(List<Object?> assets, String expectedName) {
  for (final asset in assets) {
    if (asset is Map && asset['name'] == expectedName) {
      return _requiredCcbReleaseUrl(
        asset['browser_download_url'],
        expectedName,
      );
    }
  }
  throw FormatException('release asset is missing: $expectedName');
}

String _requiredText(Object? value, String name) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty) {
    throw FormatException('$name is missing');
  }
  return text;
}

String _requiredVersion(Object? value, String name) {
  final version = _requiredText(value, name);
  if (!RegExp(r'^\d+\.\d+\.\d+$').hasMatch(version)) {
    throw FormatException('$name is invalid');
  }
  return version;
}

int _requiredInt(Object? value, String name) {
  final parsed = value is int ? value : int.tryParse(value?.toString() ?? '');
  if (parsed == null || parsed < 0) {
    throw FormatException('$name is invalid');
  }
  return parsed;
}

String _requiredGithubUrl(Object? value, String name) {
  final text = _requiredText(value, name);
  final uri = Uri.parse(text);
  if (!_isAllowedGithubUri(uri)) {
    throw FormatException('$name is not an allowed GitHub URL');
  }
  return text;
}

String _requiredCcbReleaseUrl(Object? value, String name) {
  final text = _requiredGithubUrl(value, name);
  final uri = Uri.parse(text);
  if (uri.host != 'github.com' ||
      !uri.path.startsWith(_ccbMobileGithubReleasePath)) {
    throw FormatException('$name is not a CCB Mobile release URL');
  }
  return text;
}

String? _optionalGithubUrl(Object? value) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty) {
    return null;
  }
  final uri = Uri.tryParse(text);
  return uri != null && _isAllowedGithubUri(uri) ? text : null;
}

bool _isAllowedGithubUri(Uri uri) =>
    uri.scheme == 'https' &&
    (uri.host == 'github.com' || uri.host == 'api.github.com');

Future<List<int>> _httpGetBytes(Uri uri, int maxBytes) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
  try {
    final request = await client.getUrl(uri).timeout(const Duration(seconds: 10));
    request.headers.set(HttpHeaders.acceptHeader, 'application/json, */*');
    request.headers.set(
      HttpHeaders.userAgentHeader,
      'CCB-Mobile/$ccbMobileCurrentVersion',
    );
    final response = await request.close().timeout(const Duration(seconds: 15));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      await response.drain<void>();
      throw HttpException('HTTP ${response.statusCode}', uri: uri);
    }
    if (response.contentLength > maxBytes) {
      await response.drain<void>();
      throw const CcbMobileUpdateException('Update response is too large');
    }
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 30))) {
      bytes.addAll(chunk);
      if (bytes.length > maxBytes) {
        throw const CcbMobileUpdateException('Update response is too large');
      }
    }
    return bytes;
  } finally {
    client.close(force: true);
  }
}

Future<void> _httpDownloadFile(Uri uri, File target, int maxBytes) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
  IOSink? sink;
  try {
    final request = await client.getUrl(uri).timeout(const Duration(seconds: 10));
    request.headers.set(HttpHeaders.acceptHeader, 'application/octet-stream');
    request.headers.set(
      HttpHeaders.userAgentHeader,
      'CCB-Mobile/$ccbMobileCurrentVersion',
    );
    final response = await request.close().timeout(const Duration(seconds: 15));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      await response.drain<void>();
      throw HttpException('HTTP ${response.statusCode}', uri: uri);
    }
    if (response.contentLength > maxBytes) {
      await response.drain<void>();
      throw const CcbMobileUpdateException('APK response is too large');
    }
    sink = target.openWrite();
    var received = 0;
    await for (final chunk in response.timeout(const Duration(seconds: 30))) {
      received += chunk.length;
      if (received > maxBytes) {
        throw const CcbMobileUpdateException('APK response is too large');
      }
      sink.add(chunk);
    }
    await sink.flush();
  } finally {
    await sink?.close();
    client.close(force: true);
  }
}
