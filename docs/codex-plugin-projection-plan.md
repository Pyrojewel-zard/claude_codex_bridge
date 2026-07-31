# Codex Plugin Projection Plan

## 1. Purpose

This plan defines how `ccb` must project Codex plugin assets into a managed
`CODEX_HOME`.

It closes the architecture gap behind issue `#196`: the managed home inherited
plugin-related config intent, but did not consistently inherit the plugin
catalog and installed plugin assets required to satisfy that intent.

This document complements the authority contract in
[docs/codex-session-isolation-contract.md](/home/bfly/yunwei/ccb_source/docs/codex-session-isolation-contract.md).

It also covers the current Codex plugin layout added by PR257. That layout has
both immutable startup authority and provider-writable state; those classes
must not share the same projection mechanism.

## 2. Problem Statement

The broken state was:

- managed `config.toml` could still declare or preserve plugin-enabled behavior
- managed `commands/` and `skills/` could still be projected
- but managed `CODEX_HOME` could start without the plugin marketplace and plugin
  bundle tree that Codex expects under `.tmp/plugins`

That produced an incoherent managed home:

- plugin intent was present
- plugin assets were absent
- startup behavior depended on whether Codex later repopulated cache-like state
  on its own

That is not a runtime cache miss. It is a startup authority mismatch.

## 3. Architectural Decision

Codex plugin projection is startup-owned managed-home authority.

`ccb` must treat these classes separately:

- inheritable startup authority
  - `config.toml`
  - `auth.json`
  - `skills/`
  - `commands/`
  - plugin bundle authority under `.tmp/plugins/`
  - plugin freshness marker under `.tmp/plugins.sha` when present
- per-agent writable plugin state
  - `.tmp/marketplaces/`
  - `plugins/cache/`
- non-authoritative runtime residue
  - session logs
  - history and request transcripts
  - provider runtime logs
  - any future provider-generated ephemeral caches outside the plugin bundle
    authority described above

CCB-owned control skills are mandatory startup authority, not optional user
inheritance. The owned set is `ask`, `ccb-clear`, and `reconnect`. Startup
projects those entries from the packaged CCB assets even when
`inherit_skills=false`, a role disables inherited assets, or the optional
source skill tree contains a broken entry. If Codex has already created an
unmarked `skills/` directory for system or user assets, startup repairs only
those named CCB-owned entries and preserves every unrelated entry.

Optional source-home skills use the common per-entry projection contract rather
than a whole-root copy. This keeps the managed `skills/` directory local while
valid ordinary skills and the nested `.system` collection follow their source
through independent symlink-first, marker-owned entries.

Rejected designs:

- copy all of `~/.codex`
- wait for Codex to lazily heal missing plugin assets after launch
- treat a previously populated managed `.tmp/plugins` tree as sufficient proof
  even when the source plugin bundle changed

## 4. Scope Of Projection

For managed Codex homes, `ccb` must project the source-home plugin authority
root:

- `<source-codex-home>/.tmp/plugins/`
- `<source-codex-home>/.tmp/plugins.sha` when present

That tree is projected as a unit because the marketplace listing, installed
plugin metadata, plugin manifests, bundled commands, bundled skills, bundled
agents, and assets are all internally path-coupled under the same relative
layout.

`ccb` must not attempt to model only a subset such as:

- only `marketplace.json`
- only installed plugin manifests
- only plugin `commands/` or `skills/`

Those subsets recreate the same incoherent-home failure in a different shape.

The current-layout paths are not part of that immutable bundle:

- `<source-codex-home>/.tmp/marketplaces/` is an optional seed source for the
  managed home's local `.tmp/marketplaces/`.
- `<source-codex-home>/plugins/cache/` is an optional seed source for the
  managed home's local `plugins/cache/`.

Each managed agent receives an independent writable copy. These paths must not
be symlinked to the source home or to another agent, because Codex may write to
them while running.

## 5. Refresh Rules

Startup refresh must be deterministic:

1. If the source plugin tree is absent, remove the managed immutable plugin
   tree and freshness marker only when a matching CCB projection marker proves
   ownership. Preserve unmarked state.
2. If the source plugin tree is present and the source freshness marker differs
   from the managed one, replace the managed projection.
3. If no source freshness marker exists, `ccb` may fall back to a tree-signature
   comparison, but it must not silently assume the target is current.
4. Refresh must replace the plugin tree as a unit so removed plugins do not
   remain as stale managed residue.

The fast path should use `.tmp/plugins.sha` when available because the plugin
bundle tree can be large and should not be fully recopied on every launch.

Writable seed refresh follows different rules:

1. A missing source seed never deletes an existing managed local tree.
2. An absent target is populated through a staged local copy and receives a
   CCB projection marker containing the source fingerprint.
3. An unmarked target, or a target with a foreign/invalid marker, is preserved
   without modification.
4. A PR257-era marker-owned source symlink is migrated to a local copy.
5. If the source fingerprint is unchanged, the managed local tree is retained
   so provider runtime writes survive ordinary restarts.
6. If the source fingerprint changes, only a matching CCB-owned seed may be
   atomically refreshed. Marker-write or replacement failure restores the
   previous tree.
7. Disabling inherited assets removes only matching CCB-owned projections.

Binding classification precedes this refresh. An already live,
identity-proven Codex binding performs no plugin projection because no Codex
process is launched. A launch or relaunch performs exactly one managed-home
refresh; provider-profile resolution must not project the home and then repeat
the same projection in `prepare_provider_workspace`.

## 6. Ownership Boundary

The managed plugin projection belongs to the managed Codex home, not to:

- project runtime logs
- session binding state
- completion detection
- foreground pane ownership

Therefore this fix belongs in the Codex managed-home materialization layer,
not in:

- post-launch recovery hooks
- completion polling
- ad hoc cold-start repair code

Projection ownership is proven by a valid `ccb_projected_asset` marker with the
expected Codex plugin label. File equality, path similarity, or residence under
a managed home is not sufficient permission to replace a target.

## 7. Tests

The regression surface must include:

- provider-profile materialization copies plugin authority into a fresh managed
  home
- explicit API-route managed homes still receive plugin projection
- managed home refresh updates projected plugin assets when the source plugin
  freshness marker changes
- refresh removes stale managed plugin residue when the source projection is no
  longer present
- current-layout marketplace and cache seeds are local directories rather than
  source/shared symlinks
- two managed agents do not share writable plugin state
- PR257-era marked symlinks migrate to local seed copies
- unmarked targets and missing-source local state are preserved
- source changes refresh only marker-owned seed copies and failed marker update
  restores the previous target
- accepted binding reuse performs zero plugin refreshes, while one managed
  launch performs exactly one refresh
- an unmarked managed-home `skills/` directory receives the current CCB-owned
  `ask`, `ccb-clear`, and `reconnect` entries without replacing unrelated
  system or user skills
- a broken symlink in the optional source skill tree cannot prevent the three
  packaged CCB control skills from being projected
