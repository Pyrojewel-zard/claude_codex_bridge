# Prepared Authority Before Provider Spawn

Date: 2026-08-04

## Context

A Provider process can begin reading or refreshing credentials immediately
after spawn. If CCB starts that process before durably recording its authority
generation and writer ownership, a later session-store failure leaves a live
writer that the control plane cannot safely identify or fence.

External state can also change between a source probe and a separate projection
read. A successful probe is not permission to copy different bytes observed
later.

## Decision

Every initial launch and restart uses a two-phase authority transaction:

1. quiesce and fence the previous writer;
2. obtain one immutable or generation-checked source snapshot;
3. resolve the composite authority from that snapshot;
4. transactionally materialize CCB-owned state;
5. durably record a `prepared` authority/session generation and writer lease;
6. spawn the Provider with that exact prepared generation;
7. verify process identity, roots, and binding;
8. atomically activate the generation.

If any step after spawn fails, CCB terminates the new Provider writer before it
reports a stopped/degraded result. It must not leave an uncommitted process
running merely because the generation is hidden from ready-state diagnostics.

The Provider probe must either return the secret-bearing snapshot through an
owner-only in-memory/ephemeral handle or return a source generation that the
projection operation revalidates atomically. Projection must never re-read an
unversioned source after safety classification.

## Consequences

- `provider.json` needs explicit `prepared`, `active`, `failed`, or equivalent
  lifecycle state in addition to the authority generation.
- Writer leases are ccbd-owned authority, not advisory adapter metadata.
- A commit or binding failure after spawn has a mandatory termination path.
- Crash recovery must reconcile prepared generations, process identity, and
  lease ownership before allowing new work.
- Tests need injected failures at every transaction boundary and a source
  rotation between probe and projection.
