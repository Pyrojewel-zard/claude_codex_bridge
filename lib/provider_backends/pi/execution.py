from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from provider_backends.native_cli_support import (
    NativeCliExecutionConfig,
    NativeCliExecutionRequest,
    NativeCliObservation,
    NativeCliSubprocessAdapter,
)
from provider_core.runtime_shared import provider_start_parts


def build_execution_adapter() -> NativeCliSubprocessAdapter:
    return NativeCliSubprocessAdapter(
        NativeCliExecutionConfig(
            provider="pi",
            session_filename=".pi-session",
            command_builder=_build_command,
            env_builder=_build_env,
            private_path_env_names=(
                "PI_CODING_AGENT_DIR",
                "PI_CODING_AGENT_SESSION_DIR",
            ),
            private_raw_env_names=("PI_SKIP_VERSION_CHECK", "PI_TELEMETRY"),
            observer=observe_pi_json_output,
            output_kind="jsonl",
            mode="pi_run",
            start_failed_reason="pi_run_start_failed",
            failed_reason="pi_run_failed",
            empty_reason="pi_empty_reply",
            run_error_reason="pi_run_error",
            complete_reason="pi_run_stop",
            process_exit_complete_reason="pi_run_exit",
            timeout_reason="pi_run_timeout",
        )
    )


def _build_command(request: NativeCliExecutionRequest) -> list[str]:
    session_dir = _state_path(request, "pi_session_dir", fallback="sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return [
        *provider_start_parts("pi"),
        "--mode",
        "json",
        "--session-dir",
        str(session_dir),
        "--no-approve",
        "--name",
        request.job.job_id,
        request.prompt,
    ]


def _build_env(request: NativeCliExecutionRequest) -> dict[str, str]:
    pi_home = _state_path(request, "pi_home", fallback="home")
    session_dir = _state_path(request, "pi_session_dir", fallback="sessions")
    pi_home.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    return {
        "PI_CODING_AGENT_DIR": str(pi_home),
        "PI_CODING_AGENT_SESSION_DIR": str(session_dir),
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }


def observe_pi_json_output(path: Path) -> NativeCliObservation:
    if not path or not path.is_file():
        return NativeCliObservation()
    finished = False
    finish_reason = ""
    turn_ref: str | None = None
    completed_at: object | None = None
    error = ""
    intermediate = False
    delta_chunks: list[str] = []
    latest_message_text = ""
    final_text = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return NativeCliObservation(error=f"read_stdout_failed:{exc}")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "").strip().lower().replace("-", "_")
        if "error" in event_type or "failed" in event_type:
            error = _pi_text(event) or event_type
            continue
        if "tool" in event_type:
            intermediate = True
            finish_reason = finish_reason or "tool_calls"
            continue
        message = event.get("message")
        if isinstance(message, dict) and _pi_message_role(message) == "assistant":
            message_text = _pi_message_text(message)
            if message_text:
                latest_message_text = message_text
                turn_ref = turn_ref or _pi_ref(message)
                completed_at = completed_at or _pi_time(event)
        assistant_event = event.get("assistantMessageEvent")
        if isinstance(assistant_event, dict):
            delta = str(assistant_event.get("delta") or "")
            if delta:
                delta_chunks.append(delta)
        if event_type == "turn_end":
            finished = True
            finish_reason = "turn_end"
            final_text = _pi_message_text(message) if isinstance(message, dict) else latest_message_text
            turn_ref = turn_ref or _pi_ref(event)
            completed_at = completed_at or _pi_time(event)
        elif event_type == "agent_end":
            finished = True
            finish_reason = finish_reason or "agent_end"
            final_text = final_text or _last_assistant_message_text(event.get("messages")) or latest_message_text
            turn_ref = turn_ref or _pi_ref(event)
            completed_at = completed_at or _pi_time(event)

    text = final_text or latest_message_text or "".join(delta_chunks)
    return NativeCliObservation(
        text=text,
        finished=finished,
        finish_reason=finish_reason,
        turn_ref=turn_ref,
        completed_at=completed_at,
        error=error,
        intermediate=intermediate,
    )


def _state_path(request: NativeCliExecutionRequest, key: str, *, fallback: str) -> Path:
    raw = str(request.session_data.get(key) or "").strip()
    if raw:
        return Path(raw).expanduser()
    state_dir = Path(str(request.session_data.get("pi_state_dir") or request.work_dir / ".ccb" / "pi")).expanduser()
    return state_dir / fallback


def _pi_message_role(message: dict[str, Any]) -> str:
    return str(message.get("role") or message.get("sender") or message.get("author") or "").strip().lower()


def _pi_message_text(message: dict[str, Any]) -> str:
    return _pi_text(message.get("content"))


def _last_assistant_message_text(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and _pi_message_role(message) == "assistant":
            text = _pi_message_text(message)
            if text:
                return text
    return ""


def _pi_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_pi_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    for key in ("text", "delta", "content", "message", "payload", "data", "part"):
        nested = value.get(key)
        text = _pi_text(nested)
        if text:
            return text
    return ""


def _pi_ref(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("id", "message_id", "session_id", "turn_id", "request_id"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    for key in ("message", "payload", "data"):
        ref = _pi_ref(value.get(key))
        if ref:
            return ref
    return None


def _pi_time(value: Any) -> object | None:
    if not isinstance(value, dict):
        return None
    for key in ("completed_at", "timestamp", "time", "created_at", "updated_at"):
        raw = value.get(key)
        if raw:
            return raw
    for key in ("message", "payload", "data"):
        found = _pi_time(value.get(key))
        if found:
            return found
    return None


__all__ = ["build_execution_adapter", "observe_pi_json_output"]
