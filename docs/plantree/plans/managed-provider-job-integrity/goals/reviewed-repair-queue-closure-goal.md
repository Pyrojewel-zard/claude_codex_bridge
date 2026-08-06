# Reviewed Repair Queue Closure Goal

Date: 2026-07-21

Status: Complete
Mode: Strict serial execution
Plan: [Managed Provider And Job Integrity](../README.md)
Queue authority: [Ordered repair slices](../topics/ordered-repair-slices.md)

## Objective

Close every confirmed defect from the PR257-PR266 review queue, including its
linked Issues260-263 and the explicitly deferred provider-ownership follow-ups.
Each queue item must be reproduced, repaired, verified, documented, and saved
as its own atomic commit before work begins on the next item.

The goal is complete only when the final integrated candidate is ready for an
explicit merge/release decision. Creating commits does not authorize pushing,
merging, closing upstream items, publishing packages, or releasing a version.

## Creation Baseline

- `origin/main`: `aed27abf` (merged PR269), unchanged by the 2026-07-21
  activation refresh.
- Completed local R11 candidate: `5c1ff83a` on
  `fix/unified-provider-extension-inheritance`.
- PR257 is merged. PR258, PR259, PR264, PR265, and PR266 remain open and
  `unstable` with unchanged reviewed heads: PR258 `d119bf18`, PR259
  `c4bd9427`, PR264 `1d4d1deb`, PR265 `2b79d68b`, and PR266 `3e11523c`.
- Issues260, 261, 262, and 263 remain open.
- R11 is source/runtime qualified for Claude, Gemini, and Droid, and
  source-qualified for Qwen. Copilot remains unresolved.
- One unchanged baseline test,
  `test_ccbd_socket_rejects_mutating_requests_while_lifecycle_stopping`, has a
  reproduced shutdown race. A later unrelated failure may be adjudicated only
  by proving the same failure on the current `origin/main` and running the
  remainder of the suite.

Baseline drift must be checked again when the goal is activated. This snapshot
is evidence, not permission to ignore newer `main` commits or upstream PR
changes.

## Completion Definition

All conditions are mandatory:

1. Every queue row below is `verified_commit` or `integrated`.
2. Every repair row resolves to exactly one atomic commit containing its code,
   tests, affected contracts, and PlanTree status update.
3. Each commit passes its slice gate and all cumulative regressions required by
   earlier rows.
4. Original PRs and issues have an explicit final disposition: merged,
   superseded by a named commit/PR, or closed with evidence.
5. Copilot is implemented and qualified; an environment limitation may block
   this goal but cannot be relabeled as completion.
6. R10 integrated qualification passes on the final stack against current
   `main` with no source-home mutation or live runtime residue.
7. Push, merge, issue closure, release, and publication happen only after
   separate explicit user instructions.

## Non-Negotiable Invariants

- One queue item is `in_progress` at a time. No parallel production edits.
- A failed, blocked, or uncommitted row does not unlock the next row.
- Do not merge contributor PRs as-is when their preserved counterexample still
  fails. Reimplement or selectively port only reviewed-safe behavior.
- No provider output may redefine script-owned job, callback, cancellation,
  phase, or session authority.
- No provider substitution, hidden retry, guessed session, or pane-wide
  heuristic may turn uncertainty into success.
- User-owned, unmarked, foreign-marker, credential, permission, session, and
  provider-runtime state must not be overwritten by projection code.
- Tests must use the candidate source wrapper from an external project. The
  installed release `ccb` remains reserved for live collaboration.
- A provider test must leave source state unchanged and must cleanly unmount
  its project before the slice is committed.
- No partial implementation commit, temporary debug commit, or cross-slice
  squash is allowed on the closure branch.

## Serial Queue

Allowed states: `waiting`, `ready`, `in_progress`, `blocked`,
`verified_commit`, `integrated`.

| Seq | Slice | Upstream items | Current state | Unlock condition |
| :--- | :--- | :--- | :--- | :--- |
| 0 | R11 completed provider extension candidate | PR257 follow-up | `verified_commit` (`5c1ff83a`) | Goal file accepted and baseline refreshed |
| 1 | R3 inbound completion routing documentation | PR264 | `verified_commit` (`Repair-Slice: R3`) | Seq 0 clean and recorded |
| 2 | R4 cancellation and callback terminalization | PR266, Issue263 | `verified_commit` (`Repair-Slice: R4`) | Seq 1 verified commit |
| 3 | R5 Claude queued-prompt activation | PR259 | `verified_commit` (`Repair-Slice: R5`) | Seq 2 verified commit |
| 4 | R6 Kimi exact-session resume | PR258 | `verified_commit` (`Repair-Slice: R6`) | Seq 3 verified commit |
| 5 | R7 correlated execution-state model | PR265, Issue262 | `verified_commit` (`Repair-Slice: R7`) | Seq 4 verified commit |
| 6 | R8 stuck inbound detection | Issue260 | `verified_commit` (`e937aa99`, `Repair-Slice: R8`) | Seq 5 verified commit |
| 7 | R9 active-job correction capability | Issue261 | `verified_commit` (`Repair-Slice: R9`) | Seq 6 verified commit and R4 authority retained |
| 8 | R12 generic projected-asset ownership hardening | Internal follow-up | `verified_commit` (`a41627a7`, `Repair-Slice: R12`) | Seq 7 verified commit |
| 9 | R11-C Copilot plugin/config projection | Deferred R11 remainder | `verified_commit` (`Repair-Slice: R11-C`) | Seq 8 verified commit |
| 10 | R10 integrated qualification and disposition | Entire queue | `verified_commit` (`Repair-Slice: R10`) | Seq 1-9 verified commits |

The table is the execution lock. Update one row at a time in the same commit as
its implementation. Do not mark a row `verified_commit` before its verification
commands and evidence are complete.

## Per-Slice Transaction

Run this complete transaction for every row from Seq 1 through Seq 9.

### 1. Preflight

- Read this goal, `implementation-status.md`, `roadmap.md`, the owning repair
  slice, open questions, and affected product contracts.
- Fetch `origin/main` and inspect the current upstream PR/issue state.
- Require a clean closure worktree and confirm the previous queue row has one
  verified commit.
- While the stack is unpublished, rebase it onto a newer `origin/main` before
  starting the row and rerun cumulative focused tests. Once published, do not
  rewrite reviewed history; integrate main explicitly and record that gate.
- Freeze the row's behavior, ownership, negative cases, and exact acceptance
  commands before editing production code.

### 2. Reproduce

- Add or preserve the smallest deterministic failing test for every reviewed
  counterexample.
- Demonstrate that the counterexample fails against the row baseline or retain
  an inspectable replay/fixture when native timing is required.
- Do not weaken an assertion merely to accept contributor behavior.

### 3. Implement

- Change only the owning slice and directly required shared contracts.
- Prefer existing state authorities and structured parsers.
- Update affected authoritative design documents in the same patch.
- Keep later queue items untouched even when nearby refactoring is tempting.

### 4. Verify

- Run the row-specific gate below.
- Run cumulative focused tests for every earlier committed row affected by the
  change.
- Run the full Python suite for runtime/shared-state changes. Run Rust,
  Flutter, sidebar, or mobile suites when their consumers change.
- Use `/home/bfly/yunwei/ccb_source/ccb_test` or the active candidate-worktree
  wrapper only from `/home/bfly/yunwei/test_ccb2`, with explicit allowed roots
  and isolated provider state unless inherited real state is intentional.
- For real-provider behavior, use an inspectable opened external project,
  capture exact provider/model identifiers, verify source immutability, then
  use candidate `ccb_test kill` and prove sockets/processes are gone.

### 5. Review And Commit

- Review the complete diff, run compilation/static checks, `git diff --check`,
  local Markdown-link checks, and a staged secret scan.
- Update this queue row, roadmap, implementation status, resolved questions,
  and a durable history/evidence file.
- Create one atomic commit. Use a commit trailer so evidence remains
  discoverable after an unpublished rebase:

```text
Repair-Slice: R<number-or-name>
Upstream: PR<number>, Issue<number>
```

- Require a clean worktree after commit. Do not amend that slice after the next
  row becomes `in_progress`; use a clearly attributed follow-up only if a
  later integration test discovers a regression.

## Slice Gate Index

The detailed findings, correction boundaries, negative cases, and exit gates
remain authoritative in
[ordered-repair-slices.md](../topics/ordered-repair-slices.md). Before starting
a row, load only its linked section; this goal must not duplicate or weaken
that authority.

| Seq | Gate authority | Irreducible row condition |
| :--- | :--- | :--- |
| 1 | [R3](../topics/ordered-repair-slices.md#r3-inbound-completion-routing-documentation) | Documentation/templates/static tests only; no runtime behavior change |
| 2 | [R4](../topics/ordered-repair-slices.md#r4-cancellation-and-callback-terminalization) | Chain-child cancellation resolves callback and parent without restart |
| 3 | [R5](../topics/ordered-repair-slices.md#r5-claude-queued-prompt-activation) | Old-turn and subagent output cannot complete a queued job before activation |
| 4 | [R6](../topics/ordered-repair-slices.md#r6-kimi-exact-session-resume) | First launch is fresh and same-workdir agents resume only exact owned sessions |
| 5 | [R7](../topics/ordered-repair-slices.md#r7-correlated-execution-state-model) | `unknown` plus correlated identities are shared by every required consumer |
| 6 | [R8](../topics/ordered-repair-slices.md#r8-stuck-inbound-detection) | Diagnosis-only real idle-prompt evidence; no automatic mutation or recovery |
| 7 | [R9](../topics/ordered-repair-slices.md#r9-active-job-correction-capability) | Exact-job capability/refusal and race outcomes fail closed |
| 8 | [R12](../topics/ordered-repair-slices.md#r12-generic-projected-asset-ownership-hardening) | Every retained unmarked replacement has explicit ownership proof |
| 9 | [R11 remainder](../topics/ordered-repair-slices.md#r11-remaining-provider-extension-inheritance) | Copilot entry ownership preserves credentials, sessions, permissions, cache, and local plugin data |
| 10 | [R10](../topics/ordered-repair-slices.md#r10-integrated-qualification) | Current-main cumulative suites, real Codex/Claude, source immutability, and zero residue pass |

For Seq 9, a suitable authoritative schema and offline/no-login fixture are
mandatory. If either is unavailable, mark the row `blocked`; do not copy the
whole Copilot config, substitute a provider, or declare the goal complete.

For Seq 10, write a final evidence index mapping every row to its commit and
artifacts, then propose the disposition of each upstream PR and issue. This is
still not authorization to push, merge, close, publish, or release.

## Blocked-State Rule

A row may be `blocked` only for a concrete external requirement such as a
missing qualified native CLI, unavailable authoritative schema, or repeatedly
reproduced environment failure outside the candidate. Record the exact blocker
and evidence in `implementation-status.md`.

Blocked is not complete and does not unlock the next row under this goal. Ask
for the missing input or environment change; do not skip the row, weaken its
gate, replace the provider, or hide the gap in R10 totals.

## Progress Ledger Template

For each completed row, append one compact entry to a history evidence index:

```text
Slice:
Commit selector / hash:
Upstream items:
Baseline:
Counterexample:
Focused tests:
Full/client tests:
Real project evidence:
Source immutability:
Cleanup:
Remaining risk:
Next unlocked row:
```

Keep raw logs and large artifacts outside active roadmap/status files. Link
them from history so future agents can retrieve evidence without loading the
entire execution record into context.

## Activation Checklist

- [x] User accepts this goal and authorizes execution.
- [x] Goal document is committed before the first repair slice.
- [x] Closure worktree and branch are named and clean.
- [x] `origin/main` and all upstream item states are refreshed.
- [x] Seq 0 commit is present after baseline synchronization.
- [x] The serial lock advanced through verified Seq 9; clean R11-C commit
      `6a20a514` unlocked Seq 10.
- [x] Seq 10 passed the cumulative Python/Rust/Flutter/static gates, current-main
      CI adjudication, isolated real Codex/Claude qualification, source
      immutability, and zero-residue cleanup. The current commit is selected by
      `Repair-Slice: R10`; upstream mutation remains separately gated.
