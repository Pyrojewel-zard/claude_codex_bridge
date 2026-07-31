# Decision 002: Owned Binding Retirement

Date: 2026-07-22

Status: accepted

## Context

CCB writes `.ccb-workspace.json` at the root of managed Git worktrees. Because
the file is intentionally not committed, plain `git status --porcelain`
reported every otherwise-clean workspace as dirty. Removing or renaming a
fully merged agent therefore blocked startup. Ignoring all untracked files
would fix the symptom by removing the only guard protecting real uncommitted
user artifacts from retirement.

## Decision

- Parse `git status --porcelain=v1 -z --untracked-files=all` so filenames,
  including embedded newlines, remain unambiguous.
- Exclude only the exact root `?? .ccb-workspace.json` record.
- Apply that exemption only when the marker is a regular non-symlink JSON
  record with schema version 2, `record_type=workspace_binding`,
  `workspace_mode=git-worktree`, and project, workspace, and branch identity
  matching the current workspace plan.
- Do not require exact `agent_name` equality for a shared `workspace_group`,
  but require it to be present.
- Keep any other status record dirty. Malformed, foreign, wrong-branch,
  symlinked, tracked, or modified markers do not receive the exemption.
- Before retirement, validate that the marker is still the exact untracked
  owned file, unlink it, run the dirty check again, and call non-force
  `git worktree remove`.
- Refuse recursive fallback deletion of an existing unregistered workspace
  path.
- Keep `git merge-base --is-ancestor <branch> HEAD` and `git branch -d` as the
  branch deletion boundary. Squash/rebase or patch equivalence is insufficient
  for automatic deletion.

## Consequences

A clean, actually merged, marker-only managed worktree can retire during
startup, including removal of its persisted agent state. Real user artifacts
continue to block. A file created between inspection and deletion is caught by
the second status check or Git's own non-force removal, so retirement fails
closed instead of forcing data loss.
