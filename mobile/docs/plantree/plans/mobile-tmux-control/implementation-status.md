# Mobile Tmux Control Implementation Status

Date: 2026-08-12

## Paseo-Aligned Provider Control Plane — Implemented And Accepted

The source and Flutter implementation now expose selected-agent Provider,
active/configured/pending model and thinking state, bounded Codex/Claude native
session usage, a capability-driven model sheet, and separately loaded account
quota. Model/thinking changes are scope-protected and fenced by project epoch,
Provider identity, runtime revision, config revision, and idempotency key; the
current truthful apply mode is `restart_required` and never auto-restarts an
active task. Direct HTTP and encrypted Relay carry the same fixed contract.

Paseo alignment is pinned to `getpaseo/paseo` commit `b599d38`; provenance and
source-to-target mapping are recorded in `mobile/THIRD_PARTY_NOTICES.md` and
[Decision 025](decisions/025-paseo-provider-control-alignment.md). The real
server-wide Android Emulator matrix passed for dedicated Codex and Claude
agents, including selection, native session usage, stale-mutation rejection,
state isolation, and a retained-history `New context` divider. Full Flutter
tests, analyze, debug/profile APK builds, and focused Python suites pass. The
full non-blackbox Python run passed 6657 tests; its sole unrelated two-worker
workflow smoke race passed immediately when rerun in isolation. See
[the acceptance record](history/provider-control-plane-acceptance-20260812.md).

## LAN Network Awareness And Recovery — Implemented, Physical Gate Pending

The Android LAN reliability gap is now closed at source/build level. The app
uses coarse, non-identifying network evidence to warn before a LAN claim and
to explain reconnecting LAN routes; it preserves the paired profile, exposes
Retry plus authenticated Diagnostics, and lets phone-hotspot users continue
explicitly. Terminal WebSockets now use a 15-second client ping interval so a
silent Wi-Fi half-open enters the existing cursor-resume path without input
replay. Computer-side onboarding and the mobile README cover same-network,
hotspot, guest/client isolation, VPN, firewall, and DHCP address changes.

Verification on 2026-08-02: Flutter analyze passed; the full Flutter suite
passed `736` tests with `1` existing skip; LAN/mobile Python CLI selection
passed `34` tests with `52` deselected; and a debug APK built successfully.
The APK is 179,363,174 bytes with SHA-256
`0d960b2aabcf8834b7ccc50aa7189ad66fc4d3fd0b36d3f6fe93a43b5b7ae30c`,
and packaged-permission inspection includes `ACCESS_NETWORK_STATE`.

Release acceptance remains gated on the physical Android Wi-Fi/hotspot/
guest-isolation/VPN/DHCP-change matrix recorded in
[the LAN topic](topics/lan-network-awareness-and-recovery.md).

## Public Relay Packages A-D — In Progress

Current phase: local implementation and pre-deployment verification are
complete enough to prepare the Alibaba staging host. One-time host activation,
durable phone reconnect proof, multiplexed AEAD unary/Terminal/notification/
file traffic, managed outbound host connector, Relay QR pairing, shared Flutter
socket ownership, bounded flow control, transient reconnect, and 25 MiB file
boundary coverage are present on the dedicated Relay branch.

Last verified locally: Relay-focused Python `108 passed`; full Flutter
`685 passed`; full Python `5671 passed, 2 skipped`; Flutter analyze and debug
APK build passed; 50-host/50-phone load smoke passed with no canary
persistence; APK is `8.3.0+8030000`, SHA-256
`1a954db32b9bac51536c069cc4a67ece3763f22561181c59e035ee2ac9c956e0`.

Next target: commit the clean local checkpoint, deploy it behind a dedicated
Alibaba nginx SNI without changing RustDesk/ZeroTier listeners, then execute
the no-`adb reverse` public WSS Android Emulator matrix. Public Relay remains
unaccepted until that evidence and the required soak/no-storage audit pass.

Blocked by: DNS `relay.seemlab.top -> 47.120.71.142` and SSH public-key access
to the ECS deployment account. These are not needed for the remaining local
checks.

## Realtime Recovery Package A — In Progress (review correction, 2026-07-10)

The prior `6be6a172` completion claim and its AVD record are not acceptance
evidence: reviewer found an SSE keepalive path that scanned every registered
project, a shared completion/invalidation journal, missing persistent SSE
resume, and missing non-native-provider fallback/cache lifecycle gates. This
correction is in progress until fresh source tests and a same-APK real AVD
audit prove zero internal ProjectView/conversation requests during 180 seconds
idle, durable offline completion recovery, resume/resync, safe fallback, and
stale snapshot recovery. The deleted send-refresh scheduler must remain marked
unproven until those gates complete.

Product boundary: this package does not provide unconditional global background
completion notifications for every mounted project. Completion events are
authoritative only after explicit ProjectView/conversation observation, plus
selected-target native invalidation watches. Kimi/OpenCode/unknown provider
structured fallback remains an explicit conversation-load path unless a later
provider-specific fingerprint source is added.

## Current Phase

Current execution target added 2026-07-04: land the per-agent Terminal mode
described in
[topics/agent-terminal-mode-remote-pane-control.md](topics/agent-terminal-mode-remote-pane-control.md).
This package should be implemented in `/home/bfly/yunwei/ccb_source` only. It
must promote the existing gateway `xterm` terminal transport into a selected
agent `Chat / Terminal` mode, complete direct pane-control input coverage, and
produce real Android Emulator screenshots/recording before review acceptance.
`ccb_mobile` remains a retired implementation surface and must not receive app
or gateway code changes.

Phase 4F: Pane live-output smoothness implementation.

Manual real-project AVD testing exposed the prior product-contract mismatch:
the mobile composer and selected-agent timeline could behave like a CCB ask/job
client instead of a pane-equivalent renderer and input surface. That mismatch is
now closed at smoke level by pane-backed native send/reply, multi-project
native send, desktop-origin refresh, long-history backfill, file/artifact, and
recovery smokes on disposable real projects.

The current phase is no longer architecture extraction. Product-grade local
AVD validation proved the major pane-backed contract, and manual review then
exposed a finer conversation-smoothness gap: provider-native transcript is
good final history, but command/status output and in-progress agent work need
lower-latency selected-pane output streaming.

The first app-side smoothness package is now implemented: phone sends use pane
input in paired gateway mode, `Send Tab` is available, explicit/gesture refresh
replaces blind polling, terminal output is now used as activity/status input
rather than default chat-bubble content, and `Working` is visible during active
pane-backed sends. Real AVD
evidence now covers server-wide `test_ccb2` opening, native-pane send/reply,
`Working` timing, `/status` marker visibility, and scroll-away explicit-refresh
`New messages` behavior, and a strict `180 s` idle request audit with zero
conversation/history requests, adb-reverse recovery timing, a 40-line
long-output shape smoke, a 120-line long-output command smoke with scenario
device metrics, a strict 80-line live-marker command smoke with sustained
device metrics, and a 200-line high-volume native transcript reconciliation
smoke. Release APK reverse-recovery now also has current local AVD
device-health evidence; broader `1000`-line/repeated long-output and physical
Tailnet/VPN recovery gates remain open.
Evidence:
[history/local-avd-pane-live-output-smoke-20260628.md](history/local-avd-pane-live-output-smoke-20260628.md),
[history/local-avd-native-pane-repeat-timing-20260629.json](history/local-avd-native-pane-repeat-timing-20260629.json),
[history/local-avd-native-status-command-20260629.json](history/local-avd-native-status-command-20260629.json),
[history/local-avd-scroll-away-desktop-origin-20260629.json](history/local-avd-scroll-away-desktop-origin-20260629.json),
[history/local-avd-idle-request-20260629.json](history/local-avd-idle-request-20260629.json),
[history/local-avd-reverse-recovery-timing-20260629.json](history/local-avd-reverse-recovery-timing-20260629.json),
and
[history/local-avd-native-long-output-live-turn-20260629.json](history/local-avd-native-long-output-live-turn-20260629.json),
plus
[history/local-avd-native-long-output-120-device-metrics-20260629.json](history/local-avd-native-long-output-120-device-metrics-20260629.json).
The stricter current live-marker evidence is
[history/local-avd-native-long-output-strict-80-live-device-metrics-20260629.json](history/local-avd-native-long-output-strict-80-live-device-metrics-20260629.json).
Current high-volume transcript reconciliation evidence is
[history/local-avd-native-high-volume-200-device-metrics-20260629.json](history/local-avd-native-high-volume-200-device-metrics-20260629.json).
Current status-only transcript evidence is
[history/local-avd-status-only-transcript-200-20260629.json](history/local-avd-status-only-transcript-200-20260629.json).
Current release recovery device-health evidence is
[history/local-avd-release-reverse-recovery-current-20260629.json](history/local-avd-release-reverse-recovery-current-20260629.json).

Manual review on 2026-06-29 then exposed a latency refinement: local/emulator
gateway request latency is tens of milliseconds, while the app-side
active-send conversation follow loop has a one-second first scheduled refresh.
The next package should reduce only the active-send follow-up delay, add timing
instrumentation, and preserve the accepted zero-idle-request behavior.

Current worktree progress on 2026-06-29 starts that package: the app-side
conversation refresh scheduler now begins its explicit active-send follow loop
at `250 ms`, then backs off through `750 ms`, `1500 ms`, `3 s`, `5 s`,
`10 s`, `20 s`, `40 s`, `80 s`, `160 s`, `320 s`, `640 s`, and `900 s`.
Focused scheduler/chat tests prove the default first delay is within the
`300 ms` budget and that no refresh timer is armed until an explicit schedule
call. The worktree also marks pane-backed sends as
`Working` immediately when the optimistic local turn is accepted, then clears
that status if the pane path does not schedule a follow-up refresh. The real
AVD harness now also supports `--native-pane-repeat N`: each sequential
native-pane run keeps its timing payload, and the harness emits p50/p95
summaries plus missing-Working counts so the strict gate can be evaluated from
machine-readable evidence instead of screenshots.

Earlier partial real-AVD evidence for Package A: current worktree debug APK
`app/build/app/outputs/flutter-apk/app-debug.apk`
(`sha256 4786d3e9717ba7200e17b681b0e7809e627d8af2a5752f8c746c2af9b86d09cc`)
was installed on `emulator-5554` and exercised through a server-wide real
gateway at `127.0.0.1:19255` against disposable
`/home/bfly/yunwei/test_ccb2/.../test_ccb2_alpha`. Final passing timing JSON
reported `send_to_local_bubble_ms=227`, `send_to_working_ms=null`,
`send_to_first_feedback_ms=1044`, `first_feedback_kind=expected_reply`, and
`send_to_expected_reply_ms=5247`; source-side evidence had
`prompt_contains_ccb_req_id=false`, `prompt_contains_mobile_gateway=false`,
`jobs_matches=[]`, `user_match_count=1`, and `reply_match_count=1`. This is
not completion evidence, and it has been superseded by the repeat run below:
it proved the native-pane send/reply path and timing instrumentation, but also
showed the real path did not capture a visible `Working` frame before final
feedback. The strict real-AVD packet from
[goal-low-latency-conversation.md](goal-low-latency-conversation.md) still
needs multi-action timing, idle request counts, long-output behavior, scroll
stability, and device metrics.

Current harness-only verification after that repeat support: Python smoke
helper tests pass `41/41`, including multi-marker timing extraction,
p50/p95 summary generation, and `--native-pane-repeat` argument parsing.

Current repeat real-AVD evidence:
[history/local-avd-native-pane-repeat-timing-20260629.json](history/local-avd-native-pane-repeat-timing-20260629.json)
now reflects the follow-up run after making `Working` take priority over
`Refreshing` while a pane-backed send is awaiting reply. It ran
`--native-pane-repeat 2` on `emulator-5554` through server-wide gateway
`127.0.0.1:19302` from clean source head `7e436f7e`. The repeated timing
summary was: local bubble p50 `133 ms` / p95 `186 ms`, `Working` p50 `138 ms` /
p95 `188 ms`, first visible feedback p50 `138 ms` / p95 `188 ms`, final
expected reply p50 `3206 ms` / p95 `3224 ms`, and `Working` captured `2/2`.
Both cases still proved no `CCB_REQ_ID`, no `mobile_gateway`, no jobs matches,
one native user match, and one native reply match. This closes the Package A
real-path Working visibility gate; broader streaming, long-output, idle,
recovery, and device-metrics gates remained open at this checkpoint.

Provider-command visibility now has its own real-AVD evidence:
[history/local-avd-native-status-command-20260629.json](history/local-avd-native-status-command-20260629.json)
sent `/status` from the phone into disposable `test_ccb2_alpha/mobile_probe`
through server-wide gateway `127.0.0.1:19303`; the selected-agent timeline
rendered non-local marker `Weekly limit:` in `562 ms`. This closes the
local-AVD `/status` visibility gate while leaving long-output streaming,
scroll-away behavior, idle request-count, recovery, and device-metrics gates
open at this checkpoint.

Scroll-away/new-output behavior now has targeted real-AVD evidence:
[history/local-avd-scroll-away-desktop-origin-20260629.json](history/local-avd-scroll-away-desktop-origin-20260629.json)
seeded `56` native-history turns, dragged the selected-agent timeline away from
the end, injected a desktop-origin pane marker, verified the idle window did not
blind-refresh it, then used explicit refresh to show `New messages`; tapping the
affordance returned to latest and rendered the marker. This closes the explicit
refresh scroll-away gate; long-running live output, idle request-count,
recovery, and device metrics remained open at this checkpoint.

Strict idle request-count evidence now exists:
[history/local-avd-idle-request-20260629.json](history/local-avd-idle-request-20260629.json)
opened disposable `test_ccb2_alpha/mobile_probe` on `emulator-5554` through
server-wide gateway `127.0.0.1:19306` and held the selected-agent page idle for
`180 s`. The reset idle audit window observed `0` total requests, `0`
conversation requests, `0` terminal-history requests, and `0.0`
conversation/history requests per minute. Device sampling collected `7`
samples with PSS delta `-582 KB`, wake locks `size=0`,
`mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, and no skipped-frame storm.
This closes the strict idle no-blind-polling gate; long-running live output,
high-volume long-output device metrics, and broader repeated-scenario device
metrics remain open.

Reverse-loss recovery timing now has current real-AVD evidence:
[history/local-avd-reverse-recovery-timing-20260629.json](history/local-avd-reverse-recovery-timing-20260629.json)
removed and restored `adb reverse` while exercising both the server-wide
project list and an already-open selected-agent conversation through gateway
`127.0.0.1:19309`. Project-list retry recovered in `1234 ms`; opened
conversation retry recovered in `1099 ms`; the selected-agent composer remained
present after recovery; and the route asserted no visible `CCB_REQ_ID`,
`mobile_gateway`, or `completion_snapshot` labels. This closes the recovery
timing gate. Current release recovery device-health evidence is tracked below.

Release reverse-recovery device-health evidence now exists:
[history/local-avd-release-reverse-recovery-current-20260629.json](history/local-avd-release-reverse-recovery-current-20260629.json)
installed release APK `app/build/app/outputs/flutter-apk/app-release.apk`,
opened disposable `test_ccb2_alpha/mobile_probe` through gateway
`127.0.0.1:19316`, removed `adb reverse`, observed the selected-agent
connection failure, restored `adb reverse`, and rendered marker
`Native reverse recovery restored 1782719941` after explicit refresh. Recovery
elapsed `14230.173 ms`; device metrics collected `7` samples, PSS delta
`-3448 KB`, wake locks `size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM
marker, no skipped-frame storm, and no warnings. This closes the local AVD
release recovery device-health gate; physical Tailnet/VPN recovery remains
separate.

Long-output shape now has current real-AVD evidence:
[history/local-avd-native-long-output-live-turn-20260629.json](history/local-avd-native-long-output-live-turn-20260629.json)
sent a 40-line native Codex pane prompt through gateway `127.0.0.1:19310`. The
selected-agent surface rendered the final marker inside exactly one live
terminal-output item (`live_terminal_output_expected_item_count=1`), captured
`Working` in `155 ms`, and showed no internal labels. This closes only the
small shape proof that long terminal output can update one live turn; the
long-duration/high-volume provider execution and device-health gates remain
open.

120-line long-output command smoke now has current real-AVD evidence:
[history/local-avd-native-long-output-120-device-metrics-20260629.json](history/local-avd-native-long-output-120-device-metrics-20260629.json)
sent a longer native Codex pane prompt through gateway `127.0.0.1:19313`.
Device metrics were collected from the integration test's ready-to-send marker
instead of from app cold start. It reported local bubble `273 ms`, `Working`
`281 ms`, first feedback `281 ms`, final marker `1056 ms`, one final
expected-reply item, one live terminal-output item, screenshot/UI dump artifact
paths, no FATAL/ANR/OOM, and no skipped-frame storm. This is still not final
completion evidence: the marker was in the final native reply rather than in
the live terminal-output item, the device window had only one valid memory
sample, and global wake-lock warnings remain to be interpreted in a longer
scenario.

Strict 80-line live-marker long-output evidence now exists:
[history/local-avd-native-long-output-strict-80-live-device-metrics-20260629.json](history/local-avd-native-long-output-strict-80-live-device-metrics-20260629.json)
used a marker that was not present verbatim in the user prompt, required that
marker inside the live `Terminal output` item before emitting timing evidence,
and collected device metrics throughout the longer wait. It reported local
bubble `259 ms`, `Working` `263 ms`, first feedback `263 ms`, final marker
`205237 ms`, one final expected-reply item, one live terminal-output item
containing the marker, `88` metric samples, PSS delta `-1481 KB`, wake locks
`size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM, no skipped-frame storm,
and no warnings. This upgrades the long-output evidence lane, but the original
`1000`-line/repeated-run gate remains open.

200-line high-volume native transcript reconciliation now has current
real-AVD evidence:
[history/local-avd-native-high-volume-200-device-metrics-20260629.json](history/local-avd-native-high-volume-200-device-metrics-20260629.json)
sent a prompt that required exactly `200` prefixed lines through gateway
`127.0.0.1:19318` after the active-send refresh schedule was extended through
`80 s`, `160 s`, and `320 s`. The selected-agent model contained all `200`
prefixed lines, local bubble appeared in `162 ms`, `Working` in `167 ms`,
first feedback in `167 ms`, and final transcript reconciliation in
`80313 ms`. The UI model stayed compact with `3` non-local items against the
`8` item cap. Device metrics collected `35` samples, PSS delta `11060 KB`,
wake locks `size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, no
skipped-frame storm, and no warnings. This closes the intermediate
high-volume transcript reconciliation gate, but the original `1000`-line and
repeated high-volume p50/p95 gates remain open.

Status-only terminal-stream behavior now has current real-AVD evidence:
[history/local-avd-status-only-transcript-200-20260629.json](history/local-avd-status-only-transcript-200-20260629.json)
re-ran the 200-line native Codex pane prompt through gateway
`127.0.0.1:19323` after changing terminal stream output to status-only. The
selected-agent model contained all `200` prefixed lines from the
provider/native transcript path, while `live_terminal_output_item_count=0`.
Local bubble appeared in `238 ms`, `Working` in `244 ms`, first feedback in
`244 ms`, final transcript reconciliation in `80336 ms`, and the UI stayed
compact with `4` non-local items against the `8` item cap. This is now the
authoritative local AVD evidence for the product rule that tmux/terminal stream
is an activity/status source, not a normal conversation-bubble source.

Older evidence from the former message-submit route remains useful for gateway
routing, attachments, downloads, and server-wide registry plumbing, but only
real pane-backed AVD evidence can close default mobile chat acceptance gates.

Authority:

- [Decision 015](decisions/015-pane-backed-chat-input.md): default composer
  sends must be pane-backed and must not use the ask/message route.
- [Decision 016](decisions/016-pane-composer-send-primitive.md): current alpha
  primitive is paste plus Enter against the selected CCB-validated pane.
- [topics/agent-native-conversation-and-input-correction.md](topics/agent-native-conversation-and-input-correction.md)
  is the active correction plan.
- [topics/pane-live-output-and-smooth-conversation.md](topics/pane-live-output-and-smooth-conversation.md)
  is the active conversation-smoothness plan.

## Active TODO

1. Older-history pagination: profile-mode `200` turn mixed native history and
   release-mode `200` turn long-history frame/memory/request pressure now have
   clean AVD evidence. Keep only regression follow-up for this lane unless new
   real-device behavior regresses.
2. File and artifact transfer: profile-mode live provider text artifact
   download, profile-mode `8 MiB` background/resume artifact download,
   profile-mode server-wide file/image upload plus hash download, and
   profile-mode `24 MiB` user-origin upload/download loopback plus
   release-mode `8 MiB` and `24 MiB` native artifact download performance
   plus release-mode `24 MiB` user-origin upload/download through the real
   Android system picker now have clean AVD evidence. Keep only
   release-persistence/regression follow-up unless product requirements expand
   the transfer envelope.
3. Refresh and recovery: profile-mode idle request-rate/power smoke,
   profile-mode 30-minute idle soak, release-mode 180-second idle
   request-rate/power smoke, release-mode 30-minute idle soak, scrolled-away
   explicit-refresh/new-message smoke, and release-mode adb-reverse recovery
   now have clean AVD evidence. Keep only regression follow-up for this lane
   unless Tailnet/VPN or physical-device recovery expands the product gate.
4. Rendering, performance, and conversation smoothness: release long-history,
   file-download performance, idle/power pressure, and local adb-reverse
   recovery now have non-Flutter-Driver evidence. Current app-side smoothness
   work proves real project listing/opening, pane-backed send, terminal-output
   rendering, and non-stuck `Working` on AVD. Next, land the low-latency
   active-send follow-loop from
   [goal-low-latency-conversation.md](goal-low-latency-conversation.md) and
   [topics/pane-live-output-and-smooth-conversation.md](topics/pane-live-output-and-smooth-conversation.md):
   first refresh attempt within `300 ms`, immediate `Working` on accepted pane
   sends in widget coverage, and real native-pane repeat timing now have
   current-worktree evidence. `/status` provider-command visibility also has
   current real-AVD evidence, desktop-origin scroll-away/new-message behavior
   has current real-AVD evidence, strict `180 s` idle request-count proof has
   current real-AVD evidence, and adb-reverse recovery timing has current
   real-AVD evidence. Release APK reverse-recovery also has current
   device-health evidence. A 40-line long-output shape smoke, a 120-line
   command smoke with screenshot/UI dump paths, a strict 80-line live-marker
   smoke with sustained device metrics, and a 200-line high-volume native
   transcript reconciliation smoke also have current real-AVD evidence. Next
   extend the real AVD packet to the original `1000`-line or repeated
   high-volume target; physical Tailnet/VPN recovery remains a separate
   non-local-AVD gate.
5. Human handoff: keep emulator validation on disposable real
   `/home/bfly/yunwei/test_ccb2` projects and leave the app on a known real
   server-wide gateway state before manual review. Use
   [topics/app-comprehensive-test-program.md](topics/app-comprehensive-test-program.md)
   as the top-level real-AVD execution program, use
   [topics/app-deep-test-compass-plan.md](topics/app-deep-test-compass-plan.md)
   as the lane-by-lane detailed test compass, then use
   [topics/app-stress-and-performance-test-plan.md](topics/app-stress-and-performance-test-plan.md)
   and
   [topics/app-local-avd-full-acceptance-matrix.md](topics/app-local-avd-full-acceptance-matrix.md)
   for the staged low-disruption-to-stress validation sequence and concrete
   local AVD acceptance checklist. Use
   [topics/app-real-avd-stress-casebook.md](topics/app-real-avd-stress-casebook.md)
   for named case ids and required per-case artifacts. Use
   [topics/local-avd-real-project-test-runbook.md](topics/local-avd-real-project-test-runbook.md)
   as the execution script before handing the emulator to a human reviewer:
   it requires verified pane-backed `test_ccb2` fixtures before any send/file
   stress can count.

## Done This Phase

- Server-wide mobile install/project-registry work exists and remains the
  foundation for listing multiple CCB projects from one server gateway.
- App architecture cleanup reduced `ProjectHomeScreen` into focused helpers,
  route actions, scaffold host, pairing flow/form, runtime activation, focus,
  refresh, terminal navigation, notification outcome, and shell/sidebar state.
- Real pane-backed native send/reply AVD smoke now covers one project/agent and
  a multi-project/multi-agent lane with no `CCB_REQ_ID`, no `mobile_gateway`,
  and no jobs matches.
- Current-head native pane multi-project rerun on 2026-06-27 passed from app
  head `ba445c2` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native` at `7e436f7e`. The
  server-wide gateway listed `45` mounted projects, selected fresh disposable
  `test_ccb2_alpha/mobile_probe` and `test_ccb2_beta/mobile_peer`, sent
  ordinary phone input into both real panes, and received exact replies
  `CCB_MOBILE_NATIVE_ALPHA_OK_20260627022830` and
  `CCB_MOBILE_NATIVE_BETA_OK_20260627022830`. Both source-side transcript
  checks had `jobs_matches: []`, no `CCB_REQ_ID`, no `mobile_gateway`, one
  native user match, and one native reply match. Evidence:
  [history/local-avd-native-pane-multi-current-smoke-20260627.json](history/local-avd-native-pane-multi-current-smoke-20260627.json).
- Desktop-origin explicit-refresh AVD smoke now proves direct desktop tmux pane
  input can appear in the phone selected-agent timeline after an app refresh
  without reopening the project.
- Long-history provider-native backfill AVD smoke now proves the app can load
  older selected-agent transcript pages upward from a real server-wide gateway
  using a controlled native transcript fixture, without seeding through
  `ccb ask`.
- Native selected-agent file/artifact AVD smoke now proves text attachment
  send/download, image send/preview, backend artifact text/image download
  through provider-native transcript links, and on-device SHA256 checks for
  the saved Android files on a real server-wide gateway. Later accepted
  evidence now covers live provider artifact creation, rejection, restart,
  background/resume, and release download performance.
- Reverse-loss/recovery AVD smoke now proves both the server-wide project list
  and selected-agent explicit refresh fail visibly when the Android Emulator
  loses its `adb reverse` gateway path and recover after the mapping is
  restored.
- Current-head release reverse-loss/recovery rerun on 2026-06-27 passed from
  app head `7666c69` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native` at `7e436f7e`. The
  release APK opened disposable `test_ccb2_alpha/mobile_probe`; after
  `adb reverse --remove tcp:19244`, explicit refresh showed
  `SocketException: Connection refused`; after restoring
  `tcp:19244 tcp:19244`, the same selected-agent page rendered
  `Native reverse recovery restored 1782527686`. Device metrics collected `3`
  samples, PSS delta was `1543 KB` (`1.7%`), wake locks were
  `Wake Locks: size=0` / `mWakeLockSummary=0x0`, gfxinfo reported `16`
  frames with `1` legacy janky frame (`6.25%`), and logcat had no
  FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-release-reverse-recovery-current-smoke-20260627.json](history/local-avd-release-reverse-recovery-current-smoke-20260627.json).
- Current-head clean release idle request/power rerun on 2026-06-27 passed
  after app commit `03ede70` limited selected-agent timeline network refresh
  to real drag/overscroll gestures instead of programmatic
  `UserScrollNotification`s. The release APK opened disposable
  `test_ccb2_alpha/mobile_probe` through the real server-wide gateway from
  clean app head `03ede70` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native` at `7e436f7e`, stayed
  untouched for `180` seconds, and the request proxy observed `0` total
  gateway requests, `0` conversation requests, and `0` terminal-history
  requests. Device metrics collected `7` samples, PSS delta was `1403 KB`
  (`1.54%`), wake locks were `Wake Locks: size=0` /
  `mWakeLockSummary=0x0`, gfxinfo reported `6` rendered frames with `1`
  legacy janky frame, and logcat had no FATAL/ANR/OOM or skipped-frame
  markers. Evidence:
  [history/local-avd-release-idle-current-clean-smoke-20260627.json](history/local-avd-release-idle-current-clean-smoke-20260627.json).
- Gateway-restart AVD smoke now proves both the server-wide project list and
  selected-agent explicit refresh fail visibly when the real server-wide
  mobile gateway process is stopped, then recover after the gateway is
  restarted on the same loopback port and state directory without clearing app
  data or re-pairing.
- Project-ccbd restart AVD smoke now proves selected-agent explicit refresh
  fails visibly when the opened test project's ccbd is stopped, then recovers
  after ccbd restart and explicit refresh retry on the same open project
  without clearing app data or re-pairing.
- Idle request-rate AVD smoke now proves an open selected-agent page does not
  run a blind conversation/terminal-history polling loop while untouched:
  the real gateway proxy counted `0` conversation/terminal-history requests
  over a 180-second idle window, followed by exactly one manual refresh
  request after the audit window.
- Idle metrics AVD smoke now extends that proof with device metrics from the
  same 180-second real AVD window: seven meminfo/top samples, no PSS growth,
  `Wake Locks: size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM, and no
  request-count drift before manual refresh.
- Background/resume AVD smoke now proves an open real selected-agent page can
  survive Android HOME/background and foreground resume on a real server-wide
  gateway, keep the selected-agent workspace/composer visible, avoid
  forbidden ask/provenance labels, and complete explicit selected-agent
  refresh after resume.
- Background reverse-recovery AVD smoke now proves an open real selected-agent
  page can survive Android HOME/background while the emulator loses
  `adb reverse`, then recover after the reverse mapping is restored and the
  app is foregrounded, without losing the selected-agent workspace/composer or
  forbidden-label hygiene.
- Background file-download AVD smoke now proves an `8 MiB` backend artifact
  download can be triggered from a real selected-agent timeline, survive
  Android HOME/foreground resume, save under Android app documents, and match
  the expected SHA256.
- Replay-guard AVD smoke now proves a failed selected-agent send with an
  attachment remains retryable after `adb reverse` loss, then explicit Retry
  reaches the real selected pane exactly once with no `CCB_REQ_ID` or
  `mobile_gateway` pollution in source-side native transcript evidence.
- Revoke/re-pair AVD smoke now proves a revoked paired device fails closed
  with HTTP `401 device token revoked`, then the app can claim a new pairing
  code through Connection Details and recover selected-agent refresh without
  clearing app data.
- Profile scrolled-away desktop-origin sync smoke on 2026-06-27 passed from
  clean app head `dc1e44e` and clean source head `7e436f7e` on Android
  Emulator `emulator-5554`: the profile APK opened real
  `test_ccb2_alpha/mobile_probe`, loaded `56` mixed provider-native backfill
  turns, scrolled away from the newest turn, accepted direct desktop pane
  input into tmux pane `%2`, then explicit refresh exposed the new-message
  affordance and jumped to `DESKTOP_ORIGIN_SYNC_MARKER_20260626221442`.
  Source-side evidence had `jobs_matches=[]`, no `CCB_REQ_ID`, no
  `mobile_gateway`, and one native user match. Source commit `7e436f7e`
  fixed cross-thread native transcript ordering by record timestamp so latest
  pages no longer hide newer pane input behind older backfill threads.
  Evidence:
  [history/local-avd-profile-scrolled-desktop-sync-smoke-20260627.json](history/local-avd-profile-scrolled-desktop-sync-smoke-20260627.json).
- Profile 30-minute idle soak on 2026-06-27 passed from clean app head
  `7898851` and clean source head `7e436f7e` on Android Emulator
  `emulator-5554`: the profile APK opened a real server-wide selected-agent
  page on disposable `test_ccb2` projects and stayed untouched for `1800`
  seconds. The request proxy observed `0` total idle requests, `0`
  conversation requests, and `0` terminal-history requests; the final proxy
  count was exactly one explicit post-window selected-agent refresh. Device
  metrics collected `31` samples, PSS grew by `767 KB` (`0.52%`), wake locks
  were `Wake Locks: size=0` / `mWakeLockSummary=0x0`, and logcat had no
  FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-profile-30m-idle-soak-20260627.json](history/local-avd-profile-30m-idle-soak-20260627.json).
- Release APK project-list/open-project smoke on 2026-06-27 passed from clean
  app head `44540aa` and clean source head `7e436f7e` on Android Emulator
  `emulator-5554`: the release APK was seeded with the server-wide paired
  profile, installed, and launched without Flutter Driver; ADB UIAutomator
  observed the real gateway project list containing fresh
  `test_ccb2_alpha` and `test_ccb2_beta`, tapped `test_ccb2_alpha`, and then
  observed the opened project page with `mobile_probe`, `mobile_peer`,
  `Refresh conversation`, `Attach file`, and `Send message`. Evidence:
  [history/local-avd-release-project-list-smoke-20260627.json](history/local-avd-release-project-list-smoke-20260627.json).
- Release APK 180-second idle request-rate/power smoke on 2026-06-27 passed
  from clean app head `6c3eb16` and clean source head `7e436f7e` on Android
  Emulator `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway and stayed
  untouched for `180` seconds. The request proxy observed `0` total gateway
  requests, `0` conversation requests, and `0` terminal-history requests;
  device metrics collected `7` samples, PSS delta was `-1100 KB`
  (`-1.18%`), wake locks were `Wake Locks: size=0` /
  `mWakeLockSummary=0x0`, and logcat had no FATAL/ANR/OOM or skipped-frame
  markers. Evidence:
  [history/local-avd-release-idle-request-smoke-20260627.json](history/local-avd-release-idle-request-smoke-20260627.json).
- Release APK 30-minute idle request-rate/power soak on 2026-06-27 passed
  from clean app head `f2acc00` and clean source head `7e436f7e` on Android
  Emulator `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway and stayed
  untouched for `1800` seconds. The request proxy observed `0` total gateway
  requests, `0` conversation requests, and `0` terminal-history requests;
  device metrics collected `31` samples, PSS delta was `485 KB` (`0.53%`),
  wake locks were `Wake Locks: size=0` / `mWakeLockSummary=0x0`, and logcat
  had no FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-release-30m-idle-soak-20260627.json](history/local-avd-release-30m-idle-soak-20260627.json).
- Release APK 200-turn long-history pressure smoke on 2026-06-27 passed from
  clean app head `7c8be1e` and clean source head `7e436f7e` on Android
  Emulator `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway, displayed
  the latest provider-native marker in about `2.0s`, scrolled to the oldest
  native marker after `85` ADB UIAutomator drags and about `226.6s`, and
  rendered mixed Markdown headings/tables/code plus document/image artifact
  links from the native transcript fixture. The request proxy observed `9`
  selected-agent conversation requests, `0` terminal-history requests, and
  `2.379` requests/minute during the active scroll window; device metrics
  collected `23` samples, PSS delta was `7830 KB` (`8.0%`), wake locks were
  `Wake Locks: size=0` / `mWakeLockSummary=0x0`, gfxinfo reported `182`
  frames with `5` legacy janky frames (`2.75%`), and logcat had no
  FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-release-long-history-smoke-20260627.json](history/local-avd-release-long-history-smoke-20260627.json).
- Release APK 8 MiB native artifact download performance smoke on 2026-06-27
  passed from clean app head `6a1cfa1` and clean source head `7e436f7e` on
  Android Emulator `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway, rendered a
  provider-native artifact chip `native-artifact-...txt (8.0 MB)`, tapped it
  through ADB UIAutomator, and showed `Saved ...` in about `4.38s`. The
  gateway proxy observed exactly one file route request, returned
  `8,388,608` bytes in `22.012ms`, and the response SHA256 matched the seeded
  artifact. Device metrics collected `3` samples, PSS delta was `11485 KB`
  (`12.62%`) over the short active download/settle window, wake locks were
  `Wake Locks: size=0` / `mWakeLockSummary=0x0` after settle, gfxinfo
  reported `16` frames with `1` legacy janky frame (`6.25%`), and logcat had
  no FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-release-file-download-smoke-20260627.json](history/local-avd-release-file-download-smoke-20260627.json).
- Release APK 24 MiB native artifact download hardening smoke on 2026-06-27
  passed from clean app head `84a48d3` and clean source head `7e436f7e` on
  Android Emulator `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway, rendered a
  provider-native artifact chip `native-artifact-...txt (24.0 MB)`, tapped it
  through ADB UIAutomator, and showed `Saved ...` in about `4.34s`. The
  gateway proxy observed exactly one file route request, returned
  `25,165,824` bytes in `100.227ms`, and the response SHA256
  `730cb977bd887e6ff2a8cfe096340802f079b08487bf1a7ce529a4b53f3deaca`
  matched the seeded artifact. Device metrics collected `3` samples, PSS
  delta was `16198 KB` (`17.47%`) over the active download/settle window,
  wake locks were `Wake Locks: size=0` / `mWakeLockSummary=0x0` after
  settle, gfxinfo reported `16` frames with `1` legacy janky frame
  (`6.25%`), and logcat had no FATAL/ANR/OOM or skipped-frame markers.
  Evidence:
  [history/local-avd-release-file-download-24m-smoke-20260627.json](history/local-avd-release-file-download-24m-smoke-20260627.json).
- Profile-mode 24 MiB user-origin upload/download hardening smoke on
  2026-06-27 passed from clean app head `a507698` and clean source head
  `7e436f7e` on Android Emulator `emulator-5554`: the integration harness
  opened fresh real `test_ccb2_alpha` and `test_ccb2_beta` projects through
  the server-wide gateway, exercised the existing file/image/artifact matrix,
  then uploaded `beta-mobile_probe-upload-stress-1782524465097.txt`
  (`25,165,824` bytes) through the selected-agent composer on
  `test_ccb2_beta/mobile_probe`. The app downloaded the resulting
  conversation attachment back into Android app documents with matching
  SHA256 `8777fe43ae7b36771cb810d28af83f727ffae8595625f0b024cdd4b290ed7151`;
  the upload/download loop reported `6650ms` send-to-save latency and
  `1066ms` download saved-visible latency. The run ended with
  `01:32 +3: All tests passed!`, `9` SHA256-checked downloads, and no
  FATAL/ANR/OOM or skipped-frame markers in the raw log. Evidence:
  [history/local-avd-profile-upload-24m-smoke-20260627.json](history/local-avd-profile-upload-24m-smoke-20260627.json).
- Release APK 24 MiB user-origin upload/download through the Android system
  picker on 2026-06-27 passed from clean app head `f7e889c` and clean source
  head `7e436f7e` on Android Emulator `emulator-5554`: the release APK opened
  real `test_ccb2_alpha/mobile_probe` through the server-wide gateway, tapped
  Attach file, chose File, selected
  `ccb-mobile-release-upload-20260627020845-409688.txt` from Android
  DocumentsUI Recent files, uploaded `25,165,824` bytes through the composer,
  rendered the resulting conversation attachment, then downloaded it back with
  matching SHA256
  `f8ae4cfc47823f8e88523935ea6d79ed4ea0e20ee1dc4adafe7e3d07a3dc9d3e`.
  The run reported `22932.324ms` send-to-save latency, `10210.963ms`
  download saved-visible latency, one `POST /files` and one `GET /files/{id}`
  through the proxy, PSS delta `14860 KB` (`17.44%`), `Wake Locks: size=0`,
  `mWakeLockSummary=0x0`, and no FATAL/ANR/OOM or skipped-frame markers.
  Evidence:
  [history/local-avd-release-upload-24m-smoke-20260627.json](history/local-avd-release-upload-24m-smoke-20260627.json).
- Release APK adb-reverse recovery smoke on 2026-06-27 passed from clean app
  head `89274a0` and clean source head `7e436f7e` on Android Emulator
  `emulator-5554`: the release APK opened real
  `test_ccb2_alpha/mobile_probe` through the server-wide gateway
  `127.0.0.1:19220`; after `adb reverse --remove tcp:19220`, explicit
  `Refresh conversation` showed a visible
  `SocketException: Connection refused` failure; while disconnected, the
  harness seeded a new provider-native Codex rollout marker
  `Native reverse recovery restored 1782522959`; after restoring the reverse
  mapping, explicit refresh rendered that new marker from the backend. Device
  metrics collected `4` samples, PSS delta was `408 KB` (`0.43%`), wake
  locks were `Wake Locks: size=0` / `mWakeLockSummary=0x0`, gfxinfo reported
  `16` frames with `2` legacy janky frames (`12.50%`), and logcat had no
  FATAL/ANR/OOM or skipped-frame markers. Evidence:
  [history/local-avd-release-reverse-recovery-smoke-20260627.json](history/local-avd-release-reverse-recovery-smoke-20260627.json).
- Mixed-history backfill smoke on 2026-06-27 passed from clean app worktree
  `/tmp/ccb-mobile-avd-b611e8a` and clean source worktree
  `/tmp/ccb-source-agent-native-7fece763`: app head `b611e8a`, source head
  `7fece763`, gateway `127.0.0.1:19133`, provider `codex`, `200` seeded
  native turns, `7` older pages, `92` upward drags, and Flutter integration
  `00:50 +2: All tests passed`. The dataset included Markdown headings,
  tables, code blocks, duplicate short prompts, and document/image
  `ccb-artifact://` links. Later profile/release evidence closes the frame,
  memory, and scroll-position pressure gates. Evidence:
  [history/local-avd-mixed-history-backfill-smoke-20260627.json](history/local-avd-mixed-history-backfill-smoke-20260627.json).
- Live provider artifact smoke on 2026-06-27 passed from clean app worktree
  `/tmp/ccb-mobile-live-artifact-0ab8956-3740234` and clean source worktree
  `/tmp/ccb-source-live-artifact-ac2626ac-4084005`: app head `0ab8956`,
  source head `ac2626ac`, gateway `127.0.0.1:19136`, provider `codex`,
  real project `test_ccb2_alpha`, and Android Emulator `emulator-5554`.
  The live provider created
  `mobile-live-artifact-20260626180758-134252.txt` in the project root,
  gateway metadata registered it as `mobile-file-f14dc5b0831c07028df8d0a9`,
  and the app downloaded bytes with matching SHA256
  `c57f55752e52f9af4f7b29aeb9b4f9f7763f69f9234f6227c3a93fe6fd87d8d0`.
  Source-side evidence had `jobs_matches: []`, no `CCB_REQ_ID`, no
  `mobile_gateway`, one native user match, and one native reply match.
  Evidence:
  [history/local-avd-live-provider-artifact-smoke-20260627.json](history/local-avd-live-provider-artifact-smoke-20260627.json).
- Current-head live provider artifact rerun on 2026-06-27 passed from the
  normal app worktree at `bca7bfe` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native` at `7e436f7e`.
  The server-wide gateway listed `45` mounted projects, selected fresh
  disposable `test_ccb2_alpha/mobile_probe`, pasted the artifact request
  into the real pane `%2`, rendered
  `mobile-live-artifact-20260627022247-1021026.txt`, and Android downloaded
  `43` bytes with matching SHA256
  `c4538a11f377f669126e215a74baef6a9f207d9a76e254349571aedf8d5a4ad8`.
  Source-side evidence had `jobs_matches: []`, no `CCB_REQ_ID`, no
  `mobile_gateway`, two native user matches, and one native reply match; the
  Flutter integration also asserted no visible `CCB_REQ_ID`,
  `mobile_gateway`, or `completion_snapshot`. Evidence:
  [history/local-avd-live-provider-artifact-current-smoke-20260627.json](history/local-avd-live-provider-artifact-current-smoke-20260627.json).
- Profile live provider artifact smoke on 2026-06-27 passed from clean app
  worktree at `46fe77c` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`: source head `ac2626ac`,
  gateway `127.0.0.1:19161`, provider `codex`, real project
  `test_ccb2_alpha`, selected agent `mobile_probe`, and Android Emulator
  `emulator-5554`. The profile APK opened the real server-wide project,
  emitted a ready marker, the harness pasted the artifact prompt into the
  actual tmux pane `%2`, the app explicit-refresh loop rendered the
  provider-created Markdown artifact link, and Android downloaded
  `mobile-live-artifact-20260626210228-3590796.txt` with matching SHA256
  `49548f8b886e293c09dafbdf5b8f3e6db5dfd0637f0cf20d83a30acb1ab557c0`.
  Source-side evidence had `jobs_matches: []`, no `CCB_REQ_ID`, no
  `mobile_gateway`, two native user matches, and one native reply match.
  Evidence:
  [history/local-avd-profile-live-artifact-smoke-20260627.json](history/local-avd-profile-live-artifact-smoke-20260627.json).
- Profile background file-download smoke on 2026-06-27 passed from clean app
  worktree at `98dd216` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`: source head `ac2626ac`,
  gateway `127.0.0.1:19163`, provider `codex`, real project
  `test_ccb2_alpha`, selected agent `mobile_probe`, and Android Emulator
  `emulator-5554`. The profile APK opened the real server-wide project,
  rendered the `8 MiB` backend artifact
  `native-artifact-20260626211010-3935582.txt`, requested download, the
  harness sent Android HOME for `10` seconds and resumed `MainActivity`, and
  the saved Android app-storage file SHA256
  `729e50a8809539bdb9bb357a9eec0555fdb8bc955e8c307bf9e7a07691ea8f84`
  matched the seeded artifact. Evidence:
  [history/local-avd-profile-background-file-download-smoke-20260627.json](history/local-avd-profile-background-file-download-smoke-20260627.json).
- Profile idle request-rate/power smoke on 2026-06-27 passed from clean app
  worktree at `d84ae67` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`: source head `ac2626ac`,
  gateway `127.0.0.1:19166`, request proxy `127.0.0.1:19167`,
  provider `codex`, real project `test_ccb2_alpha`, selected agent
  `mobile_probe`, and Android Emulator `emulator-5554`. The profile APK
  opened the real server-wide selected-agent page and stayed untouched for a
  `180` second idle audit window. The request proxy counted `0`
  conversation/terminal-history requests during the idle window, then exactly
  one conversation request after the audit window for the explicit checkpoint
  refresh. Device metrics recorded `7` meminfo/top samples, PSS delta
  `-3548 KB`, `Wake Locks: size=0`, `mWakeLockSummary=0x0`, no skipped frames,
  and no FATAL/ANR/OOM logcat markers. Evidence:
  [history/local-avd-profile-idle-request-smoke-20260627.json](history/local-avd-profile-idle-request-smoke-20260627.json).
- Profile server-wide gateway file/image smoke on 2026-06-27 passed from
  clean app worktree at `168db3d` and clean source worktree
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`: source head `ac2626ac`,
  gateway `127.0.0.1:19174`, provider `codex`, disposable real projects
  `test_ccb2_alpha` and `test_ccb2_beta`, and Android Emulator
  `emulator-5554`. The profile APK listed real server-wide projects, opened
  selected agents, sent text+document and image attachments across
  `alpha/mobile_probe`, `alpha/mobile_peer`, and `beta/mobile_probe`,
  downloaded backend native artifact links, and verified `9` Android
  app-storage SHA256 values. The run ended with
  `01:32 +3: All tests passed!`. Evidence:
  [history/local-avd-profile-server-wide-gateway-smoke-20260627.json](history/local-avd-profile-server-wide-gateway-smoke-20260627.json).
- 10-minute idle/performance soak on 2026-06-27 passed against a real
  server-wide gateway `127.0.0.1:19137` and request proxy `127.0.0.1:19138`:
  app head `075dcf4`, source head `ac2626ac`, Android Emulator
  `emulator-5554`, real project `test_ccb2_alpha`, `600` idle seconds,
  `0` conversation/terminal-history requests during idle, exactly `1` manual
  refresh request after the audit window, `11` meminfo/top samples, PSS delta
  `24 KB`, `Wake Locks: size=0`, `mWakeLockSummary=0x0`, and no
  FATAL/ANR/OOM logcat markers. Evidence:
  [history/local-avd-idle-10m-soak-20260627.json](history/local-avd-idle-10m-soak-20260627.json).
- 30-minute idle/power soak on 2026-06-27 passed against a real server-wide
  gateway `127.0.0.1:19139` and request proxy `127.0.0.1:19140`: app head
  `07513c2`, source head `ac2626ac`, Android Emulator `emulator-5554`, real
  project `test_ccb2_alpha`, `1800` idle seconds, `0`
  conversation/terminal-history requests during idle, exactly `1` manual
  refresh request after the audit window, `16` meminfo/top samples, PSS delta
  `-732 KB`, `Wake Locks: size=0`, `mWakeLockSummary=0x0`, and no
  FATAL/ANR/OOM logcat markers. Evidence:
  [history/local-avd-idle-30m-soak-20260627.json](history/local-avd-idle-30m-soak-20260627.json).
- File download app-restart persistence smoke on 2026-06-27 passed against a
  real server-wide gateway `127.0.0.1:19142`: app head `57907ba`, source head
  `ac2626ac`, Android Emulator `emulator-5554`, real project
  `test_ccb2_alpha`, downloaded artifact
  `native-artifact-20260626191141-2937442.txt`, app force-stop returncode
  `0`, app restart returncode `0`, and post-restart sandbox file SHA256
  `bb6eff9d9703242eeeddf8fae1867f8a0688f88bc93e36861cc9f011bcb37fb5`
  matched the original download hash. Evidence:
  [history/local-avd-file-restart-smoke-20260627.json](history/local-avd-file-restart-smoke-20260627.json).
- Replay-restart AVD smoke on 2026-06-27 passed against a real server-wide
  gateway `127.0.0.1:19145`: app head `0b2715e`, source head `ac2626ac`,
  Android Emulator `emulator-5554`, real project `test_ccb2_alpha`, and
  selected agent `mobile_probe`. The app sent a failed selected-agent message
  with `replay-guard-attachment.txt` after `adb reverse` was removed, reached
  the failed-draft persistence marker, was force-stopped, restored the draft
  and attachment after restart, retried after `adb reverse` restore, and the
  source-side native transcript saw the exact prompt once and expected reply
  once with `jobs_matches: []`, no `CCB_REQ_ID`, and no `mobile_gateway`.
  Evidence:
  [history/local-avd-replay-restart-smoke-20260627.json](history/local-avd-replay-restart-smoke-20260627.json).
- Replay-gateway-restart AVD smoke on 2026-06-27 passed against a real
  server-wide gateway `127.0.0.1:19147`: app head `d6b4790`, source head
  `ac2626ac`, Android Emulator `emulator-5554`, real project
  `test_ccb2_alpha`, and selected agent `mobile_probe`. The app sent a failed
  selected-agent message with `replay-guard-attachment.txt` after the
  server-wide gateway process was stopped, reached the failed-draft
  persistence marker, was force-stopped, restored the draft and attachment
  after restart, retried after the gateway restarted on the same loopback port
  and state directory, and the source-side native transcript saw the exact
  prompt once and expected reply once with `jobs_matches: []`, no
  `CCB_REQ_ID`, and no `mobile_gateway`. Evidence:
  [history/local-avd-replay-gateway-restart-smoke-20260627.json](history/local-avd-replay-gateway-restart-smoke-20260627.json).
- Attachment rejection AVD smoke on 2026-06-27 passed against a real
  server-wide gateway `127.0.0.1:19151`: app head `d01c322`, source head
  `ac2626ac`, Android Emulator `emulator-5554`, real project
  `test_ccb2_alpha`, and selected agent `mobile_probe`. The app opened the
  real server-wide project, rejected unsupported `installer.exe` with
  `installer.exe is not a supported attachment type`, rejected oversized
  `too-large.pdf` with `too-large.pdf is larger than 25 MB`, created no
  attachment tray/draft, and kept `CCB_REQ_ID`, `mobile_gateway`, and
  `completion_snapshot` absent from the selected-agent UI. Evidence:
  [history/local-avd-attachment-rejection-smoke-20260627.json](history/local-avd-attachment-rejection-smoke-20260627.json).
- Profile APK mixed-history backfill smoke on 2026-06-27 passed against a
  real server-wide gateway `127.0.0.1:19153`: app head `cec4f9c`, source head
  `ac2626ac`, Android Emulator `emulator-5554`, real project
  `test_ccb2_alpha`, and selected agent `mobile_probe`. The app ran
  `integration_test/server_wide_gateway_smoke_test.dart` through
  `flutter drive --profile`, opened a provider-native `200` turn mixed
  Markdown/artifact transcript, rendered the latest turn in `116 ms`, loaded
  older selected-agent transcript content after `92` upward drags in
  `46405 ms`, and emitted `All tests passed.` Evidence:
  [history/local-avd-profile-backfill-smoke-20260627.json](history/local-avd-profile-backfill-smoke-20260627.json).

## Blockers

- No current blocker for C2-C4 smoke-level pane-equivalent chat evidence.
- Full local-AVD product acceptance has no current blocker in the accepted
  server-wide real-project smoke lanes. Remaining evidence is P1/P2
  hardening: final matrix consolidation, optional physical-device/Tailnet VPN
  recovery, and any expanded file-transfer stress beyond the accepted
  profile/release upload/download and artifact paths.
- Physical-device/Tailnet/VPN validation is currently environment-blocked,
  not app-blocked: on 2026-06-27 `adb devices -l` returned no attached
  devices after the AVD was intentionally shut down, and `tailscale` was not
  installed on this host. Do not mark the full remote-device goal complete
  until an attached phone plus Tailnet/VPN route can run the recovery and
  transfer lanes.
- Physical-device/Tailnet/VPN readiness now has an executable preflight:
  `tools/mobile_physical_tailnet_preflight.py`. It is read-only and checks
  physical Android attachment, Android boot completion, host Tailscale login,
  Tailscale Serve public HTTPS port/origin shape when `--gateway-url` is
  supplied, and optional Tailnet gateway `/v1/health` without installing software,
  saving tokens, changing ACL/grants, starting Funnel, or mutating gateway
  state. Current local run with Android SDK platform-tools in `PATH` returned
  `status: blocked` because no online Android device was attached and
  `tailscale` was not installed. Evidence:
  [history/physical-tailnet-preflight-blocked-20260627.json](history/physical-tailnet-preflight-blocked-20260627.json);
  runbook:
  [topics/physical-tailnet-device-validation-runbook.md](topics/physical-tailnet-device-validation-runbook.md).
- Fake/local demo replies and CCB ask/job history still must not be used to
  close any remaining real-backend acceptance gate.

## Next Commit Target

Prepare the physical-device/Tailnet handoff lane from the accepted local
real-AVD evidence. When hardware/network is available, run the preflight first:

```bash
PATH="/home/bfly/.local/share/android-sdk/platform-tools:$PATH" \
  tools/mobile_physical_tailnet_preflight.py \
  --gateway-url https://<ccb-host>.<tailnet>.ts.net:8787
```

Only after that returns `status: ok`, run the coherent physical-device/Tailnet
recovery and transfer smoke rather than another emulator proof of the same
local baseline. The resulting artifact directory must include `summary.json`
created by `tools/mobile_physical_tailnet_evidence_init.py` and filled with
passing T0-T6 case results. Use
`tools/mobile_physical_tailnet_environment_collect.py` to write read-only T0
`preflight.json` and `environment.json`, use
`tools/mobile_physical_tailnet_case_record.py` to record each case with
safe existing non-empty evidence paths, then pass
`tools/mobile_physical_tailnet_evidence_audit.py`. Register the passing
`audit.json` as `history/physical-tailnet-final-audit.json`; only then can
`tools/mobile_acceptance_evidence_audit.py` close the physical lane.

## Last Verified

- 2026-06-27 acceptance evidence audit:
  [history/mobile-acceptance-evidence-audit-20260627.json](history/mobile-acceptance-evidence-audit-20260627.json)
  verified that the local AVD matrix has `11` accepted stages and `38` valid
  JSON evidence files, the real AVD casebook has `11` accepted rows and `44`
  valid JSON evidence files, neither accepted evidence set has semantic
  failure markers such as bad status, fake/demo, `CCB_REQ_ID`, or blind
  polling, and the only overall blocker remains physical Tailnet preflight
  status `blocked`.
- 2026-06-27 acceptance audit closure path now recognizes
  `history/physical-tailnet-final-audit.json` as the final physical Tailnet
  evidence. A clean `status: ok` final audit closes the physical lane; a
  present failed/dirty final audit fails the overall audit.
- 2026-06-27 physical Tailnet evidence packet auditor was added for future
  real-device runs: `tools/mobile_physical_tailnet_evidence_audit.py` checks
  required packet files, `summary.json` T0-T6 case coverage, preflight status,
  Tailnet/non-emulator environment evidence, file hash matches, recovery
  replay markers, and obvious log failure strings before a physical run can
  be accepted.
- 2026-06-27 physical Tailnet evidence packet auditor now also checks T5/T6
  evidence semantics: at least five timed conversation turns, direct/DERP/relay
  path records, explicit `blind_polling_seen: false`, memory samples and debug
  growth budget, idle wake-lock zero evidence, and multiple recovery events
  with `input_replayed: false`.
- 2026-06-27 acceptance evidence audit now requires
  `history/physical-tailnet-final-audit.json` to carry
  `requirements_version: physical-tailnet-stress-v2`, so a stale pre-T5/T6
  `status: ok` final audit cannot close the physical lane.
- 2026-06-27 local environment audit after committing
  `1f304f4 docs: record current clean release idle smoke`: worktree was
  clean, `adb devices -l` returned no attached devices after the emulator was
  killed, and `tailscale` was not found on PATH. This keeps physical
  device/Tailnet validation open as an external-environment lane.
- 2026-06-27 physical Tailnet preflight dry run with
  `PATH="/home/bfly/.local/share/android-sdk/platform-tools:$PATH"`
  produced structured `status: blocked`: `adb devices -l` succeeded but no
  online Android device was attached, and `tailscale status --json` failed
  because `tailscale` was not installed on PATH. The blocker is executable
  and reproducible rather than an undocumented manual gap. Evidence:
  [history/physical-tailnet-preflight-blocked-20260627.json](history/physical-tailnet-preflight-blocked-20260627.json).
- 2026-06-27 clean release idle smoke on app head `03ede70` and source head
  `7e436f7e` opened real `test_ccb2_alpha/mobile_probe`, stayed untouched for
  `180` seconds, and recorded `0` total gateway requests with no wakelocks,
  FATAL, ANR, or OOM. Evidence:
  [history/local-avd-release-idle-current-clean-smoke-20260627.json](history/local-avd-release-idle-current-clean-smoke-20260627.json).
- Code inspection on 2026-06-25 confirmed current app send path:
  `SelectedAgentWorkspace._sendMessage -> submitAgentMessage -> HTTP
  /agents/{agent}/messages`.
- Code inspection on 2026-06-25 confirmed current source handler sets
  `message_type='ask'` and current conversation backfill reads
  `.ccb/agents/<agent>/jobs.jsonl`.
- Manual AVD screenshots showed `CCB_REQ_ID` appearing in agent input, which
  confirms the default send path is still non-compliant with Decision 015.
- Manual inspection on 2026-06-25 confirmed that the `ccb_mobile/lead` phone
  timeline can show older mobile_gateway ask/completion records while the
  desktop `lead` pane contains newer active-turn content; this confirms the
  read path is not yet pane-equivalent.
- Compass baseline on 2026-06-26 against real gateway `127.0.0.1:19011` and
  real project `test_ccb2_beta` found no performance/power stability blocker:
  `/v1/projects` returned `38/38` healthy projects with p50 `80.9 ms`, 60s
  PSS delta was `-74 KB`, 3-minute idle soak PSS delta was `-40 KB`, wake
  locks were `0`, and logcat had no FATAL/ANR/OOM. Artifacts:
  `/tmp/ccb-mobile-stress-20260626155408`,
  `/tmp/ccb-mobile-stress-ui-20260626155648`, and
  `/tmp/ccb-mobile-soak-20260626155755`.
- The same compass session's controlled send probe to `test_ccb2_beta` showed
  the user's marker locally but did not prove a new backend reply and surfaced
  `Terminal output: open terminal failed: not a terminal`. Artifact:
  `/tmp/ccb-mobile-send-20260626160154`. Treat file/image/multi-turn stress as
  blocked until the selected-agent pane target and reply path are fixed.
- Follow-up inspection of the current real gateway run found that the selected
  `test_ccb2_beta` fixture was fake-only and its agents had no valid pane id.
  Treat that as an invalid fixture, not as real chat acceptance. The next AVD
  run must first pass the real pane-backed fixture gate in
  [topics/local-avd-real-project-test-runbook.md](topics/local-avd-real-project-test-runbook.md).
- Real pane-backed native send AVD smoke on 2026-06-26 passed against
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626085051`
  through gateway `127.0.0.1:19021`; source head `6042b813`, emulator
  `emulator-5554`, integration test
  `native_pane_gateway_smoke_test.dart`, expected reply
  `CCB_MOBILE_NATIVE_OK_20260626085051`, no `CCB_REQ_ID`, no
  `mobile_gateway`, and no jobs matches. Evidence:
  [history/local-avd-native-pane-smoke-20260626.json](history/local-avd-native-pane-smoke-20260626.json).
- Live manual-review state on 2026-06-26 is gateway `127.0.0.1:19022`
  running under tmux, emulator `adb reverse tcp:19022 tcp:19022`, and opened
  project
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626085413/test_ccb2_beta`
  with `mobile_probe` and `mobile_peer` visible. Evidence:
  [history/local-avd-live-real-project-handoff-20260626.json](history/local-avd-live-real-project-handoff-20260626.json).
- Casebook compass preflight on 2026-06-26 against the same real gateway
  `127.0.0.1:19022` passed C0.1/C10.1 debug preflight and wrote standardized
  casebook artifacts under `/tmp/ccb-mobile-compass-20260626091952`: 40/40
  projects healthy, `/v1/projects` p50 `145.8 ms`, PSS delta `-176 KB`, wake
  locks `0`, no FATAL/ANR/OOM. Evidence:
  [history/local-avd-casebook-compass-preflight-20260626.json](history/local-avd-casebook-compass-preflight-20260626.json).
- Real provider native-pane AVD smoke on 2026-06-26 passed on the current app
  head `e00d5e4` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626092252`
  through gateway `127.0.0.1:19023`; expected reply
  `CCB_MOBILE_NATIVE_OK_20260626092252`, one matching user prompt, one
  matching reply, no jobs matches, no `CCB_REQ_ID`, no `mobile_gateway`.
  Evidence:
  [history/local-avd-native-pane-smoke-20260626-092252.json](history/local-avd-native-pane-smoke-20260626-092252.json).
- Multi-project/multi-agent native-pane AVD smoke on 2026-06-26 passed on app
  head `114c0c0` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626093156`
  through gateway `127.0.0.1:19024`; source head `6042b813`, emulator
  `emulator-5554`, integration test
  `native_pane_multi_gateway_smoke_test.dart`, expected replies
  `CCB_MOBILE_NATIVE_ALPHA_OK_20260626093156` and
  `CCB_MOBILE_NATIVE_BETA_OK_20260626093156`, one matching user prompt and
  one matching reply for each selected project/agent, no jobs matches, no
  `CCB_REQ_ID`, and no `mobile_gateway`. Evidence:
  [history/local-avd-native-pane-multi-smoke-20260626.json](history/local-avd-native-pane-multi-smoke-20260626.json).
- Desktop-origin explicit-refresh AVD smoke on 2026-06-26 passed on app head
  `46829fb` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626100818`
  through gateway `127.0.0.1:19031`; source head `6042b813`, emulator
  `emulator-5554`, integration test
  `native_pane_desktop_sync_smoke_test.dart`, direct host tmux input marker
  `DESKTOP_ORIGIN_SYNC_MARKER_20260626100818`, one matching native user
  prompt, no jobs matches, no `CCB_REQ_ID`, and no `mobile_gateway`. The app
  asserted the marker was absent during a 30-second idle window before refresh
  and visible after explicit selected-agent refresh without reopening the
  project. Evidence:
  [history/local-avd-desktop-origin-sync-smoke-20260626.json](history/local-avd-desktop-origin-sync-smoke-20260626.json).
- Long-history provider-native backfill AVD smoke on 2026-06-26 passed on app
  head `70e9af0` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626103241`
  through gateway `127.0.0.1:19036`; source head `6042b813`, emulator
  `emulator-5554`, integration test
  `server_wide_gateway_smoke_test.dart`, 56 Codex native rollout turns seeded
  without `ccb ask`, latest page API `4.81 ms`, two older pages total
  `12.556 ms`, latest visible `118 ms`, older visible `10049 ms`, total UI
  case `14355 ms`. This is early C5 smoke evidence; later 200-turn
  profile/release evidence closes the mixed-media pressure gate. Evidence:
  [history/local-avd-long-history-backfill-smoke-20260626.json](history/local-avd-long-history-backfill-smoke-20260626.json).
- Native selected-agent file/artifact AVD smoke on 2026-06-26 passed on app
  head `16e621e` and source head `7fece763` against fresh disposable projects
  under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626112747`
  through gateway `127.0.0.1:19042`; the run used clean app/source worktrees,
  listed `43` server-wide projects, sent/downloaded text attachments,
  sent image-only turns, downloaded seeded Codex native text/image artifact
  links, verified SHA256 for `9` files saved under the Android app documents
  directory, and passed
  `app/integration_test/server_wide_gateway_smoke_test.dart` on
  `emulator-5554`. This is early C6/C7 smoke evidence; later live-provider,
  rejection, restart, background/resume, and release download evidence closes
  the local AVD file/artifact gate. Evidence:
  [history/local-avd-native-file-artifact-smoke-20260626.json](history/local-avd-native-file-artifact-smoke-20260626.json).
- Reverse-recovery AVD smoke on 2026-06-26 passed on app head `58c5f00` and
  source head `7fece763` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626120446`
  through gateway `127.0.0.1:19047`; the run removed
  `adb reverse tcp:19047` twice, first verifying project-list refresh showed
  `Could not load projects` and recovered through Retry after restore, then
  verifying selected-agent explicit refresh showed
  `Conversation refresh failed` and recovered on the same open project after
  restoring `adb reverse tcp:19047 tcp:19047`. The selected-agent surface also
  remained free of `CCB_REQ_ID`, `mobile_gateway`, and `completion_snapshot`
  labels. Evidence:
  [history/local-avd-reverse-recovery-smoke-20260626.json](history/local-avd-reverse-recovery-smoke-20260626.json).
- Gateway-restart AVD smoke on 2026-06-26 passed on app head `b584d74` and
  source head `7fece763` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626130325`
  through gateway `127.0.0.1:19049`; the run stopped and restarted the real
  server-wide mobile gateway process twice on the same listener/state
  directory, first verifying project-list refresh failure and Retry recovery,
  then verifying selected-agent refresh failure and recovery on the same open
  project. The run used clean app/source worktrees and did not clear app data
  or re-pair. Evidence:
  [history/local-avd-gateway-restart-smoke-20260626.json](history/local-avd-gateway-restart-smoke-20260626.json).
- Project-ccbd restart AVD smoke on 2026-06-26 passed on app head `6372afb`
  and source head `7fece763` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626143936`
  through gateway `127.0.0.1:19054`; the run stopped and restarted only
  `test_ccb2_alpha`'s real ccbd while keeping the gateway and emulator reverse
  path up, verified `Conversation refresh failed`, and recovered through
  explicit selected-agent refresh retry on the same open project without
  clearing app data or re-pairing. Evidence:
  [history/local-avd-ccbd-restart-smoke-20260626.json](history/local-avd-ccbd-restart-smoke-20260626.json).
- Idle request-rate AVD smoke on 2026-06-26 passed on app head `6797b14` and
  source head `7fece763` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626150715`
  through backend gateway `127.0.0.1:19057` and counting proxy
  `127.0.0.1:19058`; after opening a real selected-agent page, the app waited
  untouched for `180` seconds and recorded `0` total gateway requests,
  `0` conversation requests, `0` terminal-history requests, and
  `0.0` conversation/terminal requests per minute before a post-window manual
  refresh. Evidence:
  [history/local-avd-idle-request-smoke-20260626.json](history/local-avd-idle-request-smoke-20260626.json).
- Idle metrics AVD smoke on 2026-06-26 passed on app head `09962f6` and
  source head `7fece763` against fresh disposable projects under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626153219`
  through backend gateway `127.0.0.1:19065` and counting proxy
  `127.0.0.1:19066`; after opening a real selected-agent page, the app waited
  untouched for `180` seconds and recorded `0` total gateway requests,
  `0` conversation requests, `0` terminal-history requests,
  `0.0` conversation/terminal requests per minute, seven device metric
  samples, PSS delta `-508 KB`, `Wake Locks: size=0`,
  `mWakeLockSummary=0x0`, one skipped-frame logcat diagnostic, and no
  FATAL/ANR/OOM. Evidence:
  [history/local-avd-idle-metrics-smoke-20260626.json](history/local-avd-idle-metrics-smoke-20260626.json).

## Handoff Notes

- Do not continue adding fake/demo acceptance gates for ordinary chat.
- Do not treat CCB ask/message submit as the default mobile composer path.
- Keep `/agents/{agent}/messages` only as compatibility or future explicit
  action unless a later decision supersedes Decision 015.
- Preserve server-wide project registry, file/artifact routes, pairing,
  terminal transport, route diagnostics, and lifecycle behavior while rebasing
  chat send/read on native agent state.
- Use the casebook artifact shape from `tools/mobile_app_compass_test.py` for
  future AVD evidence, but do not treat C0.1/C10.1 preflight as proof that
  send/reply/file/recovery gates are complete.
- Release-mode AVD gates cannot use the current Flutter Driver integration
  path: the 2026-06-27 release probe failed before app start with
  `Flutter Driver (non-web) does not support running in release mode`. Build a
  separate non-driver harness, such as `flutter build apk --release` plus
  `adb`/UI automation and gateway-side request counters, before counting
  release performance or release power evidence.
