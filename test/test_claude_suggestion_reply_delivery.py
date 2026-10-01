"""Claude suggestion rendering must not strand a FIFO return delivery."""
from types import SimpleNamespace

import pytest

from provider_execution import draft_guard
from provider_execution.draft_guard import DraftTarget
from provider_backends.claude.execution_runtime.polling import _dispatch_deferred_prompt
from test_input_draft_guard import Backend, CAPTURES, _submission
from test_input_draft_fifo import _guarded_dispatcher
from test_unified_message_fifo import _ask, _active_delivery_job, _turn_end_decision, _empty_turn_end_decision


def capture(case):
    return dict(next(c for c in CAPTURES if c['provider'] == 'claude' and c['case'] == case))


@pytest.mark.parametrize('release', ['ghost', 'manual_clear', 'deadline'])
def test_claude_reply_and_later_ask_resume_in_order(tmp_path, monkeypatch, release):
    ctx, dispatcher, execution, target, now = _guarded_dispatcher(tmp_path, monkeypatch)
    backend = Backend('claude')
    backend.screen = capture('ghost_after_new_turn' if release == 'ghost' else 'accepted_cursor_at_start')
    native = DraftTarget('claude', backend, '%1', 'generation')

    def observe():
        assert not dispatcher._chain_transition_lock._is_owned()
        return native.observe()

    def clear(observation):
        target.clear_count += 1
        backend.screen = capture('accepted_cleared')

    target.observe = observe
    target.clear = clear
    monkeypatch.setattr(draft_guard, 'resolve_job_target',
                        lambda job, context: target if job.agent_name == 'claude' else None)
    producer = dispatcher.submit(_ask('codex', 'claude', 'produce reply',
                                     project_id=ctx.project_id, task_id='producer')).jobs[0]
    dispatcher.tick()
    dispatcher.complete(producer.job_id, _turn_end_decision(reply='BACK'))
    later = dispatcher.submit(_ask('claude', 'gemini', 'later ask',
                                  project_id=ctx.project_id, task_id='later')).jobs[0]
    dispatcher.tick()
    if release != 'ghost':
        assert execution.started == [producer.job_id]
        now[0] = 179.999
        dispatcher.tick()
        assert target.clear_count == 0
        assert _active_delivery_job(dispatcher, 'claude') is None
        if release == 'manual_clear':
            backend.screen = capture('accepted_cleared')
        else:
            now[0] = 180
        dispatcher.tick()
    delivery = _active_delivery_job(dispatcher, 'claude')
    assert delivery is not None and delivery.request.message_type == 'reply_delivery'
    assert target.clear_count == (1 if release == 'deadline' else 0)
    for _ in range(3):
        dispatcher.tick()
    assert execution.started == [producer.job_id, delivery.job_id]
    execution.arm_turn_end(delivery.job_id, _empty_turn_end_decision())
    dispatcher.poll_completions()
    dispatcher.tick()
    assert execution.started == [producer.job_id, delivery.job_id, later.job_id]


@pytest.mark.parametrize('ghost, accepted', [
    ('ghost_after_new_turn', 'accepted_cursor_at_start'),
    ('light_ghost', 'light_accepted_at_start'),
    ('ansi_dark_ghost', 'ansi_dark_accepted_at_start'),
])
def test_claude_final_sender_resumes_same_submission_once(ghost, accepted):
    backend = Backend('claude')
    backend.screen = capture(accepted)
    reader = SimpleNamespace(capture_state=lambda: {'cursor': 'fresh'})
    prepared = SimpleNamespace(backend=backend, pane_id='%1', reader=reader)
    submission = _submission('claude', {
        'backend': backend, 'pane_id': '%1', 'draft_guard_enabled': True,
        'prompt_sent': False, 'pending_prompt': 'BACK', 'prompt_text': 'BACK',
    })
    waiting = _dispatch_deferred_prompt(submission, prepared=prepared, now=submission.ready_at)
    assert not waiting.runtime_state['prompt_sent']
    assert backend.sent == []
    backend.screen = capture(ghost)
    sent = _dispatch_deferred_prompt(waiting, prepared=prepared, now=submission.ready_at)
    assert sent.job_id == submission.job_id
    assert sent.runtime_state['prompt_sent']
    _dispatch_deferred_prompt(sent, prepared=prepared, now=submission.ready_at)
    assert backend.sent == ['BACK']
    assert backend.keys == []
