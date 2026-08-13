from __future__ import annotations

from types import SimpleNamespace

from completion.models import CompletionSourceKind
from provider_backends.claude.execution_runtime.polling import (
    _maybe_resend_activation_enter,
    poll_submission,
)
from provider_execution.base import ProviderPollResult, ProviderSubmission

NOW = "2026-07-21T08:00:00Z"
SENT_AT = "2026-07-21T07:59:53Z"  # 7s before NOW → inside default grace window [6, 12)


def _submission(**runtime_overrides: object) -> ProviderSubmission:
    runtime_state: dict[str, object] = {
        "state": {},
        "mode": "active",
        "pane_id": "%1",
        "request_anchor": "job_current",
        "next_seq": 1,
        "anchor_seen": False,
        "prompt_activated": False,
        "reply_buffer": "",
        "raw_buffer": "",
        "session_path": "/tmp/session-one.jsonl",
        "last_assistant_uuid": "",
        "prompt_text": "CCB_REQ_ID: job_current\n\n当前任务：请处理以下事项。",
        "prompt_sent": True,
        "prompt_sent_at": SENT_AT,
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


LONG_UNICODE_PROMPT = "CCB_REQ_ID: job_current\n\n" + ("很长的中文提示词" * 400) + "\n请逐条确认。"


class _RetryBackend:
    """Fake pane backend recording every send_key; get_pane_content is injectable."""

    def __init__(self, pane_text: str) -> None:
        self.pane_text = pane_text
        self.keys: list[tuple[str, str]] = []

    def get_pane_content(self, pane_id: str, lines: int = 120) -> str:
        assert pane_id == "%1"
        return self.pane_text

    def send_key(self, pane_id: str, key: str) -> bool:
        assert pane_id == "%1"
        self.keys.append((pane_id, key))
        return True


class _FailingReadBackend:
    def get_pane_content(self, pane_id: str, lines: int = 120) -> str:
        raise RuntimeError("capture failed")

    def send_key(self, pane_id: str, key: str) -> bool:
        raise AssertionError("send_key must not be called")


class _NoSendKeyBackend:
    def get_pane_content(self, pane_id: str, lines: int = 120) -> str:
        return "CCB_REQ_ID: job_current\n❯\n"


def _prepared(backend: object) -> SimpleNamespace:
    return SimpleNamespace(backend=backend, pane_id="%1")


def _poll(*, anchor_seen: bool = False, prompt_activated: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        request_anchor="job_current",
        anchor_seen=anchor_seen,
        prompt_activated=prompt_activated,
        reached_turn_boundary=False,
        next_seq=1,
        reply_buffer="",
        raw_buffer="",
        session_path="/tmp/session-one.jsonl",
        last_assistant_uuid="",
        items=[],
    )


# ---------------------------------------------------------------------------
# 直接单元测试：_maybe_resend_activation_enter
# ---------------------------------------------------------------------------


def test_long_unicode_stuck_prompt_resends_enter_exactly_once() -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend(f"{LONG_UNICODE_PROMPT}\n❯\n")

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]
    assert updated.runtime_state["activation_enter_count"] == 1
    assert updated.runtime_state["activation_enter_at"] == NOW


def test_no_resend_when_anchor_already_seen() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\ncompleted\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(anchor_seen=True),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_when_prompt_activated() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(prompt_activated=True),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_when_idle_composer_has_no_current_job_marker() -> None:
    submission = _submission()
    backend = _RetryBackend("❯\n  ? for shortcuts\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_when_composer_holds_different_job_text() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_other\n别的任务的提示词\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_when_pane_busy() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\nworking…\nesc to interrupt")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_before_grace_window() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")
    early_now = "2026-07-21T07:59:56Z"  # +3s < grace start 6s

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=early_now,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_after_grace_window_passed() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")
    late_now = "2026-07-21T08:00:15Z"  # +15s >= grace end 12s

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=late_now,
    )

    assert result is None
    assert backend.keys == []


def test_env_grace_override_shrinks_window(monkeypatch) -> None:
    monkeypatch.setenv("CCB_CLAUDE_ACTIVATION_GRACE_S", "2")
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")
    # +3s → inside [2,4) with grace=2
    now_3s = "2026-07-21T07:59:56Z"

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=now_3s,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]


def test_no_resend_after_prior_retry() -> None:
    submission = _submission(activation_enter_count=1, activation_enter_at=NOW)
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_repeated_polling_never_exceeds_one_send() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    first = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )
    assert first is not None
    assert backend.keys == [("%1", "Enter")]

    second = _maybe_resend_activation_enter(
        first,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )
    assert second is None
    assert backend.keys == [("%1", "Enter")]


def test_no_resend_when_prompt_not_sent() -> None:
    submission = _submission(prompt_sent=False)
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_no_resend_when_pane_read_fails() -> None:
    submission = _submission()

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(_FailingReadBackend()),
        poll=_poll(),
        now=NOW,
    )

    assert result is None


def test_no_resend_when_backend_lacks_send_key() -> None:
    submission = _submission()

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(_NoSendKeyBackend()),
        poll=_poll(),
        now=NOW,
    )

    assert result is None


def test_no_wrap_raw_prompt_resends_via_anchor_fallback() -> None:
    submission = _submission(
        no_wrap=True,
        prompt_text="raw task body without wrap",
        request_anchor="job_current",
    )
    backend = _RetryBackend("job_current\nraw task body\n❯\n")

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]


# ---------------------------------------------------------------------------
# poll_submission 接线测试：重发发生且计数经 finalize 持久化
# ---------------------------------------------------------------------------


def _wired_poll_submission(
    submission: ProviderSubmission,
    backend: object,
    *,
    poll: SimpleNamespace | None = None,
    monkeypatch,
) -> ProviderPollResult:
    poll = poll if poll is not None else _poll()
    prepared = SimpleNamespace(reader=object(), backend=backend, pane_id="%1")
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.prepare_active_poll_without_liveness",
        lambda submission, now: prepared,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.poll_exact_hook",
        lambda submission, now: None,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.ensure_active_pane_alive",
        lambda submission, backend, pane_id, now: None,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.build_poll_state",
        lambda submission: poll,
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.read_events",
        lambda reader, state: ([], state),
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.state_session_path",
        lambda state: "",
    )
    monkeypatch.setattr(
        "provider_backends.claude.execution_runtime.polling.apply_session_rotation",
        lambda submission, poll, new_session_path, now: None,
    )
    return poll_submission(None, submission, now=NOW)


def test_poll_submission_resends_once_and_persists_counter(monkeypatch) -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend(f"{LONG_UNICODE_PROMPT}\n❯\n")

    result = _wired_poll_submission(submission, backend, monkeypatch=monkeypatch)

    assert isinstance(result, ProviderPollResult)
    assert result.decision is None
    assert backend.keys == [("%1", "Enter")]
    # finalize_poll_result 展开 runtime_state，计数跨轮持久化
    assert result.submission.runtime_state["activation_enter_count"] == 1
    assert result.submission.runtime_state["activation_enter_at"] == NOW


def test_poll_submission_does_not_resend_when_events_show_activation(monkeypatch) -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend(f"{LONG_UNICODE_PROMPT}\n❯\n")

    # 事件已观察到 anchor → poll.anchor_seen=True → 不得重发
    result = _wired_poll_submission(
        submission,
        backend,
        poll=_poll(anchor_seen=True),
        monkeypatch=monkeypatch,
    )

    assert isinstance(result, ProviderPollResult)
    assert result.decision is None
    assert backend.keys == []
