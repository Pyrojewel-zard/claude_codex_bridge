import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../app/runtime_mode.dart';
import '../../models/ccb_project_lifecycle.dart';
import '../../models/ccb_project_view.dart';
import '../../pairing/gateway_pairing.dart';
import '../../transport/gateway_route_diagnostics.dart';
import 'connection_details.dart';
import 'project_home_update_panel.dart';

class ProjectHomeConnectionDetailsPanelHost extends StatefulWidget {
  const ProjectHomeConnectionDetailsPanelHost({
    required this.view,
    required this.mode,
    required this.profiles,
    required this.selectedProfile,
    required this.routeDiagnostics,
    required this.lifecycleResultListenable,
    required this.loadingProfiles,
    required this.checkingRoute,
    required this.runningLifecycleActionListenable,
    required this.onModeChanged,
    required this.onProfileSelected,
    required this.onCheckRoute,
    required this.onLifecycleAction,
    super.key,
  });

  final CcbProjectView view;
  final AppRuntimeMode mode;
  final List<GatewayPairedHost> profiles;
  final GatewayPairedHost? selectedProfile;
  final GatewayRouteDiagnosticReport? routeDiagnostics;
  final ValueListenable<CcbProjectLifecycleResult?> lifecycleResultListenable;
  final bool loadingProfiles;
  final bool checkingRoute;
  final ValueListenable<CcbLifecycleAction?> runningLifecycleActionListenable;
  final ValueChanged<AppRuntimeMode> onModeChanged;
  final ValueChanged<GatewayPairedHost> onProfileSelected;
  final Future<GatewayRouteDiagnosticReport?> Function() onCheckRoute;
  final ValueChanged<CcbLifecycleAction> onLifecycleAction;

  @override
  State<ProjectHomeConnectionDetailsPanelHost> createState() =>
      _ProjectHomeConnectionDetailsPanelHostState();
}

class _ProjectHomeConnectionDetailsPanelHostState
    extends State<ProjectHomeConnectionDetailsPanelHost> {
  late AppRuntimeMode _mode;
  GatewayPairedHost? _selectedProfile;
  GatewayRouteDiagnosticReport? _routeDiagnostics;
  late bool _checkingRoute;

  @override
  void initState() {
    super.initState();
    _mode = widget.mode;
    _selectedProfile = widget.selectedProfile;
    _routeDiagnostics = widget.routeDiagnostics;
    _checkingRoute = widget.checkingRoute;
  }

  @override
  void didUpdateWidget(ProjectHomeConnectionDetailsPanelHost oldWidget) {
    super.didUpdateWidget(oldWidget);
    _mode = widget.mode;
    _selectedProfile = widget.selectedProfile;
    _routeDiagnostics = widget.routeDiagnostics;
    _checkingRoute = widget.checkingRoute;
  }

  void _handleModeChanged(AppRuntimeMode mode) {
    setState(() {
      _mode = mode;
      _routeDiagnostics = null;
    });
    widget.onModeChanged(mode);
  }

  void _handleProfileSelected(GatewayPairedHost profile) {
    setState(() {
      _selectedProfile = profile;
      _routeDiagnostics = null;
    });
    widget.onProfileSelected(profile);
  }

  Future<void> _checkRoute() async {
    if (_checkingRoute) {
      return;
    }
    setState(() {
      _checkingRoute = true;
    });
    final report = await widget.onCheckRoute();
    if (!mounted) {
      return;
    }
    setState(() {
      _checkingRoute = false;
      if (report != null) {
        _routeDiagnostics = report;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ConnectionDetailsPanel(
          view: widget.view,
          mode: _mode,
          profiles: widget.profiles,
          selectedProfile: _selectedProfile,
          routeDiagnostics: _routeDiagnostics,
          lifecycleResultListenable: widget.lifecycleResultListenable,
          loadingProfiles: widget.loadingProfiles,
          checkingRoute: _checkingRoute,
          runningLifecycleActionListenable:
              widget.runningLifecycleActionListenable,
          initiallyExpanded: true,
          onModeChanged: _handleModeChanged,
          onProfileSelected: _handleProfileSelected,
          onCheckRoute: _checkRoute,
          onLifecycleAction: widget.onLifecycleAction,
        ),
        const SizedBox(height: 12),
        const ProjectHomeUpdatePanel(),
      ],
    );
  }
}
