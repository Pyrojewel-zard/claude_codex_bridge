from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.models import RestoreMode
from cli.services.runtime_launch_runtime.session_files import _merge_existing_session_binding
from provider_backends.claude.launcher_runtime.restore import project_session_restore_target
from provider_backends.claude.launcher_runtime.service import build_start_cmd
from provider_backends.claude.session import ClaudeProjectSession
from provider_backends.pane_log_support.lifecycle_common import classify_crash_reason
from provider_backends.runtime_restore import ProviderRestoreTarget
from provider_backends.session_authority import current_provider_authority_fingerprint


def _command(target, tmp_path, *, startup_args=(), restore=True, prepared=None):
    return build_start_cmd(
        SimpleNamespace(restore=restore, auto_permission=False),
        SimpleNamespace(name='reviewer', restore_default=RestoreMode.AUTO,
                        startup_args=startup_args, env={}, provider_command_template=None),
        tmp_path, 'launch-b',
        load_profile_fn=lambda *_: None,
        prepare_home_overrides_fn=lambda *a, **kw: {},
        write_settings_overlay_fn=lambda *a, **kw: None,
        build_env_prefix_fn=lambda **kw: '',
        resolve_restore_target_fn=lambda **kw: target if kw['restore'] else ProviderRestoreTarget(tmp_path, False),
        provider_start_parts_fn=lambda *_: ['claude'],
        cli_supports_flag_fn=lambda *a: False,
        is_root_user_fn=lambda: False,
        prepared_state=prepared,
    )


@pytest.mark.parametrize('change', ['key', 'route', 'account', 'expiry', 'whitespace'])
def test_auth_changes_restore_history_and_persist_continuity(monkeypatch, tmp_path, change):
    source = tmp_path / 'source'
    (source / '.claude').mkdir(parents=True)
    auth = source / '.claude' / '.credentials.json'
    auth.write_text('{"claudeAiOauth":{"accessToken":"fake-a","expiresAt":1}}')
    metadata = source / '.claude.json'
    metadata.write_text('{"oauthAccount":{"emailAddress":"a@example.invalid"}}')
    monkeypatch.setenv('CCB_SOURCE_HOME', str(source))
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
                 'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_OAUTH_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    runtime = tmp_path / 'repo' / '.ccb' / 'agents' / 'reviewer' / 'provider-runtime' / 'claude'
    runtime.mkdir(parents=True)
    old = current_provider_authority_fingerprint('claude', None, runtime)
    if change == 'key':
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-b')
    elif change == 'route':
        monkeypatch.setenv('ANTHROPIC_BASE_URL', 'http://127.0.0.1:12345')
    elif change == 'account':
        metadata.write_text('{"oauthAccount":{"emailAddress":"b@example.invalid"}}')
    elif change == 'expiry':
        auth.write_text('{"claudeAiOauth":{"accessToken":"fake-a","expiresAt":2}}')
    else:
        auth.write_text('{ "claudeAiOauth": {"accessToken":"fake-a", "expiresAt":1} }')
    before_source = (auth.read_bytes(), metadata.read_bytes())
    new = current_provider_authority_fingerprint('claude', None, runtime)
    assert old != new
    managed = tmp_path / 'managed'
    transcript = managed / '.claude' / 'projects' / 'workspace' / 'native-a.jsonl'
    transcript.parent.mkdir(parents=True)
    transcript.write_text('original history\n')
    session = ClaudeProjectSession(tmp_path / '.claude-session', {
        'work_dir': str(tmp_path), 'claude_home': str(managed),
        'claude_session_id': 'native-a', 'claude_session_path': str(transcript),
        'ccb_conversation_id': 'conversation-a', 'ccb_authority_generation': 1,
        'claude_provider_authority_fingerprint': old,
    })
    target = project_session_restore_target(
        tmp_path, 'reviewer', load_project_session_fn=lambda *a, **kw: session,
        claude_history_state_fn=lambda **kw: ('native-a', True, tmp_path),
        managed_home=managed, authority_fingerprint=new,
    )
    prepared = {}
    command = _command(target, tmp_path, prepared=prepared)
    assert command.endswith('claude --continue')
    assert '--fork-session' not in command
    persisted = json.loads(session.session_file.read_text())
    payload = {'claude_provider_authority_fingerprint': new, **prepared}
    _merge_existing_session_binding(payload, persisted, provider='claude')
    assert payload['claude_session_id'] == 'native-a'
    assert payload['ccb_conversation_id'] == 'conversation-a'
    assert payload['ccb_authority_generation'] == 2
    assert payload['ccb_resume_compatibility'] == 'managed_local_history'
    assert transcript.read_text() == 'original history\n'
    assert (auth.read_bytes(), metadata.read_bytes()) == before_source


def test_legacy_linked_pending_rechecks_current_home_without_resurrecting_old_binding(tmp_path):
    managed = tmp_path / 'managed'
    managed.mkdir()
    session = SimpleNamespace(data={
        'claude_provider_authority_fingerprint': 'current',
        'ccb_resume_compatibility': 'linked_continuation',
        'old_claude_session_id': 'old-cleared',
        'old_claude_session_path': '/foreign/old.jsonl',
    }, work_dir=str(tmp_path), claude_home_path=managed)
    target = project_session_restore_target(
        tmp_path, 'reviewer', load_project_session_fn=lambda *a, **kw: session,
        claude_history_state_fn=lambda **kw: ('new-local', True, tmp_path),
        managed_home=managed, authority_fingerprint='current',
    )
    assert target.has_history
    assert target.continuation_session_id is None
    assert 'claude_session_id' not in session.data
    assert session.data['ccb_resume_compatibility'] == 'managed_local_history'


@pytest.mark.parametrize('foreign', ['home', 'path', 'symlink'])
def test_authority_change_does_not_bypass_ownership(tmp_path, foreign):
    managed = tmp_path / 'managed'
    managed.mkdir()
    outsider = tmp_path / 'outsider'
    outsider.mkdir()
    outside_file = outsider / 'session.jsonl'
    outside_file.write_text('foreign')
    linked = managed / 'session.jsonl'
    linked.symlink_to(outside_file)
    session = SimpleNamespace(data={
        'claude_provider_authority_fingerprint': 'old',
        'claude_session_path': str(linked if foreign == 'symlink' else outside_file),
    }, work_dir=str(tmp_path), claude_home_path=outsider if foreign == 'home' else managed)
    target = project_session_restore_target(
        tmp_path, 'reviewer', load_project_session_fn=lambda *a, **kw: session,
        claude_history_state_fn=lambda **kw: ('native', True, tmp_path),
        managed_home=managed, authority_fingerprint='new',
    )
    assert not target.has_history
    assert outside_file.read_text() == 'foreign'


@pytest.mark.parametrize('args', [('--resume', 'chosen'), ('--resume=chosen',),
                                 ('--session-id', 'chosen'), ('--continue',), ('-r', 'chosen')])
def test_explicit_controls_do_not_receive_automatic_continue(tmp_path, args):
    prepared = {}
    cmd = _command(ProviderRestoreTarget(tmp_path, True), tmp_path,
                   startup_args=args, prepared=prepared)
    assert cmd.count('--continue') == (1 if args == ('--continue',) else 0)
    assert prepared['ccb_claude_auto_restore'] is False


def test_explicit_fresh_does_not_merge_old_native_binding(tmp_path):
    prepared = {}
    cmd = _command(ProviderRestoreTarget(tmp_path, True), tmp_path,
                   restore=False, prepared=prepared)
    assert '--continue' not in cmd
    payload = {'claude_provider_authority_fingerprint': 'same', **prepared}
    _merge_existing_session_binding(payload, {
        'claude_provider_authority_fingerprint': 'same',
        'claude_session_id': 'old', 'ccb_conversation_id': 'old-conversation',
    }, provider='claude')
    assert 'claude_session_id' not in payload
    assert 'ccb_conversation_id' not in payload


@pytest.mark.parametrize('error', ['HTTP 401 Unauthorized', 'HTTP 403 Forbidden',
                                  'HTTP 429 rate limited', 'Connection timed out',
                                  'Invalid signature in thinking block'])
def test_non_session_failures_never_clear_context(tmp_path, error):
    original = {'start_cmd': 'claude --continue', 'claude_session_id': 'keep'}
    session = ClaudeProjectSession(tmp_path / 'session', dict(original))
    reason = classify_crash_reason(error)
    assert reason != 'provider_session_missing'
    assert session.prepare_crash_recovery(reason) is None
    assert session.data == original
    assert not session.session_file.exists()


def test_missing_session_fallback_is_one_shot_preserves_evidence(tmp_path):
    transcript = tmp_path / 'native.jsonl'
    transcript.write_text('keep historical bytes')
    session = ClaudeProjectSession(tmp_path / 'session', {
        'start_cmd': 'claude --continue', 'claude_session_id': 'native',
        'claude_session_path': str(transcript), 'ccb_claude_auto_restore': True,
    })
    assert session.prepare_crash_recovery('provider_session_missing')[0]
    assert session.data['old_claude_session_path'] == str(transcript)
    assert session.data['ccb_claude_restore_fallback_reason'] == 'provider_session_missing'
    assert not session.prepare_crash_recovery('provider_session_missing')[0]
    assert transcript.read_text() == 'keep historical bytes'


def test_explicit_continue_is_not_removed_on_missing_session(tmp_path):
    original = {'start_cmd': 'claude --continue', 'ccb_claude_auto_restore': False}
    session = ClaudeProjectSession(tmp_path / 'session', dict(original))
    assert not session.prepare_crash_recovery('provider_session_missing')[0]
    assert session.data == original
