# Roadmap

Date: 2026-08-06

## Done

- Requirements narrowed to disconnect-only current-session recovery.
- GitHub and official Codex capability search completed; no drop-in equivalent
  found.
- Public project, CLI, package, runtime identifiers, and PlanTree root named
  `codex-reconnect`.
- Standalone private GitHub repository established with bilingual READMEs,
  user-local install/update, conservative uninstall, and Linux/macOS CI.
- Earlier transparent App Server bridge completed and retained as a legacy
  compatibility/rollback path.
- Decision 006 accepted and implemented as the primary tmux mode.
- Native `codex` remains unwrapped, so all Codex arguments and subcommands stay
  under Codex ownership.
- Exact current `CODEX_THREAD_ID`, rollout JSONL, tmux socket, pane id, pane
  pid, and pane command binding implemented.
- EOF/cursor-only structured JSONL and SQLite terminal-error monitoring,
  internal-retry exclusion, exact thread/turn correlation, and matching
  `task_complete` gate implemented.
- Two-success OpenAI HTTPS gate, optional public diagnostic, post-probe event
  drain, newer-progress cancellation, and overload jitter implemented.
- Styled empty-input cursor proof, pane revalidation, CCB-style bracketed
  buffer paste, settling delay, staged-input proof, conditional Enter,
  one-recovery limit, and recursive-failure circuit breaker implemented.
- User-level `~/.agents/skills/reconnect` installation and safe update/uninstall
  lifecycle implemented.
- Codex 0.144.6 verified the user skill across a distinct `CODEX_HOME`.
- Non-tmux `reconnect on` fail-fast behavior verified with exit code 3 and no
  watcher process.
- 46 deterministic tests, repeated JSONL, SQLite, and input-race runs,
  formatting, shell syntax, compile, and diff checks passed.
- Installed 0.3.0 end-to-end smoke passed in a disposable real tmux: simulated
  terminal disconnect, real OpenAI HTTPS readiness, one `continue`, then clean
  `off` with no residual watcher.
- A real 0.144.6 disconnect proved that some terminal failures exist only in
  `logs_2.sqlite`; 0.3.1 added this source, parsed the captured real row, fixed
  the stale `arming` status, and restarted the affected pane as `armed`.
- A second real disconnect reached the recovery gate and exposed rotating
  placeholder text as a false non-empty-input result. Version 0.3.2 replaces
  text equality with cursor/style proof, conditionally rechecks the cursor in
  tmux, retires same-pane stale watchers, and is installed as `armed`.
- A third real disconnect under 0.3.2 proved immediate literal `continue` plus
  Enter can leave an unsubmitted multiline draft. Version 0.3.3 adopts CCB's
  buffer-paste/delay/Enter mechanism with stronger cursor fences; a real Codex
  session recorded its submitted `continue` and started the next turn.
- Release commit `1134122` passed the final 46-test and static-check gate and
  was pushed to GitHub `origin/main` on 2026-07-22.
- Captured Codex 0.145.0 terminal capacity failures now have deterministic
  coverage: `task_complete.error` and SQLite `Turn error` are both classified
  as `serverOverloaded`, then gated by two primary probes before one literal
  `continue`.
- Version 0.3.4 was synchronized to the standalone authority and CCB vendored
  copy, passed both 55-test suites, installed through the atomic user-local
  installer, and rebound the current pane's only watcher to `armed`.
- Version 0.3.5 waits for delayed prompt readiness, supersedes only the same
  thread/socket/pane watcher after a managed pane PID restart, and marks the
  current watcher instance `off` on `SIGTERM`/`SIGINT`.
- Version 0.3.6 probes the active Codex Provider route from managed config,
  falls back through ambient API route variables to standard OpenAI, and
  deduplicates matching JSONL/SQLite terminal failures.
- CCB automatic activation after authoritative thread binding is implemented
  with one successful enable per bridge/thread, bounded activation retry, and
  best-effort bridge shutdown.
- A real source-runtime CCB project auto-armed without `$reconnect on`, retained
  its Codex thread through restart, replaced the old pane-generation watcher,
  and shut down to `unmounted` with reconnect `off` and zero runtime residue.
- Standalone and vendored deterministic suites pass 59 tests; CCB bridge,
  autostart, and install integration passes 15 targeted tests.
- Standalone 0.3.5 commit `387b88f` is published on GitHub `origin/main`.
- Standalone 0.3.6 commit `94ec479` is published on GitHub `origin/main`.
- CCB automatic install/activation and the vendored 0.3.5 implementation were
  published on CCB `origin/main` as v8.5.6 source commit `8b35d868`, then
  installed locally with both installed version checks passing and the current
  watcher remaining `armed`.
- CCB v8.5.6 was released from tag commit `58b49c12` with bilingual GitHub
  notes, Linux/macOS/Android assets and checksums, and npm
  `@seemseam/ccb@8.5.6` promoted to `latest`.

## In Progress

- Perform post-fix real network-fault and organically occurring
  `serverOverloaded` qualification through an actual tmux Codex session.

## Next

- Linux/macOS/WSL2 acceptance across multiple independent live Codex panes.
- Inspect real failure audit/state transitions and recursive-failure circuit
  behavior without causing duplicate side effects.
- Evaluate a standalone `codex-reconnect` tag and optional package-registry
  delivery after the real-provider gate passes.

## Deferred

- Native Windows without tmux; Decision 006 is tmux-specific and WSL2 is the
  supported Windows-hosted path for this mode.
