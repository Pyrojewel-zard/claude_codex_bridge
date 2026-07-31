# Public Relay Encrypted Stream Package

Date: 2026-07-22

Status: local Packages A-D checkpoint; not public Relay acceptance

## Scope

- Added a versioned inner protocol carried only inside protocol-v2 AEAD
  `gateway_envelope` frames. The public relay remains opaque to request,
  Terminal, and notification semantics.
- Added strict request and stream identities, unary/stream operation
  allowlists, bounded message/window sizes, explicit receive credit,
  cancellation, slow-consumer deadlines, and session cleanup.
- Request and stream identities are single-use for the lifetime of an
  encrypted session and have a bounded identity budget. Reuse is rejected
  before a second gateway mutation or stream can start.
- Added concurrent unary request demultiplexing by `request_id` with a
  serialized AEAD send sequence.
- Bridged the selected gateway Terminal WebSocket without replaying input and
  bridged one notification SSE subscription with multiline parsing,
  `Last-Event-ID`, bounded read-only reconnect, duplicate-event suppression,
  retry-only field handling, and cancellation.
- Added the matching Dart inner schema and wired the socket transport's
  Terminal and notification streams to it.
- Relay device credentials are translated only into the loopback
  `Authorization` header and are removed from gateway mutation bodies.
- Added one-time public host activation and owner-only host credential storage.
  `ccb update mobile` can now start the managed outbound connector and emit a
  Relay pairing QR without exposing the operator invitation to the phone.
- The QR bootstrap is short-lived and single-use. Successful CCB pairing
  replaces it with a host-signed durable access grant bound to a phone Ed25519
  key; every reconnect uses a fresh session id, X25519 key, nonce, and signed
  session proof. Bootstrap material and the pairing code are not retained in
  the saved phone profile.
- Added 32 KiB encrypted upload/download chunks. Uploads are capped at 25 MiB,
  downloads at 128 MiB, and one phone session may hold at most one buffered
  upload and one download at a time.
- Repository, Terminal, and notification clients now share one Relay socket
  per paired host/device. Canceling notification or Terminal streams does not
  close unrelated traffic.
- Added transient host-socket reconnect, terminal authentication rejection for
  revoked hosts, replay rejection across restart, and quota-safe ordering so a
  capacity rejection does not consume a one-time phone bootstrap.

## Verification

Passed locally on the current checkpoint (final rerun 2026-07-23):

```text
Python Relay/host/mobile-update focused suite: 108 passed
Full Python suite with CCB provider env injection removed: 5671 passed, 2 skipped
Dart Relay protocol/socket/pairing/notification focused suite: 50 passed
Full Flutter suite: 685 passed
Flutter analyze: no issues
Flutter debug APK build: passed
Python py_compile and git diff --check: passed
Package C TLS/WSS load smoke: 50 hosts, 50 phones, 10 active streams
Configured maximum file smoke: 25 MiB upload plus byte-identical download
```

The Python suite uses real TLS/WSS Package C sockets, an outbound host
connector, a reference phone, and loopback HTTP/WebSocket/SSE fixtures. It
proves concurrent response demultiplexing, Terminal output credit, single
delivery of input and resize frames, SSE resume without duplicate event ids,
host revocation rejection, and no plaintext Terminal canary in relay state.
The load smoke completed in `1109.57 ms`, reported zero rejected frames, zero
slow-consumer disconnects, `payload_bytes_persisted: 0`, and no canary scan
hits. The debug APK SHA-256 was
`1a954db32b9bac51536c069cc4a67ece3763f22561181c59e035ee2ac9c956e0`;
its manifest identity is `8.3.0+8030000`.

## Explicit Gaps

- A same-build Android Emulator run over a real public `wss://` route remains
  required. Local TLS/WSS Python and Dart harnesses are prerequisites only and
  do not count as public acceptance.
- Relay restart, host connector interruption, app background/restart,
  Terminal, notifications, and natural provider reply must still be exercised
  together through the Alibaba endpoint without `adb reverse`.
- The required 60-minute public soak and deployment no-payload filesystem/log
  audit have not run.
- No Alibaba Cloud, DNS, nginx, RustDesk, ZeroTier, or existing service state
  was changed.
