from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_backends.codex.launcher_runtime.command_runtime.home import (
    _ensure_session_namespace_authority,
)
from provider_backends.codex.launcher_runtime.session_paths import (
    load_resume_session_id,
)
from provider_backends.codex.session_authority import (
    current_provider_authority_fingerprint,
)
from provider_profiles.models import ResolvedProviderProfile


def _profile(home: Path, *, api_key: str) -> ResolvedProviderProfile:
    return ResolvedProviderProfile(
        provider='codex',
        agent_name='agent1',
        mode='isolated',
        profile_root=str(home),
        runtime_home=str(home),
        env={
            'OPENAI_API_KEY': api_key,
            'OPENAI_BASE_URL': 'https://api.example.test',
        },
        inherit_api=False,
        inherit_auth=False,
        inherit_config=False,
    )


def test_api_key_change_rotates_session_namespace_and_blocks_resume(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)

    profile_a = _profile(codex_home, api_key='key-a')
    _ensure_session_namespace_authority(
        runtime_dir,
        codex_home,
        session_root,
        profile=profile_a,
    )
    fingerprint_a = current_provider_authority_fingerprint(profile_a, runtime_dir=runtime_dir)
    session_log = session_root / '2026' / '08' / '04' / 'rollout-session-a.jsonl'
    session_log.parent.mkdir(parents=True)
    session_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'codex_session_id': 'session-a',
                'codex_session_path': str(session_log),
                'codex_provider_authority_fingerprint': fingerprint_a,
                'codex_session_authority_fingerprint': fingerprint_a,
                'start_cmd': 'codex resume session-a',
                'codex_start_cmd': 'codex resume session-a',
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        profile_a,
        current_fingerprint=fingerprint_a,
    ) == 'session-a'

    profile_b = _profile(codex_home, api_key='key-b')
    fingerprint_b = current_provider_authority_fingerprint(profile_b, runtime_dir=runtime_dir)
    assert fingerprint_b != fingerprint_a

    _ensure_session_namespace_authority(
        runtime_dir,
        codex_home,
        session_root,
        profile=profile_b,
    )

    assert load_resume_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        profile_b,
        current_fingerprint=fingerprint_b,
    ) is None
    assert not session_log.exists()
    assert any((codex_home / 'archived-sessions').rglob(session_log.name))
    rewritten = json.loads(session_file.read_text(encoding='utf-8'))
    assert 'codex_session_id' not in rewritten
    assert 'resume session-a' not in rewritten['start_cmd']


def test_inherited_source_login_change_changes_private_fingerprint(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = tmp_path / 'repo' / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    source_home = tmp_path / 'source-codex-home'
    runtime_dir.mkdir(parents=True)
    source_home.mkdir(parents=True)
    monkeypatch.setenv('CODEX_HOME', str(source_home))

    (source_home / 'auth.json').write_text('{"tokens":{"access_token":"token-a"}}\n', encoding='utf-8')
    fingerprint_a = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)
    (source_home / 'auth.json').write_text('{"tokens":{"access_token":"token-b"}}\n', encoding='utf-8')
    fingerprint_b = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)

    assert fingerprint_a != fingerprint_b
    key_path = runtime_dir.parent.parent / 'provider-state' / 'codex' / '.ccb-authority-hmac-key'
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert 'token-a' not in fingerprint_a
    assert 'token-b' not in fingerprint_b
