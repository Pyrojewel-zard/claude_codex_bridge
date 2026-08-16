# Continuous Session Rebinding After Inherited-State Changes

Date: 2026-08-05

## Context

The current authority fence correctly prevents a Provider conversation from
being silently resumed under a different account, API route, or credential
generation. However, the v8.5.5 migration regression treated missing legacy
metadata as an authority mismatch and moved usable history out of the active
resume namespace. The result was indistinguishable from an automatic clear to
the operator.

The intended product behavior is:

1. explicit authority in `.ccb/ccb.config` wins over inherited Provider state;
2. when that dimension is not explicit, CCB reads the current external state
   one way into a private managed representation;
3. a stopped Provider restart observes the latest external state; and
4. changing inherited state does not destroy the CCB conversation, workspace,
   queue, or resumable history.

## Decision

Separate conversation continuity from Provider credential authority.

- CCB keeps a stable, Agent-owned conversation identity and local history
  index across authority generations.
- A source-owned projection is refreshed only when a new Provider generation
  is prepared. Running Provider processes are not hot-mutated.
- A compatible legacy session with missing authority metadata is adopted and
  annotated; it is never cleared merely because metadata is absent.
- When an inherited authority generation changes, the old session artifacts
  are retained. The Provider adapter first attempts a generation-aware native
  rebind. If the Provider proves that native resume is compatible, the same
  native session is resumed under the new managed projection.
- If native resume is not compatible or cannot be proven, CCB automatically
  creates a linked continuation generation while retaining the old transcript
  as read-only history. The operator must see a non-secret status such as
  `continued_on_new_authority`; no history is silently discarded.
- A known incompatible native session must not be resumed under the new
  authority. “Preserve history” is required; “reuse the remote conversation”
  is conditional on Provider capability evidence.
- Explicit CCB authority and independently Agent-owned credentials are not
  overwritten by external changes. Their conversations remain bound to their
  own authority generation.
- Source reads are tri-state (`present`, `authoritative_absent`,
  `unknown_error`). `unknown_error` blocks a new launch without deleting
  source-owned or Agent-owned history.

This supersedes the previous consequence that any authority mismatch must
make the conversation disappear from the active CCB resume surface. The
security fence remains; the user-visible continuity guarantee is implemented
by retaining and linking generations rather than by deleting or hiding them.

## Required invariants

1. No CCB clear, kill, cleanup, or restart writes to or logs out the external
   Provider source.
2. A source change is effective after the next stopped Provider generation,
   never by ambient environment reuse.
3. Every native session binding records the authority generation that created
   it and its compatibility outcome.
4. Every fallback continuation links to the prior CCB conversation and
   preserves its transcript, workspace, pending queue, and turn metadata.
5. A failed refresh or rebind leaves the Provider stopped/degraded but leaves
   recoverable local history and a diagnostic action.
6. Legacy migration is idempotent and never treats missing fingerprints as a
   credential mismatch.

## Consequences

- `resume` needs a CCB-level history/index path independent of the Provider's
  native session lookup.
- Provider adapters need two separate results: `native_resume_compatible` and
  `continuation_required`.
- Session records need generation/provenance fields, a parent conversation
  reference, and a non-secret continuity status.
- Authority changes no longer imply destructive archive-and-scrub. Archiving
  remains available for explicit operator isolation or proven unsafe residue.
- Provider capability qualification remains mandatory for native rebind and
  for any rotating OAuth credential; this decision does not authorize cloning
  a rotating refresh token.
