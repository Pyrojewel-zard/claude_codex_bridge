from __future__ import annotations

from provider_backends.claude.comm_runtime.parsing import (
    extract_content_text,
    extract_message,
    structured_event,
)


def test_extract_content_text_ignores_thinking_fragments() -> None:
    content = [
        {"type": "thinking", "text": "internal"},
        {"type": "text", "content": "hello"},
        {"type": "text", "text": "world"},
    ]

    assert extract_content_text(content) == "hello\nworld"


def test_extract_message_supports_response_item_and_event_msg() -> None:
    response_item = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "from-response"}],
        },
    }
    event_msg = {
        "type": "event_msg",
        "payload": {
            "type": "assistant_message",
            "role": "assistant",
            "text": "from-event",
        },
    }

    assert extract_message(response_item, "assistant") == "from-response"
    assert extract_message(event_msg, "assistant") == "from-event"


def test_structured_event_captures_assistant_stop_reason() -> None:
    entry = {
        "type": "assistant",
        "subtype": "completion",
        "uuid": "u-1",
        "parentUuid": "p-1",
        "message": {
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "done"}],
        },
    }

    assert structured_event(entry) == {
        "role": "assistant",
        "text": "done",
        "entry_type": "assistant",
        "subtype": "completion",
        "uuid": "u-1",
        "parent_uuid": "p-1",
        "stop_reason": "end_turn",
        "entry": entry,
    }


def test_structured_event_does_not_treat_named_session_slug_as_subagent() -> None:
    entry = {
        "type": "user",
        "slug": "bright-running-otter",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "CCB_REQ_ID: job_1\n\nrun the task",
        },
    }

    event = structured_event(entry)

    assert event is not None
    assert "subagent_name" not in event
    assert "is_sidechain" not in event


def test_structured_event_preserves_real_sidechain_identity() -> None:
    entry = {
        "type": "assistant",
        "slug": "bright-running-otter",
        "isSidechain": True,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "child result"}],
        },
    }

    event = structured_event(entry)

    assert event is not None
    assert "subagent_name" not in event
    assert event["is_sidechain"] is True


def test_structured_event_preserves_claude_message_id_for_snapshot_aggregation() -> None:
    entry = {
        "type": "assistant",
        "uuid": "transcript-entry-1",
        "message": {
            "id": "msg_01rrDqvNMrzRR5vt4O8NZvIk",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "private"}],
        },
    }

    event = structured_event(entry)

    assert event is not None
    assert event["role"] == "assistant"
    assert event["text"] == ""
    assert event["message_id"] == "msg_01rrDqvNMrzRR5vt4O8NZvIk"
    assert event["stop_reason"] == "end_turn"
