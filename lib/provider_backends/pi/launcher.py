from __future__ import annotations

from pathlib import Path

from provider_backends.native_cli_support import NativeCliLaunchConfig, build_native_cli_runtime_launcher
from provider_core.contracts import ProviderRuntimeLauncher


def build_runtime_launcher() -> ProviderRuntimeLauncher:
    return build_native_cli_runtime_launcher(
        NativeCliLaunchConfig(
            provider="pi",
            visible_args_builder=_pi_visible_args,
            visible_env_builder=_pi_visible_env,
            visible_path_env_names=(
                "PI_CODING_AGENT_DIR",
                "PI_CODING_AGENT_SESSION_DIR",
            ),
            visible_raw_env_names=("PI_SKIP_VERSION_CHECK", "PI_TELEMETRY"),
        )
    )


def _pi_visible_args(prepared_state: dict[str, object]) -> tuple[str, ...]:
    session_dir = _pi_session_dir(prepared_state)
    session_dir.mkdir(parents=True, exist_ok=True)
    return ("--session-dir", str(session_dir), "--no-approve")


def _pi_visible_env(prepared_state: dict[str, object]) -> dict[str, str]:
    home_dir = _path_from_prepared(prepared_state, "pi_home")
    session_dir = _pi_session_dir(prepared_state)
    home_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    return {
        "PI_CODING_AGENT_DIR": str(home_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(session_dir),
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }


def _pi_session_dir(prepared_state: dict[str, object]) -> Path:
    state_dir = _path_from_prepared(prepared_state, "pi_state_dir")
    return state_dir / "sessions"


def _path_from_prepared(prepared_state: dict[str, object], key: str) -> Path:
    raw = str(prepared_state.get(key) or "").strip()
    if not raw:
        raise RuntimeError(f"pi launch requires {key} in prepared_state")
    return Path(raw).expanduser()


__all__ = ["build_runtime_launcher"]
