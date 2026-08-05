from __future__ import annotations

import json

from provider_backends.claude.launcher_runtime.env import build_claude_env_prefix, claude_user_base_url, write_claude_settings_overlay
from provider_profiles.models import ResolvedProviderProfile


def test_build_claude_env_prefix_unsets_dead_local_base_url_from_env() -> None:
    result = build_claude_env_prefix(
        env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:12345"},
        should_drop_base_url_fn=lambda value: value.endswith(":12345"),
        claude_user_base_url_fn=lambda: "",
    )

    assert result == "unset ANTHROPIC_BASE_URL"


def test_build_claude_env_prefix_uses_settings_base_url_when_inheritable() -> None:
    result = build_claude_env_prefix(
        env={},
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: "https://api.example.test",
    )

    assert result == "export ANTHROPIC_BASE_URL=https://api.example.test"


def test_build_claude_env_prefix_prefers_settings_base_url_over_ambient_env() -> None:
    result = build_claude_env_prefix(
        env={"ANTHROPIC_BASE_URL": "https://old-shell.example.test"},
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: "https://ccswitch.example.test",
    )

    assert result == "export ANTHROPIC_BASE_URL=https://ccswitch.example.test"


def test_build_claude_env_prefix_preserves_auth_token_credential_kind() -> None:
    common = {
        "should_drop_base_url_fn": lambda value: False,
        "claude_user_base_url_fn": lambda: "",
    }

    explicit = build_claude_env_prefix(
        extra_env={"ANTHROPIC_AUTH_TOKEN": "explicit-token"},
        **common,
    )
    ambient = build_claude_env_prefix(
        env={"ANTHROPIC_AUTH_TOKEN": "ambient-token"},
        **common,
    )
    settings = build_claude_env_prefix(
        claude_user_api_env_fn=lambda: {"ANTHROPIC_AUTH_TOKEN": "settings-token"},
        **common,
    )

    assert explicit == (
        "unset ANTHROPIC_API_KEY; unset ANTHROPIC_AUTH_TOKEN; "
        "export ANTHROPIC_AUTH_TOKEN=explicit-token"
    )
    assert ambient == "export ANTHROPIC_AUTH_TOKEN=ambient-token"
    assert settings == "export ANTHROPIC_AUTH_TOKEN=settings-token"


def test_build_claude_env_prefix_unsets_competing_ambient_aliases_for_explicit_config() -> None:
    profile = ResolvedProviderProfile(
        provider='claude',
        agent_name='agent1',
        env={
            'ANTHROPIC_API_KEY': 'explicit-key',
            'ANTHROPIC_BASE_URL': 'https://explicit.example.test',
        },
    )

    result = build_claude_env_prefix(
        profile=profile,
        env={
            'ANTHROPIC_AUTH_TOKEN': 'ambient-token',
            'ANTHROPIC_BASE_URL': 'https://ambient.example.test',
        },
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: '',
    )

    assert 'unset ANTHROPIC_API_KEY' in result
    assert 'unset ANTHROPIC_AUTH_TOKEN' in result
    assert 'unset ANTHROPIC_BASE_URL' in result
    assert 'ANTHROPIC_API_KEY=explicit-key' in result
    assert 'ANTHROPIC_BASE_URL=https://explicit.example.test' in result
    assert 'ambient-token' not in result
    assert 'ambient.example.test' not in result


def test_write_claude_settings_overlay_returns_none_without_agent_settings(tmp_path) -> None:
    assert write_claude_settings_overlay(tmp_path, profile=None) is None


def test_write_claude_settings_overlay_strips_env_section_from_agent_settings(tmp_path) -> None:
    profile_root = tmp_path / "profile"
    settings_path = profile_root / "settings.json"
    profile_root.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:12345"},
                "theme": "light",
            }
        ),
        encoding="utf-8",
    )

    overlay = write_claude_settings_overlay(
        tmp_path,
        profile=ResolvedProviderProfile(
            provider='claude',
            agent_name='agent1',
            mode='inherit',
            profile_root=str(profile_root),
        ),
    )

    assert overlay is not None
    payload = json.loads(overlay.read_text(encoding="utf-8"))
    assert payload == {"theme": "light"}
    assert claude_user_base_url(user_settings_path=settings_path) == "http://127.0.0.1:12345"


def test_build_claude_env_prefix_passes_through_non_api_agent_env() -> None:
    result = build_claude_env_prefix(
        extra_env={"GH_CONFIG_DIR": "/home/user/.config/gh", "ANTHROPIC_API_KEY": "sk-test"},
        env={},
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: "",
    )

    assert "export GH_CONFIG_DIR=/home/user/.config/gh" in result
    assert "export ANTHROPIC_API_KEY=sk-test" in result


def test_build_claude_env_prefix_emits_passthrough_before_api_env() -> None:
    result = build_claude_env_prefix(
        extra_env={"HTTPS_PROXY": "http://proxy.example.test:3128", "ANTHROPIC_API_KEY": "sk-test"},
        env={},
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: "",
    )

    assert result.index("export HTTPS_PROXY") < result.index("export ANTHROPIC_API_KEY")


def test_build_claude_env_prefix_without_agent_env_is_unchanged() -> None:
    result = build_claude_env_prefix(
        env={},
        should_drop_base_url_fn=lambda value: False,
        claude_user_base_url_fn=lambda: "",
    )

    assert result == ""
