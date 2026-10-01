from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_backends.pane_log_support.lifecycle_common import (
    MAX_PANE_CRASH_LOGS,
    classify_crash_reason,
    persist_crash_log,
)
from provider_backends.pane_log_support.lifecycle_recovery import respawn_existing_pane
from provider_backends.codex.session import CodexProjectSession

# Real captured text from a codex pane whose isolated OAuth refresh token was
# revoked after a token rotation (the crash that surfaces to the user as a
# generic "stale" pane).
_REVOKED_CRASH = (
    "• Ran sqlite3 -json ingest/index.db ...\n"
    "■ Your access token could not be refreshed because your refresh token was "
    "revoked. Please log out and sign in again.\n"
)

_LINEAGE_CRASH = (
    "Error: Failed to resume session from rollout.jsonl: "
    "thread/resume failed during TUI bootstrap: "
    "invalid paginated history lineage for sid-source: missing source rollout\n"
)


def test_classify_detects_revoked_refresh_token() -> None:
    assert classify_crash_reason(_REVOKED_CRASH) == 'provider_auth_revoked'


def test_classify_is_case_insensitive() -> None:
    assert classify_crash_reason('REFRESH TOKEN WAS REVOKED') == 'provider_auth_revoked'


def test_classify_ignores_ordinary_crash_and_empty() -> None:
    assert classify_crash_reason('') is None
    assert classify_crash_reason(None) is None  # type: ignore[arg-type]
    assert classify_crash_reason('Traceback: KeyError foo\nExit code 1\n') is None
    # A transient network 401 without a re-auth instruction must NOT be classified
    # as revoked auth, so recovery still restarts the pane.
    assert classify_crash_reason('HTTP 401 Unauthorized on /v1/models') is None


def test_classify_detects_missing_session_and_provider_helper() -> None:
    assert classify_crash_reason('No conversation found to continue') == 'provider_session_missing'
    assert (
        classify_crash_reason('Error: failed to connect to remote app server')
        == 'provider_helper_unavailable'
    )


def test_classify_detects_codex_paginated_history_lineage() -> None:
    assert classify_crash_reason(_LINEAGE_CRASH) == 'provider_session_lineage_broken'


def _fake_backend(captured_text: str) -> object:
    def save_crash_log(pane_id, path, *, lines):  # noqa: ARG001
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(captured_text)

    return SimpleNamespace(save_crash_log=save_crash_log)


def test_persist_crash_log_writes_reason_sidecar_for_revoked_auth(tmp_path) -> None:
    session = SimpleNamespace(runtime_dir=tmp_path)

    reason = persist_crash_log(session, _fake_backend(_REVOKED_CRASH), '%4')

    assert reason == 'provider_auth_revoked'
    sidecars = list(tmp_path.glob('pane-crash-*.reason.json'))
    assert len(sidecars) == 1
    payload = json.loads(sidecars[0].read_text(encoding='utf-8'))
    assert payload['reason'] == 'provider_auth_revoked'
    assert payload['matched_signature'] == 'refresh token was revoked'
    assert payload['crash_log'].endswith('.log')
    assert 'codex login' in payload['detail']


def test_persist_crash_log_writes_no_sidecar_for_ordinary_crash(tmp_path) -> None:
    session = SimpleNamespace(runtime_dir=tmp_path)

    reason = persist_crash_log(session, _fake_backend('Segmentation fault\n'), '%4')

    assert reason is None
    assert list(tmp_path.glob('pane-crash-*.reason.json')) == []
    # the raw crash log is still captured
    assert list(tmp_path.glob('pane-crash-*.log'))


def test_persist_crash_log_noop_without_saver(tmp_path) -> None:
    session = SimpleNamespace(runtime_dir=tmp_path)
    assert persist_crash_log(session, SimpleNamespace(), '%4') is None


def test_persist_crash_log_prunes_runtime_artifacts_online(tmp_path) -> None:
    for index in range(MAX_PANE_CRASH_LOGS + 5):
        (tmp_path / f'pane-crash-{index:04d}.log').write_text('old\n', encoding='utf-8')
        (tmp_path / f'pane-crash-{index:04d}.reason.json').write_text('{}\n', encoding='utf-8')

    session = SimpleNamespace(runtime_dir=tmp_path)
    persist_crash_log(session, _fake_backend('Segmentation fault\n'), '%4')

    logs = list(tmp_path.glob('pane-crash-*.log'))
    reasons = list(tmp_path.glob('pane-crash-*.reason.json'))
    assert len(logs) == MAX_PANE_CRASH_LOGS
    retained_stems = {path.stem for path in logs}
    assert all(path.name.removesuffix('.reason.json') in retained_stems for path in reasons)


def test_respawn_uses_start_command_repaired_from_crash_reason(tmp_path, monkeypatch) -> None:
    commands: list[str] = []

    class _Backend:
        alive = False

        def pane_exists(self, pane_id: str) -> bool:
            return True

        def save_crash_log(self, pane_id: str, path: str, *, lines: int) -> None:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('No conversation found to continue\n')

        def respawn_pane(self, pane_id: str, *, cmd: str, **kwargs) -> None:
            commands.append(cmd)
            self.alive = True

        def is_alive(self, pane_id: str) -> bool:
            return self.alive

    class _Session:
        start_cmd = 'claude --continue'
        work_dir = str(tmp_path)
        runtime_dir = tmp_path

        def prepare_crash_recovery(self, reason: str):
            assert reason == 'provider_session_missing'
            self.start_cmd = 'claude'
            return True, 'repaired'

    backend = _Backend()
    session = _Session()
    monkeypatch.setattr(
        'provider_backends.pane_log_support.lifecycle_recovery.inspect_tmux_pane_ownership',
        lambda session, backend, pane_id: SimpleNamespace(is_owned=True),
    )
    monkeypatch.setattr(
        'provider_backends.pane_log_support.lifecycle_recovery.activate_rebound_pane',
        lambda *args, **kwargs: None,
    )

    error = respawn_existing_pane(
        session,
        backend,
        '%4',
        start_cmd='claude --continue',
        respawn=backend.respawn_pane,
        now_str_fn=lambda: '2026-07-30T00:00:00Z',
        attach_pane_log_fn=lambda session, backend, pane_id: None,
    )

    assert error is None
    assert commands == ['claude']


def test_codex_lineage_crash_quarantines_binding_before_respawn(tmp_path: Path, monkeypatch) -> None:
    runtime_dir = tmp_path / 'provider-runtime'
    session_root = tmp_path / 'provider-state' / 'codex' / 'home' / 'sessions'
    session_file = tmp_path / '.codex-agent-session'
    work_dir = tmp_path / 'repo'
    work_dir.mkdir()
    source_path = session_root / '2026' / '09' / '08' / 'rollout-sid-source.jsonl'
    child_path = session_root / '2026' / '09' / '08' / 'rollout-sid-child.jsonl'
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        json.dumps({'type': 'session_meta', 'payload': {
            'session_id': 'sid-source',
            'forked_from_id': 'sid-missing-source',
            'cwd': str(work_dir),
        }}) + '\n',
        encoding='utf-8',
    )
    child_path.write_text(
        json.dumps({'type': 'session_meta', 'payload': {
            'session_id': 'sid-child',
            'forked_from_id': 'sid-source',
            'cwd': str(work_dir),
        }}) + '\n',
        encoding='utf-8',
    )
    base_cmd = f'export CODEX_RUNTIME_DIR={runtime_dir}; codex -c disable_paste_burst=true'
    resume_cmd = f'{base_cmd} resume sid-child'
    data = {
        'runtime_dir': str(runtime_dir),
        'work_dir': str(work_dir),
        'terminal': 'tmux',
        'pane_id': '%4',
        'codex_session_root': str(session_root),
        'codex_session_path': str(child_path),
        'codex_session_id': 'sid-child',
        'codex_start_cmd': resume_cmd,
        'start_cmd': resume_cmd,
        'ccb_resume_compatibility': 'native_fork_continuation',
    }
    session_file.write_text(json.dumps(data), encoding='utf-8')
    session = CodexProjectSession(session_file=session_file, data=dict(data))
    commands: list[str] = []

    class _Backend:
        alive = False

        def pane_exists(self, pane_id: str) -> bool:  # noqa: ARG002
            return True

        def save_crash_log(self, pane_id: str, path: str, *, lines: int) -> None:  # noqa: ARG002
            Path(path).write_text(_LINEAGE_CRASH, encoding='utf-8')

        def respawn_pane(self, pane_id: str, *, cmd: str, **kwargs) -> None:  # noqa: ARG002
            commands.append(cmd)
            self.alive = True

        def is_alive(self, pane_id: str) -> bool:  # noqa: ARG002
            return self.alive

    backend = _Backend()
    monkeypatch.setattr(
        'provider_backends.pane_log_support.lifecycle_recovery.inspect_tmux_pane_ownership',
        lambda session, backend, pane_id: SimpleNamespace(is_owned=True),
    )
    monkeypatch.setattr(
        'provider_backends.pane_log_support.lifecycle_recovery.activate_rebound_pane',
        lambda *args, **kwargs: None,
    )

    error = respawn_existing_pane(
        session,
        backend,
        '%4',
        start_cmd=resume_cmd,
        respawn=backend.respawn_pane,
        now_str_fn=lambda: '2026-09-08T00:00:00Z',
        attach_pane_log_fn=lambda session, backend, pane_id: None,
    )

    assert error is None
    assert len(commands) == 1
    assert 'resume' not in commands[0]
    assert session.data.get('codex_session_id') is None
    assert session.data.get('codex_session_path') is None
    assert session.data['codex_binding_recovery_reason'] == 'provider_session_lineage_broken'
    assert session.data['ccb_resume_compatibility'] == 'broken_native_lineage'
    persisted = json.loads(session_file.read_text(encoding='utf-8'))
    assert persisted['rejected_codex_session_id'] == 'sid-child'
    assert persisted['start_cmd'] == session.start_cmd
    assert source_path.is_file()
    assert child_path.is_file()


def test_codex_lineage_recovery_blocks_when_binding_quarantine_cannot_persist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_file = tmp_path / '.codex-agent-session'
    data = {
        'codex_session_id': 'sid-child',
        'codex_session_path': str(tmp_path / 'rollout-sid-child.jsonl'),
        'codex_start_cmd': 'codex resume sid-child',
        'start_cmd': 'codex resume sid-child',
    }
    session_file.write_text(json.dumps(data), encoding='utf-8')
    original = session_file.read_bytes()
    session = CodexProjectSession(session_file=session_file, data=dict(data))
    monkeypatch.setattr(
        'provider_backends.codex.launcher_runtime.session_paths.safe_write_session',
        lambda *args, **kwargs: (False, 'injected write failure'),
    )

    result = session.prepare_crash_recovery('provider_session_lineage_broken')

    assert result is not None
    assert result[0] is False
    assert 'could not be persisted' in result[1]
    assert session_file.read_bytes() == original
    assert session.data == data
