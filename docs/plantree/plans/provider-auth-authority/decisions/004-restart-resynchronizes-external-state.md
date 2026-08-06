# Restart Resynchronizes External State

Date: 2026-08-04

## Context

One-way inheritance must not turn into a permanent stale snapshot. A user may
log in, log out, switch Provider account or organization, rotate a qualified
static credential, or change external API/route configuration while a CCB Agent
is stopped or running. CCB must follow those changes when the Agent intentionally
uses external inheritance, without hot-mutating a running process or writing
anything back.

## Decision

Every stopped start/restart of an external-inheritance Agent re-reads the real
external Provider authority and synchronizes the next managed generation before
process creation.

- Confirmed present/changed source state replaces the prior source-owned
  projection after capability checks.
- Confirmed logout/removal deletes or deactivates the prior source-owned
  projection and leaves the Agent status-only or unauthenticated.
- Newly present login is re-evaluated, but rotating OAuth is not cloned unless
  an independent credential can be safely derived.
- A previously external-derived credential follows source status only when the
  Provider capability record proves that its validity depends on the source
  session. A truly independent credential is not deactivated merely because
  the source logs out; unknown dependency fails closed for new derivation and
  requires an explicit operator decision for an existing credential.
- Transient, locked, malformed, or unavailable source reads are `unknown`, not
  logout; restart fails closed instead of launching with stale inherited auth.
- Explicit CCB authority and independently Agent-owned login state are outside
  this synchronization and are never overwritten by external changes.
- A synchronized account or authority change fences incompatible Provider
  session resume.

`ccb reload` without Provider replacement is not a synchronization event. The
boundary is creation of a new managed Provider process generation.

## Consequences

- External login/logout and safe API/config changes take effect predictably
  after restart.
- CCB does not preserve stale inherited auth after an authoritative external
  logout.
- Source probes need explicit `present`, `authoritative_absent`, and
  `unknown_error` results.
- Provenance must identify source-owned projections so restart can replace or
  remove them without touching Agent-owned credentials.
- Restart and session binding need an authority/account compatibility fence.
- Tests must cover every external state transition and prove zero reverse
  mutation.
