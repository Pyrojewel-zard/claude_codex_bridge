# Decision 008: Copilot Entry-Owned Plugin Seed

Date: 2026-07-21
Status: Implemented and verified by R11-C

## Problem

GitHub Copilot CLI treats `COPILOT_HOME` as one mixed configuration and state
root. Its automatically managed `config.json` contains `installedPlugins`
beside authentication/application state, while permissions, sessions,
installed plugin files, plugin data, and marketplace cache have distinct
lifecycle and ownership. Copying the whole source home or whole config would
cross credential, permission, session, cache, and writable-data boundaries.

Current GitHub
[configuration-directory documentation](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
[plugin documentation](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference),
and the offline Copilot CLI `1.0.61` fixture agree on the required split:

- installed plugin metadata is `config.json.installedPlugins`;
- installed plugin files live below `installed-plugins/`;
- marketplace cache is outside `COPILOT_HOME` and separately controlled by
  `COPILOT_CACHE_HOME`;
- persistent plugin runtime data lives below `plugin-data/`;
- permissions and sessions remain separate provider-owned state.

## Projected Authority

R11-C may read only the source `installedPlugins` field for projection and may
copy only its corresponding installed plugin directory. Each accepted entry
must have:

- non-empty path-safe `name` and string `marketplace`;
- string `installed_at`, boolean `enabled`, and optional string `version`;
- a unique `(marketplace, name)` identity;
- a source `cache_path` resolving exactly inside the source
  `installed-plugins/` root;
- a marketplace path shaped as `<marketplace>/<name>`, or one direct-install
  path shaped as `_direct/<source-id>`;
- a valid plugin manifest and no symlink inside the copied tree.

The managed entry allowlist is `name`, `marketplace`, optional `version`,
`installed_at`, `enabled`, and a `cache_path` rebased to the agent-local copy.
The source/update descriptor and every unknown field are omitted. Malformed,
duplicate, escaping, missing-tree, missing-manifest, or symlink-bearing source
data fails closed and preserves the previous managed state.

## Entry Ownership

One local schema-v1 marker records the exact managed metadata for each
`(marketplace, name)` identity and its relative installed-tree path. Each
installed tree also has its own valid projected-asset marker and stable
identity label.

- A new source entry is appended only when neither target metadata nor target
  tree conflicts.
- A previously managed entry is refreshed only while target metadata still
  equals the exact value in the marker, its tree marker is valid, and its tree
  content fingerprint still equals the last installed content.
- Local tree-content divergence is user takeover even when metadata is
  unchanged: preserve the entry and tree, remove CCB ownership markers, and
  stop managing that identity.
- Target metadata divergence is user takeover: preserve the entry and tree,
  remove CCB ownership markers, and stop managing that identity.
- Target deletion of previously managed metadata is an explicit local opt-out;
  remove only its still marker-owned installed tree.
- A source entry removed while target metadata is unchanged removes only the
  exact managed metadata and marker-owned tree.
- An unmarked/foreign target entry or tree is preserved and the source entry
  is omitted. A malformed or foreign aggregate marker blocks all mutation.
- Missing or malformed source state preserves the last good projection.
  Explicit inheritance opt-out or hard role policy removes only unchanged,
  marker-owned projected entries and trees.

Config, aggregate marker, per-entry markers, and installed trees commit as one
rollback-safe transaction. Copilot's official leading `//` config header is
preserved; unsupported inline JSONC or malformed target state fails closed.

## Isolation Boundary

Managed interactive and headless Copilot launches use the same agent-local
`COPILOT_HOME` plus an agent-local `COPILOT_CACHE_HOME`. R11-C never copies,
links, merges, deletes, or claims source/target authentication fields,
`settings.json`, `permissions-config.json`, session stores, command history,
`plugin-data/`, marketplace cache, MCP secrets/OAuth data, or any other home
entry. Installed trees are normal local directories, never symlinks to source
authority.

## Evidence Gate

Required tests cover marketplace and direct entries, two-agent isolation,
metadata/path rebasing, source update/removal, explicit opt-out, missing and
malformed source, target metadata divergence/deletion, unmarked and foreign
tree/marker conflicts, malformed target/header, symlink/escape rejection,
transaction rollback, source immutability, storage classification, launcher
cache isolation, and hard role policy.

External acceptance uses the existing offline Copilot CLI `1.0.61` binary and
a synthetic no-auth plugin fixture. `copilot plugin list` must discover the
agent-local projected plugin without login, both source and local-divergence
hashes must remain stable, and candidate cleanup must leave the project
unmounted. A missing current global executable cannot be hidden by another
provider or stronger model; real authenticated prompt qualification remains
unclaimed when no authorized Copilot login is available.
