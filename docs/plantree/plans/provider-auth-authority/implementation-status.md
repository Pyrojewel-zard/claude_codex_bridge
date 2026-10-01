# Provider Authentication Authority Implementation Status

Date: 2026-09-29

## Current Phase

Claude/Codex continuity-first restoration and OMP/Pi resume fixes are published
in stable `v8.7.4` at `947f1a4a574ea601b4bb970fbcd6ca3cea36d3c2`. Account/route
changes no longer veto native local-history continuation. See
[decision 008](decisions/008-continuity-first-native-restore.md) and
[Claude evidence](evidence/claude-continuity-first-20260929.md) and
[Codex/OMP/Pi evidence](evidence/codex-omp-pi-continuity-20260929.md).

## Last Landed

The prior released authority and OAuth work is preserved in the
[previous status snapshot](history/implementation-status-before-continuity-first.md).
GitHub assets and npm `latest` are published; isolated exact-version npm install
and private runtime checks passed. See the [release receipt](evidence/v8.7.4-release-20260929.md)
for checksums, CI qualification, and limits. Existing working panes were not upgraded.

## Active TODO

1. Replace the WSL heartbeat fixture's fixed-duration race with deterministic test synchronization; the unchanged rerun passed.
2. Align Gemini's authority-change import/fresh selection and qualify native recovery.
3. Qualify interactive pane restoration and real gateway history compatibility;
   loopback replay proves native text history transport only.
4. Retain prior OAuth writer-ownership, arbitrary profile-home, macOS Keychain,
   and organic reconnect qualification work; none is closed by this slice.

## Blocked By

No user decision is required for this scoped implementation. Universal
provider support and arbitrary gateway compatibility are not established.
No real commercial account credentials were used or requested.

## Last Verified

- Combined regression/native verification: **402 passed**, no skips.
  [Exact selection and command](evidence/codex-omp-pi-continuity-20260929.md#regression-and-boundaries).
- Real Codex 0.157.1 / Pi 0.87.1 / OMP 18.3.5: 3 passed; each preserves
  native identity and sends old user/assistant history after changed route/key
  and a further process reopen. [Evidence](evidence/codex-omp-pi-continuity-20260929.md).
- Focused authority/restore/fields/crash/env matrix: 99 passed.
- Runtime launcher and Claude pane lifecycle regression: 133 passed.
- Real Claude Code 2.1.283, two loopback gateways and synthetic keys: same
  native session and prior user/assistant history replay verified.
- Source and reproducible commands: [evidence](evidence/claude-continuity-first-20260929.md).
