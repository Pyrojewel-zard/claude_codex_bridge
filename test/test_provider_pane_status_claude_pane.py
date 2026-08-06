from __future__ import annotations

from provider_pane_status.claude_pane import parse_claude_pane_status


def test_claude_pane_reports_running_shell_as_tool_running() -> None:
    status = parse_claude_pane_status(
        """
  CCB reply guidance:

● Thinking for 9s, running 1 shell command…

✢ Billowing… (10s · ↓ 89 tokens · thought for 8s)

────────────────────────────────────────────────────────────────────
❯
"""
    )

    assert status.state == "tool_running"
    assert status.reason == "claude_pane_tool_running"


def test_claude_pane_reports_spinner_as_working() -> None:
    status = parse_claude_pane_status("✢ Billowing… (10s · ↓ 89 tokens · thought for 8s)\n")

    assert status.state == "working"
    assert status.reason == "claude_pane_spinner_active"


def test_claude_pane_reports_every_spinner_animation_frame_as_working() -> None:
    for glyph in ("·", "*", "✻", "✢", "✶", "✽"):
        status = parse_claude_pane_status(
            f"{glyph} Infusing… (13s · ↓ 105 tokens)\n"
            "────────────────────────────────────────────────────────\n"
            "❯\n"
        )

        assert status.state == "working", glyph
        assert status.reason == "claude_pane_spinner_active", glyph


def test_claude_pane_current_prompt_overrides_past_terminal_summary() -> None:
    status = parse_claude_pane_status(
        """
  Thought for 9s, ran 1 shell command

────────────────────────────────────────────────────────────────────
❯
"""
    )

    assert status.state == "free"
    assert status.reason == "claude_pane_idle_prompt"


def test_claude_pane_reports_terminal_summary_without_current_prompt() -> None:
    status = parse_claude_pane_status(
        """
  Thought for 9s, ran 1 shell command
"""
    )

    assert status.state == "terminal_summary"
    assert status.reason == "claude_pane_terminal_summary"
    assert "not_completion_authority" in status.notes


def test_claude_pane_does_not_treat_prompt_as_idle_or_free() -> None:
    status = parse_claude_pane_status(
        """
────────────────────────────────────────────────────────────────────
❯
────────────────────────────────────────────────────────────────────
  esc to interrupt
"""
    )

    assert status.state == "unknown"
    assert status.reason == "no_known_status_pattern"


def test_claude_pane_reports_scheduled_task_as_tool_running() -> None:
    status = parse_claude_pane_status("Running scheduled task · 1 shell still running\n")

    assert status.state == "tool_running"
    assert status.reason == "claude_pane_scheduled_task_running"


def test_claude_pane_ignores_nonfatal_auto_update_failure_footer() -> None:
    status = parse_claude_pane_status(
        "round result: pass\n"
        "╭──────────╮\n"
        "│ >        │\n"
        "╰──────────╯\n"
        "? for shortcuts  Bypassing Permissions\n"
        "✗ Auto-update failed · Try claude doctor\n"
    )

    assert status.state == "unknown"
    assert status.reason == "no_known_status_pattern"


def test_claude_pane_still_reports_real_failure_with_auto_update_footer() -> None:
    status = parse_claude_pane_status(
        "Provider request failed\n"
        "✗ Auto-update failed · Try claude doctor\n"
    )

    assert status.state == "api_error"
    assert status.reason == "provider_api_error"
