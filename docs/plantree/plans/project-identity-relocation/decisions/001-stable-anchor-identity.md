# Stable Anchor Identity

Date: 2026-07-24

## Context

CCB currently hashes the normalized absolute project root to produce
`project_id`. Moving or renaming a directory therefore changes identity while
copied lifecycle, lease, namespace, agent runtime, and provider session records
still contain the old identity and paths.

## Decision

Persist a stable project ID and project slug in
`.ccb/project.identity.json`.

- `project_id` and `project_slug` remain stable across root relocation.
- `bound_root` and `binding_epoch` record the latest locator and relocation
  generation; they do not define identity.
- Existing projects preserve the current path-derived ID when pre-identity
  anchor content proves they predate the identity record. They adopt a
  unanimous recorded legacy ID when the old root is gone and runtime authority
  is inactive.
- New empty anchors receive a random 256-bit ID.
- Conflicting or unproven foreign legacy bindings fail closed.
- A copied anchor whose prior bound root still exists must not silently take
  over live foreign runtime authority.
- Absolute paths remain allowed as current runtime observations, but stale
  inactive lifecycle and lease authority is rebuilt for the current anchor.

## Consequences

- Directory moves and renames no longer change project identity or stable
  namespace/workspace slug.
- `ccb -n` must preserve the identity record.
- Startup must distinguish inactive move residue from live foreign authority.
- Logical path references and an explicit copy/fork workflow remain separate
  follow-up work.
