from __future__ import annotations

from completion.models import CompletionItemKind, CompletionSourceKind
from provider_backends.claude.execution_runtime.state_machine_runtime import (
    ClaudePollState,
    handle_assistant_event,
)
from provider_execution.base import ProviderSubmission


def _submission() -> ProviderSubmission:
    return ProviderSubmission(
        job_id="job_1",
        agent_name="agent1",
        provider="claude",
        accepted_at="2026-04-06T00:00:00Z",
        ready_at="2026-04-06T00:00:00Z",
        source_kind=CompletionSourceKind.SESSION_EVENT_LOG,
        reply="",
    )


def test_handle_assistant_event_appends_chunk_and_turn_boundary() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "hello world\nCCB_DONE: job_1",
            "uuid": "assistant-1",
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [
        CompletionItemKind.ASSISTANT_CHUNK,
        CompletionItemKind.TURN_BOUNDARY,
    ]
    assert poll.reply_buffer == "hello world"
    assert poll.last_assistant_uuid == "assistant-1"
    assert poll.reached_turn_boundary is True
    assert poll.items[0].payload["assistant_uuid"] == "assistant-1"
    assert poll.items[1].payload["reason"] == "task_complete"
    assert poll.items[1].payload["last_agent_message"] == "hello world"


def test_handle_assistant_event_appends_boundary_on_main_end_turn_without_done_marker() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "final answer",
            "uuid": "assistant-1",
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [
        CompletionItemKind.ASSISTANT_CHUNK,
        CompletionItemKind.TURN_BOUNDARY,
    ]
    assert poll.items[1].payload["reason"] == "assistant_end_turn"
    assert poll.items[1].payload["last_agent_message"] == "final answer"
    assert poll.items[1].payload["assistant_uuid"] == "assistant-1"
    assert poll.items[1].payload["stop_reason"] == "end_turn"
    assert poll.reached_turn_boundary is True


def test_handle_assistant_event_appends_boundary_for_real_text_message_without_stop_reason() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "round result: pass\nsummary: ok",
            "uuid": "assistant-1",
            "stop_reason": None,
            "entry": {
                "type": "assistant",
                "uuid": "assistant-1",
                "message": {
                    "role": "assistant",
                    "stop_reason": None,
                    "content": [
                        {
                            "type": "text",
                            "text": "round result: pass\nsummary: ok",
                        }
                    ],
                },
            },
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [
        CompletionItemKind.ASSISTANT_CHUNK,
        CompletionItemKind.TURN_BOUNDARY,
    ]
    assert poll.items[1].payload["reason"] == "assistant_text_message"
    assert poll.items[1].payload["last_agent_message"] == "round result: pass\nsummary: ok"
    assert poll.items[1].payload["assistant_uuid"] == "assistant-1"
    assert "stop_reason" not in poll.items[1].payload
    assert poll.reached_turn_boundary is True


def test_handle_assistant_event_keeps_primary_uuid_for_subagent_chunks() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=3,
        anchor_seen=True,
        reply_buffer="existing",
        raw_buffer="existing",
        session_path="",
        last_assistant_uuid="primary-uuid",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "subagent update",
            "uuid": "subagent-uuid",
            "subagent_id": "worker-1",
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert poll.last_assistant_uuid == "primary-uuid"
    assert [item.kind for item in poll.items] == [CompletionItemKind.ASSISTANT_CHUNK]
    assert poll.items[0].payload["assistant_uuid"] == "subagent-uuid"
    assert poll.items[0].payload["subagent_id"] == "worker-1"


def test_handle_assistant_event_does_not_complete_real_sidechain() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="primary-uuid",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "child final answer",
            "uuid": "sidechain-uuid",
            "is_sidechain": True,
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert poll.last_assistant_uuid == "primary-uuid"
    assert [item.kind for item in poll.items] == [CompletionItemKind.ASSISTANT_CHUNK]
    assert poll.reached_turn_boundary is False


def test_handle_assistant_event_does_not_complete_tool_use_stop_reason() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "I need to inspect a file.",
            "uuid": "assistant-1",
            "stop_reason": "tool_use",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [CompletionItemKind.ASSISTANT_CHUNK]
    assert poll.reached_turn_boundary is False


def test_handle_assistant_event_does_not_complete_text_message_with_tool_use_without_stop_reason() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "I need to inspect a file.",
            "uuid": "assistant-1",
            "stop_reason": None,
            "entry": {
                "type": "assistant",
                "uuid": "assistant-1",
                "message": {
                    "role": "assistant",
                    "stop_reason": None,
                    "content": [
                        {"type": "text", "text": "I need to inspect a file."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Read",
                            "input": {"file_path": "README.md"},
                        },
                    ],
                },
            },
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [CompletionItemKind.ASSISTANT_CHUNK]
    assert poll.reached_turn_boundary is False


def test_handle_assistant_event_does_not_complete_empty_end_turn() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )

    handle_assistant_event(
        _submission(),
        poll,
        {
            "text": "   ",
            "uuid": "assistant-1",
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert poll.items == []
    assert poll.reached_turn_boundary is False
