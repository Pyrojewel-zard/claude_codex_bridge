import 'package:flutter/material.dart';

import '../../l10n/ccb_mobile_localizations.dart';
import '../../models/ccb_project.dart';
import '../../models/ccb_project_view.dart';

typedef HomeTerminalProjectLoader =
    Future<CcbProjectView> Function(String projectId);

class HomeTerminalLaunchTarget {
  const HomeTerminalLaunchTarget.agent({
    required this.projectId,
    required this.agentName,
  }) : windowName = null;

  const HomeTerminalLaunchTarget.window({
    required this.projectId,
    required this.windowName,
  }) : agentName = null;

  final String projectId;
  final String? agentName;
  final String? windowName;
}

Future<HomeTerminalLaunchTarget?> showHomeTerminalLauncherSheet(
  BuildContext context, {
  required List<CcbProject> projects,
  required HomeTerminalProjectLoader loadProjectView,
}) {
  return showModalBottomSheet<HomeTerminalLaunchTarget>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder:
        (context) => FractionallySizedBox(
          heightFactor: 0.82,
          child: HomeTerminalLauncherSheet(
            projects: projects,
            loadProjectView: loadProjectView,
          ),
        ),
  );
}

class HomeTerminalLauncherSheet extends StatefulWidget {
  const HomeTerminalLauncherSheet({
    required this.projects,
    required this.loadProjectView,
    super.key,
  });

  final List<CcbProject> projects;
  final HomeTerminalProjectLoader loadProjectView;

  @override
  State<HomeTerminalLauncherSheet> createState() =>
      _HomeTerminalLauncherSheetState();
}

class _HomeTerminalLauncherSheetState extends State<HomeTerminalLauncherSheet> {
  CcbProject? _selectedProject;
  CcbProjectView? _view;
  Object? _error;
  var _loadGeneration = 0;

  bool get _loading =>
      _selectedProject != null && _view == null && _error == null;

  @override
  void dispose() {
    _loadGeneration += 1;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    final selectedProject = _selectedProject;
    return Column(
      key: const ValueKey('home-terminal-launcher-sheet'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
          child: Row(
            children: [
              if (selectedProject != null)
                IconButton(
                  key: const ValueKey('home-terminal-launcher-back'),
                  tooltip: strings.projects,
                  onPressed: _showProjects,
                  icon: const Icon(Icons.arrow_back),
                )
              else
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 12),
                  child: Icon(Icons.terminal),
                ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      strings.openTerminal,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Text(
                      selectedProject?.displayName ??
                          strings.chooseTerminalProject,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: strings.cancel,
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(child: _buildBody(context)),
      ],
    );
  }

  Widget _buildBody(BuildContext context) {
    if (_selectedProject == null) {
      return _buildProjects(context);
    }
    if (_loading) {
      return const Center(
        key: ValueKey('home-terminal-targets-loading'),
        child: CircularProgressIndicator(),
      );
    }
    final error = _error;
    if (error != null) {
      final strings = CcbMobileLocalizations.of(context);
      return Center(
        key: const ValueKey('home-terminal-targets-error'),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_outlined, size: 40),
              const SizedBox(height: 12),
              Text(strings.couldNotLoadProject),
              const SizedBox(height: 6),
              Text(
                '$error',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                key: const ValueKey('home-terminal-targets-retry'),
                onPressed: _reloadSelectedProject,
                icon: const Icon(Icons.refresh),
                label: Text(strings.retry),
              ),
            ],
          ),
        ),
      );
    }
    return _buildTargets(context, _view!);
  }

  Widget _buildProjects(BuildContext context) {
    final projects = widget.projects;
    final strings = CcbMobileLocalizations.of(context);
    if (projects.isEmpty) {
      return Center(child: Text(strings.noCcbProjectsFound));
    }
    return ListView.separated(
      key: const ValueKey('home-terminal-project-list'),
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: projects.length,
      separatorBuilder: (context, index) => const Divider(height: 1),
      itemBuilder: (context, index) {
        final project = projects[index];
        return ListTile(
          key: ValueKey('home-terminal-project-${project.id}'),
          leading: const Icon(Icons.folder_outlined),
          title: Text(project.displayName),
          subtitle:
              project.root.trim().isEmpty
                  ? null
                  : Text(
                    project.root,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => _selectProject(project),
        );
      },
    );
  }

  Widget _buildTargets(BuildContext context, CcbProjectView view) {
    final strings = CcbMobileLocalizations.of(context);
    final windows = [...view.windows]
      ..sort((left, right) => left.order.compareTo(right.order));
    final agents =
        view.agents.where((agent) => agent.paneId != null).toList()
          ..sort((left, right) => left.order.compareTo(right.order));
    if (windows.isEmpty && agents.isEmpty) {
      return Center(
        key: const ValueKey('home-terminal-targets-empty'),
        child: Text(strings.noTerminalTargets),
      );
    }
    return ListView(
      key: const ValueKey('home-terminal-target-list'),
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 24),
      children: [
        if (windows.isNotEmpty) ...[
          _SectionLabel(label: strings.windows),
          for (final window in windows)
            ListTile(
              key: ValueKey('home-terminal-window-${window.name}'),
              leading: Icon(
                window.active ? Icons.terminal : Icons.space_dashboard_outlined,
              ),
              title: Text(window.label),
              subtitle: Text(
                window.active ? strings.activeWindow : strings.windowTerminal,
              ),
              trailing: const Icon(Icons.open_in_new),
              onTap:
                  () => Navigator.of(context).pop(
                    HomeTerminalLaunchTarget.window(
                      projectId: view.project.id,
                      windowName: window.name,
                    ),
                  ),
            ),
        ],
        if (agents.isNotEmpty) ...[
          _SectionLabel(label: strings.agents),
          for (final agent in agents)
            ListTile(
              key: ValueKey('home-terminal-agent-${agent.name}'),
              leading: const Icon(Icons.auto_awesome),
              title: Text(agent.name),
              subtitle: Text('${agent.provider} · ${agent.window}'),
              trailing: const Icon(Icons.open_in_new),
              onTap:
                  () => Navigator.of(context).pop(
                    HomeTerminalLaunchTarget.agent(
                      projectId: view.project.id,
                      agentName: agent.name,
                    ),
                  ),
            ),
        ],
      ],
    );
  }

  void _showProjects() {
    _loadGeneration += 1;
    setState(() {
      _selectedProject = null;
      _view = null;
      _error = null;
    });
  }

  void _selectProject(CcbProject project) {
    setState(() {
      _selectedProject = project;
      _view = null;
      _error = null;
    });
    _loadProject(project);
  }

  void _reloadSelectedProject() {
    final project = _selectedProject;
    if (project == null) {
      return;
    }
    setState(() {
      _view = null;
      _error = null;
    });
    _loadProject(project);
  }

  Future<void> _loadProject(CcbProject project) async {
    final generation = ++_loadGeneration;
    try {
      final view = await widget.loadProjectView(project.id);
      if (!mounted || generation != _loadGeneration) {
        return;
      }
      setState(() {
        _view = view;
        _error = null;
      });
    } catch (error) {
      if (!mounted || generation != _loadGeneration) {
        return;
      }
      setState(() {
        _view = null;
        _error = error;
      });
    }
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 6),
      child: Text(label, style: Theme.of(context).textTheme.labelLarge),
    );
  }
}
