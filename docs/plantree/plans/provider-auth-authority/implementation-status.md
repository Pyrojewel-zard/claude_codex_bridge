# Provider Authentication Authority Implementation Status

Date: 2026-08-05

## Current Phase

The v8.5.5 compatibility repair and the continuous-inheritance implementation
are landed in the worktree for Codex, Claude, and Gemini. Explicit CCB
authority wins per configured dimension; otherwise a newly prepared, stopped
Provider generation reads the current external state into a private projection.
The source boundary is one-way, and a change of authority increments CCB's
generation without clearing the stable conversation, workspace, queue, session
record, or transcript history.

Native resume remains capability-gated. A qualified fork/import is used when
the installed CLI supports it; an unqualified or unsafe binding is retained as
linked continuation evidence instead of being hidden from history.

## Last Landed

- v8.5.5 was withdrawn from GitHub on 2026-08-05 after its first startup moved
  all pre-HMAC Codex sessions out of the active namespace.
- Codex now adopts compatible pre-HMAC namespaces in place and restores the
  exact v8.5.5 `*-global`/matching-legacy-route archive shape when old binding
  evidence proves ownership.
- Recovery preserves a newer current binding while returning archived
  transcripts to native `resume`; Agents without a newer binding recover the
  old current binding.
- Claude and Gemini allow one compatible legacy continuation before persisting
  the new fingerprint; explicit mismatches still start fresh.
- `ccb restart <agent>` no longer executes persisted `session.start_cmd`.
- Codex API/login authority changes retain the active `sessions/` namespace,
  remove only the stale native binding, and record a linked continuation while
  leaving credentials and transcripts untouched.
- Claude/Gemini API, route, or login authority changes suppress incompatible
  native `--continue`/`--resume latest`, then use fork/import when supported or
  retain a linked continuation without deleting private auth or history.
- Session records now carry a stable `ccb_conversation_id`, authority
  generation/history, parent linkage, and explicit resume compatibility.
- Codex binding completion now replaces `pending_native_binding` with durable
  managed-history or proven native-fork compatibility, including idempotent
  repair when the native id and path were already present.
- Bundled `codex-reconnect` is installed and automatically armed after a
  managed Codex thread binds; capacity/network recovery remains bounded to one
  exact-thread `continue`.

## Active TODO

1. Commit and push the reviewed v8.5.6 source state.
2. Install the committed v8.5.6 replacement locally and verify the installed
   CCB and bundled reconnect versions.
3. Complete organic real network/capacity qualification for `codex-reconnect`;
   deterministic fixtures must remain the only pressure-safe fallback.
4. Close the writable-home boundary for arbitrary `provider_profile.home`.
5. Continue capability qualification and writer-lease enforcement for providers
   beyond the current Codex/Claude/Gemini slice.

## Blocked By

No blocker for the source commit or the local replacement install. Organic
Provider fault qualification, broader rotating-OAuth enforcement, and native
capability coverage remain gated by external Provider behavior and private-login
decisions. An unqualified Provider must use linked continuation rather than
block local history continuity.

## Last Verified

- `/home/bfly/yunwei/ccb_source/ccb_test --diagnose` passed from the external
  `/home/bfly/yunwei/test_ccb2` project root.
- Focused authority, restore, launch, and reconnect integration tests: `189
  passed` from the external qualification pytest environment.
- `python3 -m compileall` for the touched Python modules and `git diff --check`
  passed.
- Full source pytest run from the source root with the qualification dependency
  environment: `6188 passed, 2 skipped, 4 subtests passed`.
- External source-runtime project
  `reconnect-autostart-live-20260805-01` advanced from inherited authority
  generation 1 to 2 without changing `ccb_conversation_id`, retained both
  transcript files with matching user-message hashes, resumed the same current
  Codex thread on a same-authority Agent restart, created no archive, armed
  reconnect automatically, and shut down to `unmounted` with reconnect `off`
  and no project process residue.
