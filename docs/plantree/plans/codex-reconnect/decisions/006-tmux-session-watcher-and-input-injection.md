# Tmux Session Watcher And Input Injection

Date: 2026-07-20
Status: Implemented; real-fault qualification open

## Context

The transparent App Server bridge implemented by Decision 002 provides the
strongest structured recovery semantics, but requires every interactive Codex
CLI to be launched through `codex-reconnect open`. That breaks the required
experience: users must be able to start the original `codex` command with any
Codex arguments and enable recovery from an already-open CLI.

Verified Codex tool environments inside tmux expose `CODEX_THREAD_ID`,
`CODEX_HOME`, `TMUX`, and `TMUX_PANE`. Lifecycle events are persisted in the
matching rollout JSONL. Depending on the Codex failure path, terminal errors
are persisted either as JSONL `event_msg:error` or only as an exact-thread
`codex_core::session::turn: Turn error` row in `logs_2.sqlite`. Tmux can write
literal input to an exact pane. These sources are sufficient for an
attach-style watcher without wrapping or re-parsing the `codex` command line.

## Decision

Make tmux attachment the primary product mode:

- install `reconnect` as a user-discoverable skill;
- `$reconnect on` invokes `codex-reconnect on` in the current Codex tool
  environment;
- `on` fails immediately unless `TMUX`, `TMUX_PANE`, `CODEX_THREAD_ID`, and a
  matching Codex rollout file are available;
- start one owner-only background watcher bound to the exact Codex home,
  thread id, tmux socket, pane id, and pane pid;
- begin at the rollout EOF and current SQLite log cursor; accept only later
  JSONL terminal errors or exact-thread/turn SQLite `Turn error` rows, never
  ordinary prompt, response, or captured pane text;
- require the matching `task_complete`, two consecutive primary HTTPS
  successes, unchanged pane identity, Codex empty-input cursor and styled
  placeholder proof, and no newer submitted progress before loading an
  isolated tmux buffer, bracket-pasting literal `continue`, waiting 0.5
  seconds, proving the staged text/cursor, conditionally sending Enter, and
  deleting the buffer;
- supersede older watchers when a new thread is armed in the same socket, pane,
  and pane pid;
- `$reconnect off` stops only the watcher for the current thread and pane;
- retain one automatic continuation per incident and open the circuit if that
  continuation also terminates with an eligible error.

The original `codex` executable, arguments, subcommands, stdout, stderr, and
exit code are untouched. Native Windows without tmux is outside this mode;
WSL2 with tmux is eligible.

Decision 002 is superseded as the primary product transport. Its bridge
implementation remains temporarily as rollback evidence until tmux acceptance
is complete; it is not the default activation path.

## Implementation Evidence

- Standalone version 0.3.3 implements `on/off/status`, the bound session
  watcher, guarded tmux injection, per-thread state/audit files, and the
  user-level skill.
- The installer owns `~/.agents/skills/reconnect`; Codex 0.144.6 discovered it
  with scope `user` even under a distinct `CODEX_HOME`.
- The 46-test suite and repeated JSONL/SQLite/input-race runs pass.
- Non-tmux activation fails with exit code 3 and creates no watcher.
- An installed end-to-end disposable tmux smoke consumed a synthetic terminal
  disconnect, passed real OpenAI HTTPS readiness, injected one literal
  `continue`, and stopped cleanly through `off`.
- A real Codex 0.144.6 disconnect on 2026-07-21 supplied an SQLite-only
  terminal-error row. The 0.3.1 parser matched its exact thread/turn and the
  affected live watcher was restarted with the current SQLite cursor as
  `armed`.
- A second real disconnect was detected and reached two successful primary
  probes, but 0.3.1 skipped injection because Codex changed its dim placeholder
  text. Version 0.3.2 uses cursor/style proof plus a conditional tmux cursor
  fence and retires same-pane stale watchers.
- A third real recovery under 0.3.2 wrote `continue` but immediate Enter became
  a newline. CCB `ask` source established the reliable buffer-paste, delay,
  Enter, cleanup sequence; 0.3.3 implements it with cursor fences and produced
  a real Codex `user_message: continue` plus a new `task_started` turn.

Actual provider disconnect and organically occurring `serverOverloaded`
qualification remain open and must not be replaced by deliberate provider
pressure.

## Consequences

- Any ordinary Codex CLI opened inside tmux can opt in without restart or
  aliasing `codex`.
- Codex owns all command-line parsing, so current and future Codex parameters
  remain compatible.
- Recovery depends on Codex's persisted rollout event shape and tmux. Unknown
  schemas, missing identity, missing pane, non-empty/unprovable input state, or
  unsupported errors fail closed.
- A skill activation must execute while the Codex turn can still run local
  tools. Once armed, the watcher is local and survives provider/network loss.
- Quota, billing, authentication, policy, approval, context-window, and
  ordinary task failures remain out of scope.
- Native Windows transport work is deferred unless a Windows tmux-compatible
  environment is separately qualified.
