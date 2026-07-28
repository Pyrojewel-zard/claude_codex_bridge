from __future__ import annotations

from pathlib import Path

import pytest

from agents.models import ProviderProfileSpec
from provider_backends.qoder.skills import materialize_qoder_skills


@pytest.mark.parametrize(
    ('provider', 'source_root_name'),
    (
        ('qoder', '.qoder'),
        ('qoderclicn', '.qoder-cn'),
    ),
)
def test_qoder_skills_follow_effective_config_root(
    tmp_path: Path,
    provider: str,
    source_root_name: str,
) -> None:
    source_home = tmp_path / 'source-home'
    config_dir = tmp_path / 'effective-config'
    source_skill = source_home / source_root_name / 'skills' / 'demo'
    source_skill.mkdir(parents=True)
    (source_skill / 'SKILL.md').write_text('demo\n', encoding='utf-8')

    active = materialize_qoder_skills(
        provider=provider,
        config_dir=config_dir,
        profile=ProviderProfileSpec(),
        source_home=source_home,
    )

    assert active == ('demo', 'ask', 'ccb-clear')
    assert (config_dir / 'skills' / 'demo').is_symlink()
    assert (config_dir / 'skills' / 'demo.ccb-projection.json').is_file()
    assert (config_dir / 'skills' / 'ask' / 'SKILL.md').is_file()
    assert (config_dir / 'skills' / 'ccb-clear' / 'SKILL.md').is_file()


def test_qoder_skills_preserve_unmarked_conflicts_and_remove_only_owned_optional_entries(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / 'source-home'
    config_dir = tmp_path / 'effective-config'
    source_skills = source_home / '.qoder' / 'skills'
    for name in ('conflict', 'optional'):
        skill = source_skills / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text(f'source {name}\n', encoding='utf-8')
    conflict = config_dir / 'skills' / 'conflict'
    conflict.mkdir(parents=True)
    (conflict / 'SKILL.md').write_text('user conflict\n', encoding='utf-8')

    materialize_qoder_skills(
        provider='qoder',
        config_dir=config_dir,
        profile=ProviderProfileSpec(),
        source_home=source_home,
    )
    materialize_qoder_skills(
        provider='qoder',
        config_dir=config_dir,
        profile=ProviderProfileSpec(inherit_skills=False),
        source_home=source_home,
    )

    assert (conflict / 'SKILL.md').read_text(encoding='utf-8') == 'user conflict\n'
    assert not (config_dir / 'skills' / 'optional').exists()
    assert (config_dir / 'skills' / 'ask' / 'SKILL.md').is_file()
    assert (config_dir / 'skills' / 'ccb-clear' / 'SKILL.md').is_file()


def test_qoder_skills_do_not_mutate_explicit_source_config_root(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    source_config = source_home / '.qoder'
    user_skill = source_config / 'skills' / 'user-skill'
    user_skill.mkdir(parents=True)
    (user_skill / 'SKILL.md').write_text('user\n', encoding='utf-8')

    active = materialize_qoder_skills(
        provider='qoder',
        config_dir=source_config,
        source_home=source_home,
    )

    assert active == ()
    assert not (source_config / 'skills' / 'ask').exists()
    assert not tuple((source_config / 'skills').glob('*.ccb-projection.json'))
