from __future__ import annotations

import pytest

from provider_backends.codex.session_runtime import live_identity
from provider_backends.codex.start_cmd import extract_resume_session_id

# Anchor runtime state so hardcoded `.ccb/...` paths stay stable under this
# fork's default relocation to ~/.local/ccb.
@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


# A realistic CCB-decorated HAPI wrapper cmdline for Codex resume. The native
# `codex` executable token appears after `--started-by terminal` because the
# decorator strips only the leading executable and forwards the remaining
# provider argv (which still contains `resume <id>`).
_HAPI_WRAPPER_CMDLINE = (
    'hapi codex --started-by terminal -c disable_paste_burst=true '
    '--sandbox read-only resume aabbccdd-1111-2222-3334-555566667777'
)

# The native Codex child process that the HAPI wrapper spawns carries the same
# resume id. CCB's process-tree scan must reach this descendant.
_CODEX_CHILD_CMDLINE = (
    'codex -c disable_paste_burst=true --sandbox read-only '
    'resume aabbccdd-1111-2222-3334-555566667777'
)

_EXPECTED_SESSION_ID = 'aabbccdd-1111-2222-3334-555566667777'


def test_extract_resume_session_id_finds_id_in_hapi_wrapper_cmdline() -> None:
    # The wrapper cmdline forwards the full provider argv, so the resume token
    # is present even before descending into the child process.
    assert extract_resume_session_id(_HAPI_WRAPPER_CMDLINE) == _EXPECTED_SESSION_ID


def test_extract_resume_session_id_finds_id_in_native_codex_child_cmdline() -> None:
    assert extract_resume_session_id(_CODEX_CHILD_CMDLINE) == _EXPECTED_SESSION_ID


def test_live_identity_matches_through_hapi_wrapper_parent(monkeypatch) -> None:
    """Regression: the HAPI wrapper parent must not hide the native Codex child.

    CCB scans the whole process tree rooted at the pane pid. With HAPI mode the
    pane runs the wrapper (hapi -> codex); the codex child is a descendant and
    its cmdline carries the bound resume id, so ``live_runtime_identity`` must
    report ``match`` rather than ``mismatch``.
    """
    # Process tree: pane_pid(1000) -> hapi(1001) -> codex(1002)
    parent_map = {1001: 1000, 1002: 1001}
    cmdlines = {
        1000: 'bash -c hapi codex ...',  # pane shell, no resume id
        1001: _HAPI_WRAPPER_CMDLINE,
        1002: _CODEX_CHILD_CMDLINE,
    }

    monkeypatch.setattr(live_identity, '_scan_linux_process_parent_map', lambda: parent_map)
    monkeypatch.setattr(
        live_identity,
        '_linux_process_cmdline',
        lambda pid: cmdlines.get(pid, ''),
    )

    cmdlines_collected = live_identity._process_tree_cmdlines(1000)
    assert _HAPI_WRAPPER_CMDLINE in cmdlines_collected
    assert _CODEX_CHILD_CMDLINE in cmdlines_collected
    assert any(extract_resume_session_id(c) == _EXPECTED_SESSION_ID for c in cmdlines_collected)


def test_live_identity_mismatch_when_no_descendant_carries_resume_id(monkeypatch) -> None:
    # If neither the wrapper nor any descendant carries the bound resume id
    # (e.g. the wrapper started a fresh session), CCB must report mismatch
    # rather than falsely accepting the live process.
    parent_map = {1001: 1000}
    cmdlines = {
        1000: 'bash -c hapi codex ...',
        1001: 'hapi codex --started-by terminal -c disable_paste_burst=true',  # no resume
    }

    monkeypatch.setattr(live_identity, '_scan_linux_process_parent_map', lambda: parent_map)
    monkeypatch.setattr(
        live_identity,
        '_linux_process_cmdline',
        lambda pid: cmdlines.get(pid, ''),
    )

    collected = live_identity._process_tree_cmdlines(1000)
    assert not any(extract_resume_session_id(c) == _EXPECTED_SESSION_ID for c in collected)
