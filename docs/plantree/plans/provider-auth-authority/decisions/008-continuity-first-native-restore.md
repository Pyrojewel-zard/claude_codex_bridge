# Continuity-First Native Restore

Date: 2026-09-29
Status: Accepted direction; Claude/Codex/OMP/Pi implemented and locally verified; broader qualification open

## Context

The owner prioritizes conversation continuity across accounts and API gateways.
Decision 007 preserved transcript files but allowed unknown compatibility to
start a linked, empty conversation. Claude's fingerprint veto also treated
credential refresh metadata as incompatibility before asking the native CLI.

## Decision

Supersede decision 007's preemptive fresh/linked fallback for account/route
changes. Authentication authority and local conversation identity are separate.
Attempt native restoration from the same Agent-owned home with the newly
prepared credentials and route. A changed fingerprint is provenance, not proof
that a transcript is unusable. Explicit fresh/clear remains authoritative.

For this slice, Claude keeps its existing native `--continue` path. Do not add
exact-id resume, fork/import transformations, global recovery infrastructure,
or transcript rewriting. Remove the authority-mismatch and linked-pending
vetoes, retain ownership checks, and test session persistence as well as launch.
Only absent usable history or a recognized native missing-conversation failure
permits automatic fresh fallback. Auth, network, rate-limit, and ambiguous
compatibility failures preserve history and surface failure rather than clear.

## Acceptance And Limits

- Changed account metadata, credentials, or route still selects native continue.
- Repeated launch and legacy linked-pending records do not remain stuck fresh.
- Explicit fresh and foreign-home/path isolation remain unchanged.
- Fresh fallback preserves the old transcript and records a non-secret reason.
- Validate CCB selection, persistence, native missing-history recovery, and real
  Claude CLI history replay between two loopback endpoints with fake keys.
- Loopback evidence is not qualification of arbitrary commercial accounts,
  OAuth refresh isolation, gateways, transcript formats, or reasoning signatures.
- Codex/OMP/Pi extension authorized on 2026-09-29: preserve Codex's validated
  local native binding when authority changes; retain fingerprints for launch
  provenance. Do not remove ownership checks or relax native identity checks.
  Carry forward the earlier OMP title-slot and Pi manual-session observation
  fixes into this isolated slice, without unrelated keyboard changes.
- Verify each real CLI with temporary homes and two loopback routes/fake keys:
  finish a turn, close the process, select history through CCB, reopen on a new
  route/key, and assert old user/assistant history reaches the new endpoint.
  Repeat on the same authority, test missing/invalid bindings and explicit
  fresh, and record any CLI-specific limits. No business panes are involved.
- Gemini alignment remains separate; commercial/OAuth accounts and arbitrary
  gateway protocol compatibility are not proven by loopback qualification.

No external Provider state, business panes, installed runtime, or release
metadata changes are authorized. Rollback is a source patch revert while
stopped; no history/auth rollback or deletion is required.
