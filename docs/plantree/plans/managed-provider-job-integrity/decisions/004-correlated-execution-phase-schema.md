# Decision 004: Execution Phase Is A Correlated Additive Projection

Date: 2026-07-21
Status: Accepted for R7

## Context

Issue262 asks CCB to distinguish provider execution from mailbox delivery.
`mailbox_state=delivering` is valid lease state, but it spans request injection,
provider work, pending terminal publication, and reply delivery. PR265 adds a
ProjectView-only phase derived mostly from job status and labels nearly every
running job `executing`; it can label provider-idle work `orphaned` before the
attempt, inbound event, mailbox, lease, completion anchor, and provider evidence
are proven to describe the same job.

Provider-native activity remains the primary authority for whether a managed
provider is active, waiting, idle, or failed. Job, attempt, inbound, mailbox,
lease, completion, and reply records remain workflow and identity authority.
Neither family alone can produce a confident end-to-end execution phase.

## Decision

`execution_phase` is an optional additive field in schema-v1 ProjectView and
queue records. Existing `mailbox_state`, job `status`, `business_status`, and
`status_label` keep their current meanings. Older producers may omit the new
field, and newer CLI, sidebar, and mobile clients fall back to those existing
fields when it is absent or empty. No schema-version transition is required.

The stable phase vocabulary is:

- `queued`: an accepted/queued job is joined to its pending attempt and queued
  inbound event, and that event is the mailbox head;
- `injecting`: a running job owns the active attempt, delivering inbound event,
  mailbox, and acquired lease, but its exact completion request anchor has not
  yet been observed;
- `executing`: the same active lineage has observed the exact job request
  anchor and current provider evidence is active or pending;
- `provider_idle_pending_terminal`: the exact anchored active lineage remains
  non-terminal while the current owned provider is idle, before the bounded
  orphan threshold is satisfied;
- `reply_queued`: the source job is terminal-successful and its correlated
  automatic reply-delivery job is absent, accepted, or queued;
- `reply_delivering`: that exact reply-delivery job is running;
- `orphaned`: the exact anchored active lineage remains non-terminal and
  bounded current-session evidence proves the provider returned idle without
  terminal publication;
- `terminal`: authoritative terminal job/completion and correlated reply-
  delivery evidence require no further delivery work;
- `unknown`: active or queued evidence is missing, stale, contradictory, or
  cannot be joined by exact identity.

The pure phase resolver consumes already-read evidence; it does not read files,
capture panes, mutate jobs, or trigger recovery. Producers attach a compact
`execution_evidence` record containing only stable identity/state facts used by
the decision. Consumers render the resolver's phase and reason; they do not
rederive it.

## Identity And Precedence

Confident request phases require exact equality across all available joins:

- job id equals attempt job id;
- job agent equals attempt and inbound agent;
- attempt id equals inbound attempt id;
- inbound id equals mailbox head for `queued`, or mailbox active id and lease
  inbound id for active phases;
- active lease state is `acquired`;
- completion snapshot job/agent identity matches, and `anchor_seen` refers to
  the bound job request;
- provider activity belongs to the current project, agent, provider session,
  pane, workspace, and runtime generation before it influences the phase.

Evidence precedence is fail-closed:

1. Authoritative terminal job/completion evidence wins over lagging mailbox or
   lease cleanup and preserves R4's first-terminal-writer authority.
2. Correlated reply-delivery state determines `reply_queued`,
   `reply_delivering`, or final `terminal` after source completion.
3. Exact queued or active request lineage may produce a non-terminal phase.
4. Exact provider-idle evidence distinguishes pending terminal publication from
   bounded `orphaned` suspicion.
5. Any wrong job, attempt, inbound event, agent, mailbox head/active id, lease,
   completion snapshot, provider session, pane, workspace, or generation makes
   the non-terminal result `unknown`. Missing evidence required for a confident
   phase also makes it `unknown`.

`orphaned` is diagnostic only. R7 does not cancel, retry, restart, resend,
terminalize, or otherwise repair a job. R8 may consume this phase only after
its additional bounded observation contract is accepted.

## Consumer Contract

- ProjectView comms records expose `execution_phase`,
  `execution_phase_reason`, and compact `execution_evidence`.
- Structured queue agent records expose the same fields for their current
  queued or active request.
- CLI queue output prefers `execution_phase`; it retains and separately prints
  `mailbox_state`.
- The Rust sidebar deserializes the optional fields and prefers the execution
  phase for its Comms status text and color, falling back to the legacy labels.
- The mobile gateway preserves the fields, and the mobile model parses an
  optional comms phase with the same fallback rule.

## Consequences

The resolver can be tested with small immutable fixtures, while ProjectView and
queue producers remain responsible for safe store reads and identity assembly.
Additive schema-v1 compatibility avoids a flag-day rollout. Some active work
will display `unknown` when older or incomplete records cannot prove the full
join; that is intentional and safer than a confident but incorrect label.

## Verification

R7 must preserve failing counterexamples for wrong attempt/job identity,
mismatched mailbox head or active event, mismatched/expired lease, stale or
wrong-provider activity, terminal-vs-active cleanup lag, and older client
payloads without the new fields. It must cover every phase, ProjectView and
queue projections, CLI fallback, Rust sidebar fallback, mobile parsing, current
PR265-focused tests, the complete Python/Rust/mobile gates, and an inspectable
external source-runtime project without automatic recovery.
