import 'package:flutter/material.dart';

import '../../app/mobile_network_status.dart';
import '../../l10n/ccb_mobile_localizations.dart';
import '../../transport/route_provider.dart';

enum GatewayLanNetworkNoticeKind {
  offline,
  localNetworkRequired,
  vpnMayBlock,
  gatewayUnreachable,
}

GatewayLanNetworkNoticeKind? gatewayLanPairingWarningFor(
  MobileNetworkStatus status,
) {
  if (!status.supported || status.hasLocalNetworkTransport) {
    return null;
  }
  if (!status.connected) {
    return GatewayLanNetworkNoticeKind.offline;
  }
  if (status.vpn) {
    return GatewayLanNetworkNoticeKind.vpnMayBlock;
  }
  return GatewayLanNetworkNoticeKind.localNetworkRequired;
}

GatewayLanNetworkNoticeKind? gatewayLanNetworkNoticeFor({
  required RouteProviderKind routeKind,
  required bool reconnecting,
  required MobileNetworkStatus? status,
}) {
  if (routeKind != RouteProviderKind.lan || !reconnecting) {
    return null;
  }
  if (status == null || !status.supported) {
    return GatewayLanNetworkNoticeKind.gatewayUnreachable;
  }
  if (!status.connected) {
    return GatewayLanNetworkNoticeKind.offline;
  }
  if (status.vpn) {
    return GatewayLanNetworkNoticeKind.vpnMayBlock;
  }
  if (!status.hasLocalNetworkTransport) {
    return GatewayLanNetworkNoticeKind.localNetworkRequired;
  }
  return GatewayLanNetworkNoticeKind.gatewayUnreachable;
}

class GatewayLanNetworkBanner extends StatelessWidget {
  const GatewayLanNetworkBanner({
    required this.kind,
    required this.gatewayHost,
    required this.onRetry,
    required this.onDiagnostics,
    super.key,
  });

  final GatewayLanNetworkNoticeKind kind;
  final String gatewayHost;
  final VoidCallback onRetry;
  final VoidCallback onDiagnostics;

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    final (title, body, icon) = switch (kind) {
      GatewayLanNetworkNoticeKind.offline => (
        strings.lanPhoneOfflineTitle,
        strings.lanPhoneOfflineBody,
        Icons.signal_wifi_connected_no_internet_4_outlined,
      ),
      GatewayLanNetworkNoticeKind.localNetworkRequired => (
        strings.lanLocalNetworkRequiredTitle,
        strings.lanLocalNetworkRequiredBody(gatewayHost),
        Icons.wifi_off_outlined,
      ),
      GatewayLanNetworkNoticeKind.vpnMayBlock => (
        strings.lanVpnMayBlockTitle,
        strings.lanVpnMayBlockBody(gatewayHost),
        Icons.vpn_lock_outlined,
      ),
      GatewayLanNetworkNoticeKind.gatewayUnreachable => (
        strings.lanGatewayUnreachableTitle,
        strings.lanGatewayUnreachableBody(gatewayHost),
        Icons.router_outlined,
      ),
    };
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      label: '$title. $body',
      child: Material(
        key: const ValueKey('gateway-lan-network-banner'),
        color: colors.tertiaryContainer,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(color: colors.tertiary.withValues(alpha: 0.45)),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 8, 6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(icon, size: 22, color: colors.onTertiaryContainer),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          key: const ValueKey('gateway-lan-network-title'),
                          style: Theme.of(
                            context,
                          ).textTheme.titleSmall?.copyWith(
                            color: colors.onTertiaryContainer,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          body,
                          key: const ValueKey('gateway-lan-network-body'),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: colors.onTertiaryContainer),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              Align(
                alignment: Alignment.centerRight,
                child: Wrap(
                  spacing: 4,
                  children: [
                    TextButton(
                      key: const ValueKey('gateway-lan-network-retry'),
                      onPressed: onRetry,
                      child: Text(strings.retry),
                    ),
                    TextButton.icon(
                      key: const ValueKey('gateway-lan-network-diagnostics'),
                      onPressed: onDiagnostics,
                      icon: const Icon(Icons.route_outlined, size: 18),
                      label: Text(strings.diagnostics),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
