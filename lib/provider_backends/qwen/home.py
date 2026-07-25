from __future__ import annotations

import os
from pathlib import Path

from cli.services.role_command_policy import role_command_policy_disables_inherited_assets
from provider_core.projected_assets import seed_projected_tree
from provider_core.source_home import current_provider_source_home

_QWEN_EXTENSIONS_PROJECTION_LABEL = 'qwen-inherited-extensions'


def materialize_qwen_home_config(
    target_home: Path,
    *,
    profile=None,
    source_home: Path | None = None,
    command_policy=None,
) -> Path:
    target_home = Path(target_home).expanduser()
    source_home = (
        Path(source_home).expanduser()
        if source_home is not None
        else _system_qwen_home()
    )
    target_home.mkdir(parents=True, exist_ok=True)
    seed_projected_tree(
        source_home / 'extensions',
        target_home / 'extensions',
        enabled=(
            _inherits_config(profile)
            and not role_command_policy_disables_inherited_assets(command_policy)
        ),
        label=_QWEN_EXTENSIONS_PROJECTION_LABEL,
    )
    return target_home


def _system_qwen_home() -> Path:
    if os.environ.get('CCB_SOURCE_HOME'):
        return current_provider_source_home() / '.qwen'
    raw = str(os.environ.get('QWEN_HOME') or '').strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not _looks_like_ccb_provider_home(candidate):
            return candidate
    return current_provider_source_home() / '.qwen'


def _inherits_config(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_config', True))


def _looks_like_ccb_provider_home(path: Path) -> bool:
    parts = Path(path).expanduser().parts
    for index in range(0, max(len(parts) - 4, 0)):
        if parts[index] != 'agents':
            continue
        if parts[index + 2] == 'provider-state' and parts[index + 4] == 'home':
            return True
    return False


__all__ = ['materialize_qwen_home_config']
