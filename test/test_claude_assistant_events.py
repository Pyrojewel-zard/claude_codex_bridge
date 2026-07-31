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


def test_handle_assistant_event_does_not_complete_text_without_stop_reason() -> None:
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
    ]
    assert poll.reply_buffer == "round result: pass\nsummary: ok"
    assert poll.reached_turn_boundary is False


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
    assert poll.reply_buffer == "existing"


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


def test_same_message_thinking_end_turn_waits_for_visible_final_text() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )
    submission = _submission()

    handle_assistant_event(
        submission,
        poll,
        {
            "text": "Let me read...",
            "uuid": "assistant-process-1",
            "message_id": "msg_process_1",
            "stop_reason": "tool_use",
            "entry": {
                "type": "assistant",
                "uuid": "assistant-process-1",
                "message": {
                    "id": "msg_process_1",
                    "role": "assistant",
                    "stop_reason": "tool_use",
                    "content": [
                        {"type": "text", "text": "Let me read..."},
                        {"type": "tool_use", "name": "Read", "input": {}},
                    ],
                },
            },
        },
        now="2026-04-06T00:01:00Z",
    )
    handle_assistant_event(
        submission,
        poll,
        {
            "text": "Let me verify...",
            "uuid": "assistant-process-2",
            "message_id": "msg_process_2",
            "stop_reason": "tool_use",
            "entry": {
                "type": "assistant",
                "uuid": "assistant-process-2",
                "message": {
                    "id": "msg_process_2",
                    "role": "assistant",
                    "stop_reason": "tool_use",
                    "content": [
                        {"type": "text", "text": "Let me verify..."},
                        {"type": "tool_use", "name": "Bash", "input": {}},
                    ],
                },
            },
        },
        now="2026-04-06T00:01:10Z",
    )
    handle_assistant_event(
        submission,
        poll,
        {
            "text": "",
            "uuid": "assistant-thinking",
            "message_id": "msg_final",
            "stop_reason": "end_turn",
            "entry": {
                "type": "assistant",
                "uuid": "assistant-thinking",
                "message": {
                    "id": "msg_final",
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": "private"}],
                },
            },
        },
        now="2026-04-06T00:01:20Z",
    )

    assert poll.reached_turn_boundary is False
    assert poll.reply_buffer == "Let me read...\nLet me verify..."
    assert poll.active_assistant_text == ""
    assert poll.active_assistant_message_id == "msg_final"
    assert poll.active_assistant_stop_reason == "end_turn"

    handle_assistant_event(
        submission,
        poll,
        {
            "text": "Complete final review.",
            "uuid": "assistant-final",
            "message_id": "msg_final",
            "stop_reason": "end_turn",
            "entry": {
                "type": "assistant",
                "uuid": "assistant-final",
                "message": {
                    "id": "msg_final",
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [
                        {"type": "text", "text": "Complete final review."},
                    ],
                },
            },
        },
        now="2026-04-06T00:02:36Z",
    )

    boundaries = [
        item for item in poll.items if item.kind is CompletionItemKind.TURN_BOUNDARY
    ]
    assert len(boundaries) == 1
    assert boundaries[0].payload["last_agent_message"] == "Complete final review."
    assert boundaries[0].payload["assistant_message_id"] == "msg_final"
    assert "Let me" not in boundaries[0].payload["last_agent_message"]
    assert poll.reply_buffer == (
        "Let me read...\nLet me verify...\nComplete final review."
    )
    assert poll.terminal_reply == "Complete final review."
    assert poll.reached_turn_boundary is True


def test_same_message_prior_end_turn_can_complete_later_text_snapshot() -> None:
    poll = ClaudePollState(
        request_anchor="job_1",
        next_seq=1,
        anchor_seen=True,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session.jsonl",
        last_assistant_uuid="",
    )
    submission = _submission()

    handle_assistant_event(
        submission,
        poll,
        {
            "text": "",
            "uuid": "assistant-thinking",
            "message_id": "msg_final",
            "stop_reason": "end_turn",
            "entry": {
                "type": "assistant",
                "message": {
                    "id": "msg_final",
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": "private"}],
                },
            },
        },
        now="2026-04-06T00:01:00Z",
    )
    handle_assistant_event(
        submission,
        poll,
        {
            "text": "OK",
            "uuid": "assistant-final",
            "message_id": "msg_final",
            "stop_reason": None,
            "entry": {
                "type": "assistant",
                "message": {
                    "id": "msg_final",
                    "role": "assistant",
                    "stop_reason": None,
                    "content": [{"type": "text", "text": "OK"}],
                },
            },
        },
        now="2026-04-06T00:02:16Z",
    )

    assert poll.reached_turn_boundary is True
    assert poll.items[-1].payload["last_agent_message"] == "OK"


def test_stalled_mid_stream_assistant_text_emits_error_not_completion() -> None:
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
            "text": "API Error: Response stalled mid-stream",
            "uuid": "assistant-error",
            "message_id": "msg_error",
            "stop_reason": "end_turn",
        },
        now="2026-04-06T00:01:00Z",
    )

    assert [item.kind for item in poll.items] == [
        CompletionItemKind.ASSISTANT_CHUNK,
        CompletionItemKind.ERROR,
    ]
    assert poll.items[-1].payload["reason"] == "claude_response_stalled_mid_stream"
    assert poll.items[-1].payload["response_incomplete"] is True
    assert poll.reached_turn_boundary is True
