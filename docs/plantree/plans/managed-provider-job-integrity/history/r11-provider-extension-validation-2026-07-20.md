# R11 Provider Extension Validation Evidence

Date: 2026-07-20

## Candidate

- Branch: `fix/unified-provider-extension-inheritance`
- Base: `origin/main` at `aed27abf` (merged PR269)
- Multi-provider external project:
  `/home/bfly/yunwei/test_ccb2/provider-extension-inheritance-bootstrap-20260720-pV3QUQ`
- Claude local-path follow-up project:
  `/home/bfly/yunwei/test_ccb2/provider-extension-local-path-20260720`
- Source validation used the candidate worktree `ccb_test` from the dedicated
  external test root with isolated synthetic provider source state.

## Automated Tests

- Provider-profile, hook, and launcher regression files: `282 passed`.
- The initial full Python run, before the final negative-test additions,
  reached `4181 passed`, `15 skipped` before
  `test_ccbd_socket_rejects_mutating_requests_while_lifecycle_stopping` failed
  during teardown because the stopping daemon had already removed or reset its
  socket before the test's final `client.shutdown()` call.
- The exact shutdown test reproduced independently. The candidate has no diff
  from `origin/main` in `lib/ccbd` or `test/test_v2_ccbd_socket.py`, so this is
  recorded as an existing lifecycle-test race rather than an R11 regression.
- The complete suite with only that adjudicated baseline test excluded passed:
  `5389 passed`, `15 skipped`, `1 deselected` in 585.69 seconds.
- Changed Python modules compiled successfully and `git diff --check` passed.

## Claude Root Cause And Evidence

- Claude Code 2.1.206 emits more than 8 KiB of `--help` output. Capturing help
  through a pipe stopped at exactly 8192 bytes and hid `--setting-sources`, so
  CCB's generated `--settings` overlay could suppress normal user plugin
  settings.
- In a clean interactive home, Claude scans enabled plugins before it finishes
  synchronizing the read-only seed marketplace. A first pane therefore found
  the marketplace only after initial skill discovery and required a reload.
- The candidate captures complete help output, preserves
  `user,project,local` setting sources, and bootstraps only a missing
  agent-local writable plugin root from the immutable seed before launch. It
  atomically rebases source-root `installPath` and `installLocation` values into
  that local root. Existing writable roots and runtime mutations remain
  untouched.
- On the first real managed pane, Claude invoked
  `Skill(ccb-fixture-plugin:ccb-fixture-skill)` and returned exactly
  `ccb-fixture-plugin-loaded` without reload or restart.
- The follow-up real project repeated the first-pane invocation with
  `installed_plugins.json` pointing to
  `.ccb/agents/claude_local/provider-state/claude/home/.claude/plugins/cache/`.
  The source plugin tree SHA256 remained
  `78f8dce57156f3995ca891312b9a859f5f15c94911683f9880c7f03017bcaebe`
  before and after the interaction.
- No-source, inheritance opt-out, and hard-role sessions use managed empty or
  restricted plugin roots so ambient user plugins cannot leak into the agent.
  The no-source root is distinct from normal `plugins/`, allowing a source seed
  that appears later to receive the same first-pane bootstrap.

## Other Provider Evidence

- Real `gemini extensions list --output-format json` reported the fixture
  extension active from the agent-local managed home.
- Real `droid plugin list` reported an active projected plugin. A separate
  system-source integration check rebased its registry install paths into a
  temporary managed `FACTORY_HOME`; the source content checksum was unchanged.
- Qwen source discovery, launcher wiring, two-agent isolation, opt-out,
  missing-source, ownership, and rollback behavior are covered by automated
  tests. No Qwen executable is installed on this host, so real Qwen runtime
  qualification is not claimed.
- Copilot is explicitly deferred. Its plugin metadata shares configuration
  authority with credentials, sessions, permissions, cache, and plugin data;
  copying its whole config would violate the provider-state boundary, and no
  local Copilot CLI is available for a safe fixture qualification.

## Ownership And Cleanup

- Claude, Gemini, and Droid source trees remained unchanged during real
  validation, and their managed plugin or extension roots were normal local
  directories rather than symlinks.
- Generic JSON projection is entry-owned and marker-backed. Foreign markers and
  malformed source data fail closed; local divergence is preserved; rollback
  restores both target and marker state.
- Candidate `ccb_test kill` returned both external projects to `unmounted`.
  The follow-up project's lifecycle recorded desired state `stopped`, and its
  CCBD and tmux sockets were absent after cleanup.
