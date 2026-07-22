from __future__ import annotations

from provider_backends.native_cli_support import NativeCliLaunchConfig, build_native_cli_runtime_launcher
from provider_core.contracts import ProviderRuntimeLauncher


def build_runtime_launcher() -> ProviderRuntimeLauncher:
    return build_native_cli_runtime_launcher(
        NativeCliLaunchConfig(provider="qoderclicn", visible_args_builder=_config_dir_args)
    )


def _config_dir_args(launch_context: dict[str, object]) -> tuple[str, ...]:
    config_dir = str(launch_context.get("qoderclicn_data_dir") or "").strip()
    return ("--config-dir", config_dir) if config_dir else ()


__all__ = ["build_runtime_launcher"]
