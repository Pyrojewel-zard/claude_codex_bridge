from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cli.services.agent_history_cleanup import cleanup_agent_history, scan_agent_history
from storage.paths import PathLayout

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _write_at(path: Path, *, age_days: int, text: str = 'history') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    modified = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (modified, modified))
    return path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def test_history_cleanup_supports_any_agent_and_preserves_recent_current_and_latest(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo')

    codex_home = layout.agent_provider_state_dir('agent1', 'codex') / 'home'
    codex_old = _write_at(codex_home / 'sessions/2026/05/01/rollout-old.jsonl', age_days=80)
    codex_current = _write_at(codex_home / 'sessions/2026/04/01/rollout-current-session.jsonl', age_days=100)
    codex_recent = _write_at(codex_home / 'sessions/2026/07/30/rollout-recent.jsonl', age_days=3)
    _write_json(
        layout.ccb_dir / '.codex-agent1-session',
        {
            'agent_name': 'agent1',
            'codex_session_id': 'current-session',
            'codex_session_path': str(codex_current),
            'old_codex_session_path': str(codex_old),
        },
    )

    claude_home = layout.agent_provider_state_dir('agent2', 'claude') / 'home'
    claude_old = _write_at(claude_home / '.claude/projects/demo/old.jsonl', age_days=75)
    claude_current = _write_at(claude_home / '.claude/projects/demo/current-claude.jsonl', age_days=60)
    _write_json(
        layout.ccb_dir / '.claude-agent2-session',
        {
            'agent_name': 'agent2',
            'claude_session_id': 'current-claude',
            'claude_session_path': str(claude_current),
        },
    )
    _write_json(
        layout.agents_dir / 'agent2' / 'runtime.json',
        {'desired_state': 'mounted', 'pane_state': 'alive', 'state': 'idle'},
    )

    gemini_home = layout.agent_provider_state_dir('agent3', 'gemini') / 'home'
    gemini_older = _write_at(gemini_home / '.gemini/tmp/hash/chats/session-older.json', age_days=120)
    gemini_latest = _write_at(gemini_home / '.gemini/tmp/hash/chats/session-latest.json', age_days=70)

    scan = scan_agent_history(layout, retention_days=30, now=NOW)

    assert scan['candidate_count'] == 3, scan
    assert {row['agent'] for row in scan['agents']} == {'agent1', 'agent2', 'agent3'}
    rows = {row['agent']: row for row in scan['agents']}
    assert rows['agent1']['candidate_count'] == 1
    assert rows['agent1']['recent_count'] == 1
    assert rows['agent1']['protected_count'] == 1
    assert rows['agent2']['status'] == 'mounted'
    assert rows['agent2']['candidate_count'] == 1
    assert rows['agent3']['candidate_count'] == 1
    assert rows['agent3']['protected_count'] == 1

    selected = cleanup_agent_history(layout, retention_days=30, agent='agent1', now=NOW)

    assert selected['deleted_count'] == 1
    assert not codex_old.exists()
    assert codex_current.exists()
    assert codex_recent.exists()
    assert claude_old.exists()
    assert gemini_older.exists()

    remaining = cleanup_agent_history(layout, retention_days=30, now=NOW)

    assert remaining['deleted_count'] == 2
    assert not claude_old.exists()
    assert claude_current.exists()
    assert not gemini_older.exists()
    assert gemini_latest.exists()
    assert remaining['scan']['candidate_count'] == 0


def test_history_cleanup_recognizes_supported_provider_transcript_shapes(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo-shapes')
    roots = {
        'droid': layout.agent_provider_state_dir('droid1', 'droid') / 'home/.factory/sessions/demo',
        'kimi': layout.agent_provider_state_dir('kimi1', 'kimi') / 'home/.kimi/share/sessions/hash',
        'grok': layout.agent_provider_state_dir('grok1', 'grok') / 'home/.grok/sessions/demo',
        'deepseek': layout.agent_provider_state_dir('deep1', 'deepseek') / 'home/.deepcode/projects/demo',
        'agy': layout.agent_provider_state_dir('agy1', 'agy') / 'home/.cache/antigravity-cli/brain/demo/.system_generated/logs',
    }
    paths = {
        'droid': _write_at(roots['droid'] / 'old.jsonl', age_days=80),
        'kimi': _write_at(roots['kimi'] / 'session-old/wire.jsonl', age_days=80),
        'grok': _write_at(roots['grok'] / 'session-old/updates.jsonl', age_days=80),
        'deepseek': _write_at(roots['deepseek'] / 'old.jsonl', age_days=80),
        'agy': _write_at(roots['agy'] / 'transcript-old.jsonl', age_days=80),
    }
    _write_at(roots['droid'] / 'latest.jsonl', age_days=40)
    _write_at(roots['kimi'] / 'session-latest/wire.jsonl', age_days=40)
    _write_at(roots['grok'] / 'session-latest/updates.jsonl', age_days=40)
    _write_at(roots['deepseek'] / 'latest.jsonl', age_days=40)
    _write_at(roots['agy'] / 'transcript-latest.jsonl', age_days=40)

    scan = scan_agent_history(layout, retention_days=30, now=NOW)

    assert scan['candidate_count'] == len(paths)
    assert {row['providers'][0] for row in scan['agents']} == set(paths)

    result = cleanup_agent_history(layout, retention_days=30, now=NOW)

    assert result['deleted_count'] == len(paths)
    assert all(not path.exists() for path in paths.values())


def test_history_cleanup_ignores_unrecognized_state_and_symlinks(tmp_path: Path) -> None:
    layout = PathLayout(tmp_path / 'repo-unsafe')
    opencode = _write_at(
        layout.agent_provider_state_dir('agent1', 'opencode') / 'home/data/session-old.jsonl',
        age_days=120,
    )
    outside = _write_at(tmp_path / 'outside-rollout.jsonl', age_days=120)
    codex_link = layout.agent_provider_state_dir('agent2', 'codex') / 'home/sessions/2026/01/01/rollout-link.jsonl'
    codex_link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, codex_link)

    scan = scan_agent_history(layout, retention_days=30, now=NOW)
    result = cleanup_agent_history(layout, retention_days=30, now=NOW)

    assert scan['candidate_count'] == 0
    assert result['deleted_count'] == 0
    assert opencode.exists()
    assert codex_link.is_symlink()
    assert outside.exists()


@pytest.mark.parametrize('value', [0, 1, 14, 365, True, 'bad'])
def test_history_cleanup_rejects_unsupported_retention(value: object, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='7, 30, 90'):
        scan_agent_history(PathLayout(tmp_path / 'repo'), retention_days=value, now=NOW)
