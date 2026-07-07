from __future__ import annotations

from provider_backends.native_cli_support import NativeCliLaunchConfig, build_native_cli_runtime_launcher
from provider_core.contracts import ProviderRuntimeLauncher


def build_runtime_launcher() -> ProviderRuntimeLauncher:
    return build_native_cli_runtime_launcher(NativeCliLaunchConfig(provider="kiro", home_env="KIRO_HOME"))


__all__ = ["build_runtime_launcher"]
