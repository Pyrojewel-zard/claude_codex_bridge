# Claude Continuity-First Verification

Date: 2026-09-29
Role: evidence
Status: Pre-release verification snapshot; subsequently published in v8.7.4

Publication and installation evidence: [release receipt](v8.7.4-release-20260929.md).
Related: [decision 008](../decisions/008-continuity-first-native-restore.md)

## Source And Changes

Base: `8888fc6f2`; branch `fix/claude-continuity-first-20260929` in an isolated
worktree. The original dirty worktree and active business panes are untouched.

- `lib/provider_backends/claude/launcher_runtime/restore.py`,
  `project_session_restore_target`: remove authority-mismatch/linked-pending
  early fresh/fork returns. Inspect current Agent-owned history and rebind
  provenance without deleting the native binding. Keep home/path checks.
- `lib/provider_backends/claude/launcher_runtime/service.py`,
  `build_start_cmd`, `resolve_run_cwd`, `build_session_payload`: keep native
  `--continue`; explicit startup session controls suppress automatic restore;
  persist whether CCB selected automatic restore.
- `lib/cli/services/runtime_launch_runtime/session_files.py`,
  `_merge_existing_session_binding`: retain the validated, rebound Claude
  conversation/generation metadata across session writes. Explicit fresh or
  user-selected controls do not merge the previous native binding.
- `lib/provider_backends/claude/session_runtime/model.py`,
  `prepare_crash_recovery`: existing missing-conversation fallback retains
  old binding evidence and a non-secret reason; do not strip explicit user
  continue or repeat this fallback. No new crash signatures are introduced.

The fingerprint fence originated in `fe8dbd9ea6` (v8.5.5), with legacy
adoption/fork handling added in `8b35d868f4` (v8.5.6). Fingerprints remain in
place for provenance; their credential/config projection purpose is unchanged.

## Automated Verification

Use `uv run --no-project --with pytest --with pyyaml --with cryptography
--with aiohttp python -m pytest -q` followed by these paths:

- `test/test_claude_continuity_first.py`
- `test/test_provider_session_authority.py`
- `test/test_v2_provider_restore_launchers.py`
- `test/test_claude_session_fields.py`
- `test/test_pane_crash_reason.py`
- `test/test_claude_launcher_env.py`

Result: **99 passed**. Synthetic changes cover key, route, account metadata,
expiry, and credential-file whitespace. Assertions cover unchanged source
files/transcript bytes, stable conversation identity, generation increments,
repeat launches, old linked state, ownership/symlink rejection, explicit
controls, no-history behavior, one-shot missing-session fallback, and no
clearing on 401/403/429/network/thinking-signature errors.

Additional `test/test_v2_runtime_launch.py` and
`test/test_claude_session_ensure_pane.py`: **133 passed**.

## Native CLI Qualification

Run the same pytest command with `test/test_claude_continuity_native.py` and
`CCB_TEST_CLAUDE_BIN=/absolute/path/to/claude`.

Claude Code **2.1.283**: **1 passed**. The test uses disposable homes/projects,
an environment whitelist, no tools/MCP, and two loopback HTTP services with
fake credentials. It obtains a real native transcript, runs CCB's history
selection/command construction after an authority change, then executes the
selected native `--continue` argument against gateway B/key B. Assertions
verify the same native session ID and both prior user and assistant text in
B's request, authenticated with B's synthetic key.

The first harness attempt used the internal history function instead of its
launcher adapter; corrected without changing production code. A second
experiment showed that print-mode `--continue` does not necessarily raise
the interactive missing-conversation error. With a genuinely empty home it
starts fresh itself; the final test asserts a different native ID and no old
marker in the request. CCB's recognized pane-error fallback is unit tested,
not claimed as a live pane test. The fixture removes its temporary homes on
exit and the HTTP servers shut down in `finally` blocks.

This is a real CLI/HTTP replay test, not a real model inference/account test.
It does not qualify interactive tmux, commercial account switching, OAuth
rotation, tool/reasoning-history compatibility, remote session access, or an
arbitrary gateway. No installed runtime or working pane was restarted.

## Remaining Provider Boundaries

Historical snapshot for the Claude slice. Codex/OMP/Pi follow-up results are
now recorded in [the subsequent verification](codex-omp-pi-continuity-20260929.md).

| Provider | Audited source (under `lib/provider_backends/<provider>/`) | Current boundary |
| --- | --- | --- |
| Claude | `launcher_runtime/restore.py::project_session_restore_target` | This slice attempts native local continue despite authority changes. |
| Codex | `launcher_runtime/session_paths.py::load_resume_session_id`; `launcher_runtime/command_runtime/home.py::_link_project_session_binding` | Still gates direct resume and demotes current binding on authority change; fork fallback is not universal continuity. Follow-up required. |
| Gemini | `launcher_runtime/restore.py::resolve_gemini_restore_target` | Still changes to import/linked fresh on mismatch; follow-up required. |
| OMP/Pi | `session.py::resume_binding_for_launch` | Selection checks local ownership/native binding; no account-fingerprint veto in these functions. Cross-account native compatibility not tested here. |

## Rollout And Residual Risk

Review/integrate this scoped patch, then qualify an isolated interactive
project before release. Restore still uses Claude's most-recent local history,
not a newly implemented exact-ID selector. A corrupt/absent recorded path may
fail ownership/usability checks; this patch does not repair transcripts.
An incompatible reasoning/tool block must surface an error without silently
discarding context. A provider-specific import/translation fallback requires
separate evidence before implementation.

Rollback reverts source changes on stopped agents; retained transcript files
and generation metadata require no deletion. No commit/push/release or
external auth/config mutation was performed.
