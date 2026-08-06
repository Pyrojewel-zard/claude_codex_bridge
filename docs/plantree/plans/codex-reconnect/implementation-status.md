# Implementation Status

Date: 2026-08-07

## Current Phase

CCB automatic installation and activation are implemented, committed, and
published on `origin/main` in CCB v8.5.6 source commit
[`8b35d868`](https://github.com/SeemSeam/claude_codex_bridge/commit/8b35d868f402e5f68929782a6c2df657a8750d21).
The integration is publicly available in the bilingual
[`v8.5.6` GitHub Release](https://github.com/SeemSeam/claude_codex_bridge/releases/tag/v8.5.6)
and npm package `@seemseam/ccb@8.5.6` from tag commit `58b49c12`.
The bridge requests bundled `on` only after a concrete managed thread is bound,
records one successful enable per bridge/thread, retries startup failures with
bounded backoff, preserves a later explicit `off` or circuit-open state, and
requests shutdown of its owned watcher.

The Decision 006 tmux refactor is implemented in the standalone working tree
`/home/bfly/workspace/agent_develop/codex-reconnect`, installed locally and published as
`codex-reconnect 0.3.6`, and synchronized into CCB's vendored copy. CCB
projects the `reconnect` skill and command into each managed Codex environment
and exposes the exact managed pane/session identity needed by the watcher. The tmux
watcher, fail-closed input guards, installation lifecycle, and isolated
managed-Codex activation are deterministic-test complete. Real provider-fault
qualification remains the production gate.

The 2026-08-05 source patch closes the low-capability recovery gap observed in
Codex 0.145.0: terminal overload is emitted as a nested `error` object on
`task_complete`, and the exact `Selected model is at capacity` text is also
recognized by the SQLite fallback. The source watcher now routes both shapes
through the existing two-probe, single-literal-`continue` state machine. The
0.3.5 user-local installation completed on 2026-08-05, and the current managed
Codex pane was rebound from stale pane PID `2997587` to current PID `30678`.
Its only live watcher reached `armed`; organic real-provider requalification
remains open.

The 0.3.3 tmux refactor was committed and pushed to `origin/main` on
2026-07-22 as
[`1134122`](https://github.com/SeemSeam/codex-reconnect/commit/113412276abdea3d42d183477798307000fac307).
The earlier 0.2.0 App Server bridge remains in the repository as a non-default
compatibility path.

Version 0.3.4 and the CCB-managed session support commit were pushed to
`origin/main` on 2026-08-05 as
[`fe5cf50`](https://github.com/SeemSeam/codex-reconnect/commit/fe5cf50c6a8fc086a99441c2e0460e55958c77c6).

Version 0.3.5 then added delayed-start arming, same-thread managed-pane restart
takeover, and signal-driven owner-instance shutdown. Its three commits end at
[`387b88f`](https://github.com/SeemSeam/codex-reconnect/commit/387b88f665ccdc42ba35dd834f789ef735a83a8d)
and are published on `origin/main`.

Version 0.3.6 fixes a Provider-route false negative: recovery now probes the
active Provider route materialized in the managed Codex home instead of always
probing `chatgpt.com`. Config authority takes precedence over ambient API route
variables, while standard OpenAI remains the fallback. The same terminal turn
observed through JSONL and SQLite is deduplicated. The standalone source is
published on `origin/main` as
[`94ec479`](https://github.com/SeemSeam/codex-reconnect/commit/94ec4799c719ce182cbd7073576aa0a37e6aeb39).

The 2026-08-07 local preview install was built from clean CCB commit `43e50b08`
with the unchanged official v8.5.6 Rust helpers. Installed CCB reports that
commit and bundled `codex-reconnect 0.3.6`; installed reconnect source hashes
match the standalone authority. The installed resolver selected the active
custom Provider and received HTTP 200. An idle-gated `ccb restart ccb_self`
retained thread `019fd5da-7201-7120-b0af-bede0a4e64c5`, replaced the old
watcher with PID `3908802`, and reached `armed` with a non-default primary
probe route.

## Landed

- Public skill surface limited to `reconnect on` and `reconnect off`; the CLI
  retains `status` for diagnostics plus a hidden watcher-process entry point.
- Direct activation only from an exact tmux/Codex environment; non-tmux `on`
  fails before creating state or a process.
- Exact thread, Codex home, rollout file, tmux socket, pane id, pane pid, and
  pane foreground-command binding.
- Owner-only per-thread state, lock, watcher log, and redacted audit JSONL.
- Rollout EOF tailing plus owner-controlled `logs_2.sqlite` cursor monitoring,
  exact thread/turn correlation, internal-retry exclusion, and terminal
  `task_complete` gate.
- Network/overload-only recovery with overload jitter, two stable active-Provider
  HTTPS successes, optional public diagnostic, and a final deduplicated
  dual-source event drain.
- Newer-progress cancellation, pane revalidation, styled empty-input cursor
  proof, CCB-style bracketed buffer paste, 0.5-second input settling, staged
  text/cursor verification, conditional Enter, and buffer cleanup.
- Same-pane thread replacement disables and retires older watcher processes.
- One automatic continuation per incident and fail-closed recursive-error
  circuit breaker.
- User-level `reconnect` skill with exact `on/off` behavior and disabled
  implicit invocation; CLI-only `status` remains available for diagnostics.
- CCB-owned `reconnect` skill projection alongside `ask` and `ccb-clear`,
  including repair of managed homes that already contain `.system` skills.
- CCB source-test and installed command entry points for the vendored
  `codex-reconnect` implementation.
- Validated CCB session-pointer binding for environments where generic
  `TMUX`/`TMUX_PANE` are intentionally sanitized.
- Owner-checked managed `logs_2.sqlite` symlink support and a diagnostic filter
  that drops ordinary rows while retaining terminal Codex `Turn error` rows.
- Per-agent reconnect state under the managed provider runtime, preventing
  collisions between concurrent CCB Codex instances.
- Atomic user-local application update plus safe ownership-aware command and
  `~/.agents/skills/reconnect` symlink management.
- Correct `arming` to `armed` transition when empty-input state is learned.
- Bilingual 0.3.3 README usage, recovery, installation, state, security, and
  qualification documentation.
- Legacy `codex-reconnect open` bridge regression compatibility.
- Nested `task_complete.error` terminal classification for Codex 0.145.0,
  including selected-model capacity wording in both JSONL and SQLite paths.
- Automatic CCB activation after authoritative thread binding with bounded
  retry and no background re-enable after a successful arm.
- Same-thread watcher takeover after the same tmux socket and pane receive a
  new managed pane pid; other pane/socket conflicts remain fail closed.
- `SIGTERM`/`SIGINT` shutdown writes `enabled=false,status=off` for the current
  watcher instance without overwriting a superseding watcher.

## Verification Evidence

- `python3 -m unittest discover -s tests -v` in the standalone repository — 51
  passed on 2026-07-26, including CCB session binding, managed SQLite symlink,
  lazy SQLite discovery, and exact `/backend-api/codex/responses` failure
  fixtures.
- CCB targeted pytest qualification passed for diagnostic filtering,
  reconnect integration, launch environment, skill projection, installer
  behavior, source-test shims, and repository hygiene.
- Standalone and vendored watcher suites each passed 59 tests on 2026-08-05.
  Both suites
  include nested capacity completion, internal-retry exclusion,
  two-probe gating, one-time literal `continue`, and audit-state assertions.
- `test/test_codex_reconnect_integration.py` — 1 passed on 2026-08-05 with an
  isolated provider home; Python compilation and `git diff --check` also passed.
- An isolated source CCB project under `/home/bfly/yunwei/test_ccb2` opened a
  real managed Codex, projected the skill and command shim, bound a real thread
  through `CCB_SESSION_FILE`, and reached `armed` without `$reconnect on`.
- The same source-runtime project retained thread
  `019fd12f-c2bf-7500-ba93-89d110f9fbd5` across CCB restart, replaced the old
  pane-generation watcher, and shut down with lifecycle `unmounted`, watcher
  `enabled=false,status=off`, and zero Codex/bridge/provider runtime processes.
- A later inherited-authority change in that project created qualified fork
  thread `019fd239-3e0a-70a1-b864-4a44e603740a` without archiving the old
  transcript; the old and forked logs had matching user-message hashes. A
  same-authority Agent restart retained the forked thread, rebound reconnect to
  the new pane pid as `armed`, and normal project shutdown recorded `off` with
  no project process residue.
- CCB autostart, bridge, and source-dev install integration passed 15 targeted
  pytest tests after the 0.3.5 signal-shutdown synchronization.
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
  version 0.3.5, and the installed source/skill files match the standalone
  working tree. The replaced CCB wrapper is retained at
  `~/.local/share/codex-reconnect-wrapper-backup.VG8QmJ/codex-reconnect`.
- The affected live pane was rebound on 0.3.4 and reached `armed` with watcher
  PID `466234`; only that watcher remains live for the pane.
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
- CCB v8.5.6 source commit `8b35d868f402e5f68929782a6c2df657a8750d21`
  was pushed to `origin/main` and installed locally in source/dev mode. The
  installed commands report CCB `8.5.6` and `codex-reconnect 0.3.5`; watcher
  PID `466234` remained live with `status=armed` after installation.
- CCB tag `v8.5.6` points to `58b49c12`; GitHub Release artifacts and npm OIDC
  publication completed successfully, and npm `latest` resolves to `8.5.6`.

## Open Qualification

- Verify the current 0.3.6 live pane reaches `waiting_network` and submits one
  `continue` for an organically observed capacity event.
- Repeat an actual terminal response-stream disconnect under 0.3.6 and verify
  SQLite detection, JSONL completion correlation, two stable active-Provider HTTPS
  successes, and one continuation.
- Capture an organically occurring provider `serverOverloaded` terminal event
  and compare it with the deterministic structured fixture.
- Exercise multiple independent live Codex panes and inspect per-thread state,
  cancellation, and teardown.
- Observe a real failed automatic continuation and verify circuit-open behavior
  without creating provider pressure intentionally.

## Claim Boundary

The tmux implementation is deterministic-test complete, integrated into CCB,
and proven end to end against both JSONL and real-shape
SQLite fixtures plus real network readiness. CCB-managed skill discovery and
activation are qualified. A real pre-fix transport failure supplied the
missing event-shape evidence. The source fix, user-local installation, and live
`armed` binding are verified; post-fix automatic continuation during an organic
disconnect or organic service-overload event remains open.
