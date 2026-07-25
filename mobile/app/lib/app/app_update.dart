const ccbMobileDefaultVersion = '8.3.1+8030001';
const ccbMobileDefaultApkDownloadUrl =
    'https://github.com/bfly123/claude_code_bridge/releases/latest';

const ccbMobileCurrentVersion = String.fromEnvironment(
  'CCB_MOBILE_VERSION',
  defaultValue: ccbMobileDefaultVersion,
);

const ccbMobileApkDownloadUrl = String.fromEnvironment(
  'CCB_MOBILE_APK_URL',
  defaultValue: ccbMobileDefaultApkDownloadUrl,
);

class CcbMobileUpdateInfo {
  const CcbMobileUpdateInfo({
    this.version = ccbMobileCurrentVersion,
    this.apkDownloadUrl = ccbMobileApkDownloadUrl,
  });

  final String version;
  final String apkDownloadUrl;
}
