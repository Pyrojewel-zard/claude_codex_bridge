# Terminal Viewport And Input Design

Date: 2026-08-14
Status: Implemented and verified on a real server-wide Android Emulator route

## Role

Define the mobile raw-terminal viewport and input contract for the explicit
Open Terminal route. The normal project surface remains chat-first.

Related:

- [chat-first agent workspace](chat-first-agent-workspace.md)
- [terminal transport spike](terminal-transport-spike.md)
- [Decision 012](../decisions/012-agent-first-project-workspace.md)
- [Decision 013](../decisions/013-readable-terminal-history.md)
- [Decision 014](../decisions/014-chat-first-agent-workspace.md)

## Product Boundary

Raw terminal rendering, pointer ownership, special keys, and keyboard
coordination stay inside the explicit Terminal route. Font configuration is
shared by all terminal routes and lives in the app Settings control panel.

The Terminal route uses Termux as an interaction reference while retaining the
Flutter xterm client and CCB gateway. It does not embed Termux or replace the
CCB session model.

## 2026-08-14 Dual-Geometry Source Viewport Decision

Two direct PTY implementations are rejected for Agent Terminal:

1. Replaying source-row cursor deltas into a different phone grid. Source row
   addresses are invalid after local wrapping and produce misplaced updates.
2. Resizing the shared tmux window or pane to phone geometry. A tmux pane has
   one authoritative PTY geometry, so this also resizes and reflows every
   desktop client. It produced the large dotted unused area reported on the
   computer and is not an acceptable mobile side effect.

Agent Terminal therefore uses a dual-geometry `fixed_source` projection:

- The gateway reads the selected pane's actual columns and rows from tmux.
- The gateway never calls `resize-window`, `resize-pane`, or a resize ioctl for
  an Agent Terminal session.
- Mobile resize frames are not sent for `fixed_source`; the gateway also
  ignores such frames defensively if an older client sends one.
- Geometry revisions report desktop-side source changes to the phone. They are
  observations, not ownership transfers.
- The source pane remains a desktop-sized capture grid. The gateway captures
  it with tmux `capture-pane -J`, joining source soft-wrap rows back into
  logical lines before Flutter reflows them at the persisted readable font
  size and current device width.
- Fixed-source output uses a structured `replace_snapshot` projection. Stable
  scrollback and the mutable visible screen are separate fields; only rows
  proven to have scrolled off the source pane append to local history.
- Flutter replaces the projected screen in place for every edit. It does not
  replay source-row cursor deltas or append ANSI full-screen repaints to xterm
  scrollback. The legacy byte repaint remains in the wire frame only for older
  clients.
- Local xterm resize callbacks update only the phone renderer and the geometry
  used for a future session open. They never send a tmux resize operation.
- No visible Fit/1:1 selector or terminal-local font toolbar is added.
- Rotation, keyboard visibility, split layout, reconnect, and a second mobile
  viewer may change the local viewport but never source geometry.

This is deliberately different from Termux's own PTY. Termux can give the
running application the phone's real PTY geometry. Agent Terminal cannot do
that without changing the desktop provider pane, so its phone adaptation is a
responsive projection of captured screen rows. Text remains readable and
uses the device width, while box-drawing/full-screen layouts may wrap rather
than recompute their provider-native layout.

Host Terminal is different: each host shell is a CCB Mobile-owned tmux session
with `client` resize policy. The phone may resize that isolated session because
no desktop provider pane shares it.

The retired `adaptive_pane` value remains decode-compatible for older gateways,
but the app treats it as fixed source and never sends resize frames.

## App And Host Runtime Compatibility

The APK and the computer-side Mobile Host are separate runtime surfaces. An
updated APK does not replace an already-running Host process. A fixed-source
terminal requires the Host to emit `replace_snapshot`; an older Host emits only
the legacy append stream, which causes both clipped desktop-width rendering and
stale prompt rows during Backspace edits.

The core `ccb update` post-update entrypoint must therefore restart an active
managed Mobile Host with the newly installed code. The restart contract is:

- restart only a live service whose recorded entrypoint belongs to the updated
  installation;
- leave an intentionally stopped service stopped;
- leave a Host launched from a source/development checkout untouched;
- preserve listen address, route provider, host identity, pairing handoff, and
  paired-device tokens;
- do not rotate access merely because the executable changed;
- report a non-blocking warning and the `ccb update mobile` recovery command if
  service replacement fails.

This lifecycle rule prevents a new App from silently falling back to the old
append protocol after a successful computer-side update.

## Viewport And Font UI

- The terminal has one readable font size, defaulting to 13pt and bounded to
  10-22pt.
- `Settings > Terminal settings` is the only font-size control surface.
- Pinch does not mutate terminal font size.
- Agent Terminal locally wraps the fixed source snapshot to the device width;
  Host Terminal fills the viewport and resizes its isolated PTY.
- Entering Agent Terminal collapses the project/agent chrome into the same
  compact bar used by chat.
- Terminal content uses all available space below route and tab chrome.

## Pointer, Keyboard, And Shortcuts

- Touch drag scrolls terminal history. Agent Terminal has no second horizontal
  source-grid canvas.
- Tapping latest output activates terminal input and the software keyboard.
- Scrolling history disables input until the user returns to latest output.
- Hardware keyboard input remains scoped to the Terminal route.
- The extra-key surface stays collapsed under `+` and supports configured
  ordering, sticky modifiers, navigation keys, and common control sequences.
- Automatic terminal device/status reports are filtered from pane input;
  explicit user keys and text still reach the selected pane.
- Reconnect re-observes current source geometry and never reapplies a stale
  phone geometry.

## Implementation Packages

1. Source geometry package:
   remove shared-window leases and expose `fixed_source` geometry revisions.
2. Protocol package:
   suppress client resize for source panes in both Flutter and the gateway.
3. Flutter viewport package:
   keep readable persisted font settings and size the local xterm renderer to
   device constraints without a permanent mode toolbar.
4. Input package:
   filter automatic xterm response frames while preserving explicit input.
5. Verification package:
   prove exact tmux layout invariance in tests and on a real Android Emulator.

## Acceptance Gates

- Opening Agent Terminal leaves tmux window dimensions, pane dimensions, and
  `window_layout` exactly unchanged.
- Phone rotation, keyboard open/close, font changes, reconnect, concurrent
  mobile viewers, navigation, and app close leave those values unchanged.
- A desktop client remains usable with no new dotted unused region while the
  mobile terminal is open.
- Source columns are not clipped before reaching Flutter and are locally
  wrapped into the current device width.
- The phone font remains readable and never auto-shrinks to fit a desktop grid.
- Portrait, landscape, font, and keyboard layout changes recompute only the
  local render geometry and never send a source-pane resize frame.
- Host Terminal still follows phone dimensions because its PTY is isolated.
- Terminal input, Chinese text, shortcuts, history scrolling, reconnect, and
  stale-target handling remain functional.
- Repeated Backspace edits replace the current prompt row in place; no stale
  `xxxxx`, `xxxx`, `xxx` staircase may accumulate in local scrollback.
- Updating CCB while a managed Mobile Host is active replaces its PID and
  increments its generation without changing route/listen or revoking an
  already-paired device token.
- Chat mode and terminal-history bubbles remain unaffected.
- Focused Python and Flutter tests, static analysis, APK build, and real
  server-wide Android Emulator validation pass.

## Automated Evidence

Current automated evidence:

- `test_mobile_gateway_terminal.py` and `test_mobile_gateway_service.py`:
  155 passed. The real tmux projection test uses a 24-column pane, verifies
  that a 36-character wrapped input becomes one logical row, applies three
  Backspaces, and proves both in-place replacement and exact source geometry.
- Flutter projection/transport/pane focused batch: 34 passed. The broader
  terminal, navigation, LAN/Relay, and settings regression batch: 118 passed.
- `flutter analyze`, debug APK build, Python compile, and scoped
  `git diff --check`: passed.
- The repository-wide Flutter suite passed serially: 780 passed and 1 skipped.
  The core-probe regression now waits for the explicit `reconnecting` event
  instead of assuming the loopback HTTP round trip finishes within 20ms.
  Parallel execution can still make local socket-heavy tests contend, so the
  release gate uses `--concurrency=1` for deterministic coverage.

Latest real Android evidence used `emulator-5554`, the current-source
server-wide gateway at `127.0.0.1:8832`, and the dedicated mounted project
`test_ccb2_alpha / main / mobile_peer`. Evidence is owner-local and remains
outside the source tree under
`/tmp/ccb-mobile-terminal-projection-e2e/evidence/`:

- `05-terminal-portrait-long-line-peer.png` shows the complete
  `...RIGHT_EDGE` marker reflowed to readable portrait width.
- `06-terminal-landscape-long-line.png` shows the same logical content using
  fewer rows at landscape width.
- `07-terminal-phone-input-xxxxx.png` and `08-delete-1.png` through
  `09-delete-all.png` prove real Android keyboard input and one-at-a-time
  deletion. The final frame has one empty `mobile$` prompt and no stale rows.
- `tmux-layout-before.txt` and `tmux-layout-after-landscape.txt` have the same
  SHA256 (`684eb3e622089f5a68a0f4461b39157dd3563235ce56104457706e2ca01b3b9a`),
  proving phone reflow did not resize the desktop-owned tmux layout.
- Installed debug APK SHA256 is
  `79e5a04b93a9a7f1f2a7c0388735bd71b2f4f4892cf85e557d831c6836cae7bb`.

The earlier adaptive-pane and ANSI repaint evidence is superseded. Resizing a
shared pane affected desktop clients, while appending full-screen repaints
created stale prompt rows during edits. Neither behavior satisfies this
design.

The signed v8.6.5 compatibility investigation used the public Relay and a real
Codex pane in the dedicated
`test_ccb2/mobile-terminal-v865-real-provider` project. Owner-local evidence is
outside the source tree under `/home/bfly/.cache/ccb-emulator/final-v865/`:

- `real-relay-provider-keycode-xxxxx.png` and
  `real-relay-provider-keycode-delete-1.png` through `delete-5.png` show one
  prompt row changing from `xxxxx` to empty with no stale-row staircase;
- `current.png` and `real-relay-provider-landscape.png` show the same
  187-column provider pane reflowing at readable size in portrait and expanding
  to the landscape width;
- the installed package reports `versionName=8.6.5` and
  `versionCode=8060005`.

The process-level update fixture is recorded outside the source tree at
`/home/bfly/.cache/ccb-host-refresh-e2e/result.json`. It proves PID replacement,
generation increment, unchanged route/listen and pairing code, and successful
authentication with the pre-restart device token.

## Open Edges

- The responsive projection cannot make a provider recompute box drawing or
  full-screen layout for phone columns. Exact provider-native mobile geometry
  still requires a separately owned PTY/provider session.
- Touch selection, context copy/paste UI, terminal mouse reports, and external
  wheel routing remain a separate pointer-input package.
- Snapshot polling remains the transport baseline; tmux control-mode pane
  output is a future latency improvement after equivalent replay tests exist.

## Relay Initial History Flow Control

Agent Terminal's first fixed-source projection may contain up to 1000 lines of
scrollback. The projection frame intentionally carries both the structured
snapshot and legacy terminal bytes, so a normal provider pane can exceed the
old 256 KiB Relay receive window while remaining below the valid 512 KiB Relay
message limit. Waiting for additional credit cannot make progress because the
phone replenishes credit only after it receives that first frame.

The Relay inner protocol therefore requires the initial receive window to be
at least the maximum valid single-message size. Python Host/reference-client
and Flutter phone constants stay identical. Regression coverage sends an
encrypted terminal frame above 256 KiB through the real Host-Relay-phone test
harness and requires delivery before the stream write timeout. This preserves
the full initial terminal history instead of hiding the bug by reducing the
history line count.
