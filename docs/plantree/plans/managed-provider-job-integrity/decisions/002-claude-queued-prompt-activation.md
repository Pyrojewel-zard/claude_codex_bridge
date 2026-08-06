# Decision 002: Claude Queued Prompts Activate On Exact Replay

Date: 2026-07-21
Status: Accepted and verified for R5

## Context

PR259 converts `queue-operation/enqueue` into a synthetic user event. That
prevents one missing-anchor deadlock, but it lets the assistant output and
terminal boundary of the already-running turn complete the newly enqueued CCB
job. Current main also emits a synthetic anchor when a prompt was deferred for
pane readiness and is later sent, even though pane dispatch is not provider
activation evidence.

Claude Code 2.1.206 records enqueue content with the queued command, records an
uncorrelated `queue-operation/dequeue` without content, and replays the selected
command as an `attachment/queued_command` whose `prompt` and `source_uuid`
identify that command. Queue priority and removal mean a bare dequeue cannot
identify which prompt became active.

## Decision

Claude prompt lifecycle state records these facts separately:

- `prompt_enqueued` means an enqueue record carried the current outer
  `CCB_REQ_ID`; it is delivery evidence only.
- `queue_dequeue_observed` means a dequeue record was observed; because it has
  no prompt identity, it is diagnostic evidence and never activates a job.
- `prompt_activated` means either a normal top-level user prompt or an
  `attachment/queued_command.prompt` carried the exact current outer
  `CCB_REQ_ID`.
- `anchor_seen` is emitted only after that exact activation, except for the
  existing explicit `no_wrap` contract.

Pane dispatch and enqueue never synthesize `ANCHOR_SEEN`. Before exact
activation, Claude assistant text, assistant UUIDs, tool-only assistant
records, subagent records, system turn boundaries, API errors, hook artifacts,
and idle-pane result recovery are not completion evidence for the queued job.
After activation, only top-level assistant UUIDs may bind a system
`turn_duration`; subagent UUIDs remain fenced.

The lifecycle fields persist with the event-reader cursor. Restart therefore
resumes from the same enqueue/activation boundary without backward guessing.
Session rotation clears correlated queue and assistant state, requiring the
current prompt to activate in the newly selected top-level session.

## Consequences

An enqueued job may remain pending after the old turn finishes, but it cannot
consume that old reply or terminal event. Multiple queued prompts are safe
because only the exact replayed prompt activates its submission; observed FIFO
order is not treated as identity. Pure tool-use assistant records are retained
after activation so their top-level UUID can bind the following
`turn_duration` without contributing text.

Legacy deferred-dispatch anchors are not activation authority. Persisted state
that explicitly identifies such a synthetic anchor must fail closed until
exact activation evidence is observed; it must not be grandfathered into the
new model.

## Rejected Alternatives

Treating enqueue as activation preserves PR259's cross-turn replay. Treating a
bare dequeue as activation guesses identity when several queued commands or
priority changes exist. Pre-anchor assistant UUID bookkeeping allows the old
turn boundary to be mistaken for the new one. Pane-idle or elapsed-time
heuristics likewise cannot prove which queued command became active.

## Verification

R5 must replay an old busy text turn, an old tool-only turn, subagent records,
multiple queued prompts, exact and non-matching queued-command attachments,
restart/catch-up, and session rotation. It must prove that no old text or
terminal item enters the new reply and that hook/session completion remains
gated until exact activation.
