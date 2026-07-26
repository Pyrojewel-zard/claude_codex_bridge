# Current-Session On/Off Transport

Date: 2026-07-18
Status: Superseded as primary transport by Decision 006

## Context

The required UX is exactly `$reconnect on` and `$reconnect off` inside an
interactive Codex CLI. A skill alone is not alive while the model transport is
disconnected, current lifecycle hooks do not expose terminal network-error
events, and a second independent App Server client would receive recovery-turn
approvals outside the TUI that the user is watching.

Installing the control as a plugin also namespaces the skill in the current
App Server (`$<plugin-name>:reconnect`), which violates the requested exact
command.

## Decision

Launch the TUI through a local transparent bridge:

- TUI side: WebSocket over a short owner-only Unix-domain socket;
- App Server side: the official stdio JSONL transport;
- skill side: runtime standalone skill root projected with
  `skills/extraRoots/set`, yielding exact `$reconnect`;
- control side: intercept only exact `$reconnect on/off` `turn/start` input
  before forwarding it, keyed by that request's `threadId`;
- recovery side: observe structured App Server terminal errors and inject the
  bounded recovery `turn/start` on the same logical connection.

## Consequences

- The activation state is deterministic and does not depend on a model tool
  call, sandbox write, hook, or terminal keystroke.
- Server-initiated approvals for a recovery turn remain on the TUI connection.
- Multiple CLIs are isolated by separate bridge processes, sockets, instance
  ids, and control records.
- Global Codex configuration is unchanged.
- An already-open ordinary CLI cannot be attached safely; it must be reopened
  through `codex-reconnect open`.
- The current transport supports Linux/macOS. Windows needs a separate local
  transport design.
