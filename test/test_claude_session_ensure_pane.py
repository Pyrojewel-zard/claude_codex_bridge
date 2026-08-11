from __future__ import annotations

from pathlib import Path

import pytest

from provider_backends.claude.session_runtime.model import ClaudeProjectSession
from provider_backends.pane_log_support import lifecycle


class _HerdrBackend:
    def __init__(self) -> None:
        self.is_alive_calls: list[object] = []
        self.ensure_log_calls: list[object] = []
        self.respawn_calls: list[object] = []

    def is_alive(self, pane) -> bool:
        self.is_alive_calls.append(pane)
        return True

    def ensure_pane_log(self, pane) -> None:
        self.ensure_log_calls.append(pane)

    def respawn_pane(self, *args, **kwargs) -> None:
        self.respawn_calls.append((args, kwargs))
        raise AssertionError('Claude Herdr ensure_pane must not use tmux rebound respawn')


def test_claude_herdr_ensure_pane_uses_backend_neutral_pane_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane_ref = {
        'backend_impl': 'herdr',
        'pane_id': 'pane-claude-1',
        'session_name': 'ccb-demo',
        'window_name': 'main',
        'agent_slug': 'claude1',
    }
    backend = _HerdrBackend()
    session = ClaudeProjectSession(
        session_file=tmp_path / '.claude-session',
        data={
            'ccb_session_id': 'ccb-claude1-1',
            'agent_name': 'claude1',
            'terminal': 'mux',
            'backend_impl': 'herdr',
            'pane_id': 'pane-claude-1',
            'pane_ref': pane_ref,
            'runtime_dir': str(tmp_path),
            'work_dir': str(tmp_path),
            'active': True,
        },
    )
    session.backend = lambda: backend  # type: ignore[method-assign]

    def _fail_tmux_ownership(*args, **kwargs):
        raise AssertionError('Claude Herdr ensure_pane must not inspect tmux ownership')

    monkeypatch.setattr(lifecycle, 'inspect_tmux_pane_ownership', _fail_tmux_ownership)

    ok, pane = session.ensure_pane()

    assert (ok, pane) == (True, 'pane-claude-1')
    assert backend.is_alive_calls == [pane_ref]
    assert backend.ensure_log_calls == [pane_ref]
    assert backend.respawn_calls == []
