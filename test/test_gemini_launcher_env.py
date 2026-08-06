from __future__ import annotations

import json
import shlex

from agents.models import PermissionMode, QueuePolicy, RestoreMode, RuntimeMode, WorkspaceMode
from cli.models import ParsedStartCommand
from provider_backends.gemini import launcher as gemini_launcher
from provider_backends.gemini.launcher_runtime.env import build_gemini_env_prefix
from provider_backends.gemini.launcher_runtime.home import (
    prepare_gemini_home_overrides,
    resolve_gemini_home_layout,
)
from provider_profiles import ResolvedProviderProfile
from agents.models import AgentSpec


def test_build_gemini_env_prefix_clears_non_inherited_api_and_exports_filtered_keys() -> None:
    profile = ResolvedProviderProfile(
        provider="gemini",
        agent_name="agent1",
        env={
            "GEMINI_API_KEY": "profile-key",
            "GEMINI_MODEL": "gemini-3.1-pro-preview",
            "GOOGLE_GEMINI_BASE_URL": "https://chatapi.onechats.ai",
            "OTHER_ENV": "ignored",
        },
        inherit_api=False,
    )

    prefix = build_gemini_env_prefix(
        profile=profile,
        extra_env={"GOOGLE_API_KEY": "extra-key", "UNRELATED": "ignored"},
    )

    assert "unset GEMINI_API_KEY" in prefix
    assert "unset GEMINI_MODEL" in prefix
    assert "unset GOOGLE_API_KEY" in prefix
    assert "unset GOOGLE_GEMINI_BASE_URL" in prefix
    assert "OTHER_ENV" not in prefix
    assert "UNRELATED" not in prefix
    assert (
        "export GEMINI_API_KEY=profile-key GEMINI_MODEL=gemini-3.1-pro-preview "
        "GOOGLE_API_KEY=extra-key GOOGLE_GEMINI_BASE_URL=https://chatapi.onechats.ai"
    ) in prefix


def test_build_gemini_env_prefix_clears_only_explicitly_owned_alias_groups() -> None:
    profile = ResolvedProviderProfile(
        provider='gemini',
        agent_name='agent1',
        env={
            'GOOGLE_API_KEY': 'explicit-key',
            'GOOGLE_GEMINI_BASE_URL': 'https://explicit.example.test',
            'GOOGLE_CLOUD_PROJECT': 'explicit-project',
        },
        inherit_api=True,
    )

    prefix = build_gemini_env_prefix(profile=profile)

    for key in (
        'GEMINI_API_KEY',
        'GOOGLE_API_KEY',
        'GOOGLE_APPLICATION_CREDENTIALS',
        'GOOGLE_API_BASE',
        'GOOGLE_GEMINI_BASE_URL',
        'GOOGLE_VERTEX_BASE_URL',
        'GOOGLE_CLOUD_PROJECT',
    ):
        assert f'unset {key}' in prefix
    assert 'unset GEMINI_MODEL' not in prefix
    assert 'unset GOOGLE_CLOUD_LOCATION' not in prefix
    assert (
        'export GOOGLE_API_KEY=explicit-key '
        'GOOGLE_CLOUD_PROJECT=explicit-project '
        'GOOGLE_GEMINI_BASE_URL=https://explicit.example.test'
    ) in prefix


def _spec(name: str = 'agent1') -> AgentSpec:
    return AgentSpec(
        name=name,
        provider='gemini',
        target='.',
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
    )


def _prepared(runtime_dir) -> dict[str, object]:
    return {'project_root': runtime_dir}


def test_gemini_launcher_build_start_cmd_exports_managed_home(tmp_path) -> None:
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    spec = _spec()
    command = ParsedStartCommand(project=None, agent_names=('agent1',), restore=False, auto_permission=False)

    start_cmd = gemini_launcher.build_start_cmd(
        command,
        spec,
        runtime_dir,
        'gemini-sess-home',
        prepared_state=_prepared(runtime_dir),
    )

    expected_home = runtime_dir / 'gemini-home'
    expected_root = expected_home / '.gemini' / 'tmp'
    assert f'HOME={shlex.quote(str(expected_home))}' in start_cmd
    assert f'GEMINI_CLI_HOME={shlex.quote(str(expected_home))}' in start_cmd
    assert f'GEMINI_ROOT={shlex.quote(str(expected_root))}' in start_cmd


def test_gemini_launcher_build_start_cmd_uses_agent_provider_state_home_for_managed_runtime(tmp_path) -> None:
    runtime_dir = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'gemini'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    spec = _spec()
    command = ParsedStartCommand(project=None, agent_names=('agent1',), restore=False, auto_permission=False)

    start_cmd = gemini_launcher.build_start_cmd(
        command,
        spec,
        runtime_dir,
        'gemini-sess-home',
        prepared_state=_prepared(runtime_dir),
    )

    expected_home = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'gemini' / 'home'
    expected_root = expected_home / '.gemini' / 'tmp'
    assert f'HOME={shlex.quote(str(expected_home))}' in start_cmd
    assert f'GEMINI_CLI_HOME={shlex.quote(str(expected_home))}' in start_cmd
    assert f'GEMINI_ROOT={shlex.quote(str(expected_root))}' in start_cmd


def test_prepare_gemini_home_overrides_keeps_cli_home_aligned_with_projected_state(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'gemini'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))

    env = prepare_gemini_home_overrides(runtime_dir, None)

    expected_home = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'gemini' / 'home'
    expected_cache = tmp_path / 'xdg-cache' / 'ccb' / 'provider-cache' / 'gemini'
    assert env['HOME'] == str(expected_home)
    assert env['GEMINI_CLI_HOME'] == str(expected_home)
    assert env['GEMINI_ROOT'] == str(expected_home / '.gemini' / 'tmp')
    assert env['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env['npm_config_cache'] == str(expected_cache / 'npm')
    assert env['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')
    assert env['GEMINI_FORCE_FILE_STORAGE'] == 'true'
    assert env['GEMINI_FORCE_ENCRYPTED_FILE_STORAGE'] == 'true'
    assert (expected_cache / 'npm').is_dir()
    assert (expected_cache / 'xdg').is_dir()
    assert (expected_home / '.gemini' / 'settings.json').is_file()
    assert not (expected_home / '.gemini' / '.gemini' / 'settings.json').exists()


def test_prepare_gemini_home_overrides_pins_windows_home_under_wsl(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / 'runtime'
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    monkeypatch.setenv('WSLENV', 'EXISTING/u')

    env = prepare_gemini_home_overrides(runtime_dir, None, refresh_home=False)

    assert env['USERPROFILE'] == env['HOME']
    wslenv = env['WSLENV'].split(':')
    for name in (
        'HOME/p',
        'USERPROFILE/p',
        'GEMINI_CLI_HOME/p',
        'GEMINI_ROOT/p',
        'NPM_CONFIG_CACHE/p',
        'npm_config_cache/p',
        'XDG_CACHE_HOME/p',
        'GEMINI_FORCE_FILE_STORAGE',
        'GEMINI_FORCE_ENCRYPTED_FILE_STORAGE',
    ):
        assert name in wslenv
    assert wslenv[-1] == 'EXISTING/u'


def test_prepare_gemini_home_overrides_uses_user_cache_without_project_context(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))

    env = prepare_gemini_home_overrides(runtime_dir, None, refresh_home=False)

    expected_cache = tmp_path / 'xdg-cache' / 'ccb' / 'provider-cache' / 'gemini'
    assert env['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env['npm_config_cache'] == str(expected_cache / 'npm')
    assert env['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')
    assert (expected_cache / 'npm').is_dir()
    assert (expected_cache / 'xdg').is_dir()
    assert not (tmp_path / 'xdg-cache' / 'ccb' / 'projects').exists()


def test_prepare_gemini_home_overrides_does_not_nest_managed_xdg_cache(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    expected_cache = tmp_path / 'xdg-cache' / 'ccb' / 'provider-cache' / 'gemini'
    monkeypatch.setenv('XDG_CACHE_HOME', str(expected_cache / 'xdg'))

    env = prepare_gemini_home_overrides(runtime_dir, None, refresh_home=False)

    assert env['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')
    assert not (expected_cache / 'xdg' / 'ccb').exists()


def test_prepare_gemini_home_overrides_migrates_legacy_managed_xdg_without_nesting(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cache_home = tmp_path / 'xdg-cache'
    legacy_cache = (
        cache_home
        / 'ccb'
        / 'projects'
        / '0123456789abcdef'
        / 'provider-cache'
        / 'gemini'
    )
    monkeypatch.setenv('XDG_CACHE_HOME', str(legacy_cache / 'xdg'))

    env = prepare_gemini_home_overrides(runtime_dir, None, refresh_home=False)

    expected_cache = cache_home / 'ccb' / 'provider-cache' / 'gemini'
    assert env['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')
    assert not (legacy_cache / 'xdg' / 'ccb').exists()


def test_prepare_gemini_home_overrides_shares_one_user_cache_across_projects(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))
    runtime_a = tmp_path / 'project-a' / '.ccb' / 'agents' / 'gemini' / 'provider-runtime' / 'gemini'
    runtime_b = tmp_path / 'project-b' / '.ccb' / 'agents' / 'gemini' / 'provider-runtime' / 'gemini'
    runtime_a.mkdir(parents=True, exist_ok=True)
    runtime_b.mkdir(parents=True, exist_ok=True)

    env_a = prepare_gemini_home_overrides(runtime_a, None, refresh_home=False)
    env_b = prepare_gemini_home_overrides(runtime_b, None, refresh_home=False)

    expected_cache = tmp_path / 'xdg-cache' / 'ccb' / 'provider-cache' / 'gemini'
    assert env_a['NPM_CONFIG_CACHE'] == env_b['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env_a['XDG_CACHE_HOME'] == env_b['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')


def test_prepare_gemini_home_overrides_uses_source_home_cache_from_managed_home(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    source_home = tmp_path / 'source-home'
    managed_home = tmp_path / '.ccb' / 'agents' / 'caller' / 'provider-state' / 'gemini' / 'home'
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    monkeypatch.setenv('HOME', str(managed_home))
    monkeypatch.setenv('CCB_SOURCE_HOME', str(source_home))

    env = prepare_gemini_home_overrides(runtime_dir, None, refresh_home=False)

    expected_cache = source_home / '.cache' / 'ccb' / 'provider-cache' / 'gemini'
    assert env['NPM_CONFIG_CACHE'] == str(expected_cache / 'npm')
    assert env['XDG_CACHE_HOME'] == str(expected_cache / 'xdg')


def test_resolve_gemini_home_layout_rejects_non_managed_persisted_home(tmp_path) -> None:
    runtime_dir = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'gemini'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    session_file = tmp_path / '.ccb' / '.gemini-agent1-session'
    legacy_home = tmp_path / 'legacy-global-home'
    session_file.write_text(
        json.dumps(
            {
                'gemini_home': str(legacy_home),
                'gemini_root': str(legacy_home / '.gemini' / 'tmp'),
            }
        )
        + '\n',
        encoding='utf-8',
    )

    layout = resolve_gemini_home_layout(runtime_dir, None)

    expected_home = tmp_path / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'gemini' / 'home'
    assert layout.home_root == expected_home
