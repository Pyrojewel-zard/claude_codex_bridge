# Production Relay Package C

Status: local implementation package. This does not claim Flutter transport,
host connector, public Alibaba Cloud, or Android public-route acceptance.

## Service

Run the relay as an independent Python service:

```bash
PYTHONPATH=/opt/ccb-source/lib python3 -m mobile_gateway.relay_service
```

Production listeners require TLS. Plaintext is rejected unless
`--unsafe-plaintext-for-tests` is used on a loopback bind for explicit local
labs. The default loopback public WSS upstream is `127.0.0.1:18444`; the
separate admin listener is `127.0.0.1:18445`. Both ports were checked free on
the development host on 2026-07-22 before writing the nginx template.

Required local files:

- admission DB: `/var/lib/ccb-mobile-relay/relay-admission.sqlite3`, mode 0600;
- state directory: `/var/lib/ccb-mobile-relay`, mode 0700;
- admission secret file: mode 0600, deployment-owned, never committed;
- TLS key: mode 0600, deployment-owned, never committed.

## Package D Interface

Public WSS endpoints:

- `GET /v2/host`: outbound host connector socket.
- `GET /v2/phone`: phone rendezvous socket scoped to one admitted host.

Loopback-only admin endpoints:

- `GET /healthz`, `GET /readyz`, `GET /metrics`: payload-free operations
  telemetry only. These are served only by the separate admin listener and must
  not be proxied by the public vhost.

The service accepts only fixed protocol-v2 CCB JSON frames:

- `host_register`: first host frame. Carries `host_id`, PoP nonce, PoP expiry,
  Ed25519 signature, supported versions, and `relay.forward` capability. The
  relay verifies the Package B admitted host binding and proof before
  registering the host.
- `client_hello`: first phone frame. Carries relay `session_id`, `host_id`,
  `device_id`, client public key, fresh `phone_nonce_b64`, supported versions,
  and `rendezvous_capability`. The relay verifies this before reserving quota
  or forwarding anything to the host.
- `host_hello`: host response for the same session. Version and host/session
  identity must match.
- `gateway_envelope`: opaque Package A v2 encrypted envelope only. The relay
  validates clear routing metadata, direction, frame size, and monotonic
  visible sequence. It never decrypts the ciphertext.
- `heartbeat`, `ack`, `close`, and `error`: control frames only.

## Rendezvous Capability

Package D must obtain a fresh host-signed token before opening `/v2/phone`.
This does not reuse the relay invitation and does not put any relay invitation
secret on the phone.

Host issuance API shape:

- token prefix: `ccb-relay-rv-v1`;
- signer: the admitted host Ed25519 key already bound by Package B;
- signed fields: `schema_version=2`, `host_id`, `session_id`,
  `client_pubkey_b64`, fresh `phone_nonce_b64`, relay `aud`/origin, `iat`,
  `exp`, and unique token `nonce_b64`.

Phone presentation API shape:

- `/v2/phone` first frame is `client_hello`;
- the frame `session_id`, `host_id`, `client_pubkey_b64`, and
  `phone_nonce_b64` must exactly match the signed token;
- `aud` must match the relay `public_origin`;
- expired, replayed, mismatched, unknown-host, or revoked-host tokens fail
  closed before Package B session quota reservation.

Decision 021 reusable mobile pairing remains compatible: a reusable QR or
pairing assertion can identify the host/application relationship, but each
relay connection still needs a fresh phone nonce/key and one short-lived
host-signed rendezvous token. Captured phone requests cannot be replayed.

The relay has no arbitrary URL, destination, CONNECT, TCP, or HTTP proxy API.
If either side is disconnected, the session is closed; there is no offline
queue. Queue pressure, write timeout, quota exhaustion, stale metadata, or
revocation fails closed and releases any host-session reservation.

When nginx is used, only configured trusted proxy peers may supply
`X-CCB-Client-IP` / `X-Forwarded-For`; the relay requires strict single-hop IP
headers and otherwise rate-limits by the direct TCP peer.

## Install Template

1. Create a dedicated `ccb-relay` user.
2. Install this source checkout at `/opt/ccb-source`.
3. Create `/var/lib/ccb-mobile-relay` with owner `ccb-relay:ccb-relay` and mode
   0700.
4. Create `/etc/ccb/mobile-relay.env` from
   `deploy/mobile-relay/ccb-mobile-relay.env.example`.
5. Create `/etc/ccb/mobile-relay-admission-secrets.json` with mode 0600.
6. Install `deploy/mobile-relay/ccb-mobile-relay.service`.
7. Optionally place `deploy/mobile-relay/nginx-relay.seemlab.top.conf` after
   reviewing existing nginx/RustDesk/ZeroTier configuration.

## Rollback

Stop accepting new invitations, drain the relay, revoke affected host
credentials, rotate relay/TLS keys if needed, and restore only anonymous
admission/security metadata. Do not restore or search for CCB payload stores;
the relay must not create any.
