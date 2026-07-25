import 'dart:async';

import 'package:flutter/foundation.dart' show SynchronousFuture;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;

import '../../cache/mobile_snapshot_codec.dart';
import '../../cache/mobile_snapshot_store.dart';
import '../../app/app_factories.dart';
import '../../app/app_theme.dart';
import '../../app/background_connection.dart';
import '../../app/runtime_mode.dart';
import '../../debug/debug_profile_seed.dart';
import '../../l10n/ccb_mobile_localizations.dart';
import '../../models/ccb_agent.dart';
import '../../models/ccb_notification.dart';
import '../../models/ccb_project.dart';
import '../../models/ccb_project_lifecycle.dart';
import '../../models/ccb_project_view.dart';
import '../../notifications/task_completion_notifications.dart';
import '../../notifications/push_notifications.dart';
import '../../pairing/gateway_pairing.dart';
import '../../repository/mobile_ccb_repository.dart';
import '../../repository/gateway_mobile_ccb_repository.dart';
import '../../transport/gateway_route_diagnostics.dart';
import '../../transport/gateway_connection_outcome.dart';
import '../../transport/http_gateway_transport.dart';
import '../../transport/route_provider.dart';
import '../../transport/terminal_transport.dart';
import '../agent_chat/agent_execution_status.dart';
import 'project_home_connection_details_panel_host.dart';
import 'project_home_focus_coordinator.dart';
import 'project_home_gateway_profiles.dart';
import 'project_home_lifecycle_coordinator.dart';
import 'mobile_connection_supervisor.dart';
import 'mobile_presence_coordinator.dart';
import 'project_home_notification_target.dart';
import 'project_home_onboarding.dart';
import 'project_home_pairing_flow.dart';
import 'project_home_pairing_form_controller.dart';
import 'project_home_profile_bootstrapper.dart';
import 'project_home_profile_loading.dart';
import 'project_home_route_actions.dart';
import 'project_home_route_diagnostics.dart';
import 'project_home_runtime_activation.dart';
import 'project_home_scaffold_host.dart';
import 'project_home_shell_state.dart';
import 'project_home_task_completion_notifications.dart';
import 'project_home_terminal_navigation.dart';
import 'project_home_view_refresh.dart';
import 'project_shell_widgets.dart';

class ProjectHomeScreen extends StatelessWidget {
  const ProjectHomeScreen({
    required this.repository,
    this.profileStore,
    this.pairingClaimAndStore = defaultPairingClaimAndStore,
    this.pairingScanner = defaultPairingScanner,
    this.gatewayRepositoryFactory = defaultGatewayRepositoryFactory,
    this.gatewayTerminalTransportFactory =
        defaultGatewayTerminalTransportFactory,
    this.gatewayRouteDiagnostics = defaultGatewayRouteDiagnostics,
    this.showOnboardingWhenUnpaired = false,
    this.autoActivateStoredProfile = false,
    this.themePreference = CcbThemePreference.system,
    this.onThemePreferenceChanged,
    this.backgroundConnectionEnabled = false,
    this.backgroundConnectionPreferenceLoaded = true,
    this.onBackgroundConnectionEnabledChanged,
    this.backgroundConnectionPlatform,
    this.taskNotificationStreamClient,
    this.taskCompletionLocalNotifications,
    this.taskCompletionSeenStore,
    this.taskCompletionUnreadStore,
    this.invalidationCursorStore,
    this.pushMessaging,
    this.pushRegistrationClient,
    super.key,
  });

  final MobileCcbRepository repository;
  final GatewayHostProfileStore? profileStore;
  final GatewayPairingClaimAndStore pairingClaimAndStore;
  final GatewayPairingScanner pairingScanner;
  final GatewayRepositoryFactory gatewayRepositoryFactory;
  final GatewayTerminalTransportFactory gatewayTerminalTransportFactory;
  final GatewayRouteDiagnosticsFactory gatewayRouteDiagnostics;
  final bool showOnboardingWhenUnpaired;
  final bool autoActivateStoredProfile;
  final CcbThemePreference themePreference;
  final ValueChanged<CcbThemePreference>? onThemePreferenceChanged;
  final bool backgroundConnectionEnabled;
  final bool backgroundConnectionPreferenceLoaded;
  final ValueChanged<bool>? onBackgroundConnectionEnabledChanged;
  final BackgroundConnectionPlatform? backgroundConnectionPlatform;
  final GatewayTaskCompletionNotificationStreamClient?
  taskNotificationStreamClient;
  final TaskCompletionLocalNotifications? taskCompletionLocalNotifications;
  final TaskCompletionSeenDedupeStore? taskCompletionSeenStore;
  final TaskCompletionUnreadStore? taskCompletionUnreadStore;
  final GatewayInvalidationCursorStore? invalidationCursorStore;
  final PushMessagingClient? pushMessaging;
  final GatewayPushRegistrationClient? pushRegistrationClient;

  @override
  Widget build(BuildContext context) {
    return _ProjectHomeView(
      repository: repository,
      profileStore: profileStore ?? GatewayHostProfileStore(),
      pairingClaimAndStore: pairingClaimAndStore,
      pairingScanner: pairingScanner,
      gatewayRepositoryFactory: gatewayRepositoryFactory,
      gatewayTerminalTransportFactory: gatewayTerminalTransportFactory,
      gatewayRouteDiagnostics: gatewayRouteDiagnostics,
      showOnboardingWhenUnpaired: showOnboardingWhenUnpaired,
      autoActivateStoredProfile: autoActivateStoredProfile,
      themePreference: themePreference,
      onThemePreferenceChanged: onThemePreferenceChanged,
      backgroundConnectionEnabled: backgroundConnectionEnabled,
      backgroundConnectionPreferenceLoaded:
          backgroundConnectionPreferenceLoaded,
      onBackgroundConnectionEnabledChanged:
          onBackgroundConnectionEnabledChanged,
      backgroundConnectionPlatform:
          backgroundConnectionPlatform ??
          const MethodChannelBackgroundConnectionPlatform(),
      taskNotificationStreamClient: taskNotificationStreamClient,
      taskCompletionLocalNotifications: taskCompletionLocalNotifications,
      taskCompletionSeenStore: taskCompletionSeenStore,
      taskCompletionUnreadStore: taskCompletionUnreadStore,
      invalidationCursorStore: invalidationCursorStore,
      pushMessaging: pushMessaging,
      pushRegistrationClient: pushRegistrationClient,
    );
  }
}

class _ProjectHomeView extends StatefulWidget {
  const _ProjectHomeView({
    required this.repository,
    required this.profileStore,
    required this.pairingClaimAndStore,
    required this.pairingScanner,
    required this.gatewayRepositoryFactory,
    required this.gatewayTerminalTransportFactory,
    required this.gatewayRouteDiagnostics,
    required this.showOnboardingWhenUnpaired,
    required this.autoActivateStoredProfile,
    required this.themePreference,
    required this.onThemePreferenceChanged,
    required this.backgroundConnectionEnabled,
    required this.backgroundConnectionPreferenceLoaded,
    required this.onBackgroundConnectionEnabledChanged,
    required this.backgroundConnectionPlatform,
    required this.taskNotificationStreamClient,
    required this.taskCompletionLocalNotifications,
    required this.taskCompletionSeenStore,
    required this.taskCompletionUnreadStore,
    required this.invalidationCursorStore,
    required this.pushMessaging,
    required this.pushRegistrationClient,
  });

  final MobileCcbRepository repository;
  final GatewayHostProfileStore profileStore;
  final GatewayPairingClaimAndStore pairingClaimAndStore;
  final GatewayPairingScanner pairingScanner;
  final GatewayRepositoryFactory gatewayRepositoryFactory;
  final GatewayTerminalTransportFactory gatewayTerminalTransportFactory;
  final GatewayRouteDiagnosticsFactory gatewayRouteDiagnostics;
  final bool showOnboardingWhenUnpaired;
  final bool autoActivateStoredProfile;
  final CcbThemePreference themePreference;
  final ValueChanged<CcbThemePreference>? onThemePreferenceChanged;
  final bool backgroundConnectionEnabled;
  final bool backgroundConnectionPreferenceLoaded;
  final ValueChanged<bool>? onBackgroundConnectionEnabledChanged;
  final BackgroundConnectionPlatform backgroundConnectionPlatform;
  final GatewayTaskCompletionNotificationStreamClient?
  taskNotificationStreamClient;
  final TaskCompletionLocalNotifications? taskCompletionLocalNotifications;
  final TaskCompletionSeenDedupeStore? taskCompletionSeenStore;
  final TaskCompletionUnreadStore? taskCompletionUnreadStore;
  final GatewayInvalidationCursorStore? invalidationCursorStore;
  final PushMessagingClient? pushMessaging;
  final GatewayPushRegistrationClient? pushRegistrationClient;

  @override
  State<_ProjectHomeView> createState() => _ProjectHomeViewState();
}

class _ProjectHomeViewState extends State<_ProjectHomeView>
    with WidgetsBindingObserver {
  static const _defaultProjectId = 'proj-demo';
  final _pairingForm = ProjectHomePairingFormController();

  late MobileCcbRepository _activeRepository;
  late Future<CcbProjectView> _viewFuture;
  Future<List<CcbProject>>? _serverProjectsFuture;
  AppRuntimeMode _mode = AppRuntimeMode.fake;
  List<GatewayPairedHost> _profiles = const [];
  GatewayPairedHost? _selectedProfile;
  GatewayRouteDiagnosticReport? _routeDiagnostics;
  final _lifecycleResultNotifier = ValueNotifier<CcbProjectLifecycleResult?>(
    null,
  );
  String _activeProjectId = _defaultProjectId;
  String? _openedProjectId;
  String? _selectedAgentName;
  int _selectionRevision = 0;
  TerminalTransport? _terminalTransport;
  bool _loadingProfiles = false;
  bool _claimingPairing = false;
  bool _checkingRoute = false;
  bool _gatewayProfileActivationSucceeded = false;
  bool _profilesInitialized = false;
  CcbLifecycleAction? _runningLifecycleAction;
  final _runningLifecycleActionNotifier = ValueNotifier<CcbLifecycleAction?>(
    null,
  );
  bool _showPairingSetup = false;
  WideSidebarState _wideSidebarState = WideSidebarState.expanded;
  WideSidebarState _wideSidebarDragStartState = WideSidebarState.expanded;
  double _wideSidebarDragDelta = 0;
  bool _mobileAgentsCollapsed = false;
  late final MobileSnapshotStore _snapshotStore = MobileSnapshotStore();
  late final GatewayInvalidationCursorStore _invalidationCursorStore;
  GatewayInvalidationConnectionState _gatewayConnectionState =
      GatewayInvalidationConnectionState.connected;
  Duration? _gatewayReconnectRetryIn;
  bool _invalidationRefreshInFlight = false;
  bool _invalidationRefreshQueued = false;
  bool _gatewayRecoveryInFlight = false;
  int _conversationInvalidationRevision = 0;
  AppLifecycleState _appLifecycleState =
      WidgetsBinding.instance.lifecycleState ?? AppLifecycleState.resumed;
  String? _visibleTaskCompletionProjectId;
  String? _visibleTaskCompletionAgentName;
  final Map<String, bool> _knownProjectWorkingAgents = {};
  final Map<String, DateTime> _optimisticProjectActivityAt = {};
  List<TaskCompletionUnreadItem> _unreadTaskCompletions = const [];

  late final ProjectHomeProfileBootstrapper _profileBootstrapper =
      ProjectHomeProfileBootstrapper(store: widget.profileStore);
  late final ProjectHomeProfileLoadingCoordinator _profileLoadingCoordinator =
      ProjectHomeProfileLoadingCoordinator(bootstrapper: _profileBootstrapper);
  final _lifecycleCoordinator = const ProjectHomeLifecycleCoordinator();
  final _pairingFlowCoordinator = const ProjectHomePairingFlowCoordinator();
  final _routeDiagnosticsCoordinator =
      const ProjectHomeRouteDiagnosticsCoordinator();
  final _focusCoordinator = const ProjectHomeFocusCoordinator();
  final _runtimeSessionCoordinator =
      const ProjectHomeRuntimeSessionCoordinator();
  final _viewRefreshCoordinator = const ProjectHomeViewRefreshCoordinator();
  final _taskCompletionUnreadClearInFlight = <String>{};
  late final TaskCompletionUnreadStore _taskCompletionUnreadStore;
  late final TaskCompletionSeenDedupeStore _taskCompletionSeenStore;
  late final TaskCompletionNotificationController _taskNotifications;
  late final PushNotificationRuntime _pushNotifications;
  late final MobileConnectionSupervisor _connectionSupervisor;
  MobileConnectionOutcomeAdapter? _connectionOutcomeAdapter;
  int _gatewayActivationGeneration = 0;
  late final MobilePresenceCoordinator _presenceCoordinator;
  bool _taskNotificationsSuspendedForBackground = false;
  late final BackgroundConnectionRuntime _backgroundConnectionRuntime;
  BackgroundConnectionSystemStatus? _backgroundConnectionSystemStatus;
  bool _backgroundConnectionSystemStatusLoading = false;
  int _backgroundConnectionSystemStatusGeneration = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _connectionSupervisor = MobileConnectionSupervisor(
      onChanged: _handleSupervisorState,
    );
    _presenceCoordinator = MobilePresenceCoordinator(
      onFailure:
          (error) => _connectionSupervisor.reportFailure(
            error,
            kind: MobileTransportKind.mutation,
          ),
    );
    _backgroundConnectionRuntime = BackgroundConnectionRuntime(
      platform: widget.backgroundConnectionPlatform,
      onRunningChanged: _handleBackgroundConnectionRunningChanged,
      onStartFailed: _handleBackgroundConnectionStartFailure,
    );
    _taskCompletionUnreadStore =
        widget.taskCompletionUnreadStore ?? TaskCompletionUnreadStore();
    _taskCompletionSeenStore =
        widget.taskCompletionSeenStore ?? TaskCompletionSeenDedupeStore();
    _invalidationCursorStore =
        widget.invalidationCursorStore ?? GatewayInvalidationCursorStore();
    _taskNotifications = TaskCompletionNotificationController(
      streamClient:
          widget.taskNotificationStreamClient ??
          HttpGatewayTaskCompletionNotificationStreamClient(),
      localNotifications:
          widget.taskCompletionLocalNotifications ??
          MethodChannelTaskCompletionLocalNotifications(),
      seenStore: _taskCompletionSeenStore,
      cursorStore: _invalidationCursorStore,
      onTap: _handleTaskCompletionNotificationTap,
      onLiveEvent: _handleLiveTaskCompletionEvent,
      onInvalidationEvent: _handleGatewayInvalidationEvent,
      onConnectionStateChanged: _handleGatewayConnectionStateChanged,
      onStreamError: _handleGatewayStreamError,
      shouldShowNotification: _shouldShowTaskCompletionNotification,
    );
    _pushNotifications = PushNotificationRuntime(
      messaging: widget.pushMessaging ?? FirebasePushMessagingClient(),
      registration:
          widget.pushRegistrationClient ?? GatewayPushRegistrationClient(),
      markSeenIfNew: _taskCompletionSeenStore.markSeenIfNew,
      isRouteProfileAmbiguous: (_) => _profiles.length > 1,
      onForegroundRoute: _handleForegroundPushNotificationRoute,
      onRouteOpened: _handlePushNotificationRoute,
    );
    _activeRepository = widget.repository;
    _viewFuture = _loadActiveProjectView();
    _bootstrapProfiles();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        unawaited(_refreshBackgroundConnectionSystemStatus());
      }
    });
    if (widget.backgroundConnectionEnabled &&
        widget.backgroundConnectionPreferenceLoaded) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _requestBackgroundConnectionReconcile();
      });
    }
  }

  @override
  void didUpdateWidget(covariant _ProjectHomeView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.backgroundConnectionEnabled !=
            widget.backgroundConnectionEnabled ||
        oldWidget.backgroundConnectionPreferenceLoaded !=
            widget.backgroundConnectionPreferenceLoaded) {
      _requestBackgroundConnectionReconcile();
    }
  }

  @override
  void dispose() {
    _backgroundConnectionSystemStatusGeneration += 1;
    unawaited(_backgroundConnectionRuntime.dispose());
    WidgetsBinding.instance.removeObserver(this);
    _pairingForm.dispose();
    unawaited(_taskNotifications.dispose());
    unawaited(_pushNotifications.dispose());
    _presenceCoordinator.dispose();
    _connectionSupervisor.dispose();
    _lifecycleResultNotifier.dispose();
    _runningLifecycleActionNotifier.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appLifecycleState = state;
    if (state == AppLifecycleState.resumed) {
      _presenceCoordinator.setVisible(true);
      if (_showPairingSetup || _shouldShowUnpairedOnboarding) {
        unawaited(_refreshBackgroundConnectionSystemStatus());
      }
      _requestBackgroundConnectionReconcile();
      _connectionSupervisor.foregroundResume();
      final profile = _selectedProfile;
      if (_taskNotificationsSuspendedForBackground &&
          _mode == AppRuntimeMode.pairedGateway &&
          profile != null) {
        _startTaskCompletionNotifications(profile);
      } else if (!_backgroundConnectionRuntime.running) {
        _taskNotifications.retryNow();
      }
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.inactive ||
        state == AppLifecycleState.detached ||
        state == AppLifecycleState.hidden) {
      _presenceCoordinator.setVisible(false);
      if (state != AppLifecycleState.inactive &&
          !_backgroundConnectionRuntime.running) {
        _stopTaskCompletionNotifications(forBackground: true);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return _buildWithSystemBack(_buildContent(context));
  }

  Widget _buildContent(BuildContext context) {
    if (_showPairingSetup) {
      return _buildOnboardingScaffold();
    }
    if (_shouldShowUnpairedLoading) {
      return const ProjectHomeOnboardingLoadingScaffold();
    }
    if (_shouldShowUnpairedOnboarding) {
      return _buildOnboardingScaffold();
    }
    final serverProjectsFuture = _serverProjectsFuture;
    if (_mode == AppRuntimeMode.pairedGateway &&
        _activeProjectId.isEmpty &&
        serverProjectsFuture != null) {
      _setVisibleTaskCompletionTarget(projectId: null, agentName: null);
      return _buildServerProjectList(serverProjectsFuture);
    }
    return FutureBuilder<CcbProjectView>(
      future: _viewFuture,
      builder: (context, snapshot) {
        final error = snapshot.error;
        if (error != null) {
          return _buildProjectLoadError(error);
        }
        final view = snapshot.data;
        final selectedAgent = view == null ? null : _selectedAgentFor(view);
        if (view == null) {
          _setVisibleTaskCompletionTarget(projectId: null, agentName: null);
          return const Scaffold(
            body: SafeArea(child: Center(child: CircularProgressIndicator())),
          );
        }
        _rememberProjectActivity(view);
        final wide =
            MediaQuery.sizeOf(context).width >= projectHomeWideLayoutBreakpoint;
        final mobileChatVisible = _openedProjectId == view.project.id;
        _setVisibleTaskCompletionTarget(
          projectId: wide || mobileChatVisible ? view.project.id : null,
          agentName: wide || mobileChatVisible ? selectedAgent?.name : null,
        );
        if (wide || mobileChatVisible) {
          _clearVisibleTaskCompletionUnread(
            projectId: view.project.id,
            agentName: selectedAgent?.name,
          );
        }
        if (wide) {
          return _buildWideProjectScaffold(view, selectedAgent);
        }
        if (_openedProjectId != view.project.id) {
          return _buildProjectListScaffold(view, selectedAgent);
        }
        return ProjectHomeMobileChatScaffoldHost(
          view: view,
          selectedAgent: selectedAgent,
          repository: _activeRepository,
          terminalTransport: _terminalTransport,
          usePaneInputForMessages: _mode == AppRuntimeMode.pairedGateway,
          mobileAgentsCollapsed: _mobileAgentsCollapsed,
          unreadAgentNames: _unreadAgentNamesForProject(view.project.id),
          onBack: _closeProject,
          onOpenConnectionDetails: () {
            _openConnectionDetails(view);
          },
          onCollapseAgents: _collapseMobileAgents,
          onExpandAgents: _expandMobileAgents,
          onProjectActivity: () {
            setState(() {
              _rememberProjectUsed(view.project.id);
            });
            _presenceCoordinator.updateTarget(
              projectId: view.project.id,
              agent: selectedAgent?.name,
              userActivity: true,
            );
          },
          onWindowSelected: (windowName) {
            _selectWindow(view, windowName);
          },
          onAgentSelected: _selectAgent,
          onRefreshView:
              () => _refreshActiveView(
                preserveSelectedAgentName: selectedAgent?.name,
              ),
          onTimelineScrollDirectionChanged:
              _handleMobileTimelineScrollDirection,
          snapshotStore: _snapshotStore,
          snapshotNamespace: _snapshotNamespace,
          sendEnabled: _sendEnabled,
          sendDisabledReason: _sendDisabledReason,
          conversationRefreshToken: _conversationInvalidationRevision,
          reconnectRetryIn:
              _gatewayConnectionState ==
                      GatewayInvalidationConnectionState.reconnecting
                  ? _gatewayReconnectRetryIn
                  : null,
          onRetryConnection:
              _gatewayConnectionState ==
                      GatewayInvalidationConnectionState.reconnecting
                  ? _retryGatewayConnection
                  : null,
        );
      },
    );
  }

  Widget _buildWithSystemBack(Widget child) {
    final handleBack = _shouldHandleSystemBack;
    return PopScope<void>(
      canPop: !handleBack,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) {
          return;
        }
        _handleSystemBack();
      },
      child: child,
    );
  }

  bool get _shouldHandleSystemBack {
    if (_showPairingSetup) {
      return false;
    }
    if (_mode == AppRuntimeMode.pairedGateway) {
      return true;
    }
    return _openedProjectId != null;
  }

  void _handleSystemBack() {
    if (!_shouldHandleSystemBack) {
      return;
    }
    if (_mode == AppRuntimeMode.pairedGateway) {
      if (_activeProjectId.isNotEmpty) {
        _returnToServerProjectList();
        return;
      }
      _openPairingSettings();
      return;
    }
    if (_openedProjectId != null) {
      _closeProject();
    }
  }

  Future<CcbProjectView> _loadActiveProjectView() {
    final profile = _selectedProfile;
    return _deferredBuilderFuture(() async {
      try {
        final view = await _activeRepository
            .getProjectView(_activeProjectId)
            .timeout(projectHomeRuntimeViewLoadTimeout);
        _rememberProjectActivity(view);
        _persistProjectViewSnapshot(view);
        _updateNotificationWatch(view);
        return view;
      } catch (error) {
        throw await _gatewayRequestFailure(profile, error);
      }
    });
  }

  Future<List<CcbProject>> _loadServerProjects() {
    return _deferredBuilderFuture(_fetchServerProjects);
  }

  Future<List<CcbProject>> _fetchServerProjects() async {
    final profile = _selectedProfile;
    try {
      final projects = _sortProjectsWithLocalActivity(
        await _activeRepository.listProjects().timeout(
          projectHomeRuntimeViewLoadTimeout,
        ),
      );
      _persistProjectsSnapshot(projects);
      return projects;
    } catch (error) {
      throw await _gatewayRequestFailure(profile, error);
    }
  }

  Future<Object> _gatewayRequestFailure(
    GatewayPairedHost? profile,
    Object error,
  ) async {
    final adapter = _connectionOutcomeAdapter;
    if (adapter != null) {
      adapter.failed(GatewayConnectionOperation.dataRead, error);
    } else {
      _connectionSupervisor.reportFailure(
        error,
        auth:
            (error is GatewayHttpException && error.statusCode == 401) ||
                    (error is ProjectHomeGatewayActivationException &&
                        error.kind ==
                            ProjectHomeGatewayActivationFailureKind
                                .tokenInvalid)
                ? MobileAuthDisposition.credentialInvalid
                : error is GatewayHttpException && error.statusCode == 403
                ? MobileAuthDisposition.scopeDenied
                : MobileAuthDisposition.none,
      );
    }
    if (_mode != AppRuntimeMode.pairedGateway ||
        error is ProjectHomeGatewayActivationException) {
      return error;
    }
    final normalized = projectHomeGatewayActivationExceptionFor(error);
    return normalized;
  }

  String? get _snapshotNamespace {
    final profile = _selectedProfile;
    if (profile == null) {
      return null;
    }
    return mobileSnapshotNamespace(
      hostId: profile.profile.hostId,
      deviceId: profile.profile.deviceId,
    );
  }

  void _persistProjectsSnapshot(List<CcbProject> projects) {
    final namespace = _snapshotNamespace;
    if (namespace == null) {
      return;
    }
    unawaited(
      _snapshotStore.write(
        mobileProjectsSnapshotKey(namespace),
        projectsSnapshotPayload(projects),
      ),
    );
  }

  void _persistProjectViewSnapshot(CcbProjectView view) {
    final namespace = _snapshotNamespace;
    if (namespace == null) {
      return;
    }
    unawaited(
      _snapshotStore.write(
        mobileProjectViewSnapshotKey(
          namespace: namespace,
          projectId: view.project.id,
          namespaceEpoch: view.namespaceEpoch,
        ),
        projectViewSnapshotPayload(view),
      ),
    );
  }

  Future<T> _deferredBuilderFuture<T>(Future<T> Function() load) {
    final completer = Completer<T>();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        completer.complete(await load());
      } catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      }
    });
    return completer.future;
  }

  bool get _shouldShowUnpairedLoading =>
      widget.showOnboardingWhenUnpaired &&
      _mode == AppRuntimeMode.fake &&
      !_profilesInitialized;

  bool get _shouldShowUnpairedOnboarding =>
      widget.showOnboardingWhenUnpaired &&
      _mode == AppRuntimeMode.fake &&
      _profilesInitialized &&
      _profiles.isEmpty;

  Widget _buildOnboardingScaffold() {
    return ProjectHomeOnboardingScaffold(
      gatewayUrlController: _pairingForm.gatewayUrlController,
      pairingCodeController: _pairingForm.pairingCodeController,
      deviceNameController: _pairingForm.deviceNameController,
      routeKindListenable: _pairingForm.routeKindListenable,
      claiming: _claimingPairing,
      loadingProfiles: _loadingProfiles,
      themePreference: widget.themePreference,
      onThemePreferenceChanged: widget.onThemePreferenceChanged,
      backgroundConnectionEnabled: widget.backgroundConnectionEnabled,
      onBackgroundConnectionEnabledChanged:
          widget.onBackgroundConnectionEnabledChanged,
      backgroundConnectionSystemStatus: _backgroundConnectionSystemStatus,
      backgroundConnectionSystemStatusLoading:
          _backgroundConnectionSystemStatusLoading,
      onOpenBackgroundConnectionSystemSettings:
          _openBackgroundConnectionSystemSettings,
      onRouteKindChanged: (value) {
        setState(() {
          _setPairingRouteKind(value);
        });
      },
      onScan: _scanGatewayProfile,
      onClaim: _claimGatewayProfile,
      onClose: _canClosePairingSetup ? _closePairingSetup : null,
    );
  }

  bool get _canClosePairingSetup =>
      _mode == AppRuntimeMode.pairedGateway && _profiles.isNotEmpty;

  void _closePairingSetup() {
    setState(() {
      _showPairingSetup = false;
    });
  }

  Widget _buildProjectLoadError(Object error) {
    final strings = CcbMobileLocalizations.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.cloud_off_outlined, size: 48),
                  const SizedBox(height: 16),
                  Text(
                    strings.couldNotLoadProject,
                    key: const ValueKey('project-view-load-error'),
                    style: Theme.of(context).textTheme.titleLarge,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    error.toString(),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    key: const ValueKey('project-view-retry-button'),
                    onPressed: _retryActiveProjectView,
                    icon: const Icon(Icons.refresh),
                    label: Text(strings.retry),
                  ),
                  const SizedBox(height: 8),
                  if (_mode == AppRuntimeMode.pairedGateway)
                    TextButton.icon(
                      key: const ValueKey('project-view-back-to-list-button'),
                      onPressed: _returnToServerProjectList,
                      icon: const Icon(Icons.list_alt_outlined),
                      label: Text(strings.backToProjects),
                    )
                  else
                    TextButton(
                      key: const ValueKey('project-view-use-fake-button'),
                      onPressed: () {
                        _setRuntimeMode(AppRuntimeMode.fake);
                      },
                      child: Text(strings.useFakeDemo),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _retryActiveProjectView() {
    setState(() {
      _viewFuture = _loadActiveProjectView();
    });
  }

  void _retryServerProjects() {
    final profile = _selectedProfile;
    if (!_gatewayProfileActivationSucceeded && profile != null) {
      _activateGatewayProfile(profile);
      return;
    }
    setState(() {
      _serverProjectsFuture = _loadServerProjects();
    });
  }

  List<CcbProject> _sortProjectsWithLocalActivity(List<CcbProject> projects) {
    return sortCcbProjectsByRecentActivity(
      projects,
      optimisticActivityAt: _optimisticProjectActivityAt,
    );
  }

  void _rememberProjectUsed(String projectId, {DateTime? usedAt}) {
    final normalized = projectId.trim();
    if (normalized.isEmpty) {
      return;
    }
    _optimisticProjectActivityAt[normalized] =
        (usedAt ?? DateTime.now()).toUtc();
  }

  void _returnToServerProjectList() {
    setState(() {
      _activeProjectId = '';
      _openedProjectId = null;
      _selectedAgentName = null;
      _serverProjectsFuture = _loadServerProjects();
    });
  }

  Widget _buildServerProjectList(Future<List<CcbProject>> projectsFuture) {
    return FutureBuilder<List<CcbProject>>(
      future: projectsFuture,
      builder: (context, snapshot) {
        final error = snapshot.error;
        if (error != null) {
          return _buildProjectCatalogError(error);
        }
        final loadedProjects = snapshot.data;
        if (loadedProjects == null) {
          return const Scaffold(
            body: SafeArea(child: Center(child: CircularProgressIndicator())),
          );
        }
        final projects = _sortProjectsWithLocalActivity(loadedProjects);
        return ProjectHomeServerProjectListHost(
          projects: projects,
          onRefreshProjects: _retryServerProjects,
          onOpenSettings: _openPairingSettings,
          onOpenProject: _openServerProject,
          unreadProjectIds: _unreadProjectIds,
          workingProjectIds: _workingProjectIdsFor(projects),
        );
      },
    );
  }

  Widget _buildProjectCatalogError(Object error) {
    final strings = CcbMobileLocalizations.of(context);
    final tokenInvalid =
        error is ProjectHomeGatewayActivationException &&
        error.kind == ProjectHomeGatewayActivationFailureKind.tokenInvalid;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.cloud_off_outlined, size: 48),
                  const SizedBox(height: 16),
                  Text(
                    strings.couldNotLoadProjects,
                    key: const ValueKey('project-list-load-error'),
                    style: Theme.of(context).textTheme.titleLarge,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    error.toString(),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 20),
                  if (tokenInvalid)
                    FilledButton.icon(
                      key: const ValueKey('project-list-repair-button'),
                      onPressed: _returnToPairingSetup,
                      icon: const Icon(Icons.qr_code_scanner_outlined),
                      label: Text(strings.rePair),
                    )
                  else
                    FilledButton.icon(
                      key: const ValueKey('project-list-retry-button'),
                      onPressed: _retryServerProjects,
                      icon: const Icon(Icons.refresh),
                      label: Text(strings.retry),
                    ),
                  const SizedBox(height: 8),
                  OutlinedButton.icon(
                    key: const ValueKey('project-list-back-to-setup-button'),
                    onPressed: _returnToPairingSetup,
                    icon: const Icon(Icons.settings_outlined),
                    label: Text(strings.backToSetup),
                  ),
                  if (_selectedProfile != null) ...[
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      key: const ValueKey(
                        'project-list-route-diagnostics-button',
                      ),
                      onPressed: _checkingRoute ? null : _checkGatewayRoute,
                      icon: const Icon(Icons.route_outlined),
                      label: Text(strings.diagnostics),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildWideProjectScaffold(CcbProjectView view, CcbAgent? agent) {
    return ProjectHomeWideScaffoldHost(
      view: view,
      selectedAgent: agent,
      repository: _activeRepository,
      terminalTransport: _terminalTransport,
      usePaneInputForMessages: _mode == AppRuntimeMode.pairedGateway,
      sidebarState: _wideSidebarState,
      onOpenProject: () {
        _openProject(view);
      },
      onOpenNotifications: () {
        _openNotificationCenter(view);
      },
      onOpenConnectionDetails: () {
        _openConnectionDetails(view);
      },
      onShowProjects: _expandWideSidebarLevel,
      onAgentSelected: (agent) {
        _selectAgent(agent.name);
      },
      onOpenTerminal: (agentName) {
        _openAgentTerminal(view, agentName);
      },
      onProjectActivity: () {
        setState(() {
          _rememberProjectUsed(view.project.id);
        });
        _presenceCoordinator.updateTarget(
          projectId: view.project.id,
          agent: agent?.name,
          userActivity: true,
        );
      },
      onToggleSidebar: _toggleWideSidebarLevel,
      onHorizontalDragStart: _startWideSidebarDrag,
      onHorizontalDragUpdate: _updateWideSidebarDrag,
      onHorizontalDragEnd: _endWideSidebarDrag,
      onRefreshView:
          () => _refreshActiveView(preserveSelectedAgentName: agent?.name),
      unreadAgentNames: _unreadAgentNamesForProject(view.project.id),
      hasUnreadTaskCompletion: _projectHasUnreadTaskCompletion(view.project.id),
      hasWorkingAgents: _viewHasWorkingAgents(view),
      snapshotStore: _snapshotStore,
      snapshotNamespace: _snapshotNamespace,
      sendEnabled: _sendEnabled,
      sendDisabledReason: _sendDisabledReason,
      conversationRefreshToken: _conversationInvalidationRevision,
      reconnectRetryIn:
          _gatewayConnectionState ==
                  GatewayInvalidationConnectionState.reconnecting
              ? _gatewayReconnectRetryIn
              : null,
      onRetryConnection:
          _gatewayConnectionState ==
                  GatewayInvalidationConnectionState.reconnecting
              ? _retryGatewayConnection
              : null,
    );
  }

  void _expandWideSidebarLevel() {
    final next = expandWideSidebarLevel(_wideSidebarState);
    if (next == _wideSidebarState) {
      return;
    }
    setState(() {
      _wideSidebarState = next;
      _wideSidebarDragDelta = 0;
    });
  }

  void _toggleWideSidebarLevel() {
    final next = toggleWideSidebarLevel(_wideSidebarState);
    setState(() {
      _wideSidebarState = next;
      _wideSidebarDragDelta = 0;
    });
  }

  void _startWideSidebarDrag(DragStartDetails details) {
    _wideSidebarDragStartState = _wideSidebarState;
    _wideSidebarDragDelta = 0;
  }

  void _updateWideSidebarDrag(DragUpdateDetails details) {
    _wideSidebarDragDelta += details.delta.dx;
    final target = wideSidebarTargetForDrag(
      _wideSidebarDragStartState,
      _wideSidebarDragDelta,
    );
    if (target != _wideSidebarState) {
      setState(() {
        _wideSidebarState = target;
      });
    }
  }

  void _endWideSidebarDrag(DragEndDetails details) {
    final reset = endWideSidebarDrag(_wideSidebarState);
    _wideSidebarDragDelta = reset.dragDelta;
    _wideSidebarDragStartState = reset.dragStartState;
  }

  void _collapseMobileAgents() {
    final outcome = collapseProjectHomeMobileAgents(_mobileAgentsCollapsed);
    if (!outcome.shouldUpdate) {
      return;
    }
    setState(() {
      _mobileAgentsCollapsed = outcome.collapsed;
    });
  }

  void _expandMobileAgents() {
    final outcome = expandProjectHomeMobileAgents(_mobileAgentsCollapsed);
    if (!outcome.shouldUpdate) {
      return;
    }
    setState(() {
      _mobileAgentsCollapsed = outcome.collapsed;
    });
  }

  Widget _buildProjectListScaffold(CcbProjectView view, CcbAgent? agent) {
    return ProjectHomeProjectListHost(
      view: view,
      selectedAgent: agent,
      onOpenProject: () {
        _openProject(view);
      },
      onOpenNotifications: () {
        _openNotificationCenter(view);
      },
      onOpenConnectionDetails: () {
        _openConnectionDetails(view);
      },
      hasUnreadTaskCompletion: _projectHasUnreadTaskCompletion(view.project.id),
      hasWorkingAgents: _viewHasWorkingAgents(view),
    );
  }

  CcbAgent? _selectedAgentFor(CcbProjectView view) {
    return selectedProjectHomeAgent(view, _selectedAgentName);
  }

  void _selectAgent(String agentName) {
    final outcome = selectProjectHomeAgent(agentName);
    setState(() {
      _selectionRevision += 1;
      _selectedAgentName = outcome.selectedAgentName;
    });
    unawaited(_viewFuture.then(_updateNotificationWatch));
    unawaited(
      _clearTaskCompletionUnreadForAgent(
        projectId: _activeProjectId,
        agent: agentName,
      ),
    );
    _presenceCoordinator.updateTarget(
      projectId: _activeProjectId,
      agent: agentName,
      userActivity: true,
    );
  }

  void _updateNotificationWatch(CcbProjectView view) {
    if (_mode != AppRuntimeMode.pairedGateway || _activeProjectId.isEmpty) {
      return;
    }
    final selected = _selectedAgentFor(view);
    if (selected == null) {
      _taskNotifications.updateWatch(null);
      return;
    }
    _taskNotifications.updateWatch(
      GatewayInvalidationWatch(
        projectId: view.project.id,
        agent: selected.name,
        namespaceEpoch: view.namespaceEpoch,
        provider: selected.provider,
      ),
    );
  }

  void _handleMobileTimelineScrollDirection(ScrollDirection direction) {
    if (direction == ScrollDirection.reverse) {
      _collapseMobileAgents();
    }
  }

  void _selectWindow(CcbProjectView view, String windowName) {
    if (_mode == AppRuntimeMode.pairedGateway) {
      if (view.namespaceEpoch == null) {
        unawaited(
          _focusWindow(
            view,
            windowName,
            selectionRevision: _selectionRevision,
            previousSelectedAgentName: _selectedAgentName,
          ),
        );
        return;
      }
      final outcome = selectProjectHomeLocalWindow(view, windowName);
      if (!outcome.shouldUpdate) {
        return;
      }
      final previousSelectedAgentName = _selectedAgentName;
      final selectionRevision = ++_selectionRevision;
      setState(() {
        _selectedAgentName = outcome.selectedAgentName;
      });
      unawaited(
        _focusWindow(
          view,
          windowName,
          selectionRevision: selectionRevision,
          previousSelectedAgentName: previousSelectedAgentName,
        ),
      );
      return;
    }
    final outcome = selectProjectHomeLocalWindow(view, windowName);
    if (!outcome.shouldUpdate) {
      return;
    }
    setState(() {
      _selectionRevision += 1;
      _selectedAgentName = outcome.selectedAgentName;
    });
  }

  void _openProject(CcbProjectView view) {
    final outcome = openProjectHomeProject(view);
    setState(() {
      _openedProjectId = outcome.openedProjectId;
    });
  }

  void _openServerProject(CcbProject project) {
    setState(() {
      _rememberProjectUsed(project.id);
      _activeProjectId = project.id;
      _openedProjectId = project.id;
      _selectedAgentName = null;
      _viewFuture = _loadActiveProjectView();
    });
    _presenceCoordinator.updateTarget(
      projectId: project.id,
      agent: null,
      userActivity: true,
    );
    unawaited(_restoreProjectViewSnapshot(project.id));
  }

  Future<void> _restoreGatewayProjectListSnapshot(
    GatewayPairedHost profile,
  ) async {
    final namespace = mobileSnapshotNamespace(
      hostId: profile.profile.hostId,
      deviceId: profile.profile.deviceId,
    );
    final record = await _snapshotStore.readRecord(
      mobileProjectsSnapshotKey(namespace),
    );
    final projects =
        record == null
            ? const <CcbProject>[]
            : projectsFromSnapshotPayload(record.payload);
    if (!mounted || !_isActiveGatewayProfile(profile) || projects.isEmpty) {
      return;
    }
    setState(() {
      if (_activeProjectId.isEmpty) {
        _serverProjectsFuture = SynchronousFuture(projects);
      }
    });
    if (record?.isStale == true) {
      _showSnack('Showing cached project list while reconnecting');
    }
    // The cached list is only a startup frame. Authoritative data replaces it
    // in the background without requiring a user tap.
    try {
      final fresh = await _loadServerProjects();
      if (mounted &&
          _isActiveGatewayProfile(profile) &&
          _activeProjectId.isEmpty) {
        setState(() {
          _serverProjectsFuture = SynchronousFuture(fresh);
        });
      }
    } catch (_) {}
  }

  Future<void> _restoreProjectViewSnapshot(String projectId) async {
    final namespace = _snapshotNamespace;
    if (namespace == null) {
      return;
    }
    final record = await _snapshotStore.readLatestRecordWithPrefix(
      mobileProjectViewSnapshotPrefix(
        namespace: namespace,
        projectId: projectId,
      ),
    );
    final snapshot =
        record == null ? null : projectViewFromSnapshotPayload(record.payload);
    if (!mounted ||
        snapshot == null ||
        snapshot.project.id != projectId ||
        _activeProjectId != projectId) {
      return;
    }
    setState(() {
      _viewFuture = SynchronousFuture(snapshot);
      _selectedAgentName ??=
          snapshot.agents.isEmpty ? null : snapshot.agents.first.name;
    });
    if (record?.isStale == true) {
      _showSnack('Showing cached snapshot while reconnecting');
    }
    unawaited(_refreshActiveView());
  }

  void _closeProject() {
    if (_mode == AppRuntimeMode.pairedGateway) {
      _returnToServerProjectList();
      return;
    }
    final outcome = closeProjectHomeProject();
    setState(() {
      _openedProjectId = outcome.openedProjectId;
    });
  }

  Future<void> _bootstrapProfiles() async {
    final debugProfile = debugPairedHostFromEnvironment();
    if (debugProfile != null) {
      setState(() {
        _loadingProfiles = true;
      });
    }
    final outcome = await _profileLoadingCoordinator.bootstrap(
      selectedProfile: _selectedProfile,
      debugProfile: debugProfile,
      autoActivateDebugProfile: debugAutoActivatePairedHost,
    );
    if (!mounted) {
      return;
    }
    switch (outcome.kind) {
      case ProjectHomeProfileBootstrapLoadKind.loadRequired:
        await _loadProfiles();
      case ProjectHomeProfileBootstrapLoadKind.success:
        final result = outcome.result!;
        setState(() {
          _profiles = result.profiles;
          _selectedProfile = result.selectedProfile;
          _loadingProfiles = false;
          _profilesInitialized = true;
        });
        final activateProfile =
            result.activateProfile ??
            (widget.autoActivateStoredProfile ? result.selectedProfile : null);
        if (activateProfile != null) {
          _activateGatewayProfile(activateProfile);
        }
      case ProjectHomeProfileBootstrapLoadKind.fallbackToLoad:
        setState(() {
          _loadingProfiles = false;
        });
        await _loadProfiles();
    }
  }

  Future<void> _loadProfiles() async {
    setState(() {
      _loadingProfiles = true;
    });
    final outcome = await _profileLoadingCoordinator.load(
      selectedProfile: _selectedProfile,
    );
    if (!mounted) {
      return;
    }
    switch (outcome.kind) {
      case ProjectHomeProfileLoadKind.success:
        final result = outcome.result!;
        setState(() {
          _profiles = result.profiles;
          _selectedProfile = result.selectedProfile;
          _loadingProfiles = false;
          _profilesInitialized = true;
        });
        final activateProfile =
            widget.autoActivateStoredProfile ? result.selectedProfile : null;
        if (activateProfile != null) {
          _activateGatewayProfile(activateProfile);
        }
      case ProjectHomeProfileLoadKind.failure:
        setState(() {
          _loadingProfiles = false;
          _profilesInitialized = true;
        });
    }
  }

  void _setRuntimeMode(AppRuntimeMode mode) {
    switch (mode) {
      case AppRuntimeMode.fake:
        _gatewayProfileActivationSucceeded = false;
        _requestBackgroundConnectionReconcile();
        final reset = resetProjectHomeFakeRuntime(
          defaultProjectId: _defaultProjectId,
        );
        final session = _runtimeSessionCoordinator.activateFake(
          repository: widget.repository,
          defaultProjectId: reset.defaultProjectId,
        );
        setState(() {
          _mode = mode;
          _showPairingSetup = false;
          _activeRepository = session.repository;
          _activeProjectId = session.activeProjectId;
          _serverProjectsFuture = null;
          _openedProjectId = null;
          _selectedAgentName = null;
          _terminalTransport = session.terminalTransport;
          _gatewayConnectionState =
              GatewayInvalidationConnectionState.connected;
          _gatewayReconnectRetryIn = null;
          _viewFuture = session.viewFuture;
        });
        _stopTaskCompletionNotifications();
        _presenceCoordinator.stop();
        _connectionSupervisor.stop();
        _lifecycleResultNotifier.value = null;
      case AppRuntimeMode.pairedGateway:
        final selection = selectProjectHomePairedRuntimeProfile(
          profiles: _profiles,
          selectedProfile: _selectedProfile,
        );
        if (selection.kind == ProjectHomePairedRuntimeSelectionKind.noProfile) {
          _showSnack(selection.snackMessage!);
          return;
        }
        _activateGateway(selection.activation!);
    }
  }

  void _selectGatewayProfile(GatewayPairedHost profile) {
    _activateGatewayProfile(profile);
  }

  void _activateGatewayProfile(GatewayPairedHost profile) {
    _activateGateway(activateProjectHomeGatewayProfile(profile));
  }

  void _activateGateway(ProjectHomeGatewayActivationData activation) {
    _detachGatewayOutcomeReporters();
    final activationGeneration = ++_gatewayActivationGeneration;
    _gatewayProfileActivationSucceeded = false;
    _requestBackgroundConnectionReconcile();
    _pairingForm.applyGatewayActivation(
      gatewayUrlText: activation.gatewayUrlText,
      routeKind: activation.routeKind,
    );
    final session = _runtimeSessionCoordinator.activateGateway(
      activation: activation,
      repositoryFactory: widget.gatewayRepositoryFactory,
      terminalTransportFactory: widget.gatewayTerminalTransportFactory,
    );
    final profile = session.activation.profile;
    unawaited(
      _completeGatewayProfileActivation(
        profile,
        session.projectsFuture,
        activationGeneration: activationGeneration,
      ),
    );
    setState(() {
      _mode = AppRuntimeMode.pairedGateway;
      _showPairingSetup = false;
      _selectedProfile = profile;
      _routeDiagnostics = null;
      _activeRepository = session.repository;
      _activeProjectId = '';
      _serverProjectsFuture = session.projectsFuture;
      _openedProjectId = null;
      _selectedAgentName = null;
      _terminalTransport = session.terminalTransport;
      _gatewayConnectionState = GatewayInvalidationConnectionState.connected;
      _gatewayReconnectRetryIn = null;
    });
    _connectionSupervisor.start(
      profile: profile,
      probe:
          session.repository is MobileGatewayProfileHealthProbe
              ? session.repository as MobileGatewayProfileHealthProbe
              : null,
      probeImmediately: false,
    );
    final outcomeAdapter = MobileConnectionOutcomeAdapter(
      supervisor: _connectionSupervisor,
      isCurrent:
          () => _isActiveGatewayProfile(
            profile,
            activationGeneration: activationGeneration,
          ),
    );
    _connectionOutcomeAdapter = outcomeAdapter;
    final repository = session.repository;
    if (repository case final GatewayConnectionOutcomeReportable reportable) {
      reportable.outcomeReporter = outcomeAdapter;
    }
    final terminalTransport = session.terminalTransport;
    if (terminalTransport
        case final GatewayConnectionOutcomeReportable reportable) {
      reportable.outcomeReporter = outcomeAdapter;
    }
    _presenceCoordinator.start(
      reporter:
          session.repository is MobileGatewayPresenceReporter
              ? session.repository as MobileGatewayPresenceReporter
              : null,
      visible: _appLifecycleState == AppLifecycleState.resumed,
    );
    _startTaskCompletionNotifications(profile);
    unawaited(_pushNotifications.start(profile));
    _lifecycleResultNotifier.value = null;
    unawaited(_restoreGatewayProjectListSnapshot(profile));
  }

  Future<void> _completeGatewayProfileActivation(
    GatewayPairedHost profile,
    Future<List<CcbProject>> projectsFuture, {
    int? activationGeneration,
  }) async {
    try {
      await projectsFuture;
    } catch (error) {
      if (!_isActiveGatewayProfile(
        profile,
        activationGeneration: activationGeneration,
      )) {
        return;
      }
      await _gatewayRequestFailure(profile, error);
      return;
    }
    if (!_isActiveGatewayProfile(
      profile,
      activationGeneration: activationGeneration,
    )) {
      return;
    }
    _connectionSupervisor.reportSuccess();
    _gatewayProfileActivationSucceeded = true;
    _requestBackgroundConnectionReconcile();
    await widget.profileStore.markSuccessful(profile);
  }

  bool _isActiveGatewayProfile(
    GatewayPairedHost profile, {
    int? activationGeneration,
  }) {
    return mounted &&
        _mode == AppRuntimeMode.pairedGateway &&
        (activationGeneration == null ||
            activationGeneration == _gatewayActivationGeneration) &&
        _selectedProfile != null &&
        projectHomeGatewayProfileKey(_selectedProfile!) ==
            projectHomeGatewayProfileKey(profile);
  }

  Future<void> _invalidateGatewayProfile(GatewayPairedHost? profile) async {
    if (profile == null) {
      return;
    }
    final namespace = mobileSnapshotNamespace(
      hostId: profile.profile.hostId,
      deviceId: profile.profile.deviceId,
    );
    // Local app-private cleanup must not delay security fail-closed profile
    // revocation when a platform storage plugin is unavailable.
    unawaited(_snapshotStore.clearNamespace(namespace));
    unawaited(_invalidationCursorStore.clear(profile));
    try {
      await widget.profileStore.delete(
        hostId: profile.profile.hostId,
        deviceId: profile.profile.deviceId,
      );
    } catch (_) {
      return;
    }
    if (!_isActiveGatewayProfile(profile)) {
      return;
    }
    setState(() {
      _profiles = _profiles
          .where(
            (candidate) =>
                projectHomeGatewayProfileKey(candidate) !=
                projectHomeGatewayProfileKey(profile),
          )
          .toList(growable: false);
      _selectedProfile = null;
    });
    _requestBackgroundConnectionReconcile();
  }

  void _returnToPairingSetup() {
    _gatewayActivationGeneration += 1;
    _gatewayProfileActivationSucceeded = false;
    _requestBackgroundConnectionReconcile();
    _detachGatewayOutcomeReporters();
    _stopTaskCompletionNotifications();
    unawaited(_pushNotifications.stop());
    _presenceCoordinator.stop();
    _connectionSupervisor.stop();
    _connectionOutcomeAdapter = null;
    setState(() {
      _mode = AppRuntimeMode.fake;
      _showPairingSetup = true;
      _activeRepository = widget.repository;
      _activeProjectId = _defaultProjectId;
      _serverProjectsFuture = null;
      _openedProjectId = null;
      _selectedAgentName = null;
      _terminalTransport = null;
      _gatewayConnectionState = GatewayInvalidationConnectionState.stopped;
      _gatewayReconnectRetryIn = null;
      _routeDiagnostics = null;
      _viewFuture = _loadActiveProjectView();
    });
    _lifecycleResultNotifier.value = null;
  }

  void _detachGatewayOutcomeReporters() {
    final repository = _activeRepository;
    if (repository case final GatewayConnectionOutcomeReportable reportable) {
      reportable.outcomeReporter = null;
    }
    final terminalTransport = _terminalTransport;
    if (terminalTransport
        case final GatewayConnectionOutcomeReportable reportable) {
      reportable.outcomeReporter = null;
    }
  }

  void _openPairingSettings() {
    setState(() {
      _showPairingSetup = true;
    });
    unawaited(_refreshBackgroundConnectionSystemStatus());
  }

  Future<void> _scanGatewayProfile() async {
    final outcome = await _pairingFlowCoordinator.scan(
      isClaimingPairing: _claimingPairing,
      scanner: () => widget.pairingScanner(context),
    );
    if (!mounted) {
      return;
    }
    switch (outcome.kind) {
      case ProjectHomePairingFlowScanOutcomeKind.busy:
      case ProjectHomePairingFlowScanOutcomeKind.canceled:
        return;
      case ProjectHomePairingFlowScanOutcomeKind.success:
        final pairing = outcome.pairingToApply!;
        setState(() {
          _pairingForm.applyScannedPairing(pairing);
        });
        await _claimGatewayProfile(pairingOverride: outcome.pairingToClaim);
      case ProjectHomePairingFlowScanOutcomeKind.failure:
        _showSnack(outcome.snackMessage!);
    }
  }

  Future<void> _claimGatewayProfile({
    GatewayPairingPayload? pairingOverride,
  }) async {
    final requestOutcome = _pairingFlowCoordinator.buildRequest(
      builder: _pairingForm.buildRequest,
      pairingOverride: pairingOverride,
    );
    if (requestOutcome.kind == ProjectHomePairingRequestOutcomeKind.invalid) {
      _showSnack(requestOutcome.snackMessage!);
      return;
    }
    setState(() {
      _claimingPairing = true;
    });
    final outcome = await _pairingFlowCoordinator.claim(
      request: requestOutcome.request!,
      claimAndStore: widget.pairingClaimAndStore,
      store: widget.profileStore,
      mergeProfiles: _profileBootstrapper.mergeStoredWith,
    );
    if (!mounted) {
      return;
    }
    switch (outcome.kind) {
      case ProjectHomePairingFlowClaimOutcomeKind.success:
        setState(() {
          _profiles = outcome.profiles!;
          _pairingForm.clearPairingCode();
          _claimingPairing = false;
        });
        _activateGatewayProfile(outcome.paired!);
        _showSnack(outcome.snackMessage!);
      case ProjectHomePairingFlowClaimOutcomeKind.failure:
        setState(() {
          _claimingPairing = false;
        });
        _showSnack(outcome.snackMessage!);
    }
  }

  void _setPairingRouteKind(RouteProviderKind value) {
    _pairingForm.setRouteKind(value);
  }

  Future<void> _checkGatewayRoute() async {
    final profile = _selectedProfile;
    final beginOutcome = _routeDiagnosticsCoordinator.begin(
      selectedProfile: _selectedProfile,
      checking: _checkingRoute,
    );
    if (beginOutcome.kind == ProjectHomeRouteDiagnosticsOutcomeKind.noProfile) {
      _showSnack(beginOutcome.snackMessage!);
      return;
    }
    if (beginOutcome.kind == ProjectHomeRouteDiagnosticsOutcomeKind.busy) {
      return;
    }
    if (beginOutcome.kind != ProjectHomeRouteDiagnosticsOutcomeKind.ready) {
      return;
    }
    setState(() {
      _checkingRoute = true;
    });
    final outcome = await _routeDiagnosticsCoordinator.complete(
      profile: profile!,
      diagnostics: widget.gatewayRouteDiagnostics,
    );
    if (!mounted) {
      return;
    }
    if (outcome.kind == ProjectHomeRouteDiagnosticsOutcomeKind.success) {
      final report = outcome.report!;
      setState(() {
        _routeDiagnostics = report;
        _checkingRoute = false;
      });
      _showSnack(outcome.snackMessage!);
      return;
    }
    if (outcome.kind == ProjectHomeRouteDiagnosticsOutcomeKind.failure) {
      setState(() {
        _checkingRoute = false;
      });
      _showSnack(outcome.snackMessage!);
    }
  }

  Future<void> _requestLifecycle(
    CcbProjectView view,
    CcbLifecycleAction action,
  ) async {
    final beginOutcome = _lifecycleCoordinator.begin(
      runningAction: _runningLifecycleAction,
      action: action,
    );
    if (beginOutcome.kind == ProjectHomeLifecycleOutcomeKind.busy) {
      return;
    }
    if (beginOutcome.kind ==
        ProjectHomeLifecycleOutcomeKind.needsStopConfirmation) {
      final confirmed = await _confirmStopProject(view);
      if (confirmed != true || !mounted) {
        return;
      }
    }
    setState(() {
      _runningLifecycleAction = action;
    });
    _runningLifecycleActionNotifier.value = action;
    final outcome = await _lifecycleCoordinator.complete(
      repository: _activeRepository,
      projectId: view.project.id,
      action: action,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _runningLifecycleAction = null;
      final refreshed = outcome.refreshedView;
      if (refreshed != null) {
        _viewFuture = Future<CcbProjectView>.value(refreshed);
      }
    });
    final result = outcome.result;
    if (result != null) {
      _lifecycleResultNotifier.value = result;
    }
    _runningLifecycleActionNotifier.value = null;
    _showSnack(outcome.snackMessage!);
  }

  Future<bool?> _confirmStopProject(CcbProjectView view) {
    return confirmProjectHomeStop(context, view: view);
  }

  Future<CcbProjectView?> _refreshActiveView({
    String? preserveSelectedAgentName,
  }) async {
    final projectId = _activeProjectId;
    final selectionRevision = _selectionRevision;
    final outcome = await _viewRefreshCoordinator.refresh(
      repository: _activeRepository,
      projectId: projectId,
      selectedAgentName: preserveSelectedAgentName ?? _selectedAgentName,
    );
    if (!mounted || _activeProjectId != projectId) {
      return null;
    }
    if (outcome.kind == ProjectHomeViewRefreshOutcomeKind.success) {
      final refreshed = outcome.refreshedView!;
      _persistProjectViewSnapshot(refreshed);
      _updateNotificationWatch(refreshed);
      setState(() {
        _viewFuture = SynchronousFuture(refreshed);
        if (_selectionRevision == selectionRevision) {
          _selectedAgentName = outcome.selectedAgentName;
        }
      });
      return refreshed;
    }
    if (mounted) {
      if (_mode == AppRuntimeMode.pairedGateway && _selectedProfile != null) {
        setState(() {
          _gatewayConnectionState =
              GatewayInvalidationConnectionState.reconnecting;
          _gatewayReconnectRetryIn ??= const Duration(seconds: 1);
        });
      }
      _showSnack(outcome.snackMessage!);
    }
    return null;
  }

  bool get _sendEnabled =>
      _mode != AppRuntimeMode.pairedGateway ||
      _gatewayConnectionState !=
          GatewayInvalidationConnectionState.reconnecting;

  String? get _sendDisabledReason {
    if (_mode != AppRuntimeMode.pairedGateway) {
      return null;
    }
    if (_gatewayConnectionState ==
        GatewayInvalidationConnectionState.reconnecting) {
      final seconds = _gatewayReconnectRetryIn?.inSeconds;
      return seconds == null || seconds <= 0
          ? 'Reconnecting. Sending is disabled.'
          : 'Reconnecting. Retry in ${seconds}s.';
    }
    return 'Refresh target before sending';
  }

  void _handleSupervisorState(MobileConnectionSnapshot snapshot) {
    if (!mounted || _mode != AppRuntimeMode.pairedGateway) return;
    if (snapshot.state == MobileConnectionState.authenticationRequired) {
      final profile = _selectedProfile;
      if (profile != null) {
        final wasActivated = _gatewayProfileActivationSucceeded;
        unawaited(() async {
          await _invalidateGatewayProfile(profile);
          if (mounted && wasActivated) _returnToPairingSetup();
        }());
      }
      return;
    }
    if (snapshot.state == MobileConnectionState.online) {
      final wasReconnecting =
          _gatewayConnectionState ==
          GatewayInvalidationConnectionState.reconnecting;
      _markGatewayRequestSucceeded();
      if (wasReconnecting) {
        _taskNotifications.retryNow();
        _verifyGatewayRecovery();
      }
      return;
    }
    if (snapshot.state == MobileConnectionState.reconnecting ||
        snapshot.state == MobileConnectionState.offline) {
      setState(() {
        _gatewayConnectionState =
            GatewayInvalidationConnectionState.reconnecting;
        _gatewayReconnectRetryIn = snapshot.retryIn;
      });
    }
  }

  void _handleGatewayConnectionStateChanged(
    GatewayInvalidationConnectionState state,
    Duration? _,
  ) {
    if (!mounted || _mode != AppRuntimeMode.pairedGateway) {
      return;
    }
    // The notification SSE is an optional live-update channel. Its transport
    // can reconnect independently while ordinary gateway HTTP requests remain
    // healthy, so it must not disable chat or insert/remove gateway UI.
    if (state == GatewayInvalidationConnectionState.connected) {
      _connectionOutcomeAdapter?.succeeded(GatewayConnectionOperation.stream);
    }
    if (state == GatewayInvalidationConnectionState.connected &&
        _gatewayConnectionState ==
            GatewayInvalidationConnectionState.reconnecting) {
      _verifyGatewayRecovery();
    } else if (state == GatewayInvalidationConnectionState.reconnecting) {
      _connectionSupervisor.reportFailure(
        TimeoutException('notification stream disconnected'),
        kind: MobileTransportKind.sse,
      );
    }
  }

  void _markGatewayRequestSucceeded() {
    if (!mounted ||
        _mode != AppRuntimeMode.pairedGateway ||
        (_gatewayConnectionState ==
                GatewayInvalidationConnectionState.connected &&
            _gatewayReconnectRetryIn == null)) {
      return;
    }
    setState(() {
      _gatewayConnectionState = GatewayInvalidationConnectionState.connected;
      _gatewayReconnectRetryIn = null;
    });
  }

  void _retryGatewayConnection() {
    _connectionSupervisor.retryNow();
    _taskNotifications.retryNow();
  }

  void _verifyGatewayRecovery() {
    if (_gatewayRecoveryInFlight) {
      return;
    }
    _gatewayRecoveryInFlight = true;
    unawaited(() async {
      try {
        await _refreshAfterGatewayReconnect(requireSuccess: true);
      } catch (_) {
        // The existing reconnect banner remains until a core gateway request
        // succeeds; the next stream recovery or manual Retry probes again.
      } finally {
        _gatewayRecoveryInFlight = false;
      }
    }());
  }

  void _handleGatewayStreamError(Object error) {
    if (error is! GatewayTaskCompletionNotificationStreamException) {
      return;
    }
    _connectionOutcomeAdapter?.failed(GatewayConnectionOperation.stream, error);
  }

  Future<void> _refreshAfterGatewayReconnect({
    bool requireSuccess = false,
  }) async {
    if (_activeProjectId.isEmpty) {
      try {
        final projects = await _fetchServerProjects();
        if (mounted && _activeProjectId.isEmpty) {
          setState(() {
            _serverProjectsFuture = SynchronousFuture(projects);
          });
        }
      } catch (_) {
        if (requireSuccess) {
          rethrow;
        }
      }
      return;
    }
    if (requireSuccess) {
      final refreshed = await _refreshActiveView();
      if (refreshed == null) {
        throw StateError('gateway resync refresh did not complete');
      }
      if (mounted) {
        setState(() {
          _conversationInvalidationRevision += 1;
        });
      }
      return;
    }
    await _scheduleInvalidationRefresh(conversationChanged: true);
  }

  Future<void> _handleGatewayInvalidationEvent(
    TaskCompletionNotificationEvent event,
  ) async {
    if (!event.isInvalidation || _mode != AppRuntimeMode.pairedGateway) {
      return;
    }
    if (event.isResyncRequired) {
      await _refreshAfterGatewayReconnect(requireSuccess: true);
      return;
    }
    if (event.kind ==
            TaskCompletionNotificationEvent.projectSummaryChangedKind &&
        _activeProjectId.isEmpty) {
      try {
        final projects = await _fetchServerProjects();
        if (mounted && _activeProjectId.isEmpty) {
          setState(() {
            _serverProjectsFuture = SynchronousFuture(projects);
          });
        }
      } catch (_) {}
      return;
    }
    if (event.projectId == _activeProjectId) {
      await _scheduleInvalidationRefresh(
        conversationChanged:
            event.kind ==
            TaskCompletionNotificationEvent.conversationChangedKind,
      );
    }
  }

  Future<void> _scheduleInvalidationRefresh({
    required bool conversationChanged,
  }) async {
    if (_invalidationRefreshInFlight) {
      _invalidationRefreshQueued =
          _invalidationRefreshQueued || conversationChanged;
      return;
    }
    _invalidationRefreshInFlight = true;
    try {
      final refreshed = await _refreshActiveView();
      if (refreshed != null && mounted && conversationChanged) {
        setState(() {
          _conversationInvalidationRevision += 1;
        });
      }
    } finally {
      _invalidationRefreshInFlight = false;
      if (_invalidationRefreshQueued) {
        final queuedConversation = _invalidationRefreshQueued;
        _invalidationRefreshQueued = false;
        unawaited(
          _scheduleInvalidationRefresh(conversationChanged: queuedConversation),
        );
      }
    }
  }

  Future<CcbProjectView?> _focusWindow(
    CcbProjectView view,
    String windowName, {
    required int selectionRevision,
    required String? previousSelectedAgentName,
  }) async {
    final projectId = view.project.id;
    final outcome = await _focusCoordinator.focusWindow(
      repository: _activeRepository,
      view: view,
      windowName: windowName,
      previousSelectedAgentName: previousSelectedAgentName,
    );
    if (!mounted || _activeProjectId != projectId) {
      return null;
    }
    if (outcome.kind == ProjectHomeFocusOutcomeKind.stale) {
      if (_selectionRevision == selectionRevision) {
        setState(() {
          _selectedAgentName = previousSelectedAgentName;
        });
      }
      _showSnack(outcome.snackMessage!);
      return null;
    }
    if (outcome.kind == ProjectHomeFocusOutcomeKind.success) {
      final focusedView = outcome.focusedView!;
      _rememberProjectActivity(focusedView);
      setState(() {
        _rememberProjectUsed(focusedView.project.id);
        if (_selectionRevision == selectionRevision) {
          _selectedAgentName = outcome.selectedAgentName;
        }
        _viewFuture = Future<CcbProjectView>.value(focusedView);
      });
      final selectedAgent = outcome.selectedAgentName;
      if (selectedAgent != null) {
        unawaited(
          _clearTaskCompletionUnreadForAgent(
            projectId: focusedView.project.id,
            agent: selectedAgent,
          ),
        );
      }
      return focusedView;
    }
    setState(() {
      _viewFuture = Future<CcbProjectView>.value(outcome.originalView!);
      if (_selectionRevision == selectionRevision) {
        _selectedAgentName = previousSelectedAgentName;
      }
    });
    _showSnack(outcome.snackMessage!);
    return null;
  }

  Future<void> _openAgentTerminal(CcbProjectView view, String agentName) async {
    if (_mode == AppRuntimeMode.pairedGateway) {
      final transport = _terminalTransport;
      final outcome = projectHomeGatewayTerminalNavigation(
        view: view,
        agentName: agentName,
        hasTerminalTransport: transport != null,
      );
      if (outcome.kind == ProjectHomeTerminalNavigationKind.noTransport) {
        _showSnack(outcome.snackMessage!);
        return;
      }
      if (outcome.kind != ProjectHomeTerminalNavigationKind.open) {
        return;
      }
      final spec = outcome.spec!;
      await pushProjectHomeTerminalRoute(
        context,
        repository: _activeRepository,
        projectId: spec.projectId,
        agentName: spec.agentName,
        expectedNamespaceEpoch: spec.namespaceEpoch,
        expectedWindowName: spec.windowName,
        expectedPaneId: spec.paneId,
        terminalTransport: transport,
        gatewayTerminal: spec.gatewayTerminal,
      );
      return;
    }
    final outcome = projectHomeFakeTerminalNavigation(
      view: view,
      agentName: agentName,
    );
    final spec = outcome.spec!;
    pushProjectHomeTerminalRoute(
      context,
      repository: _activeRepository,
      projectId: spec.projectId,
      agentName: spec.agentName,
      terminalTransport: null,
      gatewayTerminal: spec.gatewayTerminal,
    );
  }

  void _openConnectionDetails(CcbProjectView view) {
    pushProjectHomeConnectionDetailsRoute(
      context,
      panel: ProjectHomeConnectionDetailsPanelHost(
        view: view,
        mode: _mode,
        profiles: _profiles,
        selectedProfile: _selectedProfile,
        routeDiagnostics: _routeDiagnostics,
        lifecycleResultListenable: _lifecycleResultNotifier,
        loadingProfiles: _loadingProfiles,
        checkingRoute: _checkingRoute,
        runningLifecycleActionListenable: _runningLifecycleActionNotifier,
        onModeChanged: _setRuntimeMode,
        onProfileSelected: _selectGatewayProfile,
        onCheckRoute: _checkGatewayRoute,
        onLifecycleAction: (action) {
          _requestLifecycle(view, action);
        },
      ),
    );
  }

  void _openNotificationCenter(CcbProjectView view) {
    showProjectHomeNotificationCenter(
      context,
      notifications: view.notifications,
      onOpen: (notification) {
        _openNotificationTarget(view, notification);
      },
    );
  }

  void _openNotificationTarget(
    CcbProjectView view,
    CcbNotification notification,
  ) {
    final outcome = resolveProjectHomeNotificationOpenOutcome(
      view,
      notification,
    );
    if (outcome.openedProjectId != null && outcome.selectedAgentName != null) {
      setState(() {
        _openedProjectId = outcome.openedProjectId;
        _selectedAgentName = outcome.selectedAgentName;
      });
    }
    _showSnack(outcome.snackMessage);
  }

  bool get _shouldRunBackgroundConnectionService =>
      widget.backgroundConnectionPreferenceLoaded &&
      widget.backgroundConnectionEnabled &&
      _mode == AppRuntimeMode.pairedGateway &&
      _selectedProfile != null &&
      _gatewayProfileActivationSucceeded;

  Future<void> _refreshBackgroundConnectionSystemStatus() async {
    final generation = ++_backgroundConnectionSystemStatusGeneration;
    if (mounted) {
      setState(() {
        _backgroundConnectionSystemStatusLoading = true;
      });
    }
    BackgroundConnectionSystemStatus? status;
    try {
      status = await widget.backgroundConnectionPlatform.readSystemStatus();
    } on BackgroundConnectionPlatformException {
      status = null;
    }
    if (!mounted || generation != _backgroundConnectionSystemStatusGeneration) {
      return;
    }
    setState(() {
      _backgroundConnectionSystemStatus = status;
      _backgroundConnectionSystemStatusLoading = false;
    });
  }

  Future<void> _openBackgroundConnectionSystemSettings() async {
    var opened = false;
    try {
      opened = await widget.backgroundConnectionPlatform.openSystemSettings();
    } on BackgroundConnectionPlatformException {
      opened = false;
    }
    if (!mounted || opened) {
      return;
    }
    _showSnack(
      CcbMobileLocalizations.of(
        context,
      ).backgroundConnectionSystemSettingsCouldNotOpen,
    );
  }

  void _requestBackgroundConnectionReconcile() {
    if (!widget.backgroundConnectionPreferenceLoaded) {
      return;
    }
    _backgroundConnectionRuntime.update(
      shouldRun: _shouldRunBackgroundConnectionService,
      canStart: _appLifecycleState == AppLifecycleState.resumed,
    );
  }

  void _handleBackgroundConnectionRunningChanged(bool running) {
    if (running) {
      final profile = _selectedProfile;
      if (_taskNotificationsSuspendedForBackground && profile != null) {
        _startTaskCompletionNotifications(profile);
      }
      return;
    }
    if (_appLifecycleState != AppLifecycleState.resumed) {
      _stopTaskCompletionNotifications(forBackground: true);
    }
  }

  void _handleBackgroundConnectionStartFailure() {
    if (!mounted) {
      return;
    }
    if (_appLifecycleState != AppLifecycleState.resumed) {
      _stopTaskCompletionNotifications(forBackground: true);
    }
    _showSnack(
      CcbMobileLocalizations.of(context).backgroundConnectionCouldNotStart,
    );
    widget.onBackgroundConnectionEnabledChanged?.call(false);
  }

  void _startTaskCompletionNotifications(GatewayPairedHost profile) {
    if (_appLifecycleState != AppLifecycleState.resumed &&
        !_backgroundConnectionRuntime.running) {
      _taskNotificationsSuspendedForBackground = true;
      return;
    }
    _taskNotificationsSuspendedForBackground = false;
    unawaited(_startTaskCompletionNotificationsAfterUnreadLoad(profile));
  }

  void _stopTaskCompletionNotifications({bool forBackground = false}) {
    _taskNotificationsSuspendedForBackground = forBackground;
    unawaited(_taskNotifications.stop());
  }

  Future<void> _startTaskCompletionNotificationsAfterUnreadLoad(
    GatewayPairedHost profile,
  ) async {
    final status = await _taskNotifications.start(profile);
    // Subscription should not wait for opportunistic local unread-cache IO.
    // A stream event remains durable in its own unread store if this load is
    // slow/corrupt, and the UI refreshes it independently.
    unawaited(_loadTaskCompletionUnread());
    if (_activeProjectId.isNotEmpty) {
      unawaited(_viewFuture.then(_updateNotificationWatch));
    }
    if (!mounted) {
      return;
    }
    if (status ==
        TaskCompletionNotificationSubscriptionStatus.missingNotifyScope) {
      _showSnack(taskCompletionMissingNotifyScopeMessage);
    }
  }

  void _handleTaskCompletionNotificationTap(TaskCompletionNotificationTap tap) {
    unawaited(_openTaskCompletionNotificationTap(tap));
  }

  Future<void> _loadTaskCompletionUnread() async {
    final items = await _taskCompletionUnreadStore.readUnreadItems();
    if (!mounted) {
      return;
    }
    setState(() {
      _unreadTaskCompletions = items;
    });
  }

  Future<void> _handleLiveTaskCompletionEvent(
    TaskCompletionNotificationEvent event,
  ) async {
    if (_isTaskCompletionTargetVisible(event)) {
      if (mounted) {
        setState(() {
          _rememberProjectUsed(event.projectId, usedAt: event.completedAt);
        });
      }
      await _clearTaskCompletionUnreadForAgent(
        projectId: event.projectId,
        agent: event.agent,
      );
      return;
    }
    final items = await _taskCompletionUnreadStore.addIfNew(event);
    if (!mounted) {
      return;
    }
    setState(() {
      _rememberProjectUsed(event.projectId, usedAt: event.completedAt);
      _unreadTaskCompletions = items;
    });
  }

  bool _shouldShowTaskCompletionNotification(
    TaskCompletionNotificationEvent event,
  ) {
    return !_isTaskCompletionTargetVisible(event);
  }

  bool _isTaskCompletionTargetVisible(TaskCompletionNotificationEvent event) {
    return _appLifecycleState == AppLifecycleState.resumed &&
        _visibleTaskCompletionProjectId == event.projectId &&
        _visibleTaskCompletionAgentName == event.agent;
  }

  void _setVisibleTaskCompletionTarget({
    required String? projectId,
    required String? agentName,
  }) {
    if (_visibleTaskCompletionProjectId == projectId &&
        _visibleTaskCompletionAgentName == agentName) {
      return;
    }
    _visibleTaskCompletionProjectId = projectId;
    _visibleTaskCompletionAgentName = agentName;
    _presenceCoordinator.updateTarget(projectId: projectId, agent: agentName);
  }

  Future<void> _clearTaskCompletionUnreadForAgent({
    required String projectId,
    required String agent,
  }) async {
    if (!_unreadTaskCompletions.any(
      (item) => item.projectId == projectId && item.agent == agent,
    )) {
      return;
    }
    final items = await _taskCompletionUnreadStore.clearAgent(
      projectId: projectId,
      agent: agent,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _unreadTaskCompletions = items;
    });
  }

  void _clearVisibleTaskCompletionUnread({
    required String projectId,
    required String? agentName,
  }) {
    final agent = agentName;
    if (agent == null) {
      return;
    }
    if (!_unreadTaskCompletions.any(
      (item) => item.projectId == projectId && item.agent == agent,
    )) {
      return;
    }
    final key = '$projectId\x00$agent';
    if (!_taskCompletionUnreadClearInFlight.add(key)) {
      return;
    }
    unawaited(
      _clearTaskCompletionUnreadForAgent(
        projectId: projectId,
        agent: agent,
      ).whenComplete(() {
        _taskCompletionUnreadClearInFlight.remove(key);
      }),
    );
  }

  Set<String> get _unreadProjectIds {
    return {for (final item in _unreadTaskCompletions) item.projectId};
  }

  bool _projectHasUnreadTaskCompletion(String projectId) {
    return _unreadTaskCompletions.any((item) => item.projectId == projectId);
  }

  Set<String> _unreadAgentNamesForProject(String projectId) {
    return {
      for (final item in _unreadTaskCompletions)
        if (item.projectId == projectId) item.agent,
    };
  }

  Set<String> _workingProjectIdsFor(List<CcbProject> projects) {
    return {
      for (final project in projects)
        if (project.hasWorkingAgents ||
            _knownProjectWorkingAgents[project.id] == true)
          project.id,
    };
  }

  void _rememberProjectActivity(CcbProjectView view) {
    _knownProjectWorkingAgents[view.project.id] = _viewHasWorkingAgents(view);
  }

  bool _viewHasWorkingAgents(CcbProjectView view) {
    return view.agents.any(agentHasSourceWorkingActivity);
  }

  Future<void> _openTaskCompletionNotificationTap(
    TaskCompletionNotificationTap tap,
  ) async {
    if (_mode != AppRuntimeMode.pairedGateway) {
      return;
    }
    CcbProjectView? targetView;
    try {
      targetView = await _activeRepository
          .getProjectView(tap.projectId)
          .timeout(projectHomeRuntimeViewLoadTimeout);
    } catch (_) {
      targetView = null;
    }
    if (!mounted) {
      return;
    }
    final route = resolveProjectHomeTaskCompletionNotificationTap(
      tap: tap,
      targetView: targetView,
    );
    switch (route.kind) {
      case ProjectHomeTaskCompletionNotificationRouteKind.openProjectAgent:
        _rememberProjectActivity(route.view!);
        setState(() {
          _activeProjectId = route.projectId!;
          _openedProjectId = route.projectId;
          _selectedAgentName = route.agentName;
          _serverProjectsFuture = null;
          _viewFuture = SynchronousFuture(route.view!);
        });
        unawaited(
          _clearTaskCompletionUnreadForAgent(
            projectId: route.projectId!,
            agent: route.agentName!,
          ),
        );
      case ProjectHomeTaskCompletionNotificationRouteKind.projectList:
        setState(() {
          _activeProjectId = '';
          _openedProjectId = null;
          _selectedAgentName = null;
          _serverProjectsFuture = _loadServerProjects();
        });
    }
  }

  Future<void> _handlePushNotificationRoute(PushNotificationRoute route) async {
    if (_mode != AppRuntimeMode.pairedGateway) {
      return;
    }
    // The cursor stream is foreground-only. Reconnect it before resolving the
    // route so a tap cannot turn a notification into a terminal operation.
    await _taskNotifications.catchUpNow();
    await _openTaskCompletionNotificationTap(
      TaskCompletionNotificationTap(
        projectId: route.projectId,
        agent: route.agent,
      ),
    );
  }

  Future<void> _handleForegroundPushNotificationRoute(
    PushNotificationRoute route,
  ) async {
    if (_mode != AppRuntimeMode.pairedGateway) {
      return;
    }
    await _taskNotifications.catchUpNow();
  }

  void _showSnack(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(message)));
  }
}
