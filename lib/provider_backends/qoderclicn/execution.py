from __future__ import annotations

from pathlib import Path

from provider_backends.native_cli_support import (
    NativeCliExecutionConfig,
    NativeCliExecutionRequest,
    NativeCliSubprocessAdapter,
)
from provider_core.runtime_shared import provider_start_parts


def build_execution_adapter() -> NativeCliSubprocessAdapter:
    return NativeCliSubprocessAdapter(
        NativeCliExecutionConfig(
            provider="qoderclicn",
            session_filename=".qoderclicn-session",
            command_builder=_build_command,
            env_builder=_build_env,
            output_kind="jsonl",
            mode="qoderclicn_run",
            start_failed_reason="qoderclicn_run_start_failed",
            failed_reason="qoderclicn_run_failed",
            empty_reason="qoderclicn_empty_reply",
            run_error_reason="qoderclicn_run_error",
            complete_reason="qoderclicn_run_stop",
            process_exit_complete_reason="qoderclicn_run_exit",
            timeout_reason="qoderclicn_run_timeout",
        )
    )


def _build_command(request: NativeCliExecutionRequest) -> list[str]:
    config_dir = _state_path(request, "qoderclicn_data_dir", fallback="data")
    config_dir.mkdir(parents=True, exist_ok=True)
    return [
        *provider_start_parts("qoderclicn"),
        "--print",
        "--output-format",
        "stream-json",
        "--config-dir",
        str(config_dir),
        "--session-id",
        request.job.job_id,
        request.prompt,
    ]


def _build_env(request: NativeCliExecutionRequest) -> dict[str, str]:
    del request
    return {}


def _state_path(request: NativeCliExecutionRequest, key: str, *, fallback: str) -> Path:
    raw = str(request.session_data.get(key) or "").strip()
    if raw:
        return Path(raw).expanduser()
    state_dir = Path(
        str(request.session_data.get("qoderclicn_state_dir") or request.work_dir / ".ccb" / "qoderclicn")
    ).expanduser()
    return state_dir / fallback


__all__ = ["build_execution_adapter"]
