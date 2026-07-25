import 'dart:async';

import 'package:flutter/material.dart';

import '../../models/ccb_agent.dart';
import '../../models/ccb_project_view.dart';
import '../../models/ccb_terminal_target.dart';
import '../../repository/mobile_ccb_repository.dart';
import '../../transport/terminal_transport.dart';
import 'agent_terminal_pane.dart';

class AgentTerminalWorkspace extends StatefulWidget {
  const AgentTerminalWorkspace({
    required this.repository,
    required this.view,
    required this.agent,
    required this.terminalTransport,
    required this.gatewayTerminal,
    required this.active,
    super.key,
  });

  final MobileCcbRepository repository;
  final CcbProjectView view;
  final CcbAgent agent;
  final TerminalTransport? terminalTransport;
  final bool gatewayTerminal;
  final bool active;

  @override
  State<AgentTerminalWorkspace> createState() => _AgentTerminalWorkspaceState();
}

class _AgentTerminalWorkspaceState extends State<AgentTerminalWorkspace> {
  _AgentTerminalWorkspaceModel? _model;
  Object? _error;
  var _validationGeneration = 0;
  var _validating = true;

  @override
  void initState() {
    super.initState();
    _validateTarget();
  }

  @override
  void didUpdateWidget(covariant AgentTerminalWorkspace oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.repository != widget.repository ||
        _expectedIdentity(oldWidget) != _expectedIdentity(widget)) {
      _validateTarget();
    }
  }

  @override
  void dispose() {
    _validationGeneration += 1;
    super.dispose();
  }

  void _validateTarget() {
    final generation = ++_validationGeneration;
    late final CcbTerminalTarget expected;
    try {
      expected = _expectedTarget(widget);
    } catch (error) {
      _setValidationState(() {
        _model = null;
        _error = error;
        _validating = false;
      });
      return;
    }
    _setValidationState(() {
      _validating = true;
      _error = null;
    });
    unawaited(_loadValidatedModel(expected, generation));
  }

  Future<void> _loadValidatedModel(
    CcbTerminalTarget expected,
    int generation,
  ) async {
    try {
      final latest = await widget.repository.getProjectView(expected.projectId);
      final target = latest.terminalTargetForAgent(expected.agent!);
      if (!_sameTargetIdentity(expected, target)) {
        throw StateError(
          'Project view is stale. Refresh and open terminal again.',
        );
      }
      if (!mounted || generation != _validationGeneration) {
        return;
      }
      setState(() {
        _model = _AgentTerminalWorkspaceModel(view: latest, target: target);
        _error = null;
        _validating = false;
      });
    } catch (error) {
      if (!mounted || generation != _validationGeneration) {
        return;
      }
      setState(() {
        _model = null;
        _error = error;
        _validating = false;
      });
    }
  }

  void _setValidationState(VoidCallback callback) {
    if (mounted && (_model != null || !_validating || _error != null)) {
      setState(callback);
      return;
    }
    callback();
  }

  @override
  Widget build(BuildContext context) {
    final model = _model;
    if (model == null) {
      if (_validating) {
        return const Center(
          key: ValueKey('agent-terminal-target-loading'),
          child: CircularProgressIndicator(),
        );
      }
      return Center(
        key: const ValueKey('agent-terminal-target-error'),
        child: Text('${_error ?? 'Terminal target is unavailable'}'),
      );
    }
    return Stack(
      fit: StackFit.expand,
      children: [
        IgnorePointer(
          ignoring: !widget.active || _validating,
          child: ExcludeFocus(
            excluding: !widget.active || _validating,
            child: AgentTerminalPane(
              view: model.view,
              target: model.target,
              terminalTransport: widget.terminalTransport,
              gatewayTerminal: widget.gatewayTerminal,
              showHeader: false,
              active: widget.active && !_validating,
            ),
          ),
        ),
        if (_validating)
          const ColoredBox(
            key: ValueKey('agent-terminal-target-switching'),
            color: Colors.black54,
            child: Center(child: CircularProgressIndicator()),
          ),
      ],
    );
  }
}

class _AgentTerminalWorkspaceModel {
  const _AgentTerminalWorkspaceModel({
    required this.view,
    required this.target,
  });

  final CcbProjectView view;
  final CcbTerminalTarget target;
}

CcbTerminalTarget _expectedTarget(AgentTerminalWorkspace widget) {
  return widget.view.terminalTargetForAgent(widget.agent.name);
}

Object _expectedIdentity(AgentTerminalWorkspace widget) {
  return Object.hash(
    widget.view.project.id,
    widget.view.namespaceEpoch,
    widget.agent.name,
    widget.agent.window,
    widget.agent.paneId,
  );
}

bool _sameTargetIdentity(CcbTerminalTarget expected, CcbTerminalTarget actual) {
  return expected.projectId == actual.projectId &&
      expected.namespaceEpoch == actual.namespaceEpoch &&
      expected.kind == actual.kind &&
      expected.agent == actual.agent &&
      expected.window == actual.window &&
      expected.paneId == actual.paneId;
}
