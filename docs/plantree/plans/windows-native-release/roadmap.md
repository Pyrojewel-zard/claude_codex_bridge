# Native Windows Release Roadmap

Date: 2026-08-12

## Completed locally

- Restored workflows, documentation, reconnect tests, executable modes, and
  Unix release code removed or rewritten by PR #293.
- Moved Windows-owned runtime and release code into dedicated folders.
- Added a native Rust launcher and Windows-only packaging workflow.
- Kept Windows out of npm package metadata and Unix release builders.
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

## Published stable v8.6.0

- Promoted the repository version to stable `8.6.0` across Python, npm, mobile,
  and Windows launcher identity.
- Kept the Windows projection and archive manifest at beta support tier.
- The isolated Windows workflow now builds both immutable beta tags and
  stable CCB tags, attaching its ZIP to the same GitHub Release.
- Stable Linux, macOS, Android, Sidebar, and npm workflows published normally;
  the Windows workflow does not replace or gate their
  platform-specific assets.
- Preserved `v8.6.0-beta.3` as immutable evidence rather than moving its tag.
- GitHub Latest, all ten published assets, their downloaded checksums, npm
  `latest`, and a clean npm-installed CLI smoke were verified after publication.

## Published stable v8.6.1

- Published the audited Mobile Provider controls, direct terminal and shortcut
  controls, built-in `ccb-compact`, and the complete Config UI Role catalog.
- Fixed Provider-mutation idempotency so cached results are bound to the exact
  project and Agent, and fixed compound Mobile terminal input frames so text
  and Enter reach the Pane in order.
- Kept the isolated Windows x64 artifact at beta support tier and attached it
  to the same stable GitHub Release without changing Unix/npm ownership.
- Main-commit Tests, Cross-Platform, and CCBD Real Platform gates passed on the
  exact release commit. All publication workflows passed for Linux, macOS,
  Android, Windows, Sidebar, and npm.
- Verified GitHub Latest, all ten downloaded assets and checksum files, the
  Android manifest, Windows PE x86-64 launchers, npm `latest`, and a clean
  npm-installed CLI and `ccb compact` help smoke.

## Next after stable publication

1. Install the ZIP on a real user Windows x64 machine.
2. Validate WezTerm + Herdr startup, pane creation, capture, restart, kill, and
   Codex/Claude provider workflows.
3. Record failures without upgrading the support tier prematurely.
4. Cut a new immutable release for fixes; do not move an already published
   stable or beta tag.
