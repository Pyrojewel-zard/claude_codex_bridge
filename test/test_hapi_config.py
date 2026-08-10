from __future__ import annotations

from pathlib import Path

import pytest

from agents.config_identity import project_config_identity_payload
from agents.config_loader import (
    ConfigValidationError,
    load_project_config,
    render_project_config_text,
)
from agents.models import HapiConfig, ProjectConfig

# Anchor runtime state so hardcoded `.ccb/...` paths in upstream config code
# stay stable under this fork's default relocation to ~/.local/ccb.
@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


def _write_config(project_root: Path, text: str) -> Path:
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding='utf-8')
    return config_path


def _load(project_root: Path):
    return load_project_config(project_root)


# ---------------------------------------------------------------------------
# HapiConfig model
# ---------------------------------------------------------------------------


def test_hapi_config_defaults_disabled() -> None:
    config = HapiConfig()
    assert config.enabled is False
    assert config.command == 'hapi'
    assert config.to_record() == {'enabled': False, 'command': 'hapi'}


def test_hapi_config_explicit_command() -> None:
    config = HapiConfig(enabled=True, command='/usr/local/bin/hapi')
    assert config.enabled is True
    assert config.command == '/usr/local/bin/hapi'


@pytest.mark.parametrize(
    'command',
    [
        '',
        '   ',
        'hapi | cat',
        'hapi; rm -rf /',
        'hapi && x',
        'hapi > /tmp/x',
        'hapi$(whoami)',
        'hapi\nx',
        'hapi x',
    ],
)
def test_hapi_config_rejects_empty_or_unsafe_command(command: str) -> None:
    with pytest.raises(Exception):
        HapiConfig(command=command)


def test_hapi_config_enabled_must_be_bool() -> None:
    with pytest.raises(Exception):
        HapiConfig(enabled='true')  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Project config parsing
# ---------------------------------------------------------------------------


def test_project_config_defaults_hapi_disabled(tmp_path: Path) -> None:
    _write_config(tmp_path, 'cmd; agent1:codex\n')
    config = _load(tmp_path).config
    assert config.hapi.enabled is False
    assert config.hapi.command == 'hapi'


def test_project_config_parses_enabled_hapi_block(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\ncommand = "hapi"\n',
    )
    config = _load(tmp_path).config
    assert config.hapi.enabled is True
    assert config.hapi.command == 'hapi'


def test_project_config_parses_explicit_hapi_command(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\ncommand = "/opt/hapi/bin/hapi"\n',
    )
    config = _load(tmp_path).config
    assert config.hapi.command == '/opt/hapi/bin/hapi'


def test_project_config_rejects_unknown_hapi_key(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\nbogus = 1\n',
    )
    with pytest.raises(ConfigValidationError, match='hapi contains unknown fields'):
        _load(tmp_path)


def test_project_config_rejects_unsafe_hapi_command(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\ncommand = "hapi | cat"\n',
    )
    with pytest.raises(ConfigValidationError, match='hapi.command'):
        _load(tmp_path)


def test_project_config_enabled_rejects_unsupported_provider(tmp_path: Path) -> None:
    _write_config(tmp_path, 'cmd; agent1:gemini\n\n[hapi]\nenabled = true\n')
    with pytest.raises(ConfigValidationError, match='supports only claude and codex'):
        _load(tmp_path)


def test_project_config_enabled_rejects_explicit_template(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[agents.agent1]\nprovider_command_template = "x {command}"\n\n[hapi]\nenabled = true\n',
    )
    with pytest.raises(ConfigValidationError, match='provider_command_template while hapi mode is enabled'):
        _load(tmp_path)


def test_project_config_disabled_allows_template_and_any_provider(tmp_path: Path) -> None:
    # Disabled mode must not impose the HAPI provider/template restrictions.
    _write_config(
        tmp_path,
        'cmd; agent1:gemini\n\n[agents.agent1]\nprovider_command_template = "wrap {command}"\n',
    )
    config = _load(tmp_path).config
    assert config.hapi.enabled is False
    assert config.agents['agent1'].provider == 'gemini'
    assert config.agents['agent1'].provider_command_template == 'wrap {command}'


# ---------------------------------------------------------------------------
# Serialization round-trip and config signature
# ---------------------------------------------------------------------------


def test_project_config_to_record_carries_hapi(tmp_path: Path) -> None:
    _write_config(tmp_path, 'cmd; agent1:claude\n\n[hapi]\nenabled = true\n')
    record = _load(tmp_path).config.to_record()
    assert record['hapi'] == {'enabled': True, 'command': 'hapi'}


def test_project_config_signature_drift_when_enabled(tmp_path: Path) -> None:
    _write_config(tmp_path, 'cmd; agent1:claude\n')
    disabled_sig = project_config_identity_payload(_load(tmp_path).config)['config_signature']
    _write_config(tmp_path, 'cmd; agent1:claude\n\n[hapi]\nenabled = true\n')
    enabled_sig = project_config_identity_payload(_load(tmp_path).config)['config_signature']
    assert disabled_sig != enabled_sig


def test_project_config_signature_stable_for_default_disabled(tmp_path: Path) -> None:
    # An absent [hapi] block and an explicit disabled block must compare equal
    # so default-disabled configs do not spuriously drift.
    _write_config(tmp_path, 'cmd; agent1:claude\n')
    absent_sig = project_config_identity_payload(_load(tmp_path).config)['config_signature']
    _write_config(tmp_path, 'cmd; agent1:claude\n\n[hapi]\nenabled = false\n')
    explicit_sig = project_config_identity_payload(_load(tmp_path).config)['config_signature']
    assert absent_sig == explicit_sig


def test_project_config_overlay_preserves_hapi(tmp_path: Path) -> None:
    # HAPI block in the hybrid overlay must survive the merge into the base
    # compact document.
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\ncommand = "/opt/hapi"\n',
    )
    config = _load(tmp_path).config
    assert config.hapi.enabled is True
    assert config.hapi.command == '/opt/hapi'


def test_project_config_copy_preserves_hapi(tmp_path: Path) -> None:
    from dataclasses import replace

    _write_config(tmp_path, 'cmd; agent1:claude\n\n[hapi]\nenabled = true\n')
    config = _load(tmp_path).config
    copied = replace(config)
    assert copied.hapi == config.hapi
    assert copied.hapi.enabled is True


def test_compact_config_render_preserves_enabled_hapi(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'cmd; agent1:claude\n\n[hapi]\nenabled = true\ncommand = "/opt/hapi"\n',
    )
    config = _load(tmp_path).config

    rendered = render_project_config_text(config)

    assert '[hapi]' in rendered
    assert 'enabled = true' in rendered
    assert 'command = "/opt/hapi"' in rendered
    _write_config(tmp_path, rendered)
    restored = _load(tmp_path).config
    assert restored.hapi == config.hapi


def test_windows_config_render_preserves_enabled_hapi(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'version = 2\nentry_window = "main"\n\n[windows]\nmain = "agent1:claude"\n\n'
        '[hapi]\nenabled = true\ncommand = "hapi"\n',
    )
    config = _load(tmp_path).config

    rendered = render_project_config_text(config)

    assert '[hapi]' in rendered
    _write_config(tmp_path, rendered)
    assert _load(tmp_path).config.hapi == config.hapi
