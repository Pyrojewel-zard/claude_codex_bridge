# Provider Authentication Authority Roadmap

Date: 2026-08-04

## Status Summary

- Current status: source-backed landing analysis and corrective plan shaping
  complete; production implementation has not started.
- Current phase: close the runtime-home, private-login, legacy-restart, secret
  injection, writer-recovery, and migration gates identified by the
  execution-readiness review.
- Next target: land the behavior-neutral contract/secrecy and observe-only
  authority slices after implementation authorization.

## Done

- Established the one-way external-state requirement and explicit CCB-local
  configuration boundary.
- Confirmed current CCB already gives explicit `key/url` authority precedence
  over inherited API/auth state for supported Providers.
- Confirmed current generic auth verification proves local source immutability
  but does not prove remote OAuth refresh/logout isolation.
- Identified Claude's copied, agent-namespaced Keychain credentials as storage
  isolation over a potentially shared remote OAuth authority.
- Identified the existing Codex contract rule that concurrent Agents must not
  rely on copies of one rotating refresh token; promoted that rule to a common
  Provider invariant.
- Recorded the initial authority, OAuth-safety, config/runtime, verification,
  and rollout design topics.
- Accepted stopped-restart synchronization: Agents in external-inheritance
  mode re-read authoritative external login/account/API state before launch;
  CCB-explicit and independently Agent-owned authority remain unchanged.
- Traced the current start path through
  `_prepare_provider_launch_set`, `prepare_provider_workspace`,
  Provider-specific home materialization, tmux command construction, and
  session persistence.
- Confirmed `ccb restart <agent>` currently respawns the persisted
  `session.start_cmd` without re-materializing profile/home/auth state or
  rebuilding the session. The target restart must quiesce, re-resolve, rebuild,
  and only then respawn.
- Identified the existing unused, storage-classified
  `agents/<agent>/provider.json` path as the sanitized runtime authority
  record, with secret projection provenance kept separately under
  `provider-state`.
- Identified two prerequisite safety gaps: arbitrary writable
  `provider_profile.home` paths and diagnostic export of literal config,
  Agent, or profile secrets.
- Identified an additional current secrecy path: Provider environment values
  may be embedded in persisted `start_cmd` session records that diagnostics
  export byte-for-byte.
- Replaced the scalar authority model with credential, route,
  account-selection, and non-auth config dimensions plus composite validation.
- Required immutable/generation-checked probe snapshots, ccbd-owned writer
  leases, and prepared-before-spawn authority transactions.
- Narrowed external-derived credential synchronization so source logout affects
  it only when Provider capability evidence proves a dependency.
- Added the complete source and patch-series map in
  [topics/code-landing-map.md](topics/code-landing-map.md).

## In Progress

- Close the writable-home boundary for `provider_profile.home`.
- Define the stopped-Agent private-login workflow and legacy-session restart
  behavior.
- Select warning versus enforcement timing for existing cloned rotating OAuth.
- Complete source-backed capability qualification beyond the initial
  Claude/Codex/Gemini targets.
- Define the owner-only runtime secret injection mechanism that replaces
  literal secret-bearing persisted shell commands.
- Define writer-lease crash recovery and process-fencing details across visible
  and headless execution.

## Next

### Phase 1: Contract Reconciliation

1. Update the generic auth inheritance contract to distinguish storage
   representation from remote credential authority.
2. Add the one-mutable-credential/one-writer invariant.
3. Narrow Claude, Codex, Gemini, and applicable native Provider contracts.
4. Specify local-only clear/logout behavior and fail-closed unknown semantics.
5. Close diagnostic/session secrecy for `start_cmd`, launch context,
   runtime/helper records, and crash evidence.

Gate: contracts agree on source authority, precedence, OAuth copy safety, and
remote side-effect boundaries.

### Phase 2: Capability And Authority Resolver

1. Define Provider credential capabilities without serializing secret values.
2. Resolve credential, route, account-selection, and non-auth configuration
   dimensions before materializing any managed home, then validate the
   composite.
3. Reject incompatible composites and unknown rotating OAuth copies.
4. Record non-secret dimensional provenance for later cleanup and diagnosis.
5. Make restart source resolution tri-state: `present`,
   `authoritative_absent`, or `unknown_error`; never treat a transient read
   failure as either valid login or confirmed logout.
6. Bind classification and projection to the same immutable or
   generation-checked source snapshot.
7. Introduce a non-enforcing writer-lease record before behavior changes.

Gate: visible and headless launch preparation obtain the same deterministic
authority result, a stopped restart reflects authoritative external changes,
and no adapter performs ad hoc fallback afterward.

### Phase 3: Provider Adapter Migration

1. Migrate Claude and Codex first because current official-login credentials
   have demonstrated rotation/revocation risk.
2. Qualify Gemini and other OAuth Providers before retaining inheritance.
3. Keep static API-key Providers on the simpler one-way snapshot path.
4. Ensure one Agent credential has one refresh writer even when CCB supports
   both a visible pane and headless execution.
5. Fence provider-session resume when synchronized account or credential
   authority changes, so a conversation cannot silently continue under the
   wrong account authority.
6. Enforce writer leases for visible/headless refresh-capable processes and
   reconcile them after daemon restart.

Gate: every enabled Provider has an explicit capability classification and a
test-backed safe authority path.

### Phase 4: Config And Operator Workflow

1. Preserve `key/url` and advanced `provider_profile.env` as CCB-only
   authority.
2. Add safe secret-reference syntax if accepted; do not require plaintext
   project config for the new design.
3. Provide an Agent-private login workflow for Providers that cannot safely
   inherit rotating OAuth.
4. Make validate/doctor explain selected authority, required restart, and
   re-login action without revealing secrets.

Gate: an operator can predict which credential wins and can recover one Agent
without touching external Provider state.

### Phase 5: Verification And Rollout

1. Add fake OAuth rotation/revocation tests, filesystem/keyring mutation tests,
   config precedence tests, and cleanup tests.
2. Run isolated source-runtime qualification from
   `/home/bfly/yunwei/test_ccb2` using the source `ccb_test` wrapper.
3. Use dedicated disposable Provider accounts only when explicitly authorized;
   never validate logout isolation against a real user's normal login.
4. Stage compatibility diagnostics before enforcing new fail-closed behavior.
5. Update release notes and migration guidance.

Gate: zero external mutation, zero competing credential authority, and no
unsupported claim of independent OAuth sessions.

## Deferred

- A CCB-owned OAuth refresh broker or token-exchange service.
- Automatic account creation or browser login automation.
- Cross-host credential synchronization.
- Secret-vault product integration beyond bounded config references.
- Unsafe compatibility modes that deliberately permit shared rotating OAuth;
  any future proposal requires a separate decision and explicit user opt-in.

## Execution-Readiness Conditions

Readiness is split by patch slice:

- Contract/secrecy and observe-only authority work is ready after explicit
  implementation authorization, provided Slice A includes session commands and
  all serialized launch/runtime evidence. It does not change credential
  selection.
- Shared launch/restart work is ready after the `provider_profile.home` and
  legacy launch-intent decisions close.
- Static projection and rotating-OAuth enforcement are not ready until all
  config, private-login, migration, and Provider capability questions that
  affect behavior are resolved.

Before any enforcement slice:

- the initial Provider capability table must have source-backed entries;
- stopped/running Agent upgrade behavior must be explicit;
- the fake OAuth server must cover rotation, reuse rejection, revocation,
  concurrent refresh, and independent derivation;
- transaction tests must cover source rotation between probe/projection,
  prepared-generation recovery, stale-writer fencing, and mandatory child
  termination after post-spawn failure;
- contract files, implementation surfaces, and test targets must match
  [topics/code-landing-map.md](topics/code-landing-map.md);
- rollback must preserve external no-write and must not recreate unsafe
  credential aliases or delete user state.
