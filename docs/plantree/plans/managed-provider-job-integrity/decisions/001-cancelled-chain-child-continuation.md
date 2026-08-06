# Decision 001: Cancelled Chain Child Continues The Parent

Date: 2026-07-21
Status: Accepted for R4

## Context

PR266 made empty ordinary cancellation non-blocking, but cancellation still
bypassed callback completion authority. A cancelled chain child could
therefore leave its edge pending and its parent unable to finish until daemon
restart repair. R4 needed one terminal policy that also covered partial output,
repeated cancel, completion races, and stale-job recovery.

## Decision

Cancelling a chain child is a terminal child result, not a terminal result for
the parent task. The callback authority must submit exactly one ordinary parent
continuation carrying the child job identity, `cancelled` status, and any
captured partial output. With no partial output, the continuation states that
the child returned no body. The parent provider then decides how to finish the
original task and CCB routes that parent result through the existing lineage.

An ordinary cancelled job with neither reply text nor reply artifact still has
a durable cancelled attempt and `ReplyRecord`, but its registered caller gets a
consumed-from-birth `completion_notice`, not a queued `task_reply`. Trace shows
the notice and ProjectView remains idle with unchanged mailbox depth. A
non-empty or artifact-backed cancelled reply stays on normal exactly-once reply
delivery.

Cancellation and normal completion share the callback edge authority and the
chain transition lock. If they race, the first persisted terminal job wins;
the loser must not rewrite the job, attempt, reply, callback edge, or completion
snapshot. Repeated cancellation returns the existing cancelled receipt and
must not create another reply, notice, or continuation.

Internal stale-job recovery with `record_reply=False` does not manufacture a
cancelled callback result; its retry remains responsible for terminalizing the
existing message lineage.

## Consequences

Cancellation must use the chain transition lock and the same idempotent result
router as normal completion. Trace keeps a durable cancellation record without
forcing an empty provider turn, while valid child cancellation resumes the
parent immediately. Direct parent cancellation terminalizes its outstanding
edge so a later child result cannot reopen the cancelled task.

## Rejected Alternative

Marking the child edge failed/cancelled without a parent continuation leaves no
provider turn able to finish the original task. A callback failure notice is
reserved for failure to create or recover the continuation itself, not for a
valid cancelled child result.

## Verification

R4 must cover empty and partial ordinary cancellation, direct child
cancellation without restart, repeat idempotency, persisted restart, an
existing caller mailbox, completion/cancel races, trace visibility, and
ProjectView's zero-depth/idle projection.
