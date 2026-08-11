from __future__ import annotations

import json
from pathlib import Path

import provider_control.session_usage as session_usage_module
from provider_control import read_provider_runtime_snapshot


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')


def test_codex_runtime_snapshot_uses_latest_turn_and_cumulative_usage(tmp_path: Path) -> None:
    path = tmp_path / 'rollout.jsonl'
    _write(
        path,
        [
            {'type': 'session_meta', 'payload': {'id': 'session-1'}},
            {'type': 'turn_context', 'payload': {'model': 'gpt-5.6-sol', 'effort': 'high'}},
            {
                'type': 'event_msg',
                'payload': {
                    'type': 'token_count',
                    'info': {
                        'model_context_window': 258400,
                        'total_token_usage': {
                            'input_tokens': 120,
                            'cached_input_tokens': 80,
                            'output_tokens': 30,
                            'reasoning_output_tokens': 10,
                            'total_tokens': 230,
                        },
                    },
                },
            },
        ],
    )

    snapshot = read_provider_runtime_snapshot('codex', path)

    assert snapshot.session_id == 'session-1'
    assert snapshot.active_model == 'gpt-5.6-sol'
    assert snapshot.active_thinking == 'high'
    assert snapshot.usage is not None
    assert snapshot.usage.total_tokens == 230
    assert snapshot.usage.context_window_max_tokens == 258400


def test_claude_runtime_snapshot_deduplicates_streamed_message_usage(tmp_path: Path) -> None:
    path = tmp_path / 'claude.jsonl'
    repeated = {
        'type': 'assistant',
        'uuid': 'message-1',
        'message': {
            'id': 'msg-1',
            'model': 'claude-sonnet-5',
            'usage': {
                'input_tokens': 10,
                'cache_read_input_tokens': 20,
                'cache_creation_input_tokens': 5,
                'output_tokens': 7,
            },
        },
    }
    _write(path, [repeated, repeated])

    snapshot = read_provider_runtime_snapshot('claude', path, fallback_session_id='fallback')

    assert snapshot.session_id == 'fallback'
    assert snapshot.active_model == 'claude-sonnet-5'
    assert snapshot.usage is not None
    assert snapshot.usage.input_tokens == 10
    assert snapshot.usage.cached_input_tokens == 25
    assert snapshot.usage.output_tokens == 7
    assert snapshot.usage.total_tokens == 42


def test_claude_runtime_snapshot_discovers_current_project_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo'
    projects_root = tmp_path / 'claude-projects'
    transcript = projects_root / 'current-session.jsonl'
    _write(
        transcript,
        [
            {
                'type': 'assistant',
                'sessionId': 'claude-session-real',
                'message': {
                    'id': 'message-real',
                    'model': 'Kimi-K3',
                    'usage': {
                        'input_tokens': 20831,
                        'cache_read_input_tokens': 0,
                        'cache_creation_input_tokens': 0,
                        'output_tokens': 541,
                    },
                },
            }
        ],
    )
    binding = project_root / '.ccb' / '.claude-mobile-session'
    binding.parent.mkdir(parents=True)
    binding.write_text(
        json.dumps(
            {
                'claude_projects_root': str(projects_root),
                'work_dir': str(project_root),
            }
        ),
        encoding='utf-8',
    )

    import provider_backends.claude.comm as claude_comm

    class _Reader:
        def __init__(self, *, root, work_dir, use_sessions_index):
            assert root == projects_root
            assert work_dir == project_root
            assert use_sessions_index is False

        def current_session_path(self):
            return transcript

    monkeypatch.setattr(claude_comm, 'ClaudeLogReader', _Reader)

    snapshot = read_provider_runtime_snapshot(
        'claude',
        None,
        project_root=project_root,
        agent='mobile',
    )

    assert snapshot.session_id == 'claude-session-real'
    assert snapshot.active_model == 'Kimi-K3'
    assert snapshot.usage is not None
    assert snapshot.usage.total_tokens == 21372


def test_unknown_provider_keeps_unknown_runtime_truthful(tmp_path: Path) -> None:
    snapshot = read_provider_runtime_snapshot('kimi', tmp_path / 'missing.jsonl')

    assert snapshot.provider == 'kimi'
    assert snapshot.source == 'unavailable'
    assert snapshot.active_model is None
    assert snapshot.usage is None


def test_runtime_snapshot_cache_is_bounded_by_transcript_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / 'cached-rollout.jsonl'
    _write(path, [{'type': 'turn_context', 'payload': {'model': 'gpt-5.5'}}])
    original = session_usage_module._read_tail_entries
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(session_usage_module, '_read_tail_entries', counted)

    first = read_provider_runtime_snapshot('codex', path)
    second = read_provider_runtime_snapshot('codex', path)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(
            json.dumps(
                {'type': 'turn_context', 'payload': {'model': 'gpt-5.6-sol'}},
            )
            + '\n'
        )
    changed = read_provider_runtime_snapshot('codex', path)

    assert first is second
    assert calls == 2
    assert changed.active_model == 'gpt-5.6-sol'
