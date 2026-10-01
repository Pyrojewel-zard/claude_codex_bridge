# v8.7.3 release qualification

Date: 2026-09-28
Role: evidence
Status: published and public installation verified; post-merge rerun passed
Related: [release notes](../../../../releases/v8.7.3.md),
[composer evidence](composer-model-independence-20260927.md),
[real Claude qualification](claude-continuous-queue-live-20260927.md)

## Source and scope

Previous release: v8.7.2 (`91fb0a4d2`). Base main: `502e5e558`, including
PR #361. Fix commit `2b5827c16` replaces the Codex model-prefix dependency
and adds three regression files plus verification records. Claude/OMP production
adapters are unchanged. Native Claude plugin investigation is evidence only.

Owner follow-up clarified a second pending source slice: six V3 preview roles
must no longer appear in install/update onboarding suggestions. Commit
`937720a7d` promotes the original local filter and regression tests. This was
absent from v8.7.2 and the initial candidate; the older V1/V2 config-panel filter
was already shipped and must not be confused with it. The new scope passed
188 update/RolePack/config-UI tests. Explicit installation, installed-role
updates and missing-source diagnostics remain intact. Final CI must include
this commit. The original workspace patch is preserved.

The original workspace and unrelated dirty changes remain untouched. Common
release metadata and platform-owned version pointers are separate changes;
the trusted-base ownership checker is not modified. Version 8.7.3 and tag
v8.7.3 were absent from npm and the remote at preparation time. Legacy local
v6.1.2/v6.1.3 tag conflicts were left untouched; main was fetched without tags.

## Local checks

- Python 3.12: 322 focused composer, FIFO, Claude start/poll/activation,
  reply-delivery and execution-service tests passed in 1.83 seconds.
- README/package version visibility and npm runner: 6 passed in 1.72 seconds.
- Bilingual release-note validator passed; manual review preserves matching
  issue references, upgrade requirements, deferred plugin and layout limits.
- `npm pack --dry-run --json`: version 8.7.3, 19 allowlisted files; no runtime
  homes, credentials, native-probe plugin or experimental IPC included.
- `git diff --check` passed.

Earlier real qualification covers 19 Claude jobs with one attempt each,
including three result chains and fixed-deadline/early-clear FIFO behavior.
The native API probe separately established important non-readiness limits;
it is not an additional real model communication pass.

## Preparation gates (completed below)

Remote Linux/macOS, lifecycle/provider blackbox, real platform, ownership and
package gates must finish before tagging. Confirm the combined common and
platform version identity, then verify GitHub artifacts/checksums, npm latest
and a clean public installation. Append receipts after completion; do not
infer publication from this preparation record.

CI follow-up: the first provider-blackbox and real-platform runs exposed a
stub layout mismatch. Its Codex footer lacked the blank separator present in
native captures. Commit `87fa25b19` corrects only the stub's spacing and cursor
position; 21 targeted stub/lifecycle/adapter checks passed (75 deselected).
The guard was not relaxed. Combined release/package checks passed 44 cases;
Linux candidate archive built successfully. Fresh CI is required on the update.

Local complete communication matrix passed mixed providers, broadcast, dual
Codex/Claude/Gemini, cross-project isolation and cleanup. An earlier harness
launch from the source cwd was rejected by `ccb_test` isolation checks; it was
stopped/cleaned through project control commands and rerun from an authorized
external cwd with caller/provider-home environment removed. The rejected run
is not counted as a pass.

## Final source and CI receipts

- Fix PR [#362](https://github.com/SeemSeam/claude_codex_bridge/pull/362)
  merged as `1988f3976136eedf4661bc96dd9f6f30d4c65578`.
- Common metadata PR [#363](https://github.com/SeemSeam/claude_codex_bridge/pull/363)
  merged as `ddf1b2c4d136f094e73684a114f3850882a7e0b4`.
- Platform metadata PR [#364](https://github.com/SeemSeam/claude_codex_bridge/pull/364)
  merged as `751a3a7271bc76b520107b13e82c0396dd21e9d1`.
- Annotated tag `v8.7.3` points to that final merge. Its tree is identical to
  qualified candidate `af48d0fa4cb788c27be9186aeb9521afc956fa26`.
- Fix-head [tests](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/36364358827)
  and [platform communication](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/36364358857)
  passed. Final candidate [tests](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/36364423766)
  and [platform communication](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/36364423834)
  also passed: Linux full suites 7475 passed, 11 skipped, 42 deselected;
  macOS 7367 passed, 119 skipped, 42 deselected; lifecycle 21 passed,
  7507 deselected. Provider blackbox, package install and Rust jobs passed.
- Ownership gates passed on each PR; retargeted #363 and #364 were also
  checked against their actual main base with the unchanged trusted checker.
  Their scopes were respectively non-platform and platform-only.
- Common-only duplicate runs `36364405435` / `36364405428` were deliberately
  cancelled to free runners; they are not passes. Combined-candidate gates
  qualify the complementary version changes. Superseded intermediate-main
  run `36365719632` was also cancelled after the final source was merged.
- The final candidate Linux archive reports 8.7.3. Direct imports from its
  extracted payload confirm all six preview roles are hidden while ordinary
  roles and `agentroles.ccb_self` remain available in recommendations.

## Public verification

Tag-triggered release runs all succeeded: artifacts `36365780301`, npm
`36365780228`, platform package `36365780328`, sidebar `36365780329`.

- [GitHub v8.7.3](https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v8.7.3)
  is public, not draft or prerelease, with all ten expected assets. The release
  body matches the committed English/Chinese notes (ignoring terminal newline).
- Downloaded Linux/macOS archives, APK and both mobile manifests pass
  `sha256sum -c SHA256SUMS`; the separate platform ZIP and sidebar checksums
  also pass. Mobile manifest reports 8.7.3 / 8070003; independent parsing of
  the downloaded APK's binary Android manifest confirms the same values and
  application ID `io.ccb.mobile.ccb_mobile`.
- [npm @seemseam/ccb 8.7.3](https://www.npmjs.com/package/@seemseam/ccb/v/8.7.3)
  is visible with `latest=8.7.3` and SLSA provenance metadata. An initial 404
  immediately after publication cleared after registry propagation.
- Fresh installation into an isolated prefix succeeds with process-local
  `NODE_OPTIONS=--use-env-proxy`; CLI reports `v8.7.3`, and the managed Python
  imports `aiohttp` / `cryptography`. No global install/config was changed.
- Both the downloaded archive and fresh npm payload pass direct six-role
  suppression checks while retaining `agentroles.coder` and `agentroles.ccb_self`.
  Installed `draft_observation.py` and `commands_runtime/update.py` exactly
  match tagged source.
- Remote annotated tag object `4eb0df52df222871ffdc93c33f49876eb14cb988`
  resolves to `751a3a7271bc76b520107b13e82c0396dd21e9d1`.

## Post-merge timing failure

The identical-tree main push run `36365751280`, after passing pre-tag
qualification, reported one macOS failure: `test_managed_pane_command_ignores_stale_socket_node`
exceeded its 15-second subprocess timeout. Other 7366 cases passed, 119 skipped,
42 deselected. All other jobs and main platform communication run `36365751326`
passed. The stale-socket test and implementation are unchanged by this release;
its shell loop performs 100 sleeps plus filesystem/process checks. Runner
latency is a hypothesis, not an established root cause. The two stale/fresh
socket tests pass locally (2 passed in 6.12s). Only failed jobs were rerun;
the rerun passed: 7367 passed, 119 skipped, 42 deselected in 1006.64s
(job `108756504721`, run attempt 2). Main's required test gate is successful.
The original timeout remains recorded; a passing rerun does not establish its
root cause. Documentation receipt PR #365 also passed full tests
(`36367638166`), platform communication (`36367638127`) and ownership
(`36367637555`) before this final result-only update. No runtime code changed.

## Cleanup and live environment

Temporary test projects were stopped through CCB; final process inspection
found no running process using the release verification root or the identified
temporary resume-test project. Public downloads, isolated npm install and test
venv under `/var/tmp/ccb-release-873-FiFtaQ` are moved to recoverable desktop
trash after verification. The isolated source checkout and durable receipts
remain available. The original dirty source workspace and business panes were
preserved; no live installation upgrade, daemon restart or issue reply occurred.
