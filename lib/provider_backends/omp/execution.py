from __future__ import annotations

from pathlib import Path

from provider_backends.native_cli_support import (
    NativeCliExecutionConfig,
    NativeCliExecutionRequest,
    NativeCliSubprocessAdapter,
)
from provider_backends.pi.execution import observe_pi_json_output
from provider_core.runtime_shared import provider_start_parts


def build_execution_adapter() -> NativeCliSubprocessAdapter:
    return NativeCliSubprocessAdapter(
        NativeCliExecutionConfig(
            provider="omp",
            session_filename=".omp-session",
            command_builder=_build_command,
            env_builder=_build_env,
            private_path_env_names=("PI_CODING_AGENT_SESSION_DIR",),
            observer=observe_pi_json_output,
            output_kind="jsonl",
            mode="omp_run",
            start_failed_reason="omp_run_start_failed",
            failed_reason="omp_run_failed",
            empty_reason="omp_empty_reply",
            run_error_reason="omp_run_error",
            complete_reason="omp_run_stop",
            process_exit_complete_reason="omp_run_exit",
            timeout_reason="omp_run_timeout",
        )
    )


def _build_command(request: NativeCliExecutionRequest) -> list[str]:
    session_dir = _state_path(request, "omp_session_dir", fallback="sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return [
        *provider_start_parts("omp"),
        "--mode",
        "json",
        "--session-dir",
        str(session_dir),
        "--approval-mode",
        "yolo",
        "--print",
        request.prompt,
    ]


def _build_env(request: NativeCliExecutionRequest) -> dict[str, str]:
    session_dir = _state_path(request, "omp_session_dir", fallback="sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    return {"PI_CODING_AGENT_SESSION_DIR": str(session_dir)}


def _state_path(request: NativeCliExecutionRequest, key: str, *, fallback: str) -> Path:
    raw = str(request.session_data.get(key) or "").strip()
    if raw:
        return Path(raw).expanduser()
    state_dir = Path(str(request.session_data.get("omp_state_dir") or request.work_dir / ".ccb" / "omp")).expanduser()
    return state_dir / fallback


__all__ = ["build_execution_adapter"]
