from __future__ import annotations

from pathlib import Path

from provider_core.inherited_skills import (
    materialize_required_control_skills,
    required_control_skills_ready,
)


GROK_CCB_SKILL_NAMES = ('ask', 'ccb-clear')


def materialize_grok_skills(target_home: Path, *, profile=None) -> tuple[str, ...]:
    del profile
    target_root = Path(target_home).expanduser() / '.grok' / 'skills'
    return materialize_required_control_skills(
        provider='grok',
        target_dir=target_root,
    )


def grok_ccb_skills_ready(target_home: Path) -> bool:
    target_root = Path(target_home).expanduser() / '.grok' / 'skills'
    return required_control_skills_ready(
        provider='grok',
        target_dir=target_root,
    )


def grok_skill_permission_args() -> tuple[str, ...]:
    return (
        '--allow',
        'Bash(command ask *)',
        '--allow',
        'Bash(command ccb clear*)',
    )


__all__ = [
    'GROK_CCB_SKILL_NAMES',
    'grok_ccb_skills_ready',
    'grok_skill_permission_args',
    'materialize_grok_skills',
]
