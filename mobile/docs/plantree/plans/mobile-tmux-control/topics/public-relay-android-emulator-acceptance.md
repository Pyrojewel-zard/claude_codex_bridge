# Public Relay Android Emulator Acceptance

Date: 2026-07-22
Status: In progress; local prerequisites pass, required public-route run not started

## Purpose

Define the strict end-to-end acceptance gate for the hosted CCB Relay,
one-time applicant invitations, end-to-end encryption, route recovery, and
unchanged CCB Mobile behavior. Local unit tests and the in-memory relay harness
are prerequisites, not substitutes for this public-route run.

Architecture and deployment authority:
[public-relay-invitation-and-aliyun-deployment.md](public-relay-invitation-and-aliyun-deployment.md).

## Acceptance Environment

- authoritative checkout: `/home/bfly/yunwei/ccb_source`;
- Android Emulator: `emulator-5554` or a recorded replacement;
- APK built from the exact tested source commit, with version and SHA-256
  recorded before installation;
- public staging relay on Alibaba Cloud, reached through normal Emulator
  Internet access over `wss://`; `adb reverse` is prohibited for relay-route
  acceptance;
- CCB host gateway remains loopback-only and reaches the relay through an
  outbound connector;
- server-wide project registry must list real mounted projects;
- all prompts, file operations, terminal input, and lifecycle tests target a
  disposable project under `/home/bfly/yunwei/test_ccb2`;
- fake/demo projects, active user projects, controlled transcript injection,
  and screenshots from a different APK/deployment are rejection conditions.

## Evidence Packet

Every run must preserve one directory containing:

- source commit, dirty-state summary, APK path/version/SHA-256, package info,
  Emulator id/API, relay build id, relay DNS/certificate summary, gateway
  identity, route provider, host id, and disposable project root;
- redacted invitation issue/claim results and an invitation-state query proving
  `consumed` without revealing the invitation;
- redacted host credential and device/route diagnostics;
- timestamped relay, connector, gateway, and logcat logs with an automated
  prohibited-plaintext scan;
- screenshots for project list, Working bubble, live/final reply, running
  project highlight, unread star, terminal mode, attachment, route failure,
  and recovery;
- a screen recording for Working animation and reconnect continuity;
- machine-readable latency, frame/byte, memory, CPU, connection, reconnect,
  and error summaries;
- relay database schema/redacted rows and filesystem scan proving that no CCB
  payload or attachment spool was persisted.

Screenshots alone never close a protocol, encryption, invitation, replay, or
no-storage gate.

## Gate 0: Build And Deployment Identity

1. Run focused source, relay, Flutter transport, pairing, and integration tests.
2. Run `flutter analyze`, full Flutter tests, debug APK build, Python compile,
   and scoped `git diff --check`.
3. Install the exact newly built APK with `adb install -r` and confirm package
   version/hash; do not rely on an already-installed build.
4. Verify DNS, valid TLS hostname/chain, WSS upgrade, public 443, relay health,
   and that the relay process itself is not publicly exposing its admin port.
5. Verify the CCB gateway listens only on loopback and the host connector is an
   outbound relay connection.

P0 pass: all identities agree and no fake/demo or `adb reverse` route is in the
relay evidence.

## Gate 1: One-Time Invitation Lifecycle

1. Issue one 24-hour invitation and verify only its verifier/redacted id is
   persisted.
2. Activate a fresh host key and confirm one credential is issued and the
   invitation becomes `consumed`.
3. Reuse the same invitation from a clean second host and require a generic
   already-used rejection with no credential.
4. Submit 10 concurrent claims for another invitation and require exactly one
   success and nine conflicts/rejections.
5. Verify expired, revoked, malformed, and unknown invitations fail without
   credential creation.
6. Revoke the activated host and prove new and existing relay sessions fail
   closed while local CCB projects continue running.

P0 pass: one invitation can create at most one host credential under normal,
concurrent, retry, restart, and response-loss simulations.

## Gate 2: Pairing And Route Identity

1. Generate the normal CCB host pairing QR with `route_provider: relay`.
2. Scan it in the Emulator and establish the relay session without exposing
   the relay invitation to the phone.
3. Verify the stored profile keeps relay origin, host fingerprint,
   capabilities, scopes, and device credential.
4. Verify a host-fingerprint mismatch, wrong relay origin, unsafe WSS URL, or
   revoked CCB device credential fails closed.
5. Pair a second clean app profile through the reusable CCB pairing handoff and
   confirm it does not require or reuse the consumed relay invitation.

P0 pass: relay admission and CCB mobile pairing remain separate, and CCB host
device authorization remains authoritative.

## Gate 3: End-To-End Confidentiality And Replay Safety

1. Send unique canary strings in project id fixture labels, prompt, reply,
   terminal input, attachment name/content, and notification source data.
2. Search relay logs, metrics, database, process arguments, crash output, and
   filesystem for every canary; all searches must be empty outside encrypted
   test artifacts retained by the test operator.
3. Capture relay-facing frames and prove only allowed routing metadata,
   ciphertext, nonce/sequence, lengths, and protocol version are visible.
4. Replay a previously accepted encrypted input frame and require rejection
   with no duplicate pane input.
5. Reverse direction, alter sequence/session/authenticated metadata, corrupt
   ciphertext, exceed the frame limit, and negotiate an unsupported/downgraded
   version; all must fail closed.

P0 pass: relay cannot recover CCB content and malformed/replayed frames never
reach the loopback gateway or selected pane.

## Gate 4: Real Server-Wide Mobile Workflow

Against one disposable real project and at least two agents:

1. Load the server-wide project list and prove multiple real mounted projects
   are visible without fake/demo markers.
2. Open the disposable project and send a unique natural provider prompt.
3. Capture optimistic user bubble, `Working · elapsed` on the active reply or
   placeholder, bright border animation with neutral bubble interior, natural
   reply takeover, and settled final reply without leaving/re-entering.
4. Confirm follow-latest keeps new bubbles visible only while the user remains
   near latest; reading history must not snap back.
5. Verify project working border and completion unread star can coexist; opening
   the target agent clears only the matching unread marker.
6. Switch windows/agents and prove no project, timeline, status, or unread
   leakage.

P0 pass: the relay route preserves the accepted LAN product behavior and no
controlled transcript injection is used as proof.

## Gate 5: Terminal, Files, And Notifications

1. Open per-agent Terminal mode, observe real pane output, send text and
   shortcut actions through the compact `+` controls, resize/scroll, and return
   to Chat without losing state.
2. Upload one image and one document; each appears once in the user turn and
   reaches the intended agent.
3. Download a backend-generated artifact, verify integrity, and exercise the
   Download/Open chooser and external URL confirmation path.
4. Trigger a fresh task completion while the app is foreground but outside the
   target agent, then while the app is normally backgrounded. Verify OS
   notification, project/window/agent unread star, tap routing, dedupe, and
   clear-on-open.
5. Verify old retained completion events do not notify after install/restart.

P0 pass: terminal and file payloads remain encrypted at the relay, and current
app-lifetime notification semantics match the existing product decision.

## Gate 6: Failure And Recovery

Run each fault while recording whether any terminal input or lifecycle request
is duplicated:

- disable and restore Emulator network;
- restart the relay process;
- interrupt and reconnect the host outbound connector;
- restart the loopback mobile gateway while CCB projects remain alive;
- background/foreground and restart the app;
- revoke the CCB device credential while relay host admission remains valid;
- revoke the relay host credential while the local CCB device remains valid;
- rotate the CCB pairing handoff without changing relay admission.

P0 pass: project runtime survives route faults, reconnect converges without
replaying side effects, stale identity fails closed, and diagnostics identify
relay, host, gateway, or device failure distinctly.

## Gate 7: Capacity, Performance, And Soak

Run a synthetic relay load in addition to the real Emulator lane:

- 50 host connectors and 50 phone sessions kept alive concurrently;
- 10 active bidirectional small-frame streams while the rest heartbeat;
- bounded attachment transfer at the configured maximum size;
- repeated connect/disconnect and invalid-handshake pressure;
- at least 60 minutes soak, followed by a relay restart and recovery run.

Record p50/p95/p99 handshake, small-frame relay overhead, reconnect time,
resident memory, CPU, file descriptors, queue depth, bytes, rejected frames,
and per-host quota actions. Initial targets are:

- no crash, unbounded queue, descriptor leak, or monotonic memory growth;
- 100 concurrent WSS connections fit within the selected 2 vCPU/2-4 GiB ECS;
- reconnect p95 below 5 seconds after network/service recovery;
- small-frame relay-added p95 latency below 300 ms from the tested region;
- idle traffic is measured and bounded, with no conversation/history polling
  reintroduced by the app.

Latency targets are staging targets, not claims about every carrier. If the
Alibaba Cloud region cannot meet them, preserve the measurements and change
region/capacity rather than weakening the recorded gate silently.

## Gate 8: Operational And No-Storage Audit

1. Restart from a backup containing only admission/security metadata.
2. Rotate TLS and relay signing keys under a documented maintenance procedure.
3. Confirm invitation and host revocation still work after restart.
4. Confirm logs rotate, omit secrets/payloads, and respect the chosen retention.
5. Confirm disk growth is bounded and attachment/frame directories do not
   exist.
6. Stop the relay and prove local CCB projects and LAN access remain intact.

P0 pass: the operator can deploy, revoke, recover, and shut down the relay
without possessing or restoring CCB business content.

## Rejection Rules

Reject the run if any of the following occurs:

- invitation succeeds more than once or raw invitation/credential appears in
  logs;
- relay sees or persists any CCB business canary in plaintext;
- public relay acceptance uses `adb reverse`, fake/demo, a stale APK, an active
  user project, or transcript injection;
- route recovery duplicates pane input or lifecycle actions;
- screenshots do not match the recorded APK/source/deployment identity;
- only widget/unit tests are offered for a public-network behavior;
- one working feature is declared accepted while a required P0 gate was not
  executed or is environment-blocked.

## Completion Record

After a passing run, add one dated evidence checkpoint under `history/`, link
it from the mobile plan evidence index, and update the roadmap. Until then this
topic remains `Planning` and public Relay remains unaccepted.
