# Workspace Sharing Roadmap

Date: 2026-06-04

## Done

- Decided not to implement automatic Git initialization or broad worktree repair
  as part of this slice.
- Defined `workspace_path` as external linked workspace behavior: CCB validates
  the path but does not create, remove, prune, copy, or switch branches there.
- Defined `workspace_group` as internal managed shared worktree behavior:
  `.ccb/workspaces/groups/<group>` on branch `ccb/group/<group>`.
- Fixed managed-worktree retirement so only the exact untracked
  `.ccb-workspace.json` with matching schema-v2 project/workspace/branch
  and agent-or-group authority is excluded from dirty status. All other tracked
  or untracked entries still block, unusual filenames are parsed through NUL-delimited Git
  porcelain, the marker is revalidated before unlink, and the final worktree
  removal is non-force with a second dirty check.
- Added real Git regressions for marker-only retirement, other untracked files,
  tracked modifications, malformed/foreign/symlink bindings, unmerged branches,
  tracked bindings, and a late user-file race.
- 2026-07-22 verification: `131` workspace/start/reset/workgroup tests passed,
  and the final cross-feature affected suite passed `418` tests. The real
  start-service test now writes the same untracked binding as production before
  retiring a merged removed agent, while a companion test proves a user
  untracked artifact is preserved and reported as a blocker.

## In Progress

- Implement config/model/planner/materializer/validator/reconcile support for
  external workspace paths and internal workspace groups.
- Complete the remaining config parsing, external validation, group reuse, and
  binding compatibility gates.

## Next

1. Complete the remaining workspace-sharing implementation slice.
2. Run broader start/reconcile/runtime tests whenever workspace identity changes.
3. Keep the public config contract aligned with verified retirement behavior.

## Deferred

- Owner-based workspace binding schema migration.
- Shared-workspace UI affordances in the sidebar.
- Automatic file overlay/sync between project root and worktree.
- Interactive worktree conflict resolution.
