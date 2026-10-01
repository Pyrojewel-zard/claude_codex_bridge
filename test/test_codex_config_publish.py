from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

import pytest

from provider_profiles import codex_home_config


@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch):
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


def _source_home(tmp_path: Path, text: str) -> Path:
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'config.toml').write_text(text, encoding='utf-8')
    return source


def test_materialize_publishes_main_config_once_after_in_memory_merge(tmp_path, monkeypatch):
    source = _source_home(
        tmp_path,
        'model = "gpt-5.5"\n\n[features]\nexternal_migration = true\n',
    )
    target = tmp_path / 'target'
    config_path = target / 'config.toml'
    original_atomic_publish = codex_home_config.atomic_write_text_if_changed
    publishes: list[tuple[Path, bool]] = []

    def record_publish(path, text, **kwargs):
        changed = original_atomic_publish(path, text, **kwargs)
        if Path(path) == config_path:
            publishes.append((Path(path), changed))
        return changed

    monkeypatch.setattr(codex_home_config, 'atomic_write_text_if_changed', record_publish)
    original_write_text = Path.write_text

    def reject_direct_main_config_write(path, text, *args, **kwargs):
        if Path(path) == config_path:
            raise AssertionError('main config must be published atomically at the end')
        return original_write_text(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, 'write_text', reject_direct_main_config_write)

    codex_home_config.materialize_codex_home_config(
        target,
        source_home=source,
        project_root=tmp_path,
        workspace_path=tmp_path,
    )
    first_text = config_path.read_text(encoding='utf-8')
    codex_home_config.materialize_codex_home_config(
        target,
        source_home=source,
        project_root=tmp_path,
        workspace_path=tmp_path,
    )

    assert publishes == [(config_path, True), (config_path, False)]
    assert first_text == config_path.read_text(encoding='utf-8')
    assert 'model = "gpt-5.5"' in first_text
    assert 'external_migration = false' in first_text


def test_invalid_source_never_overwrites_existing_target_config(tmp_path):
    source = _source_home(tmp_path, 'model = [broken\n')
    target = tmp_path / 'target'
    target.mkdir()
    config_path = target / 'config.toml'
    sentinel = 'model = "keep-me"\n'
    config_path.write_text(sentinel, encoding='utf-8')

    with pytest.raises(RuntimeError, match='cannot parse inherited Codex config source'):
        codex_home_config.materialize_codex_home_config(target, source_home=source)

    assert config_path.read_text(encoding='utf-8') == sentinel


def test_single_publish_keeps_profile_and_project_priority(tmp_path):
    source = _source_home(
        tmp_path,
        'model = "source-model"\n[features]\nexternal_migration = true\n',
    )
    target = tmp_path / 'target'
    profile = type(
        'Profile',
        (),
        {
            'env': {'CCB_CODEX_AUTH_MODE': 'none'},
            'plugins': {'review': {'enabled': True}},
            'mcp_servers': {'reviewer': {'command': 'reviewer'}},
            'inherit_config': True,
            'inherit_api': True,
            'inherit_auth': True,
            'inherit_skills': True,
            'inherit_commands': True,
            'inherit_memory': True,
        },
    )()
    codex_home_config.materialize_codex_home_config(
        target,
        source_home=source,
        profile=profile,
        project_root=tmp_path,
        workspace_path=tmp_path / 'workspace',
        model='agent-model',
    )

    config_text = (target / 'config.toml').read_text(encoding='utf-8')
    assert 'model = "agent-model"' in config_text
    assert 'external_migration = false' in config_text
    assert '[plugins.review]' in config_text
    assert '[mcp_servers.reviewer]' in config_text


def test_materialize_codex_home_config_applies_agent_model_reasoning_and_service_tier(
    tmp_path,
) -> None:
    source = _source_home(
        tmp_path,
        'model = "gpt-global"\nmodel_reasoning_effort = "low"\nservice_tier = "default"\n',
    )
    target = tmp_path / 'target-codex-overrides'

    codex_home_config.materialize_codex_home_config(
        target,
        source_home=source,
        project_root=tmp_path,
        model='gpt-6-astra',
        thinking='max',
        service_tier='fast',
    )

    config = tomllib.loads((target / 'config.toml').read_text(encoding='utf-8'))
    assert config['model'] == 'gpt-6-astra'
    assert config['model_reasoning_effort'] == 'max'
    assert config['service_tier'] == 'fast'
