import 'package:flutter/material.dart';

import '../../app/app_theme.dart';
import '../../app/background_connection.dart';
import '../../l10n/ccb_mobile_localizations.dart';
import 'gateway_pairing_panel.dart';
import 'project_home_update_panel.dart';

class ProjectHomeOnboardingScaffold extends StatelessWidget {
  const ProjectHomeOnboardingScaffold({
    required this.connectionCodeController,
    required this.claiming,
    required this.loadingProfiles,
    required this.onScan,
    required this.onClaim,
    this.themePreference = CcbThemePreference.system,
    this.onThemePreferenceChanged,
    this.backgroundConnectionEnabled = false,
    this.onBackgroundConnectionEnabledChanged,
    this.backgroundConnectionSystemStatus,
    this.backgroundConnectionSystemStatusLoading = false,
    this.onOpenBackgroundConnectionSystemSettings,
    this.onClose,
    super.key,
  });

  final TextEditingController connectionCodeController;
  final bool claiming;
  final bool loadingProfiles;
  final CcbThemePreference themePreference;
  final bool backgroundConnectionEnabled;
  final BackgroundConnectionSystemStatus? backgroundConnectionSystemStatus;
  final bool backgroundConnectionSystemStatusLoading;
  final ValueChanged<CcbThemePreference>? onThemePreferenceChanged;
  final ValueChanged<bool>? onBackgroundConnectionEnabledChanged;
  final VoidCallback? onOpenBackgroundConnectionSystemSettings;
  final VoidCallback onScan;
  final VoidCallback onClaim;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final strings = CcbMobileLocalizations.of(context);
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          key: const ValueKey('project-home-onboarding'),
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (onClose != null) ...[
                Align(
                  alignment: Alignment.centerLeft,
                  child: IconButton(
                    key: const ValueKey('project-home-settings-back-button'),
                    tooltip: strings.backToProjects,
                    onPressed: onClose,
                    icon: const Icon(Icons.arrow_back),
                  ),
                ),
                const SizedBox(height: 4),
              ],
              Icon(
                Icons.mobile_friendly,
                size: 54,
                color: theme.colorScheme.primary,
              ),
              const SizedBox(height: 16),
              Text(
                strings.connectTitle,
                key: const ValueKey('project-home-onboarding-title'),
                style: theme.textTheme.headlineSmall,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                strings.connectDescription,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              _OnboardingStep(
                icon: Icons.terminal,
                title: strings.runComputerCommandTitle,
                body: strings.runComputerCommandBody,
                code: 'ccb update mobile',
              ),
              _OnboardingStep(
                icon: Icons.qr_code_scanner,
                title: strings.scanQrTitle,
                body: strings.scanQrBody,
              ),
              const SizedBox(height: 12),
              FilledButton.icon(
                key: const ValueKey('project-home-onboarding-scan-button'),
                onPressed: claiming || loadingProfiles ? null : onScan,
                icon:
                    claiming
                        ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                        : const Icon(Icons.qr_code_scanner),
                label: Text(
                  claiming ? strings.pairing : strings.scanComputerQr,
                ),
              ),
              const SizedBox(height: 16),
              GatewayPairingPanel(
                connectionCodeController: connectionCodeController,
                claiming: claiming,
                onClaim: onClaim,
              ),
              const SizedBox(height: 16),
              _ThemePreferenceSection(
                themePreference: themePreference,
                onThemePreferenceChanged: onThemePreferenceChanged,
              ),
              const SizedBox(height: 16),
              _BackgroundConnectionSection(
                enabled: backgroundConnectionEnabled,
                onChanged: onBackgroundConnectionEnabledChanged,
                systemStatus: backgroundConnectionSystemStatus,
                systemStatusLoading: backgroundConnectionSystemStatusLoading,
                onOpenSystemSettings: onOpenBackgroundConnectionSystemSettings,
              ),
              const SizedBox(height: 16),
              const ProjectHomeUpdatePanel(),
            ],
          ),
        ),
      ),
    );
  }
}

class _BackgroundConnectionSection extends StatelessWidget {
  const _BackgroundConnectionSection({
    required this.enabled,
    required this.onChanged,
    required this.systemStatus,
    required this.systemStatusLoading,
    required this.onOpenSystemSettings,
  });

  final bool enabled;
  final ValueChanged<bool>? onChanged;
  final BackgroundConnectionSystemStatus? systemStatus;
  final bool systemStatusLoading;
  final VoidCallback? onOpenSystemSettings;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final strings = CcbMobileLocalizations.of(context);
    return Material(
      color: colorScheme.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          SwitchListTile(
            key: const ValueKey('background-connection-switch'),
            value: enabled,
            onChanged: onChanged,
            secondary: Icon(
              Icons.sync_lock_outlined,
              color: colorScheme.primary,
            ),
            title: Text(strings.backgroundConnection),
            subtitle: Text(strings.backgroundConnectionDescription),
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
          ListTile(
            key: const ValueKey('background-connection-system-settings'),
            onTap: systemStatusLoading ? null : onOpenSystemSettings,
            leading:
                systemStatusLoading
                    ? Icon(
                      Icons.sync_outlined,
                      color: colorScheme.onSurfaceVariant,
                    )
                    : Icon(
                      _systemStatusIcon,
                      color: _systemStatusColor(colorScheme),
                    ),
            title: Text(strings.backgroundConnectionSystemSettings),
            subtitle: Text(_systemStatusDescription(strings)),
            trailing: const Icon(Icons.open_in_new),
          ),
        ],
      ),
    );
  }

  IconData get _systemStatusIcon {
    final status = systemStatus;
    if (status == null) {
      return Icons.help_outline;
    }
    if (status.isRestricted) {
      return Icons.warning_amber_outlined;
    }
    if (!status.batteryOptimizationExempt) {
      return Icons.battery_saver_outlined;
    }
    return Icons.check_circle_outline;
  }

  Color _systemStatusColor(ColorScheme colorScheme) {
    final status = systemStatus;
    if (status == null) {
      return colorScheme.onSurfaceVariant;
    }
    if (status.isRestricted) {
      return colorScheme.error;
    }
    if (!status.batteryOptimizationExempt) {
      return colorScheme.tertiary;
    }
    return colorScheme.primary;
  }

  String _systemStatusDescription(CcbMobileLocalizations strings) {
    final status = systemStatus;
    if (status == null) {
      return strings.backgroundConnectionSystemUnknown;
    }
    if (status.isRestricted) {
      return strings.backgroundConnectionSystemRestricted;
    }
    if (!status.batteryOptimizationExempt) {
      return strings.backgroundConnectionSystemOptimized;
    }
    return strings.backgroundConnectionSystemUnrestricted;
  }
}

class ProjectHomeOnboardingLoadingScaffold extends StatelessWidget {
  const ProjectHomeOnboardingLoadingScaffold({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: SafeArea(
        child: Center(
          key: ValueKey('project-home-onboarding-loading'),
          child: CircularProgressIndicator(),
        ),
      ),
    );
  }
}

class _ThemePreferenceSection extends StatelessWidget {
  const _ThemePreferenceSection({
    required this.themePreference,
    required this.onThemePreferenceChanged,
  });

  final CcbThemePreference themePreference;
  final ValueChanged<CcbThemePreference>? onThemePreferenceChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final strings = CcbMobileLocalizations.of(context);
    final colorScheme = theme.colorScheme;
    final enabled = onThemePreferenceChanged != null;
    return DecoratedBox(
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
                Icon(Icons.palette_outlined, color: colorScheme.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    strings.theme,
                    style: theme.textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              strings.themeDescription,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 12),
            SegmentedButton<CcbThemePreference>(
              key: const ValueKey('theme-preference-segments'),
              selected: {themePreference},
              onSelectionChanged:
                  enabled
                      ? (selection) {
                        if (selection.isNotEmpty) {
                          onThemePreferenceChanged!(selection.first);
                        }
                      }
                      : null,
              segments: [
                ButtonSegment(
                  value: CcbThemePreference.system,
                  icon: const Icon(Icons.brightness_auto_outlined),
                  label: Text(
                    strings.themeSystem,
                    key: const ValueKey('theme-option-system'),
                  ),
                ),
                ButtonSegment(
                  value: CcbThemePreference.light,
                  icon: const Icon(Icons.light_mode_outlined),
                  label: Text(
                    strings.themeLight,
                    key: const ValueKey('theme-option-light'),
                  ),
                ),
                ButtonSegment(
                  value: CcbThemePreference.dark,
                  icon: const Icon(Icons.dark_mode_outlined),
                  label: Text(
                    strings.themeDark,
                    key: const ValueKey('theme-option-dark'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _OnboardingStep extends StatelessWidget {
  const _OnboardingStep({
    required this.icon,
    required this.title,
    required this.body,
    this.code,
  });

  final IconData icon;
  final String title;
  final String body;
  final String? code;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final codeText = code;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: theme.colorScheme.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: theme.textTheme.titleMedium),
                const SizedBox(height: 2),
                Text(
                  body,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                if (codeText != null) ...[
                  const SizedBox(height: 6),
                  SelectableText(
                    codeText,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
