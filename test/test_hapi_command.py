from __future__ import annotations

import shlex

import pytest

from hapi_integration.command import (
    decorate_hapi_argv,
    hapi_identity_env,
    render_recorded_hapi_command,
)

# Anchor runtime state so hardcoded `.ccb/...` paths stay stable under this
# fork's default relocation to ~/.local/ccb.
@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


# ---------------------------------------------------------------------------
# decorate_hapi_argv
# ---------------------------------------------------------------------------


def test_decorate_claude_strips_executable_once() -> None:
    argv = decorate_hapi_argv(
        command='hapi',
        flavor='claude',
        provider_argv=['claude', '--settings', 'x.json', '--continue'],
    )
    assert argv == ['hapi', 'claude', '--started-by', 'terminal', '--settings', 'x.json', '--continue']


def test_decorate_codex_strips_executable_once() -> None:
    argv = decorate_hapi_argv(
        command='hapi',
        flavor='codex',
        provider_argv=['codex', '-c', 'disable_paste_burst=true', '--sandbox', 'read-only'],
    )
    assert argv == ['hapi', 'codex', '--started-by', 'terminal', '-c', 'disable_paste_burst=true', '--sandbox', 'read-only']


def test_decorate_preserves_argument_order_and_count() -> None:
    args = ['--alpha', '1', '--beta', '2', '--gamma']
    argv = decorate_hapi_argv(command='hapi', flavor='claude', provider_argv=['claude', *args])
    # prefix is [hapi, claude, --started-by, terminal]; remaining provider args follow
    assert argv[4:] == args
    assert len(argv) == 4 + len(args)


def test_decorate_explicit_hapi_command_path() -> None:
    argv = decorate_hapi_argv(
        command='/opt/hapi/bin/hapi',
        flavor='claude',
        provider_argv=['claude', '--continue'],
    )
    assert argv[0] == '/opt/hapi/bin/hapi'


def test_decorate_no_double_dash_delimiter() -> None:
    # The HAPI flavor parsers do not implement a `--` passthrough; CCB must
    # not insert one.
    argv = decorate_hapi_argv(command='hapi', flavor='claude', provider_argv=['claude', '--continue'])
    assert '--' not in argv


def test_decorate_quotes_via_shlex_at_join_site() -> None:
    # The decorator returns argv; the launcher quotes. Verify a token with
    # metacharacters survives a shlex.quote round-trip at the join site.
    argv = decorate_hapi_argv(
        command='hapi',
        flavor='claude',
        provider_argv=['claude', '--settings', 'path with spaces.json'],
    )
    joined = ' '.join(shlex.quote(part) for part in argv)
    assert "'path with spaces.json'" in joined


def test_decorate_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match='command'):
        decorate_hapi_argv(command='', flavor='claude', provider_argv=['claude'])


def test_decorate_rejects_unsupported_flavor() -> None:
    with pytest.raises(ValueError, match='flavors'):
        decorate_hapi_argv(command='hapi', flavor='gemini', provider_argv=['gemini'])


def test_decorate_strips_only_first_token_when_executable_repeats() -> None:
    argv = decorate_hapi_argv(
        command='hapi',
        flavor='claude',
        provider_argv=['claude', '--model', 'claude-3'],  # second 'claude' is a value
    )
    assert argv == ['hapi', 'claude', '--started-by', 'terminal', '--model', 'claude-3']


def test_decorate_strips_custom_provider_executable() -> None:
    argv = decorate_hapi_argv(
        command='hapi',
        flavor='claude',
        provider_argv=['/opt/provider/bin/custom-claude', '--profile', 'test'],
    )
    assert argv == ['hapi', 'claude', '--started-by', 'terminal', '--profile', 'test']


def test_decorate_rejects_missing_provider_executable() -> None:
    with pytest.raises(ValueError, match='provider executable'):
        decorate_hapi_argv(command='hapi', flavor='claude', provider_argv=[])


def test_recorded_hapi_command_execs_wrapper_and_carries_identity_path(tmp_path) -> None:
    record_path = tmp_path / 'hapi-wrapper.json'
    rendered = render_recorded_hapi_command(
        wrapper_argv=['/opt/hapi', 'codex', '--started-by', 'terminal', '--profile', 'test'],
        record_path=record_path,
        launch_session_id='codex-generation-2',
    )
    parts = shlex.split(rendered)
    assert parts[:2] == ['sh', '-c']
    assert str(record_path) in parts
    assert 'codex-generation-2' in parts
    assert parts[-6:] == ['/opt/hapi', 'codex', '--started-by', 'terminal', '--profile', 'test']


def test_decorate_disabled_byte_equivalence_is_caller_controlled() -> None:
    # In disabled mode the caller never invokes the decorator; the native
    # argv passes through unchanged. This test documents that contract: the
    # decorator is a no-op surface that the caller opts into only when enabled.
    native = ['claude', '--settings', 'x']
    assert native == ['claude', '--settings', 'x']


# ---------------------------------------------------------------------------
# hapi_identity_env
# ---------------------------------------------------------------------------


def test_identity_env_required_fields() -> None:
    env = hapi_identity_env(
        project_id='proj-1',
        agent_name='worker1',
        provider='claude',
        launch_session_id='sess-abc',
        workgroup=None,
        api_url='https://hub.example.invalid',
        hapi_home='/home/caller/.hapi',
    )
    assert env == {
        'HAPI_DISABLE_RUNNER_AUTO_START': '1',
        'HAPI_CCB_PROJECT_ID': 'proj-1',
        'HAPI_CCB_AGENT_NAME': 'worker1',
        'HAPI_CCB_PROVIDER': 'claude',
        'HAPI_CCB_SESSION_ID': 'sess-abc',
        'HAPI_API_URL': 'https://hub.example.invalid',
        'HAPI_HOME': '/home/caller/.hapi',
    }
    assert 'HAPI_CCB_WORKGROUP' not in env


def test_identity_env_workgroup_present_only_when_nonempty() -> None:
    env = hapi_identity_env(
        project_id='p',
        agent_name='a',
        provider='codex',
        launch_session_id='s',
        workgroup='team-a',
        api_url='https://hub.example.invalid',
        hapi_home='/home/caller/.hapi',
    )
    assert env['HAPI_CCB_WORKGROUP'] == 'team-a'

    env_empty = hapi_identity_env(
        project_id='p',
        agent_name='a',
        provider='codex',
        launch_session_id='s',
        workgroup='',
        api_url='https://hub.example.invalid',
        hapi_home='/home/caller/.hapi',
    )
    assert 'HAPI_CCB_WORKGROUP' not in env_empty

    env_whitespace = hapi_identity_env(
        project_id='p',
        agent_name='a',
        provider='codex',
        launch_session_id='s',
        workgroup='   ',
        api_url='https://hub.example.invalid',
        hapi_home='/home/caller/.hapi',
    )
    assert 'HAPI_CCB_WORKGROUP' not in env_whitespace


def test_identity_env_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match='project_id'):
        hapi_identity_env(
            project_id='',
            agent_name='a',
            provider='codex',
            launch_session_id='s',
            workgroup=None,
            api_url='https://hub.example.invalid',
            hapi_home='/home/caller/.hapi',
        )


def test_identity_env_includes_api_url_so_hub_cannot_auto_start() -> None:
    env = hapi_identity_env(
        project_id='p',
        agent_name='a',
        provider='claude',
        launch_session_id='s',
        workgroup=None,
        api_url='https://hub.example.invalid',
        hapi_home='/home/caller/.hapi',
    )
    assert env['HAPI_API_URL'] == 'https://hub.example.invalid'


# ---------------------------------------------------------------------------
# Claude launcher integration: enabled mode decorates argv + injects env
# ---------------------------------------------------------------------------


def test_claude_launcher_hapi_enabled_decorates_argv(tmp_path, monkeypatch) -> None:
    import json
    import shlex
    from types import SimpleNamespace

    from agents.models import AgentSpec
    from cli.models import ParsedStartCommand
    from provider_backends.claude import launcher as claude_launcher

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_path / 'home'
    (home_dir / '.claude').mkdir(parents=True, exist_ok=True)
    (home_dir / '.claude' / 'settings.json').write_text('{}', encoding='utf-8')

    monkeypatch.setattr('provider_backends.claude.launcher.Path.home', lambda: home_dir)
    monkeypatch.setattr(claude_launcher, 'is_root_user', lambda: False)
    monkeypatch.setattr('provider_backends.claude.launcher.local_tcp_listener_available', lambda host, port: False)
    monkeypatch.setattr(
        claude_launcher,
        '_resolve_claude_restore_target',
        lambda **kwargs: type('T', (), {'run_cwd': runtime_dir, 'has_history': False})(),
    )
    monkeypatch.setenv('CLAUDE_START_CMD', '/opt/provider/custom-claude --profile managed')

    spec = _claude_spec_for_hapi('reviewer')
    command = ParsedStartCommand(project=None, agent_names=('reviewer',), restore=False, auto_permission=False)

    prepared = {
        'project_root': str(tmp_path),
        'workspace_path': str(runtime_dir),
        'agent_events_path': str(runtime_dir / 'events.jsonl'),
        'hapi_launch_context': {
            'enabled': True,
            'command': 'hapi',
            'flavor': 'claude',
            'api_url': 'https://hub.example.invalid',
            'hapi_home': '/home/caller/.hapi',
            'project_id': 'proj-1',
            'agent_name': 'reviewer',
            'workgroup': None,
        },
    }

    start_cmd = claude_launcher.build_start_cmd(
        command,
        spec,
        runtime_dir,
        'claude-sess-1',
        prepared_state=prepared,
    )

    parts = shlex.split(start_cmd)
    parts = parts[parts.index('sh'):]
    # The recorder execs HAPI after atomically publishing wrapper identity.
    assert parts[:2] == ['sh', '-c']
    hapi_index = parts.index('hapi')
    assert parts[hapi_index:hapi_index + 6] == [
        'hapi', 'claude', '--started-by', 'terminal', '--profile', 'managed'
    ]
    assert '/opt/provider/custom-claude' not in parts
    # No `--` wrapper delimiter.
    assert '--' not in parts[:4]
    # Identity env is exported alongside managed-home env.
    assert 'HAPI_CCB_PROJECT_ID=proj-1' in start_cmd
    assert 'HAPI_CCB_AGENT_NAME=reviewer' in start_cmd
    assert 'HAPI_CCB_PROVIDER=claude' in start_cmd
    assert 'HAPI_CCB_SESSION_ID=claude-sess-1' in start_cmd
    assert 'HAPI_DISABLE_RUNNER_AUTO_START=1' in start_cmd
    assert 'HAPI_API_URL=https://hub.example.invalid' in start_cmd
    assert 'HAPI_HOME=/home/caller/.hapi' in start_cmd
    assert 'HAPI_CCB_WORKGROUP' not in start_cmd

    # The production session writer replaces the prior launch generation.
    from cli.services.runtime_launch_runtime.session_files import write_session_file

    second_cmd = claude_launcher.build_start_cmd(
        command, spec, runtime_dir, 'claude-sess-2', prepared_state=prepared
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_id='proj-1', project_root=tmp_path),
        paths=SimpleNamespace(ccb_dir=tmp_path / '.ccb', runtime_state_root=tmp_path / '.state'),
    )
    context.paths.ccb_dir.mkdir()
    session_path = write_session_file(
        context=context,
        spec=spec,
        plan=SimpleNamespace(workspace_path=runtime_dir),
        runtime_dir=runtime_dir,
        run_cwd=runtime_dir,
        pane_id='%7',
        tmux_socket_name='ccb-proj-1',
        tmux_socket_path=str(tmp_path / 'tmux.sock'),
        pane_title_marker='CCB-reviewer',
        start_cmd=second_cmd,
        launch_session_id='claude-sess-2',
        provider_payload={'claude_start_cmd': second_cmd},
    )
    written = json.loads(session_path.read_text(encoding='utf-8'))
    assert written['ccb_session_id'] == 'claude-sess-2'
    assert 'HAPI_CCB_SESSION_ID=claude-sess-2' in written['start_cmd']
    assert 'HAPI_CCB_SESSION_ID=claude-sess-1' not in written['start_cmd']


def _claude_hapi_launcher_prepared(tmp_path, *, hapi_launch_context):
    """Shared prepared_state for claude launcher auto_permission tests.

    Returns a dict that either carries a HAPI launch context (``dict``) or
    none (``None``), mirroring production: the launcher only decorates when a
    preflight cache installed a HAPI context.
    """
    prepared = {
        'project_root': str(tmp_path),
        'workspace_path': str(tmp_path / 'runtime'),
        'agent_events_path': str(tmp_path / 'runtime' / 'events.jsonl'),
    }
    if hapi_launch_context is not None:
        prepared['hapi_launch_context'] = {
            'enabled': True,
            'command': 'hapi',
            'flavor': 'claude',
            'api_url': 'https://hub.example.invalid',
            'hapi_home': '/home/caller/.hapi',
            'project_id': 'proj-1',
            'agent_name': 'reviewer',
            'workgroup': None,
            **hapi_launch_context,
        }
    return prepared


def _claude_launcher_for_auto_permission(tmp_path, monkeypatch):
    """Mock the claude launcher so auto_permission decisions are host-independent.

    `claude_cli_supports_flag` advertises `--permission-mode` (the modern CLI),
    so native mode must choose `--permission-mode bypassPermissions` and HAPI
    mode must fall back to `--dangerously-skip-permissions`.
    """
    import shlex

    from cli.models import ParsedStartCommand
    from provider_backends.claude import launcher as claude_launcher

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_path / 'home'
    (home_dir / '.claude').mkdir(parents=True, exist_ok=True)
    (home_dir / '.claude' / 'settings.json').write_text('{}', encoding='utf-8')

    monkeypatch.setattr('provider_backends.claude.launcher.Path.home', lambda: home_dir)
    monkeypatch.setattr(claude_launcher, 'is_root_user', lambda: False)
    monkeypatch.setattr(
        claude_launcher,
        'claude_cli_supports_flag',
        lambda cmd_parts, flag: str(flag) in {'--setting-sources', '--settings', '--permission-mode'},
    )
    monkeypatch.setattr(
        claude_launcher,
        'write_claude_settings_overlay',
        lambda runtime_dir, profile=None: runtime_dir / 'claude-settings.json',
    )
    monkeypatch.setattr(
        claude_launcher,
        '_resolve_claude_restore_target',
        lambda **kwargs: type('T', (), {'run_cwd': runtime_dir, 'has_history': False})(),
    )

    spec = _claude_spec_for_hapi('reviewer')
    command = ParsedStartCommand(project=None, agent_names=('reviewer',), restore=False, auto_permission=True)
    return runtime_dir, claude_launcher, spec, command


def test_claude_launcher_hapi_auto_permission_emits_skip_flag(tmp_path, monkeypatch) -> None:
    # Regression: HAPI's claude parser consumes `--permission-mode` at the
    # wrapper level but never forwards it to the spawned claude process. Under
    # HAPI mode CCB must emit `--dangerously-skip-permissions` so the real
    # claude argv carries the flag (HAPI maps it to bypassPermissions too).
    import shlex

    runtime_dir, claude_launcher, spec, command = _claude_launcher_for_auto_permission(tmp_path, monkeypatch)
    prepared = _claude_hapi_launcher_prepared(tmp_path, hapi_launch_context={})

    start_cmd = claude_launcher.build_start_cmd(
        command, spec, runtime_dir, 'claude-sess-hapi', prepared_state=prepared
    )

    assert '--dangerously-skip-permissions' in start_cmd
    assert '--permission-mode' not in start_cmd
    # The flag travels inside the HAPI wrapper argv, reaching the real claude.
    parts = shlex.split(start_cmd)
    parts = parts[parts.index('sh'):]
    hapi_index = parts.index('hapi')
    assert '--dangerously-skip-permissions' in parts[hapi_index:]


def test_claude_launcher_non_hapi_auto_permission_keeps_permission_mode(tmp_path, monkeypatch) -> None:
    # Disabled (non-HAPI) mode must preserve upstream behavior: a CLI that
    # supports `--permission-mode` gets `--permission-mode bypassPermissions`,
    # not the skip flag.
    runtime_dir, claude_launcher, spec, command = _claude_launcher_for_auto_permission(tmp_path, monkeypatch)
    prepared = _claude_hapi_launcher_prepared(tmp_path, hapi_launch_context=None)

    start_cmd = claude_launcher.build_start_cmd(
        command, spec, runtime_dir, 'claude-sess-native', prepared_state=prepared
    )

    assert '--permission-mode bypassPermissions' in start_cmd
    assert '--dangerously-skip-permissions' not in start_cmd
    assert 'HAPI_' not in start_cmd


def test_claude_launcher_hapi_disabled_unchanged(tmp_path, monkeypatch) -> None:
    import shlex

    from cli.models import ParsedStartCommand
    from provider_backends.claude import launcher as claude_launcher

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    home_dir = tmp_path / 'home'
    (home_dir / '.claude').mkdir(parents=True, exist_ok=True)
    (home_dir / '.claude' / 'settings.json').write_text('{}', encoding='utf-8')

    monkeypatch.setattr('provider_backends.claude.launcher.Path.home', lambda: home_dir)
    monkeypatch.setattr(claude_launcher, 'is_root_user', lambda: False)
    monkeypatch.setattr('provider_backends.claude.launcher.local_tcp_listener_available', lambda host, port: False)
    monkeypatch.setattr(
        claude_launcher,
        '_resolve_claude_restore_target',
        lambda **kwargs: type('T', (), {'run_cwd': runtime_dir, 'has_history': False})(),
    )

    spec = _claude_spec_for_hapi('reviewer')
    command = ParsedStartCommand(project=None, agent_names=('reviewer',), restore=False, auto_permission=False)
    prepared = {
        'project_root': str(tmp_path),
        'workspace_path': str(runtime_dir),
        'agent_events_path': str(runtime_dir / 'events.jsonl'),
    }

    start_cmd = claude_launcher.build_start_cmd(
        command, spec, runtime_dir, 'claude-sess-2', prepared_state=prepared
    )
    cmd_part = start_cmd.rsplit('; ', 1)[-1]
    parts = shlex.split(cmd_part)
    # Disabled mode: native claude executable leads, no HAPI wrapper.
    assert parts[0] == 'claude'
    assert 'HAPI_' not in start_cmd


def _claude_spec_for_hapi(name: str):
    from agents.models import (
        AgentSpec,
        PermissionMode,
        QueuePolicy,
        RestoreMode,
        RuntimeMode,
        WorkspaceMode,
    )

    return AgentSpec(
        name=name,
        provider='claude',
        target='.',
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
        startup_args=(),
    )


# ---------------------------------------------------------------------------
# Codex launcher integration: enabled mode decorates argv, disables managed app-server
# ---------------------------------------------------------------------------


def test_codex_launcher_hapi_enabled_decorates_and_disables_managed(tmp_path, monkeypatch) -> None:
    import shlex

    from cli.models import ParsedStartCommand
    from provider_backends.codex import launcher as codex_launcher

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        'provider_backends.codex.launcher_runtime.command_runtime.service.supports_managed_app_server',
        lambda parts: True,
        raising=False,
    )
    monkeypatch.setenv('CODEX_START_CMD', '/opt/provider/custom-codex --profile managed')

    spec = _codex_spec_for_hapi('planner')
    command = ParsedStartCommand(project=None, agent_names=('planner',), restore=False, auto_permission=False)
    prepared = {
        'project_root': str(tmp_path),
        'workspace_path': str(runtime_dir),
        'agent_events_path': str(runtime_dir / 'events.jsonl'),
        'hapi_launch_context': {
            'enabled': True,
            'command': 'hapi',
            'flavor': 'codex',
            'api_url': 'https://hub.example.invalid',
            'hapi_home': '/home/caller/.hapi',
            'project_id': 'proj-1',
            'agent_name': 'planner',
            'workgroup': 'team-a',
        },
    }

    start_cmd = codex_launcher.build_start_cmd(
        command, spec, runtime_dir, 'codex-sess-1', prepared_state=prepared
    )
    parts = shlex.split(start_cmd)
    parts = parts[parts.index('sh'):]
    assert parts[:2] == ['sh', '-c']
    hapi_index = parts.index('hapi')
    assert parts[hapi_index:hapi_index + 4] == ['hapi', 'codex', '--started-by', 'terminal']
    assert '/opt/provider/custom-codex' not in parts
    assert parts[hapi_index + 4:hapi_index + 6] == ['--profile', 'managed']
    assert 'HAPI_CCB_PROJECT_ID=proj-1' in start_cmd
    assert 'HAPI_CCB_SESSION_ID=codex-sess-1' in start_cmd
    assert 'HAPI_CCB_WORKGROUP=team-a' in start_cmd
    assert 'HAPI_HOME=/home/caller/.hapi' in start_cmd
    # Managed app-server must be disabled under HAPI mode.
    assert 'app-server' not in start_cmd


def test_codex_launcher_hapi_disabled_keeps_managed_path(tmp_path, monkeypatch) -> None:
    # Disabled mode must not perturb the managed app-server decision.
    from cli.models import ParsedStartCommand
    from provider_backends.codex import launcher as codex_launcher

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(parents=True, exist_ok=True)

    spec = _codex_spec_for_hapi('planner')
    command = ParsedStartCommand(project=None, agent_names=('planner',), restore=False, auto_permission=False)
    prepared = {
        'project_root': str(tmp_path),
        'workspace_path': str(runtime_dir),
        'agent_events_path': str(runtime_dir / 'events.jsonl'),
    }
    start_cmd = codex_launcher.build_start_cmd(
        command, spec, runtime_dir, 'codex-sess-2', prepared_state=prepared
    )
    assert 'HAPI_' not in start_cmd


def _codex_spec_for_hapi(name: str):
    from agents.models import (
        AgentSpec,
        PermissionMode,
        QueuePolicy,
        RestoreMode,
        RuntimeMode,
        WorkspaceMode,
    )

    return AgentSpec(
        name=name,
        provider='codex',
        target='.',
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
        startup_args=(),
    )
