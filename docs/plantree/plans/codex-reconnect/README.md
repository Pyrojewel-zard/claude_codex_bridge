# Codex Reconnect

Date: 2026-07-26
Status: Tmux primary mode 0.3.3 integrated into CCB; real-fault requalification open
Mode: Execute ready

## Plan State

- [Roadmap](roadmap.md)
- [Implementation status](implementation-status.md)
- [Native Windows support analysis](native-windows-support.md)
- [Decision 001: app-server wait semantics and HTTPS recovery gate](decisions/001-app-server-wait-and-https-recovery-gate.md)
- [Decision 002: current-session on/off transport](decisions/002-current-session-on-off-transport.md)
- [Decision 003: public project and CLI name](decisions/003-project-name-codex-reconnect.md)
- [Decision 004: unify the session command as reconnect](decisions/004-session-command-reconnect.md)
- [Decision 005: standalone repository authority](decisions/005-standalone-repository-authority.md)
- [Decision 006: tmux session watcher and input injection](decisions/006-tmux-session-watcher-and-input-injection.md)

## Purpose

Provide an independent, opt-in supervisor for terminal network disconnects and
selected-model service overload in an interactive Codex CLI already running in
tmux. It must leave the native `codex` executable and all Codex arguments
untouched, bind recovery to the exact thread and pane, and fail closed when
identity or input safety cannot be proved.

The authoritative product repository is
[`SeemSeam/codex-reconnect`](https://github.com/SeemSeam/codex-reconnect), with
the standalone working tree at
`/home/bfly/workspace/agent_develop/codex-reconnect`. CCB also vendors the
same implementation and projects its skill into every managed Codex home;
standalone use does not depend on CCB.

The primary product surface is:

```text
tmux -> native codex [all normal Codex arguments]

$reconnect on
$reconnect off
```

The installed user skill maps those exact invocations to
`codex-reconnect on/off`. `on` outside tmux or a valid CCB-managed tmux binding
is an immediate error and does not start a watcher. The CLI retains `status`
for diagnostics, but it is not part of the skill's user-facing contract.

## Frozen Scope

In scope:

- terminal network failures persisted as Codex session `event_msg:error`
  records or exact-thread/turn SQLite `Turn error` rows;
- selected-model service pressure exposed as `serverOverloaded`;
- matching terminal `task_complete`, network-readiness gating, and one bounded
  literal `continue` submission;
- multiple tmux Codex CLIs, each with an independently bound thread/pane
  watcher;
- Linux, macOS, and WSL2 environments where Codex and tmux run together.

Out of scope:

- normal turn completion or a general long-running goal loop;
- usage quota, billing, authentication, policy/safety, context-window,
  approval, or ordinary task failures;
- automatic model fallback or downgrade;
- replaying the original prompt;
- resurrection after the Codex TUI or bound tmux pane exits;
- native Windows consoles without tmux.

## Invariants

- Activation requires either `TMUX`/`TMUX_PANE` or a validated CCB session
  pointer, plus `CODEX_THREAD_ID`, a resolvable Codex home (`CODEX_HOME` or the
  normal default), a matching owner-controlled rollout JSONL, and a live
  matching pane.
- The watcher starts at the rollout EOF and SQLite log cursor recorded during
  activation. Historical errors and ordinary conversation text cannot trigger
  it.
- Codex internal retry is authoritative; `willRetry=true` never creates a
  duplicate user turn.
- A matching terminal `task_complete` is required before recovery begins.
- Network continuation requires two consecutive successful OpenAI/Codex HTTPS
  probes. Public HTTPS is diagnostic only; ICMP is not a readiness signal.
- All newly persisted session events are drained again before injection. Newer
  user or turn progress cancels recovery.
- The tmux socket, pane id, pane pid, foreground command, and Codex empty-input
  cursor plus dim-placeholder state must still match.
- Input submission follows CCB's tmux path: load an isolated buffer, bracket-
  paste literal `continue`, wait 0.5 seconds, prove the exact staged text and
  cursor, conditionally send Enter, then delete the buffer. The pane pid and
  cursor are fenced before paste and before Enter; the original prompt is
  never replayed.
- Enabling a new Codex thread supersedes older watchers bound to the same tmux
  socket, pane, and pane pid.
- At most one automatic continuation follows an incident. Any error in that
  continuation opens the circuit and turns the watcher off.
- `$reconnect off` affects only the exact current thread/pane binding and wins
  a pending recovery race at the next state or session-event check.

## Runtime Shape

```text
native Codex TUI in a tmux pane
       |                            |
       | writes JSONL + SQLite logs | receives literal continue + Enter
       v                            ^
owner-only background watcher -- tmux socket / exact pane binding
       |
       +-- OpenAI/Codex HTTPS readiness probes
       +-- owner-only state and redacted audit log
```

The watcher does not wrap the `codex` process and does not parse its command
line. The user-level skill is installed at `~/.agents/skills/reconnect` and
points to the installed bundle. Codex 0.144.6 `skills/list` verified that this
scope is discovered even when a CLI uses a different `CODEX_HOME`.

The earlier App Server bridge from Decision 002 remains temporarily available
as `codex-reconnect open` for compatibility and rollback evidence. It is not
the default activation path and the global skill does not use it.

## Recovery State Machine

```text
OFF
  -> ARMING                    exact $reconnect on in a valid tmux Codex

ARMING
  -> ARMED                     empty-input cursor state observed
  -> ERROR/OFF                 session or pane proof fails

ARMED + active/internal retry  -> observe only
ARMED + normal completion      -> observe only
ARMED + out-of-scope failure   -> observe only
ARMED + terminal network error -> WAIT_NETWORK after task_complete
ARMED + serverOverloaded       -> BACKOFF -> WAIT_NETWORK

WAIT_NETWORK
  -> WAIT_NETWORK              primary HTTPS unstable/unreachable
  -> REVALIDATE                two consecutive primary successes
  -> ARMED                     newer user/turn progress exists
  -> OFF                       $reconnect off

REVALIDATE
  -> RECOVERY_SENT             identity and empty input still match
  -> ARMED                     input state no longer safe
  -> ERROR/OFF                 pane/session identity contradiction

RECOVERY_SENT
  -> ARMED                     continuation completes without error
  -> CIRCUIT_OPEN/OFF          continuation encounters any error
```

## Qualification Boundary

The 51-test deterministic suite, repeated JSONL/SQLite/input-race regression,
user-level skill
discovery, non-tmux failure, atomic real-tmux input smoke, and an installed
end-to-end tmux watcher smoke with real OpenAI HTTPS readiness probes pass. A
real 0.3.1 disconnect exposed a rotating-placeholder false negative. A real
0.3.2 recovery then proved that immediate literal input plus Enter can leave
`continue` unsubmitted as a multiline draft. Version 0.3.3 adopts the CCB
buffer-paste/delay/Enter path and has produced a real Codex `user_message` and
new `task_started` turn.

Production qualification still requires an inspectable real Codex network
interruption and an organically occurring `serverOverloaded` event. Tests must
not intentionally create real provider pressure.

CCB source integration additionally passes managed-home skill projection,
source-test command-shim, CCB session-pointer binding, symlinked managed SQLite
validation, terminal-error retention, and real isolated managed-Codex
`on -> armed -> off` qualification.

Version 0.3.3 is published on `origin/main` as commit
[`1134122`](https://github.com/SeemSeam/codex-reconnect/commit/113412276abdea3d42d183477798307000fac307).
