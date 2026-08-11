# Native Windows Release Plan

Date: 2026-08-11

## Goal

Turn PR #293 into an isolated, testable native Windows x64 prerelease without
changing the stable Linux, macOS, npm, sidebar, or Android release products.

## Current target

- Version/tag: `v8.6.0-beta.1`
- Artifact: `ccb-windows-x86_64.zip`
- Installer: root `install.ps1`, implemented by
  `platforms/windows/installer/install.ps1`
- Runtime source ownership: `lib/platforms/windows/`
- Release tooling ownership: `platforms/windows/`

## File map

- [roadmap.md](roadmap.md): gates and current status.
- [topics/v8.6.0-beta.1.md](topics/v8.6.0-beta.1.md): implementation and
  verification record for this prerelease.
- [decisions/001-isolated-windows-prerelease.md](decisions/001-isolated-windows-prerelease.md):
  frozen isolation and publication boundaries.

## Acceptance boundary

The tag is a beta, not a stable-support declaration. Publication requires a
native Windows x64 build, checksum, archive install, and `ccb.exe` smoke test.
Real WezTerm/Herdr behavior remains a post-publication qualification gate.
