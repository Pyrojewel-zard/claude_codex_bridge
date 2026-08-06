# Authentication Authority And Precedence

Date: 2026-08-04

Role: Target authority model

Status: Planning

Read when: changing Provider auth inheritance, config precedence, managed-home
materialization, restart, or cleanup.

## Separate The State Classes

CCB must not treat all Provider state as one copyable bundle.

| State class | Examples | External inheritance | Managed mutation |
| :--- | :--- | :--- | :--- |
| Login status and account metadata | logged-in flag, account id, organization selection | Read-only observation or allowlisted snapshot | May update only Agent-private metadata |
| Static credential authority | API key, documented non-rotating bearer/setup token | Private copy when Provider semantics are qualified | No refresh; local deletion only |
| Rotating credential authority | OAuth access/refresh pair, device session | Status only unless an independent credential can be derived | Only an independently Agent-owned credential may refresh |
| API route configuration | base URL, endpoint, account/profile selector | One-way allowlisted snapshot | Agent-private overlay only |
| Explicit CCB authority | `key/url`, Provider API env, profile route | Does not inherit competing external auth/API state | CCB-managed state only |
| Provider runtime state | sessions, caches, logs, conversation ids | Never auth authority | Agent-private only |

Login status is evidence that an external Provider can authenticate. It is not
permission to clone a rotating credential into multiple writers.

## Meaning Of No Reverse Interference

Prohibited control-plane effects include:

- changing, rotating, revoking, or logging out external credentials;
- modifying external account/organization/profile selection;
- writing external Provider config, shell environment, IDE state, or keyrings;
- using managed state to repair or overwrite its external source;
- making another Agent or external client lose authentication validity.

Expected data-plane effects are not classified as reverse configuration
interference:

- inference/API requests;
- quota and rate-limit consumption;
- billing or subscription usage;
- Provider-side audit, history, abuse, or security records caused by requests.

Diagnostics and documentation must keep these categories separate. Explicit
CCB API authority isolates credential and route selection, but it does not
isolate account-level quota when several credentials belong to one account.

## Composite Authority

Launch preparation resolves one validated composite per Agent and Provider.
The composite has at least four separately sourced dimensions:

1. credential authority;
2. API endpoint and route authority;
3. account, organization, or Provider-profile selection;
4. non-auth configuration inheritance.

Each dimension records its source, precedence reason, provenance, and
generation. The aggregate generation changes when any session-relevant
dimension changes. Provider-specific compatibility rules may reject a
combination, but an explicit value in one dimension must not silently erase or
authorize an unrelated dimension.

### Credential Modes

The credential dimension resolves one of:

1. `ccb_explicit`
   - Selected by explicit Agent API/token/route configuration.
   - Suppresses inherited auth, API, and conflicting route state.
   - Materializes only inside CCB-managed roots/environment.
2. `agent_private`
   - Selected when inheritance is disabled and the Agent already owns an
     independently acquired private login.
   - Preserves that login across restart and never promotes it to source state.
3. `external_derived`
   - Selected only when the Provider exposes a documented operation that derives
     a distinct credential from external authority without mutating or
     invalidating it; source-dependency capability separately determines
     whether the child remains valid after source changes.
4. `external_static_snapshot`
   - Selected for qualified static, non-rotating credentials and API config.
   - Refreshed one-way at stopped launch; source removal removes the inherited
     projection rather than converting it into Agent-owned state.
5. `external_status_only`
   - External login/account state is visible, but its mutable credential cannot
     safely be copied. The Agent remains unauthenticated until it receives
     explicit or independent private authority.
6. `unauthenticated`
   - No safe authority exists. Startup or work submission fails with an
     actionable, non-secret explanation.

These credential modes are mutually exclusive for one launch. Route,
account-selection, and non-auth config decisions remain explicit sibling
dimensions. A Provider adapter must not silently fall through from explicit
CCB authority to an ambient external login.

## Precedence

Highest precedence wins within each dimension:

```text
explicit Agent CCB config
    > existing independent Agent-private login
    > safely derived independent external credential
    > qualified static external snapshot
    > external status only
    > unauthenticated
```

Precedence does not authorize overwriting a lower authority or a sibling
dimension. It determines which source is selected for that dimension, after
which the composite compatibility validator accepts or rejects the complete
launch.

Examples:

- `[agents.a] key/url` wins and disables external login/API inheritance.
- An advanced explicit endpoint without an explicit credential suppresses only
  inherited route authority unless the Provider declares that endpoint and
  credential selection are inseparable; the final composite must still have a
  valid credential path.
- `inherit_auth=false` with an existing Agent-private login preserves that
  login; global credentials are not copied over it.
- An external static API key may be inherited when no explicit or Agent-private
  authority exists.
- An external rotating OAuth login may make diagnostics report “external login
  available”, but it does not become a managed credential copy.

## Provenance

Every materialized auth/config artifact needs non-secret provenance:

- authority mode;
- Provider and Agent identity;
- source class, not secret source value;
- credential kind and capability classification;
- materialization generation and timestamp;
- protected fingerprint or change marker when needed;
- whether cleanup may delete the managed artifact;
- whether refresh is allowed and which process owns it.

Provenance must distinguish:

- `inherited_snapshot`: follows source changes on a future stopped launch;
- `derived_independent`: CCB/Agent owns the derived credential only;
- `agent_login`: created directly under private managed roots;
- `ccb_explicit`: compiled from `.ccb/ccb.config` or its referenced secret;
- `provider_runtime`: never reusable as auth source.

An inherited snapshot must never silently become an Agent login merely because
the external source disappears. An Agent login must never be overwritten by a
later ambient source projection.

## Restart Synchronization

Every actual Provider process start or restart first resolves the external
source again when the selected policy is external inheritance. Restart
synchronization is one-way and authoritative for source-owned projections:

| External observation | Managed result before launch |
| :--- | :--- |
| Login/API/config present and unchanged | Keep or idempotently refresh the source-owned projection |
| Login/API/config present and changed | Replace the old source-owned projection with the new qualified state |
| Account or organization changed | Replace inherited metadata/qualified authority and fence incompatible Provider session resume |
| Authoritatively logged out or source removed | Remove the source-owned managed projection and resolve to status-only or unauthenticated |
| Newly logged in | Re-run capability resolution; project only safe static state or derive an independent credential |
| Source read is unknown, locked, timed out, or malformed | Do not launch with stale inherited authority; preserve external state and report a retryable source-resolution failure |

The source probe must distinguish `authoritative_absent` from `unknown_error`.
A transient Keychain or file-read error is not proof of logout. It also must not
authorize reuse of the last inherited credential as if it were current.

Synchronization applies only at a stopped launch boundary. A running Provider
process is never hot-mutated when the external login changes. `ccb reload`
alone may report restart intent, but it is not a credential synchronization
event.

For rotating OAuth, synchronization means updating external login/account
status and re-running safe capability selection. It does not permit raw refresh
token cloning. If the new external login cannot yield independent Agent
authority, the restarted Agent remains unauthenticated with a specific action.

The following modes intentionally ignore external login changes:

- `ccb_explicit`, until its CCB config changes;
- `agent_private`, until its private login changes.

An external-derived credential records a Provider-qualified source-dependency
mode:

- `independent`: source logout does not deactivate it;
- `requires_source_session`: source logout deactivates its local selection;
- `revoked_with_source`: it is treated as unusable after authoritative source
  logout;
- `unknown`: new derivation fails closed and existing use requires an explicit
  migration/operator decision.

An account switch requires compatibility evidence, re-derivation, or explicit
operator action. CCB never infers dependency merely from the fact that the
credential was originally derived from an external login.

## Writer Ownership

`WriterPolicy` is enforced by a ccbd-owned generation lease rather than
remaining adapter advice. The lease identifies the Agent, Provider, composite
authority generation, permitted process class, and verified process identity.

- Visible and headless paths must acquire or join the same compatible lease.
- A new generation fences the prior generation before projection or spawn.
- A daemon restart reconciles leases against live process identity before
  accepting work.
- Generation mismatch, unknown process identity, or an additional unqualified
  refresh-capable process fails closed.
- Provider-native multi-process locking is accepted only after capability and
  version qualification.

## Lifecycle Rules

- Materialization occurs before Provider process creation.
- A running process is never re-projected underneath.
- Config changes affecting authority require stopped replacement/restart.
- Reload may record restart intent but must not mutate the running Provider's
  credential roots.
- Kill and cleanup may delete only provenance-marked CCB-owned artifacts.
- Clear means conversation/context clear, not remote authentication logout.
- Local credential removal must not call remote revoke/logout unless the
  credential is independently Agent-owned and Provider scope is proven safe.
- External-inheritance restart must complete source resolution and remove or
  replace obsolete source-owned projections before process creation.
- An authority/account fingerprint change fences incompatible Provider-session
  resume and starts fresh unless Provider-specific evidence proves continuity
  safe.
- A Provider writer starts only after its authority generation and writer lease
  are durably prepared. Failure after spawn terminates the new writer before
  the Agent is reported stopped/degraded.

Related decisions:

- [One-Way External Authority](../decisions/001-one-way-external-authority.md)
- [Explicit CCB Authority And Precedence](../decisions/003-explicit-ccb-authority-and-precedence.md)
- [Restart Resynchronizes External State](../decisions/004-restart-resynchronizes-external-state.md)
- [Composite Provider Authority Dimensions](../decisions/005-composite-authority-dimensions.md)
- [Prepared Authority Before Provider Spawn](../decisions/006-prepared-authority-before-spawn.md)
