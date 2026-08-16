# LAN Network Awareness And Recovery

Date: 2026-08-02
Status: Implemented; physical validation pending
Mode: Execute-ready

## Problem

The LAN route stores the exact gateway address from the pairing payload. The
connection supervisor can recover after ordinary request failures, but the
phone cannot currently explain whether a failed LAN connection is caused by
missing Wi-Fi, a VPN, guest-network isolation, or a changed computer address.
The terminal WebSocket also has no client heartbeat, so a silent Wi-Fi half-open
connection can remain visible until another read or write detects it.

## Scope

1. Read Android network transports without requesting location, SSID, BSSID,
   or any other identifying network data.
2. Before claiming a LAN QR/code, warn when no Wi-Fi/Ethernet transport is
   visible and allow an explicit continue for phone-hotspot and platform edge
   cases.
3. While a paired LAN route is reconnecting, show a persistent bilingual
   diagnosis for offline, mobile-data-only, VPN, and Wi-Fi-but-host-unreachable
   states. The message must point to same-network, guest/client isolation,
   firewall, DHCP address change, `ccb update mobile`, Retry, and diagnostics
   as appropriate.
4. Add a bounded client WebSocket ping interval so silent terminal disconnects
   enter the existing reconnect/resume path without replaying input.
5. Expand computer-side LAN onboarding guidance with the same recovery model.

## Boundaries

- Network status is diagnostic evidence, not route or credential authority.
- Do not read or display Wi-Fi names, hardware addresses, local device
  identifiers, tokens, or pairing secrets.
- Do not automatically switch LAN profiles to Relay/Tailnet, rewrite a stored
  gateway URL, retry mutations, or bypass device-token validation.
- A phone hotspot can be a valid LAN even when Android reports cellular as the
  active transport; warnings therefore remain advisory and offer an explicit
  continue during pairing.
- Automatic mDNS discovery and transparent host-address migration remain out
  of scope because they require a separately authenticated discovery and
  host-identity contract.

## Acceptance

- LAN pairing on an Android device with no Wi-Fi/Ethernet displays a targeted
  warning before the claim request; non-LAN routes do not.
- A reconnecting LAN profile shows a persistent, localized notice, while a
  healthy LAN route and every non-LAN route remain unchanged.
- Android transport inspection needs only `ACCESS_NETWORK_STATE` and reports
  coarse booleans for connected/Wi-Fi/Ethernet/cellular/VPN.
- Terminal WebSockets use a positive default ping interval and retain the
  existing sequence cursor, handle renewal, and zero-input-replay semantics.
- Focused Dart/widget, Android source-contract, Python onboarding, formatting,
  and static-analysis tests pass. Same-commit physical Wi-Fi/guest-network/
  DHCP-change evidence remains a release gate rather than a unit-test claim.

## Landing Surface

- `mobile/app/lib/app/mobile_network_status.dart`
- `mobile/app/lib/features/project_home/gateway_lan_network_banner.dart`
- `mobile/app/lib/features/project_home/project_home_screen.dart`
- `mobile/app/lib/transport/http_gateway_transport.dart`
- `mobile/app/android/app/src/main/AndroidManifest.xml`
- `mobile/app/android/app/src/main/kotlin/io/ccb/mobile/ccb_mobile/MainActivity.kt`
- `lib/cli/services/mobile_update.py`
- focused tests beside those surfaces

## Delivered

- Android exposes only coarse connected/Wi-Fi/Ethernet/cellular/VPN booleans
  through `io.ccb.mobile/network_status`; no location or Wi-Fi identity is
  requested.
- LAN pairing performs a fail-open, two-second-bounded network preflight. A
  cellular/offline/VPN warning blocks the claim only until the user cancels or
  explicitly continues; every non-LAN route bypasses the preflight.
- A reconnecting LAN profile retains its route and credentials while showing
  the localized persistent recovery banner. Retry refreshes both network
  evidence and the existing connection supervisor; Diagnostics runs the
  existing authenticated route diagnostic.
- HTTP gateway terminal WebSockets use a 15-second ping interval. Missing
  pongs close the socket into the existing cursor-resume path; input frames are
  not replayed and stored gateway URLs are not rewritten.
- `ccb update mobile` LAN onboarding and the mobile README now explain
  same-network, hotspot, guest/client isolation, VPN, firewall, and DHCP
  address-change recovery.

## Verification

Verified locally on 2026-08-02:

- Flutter static analysis: no issues.
- Full Flutter suite: `736 passed, 1 skipped`.
- LAN/mobile Python CLI regression selection: `34 passed, 52 deselected`
  (`test_cli_services_mobile_update.py` itself: `29 passed`).
- Android debug APK built successfully with Flutter 3.44.2, Android SDK 36,
  and Temurin JDK 17. The APK is 179,363,174 bytes with SHA-256
  `0d960b2aabcf8834b7ccc50aa7189ad66fc4d3fd0b36d3f6fe93a43b5b7ae30c`.
- Packaged manifest inspection confirms `INTERNET`,
  `ACCESS_NETWORK_STATE`, and `WAKE_LOCK`.

Still required before a release acceptance claim: use one physical Android
phone to exercise ordinary same-Wi-Fi pairing, phone hotspot, guest/client
isolation, VPN-local-access denial, Wi-Fi loss/recovery, and a computer DHCP
address change. Unit/widget/build evidence does not substitute for that radio
and router matrix.
