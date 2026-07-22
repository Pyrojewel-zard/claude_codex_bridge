# Public Relay Encrypted Stream Package

Date: 2026-07-22

Status: local protocol and transport checkpoint; not public Relay acceptance

## Scope

- Added a versioned inner protocol carried only inside protocol-v2 AEAD
  `gateway_envelope` frames. The public relay remains opaque to request,
  Terminal, and notification semantics.
- Added strict request and stream identities, unary/stream operation
  allowlists, bounded message/window sizes, explicit receive credit,
  cancellation, slow-consumer deadlines, and session cleanup.
- Added concurrent unary request demultiplexing by `request_id` with a
  serialized AEAD send sequence.
- Bridged the selected gateway Terminal WebSocket without replaying input and
  bridged one notification SSE subscription with multiline parsing,
  `Last-Event-ID`, bounded read-only reconnect, and cancellation.
- Added the matching Dart inner schema and wired the socket transport's
  Terminal and notification streams to it.

## Verification

Passed locally:

```text
Python relay protocol/connector/service/crypto/admission: 49 passed
Dart relay protocol/socket transport: 10 passed
Full Flutter suite: 678 passed
Flutter analyze: no issues
Flutter debug APK build: passed
Python py_compile and git diff --check: passed
Package C TLS/WSS load smoke: 50 hosts, 50 phones, 10 active streams
```

The Python suite uses real TLS/WSS Package C sockets, an outbound host
connector, a reference phone, and loopback HTTP/WebSocket/SSE fixtures. It
proves concurrent response demultiplexing, Terminal output credit, single
delivery of input and resize frames, SSE resume without duplicate event ids,
host revocation rejection, and no plaintext Terminal canary in relay state.
The load smoke completed in `1129.41 ms`, reported zero rejected frames, zero
slow-consumer disconnects, `payload_bytes_persisted: 0`, and no canary scan
hits. The debug APK SHA-256 was
`be3eb17a199ed69ecdf1d35043bcbb3e259271118815cce5b24833ab733430c9`.

## Explicit Gaps

- File upload/download still require bounded chunk streams before Package D is
  complete; the pre-existing unary base64 surface is not accepted for large
  files.
- The production host activation/configuration lifecycle and reusable
  phone-session bootstrap are not yet wired into `ccb update mobile`.
- Full Flutter tests/build, local production-relay Android Emulator evidence,
  and public Alibaba WSS acceptance remain separate gates.
- No Alibaba Cloud, DNS, nginx, RustDesk, ZeroTier, or existing service state
  was changed.
