import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../../app/app_update.dart';
import '../../l10n/ccb_mobile_localizations.dart';
import '../../platform/external_url_opener.dart';

typedef ProjectHomeUpdateUrlLauncher = Future<bool> Function(String url);
typedef CcbMobileApkInstaller = Future<void> Function(File apk);

class ProjectHomeUpdatePanel extends StatefulWidget {
  const ProjectHomeUpdatePanel({
    this.updateInfo = const CcbMobileUpdateInfo(),
    this.updateService,
    this.installApk = installCcbMobileApk,
    this.openUpdateUrl = openExternalUrl,
    super.key,
  });

  final CcbMobileUpdateInfo updateInfo;
  final CcbMobileUpdateService? updateService;
  final CcbMobileApkInstaller installApk;
  final ProjectHomeUpdateUrlLauncher openUpdateUrl;

  @override
  State<ProjectHomeUpdatePanel> createState() => _ProjectHomeUpdatePanelState();
}

class _ProjectHomeUpdatePanelState extends State<ProjectHomeUpdatePanel> {
  late final CcbMobileUpdateService _updateService =
      widget.updateService ??
      CcbMobileUpdateService(currentVersion: widget.updateInfo.version);
  CcbMobileRelease? _release;
  String? _status;
  bool _checking = false;
  bool _installing = false;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final strings = CcbMobileLocalizations.of(context);
    final colorScheme = theme.colorScheme;
    return DecoratedBox(
      key: const ValueKey('project-home-update-panel'),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
        border: Border.all(color: colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.system_update_alt, color: colorScheme.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    strings.mobileUpdates,
                    style: theme.textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              strings.currentVersion(widget.updateInfo.version),
              key: const ValueKey('project-home-update-version'),
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 6),
            Text(
              _status ?? strings.mobileUpdatesDescription,
              key: const ValueKey('project-home-update-status'),
              style: theme.textTheme.bodyMedium?.copyWith(
                color: _release == null
                    ? colorScheme.onSurfaceVariant
                    : colorScheme.primary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              strings.mobileUpdateInstallNote,
              style: theme.textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (_release == null)
                  FilledButton.icon(
                    key: const ValueKey('project-home-update-check-button'),
                    onPressed: _checking ? null : () => unawaited(_check()),
                    icon: _checking
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh),
                    label: Text(
                      _checking
                          ? strings.checkingForUpdates
                          : strings.checkForUpdates,
                    ),
                  )
                else
                  FilledButton.icon(
                    key: const ValueKey('project-home-update-install-button'),
                    onPressed: _installing ? null : () => unawaited(_install()),
                    icon: _installing
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.download),
                    label: Text(
                      _installing
                          ? strings.downloadingUpdate
                          : strings.downloadAndInstall,
                    ),
                  ),
                OutlinedButton.icon(
                  key: const ValueKey('project-home-update-open-apk-button'),
                  onPressed: () => unawaited(_openDownload()),
                  icon: const Icon(Icons.open_in_browser),
                  label: Text(strings.openReleasePage),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _check() async {
    final strings = CcbMobileLocalizations.of(context);
    setState(() {
      _checking = true;
      _status = null;
    });
    try {
      final result = await _updateService.checkForUpdate();
      if (!mounted) return;
      setState(() {
        _release = result.release;
        _status = result.release == null
            ? strings.alreadyLatestVersion
            : strings.newVersionAvailable(result.release!.version);
      });
      final release = result.release;
      if (release != null) {
        await _showUpdateDialog(release);
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _status = strings.updateCheckFailed);
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _showUpdateDialog(CcbMobileRelease release) async {
    final strings = CcbMobileLocalizations.of(context);
    final install = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(strings.updateAvailableTitle),
        content: Text(strings.newVersionAvailable(release.version)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(strings.later),
          ),
          FilledButton(
            key: const ValueKey('manual-update-dialog-install-button'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(strings.updateNow),
          ),
        ],
      ),
    );
    if (install == true && mounted) {
      await _install();
    }
  }

  Future<void> _install() async {
    final release = _release;
    if (release == null) return;
    final strings = CcbMobileLocalizations.of(context);
    setState(() {
      _installing = true;
      _status = strings.downloadingVersion(release.version);
    });
    try {
      final apk = await _updateService.downloadApk(release);
      await widget.installApk(apk);
      if (mounted) setState(() => _status = strings.androidInstallerOpened);
    } catch (_) {
      if (mounted) setState(() => _status = strings.updateDownloadFailed);
    } finally {
      if (mounted) setState(() => _installing = false);
    }
  }

  Future<void> _openDownload() async {
    final strings = CcbMobileLocalizations.of(context);
    final opened = await widget.openUpdateUrl(
      _release?.releasePageUrl ?? widget.updateInfo.apkDownloadUrl,
    );
    if (!mounted || opened) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(strings.couldNotOpenUpdateUrl)));
  }
}
