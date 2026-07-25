from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from completion.models import CompletionItemKind, CompletionSourceKind
from provider_backends.claude.comm_runtime.parsing import structured_event
from provider_backends.claude.execution_runtime.polling import (
    _dispatch_deferred_prompt,
    _process_event,
    poll_submission,
)
from provider_backends.claude.execution_runtime.state_machine_runtime import (
    apply_session_rotation,
    build_poll_state,
    finalize_poll_result,
)
from provider_execution.base import ProviderPollResult, ProviderSubmission


NOW = "2026-07-21T08:00:00Z"


def _submission(**runtime_overrides: object) -> ProviderSubmission:
    runtime_state: dict[str, object] = {
        "state": {},
        "mode": "active",
        "pane_id": "%1",
        "request_anchor": "job_current",
        "next_seq": 1,
        "anchor_seen": False,
        "reply_buffer": "",
        "raw_buffer": "",
        "session_path": "/tmp/session-one.jsonl",
        "last_assistant_uuid": "",
        "prompt_text": "CCB_REQ_ID: job_current\n\ncurrent task",
        "prompt_sent": True,
        "no_wrap": False,
    }
    runtime_state.update(runtime_overrides)
    return ProviderSubmission(
        job_id="job_current",
        agent_name="claude1",
        provider="claude",
        accepted_at=NOW,
        ready_at=NOW,
        source_kind=CompletionSourceKind.SESSION_EVENT_LOG,
        reply="",
        runtime_state=runtime_state,
    )


def _process_raw(submission: ProviderSubmission, poll, *entries: dict[str, object]) -> None:
    for entry in entries:
        event = structured_event(entry)
        assert event is not None, entry
        result = _process_event(submission, poll, event, state={}, now=NOW)
        assert result is None


def _enqueue(job_id: str = "job_current", *, uuid: str = "queue-current") -> dict[str, object]:
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "uuid": uuid,
        "content": f"CCB_REQ_ID: {job_id}\n\nqueued task",
    }


def _dequeue(*, uuid: str = "dequeue-1") -> dict[str, object]:
    return {"type": "queue-operation", "operation": "dequeue", "uuid": uuid}


def _queued_command(job_id: str, *, source_uuid: str) -> dict[str, object]:
    return {
        "type": "attachment",
        "uuid": f"attachment-{source_uuid}",
        "attachment": {
            "type": "queued_command",
            "prompt": f"CCB_REQ_ID: {job_id}\n\nqueued task",
            "source_uuid": source_uuid,
        },
    }


def _assistant(
    text: str,
    *,
    uuid: str,
    stop_reason: str = "end_turn",
    agent_id: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "role": "assistant",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
        },
    }
    if agent_id:
        entry["agentId"] = agent_id
    return entry


def _tool_only_assistant(*, uuid: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "role": "assistant",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Read",
                    "input": {"file_path": "README.md"},
                }
            ],
        },
    }


def _turn_duration(parent_uuid: str) -> dict[str, object]:
    return {
        "type": "system",
        "subtype": "turn_duration",
        "parentUuid": parent_uuid,
        "durationMs": 10,
    }


def _user_record(
    job_id: str,
    *,
    tool_result: bool = False,
    agent_id: str | None = None,
    meta: bool = False,
) -> dict[str, object]:
    content: object = f"CCB_REQ_ID: {job_id}\n\ncurrent task"
    entry: dict[str, object] = {
        "type": "user",
        "uuid": f"user-{job_id}",
        "message": {"role": "user", "content": content},
    }
    if tool_result:
        entry["message"] = {
            "role": "user",
            "content": [{"type": "tool_result", "content": content}],
        }
        entry["toolUseResult"] = {"type": "text"}
    if agent_id:
        entry["agentId"] = agent_id
    if meta:
        entry["isMeta"] = True
    return entry


def test_structured_parser_preserves_queue_lifecycle_and_tool_only_uuid() -> None:
    enqueued = structured_event(_enqueue())
    dequeued = structured_event(_dequeue())
    activated = structured_event(_queued_command("job_current", source_uuid="queue-current"))
    tool_only = structured_event(_tool_only_assistant(uuid="assistant-tool"))

    assert enqueued is not None
    assert enqueued["role"] == "prompt_lifecycle"
    assert enqueued["prompt_phase"] == "enqueued"
    assert enqueued["text"].startswith("CCB_REQ_ID: job_current")
    assert dequeued is not None
    assert dequeued["prompt_phase"] == "dequeued"
    assert activated is not None
    assert activated["prompt_phase"] == "activated"
    assert activated["source_uuid"] == "queue-current"
    assert tool_only is not None
    assert tool_only["role"] == "assistant"
    assert tool_only["text"] == ""
    assert tool_only["uuid"] == "assistant-tool"


def test_deferred_pane_dispatch_does_not_synthesize_activation_or_anchor() -> None:
    sent: list[str] = []

    class BusyBackend:
        def get_pane_content(self, pane_id: str, lines: int = 120) -> str:
            return "old turn still busy"

        def send_text(self, pane_id: str, text: str) -> None:
            sent.append(text)

    submission = _submission(
        prompt_sent=False,
        prompt_deferred_for_ready=True,
        ready_wait_started_at="2026-07-21T07:59:00Z",
        ready_timeout_s=0.0,
    )

    dispatched = _dispatch_deferred_prompt(
        submission,
        prepared=SimpleNamespace(backend=BusyBackend(), pane_id="%1"),
        now=NOW,
    )

    assert isinstance(dispatched, ProviderSubmission)
    assert sent == ["CCB_REQ_ID: job_current\n\ncurrent task"]
    assert dispatched.runtime_state["anchor_seen"] is False
    assert dispatched.runtime_state["prompt_activated"] is False
    assert dispatched.runtime_state["next_seq"] == 1
    assert not dispatched.runtime_state.get("prompt_anchor_emitted_at")


def test_old_busy_turn_and_subagent_records_are_fenced_until_exact_activation() -> None:
    submission = _submission()
    poll = build_poll_state(submission)

    _process_raw(
        submission,
        poll,
        _enqueue(),
        _assistant("old main answer", uuid="assistant-old"),
        _assistant("old child answer", uuid="assistant-child", agent_id="worker-old"),
        _turn_duration("assistant-old"),
    )

    assert poll.prompt_enqueued is True
    assert poll.prompt_activated is False
    assert poll.anchor_seen is False
    assert poll.reply_buffer == ""
    assert poll.raw_buffer == ""
    assert poll.last_assistant_uuid == ""
    assert poll.items == []

    _process_raw(
        submission,
        poll,
        _dequeue(),
        _queued_command("job_current", source_uuid="queue-current"),
        _assistant("new answer", uuid="assistant-new"),
    )

    assert poll.queue_dequeue_observed is True
    assert poll.prompt_activated is True
    assert poll.anchor_seen is True
    assert poll.reply_buffer == "new answer"
    assert [item.kind for item in poll.items] == [
        CompletionItemKind.ANCHOR_SEEN,
        CompletionItemKind.ASSISTANT_CHUNK,
        CompletionItemKind.TURN_BOUNDARY,
    ]
    assert poll.items[-1].payload["last_agent_message"] == "new answer"


def test_multiple_queued_prompts_require_the_exact_replayed_prompt() -> None:
    submission = _submission()
    poll = build_poll_state(submission)

    _process_raw(
        submission,
        poll,
        _enqueue(),
        _dequeue(uuid="dequeue-other"),
        _queued_command("job_other", source_uuid="queue-other"),
        _assistant("other queued answer", uuid="assistant-other"),
        _turn_duration("assistant-other"),
    )

    assert poll.anchor_seen is False
    assert poll.prompt_activated is False
    assert poll.reply_buffer == ""
    assert poll.items == []

    _process_raw(
        submission,
        poll,
        _dequeue(uuid="dequeue-current"),
        _queued_command("job_current", source_uuid="queue-current"),
        _assistant("current queued answer", uuid="assistant-current"),
    )

    assert poll.anchor_seen is True
    assert poll.reply_buffer == "current queued answer"
    assert "other queued answer" not in poll.raw_buffer


def test_tool_result_and_subagent_user_records_cannot_activate_prompt() -> None:
    submission = _submission()
    poll = build_poll_state(submission)
    assert structured_event(_user_record("job_current", tool_result=True)) is None

    _process_raw(
        submission,
        poll,
        _user_record("job_current", agent_id="worker-old"),
        _user_record("job_current", meta=True),
        _assistant("old answer", uuid="assistant-old"),
    )

    assert poll.prompt_activated is False
    assert poll.anchor_seen is False
    assert poll.items == []

    _process_raw(submission, poll, _user_record("job_current"))

    assert poll.prompt_activated is True
    assert poll.anchor_seen is True
    assert [item.kind for item in poll.items] == [CompletionItemKind.ANCHOR_SEEN]


def test_tool_only_old_turn_is_ignored_but_activated_tool_uuid_binds_boundary() -> None:
    submission = _submission()
    poll = build_poll_state(submission)

    _process_raw(
        submission,
        poll,
        _enqueue(),
        _tool_only_assistant(uuid="old-tool-only"),
        _turn_duration("old-tool-only"),
        _queued_command("job_current", source_uuid="queue-current"),
        _assistant("working", uuid="new-visible", stop_reason="tool_use"),
        _tool_only_assistant(uuid="new-tool-only"),
        _turn_duration("new-tool-only"),
    )

    assert poll.last_assistant_uuid == "new-tool-only"
    assert poll.reply_buffer == "working"
    assert poll.reached_turn_boundary is True
    assert poll.items[-1].kind is CompletionItemKind.TURN_BOUNDARY
    assert poll.items[-1].payload["assistant_uuid"] == "new-tool-only"


def test_queue_lifecycle_survives_restart_and_resets_on_session_rotation() -> None:
    submission = _submission()
    poll = build_poll_state(submission)
    _process_raw(submission, poll, _enqueue())

    first = finalize_poll_result(submission, poll, state={"offset": 10})
    resumed = build_poll_state(first.submission)
    assert resumed.prompt_enqueued is True
    assert resumed.prompt_activated is False
    assert resumed.anchor_seen is False

    _process_raw(
        first.submission,
        resumed,
        _queued_command("job_current", source_uuid="queue-current"),
    )
    assert resumed.prompt_activated is True
    assert resumed.anchor_seen is True

    apply_session_rotation(
        first.submission,
        resumed,
        new_session_path="/tmp/session-two.jsonl",
        now=NOW,
    )
    assert resumed.prompt_enqueued is False
    assert resumed.queue_dequeue_observed is False
    assert resumed.prompt_activated is False
    assert resumed.anchor_seen is False
    assert resumed.last_assistant_uuid == ""


def test_legacy_deferred_dispatch_anchor_is_not_grandfathered_as_activation() -> None:
    poll = build_poll_state(
        _submission(
            anchor_seen=True,
            prompt_anchor_emitted_at="2026-07-20T08:00:00Z",
        )
    )

    assert poll.prompt_activated is False
    assert poll.anchor_seen is False
    assert poll.last_assistant_uuid == ""


def test_exact_hook_is_not_terminal_before_prompt_activation(monkeypatch) -> None:
    submission = _submission(prompt_enqueued=True, prompt_activated=False)
    prepared = SimpleNamespace(reader=object(), backend=object(), pane_id="%1")
    hook_result = ProviderPollResult(
        submission=replace(submission, reply="old hook answer"),
        decision=SimpleNamespace(terminal=True, reply="old hook answer"),
    )

    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.prepare_active_poll_without_liveness",
        lambda submission, now: prepared,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.poll_exact_hook",
        lambda submission, now: hook_result,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.ensure_active_pane_alive",
        lambda submission, backend, pane_id, now: None,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.read_events",
        lambda reader, state: ([], state),
    )

    result = poll_submission(None, submission, now=NOW)

    assert isinstance(result, ProviderPollResult)
    assert result.decision is None
    assert result.submission.reply == ""
