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
labs. The default loopback upstream is `127.0.0.1:18444`; that port was checked
free on the development host on 2026-07-22 before writing the nginx template.

Required local files:

- admission DB: `/var/lib/ccb-mobile-relay/relay-admission.sqlite3`, mode 0600;
- state directory: `/var/lib/ccb-mobile-relay`, mode 0700;
- admission secret file: mode 0600, deployment-owned, never committed;
- TLS key: mode 0600, deployment-owned, never committed.

## Package D Interface

Public WSS endpoints:

- `GET /v2/host`: outbound host connector socket.
- `GET /v2/phone`: phone rendezvous socket scoped to one admitted host.
- `GET /healthz`, `GET /readyz`, `GET /metrics`: payload-free operations
  telemetry only.

The service accepts only fixed protocol-v2 CCB JSON frames:

- `host_register`: first host frame. Carries `host_id`, PoP nonce, PoP expiry,
  Ed25519 signature, supported versions, and `relay.forward` capability. The
  relay verifies the Package B admitted host binding and proof before
  registering the host.
- `client_hello`: first phone frame. Carries relay `session_id`, `host_id`,
  `device_id`, client public key, and supported versions. It reserves one
  Package B host session.
- `host_hello`: host response for the same session. Version and host/session
  identity must match.
- `gateway_envelope`: opaque Package A v2 encrypted envelope only. The relay
  validates clear routing metadata, direction, frame size, and monotonic
  visible sequence. It never decrypts the ciphertext.
- `heartbeat`, `ack`, `close`, and `error`: control frames only.

The relay has no arbitrary URL, destination, CONNECT, TCP, or HTTP proxy API.
If either side is disconnected, the session is closed; there is no offline
queue. Queue pressure, write timeout, quota exhaustion, stale metadata, or
revocation fails closed and releases any host-session reservation.

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
