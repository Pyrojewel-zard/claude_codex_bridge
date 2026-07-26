# Implementation Status

Date: 2026-07-22

## Current Phase

The Decision 006 tmux refactor is implemented in the standalone working tree
`/home/bfly/yunwei/codex-reconnect` and installed locally as
`codex-reconnect 0.3.3`. The tmux watcher, user-level skill, fail-closed input
guards, and installation lifecycle are deterministic-test and installed-smoke
complete. Real provider-fault qualification remains the production gate.

The 0.3.3 tmux refactor was committed and pushed to `origin/main` on
2026-07-22 as
[`1134122`](https://github.com/SeemSeam/codex-reconnect/commit/113412276abdea3d42d183477798307000fac307).
The earlier 0.2.0 App Server bridge remains in the repository as a non-default
compatibility path.

## Landed

- Public `codex-reconnect on`, `off`, and `status` commands plus a hidden
  watcher-process entry point.
- Direct activation only from an exact tmux/Codex environment; non-tmux `on`
  fails before creating state or a process.
- Exact thread, Codex home, rollout file, tmux socket, pane id, pane pid, and
  pane foreground-command binding.
- Owner-only per-thread state, lock, watcher log, and redacted audit JSONL.
- Rollout EOF tailing plus owner-controlled `logs_2.sqlite` cursor monitoring,
  exact thread/turn correlation, internal-retry exclusion, and terminal
  `task_complete` gate.
- Network/overload-only recovery with overload jitter, two stable primary HTTPS
  successes, optional public diagnostic, and a final dual-source event drain.
- Newer-progress cancellation, pane revalidation, styled empty-input cursor
  proof, CCB-style bracketed buffer paste, 0.5-second input settling, staged
  text/cursor verification, conditional Enter, and buffer cleanup.
- Same-pane thread replacement disables and retires older watcher processes.
- One automatic continuation per incident and fail-closed recursive-error
  circuit breaker.
- User-level `reconnect` skill with exact `on/off/status` behavior and disabled
  implicit invocation.
- Atomic user-local application update plus safe ownership-aware command and
  `~/.agents/skills/reconnect` symlink management.
- Correct `arming` to `armed` transition when empty-input state is learned.
- Bilingual 0.3.3 README usage, recovery, installation, state, security, and
  qualification documentation.
- Legacy `codex-reconnect open` bridge regression compatibility.

## Verification Evidence

- `python3 -m unittest discover -s tests -v` in the standalone repository — 46
  passed again as the final release gate on 2026-07-22.
- The SQLite terminal-error plus JSONL completion recovery test passed 10
  consecutive repetitions.
- The terminal-disconnect/two-probe/injection race test passed 10 consecutive
  repetitions after its state-update synchronization was tightened.
- `python3 -m black --check codex_reconnect tests`, Python compile, `sh -n` for
  both installers, and `git diff --check` passed.
- Real tmux atomic-input smoke produced `GOT:continue` from one literal
  `send-keys` command sequence.
- Installed-path end-to-end tmux smoke armed thread
  `installed-tmux-live-smoke-thread`, consumed a synthetic terminal disconnect,
  passed two real OpenAI/Codex HTTPS probes, injected one `continue`, accepted
  `off`, and left no watcher process.
- Installed non-tmux `reconnect on` returned exit code 3 with
  `TMUX/TMUX_PANE missing` and started no watcher.
- `codex app-server` `skills/list` under a distinct temporary `CODEX_HOME`
  returned the installed `reconnect` skill with scope `user` from
  `~/.agents/skills/reconnect`.
- A real Codex 0.144.6 failure on 2026-07-21 showed no JSONL `event_msg:error`
  but did record `codex_core::session::turn: Turn error` in `logs_2.sqlite`.
  The 0.3.1 parser identified its exact thread, turn, row, and network class.
- A second real disconnect was detected, waited through loss of both primary
  and public HTTPS, then reached two primary HTTPS successes. Injection was
  skipped because Codex rotated its dim placeholder text; 0.3.2 now proves the
  cursor row/column and placeholder style instead of comparing placeholder
  text, with a final conditional cursor check inside the tmux send command.
- Local installation resolves to `~/.local/bin/codex-reconnect`, reports
  version 0.3.3, and the installed source/skill files match the working tree.
- The affected live pane was restarted on 0.3.3 and reached `armed` as PID
  `146071`; its older same-pane watchers remain retired.
- A disposable real tmux accepted the conditional send only at its expected
  cursor and received exactly `continue`.
- CCB `ask` source inspection identified its reliable sequence as
  `load-buffer`, `paste-buffer -p`, a default 0.5-second delay, separate Enter,
  and `delete-buffer`; 0.3.3 implements that sequence with extra pre-paste and
  pre-Enter cursor fences.
- A real 0.3.2 recovery detected turn
  `019f84c2-eb56-75e3-a264-1f9595aeefef`, waited for network readiness, and
  wrote `continue`, but immediate Enter became a newline and left the watcher
  incorrectly at `recovery_sent`. This is the captured regression shape.
- Installed 0.3.3 then bracket-pasted and submitted `continue` in the same real
  Codex pane; session JSONL recorded `user_message: continue` and new turn
  `019f84e0-ab2b-7060-a5dc-a0b7a71342f0` reached `task_started`.
- The 300-round live qualification attempt in turn
  `019f84e3-2271-7d61-a202-4b85e4585dce` was manually interrupted after
  25/300. It produced no eligible terminal network failure, readiness probes,
  or automatic continuation and therefore is not counted as qualification.
- Release commit `113412276abdea3d42d183477798307000fac307` passed the 46-test
  suite, Black, Python compilation, both installer shell syntax checks, and
  cached-diff validation; `git ls-remote` confirmed the same hash at
  `refs/heads/main`.

## Open Qualification

- Repeat an actual terminal response-stream disconnect under 0.3.3 and verify
  SQLite detection, JSONL completion correlation, two stable OpenAI HTTPS
  successes, and one continuation.
- Capture an organically occurring provider `serverOverloaded` terminal event
  and compare it with the deterministic structured fixture.
- Exercise multiple independent live Codex panes and inspect per-thread state,
  cancellation, and teardown.
- Observe a real failed automatic continuation and verify circuit-open behavior
  without creating provider pressure intentionally.

## Claim Boundary

The tmux implementation is deterministic-test complete, installed locally,
and proven end to end against both JSONL and real-shape SQLite fixtures plus
real network readiness. A real pre-fix transport failure supplied the missing
event-shape evidence, but post-fix automatic continuation and organic
service-overload qualification remain open.
