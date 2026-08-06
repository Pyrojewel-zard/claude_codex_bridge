# R1/R2 Validation Evidence

Date: 2026-07-20

## Candidate

- Branch: `fix/managed-plugin-projection-safety`
- Base: `origin/main` at `5214ce03` (merged PR257)
- External project:
  `/home/bfly/yunwei/test_ccb2/plugin-projection-r1-r2-20260720`
- Source wrapper diagnosis: official source wrapper and candidate-worktree
  wrapper both accepted the external project; candidate execution used an
  explicit `CCB_TEST_ROOTS=/home/bfly/yunwei/test_ccb2`.

## Automated Tests

- Provider-profile plus launcher regression files: `222 passed`.
- Full Python suite: `5373 passed`, `15 skipped`, one failure in
  `test_ccbd_socket_rejects_mutating_requests_while_lifecycle_stopping` caused
  by the known non-deterministic shutdown connection-reset race.
- Isolated rerun of that exact test: `1 passed`.
- `git diff --check`, Python compilation, and local Markdown target checks:
  passed.

## Real Project

- Candidate `ccb_test config validate`: valid two-agent inplace layout with
  `codexseed` and `claudeseed`.
- Non-interactive candidate startup returned `start_status: ok`; CCBD was
  healthy and both agents mounted idle in real provider panes.
- The first TTY attach attempt started the backend successfully but the test PTY
  could not satisfy terminal clear capability. Control-plane inspection proved
  the resulting backend healthy; this was an attach-environment limitation,
  not a provider startup failure.

## Codex Evidence

- Real source cache:
  `/home/bfly/.codex/plugins/cache/openai-curated-remote`.
- Managed `plugins/cache` was a normal directory, not a symlink.
- The same real plugin metadata file in source and managed target had different
  inodes.
- Managed marker mode was `copy-seed` with a source metadata fingerprint.
- An agent-local runtime sentinel survived `ccb_test restart codexseed` while
  the source fingerprint was unchanged; the sentinel was removed after the
  check.
- Aggregate SHA256 of all real source cache files was
  `c272af7e871194627d9c0e4d2dfac1397ace85ec09a103cf0aadb144c31cb9ff`
  before and after a complete managed start, proving no observed source-content
  mutation.

## Claude Evidence And Limit

- Real source `/home/bfly/.claude/plugins/` contained only `blocklist.json` at
  startup and therefore was not a usable official plugin seed.
- The live Claude process had the expected managed `HOME` and
  `CLAUDE_PROJECTS_ROOT`, with no `CLAUDE_CODE_PLUGIN_SEED_DIR` or
  `CLAUDE_CODE_PLUGIN_CACHE_DIR` exported.
- Claude subsequently populated its own agent-local default marketplace state;
  that provider behavior is not evidence that an inherited custom plugin was
  seeded.
- Unit/integration tests prove usable-seed environment export, two-agent
  writable-root isolation, inheritance opt-out, hard-role opt-out, WSL path
  forwarding, and pre-process command placement. Real custom-plugin loading is
  intentionally not claimed for this account.

## Cleanup

- Candidate `ccb_test kill` returned `state: unmounted`.
- Project CCBD/tmux sockets and observed backend/provider PIDs were gone.
- Provider-state files remain in the external test project for inspection;
  system-installed CCB state and source-home plugin content were not modified.
