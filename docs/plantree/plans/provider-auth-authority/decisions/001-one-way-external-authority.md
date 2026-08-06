# One-Way External Provider Authority

Date: 2026-08-04

## Context

CCB should benefit from a user's existing Provider login and API configuration,
but managed Providers must not alter the user's shell, IDE, Provider home,
keyring, or remote external login. Filesystem copy isolation alone does not
cover refresh and logout effects on shared remote credentials.

## Decision

External Provider auth, account, API, and route state is read-only inheritance
input. CCB may observe it, copy capability-qualified static state, or use a
Provider-supported operation to derive independent Agent authority. There is no
managed-to-external synchronization or repair path.

Managed refresh, logout, clear, kill, cleanup, and config changes must not
modify or remotely invalidate external authority. If the Provider cannot meet
that boundary, CCB leaves the Agent unauthenticated and requests explicit CCB
API authority or an independent Agent-private login.

Normal authenticated requests may still consume quota, incur billing, and
produce Provider-side audit/history records. Those are expected data-plane
effects of using the selected credential, not permission to mutate external
authentication or configuration authority.

## Consequences

- External login convenience becomes conditional on credential semantics.
- CCB may report that an external account is logged in without reusing its
  mutable credential.
- Unknown Provider behavior fails closed.
- Cleanup is local-only and never uses remote logout as a deletion shortcut.
- Shipped contracts and tests must add server-side isolation, not just source
  path immutability.
