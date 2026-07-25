# Workspace Sharing Plan

Date: 2026-06-04

## Purpose

Add a small, explicit way for users to share or redirect agent workspaces while
preserving the current default behavior. The feature must avoid automatic Git
initialization, worktree repair, branch switching, code copying, or lifecycle
actions that the user did not request.

## File Map

- [roadmap.md](roadmap.md): current implementation state and remaining gates.
- [decisions/001-explicit-path-and-group.md](decisions/001-explicit-path-and-group.md):
  decision record for `workspace_path` and `workspace_group`.
- [decisions/002-owned-binding-retirement.md](decisions/002-owned-binding-retirement.md):
  narrow dirty-state exemption and non-force retirement for owned worktree
  bindings.

## Scope

In scope:

- `workspace_path` as an exact external workspace path for an agent.
- `workspace_group` as a CCB-managed internal shared worktree.
- Multiple agents sharing the same cwd by explicit configuration.
- Preserving agent-scoped provider homes, sessions, memory, runtime state, and
  queues even when cwd is shared.
- Safely retiring removed or renamed managed worktrees without treating CCB's
  own validated binding as user work.

Out of scope:

- Automatically running `git init` or creating an initial commit.
- Repairing arbitrary broken worktrees.
- Copying untracked or modified files into another workspace.
- Changing default per-agent worktree paths or branches.
