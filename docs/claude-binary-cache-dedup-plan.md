# Claude Binary Cache Dedup Plan

## 1. Purpose

This plan defines how CCB should stop storing a full Claude Code binary version
cache inside every managed Claude agent home.

It complements the Claude isolation authority in
[docs/claude-session-isolation-contract.md](/home/bfly/yunwei/ccb_source/docs/claude-session-isolation-contract.md).
That contract remains authoritative for conversation, auth, config, and
session-state isolation. This plan narrows only the provider binary/cache
placement problem.

This is a Claude-specific child plan of
[docs/ccb-provider-state-storage-boundary-plan.md](/home/bfly/yunwei/ccb_source/docs/ccb-provider-state-storage-boundary-plan.md).
The general storage boundary plan is authoritative for cross-provider storage
classes, `.ccb/provider-profiles` semantics, shared cache placement, and
diagnostics/cleanup sequencing.

Superseding decision, 2026-07-23: project-scoped Claude binary sharing is
retired. Managed panes use the user-installed Claude executable, export
`DISABLE_AUTOUPDATER=1`, and do not copy/hash/link Claude binaries under
`~/.cache/ccb/projects/` or `.ccb/shared-cache/`. The former shared-cache
implementation remains relevant only as a guarded upgrade-cleanup format.

## 2. Current Problem

Managed Claude launches set `HOME` to the agent-scoped provider-state home:

```text
.ccb/agents/<agent>/provider-state/claude/home/
```

This is necessary because Claude Code does not expose a stable dedicated
`CLAUDE_HOME` flag and reads important runtime state from `HOME`.

However, Claude Code also stores its user-level executable version cache under
that same home:

```text
<HOME>/.local/share/claude/versions/<version>
<HOME>/.local/bin/claude -> ../share/claude/versions/<current-version>
```

In a CCB managed home, that becomes:

```text
.ccb/agents/<agent>/provider-state/claude/home/.local/share/claude/versions/
```

Observed local example:

```text
2.1.132  ~249 MB
2.1.133  ~230 MB
2.1.137  ~231 MB
```

Only `2.1.137` is the current symlink target, but the older binaries remain in
the agent provider-state tree. This turns provider-state into a durable binary
cache and can make one Claude agent consume hundreds of MB.

This is a side effect of CCB's private-`HOME` isolation strategy. CCB is not
intentionally treating Claude binaries as project authority. Because Claude Code
uses `$HOME/.local/...` for its self-managed executable cache, changing `HOME`
for session isolation also changes the binary cache location.

That coupling is undesirable:

- session/config/auth isolation is project and agent scoped
- executable binaries and self-update caches are tool/runtime artifacts
- tool binaries should normally be user-level, system-level, or shared CCB cache
  resources, not per-project and per-agent durable state

## 3. Design Boundary

CCB must keep these categories separate:

- **Agent-isolated authority**
  - `.claude/projects/`
  - `.claude/session-env/`
  - `.claude/settings.json`
  - `.claude/skills/`, `.claude/commands/`, `.claude/CLAUDE.md`
  - `.claude.json`
- **Agent-local secret**
  - `.claude/.credentials.json`
  - `.config/claude-code/auth.json`
- **Shared or cleanable provider binary/cache**
  - `.local/share/claude/versions/`
  - `.local/bin/claude`
  - other Claude self-update binaries that do not define conversation identity

The version cache is not Claude conversation authority. It should not be copied
into diagnostics as session evidence, and it should not be duplicated per
agent unless the user explicitly requests fully self-contained managed homes.

The intended boundary is:

- CCB may set private `HOME` to isolate Claude conversation state.
- CCB should not let that private `HOME` make provider binaries project-owned.
- CCB disables managed-pane self-update and uses the user-installed executable.
- If Claude still writes `$HOME/.local/...`, CCB reports the drift and permits
  conservative stopped-project cleanup; it does not redirect the binary into a
  project cache.

## 4. Target State

Default managed Claude launches still use an agent-scoped private `HOME`, but
the executable is owned by the user's Provider installation:

```text
~/.local/bin/claude
~/.local/share/claude/versions/

.ccb/agents/<agent>/provider-state/claude/home/
  .claude/...
```

The managed agent home should contain no CCB-created `.local/bin/claude` or
`.local/share/claude/versions` projection. Provider version discovery and
mutation belong to explicit `ccb update`; managed Claude startup disables
Claude's native self-updater.

During one-way migration, startup may remove only symlinks whose target is
exactly a known CCB legacy cache root. It must preserve cache payload for
explicit stopped-project cleanup and must not remove foreign/user symlinks.

## 5. Implementation Phases

### Phase 0 - Audit And Classification

Add a read-only storage inspection path before deleting anything.

Required behavior:

- report `provider-state/claude/home/.local/share/claude/versions/*`
- identify the current symlink target from `.local/bin/claude`
- classify non-target versions as `cleanable_binary_cache`
- classify the target version as `active_binary_cache`
- include parent-plan metadata such as `reachable_from_current_symlink`,
  `is_active_version`, and `reclaimable`
- surface projected auth/config/session files separately as authority
  or secret according to the parent storage-boundary plan

Suggested command surface:

```text
ccb doctor storage
```

Exit criteria:

- users can see how much disk is binary cache vs. session authority
- no file deletion occurs in this phase

### Phase 1 - Safe Prune Policy

Add conservative pruning for per-agent Claude version caches.

Policy:

- never delete the current `.local/bin/claude` symlink target
- delete older versions only when they are regular files under the managed
  Claude home
- skip pruning if the symlink target cannot be resolved safely
- report and skip if the `versions/` directory itself is a symlink
- cleanup must follow the parent storage-boundary plan's lifecycle guard: do
  not prune while the backend is active or pending `ask` jobs exist, and hold
  the project startup/lifecycle lock while checking and pruning

Suggested command surface:

```text
ccb cleanup
```

Exit criteria:

- current Claude still launches after cleanup
- repeated cleanup is idempotent
- corrupted or unexpected symlink layouts are reported, not force-deleted

### Phase 2 - User-Owned Executable

The earlier project-shared binary-cache approach is retired.

Approach:

1. Use the Provider executable already resolved from the user's startup
   environment or explicit `CLAUDE_START_CMD`.
2. Export `DISABLE_AUTOUPDATER=1` and the common no-update-notifier override
   only inside CCB-managed panes.
3. Do not create a CCB Claude binary cache.
4. Keep managed `HOME` scoped to the agent for `.claude/*` isolation.

Exit criteria:

- new projects create no CCB Claude binary cache
- Claude conversations remain isolated by managed home
- provider version changes occur only through explicit `ccb update`

### Phase 3 - Startup Guard

Prevent future binary-cache drift back into provider-state and migrate legacy
CCB projections.

Required behavior:

- on managed Claude startup, detect CCB-owned legacy `versions` symlinks
- detach only links targeting the retired external or `.ccb/shared-cache`
  Claude roots
- remove a managed `.local/bin/claude` link only when it resolves inside that
  same retired cache
- emit a diagnostics notice when Claude writes binary cache into provider-state
  again
- never let this notice affect ask/job completion semantics

Exit criteria:

- normal restarts do not steadily grow `.ccb/agents/<agent>/provider-state`
  with old Claude binaries

## 6. Risk Analysis

### Claude CLI May Require HOME-Local Binaries

If a future Claude release ignores `DISABLE_AUTOUPDATER` and writes
`$HOME/.local/share/claude/versions` again, retain drift diagnostics and
stopped-project pruning. Do not reintroduce project-scoped binary copying
without a new measured decision.

### Symlink Safety

Cleanup must never follow arbitrary symlinks outside the expected managed home
or shared cache. Only delete normalized paths that are direct children of the
managed `versions/` directory.

### macOS Login Compatibility

macOS may materialize auth from Keychain into the managed home. Binary cache
dedup must not touch `.claude/.credentials.json` or
`.config/claude-code/auth.json`.

### Diagnostics Semantics

Binary caches are not diagnostic evidence by default. Diagnostic bundles should
record their presence and size, but should not export hundreds of MB of version
binaries.

## 7. Tests

Required unit tests:

- detects current Claude version symlink target
- classifies current vs. old version files
- prune keeps only versions currently referenced by managed Claude homes
- prune refuses unsafe symlink targets
- managed launch still writes `HOME=<managed-home>`
- managed launch exports `DISABLE_AUTOUPDATER=1`
- new startup creates no CCB project binary cache
- legacy CCB links are detached while foreign links are preserved
- storage classification marks `.claude/.credentials.json` and
  `.config/claude-code/auth.json` as secret, not cache or projected config

Required integration tests:

- Linux managed Claude startup after prune
- macOS managed Claude startup after prune
- WSL managed Claude startup after prune
- two Claude agents use the user-installed executable but keep separate session
  roots

## 8. Recommended Migration Slice

1. Disable Claude self-update in managed panes.
2. Stop creating the project cache.
3. Detach only exact CCB-owned legacy links during provider preparation.
4. Remove the current stopped project's cache through `ccb cleanup`.
5. Require `--legacy-provider-caches` plus manifest/project-id validation for
   cross-project orphan cleanup.
6. Verify fresh and migrated launches on Linux, macOS, and WSL.

## 9. Current Implementation Status

Implemented:

- Parent storage classification reports Claude
  `.local/share/claude/versions/*` as `REBUILDABLE_CACHE`.
- The current `.local/bin/claude` symlink is surfaced as the active entry, and
  files inside the current version subtree are marked with
  `is_active_version` and `reachable_from_current_symlink`.
- Claude auth files classify as `SECRET`.
- Claude `.claude.json` classifies as session/trust authority.
- Claude no longer accepts provider-profile `runtime_home` as a supported
  launch boundary; managed launches keep `HOME` under
  `.ccb/agents/<agent>/provider-state/claude/home`.
- `ccb cleanup` prunes old per-agent Claude version caches while keeping the
  current symlink target plus one rollback version.
- `ccb cleanup` reports symlinked `versions/` directories instead of silently
  ignoring them.
- Managed Claude startup preparation records a de-duplicated
  `claude_binary_cache_drift` agent event when a per-agent `versions/` cache
  appears, so diagnostics can explain why provider-state is growing again.
- The former route to
  `~/.cache/ccb/projects/<project-id-prefix>/provider-cache/claude/versions`
  has been removed. New startup performs no binary copy, hash, shared-cache
  creation, or active-version selection.
- Managed Claude startup exports `DISABLE_AUTOUPDATER=1`.
- Startup detaches exact CCB-owned legacy external/shared-cache links and emits
  `claude_binary_cache_detached`; foreign symlinks are preserved.
- `ccb cleanup` removes the stopped current project's retired cache after
  detaching its recognized links.
- `ccb cleanup --legacy-provider-caches` removes only manifest-valid cache
  buckets whose recomputed project identity matches and whose recorded project
  root no longer exists.
- `ccb cleanup` removes rebuildable Claude cache residue from managed homes:
  `.cache/claude`, `.npm/_logs`, `.claude/cache`, `.claude/telemetry`,
  `.claude/paste-cache`, and `.claude/plugins/marketplaces`.

Not implemented yet:

- Cross-platform real-provider qualification of the retired-cache migration on
  Linux, macOS, and WSL.

The next Claude-specific step is real launch validation confirming managed
Claude starts from the user installation, does not recreate the project cache,
and preserves isolated conversation/auth state.
