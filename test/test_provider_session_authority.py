from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

from provider_backends.claude.launcher_runtime.restore import project_session_restore_target
from provider_backends.gemini.launcher_runtime.restore import resolve_gemini_restore_target
from provider_backends.session_authority import current_provider_authority_fingerprint


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


def test_gemini_authority_change_blocks_resume_latest(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = _runtime_dir(tmp_path, 'gemini')
    workspace = tmp_path / 'repo' / '.ccb' / 'workspaces' / 'reviewer'
    workspace.mkdir(parents=True)
    monkeypatch.setenv('CCB_SOURCE_HOME', str(tmp_path / 'source-home'))
    monkeypatch.setenv('GEMINI_API_KEY', 'provider-secret-a')
    fingerprint_a = current_provider_authority_fingerprint('gemini', None, runtime_dir)
    monkeypatch.setenv('GEMINI_API_KEY', 'provider-secret-b')
    session = SimpleNamespace(
        data={'gemini_provider_authority_fingerprint': fingerprint_a},
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
