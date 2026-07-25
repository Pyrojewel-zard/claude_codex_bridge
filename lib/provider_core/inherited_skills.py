from __future__ import annotations

from pathlib import Path

from provider_core.projected_assets import route_projected_tree


def packaged_inherited_skills_dir(provider: str) -> Path:
    normalized = str(provider or '').strip().lower()
    return _repo_root() / 'inherit_skills' / f'{normalized}_skills'


def packaged_inherited_skill_file(provider: str, relative_path: str) -> Path:
    return packaged_inherited_skills_dir(provider) / relative_path


def route_packaged_inherited_skills_dir(
    *,
    provider: str,
    target_dir: Path,
    enabled: bool,
    label: str,
) -> bool:
    return route_projected_tree(
        packaged_inherited_skills_dir(provider),
        Path(target_dir),
        enabled=enabled,
        label=label,
    )


def inherits_skills(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_skills', True))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


__all__ = [
    'inherits_skills',
    'packaged_inherited_skill_file',
    'packaged_inherited_skills_dir',
    'route_packaged_inherited_skills_dir',
]
