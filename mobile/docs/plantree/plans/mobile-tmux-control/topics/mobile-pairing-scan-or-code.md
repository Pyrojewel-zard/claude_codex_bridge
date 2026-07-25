# Mobile Pairing: Scan Or Connection Code

Date: 2026-07-26
Status: Implemented and validated

## Goal

Reduce the unpaired phone experience to two actions:

1. scan the QR produced by `ccb update mobile`; or
2. paste the connection code printed beside that QR.

The phone must not ask the user to choose LAN, Tailscale, Cloudflare, official
Relay, or self-hosted Relay. It must not ask for an IP address, gateway URL,
Relay origin, route provider, or device name. Those decisions belong to the
computer-side `ccb update mobile` flow.

## Product Contract

The first screen presents:

- one primary `Scan computer QR` action;
- one collapsed `Enter connection code` section;
- one connection-code field and one `Connect` command inside that section.

The computer-side instruction is always:

```sh
ccb update mobile
```

The command's route menu determines transport. After the route and gateway are
ready, the command prints both a QR and a connection code containing the same
pairing payload.

The phone derives all connection configuration from the scanned or pasted
payload. It assigns the existing default device name automatically.

## Connection Code V1

The textual format is:

```text
ccb1_<base64url-without-padding>
```

The decoded bytes are UTF-8 JSON with the same schema as the existing pairing
QR:

- `pairing_code`;
- `claim_endpoint`;
- `route_provider`;
- `gateway_url`;
- `scopes`;
- optional project, host, expiry, WebSocket, Relay mode, fingerprint, and
  Relay phone-bootstrap fields.

Properties:

- Base64URL is used so the complete value remains one copyable token.
- Padding is omitted when printed and restored by the decoder.
- Encoded input is bounded before decoding.
- Decoded JSON is bounded and must parse as a pairing object.
- Raw JSON remains accepted as an import compatibility path, but the computer
  prints `ccb1_` codes for ordinary use.
- The QR remains JSON in this package so existing released apps can continue
  scanning new computer output.

The connection code is not an identity credential or a reusable account key.
It is pairing material. For Relay it contains the single-use phone bootstrap;
for every route it contains the pairing code. It must not enter logs,
analytics, screenshots, crash reports, source files, or shell history.

## Shared Claim Path

Both inputs produce a complete `GatewayPairingPayload` and call the same claim
coordinator:

```text
QR scanner ─┐
            ├─> GatewayPairingPayload ─> claim/store ─> activate profile
code field ─┘
```

No route-specific claim logic may be implemented in the onboarding widgets.

On success:

- clear the connection-code field;
- store the claimed profile in secure storage;
- enter the real server-wide project list.

On failure:

- keep the pasted code so the user can retry transient errors;
- do not partially store or activate a profile;
- show a concise error without echoing the code.

## UI Removal Boundary

Remove from unpaired and re-pair setup:

- gateway URL/IP field;
- pairing PIN field;
- device-name field;
- route dropdown;
- route examples and `Use example address`;
- official/self-hosted Relay selector;
- phone-side Relay activation commands.

Route diagnostics remain available after pairing. They are status information,
not setup choices.

The scanner's fallback button becomes `Enter code`, returning to the same
connection-code section instead of a legacy manual-IP form.

## Computer Output

`ccb update mobile` continues to print the complete QR, then prints:

```text
If scanning is unavailable, paste this connection code in CCB Mobile:
ccb1_...
```

It must not print a separate gateway URL and pairing PIN. The connection code
is generated from the exact canonical payload used for the QR.

## Compatibility

- New App + new CLI: scan or paste `ccb1_` code.
- New App + old CLI: QR works; raw QR JSON can also be pasted when available.
- Old App + new CLI: QR remains compatible.
- Existing paired profiles are unaffected.
- Runtime activation and stored profile route metadata remain unchanged.

## Automated Acceptance

1. Python encoder round-trips the canonical QR JSON without padding.
2. Dart decoder accepts `ccb1_` and legacy raw JSON.
3. Oversized, malformed Base64URL, non-UTF-8, and non-object JSON are rejected.
4. A pasted LAN code derives LAN URL and route without visible route inputs.
5. A pasted Relay code preserves every crypto/bootstrap field.
6. Scan and paste use the same claim/store coordinator.
7. Failed claim retains the code and does not activate a repository.
8. Successful claim clears the code.
9. Widget tests assert that URL, route, pairing-PIN, and device-name controls
   are absent.
10. Existing stored-profile, notification, conversation, and terminal tests
    remain green.

## Real Emulator Matrix

Use the same APK hash and server-wide source worktree for every row:

| Route | Input | Required proof |
| --- | --- | --- |
| LAN | QR | project list, conversation, terminal, diagnostics |
| LAN | connection code | same proof, no manual IP UI |
| official Relay | QR | project list, terminal, `relay/official`, no adb reverse |
| official Relay | connection code | same proof and force-stop reconnect |

Additional UI evidence:

- the clean first screen contains only scan/code pairing choices;
- expanding code input does not expose URL, route, Relay mode, or device name;
- malformed code shows an error without printing the submitted value.

All screenshots, UI dumps, connection codes, QR payloads, logcat output, APK
hashes, and server checks belong under an owner-only external temporary root.
No runtime evidence or pairing material may be written into the source tree.

## Completion Gate

This package is complete only when:

- PlanTree, CLI output, and App UI agree;
- relevant Python and Flutter tests pass;
- the APK builds and installs;
- all four emulator matrix rows pass against real mounted projects;
- Relay validation has no `adb reverse`;
- source and staged-diff secret scans pass;
- `git diff --check` passes.

## Validation Record

The 2026-07-26 acceptance pass used one debug APK for the complete matrix:

- version: `8.3.1+8030001`;
- SHA256:
  `acd8c0d8de80f37ed83c3f72207e52a290e651247a4dfc5446ece9dca1d942be`;
- emulator: `emulator-5554`;
- project source: real server-wide mounted projects, not demo mode.

Results:

- LAN connection code: paired and loaded the real project list.
- LAN QR from image: decoded, claimed, and loaded the real project list.
- LAN route: diagnostics reported `lan`; conversation and Terminal opened.
- official Relay connection code: paired without `adb reverse`, loaded projects,
  and recovered the same profile after force-stop/relaunch.
- official Relay QR from image: decoded, claimed, and loaded projects without
  `adb reverse`.
- official Relay route: diagnostics reported `relay/official`; conversation and
  Terminal opened.
- the emulator was left paired to the official Relay after testing.
- the shared server still had the CCB Relay and RustDesk `hbbs`/`hbbr`
  processes/listeners active after validation.

Automated gates:

- Python mobile CLI/gateway suite: 176 passed.
- full Flutter suite: 708 passed, 1 intentionally skipped.
- APK build and overwrite install: passed.
- Dart analysis found no source issues, but the shared host exhausted its
  inotify instance quota during analysis-server shutdown; full Flutter tests
  and the APK build remained clean compilation gates.
- `git diff --check`: passed.

Pairing payloads, connection codes, screenshots, UI dumps, service output, and
server checks were retained only in the owner-only external test root. None are
part of this repository.
