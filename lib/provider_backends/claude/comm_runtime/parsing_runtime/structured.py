from __future__ import annotations

from typing import Any

from .entries import extract_message


def structured_event(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    entry_type = str(entry.get("type") or "").strip().lower()
    subtype = _optional_text(entry.get("subtype"))
    uuid = _optional_text(entry.get("uuid"), lowercase=False)
    parent_uuid = _optional_text(entry.get("parentUuid"), lowercase=False)

    user_msg = extract_message(entry, "user")
    if user_msg:
        return _event_record(
            role="user",
            text=user_msg,
            entry_type=entry_type,
            subtype=subtype,
            uuid=uuid,
            parent_uuid=parent_uuid,
            stop_reason=None,
            entry=entry,
        )

    assistant_msg = extract_message(entry, "assistant")
    if assistant_msg:
        return _event_record(
            role="assistant",
            text=assistant_msg,
            entry_type=entry_type,
            subtype=subtype,
            uuid=uuid,
            parent_uuid=parent_uuid,
            stop_reason=_assistant_stop_reason(entry),
            entry=entry,
        )

    # Emit a zero-text assistant event for assistant entries whose content is
    # pure tool_use / thinking blocks (no visible text). The completion
    # detector ignores these for reply extraction, but the state machine needs
    # them for `last_assistant_uuid` bookkeeping so that a subsequent
    # system/turn_duration event can match its parent_uuid. This case arises
    # when the assistant dispatches multiple async CCB asks (pure tool_use
    # turns) before emitting its final end_turn text summary. Without this
    # bookkeeping, a prompt delivered via `queue-operation` (busy REPL) can
    # still miss the turn boundary because the pre-anchor uuid tracker never
    # sees intermediate assistant tool_use events (structured_event previously
    # returned None for them since extract_message yields no text).
    if _is_assistant_tool_use_entry(entry):
        return _event_record(
            role="assistant",
            text="",
            entry_type=entry_type,
            subtype=subtype,
            uuid=uuid,
            parent_uuid=parent_uuid,
            stop_reason=_assistant_stop_reason(entry),
            entry=entry,
        )

    if entry_type == "system":
        return _event_record(
            role="system",
            text="",
            entry_type=entry_type,
            subtype=subtype,
            uuid=uuid,
            parent_uuid=parent_uuid,
            stop_reason=None,
            entry=entry,
        )

    # Claude Code CLI queues incoming input when the REPL is busy (cooking / in a
    # tool_use turn). In that case the prompt is recorded as a
    # `queue-operation`/`enqueue` entry (with the full prompt in `content`) plus
    # a later `attachment`/`queued_command` marker. It does NOT synthesize a
    # `type:"user"` message entry. If we drop the record the completion
    # detector never sees the anchor marker (`CCB_REQ_ID:`) and the attempt
    # deadlocks: anchor_seen stays False, assistant events are gated out,
    # last_assistant_uuid is never updated, and the `turn_duration` system
    # event can never match. Emit a synthetic user event so the rest of the
    # pipeline (handle_user_event / anchor detection) works identically to the
    # idle-REPL path. See docs/claude-queue-operation-completion-deadlock-diagnosis.md.
    if entry_type == "queue-operation":
        op = _optional_text(entry.get("operation"))
        if op == "enqueue":
            text = str(entry.get("content") or "").strip()
            if text:
                return _event_record(
                    role="user",
                    text=text,
                    entry_type=entry_type,
                    subtype=subtype,
                    uuid=uuid,
                    parent_uuid=parent_uuid,
                    stop_reason=None,
                    entry=entry,
                )

    return None


def _assistant_stop_reason(entry: dict[str, Any]) -> str | None:
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    return _optional_text(message.get("stop_reason"), lowercase=False)


def _is_assistant_tool_use_entry(entry: dict[str, Any]) -> bool:
    if str(entry.get("type") or "").strip().lower() != "assistant":
        return False
    message = entry.get("message")
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return False
    for item in content:
        if not isinstance(item, dict):
            return False
        ctype = str(item.get("type") or "").strip().lower()
        if ctype in {"text", "tool_result"}:
            # Has real visible text → extract_message would have caught it.
            return False
        if ctype in {"tool_use", "thinking", "thinking_delta"}:
            continue
        return False
    return True


def _event_record(
    *,
    role: str,
    text: str,
    entry_type: str,
    subtype: str | None,
    uuid: str | None,
    parent_uuid: str | None,
    stop_reason: str | None,
    entry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": role,
        "text": text,
        "entry_type": entry_type,
        "subtype": subtype,
        "uuid": uuid,
        "parent_uuid": parent_uuid,
        "stop_reason": stop_reason,
        "entry": entry,
    }


def _optional_text(value: object, *, lowercase: bool = True) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.lower() if lowercase else text


__all__ = ["structured_event"]
