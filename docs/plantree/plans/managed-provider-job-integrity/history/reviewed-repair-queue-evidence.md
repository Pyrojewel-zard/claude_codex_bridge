# Reviewed Repair Queue Evidence

Date: 2026-07-21
Goal: [Reviewed Repair Queue Closure](../goals/reviewed-repair-queue-closure-goal.md)

This compact ledger records one accepted evidence block per verified repair
slice. Large or runtime-specific artifacts stay outside active PlanTree files
and are linked here when created.

## R3: Inbound Completion Routing Documentation

Slice: R3 inbound completion routing documentation

Commit selector / hash: commit subject `docs: correct inbound completion
routing` with trailer `Repair-Slice: R3`

Upstream items: PR264 at unchanged reviewed head `1d4d1deb`

Baseline: `0d145aa3` on `origin/main` `aed27abf`; PR264 remained open and
`unstable` during the 2026-07-21 preflight.

Counterexample: with only the corrected static assertions added, the focused
gate reported `4 failed, 14 passed`. The failures proved that projected ask
templates and generated runtime memory did not distinguish registered-agent
lineage from direct CLI control output, and the user guide did not require
rematerialization followed by restart/new session for providers without hot
reload.

Focused tests: `test/test_ask_skill_templates.py` plus
`test/test_project_memory.py`: `18 passed`.

Full/client tests: no runtime logic, schema, Rust, sidebar, mobile, or client
surface changed. The cumulative R11 provider-hook/profile/launcher gate passed
`282` tests. Changed Python files compiled successfully and
`git diff --check` passed.

Real project evidence: not required for this documentation/materialization-only
slice.

Source immutability: no provider source was read or projected by the R3 gate.

Cleanup: no CCB runtime project, socket, provider process, or tmux pane was
opened.

Remaining risk: already-running provider sessions retain cached instructions
until runtime memory is rematerialized and the provider hot-reloads it or is
restarted/reopened as documented.

Next unlocked row: R4 cancellation and callback terminalization.

## R4: Cancellation And Callback Terminalization

Slice: R4 cancellation and callback terminalization

Commit selector / hash: commit subject `fix: terminalize cancelled callback
chains` with trailer `Repair-Slice: R4`

Upstream items: PR266 at unchanged reviewed head `3e11523c`; Issue263 remained
open during the 2026-07-21 preflight.

Baseline: R3 commit `40e412653840cf346bb7e7b191f833318a0bf778` on
`origin/main` `aed27abf`; PR266 remained open and `unstable`.

Counterexample: with the six preserved R4 tests added before the runtime
repair, the focused gate reported `5 failed, 1 passed`. The failures proved
that empty cancellation had no durable control notice, chain-child
cancellation left its callback edge pending, a pre-existing mailbox gained an
empty reply, completion could be overwritten by cancellation, and
trace/ProjectView did not expose the zero-depth notice policy.

Focused tests: message-bureau dispatcher integration `83 passed`; control
queue `15 passed`; ProjectView `82 passed`; dispatcher `61 passed`; cancel
flags `2 passed`; communication recovery `12 passed`. The cumulative R11/R3
provider projection and instruction gate passed `300` tests.

Full/client tests: the complete Python remainder passed `5261` tests with `2`
skipped and the single lifecycle-stopping socket race deselected. The exact
race reproduced on `origin/main` `aed27abf` at the same final socket operation
(`ConnectionResetError` / `CcbdClientError`), satisfying the goal's baseline
adjudication rule. No Rust, Flutter, sidebar, or mobile schema changed.

Real project evidence: external mounted fake-provider project
`/home/bfly/yunwei/test_ccb2/r4-cancel-runtime-20260721-fkyoH9`; result artifact
`r4-runtime-result.json`. Callback edge `cb_6995f5eefed5` reached `done`, its
cancelled child produced one reply and continuation `job_d3476f1ddcd6`, and
ordinary cancelled job `job_c5a7e70dc1e7` produced one consumed completion
notice while caller depth and pending replies remained zero.

Source immutability: the candidate binary diff SHA256 remained
`481874ea96406a0c989032c25edbe9ecd7ea780b84495d24141c26985af5bfe9`
before and after the mounted run; the untracked-set SHA256 remained
`dc61b15cfea4f14edc27267bc5f420115db7db79018491c17034c4cc1a4018ac`.

Cleanup: candidate `ccb_test kill` returned the external project to
`unmounted`; the ccbd and tmux sockets were absent and the recorded keeper and
daemon PIDs no longer existed.

Remaining risk: the pre-existing lifecycle-stopping socket teardown race
remains outside R4. Provider-native cancel is still best-effort, but terminal
lineage, callback continuation, repeat idempotency, and completion-race
authority now fail closed around the first persisted terminal job.

Next unlocked row: R5 Claude queued-prompt activation.

## R5: Claude Queued-Prompt Activation

Slice: R5 Claude queued-prompt activation

Commit selector / hash: commit subject `fix: bind Claude queued prompts to
activation` with trailer `Repair-Slice: R5`

Upstream item: PR259 remained open at unchanged reviewed head `c4bd9427` and
reported `UNSTABLE` during the 2026-07-21 preflight.

Baseline: R4 commit `38645d475ab2283ee88bd11531727d8f2e7319ad` on
`origin/main` `aed27abf`.

Counterexample: with seven preserved R5 tests added before the runtime repair,
the focused gate reported `7 failed`. The failures proved pane dispatch and
enqueue synthesized activation too early, old main/subagent/tool-only output
could bind the queued job, exact multi-prompt replay was not required, queue
state did not survive restart/rotation correctly, and pre-activation hook
output could terminalize the new job.

Frozen authority: [Decision 002](../decisions/002-claude-queued-prompt-activation.md)
separates enqueue, bare dequeue observation, exact activation, and anchoring.
Only a normal top-level user prompt or exact
`attachment/queued_command.prompt` carrying the current outer request ID may
activate; tool-result, meta, subagent, assistant, system, hook, pane-idle, and
API-error records are fenced before that point.

Focused tests: all Claude-specific files passed `98` tests. The combined
Claude/execution-service/message-bureau gate passed `260` tests. The cumulative
R11/R3/R4 provider projection, instruction, dispatcher, control-queue,
ProjectView, cancel, and recovery gate passed all `555` collected tests.

Full/client tests: the first complete run reached `5269 passed`, `2 skipped`,
and the one adjudicated lifecycle-stopping socket-race deselection before the
unrelated `restart_replay_pass` fake-runtime scenario missed terminal scheduler
authority after 96 activations. The exact scenario immediately passed alone
(`1 passed in 33.09s`). A second complete remainder, deselecting that
independently green scenario and the existing socket race, passed `5269`
tests with `2 skipped` and `2 deselected` in `951.69s`. No Rust, Flutter,
sidebar, or mobile consumer changed.

Real project evidence: external opened Claude project
`/home/bfly/yunwei/test_ccb2/r5-claude-queue-runtime-20260721-RyGaHI` used
Claude Code 2.1.206 with displayed model `DeepSeek-V4-pro`. While
`sleep 25; echo OLD_TURN_SENTINEL` was visibly running, CCB submitted
`job_aadf1ff01a30`. Persisted activation state recorded enqueue, exact
activation source UUID `6c43ca6c-6d05-4ccf-a984-8a5c74902706`, and one
anchor. One attempt and one reply completed with observed reason
`assistant_end_turn`; the reply was exactly `NEW_QUEUED_SENTINEL_2` and did
not contain the old sentinel. Compact artifact: `r5-runtime-result.json` in
that external project.

Source immutability: candidate binary-diff SHA256 remained
`7a5f721b34fce861551700524338a90468faba31361777727bf290044aa54df2`
before and after the mounted run; the untracked-set SHA256 remained
`1ccb87128ffec34330cbbf0afa30fa5f2bc91ce31cd923c17e1e90033bbf3b11`.

Cleanup: candidate `ccb_test kill` returned `kill_status: ok` and left the
project `unmounted`. The ccbd and tmux sockets were absent, and recorded keeper
PID 708543, daemon PID 708595, and Claude PID 708960 no longer existed.

Remaining risk: the exact replay contract depends on Claude retaining its
current `attachment/queued_command.prompt` record. Unknown future record
shapes fail closed and leave the job pending rather than accepting old output.
The unrelated restart-replay fake-runtime timing miss remains a test-harness
flakiness signal; its exact isolated pass is recorded rather than hidden.

Next unlocked row: R6 Kimi exact-session resume.

## R6: Kimi Exact-Session Resume

Slice: R6 Kimi exact-session resume

Commit selector / hash: commit subject `fix: resume exact Kimi sessions` with
trailer `Repair-Slice: R6`

Upstream item: PR258 remained open at unchanged reviewed head `d119bf18` and
reported `UNSTABLE` during the 2026-07-21 preflight.

Baseline: R5 commit `bc31832e8b53030f3cfb1750c3fc4ed8b5267e64` on
`origin/main` `aed27abf`. Kimi 1.47.0 exposed exact `--session`/`--resume` and
workdir-global `--continue`; an isolated fresh-share probe reproduced
`--continue` exiting 2 with `No previous session found`.

Counterexample: the three preserved R6 behavior tests failed before production
changes because exact restart selection was absent, explicit-session
precedence had no recorded state, and the session payload did not retain a
native binding. The first live candidate then exposed a deeper restart-path
counterexample: `ccb restart kimi1` reused the original fresh `start_cmd`, the
visible Kimi pane opened a different native UUID, and the CCB record still
claimed the old binding. That external project was stopped cleanly before the
restart-command preparation repair.

Frozen authority: [Decision 003](../decisions/003-kimi-exact-session-ownership.md)
binds a native Kimi session only after the target agent's exact CCB request is
observed in that session. First launch never guesses `--continue`; restart
validates project, agent, workdir, share root, exact non-symlinked native
layout, persisted command template, and current long-option capability before
selecting the owned ID. Invalid or unsupported authority clears only the
carried binding and starts fresh. Explicit user session controls win.

Implementation: Kimi launch payloads now record the share root, a single
exact-session command-template insertion point, capability command parts,
explicit-control state, and only a validated native binding. Native-log polling
records the observed UUID/path against the matching CCB launch record and
rejects stale executions. Manual and dead-pane restart materialize only the
validated exact selector; missing, malformed, mismatched, symlinked, drifted,
or unsupported authority rewrites the control record to a documented fresh
state without deleting provider data. The CCB pane-launch ID is never treated
as a Kimi session ID.

Focused tests: Kimi session/launcher behavior passed `45` tests. The broader
Kimi/native/restart gate passed `120` tests. Expanded launch, completion,
runtime binding, health, registry, and restart integration passed `193` tests.
Python compilation, Pyflakes, and `git diff --check` passed.

Full/client tests: the complete Python remainder passed `5455` tests with `2`
skipped and `2` deselected in `936.97s`. The independently deselected
`restart_replay_pass` fake-runtime case passed alone (`1 passed` in `31.92s`).
The other deselection is the lifecycle-stopping socket race already reproduced
on frozen `origin/main`. No Rust, Flutter, sidebar, mobile, or serialized client
schema changed in R6.

Real project evidence: external opened project
`/home/bfly/yunwei/test_ccb2/r6-kimi-exact-runtime2-20260721-9hlXai` used Kimi
CLI 1.47.0, displayed model `kimi-for-coding`, and two agents in one in-place
workdir. Both first-launch records were `fresh_no_binding` with no implicit
session selector. Jobs `job_3c43dfe74b89` and `job_46bb9eb26703` produced
distinct observed native UUIDs `cdd2735e-4adc-4e7a-baa7-0e76b66ac9de` and
`d22e3fa2-3331-42b2-b23a-f55c8a78034b`. CCB-controlled restart commands and
visible Kimi pane headers selected those same respective UUIDs. Continuation
prompts did not contain the hidden tokens; jobs `job_130ed2ccd6d3` and
`job_f11970359882` returned only `ALPHA_7A21` and `BETA_9B34`, proving both
continuity and no cross-agent resume. After a clean stop, the exact final
candidate remounted both original UUIDs with one selector per command; jobs
`job_f48cde3fddc9` and `job_4f357e3e3a31` again returned `ALPHA_7A21` and
`BETA_9B34`. Compact artifact: `r6-runtime-result.json` in that external
project. The acceptance operator did not directly inspect Kimi credentials or
native conversation content; CCB's existing completion reader necessarily
consumed the target workdir's native turn log.

Source immutability: candidate binary-diff SHA256 remained
`52131e6a195b59ea29c34b4c73459961fdf51080b0c35a0c33e59ea0e0c9e65b`
before and after the mounted run; the untracked-set SHA256 remained
`96bae5616cba9544958ce825a89cff6729cce1a993f4278241e0d105daa928b2`.

Cleanup: candidate `ccb_test kill` returned `kill_status: ok` and left the
project `unmounted`. The ccbd and tmux sockets were absent, and recorded keeper
PID 4063913 no longer existed. The earlier counterexample project was also
cleanly unmounted.

Remaining risk: exact restart depends on the configured Kimi executable
continuing to expose a stable long selector and the documented share/session
layout. Capability or layout drift fails fresh rather than guessing. Explicit
user session controls can intentionally choose broader native behavior. Kimi
still does not support restoration of an interrupted in-flight CCB job.

Next unlocked row: R7 correlated execution-state model.

## R7: Correlated Execution-State Model

Slice: R7 correlated execution-state model

Commit selector / hash: commit subject `feat: expose correlated execution
phases` with trailer `Repair-Slice: R7`

Upstream items: PR265 remained open at unchanged reviewed head `2b79d68b` and
reported `UNSTABLE`; Issue262 remained open during the 2026-07-21 preflight.

Baseline: R6 commit `12a67d6265892f07ee58d72ff3fcc15d9f6d611d` on
`origin/main` `aed27abf`. PR265 lacked queue, CLI, Rust sidebar, mobile, exact
identity joins, and explicit contradictory-evidence behavior.

Counterexample: preserved fixtures prove wrong job, attempt, inbound event,
mailbox head/active id, lease, agent, completion snapshot, provider, pane, and
stale activity cannot produce a confident non-terminal phase. A completion
anchor without provider-native evidence also remains `unknown`; terminal
authority wins over lagging active mailbox/lease state.

Frozen authority: [Decision 004](../decisions/004-correlated-execution-phase-schema.md)
defines the additive schema-v1 vocabulary `queued`, `injecting`, `executing`,
`provider_idle_pending_terminal`, `reply_queued`, `reply_delivering`,
`orphaned`, `terminal`, and `unknown`. Exact correlated workflow and provider
identity are required; clients fall back to legacy labels only when the field
is absent. The projection is diagnostic and never mutates or recovers a job.

Implementation: one pure resolver consumes immutable evidence assembled by
ProjectView and structured queue producers. ProjectView reads exact
job/attempt/inbound/mailbox/lease/completion/reply and current provider
evidence; queue intentionally fails closed when it cannot observe provider-
native identity. CLI retains mailbox state separately, Rust and mobile prefer
the optional phase with legacy fallback, and maintenance may surface an
existing blocked-communication concern without introducing recovery.

Focused tests: the cumulative execution-phase, ProjectView, queue,
maintenance, dispatcher, and mobile-gateway gate passed `334` tests in
`9.23s`. The final renderer fallback assertion passed in a `25`-test focused
gate. Python compilation and `git diff --check` passed; Pyflakes found only the
pre-existing unused local at
`test/test_v2_message_bureau_dispatcher_integration.py:3108`.

Full/client tests: Rust formatting passed and all `78` sidebar tests passed.
Flutter formatting passed, the `5` focused model/fixture tests passed,
`flutter analyze` reported no issues, and all `659` Flutter tests passed. The
corrected complete Python run passed `5335` tests with `2` skipped and `2`
deselected in `1101.49s`. The isolated `restart_replay_pass` scenario passed
(`1 passed in 32.97s`); the other deselection is the lifecycle-stopping socket
race already adjudicated on the frozen baseline. An earlier full run's `36`
provider projection failures were proven to be a harness error from forcing
`CCB_SOURCE_HOME`: all implicated provider files passed `178` tests after the
global override was removed, and the corrected full run was clean.

Real project evidence: external opened project
`/home/bfly/yunwei/test_ccb2/r7-execution-phase-runtime-20260721-cCTNQC` used
the candidate worktree wrapper, inherited real provider state, Claude Code
`2.1.206`, binary
`/home/bfly/.local/share/claude/versions/2.1.206`, and displayed model
`DeepSeek-V4-pro`. While exact job `job_c916976bdeb2`, attempt
`att_332a5466dfad`, and inbound event `iev_20fc6a1723da` visibly ran a
30-second Bash sleep, queue reported `unknown/provider_identity_mismatch`
because it had no provider-native evidence, while ProjectView joined the exact
lineage and current pane/session as `executing/provider_active`. The job then
became `terminal/job_completed` with one attempt, one reply, no recovery, and
reply text exactly `R7_PHASE_DONE`. Compact artifact: `r7-runtime-result.json`
in that external project.

Source immutability: candidate tracked-diff SHA256 remained
`b0061e5c57bbb28c12e805059f46f44ef8e578fabb8a33b4a532dcd6368b05f1`
before and after the mounted run; the untracked-set SHA256 remained
`b4ef4174c0c1f230efd88ab80b3ac3e1419c87f99bfdc481724a113b63044568`.

Cleanup: candidate `ccb_test kill` returned the external project to
`unmounted`; ccbd and tmux sockets were absent, and recorded keeper PID
1162501, daemon PID 1162694, and provider PID 1164751 no longer existed.

Remaining risk: queue does not own provider-native evidence and therefore may
show `unknown` for an anchored active request that ProjectView can prove is
`executing`; this is deliberate fail-closed behavior. `orphaned` remains a
diagnostic phase only. R8 must add bounded observation without turning phase
projection into automatic restart, resend, cancellation, or terminalization.

Next unlocked row: R8 stuck inbound detection.

## R8: Stuck Inbound Detection

Slice: R8 stuck inbound detection

Commit selector / hash: commit subject `feat: diagnose orphaned active
inbounds` with trailer `Repair-Slice: R8`

Upstream item: Issue260 remained open and unchanged since 2026-07-18 during
the 2026-07-21 preflight. Its requested first step was a non-destructive
diagnostic; automatic cancel, retry, restart, resend, lease release, and
terminalization remained out of scope.

Baseline: R7 commit `56f8dcdad8c2e88a3c7df8d5dc0abcf375e10aa3` on
`origin/main` `aed27abf`. A single exact idle-pane capture previously promoted
the active job directly to `orphaned`, so terminal publication lag could be
misdiagnosed as a recoverable stuck job.

Counterexample: the preserved exact-idle integration fixture failed before
production changes because its first capture immediately returned
`blocked/orphaned`. The corrected fixture proves first observation and cache
hits stay `provider_idle_pending_terminal`, the same exact identity becomes
`orphaned` only after the fixed window, and job/attempt/inbound/mailbox/lease/
completion/runtime records remain unchanged. Progress or terminal evidence,
missing evidence, job disappearance, signature change, binding rotation, and
service restart reset the in-memory observation. Existing fixtures retain
wrong attempt/inbound/mailbox/lease, queued prompt, stale/wrong pane, active
reasoning/tool, and fresh-idle guards.

Frozen authority:
[Decision 005](../decisions/005-bounded-orphaned-inbound-diagnosis.md) requires
the already eligible running Claude job to present the same exact active
lineage and current pane/session/workspace/generations twice at least 30
seconds apart. Missing or changing facts fail closed. The diagnostic is
service-local, read-only, and carries
`recommended_action=explicit_comms_recover` with `automatic_action=none`;
explicit recovery remains a separate authority-revalidating operator action.

Implementation: ProjectView owns a bounded in-memory tracker keyed by exact
lineage and runtime signature. It retains R7's
`provider_idle_pending_terminal` phase until confirmation, then emits
`orphaned_active_inbound` with exact ids, state, provider evidence, observation
window, and manual recovery target. Tracker state resets on evidence loss or
rotation and is pruned when a job leaves the projection; cached responses do
not advance it. Maintenance preserves the same envelope in concern evidence,
trace merges it only for matching resolved jobs, doctor reuses its existing
daemon client to list current envelopes, CLI renderers preserve the fields,
and the Rust sidebar deserializes and displays the optional condition without
triggering action. Diagnostics and sidebar contracts document the same
no-mutation boundary.

Focused tests: the final ProjectView, execution-phase, maintenance, trace,
doctor, CLI, service-graph, recovery, and message-bureau gate passed `308`
tests in `5.07s`. Python compilation and `git diff --check` passed. Rust
formatting passed and all `79` sidebar tests passed.

Full tests: the complete Python run passed `5340` tests with `2` skipped and
`2` deselected in `975.68s`. The isolated `restart_replay_pass` fake-runtime
scenario passed (`1 passed in 32.69s`); the other deselection is the previously
adjudicated lifecycle-stopping socket race.

Real project evidence: external opened project
`/home/bfly/yunwei/test_ccb2/r8-orphaned-inbound-runtime-20260721-B1KYSq`
used the candidate wrapper, inherited real provider state, Claude Code
`2.1.206`, binary `/home/bfly/.local/share/claude/versions/2.1.206`, displayed
model `DeepSeek-V4-pro`, and a lab-local roles store. A controlled 600-second
daemon poll interval left completion publication unconsumed after the real
provider visibly returned idle with reply `R8_PROVIDER_RETURNED_IDLE`; an
early poll while `sleep 30` was active had already persisted the exact request
anchor as non-terminal. Job `job_79a0203ed50d`, attempt
`att_5ba2dddff7f3`, inbound `iev_6450d24d1514`, mailbox active id, acquired
lease, completion anchor, runtime binding, and idle pane identity joined
exactly. The first ProjectView observation stayed
`provider_idle_pending_terminal` and non-recoverable. The unchanged second
observation emitted `orphaned_active_inbound` after `59.035s`; trace and doctor
rendered the same ids, required `30.0s` window, manual recommendation, and
`automatic_action=none`.

No-mutation evidence: SHA256 values for job ledger, runtime, attempts,
execution state, lease, inbox, mailbox, messages, absent reply ledger, and
completion snapshot were identical before and after ProjectView, trace, and
doctor observations. No recovery was invoked. Compact artifact:
`r8-runtime-result.json` in the external project. A preceding external run at
`/home/bfly/yunwei/test_ccb2/r8-orphaned-inbound-runtime-20260721-qnWCLY`
hit the terminal race before confirmation; R8 returned `terminal/hook_stop`
with zero diagnostics, providing a live false-positive guard.

Source immutability: candidate tracked-diff SHA256 remained
`0b0761de30bfbed7596d811c71fdece1119fe49e7ed8a7b477c9766b57ce8a42`
before and after the mounted run; the untracked-set SHA256 remained
`714033875d04261b29db4bf8e0d6232b4082d5bbd277b2e060e70347a891d0b4`.

Cleanup: candidate `ccb_test kill` returned the accepted project to
`unmounted`; ccbd and tmux sockets were absent, recorded keeper PID 3685371
and daemon PID 3685374 were absent, and no process retained the project path.
The two earlier observation/terminal-race projects were also cleanly
unmounted.

Remaining risk: the exact-idle predicate is intentionally Claude-only until
another provider supplies an equivalent native proof. Observation progress is
lost on daemon/service restart, so diagnosis may be delayed but cannot inherit
stale suspicion. The feature recommends explicit recovery but does not make
that action safe without its existing invocation-time authority checks.

Next unlocked row after this atomic commit: R9 active-job correction
capability.

## R9: Active-Job Correction Capability

Slice: R9 active-job correction capability

Commit selector / hash: commit subject `feat: steer exact active jobs` with
trailer `Repair-Slice: R9`

Upstream item: Issue261 remained open during the 2026-07-21 preflight. PR264
documents explicit cancel/resubmit but does not provide exact active-turn
steering, so it was not treated as an implementation of this issue.

Baseline: R8 commit `e937aa99b2586565a33638818867b3f425cba2f2` on
`origin/main` `aed27abf`. Existing pane transport addressed an agent surface,
not an exact job/turn, and could neither atomically reject a stale turn nor
prove that accepted input belonged to the currently bound job.

Counterexample: wrong/stale/non-running jobs, a starting submission, queued
siblings, stale expected turns, completion and cancellation races, service
restart, duplicate follow-up ids, ambiguous WebSocket delivery, unsupported
providers, and local-fallback Codex all fail closed in preserved tests. An
initial real Codex launch additionally reproduced `path must be shorter than
SUN_LEN`: the overlong project-local app-server socket forced local fallback
and correctly advertised no remote capability. The corrected placement uses
the bounded shared runtime-socket root and a hash of the full provider runtime
directory.

Frozen authority:
[Decision 006](../decisions/006-exact-active-job-followup.md) defines
`ccb followup <active_job_id> --message ...`, append-only accepted outbox
ordering, native follow-up idempotency, explicit accepted/injected/rejected/
too-late/terminal outcomes, and the existing job terminal authority. Only a
visible managed Codex TUI sharing the slot-owned app-server qualifies, and
only `turn/steer` with the exact `threadId`, `expectedTurnId`, and
`clientUserMessageId` may inject. Claude panes, legacy/local Codex, and
unadvertised providers refuse; pane input, cancel/resubmit, retry, or provider
substitution are not implicit fallbacks.

Implementation: the CLI/socket/dispatcher path writes one globally stable FIFO
outbox keyed by follow-up id and never creates a job, attempt, mailbox item, or
callback. Restart replay stops at ambiguous accepted delivery so later entries
cannot overtake. Execution state commits and injection are serialized while
slow provider polling/startup stays outside the lock and stale results are
discarded by exact identity. Managed Codex supervises a slot-owned app-server,
attaches the visible TUI with `--remote unix://...`, speaks the local RFC6455
WebSocket protocol, and requires a matching runtime-owned remote marker. Long
socket paths use a deterministic short placement. Project stop repeats exact
socket/pid/marker cleanup after process termination so a forcibly terminated
bridge cannot leave false capability evidence. Trace joins follow-up lineage
but redacts correction text from all public/terminal records; only the durable
accepted row retains it for replay.

Focused tests: final exact-job, FIFO, restart, ambiguity, race, CLI, trace,
managed app-server, capability-marker, short-socket, execution-lock, and
stop-flow gates all passed. The late marker/outbox gate passed `243` tests, the
short-socket/runtime gate passed `164`, and the final stop/kill/follow-up gate
passed `41` tests in `4.64s`. Python compilation and `git diff --check` passed.

Full/client tests: the final complete Python run passed `5518` tests with `2`
skipped and no deselections in `1043.10s`. R9 changes no Rust/sidebar/mobile
schema or consumer, so those client suites are deferred to cumulative R10
rather than claimed here.

Real project evidence: external opened project
`/home/bfly/yunwei/test_ccb2/r9-active-followup-real-20260721` used the
candidate wrapper, inherited real provider state, and a lab-local roles store.
Codex CLI `0.144.6`, model `gpt-5.6-terra`, effort `low`, bound exact job
`job_861c7eecd75f`, attempt `att_5cedce6c4c2c`, thread
`019f8439-498a-70a2-8fcb-98e729c424c8`, and turn
`019f843d-e252-7591-9656-2072d81bf287`. Follow-up
`fup_460885d08eee` persisted `accepted` then became `injected` through
`codex_app_server_turn_steer` with identical expected/provider turn refs. The
same single job and attempt completed with reply exactly `R9_CORRECTED`.
Terminal follow-ups returned `too_late/job_already_completed`; the native
session remained 27 lines at SHA256
`c5d9be310d2149d386503179c80bf41a78225bc8fc0d45cfa895a61ff6309f63`,
and neither late text entered it. Public trace omitted correction request text
while retaining the final reply and full job/message/attempt lineage.

The same project ran Claude CLI `2.1.206`, model `deepseek-v4-pro`, on active
job `job_4b8805deeddc` and attempt `att_87dea91fc645`. Follow-up
`fup_4843000d78e4` returned
`rejected/claude_tui_missing_atomic_active_turn_precondition` with no pane
fallback. The correction text appeared in neither provider session nor pane;
the original single job/attempt completed with reply exactly `CLAUDE_DONE`.
Compact artifact: `r9-runtime-result.json` in the external project. Durable
raw follow-up lineage remains in `.ccb/ccbd/active-followups.jsonl` there.

Source immutability: the main real job run retained complete candidate digest
`4805bd4b89316d8b94fb1146d21af73d83c70260d3d86ba43b5e5500833b11d0`
before and after. That run exposed the stop-path marker residue, which was
fixed and retested. On the final code, a fresh real managed app-server start
and stop retained complete digest
`52e6d46bdc2e8bbc899b260a9a965a0c3c306cfe4d09bf2b41fbb0d86c220475`
before and after.

Cleanup: the first accepted injection run cleanly stopped every recorded
process and socket but exposed one stale `app-server.remote` marker; that run
was not accepted as final cleanup evidence. After the stop-path fix, repeated
real starts produced the 59-byte owned socket
`/run/user/1000/ccb-runtime/app-server-ae002bb6e6eefd01.sock` and matching
marker. Candidate `ccb_test kill` returned `kill_status: ok`, left the project
`unmounted`, and removed ccbd/tmux/app-server sockets, app-server pid, remote
marker, keeper/daemon/provider processes, and panes.

Remaining risk: Codex CLI app-server protocol or `--remote` capability may
change in a later native release; the executable/version capability probe,
WebSocket readiness, marker match, and exact expected-turn precondition then
fail closed. Transport ambiguity intentionally leaves the durable accepted
row pending instead of claiming rejection or retrying. Claude remains
unsupported until it exposes an equivalent atomic exact-turn primitive.

Next unlocked row after this atomic commit: R12 generic projected-asset
ownership hardening.

## R12: Generic Projected-Asset Ownership Hardening

Slice: R12 generic projected-asset ownership hardening

Commit selector / hash: commit subject `fix: require projected asset
ownership` with trailer `Repair-Slice: R12`

Upstream item: internal follow-up from the completed provider-extension audit.
No pull request or issue was mutated. R11-C Copilot projection remained
deferred until this shared ownership predicate was verified.

Baseline: R9 commit `653be92154872e7a706d8b429c739bbd4fec150e` on
`origin/main` `aed27abf`. The three remaining production bypasses were packaged
inherited skills (currently consumed by Kimi), Claude skills/commands, and
Droid skills. The shared predicate accepted any marker file and could replace
an unmarked content-identical directory.

Counterexamples: preserved tests cover unmarked different and identical
directories, foreign symlinks, exact-source legacy symlinks, foreign,
malformed, wrong-schema, wrong-label, wrong-mode, empty-source, and symlinked
markers, target-absent marker conflicts, marker-write rollback, disabled and
source-missing cleanup, and valid owned refresh. Provider regressions prove
unmarked Claude skills/commands, Droid skills, and packaged Kimi skills remain
user-owned; Kimi does not activate the conflicting packaged root.

Frozen authority:
[Decision 007](../decisions/007-marker-first-projected-asset-ownership.md)
requires a local regular schema-v1 `ccb_projected_asset` marker with the exact
consumer label, non-empty source, and recognized mode. Only a markerless
symlink already resolving exactly to the current source may be adopted, and
its inode is retained. Foreign markers block even when the target is absent.
The compatibility `allow_unmarked_replace` keyword grants no replacement or
cleanup authority.

Implementation: the shared router validates marker ownership before any
mutation, removes only valid same-label owned targets, and rolls back only a
candidate created by the current call when marker creation fails. Exact-source
legacy symlinks receive a marker in place. All remaining production
`allow_unmarked_replace=True` calls were removed from packaged inherited
skills, Claude, and Droid. Storage, Claude isolation, Kimi integration, and
developer contracts now state the same marker-first rule.

Focused/full tests: the final generic/provider/RolePack/storage gate passed
`399` tests in `5.88s`. The complete Python suite passed `5536` tests with `2`
skipped and no deselections in `1067.43s`. Python compilation and
`git diff --check` passed. R12 changes no Rust/sidebar/mobile schema or
consumer, so client suites remain part of cumulative R10 rather than being
claimed here.

External candidate evidence: project
`/home/bfly/yunwei/test_ccb2/r12-projected-assets-20260721` used
`/home/bfly/yunwei/ccb_worktrees/unified-provider-extension-inheritance/ccb_test`,
an isolated source home, and the source-test fake provider; no provider login
or credential access occurred. Config validation passed. The interactive
start could not attach because the calling terminal lacked clear-screen
support, but candidate `doctor` proved the already-started backend was
`mounted`, `healthy`, socket-connectable, and running from the candidate
implementation root.

External materialization: isolated Claude and Droid source homes plus the
candidate packaged Kimi source exercised the production consumers. Unmarked
user targets were preserved, packaged source entries were not copied into
them, Kimi omitted its conflicting managed root, exact legacy symlink adoption
retained the symlink inode, and valid owned refresh/cleanup passed. Claude,
Droid, and Kimi source SHA256 values were identical before and after. Compact
artifact: `r12-runtime-result.json` in the external project.

Cleanup: candidate `ccb_test kill` returned `kill_status: ok` and
`state: unmounted`. The ccbd socket was absent, recorded daemon PID `2915851`
and keeper PID `2915798` were absent, and post-cleanup doctor reported
`ccbd_state: unmounted`, `ccbd_health: unmounted`, and a destroyed namespace.

Remaining risk: a valid same-label marker is explicit local ownership
authority; consumers must therefore keep labels stable and must not create
such markers for user-owned targets. The compatibility keyword remains in the
Python signature for callers but is deliberately inert and may be removed in
a later API cleanup.

Next unlocked row after this atomic commit: R11-C Copilot plugin/config
projection.

## R11-C: Copilot Plugin/Config Projection

Slice: R11-C Copilot plugin/config projection

Commit selector / hash: commit subject `feat: inherit Copilot plugins safely`
with trailer `Repair-Slice: R11-C`

Upstream item: deferred R11 remainder after merged PR257. No pull request or
issue was mutated.

Baseline: R12 commit `a41627a7f47ecc8827626b9593162676cfccc885` on
`origin/main` `aed27abf`. Current GitHub Copilot CLI documentation and the
offline Copilot CLI `1.0.61` fixture established that automatically managed
`config.json` mixes `installedPlugins` with authentication/application state,
while installed files, permissions, sessions, plugin data, MCP state, and
marketplace cache have separate ownership.

Counterexamples: tests preserve source/target authentication and application
fields, settings, permissions, sessions, plugin data, unmarked target trees,
foreign/malformed/symlinked markers, metadata and tree-content divergence,
local metadata deletion, missing/malformed source, malformed target entries,
path escape, root/nested symlinks, transaction failure, explicit profile and
hard-role opt-out, source removal, direct installs, and two-agent isolation.
The external fixture initially retained its old absolute `cache_path`; the
candidate correctly failed closed with no target files until the path was
rebased inside the current source root.

Frozen authority:
[Decision 008](../decisions/008-copilot-entry-owned-plugin-seed.md) permits
only validated, allowlisted `config.json.installedPlugins` metadata and the
exact corresponding installed tree. Stable identity, aggregate ownership,
per-tree marker ownership, and the last-installed content fingerprint govern
refresh/removal. Metadata deletion creates a persistent opt-out tombstone;
metadata or tree divergence transfers ownership. Missing/malformed source
preserves the last good state, while an explicit empty source list removes
only unchanged owned entries.

Implementation: `prepare_provider_workspace` invokes the Copilot materializer
before launch. It validates marketplace/direct layouts and plugin manifests,
rejects escaping or symlink-bearing input, rebases `cache_path`, copies local
writable trees, and transactionally commits config, aggregate marker, tree
markers, and trees with rollback. It never projects auth, settings,
permissions, sessions, plugin data, MCP state, or cache. Interactive and
headless launch paths both set agent-local `COPILOT_HOME` and
`COPILOT_CACHE_HOME`; storage classification treats mixed `config.json` as
secret, installed plugin projection as projected config, plugin data as
session state, and `data/cache/` as rebuildable cache.

Focused/full tests: the final Copilot ownership gate passed `22` tests in
`0.23s`. The cumulative projected-asset/provider-profile/source-home/native-
CLI/runtime/storage gate passed `426` tests in `57.63s`. The complete Python
suite passed `5547` tests with `15` conditional skips and no failures in
`648.61s`. Python compilation and `git diff --check` passed. R11-C changes no
Rust/sidebar/mobile schema or consumer, so those suites remain part of R10.

External candidate evidence: project
`/home/bfly/yunwei/test_ccb2/r11c-copilot-plugin-20260721` used the candidate
source wrapper, isolated `HOME`/`CCB_SOURCE_HOME`, and a fake mounted provider;
no provider login or credential access occurred. Config validation passed and
candidate `doctor` proved a healthy mounted backend running from the candidate
implementation root. The offline binary identified itself as GitHub Copilot
CLI `1.0.61` and native `copilot plugin list` discovered
`ccb-fixture-plugin@ccb-fixture-marketplace (v1.0.0)` from both isolated homes.
Each config pointed only to its own local installed tree.

Source immutability and local ownership: the complete source-home fingerprint
was `8b3e07748423f91078a8234a240f047cdbc6037d0a0c253a58fe8fb25f741e9a`
before and after. After agent1 locally changed the projected skill, repeat
materialization preserved plugin-tree fingerprint
`92f3df48181aa04963cb97e57fc33377f6ced79c70baa047adde5c60b9ca5451`
and removed both aggregate and tree ownership markers; native plugin discovery
still succeeded. Compact artifact: `r11c-runtime-result.json` in the external
project.

Cleanup: candidate `ccb_test kill` left `ccbd_state: unmounted` and
`ccbd_health: unmounted`; the project socket was absent and recorded daemon
PID `3805869` plus keeper PID `3805866` were dead.

Remaining risk: real authenticated prompt execution remains unclaimed because
no authorized Copilot login was used. This does not weaken the qualified
plugin/config projection boundary: native offline discovery, source
immutability, agent isolation, ownership transfer, and cleanup all passed.

Next unlocked row after this atomic commit: R10 integrated qualification and
disposition.

## R10: Integrated Qualification And Disposition

Slice: R10 integrated qualification and disposition

Commit selector / hash: commit subject `docs: qualify reviewed repair queue`
with trailer `Repair-Slice: R10`. The exact hash is intentionally obtained
only after this evidence-bearing commit is created.

Upstream items: PR257, PR258, PR259, PR264, PR265, PR266, and Issues260-263.
No pull request, issue, branch, package, or release was mutated by R10.

Baseline: clean R11-C commit
`6a20a5144f90193428ac5b9833e7ddd57d11abc3` on current `origin/main`
`aed27abf8899bd1d3ce72d08bb9133e3980f19ba`. The latter remained an ancestor
after a fresh fetch. PR257 was still merged. PR258, PR259, PR264, PR265, and
PR266 remained open and `UNSTABLE` at reviewed heads `d119bf18`, `c4bd9427`,
`1d4d1deb`, `2b79d68b`, and `3e11523c`; Issues260-263 remained open.

### Final Evidence Index

| Row | Atomic commit / integration | Upstream mapping | Durable evidence |
| :--- | :--- | :--- | :--- |
| R1/R2 projection safety | `06e1a46a97f94bdf7026347fccfdfe94542a9645`, merged by PR269 as `aed27abf` | Post-PR257 safety repair | [R1/R2 record](r1-r2-validation-2026-07-20.md) |
| R11 provider extensions | `5c1ff83a` | Deferred provider-extension follow-up | [R11 record](r11-provider-extension-validation-2026-07-20.md) |
| R3 inbound routing | `40e412653840cf346bb7e7b191f833318a0bf778` | PR264 | [R3](#r3-inbound-completion-routing-documentation) |
| R4 cancellation | `38645d475ab2283ee88bd11531727d8f2e7319ad` | PR266, Issue263 | [R4](#r4-cancellation-and-callback-terminalization) |
| R5 Claude activation | `bc31832e8b53030f3cfb1750c3fc4ed8b5267e64` | PR259 | [R5](#r5-claude-queued-prompt-activation) |
| R6 Kimi resume | `12a67d6265892f07ee58d72ff3fcc15d9f6d611d` | PR258 | [R6](#r6-kimi-exact-session-resume) |
| R7 execution phases | `56f8dcdad8c2e88a3c7df8d5dc0abcf375e10aa3` | PR265, Issue262 | [R7](#r7-correlated-execution-state-model) |
| R8 stuck inbound diagnosis | `e937aa99b2586565a33638818867b3f425cba2f2` | Issue260 | [R8](#r8-stuck-inbound-detection) |
| R9 active correction | `653be92154872e7a706d8b429c739bbd4fec150e` | Issue261 | [R9](#r9-active-job-correction-capability) |
| R12 generic ownership | `a41627a7f47ecc8827626b9593162676cfccc885` | Internal ownership follow-up | [R12](#r12-generic-projected-asset-ownership-hardening) |
| R11-C Copilot | `6a20a5144f90193428ac5b9833e7ddd57d11abc3` | Deferred R11 remainder | [R11-C](#r11-c-copilot-pluginconfig-projection) |
| R10 integration | current commit selected by `Repair-Slice: R10` | Entire queue | This section plus external `r10-runtime-result.json` |

### Cumulative And Client Gates

The final union of all direct counterexample files passed `945` tests in
`67.20s`. The complete Python suite passed `5547` tests with `15` conditional
skips and no failure in `648.61s`. The CI provider-blackbox selection passed
`21` tests with `57` deselected in `137.59s`. The exact current-main shutdown
heartbeat counterexample then passed `20/20` repeated candidate runs.

Rust formatting passed for sidebar, `ccb-rs-helper`, and the runtime
accelerator. Their complete test counts were respectively `79`, `8`, and
`10`. Flutter SDK `3.44.2` / Dart `3.12.2` reported no analyze issue and all
`659` tests passed. `dart format --output=none --set-exit-if-changed` identified
these six baseline files:

- `mobile/app/lib/transport/http_gateway_transport.dart`
- `mobile/app/test/android_release_mlkit_config_test.dart`
- `mobile/app/test/debug_profile_seed_test.dart`
- `mobile/app/test/http_gateway_transport_test.dart`
- `mobile/app/integration_test/server_wide_idle_request_smoke_test.dart`
- `mobile/app/integration_test/server_wide_live_artifact_smoke_test.dart`

The format command did not modify them, and an exact diff of those six paths
against `origin/main` was empty. They are therefore current-main format drift,
not candidate changes, and were not swept into this repair commit. The
candidate's two intentional R7 mobile differences are the ProjectView model
and its fixture test; Flutter analyze and all `659` tests cover them. Python
compilation, pyflakes, `git diff --check`, local Markdown links, Rust format,
and the staged secret scan passed.

### Current-Main CI Adjudication

The refreshed `origin/main` head itself, not this unpublished candidate, had a
successful
[Cross-Platform Compatibility Test run](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/29730742830),
a failed [Tests run](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/29730742725),
and a failed
[CCBD Real Platform Smoke run](https://github.com/SeemSeam/claude_codex_bridge/actions/runs/29730742686).
The Tests run's Rust helpers, provider blackbox, and macOS install smoke jobs
passed. Ubuntu Python 3.10/3.11 each failed only
`test_ccbd_stop_all_does_not_run_post_shutdown_heartbeat` because the expected
namespace-destroy event was absent; Python 3.12 additionally saw the stopping
socket reset during an OpenCode degradation test. The 3.11 job completed
`5215` passing tests before that single failure. All macOS Python versions
failed in the performance fixture after
`constructor_process_residue_or_audit_degraded`, plus the process-resource
profiling assertion. WSL tests reported the same shutdown race with performance
fixture, `/proc/io`, process-profile, and stopping-socket timing failures.

In the real-platform smoke run, macOS passed. WSL failed the fake-provider
restart test because restore correctly exposed one recovered item as
`replay_pending` while the test expected zero immediately. These are direct
current-main platform results. They are not hidden or relabeled as candidate
passes; the final candidate instead supplies the complete local suite,
provider blackbox, exact `20/20` race repeat, unchanged failing performance
files, and an exact no-diff check for the six baseline Dart-format files.

### External Real-Provider Acceptance

Project `/home/bfly/yunwei/test_ccb2/r10-integrated-real-20260721` used
`/home/bfly/yunwei/ccb_worktrees/unified-provider-extension-inheritance/ccb_test`,
explicit `CCB_TEST_ROOTS=/home/bfly/yunwei/test_ccb2`, inherited real provider
configuration, and project-local empty `roles-store`. Wrapper diagnosis proved
the project was outside source and inside the explicit allowed test root.

The frozen corpus was identical for both providers: `R10 qualification corpus
v1. Do not use tools. Reply with exactly R10_REAL_OK and nothing else.` Codex
CLI `0.144.6`, exact model `gpt-5.6-terra`, reasoning effort `low`, completed
job `job_4caf590ecb0f`, message `msg_9c5a0c130083`, and attempt
`att_e53b668ac445` with reply `rep_5403aa8dfa4a` exactly `R10_REAL_OK`. Claude
CLI `2.1.206`, exact model `deepseek-v4-pro`, completed job
`job_f418e6fcb6fc`, message `msg_a58c6c304127`, and attempt
`att_2bdb2b0df23d` with reply `rep_318bc4691ed6` exactly `R10_REAL_OK`. Each
authoritative trace contained one message, one attempt, one reply, one event,
and one job with no retry or substitution.

Before cleanup, live generation 3 was `mounted`, `healthy`, and running from
the candidate implementation root. Active executions, pending items,
terminal-pending items, restore replay-pending items, and active inbound
diagnostics were all zero; both mailbox-consistency views were `ok`. The
candidate tracked-file SHA256 stayed
`157a6c21b26d07d56334e776a2d1eb6977ccb085998eae12676c256efbb35eb6`
across the accepted cycle. The combined inherited Codex skills/plugin-cache
and Claude skills/commands source digest stayed
`3fed0b5c17be513dcea2ac81575e72363622c3544f429b267008fc06bd781194`.

Candidate `kill` returned `ok`, non-forced, and `unmounted`. Final doctor
reported unmounted health, dead daemon PID, non-connectable socket, and
`lease_unmounted`; ccbd/tmux sockets and every process containing the project
path were absent. Compact artifact:
`/home/bfly/yunwei/test_ccb2/r10-integrated-real-20260721/r10-runtime-result.json`.

One rejected harness path is retained for audit. The initial external `ask
all` inherited the live ccb_self `CCB_CALLER_*` binding and therefore targeted
the source project's 15 configured agents instead of the two-agent test
project. Those results were excluded. Nine jobs completed, one failed, and the
five still running were explicitly cancelled; all became terminal and none was
a chain job. Every accepted external command then cleared
`CCB_CALLER_ACTOR`, `CCB_CALLER_PROJECT_ID`, `CCB_CALLER_PROJECT_ROOT`, and
`CCB_CALLER_RUNTIME_DIR`, and two isolated Codex/Claude cycles completed and
cleaned up. This was a qualification-harness isolation error, not accepted
provider evidence.

### Proposed Upstream Dispositions

These are final review recommendations, not executed remote actions:

| Item | Proposed disposition | Evidence authority |
| :--- | :--- | :--- |
| PR257 | Keep merged; no action. Its safety follow-up is merged through PR269 and the remaining provider work is in R11/R12/R11-C. | `5214ce03`, `aed27abf`, `5c1ff83a`, `a41627a7`, `6a20a514` |
| PR258 | Close as superseded by the exact owned Kimi session implementation. | R6 `12a67d6265892f07ee58d72ff3fcc15d9f6d611d` |
| PR259 | Close as superseded by activation-bound Claude queued prompts. | R5 `bc31832e8b53030f3cfb1750c3fc4ed8b5267e64` |
| PR264 | Close as superseded by the corrected inbound-routing documentation and templates. | R3 `40e412653840cf346bb7e7b191f833318a0bf778` |
| PR265 | Close as superseded by the shared correlated execution-phase model and clients. | R7 `56f8dcdad8c2e88a3c7df8d5dc0abcf375e10aa3` |
| PR266 | Close as superseded by first-writer terminal cancellation and callback continuation. | R4 `38645d475ab2283ee88bd11531727d8f2e7319ad` |
| Issue260 | Close as resolved after integration; diagnosis remains read-only and bounded. | R8 `e937aa99b2586565a33638818867b3f425cba2f2` |
| Issue261 | Close as resolved with a capability matrix: exact active-turn correction is qualified for managed Codex and explicitly refused for unsupported Claude panes. | R9 `653be92154872e7a706d8b429c739bbd4fec150e` |
| Issue262 | Close as resolved after ProjectView/queue/CLI/sidebar/mobile integration. | R7 `56f8dcdad8c2e88a3c7df8d5dc0abcf375e10aa3` |
| Issue263 | Close as resolved after cancellation/callback integration. | R4 `38645d475ab2283ee88bd11531727d8f2e7319ad` |

Remaining risk: this is an unpublished local stack. macOS/WSL current-main CI
failures remain real upstream baseline work, and future provider CLI protocol
changes may invalidate exact capability probes. Neither risk authorizes hidden
retry, provider substitution, source mutation, or remote closure. The strict
repair goal is locally complete; push, PR/issue mutation, merge, package
publication, and release remain explicit user-controlled gates.
