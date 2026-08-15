from __future__ import annotations

from types import SimpleNamespace

from completion.models import CompletionSourceKind
from provider_backends.claude.execution_runtime.polling import (
    _composer_holds_prompt_tail,
    _current_composer_block,
    _maybe_resend_activation_enter,
    _prompt_tail_fingerprint,
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
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 长提示仍在输入框\n")

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
    assert updated.runtime_state["activation_enter_evidence"] == "anchor_marker"


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


def test_marker_in_history_with_empty_composer_does_not_send() -> None:
    submission = _submission()
    backend = _RetryBackend("CCB_REQ_ID: job_current\n上一轮历史输出\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
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


def test_resend_after_old_tight_end_bound_within_generous_max_wait() -> None:
    submission = _submission()
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 当前任务仍在输入框\n")
    # +15s was past the old [6,12)s end bound, but is inside the generous
    # give-up cap (default 600s): the retry must still fire.
    late_now = "2026-07-21T08:00:15Z"

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=late_now,
    )

    assert result is not None
    assert backend.keys == [("%1", "Enter")]
    assert result.runtime_state["activation_enter_evidence"] == "anchor_marker"


def test_no_resend_beyond_max_wait_cap() -> None:
    submission = _submission(prompt_sent_at="2026-07-21T07:50:00Z")  # 600s before NOW
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_max_wait_cap_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CCB_CLAUDE_ACTIVATION_MAX_WAIT_S", "10")
    submission = _submission(prompt_sent_at="2026-07-21T07:59:50Z")  # 10s before NOW
    backend = _RetryBackend("CCB_REQ_ID: job_current\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_env_grace_override_shrinks_window(monkeypatch) -> None:
    monkeypatch.setenv("CCB_CLAUDE_ACTIVATION_GRACE_S", "2")
    submission = _submission()
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 当前任务仍在输入框\n")
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
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 当前任务仍在输入框\n")

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
    backend = _RetryBackend("❯ job_current raw task body\n")

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]
    assert updated.runtime_state["activation_enter_evidence"] == "anchor_marker"


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
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 长提示仍在输入框\n")

    result = _wired_poll_submission(submission, backend, monkeypatch=monkeypatch)

    assert isinstance(result, ProviderPollResult)
    assert result.decision is None
    assert backend.keys == [("%1", "Enter")]
    # finalize_poll_result 展开 runtime_state，计数跨轮持久化
    assert result.submission.runtime_state["activation_enter_count"] == 1
    assert result.submission.runtime_state["activation_enter_at"] == NOW
    assert result.submission.runtime_state["activation_enter_evidence"] == "anchor_marker"


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


# ---------------------------------------------------------------------------
# 真实折叠长粘贴（recurrence）用例：composer 显示 [Pasted text #N +M lines]
# ---------------------------------------------------------------------------


def test_collapsed_pasted_placeholder_resends_exactly_once() -> None:
    # 初次 Enter 被吞：长提示被 Claude 折叠为占位符，pane 中看不到原始锚文本，
    # 但当前 composer 行的折叠占位符证明本 job 的提示仍待提交 → 恰一次 retry。
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend("会话历史…\n❯ [Pasted text #4 +11 lines]\n")

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
    assert updated.runtime_state["activation_enter_evidence"] == "pasted_placeholder"


def test_collapsed_placeholder_repeated_poll_never_resends() -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend("会话历史…\n❯ [Pasted text #4 +11 lines]\n")

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


def test_historical_placeholder_with_empty_composer_does_not_send() -> None:
    # 占位符仅出现在历史输出（上一轮被折叠的粘贴），当前 composer 为空 → 不发。
    submission = _submission()
    backend = _RetryBackend("上一轮对话…\nuser [Pasted text #2 +5 lines]\n❯\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_placeholder_composer_busy_does_not_send() -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend("❯ [Pasted text #4 +11 lines]\nesc to interrupt")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_placeholder_composer_already_activated_does_not_send() -> None:
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend("会话历史…\n❯ [Pasted text #4 +11 lines]\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(prompt_activated=True),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_composer_holding_different_plaintext_does_not_send() -> None:
    # composer 内是另一个任务的明文（无本 job 锚、非折叠占位符）→ 不发。
    submission = _submission()
    backend = _RetryBackend("❯ CCB_REQ_ID: job_other 别的任务的提示词\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_placeholder_in_history_with_foreign_composer_text_does_not_send() -> None:
    # 历史含占位符 + 当前 composer 是其他任务的明文 → 两个证据都不满足 → 不发。
    submission = _submission()
    backend = _RetryBackend("user [Pasted text #3 +8 lines]\n❯ 别的任务的明文\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_placeholder_marker_path_preserved_anchor_still_works() -> None:
    # 普通（未折叠）marker 路径保持：pane 仍含本 job 原始锚文本 → 照常重发。
    submission = _submission(prompt_text=LONG_UNICODE_PROMPT)
    backend = _RetryBackend("❯ CCB_REQ_ID: job_current 长提示仍在输入框\n")

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]
    assert updated.runtime_state["activation_enter_evidence"] == "anchor_marker"


# ---------------------------------------------------------------------------
# 观察者字段可见性：export_runtime_state 必须暴露新的 activation 状态
# ---------------------------------------------------------------------------


def test_export_runtime_state_exposes_activation_fields() -> None:
    from provider_backends.claude.execution import ClaudeProviderAdapter

    submission = _submission(
        activation_enter_count=1,
        activation_enter_at=NOW,
        activation_enter_evidence="pasted_placeholder",
    )
    exported = ClaudeProviderAdapter().export_runtime_state(submission)
    assert exported["activation_enter_count"] == 1
    assert exported["activation_enter_at"] == NOW
    assert exported["activation_enter_evidence"] == "pasted_placeholder"


def test_export_runtime_state_absent_evidence_is_none() -> None:
    from provider_backends.claude.execution import ClaudeProviderAdapter

    submission = _submission()
    exported = ClaudeProviderAdapter().export_runtime_state(submission)
    assert exported["activation_enter_count"] is None
    assert exported["activation_enter_at"] is None
    assert exported["activation_enter_evidence"] is None


# ---------------------------------------------------------------------------
# v3 (PR #305 第三版)：prompt-tail fingerprint —— 展开式多行 composer / TUI wrap
# ---------------------------------------------------------------------------

TAIL_PROMPT = (
    "CCB_REQ_ID: job_current\n\n"
    "当前任务：处理场馆预约草稿金额扩容与充值续充恢复。\n"
    "第一项：核对 balance_at_save 与 total_pay_amount 的精度透传。\n"
    "第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。"
)

WRAP_PROMPT = (
    "CCB_REQ_ID: job_current\n\n"
    "当前任务：请逐项核对场馆预约草稿金额列、储值余额口径与充值续充恢复路径是否一致。\n"
    "并按步骤确认每项结果。"
)


def _expanded_tail_pane() -> str:
    # 展开式多行 composer：anchor 已滚出 capture、无折叠占位符，仅尾部业务行可见。
    return (
        "会话历史…\n"
        "❯ 当前任务：处理场馆预约草稿金额扩容与充值续充恢复。\n"
        "  第一项：核对 balance_at_save 与 total_pay_amount 的精度透传。\n"
        "  第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。\n"
        "  ? for shortcuts\n"
    )


# --- fingerprint 直接单元测试 -------------------------------------------------


def test_prompt_tail_fingerprint_requires_two_business_lines() -> None:
    # 只有 1 条非通用业务行（anchor 行已被排除）→ 不足以构成指纹。
    assert _prompt_tail_fingerprint("CCB_REQ_ID: job_current\n\n只有一行业务") is None
    fp = _prompt_tail_fingerprint(TAIL_PROMPT)
    assert fp is not None
    assert len(fp) >= 2
    # 通用控制行（CCB_*）绝不进入指纹。
    assert all("CCB" not in frag for frag in fp)


def test_prompt_tail_fingerprint_excludes_generic_control_lines() -> None:
    # CCB_REPLY_MODE / CCB_REQ_ID 是通用尾行；剔除后只剩 1 条业务行 → 无指纹。
    fp = _prompt_tail_fingerprint(
        "CCB_REQ_ID: job_current\n\nCCB_REPLY_MODE: compact\n唯一业务行"
    )
    assert fp is None
    # 控制行落在尾部也不得成为指纹：指纹由控制行之前的业务行构成。
    fp = _prompt_tail_fingerprint(
        "CCB_REQ_ID: job_current\n\n"
        "第一项：核对场馆预约草稿金额扩容的精度透传。\n"
        "第二项：确认 cancel 在 EXPIRED 终态下的行为。\n"
        "CCB_REPLY_MODE: compact"
    )
    assert fp is not None
    assert all("CCB_REPLY_MODE" not in frag for frag in fp)
    assert fp[-1] == "第二项：确认 cancel 在 EXPIRED 终态下的行为。"


def test_prompt_tail_fingerprint_uses_tail_of_long_line() -> None:
    # 长行只贡献尾部片段（≤ _TAIL_FRAGMENT_CHARS=48），短尾行整体保留。
    fp = _prompt_tail_fingerprint(LONG_UNICODE_PROMPT)
    assert fp is not None
    assert all(len(frag) <= 48 for frag in fp)
    assert fp[-1] == "请逐条确认。"


# --- current-composer block 直接单元测试 ------------------------------------


def test_current_composer_block_extracts_expanded_multiline() -> None:
    block = _current_composer_block(_expanded_tail_pane())
    assert block is not None
    assert "当前任务：处理场馆预约草稿金额扩容与充值续充恢复。" in block
    assert "第一项：核对 balance_at_save 与 total_pay_amount 的精度透传。" in block
    assert "第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。" in block
    assert "会话历史" not in block  # 历史不得混入当前 composer block


def test_current_composer_block_empty_when_idle() -> None:
    block = _current_composer_block("会话历史…\n❯\n  ? for shortcuts\n")
    assert block is not None
    assert block.strip() == ""


def test_composer_holds_prompt_tail_ignores_history_only_tail() -> None:
    # 尾部业务行只在历史转录中出现、当前 composer 为空 → 不得命中。
    pane = (
        "user 当前任务：处理场馆预约草稿金额扩容与充值续充恢复。\n"
        "user 第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。\n"
        "❯\n"
    )
    assert _composer_holds_prompt_tail(pane, TAIL_PROMPT) is False


# --- v3 集成测试：第三种证据 prompt_tail -------------------------------


def test_expanded_multiline_prompt_tail_resends_exactly_once() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(_expanded_tail_pane())

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
    assert updated.runtime_state["activation_enter_evidence"] == "prompt_tail"


def test_tui_wrapped_prompt_tail_resends_exactly_once() -> None:
    # TUI 自动换行：一条逻辑行折成多行 composer 行，指纹跨行仍命中。
    submission = _submission(prompt_text=WRAP_PROMPT)
    pane = (
        "❯ 当前任务：请逐项核对场馆预约草稿金额列、储值余额口径\n"
        "  与充值续充恢复路径是否一致。并按步骤确认每项结果。\n"
    )
    backend = _RetryBackend(pane)

    updated = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert updated is not None
    assert backend.keys == [("%1", "Enter")]
    assert updated.runtime_state["activation_enter_evidence"] == "prompt_tail"


def test_tail_in_history_but_current_composer_foreign_does_not_send() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(
        "user 当前任务：处理场馆预约草稿金额扩容与充值续充恢复。\n"
        "user 第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。\n"
        "❯ 完全不同的另一个任务\n"
    )

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_tail_in_history_but_current_composer_empty_does_not_send() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(
        "user 当前任务：处理场馆预约草稿金额扩容与充值续充恢复。\n"
        "user 第二项：确认 cancel 在 EXPIRED 终态下明确返回 DRAFT_EXPIRED。\n"
        "❯\n"
    )

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_prompt_tail_evidence_respects_busy_pane() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(_expanded_tail_pane() + "esc to interrupt")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_prompt_tail_evidence_respects_already_activated() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(_expanded_tail_pane())

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(prompt_activated=True),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_prompt_tail_evidence_respects_at_most_once() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(_expanded_tail_pane())

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


def test_prompt_tail_evidence_respects_foreign_composer() -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend("❯ 处理退款规则与会员卡订单的另一个任务。\n")

    result = _maybe_resend_activation_enter(
        submission,
        prepared=_prepared(backend),
        poll=_poll(),
        now=NOW,
    )

    assert result is None
    assert backend.keys == []


def test_poll_submission_tail_evidence_persists_counter(monkeypatch) -> None:
    submission = _submission(prompt_text=TAIL_PROMPT)
    backend = _RetryBackend(_expanded_tail_pane())

    result = _wired_poll_submission(submission, backend, monkeypatch=monkeypatch)

    assert isinstance(result, ProviderPollResult)
    assert result.decision is None
    assert backend.keys == [("%1", "Enter")]
    assert result.submission.runtime_state["activation_enter_count"] == 1
    assert result.submission.runtime_state["activation_enter_at"] == NOW
    assert result.submission.runtime_state["activation_enter_evidence"] == "prompt_tail"
