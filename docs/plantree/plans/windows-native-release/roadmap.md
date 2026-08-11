# Native Windows Release Roadmap

Date: 2026-08-11

## Completed locally

- Restored workflows, documentation, reconnect tests, executable modes, and
  Unix release code removed or rewritten by PR #293.
- Moved Windows-owned runtime and release code into dedicated folders.
- Added a native Rust launcher and Windows-only packaging workflow.
- Kept Windows out of npm package metadata and stable tag workflows.
- Restored project-scoped tmux socket binding after PR #293's backend cache
  reuse broke the Linux/macOS/WSL lifecycle smoke.

## Published candidate

- `v8.6.0-beta.1` is immutable and superseded: native tests passed, but the
  ZIP builder rejected a stale `commands/` allowlist entry before publication.
- `v8.6.0-beta.2` is immutable and superseded: native tests and ZIP build
  passed, but archive installation incorrectly prompted for missing Herdr even
  with `-Yes`; no GitHub Release was created.
- `v8.6.0-beta.3` is published as a GitHub prerelease. Windows 2022 native
  tests, PE/ZIP build, PowerShell archive install, installed launcher smoke,
  SHA256 verification, and asset publication passed.
- Stable npm, Linux/macOS artifact, Sidebar, and Android publication routes
  remained untouched.

## Next after publication

1. Install the ZIP on a real user Windows x64 machine.
2. Validate WezTerm + Herdr startup, pane creation, capture, restart, kill, and
   Codex/Claude provider workflows.
3. Record failures without upgrading the support tier prematurely.
4. Cut another beta for fixes; do not move an already published tag.
