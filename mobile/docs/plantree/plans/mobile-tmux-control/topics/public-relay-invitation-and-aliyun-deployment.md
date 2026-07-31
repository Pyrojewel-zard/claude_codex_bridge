# Public Relay Invitation And Alibaba Cloud Deployment

Date: 2026-07-22
Status: In progress; local Packages A-D implemented, public deployment unaccepted

## Purpose

Turn the existing local `RouteProvider.relay` contract into a small hosted CCB
Relay for an initial population of tens of users. The service should remove the
phone-side Tailscale/VPN conflict while retaining the loopback-only CCB gateway,
outbound-only host connectivity, end-to-end encrypted CCB traffic, and strict
CCB device authorization.

This topic implements the direction in
[Decision 011](../decisions/011-relay-default-remote-route.md) and the admission
contract in
[Decision 023](../decisions/023-one-time-public-relay-admission.md). The local
protocol baseline remains
[relay-route-provider-spike.md](relay-route-provider-spike.md).

## Product Boundary

```text
Android app
  -> TLS/WSS
  -> hosted CCB Relay
  -> existing outbound CCB host connector
  -> loopback-only server-wide mobile gateway
  -> ccbd + real mounted CCB projects
```

The relay is a route provider, not a CCB runtime owner. It must not execute
tmux commands, discover projects, parse transcripts, mint CCB device scopes,
or control project lifecycle.

"CCB only" means a valid one-time-admitted host credential, a constrained CCB
relay envelope, CCB host pairing/device authorization, and enforced quotas. It
does not mean binary attestation and does not rely on an embedded shared secret.

## P0 Trust And Privacy Contract

- TLS 1.3 protects both public WSS legs and authenticates the relay endpoint.
- CCB payloads are encrypted above relay TLS between the phone and host. The
  implementation must use an audited cross-platform construction; custom
  cryptographic primitives are prohibited.
- The handshake authenticates the CCB host public key/fingerprint already
  carried by the pairing contract and derives per-session authenticated
  encryption keys.
- Every encrypted frame binds protocol version, relay session id, direction,
  and monotonically increasing sequence number as authenticated data.
- Duplicate, reordered beyond the accepted window, oversized, stale, or
  unknown-session frames fail closed.
- Relay operators can observe only the minimum routing envelope, byte counts,
  timing, connection state, and anonymous identifiers. Project ids, agent
  names, prompts, replies, paths, terminal tokens, file names, and file content
  must remain encrypted.
- No forwarded frame, attachment chunk, notification body, or conversation
  payload is written to disk, queues, crash reports, access logs, or metrics.
- P0 has no offline message queue. If either side is disconnected, frames are
  rejected rather than retained for later delivery.

The exact audited crypto library and interoperable handshake suite require a
dependency/source check before implementation. The expected primitive family
is X25519 key agreement, HKDF-SHA-256 key derivation, and an AEAD such as
ChaCha20-Poly1305, preferably through a reviewed Noise-compatible library. This
is a dependency gate, not permission to hand-roll the construction.

## Admission And Credential Lifecycle

### Operator Invitation

1. An operator issues a random invitation with at least 128 bits of entropy and
   a short validity period, default 24 hours.
2. The relay stores only a keyed verifier plus anonymous issuance metadata.
3. `ccb relay activate <invite>` generates a host key pair locally and submits
   the invitation, host public key, protocol version, and activation nonce.
4. One database transaction validates `unused`, creates the host credential,
   and marks the invitation `consumed`.
5. The returned credential is stored owner-only by CCB. Later connections use
   key proof and short-lived session capabilities.
6. Additional hosts require additional invitations.

Required operator surface:

- issue invitation with expiry and optional connection/bandwidth quota;
- inspect redacted invitation status without revealing the code;
- revoke an unused invitation;
- list and revoke anonymous host credentials;
- inspect aggregate relay health and quota counters without CCB payload data.

### Mobile Pairing

The relay invitation is not a mobile pairing code. Once a host is activated,
the existing CCB pairing QR identifies the relay route and CCB host. A phone may
rendezvous with that active host, but the host still performs the authoritative
CCB pairing claim and issues its existing scoped device credential. Decision
021's reusable pairing behavior remains unchanged.

## Minimal Persistent State

A single-instance P0 may use a transactional SQLite database in WAL mode. The
schema should contain only:

- invitation verifier, state, issued/expiry/consumed timestamps, and quota;
- random relay host id, host public key, credential status, created/revoked
  timestamps, and quota;
- signing-key version and schema migration version;
- bounded, payload-free security audit events.

Active socket maps, session keys, sequence windows, heartbeat state, and
backpressure queues remain memory-only and disappear on restart. TLS keys,
relay signing keys, and database backups are operational secrets and must be
owner-readable only. "No data storage" in product language must be stated as
"no CCB business payload storage," not as zero security metadata.

Package B admission key material is deployment-owned configuration, not
database state. Operators must provide it with `--secrets`, with
`CCB_RELAY_ADMISSION_SECRETS`, or with both
`CCB_RELAY_VERIFIER_KEY_B64` and `CCB_RELAY_CAPABILITY_KEY_B64`; the same key
material must be present after restart. The admission database stores only a
non-secret fingerprint of those keys and fails closed if the fingerprint is
missing on a populated database or changes across restart. The SQLite
database, WAL, and SHM files must be owner-only. Raw invitation values,
verifier keys, and capability keys must not appear in logs, audit rows, or
database files.

## Abuse And Resource Controls

- one invite activates one host; no universal invite or client-embedded key;
- per-host concurrent phone/session limit and aggregate bandwidth quota;
- per-IP unauthenticated handshake rate limit before host/device auth;
- fixed frame kinds, maximum envelope/frame/chunk size, bounded in-memory
  queues, write deadlines, and slow-consumer disconnect;
- heartbeat and idle session TTL; disconnected sessions release memory;
- no arbitrary destination, CONNECT method, port forwarding, URL fetch, or
  generic byte-stream API;
- load shedding returns an explicit retryable route error without replaying
  terminal input or lifecycle actions;
- administrative endpoints are not public app endpoints and require a local
  CLI, SSH-restricted socket, or separate operator credential.

Because an approved open-source client can be modified, quotas and revocation
remain necessary even after protocol validation.

## Implementation Packages

### Package A: Threat Model And Crypto Interop Gate

- freeze cleartext envelope fields and prohibited payload fields;
- select maintained Python/Dart crypto libraries after current-source review;
- create deterministic cross-language handshake and AEAD test vectors;
- prove key confirmation, direction separation, replay rejection, and key
  erasure on close;
- update protocol version negotiation and reject downgrade.

### Package B: Admission Store And Operator CLI

- add atomic one-time invitation consumption and host key binding;
- add issue/status/revoke commands with JSON output and redacted rendering;
- add short-lived session capability verification and host revocation;
- add concurrency, expiry, crash-boundary, migration, and log-redaction tests.

Current candidate evidence, 2026-07-22:
[history/public-relay-ab-package-20260722.md](../history/public-relay-ab-package-20260722.md).
This is a local Package A/B implementation checkpoint only: it freezes the v2
crypto/admission boundaries, adds shared Python/Dart vectors, transactional
SQLite/WAL one-time invitation storage, host PoP session capabilities, and
operator-local CLI rendering. It does not claim Package C/D relay service,
host connector, public WSS, Android public-route acceptance, or Alibaba Cloud
deployment.

### Package C: Production Relay Service

- replace the in-memory-only public boundary with an async TLS/WSS relay
  service while preserving `RelayFrame` semantics;
- implement host registration, phone rendezvous, opaque bidirectional
  forwarding, heartbeat, backpressure, quotas, and diagnostics;
- keep the relay deployable independently from the CCB host process;
- add systemd health/readiness, graceful drain, metrics, and backup/restore of
  security metadata only.

### Package D: Host Connector And Flutter Transport

- connect `ccb install/update mobile` host service outbound to the relay;
- preserve the loopback-only server-wide gateway and existing project model;
- make the Flutter relay transport complete the authenticated E2EE handshake,
  reconnect safely, and expose route diagnostics without screen-level route
  branches;
- preserve LAN, Tailnet, and Cloudflare profiles and allow route fallback only
  by explicit user choice.

### Package E: Alibaba Cloud Staging Deployment

- deploy one staging relay and run the full public-route acceptance plan;
- keep production DNS separate until invitation, revocation, no-payload, and
  recovery gates pass;
- record deployment configuration without private keys or invitation values.

### Package F: Limited Beta And Operations

- issue invitations manually to the first cohort;
- set conservative quotas and monitor connections, memory, bandwidth, errors,
  and abuse without inspecting content;
- document incident response, key rotation, database backup, host revocation,
  and complete service shutdown;
- expand capacity only from observed metrics.

## Current Implementation Checkpoint

Local Packages A-D are implemented on the dedicated Relay branch as of
2026-07-22. The checkpoint includes one-time host activation, persistent
payload-free admission metadata, host and phone proof-of-possession,
single-use QR bootstrap followed by a durable host-signed phone grant,
AEAD-protected unary and multiplexed stream traffic, Terminal and notification
streams, bounded file chunks, shared Flutter socket ownership, reconnect, and
managed outbound host-connector startup.

The current local evidence is recorded in
[public-relay-stream-package-20260722.md](../history/public-relay-stream-package-20260722.md).
This does not complete Package E: no public DNS/TLS endpoint, Alibaba Cloud
service, or no-`adb reverse` Android Emulator acceptance has passed yet.

## Execution Order And Review Ownership

1. Lead freezes the threat model, protocol version, evidence schema, and the
   distinction between relay admission and CCB mobile pairing.
2. Source/backend owner lands Packages A-C with a security-focused reviewer;
   invitation atomicity, replay protection, and plaintext leakage are blocking
   review findings.
3. Mobile app owner lands Package D and cross-reviews QR/profile/reconnect UX
   without changing route-agnostic project and chat screens.
4. Lead deploys Package E to staging only after local protocol tests pass, then
   owns the full same-build Emulator evidence packet.
5. Beta invitations remain manual until Package F capacity, revoke, incident,
   and no-payload audit gates are accepted.

No package may claim public-relay acceptance from the in-memory harness, widget
tests, screenshots alone, or a different APK/relay build.

## Alibaba Cloud Deployment Profile

Alibaba Cloud ECS is suitable for the first hosted relay. For tens of users,
start with:

- Linux ECS, 2 vCPU and 2 GiB RAM minimum; 2 vCPU and 4 GiB RAM preferred for
  operational headroom;
- 20-40 GiB system disk;
- public IPv4/EIP and measured outbound bandwidth; start around 5 Mbit/s when
  file transfer is enabled and adjust from real traffic;
- one DNS name such as `relay.seemlab.top`;
- TCP 443 public; TCP 80 only when required for certificate issuance/redirect;
- SSH restricted to the operator's source IP and key authentication, or use a
  managed session facility;
- Caddy or Nginx may terminate TLS and proxy WSS, while the relay process binds
  loopback; the deployment must preserve WebSocket timeouts and backpressure.

Alibaba Cloud documents that ECS public access requires public bandwidth/public
IP configuration and that security groups should expose only required service
ports. Its current security guidance recommends opening 80/443 for public web
services and restricting SSH to known administrator addresses:

- <https://www.alibabacloud.com/help/en/ecs/user-guide/ip-address/>
- <https://www.alibabacloud.com/help/en/ecs/user-guide/security-groups-for-different-use-cases>

Region choice is operationally significant:

- China mainland ECS gives better domestic routing but a domain resolving to a
  mainland server requires ICP filing even for API/relay or non-standard-port
  use. Alibaba Cloud's current filing guidance states this explicitly:
  <https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-application-overview>.
- Alibaba Cloud Hong Kong or an overseas region does not require mainland ICP
  filing according to that guidance and is the fastest staging choice, but
  mainland latency and cross-border stability must be measured before beta.

ICP filing is not the only possible operational or regulatory obligation. The
operator must separately confirm current App/public-network and public-security
registration requirements for the chosen deployment and user population; this
plan is an engineering boundary, not legal advice.

Recommended sequence: use Hong Kong for the first staging proof unless an
already-filed domain and mainland ECS are available; choose the production
region only after the public Emulator latency/soak evidence is recorded.

## Inputs Required From The Operator

Implementation and local tests can start without cloud credentials. Public
staging requires:

1. Alibaba Cloud ECS region, OS, public IP/EIP, and expected bandwidth.
2. A DNS name and ability to add/update its A/AAAA records.
3. ICP filing status when a China mainland region is selected.
4. SSH public-key access to a dedicated sudo-capable deployment account; do not
   send a root password or private key in chat.
5. Security-group permission for public 443 and administrator-restricted SSH;
   optionally 80 for certificate automation.
6. The intended invitation issuer/administrator and initial cohort size. No
   applicant name, phone, or email is required by the relay design.
7. Confirmation of security audit retention, defaulting to 30 days of
   payload-free events, and whether IP addresses should be truncated or kept
   only in short-lived abuse counters.
8. A stable Android test APK build/signing lane for physical beta; debug APK is
   sufficient for Emulator staging acceptance.

## Rollback

- stop accepting new invitations;
- revoke affected host credentials and rotate relay signing/TLS keys when
  required;
- drain and stop the relay without stopping any CCB project or local gateway;
- retain LAN, Tailnet, and Cloudflare route profiles as explicit alternatives;
- restore only the anonymous admission database and keys, never CCB payloads.

## Exit Criteria

The public relay is beta-ready only after every P0 gate in
[public-relay-android-emulator-acceptance.md](public-relay-android-emulator-acceptance.md)
passes against the same source commit, APK hash, relay deployment, and real
server-wide dedicated test project.

## Historical Deployment Preflight (2026-07-22)

The 2026-07-22 read-only preflight identified Alibaba Cloud target
`47.120.71.142`, confirmed the existing RustDesk-related public port surface,
and found that the historical local SSH key was no longer authorized. At that
checkpoint, source still contained only the non-networked local relay harness;
later implementation status is recorded above. No remote change was made
during the preflight. See
[the preflight record](../history/public-relay-aliyun-preflight-20260722.md).
