# Provider Asset Projection Contract

## 1. Purpose

This document defines the common projection process for system provider assets,
CCB control assets, Role assets, generated configuration, MCP configuration,
authentication state, and provider-writable state inside managed CCB agents.

Provider-specific contracts may narrow these rules, but they must not weaken the
source, effective-root, ownership, secret-isolation, or refresh boundaries here.

## 2. Projection Pipeline

Every managed projection follows this order:

1. Resolve the source authority.
   - Use the real account home or explicit `CCB_SOURCE_HOME`.
   - Never use another managed provider home as the inheritance source.
   - Packaged CCB control skills come from `inherit_skills/<provider>_skills/`.
   - Role skills come from the installed immutable Role snapshot.
2. Resolve the effective consumer root.
   - Resolve provider flags and environment variables before projecting.
   - The path actually read by the provider is authoritative.
   - A default managed-home path must not be used when a provider flag selects
     another config root.
3. Classify each asset by mutability and sensitivity.
4. Apply the matching projection mechanism.
5. Write or validate CCB ownership evidence.
6. Launch the provider only after required projections are ready.
7. Refresh again only on a managed launch or relaunch, never underneath an
   already running identity-proven binding.

The core invariant is:

`source authority -> resolved effective root -> asset-specific projection`

Changing an environment variable or provider flag that changes the effective
root requires changing the projection target and migration logic in the same
patch.

## 3. Projection Mechanisms

### 3.1 Immutable optional assets

Examples include system skills, commands, and immutable Role skill snapshots.

- Project each independent skill as its own entry.
- Prefer a symlink to the read-only source.
- If symlinks are unavailable, use a marked copy.
- One missing, broken, or conflicting entry must not suppress other valid
  entries.
- A local unmarked target entry is user/provider-owned and must be preserved.
- The parent `skills/` directory remains local so provider-created, user-created,
  Role, optional inherited, and required CCB entries can coexist.

### 3.2 Mandatory CCB control assets

Examples are `ask`, `ccb-clear`, `ccb-compact`, `ccb-diagnose`, and
provider-specific controls such as Codex `reconnect`.

- Project them independently of `inherit_skills`.
- Repair only the reserved CCB-owned names.
- Preserve every unrelated entry.
- Fail launch when a required packaged source is missing or cannot be made
  readable in a CCB-managed target.

### 3.3 Immutable coupled bundles

Internally coupled trees, such as the Codex plugin bundle, may use a
content-addressed shared bundle and a marked route into the managed home.
Replacement is atomic at bundle granularity.

### 3.4 Provider-writable trees

Plugin caches, extension roots, marketplaces, and other provider-writable state
must be agent-local. They may be seeded through a staged copy, but must not be
linked to the source account or another agent.

### 3.5 Generated config and MCP state

Generated config and MCP state are merged into the provider's effective config
file. They are not generic directory projections.

- Preserve provider-written fields that CCB does not own.
- Refresh only allowlisted inherited fields.
- Map project-scoped MCP state to the current managed workspace.
- Do not copy unrelated source project records.
- MCP definitions may contain secrets and must be classified accordingly.

### 3.6 Authentication and credential state

Authentication projection is one-way copy-only:

- no symlink, hard link, junction, mount, or reverse synchronization;
- no write-through path to the source account;
- no diagnostic export of copied secrets;
- preserve compatible agent-local login state when the provider-specific
  contract permits it;
- record projected files and auth-bearing fields in an owner-only, non-secret
  provenance manifest;
- on confirmed source absence, remove only entries recorded as source-owned;
- on a malformed/missing manifest, preserve unmarked local state rather than
  inferring ownership from path or content;
- on a source read, permission, parse, or credential-service error, fail the
  launch preparation without deleting the prior projection.

Auth source state is tri-state: `present`, `authoritative_absent`, or
`unknown_error`. Projection and cleanup must consume the same classified source
snapshot; a second unversioned read must not turn an error into absence.

## 4. Ownership And Conflict Rules

A replaceable projection is owned only when a local regular-file marker records:

- schema version `1`;
- record type `ccb_projected_asset`;
- exact consumer label;
- non-empty source;
- recognized mode such as `symlink`, `copy`, or `copy-seed`.

Content equality and residence under `.ccb` do not grant ownership.

For per-entry skill projection:

- target absent: create the projection;
- target has a matching marker: refresh or remove it as required;
- target is unmarked: preserve it and continue with other entries;
- marker is malformed, foreign, or has the wrong label: preserve and fail that
  entry closed;
- source disappears or inheritance is disabled: remove only matching
  CCB-owned entries.

## 5. Effective-Root Matrix

| Provider | Source authority | Effective target | Important rule |
| --- | --- | --- | --- |
| Codex | `<source CODEX_HOME>/skills` | `<managed CODEX_HOME>/skills` | Project optional skills per entry; `.system` is one nested collection entry. |
| Claude | `<source HOME>/.claude/skills` | `$CLAUDE_CONFIG_DIR/skills` | Active trust/MCP state is `$CLAUDE_CONFIG_DIR/.claude.json`, not `$HOME/.claude.json`. |
| Qoder | `<source HOME>/.qoder/skills` | `<effective --config-dir>/skills` | Resolve explicit or managed `--config-dir` before projection. |
| Qoder CLI CN | `<source HOME>/.qoder-cn/skills` | `<effective --config-dir>/skills` | Keep the released provider key `qoderclicn`; it shares packaged CCB controls with Qoder. |
| Role skills | installed immutable Role snapshot | provider-native managed skills root | Symlink-first, marker-owned, adopted on managed restart. |

An explicit Qoder config root that is exactly the source account config root is
external user authority. CCB must not inject markers or replace reserved names
inside it.

## 6. Refresh And Followability

Symlinks provide file-content followability, not process hot reload.

- Source edits become visible through a valid symlink immediately at the
  filesystem level.
- A running provider may cache skill discovery; CCB does not promise hot reload.
- Source entry additions/removals, profile filters, effective-root changes, and
  Role snapshot changes are adopted on the next managed launch or relaunch.
- Accepting a live binding performs no background projection mutation.

## 7. Migration Rules

Migration must be explicit whenever the provider's effective path changes.

For Claude releases that honor explicit `CLAUDE_CONFIG_DIR`:

- active state is `<managed-home>/.claude/.claude.json`;
- legacy CCB state may exist at `<managed-home>/.claude.json`;
- startup recursively merges legacy state first and active provider state
  second, then applies current source-home allowlisted projection;
- the active file is written atomically;
- the legacy file is removed only after the active write succeeds.

For legacy whole-tree Codex skill projections:

- remove the whole-tree target only when its matching root marker proves CCB
  ownership;
- re-project valid skills as independently marked entries;
- preserve unmarked local entries and conflicts.

## 8. Test Requirements

Changes to provider projection must test:

- source and effective target resolution;
- default and explicit provider config roots;
- symlink success and marked-copy fallback;
- unmarked conflict preservation;
- stale owned-entry cleanup;
- broken optional entry isolation;
- required control readiness with optional inheritance disabled;
- secret classification and diagnostic exclusion;
- legacy-path migration with mixed old/new state;
- visible and headless processes consuming the same resolved root.
- owner-only auth provenance mode and malformed-manifest preservation;
- confirmed source logout removing only source-owned auth;
- source-read failure preserving the previous projection and failing closed;
- source bytes, mode, and timestamps remaining unchanged across projection.
