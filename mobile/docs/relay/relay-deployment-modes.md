# CCB Mobile Relay Deployment Modes

CCB Mobile supports two Relay deployment modes. Both keep the desktop mobile
gateway loopback-only. The Relay transports encrypted envelopes and must not
receive task prompts, replies, terminal output, or files in plaintext.

## CCB Official Relay

The official endpoint is `wss://47.120.71.142`. Obtain a one-time invitation
from the CCB Relay operator, save it as an owner-only file, then activate:

```sh
ccb relay host activate --mode official --invitation-file /path/to/ccb-relay.key
ccb update mobile --route-provider relay
```

The invitation is consumed by activation and is never encoded into the phone
QR. The QR contains the official endpoint, host fingerprint, and a single-use
pairing bootstrap. Clients reject an arbitrary endpoint labelled `official`.

## Self-Hosted Relay

Operate a Relay with a stable public `wss://` URL, Android-trusted TLS, an
HTTPS/WebSocket reverse proxy on port 443, owner-only state, and bounded
admission, connection, frame, and stream limits.

```sh
ccb relay host activate --mode self-hosted \
  --relay-origin wss://relay.example.com \
  --invitation-file /path/to/ccb-relay.key
ccb update mobile --route-provider relay
```

The self-hosted service issues its own one-time invitation. Do not expose an
unauthenticated generic proxy, public relay administration API, or reusable
pairing secret. Relay metadata can still reveal endpoint, timing, byte counts,
and connection lifetime; it does not reveal plaintext task data.

This separation follows deployment ergonomics found in relay products such as
Paseo, but CCB uses its own protocol and implementation.
