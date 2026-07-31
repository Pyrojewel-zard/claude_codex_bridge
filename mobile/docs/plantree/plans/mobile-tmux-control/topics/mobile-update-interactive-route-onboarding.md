# Interactive Mobile Route Onboarding

Date: 2026-07-25
Status: Implemented and validated

## Goal

Make the ordinary mobile setup entry point:

```sh
ccb update mobile
```

short, explicit, and safe. In an interactive terminal it must ask which route
the user wants instead of silently choosing Tailnet:

```text
Choose how this computer connects to CCB Mobile:
  1. Tailscale
  2. Local network (LAN)
  3. CCB official Relay
  4. Self-hosted Relay
Select [1-4]:
```

The route choice changes only transport setup. It must not change the mobile
gateway API, project ids, pairing scopes, terminal protocol, notification
contract, or device-token authority.

## Current Defects

The pre-change command has two coupled defects:

1. `ccb update mobile` has no route prompt and eventually defaults to
   `tailnet`.
2. `ccb update mobile --route-provider lan` enters the Tailnet onboarding
   function, so an explicit LAN request can still receive Tailscale guidance.

The Relay route has a working activation and credential contract, but ordinary
users must currently discover and run separate commands without guided
onboarding.

## UX Contract

### Interactive invocation

The four-item menu is shown only when all of these are true:

- target is `mobile`;
- `--route-provider` was not supplied;
- stdin and stdout are TTYs.

Input is trimmed and accepts only `1`, `2`, `3`, or `4`. Invalid input is
retried up to three times. EOF, an empty answer, or `Ctrl+C` cancels without
starting, replacing, or rotating the mobile gateway.

### Non-interactive invocation

Pipes, CI, cron, installers, and command wrappers must never block on a prompt.
For compatibility, a non-TTY bare invocation retains the existing Tailnet
default and prints a concise notice recommending an explicit flag:

```text
Non-interactive mobile setup defaults to Tailscale.
Use --route-provider lan|tailnet|relay explicitly to select another route.
```

Explicit flags are always non-interactive except when Tailscale's existing
optional package-install confirmation is itself running in a TTY.

Cloudflare Tunnel remains available through the explicit advanced flag
`--route-provider cloudflare_tunnel`; it is intentionally omitted from the
beginner menu.

## Route Flows

### 1. Tailscale

- Reuse the existing Tailnet onboarding.
- Keep the gateway loopback-only.
- Detect installation and login state.
- Require explicit confirmation before installing Tailscale.
- Configure Tailscale Serve, never Funnel.
- Tell the user that the phone must sign in to the same Tailnet.
- Print the pairing QR only after the gateway and route are ready.

### 2. Local network (LAN)

- Explain that phone and computer must be on the same trusted LAN.
- Suggest a private IPv4 address when one can be discovered locally.
- Ask for `HOST:PORT`, prefilled with `<detected-private-ip>:8787`.
- If no private address is discoverable, show
  `192.168.1.100:8787` as an example but require the user to enter the actual
  address.
- Reject loopback, unspecified, multicast, public, and malformed addresses.
- Start the gateway directly on the selected private interface.
- Derive `http://HOST:PORT` unless `--public-url` was explicitly supplied.
- Warn that LAN mode is plaintext HTTP and should be used only on a trusted
  local network; do not claim Internet reachability.
- Print the same complete pairing QR and manual pairing fallback.

### 3. CCB official Relay

- First inspect the existing owner-only Relay host credential file.
- If valid credentials with `relay_mode=official` already exist, reuse them.
  A new invitation is not required for each pairing QR.
- If no credentials exist, ask for the path to an owner-only, one-time
  invitation file.
- Do not accept or echo invitation contents in the guided flow.
- Empty input must stop before gateway startup and print:
  - request an invitation by email at `bfly123@126.com`; or
  - contact the CCB Relay administrator through WeChat.
- Do not invent or print a WeChat account that was not configured.
- Activation consumes the invitation on the computer. The invitation must
  never enter the phone QR, logs, evidence, shell history, or source tree.
- If existing credentials are self-hosted, do not overwrite them. Explain that
  the operator must revoke or back up/remove the old credential file before
  switching modes.

### 4. Self-hosted Relay

- First reuse valid existing credentials with `relay_mode=self-hosted`.
- Otherwise explain the minimum server contract:
  - a stable public `wss://` endpoint;
  - Android-trusted TLS on port 443;
  - WebSocket reverse proxying;
  - owner-only admission state;
  - bounded host/session/frame/stream limits;
  - one-time invitations issued by that Relay operator.
- Link to `mobile/docs/relay/relay-deployment-modes.md` and its GitHub version.
- Ask for the Relay `wss://` origin and owner-only invitation-file path.
- Empty input exits with copyable activation and rerun command shapes; it must
  not partially create credentials or start a gateway.
- Never auto-deploy a remote server or alter firewall/DNS from
  `ccb update mobile`.

## Explicit Automation

Existing explicit route flags remain supported:

```sh
ccb update mobile --route-provider tailnet
ccb update mobile --route-provider lan --listen 192.168.1.20:8787
ccb update mobile --route-provider relay
ccb update mobile --route-provider cloudflare_tunnel \
  --listen 127.0.0.1:8787 --public-url https://mobile.example.com
```

Relay activation remains a separate deterministic command for scripts:

```sh
ccb relay host activate --mode official \
  --invitation-file /path/to/ccb-relay.key

ccb relay host activate --mode self-hosted \
  --relay-origin wss://relay.example.com \
  --invitation-file /path/to/ccb-relay.key
```

The guided menu calls the same activation service; it must not create a second
credential format.

## Security And Evidence Boundary

- Invitation files and Relay host credentials must be owner-only.
- Existing host credentials are reusable; pairing codes and Relay phone
  bootstraps remain independently rotatable and single-use.
- Prompts may show paths but must never print invitation contents.
- Errors must not include raw invitation data, private keys, pairing tokens, or
  complete Relay envelopes.
- Test evidence belongs under a temporary external root such as:

```text
/tmp/ccb-mobile-route-onboarding-20260725/
```

- No screenshot, packet capture, invitation, server key, credential JSON,
  emulator state, or redacted runtime dump belongs in the source checkout.
- Repository tests may contain synthetic fixtures only.

## Implementation Tree

1. `lib/cli/management_runtime/commands_runtime/update.py`
   - TTY detection and four-route selection;
   - route dispatch;
   - Relay credential reuse/activation guidance;
   - non-interactive compatibility.
2. `lib/cli/services/mobile_update.py`
   - LAN onboarding;
   - private-address suggestion and validation;
   - shared service summary, QR, and phone guidance.
3. Existing Relay services
   - keep `relay_host_activate_command` and
     `mobile_gateway.relay_host_credentials` authoritative.
4. Tests
   - management route selection/dispatch;
   - invalid/cancel/EOF behavior;
   - non-TTY default;
   - explicit-route no-prompt behavior;
   - official credential reuse and missing-key guidance;
   - self-hosted setup guidance;
   - LAN validation and QR generation.

## Automated Acceptance Matrix

| Case | Expected result |
| --- | --- |
| TTY, choose `1` | Tailnet onboarding only |
| TTY, choose `2` | LAN onboarding only |
| TTY, choose `3`, official credentials exist | Reuse, start Relay |
| TTY, choose `3`, no credentials, valid key path | Activate once, start Relay |
| TTY, choose `3`, empty key path | Contact guidance, no service start |
| TTY, choose `4`, self-hosted credentials exist | Reuse, start Relay |
| TTY, choose `4`, no credentials | Origin/key guidance, no partial state |
| Invalid choice three times | Clean failure, no service start |
| EOF or empty selection | Clean cancellation |
| Non-TTY bare invocation | Tailnet compatibility path, no read |
| Explicit `--route-provider lan` | No Tailnet checks |
| Explicit `--route-provider relay` | No menu, reuse activated credentials |
| Explicit Cloudflare route | Existing advanced route remains reachable |

## Real Validation

Use one source commit and one APK hash for the final route regression.

### LAN

1. Start the server-wide gateway on a dedicated private or emulator-reachable
   address.
2. Pair the Android emulator through the generated LAN QR.
3. Verify real mounted projects, project view, conversation, terminal,
   notification stream, and route diagnostics.
4. Confirm no Tailscale command is invoked.

### Official Relay

1. Reuse the activated CCB official Relay host credentials.
2. Run the interactive menu and select option `3`.
3. Pair a clean emulator profile through the complete Relay QR.
4. Verify project list, conversation, terminal WebSocket, notification stream,
   reconnect, and diagnostics through the public Relay.
5. Confirm no invitation appears in the QR or captured redacted evidence.

### Self-hosted Relay

Automated tests use a local TLS/WebSocket Relay harness and synthetic
invitation. Public self-hosted deployment is not required for this package,
but the same activation and route contract must pass end to end.

## Completion Gate

This package is complete only when:

- the PlanTree and CLI behavior agree;
- focused Python tests pass;
- the broader relevant CLI/mobile gateway tests pass;
- Flutter tests and APK build still pass;
- real emulator LAN and official Relay routes pass against real mounted
  projects;
- `git diff --check` passes;
- the source worktree contains no runtime evidence or secret material.

## Validation Result

Completed on 2026-07-25 from one isolated source worktree and one debug APK:

- 455 relevant Python CLI, gateway, Relay, stream, terminal, notification, and
  parser tests passed.
- 713 Flutter tests passed; one explicitly skipped test remained skipped.
- The debug APK built successfully as version `8.3.1+8030001`.
- Interactive LAN setup selected the physical RFC1918 interface instead of
  Tailscale, tunnel, container, or benchmark-network interfaces.
- A clean Android emulator paired through the generated LAN QR, listed real
  server-wide projects, opened a structured conversation, rendered the real
  pane through Terminal WebSocket, and reported `lan` in diagnostics.
- Interactive official Relay setup reused the activated host credentials
  without requesting another invitation. A clean emulator paired through a
  fresh single-use Relay bootstrap, listed the same real projects, opened the
  same conversation and terminal, reported `relay/official`, and reconnected
  after an app force-stop without scanning another QR.
- `adb reverse` was absent throughout Relay validation.
- The shared server still reported the CCB Relay service and both RustDesk
  services/listeners active after validation.
- Missing official and self-hosted Relay setup inputs exited before creating
  service state; the official path printed the configured email and WeChat
  contact guidance.
- Pairing payloads, QR images, logs, screenshots, server summaries, and
  credentials remained under an external owner-controlled temporary evidence
  root and were not added to the source checkout.

The Flutter analyzer reported no Dart issues but could not exit cleanly because
the shared test host had exhausted its per-user inotify-instance quota. The
full Flutter test compilation and APK build both completed successfully; this
environmental analyzer failure is recorded rather than presented as a passing
analyzer run.
