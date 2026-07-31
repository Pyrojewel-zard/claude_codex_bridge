import 'package:ccb_mobile/features/agent_chat/agent_turn_sync_tracker.dart';
import 'package:ccb_mobile/models/ccb_agent.dart';
import 'package:ccb_mobile/models/ccb_agent_conversation.dart';
import 'package:ccb_mobile/models/ccb_conversation_item.dart';
import 'package:ccb_mobile/models/ccb_project.dart';
import 'package:ccb_mobile/models/ccb_project_view.dart';
import 'package:test/test.dart';

void main() {
  test('stale idle snapshot cannot clear a newly submitted turn', () {
    final tracker = AgentTurnSyncTracker();
    final baselineAgent = _agent(state: 'idle', lastProgressAt: 't0');
    final baselineView = _view(
      agent: baselineAgent,
      generatedAt: DateTime.utc(2026, 7, 28, 1),
      sequence: 10,
    );
    tracker.markSubmitted(
      agentName: baselineAgent.name,
      conversation: _conversation(),
    );

    final decision = tracker.observe(
      agentName: baselineAgent.name,
      sourceState: 'idle',
      conversation: _conversation(),
      view: baselineView,
      agent: baselineAgent,
      conversationReconciled: true,
    );

    expect(decision.result, AgentTurnSyncResult.pending);
    expect(tracker.isAwaiting(baselineAgent.name), isTrue);
  });

  test('newer idle evidence cannot clear an unobserved or unconsumed turn', () {
    var now = DateTime.utc(2026, 7, 28, 1);
    final tracker = AgentTurnSyncTracker();
    final agent = _agent(state: 'idle', lastProgressAt: 't0');
    tracker.markSubmitted(agentName: agent.name, conversation: _conversation());

    now = now.add(const Duration(seconds: 1));
    final early = tracker.observe(
      agentName: agent.name,
      sourceState: 'idle',
      conversation: _conversation(),
      view: _view(agent: agent, generatedAt: now, sequence: 11),
      agent: agent,
      conversationReconciled: true,
    );
    expect(early.result, AgentTurnSyncResult.pending);

    now = now.add(agentTurnInitialReconciliationDelay);
    final stillPending = tracker.observe(
      agentName: agent.name,
      sourceState: 'idle',
      conversation: _conversation(),
      view: _view(agent: agent, generatedAt: now, sequence: 12),
      agent: agent,
      conversationReconciled: true,
    );

    expect(stillPending.result, AgentTurnSyncResult.pending);
    expect(stillPending.observedSourceWorking, isFalse);
    expect(tracker.isAwaiting(agent.name), isTrue);
  });

  test('working then idle settles only after conversation reconciliation', () {
    final tracker = AgentTurnSyncTracker();
    final idle = _agent(state: 'idle', lastProgressAt: 't0');
    tracker.markSubmitted(agentName: idle.name, conversation: _conversation());
    final working = _agent(state: 'active', lastProgressAt: 't1');
    tracker.observe(
      agentName: idle.name,
      sourceState: 'working',
      conversation: _conversation(),
      view: _view(
        agent: working,
        generatedAt: DateTime.utc(2026, 7, 28, 1, 0, 1),
        sequence: 11,
      ),
      agent: working,
      conversationReconciled: false,
    );
    final settledView = _view(
      agent: _agent(state: 'idle', lastProgressAt: 't2'),
      generatedAt: DateTime.utc(2026, 7, 28, 1, 0, 2),
      sequence: 12,
    );

    final beforeConversation = tracker.observe(
      agentName: idle.name,
      sourceState: 'idle',
      conversation: _conversation(),
      view: settledView,
      agent: settledView.agents.single,
      conversationReconciled: false,
    );
    final afterConversation = tracker.observe(
      agentName: idle.name,
      sourceState: 'idle',
      conversation: _conversation(),
      view: settledView,
      agent: settledView.agents.single,
      conversationReconciled: true,
    );

    expect(beforeConversation.result, AgentTurnSyncResult.pending);
    expect(afterConversation.result, AgentTurnSyncResult.completed);
    expect(afterConversation.observedSourceWorking, isTrue);
    expect(tracker.isAwaiting(idle.name), isFalse);
  });

  test(
    'fresh idle metadata alone cannot settle a turn whose active pulse was missed',
    () {
      final tracker = AgentTurnSyncTracker();
      final baselineAgent = _agent(state: 'idle', lastProgressAt: 't0');
      tracker.markSubmitted(
        agentName: baselineAgent.name,
        conversation: _conversation(),
      );
      final completedAgent = _agent(
        state: 'idle',
        source: 'claude_runtime',
        reason: 'claude_activity_idle',
        lastProgressAt: 't1',
      );

      final decision = tracker.observe(
        agentName: baselineAgent.name,
        sourceState: 'idle',
        conversation: _conversation(),
        view: _view(
          agent: completedAgent,
          generatedAt: DateTime.utc(2026, 7, 28, 1, 0, 1),
          sequence: 11,
        ),
        agent: completedAgent,
        conversationReconciled: true,
      );

      expect(decision.result, AgentTurnSyncResult.pending);
      expect(decision.observedSourceWorking, isFalse);
      expect(tracker.isAwaiting(baselineAgent.name), isTrue);
    },
  );

  test('new running reply does not settle against unchanged idle evidence', () {
    final tracker = AgentTurnSyncTracker();
    final agent = _agent(state: 'idle', lastProgressAt: 't0');
    final view = _view(
      agent: agent,
      generatedAt: DateTime.utc(2026, 7, 28, 1),
      sequence: 10,
    );
    tracker.markSubmitted(agentName: agent.name, conversation: _conversation());

    final decision = tracker.observe(
      agentName: agent.name,
      sourceState: 'idle',
      conversation: _conversation(
        items: [_reply(id: 'reply-1', body: 'partial', completed: false)],
      ),
      view: view,
      agent: agent,
      conversationReconciled: true,
    );

    expect(decision.result, AgentTurnSyncResult.pending);
    expect(decision.observedSourceWorking, isTrue);
    expect(tracker.hasObservedSourceWorking(agent.name), isTrue);
    expect(tracker.isAwaiting(agent.name), isTrue);
  });

  test('completed reply settles even when source working pulse was missed', () {
    final tracker = AgentTurnSyncTracker();
    final agent = _agent(state: 'idle', lastProgressAt: 't0');
    final view = _view(
      agent: agent,
      generatedAt: DateTime.utc(2026, 7, 28, 1),
      sequence: 10,
    );
    tracker.markSubmitted(agentName: agent.name, conversation: _conversation());

    final decision = tracker.observe(
      agentName: agent.name,
      sourceState: 'idle',
      conversation: _conversation(
        items: [_reply(id: 'reply-1', body: 'done', completed: true)],
      ),
      view: view,
      agent: agent,
      conversationReconciled: true,
    );

    expect(decision.result, AgentTurnSyncResult.settledIdle);
    expect(tracker.isAwaiting(agent.name), isFalse);
  });
}

CcbAgent _agent({
  required String state,
  String source = 'provider_pane',
  String reason = 'claude_pane_idle_prompt',
  required String lastProgressAt,
}) {
  return CcbAgent(
    name: 'claude-agent',
    provider: 'claude',
    window: 'main',
    order: 0,
    active: true,
    queueDepth: 0,
    activityState: state,
    activitySource: source,
    activityReason: reason,
    lastProgressAt: lastProgressAt,
  );
}

CcbProjectView _view({
  required CcbAgent agent,
  required DateTime generatedAt,
  required int sequence,
}) {
  return CcbProjectView(
    project: const CcbProject(
      id: 'proj',
      displayName: 'Project',
      root: '/tmp/project',
    ),
    namespaceEpoch: 7,
    tmuxSocketPath: null,
    tmuxSessionName: null,
    activeWindow: 'main',
    activePaneId: null,
    windows: const [],
    agents: [agent],
    contentItems: const [],
    notifications: const [],
    terminalHistories: const {},
    generatedAt: generatedAt,
    sequence: sequence,
    ttlMs: 1000,
  );
}

CcbAgentConversation _conversation({
  List<CcbConversationItem> items = const [],
}) {
  return CcbAgentConversation(
    projectId: 'proj',
    agentName: 'claude-agent',
    namespaceEpoch: 7,
    items: items,
  );
}

CcbConversationItem _reply({
  required String id,
  required String body,
  required bool completed,
}) {
  return CcbConversationItem(
    id: id,
    agentName: 'claude-agent',
    kind: CcbConversationItemKind.agentReply,
    title: 'Agent',
    body: body,
    source: 'provider_native/claude',
    startedAt: DateTime.utc(2026, 7, 28, 1, 0, 1),
    completedAt: completed ? DateTime.utc(2026, 7, 28, 1, 0, 2) : null,
  );
}
