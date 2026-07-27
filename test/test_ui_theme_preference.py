from __future__ import annotations

import json

from terminal_runtime.tmux_theme import tmux_theme_profile
from terminal_runtime.ui_theme import (
    detect_system_theme,
    effective_theme_preference,
    load_theme_preference,
    resolve_theme_request,
    save_theme_preference,
    theme_config_path,
)


def test_theme_preference_normalizes_aliases_and_persists(tmp_path) -> None:
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'config')}
    preference = resolve_theme_request('catppuccin-latte', environ=env)

    assert preference is not None
    assert preference.theme == 'light'
    assert preference.palette == 'latte'
    assert preference.tmux_profile == 'light'

    path = save_theme_preference(preference, environ=env)
    assert path == theme_config_path(env)
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload['theme'] == 'light'
    assert payload['palette'] == 'latte'
    assert payload['tmux_profile'] == 'light'
    assert load_theme_preference(env) == preference


def test_theme_preference_cycles_from_saved_theme(tmp_path) -> None:
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'config')}
    light = resolve_theme_request('light', environ=env)
    assert light is not None
    save_theme_preference(light, environ=env)

    assert resolve_theme_request('+', environ=env).theme == 'solarized'
    assert resolve_theme_request('-', environ=env).theme == 'dark'


def test_theme_preference_returns_none_for_unknown_theme(tmp_path) -> None:
    assert resolve_theme_request('unknown-theme', environ={'XDG_CONFIG_HOME': str(tmp_path / 'config')}) is None


def test_system_theme_persists_selection_and_resolves_effective_palette(tmp_path) -> None:
    env = {
        'XDG_CONFIG_HOME': str(tmp_path / 'config'),
        'CCB_SYSTEM_THEME': 'light',
    }
    preference = resolve_theme_request('system-default', environ=env)

    assert preference is not None
    assert preference.theme == 'system'
    assert preference.palette == 'system'
    assert preference.tmux_profile == 'system'
    assert effective_theme_preference(preference, env).theme == 'light'
    assert effective_theme_preference(preference, env).palette == 'latte'

    path = save_theme_preference(preference, environ=env)
    assert json.loads(path.read_text(encoding='utf-8')) == {
        'palette': 'system',
        'schema_version': 1,
        'theme': 'system',
        'tmux_profile': 'system',
    }
    assert load_theme_preference(env) == preference


def test_system_theme_detection_honors_explicit_override() -> None:
    assert detect_system_theme({'CCB_SYSTEM_THEME': 'dark'}) == 'dark'
    assert detect_system_theme({'CCB_SYSTEM_THEME': 'prefer-light'}) == 'light'


def test_saved_theme_wins_over_stale_tmux_environment(tmp_path) -> None:
    env = {
        'XDG_CONFIG_HOME': str(tmp_path / 'config'),
        'CCB_TMUX_THEME_PROFILE': 'light',
    }
    dark = resolve_theme_request('dark', environ=env)
    assert dark is not None
    save_theme_preference(dark, environ=env)

    assert tmux_theme_profile(env) == 'default'


def test_tmux_environment_remains_bootstrap_fallback_without_saved_theme(tmp_path) -> None:
    env = {
        'XDG_CONFIG_HOME': str(tmp_path / 'missing-config'),
        'CCB_TMUX_THEME_PROFILE': 'light',
    }

    assert tmux_theme_profile(env) == 'light'
