from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_backends.codex.launcher_runtime.command_runtime.home import (
    _ensure_session_namespace_authority,
)
from provider_backends.codex.launcher_runtime.session_paths import (
    load_linked_continuation_session_id,
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


def test_api_key_change_links_session_and_keeps_native_history_visible(tmp_path: Path) -> None:
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
                'ccb_session_id': 'ccb-launch-a',
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
    assert session_log.is_file()
    assert not (codex_home / 'archived-sessions').exists()
    rewritten = json.loads(session_file.read_text(encoding='utf-8'))
    assert 'codex_session_id' not in rewritten
    assert 'resume session-a' not in rewritten['start_cmd']
    assert rewritten['codex_provider_authority_fingerprint'] == fingerprint_b
    assert rewritten['ccb_conversation_id'] == 'ccb-launch-a'
    assert rewritten['ccb_authority_generation'] == 2
    assert rewritten['ccb_continuity_status'] == 'continued_on_new_authority'
    assert rewritten['ccb_resume_compatibility'] == 'linked_continuation'
    assert rewritten['old_codex_session_id'] == 'session-a'
    assert rewritten['old_codex_session_path'] == str(session_log)
    assert rewritten['ccb_session_history'] == [
        {
            'provider': 'codex',
            'authority_generation': 1,
            'continuity_status': 'historical',
            'conversation_id': 'ccb-launch-a',
            'provider_session_id': 'session-a',
            'provider_session_path': str(session_log),
        }
    ]
    assert load_linked_continuation_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        current_fingerprint=fingerprint_b,
    ) == 'session-a'


def test_unrelated_source_config_change_does_not_rotate_codex_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / 'repo-config' / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    source_home = tmp_path / 'source-codex-config'
    runtime_dir.mkdir(parents=True)
    source_home.mkdir(parents=True)
    monkeypatch.setenv('CODEX_HOME', str(source_home))
    config = source_home / 'config.toml'
    config.write_text(
        '\n'.join(
            (
                'model = "gpt-a"',
                'model_provider = "custom"',
                '[model_providers.custom]',
                'base_url = "https://route-a.example.test/v1"',
                'wire_api = "responses"',
                '[mcp_servers.demo]',
                'command = "demo-a"',
            )
        )
        + '\n',
        encoding='utf-8',
    )
    first = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)

    config.write_text(
        config.read_text(encoding='utf-8')
        .replace('model = "gpt-a"', 'model = "gpt-b"')
        .replace('command = "demo-a"', 'command = "demo-b"'),
        encoding='utf-8',
    )
    unrelated = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)
    config.write_text(
        config.read_text(encoding='utf-8').replace(
            'https://route-a.example.test/v1',
            'https://route-b.example.test/v1',
        ),
        encoding='utf-8',
    )
    changed_route = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)

    assert unrelated == first
    assert changed_route != first


def test_referenced_codex_auth_sidecar_change_rotates_authority(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = tmp_path / 'repo-sidecar' / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    source_home = tmp_path / 'source-codex-sidecar'
    runtime_dir.mkdir(parents=True)
    source_home.mkdir(parents=True)
    monkeypatch.setenv('CODEX_HOME', str(source_home))
    (source_home / 'config.toml').write_text(
        'token_file = "$CODEX_HOME/company-extra-token"\n',
        encoding='utf-8',
    )
    sidecar = source_home / 'company-extra-token'
    sidecar.write_text('token-a\n', encoding='utf-8')
    first = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)
    sidecar.write_text('token-b\n', encoding='utf-8')
    second = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)

    assert second != first


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


def test_explicit_codex_api_ignores_unselected_managed_auth(monkeypatch, tmp_path: Path) -> None:
    runtime_dir = tmp_path / 'repo-explicit-auth' / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    runtime_dir.mkdir(parents=True)
    managed_home = runtime_dir.parent.parent / 'provider-state' / 'codex' / 'home'
    managed_home.mkdir(parents=True)
    sidecar = managed_home / 'company-codex-api-key'
    sidecar.write_text('managed-a\n', encoding='utf-8')
    profile = _profile(managed_home, api_key='explicit-key')

    fingerprint_a = current_provider_authority_fingerprint(profile, runtime_dir=runtime_dir)
    sidecar.write_text('managed-b\n', encoding='utf-8')
    fingerprint_b = current_provider_authority_fingerprint(profile, runtime_dir=runtime_dir)

    assert fingerprint_a == fingerprint_b


def test_canonical_legacy_session_without_fingerprint_is_adopted(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-canonical-legacy'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    session_log = session_root / '2026/08/04/rollout-legacy.jsonl'
    runtime_dir.mkdir(parents=True)
    session_log.parent.mkdir(parents=True)
    session_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'codex_session_id': 'legacy-session',
                'codex_session_path': str(session_log),
                'start_cmd': 'codex resume legacy-session',
                'codex_start_cmd': 'codex resume legacy-session',
            }
        ),
        encoding='utf-8',
    )

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=None)

    current = current_provider_authority_fingerprint(None, runtime_dir=runtime_dir)
    adopted = json.loads(session_file.read_text(encoding='utf-8'))
    assert session_log.is_file()
    assert not (codex_home / 'archived-sessions').exists()
    assert adopted['codex_provider_authority_fingerprint'] == current
    assert adopted['codex_session_authority_fingerprint'] == current
    assert load_resume_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        current_fingerprint=current,
    ) == 'legacy-session'


def test_v855_global_archive_is_restored_with_legacy_binding(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-recovery'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)
    profile = _profile(codex_home, api_key='key-a')

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)
    current = current_provider_authority_fingerprint(profile, runtime_dir=runtime_dir)
    relative_log = Path('2026/08/04/rollout-legacy-session.jsonl')
    archived_log = codex_home / 'archived-sessions' / '20260805-085803-global' / relative_log
    archived_log.parent.mkdir(parents=True)
    archived_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    old_log = session_root / relative_log
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'old_codex_session_id': 'legacy-session',
                'old_codex_session_path': str(old_log),
                'codex_provider_authority_fingerprint': current,
                'start_cmd': 'codex',
                'codex_start_cmd': 'codex',
            }
        ),
        encoding='utf-8',
    )

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)

    assert old_log.is_file()
    assert not archived_log.exists()
    restored = json.loads(session_file.read_text(encoding='utf-8'))
    assert restored['codex_session_id'] == 'legacy-session'
    assert restored['codex_session_path'] == str(old_log)
    assert restored['codex_session_authority_fingerprint'] == current
    assert load_resume_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        profile,
        current_fingerprint=current,
    ) == 'legacy-session'


def test_v855_archive_merge_preserves_a_new_current_binding(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-current-binding'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)
    profile = _profile(codex_home, api_key='key-a')

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)
    current = current_provider_authority_fingerprint(profile, runtime_dir=runtime_dir)
    old_relative = Path('2026/08/04/rollout-old.jsonl')
    old_log = session_root / old_relative
    archived_log = codex_home / 'archived-sessions' / '20260805-085803-global' / old_relative
    archived_log.parent.mkdir(parents=True)
    archived_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    current_log = session_root / '2026/08/05/rollout-current.jsonl'
    current_log.parent.mkdir(parents=True)
    current_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'codex_session_id': 'current-session',
                'codex_session_path': str(current_log),
                'old_codex_session_id': 'old-session',
                'old_codex_session_path': str(old_log),
                'codex_provider_authority_fingerprint': current,
                'codex_session_authority_fingerprint': current,
            }
        ),
        encoding='utf-8',
    )

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)

    assert old_log.is_file()
    restored = json.loads(session_file.read_text(encoding='utf-8'))
    assert restored['codex_session_id'] == 'current-session'
    assert restored['codex_session_path'] == str(current_log)


def test_nonlegacy_authority_archive_is_not_restored(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-nonlegacy-archive'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)
    profile = _profile(codex_home, api_key='key-a')

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)
    current = current_provider_authority_fingerprint(profile, runtime_dir=runtime_dir)
    relative_log = Path('2026/08/04/rollout-other-authority.jsonl')
    old_log = session_root / relative_log
    archived_log = codex_home / 'archived-sessions' / '20260805-085803-other-authority' / relative_log
    archived_log.parent.mkdir(parents=True)
    archived_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'old_codex_session_id': 'other-session',
                'old_codex_session_path': str(old_log),
                'codex_provider_authority_fingerprint': current,
            }
        ),
        encoding='utf-8',
    )

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile)

    assert archived_log.is_file()
    assert not old_log.exists()
    unchanged = json.loads(session_file.read_text(encoding='utf-8'))
    assert 'codex_session_id' not in unchanged


def test_v855_archive_remains_resume_visible_after_authority_change(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-recovery-after-change'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)
    profile_a = _profile(codex_home, api_key='key-a')
    profile_b = _profile(codex_home, api_key='key-b')

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile_a)
    fingerprint_a = current_provider_authority_fingerprint(profile_a, runtime_dir=runtime_dir)
    relative_log = Path('2026/08/04/rollout-v855-hidden.jsonl')
    restored_log = session_root / relative_log
    archived_log = codex_home / 'archived-sessions' / '20260805-085803-global' / relative_log
    archived_log.parent.mkdir(parents=True)
    archived_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'ccb_session_id': 'ccb-launch-a',
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'old_codex_session_id': 'v855-hidden-session',
                'old_codex_session_path': str(restored_log),
                'codex_provider_authority_fingerprint': fingerprint_a,
            }
        ),
        encoding='utf-8',
    )

    fingerprint_b = current_provider_authority_fingerprint(profile_b, runtime_dir=runtime_dir)
    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile_b)

    assert restored_log.is_file()
    assert not archived_log.exists()
    restored = json.loads(session_file.read_text(encoding='utf-8'))
    assert restored['codex_provider_authority_fingerprint'] == fingerprint_b
    assert restored['ccb_conversation_id'] == 'ccb-launch-a'
    assert restored['ccb_authority_generation'] == 2
    assert restored['ccb_resume_compatibility'] == 'linked_continuation'
    assert 'codex_session_id' not in restored
    assert restored['ccb_session_history'][0]['provider_session_id'] == 'v855-hidden-session'
    assert restored['ccb_session_history'][0]['provider_session_path'] == str(restored_log)


def test_authority_change_does_not_record_codex_path_outside_session_root(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo-outside-binding'
    runtime_dir = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    codex_home = project_root / '.ccb' / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home'
    session_root = codex_home / 'sessions'
    runtime_dir.mkdir(parents=True)
    session_root.mkdir(parents=True)
    outside_log = tmp_path / 'outside.jsonl'
    outside_log.write_text('{"type":"session_meta"}\n', encoding='utf-8')
    profile_a = _profile(codex_home, api_key='key-a')
    profile_b = _profile(codex_home, api_key='key-b')
    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile_a)
    fingerprint_a = current_provider_authority_fingerprint(profile_a, runtime_dir=runtime_dir)
    session_file = project_root / '.ccb' / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'ccb_session_id': 'ccb-launch-a',
                'codex_home': str(codex_home),
                'codex_session_root': str(session_root),
                'codex_session_id': 'outside-session',
                'codex_session_path': str(outside_log),
                'codex_provider_authority_fingerprint': fingerprint_a,
                'codex_session_authority_fingerprint': fingerprint_a,
            }
        ),
        encoding='utf-8',
    )

    _ensure_session_namespace_authority(runtime_dir, codex_home, session_root, profile=profile_b)

    rewritten = json.loads(session_file.read_text(encoding='utf-8'))
    assert outside_log.is_file()
    assert rewritten['ccb_session_history'][0]['provider_session_id'] == 'outside-session'
    assert 'provider_session_path' not in rewritten['ccb_session_history'][0]
    assert 'old_codex_session_path' not in rewritten
