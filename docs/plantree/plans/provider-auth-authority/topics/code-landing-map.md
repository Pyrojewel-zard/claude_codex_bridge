# Code Landing Map

Date: 2026-08-04

Role: Source-backed implementation map and execution-readiness check

Status: Analysis complete; observe-only foundation is ready, enforcement
requires the decisions listed under [Remaining Gates](#remaining-gates).

Read when: converting the accepted authority design into source changes,
reviewing a patch series, or deciding whether a behavior slice is safe to
start.

## Landing Conclusion

The change cannot be implemented safely as another credential-copy condition
inside the Claude, Codex, or Gemini home materializers. Authentication
authority must be resolved as one validated composite, before any Provider home
is written, and the same result must drive visible panes, headless execution,
session binding, cleanup, and diagnostics.

The present start path already has a usable preparation boundary:

```text
AgentSpec/config
  -> ccbd start preparation
  -> prepare_provider_workspace(refresh_profile=True)
  -> Provider-specific home materialization
  -> launcher prepared state / start command
  -> tmux launch
  -> provider session record
```

The present restart path bypasses that boundary:

```text
load old provider session
  -> read session.start_cmd
  -> respawn existing pane with the old command
  -> refresh binding
```

Therefore, the central lifecycle change is:

```text
busy/ownership gate
  -> stop the old Provider writer while retaining pane authority
  -> reload current AgentSpec and launch intent
  -> re-materialize Provider profile
  -> obtain one immutable or generation-checked external snapshot
  -> resolve and validate the composite authority
  -> transactionally update only CCB-owned projection from that snapshot
  -> rebuild secret-free prepared state, cwd, command, and session payload
  -> durably prepare authority/session generation and writer lease
  -> respawn with that prepared generation
  -> verify binding and atomically activate, or terminate the new writer
```

A source read error must leave the Agent stopped and actionable. It must never
respawn with the old credential or old `start_cmd`.

## Current Code Evidence

| Concern | Current source | Finding |
| :--- | :--- | :--- |
| Start preparation | `lib/ccbd/start_preparation.py::_prepare_provider_launch_set` | New launches call `prepare_provider_workspace(..., refresh_profile=True)` before runtime launch. |
| Shared Provider preparation | `lib/cli/services/provider_hooks.py::prepare_provider_workspace` | Resolves the profile, materializes a Provider home, and installs hooks, but has no typed authentication-authority result. |
| Provider dispatch | `lib/cli/services/provider_hooks.py::_materialize_provider_home` | Claude, Codex, Gemini, and native adapters read/copy auth independently, so precedence and error semantics can drift. |
| Pane launch | `lib/cli/services/runtime_launch_runtime/tmux_runtime.py::launch_tmux_runtime` | Builds prepared state, cwd, command, pane, and session in one path that can be extracted and reused. |
| Restart | `lib/ccbd/handlers/project_restart.py::_restart_agent_pane` | Reuses persisted `session.start_cmd`; it does not refresh profile, source state, managed home, command, or session authority. |
| Profile model | `lib/provider_profiles/models.py` | `ProviderProfileSpec` and `ResolvedProviderProfile` carry inheritance booleans and env values, but no provenance, credential class, probe state, writer policy, or authority generation. |
| Explicit shortcut | `lib/agents/config_loader_runtime/parsing_runtime/agent_specs.py::_apply_agent_api_shortcut` | Existing `key/url` compilation already disables inherited API/auth, and Codex config inheritance; this is the correct precedence foundation. |
| Explicit home | `lib/provider_profiles/materializer.py::_resolve_profile_root` | `provider_profile.home` can resolve to any absolute path; treating that path as a writable runtime home would violate the CCB-only boundary. |
| Backend contract | `lib/provider_core/contracts.py::ProviderBackend` | Backends expose execution, session, and runtime-launch adapters, but no authentication probe/materialization capability. |
| Authority path | `lib/storage/paths_agents.py::agent_provider_path` | `agents/<agent>/provider.json` already exists in the path model and storage classification, but is currently unused. |
| Claude auth | `lib/provider_backends/claude/launcher_runtime/home.py` | File and macOS Keychain credentials are copied into managed storage; an existing managed Keychain entry is not reconciled with external rotation/logout. |
| Codex auth | `lib/provider_profiles/codex_home_config.py` | Auth projection and revoked-token refresh can replace a managed copy from the source; this is unsafe for an unqualified rotating OAuth lineage. |
| Gemini auth | `lib/provider_backends/gemini/launcher_runtime/home.py` | OAuth/keyring state can be converted into a managed OAuth file without a common rotation/writer decision. |
| Diagnostics | `lib/cli/services/diagnostics_runtime/sources.py` and `staging.py` | Project config, Agent session files, and JSON records can be copied byte-for-byte; explicit keys and secret-bearing `start_cmd` values in config/profile/Agent/session/runtime evidence require redaction or exclusion. |

## Target Data Model

### Shared contract

Add `lib/provider_core/auth_contracts.py` with immutable, secret-free control
types:

```text
ExternalAuthProbeState
  present | authoritative_absent | unknown_error

CredentialKind
  static_api_key | static_bearer | rotating_oauth
  provider_private | derived_independent | unknown

CredentialAuthorityMode
  ccb_explicit | agent_private | external_static_snapshot
  external_derived | external_status_only
  unauthenticated | reauth_required

RouteAuthorityMode
  ccb_explicit | external_snapshot | provider_default | unavailable

AccountAuthorityMode
  ccb_explicit | agent_private | external_snapshot | unavailable

ConfigInheritanceMode
  ccb_explicit | allowlisted_external | provider_default | disabled

SourceDependency
  independent | requires_source_session | revoked_with_source | unknown

WriterPolicy
  none | single_visible_writer | single_agent_writer
  provider_native_safe_multi_process

ProviderAuthProbe
  state, credential_kind, source_kind, account_hint,
  source_generation_handle, snapshot_handle, error_code

ResolvedProviderAuthority
  credential, route, account, config, probe_state, credential_kind,
  source_dependency, compatibility_result, precedence_reasons,
  projection_actions, writer_policy, generation, lifecycle_state,
  resume_compatible, operator_action
```

`source_generation_handle` is an in-memory or protected-project correlation
handle, not a raw token hash. `snapshot_handle` refers to the exact owner-only
in-memory/ephemeral source snapshot classified by the probe. Projection either
consumes that snapshot or atomically revalidates its generation; it must not
perform an unversioned second source read. No secret value belongs in these
dataclasses' public serialization.

Extend `ProviderBackend` with an optional `auth_adapter`, and expose an
authentication-adapter map from `lib/provider_core/registry.py`. The adapter
owns only Provider facts:

- probe the allowlisted external source without writing it;
- classify known credential storage and rotation semantics;
- apply a resolved projection to a CCB-owned destination;
- report whether independent derivation, local clear, or multiple writers are
  supported;
- return `unknown_error` rather than collapsing access failures into logout.

The generic resolver owns precedence and lifecycle policy; Provider adapters
must not re-decide it.

### Runtime authority record

Use the existing `PathLayout.agent_provider_path(agent)` location for a
sanitized `provider.json` record:

```json
{
  "schema_version": 1,
  "agent": "coder",
  "provider": "claude",
  "credential_authority": "external_status_only",
  "route_authority": "provider_default",
  "account_authority": "external_snapshot",
  "config_authority": "allowlisted_external",
  "credential_kind": "rotating_oauth",
  "probe_state": "present",
  "writer_policy": "none",
  "generation": 7,
  "lifecycle_state": "active",
  "source_action": "observed_not_copied",
  "resume_compatible": false,
  "operator_action": "agent_private_login_required"
}
```

This record is control-plane authority and may be included in redacted
diagnostics. It must contain no token, API key, raw credential document, stable
cross-project hash, or keyring payload.

The authority record moves through a bounded `prepared -> active` lifecycle.
Failed or abandoned prepared generations are diagnosable and cannot authorize
work. Activation occurs only after Provider process identity and binding match
the prepared generation.

Store projection provenance that can correlate source and managed generations
under:

```text
agents/<agent>/provider-state/<provider>/auth-provenance.json
```

That record is owner-only secret material. Add the filename to the Python and
Rust storage classifiers, exclude it from diagnostic bundles, and use a
project-scoped protected HMAC or equivalent local handle instead of a raw
stable SHA-256 token/file identity. The existing Codex
`.ccb-auth-projection.json` should migrate to the same privacy rule rather
than becoming a second authority system.

### Profile versus authority

Keep `ResolvedProviderProfile` as the compiled config/root/environment model.
Do not overload it with observed login state. Introduce one launch aggregate,
for example `PreparedProviderLaunch`, containing:

```text
resolved_profile
resolved_authority
runtime_dir
run_cwd
prepared_state
start_cmd
provider_session_payload
launch_intent
```

This makes initial start and restart consume the same artifact and prevents a
Provider materializer from falling back to ambient state after resolution.
Secret environment values are represented only by owner-only runtime
references; neither `launch_intent` nor persisted `start_cmd` may contain them.

## Config Compilation Changes

### Preserve the current public surface first

The first implementation should keep `inherit_auth`, `inherit_api`,
`inherit_config`, `key/url`, and `provider_profile.env`. Compile them to
the internal typed authority model before adding a new public
`auth_source` field.

Required parser/validator changes:

1. Continue compiling supported `key/url` into `ccb_explicit`.
2. Classify every Provider auth, API, route, and account-selection key in
   `agents.<name>.env` or `provider_profile.env` into its owned authority
   dimension using Provider allowlists.
3. Resolve dimensions independently, then reject incompatible composites. The
   existing `key/url` shortcut remains an intentional complete
   credential-and-route selection.
4. Never fall back to external auth when explicit CCB authority is invalid or
   rejected by the Provider.
5. Keep non-auth config inheritance only through Provider-specific field
   allowlists.

Affected files:

- `lib/provider_profiles/api_shortcuts.py`: expose Provider auth/route key
  classification rather than only shortcut emission.
- `lib/agents/config_loader_runtime/parsing_runtime/agent_specs.py`: compile
  all explicit auth routes to one authority selection.
- `lib/agents/config_loader_runtime/parsing_runtime/provider_profiles.py` and
  `common.py`: validate the final inheritance combination.
- `lib/provider_profiles/models.py`: keep public profile fields stable; add
  only safe helpers needed for authority compilation.

### Resolve `provider_profile.home` before behavior enforcement

Current code may use an arbitrary absolute `provider_profile.home` as a
writable runtime root. The implementation must choose and validate one of
these semantics:

- recommended: `home` is a read-only source profile, while writable runtime
  state always lives under
  `agent_provider_state_dir(agent, provider)/home`; or
- constrain `home` to a CCB-owned path proven to be within the managed state
  root.

Do not ship authority enforcement while an external Provider home can still
be selected as the managed write destination.

### Secret serialization

Before documenting explicit API config as bundle-safe:

- redact secret fields when serializing `AgentSpec` and resolved profiles for
  diagnostics, or store only secret references;
- make diagnostic staging use category-aware sanitized JSON/TOML serializers
  for `.ccb/ccb.config`, `agent.json`, and
  `provider-profile.json`;
- remove literal secrets from persisted `start_cmd`, Provider session JSON,
  structured launch intent, launch context, runtime/helper records, and crash
  evidence, or apply category-aware redaction before each can enter a bundle;
- migrate or redact legacy session records whose shell commands embed secret
  environment values;
- add regression fixtures proving literal keys never enter the archive.

This security fix may land independently before the larger authority behavior.

## Shared Launch Preparation

Extract the non-tmux portion of
`lib/cli/services/runtime_launch_runtime/tmux_runtime.py::launch_tmux_runtime`
into a reusable service, for example:

```text
lib/cli/services/runtime_launch_runtime/provider_launch_preparation.py
  prepare_provider_launch(...)
  commit_provider_launch_session(...)
```

`prepare_provider_launch` must:

1. materialize the current Provider profile;
2. resolve the external source anchor through
   `provider_core/source_home.py`, never through a managed pane's HOME;
3. invoke the registered auth probe exactly once to obtain an immutable or
   generation-checked snapshot;
4. resolve each authority dimension and validate the composite;
5. apply a transactional, provenance-aware managed projection from that same
   snapshot;
6. create Provider launcher prepared state and cwd;
7. build a fresh start command and session payload;
8. return the sanitized authority generation.

Initial start continues to call preparation from
`lib/ccbd/start_preparation.py`, but passes the resulting launch aggregate
forward instead of re-resolving later. Runtime launch consumes it without an
ambient fallback.

Any headless execution path in `lib/provider_execution/` must bind to the
same Agent authority generation. It may share a qualified Provider-native lock
or be serialized behind the one Agent writer; it may not create another
mutable credential copy.

### Writer lease authority

Add a ccbd-owned writer-lease service keyed by Agent, Provider, and composite
authority generation. It records permitted process class and verified process
identity, fences older generations before projection, and reconciles live
processes after daemon restart. Visible and headless execution must acquire or
join this lease before they can use refresh-capable authority. Adapter-reported
`WriterPolicy` is capability input; the lease service is enforcement.

## Restart State Machine

Replace the old-command respawn in
`lib/ccbd/handlers/project_restart.py::_restart_agent_pane` with these
states:

| State | Required behavior | Failure result |
| :--- | :--- | :--- |
| `gate` | Confirm current-graph Agent, no active job/delivery, valid pane ownership, and restart-compatible Role state. | Return blocked/failed without touching the process. |
| `quiesce` | Stop the owned Provider writer and retain pane/slot authority; wait until the old process identity is gone. | Report failed; never prepare over a live writer. |
| `resolve` | Load current AgentSpec and structured launch intent, refresh profile, probe external state, and resolve authority. | Leave Agent stopped/degraded with an actionable reason. |
| `project` | Atomically replace/remove only source-owned CCB projection from the probed snapshot; preserve proven `agent_private` state. | Leave stopped; do not reuse old projection. |
| `prepare` | Recompute cwd, prepared state, secret-free command/launch intent, Provider payload, authority/session generation, and durably record the prepared authority plus writer lease. | Leave stopped; old command is not fallback authority. |
| `respawn` | Respawn the retained pane with the prepared generation and apply pane identity. | Terminate any partial child and report stopped/degraded. |
| `activate` | Verify process identity, roots, session binding, and generation, then atomically activate session and sanitized `provider.json`. | Terminate the new writer, retain failed prepared evidence, and do not advertise ready. |

`terminal_runtime/tmux_respawn_service.py` and the tmux backend need one
control-plane quiesce primitive. It must operate on the verified pane id, retain
the slot, and avoid raw out-of-band tmux mutation.

Do not parse the old shell command to recover options. Persist a non-secret
structured launch-intent section in the Provider session record, including the
effective start-policy fields required to rebuild the command. Old sessions
without that field use deterministic current defaults or return
`restart_requires_full_start`; they must not silently inherit stale auth
environment from the string.

Persisted `start_cmd` is not allowed to carry literal auth/API environment
values. Secret references are resolved only inside the owner-controlled spawn
boundary and are excluded from session, runtime, logs, and diagnostics.

`ccb reload` remains config materialization only. It does not probe, copy,
delete, or rotate authentication state. Synchronization occurs only when an
actual stopped Provider launch crosses `resolve`.

## Provider-Specific Landing

### Claude

Change `lib/provider_backends/claude/launcher_runtime/home.py` so
`_materialize_auth` receives a `ResolvedProviderAuthority` and an explicit
projection action.

- Split macOS Keychain probe from managed Keychain seed.
- Preserve Keychain errors as `unknown_error`; do not collapse them into
  absence.
- Reconcile an inherited managed entry on confirmed source replacement/logout.
- Preserve a managed entry only when provenance says `agent_private`.
- Treat official rotating OAuth as `external_status_only` until an
  independent derivation capability is proven.
- Keep Provider login/logout disabled in ordinary managed sessions; introduce
  a separate stopped-Agent private-login workflow before enforcement.

The Claude isolation contract's current “preserve managed auth when the source
disappears” rule must be narrowed by provenance: preserve
`agent_private`, remove an inherited source-owned projection.

### Codex

Refactor `lib/provider_profiles/codex_home_config.py` so auth projection is
an action supplied by the resolver.

- Remove automatic source replacement for revoked managed rotating OAuth.
- Retain copy/refresh only for capability-qualified static snapshots.
- Replace raw file SHA correlation in
  `.ccb-auth-projection.json` with protected, project-local provenance.
- Extend `lib/provider_backends/codex/session_authority.py` from explicit
  route fingerprinting to the generic authority generation.
- Fence resume when account/authority generation changes.

Existing revoked-token recovery tests in
`test/test_codex_session_ensure_pane.py` must be rewritten: a new external
rotating token is observed after restart but is not cloned into another
writer.

### Gemini

Change `lib/provider_backends/gemini/launcher_runtime/home.py` to separate
file/keyring probe from projection.

- Treat OAuth/keyring state as rotating or unknown unless qualified.
- Do not convert external keyring OAuth into a managed writable file by
  default.
- Apply authoritative absence only to a proven inherited projection.
- Verify that the external source-home/keyring probe uses the common source
  anchor and is reachable in the normal launch path.

### Other Providers

Register capabilities incrementally. The safe default for an unclassified
adapter is `unknown` plus status-only/fail-closed for credential copying.
Do not switch every native Provider to enforcement until an operator workflow
and migration path exist; the first behavior slice should cover Claude, Codex,
and Gemini.

## File-Level Change Set

### New shared files

| File | Responsibility |
| :--- | :--- |
| `lib/provider_core/auth_contracts.py` | Secret-free enums, probe/result/capability dataclasses, and auth-adapter contract. |
| `lib/provider_auth/resolver.py` | Generic precedence, tri-state resolution, capability checks, and one-writer policy. |
| `lib/provider_auth/store.py` | Atomic sanitized `provider.json` read/write and schema migration. |
| `lib/provider_auth/provenance.py` | Owner-only protected projection lineage and ownership checks. |
| `lib/provider_auth/writer_lease.py` | ccbd-owned generation lease, process fencing, and visible/headless writer enforcement. |
| `lib/cli/services/runtime_launch_runtime/provider_launch_preparation.py` | Shared initial-start/restart preparation and fresh command/session construction. |

### Existing integration files

| File | Planned change |
| :--- | :--- |
| `lib/provider_core/contracts.py` | Add optional `auth_adapter` to `ProviderBackend`. |
| `lib/provider_core/registry.py` and `registry_runtime.py` | Register and expose Provider auth adapters/capabilities. |
| `lib/provider_profiles/materializer.py` | Separate read-only profile source from CCB-owned writable runtime home; stop serializing unsafe secret values. |
| `lib/cli/services/provider_hooks.py` | Consume one resolved composite authority and pass explicit per-dimension projection actions to Provider materializers. |
| `lib/ccbd/start_preparation.py` | Prepare and retain a launch aggregate for every actual new launch. |
| `lib/cli/services/runtime_launch_runtime/tmux_runtime.py` | Consume shared preparation instead of rebuilding it ad hoc. |
| `lib/cli/services/runtime_launch_runtime/session_files.py` | Persist secret-free launch intent, prepared/active authority generation, and safe command metadata; migrate legacy secret-bearing commands. |
| `lib/ccbd/handlers/project_restart.py` | Implement quiesce/resolve/project/prepare/respawn/activate with mandatory post-spawn cleanup instead of old-command respawn. |
| `lib/terminal_runtime/tmux_respawn_service.py` | Add verified pane quiesce and stopped-pane failure handling. |
| `lib/provider_execution/service.py` and active-start paths | Require the current authority generation and acquire/join the ccbd writer lease. |
| `lib/cli/services/doctor_runtime/agents.py` | Report sanitized authority dimensions, compatibility, probe state, generation, lease state, and required action. |
| `lib/cli/services/diagnostics_runtime/sources.py` and `staging.py` | Redact config/Agent/profile/session/runtime secrets, sanitize command-bearing records, and exclude provenance. |
| `lib/storage_classification/provider_home.py` and `service.py` | Classify new provenance as secret and `provider.json` as sanitized authority. |
| `tools/ccb-rs-helper/src/main.rs` | Mirror Python storage classification. |

### Contract files changed in the same patch series

- `docs/provider-auth-inheritance-contract.md`
- `docs/ccb-provider-state-storage-boundary-plan.md`
- `docs/ccb-config-layout-contract.md`
- `docs/ccbd-startup-supervision-contract.md`
- `docs/ccbd-diagnostics-contract.md`
- `docs/claude-session-isolation-contract.md`
- `docs/codex-session-isolation-contract.md`
- `docs/gemini-session-isolation-contract.md`

## Patch Series

### Slice A: Contracts and secrecy

- Update contracts to separate filesystem isolation from remote authority.
- Add diagnostic redaction for config, AgentSpec, and resolved profile data.
- Remove or redact secret-bearing persisted `start_cmd`, Provider session,
  launch-context, runtime/helper, and crash-log fields, including legacy
  records selected for diagnostics.
- Add the owner-only provenance storage classification.
- No authentication behavior changes.

Acceptance: secret fixtures never appear in any persisted launch/session record
or diagnostic bundle; external paths remain read-only.

### Slice B: Observe-only authority core

- Add composite auth contracts, registry wiring, resolver, sanitized store,
  source snapshot handles, writer-lease schema, and doctor output.
- Register initial Claude/Codex/Gemini capability probes.
- Keep current projection behavior behind compatibility mode, but emit precise
  `safe`, `status_only`, `duplicate_writer_risk`, and
  `reauth_required` diagnostics.

Acceptance: all launch surfaces compute the same dimensional composite and
generation without changing credentials; a source change between probe and
projection is detected rather than copied under stale classification.

### Slice C: Shared launch and true restart synchronization

- Extract `PreparedProviderLaunch`.
- Persist structured launch intent.
- Make initial start and restart use the same preparation.
- Quiesce before source probe/projection; block stale launch on
  `unknown_error`.
- Persist the prepared authority/session generation and writer lease before
  spawn, then activate only after binding verification.
- Terminate a newly spawned writer on every activation/commit failure.
- Fence Provider-session resume on authority generation changes.

Acceptance: external static login/change/logout is reflected after restart;
explicit/private Agents ignore external changes; old `start_cmd` is never
the restart authority.

### Slice D: Provenance-aware static projection

- Make Provider materializers action-driven.
- Transactionally synchronize qualified static credentials.
- Remove only source-owned inherited projections on authoritative absence.
- Preserve proven Agent-private state.

Acceptance: source file/keyring metadata and content remain unchanged across
start, refresh simulation, restart, clear, kill, and cleanup.

### Slice E: Rotating OAuth enforcement

- Stop new rotating OAuth clones for Claude/Codex/Gemini.
- Remove automatic clone-based revoked-token recovery.
- Add the stopped-Agent private-login or explicit-API recovery workflow.
- Migrate existing copies using a warning/enforcement policy selected by the
  operator decision.

Acceptance: a fake rotating OAuth lineage has one writer, concurrent reuse is
rejected, and Agent cleanup cannot revoke external or another Agent's login.

### Slice F: Provider qualification and rollout

- Classify remaining Providers.
- Run isolated source-runtime and disposable-account checks where authorized.
- Publish unsupported/qualified modes, migration notes, and rollback evidence.

## Test Landing Matrix

| Area | Existing/new test targets | Required assertions |
| :--- | :--- | :--- |
| Resolver/store | new `test/test_provider_auth_authority.py` | Per-dimension precedence, composite compatibility, tri-state probe, credential class, source dependency, generation, prepared/active lifecycle, and atomic sanitized record. |
| Config | `test/test_provider_profiles.py`, config-loader tests | Explicit env/shortcut suppression, dual-authority rejection, managed-home boundary, no fallback. |
| Start preparation | `test/test_ccbd_start_preparation.py`, `test/test_v2_ccbd_start_flow.py`, `test/test_v2_runtime_launch.py` | One resolution per launch and the same aggregate reaches command/session construction. |
| Restart | `test/test_ccb_restart.py`, `test/test_v2_runtime_launch_session_files.py` | Old writer stopped first, prepared authority durable before spawn, fresh secret-free command built, source changes synchronized, unknown probe leaves stopped, post-spawn commit failure kills the new writer, and legacy session behavior is explicit. |
| Claude/Codex/Gemini | `test/test_provider_profiles.py`, `test/test_codex_session_ensure_pane.py` plus focused new tests | Provenance-aware removal/preservation, status-only OAuth, no automatic rotating clone, account-change resume fence. |
| Diagnostics | `test/test_v2_diagnostics_bundle.py`, doctor tests | Literal keys/tokens absent from config, session `start_cmd`, launch context, runtime/helper records, crash logs, and bundles; sanitized authority/action present; provenance excluded. |
| Storage | `test/test_storage_classification.py` and Rust helper tests | Python/Rust classification parity for provider authority and secret provenance. |
| Supervision | ccbd supervision/start matrix tests | Failed probe never advertises mounted/ready Provider and never respawns stale authority. |
| OAuth semantics | new local fake OAuth server fixture | Rotation, reuse rejection, per-credential/account-wide revoke, concurrency, independent derivation. |
| Snapshot/lease races | new authority transaction tests | Source rotation between probe/projection is rejected; stale generations are fenced; visible/headless writer acquisition is serialized; daemon recovery reconciles live identity. |

Unit and fake-server tests must use synthetic credentials. Later source-runtime
validation must run from `/home/bfly/yunwei/test_ccb2` with:

```bash
cd /home/bfly/yunwei/test_ccb2
HOME=/home/bfly/yunwei/test_ccb2/source_home \
CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home \
/home/bfly/yunwei/ccb_source/ccb_test --diagnose
```

Then run the selected source test workflow with the same isolated HOME. Tests
that deliberately exercise real inherited state require explicit scope and
must not use the source checkout as the live runtime project.

## Failure And Rollback Rules

- A restart that has quiesced the old writer but cannot resolve new authority
  fails stopped; it does not restore the old command automatically.
- Rollback may run an older binary but may not reconstruct an inherited token
  copy from secret provenance.
- Schema readers must tolerate absent `provider.json` and old session records
  during the compatibility phase.
- A behavior slice may be disabled by a local compatibility flag, but the
  external no-write and diagnostics-redaction boundaries are never disabled.
- No migration step calls Provider logout/revoke or deletes external state.

## Remaining Gates

The full enforcement series is not implementation-ready until these decisions
are closed:

1. Define `provider_profile.home` as a read-only source or constrain it to a
   CCB-owned writable root.
2. Select the stopped-Agent private-login workflow for rotating OAuth
   Providers.
3. Choose immediate enforcement versus a warning-only compatibility release
   for existing clones.
4. Define legacy-session restart behavior when structured launch intent is
   absent.
5. Decide whether removal of explicit CCB authority automatically returns to
   external inheritance or requires explicit selection.
6. Qualify source-dependency semantics for every Provider operation claimed to
   produce an independent credential.

Slice A is ready to implement independently. Slice B is ready for schema and
observe-only work once its source snapshot and writer-lease records are kept
non-enforcing. Slice C is ready after gates 1 and 4. Slices D and E require all
six decisions plus Provider capability evidence.
