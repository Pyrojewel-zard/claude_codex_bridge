# Public Project And CLI Name

Date: 2026-07-19
Status: Accepted and implemented

## Context

The tool needs a public name distinct from its in-session control command.
`codex-continue` sounds like a general task-continuation loop, while the actual
scope is deliberately limited to reconnecting after terminal network or model
service-overload failures. `codex-resume` would also be confused with Codex's
built-in `resume` command.

## Decision

Use `codex-reconnect` for the project, executable, Python package, state
directory, runtime identifiers, and PlanTree root. Use `$reconnect on` and
`$reconnect off` as the exact current-session activation UX.

The resulting naming layers are:

- repository/tool directory: `tools/codex-reconnect/`;
- executable: `codex-reconnect`;
- Python package: `codex_reconnect`;
- state directory: `codex-reconnect/` under the platform state root;
- internal environment prefix: `CODEX_RECONNECT_`;
- current-session control commands: `$reconnect on/off`.

## Consequences

- The public name describes the narrow fault-recovery behavior and avoids
  implying autonomous completion of ordinary work.
- Existing design invariants and recovery behavior are unchanged.
- No legacy `codex-continuity` executable alias is retained before the first
  packaged release, so the repository exposes one unambiguous name.
