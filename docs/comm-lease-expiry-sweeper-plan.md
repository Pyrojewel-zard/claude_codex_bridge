# Comm Lease-Expiry Sweeper Plan

## 1. Document Role

This document defines the phase-2 design for closing the *non-`ask`* class of
wedged mailbox deliveries — the gap left open by the phase-1 job-heartbeat
reaper. It is a **design/plan only**; no code is proposed for landing under this
document until the plan is reviewed.

Primary trigger incident:

- 2026-07-09 CCB communication stall
  (`/Users/leel/my_work/MiniMES/docs/incidents/2026-07-09-ccb-stall-incident.md`)
  - a delivery to `pm` acquired a lease and then never converged; the completion
    detector's `session_event_log` source never bound a `session_path`
    (frozen at `event_seq 0`), so no terminal decision was ever produced
  - the event stayed `DELIVERING` for ~10h, starving everything queued behind it
  - only a full daemon shutdown (`stop_all`) could finalize it

This plan is a sibling of, and depends on the vocabulary in:

- `docs/managed-provider-completion-reliability-plan.md` (completion-timeout
  closure for pane-backed providers)
- `docs/agent-mailbox-kernel-design.md` (mailbox state machine + lease model)

It does not replace either. It adds one **lease-level, message-type-agnostic**
safety net beneath both.

## 2. Root Cause Boundary

### 2.1 What phase-1 already covers

Phase-1 (`fix/comm-delivering-watchdog`, commit `b9447dc6`) armed the existing
job-heartbeat reaper by setting `JOB_HEARTBEAT_TERMINAL_NOTICE_COUNT = 6` in
`lib/ccbd/app_runtime/bootstrap.py`. After ~6 consecutive no-progress heartbeat
intervals (~60 min of continuous silence, reset by any detected session-log
progress) a wedged job is terminated as `INCOMPLETE` (`reason=heartbeat_timeout`,
no re-run) and its mailbox queue is released.

**Constraint:** the job heartbeat service only tracks one message type —

```
lib/ccbd/services/job_heartbeat.py:15
_TRACKED_MESSAGE_TYPES = frozenset({'ask'})
```

So phase-1 only rescues stuck **`ask`** deliveries that have an associated
tracked job.

### 2.2 The uncovered class

A mailbox delivery becomes `DELIVERING` for *any* `InboundEventType`, not just
the `ask` path:

- `TASK_REPLY`
- `COMPLETION_NOTICE`
- `RETRY_SIGNAL`
- `SYSTEM_SIGNAL`
- `BARRIER_RELEASE`
- (and `TASK_REQUEST` deliveries that never register a tracked job)

Each of these acquires a `DeliveryLease` on claim. The lease is created with:

```
lib/mailbox_kernel/service_runtime/transitions_runtime/claiming.py:89
expires_at=None,
```

i.e. **no lease deadline and no reaper watches it.** If the consumer never
finalizes the event (the same failure mode as the incident, but on a non-`ask`
event), there is:

- no tracked job → the phase-1 heartbeat reaper never sees it
- no `expires_at` → nothing else times it out
- result: the event stays `DELIVERING` indefinitely and blocks its queue until a
  full daemon restart

This is the residual structural gap. Phase-2 closes it at the lease layer so the
net is **message-type-agnostic**.

## 3. Design

### 3.1 Principle

Give every delivery lease a bounded lifetime, and add one periodic sweep that
terminates leases which have exceeded that lifetime *with no observed progress*.
Progress (a `last_progress_at` advance) renews the deadline, so healthy
long-running deliveries are never reaped — identical safety property to phase-1,
one layer lower.

### 3.2 Change points

1. **Populate `expires_at` on lease acquisition**
   - `lib/mailbox_kernel/service_runtime/transitions_runtime/claiming.py`
     `_delivery_lease()` — currently hard-codes `expires_at=None`.
   - Compute `expires_at = now + lease_ttl` from an injected policy value (do NOT
     hard-code the TTL at the call site; thread it from a policy object the way
     `HeartbeatPolicy` is threaded, so it is testable and tunable).
   - `DeliveryLease` already carries the field
     (`lib/mailbox_kernel/models.py:79`, `expires_at: str | None`) and
     `last_progress_at`, so no model change is required — only population.

2. **Renew `expires_at` on progress**
   - Wherever `last_progress_at` is advanced for an active lease, also push
     `expires_at` forward by the TTL. This is what makes the sweep safe: only
     genuinely idle leases expire.

3. **Add a lease-expiry sweep step in the maintenance loop**
   - `lib/ccbd/app_runtime/lifecycle.py` `_heartbeat_failures(app)` runs an
     ordered list of tick steps (`health_monitor`, `runtime_supervision`,
     `dispatcher_runtime_views`, `dispatcher_tick`,
     `dispatcher_poll_completions`, `reload_drain_auto_retry`, `job_heartbeat`).
   - Add one step, e.g. `lease_expiry_sweep`, that asks the mailbox kernel for
     leases whose `expires_at` is in the past **and** whose `lease_state` is
     still `ACQUIRED`, and drives each through a terminal transition.

4. **Define the terminal transition for an expired non-job event**
   - For an event with no tracked job, terminate via the mailbox kernel:
     move `DELIVERING → ABANDONED` (not `CONSUMED` — the work never produced a
     valid result), mark the lease `EXPIRED`, and advance the queue so the next
     event can be delivered.
   - `ABANDONED` vs `CONSUMED` matters for observability: `CONSUMED` implies a
     legitimate result was recorded; an expiry sweep must not fake one. Choose
     `ABANDONED` (or introduce a dedicated `EXPIRED` inbound status if review
     prefers a distinct signal from user-driven abandonment).
   - If an expired lease *does* have a tracked `ask` job, let phase-1 own it —
     the sweep should skip leases whose event already has a live tracked job to
     avoid double-terminalization (see §4.3).

### 3.3 Policy / tuning

- Introduce a lease TTL policy value. Suggested starting point: comfortably
  longer than the phase-1 reap window so phase-1 (job-aware, more precise) fires
  first for `ask`, and the lease sweep is a pure backstop for the non-`ask`
  classes. e.g. lease TTL ≈ 75–90 min while phase-1 reaps at ~60 min.
- Keep the value in a policy object (mirroring `HeartbeatPolicy`) so it is
  injectable in tests and overridable per deployment.

## 4. Risks

### 4.1 False-positive reaping of a slow-but-healthy delivery

- **Mitigation:** the sweep keys off `expires_at`, and `expires_at` is renewed
  on every `last_progress_at` advance. A delivery that is making any observable
  progress never expires. This is the same guarantee phase-1 relies on; the risk
  is only as large as the "we cannot observe progress" blind spot, which is
  exactly the incident condition we *want* to terminate.

### 4.2 Choosing the wrong terminal status

- Terminating as `CONSUMED` would silently mask a lost delivery as success.
  **Mitigation:** terminate as `ABANDONED` (or a new `EXPIRED` status) so the
  event is visibly non-successful and traceable. Requires a review decision on
  whether to reuse `ABANDONED` or add `EXPIRED`.

### 4.3 Double-terminalization / race with phase-1

- If both the phase-1 heartbeat reaper and the phase-2 lease sweep target the
  same wedged `ask` event, they could race.
  **Mitigation:** the sweep explicitly skips any lease whose event has a live
  tracked job (phase-1's domain). Phase-1 handles all `ask`; phase-2 handles the
  rest. The mailbox kernel transition must also be idempotent — a second
  terminalization of an already-terminal event is a no-op, not an error.

### 4.4 Clock/TTL threading regressions

- Hard-coding the TTL at the `claiming.py` call site (instead of threading a
  policy + clock) would make the behavior untestable and un-tunable, and risk a
  drift-back like the `_DEFAULT_TERMINAL_NOTICE_COUNT = None` default that caused
  this incident class. **Mitigation:** inject TTL + clock; add a regression test
  that asserts a positive TTL is armed at bootstrap (mirroring the phase-1
  `test_ccbd_bootstrap_arms_job_heartbeat_reaper` guard).

### 4.5 Persisted leases with `expires_at=None` after upgrade

- Leases acquired *before* this change (or reloaded from persisted state) carry
  `expires_at=None`. The sweep must treat `None` safely — either backfill a
  deadline on first observation, or leave `None` leases to phase-1 / restart and
  only sweep leases that carry a concrete `expires_at`. Decide during
  implementation; document the chosen behavior.

## 5. Test Plan

1. **Unit — lease acquisition populates `expires_at`**
   - Claim an event with an injected clock + TTL policy; assert the resulting
     `DeliveryLease.expires_at == now + ttl` and `lease_state == ACQUIRED`.

2. **Unit — progress renews `expires_at`**
   - Advance `last_progress_at`; assert `expires_at` moves forward by the TTL and
     the lease is not swept.

3. **Integration — sweep terminates an idle non-`ask` lease**
   - Bootstrap a test project (reuse `_bootstrap_test_project` +
     `StepClock` pattern from
     `test/test_v2_message_bureau_dispatcher_integration.py`).
   - Deliver a `TASK_REPLY` (or other non-`ask`) event so it enters `DELIVERING`
     with a lease; step the clock past the TTL with no progress; run the
     maintenance tick; assert the event transitions to `ABANDONED`/`EXPIRED`, the
     lease is `EXPIRED`, and the queue advances (next event becomes deliverable).

4. **Integration — healthy delivery is NOT swept**
   - Same setup, but advance `last_progress_at` each interval; assert the event
     is never terminated across multiple TTL windows.

5. **Integration — no double-terminalization with phase-1**
   - A wedged `ask` event with a live tracked job: assert the lease sweep skips
     it and phase-1's heartbeat reaper is the one that terminates it (single
     terminal decision, single reply).

6. **Bootstrap guard (regression)**
   - Assert the daemon constructs the mailbox kernel / maintenance loop with a
     positive lease TTL, so the value cannot silently drift back to "disabled"
     (direct analogue of the phase-1 bootstrap guard test).

7. **Regression sweep**
   - `pytest -k "mailbox or dispatcher or heartbeat or lease"` green, plus the
     bootstrap-sensitive `test_v2_ccbd_socket.py` subset.

## 6. Relationship to Phase-1

Phase-1 and phase-2 are **complementary, non-overlapping nets**:

| | Phase-1 (`fix/comm-delivering-watchdog`, shipped) | Phase-2 (this plan) |
| - | - | - |
| Layer | Job heartbeat service | Mailbox delivery lease |
| Scope | `ask` jobs only (`_TRACKED_MESSAGE_TYPES = {'ask'}`) | All event types with no tracked job |
| Trigger | `terminal_notice_count` no-progress intervals | `expires_at` passed with no progress |
| Terminal | Job `INCOMPLETE`, `reason=heartbeat_timeout`, no re-run | Event `ABANDONED`/`EXPIRED`, lease `EXPIRED`, queue advanced |
| Precision | Higher (job-aware) | Lower (lease-level backstop) |

Phase-1 fires first for `ask` (shorter window, job-aware). Phase-2 is the
message-type-agnostic backstop that catches everything phase-1 structurally
cannot see. Together they remove the "only a full daemon restart clears it"
property that defined the 2026-07-09 incident.

## 7. Out of Scope

- Fixing *why* the `session_event_log` completion source failed to bind a
  `session_path` — that is completion-detection reliability work
  (`docs/managed-provider-completion-reliability-plan.md`), not the lease net.
  This plan makes the *consequence* self-healing; it does not remove the
  upstream trigger.
- Any change to `opencode`'s existing completion contract.
- Auto re-run / retry of terminated deliveries (explicitly excluded, consistent
  with phase-1's terminate-and-alert semantics).
