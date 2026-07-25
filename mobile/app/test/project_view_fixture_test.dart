import 'package:ccb_mobile/ccb_mobile.dart';
import 'package:test/test.dart';

void main() {
  test('fixture maps project view into CCB models', () {
    final view = CcbProjectView.fromProjectViewPayload(demoProjectViewFixture);

    expect(view.project.id, 'proj-demo');
    expect(view.namespaceEpoch, 4);
    expect(view.tmuxSocketPath, '/tmp/ccb-demo/tmux.sock');
    expect(view.tmuxSessionName, 'ccb-demo');
    expect(view.windows.single.agents, containsAll(['lead', 'mobile']));
    expect(view.agentByName('mobile')?.active, isTrue);
    expect(
      view.contentForAgent('mobile').single.title,
      'Emulator landing status',
    );
    expect(view.contentForAgent('lead').single.id, 'content-lead-plan');
    final history = view.terminalHistoryForAgent('mobile');
    expect(history?.historyScope, 'tmux_scrollback');
    expect(history?.sourcePaneId, '%2');
    expect(
      history?.blocks.map((item) => item.id),
      contains('mobile-checkpoint-09'),
    );
    expect(
      view.notifications.map((item) => item.kind),
      containsAll([
        CcbNotificationKind.taskCompleted,
        CcbNotificationKind.callbackWaiting,
        CcbNotificationKind.commsMention,
      ]),
    );
    expect(
      view.notifications
          .singleWhere((item) => item.kind == CcbNotificationKind.taskCompleted)
          .target
          .contentId,
      'content-lead-plan',
    );
    expect(
      view.notifications
          .singleWhere((item) => item.kind == CcbNotificationKind.commsMention)
          .target
          .commsId,
      'comms-mobile-callback',
    );

    final target = view.terminalTargetForAgent('mobile');
    expect(target.projectId, 'proj-demo');
    expect(target.namespaceEpoch, 4);
    expect(target.agent, 'mobile');
    expect(target.window, 'main');
    expect(target.paneId, '%2');
    expect(target.hasDirectTmuxAttachEvidence, isTrue);
    expect(target.canAcceptTerminalInput, isTrue);

    final windowTarget = view.terminalTargetForWindow('main');
    expect(windowTarget.kind, CcbTerminalTargetKind.windowActivePane);
    expect(windowTarget.projectId, 'proj-demo');
    expect(windowTarget.namespaceEpoch, 4);
    expect(windowTarget.agent, isNull);
    expect(windowTarget.window, 'main');
    expect(windowTarget.paneId, '%2');
    expect(windowTarget.hasDirectTmuxAttachEvidence, isTrue);
    expect(windowTarget.canAcceptTerminalInput, isTrue);
  });

  test('fake repository rejects stale namespace epoch', () async {
    final repo = FakeMobileCcbRepository.demo();

    await expectLater(
      repo.focusAgent(
        projectId: 'proj-demo',
        agent: 'mobile',
        namespaceEpoch: 3,
      ),
      throwsStateError,
    );
  });

  test('project view synthesizes failed, blocked, and unhealthy attention', () {
    final view = CcbProjectView.fromProjectViewPayload({
      'view': {
        'project': {
          'id': 'proj-alerts',
          'root': '/tmp/proj-alerts',
          'display_name': 'alerts',
        },
        'namespace': {'epoch': 2},
        'windows': [
          {
            'name': 'main',
            'label': 'main',
            'kind': 'agents',
            'order': 0,
            'active': true,
            'agents': ['failed', 'blocked', 'missing'],
          },
        ],
        'agents': [
          {
            'name': 'failed',
            'provider': 'codex',
            'window': 'main',
            'state': 'failed',
          },
          {
            'name': 'blocked',
            'provider': 'codex',
            'window': 'main',
            'state': 'blocked',
          },
          {
            'name': 'missing',
            'provider': 'codex',
            'window': 'main',
            'runtime_health': 'missing',
          },
        ],
        'comms': {
          'items': [
            {
              'id': 'callback-thread',
              'kind': 'callback',
              'agent': 'blocked',
              'title': 'Callback thread',
              'text': 'waiting for user',
            },
          ],
        },
      },
    });

    expect(
      view.notifications.map((item) => item.kind),
      containsAll([
        CcbNotificationKind.taskFailed,
        CcbNotificationKind.taskBlocked,
        CcbNotificationKind.agentUnhealthy,
        CcbNotificationKind.commsMention,
      ]),
    );
    expect(
      view.notifications
          .singleWhere((item) => item.kind == CcbNotificationKind.taskFailed)
          .severity,
      CcbNotificationSeverity.critical,
    );
  });

  test('project view maps source activity fields onto agents', () {
    final view = CcbProjectView.fromProjectViewPayload({
      'view': {
        'project': {
          'id': 'proj-activity',
          'root': '/tmp/proj-activity',
          'display_name': 'activity',
        },
        'namespace': {'epoch': 2},
        'agents': [
          {
            'name': 'lead',
            'provider': 'codex',
            'window': 'main',
            'activity_state': 'pending',
            'activity_symbol': '↻',
            'activity_color': 'yellow',
            'activity_source': 'codex_runtime',
            'activity_reason': 'codex_runtime_reconnecting',
            'last_progress_at': '2026-06-29T10:00:00Z',
          },
        ],
      },
    });

    final agent = view.agentByName('lead')!;
    expect(agent.activityState, 'pending');
    expect(agent.activitySymbol, '↻');
    expect(agent.activityColor, 'yellow');
    expect(agent.activitySource, 'codex_runtime');
    expect(agent.activityReason, 'codex_runtime_reconnecting');
    expect(agent.lastProgressAt, '2026-06-29T10:00:00Z');
  });

  test(
    'project view prefers additive execution phase with legacy fallback',
    () {
      final view = CcbProjectView.fromProjectViewPayload({
        'view': {
          'project': {
            'id': 'proj-phase',
            'root': '/tmp/proj-phase',
            'display_name': 'phase',
          },
          'namespace': {'epoch': 2},
          'comms': [
            {
              'id': 'job-new',
              'status': 'running',
              'business_status': 'replying',
              'status_label': 'work',
              'execution_phase': 'provider_idle_pending_terminal',
              'execution_phase_reason': 'provider_idle_terminal_pending',
            },
            {
              'id': 'job-old',
              'status': 'running',
              'business_status': 'replying',
              'status_label': 'work',
            },
          ],
        },
      });

      expect(view.comms[0].displayPhase, 'provider_idle_pending_terminal');
      expect(
        view.comms[0].executionPhaseReason,
        'provider_idle_terminal_pending',
      );
      expect(view.comms[1].displayPhase, 'work');
      expect(view.comms[1].executionPhase, isNull);
    },
  );
}
