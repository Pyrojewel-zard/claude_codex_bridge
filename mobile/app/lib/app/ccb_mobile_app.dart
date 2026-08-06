import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../features/project_home/project_home_screen.dart';
import '../l10n/ccb_mobile_localizations.dart';
import '../pairing/gateway_pairing.dart';
import '../repository/fake_mobile_ccb_repository.dart';
import 'app_theme.dart';
import 'app_update.dart';
import 'background_connection.dart';
import 'mobile_network_status.dart';

class CcbMobileApp extends StatefulWidget {
  const CcbMobileApp({
    this.enableProductOnboarding = true,
    this.themePreferenceStore,
    this.backgroundConnectionPreferenceStore,
    this.backgroundConnectionPlatform,
    this.mobileNetworkStatusPlatform,
    this.profileStore,
    this.updateService,
    this.automaticUpdateCheck = true,
    this.androidPlatformOverride,
    this.installApk = installCcbMobileApk,
    super.key,
  });

  final bool enableProductOnboarding;
  final CcbThemePreferenceStore? themePreferenceStore;
  final CcbBackgroundConnectionPreferenceStore?
  backgroundConnectionPreferenceStore;
  final BackgroundConnectionPlatform? backgroundConnectionPlatform;
  final MobileNetworkStatusPlatform? mobileNetworkStatusPlatform;
  final GatewayHostProfileStore? profileStore;
  final CcbMobileUpdateService? updateService;
  final bool automaticUpdateCheck;
  final bool? androidPlatformOverride;
  final Future<void> Function(File apk) installApk;

  @override
  State<CcbMobileApp> createState() => _CcbMobileAppState();
}

class _CcbMobileAppState extends State<CcbMobileApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  late final CcbThemePreferenceStore _themePreferenceStore =
      widget.themePreferenceStore ?? FlutterCcbThemePreferenceStore();
  late final CcbBackgroundConnectionPreferenceStore
  _backgroundConnectionPreferenceStore =
      widget.backgroundConnectionPreferenceStore ??
      FlutterCcbBackgroundConnectionPreferenceStore();
  CcbThemePreference _themePreference = CcbThemePreference.system;
  bool _backgroundConnectionEnabled = false;
  bool _backgroundConnectionPreferenceLoaded = false;

  @override
  void initState() {
    super.initState();
    _loadThemePreference();
    _loadBackgroundConnectionPreference();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_checkForUpdateOnLaunch());
    });
  }

  Future<void> _checkForUpdateOnLaunch() async {
    final isAndroid = widget.androidPlatformOverride ?? Platform.isAndroid;
    if (!widget.automaticUpdateCheck || !isAndroid) return;
    try {
      final service = widget.updateService ?? CcbMobileUpdateService();
      final result = await service.checkForUpdate();
      final release = result.release;
      final dialogContext = _navigatorKey.currentContext;
      if (!mounted || release == null || dialogContext == null) return;
      await _showUpdateDialog(dialogContext, service, release);
    } catch (_) {
      // Startup checks are best-effort and must never block the app.
    }
  }

  Future<void> _showUpdateDialog(
    BuildContext dialogContext,
    CcbMobileUpdateService service,
    CcbMobileRelease release,
  ) async {
    var downloading = false;
    String? errorMessage;
    await showDialog<void>(
      context: dialogContext,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          final strings = CcbMobileLocalizations.of(context);
          return AlertDialog(
            title: Text(strings.updateAvailableTitle),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(strings.newVersionAvailable(release.version)),
                if (downloading) ...[
                  const SizedBox(height: 16),
                  const LinearProgressIndicator(),
                  const SizedBox(height: 8),
                  Text(strings.downloadingVersion(release.version)),
                ],
                if (errorMessage != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    errorMessage!,
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
            actions: [
              TextButton(
                onPressed: downloading ? null : () => Navigator.of(context).pop(),
                child: Text(strings.later),
              ),
              FilledButton(
                key: const ValueKey('startup-update-install-button'),
                onPressed: downloading
                    ? null
                    : () async {
                        setDialogState(() {
                          downloading = true;
                          errorMessage = null;
                        });
                        try {
                          final apk = await service.downloadApk(release);
                          await widget.installApk(apk);
                          if (context.mounted) Navigator.of(context).pop();
                        } catch (_) {
                          if (context.mounted) {
                            setDialogState(() {
                              downloading = false;
                              errorMessage = strings.updateDownloadFailed;
                            });
                          }
                        }
                      },
                child: Text(strings.updateNow),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _loadThemePreference() async {
    final preference = await _themePreferenceStore.read();
    if (!mounted) {
      return;
    }
    setState(() {
      _themePreference = preference;
    });
  }

  void _setThemePreference(CcbThemePreference preference) {
    setState(() {
      _themePreference = preference;
    });
    unawaited(_themePreferenceStore.write(preference));
  }

  Future<void> _loadBackgroundConnectionPreference() async {
    final enabled = await _backgroundConnectionPreferenceStore.read();
    if (!mounted) {
      return;
    }
    setState(() {
      _backgroundConnectionEnabled = enabled;
      _backgroundConnectionPreferenceLoaded = true;
    });
  }

  void _setBackgroundConnectionEnabled(bool enabled) {
    setState(() {
      _backgroundConnectionEnabled = enabled;
      _backgroundConnectionPreferenceLoaded = true;
    });
    unawaited(_backgroundConnectionPreferenceStore.write(enabled));
  }

  @override
  Widget build(BuildContext context) {
    final repository = FakeMobileCcbRepository.demo();
    return MaterialApp(
      navigatorKey: _navigatorKey,
      onGenerateTitle: (context) => CcbMobileLocalizations.of(context).appTitle,
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      supportedLocales: CcbMobileLocalizations.supportedLocales,
      theme: ccbLightTheme(),
      darkTheme: ccbDarkTheme(),
      themeMode: _themePreference.themeMode,
      home: ProjectHomeScreen(
        repository: repository,
        profileStore: widget.profileStore,
        showOnboardingWhenUnpaired: widget.enableProductOnboarding,
        autoActivateStoredProfile: widget.enableProductOnboarding,
        themePreference: _themePreference,
        onThemePreferenceChanged: _setThemePreference,
        backgroundConnectionEnabled: _backgroundConnectionEnabled,
        backgroundConnectionPreferenceLoaded:
            _backgroundConnectionPreferenceLoaded,
        onBackgroundConnectionEnabledChanged: _setBackgroundConnectionEnabled,
        backgroundConnectionPlatform: widget.backgroundConnectionPlatform,
        mobileNetworkStatusPlatform: widget.mobileNetworkStatusPlatform,
      ),
    );
  }
}
