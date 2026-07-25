# Ordered Repair Slices

Date: 2026-07-20

Role: implementation plan and acceptance matrix
Status: active planning authority
Domain: managed provider and job integrity
Read when: starting, reviewing, or accepting R1-R12
Related: [roadmap](../roadmap.md), [open questions](../open-questions.md)

## Review Evidence Baseline

The 2026-07-19 review ran focused tests on each contributor head and again
after merging the reviewed `main`:

| Change | Head evidence | Merged-main evidence | Acceptance result |
| :--- | :--- | :--- | :--- |
| PR257 | 113 provider-profile tests passed | Already merged | Follow-up required |
| PR258 | 9 native CLI tests passed | 11 passed | Rejected by first-launch and alias counterexamples |
| PR259 | 22 Claude tests passed | 27 passed | Rejected by cross-turn replay |
| PR264 | 17 documentation/static tests passed | 17 passed | Minor wording changes required |
| PR265 | 120 ProjectView tests passed | 120 passed | Partial diagnostic slice only |
| PR266 | 78 cancellation tests passed | 78 passed | Rejected by chain-cancel counterexample |

The open-PR CI matrix was not green at review time. Some observed macOS/WSL
failures matched an existing shutdown race, but every candidate must still
obtain a current green or explicitly adjudicated gate after revision.

## R1: Codex Plugin Projection Safety

Status: landed as `06e1a46a` through merge `aed27abf`.

Finding:

- Merged PR257 routes `plugins/cache` and `.tmp/marketplaces` with
  `allow_unmarked_replace=True`.
- A missing source cache deletes an existing managed local plugin cache.
- A present source can become a shared mutable symlink target for multiple
  managed agents.
- The authoritative Codex plugin projection contract still describes the old
  startup authority.

Correction boundary:

- Classify each path as immutable startup authority or agent-owned writable
  state before changing code.
- Never delete or replace unmarked agent-owned state because a source path is
  missing.
- Replace only marker-owned projections and keep writable runtime cache local
  to the managed home.

Frozen decision (2026-07-20):

- `.tmp/plugins/` plus `.tmp/plugins.sha` remains immutable whole-bundle
  authority and may use content-addressed shared storage.
- `.tmp/marketplaces/` and `plugins/cache/` are per-agent writable state seeded
  by staged copies. They must not resolve to the source home or another agent.
- Missing source preserves writable local state. Source changes refresh only a
  valid marker-owned seed, and failed replacement restores the previous tree.
- Unmarked and foreign-marker targets are never replaced or claimed.

Required evidence:

- Missing source preserves managed local cache.
- Source present does not permit managed sessions to mutate source authority.
- Two Codex agents do not share writable cache state.
- Upgrade, repeated refresh, stale marker, and rollback cases pass.
- Codex plugin and provider-state storage contracts are updated.

Exit gate: land with R2 in one main-based PR after merged-main and external
source-runtime evidence passes.

## R2: Claude Plugin Seed Support

Status: base seed/cache isolation landed as `06e1a46a`; first-interactive-load
hardening is included in the active R11 candidate.

Finding:

- Managed Claude homes inherit `enabledPlugins` but not marketplace
  registration, marketplace sources, or plugin cache content.
- A plugin such as Ponytail can therefore be enabled in settings but absent
  from the first isolated Claude session.

Correction boundary:

- Use Claude's supported plugin seed boundary for inherited read-only plugin
  authority rather than sharing a mutable cache between agents.
- Keep each managed Claude home's writable provider state independent.
- Forward seed paths correctly when Windows Claude is launched through WSL.

Frozen decision (2026-07-20):

- Plugin inheritance follows `inherit_config` plus the existing hard-role
  inherited-assets gate; no new profile field is added in this slice.
- A usable source `.claude/plugins/` is exposed through the provider-supported
  read-only `CLAUDE_CODE_PLUGIN_SEED_DIR` boundary.
- `CLAUDE_CODE_PLUGIN_CACHE_DIR` points to the full agent-local
  `<managed-home>/.claude/plugins/` root, not its `cache/` child.
- A source directory containing only `blocklist.json` is not treated as a seed.

Required evidence:

- First managed SessionStart sees a seeded plugin skill/hook.
- No-source and plugin-inheritance-disabled paths remain clean.
- Two concurrent Claude agents can load the plugin without source mutation or
  shared writable state.
- Linux, macOS, and applicable WSL path handling are covered.
- Claude isolation and provider-state storage contracts are updated.

Exit gate: land with R1 after fresh external project validation. When the test
account has no installed source plugin, record that limitation and retain the
first-process environment, two-agent isolation, and no-source evidence rather
than fabricating a real-plugin pass.

## R3: Inbound Completion Routing Documentation

Finding:

- PR264 correctly requires an inbound agent to finish its current continuation
  directly instead of sending another ask to the original caller.
- Its rematerialization wording can imply that a running provider session
  rereads changed memory without restart.

Correction boundary:

- State that rematerialized memory is adopted by a restarted or new provider
  session when the provider does not hot-reload it.
- Scope direct finalization to registered agent callers; direct CLI users read
  trace/watch/control output.

Required evidence: static template assertions for every projected ask skill
and generated runtime-memory variant touched by the PR.

Exit gate: land as a documentation-only change without coupling it to R4.

## R4: Cancellation And Callback Terminalization

Finding:

- PR266 correctly avoids putting an empty cancelled reply at mailbox head.
- Cancellation calls terminal recording directly and bypasses normal callback
  continuation finalization.
- Cancelling a chain child can leave its callback edge pending and its parent
  message running until a dispatcher restart repairs the edge.

Correction boundary:

- Route cancellation through the same idempotent terminal callback authority
  as normal completion, or explicitly terminalize the edge in that authority.
- A cancelled chain child creates exactly one parent continuation with
  structured `cancelled` status and any preserved partial output; the parent
  remains responsible for the original caller's terminal result. See
  [Decision 001](../decisions/001-cancelled-chain-child-continuation.md).
- Preserve partial provider output as normal reply content.
- Define trace/ProjectView visibility for consumed-from-birth control notices.

Required evidence:

- Ordinary empty cancel leaves no caller mailbox depth.
- Non-empty partial cancel remains deliverable exactly once.
- Chain child cancel resolves parent continuation according to the frozen
  policy without dispatcher restart.
- Repeated cancel, completion race, persistence/restart, and pre-existing
  caller mailbox cases pass.

Exit gate: revised PR266 or a clean replacement PR passes callback, mailbox,
trace, and external source-runtime tests.

## R5: Claude Queued-Prompt Activation

Status: verified by the atomic commit selected by `Repair-Slice: R5`.

Finding:

- PR259 treats `queue-operation/enqueue` as a synthetic user anchor.
- Real Claude logs show the old assistant may emit `end_turn` before dequeue
  and before the queued prompt becomes active.
- Replay proved old-turn output can be captured as the new job reply.

Correction boundary:

- Represent `enqueued`, dequeue observation, `activated`, and `anchored`
  separately.
- Do not accept assistant content or terminal evidence for the new job until
  activation is correlated to that prompt.
- Fence pre-anchor assistant UUID and subagent events from the new turn.

Frozen decision (2026-07-21):

- Enqueue proves delivery only. A bare dequeue has no prompt identity and is
  diagnostic only.
- A normal top-level user record or exact
  `attachment/queued_command.prompt` carrying the current outer request ID is
  activation authority. Tool-result, meta, and subagent user records are not.
- Pane dispatch never synthesizes activation or `ANCHOR_SEEN`. Pre-activation
  assistant, tool, subagent, system, hook, API-error, and idle-pane evidence is
  fenced.
- Queue lifecycle state survives daemon restart with the reader cursor and is
  cleared by top-level session rotation. See
  [Decision 002](../decisions/002-claude-queued-prompt-activation.md).

Required evidence:

- Old busy turn plus one queued prompt.
- Multiple queued prompts with exact and non-matching activation replay.
- Tool-only old turn, subagent records, restart/catch-up, and session rotation.
- No old assistant content or terminal event enters the new reply.

Exit gate: satisfied by replacing PR259's enqueue-time anchor model with exact
activation correlation, preserved counterexamples, a real busy-pane Claude
run, and cumulative/full regression gates.

## R6: Kimi Exact-Session Resume

Status: verified by the atomic commit selected by `Repair-Slice: R6`.

Finding:

- PR258 adds `--continue` whenever generic `restore` is true, including an
  ordinary first launch.
- Kimi 1.47.0 exits when no prior workdir session exists.
- Flag aliases vary by Kimi version, and workdir-global latest-session lookup
  can resume another CCB agent's session.

Correction boundary:

- Persist the exact native Kimi session identity observed for the managed
  agent and resume only that session.
- Start fresh when no CCB-owned session exists or reset was requested.
- Prefer stable long options and capability-aware parsing; recognize explicit
  user session/resume flags without adding a conflicting flag.

Frozen decision (2026-07-21):

- The agent-specific `.kimi-<agent>-session` record owns a native ID only
  after that agent's exact CCB request is observed in the native wire log.
- Managed restart emits only capability-confirmed `--session <owned-id>`;
  workdir-global `--continue`, newest-directory selection, and CCB launch IDs
  are never automatic resume authority.
- First launch, reset, invalid/missing binding, storage drift, and unsupported
  exact-session capability start fresh and clear carried binding without
  deleting provider data. Explicit user session controls win.
- See [Decision 003](../decisions/003-kimi-exact-session-ownership.md).

Required evidence:

- Empty first launch, normal restart, clear/reset, and explicit session flags.
- Two in-place Kimi agents in the same workdir never resume each other.
- Missing/corrupt prior session fails clearly or starts fresh according to a
  documented decision, without silent fallback to another session.

Exit gate: satisfied by replacing PR258's workdir-global continuation with
observation-bound per-agent ownership, capability-confirmed exact restart,
fail-fresh invalid authority, preserved counterexamples, and a real
same-workdir two-agent Kimi run.

## R7: Correlated Execution-State Model

Status: verified atomic commit selected by `Repair-Slice: R7`.

Finding:

- PR265 maps nearly every running job to `executing`, classifies orphan risk
  before full attempt/inbound/mailbox/lease correlation, and has no explicit
  contradictory-evidence `unknown` state.
- The new field is not consumed by structured queue, CLI, Rust sidebar, or
  mobile surfaces required by Issue262.

Correction boundary:

- Apply the additive phase vocabulary and fail-closed evidence precedence model
  frozen in
  [Decision 004](../decisions/004-correlated-execution-phase-schema.md).
- Derive phase from job, execution runtime, inbound attempt, mailbox, lease,
  provider anchor/activity, and terminal evidence with matching identities.
- Contradictory or incomplete evidence must be `unknown`, not a confident
  orphan/executing label.

Required evidence:

- Injecting, queued, anchored/executing, provider-idle-pending-terminal,
  terminal, orphaned, and unknown fixtures.
- Mismatched job/attempt/lease and stale pane evidence cannot produce a
  confident phase.
- ProjectView, structured queue, CLI, sidebar, and mobile consume the same
  field with backward-compatible fallback.
- Diagnostics and sidebar contracts are updated.

Exit gate: satisfied by the shared pure resolver, exact-correlated producer
evidence, contradictory-evidence `unknown`, all required clients, updated
contracts, cumulative suites, and external real-provider evidence. PR265
remains held and Issue262 remains open for the final disposition gate.

## R8: Stuck Inbound Detection

Status: verified atomic commit selected by `Repair-Slice: R8`.

Finding: Issue260 describes a running inbound job that remains mailbox head
after the provider has returned to an idle prompt without terminal evidence.

Correction boundary:

- Build only on R7 correlated identities and phase authority.
- Require running job, active matching inbound/lease, provider-idle evidence,
  and absent terminal evidence over a bounded observation interval.
- Apply the exact observation and reset policy frozen in
  [Decision 005](../decisions/005-bounded-orphaned-inbound-diagnosis.md).
- Emit diagnostic suspicion first; do not auto-restart, resend, or complete.

Required evidence:

- True stuck fixture and false-positive guards for long reasoning, tool use,
  queued prompt, stale pane snapshot, session rotation, and terminal race.
- Doctor, ProjectView, trace, CLI, and sidebar expose the same reason/evidence.

Exit gate: satisfied. External real-Claude project
`/home/bfly/yunwei/test_ccb2/r8-orphaned-inbound-runtime-20260721-B1KYSq`
diagnosed the same exact idle lineage only after the bounded window. Job,
attempt, inbound, mailbox, lease, completion, reply, and runtime authority
hashes did not change during ProjectView, trace, or doctor observations; no
automatic recovery ran. A separate live terminal race returned terminal with
zero diagnostics. Issue260 remains open for the final disposition gate.

## R9: Active-Job Correction Capability

Finding: Issue261 requests correction/follow-up delivery to a job that is
already active; PR264 only documents cancel and resubmit behavior.

Correction boundary:

- Address an exact job and active provider turn, not merely an agent pane.
- Preserve correction lineage and ordering relative to completion/cancel.
- Advertise provider support explicitly and fail closed when unsupported.
- Never substitute another provider or hide failed injection behind retries.

Required evidence:

- Supported provider success, unsupported provider refusal, wrong/stale job,
  multiple queued jobs, completion race, cancellation race, and restart.
- Caller and operator can distinguish accepted, rejected, too-late, and
  terminal outcomes.

Exit gate: product semantics and provider capability matrix are frozen before
implementation; R9 cannot weaken R4 terminal authority or R7 phase authority.

## R10: Integrated Qualification

Status: verified by the atomic evidence commit selected with
`Repair-Slice: R10`, after clean R11-C commit `6a20a514`.

Required gates:

- Focused regression suites for every R1-R9 counterexample.
- Full Python and Rust suites, plus affected Flutter/sidebar/mobile suites.
- Clean merge with current `main` and current CI adjudication.
- External source-wrapper diagnose and inspectable live project validation.
- Real Codex primary and Claude secondary acceptance where provider behavior is
  involved; no Grok/Gemini/OpenCode credential requirement for this lane.
- Provider source homes remain unmodified, cancellation leaves no unresolved
  chain edge, and completed tests leave no mounted runtime residue.

Release decision: batch only compatible slices. A critical main regression may
ship earlier as a focused hotfix after its own complete gate.

Verified result: the union counterexample gate passed `945` tests; complete
Python passed `5547` with `15` skips; provider blackbox passed `21`; Rust
passed `79 + 8 + 10` plus formatting; Flutter analyze and all `659` tests
passed. Real Codex `gpt-5.6-terra/low` and Claude `deepseek-v4-pro` each
completed one identical frozen task with exact reply `R10_REAL_OK`. Candidate
and inherited extension-source digests were unchanged, live state had no
active/pending/replay item, and non-forced cleanup left no project process or
socket. Current-main CI platform failures and the six-file Dart format drift
are explicitly adjudicated in the durable R10 evidence.

## R11: Remaining Provider Extension Inheritance

Status: Claude, Gemini, Qwen, and Droid candidate committed on its qualified
branch; Copilot deferred.

Frozen decision (2026-07-20):

- Claude keeps the official read-only seed plus per-agent writable root, but a
  new root is bootstrapped locally before the first interactive scan because
  Claude Code 2.1.206 synchronizes seed marketplaces too late for that session.
- Gemini and Qwen extension directories are marker-owned local seeds under the
  already isolated provider home; source missing preserves the last seed and
  explicit opt-out removes only CCB-owned state.
- Droid copies only `plugins/`, rebases plugin registry paths into the managed
  `FACTORY_HOME`, and marker-merges only `enabledPlugins`. It does not copy the
  whole settings file, sessions, or auth.
- Hard role policy and config opt-out disable these inherited capabilities.
- Copilot remains deferred because installed plugins, auth-sensitive config,
  permissions, sessions, cache, and plugin data do not yet have a frozen
  entry-level ownership contract.

Required evidence:

- Claude clean-home first pane loads an offline plugin skill without reload or
  restart, installed plugin paths resolve inside the agent-local cache, and the
  complete-help capability probe sees flags beyond 8 KiB.
- Gemini and Droid real CLIs see the managed local extension/plugin state.
- Qwen source, launcher, two-agent, opt-out, missing-source, and marker tests
  pass; real runtime qualification stays unclaimed while the CLI is absent.
- Source trees remain unchanged, managed writable roots are not symlinks, and
  malformed/foreign ownership data fails closed.

Exit gate: focused regressions pass, any unrelated full-suite failure is
explicitly adjudicated, the external CCB project is cleanly unmounted,
contracts and evidence are updated, and Copilot is recorded as an explicit
defer rather than a silent partial fix.

### R11-C: Copilot Plugin/Config Projection

Status: verified by the atomic commit selected with `Repair-Slice: R11-C`.

Frozen decision:

- [Decision 008](../decisions/008-copilot-entry-owned-plugin-seed.md) permits
  only allowlisted `config.json.installedPlugins` entries and their exact
  installed trees; aggregate and per-tree markers prove ownership.
- Metadata conflicts and local divergence preserve target state and omit or
  relinquish that entry. Missing/malformed source preserves the last good
  projection; explicit opt-out removes only unchanged marker-owned entries.
- Auth/application fields, settings, permissions, sessions, command history,
  plugin data, marketplace cache, and MCP secret/OAuth state are never copied,
  merged, deleted, or claimed. Managed cache is agent-local.

Required evidence:

- Marketplace/direct, two-agent, refresh/removal/opt-out, missing/malformed,
  conflict/divergence/deletion, escape/symlink, marker, rollback, storage, hard
  role, launcher/headless cache, and source-immutability tests.
- External source wrapper plus offline Copilot CLI `1.0.61` synthetic plugin
  discovery without login, exact source/divergence hashes, and clean unmount.

Exit gate: Copilot installed plugin discovery works from the isolated managed
home, no forbidden source or target state changes, focused/full/external gates
pass, and R11-C lands as one atomic commit before R10 starts. Satisfied by the
`22`-test focused ownership gate, `426`-test cumulative provider gate, complete
`5547`-test Python suite, and external offline Copilot CLI `1.0.61` discovery
from two isolated homes. Source and repeated local-divergence hashes remained
unchanged; candidate cleanup left the project unmounted.

## R12: Generic Projected-Asset Ownership Hardening

Status: verified by the atomic commit selected with `Repair-Slice: R12`.

Finding:

- Packaged inherited skills, Claude skills/commands, and Droid skills still
  enabled `allow_unmarked_replace=True`.
- The shared replacement predicate treated any same-name marker file as
  ownership proof and could replace an unmarked content-identical directory.

Frozen decision:

- [Decision 007](../decisions/007-marker-first-projected-asset-ownership.md)
  requires a valid local schema-v1 `ccb_projected_asset` marker with exact
  label, non-empty source, and recognized mode.
- The only markerless migration writes a marker beside an exact current-source
  symlink without replacing it.
- Unmarked directories and foreign/malformed/symlinked markers are always
  preserved. The compatibility flag grants no replacement or cleanup
  authority.

Required evidence:

- Generic different/identical directory, foreign symlink, exact symlink,
  marker-write failure, marker schema, valid refresh, source-missing, and
  disabled cleanup tests.
- Consumer regressions for packaged Kimi skills, Claude skills/commands, Droid
  skills, RolePack and per-skill projections, and existing marker-first seeds.
- External candidate materialization with fake source homes, unchanged source
  hashes, no provider login, clean unmount, and no source-worktree mutation.

Exit gate: every production `allow_unmarked_replace=True` call is removed,
generic replacement is marker-first, focused/full/external gates pass, and R12
lands as one atomic commit before R11-C starts.

Verified evidence:

- The final generic/provider/RolePack/storage gate passed `399` tests in
  `5.88s`; the complete Python suite passed `5536` tests with `2` skipped in
  `1067.43s`. Compilation and `git diff --check` passed.
- External candidate project
  `/home/bfly/yunwei/test_ccb2/r12-projected-assets-20260721` used the source
  wrapper and fake provider without login. Candidate `doctor` observed a
  healthy mounted backend from the candidate implementation root.
- Claude, Droid, and packaged Kimi counterexamples preserved unmarked user
  assets; Kimi omitted the conflicting root. Exact legacy symlink adoption
  retained its inode, valid owned refresh/cleanup passed, and all fake-source
  hashes were unchanged.
- Candidate `kill` returned the project to `unmounted`; daemon, keeper, and
  socket evidence were absent. Compact evidence is `r12-runtime-result.json`
  in the external project.
