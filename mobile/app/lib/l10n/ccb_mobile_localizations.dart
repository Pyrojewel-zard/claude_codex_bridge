import 'package:flutter/widgets.dart';

class CcbMobileLocalizations {
  const CcbMobileLocalizations(this.locale);

  final Locale locale;

  static const supportedLocales = <Locale>[Locale('en'), Locale('zh')];

  static CcbMobileLocalizations of(BuildContext context) {
    return CcbMobileLocalizations(Localizations.localeOf(context));
  }

  bool get isChinese => locale.languageCode.toLowerCase() == 'zh';

  String get appTitle => 'CCB Mobile';

  String get connectTitle => isChinese ? '连接 CCB Mobile' : 'Connect CCB Mobile';

  String get connectDescription =>
      isChinese
          ? '把手机作为电脑上 CCB 项目的实时查看和输入界面。'
          : 'Use your phone as a live view and input surface for CCB projects running on your computer.';

  String get installTailscaleTitle =>
      isChinese ? '安装 Tailscale' : 'Install Tailscale';

  String get installTailscaleBody =>
      isChinese
          ? '在这台手机上安装 Tailscale，并登录到和电脑相同的 tailnet。'
          : 'Install Tailscale on this phone and sign in to the same tailnet as your computer.';

  String get runComputerCommandTitle =>
      isChinese ? '在电脑上运行一条命令' : 'Run one command on the computer';

  String get runComputerCommandBody =>
      isChinese
          ? '在任意已启用 CCB 的终端运行这条命令。它会启动服务器级网关并打印配对二维码。'
          : 'In any CCB-enabled terminal, run this command. It starts the server-wide gateway and prints a pairing QR.';

  String get scanQrTitle => isChinese ? '扫描二维码' : 'Scan the QR';

  String get scanQrBody =>
      isChinese
          ? '保持手机上的 Tailscale VPN 开启，然后扫描电脑显示的二维码。'
          : 'Keep Tailscale VPN enabled on the phone, then scan the QR shown by the computer.';

  String get pairing => isChinese ? '正在配对' : 'Pairing';

  String get scanComputerQr => isChinese ? '扫描电脑二维码' : 'Scan computer QR';

  String get pairGateway => isChinese ? '配对网关' : 'Pair Gateway';

  String get gatewayUrl => isChinese ? '网关地址' : 'Gateway URL';

  String get pairingCode => isChinese ? '配对码' : 'Pairing code';

  String get deviceName => isChinese ? '设备名称' : 'Device name';

  String get route => isChinese ? '路由' : 'Route';

  String get scanQr => isChinese ? '扫码' : 'Scan QR';

  String get claim => isChinese ? '连接' : 'Claim';

  String get couldNotLoadProject =>
      isChinese ? '无法加载项目' : 'Could not load project';

  String get couldNotLoadProjects =>
      isChinese ? '无法加载项目列表' : 'Could not load projects';

  String get retry => isChinese ? '重试' : 'Retry';

  String get rePair => isChinese ? '重新配对' : 'Re-pair';

  String get deleteMessage => isChinese ? '删除' : 'Delete';

  String get collapseMessage => isChinese ? '折叠消息' : 'Collapse message';

  String get expandMessage => isChinese ? '展开消息' : 'Expand message';

  String get backToProjects => isChinese ? '返回项目列表' : 'Back to projects';

  String get useFakeDemo => isChinese ? '使用演示模式' : 'Use fake demo';

  String get backToSetup => isChinese ? '返回设置' : 'Back to setup';

  String get refreshProjects => isChinese ? '刷新项目' : 'Refresh projects';

  String get noCcbProjectsFound =>
      isChinese ? '未找到 CCB 项目' : 'No CCB projects found';

  String get noAgents => isChinese ? '没有 agent' : 'No agents';

  String get noAgent => isChinese ? '无 agent' : 'no agent';

  String get notifications => isChinese ? '通知' : 'Notifications';

  String get diagnostics => isChinese ? '诊断' : 'Diagnostics';

  String get settings => isChinese ? '设置' : 'Settings';

  String get theme => isChinese ? '主题' : 'Theme';

  String get themeDescription =>
      isChinese
          ? '选择适合长时间查看对话、日志和项目状态的显示风格。'
          : 'Choose a display style for long chat, log, and project sessions.';

  String get themeSystem => isChinese ? '跟随系统' : 'System';

  String get themeLight => isChinese ? '浅色' : 'Light';

  String get themeDark => isChinese ? '深色' : 'Dark';

  String get backgroundConnection =>
      isChinese ? '保持后台连接' : 'Keep connected in background';

  String get backgroundConnectionDescription =>
      isChinese
          ? '配对后使用系统常驻通知保持实时事件连接。会增加耗电，可随时关闭。'
          : 'After pairing, keep the live event connection active with a persistent system notification. This uses more battery and can be disabled anytime.';

  String get backgroundConnectionCouldNotStart =>
      isChinese
          ? '无法启动后台连接，设置已关闭。'
          : 'Could not start the background connection. The setting was disabled.';

  String get backgroundConnectionSystemSettings =>
      isChinese ? '系统后台权限' : 'System background access';

  String get backgroundConnectionSystemRestricted =>
      isChinese
          ? 'Android 已限制此 App 的后台活动。点击打开系统设置。'
          : 'Android is restricting background activity for this app. Tap to open system settings.';

  String get backgroundConnectionSystemOptimized =>
      isChinese
          ? '系统仍在进行电池优化，部分设备可能中断连接。点击检查系统设置。'
          : 'Battery optimization is active and may interrupt the connection on some devices. Tap to review system settings.';

  String get backgroundConnectionSystemUnrestricted =>
      isChinese
          ? '系统未限制后台活动。点击可查看系统设置。'
          : 'System background activity is unrestricted. Tap to review system settings.';

  String get backgroundConnectionSystemUnknown =>
      isChinese
          ? '无法读取系统后台限制状态。点击打开系统设置。'
          : 'Could not read the system background restriction state. Tap to open system settings.';

  String get backgroundConnectionSystemSettingsCouldNotOpen =>
      isChinese
          ? '无法打开 Android 系统设置。'
          : 'Could not open Android system settings.';

  String get mobileUpdates =>
      isChinese ? 'CCB Mobile 更新' : 'CCB Mobile updates';

  String currentVersion(String version) {
    return isChinese ? '当前版本：$version' : 'Current version: $version';
  }

  String get mobileUpdatesDescription =>
      isChinese
          ? '打开官方发布页下载新的 APK，并通过相同签名渠道覆盖安装。'
          : 'Open the official release page to download a newer APK and install it over the same signed channel.';

  String get mobileUpdateInstallNote =>
      isChinese
          ? '覆盖安装会保留已配对资料。若 Android 提示签名冲突，说明曾安装不同签名的测试包，需要一次性卸载后再安装正式包。'
          : 'Cover-installing preserves paired data. If Android reports a signature conflict, an older test APK used a different signature and must be uninstalled once before installing the official build.';

  String get openApkDownload => isChinese ? '打开 APK 下载' : 'Open APK download';

  String get couldNotOpenUpdateUrl =>
      isChinese ? '无法打开更新下载链接' : 'Could not open update download';

  String get projects => isChinese ? '项目' : 'Projects';

  String get openTerminal => isChinese ? '打开终端' : 'Open Terminal';

  String get returnToChat => isChinese ? '返回对话' : 'Return to Chat';

  String messageAgent(String agentName) {
    return isChinese ? '给 $agentName 发消息' : 'Message $agentName';
  }

  String get openMessageInput => isChinese ? '展开消息输入框' : 'Open message input';

  String get collapseMessageInput =>
      isChinese ? '折叠消息输入框' : 'Collapse message input';

  String get attachFile => isChinese ? '添加附件' : 'Attach file';

  String get sendTab => isChinese ? '发送 Tab' : 'Send Tab';

  String get sendEsc => isChinese ? '发送 Esc' : 'Send Esc';

  String get sendMessage => isChinese ? '发送消息' : 'Send message';

  String get sendingMessage => isChinese ? '正在发送' : 'Sending message';

  String get photoImage => isChinese ? '图片' : 'Photo/Image';

  String get file => isChinese ? '文件' : 'File';

  String get cancel => isChinese ? '取消' : 'Cancel';

  String get open => isChinese ? '打开' : 'Open';

  String get removeAttachment => isChinese ? '移除附件' : 'Remove attachment';

  String get openAttachment => isChinese ? '打开附件' : 'Open attachment';

  String get downloadAttachment => isChinese ? '下载附件' : 'Download attachment';

  String openAttachmentQuestion(String fileName) {
    return isChinese
        ? '使用系统应用打开 $fileName？'
        : 'Open $fileName with another app?';
  }

  String openUrlQuestion(String url) {
    return isChinese
        ? '使用浏览器或其他应用打开这个链接？\n$url'
        : 'Open this link with a browser or another app?\n$url';
  }

  String get openUrl => isChinese ? '打开链接' : 'Open link';

  String get couldNotOpenUrl => isChinese ? '无法打开链接' : 'Could not open link';

  String get refreshConversation => isChinese ? '刷新对话' : 'Refresh conversation';

  String get newMessages => isChinese ? '新消息' : 'New messages';

  String get communicating => isChinese ? '通讯中' : 'Communicating';

  String agentCompleted(String agentName) {
    return isChinese ? '$agentName 已完成' : '$agentName completed';
  }

  String executionStatus(String label) {
    if (!isChinese) {
      return label;
    }
    return switch (label) {
      'Idle' => '空闲',
      'Working' => 'Working',
      'Exception' => '异常',
      _ => label,
    };
  }

  String get stopProject => isChinese ? '停止项目' : 'Stop project';

  String stopProjectQuestion(String projectName) {
    return isChinese ? '停止 $projectName？' : 'Stop $projectName?';
  }

  String get stop => isChinese ? '停止' : 'Stop';

  String get runtime => isChinese ? '运行模式' : 'Runtime';

  String runtimeModeLabel(String label) {
    if (!isChinese) {
      return label;
    }
    return switch (label) {
      'Fake' => '演示',
      'Paired' => '已配对',
      _ => label,
    };
  }

  String get gatewayProfile => isChinese ? '网关配置' : 'Gateway profile';

  String get checking => isChinese ? '检查中' : 'Checking';

  String get checkRoute => isChinese ? '检查路由' : 'Check Route';

  String get checkingRoute => isChinese ? '正在检查路由' : 'Checking route';

  String get routeUnchecked => isChinese ? '路由未检查' : 'Route unchecked';
}
