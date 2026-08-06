# CCB Automatic Installation And Activation

Date: 2026-08-05
Status: Accepted and implemented

## Context

CCB already vendors `codex-reconnect`, installs its command entrypoint, and
projects the `reconnect` control skill into managed Codex homes. Recovery still
requires a user to run `$reconnect on` after each managed Codex launch. This is
easy to miss precisely when a lower-capability or capacity-constrained model
needs continuation support.

Activation cannot happen before Codex creates or resumes a concrete thread.
The watcher requires the exact Codex thread, rollout file, managed home, tmux
socket, pane id, and pane pid; guessing any of them would weaken the existing
fail-closed boundary.

## Decision

- Every CCB installation includes the bundled `codex-reconnect` command and
  its managed Codex control skill. No separate standalone installation is a
  prerequisite for CCB use.
- The CCB Codex bridge invokes the bundled command with `on` only after its
  authoritative managed session file contains a concrete `codex_session_id`.
- Automatic activation uses the agent provider runtime's `reconnect/` state
  directory and the existing `CCB_SESSION_FILE` binding. It does not wrap the
  native `codex` command, inject an activation prompt, or infer pane identity.
- A bridge records one successful automatic activation per Codex thread. It
  may retry a failed startup with bounded backoff, but it must not re-enable a
  thread after a successful activation. Consequently, `$reconnect off` and a
  recovery circuit opening remain authoritative for that live thread.
- A restart may supersede a prior watcher only for the same thread, tmux
  socket, and pane id when the pane pid proves a new managed generation.
  Different pane or socket identity remains a fail-closed conflict.
- Bridge shutdown requests best-effort watcher disablement. A watcher receiving
  `SIGTERM` or `SIGINT` atomically marks only its current instance `off`; this
  covers normal project cleanup even when the bridge cannot run its finalizer.
- Standalone Codex sessions remain opt-in through `$reconnect on`; automatic
  activation is CCB integration policy, not a new standalone default.
- Reconnect startup failure is visible in bridge diagnostics but does not
  prevent the managed Codex session from operating.

## Acceptance

- A CCB install exposes the bundled command without a prior standalone install.
- A fresh managed Codex session reaches `armed` without user activation.
- Repeated binding polls do not create duplicate watchers.
- `$reconnect off` remains off for the rest of the live bridge/thread.
- A failed activation retries at a bounded rate and never blocks Codex.
- Managed shutdown disables the current owned watcher, with no live watcher
  process left after project cleanup.

## Consequences

CCB-managed Codex receives reconnect protection by default. The bridge becomes
the activation owner but not the recovery engine: all classification, network
gating, input fencing, circuit breaking, and audit behavior remain inside the
vendored standalone implementation.
