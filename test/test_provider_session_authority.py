from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from provider_backends.claude.launcher_runtime.restore import project_session_restore_target
from provider_backends.gemini.launcher_runtime.restore import resolve_gemini_restore_target
from provider_backends.session_authority import (
    current_provider_authority_fingerprint,
    provider_authority_matches,
    remember_bound_provider_session_authority,
    rebind_provider_session_data,
)


def _runtime_dir(tmp_path: Path, provider: str) -> Path:
    runtime_dir = (
        tmp_path
        / 'repo'
        / '.ccb'
        / 'agents'
        / 'reviewer'
        / 'provider-runtime'
        / provider
    )
    runtime_dir.mkdir(parents=True)
    return runtime_dir


def test_provider_authority_fingerprint_changes_without_persisting_api_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'claude')
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'provider-secret-a')

    fingerprint_a = current_provider_authority_fingerprint('claude', None, runtime_dir)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'provider-secret-b')
    fingerprint_b = current_provider_authority_fingerprint('claude', None, runtime_dir)

    key_path = (
        runtime_dir.parent.parent
        / 'provider-state'
        / 'claude'
        / '.ccb-authority-hmac-key'
    )
    assert fingerprint_a != fingerprint_b
    assert 'provider-secret-a' not in key_path.read_text(encoding='ascii')
    assert 'provider-secret-b' not in key_path.read_text(encoding='ascii')
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_keyring_owned_projection_changes_inherited_authority_fingerprint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'gemini')
    source_home = tmp_path / 'source-home-keyring'
    managed_home = runtime_dir.parent.parent / 'provider-state' / 'gemini' / 'home'
    managed_gemini = managed_home / '.gemini'
    managed_gemini.mkdir(parents=True)
    source_home.mkdir(parents=True)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(source_home))
    (managed_home / '.ccb-auth-projection.json').write_text(
        '{"schema_version":1,"record_type":"ccb_gemini_auth_projection",'
        '"projected_files":["oauth_creds.json"],"keyring_projected":true}\n',
        encoding='utf-8',
    )
    projected = managed_gemini / 'oauth_creds.json'
    projected.write_text('{"access_token":"one"}\n', encoding='utf-8')
    first = current_provider_authority_fingerprint('gemini', None, runtime_dir)
    projected.write_text('{"access_token":"two"}\n', encoding='utf-8')
    second = current_provider_authority_fingerprint('gemini', None, runtime_dir)

    assert second != first


def test_unmarked_managed_auth_does_not_override_external_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'gemini')
    source_home = tmp_path / 'source-home-unmarked'
    managed_auth = runtime_dir.parent.parent / 'provider-state' / 'gemini' / 'home' / '.gemini' / 'oauth_creds.json'
    managed_auth.parent.mkdir(parents=True)
    source_home.mkdir(parents=True)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(source_home))
    managed_auth.write_text('{"access_token":"private-a"}\n', encoding='utf-8')
    first = current_provider_authority_fingerprint('gemini', None, runtime_dir)
    managed_auth.write_text('{"access_token":"private-b"}\n', encoding='utf-8')
    second = current_provider_authority_fingerprint('gemini', None, runtime_dir)

    assert second == first


@pytest.mark.parametrize(
    ('provider', 'credential_key', 'auth_relative'),
    (
        ('claude', 'ANTHROPIC_API_KEY', '.claude/.credentials.json'),
        ('gemini', 'GEMINI_API_KEY', '.gemini/oauth_creds.json'),
    ),
)
def test_explicit_credential_fingerprint_ignores_unselected_managed_oauth(
    monkeypatch,
    tmp_path: Path,
    provider: str,
    credential_key: str,
    auth_relative: str,
) -> None:
    runtime_dir = _runtime_dir(tmp_path, provider)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    managed_home = runtime_dir.parent.parent / 'provider-state' / provider / 'home'
    auth_path = managed_home / auth_relative
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text('{"refresh_token":"managed-a"}\n', encoding='utf-8')
    profile = SimpleNamespace(
        provider=provider,
        agent_name='reviewer',
        mode='inherit',
        runtime_home=str(managed_home),
        env={credential_key: 'explicit-key'},
        inherit_api=True,
        inherit_auth=False,
        inherit_config=True,
    )

    fingerprint_a = current_provider_authority_fingerprint(provider, profile, runtime_dir)
    auth_path.write_text('{"refresh_token":"managed-b"}\n', encoding='utf-8')
    fingerprint_b = current_provider_authority_fingerprint(provider, profile, runtime_dir)

    assert fingerprint_a == fingerprint_b


@pytest.mark.parametrize(
    ('provider', 'auth_relative'),
    (
        ('claude', '.claude/.credentials.json'),
        ('gemini', '.gemini/oauth_creds.json'),
    ),
)
def test_agent_private_auth_change_updates_fingerprint_when_auth_is_not_inherited(
    monkeypatch,
    tmp_path: Path,
    provider: str,
    auth_relative: str,
) -> None:
    runtime_dir = _runtime_dir(tmp_path, provider)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    managed_home = runtime_dir.parent.parent / 'provider-state' / provider / 'home'
    auth_path = managed_home / auth_relative
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text('{"refresh_token":"managed-a"}\n', encoding='utf-8')
    profile = SimpleNamespace(
        provider=provider,
        agent_name='reviewer',
        mode='isolated',
        runtime_home=str(managed_home),
        env={},
        inherit_api=False,
        inherit_auth=False,
        inherit_config=True,
    )

    fingerprint_a = current_provider_authority_fingerprint(provider, profile, runtime_dir)
    auth_path.write_text('{"refresh_token":"managed-b"}\n', encoding='utf-8')
    fingerprint_b = current_provider_authority_fingerprint(provider, profile, runtime_dir)

    assert fingerprint_a != fingerprint_b


def test_explicit_gemini_route_ignores_competing_ambient_alias(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'gemini')
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    profile = SimpleNamespace(
        provider='gemini',
        agent_name='reviewer',
        mode='inherit',
        env={'GOOGLE_GEMINI_BASE_URL': 'https://explicit.example.test'},
        inherit_api=True,
        inherit_auth=True,
        inherit_config=True,
    )
    monkeypatch.setenv('GOOGLE_API_BASE', 'https://ambient-a.example.test')
    fingerprint_a = current_provider_authority_fingerprint('gemini', profile, runtime_dir)
    monkeypatch.setenv('GOOGLE_API_BASE', 'https://ambient-b.example.test')
    fingerprint_b = current_provider_authority_fingerprint('gemini', profile, runtime_dir)

    assert fingerprint_a == fingerprint_b


def test_claude_authority_change_blocks_continue_before_history_lookup(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    managed_home = tmp_path / 'managed-home'
    workspace.mkdir()
    session = SimpleNamespace(
        data={'claude_provider_authority_fingerprint': 'authority-a'},
        work_dir=str(workspace),
        claude_home_path=managed_home,
    )

    target = project_session_restore_target(
        workspace,
        'reviewer',
        load_project_session_fn=lambda *args, **kwargs: session,
        claude_history_state_fn=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError('mismatched authority must not inspect Claude history')
        ),
        managed_home=managed_home,
        authority_fingerprint='authority-b',
    )

    assert target is not None
    assert target.run_cwd == workspace
    assert target.has_history is False
    assert session.data['claude_provider_authority_fingerprint'] == 'authority-b'
    assert session.data['ccb_resume_compatibility'] == 'linked_continuation'

    second_target = project_session_restore_target(
        workspace,
        'reviewer',
        load_project_session_fn=lambda *args, **kwargs: session,
        claude_history_state_fn=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError('pending linked continuation must not resume old history')
        ),
        managed_home=managed_home,
        authority_fingerprint='authority-b',
    )
    assert second_target is not None
    assert second_target.has_history is False


def test_claude_authority_change_forks_managed_native_history(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    managed_home = tmp_path / 'managed-home'
    session_path = managed_home / '.claude' / 'projects' / 'workspace' / 'native-a.jsonl'
    workspace.mkdir()
    session_path.parent.mkdir(parents=True)
    session_path.write_text('{}\n', encoding='utf-8')
    session = SimpleNamespace(
        data={
            'claude_provider_authority_fingerprint': 'authority-a',
            'claude_session_id': 'native-a',
            'claude_session_path': str(session_path),
        },
        work_dir=str(workspace),
        claude_home_path=managed_home,
    )

    target = project_session_restore_target(
        workspace,
        'reviewer',
        load_project_session_fn=lambda *args, **kwargs: session,
        claude_history_state_fn=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError('mismatched authority must not inspect Claude history')
        ),
        managed_home=managed_home,
        authority_fingerprint='authority-b',
    )

    assert target is not None
    assert target.has_history is False
    assert target.continuation_mode == 'fork'
    assert target.continuation_session_id == 'native-a'
    assert session.data['old_claude_session_path'] == str(session_path)
    assert session_path.is_file()


def test_claude_legacy_session_without_fingerprint_continues_once(tmp_path: Path) -> None:
    workspace = tmp_path / 'workspace'
    managed_home = tmp_path / 'managed-home'
    workspace.mkdir()
    managed_home.mkdir()
    session = SimpleNamespace(
        data={},
        work_dir=str(workspace),
        claude_home_path=managed_home,
    )

    target = project_session_restore_target(
        workspace,
        'reviewer',
        load_project_session_fn=lambda *args, **kwargs: session,
        claude_history_state_fn=lambda **kwargs: ('legacy-session', True, workspace),
        managed_home=managed_home,
        authority_fingerprint='current-authority',
    )

    assert target is not None
    assert target.run_cwd == workspace
    assert target.has_history is True


def test_legacy_authority_compatibility_requires_explicit_opt_in() -> None:
    assert provider_authority_matches({}, 'gemini', 'current-authority') is False
    assert provider_authority_matches(
        {},
        'gemini',
        'current-authority',
        allow_legacy_missing=True,
    ) is True
    assert provider_authority_matches(
        {'gemini_provider_authority_fingerprint': 'old-authority'},
        'gemini',
        'current-authority',
        allow_legacy_missing=True,
    ) is False


def test_authority_rebind_preserves_stable_conversation_and_old_binding() -> None:
    data: dict[str, object] = {
        'ccb_session_id': 'ccb-launch-a',
        'claude_provider_authority_fingerprint': 'authority-a',
        'claude_session_id': 'native-a',
        'claude_session_path': '/managed/history/native-a.jsonl',
    }

    assert rebind_provider_session_data(
        data,
        'claude',
        'authority-b',
        native_resume_compatible=False,
    ) is True

    assert data['ccb_conversation_id'] == 'ccb-launch-a'
    assert data['ccb_authority_generation'] == 2
    assert data['ccb_continuity_status'] == 'continued_on_new_authority'
    assert data['ccb_resume_compatibility'] == 'linked_continuation'
    assert 'claude_session_id' not in data
    assert 'claude_session_path' not in data
    assert data['ccb_session_history'] == [
        {
            'provider': 'claude',
            'authority_generation': 1,
            'continuity_status': 'historical',
            'conversation_id': 'ccb-launch-a',
            'provider_session_id': 'native-a',
            'provider_session_path': '/managed/history/native-a.jsonl',
        }
    ]


def test_new_native_binding_completes_linked_authority_generation() -> None:
    data: dict[str, object] = {
        'ccb_session_id': 'ccb-launch-b',
        'ccb_conversation_id': 'conversation-a',
        'ccb_authority_generation': 2,
        'ccb_continuity_status': 'continued_on_new_authority',
        'ccb_resume_compatibility': 'linked_continuation',
        'ccb_continuation_launch_mode': 'import',
        'gemini_provider_authority_fingerprint': 'authority-b',
        'gemini_session_id': 'native-b',
        'gemini_session_path': '/managed/history/native-b.jsonl',
        'old_gemini_session_id': 'native-a',
    }

    assert remember_bound_provider_session_authority(data, 'gemini') is True
    assert data['ccb_conversation_id'] == 'conversation-a'
    assert data['ccb_authority_generation'] == 2
    assert data['gemini_session_authority_fingerprint'] == 'authority-b'
    assert data['ccb_resume_compatibility'] == 'native_fork_continuation'
    assert data['old_gemini_session_id'] == 'native-a'


def test_codex_fork_binding_completes_linked_authority_generation() -> None:
    data: dict[str, object] = {
        'ccb_session_id': 'ccb-launch-b',
        'ccb_conversation_id': 'conversation-a',
        'ccb_authority_generation': 2,
        'ccb_continuity_status': 'continued_on_new_authority',
        'ccb_resume_compatibility': 'linked_continuation',
        'ccb_continuation_launch_mode': 'fork',
        'codex_provider_authority_fingerprint': 'authority-b',
        'codex_session_id': 'native-b',
        'codex_session_path': '/managed/history/native-b.jsonl',
        'old_codex_session_id': 'native-a',
    }

    assert remember_bound_provider_session_authority(data, 'codex') is True
    assert data['ccb_conversation_id'] == 'conversation-a'
    assert data['ccb_authority_generation'] == 2
    assert data['codex_session_authority_fingerprint'] == 'authority-b'
    assert data['ccb_resume_compatibility'] == 'native_fork_continuation'
    assert data['old_codex_session_id'] == 'native-a'

    rebound = dict(data)
    assert remember_bound_provider_session_authority(rebound, 'codex') is False
    assert rebound == data


def test_codex_repeated_fork_binding_repairs_demoted_compatibility() -> None:
    data: dict[str, object] = {
        'ccb_continuity_schema_version': 1,
        'ccb_session_id': 'ccb-launch-b',
        'ccb_conversation_id': 'conversation-a',
        'ccb_authority_generation': 2,
        'ccb_continuity_status': 'continued_on_new_authority',
        'ccb_resume_compatibility': 'managed_local_history',
        'ccb_continuation_launch_mode': 'fork',
        'codex_provider_authority_fingerprint': 'authority-b',
        'codex_session_authority_fingerprint': 'authority-b',
        'codex_session_id': 'native-b',
        'codex_session_path': '/managed/history/native-b.jsonl',
        'old_codex_session_id': 'native-a',
    }

    assert remember_bound_provider_session_authority(data, 'codex') is True
    assert data['ccb_resume_compatibility'] == 'native_fork_continuation'
    assert data['ccb_continuity_status'] == 'continued_on_new_authority'


def test_new_native_binding_does_not_claim_unrequested_context_import() -> None:
    data: dict[str, object] = {
        'ccb_session_id': 'ccb-launch-b',
        'ccb_conversation_id': 'conversation-a',
        'ccb_authority_generation': 2,
        'ccb_continuity_status': 'continued_on_new_authority',
        'ccb_resume_compatibility': 'linked_continuation',
        'gemini_provider_authority_fingerprint': 'authority-b',
        'gemini_session_id': 'native-b',
    }

    assert remember_bound_provider_session_authority(data, 'gemini') is True
    assert data['gemini_session_authority_fingerprint'] == 'authority-b'
    assert data['ccb_resume_compatibility'] == 'linked_continuation'


def test_gemini_authority_change_blocks_resume_latest(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'gemini')
    workspace = tmp_path / 'repo' / '.ccb' / 'workspaces' / 'reviewer'
    workspace.mkdir(parents=True)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    monkeypatch.setenv('GEMINI_API_KEY', 'provider-secret-a')
    fingerprint_a = current_provider_authority_fingerprint('gemini', None, runtime_dir)
    monkeypatch.setenv('GEMINI_API_KEY', 'provider-secret-b')
    managed_root = (
        runtime_dir.parent.parent
        / 'provider-state'
        / 'gemini'
        / 'home'
        / '.gemini'
        / 'tmp'
    )
    old_session = managed_root / 'project-hash' / 'chats' / 'session-native-a.jsonl'
    old_session.parent.mkdir(parents=True)
    old_session.write_text('{}\n', encoding='utf-8')
    session = SimpleNamespace(
        data={
            'gemini_provider_authority_fingerprint': fingerprint_a,
            'gemini_session_id': 'native-a',
            'gemini_session_path': str(old_session),
            'gemini_root': str(managed_root),
        },
        work_dir=str(workspace),
    )

    target = resolve_gemini_restore_target(
        spec=SimpleNamespace(name='reviewer'),
        runtime_dir=runtime_dir,
        workspace_path=workspace,
        restore=True,
        load_project_session_fn=lambda *args, **kwargs: session,
        load_profile_fn=lambda runtime: None,
    )

    assert target.run_cwd == workspace
    assert target.has_history is False
    assert target.continuation_mode == 'import'
    assert target.continuation_session_path == old_session
    assert session.data['ccb_resume_compatibility'] == 'linked_continuation'
    assert session.data['ccb_session_history'][0]['provider_session_id'] == 'native-a'

    second_target = resolve_gemini_restore_target(
        spec=SimpleNamespace(name='reviewer'),
        runtime_dir=runtime_dir,
        workspace_path=workspace,
        restore=True,
        load_project_session_fn=lambda *args, **kwargs: session,
        load_profile_fn=lambda runtime: None,
    )
    assert second_target.run_cwd == workspace
    assert second_target.has_history is False
    assert second_target.continuation_mode == 'import'
    assert second_target.continuation_session_path == old_session
