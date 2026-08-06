# Decision 005: Orphaned Active Inbound Requires Bounded Exact Observation

Date: 2026-07-21
Status: Accepted for R8

## Context

Issue260 reports a running business job whose exact inbound event and lease
continue to block a mailbox after Claude has returned to its idle prompt and
no terminal completion arrives. R7 can correlate that active lineage and
distinguish provider idle from execution, but a single pane capture is not
enough to promote `provider_idle_pending_terminal` to `orphaned`: terminal
publication may be lagging, a provider may still be reasoning or using tools,
the pane may be stale, or the runtime binding may have rotated.

The first repair must make this state unmistakable without turning a
diagnostic read into cancellation, retry, restart, resend, lease release, or
terminalization.

## Decision

R8 emits `orphaned_active_inbound` only after two qualifying observations of
the same exact active lineage and current provider binding are separated by at
least 30 seconds. The existing 30-second no-progress/job-age threshold is only
eligibility for the first observation; it is not sufficient by itself. Thus a
newly observed exact idle prompt remains
`provider_idle_pending_terminal` for at least one additional window.

A qualifying observation requires all R7 active-lineage joins and:

- job status remains `running` and its completion snapshot is non-terminal;
- attempt, inbound event, mailbox active id, acquired lease, and completion
  request anchor match exactly;
- current Claude pane evidence contains the exact request marker followed by
  the idle prompt;
- project, agent, job, provider session/reference, pane, workspace, daemon/
  runtime/binding generation, and job progress revision are unchanged;
- the evidence is read from the current service graph and current runtime
  record, not a carried or body-derived identity.

The observation resets immediately when the job progresses or terminalizes,
the provider becomes active, the exact idle marker disappears, any lineage
join changes, the pane/session/workspace/generation rotates, or the project
view service restarts. A reset starts a new observation window; it never
inherits elapsed time from the old identity. Missing timestamps or identity
facts fail closed. Read frequency cannot shorten the fixed window, and a
cached response cannot advance it.

The exact-idle pane predicate is initially Claude-only because it is the only
current parser that proves an idle prompt occurs after the exact CCB request
marker. Other providers remain `provider_idle_pending_terminal` or `unknown`
until an equivalent native predicate is accepted; provider substitution and
generic prompt-shape guesses are forbidden.

## Diagnostic Envelope

After the window is satisfied, the ProjectView Comms row sets
`execution_phase=orphaned`, reason `provider_idle_without_terminal`, and adds
an optional `active_inbound_diagnostic` record containing:

- `condition_kind=orphaned_active_inbound`, confidence, job id/status/age and
  last progress time;
- attempt and inbound ids/status, mailbox state/head/active identity and head
  event type, and lease state/identity;
- provider state/reason/last progress and current observation time;
- observation start, elapsed seconds, and required window;
- `recommended_action=explicit_comms_recover`, the exact recover target, and
  `automatic_action=none`.

ProjectView is the observation authority. Maintenance includes the same
envelope in concern evidence. The trace handler merges the matching envelope
from the current ProjectView into exact job lineage output. Doctor lists all
current envelopes, CLI renderers preserve the condition/reason/ids/window and
manual-action fields, and the Rust sidebar deserializes the optional envelope
and displays the same condition/reason while retaining its deliberate manual
recover action. Consumers do not rederive or extend the observation window.

## No-Mutation Boundary

Observation tracking is bounded in-memory diagnostic state owned by the
long-lived ProjectView service. It is not persisted job, mailbox, lease,
completion, provider-session, or scheduling authority. ProjectView, doctor,
trace, maintenance evaluation, CLI rendering, and sidebar rendering must not
call `comms_recover`, cancel, retry, restart, resend, acknowledge, release a
lease, write terminal state, or otherwise mutate the correlated job.

Existing explicit `comms recover` remains a separate user/operator action and
must revalidate its own authority at invocation time. R8 only recommends that
action and never performs it. Automatic convergence remains deferred.

## Consequences

Detection may take more than 60 seconds after the last job update: the job
must first be eligible, then the exact idle state must survive the additional
30-second observation window. Low-frequency readers may detect later, never
earlier. Daemon or binding restart intentionally loses observation progress
and delays diagnosis rather than carrying stale suspicion forward.

## Verification

R8 must preserve fixtures for the first exact idle observation, the same
identity after the window, progress reset, terminal race, wrong attempt/
inbound/mailbox/lease, queued work, active reasoning/tool use, stale or wrong
pane marker, session/pane/workspace/generation rotation, service restart, and
cache hits. ProjectView, maintenance, trace, doctor/CLI, and Rust sidebar must
surface the same envelope. Tests and an external real-Claude project must
prove no job, attempt, inbound, mailbox, lease, completion, reply, or provider
runtime authority changes merely because the diagnostic is observed.
