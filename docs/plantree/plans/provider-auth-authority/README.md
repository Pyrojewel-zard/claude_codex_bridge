# Provider Authentication Authority Plan

Date: 2026-08-04

Status: In progress

## Purpose

Define a Provider authentication and API-configuration model in which CCB may
consume external user state in one direction, but no managed Provider process,
cleanup path, refresh, logout, or configuration update can modify or invalidate
that external state.

The target boundary is:

```text
external Provider state --re-read on stopped restart--> CCB private authority
          ^                                      |               |
          |---------- no reverse edge -----------|               v
                                                        managed process
```

An explicit API key, token, URL, route, or Provider profile in
`.ccb/ccb.config` is CCB-local authority. It applies only to the selected CCB
Agent and must neither inherit a competing external credential nor write its
selection back to the user's shell, Provider home, IDE, OS keyring, or remote
external login session.

## Why This Plan Exists

CCB 8.4.3 introduced private Provider homes and agent-namespaced credential
storage. That isolates filesystem and keyring destinations, but a copied OAuth
access/refresh token can still represent the same remote authorization. Two
private files containing the same rotating refresh token are not two isolated
logins.

The shipped generic contract requires managed logout not to log out another
Agent or the user's external Provider, while its current verification focuses
on local storage mutation. This plan closes the missing server-side authority
boundary.

## Authority

Shipped contracts remain authoritative until implementation and contract
updates land:

- [Provider authentication inheritance contract](../../../provider-auth-inheritance-contract.md)
- [CCB config layout contract](../../../ccb-config-layout-contract.md)
- [Claude session isolation contract](../../../claude-session-isolation-contract.md)
- [Codex session isolation contract](../../../codex-session-isolation-contract.md)

This plan records the accepted direction and required corrections; it does not
claim that current releases already satisfy them.

Within this plan root, decision records define the stable target direction,
topics provide the solution map, and [roadmap.md](roadmap.md) owns planning and
execution order.

## File Map

- [roadmap.md](roadmap.md): phases, readiness gates, and deferred work.
- [implementation-status.md](implementation-status.md): current landed slice,
  verification, and next implementation target.
- [open-questions.md](open-questions.md): unresolved config, migration, and
  Provider-capability questions.
- [topics/authority-and-precedence.md](topics/authority-and-precedence.md):
  authority types, precedence, provenance, and lifecycle rules.
- [topics/oauth-and-provider-capabilities.md](topics/oauth-and-provider-capabilities.md):
  credential classification, rotating OAuth constraints, and Provider
  qualification.
- [topics/config-and-runtime-boundary.md](topics/config-and-runtime-boundary.md):
  `.ccb/ccb.config`, managed environment, cleanup, and diagnostics behavior.
- [topics/code-landing-map.md](topics/code-landing-map.md): source-backed
  call-chain analysis, file-level changes, restart state machine, patch
  sequence, tests, and execution-readiness gates.
- [topics/continuous-inheritance-implementation.md](topics/continuous-inheritance-implementation.md):
  implementation packages for config precedence, stopped-restart refresh,
  stable CCB conversations, generation rebinding, migration, and acceptance.
- [topics/verification-and-rollout.md](topics/verification-and-rollout.md):
  test matrix, migration, rollout, and rollback gates.
- [decisions/001-one-way-external-authority.md](decisions/001-one-way-external-authority.md):
  external state is read-only input with no reverse effect.
- [decisions/002-rotating-oauth-is-not-copyable-authority.md](decisions/002-rotating-oauth-is-not-copyable-authority.md):
  rotating OAuth cannot be treated as safe independent copies.
- [decisions/003-explicit-ccb-authority-and-precedence.md](decisions/003-explicit-ccb-authority-and-precedence.md):
  explicit CCB configuration is Agent-local and suppresses competing inheritance.
- [decisions/004-restart-resynchronizes-external-state.md](decisions/004-restart-resynchronizes-external-state.md):
  stopped restart re-reads and one-way synchronizes external inherited state.
- [decisions/005-composite-authority-dimensions.md](decisions/005-composite-authority-dimensions.md):
  credential, route, account selection, and non-auth config resolve as a
  validated composite rather than one scalar mode.
- [decisions/006-prepared-authority-before-spawn.md](decisions/006-prepared-authority-before-spawn.md):
  authority and writer ownership become durable before Provider spawn and are
  activated only after binding verification.
- [decisions/007-continuous-session-rebinding.md](decisions/007-continuous-session-rebinding.md):
  authority changes refresh the Provider generation without deleting the CCB
  conversation; native resume is capability-gated and otherwise becomes a
  linked continuation.

## Scope

In scope:

- External Provider login, API, account-selection, route, and endpoint state as
  read-only inheritance sources.
- CCB-explicit Agent API configuration and Provider profiles.
- Static secrets, bearer tokens, OS keyrings, rotating OAuth, and
  Provider-native private login state.
- Visible panes and headless subprocesses using the same authority decision.
- Server-side refresh and revocation effects, not only filesystem isolation.
- Provenance, diagnostics, cleanup, migration, and multi-Agent concurrency.
- Codex, Claude, Gemini, and native CLI Providers through a shared capability
  model with Provider-specific narrowing.

Out of scope for the first implementation slice:

- Acquiring credentials from the internet or automatically registering user
  accounts.
- A general OAuth broker owned by CCB.
- Writing external Provider config, repairing external logins, or synchronizing
  managed refresh results back to external state.
- Treating copied credentials as conversation or Agent identity.
- Publishing or releasing before provider-specific qualification is complete.

## Non-Drift Invariants

1. External Provider homes, environment, IDE state, and OS credential services
   are read-only sources to CCB.
2. There is no managed-to-external synchronization, reconciliation, logout,
   revocation, chmod, delete, rename, keyring write, or config write path.
3. A credential with mutable refresh state has exactly one authorized writer.
4. Storage separation does not count as remote authentication isolation.
5. A rotating or remotely revocable external OAuth credential is not cloned
   into concurrent managed writers unless the Provider offers a documented
   operation that derives an independent credential.
6. Explicit CCB API or route configuration is Agent-local, wins in every
   dimension it explicitly owns, rejects incompatible inherited dimensions,
   and is never projected back outside CCB.
7. Inherited snapshots and Agent-owned credentials have explicit provenance;
   one must never silently become the other.
8. Removing or changing CCB authority affects only stopped/restarted managed
   processes and managed state. It never repairs or mutates external state.
9. CCB kill, clear, uninstall, reload, and cleanup remove only CCB-owned state
   and never invoke a remote logout for an inherited credential.
10. Unknown credential rotation, logout scope, or writable storage behavior
    fails closed rather than being guessed safe.
11. Diagnostics may expose kinds, paths, ownership, timestamps, and protected
    fingerprints, but never credential values.
12. An Agent using external inheritance re-reads the external Provider on every
    stopped launch/restart. Confirmed login, logout, account switch, credential
    replacement, and inherited API/route changes replace or remove the
    source-owned managed projection before a new process starts.
13. Explicit CCB authority and independently Agent-owned login state do not
    follow external changes and must never be overwritten by restart
    synchronization.
14. Provider authority is a validated composite of credential, route, account
    selection, and non-auth configuration dimensions; one scalar mode must not
    silently erase or authorize an unrelated dimension.
15. A new Provider writer starts only after its prepared authority generation
    and writer lease are durable. Spawn or activation failure terminates that
    writer and leaves the Agent stopped/degraded.
16. Probe classification and projection consume the same immutable or
    generation-checked external snapshot; an unversioned second read is not
    allowed.

“No reverse interference” protects authentication and configuration authority.
It does not claim that authenticated model use is side-effect free: successful
requests may consume quota, incur billing, appear in Provider audit/history,
and contribute to account rate limits. Those expected data-plane effects must
be attributed to the selected credential and explained separately from
forbidden credential/config mutation.

## Reading Path

Start with [topics/authority-and-precedence.md](topics/authority-and-precedence.md),
then read [topics/oauth-and-provider-capabilities.md](topics/oauth-and-provider-capabilities.md).
Use [topics/config-and-runtime-boundary.md](topics/config-and-runtime-boundary.md)
for config semantics. Before implementation, read the source-backed
[topics/code-landing-map.md](topics/code-landing-map.md), then apply the
acceptance gates in
[topics/verification-and-rollout.md](topics/verification-and-rollout.md).
