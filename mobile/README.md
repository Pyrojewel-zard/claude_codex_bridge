# CCB Mobile

Native Android/iOS/iPadOS remote controller for server-side CCB tmux projects.

This directory is the authoritative CCB Mobile source inside the CCB monorepo.
The legacy standalone `ccb_mobile` repository is retired as an implementation
surface and now exists only for migration/runtime compatibility notes.

CCB and provider CLIs run on the server; the mobile app is a controller for
project discovery, agent switching, terminal access, Markdown reading,
notifications, local/Tailnet gateway access, and file transfer.

## Android Alpha Release

CCB Mobile v8.3.1 is published as an Android APK:

- [Download ccb-mobile-v8.3.1.apk](https://github.com/SeemSeam/claude_codex_bridge/releases/download/v8.3.1/ccb-mobile-v8.3.1.apk)
- Server setup entrypoint: `ccb update mobile`
- App source: [`app/`](app/)

### Android app updates

The Android app checks the latest GitHub release after startup and also exposes
a manual **Check for updates** action in the connection settings. When GitHub
is unreachable, release metadata and APK downloads fall back to `gh-proxy.com`,
`ghfast.top`, and `ghproxy.net`, in that order. The downloaded APK must match
the size and SHA-256 digest in the release manifest before Android's installer
is opened. Android still requires the user to approve the signed APK update;
the app does not perform silent installation.

The app is designed for real server-side CCB projects, not a demo-only flow.
It connects to the server-wide mobile gateway, lists mounted CCB projects,
renders agent transcripts, sends pane-native text input, opens terminal views,
and supports image/document upload and download through the authenticated
gateway.

## Plan Tree

- [Mobile tmux control plan](docs/plantree/plans/mobile-tmux-control/README.md)
- [Remote access roadmap](docs/plantree/plans/mobile-tmux-control/topics/remote-access-roadmap.md)
- [Native Flutter blueprint](docs/plantree/plans/mobile-tmux-control/topics/native-flutter-ccb-blueprint.md)

## Project Layout

```text
app/                 Flutter mobile app
docs/plantree/       Planning tree and design decisions
tools/               Emulator, gateway, and acceptance helpers
```

iOS/iPadOS remain source-supported targets, but v8.3.1 release validation is
Android-focused.
