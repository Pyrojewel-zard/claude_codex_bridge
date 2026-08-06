from __future__ import annotations

import json
from types import SimpleNamespace

from provider_backends.pane_log_support.lifecycle_common import (
    MAX_PANE_CRASH_LOGS,
    classify_crash_reason,
    persist_crash_log,
)
from provider_backends.pane_log_support.lifecycle_recovery import respawn_existing_pane

# Real captured text from a codex pane whose isolated OAuth refresh token was
# revoked after a token rotation (the crash that surfaces to the user as a
# generic "stale" pane).
_REVOKED_CRASH = (
    "• Ran sqlite3 -json ingest/index.db ...\n"
    "■ Your access token could not be refreshed because your refresh token was "
    "revoked. Please log out and sign in again.\n"
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
