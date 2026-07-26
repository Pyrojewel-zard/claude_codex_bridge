# Unify The Session Command As Reconnect

Date: 2026-07-20
Status: Accepted and implemented

## Context

The first implementation used the project name `codex-reconnect` but exposed
`$continuity on/off` inside the managed Codex CLI. The two terms described the
same narrow feature and created unnecessary naming and discovery overhead.

## Decision

Use `$reconnect on` and `$reconnect off` as the only current-session control
commands. Rename the projected standalone skill to `reconnect`, and align
user-facing messages, audit events, control output, tests, and active docs.

Do not retain `$continuity on/off` as a compatibility alias before the first
packaged release.

## Consequences

- Project, executable, skill, and session command now share one term.
- Exact interception remains deterministic and scoped to one managed thread.
- Recovery policy, network gates, model pinning, and circuit-breaker behavior
  do not change.
