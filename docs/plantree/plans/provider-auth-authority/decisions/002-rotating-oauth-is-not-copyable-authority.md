# Rotating OAuth Is Not Copyable Authority

Date: 2026-08-04

## Context

CCB currently can place the same OAuth payload into different Agent-private
files or namespaced keyring services. Those destinations are physically
separate, but access/refresh tokens may still belong to one rotating or
revocable remote authorization. A refresh or logout by one copy can invalidate
the others or the external CLI.

## Decision

A rotating, remotely mutable, or unknown OAuth credential must not be cloned
and treated as independent Agent authority.

One mutable refresh lineage has exactly one authorized writer. Multiple Agents
or multiple refresh-capable processes must use independently issued credentials
or a proven serialized authority. CCB may inherit external OAuth login status,
but may materialize a usable Agent credential only through a documented
independent derivation/login operation.

Serialization is enforced by a ccbd-owned authority-generation writer lease.
Private homes, adapter metadata, or an assumed Provider lock do not satisfy the
one-writer rule without process-identity and version-qualified enforcement.

Keyring service names, private homes, credential files, and hashes are storage
representations and do not prove remote-session independence.

## Consequences

- Claude and other rotating-OAuth Providers require migration from raw token
  copying.
- The existing Codex single-refresh-stream rule becomes a common Provider rule.
- Provider capability qualification must include refresh and logout semantics.
- Visible/headless execution within one Agent must also respect the one-writer
  rule.
- Static API keys and qualified non-rotating tokens remain eligible for
  one-way projection.
