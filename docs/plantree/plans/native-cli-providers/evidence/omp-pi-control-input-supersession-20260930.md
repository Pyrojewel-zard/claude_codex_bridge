# OMP/Pi Control-Input Supersession Repair

Date: 2026-09-30
Role: evidence
Status: release candidate verified; not yet published

## Failure

OMP 18.3.5 emitted the interactive input extension event before dispatching
the `/model` TUI command. The shared Pi/OMP CCB extension interpreted every
unmatched non-extension input as a replacement turn, wrote
`request_superseded`, cleared `activeReqId`, and caused the adapter to terminate
the ask as `omp_request_superseded` without a usable reply. Historical runtime
records for `job_ac16c2282220` and `job_b3694c477161` contain an input SHA-256
equal to `/model` and confirm the false classification.

## Repair

- The shared input handler now binds recognized CCB dispatches but does not
  terminalize unmatched control or user submissions.
- A different prompt supersedes an active request only when Pi/OMP emits
  `before_agent_start`, the native boundary for an ordinary prompt or an
  actually dequeued user-containing batch reaching the provider.
- The first `before_agent_start` belonging to the bound CCB dispatch is retained
  through explicit bound-start state plus anchor/digest checks.
- `session_switch` still supersedes the old request with a reason-qualified
  diagnostic. A later CCB dispatch still supersedes defensively through the
  existing dispatch binding logic.
- There is no `/model` command whitelist; selectors and future control-only
  commands are excluded by lifecycle semantics rather than command spelling.

## Verification

Focused pytest coverage executes the generated Pi extension with Bun and proves:

1. `/model` emits input without superseding or losing `job_model` attribution;
2. a real different `before_agent_start` supersedes as `unmanaged_agent_turn`;
3. a native `session_switch(new)` supersedes as `session_switch:new`;
4. the generated OMP extension inherits the same event boundary;
5. the Pi pane adapter and FIFO/empty-result delivery regressions still pass.

On the v8.7.5 release baseline, the focused regression command passed `302`
tests with two pre-existing, explicitly gated smoke tests skipped.

A disposable CCB project then ran real OMP 18.3.5 job
`job_727bce7356c0` from the v8.7.5 release worktree. While its `sleep 25`
tool call was active, `/model`
changed the default model from `paratera2/grok-4.6` to
`bingxing/AWS-GPT-5.6-Sol`. Authoritative trace remained `running` after the
switch, then the same attempt completed once with exact reply
`CCB_RELEASE_875_MODEL_SWITCH_OK`; the event stream contained no
`request_superseded`. The temporary project, worktree, daemon, tmux server,
and provider process were removed after verification.

## Limit

Pi uses the same generated extension and passed the Bun lifecycle replay plus
pane-adapter regressions, but a separate authenticated Pi TUI `/model` run was
not performed. The real active-turn qualification above is OMP-specific.
