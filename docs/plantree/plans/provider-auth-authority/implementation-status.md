# Provider Authentication Authority Implementation Status

Date: 2026-08-04

## Current Phase

The first production slice is implemented in the worktree: manual Agent
restart now forces the normal Provider preparation and launch pipeline in the
existing pane, and Codex, Claude, and Gemini resume use Agent-private
credential/route authority fences.

## Last Landed

- Worktree implementation on 2026-08-04; commit pending.
- `ccb restart <agent>` no longer executes persisted `session.start_cmd`.
- Codex API/login authority changes rotate the active `sessions/` namespace
  and remove stale resume binding while leaving credentials untouched.
- Claude/Gemini API, route, or login authority changes suppress native
  `--continue`/`--resume latest` without deleting private auth or history.

## Active TODO

1. Run inspectable isolated source-runtime validation from
   `/home/bfly/yunwei/test_ccb2`.
2. Add mandatory new-writer termination when a post-spawn commit fails.
3. Continue the capability resolver and sanitized `provider.json` authority
  record defined by the landing map.

## Blocked By

No blocker for the Codex restart/session fence. Broader rotating-OAuth
enforcement remains gated by the capability and private-login decisions in the
roadmap.

## Last Verified

- `python3 -m compileall -q lib/ccbd lib/provider_backends/codex`
- 46 focused pytest cases passed for restart preparation, Codex authority,
  resume/session namespace, and runtime session files.
- Full source pytest run: `6123 passed, 2 skipped, 5 failed`; all five failures
  are unrelated Role workflow smoke cases blocked by the missing `agent-roles`
  executable or its residue check.
