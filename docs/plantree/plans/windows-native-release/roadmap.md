# Native Windows Release Roadmap

Date: 2026-08-11

## Completed locally

- Restored workflows, documentation, reconnect tests, executable modes, and
  Unix release code removed or rewritten by PR #293.
- Moved Windows-owned runtime and release code into dedicated folders.
- Added a native Rust launcher and Windows-only packaging workflow.
- Kept Windows out of npm package metadata and stable tag workflows.

## Current gate

- Run focused Python/static regression tests in the isolated release worktree.
- Push the release commit and immutable prerelease tag.
- Require the Windows 2022 GitHub Actions build, PowerShell archive install,
  and native launcher smoke test to pass before the GitHub prerelease exists.

## Next after publication

1. Install the ZIP on a real user Windows x64 machine.
2. Validate WezTerm + Herdr startup, pane creation, capture, restart, kill, and
   Codex/Claude provider workflows.
3. Record failures without upgrading the support tier prematurely.
4. Cut another beta for fixes; do not move an already published tag.
