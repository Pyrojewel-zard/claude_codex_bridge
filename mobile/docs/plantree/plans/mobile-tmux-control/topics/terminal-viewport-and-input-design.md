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
- The source pane remains a desktop-sized capture grid. Flutter's xterm model
  independently sizes itself to the phone viewport at the persisted readable
  font size, so captured rows wrap locally to the available device width.
- The gateway sends a complete visible-pane repaint whenever a fixed-source
  snapshot changes. It does not send source-row cursor deltas into the locally
  wrapped phone grid.
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
- Chat mode and terminal-history bubbles remain unaffected.
- Focused Python and Flutter tests, static analysis, APK build, and real
  server-wide Android Emulator validation pass.

## Automated Evidence

Current evidence:

- Python terminal tests: 25 passed. The real tmux test opens a two-pane window,
  opens two mobile sessions, requests phone resizes, closes both sessions, and
  asserts exact source window/pane/layout equality at every step.
- Gateway, terminal, and host lifecycle integration tests: 178 passed. The
  WebSocket contract reports `fixed_source` and ignores an incoming Agent
  Terminal resize frame.
- Flutter terminal transport, contract, keyboard, viewport, and reconnect
  focused tests cover local device-width reflow and repeated snapshot
  replacement. The broader terminal, LAN/Relay transport, navigation, layout,
  and settings batch passed 110 tests serially. Legacy `adaptive_pane` remains
  non-owning for source geometry.
- Full Flutter suite: 778 passed, 1 skipped.
- Python compile, `flutter analyze`, debug APK build, and scoped
  `git diff --check`: passed.

Real Android evidence used `emulator-5554`, the isolated current-source
server-wide gateway at `127.0.0.1:8831`, and the dedicated real project
`pr289-pi-real-smoke / main / pi1`. Evidence is outside the source tree under
`/tmp/ccb-mobile-responsive-source-20260814/`:

- A pseudo-desktop tmux client stayed attached at `160x48`; its window stayed
  `160x47` with panes `12x46` and `147x46`.
- The complete window/pane/layout snapshot SHA256 remained
  `57e0010f6f402182cb8d81ad04235477ef92987d1fc98ecc98226ec4b349d212`
  before open, after portrait rendering, after rotation, after keyboard
  display, and after gateway restart/reconnect.
- `04-terminal-portrait.png` shows the 160-column source content wrapped to a
  readable portrait device width with no horizontal source-grid canvas.
- `05-terminal-landscape.png` shows the same live source using the wider
  landscape geometry without changing tmux.
- `06-terminal-keyboard.png` covers terminal input focus and keyboard state.
- `08-dynamic-input.png` proves a changed real pane snapshot appears in place
  without leaving or reopening the terminal.
- `09-after-gateway-reconnect.png` proves the responsive projection recovers
  after a forced gateway restart.
- Installed debug APK SHA256 is
  `ee1c05a11f69e373fe2a6433f3cb9ca816b419a2f413b6cb3afabc7dd98b3dce`;
  filtered logcat contains no app fatal exception.

The earlier adaptive-pane emulator evidence is superseded. It proved that the
phone could resize and later restore a pane, but it did not satisfy simultaneous
desktop usability and therefore is not acceptance evidence for this design.

## Open Edges

- The responsive projection cannot make a provider recompute box drawing or
  full-screen layout for phone columns. Exact provider-native mobile geometry
  still requires a separately owned PTY/provider session.
- Touch selection, context copy/paste UI, terminal mouse reports, and external
  wheel routing remain a separate pointer-input package.
- Snapshot polling remains the transport baseline; tmux control-mode pane
  output is a future latency improvement after equivalent replay tests exist.
