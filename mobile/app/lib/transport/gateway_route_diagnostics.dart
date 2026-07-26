import '../models/ccb_project.dart';
import '../models/ccb_project_view.dart';
import 'gateway_transport.dart';
import 'route_provider.dart';

class GatewayRouteDiagnostics {
  const GatewayRouteDiagnostics({required GatewayTransport transport})
    : _transport = transport;

  final GatewayTransport _transport;

  Future<GatewayRouteDiagnosticReport> check({String? projectId}) async {
    final profile = _transport.profile;
    final checks = <GatewayRouteDiagnosticCheck>[
      ..._localRouteChecks(profile.routeProvider),
    ];
    GatewayHealth? health;
    GatewayDevice? device;
    List<CcbProject> projects = const [];
    CcbProjectView? view;
    String? selectedProjectId = projectId;

    try {
      health = await _transport.health();
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'gateway_health',
          ok: health.status == 'ok',
          message:
              health.status == 'ok'
                  ? 'Gateway healthy'
                  : 'Gateway health is ${health.status}',
        ),
      );
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'gateway_capabilities',
          ok:
              health.capabilities.contains('http_json') &&
              health.capabilities.contains('project_view'),
          message: 'Gateway capabilities: ${_sortedText(health.capabilities)}',
        ),
      );
    } catch (error) {
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'gateway_health',
          ok: false,
          message: 'Gateway health failed: $error',
        ),
      );
    }

    try {
      device = await _transport.device();
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'device_auth',
          ok:
              device.deviceId == profile.deviceId &&
              !device.revoked &&
              device.scopes.contains('view'),
          message:
              device.revoked
                  ? 'Device is revoked'
                  : 'Device authenticated as ${device.deviceId}',
        ),
      );
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'route_provider_scope',
          ok: device.routeProvider == profile.routeProvider.kind,
          message: 'Route provider ${device.routeProvider.wireName} for device',
        ),
      );
      checks.add(
        _deviceGatewayUrlCheck(profile.routeProvider, device.gatewayUrl),
      );
      selectedProjectId ??= device.projectId;
    } catch (error) {
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'device_auth',
          ok: false,
          message: 'Device auth failed: $error',
        ),
      );
    }

    try {
      projects = await _transport.listProjects();
      final hasProjects = projects.isNotEmpty;
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'project_list',
          ok: hasProjects,
          message: hasProjects ? 'Projects reachable' : 'No projects returned',
        ),
      );
      if (hasProjects &&
          !projects.any((project) => project.id == selectedProjectId)) {
        selectedProjectId = projects.first.id;
      }
    } catch (error) {
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'project_list',
          ok: false,
          message: 'Project list failed: $error',
        ),
      );
    }

    if (_hasText(selectedProjectId)) {
      try {
        view = await _transport.getProjectView(selectedProjectId!);
        final redacted =
            view.tmuxSocketPath == null && view.tmuxSessionName == null;
        checks.add(
          GatewayRouteDiagnosticCheck(
            code: 'project_view_redacted',
            ok: redacted,
            message:
                redacted
                    ? 'ProjectView redacted'
                    : 'ProjectView exposes tmux attach evidence',
          ),
        );
      } catch (error) {
        checks.add(
          GatewayRouteDiagnosticCheck(
            code: 'project_view',
            ok: false,
            message: 'ProjectView failed: $error',
          ),
        );
      }
    } else {
      checks.add(
        const GatewayRouteDiagnosticCheck(
          code: 'project_view',
          ok: false,
          message: 'Project id unavailable',
        ),
      );
    }

    return GatewayRouteDiagnosticReport(
      profile: profile,
      health: health,
      device: device,
      projects: projects,
      checkedProjectId: selectedProjectId,
      projectView: view,
      checks: checks,
    );
  }
}

class GatewayRouteDiagnosticReport {
  const GatewayRouteDiagnosticReport({
    required this.profile,
    required this.checks,
    this.health,
    this.device,
    this.projects = const [],
    this.checkedProjectId,
    this.projectView,
  });

  final GatewayHostProfile profile;
  final GatewayHealth? health;
  final GatewayDevice? device;
  final List<CcbProject> projects;
  final String? checkedProjectId;
  final CcbProjectView? projectView;
  final List<GatewayRouteDiagnosticCheck> checks;

  bool get ready => checks.isNotEmpty && checks.every((check) => check.ok);

  String get summary {
    if (ready) {
      return 'Route ready';
    }
    for (final check in checks) {
      if (!check.ok) {
        return check.message;
      }
    }
    return 'Route not checked';
  }

  Map<String, Object?> toJson() {
    return {
      'ready': ready,
      'route_provider': profile.routeProvider.kind.wireName,
      'gateway_url': profile.routeProvider.gatewayUrl.toString(),
      if (checkedProjectId != null) 'project_id': checkedProjectId,
      'checks': [for (final check in checks) check.toJson()],
    };
  }
}

class GatewayRouteDiagnosticCheck {
  const GatewayRouteDiagnosticCheck({
    required this.code,
    required this.ok,
    required this.message,
  });

  final String code;
  final bool ok;
  final String message;

  Map<String, Object?> toJson() {
    return {'code': code, 'ok': ok, 'message': message};
  }
}

List<GatewayRouteDiagnosticCheck> _localRouteChecks(RouteProvider route) {
  final checks = <GatewayRouteDiagnosticCheck>[
    GatewayRouteDiagnosticCheck(
      code: 'gateway_url',
      ok: route.gatewayUrl.hasScheme && route.gatewayUrl.host.isNotEmpty,
      message: 'Gateway URL ${route.gatewayUrl}',
    ),
  ];
  if (route.kind == RouteProviderKind.cloudflareTunnel) {
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'cloudflare_origin',
        ok: _isOriginOnly(route.gatewayUrl),
        message:
            'Cloudflare gateway URL must be an HTTPS origin without path, '
            'query, fragment, or credentials',
      ),
    );
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'cloudflare_https',
        ok: route.gatewayUrl.scheme == 'https',
        message: 'Cloudflare gateway URL must use HTTPS',
      ),
    );
    final websocketUrl = route.websocketUrl;
    if (websocketUrl != null) {
      checks.add(
        GatewayRouteDiagnosticCheck(
          code: 'cloudflare_wss',
          ok: websocketUrl.scheme == 'wss',
          message: 'Cloudflare WebSocket URL must use WSS',
        ),
      );
    }
  }
  if (route.kind == RouteProviderKind.relay) {
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'relay_origin',
        ok: _isOriginOnly(route.gatewayUrl),
        message:
            'Relay gateway URL must be an HTTPS origin without path, query, '
            'fragment, or credentials',
      ),
    );
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'relay_https',
        ok: route.gatewayUrl.scheme == 'https',
        message: 'Relay gateway URL must use HTTPS',
      ),
    );
    final websocketUrl = route.websocketUrl;
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'relay_wss',
        ok:
            websocketUrl != null &&
            websocketUrl.scheme == 'wss' &&
            _isOriginOnly(websocketUrl),
        message:
            'Relay WebSocket URL must be a WSS origin without path, query, '
            'fragment, or credentials',
      ),
    );
    checks.addAll(_relayDiagnosticChecks(route));
  }
  return checks;
}

List<GatewayRouteDiagnosticCheck> _relayDiagnosticChecks(RouteProvider route) {
  final checks = <GatewayRouteDiagnosticCheck>[];
  final diagnostics = route.diagnostics;
  final state = _diagnosticText(diagnostics, const ['relay_state', 'state']);
  if (state != null) {
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'relay_host_state',
        ok: _relayStateOk(state),
        message: _relayStateMessage(state),
      ),
    );
  }

  final observedFingerprint = _diagnosticText(diagnostics, const [
    'relay_host_fingerprint',
    'observed_host_fingerprint',
    'host_fingerprint',
  ]);
  final expectedFingerprint =
      _diagnosticText(diagnostics, const ['expected_host_fingerprint']) ??
      _optionalText(route.hostFingerprint);
  if (observedFingerprint != null && expectedFingerprint != null) {
    final matches = observedFingerprint == expectedFingerprint;
    checks.add(
      GatewayRouteDiagnosticCheck(
        code: 'relay_host_fingerprint',
        ok: matches,
        message:
            matches
                ? 'Relay host fingerprint matches profile'
                : 'Relay host fingerprint $observedFingerprint does not '
                    'match expected $expectedFingerprint',
      ),
    );
  }
  return checks;
}

bool _relayStateOk(String state) {
  return switch (state) {
    'registered' || 'ready' => true,
    _ => false,
  };
}

String _relayStateMessage(String state) {
  return switch (state) {
    'registered' => 'Relay host registered',
    'ready' => 'Relay host ready',
    'host_disconnected' => 'Relay host is disconnected',
    'unknown_host' => 'Relay host is unknown to the relay',
    'relay_unreachable' => 'Relay control plane is unreachable',
    'stale_device' => 'Relay device authorization is stale',
    'host_fingerprint_mismatch' => 'Relay host fingerprint mismatch',
    _ => 'Relay host state $state is not recognized',
  };
}

GatewayRouteDiagnosticCheck _deviceGatewayUrlCheck(
  RouteProvider route,
  Uri? deviceGatewayUrl,
) {
  if (deviceGatewayUrl == null) {
    return const GatewayRouteDiagnosticCheck(
      code: 'device_gateway_url',
      ok: false,
      message: 'Device gateway URL missing',
    );
  }
  if (route.kind == RouteProviderKind.cloudflareTunnel &&
      !_isOriginOnly(deviceGatewayUrl)) {
    return const GatewayRouteDiagnosticCheck(
      code: 'device_gateway_url',
      ok: false,
      message:
          'Device Cloudflare gateway URL must be an HTTPS origin without path, '
          'query, fragment, or credentials',
    );
  }
  if (route.kind == RouteProviderKind.relay &&
      (deviceGatewayUrl.scheme != 'https' ||
          !_isOriginOnly(deviceGatewayUrl))) {
    return const GatewayRouteDiagnosticCheck(
      code: 'device_gateway_url',
      ok: false,
      message:
          'Device relay gateway URL must be an HTTPS origin without path, '
          'query, fragment, or credentials',
    );
  }
  final matches = _sameOrigin(deviceGatewayUrl, route.gatewayUrl);
  return GatewayRouteDiagnosticCheck(
    code: 'device_gateway_url',
    ok: matches,
    message:
        matches
            ? 'Device gateway URL matches profile route'
            : 'Device gateway URL ${_originText(deviceGatewayUrl)} does not '
                'match profile route ${_originText(route.gatewayUrl)}',
  );
}

bool _isOriginOnly(Uri uri) {
  final pathOk = uri.path.isEmpty || uri.path == '/';
  return pathOk &&
      !uri.hasQuery &&
      uri.fragment.isEmpty &&
      uri.userInfo.isEmpty;
}

bool _sameOrigin(Uri left, Uri right) {
  return left.scheme == right.scheme &&
      left.host.toLowerCase() == right.host.toLowerCase() &&
      _effectivePort(left) == _effectivePort(right);
}

int _effectivePort(Uri uri) {
  if (uri.hasPort) {
    return uri.port;
  }
  return switch (uri.scheme) {
    'https' || 'wss' => 443,
    'http' || 'ws' => 80,
    _ => 0,
  };
}

String _originText(Uri uri) {
  final port = _effectivePort(uri);
  final defaultPort =
      (uri.scheme == 'https' && port == 443) ||
      (uri.scheme == 'http' && port == 80) ||
      (uri.scheme == 'wss' && port == 443) ||
      (uri.scheme == 'ws' && port == 80);
  final portText = port == 0 || defaultPort ? '' : ':$port';
  return '${uri.scheme}://${uri.host}$portText';
}

String _sortedText(Set<String> values) {
  final sorted = values.toList()..sort();
  return sorted.join(', ');
}

String? _diagnosticText(Map<String, String> diagnostics, List<String> keys) {
  for (final key in keys) {
    final value = _optionalText(diagnostics[key]);
    if (value != null) {
      return value;
    }
  }
  return null;
}

String? _optionalText(String? value) {
  final text = value?.trim();
  return text == null || text.isEmpty ? null : text;
}

bool _hasText(String? value) => value != null && value.trim().isNotEmpty;
