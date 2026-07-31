# Project Identity And Relocation Roadmap

Date: 2026-07-24

## Done

- Confirmed that path-derived `project_id` changes after a directory move and
  that keeper preserves the stale lifecycle ID into the next startup fence.
- Defined stable identity, stable slug, locator-only root binding, and
  fail-closed live-authority rules.
- Added `.ccb/project.identity.json` with backward-compatible legacy adoption.
- Reconciled inactive foreign lifecycle and lease records before startup.
- Preserved identity through explicit project reset.
- Added rename, cross-root move, stale lifecycle, active-authority, and reset
  regression coverage.
- Updated the startup supervision contract.
- Verified a real stopped-project rename and simulated pre-identity move with the
  external source test wrapper.

## In Progress

- Review and land the P0/P1 working-tree implementation.

## Next

1. Introduce logical path references and separate durable binding intent from
   observed PID, pane, socket, and filesystem paths.
2. Add an explicit `ccb project fork` flow for copied anchors.
3. Add a host-level binding registry keyed by stable project ID.
4. Qualify provider session restoration after relocation across Codex,
   Claude, and supported native pane-backed providers.

## Deferred

- Preserving live PIDs or tmux panes across an active filesystem move.
- Automatically rewriting explicit external `workspace_path` values.
- Treating Git remote, commit, inode, or filesystem path as project identity.
