from __future__ import annotations

from pathlib import Path

from provider_backends.native_cli_support import NativeCliLaunchConfig, build_native_cli_runtime_launcher
from provider_core.contracts import ProviderRuntimeLauncher


def build_runtime_launcher() -> ProviderRuntimeLauncher:
    return build_native_cli_runtime_launcher(
        NativeCliLaunchConfig(
            provider="omp",
            visible_args_builder=_omp_visible_args,
            visible_env_builder=_omp_visible_env,
            visible_path_env_names=("PI_CODING_AGENT_DIR",),
        )
    )


def _omp_visible_args(prepared_state: dict[str, object]) -> tuple[str, ...]:
    session_dir = _path_from_prepared(prepared_state, "omp_state_dir") / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    return ("--session-dir", str(session_dir))


def _omp_visible_env(prepared_state: dict[str, object]) -> dict[str, str]:
    agent_dir = _path_from_prepared(prepared_state, "omp_home") / ".omp" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return {"PI_CODING_AGENT_DIR": str(agent_dir)}


def _path_from_prepared(prepared_state: dict[str, object], key: str) -> Path:
    raw = str(prepared_state.get(key) or "").strip()
    if not raw:
        raise RuntimeError(f"omp launch requires {key} in prepared_state")
    return Path(raw).expanduser()


__all__ = ["build_runtime_launcher"]
