from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_pane_status.claude_session import (
    claude_activity_status,
    compose_claude_runtime_status,
    read_claude_session_status,
)
from provider_pane_status.claude_pane import parse_claude_pane_status


def _append_jsonl(path: Path, *entries: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def _assistant_entry(*, text: str = "done", stop_reason: str | None = None) -> dict[str, object]:
    message: dict[str, object] = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
    }
    if stop_reason:
        message["stop_reason"] = stop_reason
    return {
        "type": "assistant",
        "subtype": "completion",
        "uuid": "assistant-1",
        "message": message,
    }


def test_claude_session_status_reports_assistant_end_turn_as_free(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    _append_jsonl(
        session,
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        _assistant_entry(stop_reason="end_turn"),
    )

    status = read_claude_session_status(session)

    assert status.state == "free"
    assert status.reason == "claude_session_assistant_end_turn"
    assert status.matched_patterns == ("assistant_end_turn",)


def test_claude_session_status_reports_latest_user_as_working(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    _append_jsonl(session, {"type": "user", "message": {"role": "user", "content": "Summarize"}})

    status = read_claude_session_status(session)

    assert status.state == "working"
    assert status.reason == "claude_session_user_turn"


def test_claude_session_status_treats_local_clear_as_free(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    _append_jsonl(
        session,
        {"type": "user", "message": {"role": "user", "content": "real prompt"}},
        _assistant_entry(stop_reason="end_turn"),
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": (
                    "<command-name>/clear</command-name>\n"
                    "<command-message>clear</command-message> "
                    "<command-args></command-args>"
                ),
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": (
                    "<local-command-caveat>Local command metadata. "
                    "Do not respond.</local-command-caveat>"
                ),
            },
        },
    )

    status = read_claude_session_status(session)

    assert status.state == "free"
    assert status.reason == "claude_session_local_control"
    assert status.matched_patterns == ("local_control",)


def test_claude_session_status_reports_tool_use_as_tool_running(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    _append_jsonl(
        session,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}}],
            },
        },
    )

    status = read_claude_session_status(session)

    assert status.state == "tool_running"
    assert status.reason == "claude_session_tool_use"


def test_claude_session_status_reports_exhausted_api_error(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    _append_jsonl(
        session,
        {
            "type": "system",
            "subtype": "api_error",
            "timestamp": "2026-07-01T00:00:00Z",
            "retryAttempt": 3,
            "maxRetries": 3,
            "cause": {"code": "model_not_found", "path": "/v1/messages"},
        },
    )

    status = read_claude_session_status(session)

    assert status.state == "api_error"
    assert status.reason == "claude_session_api_error"
    assert "error_code=model_not_found" in status.notes


def test_claude_activity_status_maps_hook_events_without_pane_text() -> None:
    tool = claude_activity_status(
        SimpleNamespace(
            state="active",
            reason="provider_PreToolUse",
            event_name="PreToolUse",
            diagnostics={"tool_name": "Bash"},
        )
    )
    waiting = claude_activity_status(
        SimpleNamespace(
            state="pending",
            reason="provider_Notification",
            event_name="Notification",
            diagnostics={},
        )
    )

    assert tool is not None
    assert tool.state == "tool_running"
    assert waiting is not None
    assert waiting.state == "waiting_for_user"


def test_claude_runtime_status_exposes_start_for_running_job_without_signal() -> None:
    session = read_claude_session_status(None)

    status = compose_claude_runtime_status(None, session, job_running=True)

    assert status.state == "start"
    assert status.reason == "prompt_submitted_waiting_for_first_signal"
    assert status.source == "stabilizer"
    assert "raw_session_reason=missing_session_path" in status.notes


def test_claude_runtime_status_treats_no_session_no_job_as_free() -> None:
    session = read_claude_session_status(None)

    status = compose_claude_runtime_status(None, session, job_running=False)

    assert status.state == "free"
    assert status.reason == "no_claude_session_no_active_turn"
    assert status.source == "runtime"


def test_claude_runtime_status_keeps_missing_bound_session_unknown(tmp_path: Path) -> None:
    session = read_claude_session_status(tmp_path / "missing.jsonl")

    status = compose_claude_runtime_status(None, session, job_running=False)

    assert status.state == "unknown"
    assert status.reason == "session_path_missing"
    assert status.source == "session"


def test_claude_runtime_status_uses_pane_active_over_idle_activity() -> None:
    activity = claude_activity_status(
        SimpleNamespace(state="idle", reason="provider_Stop", event_name="Stop", diagnostics={})
    )
    session = read_claude_session_status(None)
    pane = parse_claude_pane_status("● Thinking for 9s, running 1 shell command…\n❯\n")

    status = compose_claude_runtime_status(activity, session, job_running=False, pane_status=pane)

    assert status.state == "tool_running"
    assert status.reason == "claude_pane_tool_running"
    assert status.source == "pane"
    assert status.activity_state == "idle"
    assert status.pane_state == "tool_running"


def test_claude_runtime_status_uses_idle_prompt_over_stale_active_activity() -> None:
    activity = claude_activity_status(
        SimpleNamespace(
            state="active",
            reason="provider_PreToolUse",
            event_name="PreToolUse",
            diagnostics={"tool_name": "Bash"},
        )
    )
    session = read_claude_session_status(None)
    pane = parse_claude_pane_status("Finished previous task\n\n❯\n")

    status = compose_claude_runtime_status(
        activity,
        session,
        job_running=False,
        pane_status=pane,
    )

    assert status.state == "free"
    assert status.reason == "claude_pane_idle_prompt"
    assert status.source == "pane"
    assert status.activity_state == "active"
    assert status.pane_state == "free"


def test_claude_runtime_status_uses_real_footer_idle_prompt_over_notification() -> None:
    activity = claude_activity_status(
        SimpleNamespace(
            state="pending",
            reason="provider_Notification",
            event_name="Notification",
            diagnostics={},
        )
    )
    session = read_claude_session_status(None)
    pane = parse_claude_pane_status(
        "● hello from the previous turn\n"
        "✻ Cogitated for 2s\n"
        "────────────────────────────────────────\n"
        "❯\u00a0\n"
        "────────────────────────────────────────\n"
        "⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    )

    status = compose_claude_runtime_status(
        activity,
        session,
        job_running=False,
        pane_status=pane,
    )

    assert pane.state == "free"
    assert status.state == "free"
    assert status.reason == "claude_pane_idle_prompt"
    assert status.source == "pane"
    assert status.activity_state == "pending"


def test_claude_pane_idle_prompt_supersedes_old_error_and_summary_text() -> None:
    pane = parse_claude_pane_status(
        "API error: old request failed\n"
        "Thought for 9s, ran 1 shell command\n"
        "────────────────────────────────────────\n"
        "❯\n"
        "────────────────────────────────────────\n"
        "⏵⏵ bypass permissions on\n"
    )

    assert pane.state == "free"
    assert pane.reason == "claude_pane_idle_prompt"


def test_claude_activity_status_discards_stale_active_hook() -> None:
    status = claude_activity_status(
        SimpleNamespace(
            state="active",
            reason="provider_PreToolUse",
            event_name="PreToolUse",
            diagnostics={"tool_name": "Bash"},
            updated_at="2026-07-01T00:00:00Z",
        ),
        now="2026-07-01T00:03:01Z",
    )

    assert status is None


def test_claude_runtime_status_treats_terminal_summary_with_prompt_as_free() -> None:
    activity = claude_activity_status(
        SimpleNamespace(
            state="active",
            reason="provider_PreToolUse",
            event_name="PreToolUse",
            diagnostics={"tool_name": "Bash"},
        )
    )
    session = read_claude_session_status(None)
    pane = parse_claude_pane_status("Thought for 9s, ran 1 shell command\n❯\n")

    status = compose_claude_runtime_status(activity, session, job_running=False, pane_status=pane)

    assert status.state == "free"
    assert status.reason == "claude_pane_idle_prompt"
    assert status.source == "pane"
    assert status.pane_state == "free"
    assert status.pane_reason == "claude_pane_idle_prompt"
