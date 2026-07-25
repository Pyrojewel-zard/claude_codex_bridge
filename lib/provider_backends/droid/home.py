from __future__ import annotations

import os
from pathlib import Path

from cli.services.role_command_policy import role_command_policy_disables_inherited_assets
from provider_core.projected_assets import (
    projected_path_is_owned,
    remove_projected_path,
    route_projected_tree,
    seed_projected_tree,
)
from provider_core.projected_settings import (
    project_json_mapping_fields,
    rebase_json_path_fields,
)
from provider_core.source_home import current_provider_source_home

_DROID_SKILLS_PROJECTION_LABEL = 'droid-inherited-skills'
_DROID_PLUGINS_PROJECTION_LABEL = 'droid-inherited-plugins'
_DROID_PLUGIN_SETTINGS_PROJECTION_LABEL = 'droid-inherited-plugin-settings'
_DROID_PLUGIN_PATH_KEYS = frozenset({'installLocation', 'installPath'})


def managed_droid_home_for_runtime(runtime_dir: Path) -> Path:
    runtime_dir = Path(runtime_dir).expanduser()
    if runtime_dir.parent.name == 'provider-runtime':
        return runtime_dir.parent.parent / 'provider-state' / 'droid' / 'home'
    return runtime_dir / 'droid-home'


def materialize_droid_home_config(
    target_home: Path,
    *,
    profile=None,
    source_home: Path | None = None,
    command_policy=None,
) -> Path:
    target_home = Path(target_home).expanduser()
    source_home = Path(source_home).expanduser() if source_home is not None else _system_factory_home()
    target_home.mkdir(parents=True, exist_ok=True)
    (target_home / 'sessions').mkdir(parents=True, exist_ok=True)
    _route_inherited_tree(
        source_home / 'skills',
        target_home / 'skills',
        enabled=_inherits_skills(profile),
        label=_DROID_SKILLS_PROJECTION_LABEL,
    )
    inherited_plugins_enabled = (
        _inherits_config(profile)
        and not role_command_policy_disables_inherited_assets(command_policy)
    )
    source_plugins = source_home / 'plugins'
    target_plugins = target_home / 'plugins'
    seeded = seed_projected_tree(
        source_plugins,
        target_plugins,
        enabled=inherited_plugins_enabled,
        label=_DROID_PLUGINS_PROJECTION_LABEL,
    )
    plugins_owned = projected_path_is_owned(
        target_plugins,
        label=_DROID_PLUGINS_PROJECTION_LABEL,
    )
    plugins_available = (
        inherited_plugins_enabled
        and target_plugins.is_dir()
        and (seeded or plugins_owned)
    )
    if plugins_available and not rebase_json_path_fields(
        (target_plugins / 'installed_plugins.json', target_plugins / 'known_marketplaces.json'),
        source_root=source_plugins,
        target_root=target_plugins,
        fields=_DROID_PLUGIN_PATH_KEYS,
    ):
        remove_projected_path(target_plugins, label=_DROID_PLUGINS_PROJECTION_LABEL)
        plugins_available = False
    project_json_mapping_fields(
        source_home / 'settings.json',
        target_home / 'settings.json',
        fields=('enabledPlugins',),
        enabled=plugins_available,
        label=_DROID_PLUGIN_SETTINGS_PROJECTION_LABEL,
        marker_path=target_home / '.ccb-plugin-settings-projection.json',
    )
    return target_home


def _route_inherited_tree(source: Path, target: Path, *, enabled: bool, label: str) -> None:
    route_projected_tree(source, target, enabled=enabled, label=label)


def _system_factory_home() -> Path:
    if os.environ.get('CCB_SOURCE_HOME'):
        return current_provider_source_home() / '.factory'
    for name in ('FACTORY_HOME', 'FACTORY_ROOT'):
        raw = str(os.environ.get(name) or '').strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not _looks_like_ccb_provider_home(candidate):
            return candidate
    return current_provider_source_home() / '.factory'


def _inherits_skills(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_skills', True))


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


__all__ = ['managed_droid_home_for_runtime', 'materialize_droid_home_config']
