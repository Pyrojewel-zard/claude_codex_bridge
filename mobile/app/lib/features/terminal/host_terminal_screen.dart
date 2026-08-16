import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/chat_background.dart';
import '../../l10n/ccb_mobile_localizations.dart';
import '../../transport/terminal_transport.dart';
import 'agent_terminal_pane.dart';

class HostTerminalScreen extends StatefulWidget {
  const HostTerminalScreen({
    required this.transport,
    this.maxSessions = 6,
    super.key,
  });

  final HostTerminalTransport transport;
  final int maxSessions;

  @override
  State<HostTerminalScreen> createState() => _HostTerminalScreenState();
}

class _HostTerminalScreenState extends State<HostTerminalScreen>
    with TickerProviderStateMixin {
  var _slots = const <int>[1];
  final _paneControllers = <int, LiveTerminalPaneController>{};
  late TabController _tabController;

  int get _selectedSlot => _slots[_tabController.index];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _slots.length, vsync: this)
      ..addListener(_handleTabChanged);
  }

  @override
  void dispose() {
    _tabController
      ..removeListener(_handleTabChanged)
      ..dispose();
    super.dispose();
  }

  void _handleTabChanged() {
    if (!_tabController.indexIsChanging && mounted) {
      setState(() {});
    }
  }

  void _addTerminal() {
    final strings = CcbMobileLocalizations.of(context);
    final nextSlot =
        List<int>.generate(
          widget.maxSessions,
          (index) => index + 1,
        ).where((slot) => !_slots.contains(slot)).firstOrNull;
    if (nextSlot == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(strings.maximumTerminalsReached)));
      return;
    }
    _replaceSlots([..._slots, nextSlot], selectedSlot: nextSlot);
  }

  Future<void> _closeCurrentTerminal() async {
    final strings = CcbMobileLocalizations.of(context);
    final slot = _selectedSlot;
    final confirmed = await showDialog<bool>(
      context: context,
      builder:
          (context) => AlertDialog(
            title: Text(strings.closeTerminal),
            content: Text(
              strings.closeTerminalQuestion(strings.shellName(slot)),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(strings.cancel),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(strings.close),
              ),
            ],
          ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    await _paneControllers[slot]?.closeSession();
    Object? terminationError;
    try {
      await widget.transport.terminateHostTerminal(_slotId(slot));
    } catch (error) {
      terminationError = error;
    }
    if (!mounted) {
      return;
    }
    if (_slots.length == 1) {
      Navigator.of(context).pop();
    } else {
      final nextSlots = _slots.where((candidate) => candidate != slot).toList();
      final oldIndex = _slots.indexOf(slot);
      final nextSlot = nextSlots[oldIndex.clamp(0, nextSlots.length - 1)];
      _replaceSlots(nextSlots, selectedSlot: nextSlot);
    }
    _paneControllers.remove(slot);
    if (terminationError != null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(terminationError.toString())));
    }
  }

  void _replaceSlots(List<int> slots, {required int selectedSlot}) {
    final nextIndex = slots.indexOf(selectedSlot);
    final oldController = _tabController;
    final nextController = TabController(
      length: slots.length,
      initialIndex: nextIndex < 0 ? 0 : nextIndex,
      vsync: this,
    )..addListener(_handleTabChanged);
    setState(() {
      _slots = List.unmodifiable(slots);
      _tabController = nextController;
    });
    oldController.removeListener(_handleTabChanged);
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => oldController.dispose(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final strings = CcbMobileLocalizations.of(context);
    final hasBackground = ccbWorkspaceBackgroundEnabled(context);
    final scaffold = Scaffold(
      key: const ValueKey('host-terminal-screen'),
      backgroundColor: hasBackground ? Colors.transparent : null,
      appBar: AppBar(
        backgroundColor:
            hasBackground
                ? Theme.of(context).colorScheme.surface.withValues(alpha: 0.86)
                : null,
        title: Text(strings.computerTerminal),
        actions: [
          IconButton(
            key: const ValueKey('host-terminal-add'),
            tooltip: strings.newTerminal,
            onPressed: _slots.length < widget.maxSessions ? _addTerminal : null,
            icon: const Icon(Icons.add_box_outlined),
          ),
          IconButton(
            key: const ValueKey('host-terminal-close'),
            tooltip: strings.closeTerminal,
            onPressed: _closeCurrentTerminal,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
        bottom: TabBar(
          key: ValueKey('host-terminal-tabs-${_slots.join('-')}'),
          controller: _tabController,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: [
            for (final slot in _slots)
              Tab(
                key: ValueKey('host-terminal-tab-$slot'),
                icon: const Icon(Icons.terminal, size: 18),
                text: strings.shellName(slot),
              ),
          ],
        ),
      ),
      body: IndexedStack(
        index: _tabController.index,
        children: [
          for (final slot in _slots)
            LiveTerminalPane(
              key: ValueKey('host-terminal-pane-$slot'),
              title: strings.shellName(slot),
              subtitle: '~',
              sessionIdentity: _slotId(slot),
              terminalViewKey: ValueKey('host-terminal-view-$slot'),
              scrollDebugLabel: 'host-terminal-$slot-history',
              showHeader: false,
              active: slot == _selectedSlot,
              controller: _paneControllers.putIfAbsent(
                slot,
                LiveTerminalPaneController.new,
              ),
              openSession:
                  (geometry) => widget.transport.openHostTerminal(
                    HostTerminalOpenRequest(
                      clientSessionId: _slotId(slot),
                      displayName: strings.shellName(slot),
                      geometry: geometry,
                    ),
                  ),
            ),
        ],
      ),
    );
    return CcbWorkspaceBackground(terminal: true, child: scaffold);
  }
}

String _slotId(int slot) => 'shell-$slot';

extension<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    return iterator.moveNext() ? iterator.current : null;
  }
}
