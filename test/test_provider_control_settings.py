from __future__ import annotations

from pathlib import Path

import pytest

from agents.config_loader import load_project_config
import provider_control.settings as settings_module
from provider_control import (
    ProviderSettingsError,
    ProviderSettingsStore,
    project_config_revision,
    provider_restart_pending_agents,
)


def _write_v2_project(root: Path) -> Path:
    config = root / '.ccb' / 'ccb.config'
    config.parent.mkdir(parents=True)
    config.write_text(
        '''version = 2
entry_window = "main"

[windows]
main = "mobile:codex"

[agents.mobile]
# Keep this operator note.
model = "gpt-5.5"
thinking = "medium"
''',
        encoding='utf-8',
    )
    return config


def test_provider_settings_preserves_document_and_records_restart_intent(tmp_path: Path) -> None:
    config = _write_v2_project(tmp_path)
    before = project_config_revision(tmp_path)

    result = ProviderSettingsStore().apply(
        project_root=tmp_path,
        agent='mobile',
        model='gpt-5.6-sol',
        thinking='xhigh',
        expected_revision=str(before),
        allowed_models={'gpt-5.5', 'gpt-5.6-sol'},
        allowed_thinking={'low', 'medium', 'high', 'xhigh'},
    )

    text = config.read_text(encoding='utf-8')
    assert '# Keep this operator note.' in text
    assert 'model = "gpt-5.6-sol"' in text
    assert 'thinking = "xhigh"' in text
    assert result.changed is True
    assert result.backup_path is not None
    assert Path(result.backup_path).is_file()
    assert (tmp_path / '.ccb' / 'ccbd' / 'config-restart-intent.json').is_file()
    assert provider_restart_pending_agents(tmp_path) == frozenset({'mobile'})
    assert 'backup_path' not in result.to_record()


def test_provider_settings_rolls_back_when_restart_intent_cannot_be_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_v2_project(tmp_path)
    original = config.read_text(encoding='utf-8')

    def _fail_restart_intent(*args, **kwargs):
        raise OSError('intent store unavailable')

    monkeypatch.setattr(
        settings_module,
        'record_config_restart_intent',
        _fail_restart_intent,
    )

    with pytest.raises(ProviderSettingsError, match='restart state') as excinfo:
        ProviderSettingsStore().apply(
            project_root=tmp_path,
            agent='mobile',
            model='gpt-5.6-sol',
            thinking='high',
            expected_revision=str(project_config_revision(tmp_path)),
            allowed_models={'gpt-5.6-sol'},
            allowed_thinking={'high'},
        )

    assert excinfo.value.status_code == 503
    assert config.read_text(encoding='utf-8') == original
    assert provider_restart_pending_agents(tmp_path) == frozenset()


def test_provider_settings_rejects_stale_revision_without_writing(tmp_path: Path) -> None:
    config = _write_v2_project(tmp_path)
    original = config.read_text(encoding='utf-8')

    with pytest.raises(ProviderSettingsError, match='changed') as excinfo:
        ProviderSettingsStore().apply(
            project_root=tmp_path,
            agent='mobile',
            model='gpt-5.6-sol',
            thinking='high',
            expected_revision='stale',
            allowed_models={'gpt-5.6-sol'},
            allowed_thinking={'high'},
        )

    assert excinfo.value.status_code == 409
    assert config.read_text(encoding='utf-8') == original


def test_provider_settings_rejects_unlisted_thinking_before_reading_config(tmp_path: Path) -> None:
    with pytest.raises(ProviderSettingsError, match='thinking option') as excinfo:
        ProviderSettingsStore().apply(
            project_root=tmp_path,
            agent='mobile',
            model='gpt-5.6-sol',
            thinking='unsafe-flag',
            expected_revision='revision',
            allowed_models={'gpt-5.6-sol'},
            allowed_thinking={'low', 'high'},
        )

    assert excinfo.value.status_code == 422


def test_provider_settings_compiles_claude_model_and_effort_for_restart(
    tmp_path: Path,
) -> None:
    config = tmp_path / '.ccb' / 'ccb.config'
    config.parent.mkdir(parents=True)
    config.write_text(
        '''version = 2
entry_window = "main"

[windows]
main = "claude_agent:claude"

[agents.claude_agent]
model = "sonnet"
thinking = "high"
''',
        encoding='utf-8',
    )

    ProviderSettingsStore().apply(
        project_root=tmp_path,
        agent='claude_agent',
        model='opus',
        thinking='xhigh',
        expected_revision=str(project_config_revision(tmp_path)),
        allowed_models={'sonnet', 'opus'},
        allowed_thinking={'low', 'medium', 'high', 'xhigh', 'max'},
    )

    spec = load_project_config(tmp_path).config.agents['claude_agent']
    assert spec.model == 'opus'
    assert spec.thinking == 'xhigh'
    assert spec.startup_args[:4] == ('--model', 'opus', '--effort', 'xhigh')
