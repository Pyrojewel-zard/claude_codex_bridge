# Mobile Tmux Control Evidence Index

Date: 2026-06-29

## 2026-07-22: Public Relay Encrypted Stream Package

Evidence:

- [public-relay-stream-package-20260722.md](public-relay-stream-package-20260722.md)

Result:

- Local protocol checkpoint: encrypted inner request/response and bounded
  Terminal/notification streams pass Python real-socket and Dart transport
  tests.
- File chunking, host activation/bootstrap lifecycle, Android Emulator, and
  public WSS acceptance remain open and are not claimed.

## 2026-07-22: Public Relay Package D Local Implementation

Evidence:

- [public-relay-d-package-20260722.md](public-relay-d-package-20260722.md)

Result:

- Local Package D implementation checkpoint only: Python outbound host
  connector, loopback operation allowlist, v2 E2EE request/response proxy,
  Flutter socket transport surface, and local docs are present.
- Python relay connector/service/crypto/admission focused tests passed.
- Flutter/Dart execution, public Alibaba WSS, and Android public-route
  acceptance are not claimed.

## 2026-07-22: Public Relay Package A/B Candidate

Evidence:

- [public-relay-ab-package-20260722.md](public-relay-ab-package-20260722.md)

Result:

- Local Package A/B implementation checkpoint only: relay crypto protocol v2,
  deterministic Python/Dart vectors, SQLite/WAL one-time invitation store,
  host PoP session capabilities, and local operator CLI are covered by Python
  and Flutter tests.
- No production relay listener, public WSS acceptance, Android public-route
  acceptance, host connector, or cloud deployment is claimed.

## 2026-07-14: Paseo-Inspired Device-Bound Push Integration

Evidence:

- [paseo-push-integration-20260714.md](paseo-push-integration-20260714.md)

Result:

- Local source full tests, Flutter full tests, and debug/profile/release APK
  builds passed.
- Real Firebase delivery, emulator/physical-device lifecycle, screenshots,
  logcat, and request-count evidence are BLOCKED because no Android device is
  attached and Firebase operator credentials are not injected.

## 2026-07-10: Realtime Authority and Recovery

- [Fresh profile-APK AVD evidence](/tmp/ccb-mobile-realtime-recovery-20260710/README.md):
  same-SHA server-wide/dedicated-project cold snapshot, native invalidation,
  reconnect retention, notification, and 259-second idle audit.

## Open External Gaps

### 2026-06-29: Local AVD Native Pane Timing And `/status`

Evidence:

- [local-avd-native-pane-repeat-timing-20260629.json](local-avd-native-pane-repeat-timing-20260629.json)
- [local-avd-native-status-command-20260629.json](local-avd-native-status-command-20260629.json)
- [local-avd-scroll-away-desktop-origin-20260629.json](local-avd-scroll-away-desktop-origin-20260629.json)
- [local-avd-idle-request-20260629.json](local-avd-idle-request-20260629.json)
- [local-avd-reverse-recovery-timing-20260629.json](local-avd-reverse-recovery-timing-20260629.json)
- [local-avd-native-long-output-live-turn-20260629.json](local-avd-native-long-output-live-turn-20260629.json)
- [local-avd-native-long-output-120-device-metrics-20260629.json](local-avd-native-long-output-120-device-metrics-20260629.json)
- [local-avd-native-long-output-strict-80-live-device-metrics-20260629.json](local-avd-native-long-output-strict-80-live-device-metrics-20260629.json)
- [local-avd-native-high-volume-200-device-metrics-20260629.json](local-avd-native-high-volume-200-device-metrics-20260629.json)
- [local-avd-status-only-transcript-200-20260629.json](local-avd-status-only-transcript-200-20260629.json)
- [local-avd-release-reverse-recovery-current-20260629.json](local-avd-release-reverse-recovery-current-20260629.json)

Result:

- repeat native-pane sends ran through real server-wide gateway
  `127.0.0.1:19302` on `emulator-5554` against disposable
  `test_ccb2_alpha/mobile_probe`;
- local bubble p50 `133 ms`, `Working` p50 `138 ms`, first visible feedback
  p50 `138 ms`, expected reply p50 `3206 ms`, and `Working` captured `2/2`;
- source-side evidence still showed no `CCB_REQ_ID`, no `mobile_gateway`, no
  jobs matches, one native user match, and one native reply match per run;
- separate `/status` command smoke through gateway `127.0.0.1:19303` rendered
  non-local marker `Weekly limit:` in `562 ms`;
- scroll-away desktop-origin smoke through gateway `127.0.0.1:19304` seeded
  `56` native-history turns, dragged away from latest, verified no blind pickup
  during the idle window, and used explicit refresh plus `New messages` to
  render the injected pane marker;
- strict idle request audit through gateway `127.0.0.1:19306` held
  `test_ccb2_alpha/mobile_probe` open on `emulator-5554` for `180 s` and
  observed `0` total requests, `0` conversation requests, `0` terminal-history
  requests, and `0.0` conversation/history requests per minute in the reset
  audit window; device sampling had `7` samples, PSS delta `-582 KB`, wake
  locks `size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, and no
  skipped-frame storm;
- reverse-loss recovery timing through gateway `127.0.0.1:19309` removed and
  restored `adb reverse` for both project-list and already-open selected-agent
  refresh paths; project-list retry recovered in `1234 ms`, conversation retry
  recovered in `1099 ms`, and internal labels remained absent;
- 40-line long-output shape smoke through gateway `127.0.0.1:19310` rendered
  its final marker in exactly one live terminal-output conversation item,
  captured `Working` in `155 ms`, and kept internal labels absent;
- 120-line long-output command smoke through gateway `127.0.0.1:19313` used
  the same real server-wide path and collected device metrics from the
  ready-to-send marker: local bubble `273 ms`, `Working` `281 ms`, first
  feedback `281 ms`, final marker `1056 ms`, one final expected-reply item,
  one live terminal-output item, no FATAL/ANR/OOM, no skipped-frame storm, and
  screenshot/UI dump artifact paths. This is stronger than the 40-line shape
  smoke but still does not close the 1000-line/long-duration gate because the
  expected marker was not inside the live terminal-output item and the device
  metric window produced only one valid memory sample plus global wake-lock
  warnings;
- strict 80-line live-marker smoke through gateway `127.0.0.1:19315` fixed
  that false-positive risk by using a marker that was not present verbatim in
  the user prompt and requiring the marker inside the live `Terminal output`
  item before timing evidence was emitted. It reported local bubble `259 ms`,
  `Working` `263 ms`, first feedback `263 ms`, final marker `205237 ms`, one
  final expected-reply item, one live terminal-output item containing the
  marker, `88` device-metric samples, PSS delta `-1481 KB`, wake locks
  `size=0`, `mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, no skipped-frame
  storm, and no warnings;
- 200-line high-volume transcript reconciliation smoke through gateway
  `127.0.0.1:19318` extended the active-send follow-up refresh tail through
  `80 s`, `160 s`, and `320 s`, then verified all `200` prefixed lines were
  present in the selected-agent model. It reported local bubble `162 ms`,
  `Working` `167 ms`, first feedback `167 ms`, final transcript reconciliation
  `80313 ms`, `3` non-local conversation items against the `8` item cap,
  `35` device-metric samples, PSS delta `11060 KB`, wake locks `size=0`,
  `mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, no skipped-frame storm, and
  no warnings;
- status-only transcript smoke through gateway `127.0.0.1:19323` verified the
  updated product contract: terminal stream output drove the composer-adjacent
  `Working` state but created `0` `Terminal output` conversation items. The
  provider/native transcript model contained all `200` prefixed lines, local
  bubble appeared in `238 ms`, `Working` in `244 ms`, first feedback in
  `244 ms`, final transcript reconciliation in `80336 ms`, and the model
  stayed compact with `4` non-local items against the `8` item cap;
- release reverse-recovery smoke through gateway `127.0.0.1:19316` installed
  release APK `app/build/app/outputs/flutter-apk/app-release.apk`, opened
  disposable real project `test_ccb2_alpha/mobile_probe`, removed `adb reverse`,
  observed `Connection refused`, restored `adb reverse`, and rendered marker
  `Native reverse recovery restored 1782719941`. Recovery elapsed
  `14230.173 ms`, screenshot path was
  `/tmp/ccb-mobile-release-reverse-recovery-1782719951.png`, device metrics had
  `7` memory samples, PSS delta `-3448 KB`, wake locks `size=0`,
  `mWakeLockSummary=0x0`, no FATAL/ANR/OOM marker, no skipped-frame storm, and
  no warnings;
- remaining open gaps are true long-duration/high-volume output at the
  original `1000`-line target, broader p50/p95 across repeated high-volume
  long-output runs, and physical Tailnet/VPN recovery beyond local AVD.

### 2026-06-28: Local AVD Pane Live-Output Smoke

Evidence:

- [local-avd-pane-live-output-smoke-20260628.md](local-avd-pane-live-output-smoke-20260628.md)

Result:

- current debug APK opened the real server-wide project list through gateway
  `127.0.0.1:18999` and selected real `/home/bfly/yunwei/test_ccb2`;
- phone send used the pane-backed path without adding a new `CCB_REQ_ID` or
  `mobile_gateway` wrapper;
- terminal output rendered in the selected-agent page;
- app-side `Working` state now clears after first pane output or terminal
  notice instead of staying stuck after stream close;
- superseded by the 2026-06-29 native-pane repeat and `/status` command
  evidence above; retain this entry as the original partial smoke result and
  failure trail.

### 2026-06-27: Physical Tailnet Evidence Packet Auditor Added

Scope: make future physical Android phone + Tailnet run artifacts
machine-checkable before they can close the remaining remote-device lane.

Evidence:

- init tool:
  `tools/mobile_physical_tailnet_evidence_init.py`
- environment collector:
  `tools/mobile_physical_tailnet_environment_collect.py`
- case recorder:
  `tools/mobile_physical_tailnet_case_record.py`
- audit tool:
  `tools/mobile_physical_tailnet_evidence_audit.py`
- runbook gate:
  [../topics/physical-tailnet-device-validation-runbook.md](../topics/physical-tailnet-device-validation-runbook.md)

Result:

- the auditor requires the physical run packet files from the runbook,
  including summary, preflight, environment, projects, gateway health, route
  diagnostics, timings, request counts, memory, transfer hashes, recovery
  events, power, logcat, gateway/source tails, screenshots, and UI dumps;
- the init tool creates the artifact directory, `summary.json` with T0-T6
  marked `pending`, and capture directories, but does not create passing
  evidence;
- the environment collector writes read-only T0 `preflight.json` and
  `environment.json` evidence with app/source git state plus `adb` and
  Tailscale command outputs;
- the case recorder updates `summary.json` per T0-T6 case, refuses accepted
  case statuses without safe existing non-empty evidence paths, and rolls the
  packet status to `ok` only after every case is accepted;
- it blocks/fails packets with missing files, invalid JSON, missing or failed
  T0-T6 case results, accepted cases without safe existing non-empty evidence
  paths, preflight not ok, non-tailnet route provider evidence, emulator
  evidence, file hash mismatch, replay markers, `CCB_REQ_ID`, FATAL, OOM, or
  ANR markers;
- it now also fails physical packets that lack T6 semantics: five timed
  conversation turns with own-message and provider-reply latency, direct/DERP
  or relay path evidence, explicit no-blind-polling request evidence, at least
  two memory samples within the debug growth budget, idle wake-lock zero
  evidence, and multiple recovery events with no input replay.

Plan impact:

- a future physical Tailnet run must produce an auditable artifact directory
  with complete T0-T6 case results rather than a screenshot-only manual claim;
- once the packet audit passes, the final audit JSON must be registered at
  `history/physical-tailnet-final-audit.json` so
  `tools/mobile_acceptance_evidence_audit.py` can close the physical lane;
- that final audit must carry `requirements_version:
  physical-tailnet-stress-v2`; stale `status: ok` files from older physical
  audit rules are rejected.

### 2026-06-27: Acceptance Evidence Audit Blocks Only On Physical Tailnet

Scope: verify the accepted local AVD matrix and casebook evidence are
discoverable and valid JSON while keeping the physical Tailnet lane explicit.

Evidence:

- [mobile-acceptance-evidence-audit-20260627.json](mobile-acceptance-evidence-audit-20260627.json)
- audit tool:
  `tools/mobile_acceptance_evidence_audit.py`

Result:

- local AVD matrix audit: `status: ok`, `11` accepted stages, `38` linked
  evidence files, no missing files, no invalid JSON, no semantic failure
  markers;
- real AVD casebook audit: `status: ok`, `11` accepted case rows, `44` linked
  evidence files, no missing files, no invalid JSON, no semantic failure
  markers;
- physical Tailnet lane: `status: blocked` from the preflight evidence below;
- overall audit status: `blocked`, not `ok`, because the physical phone +
  Tailnet T0-T6 run is still not executed.

Follow-up closure behavior:

- `tools/mobile_acceptance_evidence_audit.py` now checks
  `history/physical-tailnet-final-audit.json` when present;
- a clean final physical audit changes the physical lane to `ok`;
- a present but failed/dirty final physical audit makes the overall acceptance
  audit fail instead of remaining blocked.

Plan impact:

- local AVD acceptance can be checked by command instead of manual link
  inspection;
- completion remains correctly gated on physical-device/Tailnet validation.

### 2026-06-27: Physical Tailnet Preflight Blocked By Environment

Scope: make the remaining physical Android phone + Tailnet validation lane
executable and record the current host/device blocker.

Evidence:

- [physical-tailnet-preflight-blocked-20260627.json](physical-tailnet-preflight-blocked-20260627.json)
- preflight tool:
  `tools/mobile_physical_tailnet_preflight.py`
- physical Tailnet runbook:
  [../topics/physical-tailnet-device-validation-runbook.md](../topics/physical-tailnet-device-validation-runbook.md)

Result:

- `tools/mobile_physical_tailnet_preflight.py` produced structured
  `status: blocked`;
- Android SDK `adb devices -l` ran successfully but found no online Android
  device;
- `tailscale status --json` failed because `tailscale` was not installed on
  PATH;
- no app, gateway, or Tailnet state was modified by the preflight.

Plan impact:

- the blocker is now reproducible with a single read-only command instead of
  an informal note;
- local AVD acceptance remains accepted, but it still cannot close the
  physical-device/Tailnet remote route lane.

## Accepted Checkpoints

### 2026-06-27: Current Clean Release Idle Request/Power Smoke

Scope: prove the current committed app and current native source worktree no
longer issue blind selected-agent conversation or terminal-history requests
while an opened release APK page is untouched.

Evidence:

- [local-avd-release-idle-current-clean-smoke-20260627.json](local-avd-release-idle-current-clean-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-idle-current-clean-180-20260627.log`
- screenshot:
  `/tmp/ccb-mobile-release-idle-request-1782530371.png`

Environment:

- mobile app head:
  `03ede70 fix: gate timeline refresh to drag scroll`;
- app dirty state: `false`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- source dirty state: `false`;
- backend gateway: `http://127.0.0.1:19256`;
- request-counting proxy: `http://127.0.0.1:19257`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627031541`.

Result:

- the release APK opened disposable `test_ccb2_alpha/mobile_probe` through
  the real server-wide project list;
- the app stayed untouched on the selected-agent page for `180` seconds;
- the request proxy observed `0` total gateway requests, `0` conversation
  requests, `0` terminal-history requests, and `0.0` requests per minute;
- the project list also showed server-wide real projects, including fresh
  `test_ccb2_alpha` and `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- device metrics collected `7` samples, PSS delta was `1403 KB` (`1.54%`),
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `6` rendered frames and `1` legacy janky frame, and logcat
  had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- refreshes the current-head release no-idle-polling gate after fixing
  programmatic `UserScrollNotification` handling;
- proves selected-agent refresh is operation-driven in this release path:
  explicit button, real drag/overscroll, active send, resume, or project open,
  not a blind background loop;
- does not close physical-device Tailnet/VPN recovery, which still needs a
  host with `tailscale` and an attached phone.

### 2026-06-27: Current-Head Release Reverse Recovery

Scope: prove the current checked-out app and current native source worktree can
recover an already-open release APK selected-agent view after the Android
Emulator loses and regains its `adb reverse` gateway path.

Evidence:

- [local-avd-release-reverse-recovery-current-smoke-20260627.json](local-avd-release-reverse-recovery-current-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-reverse-recovery-current-20260627.log`
- screenshot:
  `/tmp/ccb-mobile-release-reverse-recovery-1782527720.png`

Environment:

- mobile app head:
  `7666c69 docs: record current native pane avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19244`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627023354`.

Result:

- the release APK opened disposable `test_ccb2_alpha/mobile_probe` through
  the real server-wide project list;
- after `adb reverse --remove tcp:19244`, explicit refresh showed a visible
  `SocketException: Connection refused` failure;
- after restoring `tcp:19244 tcp:19244`, the same open selected-agent page
  refreshed and rendered `Native reverse recovery restored 1782527686`;
- recovery took `39104.647ms` including the scripted reconnect and
  post-recovery settle window;
- device metrics collected `3` samples, PSS delta was `1543 KB` (`1.7%`),
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `16` frames and `1` legacy janky frame (`6.25%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- refreshes the release-mode local link-loss/recovery gate at the current
  app/source heads;
- does not close physical-device Tailnet/VPN recovery, which still needs a
  host with `tailscale` and an attached phone.

### 2026-06-27: Current-Head Native Pane Multi-Project Send

Scope: prove the current checked-out app and current native source worktree can
send ordinary phone input into two disposable real CCB project panes and
receive exact provider replies without ask/job metadata.

Evidence:

- [local-avd-native-pane-multi-current-smoke-20260627.json](local-avd-native-pane-multi-current-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-native-pane-multi-current-20260627.log`

Environment:

- mobile app head:
  `ba445c2 docs: record current live artifact avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19242`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627022830`.

Result:

- the server-wide project list returned `45` mounted projects, and the smoke
  selected fresh disposable `test_ccb2_alpha/mobile_probe` and
  `test_ccb2_beta/mobile_peer`;
- alpha phone input requested exact reply
  `CCB_MOBILE_NATIVE_ALPHA_OK_20260627022830`, and beta phone input requested
  exact reply `CCB_MOBILE_NATIVE_BETA_OK_20260627022830`;
- both selected provider transcripts recorded one native user match and one
  native reply match;
- both source-side checks had `jobs_matches: []`, no `CCB_REQ_ID`, and no
  `mobile_gateway`.

Plan impact:

- refreshes the pane-equivalent mobile send/reply gate at the current
  app/source heads;
- confirms the run used disposable `/home/bfly/yunwei/test_ccb2` projects
  rather than the active `ccb_mobile` repo.

### 2026-06-27: Current-Head Live Provider Artifact Download

Scope: prove the current checked-out app and current native source worktree can
open a real server-wide project, let the real provider create a workspace file,
render the generated artifact link, and download it on Android with matching
bytes.

Evidence:

- [local-avd-live-provider-artifact-current-smoke-20260627.json](local-avd-live-provider-artifact-current-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-live-artifact-current-20260627.log`

Environment:

- mobile app head: `bca7bfe docs: record release 24m upload smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19240`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627022247`.

Result:

- the server-wide project list returned `45` mounted projects, and the test
  selected fresh disposable `test_ccb2_alpha/mobile_probe` under
  `/home/bfly/yunwei/test_ccb2`;
- the host harness pasted the artifact request directly into the real tmux
  pane `%2`, not through `ccb ask`;
- the provider created `mobile-live-artifact-20260627022247-1021026.txt` in
  the selected project root, the gateway registered it as
  `mobile-file-6f2628893d8b31f31d6dc6d6`, and Android downloaded `43` bytes
  with SHA256
  `c4538a11f377f669126e215a74baef6a9f207d9a76e254349571aedf8d5a4ad8`;
- source-side evidence had `jobs_matches: []`, no `CCB_REQ_ID`, no
  `mobile_gateway`, two native user matches, and one native reply match;
- the Flutter integration also asserted `CCB_REQ_ID`, `mobile_gateway`, and
  `completion_snapshot` were not visible in the selected-agent timeline.

Plan impact:

- refreshes the live provider-created artifact gate at the current app/source
  heads;
- keeps physical-device/Tailnet transfer validation as a separate P2 hardening
  lane because this run used local LAN/ADB reverse.

### 2026-06-27: Release APK 24 MiB User-Origin Upload Via Android System Picker

Scope: prove a release APK can upload a near-limit user-selected file through
the real Android DocumentsUI picker, render the resulting conversation
attachment, download it back through the gateway, and stay inside device
stability gates.

Evidence:

- [local-avd-release-upload-24m-smoke-20260627.json](local-avd-release-upload-24m-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-upload-24m-stream-smoke-20260627.log`
- screenshot:
  `/tmp/ccb-mobile-release-upload-1782526203.png`

Environment:

- mobile app head:
  `f7e889c fix: stream gateway attachment uploads`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19230` with request proxy
  `http://127.0.0.1:19231`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627020845`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list, tapped Attach file, chose File, and selected
  `ccb-mobile-release-upload-20260627020845-409688.txt` from Android
  DocumentsUI Recent files;
- the selected user-origin attachment was `25,165,824` bytes with SHA256
  `f8ae4cfc47823f8e88523935ea6d79ed4ea0e20ee1dc4adafe7e3d07a3dc9d3e`;
- the app uploaded the attachment through the selected-agent composer,
  rendered the resulting conversation attachment chip, tapped that chip, and
  showed `Saved ccb-mobile-release-upload-20260627020845-409688.txt`;
- the request proxy observed one `POST /files` upload and one
  `GET /files/{id}` download; the download returned `25,165,824` bytes in
  `50.534ms` with the same SHA256;
- the upload/download loop reported `22932.324ms` send-to-save latency and
  `10210.963ms` download saved-visible latency;
- device metrics collected `6` samples, PSS delta was `14860 KB`
  (`17.44%`) over the active upload/download and post-save settle window,
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `26` frames and `3` legacy janky frames (`11.54%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers;
- the harness installed `adb reverse` for both the request-proxy port
  `tcp:19231` and the underlying gateway port `tcp:19230`, so terminal/session
  routes did not produce connection-refused noise while the proxy recorded
  file routes.

Plan impact:

- closes release-mode user-origin upload with the real Android system picker
  for the local real server-wide Android Emulator path;
- keeps physical-device/Tailnet transfer pressure as a separate P2 hardening
  lane.

### 2026-06-27: Profile AVD 24 MiB User-Origin Upload Hardening

Scope: prove the app can upload a near-limit user-selected attachment through
the selected-agent composer on a real server-wide Android Emulator path, then
download the resulting conversation attachment back to Android app documents
with matching SHA256.

Evidence:

- [local-avd-profile-upload-24m-smoke-20260627.json](local-avd-profile-upload-24m-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-upload-24m-smoke-20260627.log`

Environment:

- mobile app head:
  `a507698 test: add user upload stress avd hook`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19224`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627014028`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- profile integration opened the real server-wide gateway, exercised the
  existing file/image/artifact matrix, then uploaded
  `beta-mobile_probe-upload-stress-1782524465097.txt` on
  `test_ccb2_beta/mobile_probe`;
- the selected user-origin attachment was `25,165,824` bytes with SHA256
  `8777fe43ae7b36771cb810d28af83f727ffae8595625f0b024cdd4b290ed7151`;
- the app downloaded the resulting conversation attachment to
  `/data/user/0/io.ccb.mobile.ccb_mobile/app_flutter/...`, preserving the
  same byte count and SHA256;
- the upload/download loop reported `6650ms` send-to-save latency and
  `1066ms` download saved-visible latency;
- the integration ended with `01:32 +3: All tests passed!`, `9`
  SHA256-checked downloaded files, and no FATAL/ANR/OOM or skipped-frame
  markers in the raw log.

Plan impact:

- closes local real AVD `24 MiB` user-origin upload/download loopback
  hardening in profile integration mode;
- does not close release-mode user-origin upload with the real Android system
  picker or physical-device/Tailnet transfer pressure.

### 2026-06-27: Release APK 24 MiB Native Artifact Download Hardening

Scope: prove a release APK can render and save a near-limit provider-native
artifact through the real server-wide Android Emulator path, with gateway byte
and hash verification plus device stability checks.

Evidence:

- [local-avd-release-file-download-24m-smoke-20260627.json](local-avd-release-file-download-24m-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-file-download-24m-smoke-20260627.log`
- screenshot:
  `/tmp/ccb-mobile-release-file-download-1782523632.png`

Environment:

- mobile app head:
  `84a48d3 docs: consolidate local avd acceptance matrix`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19222` with request proxy
  `http://127.0.0.1:19223`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627012611`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list, tapped the requested agent chip, and explicitly
  refreshed the selected-agent conversation;
- the release app rendered the native transcript artifact chip
  `native-artifact-20260627012611-2745008.txt (24.0 MB)`;
- tapping the chip produced `Saved native-artifact-20260627012611-2745008.txt`
  after about `4.34s`;
- the request proxy observed exactly one file-route download,
  `GET /v1/projects/{project}/agents/{agent}/files/{id}`, status `200`,
  `25,165,824` response bytes, route elapsed `100.227ms`, and SHA256
  `730cb977bd887e6ff2a8cfe096340802f079b08487bf1a7ce529a4b53f3deaca`,
  matching the seeded artifact;
- device metrics collected `3` samples, PSS delta was `16198 KB`
  (`17.47%`) over the active 24 MiB download and post-save settle window,
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `16` frames and `1` legacy janky frame (`6.25%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- closes near-limit `20-25 MB` release artifact-download hardening for the
  local real server-wide Android Emulator path;
- does not close large user-origin upload or physical-device/Tailnet transfer
  pressure.

### 2026-06-27: Release APK ADB Reverse Loss And Explicit-Refresh Recovery

Scope: prove a release APK on a real server-wide selected-agent page fails
visibly when the Android Emulator loses its `adb reverse` gateway path, then
recovers through an explicit refresh after the reverse mapping is restored and
new backend transcript content is available.

Evidence:

- [local-avd-release-reverse-recovery-smoke-20260627.json](local-avd-release-reverse-recovery-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-reverse-recovery-smoke-20260627-clean.log`
- screenshot:
  `/tmp/ccb-mobile-release-reverse-recovery-1782522969.png`

Environment:

- mobile app head:
  `89274a0 test: add release reverse recovery avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19220`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627011507`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list and tapped the requested agent chip;
- after `adb reverse --remove tcp:19220`, tapping `Refresh conversation`
  showed a visible `SocketException: Connection refused` failure in the
  selected-agent UI;
- while disconnected, the harness seeded a new provider-native Codex rollout
  marker `Native reverse recovery restored 1782522959`;
- after restoring `adb reverse` as `tcp:19220 tcp:19220`, tapping
  `Refresh conversation` displayed that newly seeded marker, proving the app
  reached the backend rather than reusing stale UI content;
- device metrics collected `4` samples, PSS delta was `408 KB` (`0.43%`),
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `16` frames and `2` legacy janky frames (`12.50%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- closes release APK adb-reverse recovery pressure for the local real
  server-wide Android Emulator path;
- physical device and Tailnet/VPN recovery remain separate validation paths.

### 2026-06-27: Release APK 8 MiB Native Artifact Download Performance

Scope: prove a release APK can render a provider-native downloadable artifact
from a real server-wide selected-agent transcript, download it through the
gateway, verify bytes/hash at the gateway proxy, and stay within device
stability gates.

Evidence:

- [local-avd-release-file-download-smoke-20260627.json](local-avd-release-file-download-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-file-download-smoke-20260627-clean.log`
- screenshot:
  `/tmp/ccb-mobile-release-file-download-1782521878.png`

Environment:

- mobile app head: `6a1cfa1 test: add release file download avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19214` with request proxy
  `http://127.0.0.1:19215`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627005656`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list, tapped the requested agent chip, and explicitly
  refreshed the selected-agent conversation;
- the release app rendered the native transcript artifact chip
  `native-artifact-20260627005656-1404768.txt (8.0 MB)`;
- tapping the chip produced `Saved native-artifact-20260627005656-1404768.txt`
  after about `4.38s`;
- the request proxy observed exactly one file-route download,
  `GET /v1/projects/{project}/agents/{agent}/files/{id}`, status `200`,
  `8,388,608` response bytes, route elapsed `22.012ms`, and SHA256
  `5d72871e199c9519efb0e2df7654e0e615be3fcbac712a1be25446f38976ee0a`,
  matching the seeded artifact;
- device metrics collected `3` samples, PSS delta was `11485 KB`
  (`12.62%`) over the short active download and post-save settle window,
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `16` frames and `1` legacy janky frame (`6.25%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- closes release APK 8 MiB native artifact download performance for the real
  server-wide Android Emulator path;
- does not close recovery pressure.

### 2026-06-27: Release APK 200-Turn Long-History Frame/Memory Pressure

Scope: prove a release APK can open a real server-wide selected-agent page,
load and render a long provider-native transcript with Markdown/code/artifact
links, scroll to older pages through the phone UI, and stay within memory,
frame, request-rate, power, and logcat gates.

Evidence:

- [local-avd-release-long-history-smoke-20260627.json](local-avd-release-long-history-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-long-history-smoke-20260627-clean.log`
- screenshot:
  `/tmp/ccb-mobile-release-long-history-1782520840.png`

Environment:

- mobile app head: `7c8be1e test: add release long history avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19208` with request proxy
  `http://127.0.0.1:19209`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260627003602`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list, tapped the requested agent chip, and explicitly
  refreshed the selected-agent conversation;
- the seeded native transcript contained `200` turns, `7` older pages,
  duplicate short prompts, Markdown headings/tables/code blocks, and
  document/image artifact links;
- the latest native marker was visible in about `2.0s` without an extra drag;
- the oldest native marker became visible after `85` ADB swipes and about
  `226.6s`;
- during the active scroll window, the request proxy observed `9`
  selected-agent conversation requests and `0` terminal-history requests
  (`2.379` requests/minute);
- device metrics collected `23` samples, PSS delta was `7830 KB` (`8.0%`),
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `182` frames and `5` legacy janky frames (`2.75%`), and
  logcat had no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- closes the release APK long-history frame/memory/request pressure gate for
  real server-wide Android Emulator validation;
- does not close release file performance or recovery pressure.

### 2026-06-27: Release APK 30-Minute Idle Request And Power Soak

Scope: prove a release APK open on a real server-wide selected-agent page can
remain untouched for 30 minutes without hidden gateway polling, memory drift,
app wake locks, skipped-frame logcat markers, or fatal Android logcat events.

Evidence:

- [local-avd-release-30m-idle-soak-20260627.json](local-avd-release-30m-idle-soak-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-30m-idle-soak-20260627.log`
- screenshot:
  `/tmp/ccb-mobile-release-idle-request-1782518497.png`

Environment:

- mobile app head: `f2acc00 docs: record release idle avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19196` with request proxy
  `http://127.0.0.1:19197`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626233056`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list before the idle audit window;
- during the `1800` second untouched idle window, the request proxy observed
  `0` total requests, `0` conversation requests, and `0` terminal-history
  requests;
- device metrics collected `31` samples, PSS delta was `485 KB` (`0.53%`),
  wake locks reported `Wake Locks: size=0` and `mWakeLockSummary=0x0`,
  gfxinfo reported `0` rendered frames during the idle check, and logcat had
  no FATAL/ANR/OOM or skipped-frame markers.

Plan impact:

- closes the release APK selected-agent 30-minute idle request-rate/power
  soak for real server-wide Android Emulator validation;
- does not close release long-history frame/memory pressure, release file
  performance, or recovery pressure.

### 2026-06-27: Release APK 180-Second Idle Request And Power Smoke

Scope: prove a release APK open on a real server-wide selected-agent page can
remain untouched for 180 seconds without hidden gateway polling, memory drift,
app wake locks, skipped-frame logcat markers, or fatal Android logcat events.

Evidence:

- [local-avd-release-idle-request-smoke-20260627.json](local-avd-release-idle-request-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-idle-request-smoke-20260627-clean.log`
- screenshot:
  `/tmp/ccb-mobile-release-idle-request-1782516242.png`

Environment:

- mobile app head: `6c3eb16 test: add release idle avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19194` with request proxy
  `http://127.0.0.1:19195`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626232025`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under `/home/bfly/yunwei/test_ccb2`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator opened `test_ccb2_alpha/mobile_probe` from the real
  server-wide project list before the idle audit window;
- during the `180` second untouched idle window, the request proxy observed
  `0` total requests, `0` conversation requests, and `0` terminal-history
  requests;
- device metrics collected `7` samples, PSS delta was `-1100 KB`
  (`-1.18%`), wake locks reported `Wake Locks: size=0` and
  `mWakeLockSummary=0x0`, and logcat had no FATAL/ANR/OOM or skipped-frame
  markers.

Plan impact:

- closes the focused release APK selected-agent idle request-rate/power smoke
  for real server-wide Android Emulator validation;
- does not close release-mode 30-minute idle soak, release long-history
  frame/memory pressure, release file performance, or recovery pressure.

### 2026-06-27: Release APK Server-Wide Project List Real AVD Smoke

Scope: prove a release APK can be seeded with a real paired gateway profile,
launch without Flutter Driver, list server-wide real CCB projects, and open a
fresh disposable `test_ccb2` project on Android Emulator.

Evidence:

- [local-avd-release-project-list-smoke-20260627.json](local-avd-release-project-list-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-release-project-list-smoke-20260627-clean.log`
- screenshot:
  `/tmp/ccb-mobile-release-project-list-1782515382.png`

Environment:

- mobile app head: `44540aa test: add release project list avd smoke`;
- source worktree: `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19191` with
  `adb reverse tcp:19191 tcp:19191`;
- device: Android Emulator `emulator-5554`;
- APK: `build/app/outputs/flutter-apk/app-release.apk`.

Result:

- the harness started fresh real projects `test_ccb2_alpha` and
  `test_ccb2_beta` under
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626230907`;
- `flutter build apk --release` produced a `71.7MB` APK and installed it on
  the emulator;
- ADB UIAutomator observed both fresh `test_ccb2` projects in the server-wide
  project list, then tapped the `test_ccb2_alpha` tile;
- after opening, UIAutomator observed `test_ccb2_alpha`, `mobile_probe`,
  `mobile_peer`, `Refresh conversation`, `Attach file`, and `Send message`;
- the first attempted run exposed that Flutter release puts visible labels in
  UIAutomator `content-desc`; the harness now parses both `text` and
  `content-desc`, with self-test coverage.

Plan impact:

- closes the first non-Flutter-Driver release APK harness gate for project
  list and open-project validation;
- does not close release long-history frame/memory pressure, release file
  performance, or release idle/power soak.

### 2026-06-27: Profile APK 30-Minute Idle Request And Power Soak

Scope: prove a profile APK open on a real server-wide selected-agent page can
remain untouched for 30 minutes without hidden gateway polling, memory drift,
wake locks, skipped frames, or fatal Android logcat events.

Evidence:

- [local-avd-profile-30m-idle-soak-20260627.json](local-avd-profile-30m-idle-soak-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-30m-idle-soak-20260627.log`

Environment:

- mobile app head:
  `7898851 docs: record profile scrolled desktop sync smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19187` with request proxy
  `http://127.0.0.1:19188`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626222109`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` opened a
  real selected-agent page, emitted `CCB_IDLE_AUDIT_END selected-agent`, and
  ended with `30:11 +2: All tests passed!`;
- during the `1800` second idle audit window, the request proxy observed
  `0` total requests, `0` conversation requests, and `0` terminal-history
  requests;
- after the audit window, the final proxy count was exactly one explicit
  selected-agent conversation refresh;
- device metrics collected `31` meminfo/top samples, PSS delta was `767 KB`
  (`0.52%` growth), wake locks reported `Wake Locks: size=0` and
  `mWakeLockSummary=0x0`, logcat had no FATAL/ANR/OOM and no skipped-frame
  markers, and the metrics collector reported no warnings or errors.

Plan impact:

- closes profile-mode 30-minute selected-agent idle request-rate/power soak
  for the real server-wide Android Emulator path;
- does not close release-mode power, release frame/memory pressure, or the
  non-Flutter-Driver release harness.

### 2026-06-27: Profile APK Scrolled-Away Desktop-Origin Sync Real AVD Smoke

Scope: prove a profile APK can stay on a real selected-agent timeline, scroll
away from the newest turn, accept direct desktop pane input, refresh explicitly,
show a new-message affordance, and jump to the new provider-native turn without
reopening the project or falling back to stale ask/job history.

Evidence:

- [local-avd-profile-scrolled-desktop-sync-smoke-20260627.json](local-avd-profile-scrolled-desktop-sync-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-scrolled-desktop-sync-smoke-20260627-fixed-source.log`

Environment:

- mobile app head:
  `dc1e44e test: clear stale new-message affordance in desktop sync smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7e436f7e fix: order mobile native transcript pages by record time`;
- backend gateway: `http://127.0.0.1:19186` with
  `adb reverse tcp:19186 tcp:19186`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626221442`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/native_pane_desktop_sync_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, loaded `56` mixed provider-native backfill
  turns, scrolled away from the newest turn with `22` timeline drags, and
  printed `CCB_DESKTOP_SYNC_SCROLLED_AWAY 22`;
- the host pasted `DESKTOP_ORIGIN_SYNC_MARKER_20260626221442` into the real
  selected tmux pane `%2`, waited `30` seconds, and then the app surfaced the
  new-message affordance only after explicit refresh;
- the app jumped to the pane-injected marker and the Flutter run ended with
  `00:46 +2: All tests passed!`;
- source-side evidence reported `jobs_matches=[]`,
  `prompt_contains_ccb_req_id=false`, `prompt_contains_mobile_gateway=false`,
  and `user_match_count=1`;
- source commit `7e436f7e` fixed native transcript pagination by sorting
  Codex rollout items by record timestamp across threads, so newer pane input
  is no longer hidden ahead of older backfill thread records.

Plan impact:

- closes the profile-mode scrolled-away explicit-refresh and new-message
  behavior smoke for real server-wide Android Emulator validation;
- does not close release-mode frame/memory/power pressure or the
  non-Flutter-Driver release harness.

### 2026-06-27: Profile APK Server-Wide File/Image Real AVD Smoke

Scope: prove a profile APK can use the server-wide gateway to list real
projects, open selected agents, send text+document and image attachments, and
download both backend native artifacts and sent attachment files with matching
hashes.

Evidence:

- [local-avd-profile-server-wide-gateway-smoke-20260627.json](local-avd-profile-server-wide-gateway-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-server-wide-gateway-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `168db3d test: stabilize profile gateway smoke text entry`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19174` with
  `adb reverse tcp:19174 tcp:19174`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626213707`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_gateway_smoke_test.dart` opened
  selected-agent workspaces in profile mode;
- the run sent text+document and image attachments across
  `alpha/mobile_probe`, `alpha/mobile_peer`, and `beta/mobile_probe`;
- Android downloaded `9` files into app storage, including backend native
  text/image artifacts plus sent text/image/doc attachments, and every
  SHA256 matched the source fixture;
- the same profile run also executed the server-wide upward-scroll backfill
  smoke target;
- the Flutter run ended with `01:32 +3: All tests passed!`.

Plan impact:

- closes the profile-mode server-wide selected-agent file/image upload plus
  hash download smoke for real Android Emulator validation;
- does not close release-mode file performance or release-mode persistence.

### 2026-06-27: Profile APK Idle Request-Rate And Power Real AVD Smoke

Scope: prove a profile APK open on a real selected-agent page does not run
blind conversation/terminal-history polling while untouched, and does not show
idle memory, wakelock, or fatal logcat drift.

Evidence:

- [local-avd-profile-idle-request-smoke-20260627.json](local-avd-profile-idle-request-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-idle-request-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `d84ae67 test: enable profile idle request smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19166` with request proxy
  `127.0.0.1:19167`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626212102`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`;
- the request proxy counted `0` total requests during the `180` second idle
  audit window, including `0` conversation requests and `0`
  terminal-history requests;
- the final proxy count was exactly `1` conversation request after the audit
  window, matching the explicit checkpoint refresh;
- device metrics recorded `7` meminfo/top samples, PSS delta `-3548 KB`,
  `Wake Locks: size=0`, `mWakeLockSummary=0x0`, no skipped frames, and no
  FATAL/ANR/OOM logcat markers;
- the Flutter run emitted `CCB_IDLE_AUDIT_END selected-agent` and ended with
  `03:10 +2: All tests passed!`.

Plan impact:

- closes the profile-mode selected-agent idle request-rate/power smoke for a
  real server-wide Android Emulator path;
- does not close release-mode request-rate/power soak or scrolled-away
  new-message behavior.

### 2026-06-27: Profile APK 8 MiB Background File Download Real AVD Smoke

Scope: prove a profile APK can download an `8 MiB` backend artifact from a
real selected-agent timeline, survive Android HOME/background and foreground
resume, and keep the saved bytes intact.

Evidence:

- [local-avd-profile-background-file-download-smoke-20260627.json](local-avd-profile-background-file-download-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-background-file-download-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `98dd216 test: enable profile background file smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19163` with
  `adb reverse tcp:19163 tcp:19163`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626211010`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, while the gateway listed `42` mounted
  projects total;
- Flutter integration
  `app/integration_test/server_wide_background_file_download_smoke_test.dart`
  opened `test_ccb2_alpha/mobile_probe`;
- the selected-agent timeline rendered
  `native-artifact-20260626211010-3935582.txt` from the provider-native
  artifact fixture;
- Android requested the artifact download, emitted
  `CCB_BACKGROUND_FILE_DOWNLOAD_READY`, then the harness sent Android HOME
  and resumed `MainActivity` after `10` seconds;
- the app emitted `CCB_DOWNLOAD_SHA256` for
  `/data/user/0/io.ccb.mobile.ccb_mobile/app_flutter/native-artifact-20260626211010-3935582.txt`;
- saved size was `8388608` bytes and SHA256 matched
  `729e50a8809539bdb9bb357a9eec0555fdb8bc955e8c307bf9e7a07691ea8f84`;
- the Flutter run emitted `CCB_BACKGROUND_FILE_DOWNLOAD_DONE` and ended with
  `00:16 +2: All tests passed!`.

Plan impact:

- closes profile-mode `8 MiB` background/resume artifact download for a real
  server-wide Android Emulator path;
- does not close release-mode file performance or release-mode persistence.

### 2026-06-27: Profile APK Live Provider Artifact Download Real AVD Smoke

Scope: prove a profile APK can open a real server-wide project, pick up a
provider-created artifact link from the selected agent pane through explicit
refresh, and download the artifact bytes through the mobile gateway.

Evidence:

- [local-avd-profile-live-artifact-smoke-20260627.json](local-avd-profile-live-artifact-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-live-artifact-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `46fe77c test: drive live artifact smoke through real pane`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19161` with
  `adb reverse tcp:19161 tcp:19161`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626210228`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, while the gateway listed `42` mounted
  projects total;
- Flutter integration
  `app/integration_test/server_wide_live_artifact_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, emitted `CCB_LIVE_ARTIFACT_READY`, then
  explicit-refreshed until the generated artifact link appeared;
- the host harness pasted the artifact request into the actual selected tmux
  pane `%2` instead of using `ccb ask` or a mobile message route;
- the live provider created
  `mobile-live-artifact-20260626210228-3590796.txt` in the project root;
- gateway metadata registered the file as
  `mobile-file-58bf85e0c24959ad81b48f24`;
- Android downloaded `43` bytes and SHA256 matched
  `49548f8b886e293c09dafbdf5b8f3e6db5dfd0637f0cf20d83a30acb1ab557c0`;
- source-side evidence reported `jobs_matches=[]`,
  `prompt_contains_ccb_req_id=false`, `prompt_contains_mobile_gateway=false`,
  `user_match_count=2`, and `reply_match_count=1`;
- the Flutter run emitted `CCB_LIVE_ARTIFACT_SMOKE_DONE` and ended with
  `00:44 +2: All tests passed!`.

Plan impact:

- closes profile-mode live provider-created text artifact download for a real
  server-wide Android Emulator path;
- does not close release-mode file performance, large-file pressure, or file
  persistence under release conditions.

### 2026-06-27: Profile APK Mixed-History Backfill Real AVD Smoke

Scope: prove the server-wide selected-agent backfill path works in a profile
APK against a real Android Emulator and provider-native long-history fixture.

Evidence:

- [local-avd-profile-backfill-smoke-20260627.json](local-avd-profile-backfill-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-profile-backfill-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `cec4f9c test: enable profile mobile backfill smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19153` with
  `adb reverse tcp:19153 tcp:19153`;
- device: Android Emulator `emulator-5554`;
- Flutter build mode: profile APK via `flutter drive --profile`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626203025`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_gateway_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe` using an explicit profile-test paired-host
  seed;
- the provider-native dataset contained `200` turns, Markdown headings,
  tables, code blocks, duplicate short prompts, and document/image artifact
  links;
- the app rendered the latest selected-agent content in `116 ms`, loaded older
  selected-agent content after `92` upward drags in `46405 ms`, and settled in
  `112 ms`;
- gateway-side page timings were `27.344 ms` for latest, `144.704 ms` for the
  older page, and `19.763 ms` for the oldest page;
- the Flutter run emitted `CCB_BACKFILL_METRICS` and ended with
  `All tests passed.`

Plan impact:

- closes profile-mode 200-turn backfill smoke evidence for real server-wide
  Android Emulator validation;
- does not close release-mode frame/memory pressure, profile/release file
  pressure, or profile/release recovery/soak.

### 2026-06-27: Attachment Rejection Real AVD Smoke

Scope: prove unsupported and oversized local attachments are rejected before
draft creation on a real server-wide Android Emulator path.

Evidence:

- [local-avd-attachment-rejection-smoke-20260627.json](local-avd-attachment-rejection-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-attachment-rejection-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `d01c322 fix: reject unsupported mobile attachments`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19151` with
  `adb reverse tcp:19151 tcp:19151`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626201614`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_attachment_rejection_smoke_test.dart`
  opened `test_ccb2_alpha/mobile_probe` from the server-wide project list;
- selecting `installer.exe` showed
  `installer.exe is not a supported attachment type` and left no
  `agent-attachment-tray`;
- selecting `too-large.pdf` showed `too-large.pdf is larger than 25 MB` and
  left no `agent-attachment-tray`;
- the selected-agent UI contained no `CCB_REQ_ID`, no `mobile_gateway`, and
  no `completion_snapshot`;
- the Flutter run emitted `CCB_ATTACHMENT_REJECTION_SMOKE_DONE` and ended
  with `00:12 +1: All tests passed!`.

Plan impact:

- closes the debug-mode oversized/unsupported attachment rejection gate for a
  real server-wide Android Emulator path;
- does not close profile/release file performance or successful
  upload/download pressure.

### 2026-06-27: Failed Send Gateway-Restart Replay Real AVD Smoke

Scope: prove a failed selected-agent send with a local attachment remains
visible and retryable across server-wide gateway process stop/restart plus
Android app force-stop/restart, then reaches the real selected agent pane
exactly once.

Evidence:

- [local-avd-replay-gateway-restart-smoke-20260627.json](local-avd-replay-gateway-restart-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-replay-gateway-restart-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `d6b4790 test: add gateway restart replay smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19147` with
  `adb reverse tcp:19147 tcp:19147`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626195641`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/native_pane_replay_guard_smoke_test.dart` ran in two
  stages with `--no-uninstall`: the failed stage stopped the gateway process,
  sent a prompt plus `replay-guard-attachment.txt`, waited for `Retry`, and
  emitted `CCB_REPLAY_GUARD_FAILED_PERSIST_READY`;
- the harness force-stopped `io.ccb.mobile.ccb_mobile`, restarted the
  server-wide gateway on the same loopback port and state directory, restarted
  the same integration test in retry mode, restored the failed draft from app
  storage, tapped `Retry`, and emitted `CCB_REPLAY_GUARD_DONE`;
- source-side native transcript evidence reported `user_match_count=1`,
  `reply_match_count=1`, `jobs_matches=[]`,
  `prompt_contains_ccb_req_id=false`, and
  `prompt_contains_mobile_gateway=false`;
- both Flutter stages ended with `All tests passed!`, the gateway stop event
  returned `-15`, the gateway start event returned a fresh healthy gateway
  summary, and host `force_stop_returncode=0`.

Plan impact:

- closes the smoke-level failed-send draft persistence-after-gateway-restart
  gate for a real server-wide Android Emulator path;
- does not close oversized/unsupported file rejection or profile/release file
  pressure.

### 2026-06-27: Failed Send Replay-Restart Real AVD Smoke

Scope: prove a failed selected-agent send with a local attachment remains
visible and retryable after Android app force-stop/restart, then reaches the
real selected agent pane exactly once after gateway connectivity is restored.

Evidence:

- [local-avd-replay-restart-smoke-20260627.json](local-avd-replay-restart-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-replay-restart-smoke-20260627-clean.log`

Environment:

- mobile app head:
  `0b2715e fix: persist failed mobile attachment retries`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19145` with
  `adb reverse tcp:19145 tcp:19145`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626194623`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/native_pane_replay_guard_smoke_test.dart` ran in two
  stages with `--no-uninstall`: the failed stage removed `adb reverse`, sent a
  prompt plus `replay-guard-attachment.txt`, waited for `Retry`, and emitted
  `CCB_REPLAY_GUARD_FAILED_PERSIST_READY`;
- the harness force-stopped `io.ccb.mobile.ccb_mobile`, restored
  `adb reverse`, restarted the same integration test in retry mode, restored
  the failed draft from app storage, tapped `Retry`, and emitted
  `CCB_REPLAY_GUARD_DONE`;
- source-side native transcript evidence reported `user_match_count=1`,
  `reply_match_count=1`, `jobs_matches=[]`,
  `prompt_contains_ccb_req_id=false`, and
  `prompt_contains_mobile_gateway=false`;
- both Flutter stages ended with `All tests passed!`, and host
  `force_stop_returncode=0`.

Plan impact:

- closes the smoke-level failed-send draft persistence-after-app-restart gate
  for a real server-wide Android Emulator path;
- does not close oversized/unsupported file rejection, gateway-restart
  failed-draft persistence, or profile/release file pressure.

### 2026-06-27: File Download App-Restart Persistence Real AVD Smoke

Scope: prove a downloaded backend artifact remains in Android app storage and
keeps the same bytes after the app process is force-stopped and restarted.

Evidence:

- [local-avd-file-restart-smoke-20260627.json](local-avd-file-restart-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-file-restart-smoke-20260627031141.log`

Environment:

- mobile app head:
  `57907ba test: add mobile file restart smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19142` with
  `adb reverse tcp:19142 tcp:19142`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626191141`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_background_file_download_smoke_test.dart`
  opened `test_ccb2_alpha/mobile_probe`, downloaded
  `native-artifact-20260626191141-2937442.txt`, and emitted
  `CCB_DOWNLOAD_SHA256` with path
  `/data/user/0/io.ccb.mobile.ccb_mobile/app_flutter/native-artifact-20260626191141-2937442.txt`;
- the harness kept the app installed with `--no-uninstall`, then
  force-stopped `io.ccb.mobile.ccb_mobile`, restarted `.MainActivity`, and
  read the saved file from the app sandbox using `run-as`;
- post-restart file SHA256 matched the original download hash
  `bb6eff9d9703242eeeddf8fae1867f8a0688f88bc93e36861cc9f011bcb37fb5`;
- the Flutter run ended with `00:12 +1: All tests passed!`, and the host
  restart/hash check passed with `force_stop_returncode=0` and
  `restart_returncode=0`.

Plan impact:

- closes the smoke-level downloaded artifact persistence-after-app-restart
  gate for a real server-wide Android Emulator path;
- does not close unsupported/oversized file errors, failed-send draft
  persistence across app restart, or profile/release file pressure.

### 2026-06-27: 30-Minute Idle/Power Real AVD Soak

Scope: prove the selected-agent screen does not run blind
conversation/terminal-history refreshes and does not show obvious memory,
wake-lock, or fatal-logcat pressure over a 30-minute real Android Emulator
idle window.

Evidence:

- [local-avd-idle-30m-soak-20260627.json](local-avd-idle-30m-soak-20260627.json)
- raw log:
  `/tmp/ccb-mobile-idle-30m-soak-20260627023102.log`

Environment:

- mobile app head:
  `07513c2 docs: record 10 minute idle avd soak`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19139`, request proxy
  `127.0.0.1:19140`, and `adb reverse tcp:19140 tcp:19140`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626183102`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, emitted `CCB_IDLE_AUDIT_BEGIN`, held the
  selected-agent page idle for `1800` seconds, then emitted
  `CCB_IDLE_AUDIT_END`;
- request proxy counts during the idle window were exactly zero:
  `total_requests=0`, `conversation_requests=0`,
  `terminal_history_requests=0`;
- after the audit window, manual refresh generated exactly one conversation
  request, proving the gateway path remained usable;
- ADB metrics collected `16` meminfo/top samples, PSS delta was `-732 KB`
  (`-0.0023` growth ratio), power reported `Wake Locks: size=0` and
  `mWakeLockSummary=0x0`, and logcat had no FATAL/ANR/OOM markers;
- the Flutter run ended with `30:12 +1: All tests passed!`.

Plan impact:

- closes the debug-mode 30-minute idle/power soak gate for the current
  explicit-refresh design;
- profile/release frame timing and profile/release recovery pressure remain
  open.

### 2026-06-27: 10-Minute Idle/Performance Real AVD Soak

Scope: extend the accepted no-idle-polling device-metrics gate from a short
window to a 10-minute real Android Emulator selected-agent idle soak.

Evidence:

- [local-avd-idle-10m-soak-20260627.json](local-avd-idle-10m-soak-20260627.json)
- raw log:
  `/tmp/ccb-mobile-idle-10m-soak-20260627021710.log`

Environment:

- mobile app head:
  `075dcf4 docs: record live provider artifact avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19137`, request proxy
  `127.0.0.1:19138`, and `adb reverse tcp:19138 tcp:19138`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626181710`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, emitted `CCB_IDLE_AUDIT_BEGIN`, held the
  selected-agent page idle for `600` seconds, then emitted
  `CCB_IDLE_AUDIT_END`;
- request proxy counts during the idle window were exactly zero:
  `total_requests=0`, `conversation_requests=0`,
  `terminal_history_requests=0`;
- after the audit window, manual refresh generated exactly one conversation
  request, proving the gateway path remained usable;
- ADB metrics collected `11` meminfo/top samples, PSS delta was `24 KB`
  (`0.0001` growth ratio), power reported `Wake Locks: size=0` and
  `mWakeLockSummary=0x0`, and logcat had no FATAL/ANR/OOM markers;
- the Flutter run ended with `10:12 +1: All tests passed!`.

Plan impact:

- strengthens the no-blind-refresh and low-idle-pressure evidence for the
  current explicit-refresh design;
- does not replace the remaining 30-minute profile/release soak requirement.

### 2026-06-27: Live Provider Artifact Download Real AVD Smoke

Scope: prove a real provider can create a workspace file during a selected
agent turn, have the gateway expose the markdown file link as a mobile
downloadable artifact, and have the Android app download the exact bytes.

Evidence:

- [local-avd-live-provider-artifact-smoke-20260627.json](local-avd-live-provider-artifact-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-live-artifact-smoke-20260627020758.log`

Environment:

- mobile app head:
  `0ab8956 test: add live provider artifact smoke`;
- source worktree:
  `/tmp/ccb-source-live-artifact-ac2626ac-4084005`;
- source head: `ac2626ac fix: default mobile terminal attach term`;
- backend gateway: `http://127.0.0.1:19136` with
  `adb reverse tcp:19136 tcp:19136`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626180758`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- the app opened `test_ccb2_alpha/mobile_probe` and sent a pane-backed prompt
  asking the live Codex provider to create
  `mobile-live-artifact-20260626180758-134252.txt` in the project root;
- the provider-created file existed under the real project root with SHA256
  `c57f55752e52f9af4f7b29aeb9b4f9f7763f69f9234f6227c3a93fe6fd87d8d0`;
- gateway metadata registered the workspace link as
  `mobile-file-f14dc5b0831c07028df8d0a9` with the same SHA256 and size
  `42` bytes;
- Flutter integration
  `app/integration_test/server_wide_live_artifact_smoke_test.dart` tapped the
  downloadable attachment chip and emitted matching `CCB_DOWNLOAD_SHA256` and
  `CCB_LIVE_ARTIFACT_SMOKE_DONE` hashes;
- source-side evidence reported `jobs_matches: []`,
  `prompt_contains_ccb_req_id: false`,
  `prompt_contains_mobile_gateway: false`, `user_match_count: 1`, and
  `reply_match_count: 1`.

Plan impact:

- closes the smoke-level live provider-created text artifact download gate on
  a real server-wide Android Emulator path;
- does not close oversized/unsupported file errors, retry, app restart
  persistence, profile/release file performance, or long power/performance
  soak.

### 2026-06-27: Mixed 200-Turn Native History Real AVD Smoke

Scope: prove the app can load a controlled `200` turn provider-native Codex
history with Markdown tables/code blocks, duplicate short prompts, and
document/image artifact links through the real server-wide gateway on Android
Emulator.

Evidence:

- [local-avd-mixed-history-backfill-smoke-20260627.json](local-avd-mixed-history-backfill-smoke-20260627.json)

Environment:

- mobile app head:
  `b611e8a test: add mixed history fixture coverage`;
- source worktree:
  `/tmp/ccb-source-agent-native-7fece763`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19133` with
  `adb reverse tcp:19133 tcp:19133`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626173557`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- the harness seeded `200` Codex-native provider transcript turns for
  `test_ccb2_alpha/mobile_probe`, including Markdown headings, tables, code
  blocks, duplicate `hi` prompts, and `ccb-artifact://` links for one Markdown
  document and one PNG image;
- source-side gateway conversation checks reached the latest marker in one
  poll, then paged through `7` older pages to the oldest marker;
- Flutter integration
  `app/integration_test/server_wide_gateway_smoke_test.dart` ran the
  backfill-only path and reached the oldest marker after `92` upward drags;
- emitted metrics were `latest_visible_ms=119`, `older_visible_ms=47146`,
  `post_backfill_settle_ms=116`, and `total_ms=50545`, and the test ended
  with `All tests passed`.

Plan impact:

- closes the debug real-AVD 200-turn mixed native-history upward-pagination
  smoke gate;
- does not close profile/release frame and memory pressure, scroll-position
  stability beyond marker visibility, live provider-generated artifact
  creation, retry/restart persistence, or 30-minute power soak.

### 2026-06-27: Revoke/Re-Pair Real AVD Smoke

Scope: prove a paired mobile device fails closed after revocation, then can
re-pair through the app UI without clearing app data and recover protected
selected-agent refresh.

Evidence:

- [local-avd-revoke-repair-smoke-20260627.json](local-avd-revoke-repair-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-revoke-repair-smoke-20260627005524.log`

Environment:

- mobile app head:
  `a57fc92 test: add mobile revoke repair smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19072` with
  `adb reverse tcp:19072 tcp:19072`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626165524`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened
  `test_ccb2_alpha/mobile_probe`;
- the app started with an initial paired profile, then Flutter integration
  `app/integration_test/server_wide_revoke_repair_smoke_test.dart` emitted
  `CCB_REPAIR_READY_REVOKE`;
- the host harness revoked the initial device
  `avd_20260626165524`, then verified the old token failed closed on
  `/v1/devices/me` with HTTP `401` and body `device token revoked`;
- the app tapped selected-agent refresh and observed the protected refresh
  failure, then opened Connection Details and claimed a new pairing token
  `pair_355f43918c137673` through the normal UI;
- after `Gateway paired`, the app returned to the real selected project/agent,
  refreshed successfully, and ended with `CCB_REPAIR_DONE` and
  `All tests passed`.

Plan impact:

- closes the smoke-level revoke/re-pair recovery gate for a real server-wide
  Android Emulator path without clearing app data;
- does not close longer profile/release recovery pressure, live
  provider-generated artifact edge cases, 200+ mixed-history pressure, or
  30-minute power soak.

### 2026-06-27: Replay-Guard Real AVD Smoke

Scope: prove a failed selected-agent send with an attachment remains
retryable after gateway path loss and does not duplicate pane input when the
user explicitly retries.

Evidence:

- [local-avd-replay-guard-smoke-20260627.json](local-avd-replay-guard-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-replay-guard-smoke-20260627003344.log`

Environment:

- mobile app head:
  `952f2b2 test: add mobile replay guard smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19070` with
  `adb reverse tcp:19070 tcp:19070`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626163344`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened
  `test_ccb2_alpha/mobile_probe`;
- Flutter integration
  `app/integration_test/native_pane_replay_guard_smoke_test.dart` selected a
  real pane-backed agent, attached `replay-guard-attachment.txt`, and emitted
  `CCB_REPLAY_GUARD_REMOVE_REVERSE_READY`;
- the host harness removed `adb reverse tcp:19070`, the app send failed
  visibly, and the failed message retained both the prompt and attachment
  filename;
- after the harness restored `adb reverse tcp:19070 tcp:19070`, the test
  tapped `Retry` exactly once and waited for the expected provider reply
  `CCB_MOBILE_REPLAY_OK_20260626163344`;
- source-side native transcript evidence found `user_match_count == 1`,
  `reply_match_count == 1`, no CCB jobs matches, no `CCB_REQ_ID`, and no
  `mobile_gateway` pollution.

Plan impact:

- closes the smoke-level pending draft/attachment preservation and duplicate
  terminal-input replay guard for recoverable gateway-path failure on a real
  server-wide Android Emulator path;
- does not close live provider-generated artifact edge cases, 200+
  mixed-history profile/release pressure, or 30-minute power soak.

### 2026-06-27: Background File-Download Real AVD Smoke

Scope: prove a real selected-agent backend artifact download can survive an
Android HOME/background and foreground resume cycle, then still save the exact
file on the emulator.

Evidence:

- [local-avd-background-file-download-smoke-20260627.json](local-avd-background-file-download-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-background-file-download-smoke-20260627002153.log`

Environment:

- mobile app head:
  `f598ee5 test: add mobile background file download smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19069` with
  `adb reverse tcp:19069 tcp:19069`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626162153`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened
  `test_ccb2_alpha/mobile_probe`;
- the harness seeded native Codex artifact links and a deterministic
  `8,388,608` byte text artifact in the server-wide gateway file store;
- Flutter integration
  `app/integration_test/server_wide_background_file_download_smoke_test.dart`
  tapped the artifact chip and emitted
  `CCB_BACKGROUND_FILE_DOWNLOAD_READY`;
- the host harness sent Android `HOME`, waited `10` seconds, and relaunched
  `io.ccb.mobile.ccb_mobile/.MainActivity`;
- after foregrounding, the selected-agent workspace/composer remained visible,
  the app showed `Saved native-artifact-20260626162153-3775658.txt`, and the
  saved file SHA256 matched
  `eecfa42d3fd9f01ff02adea842a88f5ffb7234bb72040a80df42aec56db7d3f2`;
- no `CCB_REQ_ID`, `mobile_gateway`, or `completion_snapshot` labels were
  visible, and the integration run ended with `All tests passed`.

Plan impact:

- closes the file-download background/resume subgate for a backend artifact on
  a real server-wide Android Emulator path;
- does not close pending draft/file preservation, duplicate input replay,
  revoke/re-pair, live provider-generated artifacts, or profile/release soak.

### 2026-06-27: Background Reverse-Recovery Real AVD Smoke

Scope: prove an already-open real selected-agent page survives Android
backgrounding while the emulator loses and regains its `adb reverse` gateway
path, then remains usable for explicit conversation refresh.

Evidence:

- [local-avd-background-reverse-recovery-smoke-20260627.json](local-avd-background-reverse-recovery-smoke-20260627.json)
- raw log:
  `/tmp/ccb-mobile-background-reverse-smoke-20260627000711.log`

Environment:

- mobile app head:
  `da99280 test: add mobile background reverse recovery smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19068` with
  `adb reverse tcp:19068 tcp:19068`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626160711`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened
  `test_ccb2_alpha/mobile_probe`;
- Flutter integration
  `app/integration_test/server_wide_background_reverse_recovery_smoke_test.dart`
  waited for the selected-agent workspace/composer and emitted
  `CCB_BACKGROUND_REVERSE_READY selected-agent`;
- the host harness sent Android `HOME`, removed
  `adb reverse tcp:19068`, waited `10` seconds, restored
  `adb reverse tcp:19068 tcp:19068`, and relaunched
  `io.ccb.mobile.ccb_mobile/.MainActivity`;
- after foregrounding, the selected-agent workspace/composer remained visible,
  no `CCB_REQ_ID`, `mobile_gateway`, or `completion_snapshot` labels were
  visible, and explicit selected-agent refresh completed;
- the integration run returned `0` and ended with `All tests passed`.

Plan impact:

- closes the reverse-loss-while-backgrounded selected-agent subgate for a real
  server-wide Android Emulator path;
- does not close the full background/recovery gate: file-download
  background/resume, pending draft/file preservation, duplicate input replay,
  and revoke/re-pair evidence remain open.

### 2026-06-26: Background/Resume Real AVD Smoke

Scope: prove an already-open real selected-agent page survives a real Android
HOME/background and foreground resume cycle, then remains usable for explicit
conversation refresh.

Evidence:

- [local-avd-background-resume-smoke-20260626.json](local-avd-background-resume-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-background-resume-smoke-20260626235602.log`

Environment:

- mobile app head:
  `69bbe32 test: add mobile background resume avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19067` with
  `adb reverse tcp:19067 tcp:19067`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626155602`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and `/v1/projects` returned the mixed
  server-wide list including the new disposable projects;
- Flutter integration
  `app/integration_test/server_wide_background_resume_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, waited for the selected-agent composer and
  refresh button, and emitted `CCB_BACKGROUND_RESUME_READY`;
- the host harness sent a real Android `HOME` key event, waited `10` seconds,
  and relaunched `io.ccb.mobile.ccb_mobile/.MainActivity`; Android reported
  the existing task was brought to the front;
- after resume, the app still showed `selected-agent-workspace` and
  `agent-message-composer`, did not show `agent-conversation-loading`, and
  did not show `CCB_REQ_ID`, `mobile_gateway`, or `completion_snapshot`;
- the test triggered explicit selected-agent refresh after resume and
  completed with `All tests passed`.

Plan impact:

- closes the selected-agent page portion of C9.3/D8 background/resume for a
  real server-wide Android Emulator path;
- does not close the full background/resume gate: file-download-in-background,
  reverse-loss-while-backgrounded, draft/attachment preservation, and replay
  guard evidence remain open.

### 2026-06-26: Idle Metrics Real AVD Smoke

Scope: extend the no-idle-polling smoke with device-level debug metrics from
the same untouched selected-agent window.

Evidence:

- [local-avd-idle-metrics-smoke-20260626.json](local-avd-idle-metrics-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-idle-metrics-smoke-20260626233219.log`

Environment:

- mobile app head:
  `09962f6 test: collect idle device metrics in avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19065`;
- counting proxy: `127.0.0.1:19066` with
  `adb reverse tcp:19066 tcp:19066`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626153219`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened a real selected-agent
  page through the counting proxy;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` marked a
  180-second untouched idle audit window, and the host harness sampled
  `top`, `dumpsys meminfo`, `dumpsys power`, package `batterystats`,
  `gfxinfo`, and logcat;
- during the audit window, the proxy counted `0` total gateway requests,
  `0` selected-agent conversation requests, `0` terminal-history requests,
  and `0.0` conversation/terminal requests per minute;
- device metrics recorded seven samples, PSS delta `-508 KB`, PSS growth
  ratio `-0.0016`, `Wake Locks: size=0`, `mWakeLockSummary=0x0`, no
  collection warnings, and no FATAL/ANR/OOM;
- after the audit window, the test triggered one explicit selected-agent
  refresh and the proxy final counters showed one
  `/v1/projects/{project}/agents/{agent}/conversation` request, proving the
  counter window still distinguishes idle from manual refresh.

Plan impact:

- closes the debug C4.3 request-count evidence and strengthens C10.1 debug
  preflight with memory, wake-lock, gfxinfo, and logcat metrics on a real
  server-wide Android Emulator path;
- does not close the full C10.1 release gate: profile/release 30-minute soak,
  sustained CPU/frame/memory trends, and app-specific battery attribution
  remain open.

### 2026-06-26: Idle Request-Rate Real AVD Smoke

Scope: prove an already-open selected-agent page does not silently poll
conversation or terminal-history endpoints while the phone is untouched.

Evidence:

- [local-avd-idle-request-smoke-20260626.json](local-avd-idle-request-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-idle-request-smoke-20260626230715.log`

Environment:

- mobile app head:
  `6797b14 test: add mobile idle request avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- backend gateway: `http://127.0.0.1:19057`;
- counting proxy: `127.0.0.1:19058` with
  `adb reverse tcp:19058 tcp:19058`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626150715`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and the app opened a real selected-agent
  page through the counting proxy;
- Flutter integration
  `app/integration_test/server_wide_idle_request_smoke_test.dart` waited for
  the selected-agent page to settle, marked `CCB_IDLE_AUDIT_BEGIN`, left the
  emulator untouched for `180` seconds, and marked `CCB_IDLE_AUDIT_END`;
- during the audit window, the proxy counted `0` total gateway requests,
  `0` selected-agent conversation requests, `0` terminal-history requests,
  and `0.0` conversation/terminal requests per minute;
- after the audit window, the test triggered one explicit selected-agent
  refresh and the proxy final counters showed one
  `/v1/projects/{project}/agents/{agent}/conversation` request, proving the
  counter window distinguishes idle from manual refresh;
- the app asserted no `CCB_REQ_ID`, `mobile_gateway`, or
  `completion_snapshot` labels were visible on the selected-agent surface.

Plan impact:

- closes the C4.3 debug request-rate smoke for "no blind 3-second polling" on
  a real server-wide Android Emulator path;
- does not close the full C10.1 release gate: profile/release CPU, memory,
  wake-lock, frame, and 30-minute soak evidence remain open.

### 2026-06-26: Project ccbd-Restart Real AVD Smoke

Scope: prove the app can recover on an already-open selected-agent page when
that project's real `ccbd` is stopped and restarted while the server-wide
mobile gateway and `adb reverse` path remain up.

Evidence:

- [local-avd-ccbd-restart-smoke-20260626.json](local-avd-ccbd-restart-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-ccbd-restart-smoke-20260626223936.log`

Environment:

- mobile app head:
  `6372afb test: add mobile ccbd restart avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- gateway: `http://127.0.0.1:19054` with
  `adb reverse tcp:19054 tcp:19054`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626143936`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and `/v1/projects` returned a mixed
  server-wide list including the new disposable projects;
- Flutter integration
  `app/integration_test/server_wide_ccbd_restart_smoke_test.dart` opened
  `test_ccb2_alpha/mobile_probe`, emitted a host-side stop marker, and
  verified `Conversation refresh failed` after the selected project's ccbd was
  killed;
- the harness restarted only that project's ccbd with the same project id and
  socket path shape while keeping the gateway and emulator reverse mapping up;
- the app recovered through explicit selected-agent refresh retry on the same
  open project without clearing app data, re-pairing, or reopening the
  project;
- the app asserted no `CCB_REQ_ID`, `mobile_gateway`, or
  `completion_snapshot` labels were visible on the selected-agent surface.

Plan impact:

- closes the project-ccbd restart smoke portion of C9.1/Stage 9 recovery for
  selected-agent explicit refresh on a real server-wide Android Emulator path;
- does not close the full recovery/security bundle: revoke/re-pair,
  background/resume, longer request-rate, pending draft/file preservation, and
  duplicate terminal-input replay evidence remain open.

### 2026-06-26: Gateway-Restart Real AVD Smoke

Scope: prove the app can recover by explicit user retry/refresh when the real
server-wide mobile gateway process is stopped and restarted on the same
loopback port, without clearing app data or re-pairing.

Evidence:

- [local-avd-gateway-restart-smoke-20260626.json](local-avd-gateway-restart-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-gateway-restart-smoke-20260626210325.log`

Environment:

- mobile app head:
  `b584d74 test: add mobile gateway restart avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- gateway: `http://127.0.0.1:19049` with
  `adb reverse tcp:19049 tcp:19049`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626130325`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and `/v1/projects` returned a mixed
  server-wide list including the new disposable projects;
- Flutter integration
  `app/integration_test/server_wide_gateway_restart_smoke_test.dart` first
  stayed on the server-wide project list, emitted a host-side stop marker,
  and verified the project-list refresh failure while the gateway process was
  stopped;
- the harness terminated the real gateway process, then restarted it on the
  same `127.0.0.1:19049` listener and same state directory; the app tapped
  Retry and recovered the project list without clearing app data;
- the test then opened `test_ccb2_alpha/mobile_probe`, stopped/restarted the
  same gateway again, verified `Conversation refresh failed`, and verified
  explicit selected-agent refresh recovered on the same open project;
- both gateway stop events were real process terminations, and both restart
  events produced a fresh gateway with the same local URL and pairing claim
  endpoint;
- the app asserted no `CCB_REQ_ID`, `mobile_gateway`, or
  `completion_snapshot` labels were visible on the selected-agent surface.

Plan impact:

- closes the gateway-process restart smoke portion of C9.1/Stage 9 recovery
  for project-list and selected-agent explicit refresh;
- does not close the full recovery/security bundle: revoke/re-pair,
  background/resume, longer request-rate, pending draft/file preservation, and
  duplicate terminal-input replay evidence remain open.

### 2026-06-26: Reverse-Recovery Real AVD Smoke

Scope: prove the app can surface project-list and selected-agent refresh
failures when the Android Emulator loses its host gateway path, then recover
after `adb reverse` is restored and the user explicitly retries/refreshes.

Evidence:

- [local-avd-reverse-recovery-smoke-20260626.json](local-avd-reverse-recovery-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-reverse-recovery-smoke-20260626200446.log`

Environment:

- mobile app head:
  `58c5f00 test: cover project list reverse recovery`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `7fece763 fix: expose native artifact links to mobile`;
- gateway: `http://127.0.0.1:19047` with
  `adb reverse tcp:19047 tcp:19047`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626120446`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and `/v1/projects` returned `42` mounted
  projects;
- Flutter integration
  `app/integration_test/server_wide_reverse_recovery_smoke_test.dart` first
  stayed on the server-wide project list, emitted a host-side recovery marker,
  and verified the project-list refresh failure and retry path;
- the harness removed the real emulator mapping with
  `adb reverse --remove tcp:19047`, the app tapped project-list refresh, and
  the UI showed `Could not load projects`;
- the harness restored `adb reverse tcp:19047 tcp:19047`, the app tapped
  Retry, and the server-wide project list returned without clearing app data;
- the test then opened `test_ccb2_alpha/mobile_probe`, removed/restored the
  same reverse mapping again, verified `Conversation refresh failed`, and
  verified explicit refresh cleared the failure item on the same open project;
- the app asserted no `CCB_REQ_ID`, `mobile_gateway`, or
  `completion_snapshot` labels were visible on the selected-agent surface.

Plan impact:

- closes the first C9.1 reverse-loss/recovery smoke for both project-list and
  selected-agent refresh on a real server-wide Android Emulator path;
- does not close the full recovery/security bundle: revoke/re-pair,
  background/resume, longer request-rate, and soak evidence remain open.

### 2026-06-26: Native File And Artifact Hash-Verified AVD Smoke

Scope: prove image/document attachment UI and backend artifact downloads can
work through the native selected-agent/server-wide mobile path and save the
expected bytes on the Android device, not the old ask/message fake reply route.

Evidence:

- [local-avd-native-file-artifact-smoke-20260626.json](local-avd-native-file-artifact-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-file-artifact-hash-server-wide-smoke-20260626193500.log`

Environment:

- mobile app head:
  `16e621e test: verify mobile downloaded file hashes`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head:
  `7fece763 fix: expose native artifact links to mobile`;
- gateway: `http://127.0.0.1:19042` with
  `adb reverse tcp:19042 tcp:19042`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626112747`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, and `/v1/projects` returned `43` mounted
  projects;
- source commit `7fece763` maps `ccb-artifact://...` links in Codex
  provider-native transcript messages to mobile downloadable attachment
  metadata;
- the integration test downloaded seeded native text and image artifacts from
  the selected-agent timeline:
  `native-artifact-20260626112747-2768766.txt` and
  `native-image-20260626112747-2768766.png`;
- the same run sent and downloaded text-file conversation attachments, sent
  image-only messages, crossed `mobile_probe` and `mobile_peer`, and opened
  both alpha and beta projects;
- the integration test read the saved files from
  `/data/user/0/io.ccb.mobile.ccb_mobile/app_flutter/...` and verified
  SHA256 for `9` downloaded files, including both seeded native artifacts,
  alpha/beta text attachments, and probe/peer images;
- Flutter integration
  `app/integration_test/server_wide_gateway_smoke_test.dart` passed both test
  cases on the emulator.

Plan impact:

- closes first C6.1/C6.2/C7.1 smoke coverage after native selected-agent chat
  routing became active, including on-device saved-file hash verification;
- does not close full file/artifact acceptance: live provider-generated
  artifact creation, oversized/unsupported retry, restart persistence, and
  profile/release file performance remain open.

### 2026-06-26: Long-History Provider-Native Backfill AVD Smoke

Scope: prove the app can load and render an older selected-agent native
transcript page from a real server-wide gateway without using `ccb ask` as the
seed path.

Evidence:

- [local-avd-long-history-backfill-smoke-20260626.json](local-avd-long-history-backfill-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-long-history-backfill-smoke-20260626183230.log`

Environment:

- mobile app head:
  `70e9af0 test: seed long-history native transcript smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19036` with
  `adb reverse tcp:19036 tcp:19036`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626103241`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway, alongside the machine's currently mounted
  projects;
- the long-history dataset wrote `56` Codex provider-native rollout turns into
  the disposable `test_ccb2_alpha/mobile_probe` agent state;
- the seed path did not call `ccb ask` or create jobs;
- gateway API timings were low for the synthetic native dataset:
  `/view` `24.287 ms`, latest page `4.81 ms`, two older pages total
  `12.556 ms`, oldest page `5.684 ms`;
- Android Emulator integration
  `integration_test/server_wide_gateway_smoke_test.dart` passed both
  server-wide and backfill cases;
- UI metrics reported latest content visible in `118 ms`, older content
  visible after upward scroll in `10049 ms`, total case time `14355 ms`, and
  `18` drag gestures.

Plan impact:

- closes a first C5.1 smoke for provider-native older-history pagination and
  rendering against a real server-wide gateway;
- does not close the full C5/C10 performance gate: the required
  `200+` mixed Markdown/image/document/artifact dataset, profile/release frame
  timings, memory, CPU, power, and live-provider long-turn latency remain
  open.

### 2026-06-26: Desktop-Origin Explicit-Refresh AVD Smoke

Scope: prove the selected-agent phone timeline can pick up text typed
directly into the desktop/server agent pane after an explicit app refresh,
without relying on the mobile send path or fake/demo history.

Evidence:

- [local-avd-desktop-origin-sync-smoke-20260626.json](local-avd-desktop-origin-sync-smoke-20260626.json)
- raw log:
  `/tmp/ccb-mobile-desktop-origin-sync-smoke-20260626103100.log`

Environment:

- mobile app head:
  `46829fb test: extend desktop-origin sync idle smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19031` with
  `adb reverse tcp:19031 tcp:19031`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626100818`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were mounted
  through the server-wide gateway;
- Flutter integration
  `integration_test/native_pane_desktop_sync_smoke_test.dart` passed on the
  emulator;
- the host injected
  `DESKTOP_ORIGIN_SYNC_MARKER_20260626100818` directly into
  `test_ccb2_alpha/mobile_probe` pane `%2` through the project tmux socket;
- the app asserted the marker was absent during a 30-second idle window, then
  visible after tapping the selected-agent conversation refresh action;
- native provider evidence found one matching user prompt, with
  `jobs_matches` empty, `prompt_contains_ccb_req_id` false, and
  `prompt_contains_mobile_gateway` false.

Plan impact:

- closes the first C4.1 desktop-origin explicit-refresh smoke for one real
  project/agent with the casebook-required 30-second no-refresh window;
- does not close the complete refresh/power bundle: longer idle request-rate,
  scrolled-away new-message behavior, older-history pagination, file/artifact
  transfer, disconnect/recovery, and soak remain open.

### 2026-06-26: Multi-Project Multi-Agent Native-Pane AVD Smoke

Scope: extend the real provider native-pane Android Emulator smoke from one
project/agent to two disposable `test_ccb2` projects and two agents, proving
ordinary phone sends can route to different real pane-backed agents without
ask-job metadata.

Evidence:

- [local-avd-native-pane-multi-smoke-20260626.json](local-avd-native-pane-multi-smoke-20260626.json)
- raw log: `/tmp/ccb-mobile-native-pane-multi-smoke-20260626093000.log`

Environment:

- mobile app head:
  `114c0c0 test: add multi-project native pane avd smoke`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19024` with
  `adb reverse tcp:19024 tcp:19024`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626093156`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were started with
  `mobile_probe` and `mobile_peer` as `codex` pane-backed agents;
- Flutter integration
  `integration_test/native_pane_multi_gateway_smoke_test.dart` passed on the
  emulator;
- the phone sent one deterministic prompt to `test_ccb2_alpha/mobile_probe`
  and one deterministic prompt to `test_ccb2_beta/mobile_peer`;
- native provider evidence found one matching user prompt and one matching
  reply for each selected project/agent rollout file;
- for both cases, `jobs_matches` was empty,
  `prompt_contains_ccb_req_id` was `false`, and
  `prompt_contains_mobile_gateway` was `false`.

Plan impact:

- strengthens C3.1/C3.2 from a single selected agent to a
  multi-project/multi-agent smoke;
- still does not close the complete goal: desktop-origin sync,
  older-history pagination, file/image upload, backend artifact download,
  disconnect/recovery, request-rate evidence, and soak remain open.

### 2026-06-26: Current Real Native-Pane Send/Reply AVD Smoke

Scope: rerun the real provider native-pane Android Emulator smoke after the
casebook artifact tooling landed, using fresh disposable `test_ccb2` projects.

Evidence:

- [local-avd-native-pane-smoke-20260626-092252.json](local-avd-native-pane-smoke-20260626-092252.json)
- raw log: `/tmp/ccb-mobile-native-pane-smoke-20260626092300.log`

Environment:

- mobile app head: `e00d5e4 test: emit casebook compass artifacts`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19023` with
  `adb reverse tcp:19023 tcp:19023`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626092252`.

Result:

- fresh real projects `test_ccb2_alpha` and `test_ccb2_beta` were started with
  `mobile_probe` and `mobile_peer` as `codex` pane-backed agents;
- Flutter integration
  `integration_test/native_pane_gateway_smoke_test.dart` passed on the
  emulator;
- the phone sent
  `Please reply with exactly CCB_MOBILE_NATIVE_OK_20260626092252 and no other text.`
  to `test_ccb2_alpha/mobile_probe`;
- native provider evidence found one matching user prompt and one matching
  reply in the Codex rollout file;
- `jobs_matches` was empty, `prompt_contains_ccb_req_id` was `false`, and
  `prompt_contains_mobile_gateway` was `false`.

Plan impact:

- refreshes C3.1/C3.2 real-provider evidence on the current app head;
- still does not close the complete goal: two-agent/two-project pressure,
  desktop-origin sync, older-history paging, file/image upload, backend
  artifact download, recovery, and soak remain open.

### 2026-06-26: Casebook Compass Preflight Artifact Shape

Scope: validate the enhanced compass tool's casebook artifact output and
record one clean low-disruption real-gateway C0.1/C10.1 debug preflight on the
currently opened Android Emulator.

Evidence:

- [local-avd-casebook-compass-preflight-20260626.json](local-avd-casebook-compass-preflight-20260626.json)
- artifact root: `/tmp/ccb-mobile-compass-20260626091952`

Environment:

- mobile app head: `e00d5e4 test: emit casebook compass artifacts`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19022` with
  `adb reverse tcp:19022 tcp:19022`;
- device: Android Emulator `emulator-5554`.

Result:

- the run wrote standard casebook files:
  `environment.json`, `projects.json`, `request-counts.json`, `memory.json`,
  `power-summary.json`, `timings.json`, `casebook-summary.json`, screenshot,
  UI dump, and logcat tail;
- C0.1/C10.1 debug-preflight status was `ok`;
- `/v1/projects` returned `40` projects with `40` healthy entries;
- project API p50 was `145.8 ms`, max `149.7 ms`;
- PSS delta was `-176 KB`, wake locks were `0`, and logcat had no
  FATAL/ANR/OOM markers.

Plan impact:

- improves repeatable evidence shape for future full stress runs;
- does not close selected-agent pane identity, phone send, provider reply,
  file upload/download, artifact download, disconnect/recovery, or long soak;
- `request-counts.json` currently records host compass API samples only, so
  full idle app endpoint request-rate evidence still needs gateway log parsing
  or instrumentation.

### 2026-06-26: Real Pane-Backed Native Send AVD Smoke

Scope: validate the runbook's real pane-backed fixture gate and one
pane-equivalent Android Emulator send/reply path against disposable
`test_ccb2` projects, not fake/demo.

Evidence:

- [local-avd-native-pane-smoke-20260626.json](local-avd-native-pane-smoke-20260626.json)
- raw log: `/tmp/ccb-mobile-native-pane-smoke-20260626165051.log`

Environment:

- mobile app head: `e5c62fc docs: add local avd real-project test runbook`;
- source worktree:
  `/home/bfly/yunwei/ccb_source_mobile_agent_native`;
- source head: `6042b813 fix: prefer native mobile conversation transcript`;
- gateway: `http://127.0.0.1:19021` with
  `adb reverse tcp:19021 tcp:19021`;
- device: Android Emulator `emulator-5554`;
- projects root:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-server-wide-avd-20260626085051`.

Result:

- the smoke created two disposable real CCB projects,
  `test_ccb2_alpha` and `test_ccb2_beta`, each with `mobile_probe` and
  `mobile_peer` as `codex` pane-backed agents;
- server-wide `/v1/projects` listed those projects plus other mounted server
  projects;
- Flutter integration
  `integration_test/native_pane_gateway_smoke_test.dart` passed on the
  emulator;
- the phone sent
  `Please reply with exactly CCB_MOBILE_NATIVE_OK_20260626085051 and no other text.`
  to `mobile_probe`;
- native evidence found one matching user prompt and one matching Codex reply
  in the provider rollout file;
- `jobs_matches` was empty, `prompt_contains_ccb_req_id` was `false`, and
  `prompt_contains_mobile_gateway` was `false`.

Plan impact:

- closes the previous fake-only fixture blocker for one real pane-backed
  native send/reply lane;
- does not close the full app stress goal: file/image transfer, backend
  artifact download, multi-agent/multi-project pressure, disconnect recovery,
  long-history rendering pressure, request-rate/power soak, and manual
  reviewer handoff still need staged AVD evidence.

### 2026-06-26: Live Real-Project Emulator Handoff Snapshot

Scope: leave the currently opened Android Emulator on a real server-wide
gateway and disposable `test_ccb2` project page after the native-pane smoke,
so manual review starts from a valid real-project state instead of demo/fake.

Evidence:

- [local-avd-live-real-project-handoff-20260626.json](local-avd-live-real-project-handoff-20260626.json)
- live project screenshot:
  `/tmp/ccb-mobile-open-real-project-20260626170340/screen.png`
- live gateway log: `/tmp/ccb_mobile_gateway_live_19022.log`
- compass artifact after gateway restart:
  `/tmp/ccb-mobile-compass-20260626085822/summary.json`

Result:

- stable gateway was restarted under tmux on `127.0.0.1:19022` using the same
  mobile host state from the live setup;
- Android Emulator `emulator-5554` has `adb reverse tcp:19022 tcp:19022`;
- `/v1/projects` returned `40` projects with `40` healthy entries in the
  compass rerun;
- the app foreground recovered to the server-wide project list after restart;
- the top disposable project `test_ccb2_beta` was opened and the UI dump
  contained `test_ccb2_beta`, `mobile_probe`, and `mobile_peer`;
- the opened project UI dump did not contain `demo`, `CCB_REQ_ID`,
  `mobile_gateway`, or `completion_snapshot`.

Plan impact:

- proves the emulator can now be handed to a reviewer on a real project page;
- keeps full completion open: file/image transfer, backend artifact download,
  controlled multi-agent sends, explicit disconnect/retry automation, and soak
  gates still need accepted evidence.

### 2026-06-26: App Compass Baseline And Power Preflight

Scope: start the staged app stress/performance plan on the current Android
Emulator without destabilizing the app: real server-wide gateway, real
`test_ccb2_beta` project, no fake/demo acceptance, no bulk sends, no file
uploads, no reinstall, and no batterystats reset.

Evidence:

- [app-compass-baseline-20260626.json](app-compass-baseline-20260626.json)
- baseline artifact: `/tmp/ccb-mobile-stress-20260626155408/summary.json`
- light UI artifact: `/tmp/ccb-mobile-stress-ui-20260626155648/summary.json`
- idle soak artifact: `/tmp/ccb-mobile-soak-20260626155755/summary.json`
- controlled send artifact: `/tmp/ccb-mobile-send-20260626160154/summary.json`

Result:

- `/v1/projects` listed `38/38` healthy projects; p50 was `80.9 ms`, max
  `438.3 ms`;
- 60-second baseline and 3-minute idle soak showed no memory growth, no
  FATAL/ANR/OOM, and no app-held wake locks;
- returning to the project list and reopening `test_ccb2_beta` each took about
  `2.0 s` in debug mode;
- controlled send remained a blocker for native conversation stress: the
  user's marker became visible locally, but no new backend reply was proven and
  the UI surfaced `open terminal failed: not a terminal`.

Plan impact:

- closes Level 0/short-soak diagnostic stability for this environment;
- keeps Level 2 conversation, file/image, long-history, and multi-turn stress
  blocked until the selected-agent pane target and reply path are fixed.

### 2026-06-25: Manual Server-Wide Real Project AVD Validation

Scope: verify the currently installed Android Emulator app against a
server-wide gateway backed by real local CCB projects on this machine, not the
fake/local demo repository.

Environment:

- mobile app repo head: `54d9d88 docs: record real conversation backfill
  validation`;
- source repo head: `8bd533e4 fix: expose full mobile conversation history`;
- gateway: `http://127.0.0.1:18969` with `adb reverse tcp:18969 tcp:18969`;
- device: Android Emulator `emulator-5554`;
- app package: `io.ccb.mobile.ccb_mobile`, pid `23769`.

Validated:

- the app project list showed real mounted projects including
  `/home/bfly/yunwei/ccb_source` and `/home/bfly/yunwei/ccb_mobile` as
  healthy, alongside the disposable smoke projects;
- `ccb_mobile/talk1` loaded real backend history, including a desktop
  `CCBREPLY`, a previous `mobile_gateway` user message, and completion reply
  `OK`;
- sending `mobile_real_backend_ui_0938_reply_exact_OK` from the emulator to
  `ccb_mobile/talk1` created real backend job `job_755280a4a382`, completed
  with reply `OK`, and the UI rendered both the mobile message and agent reply;
- opening `ccb_source/talk2` loaded real `/home/bfly/yunwei/ccb_source`
  conversation history; sending
  `mobile_real_ccb_source_talk2_0941_reply_exact_OK` created real backend job
  `job_42685e1e512d`, completed with the same reply text, and the UI rendered
  it after tapping the visible `New messages` affordance;
- selecting `ccb_source/main` rendered older release/review CCB history, and
  repeated upward-history loading remained responsive enough for manual use:
  20 consecutive history-drag gestures took about `9249 ms`, the app process
  remained alive, and recent logcat showed no `FATAL EXCEPTION` or `ANR`;
- document attachment selection from Android DocumentsUI worked inside the
  real `ccb_source/talk2` project. Sending `ccb-vm-doc-after-fix.txt` created
  backend job `job_955f0809306e` with attachment metadata
  `mobile-file-558ead81670448c4`, `text/plain`, `57` bytes, and the UI rendered
  the sent attachment chip.

Observed gaps:

- while the attachment metadata and message submit path reached the real
  backend, the receiving agent reported that it could find only job metadata
  and not the actual uploaded file on disk. This keeps "mobile-uploaded file
  is directly readable by the agent" open;
- incoming replies sometimes appear behind a `New messages` affordance when
  the user is not pinned to the latest timeline position. This is correct as a
  scroll-state guard, but the product should make the communicating/new-message
  state less confusing;
- the old bottom `Communicating` row is still visually separate from the
  message bubble during pending sends, matching prior user feedback that this
  should become an in-bubble status treatment.

Evidence screenshots:

- `/tmp/ccb_projects_after_back.png`;
- `/tmp/ccb_current_foreground.png`;
- `/tmp/ccb_after_reply_0938.png`;
- `/tmp/ccb_source_after_new_messages_tap.png`;
- `/tmp/ccb_source_attachment_visible.png`;
- `/tmp/ccb_source_main_after_older_scroll_2.png`.

### 2026-06-25: Real Gateway Full Conversation History Backfill AVD Smoke

Scope: prove that the phone can synchronize more than the current ProjectView
recent-comms window from a real local CCB backend, fetch older selected-agent
conversation pages dynamically by scrolling upward, and render the oldest
computer-side agent reply in Android Emulator.

Commits:

- source main `8bd533e4 fix: expose full mobile conversation history`;
- mobile app main `b9c405f test: cover real gateway conversation backfill
  smoke`.

Result:

- source mobile gateway still uses ProjectView to validate the selected agent
  and namespace epoch, then augments conversation items from
  `.ccb/agents/<agent>/jobs.jsonl` plus completion snapshots so completed job
  history older than the ProjectView recent-comms limit remains reachable;
- ProjectView recent-comms alone was proven insufficient during real smoke:
  56 completed turns produce more than one mobile conversation page, while
  ProjectView exposes only the latest visible subset;
- the server-wide AVD smoke now chooses projects by exact root path instead of
  duplicate display name, avoiding stale registry entries from earlier runs;
- the smoke seeds 56 completed computer-side `ccb ask` turns, verifies the
  latest conversation page has `next_cursor`, follows older cursors until the
  oldest seeded reply is present, then runs the Flutter integration test on
  Android Emulator `emulator-5554`;
- the app opened the paired server-wide gateway project, selected
  `mobile_probe`, rendered the latest reply, dragged the timeline upward, and
  rendered the oldest seeded reply.

Verification:

- source `PYTHONPATH=lib python -m pytest test/test_mobile_gateway_service.py
  -q`: `35 passed`;
- source `python -m py_compile lib/mobile_gateway/service.py`: passed;
- source `git diff --check -- lib/mobile_gateway/service.py
  test/test_mobile_gateway_service.py`: passed;
- mobile validation script `python -m py_compile
  tools/mobile_server_wide_emulator_smoke.py`: passed;
- mobile scoped `git diff --check -- tools/mobile_server_wide_emulator_smoke.py
  app/integration_test/server_wide_gateway_smoke_test.dart`: passed;
- real AVD smoke:
  `python tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source/ccb_test --gateway-listen 127.0.0.1:18968
  --device-id emulator-5554 --force-config --include-long-history-backfill
  --backfill-turns 56 --flutter-timeout 720`: `status=ok`.

Measured evidence from the passing smoke:

- source gateway project view latency: `13.58 ms`;
- latest `/conversation?limit=50` page latency: `208.836 ms`;
- older cursor traversal: `2` older pages, `318.338 ms` total,
  oldest-page latency `152.825 ms`;
- desktop `ccb ask` seed latency: `p50 254.353 ms`, `p95 282.109 ms`,
  max `294.777 ms` over `56` samples;
- job completion wait latency: `p50 1061.532 ms`, `p95 1094.03 ms`,
  max `1103.411 ms` over `56` samples;
- emulator UI latest reply visible: `118 ms`;
- emulator UI oldest reply visible after upward dynamic loading: `18063 ms`
  with `34` drag steps;
- emulator integration total for the backfill lane: `22982 ms`;
- integration output ended with `All tests passed!`.

Plan impact:

- closes the earlier gap where `/conversation` paginated only the small
  ProjectView visible slice instead of full computer-side agent history;
- establishes a repeatable real-backend AVD performance smoke for long chat
  history;
- leaves product threshold tuning and real-provider/Tailnet relay validation
  as follow-up, not basic local-backend correctness.

### 2026-06-25: Dynamic Selected-Agent Conversation Backfill

Scope: avoid loading the full selected-agent conversation history up front
while still allowing the phone to reach older backend messages by scrolling up.

Commits:

- source main `9025d986 feat: paginate mobile agent conversations`;
- mobile app main `7695d7b feat: load older agent conversations on scroll`.

Result:

- source `/v1/projects/{project_id}/agents/{agent}/conversation` now returns
  the latest conversation page first, includes `next_cursor` when older items
  exist, and serves older pages by cursor with invalid cursor requests failing
  closed;
- the app passes `limit` and `cursor` through `AgentConversationLoader`, keeps
  the per-agent `nextCursor` in `AgentChatController`, and exposes older-page
  availability to the selected-agent workspace model;
- upward scroll near the top of the selected-agent timeline triggers one
  guarded older-page load, prepends older items before the current page,
  dedupes overlapping item ids, and does not mark older history as a new
  incoming message;
- after older items are prepended, the workspace restores the user's scroll
  position by compensating for the new max scroll extent, avoiding a jump to
  the latest message.

Verification:

- source `PYTHONPATH=lib python -m pytest test/test_mobile_gateway_service.py
  -q`: `34 passed`;
- source `python -m py_compile lib/mobile_gateway/service.py
  test/test_mobile_gateway_service.py`: passed;
- source scoped `git diff --check -- lib/mobile_gateway/service.py
  test/test_mobile_gateway_service.py`: passed;
- app focused conversation tests:
  `flutter test test/agent_chat_repository_loaders_test.dart
  test/agent_conversation_refresh_coordinator_test.dart
  test/agent_chat_controller_test.dart test/conversation_timeline_test.dart
  test/selected_agent_workspace_model_test.dart
  test/agent_chat_comms_status_widget_test.dart`: passed;
- app chat/gateway regression batch for composer sends, attachments,
  downloads, markdown rendering, repository submit, and HTTP/gateway
  transport contracts: passed;
- app full `flutter test`: `371` tests passed;
- app `git diff --check`: passed;
- app `flutter analyze`: exited nonzero because of the known analysis-server
  `Too many open files` environment issue, but ended with `No issues found!`.

Plan impact:

- closes the code path needed for dynamic conversation backfill across both
  real gateway API and app UI state;
- keeps full-history loading out of the initial selected-agent page;
- leaves a dedicated Android Emulator long-history upward-scroll smoke against
  the server-wide gateway as the next validation target, because this checkpoint
  did not add a new AVD run.

### 2026-06-24: Server-Wide Local Backend And AVD Multi-Project Smoke

Scope: prove the product-shape path requested by the user: one server-level
`ccb install mobile` gateway, one paired phone profile, and multiple mounted
CCB projects selectable from the app first page.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_server_wide_full`, commit
  `227e2963 fix: resolve mobile artifacts from gateway file store`;
- mobile app commit `bc57020 test: add server-wide emulator gateway smoke`.

Artifacts:

- [server-wide-backend-full-smoke-20260624.json](server-wide-backend-full-smoke-20260624.json)
- [server-wide-avd-full-smoke-20260624.json](server-wide-avd-full-smoke-20260624.json)
- [server-wide-manual-codex-session-20260624.json](server-wide-manual-codex-session-20260624.json)
- [server-wide-landing-avd-smoke-20260624.json](server-wide-landing-avd-smoke-20260624.json)
- [server-wide-landing-final-avd-smoke-20260624.json](server-wide-landing-final-avd-smoke-20260624.json)
- [server-wide-landing-review-fix-avd-smoke-20260624.json](server-wide-landing-review-fix-avd-smoke-20260624.json)
- [server-wide-source-main-avd-smoke-20260624.json](server-wide-source-main-avd-smoke-20260624.json)
- [server-wide-source-main-current-goal-20260624.json](server-wide-source-main-current-goal-20260624.json)
- [current-machine-running-projects-avd-20260624.json](current-machine-running-projects-avd-20260624.json)

Result:

- source backend smoke started `test_ccb2_alpha` and `test_ccb2_beta` as two
  real local CCB projects, then ran one loopback-only `ccb install mobile`
  gateway;
- `/v1/projects` listed both mounted projects with healthy status and
  file/message/terminal/lifecycle capabilities;
- both projects passed ProjectView, selected-agent message submit, backend
  Markdown reply visibility, document upload/download, and backend-generated
  artifact download through the gateway;
- Android Emulator `emulator-5554` used `adb reverse tcp:18891 tcp:18891`,
  opened the app with a real paired gateway profile, selected both server
  projects, and exercised multi-agent chat, image upload/download, document
  upload/download, and text/PNG backend artifact downloads;
- the AVD integration output ended with `All tests passed!`.
- a later manual session was opened on `127.0.0.1:18893` with provider
  `codex`, `adb reverse tcp:18893 tcp:18893`, and the same server-wide gateway
  shape. The app first page listed `test_ccb2_beta` and `test_ccb2_alpha` from
  `/home/bfly/yunwei/test_ccb2/...`, not the `ccb_mobile` repo or the
  app-local fake repository.
- a separate source landing worktree merged source main `af53f5a4` with
  `mobile/server-wide-local-backend` into commit `adb18294`, then re-ran the
  server-wide Android Emulator smoke on `127.0.0.1:18894`; the integration
  output again ended with `All tests passed!`.
- a whitespace-only follow-up `b47488c1` cleaned the landing range so
  `git diff --check af53f5a4..HEAD` passes, then re-ran the server-wide
  Android Emulator smoke on `127.0.0.1:18895`; the integration output again
  ended with `All tests passed!`.
- reviewer1 found a High blocker in `job_7b9b8244baf4`: one stale/unreachable
  project could fail the whole `/v1/projects` response. Follow-up `9de121bc`
  changes project listing to degrade the unreachable entry instead of failing
  the list, adds mixed-registry coverage, and re-runs the server-wide Android
  Emulator smoke on `127.0.0.1:18896`; the integration output again ended
  with `All tests passed!`.
- reviewer1 re-review `job_1902074f73dd` accepts `9de121bc`; no blockers were
  found and the previous stale-project list blocker is closed.
- source main was then merged in `/home/bfly/yunwei/ccb_source` as
  `59f1c07b merge: land server-wide mobile backend`. Existing unrelated dirty
  source docs were preserved. Source-main server-wide Android Emulator smoke
  ran on `127.0.0.1:18897` and ended with `All tests passed!`.
- the current goal was re-verified directly against source main. A
  source-main `ccb_test install mobile` run from
  `/home/bfly/yunwei/test_ccb2` on `127.0.0.1:18898` listed 5 registry entries:
  2 healthy projects and 3 unreachable/stale entries degraded instead of
  failing `/v1/projects`.
- a fresh source-main AVD smoke then ran on `127.0.0.1:18899` using
  `/home/bfly/yunwei/ccb_source/ccb_test`; Android Emulator `emulator-5554`
  opened two newly started CCB projects, switched two agents, completed
  multiple Markdown reply turns, uploaded/downloaded image and document
  attachments, and downloaded backend-generated text/PNG artifacts. The
  integration output ended with `All tests passed!`.
- a live manual VM session is open for user testing on `127.0.0.1:18903`,
  hosted by isolated tmux socket `/tmp/ccb_mobile_gateway_18903.tmux.sock`.
  The installed debug app profile points at that gateway, `adb reverse
  tcp:18903 tcp:18903` is active, `/v1/projects` returns `test_ccb2_alpha` and
  `test_ccb2_beta` as healthy, and the emulator UI dump shows both project
  rows on the app first page.
- source main `821b7f7f` extends `ccb install mobile` to merge the persisted
  host project registry with currently running `ccbd` processes discovered
  from `/proc`. A live manual VM session on `127.0.0.1:18905` with
  `adb reverse tcp:18905 tcp:18905` listed 29 projects, including real running
  local projects `ccb_source`, `ccb_mobile`, `system_optimal`, `Liuhuaiyu`,
  and `test_ccb2`.
- the same `18905` AVD session opened real project `ccb_mobile`, selected
  real agent `talk1`, sent
  `mobile_real_all_projects_talk1_000229_reply_exact_OK`, and showed `Sent`
  followed by backend reply text `OK` in the phone UI. The gateway
  conversation API also returned `agent_reply body OK`.

Verification:

- source focused server-wide/mobile/router/parser tests: `200 passed`;
- source `python -m py_compile` for touched gateway/registry/control-plane
  modules: passed;
- mobile server-wide AVD smoke:
  `./tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_server_wide_full/ccb --gateway-listen
  127.0.0.1:18891 --device-id emulator-5554 --force-config`: `status=ok`;
- app focused server-project/pairing/gateway tests: passed;
- app full `flutter test`: `364 passed`;
- landing merge branch source focused tests: `200 passed`;
- landing merge branch source `py_compile` and `git diff --check`: passed;
- landing merge branch AVD smoke:
  `./tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_server_wide_landing/ccb
  --gateway-listen 127.0.0.1:18894 --device-id emulator-5554 --force-config
  --flutter-timeout 240`: `status=ok`;
- final landing candidate `b47488c1` source focused tests: `200 passed`;
- final landing candidate source `py_compile`, worktree `git diff --check`,
  and range `git diff --check af53f5a4..HEAD`: passed;
- final landing candidate AVD smoke:
  `./tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_server_wide_landing/ccb
  --gateway-listen 127.0.0.1:18895 --device-id emulator-5554 --force-config
  --flutter-timeout 240`: `status=ok`;
- review-fix candidate `9de121bc` source focused tests: `201 passed`;
- review-fix candidate source full pytest:
  `PYTHONPATH=lib python -m pytest -q`: `3001 passed, 2 skipped`;
- mobile repo full regression:
  `source tools/mobile_toolchain_env.sh && cd app && flutter test`:
  `364 passed`;
- current-machine source focused tests:
  `PYTHONPATH=lib python -m pytest test/test_mobile_cli_service.py -q`:
  `14 passed`;
- current-machine source gateway/install/router/parser regression:
  `PYTHONPATH=lib python -m pytest test/test_mobile_cli_service.py
  test/test_mobile_gateway_service.py test/test_cli_management_install.py
  test/test_cli_management_update.py test/test_v2_cli_router.py
  test/test_v2_cli_parser.py -q`: `190 passed`;
- current-machine source `py_compile` and scoped `git diff --check`: passed;
- source main focused tests after merge: `201 passed`;
- source main `py_compile` after merge: passed;
- source main merge range `git diff --check HEAD^..HEAD`: passed;
- source main AVD smoke:
  `./tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source/ccb --gateway-listen 127.0.0.1:18897
  --device-id emulator-5554 --force-config --flutter-timeout 240`:
  `status=ok`;
- current-goal source-main install probe:
  `/home/bfly/yunwei/ccb_source/ccb_test install mobile --listen
  127.0.0.1:18898 --route-provider lan` from `/home/bfly/yunwei/test_ccb2`:
  `/v1/projects` returned 5 entries, with 2 healthy and 3 degraded stale
  entries;
- current-goal fresh AVD smoke:
  `source tools/mobile_toolchain_env.sh && python
  tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source/ccb_test --gateway-listen 127.0.0.1:18899
  --force-config`: `status=ok`, integration output `All tests passed!`;
- current-goal manual VM session:
  `curl http://127.0.0.1:18903/v1/projects` returned healthy
  `test_ccb2_alpha` and `test_ccb2_beta`, and
  `/tmp/ccb_mobile_window_18903.xml` contained both project rows with
  `healthy` status;
- review-fix candidate source `py_compile`, worktree `git diff --check`, and
  range `git diff --check af53f5a4..HEAD`: passed;
- review-fix candidate AVD smoke:
  `./tools/mobile_server_wide_emulator_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_server_wide_landing/ccb
  --gateway-listen 127.0.0.1:18896 --device-id emulator-5554 --force-config
  --flutter-timeout 240`: `status=ok`;
- `git diff --check`: passed in both worktrees.

Plan impact:

- closes the previous mismatch where the app could accidentally test only the
  current `ccb_mobile` project or app-local fake repository;
- establishes `ccb install mobile` as the server-level local acceptance lane;
- leaves physical Tailnet/relay and optional live external-provider response
  smoke as follow-ups, not blockers for the local server-wide path.

### 2026-06-24: Live Current-Project Backend Reply And File Smoke

Scope: prove the open Android Emulator is connected to the live local
`/home/bfly/yunwei/ccb_mobile` CCB backend, not the app-local fake repository,
and close the slow real-reply refresh gap found during manual testing.

Commits:

- app commit `b189c90 fix: keep polling for slow backend replies`.

Artifacts:

- [local-real-backend-live-current-project-20260624.json](local-real-backend-live-current-project-20260624.json)

Result:

- Android Emulator `emulator-5554` was rebuilt with the real paired profile
  for gateway `http://127.0.0.1:18931` and
  `adb reverse tcp:18931 tcp:18931`;
- the open app showed the current project `ccb_mobile` and selected `lead`;
- the real backend conversation contains two user/reply pairs:
  `mobile_real_backend_ping_143105` ->
  `mobile_real_backend_reply_143105_ok`, and
  `mobile_real_backend_ping_fixed_143612` ->
  `mobile_real_backend_reply_fixed_143612_ok`;
- the emulator UI dump and screenshot show both backend replies with no
  `FAKE[` marker;
- authenticated file API checks uploaded a text file and PNG image to the
  real `lead` gateway route, downloaded the JSON `content_base64` payloads,
  and verified decoded bytes against the uploaded hashes;
- Android Emulator UI smoke passed attachment upload/download, image
  upload/download, backend generated artifact downloads, deterministic
  Markdown reply, and multi-agent image/turn coverage after the reply wait was
  extended.

Verification:

- app `flutter test test/conversation_refresh_scheduler_test.dart
  test/agent_message_submit_coordinator_test.dart`: 12 passed;
- app `flutter test`: 358 passed;
- app `python3 tools/mobile_emulator_ui_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb --provider fake
  --gateway-listen 127.0.0.1:18942 --include-attachment-route
  --include-image-route --include-backend-artifact-route
  --include-multi-agent-route --skip-terminal-test --harness-timeout 360
  --flutter-timeout 360`: `status=ok`, integration smoke 7 passed;
- app `git diff --check`: passed;
- app `flutter analyze`: no issues found, but exited nonzero because the
  known analysis server `Too many open files` error occurred.

Plan impact:

- answers the manual-test failure directly: a message sent from the emulator
  can reach the real local backend and a backend answer returns into the
  visible mobile chat;
- keeps deterministic fake-provider smoke as auxiliary UI automation only,
  while the current-project live reply evidence uses the real `lead` backend;
- leaves only targeted follow-ups for foreground/resume timing,
  oversized-file rejection timing, and physical Tailnet/relay smoke.

### 2026-06-24: Real-Local Multi-Agent Image And Artifact AVD Lane

Scope: verify the local Android Emulator against the real host-side CCB
gateway for two agents, per-agent draft isolation, multiple backend message
turns, image upload/download, and backend-generated file downloads.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix`, commit
  `50bf589f feat: expose mobile backend artifacts in conversations`;
- app commit `2a23157 test: cover multi-agent local backend emulator smoke`.

Artifacts:

- [local-real-backend-avd-multi-agent-image-turns-smoke-20260623.json](local-real-backend-avd-multi-agent-image-turns-smoke-20260623.json)

Result:

- Android Emulator `emulator-5554` passed a fresh real-local lane through
  loopback gateway `127.0.0.1:18923` and
  `adb reverse tcp:18923 tcp:18923`;
- the disposable host-side CCB project was started from
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb` with agents
  `mobile_probe` and `mobile_peer`;
- the app paired with the real gateway, activated the paired runtime profile,
  and preserved separate composer drafts while switching between both agents;
- both agents sent two deterministic backend message-route turns and displayed
  the rendered Markdown replies with per-agent `agent=<name>` code-block
  evidence;
- both agents uploaded a PNG image through the gateway, displayed the returned
  conversation attachment, tapped the attachment, and received `Saved <file>`
  feedback;
- both agents triggered backend-generated text and PNG artifacts, expanded the
  reply, tapped both artifact links, and received authenticated saved-file
  feedback;
- the runner cleaned up adb reverse and stopped the disposable runtime.

Verification:

- app `source ../tools/mobile_toolchain_env.sh && flutter test
  integration_test/emulator_gateway_smoke_test.dart`: 7 passed
- AVD multi-agent/image/artifact smoke:
  `/tmp/ccb-mobile-avd-multi-agent-image-turns-smoke.json`, `status=ok`
- app `python -m py_compile tools/mobile_emulator_ui_smoke.py`: passed
- app `git diff --check`: passed.

Plan impact:

- closes the user's local-VM concern that testing must use a real local CCB
  backend rather than the app-local fake repository;
- proves backend-generated files can be surfaced as conversation links and
  downloaded to the phone for more than one agent in the same app session;
- keeps pure pane-backed text send as a separate product behavior: this lane
  verifies the current real gateway message route using deterministic
  Markdown/message bodies plus small attached fixtures.

### 2026-06-23: Real-Local Backend Artifact, Revoke, Terminal, And Latency Closure

Scope: close the user's requested real local CCB backend path for generated
agent files and prove the Android Emulator is testing the real gateway, not
the app-local fake repository.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix`, commit
  `50bf589f feat: expose mobile backend artifacts in conversations`;
- app commit `b132f37 test: cover backend artifact downloads in emulator
  smoke`.

Artifacts:

- [local-real-backend-source-probe-artifacts-revoke-20260623.json](local-real-backend-source-probe-artifacts-revoke-20260623.json)
- [local-real-backend-avd-file-md-artifact-smoke-20260623.json](local-real-backend-avd-file-md-artifact-smoke-20260623.json)
- [local-real-backend-avd-terminal-smoke-20260623.json](local-real-backend-avd-terminal-smoke-20260623.json)
- [local-real-backend-avd-lifecycle-stop-smoke-20260623.json](local-real-backend-avd-lifecycle-stop-smoke-20260623.json)
- [local-real-backend-latency-summary-20260623.json](local-real-backend-latency-summary-20260623.json)

Result:

- source gateway conversation replies now resolve `ccb-artifact://<file_id>`
  links into authenticated mobile attachment metadata;
- source fake-provider artifact jobs write generated text and PNG files into
  the mobile file store passed by the gateway, not through host path guesses;
- ProjectView now requires bearer auth, so revoked devices fail closed on
  ProjectView as well as device, message, terminal, and file routes;
- Android Emulator `emulator-5554` passed the combined real-local lane through
  loopback gateway `127.0.0.1:18899`, covering document upload/download,
  image upload/download, Markdown reply rendering, and backend-generated text
  + image artifact link downloads;
- Android Emulator `emulator-5554` passed the terminal lane through loopback
  gateway `127.0.0.1:18900`, covering route diagnostics, paired activation,
  selected-agent focus, terminal WebSocket, reconnect button path, and
  post-smoke terminal target;
- Android Emulator `emulator-5554` passed the lifecycle stop lane through
  loopback gateway `127.0.0.1:18901`; this lane intentionally uses a throwaway
  runtime and skips post-stop terminal target validation;
- five source/gateway capability probe runs passed with p50/p95 budgets green:
  backend artifact route p50 `1520.988 ms`, p95 `1523.777 ms`; deterministic
  agent reply marker p50 `1513.836 ms`, p95 `1515.126 ms`; ProjectView p50
  `9.061 ms`, p95 `10.058 ms`; file upload/download under `2 ms`.

Verification:

- source `python -m py_compile lib/mobile_gateway/service.py
  lib/provider_execution/fake.py test/test_mobile_gateway_service.py
  test/test_provider_execution_fake_runtime.py`: passed
- source `PYTHONPATH=lib python -m pytest -q
  test/test_mobile_gateway_service.py test/test_ccbd_project_view.py
  test/test_provider_execution_fake_runtime.py`: 97 passed
- app `python tools/mobile_local_backend_capability_probe_test.py`: 8 passed
- app `python tools/mobile_local_backend_latency_summary_test.py`: 7 passed
- app `source ../tools/mobile_toolchain_env.sh && flutter test
  integration_test/emulator_gateway_smoke_test.dart`: 6 passed
- app `source ../tools/mobile_toolchain_env.sh && flutter test
  test/gateway_terminal_transport_test.dart test/http_gateway_transport_test.dart
  test/relay_gateway_transport_test.dart`: 18 passed
- AVD combined file/image/Markdown/artifact smoke:
  `/tmp/ccb-mobile-avd-fake-full-file-md-artifact-smoke.json`, `status=ok`
- AVD terminal smoke: `/tmp/ccb-mobile-avd-terminal-smoke.json`, `status=ok`
- `git diff --check`: passed in source and app worktrees.

Plan impact:

- answers the user requirement: a backend CCB agent can generate files and
  expose them as conversation links that the phone downloads through the
  authenticated gateway;
- narrows remaining local-backend matrix gaps to app foreground/resume timing,
  oversized rejection timing, and physical Tailnet/relay smoke after source
  and app changes are landed.

### 2026-06-23: Backend Artifact Route And Link Tooling

Scope: make the user's required "backend CCB agent generates a file and the
phone downloads it from the conversation" lane executable before claiming AVD
closure.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix`, commit
  `d0da183a feat: expose backend generated artifacts through mobile gateway
  (fake provider)`;
- app commit `201d416 feat: implement backend-agent generated artifact
  download`.

Result:

- source fake provider command `ccb-local-artifact:<id>` creates generated
  text and PNG artifacts under the mobile gateway file store;
- the conversation reply returns those generated files as mobile attachment
  metadata and emits `ccb-artifact://<file_id>` Markdown links;
- app conversation bubbles map `ccb-artifact://<file_id>` links back to the
  matching attachment and reuse the authenticated `/files/{file_id}` download
  path;
- the backend capability probe has a `backend_artifact_route` gate, and the
  latency summary includes the backend-generated artifact route budget.

Verification:

- source `PYTHONPATH=lib python -m pytest -q
  test/test_mobile_gateway_service.py test/test_ccbd_project_view.py`: 88
  passed
- `python tools/mobile_local_backend_capability_probe_test.py`: 8 passed
- `python tools/mobile_local_backend_latency_summary_test.py`: 7 passed
- `source ../tools/mobile_toolchain_env.sh && flutter test
  test/conversation_bubble_test.dart`: 6 passed
- `python -m py_compile tools/mobile_local_backend_capability_probe.py
  tools/mobile_local_backend_capability_probe_test.py
  tools/mobile_local_backend_latency_summary.py
  tools/mobile_local_backend_latency_summary_test.py`: passed

Plan impact:

- resolves the implementation direction for generated artifacts: reuse
  conversation `attachments` plus authenticated `/files/{file_id}` download,
  with `ccb-artifact://<file_id>` as an app-internal Markdown link;
- does not close the full real-local matrix. Fresh AVD evidence must still
  prove tap-to-download/open feedback and byte/hash verification on the
  Android Emulator.

### 2026-06-23: Real-Local AVD Terminal, Media Attachment, And Markdown Lanes

Scope: prove the Android Emulator can connect to a real host-side CCB source
gateway through loopback plus `adb reverse`, and close the first two
high-risk UI lanes in the real local backend matrix: paired terminal control,
document/image upload/download, and deterministic Markdown reply rendering.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix`, commit
  `99fa0544 feat: add mobile gateway file routes`;
- source worktree commit
  `7156431f fix: preserve mobile attachment metadata in conversation`;
- source worktree commit
  `9a6cd505 test: add deterministic mobile markdown fake reply`;
- app commit `ac654ee test: cover emulator attachment upload download`;
- app commit `7f9aeb7 test: cover emulator markdown reply smoke`;
- app commit `12cfa53 test: cover emulator image attachment smoke`.

Artifacts:

- [local-real-backend-avd-smoke-20260623.json](local-real-backend-avd-smoke-20260623.json)
- terminal lane raw run:
  `/tmp/ccb-mobile-avd-terminal-smoke-source-worktree.json`
- attachment lane raw run:
  `/tmp/ccb-mobile-avd-real-local-attachment-smoke.json`
- attachment plus Markdown lane raw run:
  `/tmp/ccb-mobile-avd-real-local-attachment-markdown-smoke.json`
- media plus Markdown lane raw run:
  `/tmp/ccb-mobile-avd-real-local-media-markdown-smoke.json`

Result:

- terminal lane: `status=ok`, source provider `codex`, gateway
  `http://127.0.0.1:18896`, `adb reverse tcp:18896 tcp:18896`,
  integration smoke `returncode=0`, terminal route enabled, post-harness
  `mobile_terminal_target_ok=true`;
- attachment lane: `status=ok`, source provider `fake` for deterministic
  backend reply, gateway `http://127.0.0.1:18897`,
  `adb reverse tcp:18897 tcp:18897`, integration smoke `returncode=0`,
  attachment route enabled and terminal route skipped intentionally;
- attachment plus Markdown lane: `status=ok`, source provider `fake`,
  gateway `http://127.0.0.1:18897`, attachment route and Markdown route
  enabled, terminal route skipped intentionally, integration smoke
  `returncode=0`;
- media plus Markdown lane: `status=ok`, source provider `fake`, gateway
  `http://127.0.0.1:18897`, document route, image route, and Markdown route
  enabled, terminal route skipped intentionally, integration smoke
  `returncode=0`;
- the source gateway now preserves mobile attachment metadata through
  ProjectView Comms and the conversation route without leaking host-local
  paths;
- source fake provider now has a deterministic `ccb-local-md:<id>` fixture
  that returns Markdown with title, reply marker, list item, code block, and
  link text through the real dispatcher;
- the app AVD lane selects a local text file through mocked `file_picker`,
  uploads it through the real gateway route, observes the deterministic agent
  reply, taps the conversation attachment chip, downloads the bytes, and sees
  `Saved <file>` feedback.
- the app AVD Markdown lane sends a message-route body plus attachment,
  expands the returned Markdown reply, and waits for the title, reply marker,
  list item, code-block text, and link text to render.
- the app AVD image lane selects a generated PNG through mocked `file_picker`,
  uploads it through the real gateway route, observes the deterministic agent
  reply, taps the conversation image/file chip, downloads the bytes, and sees
  `Saved <image>.png` feedback.

Verification:

- source focused tests:
  `PYTHONPATH=lib python -m pytest -q test/test_mobile_gateway_service.py
  test/test_ccbd_project_view.py -q`: passed
- source `python -m py_compile lib/mobile_gateway/service.py
  lib/ccbd/project_view/service.py test/test_mobile_gateway_service.py
  test/test_ccbd_project_view.py`: passed
- app `python -m py_compile tools/mobile_emulator_ui_smoke.py`: passed
- app `python tools/mobile_emulator_ui_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb
  --device-id emulator-5554 --gateway-listen 127.0.0.1:18896
  --flutter-timeout 420 --start-timeout 90 --gateway-timeout 30
  --harness-timeout 10 --adb-timeout 30`: returned `status=ok`
- app `python tools/mobile_emulator_ui_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb
  --provider fake --include-attachment-route --skip-terminal-test
  --device-id emulator-5554 --gateway-listen 127.0.0.1:18897
  --flutter-timeout 480 --start-timeout 90 --gateway-timeout 30
  --harness-timeout 10 --adb-timeout 30`: returned `status=ok`
- app `python tools/mobile_emulator_ui_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb
  --provider fake --include-attachment-route --include-markdown-route
  --skip-terminal-test --device-id emulator-5554
  --gateway-listen 127.0.0.1:18897 --flutter-timeout 540
  --start-timeout 90 --gateway-timeout 30 --harness-timeout 10
  --adb-timeout 30`: returned `status=ok`
- app `python tools/mobile_emulator_ui_smoke.py --source-ccb
  /home/bfly/yunwei/ccb_source_mobile_local_backend_matrix/ccb
  --provider fake --include-attachment-route --include-image-route
  --include-markdown-route --skip-terminal-test --device-id emulator-5554
  --gateway-listen 127.0.0.1:18897 --flutter-timeout 620
  --start-timeout 90 --gateway-timeout 30 --harness-timeout 10
  --adb-timeout 30`: returned `status=ok`
- `git diff --check`: passed in both source and app worktrees.

Plan impact:

- closes the real-local AVD terminal lane, deterministic Markdown reply lane,
  and document/image upload/download lanes for
  [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md);
- does not close the full matrix yet. Remaining required lanes include
  revoke fail-closed, gateway/adb reconnect recovery, and repeated p50/p95
  latency measurement.

### 2026-06-23: Source Loopback Real-Backend Capability Probe

Scope: prove the host-side real CCB mobile gateway path can complete the
backend gates required by the local matrix before driving the Android
Emulator UI.

Commits:

- source worktree
  `/home/bfly/yunwei/ccb_source_mobile_local_backend_matrix`, commit
  `99fa0544 feat: add mobile gateway file routes`;
- app commit `eea9cac test: add local backend capability probe`;
- app commit `f1670db test: accept source pairing claim shape in mobile probe`.

Artifacts:

- [local-real-backend-source-probe-20260623.json](local-real-backend-source-probe-20260623.json)
- raw latest run: `/tmp/ccb-mobile-local-probe-source-file-route.json`

Result:

- disposable real CCB project:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-local-capability-20260623-213502-5328bc`;
- loopback gateway: `http://127.0.0.1:42927`;
- probe status: `ok`;
- capabilities reported by `/v1/health`: `http_json`, `project_view`,
  `pairing`, `device_tokens`, `lifecycle`, `focus`, `terminal_open`,
  `websocket_terminal`, `terminal_history`, `file_upload`, and
  `file_download`;
- authenticated gates passed: pairing claim, ProjectView, message submit,
  deterministic `agent_reply` marker, file upload, and file download.

Timing:

- full probe subprocess: 1078 ms;
- health: 2.610 ms;
- pairing claim: 1.857 ms;
- ProjectView: 10.385 ms;
- message submit accepted: 3.853 ms;
- backend accepted to deterministic reply marker: 1013.499 ms;
- file upload route: 1.567 ms;
- file download route: 0.880 ms.

Verification:

- `python tools/mobile_local_backend_capability_probe_test.py`: 6 passed
- `python -m py_compile tools/mobile_local_backend_capability_probe.py
  tools/mobile_local_backend_capability_probe_test.py`: passed
- real source loopback probe using source commit `99fa0544` and app commit
  `f1670db`: passed
- `git diff --check`: passed

Plan impact:

- closes the backend capability prerequisite for
  [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md);
- does not close the AVD UI matrix, which must still pair the current app to
  the real source gateway through `adb reverse` and verify visible replies,
  Markdown rendering, attachment upload/download, diagnostics, terminal,
  lifecycle, reconnect, revoke, and response-speed budgets.

### 2026-06-23: Local Real-Backend Capability Probe

Scope: add the first executable gate for the local real-backend matrix so
manual or automated runs can distinguish "message locally sent" from
"backend accepted and agent reply visible."

Artifacts:

- `tools/mobile_local_backend_capability_probe.py`
- `tools/mobile_local_backend_capability_probe_test.py`
- [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md)

Result:

- probe claims a real loopback gateway pairing profile, reads authenticated
  ProjectView, submits a selected-agent message, polls for a deterministic
  `agent_reply` marker, and probes file upload/download routes;
- every gate is reported as `pass`, `fail`, or `blocked` with duration
  metrics and `next_actions`;
- source-side blockers are now machine-visible instead of inferred from UI
  screenshots: deterministic local reply fixture and gateway file routes must
  land before the full AVD matrix can be accepted.

Verification:

- `python tools/mobile_local_backend_capability_probe_test.py`: 5 passed
- `python -m py_compile tools/mobile_local_backend_capability_probe.py
  tools/mobile_local_backend_capability_probe_test.py`: passed
- `python tools/mobile_local_backend_capability_probe.py --gateway-url
  http://127.0.0.1:65530 --http-timeout 0.2 --reply-timeout 0.1
  --poll-interval 0.01 || true`: produced JSON with health `fail` and
  authenticated gates `blocked`
- `git diff --check`: passed

Plan impact:

- first implementation package for
  [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md);
- does not close the full local real-backend matrix by itself.

### 2026-06-23: Local Real-Backend Comprehensive Test Plan

Scope: correct the local-test acceptance boundary after manual AVD testing
clarified that "local" means Android Emulator through loopback/`adb reverse`
to a real host-side CCB test backend, not the app's fake `demo` repository.

Artifacts:

- [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md)
- [../topics/android-emulator-comprehensive-test-plan.md](../topics/android-emulator-comprehensive-test-plan.md)

Result:

- fake/local evidence is now scoped to auxiliary app/UI regression;
- real local backend acceptance requires paired gateway mode against a real
  CCB project, deterministic send-to-agent-reply visibility, Markdown reply
  rendering, document/image upload and download, route diagnostics, terminal
  WebSocket control, lifecycle, reconnect, revoke fail-closed behavior, and
  response-speed metrics;
- physical phone/iPad Tailnet smoke remains important, but it follows the
  real local backend matrix instead of replacing it.

Verification:

- plan-tree topic, roadmap, root registry, and implementation-status updates
  are linked from the active plan.

### 2026-06-23: Android Emulator Comprehensive P0 Matrix Completion

Scope: close the remaining P0 gates in
[../topics/android-emulator-comprehensive-test-plan.md](../topics/android-emulator-comprehensive-test-plan.md)
after the core fake/local overwrite fix.

Commits:

- app commit `341ee4c test: complete emulator chat matrix coverage`
- app commit `0200fcb docs: finalize emulator P0 matrix evidence and add missing concurrent send test`

Artifacts:

- `app/test/agent_chat_composer_widget_test.dart`
- `app/test/agent_message_submit_coordinator_test.dart`
- `app/test/gateway_route_diagnostics_test.dart`
- `app/integration_test/emulator_gateway_smoke_test.dart`
- AVD smoke JSON: `/tmp/ccb_mobile_emulator_ui_smoke_matrix.json`
- Fresh install/focus artifacts:
  `/tmp/ccb_vm_matrix_focus_after_install.txt`,
  `/tmp/ccb_vm_matrix_launch_after_install.png`, and
  `/tmp/ccb_vm_matrix_launch_window.xml`.

Result:

- duplicate fake/local message bodies remain visible as separate local
  timeline entries;
- concurrent/pending send attempts do not create duplicate submit requests;
- failed sends show Retry, and retry reuses the same local message id instead
  of creating an unrelated message;
- mocked `file_picker` coverage proves cancel no-op, five-file max retention,
  max-count snackbar, and oversized-file rejection preserving existing draft
  attachments;
- gateway attachment download ignores repeated taps while the first download is
  pending;
- paired loopback integration smoke now sends two consecutive selected-agent
  messages and waits for both bodies in the conversation/timeline;
- terminal WebSocket send, paste, resize, and reconnect remain green in the
  AVD smoke;
- route diagnostics fail closed when a paired device is revoked;
- fresh debug APK install and launch focused
  `io.ccb.mobile.ccb_mobile/.MainActivity`.

Verification:

- `flutter test test/gateway_route_diagnostics_test.dart
  test/agent_chat_composer_widget_test.dart`: 30 passed
- focused chat/attachment/terminal/gateway regression batch: 91 passed
- `python tools/mobile_emulator_ui_smoke.py --device-id emulator-5554
  --gateway-listen 127.0.0.1:18895 --flutter-timeout 360`: returned
  `status: ok`; Flutter integration smoke passed 2 tests; adb reverse was
  removed; runtime cleanup unmounted the disposable project
- `flutter build apk --debug`: passed
- `adb install -r build/app/outputs/flutter-apk/app-debug.apk`: passed
- `adb shell am start -n io.ccb.mobile.ccb_mobile/.MainActivity`: focused the
  app package
- `flutter test`: 358 passed
- `flutter analyze`: no issues found
- `git diff --check`: passed

Plan impact:

- closes the Android Emulator app/UI regression matrix;
- no longer closes real local CCB backend send-to-agent-reply acceptance; that
  is now governed by
  [../topics/local-real-backend-comprehensive-test-plan.md](../topics/local-real-backend-comprehensive-test-plan.md).

### 2026-06-23: Android Emulator Core Chat Regression Fix

Scope: close the fake/local selected-agent consecutive-send overwrite found
during manual AVD testing, and rerun the VM-first core
chat/document/image/gateway regression before completing the remaining
comprehensive P0 matrix.

Commits:

- app commit `e7871dd fix: persist fake/local submissions and prune
  attachment-only local messages`
- app commit `22fa259 test: cover vm chat consecutive sends`

Artifacts:

- `app/lib/repository/fake_mobile_ccb_repository.dart`
- `app/lib/features/agent_chat/agent_chat_state_helpers.dart`
- `app/test/agent_chat_state_helpers_test.dart`
- `app/test/fake_mobile_ccb_repository_test.dart`
- `app/test/agent_message_submit_coordinator_test.dart`
- `app/test/agent_chat_composer_widget_test.dart`
- [../topics/android-emulator-comprehensive-test-plan.md](../topics/android-emulator-comprehensive-test-plan.md)
- Manual AVD evidence under `/tmp/`: `ccb_vm_current_after_fix.png`,
  `ccb_current_window.xml`, `ccb_vm_two_send_after_fix.png`,
  `ccb_vm_enter_two_send_after_fix.png`, `ccb_vm_doc_sent_after_fix.png`,
  `ccb_vm_doc_download_after_fix.png`, `ccb_vm_photo_attached_after_fix.png`,
  `ccb_vm_photo_sent_after_fix.png`, `ccb_vm_photo_download_after_fix.png`,
  and matching UI dumps.
- Loopback paired-gateway smoke JSON:
  `/tmp/ccb_mobile_emulator_ui_smoke_after_fix.json`.

Result:

- fake/local repository now persists submitted user messages instead of
  rebuilding each submit response from immutable fixture data plus only the
  current message;
- attachment-only local-message pruning now uses attachment coverage when
  `body` is empty;
- AVD button sends `mfirst-fixed623` and `vmsecond-fixed623` remained visible
  together with `Sent`;
- AVD hardware Enter sends `enterone623` and `entertwo623` remained visible
  together with `Sent`;
- Android DocumentsUI selected `ccb-vm-doc-after-fix.txt`, sent it as an
  attachment-only message, and tapping the sent chip showed
  `Saved ccb-vm-doc-after-fix.txt`;
- Android image picker/DocumentsUI selected `ccb-vm-photo-after-fix.png`, sent
  it as an image-only message, and tapping the sent chip showed
  `Saved ccb-vm-photo-after-fix.png`;
- disposable loopback gateway smoke through `127.0.0.1:18893` passed route
  diagnostics and explicit gateway terminal open with `mobile_terminal_target_ok`
  before and after the integration smoke.

Verification:

- focused affected tests: 29 passed
- plan chat/attachment regression batch: 53 passed
- `python tools/mobile_emulator_ui_smoke.py --device-id emulator-5554
  --gateway-listen 127.0.0.1:18893 --flutter-timeout 300`: returned
  `status: ok`; Flutter integration smoke passed 2 tests; adb reverse was
  removed; runtime cleanup unmounted the disposable project
- `flutter test`: 350 tests passed
- `flutter analyze`: no issues found
- `git diff --check`: passed

Residual notes:

- The full AVD run validates route diagnostics and terminal-open smoke; the
  destructive revoke path remains covered by existing source/app token and
  gateway safety evidence rather than rerun through this app UI flow.
- ADB `input text` can still drop a leading character in injected text
  (`vmfirst` appeared as `mfirst`); this is an emulator input quirk, not an
  app persistence failure.
- DocumentsUI can expose recent txt files in the image flow; the passing image
  run explicitly selected `ccb-vm-photo-after-fix.png` after clearing the wrong
  selection.

Plan impact:

- closes the user-reported VM-first overwrite blocker;
- does not close the complete emulator plan by itself; the remaining P0
  matrix gates are listed in
  [../topics/android-emulator-comprehensive-test-plan.md](../topics/android-emulator-comprehensive-test-plan.md).

### 2026-06-23: Android Emulator Chat And Attachment Deep Smoke

Scope: verify the phone-width selected-agent chat path on Android Emulator
after the file-attachment feature and the follow-up message-send visibility
fixes, before moving on to physical phone/iPad Tailnet validation.

Status update: partially superseded by a later same-day manual AVD probe. The
single-message text and attachment paths below passed, but consecutive
fake/local sends are not accepted: sending `vmfirst623` followed by
`vmsecond623` left only `vmsecond623 / Sent` visible. The active remediation
and full VM matrix are tracked in
[../topics/android-emulator-comprehensive-test-plan.md](../topics/android-emulator-comprehensive-test-plan.md).

Commits:

- mobile app commit `ac257cd feat: add agent chat file attachments`
- mobile app commit `d7881a1 fix: send agent messages from hardware enter`
- mobile app commit `cf08b24 fix: keep sent agent messages visible`

Artifacts:

- `app/lib/features/agent_chat/agent_message_composer.dart`
- `app/lib/features/agent_chat/agent_message_submit_coordinator.dart`
- `app/lib/features/agent_chat/agent_repository_message_submitter.dart`
- `app/lib/features/agent_chat/agent_chat_timeline_items.dart`
- `app/lib/features/agent_chat/selected_agent_workspace.dart`
- `app/test/agent_chat_composer_widget_test.dart`
- `app/test/conversation_bubble_test.dart`
- `app/test/agent_message_submit_coordinator_test.dart`
- `app/test/agent_repository_message_submitter_test.dart`
- `app/integration_test/emulator_gateway_smoke_test.dart`
- `tools/mobile_emulator_ui_smoke.py`
- Manual evidence screenshots under `/tmp/`: `ccb_deep_text_button_sent.png`,
  `ccb_deep_text_enter_sent.png`, `ccb_deep_received_top.png`,
  `ccb_deep_doc_sent.png`, `ccb_deep_doc_saved.png`,
  `ccb_deep_image_sent.png`, and `ccb_deep_image_saved.png`.

Result:

- clean Android Emulator app state opened the fake `demo` project and selected
  `mobile`;
- button send produced a visible user message with `Sent` state, without being
  hidden below supplemental terminal history;
- hardware Enter produced a visible `Sent` message;
- received/remote timeline rendering showed the fixture Markdown reply
  `Emulator landing status` and readable terminal-history entries such as
  `Gateway claim` and `Readable history contract`;
- Android DocumentsUI file picking selected `ccb-deep-doc.txt`, sent it as an
  attachment with `Sent` state, and tapping the sent chip showed
  `Saved ccb-deep-doc.txt`;
- Android Photo/Image picking selected a MediaStore-indexed screenshot
  `ccb-deep-photo.png`, sent it as an image attachment with `Sent` state, and
  tapping the sent chip showed `Saved ccb-deep-photo.png`;
- disposable loopback gateway AVD smoke paired through
  `http://127.0.0.1:18891`, ran route diagnostics, submitted a selected-agent
  chat message and waited for the conversation body to return, opened the
  explicit gateway terminal, and cleaned up adb reverse plus runtime.

Verification:

- `flutter test test/agent_chat_composer_widget_test.dart
  test/conversation_bubble_test.dart test/agent_message_submit_coordinator_test.dart
  test/agent_chat_state_helpers_test.dart test/agent_chat_timeline_items_test.dart
  test/agent_repository_message_submitter_test.dart
  test/http_gateway_transport_test.dart test/gateway_mobile_ccb_repository_test.dart`:
  57 tests passed
- `flutter build apk --debug`: passed and installed to `emulator-5554`
- Manual AVD smoke: text send by button, text send by hardware Enter,
  received Markdown/history reading, document send/save, image send/save
  passed
- `python tools/mobile_emulator_ui_smoke.py --device-id emulator-5554
  --gateway-listen 127.0.0.1:18891 --flutter-timeout 240`: returned
  `status: ok`; Flutter integration smoke passed 2 tests; pre/post harness
  `mobile_terminal_target_ok: true`; cleanup removed adb reverse and unmounted
  the disposable runtime
- `flutter test`: 342 tests passed
- `flutter analyze`: no issues found
- `git diff --check`: passed

Residual notes:

- ADB `input text` can drop a leading character in manual injection; this is
  an emulator input quirk and did not affect app send behavior.
- ADB-pushed tiny PNGs do not always appear in the Photo/Image picker Recent
  view until MediaStore indexes them; using a real emulator screenshot under
  `/sdcard/Pictures` plus media scan matched normal user image-picking
  behavior and passed.
- Physical phone/iPad Tailnet validation remains the next route-level gate.

Plan impact:

- closes the emulator-side deep verification for chat send/receive,
  document transfer, image transfer, and attachment save/open feedback;
- keeps the next active target on physical device Tailnet validation rather
  than more app-side architecture extraction.

### 2026-06-23: Source `ccb update mobile` Tailnet Onboarding

Scope: add a source-side optional Mobile bundle entry so private Tailnet users
can start Mobile/Tailscale onboarding with `ccb update mobile` without making
mobile or Tailscale dependencies part of mandatory `ccb update`.

Commits:

- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet` branch
  `worker1/mobile-update-tailnet` commit `b6e148f2`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet` branch
  `worker1/mobile-update-tailnet` commit `d73ae650`

Artifacts:

- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/lib/cli/services/mobile_update.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/lib/cli/management_runtime/commands_runtime/update.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/lib/cli/router.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/test/test_cli_services_mobile_update.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/test/test_cli_management_update.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/test/test_v2_cli_parser.py`
- `/home/bfly/yunwei/ccb_source_mobile_update_tailnet/test/test_v2_cli_router.py`

Result:

- `ccb update mobile` is implemented as an optional bundle/onboarding target,
  analogous to `ccb update rich`;
- logged-in Tailscale users can proceed directly to Mobile gateway/QR setup;
- non-logged-in users get Tailscale login handoff without CCB storing
  credentials;
- generated Tailnet route uses `--public-url https://<host>:8787` and
  `tailscale serve --bg --https=8787 http://127.0.0.1:8787`, keeping public
  Tailnet HTTPS port and local gateway port aligned;
- review confirmed no Funnel, no token/password storage, no ACL/grant edits,
  loopback-only gateway, non-loopback listen rejection, and Tailnet route
  metadata boundaries.

Verification:

- Focused/relevant tests after follow-up: 147 passed
- Worker full pytest before follow-up: 2993 passed, 2 skipped
- `python -m py_compile ...`: passed
- `git diff --check`: passed
- reviewer1 accepted final stack

Plan impact:

- closes the source-side `ccb update mobile` Tailnet onboarding implementation
  package;
- leaves live physical phone/iPad Tailnet route smoke as the remaining
  acceptance gate for the stable private route;
- keeps CCB Relay as the ordinary-user default not-on-LAN route.

### 2026-06-21: Consolidated Emulator-Only Acceptance Checklist And AVD Smoke

Scope: consolidate all emulator-only completion gates into one auditable
checklist and refresh local AVD smoke evidence without physical devices,
public DNS, public IP, Cloudflare, production relay, or external servers.

Commits:

- mobile plan-tree checkpoint: the commit that adds this section

Artifacts:

- `docs/plantree/plans/mobile-tmux-control/topics/emulator-only-acceptance-checklist.md`
- `docs/plantree/plans/mobile-tmux-control/goal-emulator-only.md`
- `docs/plantree/plans/mobile-tmux-control/implementation-status.md`
- `tools/mobile_emulator_ui_smoke.py`
- `app/integration_test/emulator_gateway_smoke_test.dart`

Result:

- the new checklist maps every emulator-only completion gate to current
  authoritative proof, next audit command, accepted deferral, or residual
  risk;
- the final audit accepts every gate in
  [goal-emulator-only.md](../goal-emulator-only.md) as proven locally or
  explicitly deferred by the goal;
- normal AVD smoke proves disposable runtime startup, loopback gateway,
  `adb reverse`, debug APK build/install, local pairing/claim, route
  diagnostics, selected-agent reader/history behavior, lifecycle
  wake/open/close, selected-agent live terminal open, terminal
  input/paste/resize/reconnect, post-smoke attachability, and cleanup;
- throwaway stop AVD smoke proves confirmed lifecycle stop against an isolated
  disposable runtime and records the expected post-harness skip reason;
- public relay, Cloudflare, public DNS/IP, physical devices, app stores, and
  production remote access remain outside emulator-only completion.

Verification:

- `python3 -m py_compile tools/mobile_emulator_ui_smoke.py`: passed
- Normal AVD smoke
  `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18877
  --gateway-timeout 30 --flutter-timeout 300 --harness-timeout 10`: returned
  `status: ok`, `adb_reverse.mapping: tcp:18877 tcp:18877`,
  `gateway.gateway_url: http://127.0.0.1:18877`,
  `gateway.pairing_code_seen: true`, two Flutter integration tests passed,
  pre/post harness `mobile_terminal_target_ok: true`, selected agent
  `mobile_probe`, selected pane `%2`, and cleanup removed adb reverse and
  unmounted the disposable runtime
- Throwaway stop AVD smoke
  `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18879
  --gateway-timeout 30 --flutter-timeout 300 --harness-timeout 10
  --include-lifecycle-stop`: returned `status: ok`,
  `adb_reverse.mapping: tcp:18879 tcp:18879`, two Flutter integration tests
  passed, `post_harness.skipped: true` with reason
  `lifecycle stop was requested by the AVD smoke`, and cleanup removed adb
  reverse and unmounted the disposable runtime

Plan impact:

- moves the active Next Target to final completion audit against
  [goal-emulator-only.md](../goal-emulator-only.md) and
  [topics/emulator-only-acceptance-checklist.md](../topics/emulator-only-acceptance-checklist.md);
- closes the long-running emulator-only goal while leaving the broader
  `mobile-tmux-control` plan open for post-emulator targets such as production
  relay, release packaging, iPad/iOS validation, or public-route hardening.

### 2026-06-21: Relay Health Diagnostics

Scope: add local source/app relay health diagnostics for unknown host,
disconnected host, relay unreachable, stale device, and host-fingerprint
mismatch states without public relay deployment, public DNS, Cloudflare,
physical device, or non-loopback gateway exposure.

Commits:

- `/home/bfly/yunwei/ccb_source` commit `1112559d`
- mobile app commit `c10e4f1`

Artifacts:

- `/home/bfly/yunwei/ccb_source/lib/mobile_gateway/relay.py`
- `/home/bfly/yunwei/ccb_source/test/test_mobile_gateway_relay.py`
- `app/lib/transport/gateway_route_diagnostics.dart`
- `app/test/gateway_route_diagnostics_test.dart`
- `docs/plantree/plans/mobile-tmux-control/topics/relay-route-provider-spike.md`
- `docs/plantree/plans/mobile-tmux-control/goal-emulator-only.md`

Result:

- source `LocalRelayServerHarness` can simulate relay unreachable state,
  stale device state, and expected/observed host-fingerprint mismatch while
  preserving existing unknown/disconnected host diagnostics;
- app `GatewayRouteDiagnostics` maps source-compatible relay `state` or
  `relay_state` metadata into route-health checks and compares observed relay
  host fingerprint metadata against the stored profile fingerprint;
- route diagnostics remain a route-provider concern and do not alter
  route-agnostic `GatewayTransport`, ProjectView, lifecycle, terminal, or
  relay-envelope schemas.

Verification:

- Source `python3 -m py_compile lib/mobile_gateway/relay.py
  test/test_mobile_gateway_relay.py`: passed
- Source `python3 -m pytest test/test_mobile_gateway_relay.py -q`: 8 tests
  passed
- Source `python3 -m pytest test/test_mobile_gateway_relay.py
  test/test_mobile_gateway_service.py test/test_v2_cli_parser.py
  test/test_v2_cli_render.py test/test_v2_phase2_entrypoint.py -q`: 175 tests
  passed
- Source `git diff --check -- lib/mobile_gateway/relay.py
  test/test_mobile_gateway_relay.py`: passed
- App `flutter test test/gateway_route_diagnostics_test.dart`: 12 tests passed
- App `flutter test test/gateway_route_diagnostics_test.dart
  test/gateway_pairing_test.dart test/relay_protocol_test.dart
  test/relay_gateway_transport_test.dart`: 26 tests passed
- App `flutter test`: 76 tests passed
- App `flutter build apk --debug`: built app-debug APK
- App `flutter analyze`: printed `No issues found!` but exited non-zero due to
  repeated Dart Analysis Server `OS Error: Too many open files, errno = 24`
- App/source `git diff --check` for touched files: passed

Plan impact:

- closes the source/app relay health diagnostics package;
- moves the active Next Target to consolidated emulator-only acceptance
  checklist and refreshed AVD smoke evidence;
- keeps public `relay.seemlab.top`, Cloudflare, public DNS, and physical-device
  validation out of the emulator-only acceptance gate.

### 2026-06-21: Source Local Mobile Relay Harness

Scope: add a source-side fake outbound relay client and local relay server
harness without public networking, production relay deployment, public DNS,
public IP, Cloudflare, physical device, or real E2EE implementation.

Commits:

- `/home/bfly/yunwei/ccb_source` commit `1b438505`

Artifacts:

- `/home/bfly/yunwei/ccb_source/lib/mobile_gateway/relay.py`
- `/home/bfly/yunwei/ccb_source/test/test_mobile_gateway_relay.py`
- `/home/bfly/yunwei/ccb_source/lib/cli/services/mobile.py`
- `/home/bfly/yunwei/ccb_source/lib/cli/render_runtime/ops_views_basic.py`
- `/home/bfly/yunwei/ccb_source/test/test_v2_cli_render.py`

Result:

- `RelayHostRegistration`, `RelayFrame`, and `RelayHandshakeTranscript` mirror
  the app-side local relay contract;
- `MobileGatewayRelayOutboundClient` registers a host into
  `LocalRelayServerHarness` without opening a public listener;
- the harness negotiates client/host hello, stores a session, forwards only
  opaque gateway envelopes, returns ack frames, and reports disconnected or
  unknown host diagnostics;
- `ccb mobile serve --route-provider relay` now emits a local
  `relay_outbound` summary while keeping the actual gateway listener
  loopback-bound;
- tests reject cleartext gateway URLs, pairing/device/terminal tokens,
  project ids, terminal ids, route metadata, and paste text in relay payloads.

Verification:

- Source `python3 -m py_compile lib/mobile_gateway/relay.py
  lib/cli/services/mobile.py lib/cli/render_runtime/ops_views_basic.py
  test/test_mobile_gateway_relay.py test/test_v2_cli_render.py`: passed
- Source `python3 -m pytest test/test_mobile_gateway_relay.py -q`: 7 tests
  passed
- Source `python3 -m pytest test/test_mobile_gateway_relay.py
  test/test_mobile_gateway_service.py test/test_v2_cli_parser.py
  test/test_v2_cli_render.py test/test_v2_phase2_entrypoint.py -q`: 174 tests
  passed
- Source `git diff --check -- lib/mobile_gateway/relay.py
  lib/cli/services/mobile.py lib/cli/render_runtime/ops_views_basic.py
  test/test_mobile_gateway_relay.py test/test_v2_cli_render.py`: passed

Plan impact:

- closes the source-side fake outbound relay client/local relay harness
  package;
- moves the active Next Target to source/app relay health diagnostics and
  emulator-only acceptance checklist consolidation;
- keeps public `relay.seemlab.top`, Cloudflare, public DNS, and physical-device
  validation out of the emulator-only acceptance gate.

### 2026-06-21: Relay Protocol Handshake App Contract

Scope: add app-side relay frame, handshake, and host-outbound registration
contracts without requiring a source outbound client, production relay, public
DNS, public IP, Cloudflare, physical device, or real E2EE implementation.

Commits:

- mobile app commit `3bd2ca1`

Artifacts:

- `app/lib/transport/relay_protocol.dart`
- `app/test/relay_protocol_test.dart`
- `app/lib/ccb_mobile.dart`
- `app/tool/terminal_token_renewal_smoke.dart`
- `app/lib/main.dart`
- `docs/plantree/plans/mobile-tmux-control/topics/relay-route-provider-spike.md`

Result:

- `RelayFrame` now models local `client_hello`, `host_hello`,
  `gateway_envelope`, `ack`, and `close` frames;
- `RelayHandshakeTranscript` validates session, host, version, and public-key
  agreement before a local relay session is ready;
- opaque `RelayGatewayEnvelope` data can be wrapped into relay frames without
  exposing CCB project, terminal, route, or token fields;
- `RelayHostRegistration` defines the host-outbound registration JSON shape
  without local gateway listener metadata or bearer/token material;
- relay protocol tests reject cleartext gateway URLs, route metadata, pairing
  codes, device tokens, terminal tokens, project ids, terminal ids, and paste
  text;
- analyzer-facing cleanup fixed the terminal token-renewal smoke lifecycle
  imports and removed a stale lifecycle result field superseded by the
  lifecycle notifier.

Verification:

- App `flutter test test/relay_protocol_test.dart`: 5 tests passed
- App `flutter test test/relay_protocol_test.dart
  test/relay_gateway_transport_test.dart test/gateway_transport_contract_test.dart
  test/widget_test.dart`: 28 tests passed
- App `dart run tool/terminal_token_renewal_smoke.dart`: returned `status: ok`
  with renewal, resume cursor, input, paste, and close checks passing
- App `flutter test`: 73 tests passed
- App `flutter build apk --debug`: built app-debug APK
- App `flutter analyze`: printed `No issues found!` but exited non-zero due to
  repeated Dart Analysis Server `OS Error: Too many open files, errno = 24`
- `git diff --check`: passed

Plan impact:

- closes the app-side relay frame/handshake/host-registration package;
- moves the active Next Target to a source-side fake outbound relay client and
  local relay server harness;
- keeps public `relay.seemlab.top`, Cloudflare, public DNS, and physical-device
  validation out of the emulator-only acceptance gate.

### 2026-06-21: Relay Transport Envelope Local Adapter

Scope: add fake/local relay transport adapter coverage without requiring a
production relay, public DNS, public IP, Cloudflare, physical device, or real
E2EE implementation.

Commits:

- mobile app commit `f8c5a25`

Artifacts:

- `app/lib/transport/relay_gateway_transport.dart`
- `app/test/relay_gateway_transport_test.dart`
- `app/lib/ccb_mobile.dart`
- `docs/plantree/plans/mobile-tmux-control/topics/relay-route-provider-spike.md`

Result:

- `RelayGatewayTransport` requires relay profiles and rejects non-relay
  profiles;
- the adapter delegates existing `GatewayTransport` operations while recording
  opaque local envelopes for health, device, project list/view, focus,
  readable history, lifecycle, terminal open, terminal frames, and terminal
  input;
- envelope parsing validates positive sequence numbers and base64 opaque
  fields;
- tests prove envelope JSON does not expose CCB project ids, agent/window
  names, terminal ids, terminal tokens, pasted input, route-provider metadata,
  gateway URLs, or relay WebSocket URLs.

Verification:

- App `flutter test test/relay_gateway_transport_test.dart`: 3 tests passed
- App `flutter test test/relay_gateway_transport_test.dart
  test/gateway_transport_contract_test.dart`: 13 tests passed
- App `flutter test`: 68 tests passed
- App `flutter build apk --debug`: built app-debug APK
- `git diff --check`: passed

Plan impact:

- closes the fake/local `RelayGatewayTransport` adapter package;
- moves the active Next Target to source/app relay frame, E2EE handshake, and
  host outbound-client contracts behind local tests;
- keeps public `relay.seemlab.top`, Cloudflare, public DNS, and physical-device
  validation out of the emulator-only acceptance gate.

### 2026-06-21: Relay Route Metadata Guards

Scope: start the relay route-provider spike with local app contract coverage,
without requiring a production relay, public DNS, public IP, Cloudflare, or a
physical device.

Commits:

- mobile app commit `28dc384`

Artifacts:

- `app/lib/transport/gateway_route_diagnostics.dart`
- `app/test/gateway_route_diagnostics_test.dart`
- `app/test/gateway_pairing_test.dart`
- `docs/plantree/plans/mobile-tmux-control/topics/relay-route-provider-spike.md`

Result:

- relay route diagnostics now require an HTTPS origin-only `gateway_url`;
- relay route diagnostics now require a WSS origin-only `websocket_url`;
- device `/v1/devices/me` route metadata must match the stored relay profile
  origin and remain HTTPS origin-only;
- pairing/secure-store tests preserve relay `websocket_url`, capabilities,
  diagnostics, host fingerprint, lifecycle-capable scopes, and profile
  roundtrip without storing the one-time pairing code;
- the relay spike has a durable local-contract plan and follow-up package map.

Verification:

- App `flutter test test/gateway_route_diagnostics_test.dart
  test/gateway_pairing_test.dart`: 15 tests passed
- App `flutter test`: 65 tests passed
- App `flutter build apk --debug`: built app-debug APK
- `git diff --check`: passed

Plan impact:

- closes the first relay metadata/profile contract slice;
- keeps the active Next Target on fake/local RelayGatewayTransport adapter and
  relay frame/E2EE envelope tests;
- keeps production `relay.seemlab.top` deployment out of the emulator-only
  acceptance gate.

### 2026-06-21: Paired AVD Lifecycle Smoke

Scope: make lifecycle/admin controls part of the repeatable Android Emulator
acceptance path while keeping destructive stop isolated to a throwaway runtime.

Commits:

- mobile app commit `f08754f`

Artifacts:

- `app/lib/main.dart`
- `app/integration_test/emulator_gateway_smoke_test.dart`
- `tools/mobile_emulator_ui_smoke.py`
- `app/test/widget_test.dart`

Result:

- the normal source-backed emulator wrapper now drives manual gateway claim,
  route diagnostics, real paired lifecycle wake/open/close, selected-agent live
  terminal control, and post-smoke attachability;
- `--include-lifecycle-stop` runs the destructive stop path only on a
  disposable runtime and records why post-harness terminal assertions are
  skipped;
- Connection details lifecycle state now uses `ValueNotifier`s so an already
  open route updates status/detail after lifecycle actions;
- widget and integration coverage assert lifecycle detail includes CCB
  authority and `no raw tmux`.

Verification:

- App `flutter test test/widget_test.dart`: 10 tests passed
- App `flutter test integration_test/emulator_gateway_smoke_test.dart`: 2
  integration tests passed on `emulator-5554`
- Live emulator UI
  `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18787
  --gateway-timeout 30 --flutter-timeout 300 --harness-timeout 10`: returned
  `status: ok`, `adb_reverse.mapping: tcp:18787 tcp:18787`,
  `integration_smoke.include_lifecycle_stop: false`, two integration tests
  passed, and post-harness `mobile_terminal_target_ok: true`
- Throwaway stop emulator UI
  `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18789
  --gateway-timeout 30 --flutter-timeout 300 --harness-timeout 10
  --include-lifecycle-stop`: returned `status: ok`,
  `adb_reverse.mapping: tcp:18789 tcp:18789`,
  `integration_smoke.include_lifecycle_stop: true`, two integration tests
  passed, and `post_harness.skipped: true`
- App `flutter test`: 61 tests passed
- App `flutter build apk --debug`: built app-debug APK
- `python3 -m py_compile tools/mobile_emulator_ui_smoke.py`: passed
- `git diff --check`: passed

Plan impact:

- closes the live paired AVD lifecycle-smoke TODO;
- moves the active Next Target to the relay route-provider spike with
  emulator-only fake/local acceptance gates;
- keeps Cloudflare, production relay, and public network validation deferred.

### 2026-06-21: Safe Lifecycle Controls Local Coverage

Scope: add CCB-authorized lifecycle controls for emulator-only landing without
raw tmux kill operations, physical devices, public routes, Cloudflare, relay,
or external servers.

Commits:

- `/home/bfly/yunwei/ccb_source` commit `e1ace0b0`
- mobile app commit `b8d9507`

Artifacts:

- `/home/bfly/yunwei/ccb_source/lib/mobile_gateway/service.py`
- `/home/bfly/yunwei/ccb_source/lib/cli/services/mobile.py`
- `/home/bfly/yunwei/ccb_source/test/test_mobile_gateway_service.py`
- `app/lib/models/ccb_project_lifecycle.dart`
- `app/lib/main.dart`
- `app/lib/transport/http_gateway_transport.dart`
- `app/test/http_gateway_transport_test.dart`
- `app/test/gateway_transport_contract_test.dart`
- `app/test/widget_test.dart`
- `app/integration_test/emulator_gateway_smoke_test.dart`

Result:

- source gateway exposes scoped `POST /v1/projects/<project>/lifecycle`;
- wake/open return redacted ProjectView plus lifecycle state, close returns a
  mobile-view lifecycle result, and stop uses CCB authority with
  `force: false`;
- lifecycle responses record `ccb_authority: true` and
  `tmux_kill_server: false`;
- app manual pairing requests `lifecycle` scope;
- Connection details expose wake/open/close/stop lifecycle controls and
  require confirmation before stop;
- transport/repository contracts keep lifecycle data separate from
  route-provider metadata and raw terminal frame schemas.

Verification:

- Source `python3 -m pytest test/test_mobile_gateway_service.py
  test/test_v2_cli_render.py test/test_v2_cli_parser.py -q`: 89 tests passed
- Source `git diff --check -- lib/mobile_gateway/service.py
  lib/cli/services/mobile.py lib/cli/router.py
  test/test_mobile_gateway_service.py`: passed
- App `flutter test test/http_gateway_transport_test.dart
  test/gateway_mobile_ccb_repository_test.dart
  test/gateway_transport_contract_test.dart test/widget_test.dart`: 34 tests
  passed
- App `flutter test`: 61 tests passed
- App `flutter build apk --debug`: built app-debug APK
- App `flutter test integration_test/emulator_gateway_smoke_test.dart`: 2
  integration tests passed on the current emulator run; fake lifecycle UI was
  exercised, while the real paired-gateway case skipped because no pairing code
  was provided for that direct invocation
- App `git diff --check`: passed

Plan impact:

- closes the core safe lifecycle route/UI contract slice;
- keeps the active Next Target on live paired AVD lifecycle smoke against an
  installed source route, with stop restricted to a disposable runtime;
- keeps public relay and Cloudflare out of the emulator-only acceptance gate.

### 2026-06-21: Notification Center And Deep-Link Local Coverage

Scope: add local notification synthesis and in-app deep-link coverage for
ProjectView/Comms attention states without requiring a physical device,
public route, Cloudflare, relay, or external server.

Commits:

- mobile app commit `14e68a7`

Artifacts:

- `app/lib/models/ccb_notification.dart`
- `app/lib/models/ccb_project_view.dart`
- `app/lib/main.dart`
- `app/test/project_view_fixture_test.dart`
- `app/test/widget_test.dart`

Result:

- `CcbProjectView` synthesizes completion, failed, blocked,
  callback-needed, unhealthy-agent, and Comms attention notifications from
  ProjectView-like payloads;
- the app top bar now exposes a notification center with bounded,
  scrollable bottom-sheet layout;
- notification taps select the target agent workspace and surface content or
  Comms target feedback without opening raw terminal mode;
- fixture coverage now includes completed/callback/Comms attention states for
  repeatable local testing.

Verification:

- App `flutter test test/project_view_fixture_test.dart test/widget_test.dart`:
  12 tests passed
- App `flutter test`: 57 tests passed
- App `flutter build apk --debug`: built app-debug APK
- `git diff --check`

Plan impact:

- closes the local notification/deep-link regression TODO for ProjectView and
  Comms deltas;
- keeps the active Next Target on safe lifecycle controls against isolated
  runtime, with optional AVD smoke expansion for the notification path.

### 2026-06-21: Terminal Token-Renewal Local Smoke

Scope: add a repeatable local harness for terminal token-expiry/renewal
behavior without needing a physical device, public route, Cloudflare, relay, or
an emulator-specific expiry hook.

Commits:

- mobile app commit `6d2fab7`

Artifacts:

- `app/tool/terminal_token_renewal_smoke.dart`

Result:

- the harness reuses the production `GatewayTerminalTransport`;
- a fake `GatewayTransport` emits output sequence `11`, then an
  `expired` terminal error frame;
- the transport opens a fresh terminal handle and reconnects with resume cursor
  `11`;
- the renewed terminal-open request preserves the current geometry
  `132x43` with `1000x700` pixels;
- output continues after renewal and input/paste frames are sent through the
  renewed handle.

Verification:

- App `dart run tool/terminal_token_renewal_smoke.dart` returned
  `status: ok`, `renewal_completed: true`, `open_count: 2`,
  `resume_cursors: [null, 11]`, `output_error_count: 0`,
  `post_renewal_input_sent: true`, `post_renewal_paste_sent: true`, and
  `close_completed: true`
- App `flutter test test/gateway_terminal_transport_test.dart`: 3 tests passed
- App `flutter test`: 55 tests passed
- App `flutter build apk --debug`: built app-debug APK
- `git diff --check`

Plan impact:

- closes the explicit terminal token-expiry/renewal local-harness TODO;
- keeps the active Next Target on notification/deep-link coverage and safe
  lifecycle controls against isolated runtime.

### 2026-06-21: Android Emulator UI Covers Terminal Controls

Scope: extend the emulator-only UI smoke from terminal-open visibility to
actual selected-agent terminal control through the AVD app surface.

Commits:

- mobile app commit `5b72330`

Artifacts:

- `app/lib/features/terminal/fake_terminal_screen.dart`
- `app/lib/transport/gateway_terminal_transport.dart`
- `app/test/widget_test.dart`
- `app/integration_test/emulator_gateway_smoke_test.dart`

Result:

- the live terminal view now exposes a phone-stable two-row control bar with
  text input plus send, paste, size-sync, and reconnect icon buttons;
- explicit terminal control statuses are visible and are no longer overwritten
  by best-effort xterm device-status writes during WebSocket reconnects;
- `GatewayTerminalTransport` bounds subscription cancellation during reconnect
  and renewal so a stalled socket close cannot hang the user action forever;
- widget tests prove the terminal UI calls `writeBytes`, `paste`, `resize`,
  and `reconnect` on the injected `TerminalSession`;
- AVD integration now drives the selected-agent gateway terminal controls after
  live gateway claim and terminal open.

Verification:

- App `flutter test test/widget_test.dart
  test/gateway_terminal_transport_test.dart`: 11 tests passed
- App `flutter test`: 55 tests passed
- Script-level loopback
  `tools/mobile_gateway_terminal_smoke.py --gateway-listen 127.0.0.1:18788
  --gateway-timeout 30 --harness-timeout 10` returned `status: ok`,
  `input_sent: true`, `paste_sent: true`, `resize_sent: true`,
  `reconnect_completed: true`, `close_completed: true`, and
  `route_diagnostics_ready: true`
- Live emulator UI
  `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18787
  --gateway-timeout 30 --flutter-timeout 240 --harness-timeout 10` returned
  `status: ok`, `adb_reverse.mapping: tcp:18787 tcp:18787`,
  two integration tests passed on `emulator-5554`, and post-harness
  `mobile_terminal_target_ok: true` for selected agent `mobile_probe` pane `%2`
- `python3 tools/mobile_gateway_terminal_smoke_preflight_test.py`: 13 tests
  passed
- `python3 -m py_compile tools/mobile_emulator_ui_smoke.py`
- App `flutter build apk --debug`: built app-debug APK
- `git diff --check`
- App `flutter analyze` printed `No issues found!` but exited non-zero from
  repeated Dart Analysis Server `OS Error: Too many open files, errno = 24`

Plan impact:

- closes the AVD UI live terminal input/paste/resize/reconnect TODO;
- keeps the active Next Target on terminal token-expiry/renewal simulation
  where feasible, notification/deep-link coverage, and safe lifecycle controls
  against isolated runtime.

### 2026-06-20: Android Emulator UI Smoke Harness

Scope: add the first repeatable AVD-level UI smoke for emulator-only landing,
covering app screen gestures and a live local paired-gateway path.

Commits:

- mobile app commit `9a4a0c2`

Artifacts:

- `app/integration_test/emulator_gateway_smoke_test.dart`
- `tools/mobile_emulator_ui_smoke.py`
- `app/pubspec.yaml`
- `app/pubspec.lock`
- `app/lib/main.dart`

Result:

- Flutter integration tests now run on Android Emulator and drive the actual
  app surface;
- fake fixture coverage proves selected-agent switching, structured Markdown
  content, and vertical readable-history scrolling on device;
- live gateway coverage claims a disposable loopback gateway through the UI,
  checks route diagnostics, activates the stored paired profile, and opens a
  selected-agent gateway terminal until `Gateway WebSocket` is visible;
- host wrapper owns disposable CCB runtime startup, fixed loopback gateway,
  ADB readiness, `adb reverse`, integration-test execution, and cleanup.

Verification:

- App `flutter test integration_test/emulator_gateway_smoke_test.dart
  -d emulator-5554`: 2 integration tests passed
- `tools/mobile_emulator_ui_smoke.py --gateway-listen 127.0.0.1:18787
  --gateway-timeout 30 --flutter-timeout 240 --harness-timeout 10` returned
  `status: ok`, `adb_reverse.mapping: tcp:18787 tcp:18787`,
  `route_provider: lan`, two integration tests passed, and post-harness
  `mobile_terminal_target_ok: true` for `mobile_probe` pane `%2`
- App `flutter test`: 55 tests passed
- `python3 tools/mobile_gateway_terminal_smoke_preflight_test.py`: 13 tests
  passed
- App `flutter build apk --debug`: built app-debug APK
- `python3 -m py_compile tools/mobile_emulator_ui_smoke.py`
- `git diff --check`
- App `flutter analyze` printed `No issues found!` but exited non-zero from
  repeated Dart Analysis Server `OS Error: Too many open files, errno = 24`

Plan impact:

- closes the first Android Emulator UI smoke TODO for app-screen driven
  pairing, route diagnostics, selected-agent reading, history scroll, and
  live terminal open;
- keeps the active Next Target on deeper live terminal input/paste/resize,
  reconnect/token-renewal, notification/deep-link, and lifecycle-control
  emulator coverage.

### 2026-06-20: Loopback Gateway Smoke Covers Readable History

Scope: make the repeatable local gateway smoke prove that selected-agent
reading uses the authenticated `/terminal-history` route before raw terminal
fallback opens.

Commits:

- mobile app commit `be5f345`

Artifacts:

- `app/tool/gateway_terminal_smoke.dart`
- `tools/mobile_gateway_terminal_smoke.py`

Result:

- Dart smoke now focuses the selected agent, fetches readable terminal history
  with `CCB_MOBILE_HISTORY_MAX_LINES` defaulting to 240, rejects missing,
  mismatched, scope-less, pane-less, or stale history, and reports history
  evidence in JSON;
- Python smoke wrapper now fails unless Dart reports
  `terminal_history_loaded: true` and a `terminal_history_source_pane_id`;
- raw terminal output/input/paste/resize/reconnect remains the explicit
  fallback path after selected-agent history is fetched.

Verification:

- App `flutter test test/gateway_mobile_ccb_repository_test.dart
  test/widget_test.dart`: 11 tests passed
- App `flutter analyze`: `No issues found!`
- `python3 -m py_compile tools/mobile_gateway_terminal_smoke.py`
- `python3 tools/mobile_gateway_terminal_smoke_preflight_test.py`: 13 tests
  passed
- App `flutter test`: 55 tests passed
- `git diff --check -- app/tool/gateway_terminal_smoke.dart
  tools/mobile_gateway_terminal_smoke.py`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `terminal_history_loaded: true`,
  `terminal_history_scope: tmux_scrollback`,
  `terminal_history_source_pane_id: %2`,
  `terminal_history_stale: false`, `close_completed: true`, and
  `reconnect_completed: true`

Plan impact:

- closes the script-level selected-agent terminal-history smoke TODO;
- keeps the active Next Target on Android emulator UI smoke for app surface
  gestures, selected-agent switching, connection details, and terminal expiry
  renewal.

### 2026-06-18: Route-Provider Schema Boundary Guards

Scope: harden the app-side invariant that Cloudflare-first/relay-compatible
route metadata stays below the route boundary and out of CCB identity,
ProjectView-derived terminal requests, terminal ids, and terminal frame
schemas.

Commits:

- mobile app commit `c87c924`

Artifacts:

- `app/test/gateway_transport_contract_test.dart`

Result:

- WebSocket frame parsing drops unexpected `route_provider` and `gateway_url`
  fields when re-serializing a frame;
- ProjectView payloads that contain extra route fields still produce
  route-agnostic terminal targets and terminal-open requests;
- terminal handle target summaries omit route-provider metadata;
- terminal ids are checked not to encode Cloudflare host or provider data;
- existing route-provider pairing metadata remains allowed only at the profile
  and pairing boundary.

Verification:

- App `dart format app/test/gateway_transport_contract_test.dart`: formatted
  1 file, 0 changed
- App `flutter test test/gateway_transport_contract_test.dart`: 9 tests passed
- App `flutter test`: 52 tests passed
- app loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `device_gateway_url: ok`, `output_bytes_seen: 5369`,
  `close_completed: true`, and `reconnect_completed: true`
- app `git diff --check`

Plan impact:

- closes the active route-provider schema-boundary TODO;
- keeps the active Next Target on external Cloudflare config/credentials plus
  named/cellular public smoke.

### 2026-06-18: Mobile Developer SSH Diagnostic Removal

Scope: remove the remaining non-release developer SSH diagnostic runtime after
gateway-only terminal smoke covered equivalent output/input/paste/resize and
reconnect validation.

Commits:

- mobile app commit `4b43a4f`

Artifacts:

- `app/lib/main.dart`
- `app/lib/features/terminal/fake_terminal_screen.dart`
- `app/lib/ccb_mobile.dart`
- `app/pubspec.yaml`
- `app/pubspec.lock`
- deleted `app/lib/transport/ssh_terminal_transport.dart`
- deleted `app/test/ssh_terminal_transport_test.dart`
- deleted `app/tool/ssh_direct_terminal_smoke.dart`

Result:

- runtime mode selection now exposes only fake and paired-gateway modes;
- the Developer SSH profile panel and injected SSH transport factory are gone;
- live terminal status now reports the gateway WebSocket path;
- direct `dartssh2` and its SSH-only transitive dependencies were removed from
  the app dependency lockfile;
- SSH direct PTY history remains preserved as validation evidence, but the app
  runtime no longer ships or tests that diagnostic path.

Verification:

- App `flutter pub get`: removed `dartssh2`, `asn1lib`, `pinenacl`, and
  `pointycastle` from `app/pubspec.lock`
- App `dart format app/lib/main.dart
  app/lib/features/terminal/fake_terminal_screen.dart app/lib/ccb_mobile.dart
  app/test/widget_test.dart`: formatted 4 files, 0 changed
- App `flutter test`: 49 tests passed
- app loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `device_gateway_url: ok`, `output_bytes_seen: 5369`,
  `close_completed: true`, and `reconnect_completed: true`
- App `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`, with the existing
  `mobile_scanner` Kotlin Gradle Plugin future-compatibility warning
- App `flutter analyze` and `dart analyze lib test` still return non-zero from
  Dart Analysis Server watcher failures with `OS Error: Too many open files`;
  `flutter analyze` printed `No issues found!` before reporting server errors
- app `git diff --check`

Plan impact:

- closes the active developer SSH diagnostic cleanup TODO;
- keeps the active Next Target on external Cloudflare config/credentials plus
  named/cellular public smoke.

### 2026-06-18: Cloudflare Source Public URL Origin Guard

Scope: make source `ccb mobile serve --public-url` reject non-origin URLs
before pairing metadata is emitted.

Commits:

- `/home/bfly/yunwei/ccb_source` commit `a071e257`

Artifacts:

- `/home/bfly/yunwei/ccb_source/lib/cli/services/mobile.py`
- `/home/bfly/yunwei/ccb_source/test/test_mobile_cli_service.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- source accepts the loopback fallback when `--public-url` is absent or blank;
- source accepts origin-only public URLs and normalizes a trailing slash;
- source rejects path, query, fragment, credentials, and invalid port cases;
- English and Chinese Cloudflare Alpha docs now state that non-origin
  `--public-url` values are rejected before pairing metadata is emitted.

Verification:

- CCB source `python -m py_compile lib/cli/services/mobile.py
  test/test_mobile_cli_service.py`
- CCB source
  `python -m pytest test/test_mobile_cli_service.py
  test/test_v2_cli_parser.py::test_parse_mobile_serve
  test/test_mobile_gateway_service.py::test_pairing_claim_creates_hashed_device_records_and_audit
  -q`: 11 tests passed
- app loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `device_gateway_url: ok`, `output_bytes_seen: 5476`,
  `close_completed: true`, and `reconnect_completed: true`
- source/mobile `git diff --check`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but source/app/harness route-shape guards now align before
  the public run.

### 2026-06-18: Cloudflare Device Route Metadata Diagnostics

Scope: verify that the app profile route and the server-reported
`/v1/devices/me` route metadata agree before a Cloudflare or LAN route is
considered ready.

Commits:

- mobile app commit `1d4e28c`

Artifacts:

- `app/lib/transport/gateway_route_diagnostics.dart`
- `app/test/gateway_route_diagnostics_test.dart`

Result:

- `GatewayRouteDiagnostics` now emits `device_gateway_url`;
- device gateway URL metadata must match the app profile route origin;
- Cloudflare device gateway URLs must also be origin-only;
- mismatched device/profile route origins fail readiness before terminal
  streaming;
- loopback gateway smoke proves the current CCB source `/v1/devices/me`
  metadata passes the new check.

Verification:

- `/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/dart format
  app/lib/transport/gateway_route_diagnostics.dart
  app/test/gateway_route_diagnostics_test.dart`: formatted 2 files, 2 changed
- `/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter test
  test/gateway_route_diagnostics_test.dart`: 6 tests passed
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `device_gateway_url: ok`, `output_bytes_seen: 5473`,
  `close_completed: true`, and `reconnect_completed: true`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but the app now verifies server device route metadata against
  the local profile before using the route.

### 2026-06-18: Cloudflare App Route Origin Diagnostics

Scope: make the mobile app's route diagnostics enforce the same origin-only
Cloudflare gateway URL rule as the named-tunnel smoke preflight.

Commits:

- mobile app commit `9396842`

Artifacts:

- `app/lib/transport/gateway_route_diagnostics.dart`
- `app/test/gateway_route_diagnostics_test.dart`

Result:

- `GatewayRouteDiagnostics` now adds a `cloudflare_origin` check for
  Cloudflare Tunnel profiles;
- Cloudflare gateway URLs with path, query string, fragment, or credentials
  fail route readiness before terminal WebSocket use;
- valid origin-only Cloudflare profiles continue to pass HTTPS/WSS route
  diagnostics;
- LAN route diagnostics remain unchanged.

Verification:

- `/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/dart format
  app/lib/transport/gateway_route_diagnostics.dart
  app/test/gateway_route_diagnostics_test.dart`: formatted 2 files, 0 changed
- `/home/bfly/.local/share/flutter-sdks/3.44.2/flutter/bin/flutter test
  test/gateway_route_diagnostics_test.dart`: 4 tests passed
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5378`, `close_completed: true`, and
  `reconnect_completed: true`
- `flutter analyze` and scoped `dart analyze` hit Dart analysis server
  watcher failures with `OS Error: Too many open files`; the first
  `flutter analyze` run printed `No issues found` before returning non-zero
  because of server errors

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but both the harness preflight and app runtime diagnostics now
  reject non-origin Cloudflare gateway URLs before terminal streaming.

### 2026-06-18: Cloudflare Public URL Origin Guard

Scope: prevent named-tunnel smoke setup from accepting a public gateway URL
that includes a path, query string, fragment, or credentials before the
operator runs the final public smoke.

Commits:

- mobile app commit `53a50dd`
- `/home/bfly/yunwei/ccb_source` docs commit `9cd71bd8`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- named-tunnel preflight now rejects non-origin public URLs before starting
  any disposable CCB runtime;
- blocked output includes `suggested_gateway_public_url`;
- `named_tunnel_smoke_command` and `existing_tunnel_smoke_command` normalize
  to the origin-only URL;
- a trailing slash remains accepted and is normalized in generated commands;
- English and Chinese setup guides document the origin-only public URL rule.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 13 tests
  passed
- CLI preflight with
  `--gateway-public-url https://mobile.example.com/mobile?debug=1#pair`
  returned expected `status: blocked`, missing path/query messages,
  `suggested_gateway_public_url: https://mobile.example.com`, and origin-only
  automated/existing tunnel smoke commands
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5371`, `close_completed: true`, and
  `reconnect_completed: true`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but operators now get an explicit origin-only public URL gate
  before named/cellular validation.

### 2026-06-18: Cloudflare Manual And Existing-Tunnel Smoke Commands

Scope: support operators who start `cloudflared tunnel run` themselves or
already have the named tunnel running outside the smoke harness.

Commits:

- mobile app commit `434ed01`
- `/home/bfly/yunwei/ccb_source` docs commit `93c0de50`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- named-tunnel preflight JSON now includes `cloudflared_run_command`;
- named-tunnel preflight JSON now includes `existing_tunnel_smoke_command`;
- `cloudflared_run_command` preserves the cloudflared binary, config path, and
  optional tunnel name;
- `existing_tunnel_smoke_command` omits `--cloudflared-named-tunnel` and keeps
  the fixed listen, public URL, and `cloudflare_tunnel` route provider;
- English and Chinese setup guides document both command fields.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 11 tests
  passed
- real-environment named-tunnel command with
  `--cloudflared-tunnel-name team-mobile` returned expected
  `cloudflared_run_command`, `existing_tunnel_smoke_command`, and
  `named_tunnel_smoke_command`, preflight `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, and cleanup `runtime_started: false`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5476`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, with both harness-owned and externally managed tunnel smoke
  commands now available from preflight JSON.

### 2026-06-18: Cloudflare Named-Tunnel Copyable Smoke Command

Scope: make the final public smoke command explicit in preflight JSON so the
operator can move from a fixed named-tunnel setup to the automated smoke
without reconstructing arguments by hand.

Commits:

- mobile app commit `3f0a0b5`
- `/home/bfly/yunwei/ccb_source` docs commit `8e047913`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- named-tunnel preflight JSON now includes `named_tunnel_smoke_command`;
- the command preserves custom `cloudflared` binary, config path, tunnel name,
  fixed loopback listen address, public URL, and route provider;
- successful preflight `next_actions` now points to the same exact command;
- English and Chinese setup guides document the copyable command field.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 11 tests
  passed
- real-environment named-tunnel command with
  `--cloudflared-tunnel-name team-mobile` returned expected
  `named_tunnel_smoke_command`, preflight `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, and cleanup `runtime_started: false`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5369`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but preflight now emits the exact automated smoke command to
  run after setup fixes.

### 2026-06-18: Cloudflare Named-Tunnel Fixed Listen Guard

Scope: prevent the named-tunnel preflight from producing unusable
`127.0.0.1:0` Cloudflare ingress guidance or allowing a public/non-loopback
gateway listen value into the named-tunnel smoke path.

Commits:

- mobile app commit `e1e14a2`
- `/home/bfly/yunwei/ccb_source` docs commit `867300d7`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- named-tunnel preflight validates `--gateway-listen` before runtime startup;
- dynamic port `127.0.0.1:0`, non-loopback hosts, malformed listens, and
  out-of-range ports block with targeted `next_actions`;
- blocked output includes `suggested_gateway_listen: 127.0.0.1:8787`;
- `config_template` and setup actions use the fixed loopback suggestion when
  the requested listen is not usable for a named tunnel;
- English and Chinese setup guides state that named tunnels need a fixed
  loopback listen and that the dynamic port is only for LAN/quick-tunnel smoke.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 11 tests
  passed
- real-environment named-tunnel command with default
  `--gateway-listen 127.0.0.1:0` returned expected fixed-port
  `next_actions`, preflight `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, cleanup `runtime_started: false`,
  `suggested_gateway_listen: 127.0.0.1:8787`, and a
  `config_template` origin service `http://127.0.0.1:8787`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5473`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but the preflight no longer hands operators an invalid
  dynamic-port Cloudflare origin.

### 2026-06-18: Cloudflare Named-Tunnel Override Handoff

Scope: keep preflight setup guidance consistent when the operator uses a named
tunnel other than the default `ccb-mobile`.

Commits:

- mobile app commit `11bae28`
- `/home/bfly/yunwei/ccb_source` docs commit `69891f03`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- `--cloudflared-tunnel-name` now flows into named-tunnel preflight;
- blocked preflight JSON reports both the requested
  `cloudflared_tunnel_name` and effective `setup_tunnel_name`;
- setup `next_actions` use the requested tunnel name for
  `cloudflared tunnel create` and `cloudflared tunnel route dns`;
- ok preflight handoff text includes the matching
  `--cloudflared-tunnel-name <name>` argument;
- English and Chinese setup guides document the optional override.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 9 tests
  passed
- real-environment named-tunnel missing-config command with
  `--cloudflared-tunnel-name team-mobile` returned expected `next_actions`,
  preflight `status: blocked`, missing `/home/bfly/.cloudflared/config.yml`,
  cleanup `runtime_started: false`, `cloudflared_tunnel_name: team-mobile`,
  and `setup_tunnel_name: team-mobile`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5378`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target remains external Cloudflare config/credentials plus
  public smoke, but non-default tunnel operators now get consistent setup and
  smoke instructions.

### 2026-06-18: Cloudflare Preflight Next-Actions And Config Template

Scope: make blocked named-tunnel preflight output directly actionable, so the
operator can move from missing Cloudflare setup to the automated public smoke
without cross-referencing multiple docs or manually reconstructing the
Cloudflare config shape.

Commits:

- mobile app commit `eadcece`
- follow-up mobile app commit `de79cde`
- follow-up mobile app commit `2ff36a9`
- `/home/bfly/yunwei/ccb_source` docs commit `9ce07104`
- `/home/bfly/yunwei/ccb_source` docs commit `a2ac6f1e`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- named-tunnel preflight JSON now includes `next_actions`;
- named-tunnel preflight JSON now also includes `config_template`;
- missing config points to `cloudflared tunnel login`, `cloudflared tunnel
  create`, `cloudflared tunnel route dns`, and config creation;
- missing config includes a side-effect-free `~/.cloudflared/config.yml` draft
  with the requested hostname, credentials placeholder, and gateway listen
  origin;
- the generated config draft is covered by a round-trip self-test that writes
  it as `config.yml`, creates the referenced credentials file, and verifies
  hostname/origin preflight returns ok;
- invalid route provider/public URL, missing credentials-file, origin port
  mismatch, and missing hostname ingress produce targeted repair messages;
- successful preflight points to the automated `--cloudflared-named-tunnel`
  smoke command.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 8 tests
  passed
- real-environment named-tunnel missing-config command returned expected
  `next_actions`, `config_template`, preflight `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, and cleanup `runtime_started: false`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5473`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target remains external credentials plus public smoke, but the
  blocked state now tells the operator exactly how to reach that gate and
  provides a self-tested config draft to start from.

### 2026-06-18: Automated Cloudflare Named-Tunnel Smoke Harness

Scope: remove the remaining manual `cloudflared tunnel run` step from
development smoke validation once named-tunnel credentials exist.

Commits:

- mobile app commit `1c2d4de`
- follow-up mobile app commit `f4bb5e5`
- `/home/bfly/yunwei/ccb_source` docs commit `444b648c`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- added `--cloudflared-named-tunnel`;
- rejects combining named-tunnel and quick-tunnel modes;
- runs named-tunnel preflight before `init_project` or `ccb -s`;
- starts `cloudflared tunnel --config <config> run [name]` under harness
  ownership after gateway startup;
- waits for a registered Cloudflare tunnel connection before public health
  readiness and Dart terminal smoke;
- cleanup owns cloudflared, gateway, and disposable CCB runtime only after
  runtime actually starts.
- follow-up test coverage proves failed preflight returns cleanup
  `runtime_started: false` and does not create the disposable project
  directory.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 7 tests
  passed
- named-tunnel missing-config command returned expected `status: error`,
  preflight `status: blocked`, missing `/home/bfly/.cloudflared/config.yml`,
  and cleanup `runtime_started: false`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5378`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target is now external: provision Cloudflare named-tunnel
  config/credentials, run the single-command public smoke, and record evidence.

### 2026-06-18: Hostname-Aware Cloudflare Preflight Self-Test

Scope: make the named-tunnel preflight safe for common multi-ingress
`cloudflared` configs and add local self-test coverage that does not require a
Cloudflare account.

Commits:

- mobile app commit `6f26591`
- `/home/bfly/yunwei/ccb_source` docs commit `973a2707`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- preflight now parses `cloudflared` ingress hostname/service pairs;
- when `--gateway-public-url` has a hostname, preflight selects the matching
  ingress service instead of the first HTTP service;
- multi-ingress configs block if no ingress hostname matches the public URL;
- matched origins block if their port does not match `--gateway-listen`;
- source docs now explain the multi-ingress hostname matching rule.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py
  tools/mobile_gateway_terminal_smoke_preflight_test.py`
- `python tools/mobile_gateway_terminal_smoke_preflight_test.py`: 4 tests
  passed
- real-environment preflight returned expected `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, and `origin_selection: none`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5473`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- the remaining Cloudflare gate is external configuration and public-route
  evidence, not untested preflight logic.

### 2026-06-18: Cloudflare Named-Tunnel Preflight

Scope: make the named-tunnel gate diagnosable before starting disposable CCB
runtime, so missing Cloudflare credentials/config are separated from gateway or
terminal smoke failures.

Commits:

- mobile app commit `4f41391`
- `/home/bfly/yunwei/ccb_source` docs commit `44ba9edd`

Artifacts:

- `tools/mobile_gateway_terminal_smoke.py`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`

Result:

- added `--cloudflared-named-tunnel-preflight`;
- checks `cloudflared` binary/version, `~/.cloudflared/config.yml`, configured
  tunnel, credentials-file, public HTTPS URL, route provider, and origin/listen
  match;
- exits before creating a disposable CCB project or starting `ccb mobile
  serve`;
- documents the preflight before the full named-tunnel smoke command.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py`
- preflight command with `/tmp/ccb-mobile-cloudflared/cloudflared` returned
  expected exit code `1`, `status: blocked`, missing
  `/home/bfly/.cloudflared/config.yml`, and warning for missing
  `/home/bfly/.cloudflared/cert.pem`
- loopback `tools/mobile_gateway_terminal_smoke.py --gateway-timeout 30
  --dart-timeout 120 --harness-timeout 10` returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `output_bytes_seen: 5493`, `close_completed: true`, and
  `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- active Next Target is now: provision named-tunnel config/credentials, rerun
  preflight to `ok`, then run the full public terminal smoke.

### 2026-06-18: Cloudflare Alpha User-Facing Setup Docs

Scope: promote the Cloudflare named-tunnel setup path from plan-tree notes into
user-facing source documentation without claiming named-tunnel validation has
passed.

Source commit: `/home/bfly/yunwei/ccb_source` `c3c7fd1b`

Artifacts:

- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.md`
- `/home/bfly/yunwei/ccb_source/docs/mobile-cloudflare-alpha.zh.md`
- README links from `/home/bfly/yunwei/ccb_source/README.md` and
  `/home/bfly/yunwei/ccb_source/README_zh.md`

Result:

- documents Cloudflare account/domain and WebSocket prerequisites;
- documents locally-managed named tunnel creation, DNS routing, and
  `~/.cloudflared/config.yml`;
- documents loopback-only `ccb mobile serve --public-url
  https://mobile.example.com --route-provider cloudflare_tunnel`;
- documents mobile pairing, local `ccb mobile devices`, and
  `ccb mobile revoke <device_id>`;
- keeps Quick Tunnels limited to development smoke use;
- preserves named-tunnel or cellular validation as the remaining public route
  gate.

Verification:

- source `git diff --cached --check`
- local precheck found no `/home/bfly/.cloudflared/cert.pem`, so named-tunnel
  validation is not runnable here without Cloudflare account/domain
  credentials.

Plan impact:

- setup documentation is no longer blocked on plan-tree-only notes;
- active Next Target is now evidence collection from the documented named
  tunnel path or an equivalent cellular validation run.

### 2026-06-18: Started Isolated CCB Project Terminal Harness

Scope: validate that a disposable CCB project exposes the facts needed for the
mobile terminal target without touching `/home/bfly/yunwei/ccb_source` or this
repository's active `.ccb` runtime.

Setup:

- commit: `b950e0f`
- project root: `/tmp/ccb-mobile-terminal-run-20260618150322`
- CCB: `ccb (Claude Code Bridge) v7.6.11 4ff0c44 2026-06-18`
- tmux: `tmux 3.6a`
- start command: `ccb -s`
- harness: `tools/mobile_terminal_harness.py --project-root <run_root>`

Result:

- harness status: success
- `mobile_terminal_target_ok`: `true`
- `ccbd` socket discovered under the disposable project `.ccb/ccbd/`
- `project_view` returned namespace epoch `1`
- namespace tmux socket and session were present
- selected agent was `mobile_probe`
- selected pane evidence was `%2`
- generated attach command used `tmux -S <socket> attach-session -t <session>`
- cleanup command `ccb kill -f` returned `kill_status: ok`

Plan impact:

- supports
  [Decision 009](../decisions/009-ssh-direct-pty-first-terminal-slice.md)
  selecting SSH direct PTY for the first real terminal slice;
- closes the current execution question about SSH direct PTY vs gateway PTY
  for the first validation slice;
- moves the active Next Target to implementing the SSH direct terminal adapter
  behind the terminal transport boundary.

### 2026-06-18: SSH Direct PTY Transport Adapter

Scope: implement the first live terminal transport boundary without adding
generic tmux browsing or requiring a CCB gateway first.

Commit: `62d4150`

Artifacts:

- `app/lib/transport/terminal_transport.dart`
- `app/lib/transport/ssh_terminal_transport.dart`
- `app/test/ssh_terminal_transport_test.dart`
- injected live mode in `app/lib/features/terminal/fake_terminal_screen.dart`

Result:

- `TerminalOpenRequest` rejects stale/missing namespace and direct tmux
  evidence before connecting;
- `SshTerminalTransport` uses `dartssh2` to execute only the socket-aware
  attach command generated from `CcbTerminalTarget`;
- live terminal sessions forward output into `xterm` and forward input,
  paste, resize, and reconnect through the transport boundary;
- default app behavior remains fake/read-only until a developer SSH profile or
  later pairing flow injects the live transport.

Verification:

- `flutter test`: all 18 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- moves the active Next Target to developer SSH profile wiring and live
  isolated CCB project validation;
- preserves `GatewayTransport` as the product route for Cloudflare Tunnel,
  tokens, content, notifications, lifecycle, and relay compatibility.

### 2026-06-18: Developer SSH Profile Entry Point

Scope: make the SSH direct PTY transport reachable from the app without
hard-coded credentials and without changing the default fake terminal path.

Commit: `cf3bc9d`

Artifacts:

- `app/lib/main.dart`
- `app/test/widget_test.dart`

Result:

- `ProjectHomeScreen` now holds an in-memory developer SSH profile;
- host, port, username, and optional password create an injected
  `SshTerminalTransport`;
- tapping an agent uses live transport only when the developer profile is
  enabled;
- fake/read-only terminal behavior remains the default;
- widget coverage proves the injected path still launches the socket-aware
  CCB attach command.

Verification:

- `flutter test`: all 19 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- moves the active Next Target to live SSH direct PTY validation against a
  started isolated CCB project;
- keeps QR pairing, gateway tokens, Cloudflare Tunnel, content, notifications,
  lifecycle, and relay compatibility as later GatewayTransport work.

### 2026-06-18: SSH Direct PTY Live Smoke

Scope: validate the real `SshTerminalTransport` path against a started isolated
CCB project over SSH without modifying user SSH state.

Commit: `25cbbf4`

Artifacts:

- `app/tool/ssh_direct_terminal_smoke.dart`
- `app/lib/transport/ssh_terminal_transport.dart`

Setup:

- temporary root: `/tmp/ccb-mobile-ssh-live-20260618152739`
- temporary sshd: localhost port `50823`
- disposable CCB project:
  `/tmp/ccb-mobile-ssh-live-20260618152739/project`
- CCB selected agent: `mobile_probe`
- namespace epoch: `1`
- tmux session: `ccb-project-c2eb54da`

Result:

- temporary sshd accepted one-time key login;
- isolated harness returned `mobile_terminal_target_ok: true`;
- smoke opened the socket-aware command through `SshTerminalTransport`;
- smoke sent tmux client input/paste, resized, reconnected, and exited with
  `status: ok`;
- `output_bytes_seen` was `4096`;
- `close_timed_out` was `true`, so the adapter now bounds SSH close waits;
- post-smoke harness still returned `mobile_terminal_target_ok: true`.

Verification:

- `flutter test`: all 19 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the SSH direct live-validation TODO for the host-side transport path;
- keeps Android `flutter run` smoke as the remaining mobile runtime gate;
- moves the active Next Target to Android emulator/device smoke plus the next
  gateway contract checkpoint.

### 2026-06-18: Android Emulator Flutter Run Smoke

Scope: verify the Flutter app starts on an Android runtime, not only through
unit/widget tests or APK build.

Commit: `87f5b5a`

Setup:

- helper: `tools/mobile_toolchain_env.sh`
- system image: `system-images;android-35;google_apis;x86_64`
- AVD: `ccb_mobile_api35`
- AVD path: `/home/bfly/.android/avd/ccb_mobile_api35.avd`
- emulator device id: `emulator-5554`
- Android runtime: Android 15 API 35

Result:

- headless emulator booted with `sys.boot_completed=1`;
- `flutter devices` detected `sdk gphone64 x86 64`;
- `flutter run -d emulator-5554 --debug --target lib/main.dart --no-hot`
  built and installed the app;
- Flutter run key commands and Dart VM Service were reported;
- `adb shell pidof io.ccb.mobile.ccb_mobile` returned pid `3170`;
- `adb shell pm path io.ccb.mobile.ccb_mobile` returned the installed APK path;
- `dumpsys activity top` showed
  `io.ccb.mobile.ccb_mobile/.MainActivity` with pid `3170`.

Plan impact:

- closes the Android emulator/device smoke gate for the current native base;
- moves the active Next Target to app-side gateway transport boundary work.

### 2026-06-18: Gateway Contract Checkpoint

Scope: freeze the next route-agnostic gateway boundary before adding
`ccb mobile serve`, Cloudflare Tunnel, content, notifications, or lifecycle
implementation.

Commit: `87f5b5a`

Artifact:

- [../topics/gateway-contract-checkpoint.md](../topics/gateway-contract-checkpoint.md)

Result:

- records boundary rules for `GatewayTransport`, `RouteProvider`, SSH fallback,
  and Cloudflare-first remote access;
- defines app-facing repository operations;
- sketches pairing envelope, gateway HTTP endpoints, terminal open response,
  terminal frames, replay/stale-target behavior, and close semantics;
- lists the CCB source ready-check questions that must be answered before
  editing `/home/bfly/yunwei/ccb_source`;
- defines the acceptance gate for the first gateway implementation package.

Plan impact:

- moves the active Next Target to app-side `GatewayTransport` and
  `RouteProvider` interfaces with fake gateway tests;
- keeps direct CCB source gateway work behind a separate ready-check.

### 2026-06-18: App-Side Gateway Transport Boundary

Scope: implement the Flutter-side gateway contract boundary without adding
server gateway code or editing `/home/bfly/yunwei/ccb_source`.

Commit: `e8a931b`

Artifacts:

- `app/lib/transport/route_provider.dart`
- `app/lib/transport/gateway_transport.dart`
- `app/test/gateway_transport_contract_test.dart`

Result:

- `RouteProviderKind`, `RouteProvider`, and `GatewayHostProfile` model
  LAN/tailnet/Cloudflare/relay reachability below the app repository layer;
- `GatewayTransport` defines health, project list/view, focus, terminal open,
  terminal frames, and frame-send operations;
- `GatewayTerminalOpenRequest` serializes CCB identity and geometry while
  omitting tmux socket/session evidence;
- terminal frames are route agnostic and include sequence numbers for input,
  paste, and output;
- fake gateway tests prove route-provider metadata stays out of project ids,
  terminal ids, ProjectView payloads, and terminal frame semantics.

Verification:

- `flutter test`: all 24 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- moves the active Next Target to the CCB source ready-check for
  `ccb mobile serve`;
- keeps direct source edits blocked until runtime ownership, storage, endpoint
  reuse, terminal ownership, registry, source files, and verification gates are
  recorded.

### 2026-06-18: CCB Source Ready-Check For Mobile Gateway

Scope: open the first CCB source gateway package by answering the
`ccb mobile serve` runtime ownership, storage, endpoint reuse, terminal PTY,
project registry, source file, and verification questions.

Artifacts:

- commit: `e64029f`
- [../topics/ccb-mobile-serve-ready-check.md](../topics/ccb-mobile-serve-ready-check.md)
- [../decisions/010-cli-managed-mobile-gateway-sidecar.md](../decisions/010-cli-managed-mobile-gateway-sidecar.md)

Source snapshot:

- CCB source checkout: `/home/bfly/yunwei/ccb_source`
- CCB source version: `7.6.12`
- CCB source status: clean before ready-check inspection

Result:

- selected `ccb mobile serve` as a CLI-managed, loopback-first,
  current-project gateway sidecar;
- kept `ccbd` as project authority for ProjectView, focus, namespace epoch,
  tmux socket/session facts, lifecycle, Comms, and jobs;
- selected `PathLayout(project_root).ccbd_dir / "mobile"` for first mobile
  device/token/audit state;
- selected existing `CcbdClient` endpoints for `ping`, `project_view`,
  `project_focus_agent`, and `project_focus_window`;
- selected gateway-owned PTY/WebSocket streaming for the first product
  terminal path, with ccbd validation before attach;
- limited the first source package to loopback health, current project list,
  and ProjectView routes.

Plan impact:

- unblocks G1 source work in `/home/bfly/yunwei/ccb_source`;
- keeps public exposure, Cloudflare remote use, QR pairing, terminal tokens,
  content, notifications, lifecycle, and multi-project registry as later
  packages behind the same `GatewayTransport` boundary.

### 2026-06-18: CCB Source G1 Mobile Gateway Skeleton

Scope: land the first loopback current-project `ccb mobile serve` skeleton in
the CCB source checkout without adding public exposure, pairing, terminal
WebSocket streaming, or multi-project registry.

Source commit: `/home/bfly/yunwei/ccb_source` `bcee866e`

Artifacts:

- `lib/mobile_gateway/`
- `lib/cli/services/mobile.py`
- CLI parser/dispatch/render integration for `ccb mobile serve`
- `lib/storage/paths_ccbd.py` mobile state path properties
- `test/test_mobile_gateway_service.py`
- focused additions to parser/render/router/phase2 tests

Result:

- `ccb mobile serve` is a normal phase2 CLI command;
- default listen is `127.0.0.1:8787`;
- non-loopback listen addresses are rejected in G1;
- G1 HTTP endpoints are `/v1/health`, `/v1/projects`, and
  `/v1/projects/{project_id}/view`;
- project list is current-project only;
- ProjectView gateway responses redact server-side tmux socket/session fields;
- stopping the gateway handle closes the HTTP server and does not call ccbd
  stop/shutdown or raw tmux kill operations.

Verification:

- `git diff --check`
- `python -m py_compile lib/mobile_gateway/service.py
  lib/cli/services/mobile.py lib/cli/phase2_runtime/handlers_ops.py`
- `HOME=/home/bfly/yunwei/test_ccb2/source_home
  CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home
  /home/bfly/yunwei/ccb_source/ccb_test --diagnose`
- same environment with `/home/bfly/yunwei/ccb_source/ccb_test mobile serve
  --help`
- `python -m pytest test/test_mobile_gateway_service.py
  test/test_v2_cli_parser.py test/test_v2_cli_render.py
  test/test_v2_cli_router.py
  test/test_v2_phase2_entrypoint.py::test_phase2_mobile_serve_uses_gateway_prepare`
  passed 134 tests.

Plan impact:

- moves the active Next Target to app-side `GatewayTransport` HTTP client and
  repository wiring against the G1 JSON shape;
- G2 source work should focus on pairing/device/token storage only after app
  wiring proves the G1 contract.

### 2026-06-18: App G1 HTTP Gateway Wiring

Scope: consume the landed G1 `ccb mobile serve` JSON shape from the Flutter
app without adding pairing, focus routes, terminal WebSocket streaming, or
public exposure.

Commit: `aaec0ad`

Artifacts:

- `app/lib/transport/http_gateway_transport.dart`
- `app/lib/repository/gateway_mobile_ccb_repository.dart`
- `app/test/http_gateway_transport_test.dart`
- `app/test/gateway_mobile_ccb_repository_test.dart`

Result:

- `HttpGatewayTransport` reads `/v1/health`, `/v1/projects`, and
  `/v1/projects/{project_id}/view`;
- local HTTP gateway tests use the G1 JSON shape and verify ProjectView tmux
  socket/session redaction;
- `GatewayMobileCcbRepository` adapts the gateway transport to the existing
  `MobileCcbRepository` interface;
- G1 routes not exposed by the gateway, including focus and terminal open,
  remain fail-closed.

Verification:

- `git diff --check`
- `flutter test`: 30 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the app-side G1 HTTP transport/repository TODO;
- moves the active Next Target to G2 pairing/device-token source work plus app
  host-profile import/persistence.

### 2026-06-18: G2 Pairing And Device-Token Foundation

Scope: add the first secure pairing/device-token foundation on both sides of
the gateway before exposing focus or terminal input routes.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `55c26078`
- mobile app commit `d01a338`

Artifacts:

- source `lib/mobile_gateway/pairing.py`
- source `lib/mobile_gateway/service.py`
- source `lib/cli/services/mobile.py`
- app `app/lib/pairing/gateway_pairing.dart`
- app `app/lib/transport/http_gateway_transport.dart`
- source/app focused tests for pairing, token hashing, secure profile storage,
  and bearer-token injection

Result:

- `ccb mobile serve` emits a short-lived pairing code in the CLI summary;
- pairing codes and device tokens are stored only as hashes under
  `.ccb/ccbd/mobile`;
- `POST /v1/pairing/claim` exchanges a one-time pairing code for a device
  token and host profile;
- bearer-token `GET /v1/devices/me` validates device tokens and scopes;
- `POST /v1/devices/{device_id}/revoke` supports G2 self-revoke;
- mobile audit JSONL records metadata only and does not store token plaintext
  or terminal bytes;
- the Flutter app can parse the pairing payload, claim it, persist the paired
  profile/device token through `flutter_secure_storage`, and inject the token
  into `HttpGatewayTransport`.

Verification:

- CCB source `git diff --check`
- CCB source `python -m py_compile lib/mobile_gateway/service.py
  lib/mobile_gateway/pairing.py lib/cli/services/mobile.py
  lib/cli/render_runtime/ops_views_basic.py`
- CCB source `python -m pytest test/test_mobile_gateway_service.py
  test/test_v2_cli_parser.py test/test_v2_cli_render.py
  test/test_v2_cli_router.py
  test/test_v2_phase2_entrypoint.py::test_phase2_mobile_serve_uses_gateway_prepare`
  passed 136 tests
- CCB source `ccb_test --diagnose`
- CCB source `ccb_test mobile serve --help`
- app `flutter test`: 33 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the G2 pairing/device-token storage and app import TODOs;
- opens authenticated focus-agent/window routes and Flutter pairing/profile UI
  as the next package;
- keeps public/non-loopback exposure blocked until authenticated project routes
  and terminal-token replay behavior are verified.

### 2026-06-18: Authenticated Focus Routes

Scope: expose focus-agent/window through the mobile gateway only after G2
device-token storage exists, and wire the Flutter transport/repository to the
new authenticated routes.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `88f0b568`
- mobile app commit `ba2d51e`

Artifacts:

- source `lib/mobile_gateway/service.py`
- source `lib/cli/services/mobile.py`
- app `app/lib/transport/http_gateway_transport.dart`
- app `app/test/http_gateway_transport_test.dart`
- app `app/test/gateway_mobile_ccb_repository_test.dart`

Result:

- `POST /v1/projects/{project_id}/focus-agent` and `focus-window` require a
  valid device bearer token with `focus` scope;
- gateway focus routes reuse ccbd `project_focus_agent/window` instead of
  manipulating tmux panes directly;
- gateway returns a refreshed ProjectView after focus while still redacting
  tmux socket/session evidence;
- `HttpGatewayTransport.focusAgent/focusWindow` POST the target identity and
  namespace epoch to the gateway with the stored bearer token;
- `GatewayMobileCcbRepository` can focus through the authenticated gateway
  transport and receive the refreshed view.

Verification:

- CCB source `git diff --check`
- CCB source `python -m py_compile lib/mobile_gateway/service.py
  lib/mobile_gateway/pairing.py lib/cli/services/mobile.py
  lib/cli/render_runtime/ops_views_basic.py`
- CCB source `python -m pytest test/test_mobile_gateway_service.py
  test/test_v2_cli_parser.py test/test_v2_cli_render.py
  test/test_v2_cli_router.py
  test/test_v2_phase2_entrypoint.py::test_phase2_mobile_serve_uses_gateway_prepare`
  passed 138 tests
- CCB source `ccb_test --diagnose`
- CCB source `ccb_test mobile serve --help`
- app `flutter test`: 34 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the authenticated focus-agent/window TODO;
- moves the active Next Target to the Flutter pairing/profile UI and explicit
  fake/paired-gateway/developer-SSH runtime modes;
- terminal WebSocket/token work remains a later package.

### 2026-06-18: App Pairing/Profile UI And Runtime Modes

Scope: make the paired gateway path selectable in the Flutter app without
pretending gateway terminal WebSocket support exists yet.

Commit: `6359df1`

Artifacts:

- `app/lib/main.dart`
- `app/test/widget_test.dart`

Result:

- the app has explicit fake, paired gateway, and developer SSH runtime modes;
- manual gateway URL + pairing code form calls `GatewayPairingClient` through
  an injectable claim-and-store boundary;
- secure paired profiles load from `GatewayHostProfileStore`;
- selecting a paired profile activates `GatewayMobileCcbRepository`;
- in paired gateway mode, tapping an agent calls authenticated focus and
  refreshes ProjectView instead of opening a fake/direct SSH terminal;
- developer SSH remains a distinct developer mode and fake remains the
  default.

Verification:

- `git diff --check`
- `flutter test`: 35 tests passed
- `flutter analyze`: no issues found
- `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the manual pairing/profile UI and explicit runtime-mode TODOs;
- opens terminal-open/token/WebSocket source work and app gateway-terminal
  wiring as the next package;
- QR camera scanning remains a follow-up after the manual pairing path.

### 2026-06-18: Terminal-Open Token Foundation

Scope: add the first authenticated gateway terminal-open route and app-side
handle parsing without claiming WebSocket frame streaming is complete.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `dfcb7af7`
- mobile app commit `faa3039`

Artifacts:

- source `lib/mobile_gateway/pairing.py`
- source `lib/mobile_gateway/service.py`
- source `lib/cli/services/mobile.py`
- source `lib/cli/router.py`
- source `test/test_mobile_gateway_service.py`
- app `app/lib/transport/http_gateway_transport.dart`
- app `app/test/http_gateway_transport_test.dart`

Result:

- `POST /v1/projects/{project_id}/terminals` requires a device bearer token
  with `terminal_input` scope;
- default `ccb mobile serve` pairing scopes now include `terminal_input`;
- the gateway validates project id, namespace epoch, target kind, and
  agent/window identity through unredacted ProjectView before minting a
  terminal token;
- terminal tokens are stored only as hashes under
  `.ccb/ccbd/mobile/terminal-tokens.jsonl`;
- terminal-open audit metadata avoids token plaintext and terminal bytes;
- terminal-open responses include terminal id, terminal token, expiry,
  WebSocket URL, target epoch, and redacted target summary without tmux
  socket/session evidence;
- `HttpGatewayTransport.openTerminal` POSTs the existing terminal-open request
  shape, injects the device token as an Authorization header, and parses the
  returned handle;
- terminal frame streaming remains fail-closed in the app until the gateway
  WebSocket/PTy package lands.

Verification:

- CCB source `python -m py_compile lib/mobile_gateway/service.py
  lib/mobile_gateway/pairing.py lib/cli/services/mobile.py lib/cli/router.py
  lib/cli/render_runtime/ops_views_basic.py`
- CCB source `python -m pytest test/test_mobile_gateway_service.py` passed
  10 tests
- CCB source `python -m pytest test/test_v2_cli_parser.py
  test/test_v2_cli_render.py test/test_v2_cli_router.py
  test/test_v2_phase2_entrypoint.py::test_phase2_mobile_serve_uses_gateway_prepare`
  passed 130 tests
- CCB source `git diff --check`
- CCB source `ccb_test --diagnose`
- CCB source `ccb_test mobile serve --help`
- app targeted `flutter test test/http_gateway_transport_test.dart`: 6 tests
  passed
- app `flutter test`: 36 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the terminal-open/token foundation TODO;
- moves the active Next Target to gateway terminal WebSocket/PTy frame
  streaming and app `terminalFrames`/`sendTerminalFrame` wiring;
- keeps Cloudflare/public exposure blocked until terminal replay behavior,
  tunnel diagnostics, and broader audit/revocation behavior are verified.

### 2026-06-18: Terminal WebSocket/PTy Streaming Foundation

Scope: add the first route-agnostic gateway terminal WebSocket stream and
Flutter frame transport while leaving paired-gateway UI integration and real
isolated smoke as the next package.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `8ce445f1`
- mobile app commit `f3e2d78`

Artifacts:

- source `lib/mobile_gateway/terminal.py`
- source `lib/mobile_gateway/websocket.py`
- source `lib/mobile_gateway/service.py`
- source `lib/mobile_gateway/pairing.py`
- source `test/test_mobile_gateway_service.py`
- app `app/lib/transport/gateway_transport.dart`
- app `app/lib/transport/http_gateway_transport.dart`
- app `app/test/http_gateway_transport_test.dart`

Result:

- `GET /v1/terminals/{terminal_id}` upgrades to a terminal WebSocket stream;
- the first client frame must be an `open` frame carrying terminal id and
  terminal token;
- the gateway validates terminal tokens against hashed records, revalidates
  ProjectView namespace epoch and agent/window target identity, and then opens
  a server-side tmux attach client;
- output/input/paste/resize/closed/error frames follow the existing
  route-agnostic frame schema;
- input and paste frames enforce monotonic sequence numbers before bytes/text
  reach the attach client;
- close remains client-scoped and does not stop `ccbd`, provider panes, or the
  project tmux session;
- app `HttpGatewayTransport.terminalFrames` connects to the WebSocket and
  sends the `open` frame automatically;
- app `sendTerminalFrame` sends input/paste/resize/closed frames over the
  active socket and fails closed when no socket is active.

Verification:

- CCB source `python -m py_compile lib/mobile_gateway/service.py
  lib/mobile_gateway/pairing.py lib/mobile_gateway/terminal.py
  lib/mobile_gateway/websocket.py lib/cli/services/mobile.py
  lib/cli/router.py lib/cli/render_runtime/ops_views_basic.py`
- CCB source `python -m pytest test/test_mobile_gateway_service.py
  test/test_v2_cli_parser.py test/test_v2_cli_render.py
  test/test_v2_cli_router.py
  test/test_v2_phase2_entrypoint.py::test_phase2_mobile_serve_uses_gateway_prepare`
  passed 142 tests
- CCB source `git diff --check`
- CCB source `ccb_test --diagnose`
- CCB source `ccb_test mobile serve --help`
- app targeted `flutter test test/http_gateway_transport_test.dart`: 7 tests
  passed
- app `flutter test`: 37 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`

Plan impact:

- closes the source/app terminal WebSocket frame transport TODO;
- moves the active Next Target to paired-gateway terminal UI integration and
  isolated gateway terminal smoke;
- keeps Cloudflare/public exposure blocked until the real gateway smoke,
  reconnect behavior, tunnel diagnostics, and broader audit/revocation
  behavior are verified.

### 2026-06-18: Paired Gateway Terminal UI

Scope: make the existing terminal screen reachable from paired gateway mode
using gateway terminal handles and WebSocket frames instead of direct tmux
attach evidence.

Commit: `5b3c985`

Artifacts:

- `app/lib/transport/gateway_terminal_transport.dart`
- `app/lib/transport/terminal_transport.dart`
- `app/lib/features/terminal/fake_terminal_screen.dart`
- `app/lib/main.dart`
- `app/test/gateway_terminal_transport_test.dart`
- `app/test/widget_test.dart`

Result:

- paired gateway mode now creates a `GatewayTerminalTransport`;
- manual pairing asks for `terminal_input` in addition to `view` and `focus`;
- tapping an agent focuses through the authenticated gateway route, then opens
  the existing terminal screen through a gateway terminal request;
- gateway terminal sessions open a terminal handle, stream output frames into
  `TerminalSession.output`, and send input/paste/resize/closed frames back
  through the gateway transport;
- gateway reconnect fails closed until the app and gateway have a resume cursor
  contract;
- redacted paired-gateway ProjectView data no longer needs tmux socket/session
  evidence in the Flutter UI.

Verification:

- app targeted `flutter test test/gateway_terminal_transport_test.dart
  test/http_gateway_transport_test.dart test/widget_test.dart`: 13 tests
  passed
- app `flutter test`: 39 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `git diff --check`

Plan impact:

- closes the paired-gateway agent terminal UI TODO;
- moves the active Next Target to isolated gateway terminal smoke against a
  disposable CCB project;
- keeps window-specific terminal UI, QR scanning, and Cloudflare/public
  exposure behind later gates.

### 2026-06-18: Isolated Gateway Terminal Smoke

Scope: prove the paired-gateway terminal path against a disposable source-backed
CCB project instead of only local fake WebSocket/widget coverage.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `0ac903f4`
- mobile app commit `03c6925`

Artifacts:

- source `lib/ccbd/project_focus/service.py`
- source `test/test_ccbd_project_focus.py`
- app `tools/mobile_gateway_terminal_smoke.py`
- app `app/tool/gateway_terminal_smoke.dart`
- app `app/lib/pairing/gateway_pairing.dart`
- app `app/lib/transport/http_gateway_transport.dart`
- app `app/test/gateway_pairing_test.dart`
- app `app/test/http_gateway_transport_test.dart`

Result:

- source `project_focus_agent` now focuses the pane found through CCB pane
  options, so logical CCB window names do not need to match actual tmux window
  names;
- the smoke starts a disposable CCB project under `/home/bfly/yunwei/test_ccb2`
  with agent `mobile_probe`;
- source `ccb mobile serve` starts on a loopback ephemeral port and emits a
  pairing summary;
- the Dart smoke claims the pairing code, reads health/projects/ProjectView,
  focuses the selected agent, opens a terminal handle, and verifies the gateway
  terminal target remains redacted with no direct tmux evidence;
- the real gateway WebSocket/PTy path streams output and accepts input, paste,
  resize, and close frames;
- reconnect remains fail-closed until a resume cursor contract is designed;
- cleanup stops the gateway process and kills the disposable CCB runtime.

Latest smoke evidence:

- command: `tools/mobile_gateway_terminal_smoke.py`
- status: `ok`
- disposable project:
  `/home/bfly/yunwei/test_ccb2/ccb-mobile-gateway-smoke-20260618095356`
- selected agent/window: `mobile_probe` / `main`
- namespace epoch: `1`
- `target_has_direct_tmux_evidence: false`
- `output_bytes_seen: 5476`
- `input_sent: true`, `paste_sent: true`, `resize_sent: true`
- `close_completed: true`
- `reconnect_failed_closed: true`
- cleanup: `ccb kill -f` returned `kill_status: ok`

Verification:

- CCB source `python -m py_compile lib/ccbd/project_focus/service.py`
- CCB source `python -m pytest test/test_ccbd_project_focus.py
  test/test_mobile_gateway_service.py`: 23 tests passed
- CCB source `git diff --check`
- app `python -m py_compile tools/mobile_gateway_terminal_smoke.py`
- app `dart format --set-exit-if-changed` on touched Dart files
- app `flutter test`: 39 tests passed
- app `flutter analyze`: no Dart issues found, but the Analysis Server emitted
  `Too many open files` handler errors in this environment and returned nonzero
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `git diff --check`

Plan impact:

- closes the isolated gateway terminal smoke TODO;
- moves the active Next Target to window-level terminal/focus UI;
- keeps QR scanning, reconnect resume, tunnel diagnostics, and public
  Cloudflare/non-loopback gateway exposure behind later gates.

### 2026-06-18: Window-Level Terminal/Focus UI

Scope: expose configured CCB windows as first-class mobile targets instead of
only opening terminals through agent taps.

Commit: `92312e0`

Artifacts:

- `app/lib/models/ccb_terminal_target.dart`
- `app/lib/models/ccb_project_view.dart`
- `app/lib/features/terminal/fake_terminal_screen.dart`
- `app/lib/main.dart`
- `app/test/ccb_terminal_target_test.dart`
- `app/test/project_view_fixture_test.dart`
- `app/test/gateway_transport_contract_test.dart`
- `app/test/widget_test.dart`

Result:

- `CcbTerminalTarget.windowActivePane` represents a stable window terminal
  identity with `terminal_input` scope;
- `CcbProjectView.terminalTargetForWindow` maps ProjectView windows into
  `window_active_pane` targets and includes the active pane id only when the
  requested window is active;
- gateway terminal-open serialization sends `kind: window_active_pane` with
  window identity while keeping tmux socket/session evidence out of the remote
  request;
- `FakeTerminalScreen` now opens either an agent target or a window target;
- the home screen renders a separate `Windows` section before agents;
- paired gateway window taps call authenticated `focusWindow`, refresh
  ProjectView, and open the existing gateway terminal transport for the
  selected window;
- fake mode can open a read-only window terminal transcript, and developer SSH
  mode can inject the same terminal transport boundary for window targets.

Verification:

- targeted `flutter test test/ccb_terminal_target_test.dart
  test/project_view_fixture_test.dart test/gateway_transport_contract_test.dart
  test/widget_test.dart`: 17 tests passed
- app `flutter test`: 42 tests passed
- app `flutter analyze`: no Dart issues found, but the Analysis Server emitted
  `Too many open files` handler errors in this environment and returned nonzero
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `tools/mobile_gateway_terminal_smoke.py`: returned `status: ok`,
  `output_bytes_seen: 5378`, `close_completed: true`, and
  `reconnect_failed_closed: true`
- app `git diff --check`

Plan impact:

- closes the window-level terminal/focus UI TODO;
- moves the active Next Target to QR camera scanning for gateway pairing;
- keeps reconnect resume, tunnel diagnostics, broader audit/revocation, and
  public Cloudflare/non-loopback gateway exposure behind later gates.

### 2026-06-18: QR Camera Pairing Scanner

Scope: make the source gateway pairing payload claimable from a phone camera
instead of requiring manual gateway URL and pairing code entry.

Commit: `b3f03ab`

Artifacts:

- `app/lib/pairing/gateway_pairing_scanner_screen.dart`
- `app/lib/pairing/gateway_pairing.dart`
- `app/lib/main.dart`
- `app/android/app/src/main/AndroidManifest.xml`
- `app/ios/Runner/Info.plist`
- `app/test/gateway_pairing_test.dart`
- `app/test/widget_test.dart`

Result:

- the app reuses `mobile_scanner` 7.2.0 for QR detection;
- Android and iOS declare camera permission metadata;
- source-shaped pairing JSON scans parse through
  `GatewayPairingPayload.fromQrText`;
- the Pair Gateway panel exposes `Scan QR`, then sends the scanned payload
  through the existing secure claim-and-store path;
- no `/home/bfly/yunwei/ccb_source` change was required because the existing
  pairing payload already includes `pairing_code`, `project_id`,
  `route_provider`, `gateway_url`, `claim_endpoint`, `scopes`, and
  `expires_at`.

Verification:

- app focused `flutter test test/gateway_pairing_test.dart
  test/widget_test.dart`: 11 tests passed
- app `flutter test`: 45 tests passed
- app `dart format --set-exit-if-changed` on touched Dart files
- app `flutter analyze`: no Dart issues found, but the Analysis Server emitted
  `Too many open files` handler errors in this environment and returned nonzero
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `git diff --check`

Plan impact:

- closes the QR pairing TODO for normal paired-gateway onboarding;
- moves the active Next Target to reducing or replacing the developer-only SSH
  profile with a safer short-lived credential flow;
- keeps reconnect resume, tunnel diagnostics, broader audit/revocation, and
  public Cloudflare/non-loopback gateway exposure behind later gates.

### 2026-06-18: Release Developer SSH Gate

Scope: remove the developer SSH profile from release/user-facing builds while
keeping the non-release diagnostic transport available for local validation.

Commit: `2590a97`

Artifacts:

- `app/lib/main.dart`
- `app/test/widget_test.dart`

Result:

- `ProjectHomeScreen.allowDeveloperSsh` defaults to `!kReleaseMode`;
- release builds do not expose the SSH runtime segment or Developer SSH
  profile panel;
- disabled SSH mode attempts fail closed and do not create an
  `SshTerminalTransport`;
- existing developer SSH widget coverage explicitly enables the diagnostic
  path, so local non-release smoke validation remains possible.

Verification:

- app `flutter test test/widget_test.dart`: 7 tests passed
- app `flutter test`: 46 tests passed
- app `dart format --set-exit-if-changed` on touched Dart files
- app `flutter analyze`: no Dart issues found, but the Analysis Server emitted
  `Too many open files` handler errors in this environment and returned nonzero
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `flutter build apk --release`: built
  `app/build/app/outputs/flutter-apk/app-release.apk`
- app `git diff --check`

Plan impact:

- closes the user-facing developer SSH exposure before remote release;
- leaves complete SSH removal as a later cleanup once gateway-only smoke
  validation replaces the remaining non-release diagnostic path;
- moves the active Next Target to gateway terminal reconnect/resume cursor
  design before public Cloudflare/non-loopback exposure.

### 2026-06-18: Gateway Terminal Resume Cursor

Scope: replace paired-gateway terminal reconnect fail-closed behavior with a
source/app cursor contract that resumes from the latest verified terminal
output sequence and rejects stale cursors.

Commits:

- `/home/bfly/yunwei/ccb_source` source commit `300f1f80`
- mobile app commit `3bebca4`

Artifacts:

- source `lib/mobile_gateway/pairing.py`
- source `lib/mobile_gateway/service.py`
- source `test/test_mobile_gateway_service.py`
- app `app/lib/transport/gateway_transport.dart`
- app `app/lib/transport/http_gateway_transport.dart`
- app `app/lib/transport/gateway_terminal_transport.dart`
- app `app/test/gateway_terminal_transport_test.dart`
- app `app/test/http_gateway_transport_test.dart`
- app `app/test/gateway_transport_contract_test.dart`
- app `app/tool/gateway_terminal_smoke.dart`

Result:

- source terminal handles persist `last_output_seq` and disconnected state;
- WebSocket open accepts an optional `resume_cursor` and replies with
  `resume_cursor` plus `last_input_seq`;
- transport disconnect marks a handle disconnected instead of closed;
- matching resume cursors reopen the stream from the stored output sequence;
- stale or missing resume cursors after disconnect return explicit errors and
  do not replay stale terminal input;
- the Flutter app records the latest output sequence and reconnects gateway
  terminal streams with that cursor;
- the real isolated gateway smoke now reports `reconnect_completed: true`.

Verification:

- CCB source `python -m py_compile lib/mobile_gateway/service.py
  lib/mobile_gateway/pairing.py lib/mobile_gateway/terminal.py
  lib/mobile_gateway/websocket.py`
- CCB source focused pytest: `144 passed`
- app focused `flutter test test/gateway_terminal_transport_test.dart
  test/http_gateway_transport_test.dart test/gateway_transport_contract_test.dart`:
  16 tests passed
- app `flutter test`: 47 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `tools/mobile_gateway_terminal_smoke.py`: returned `status: ok`,
  `output_bytes_seen: 5476`, `close_completed: true`,
  `close_timed_out: false`, and `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- closes the gateway terminal reconnect/resume cursor TODO;
- keeps developer SSH as non-release diagnostic only;
- moves the active Next Target to Cloudflare Tunnel route diagnostics before
  public/non-loopback gateway exposure.

### 2026-06-18: App-Side Gateway Route Diagnostics

Scope: add the first route readiness gate for Cloudflare/Tunnel work while
keeping route-provider metadata below the `GatewayTransport` boundary and
without changing CCB source contracts.

Commit: `b9555a9`

Artifacts:

- `app/lib/transport/gateway_transport.dart`
- `app/lib/transport/gateway_route_diagnostics.dart`
- `app/lib/transport/http_gateway_transport.dart`
- `app/lib/main.dart`
- `app/test/gateway_route_diagnostics_test.dart`
- `app/test/http_gateway_transport_test.dart`
- `app/test/widget_test.dart`

Result:

- `GatewayTransport.device()` consumes the existing source
  `/v1/devices/me` authenticated device contract;
- `GatewayRouteDiagnostics` checks Cloudflare HTTPS/WSS route shape, gateway
  health and capabilities, paired-device auth, route-provider scope, project
  list reachability, and ProjectView tmux redaction;
- the runtime panel exposes an injectable `Check Route` action and keeps
  Cloudflare-specific behavior out of screen-level branching;
- long gateway profile labels now ellipsize in the runtime dropdown to avoid
  mobile/desktop layout overflow.

Verification:

- app focused `flutter test test/gateway_route_diagnostics_test.dart
  test/http_gateway_transport_test.dart test/gateway_transport_contract_test.dart
  test/gateway_terminal_transport_test.dart test/widget_test.dart`: 28 tests
  passed
- app `flutter test`: 52 tests passed
- app `flutter analyze`: no issues found
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app `git diff --check`

Plan impact:

- closes the app-side route diagnostics TODO;
- keeps public/non-loopback gateway exposure blocked until a repeatable
  Cloudflare Tunnel live smoke/setup path and broader audit/revocation checks
  land;
- moves the active Next Target to Cloudflare Tunnel live smoke and setup notes.

### 2026-06-18: Cloudflare Tunnel Smoke Harness Preparation

Scope: prepare the first repeatable not-on-LAN smoke path without changing the
route-agnostic gateway API or allowing the gateway to bind a public listener.

Commits:

- source `a222446c`
- app `08eed72`

Artifacts:

- `/home/bfly/yunwei/ccb_source/lib/cli/services/mobile.py`
- `/home/bfly/yunwei/ccb_source/lib/cli/parser_runtime/commands.py`
- `tools/mobile_gateway_terminal_smoke.py`
- `app/tool/gateway_terminal_smoke.dart`
- [../topics/cloudflare-tunnel-live-smoke.md](../topics/cloudflare-tunnel-live-smoke.md)

Result:

- `ccb mobile serve` accepts `--public-url` and `--route-provider` and writes
  route metadata into pairing payloads while preserving loopback-only listen
  validation;
- the mobile smoke harness supports a named tunnel URL and a development
  `cloudflared tunnel --url` quick tunnel path;
- the Dart smoke asserts route-provider metadata, runs
  `GatewayRouteDiagnostics`, and then exercises terminal
  output/input/paste/resize/close/reconnect through the gateway terminal
  transport.

Verification:

- source focused pytest: `144 passed`
- app `tools/mobile_gateway_terminal_smoke.py`: returned `status: ok`,
  `route_diagnostics_ready: true`, `target_has_direct_tmux_evidence: false`,
  `output_bytes_seen: 5467`, and `reconnect_completed: true`
- app `flutter test`: 52 tests passed
- app `flutter analyze` and `dart analyze lib test tool`: no Dart issues
  reported, but Analysis Server returned
  `OS Error: Too many open files, errno = 24` while creating watchers in this
  environment
- app `flutter build apk --debug`: built
  `app/build/app/outputs/flutter-apk/app-debug.apk`
- app/source `git diff --check`

Plan impact:

- closes the local Cloudflare smoke harness/setup preparation task;
- leaves live Cloudflare acceptance pending until quick-tunnel DNS or a named
  tunnel hostname resolves through the app process;
- keeps broad public or non-loopback exposure blocked until live smoke and
  broader audit/revocation review pass.

### 2026-06-18: Live Quick-Tunnel Attempt And Resolver Blocker

Scope: run the prepared Cloudflare quick-tunnel smoke far enough to validate
cloudflared startup, gateway route metadata, cleanup, and the next blocking
condition for full live terminal acceptance.

Commit:

- app `f75f1ec`

Result:

- temporary `/tmp/ccb-mobile-cloudflared/cloudflared` reported version
  `2026.6.0`;
- `cloudflared tunnel --url http://127.0.0.1:<port>` created
  `https://clip-well-national-construct.trycloudflare.com`;
- `ccb mobile serve` started on loopback `127.0.0.1:39863` with
  `route_provider: cloudflare_tunnel` and pairing metadata pointing at the
  quick-tunnel URL;
- public DNS servers `1.1.1.1` and `8.8.8.8` returned Cloudflare A records
  for the quick-tunnel hostname;
- the system resolver used by Python/Dart/curl returned NXDOMAIN for the same
  hostname through `127.0.0.53`, so public `/v1/health` never became reachable
  from the app process;
- cleanup stopped cloudflared, terminated the gateway process, and `ccb kill
  -f` returned `kill_status: ok`.

Harness change:

- `tools/mobile_gateway_terminal_smoke.py` now waits for public `/v1/health`
  before Dart pairing when a public gateway URL is used;
- failure JSON includes sanitized cloudflared and gateway summaries so DNS,
  edge, origin, or app failures can be separated.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py`: passed
- loopback `tools/mobile_gateway_terminal_smoke.py`: returned `status: ok`,
  `route_diagnostics_ready: true`, `target_has_direct_tmux_evidence: false`,
  `output_bytes_seen: 5378`, and `reconnect_completed: true`
- app/source `git diff --check`

Plan impact:

- replaces the previous `cloudflared`-missing blocker with a resolver-specific
  blocker for this host;
- this checkpoint was superseded by the later accepted quick-tunnel smoke with
  a process-local public DNS override.

### 2026-06-18: Cloudflare Quick-Tunnel Live Smoke Acceptance

Scope: validate the public Cloudflare Tunnel route end to end while keeping
`ccb mobile serve` loopback-bound and preserving the route-agnostic
GatewayTransport contract.

Commit:

- app `a8eeec0`

Result:

- temporary `/tmp/ccb-mobile-cloudflared/cloudflared` reported version
  `2026.6.0`;
- `cloudflared tunnel --url http://127.0.0.1:58999` created
  `https://dir-peter-measuring-wholesale.trycloudflare.com`;
- `ccb mobile serve` kept its local listener on `127.0.0.1:58999` while
  pairing metadata used `route_provider: cloudflare_tunnel`;
- the smoke harness used `dig @1.1.1.1` to select public DNS address
  `104.16.231.132` for the generated hostname without changing system DNS;
- public `/v1/health` returned HTTP `200`, status `ok`, after 12 attempts;
- Dart terminal smoke returned `status: ok`,
  `route_diagnostics_ready: true`,
  `target_has_direct_tmux_evidence: false`, `output_bytes_seen: 7646`,
  `input_sent: true`, `paste_sent: true`, `resize_sent: true`,
  `close_completed: true`, `close_timed_out: false`, and
  `reconnect_completed: true`;
- cleanup stopped cloudflared, terminated the gateway process, and `ccb kill
  -f` returned `kill_status: ok`.

Verification:

- `python -m py_compile tools/mobile_gateway_terminal_smoke.py`: passed
- app `dart format --set-exit-if-changed
  lib/transport/http_gateway_transport.dart tool/gateway_terminal_smoke.dart`:
  passed
- app focused `flutter test test/http_gateway_transport_test.dart
  test/gateway_terminal_transport_test.dart test/gateway_pairing_test.dart`:
  16 tests passed
- app `tools/mobile_gateway_terminal_smoke.py`: loopback regression returned
  `status: ok` and `reconnect_completed: true`
- app `tools/mobile_gateway_terminal_smoke.py --cloudflared-quick-tunnel
  --cloudflared-bin /tmp/ccb-mobile-cloudflared/cloudflared
  --cloudflared-timeout 60 --public-ready-timeout 90 --gateway-timeout 30
  --dart-timeout 120`: returned `status: ok`
- app `flutter test`: 52 tests passed
- app/source `git diff --check`

Plan impact:

- closes the live quick-tunnel acceptance blocker for the current alpha smoke;
- keeps broad public/non-loopback gateway exposure blocked until named-tunnel
  setup, audit/revocation behavior, token expiry, and cellular or named-tunnel
  validation are reviewed.

### 2026-06-18: Cloudflare Alpha Host-Side Device Revocation

Scope: close the public-route lost-device revocation gap without exposing a
public HTTP admin route through Cloudflare Tunnel.

Commit:

- source `8a264cae`

Result:

- `ccb mobile devices` lists paired mobile devices from the current project's
  local `.ccb/ccbd/mobile/devices.json`;
- `ccb mobile revoke <device_id>` revokes a paired device locally on the
  server and writes audit metadata;
- device revocation cascades to still-open terminal handles for that device;
- terminal token authentication also checks whether the owning device is
  revoked;
- WebSocket cleanup now records terminal close/disconnect state before closing
  the PTY session, so stored terminal state is observable when the session is
  closed;
- the public HTTP gateway surface is unchanged: no admin list/revoke endpoint
  was added.

Verification:

- source `python -m py_compile lib/mobile_gateway/pairing.py
  lib/mobile_gateway/service.py lib/cli/models_start.py
  lib/cli/parser_runtime/commands.py lib/cli/services/mobile.py
  lib/cli/phase2_services.py lib/cli/phase2.py
  lib/cli/phase2_runtime/handlers_ops.py
  lib/cli/render_runtime/ops_views_basic.py lib/cli/router.py`: passed
- source `pytest -q test/test_mobile_gateway_service.py
  test/test_v2_cli_parser.py test/test_v2_cli_render.py
  test/test_v2_phase2_entrypoint.py`: 162 passed
- mobile `tools/mobile_gateway_terminal_smoke.py`: returned `status: ok`,
  `route_provider: lan`, `route_diagnostics_ready: true`,
  `target_has_direct_tmux_evidence: false`, `output_bytes_seen: 5378`,
  and `reconnect_completed: true` against source `8a264cae`
- source/mobile `git diff --check`

Plan impact:

- closes the Cloudflare alpha host-side revoke/token invalidation gap;
- moves the active public-route gate to named-tunnel or cellular validation
  plus user-facing setup docs.
