# Decision 006: Exact Active-Job Follow-Up Uses Native Turn Preconditions

Date: 2026-07-21
Status: Accepted and verified for R9

## Context

Issue261 asks CCB to correct work that is already executing without creating a
second ordinary mailbox job. The current managed Codex and Claude runtimes are
interactive panes. Their event logs can prove which prompt or turn was
observed after delivery, but a pane `Enter` cannot atomically require that the
same turn is still active. If the provider finishes between the last CCB check
and that keypress, the text may start a new turn.

Codex exposes a stronger native contract through app-server. `turn/steer`
accepts the exact thread plus an `expectedTurnId`; the request fails if that
turn is no longer active. The installed Codex 0.144.6 schema also accepts a
`clientUserMessageId`, which can carry CCB's durable follow-up identity.
Codex's remote TUI can attach to the same app-server, so the visible managed
pane and the structured control request can share one provider authority.
The transport and steering primitives are documented in the official
[Codex app-server reference](https://learn.chatgpt.com/docs/app-server.md).

Claude Code 2.1.206 records busy input as queued-command lifecycle events, but
those records are post-dispatch evidence. They do not expose an atomic
expected-active-turn request to CCB. Decision 002 therefore remains useful for
queued ordinary jobs but does not qualify pane input as active-job correction.

## Decision

`ccb followup <job_id> --message <text>` addresses one exact running job. It
creates a durable follow-up record, never a `JobRecord`, mailbox attempt,
inbound event, callback edge, or provider substitute. Records are append-only
and ordered per target job by acceptance sequence.

The state vocabulary is:

- `accepted`: CCB durably accepted the request and has not yet obtained a
  provider result.
- `injected`: the provider atomically accepted the exact target turn.
- `rejected`: the job, active execution binding, or provider capability did
  not qualify; no provider input was sent.
- `too_late`: the addressed job was already terminal when CCB evaluated it.
- `terminal`: CCB accepted the record, but the provider's exact-turn
  precondition or a concurrent CCB terminal transition won before injection.

Initial validation and every replay re-read R4 job authority while holding the
same chain-transition lock used by completion and cancellation. Provider-state
commits and follow-up injection are serialized inside the execution service;
slow provider polls run outside that lock, and their result is discarded when
an injection or terminal transition changed the active submission. A terminal-
pending provider decision removes the active submission before CCB can inject.
Completion and cancellation never reopen an accepted record.

An `accepted` record is an outbox entry. Restart replays it in original order
only while the same job remains running and the provider exposes an exact
active binding. Provider adapters must use `followup_id` as an idempotency key;
an injected record is never replayed. A replay that loses job/turn authority
becomes `terminal` or `rejected`, not a queued ordinary prompt.

## Capability Matrix

| Provider transport | R9 capability | Mechanism / refusal |
| :--- | :--- | :--- |
| Codex managed remote app-server | supported | `turn/steer(threadId, expectedTurnId, clientUserMessageId)` on the same app-server used by the visible TUI |
| Codex legacy/local interactive TUI | refused | pane `Enter` has no atomic expected-turn precondition |
| Claude interactive TUI | refused | queued-command events prove replay only after pane dispatch and cannot prevent the terminal-to-new-turn race |
| Other production adapters | refused | unsupported unless the adapter advertises an exact, idempotent active-turn primitive |
| CCB fake adapter | supported for deterministic contract/restart tests | in-memory exact job/turn compare-and-record keyed by `followup_id` |

Support is evaluated from the active submission, not the provider name alone.
A Codex job without a bound thread, bound turn, live managed app-server socket,
or matching active submission fails closed. CCB does not fall back to pane
input, cancel-and-resubmit, another provider, or an automatic retry.

## Trace And Caller Contract

The command and socket API return the latest follow-up record, including
`followup_id`, exact `job_id`, provider, sequence, status, reason, provider
mechanism, expected turn reference, and timestamps. `ccb trace` accepts a
follow-up id and also joins all follow-up records to a traced job. Message text
is stored for accepted/restart delivery but is omitted from ordinary rendered
status and trace summaries.

`injected` exits successfully. `accepted` remains a durable pending outcome;
`rejected`, `too_late`, and `terminal` are structured non-success outcomes so
scripts do not mistake refusal or an unknown transport result for delivery.
Retrying is an explicit new follow-up with a new identity.

## Rejected Alternatives

Sending keys to a pane after checking ProjectView, pane status, or a provider
log still leaves a check-to-send race. Treating Claude enqueue or Codex user
log entries as acceptance proves only that an unsafe side effect already
happened. Cancel-and-resubmit changes job and callback lineage. Hidden retries
can reorder multiple corrections and conceal a terminal conflict.

## Verification

R9 must cover supported injection, every explicit refusal, wrong and stale
jobs, multiple queued jobs, FIFO follow-ups, completion and cancellation
races, idempotent restart replay, trace joins, CLI exit behavior, Codex
app-server success and expected-turn rejection, legacy Codex refusal, and
Claude refusal. Real qualification must use an inspectable managed Codex
remote-app-server project and prove that a terminal race creates no new turn.
