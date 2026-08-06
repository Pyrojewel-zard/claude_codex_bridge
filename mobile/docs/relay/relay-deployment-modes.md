# CCB Mobile Relay Deployment Modes

CCB Mobile supports two Relay deployment modes. Both keep the desktop mobile
gateway loopback-only. The Relay transports encrypted envelopes and must not
receive task prompts, replies, terminal output, or files in plaintext.

## CCB Official Relay

The official endpoint is `wss://47.120.71.142`. Obtain a one-time invitation
from the CCB Relay operator by email at `bfly123@126.com` or through WeChat,
save it as an owner-only file, then activate:

```sh
ccb relay host activate --mode official --invitation-file /path/to/ccb-relay.key
ccb update mobile --route-provider relay
```

Relay pairing payloads are high-density QR codes. When the QR cannot be
rendered safely within the current terminal width, the CLI omits the wrapped
character preview and writes an owner-only PNG to
`~/.local/state/ccb/mobile/pairing-qr.png`. Open that image at normal size and
scan it with CCB Mobile. Set `CCB_MOBILE_PAIRING_QR_OUTPUT` to choose another
output path.

The invitation is consumed by activation and is never encoded into the phone
QR. The QR contains the official endpoint, host fingerprint, and a single-use
pairing bootstrap. Clients reject an arbitrary endpoint labelled `official`.

## Self-Hosted Relay

Operate a Relay with a stable public `wss://` URL, Android-trusted TLS, an
HTTPS/WebSocket reverse proxy on port 443, owner-only state, and bounded
admission, connection, frame, and stream limits.

Use the service, systemd, nginx, TLS, state-directory, and rollback checklist
in [Production Relay Package C](production-relay-package-c.md). The minimal
deployment sequence is:

1. install the CCB source and Relay Python dependencies on the server;
2. create a dedicated non-login service user and owner-only state/secrets;
3. bind the Relay service and admin listener to loopback;
4. expose only `/v2/host` and `/v2/phone` through an Android-trusted TLS
   reverse proxy on port 443;
5. keep health, readiness, metrics, and admission administration off the
   public virtual host;
6. issue a bounded, short-lived one-time invitation from the Relay operator
   account.

Example operator-side invitation issuance:

```sh
ccb relay invite issue \
  --db /var/lib/ccb-mobile-relay/relay-admission.sqlite3 \
  --secrets /etc/ccb/mobile-relay-admission-secrets.json \
  --ttl-seconds 900 \
  --json
```

Transfer the invitation to the approved computer as an owner-only file. Do
not place it in a phone QR, shell history, source checkout, shared log, or
public download.

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
