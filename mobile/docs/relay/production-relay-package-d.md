# Production Relay Package D

Status: local implementation package. This adds a real host connector and a
Flutter socket-backed relay transport. It does not claim public Alibaba Cloud
acceptance or Android public-route acceptance.

## Host Connector

The host connector is an outbound-only client for `GET /v2/host`.

Required boundaries:

- `relay_origin` must be an origin-only `wss://` URL. Path, query, fragment,
  embedded credentials, and plaintext `ws://` are rejected.
- `gateway_origin` must be an origin-only loopback `http://` or `https://`
  URL. Non-loopback hosts are rejected. The server-wide mobile gateway remains
  bound to `127.0.0.1`.
- The host Ed25519 signing key is the Package B admitted host credential key.
  It is used only for PoP registration and host-signed phone rendezvous tokens.
- The host X25519 key is the relay E2EE static key. Its `sha256:` fingerprint
  is the value paired phones confirm before deriving the v2 session keys.
- TLS verification uses the platform verifier by default. Local self-signed
  testing must pass an explicit test trust context and must not be reported as
  public WSS acceptance.

The connector registers with a fresh nonce and bounded proof expiry, reads
Package C `client_hello` frames, returns `host_hello`, derives the accepted v2
`RelayCryptoSession`, decrypts `gateway_envelope` requests, and proxies only
fixed CCB mobile operations to the configured loopback gateway.

## Operation Allowlist

Allowed request operations are explicit and map to fixed gateway routes:

- `health`, `device`, `list_projects`, `get_project_view`;
- `focus_agent`, `focus_window`, `terminal_history`, `agent_conversation`;
- `submit_agent_message`, `lifecycle`, `open_terminal`;
- `upload_file`, `download_file`, `notification_events`.

There is no raw URL, method override, CONNECT, TCP forwarding, alternate port,
or arbitrary path operation. Device tokens, project IDs, terminal handles,
file bodies, and message text exist only inside the v2 encrypted envelope.

Unsupported operations return an encrypted low-sensitive error payload and do
not touch the loopback gateway.

## Flutter Transport

`RelaySocketGatewayTransport` is selected only for relay profiles. LAN,
Tailnet, and Cloudflare profiles continue to use `HttpGatewayTransport`.

Relay profiles must include:

- `websocket_url`: relay WSS origin;
- `server_fingerprint`: expected host X25519 fingerprint;
- `relay_session_id`, `relay_client_private_key_b64`,
  `relay_phone_nonce_b64`, and `relay_rendezvous_capability`.

The transport opens `/v2/phone`, sends `client_hello`, verifies the host
fingerprint from `host_hello`, derives the v2 `RelayCryptoSession`, and
serializes gateway operations over encrypted `gateway_envelope` frames. It
fails closed on relay error, disconnect, downgrade, or fingerprint mismatch
and does not replay mutations automatically.

## Diagnostics

Host connector diagnostics are owner-only state and intentionally exclude
credentials, pairing codes, device tokens, request bodies, paths from rejected
raw requests, and decrypted payloads. Current fields include connector state,
host ID, relay/gateway origins, host fingerprint, opened session count,
proxied/rejected request counts, and low-sensitive last error code/class.

## Remaining Acceptance

Local socket tests may use loopback WSS with an explicit trust context or
loopback `ws://` in Flutter unit tests. That is implementation evidence only.
Public acceptance still requires the Package E Alibaba deployment profile,
public DNS/TLS, Android emulator install, no `adb reverse`, and the full
public-route evidence packet from
`mobile/docs/plantree/plans/mobile-tmux-control/topics/public-relay-android-emulator-acceptance.md`.
