# Continuous Inheritance Implementation Plan

Date: 2026-08-05

Status: Planning

## Goal

Make the requested behavior observable and testable without weakening the
one-way external-state boundary:

```text
ccb.config authority
        | (wins per owned dimension)
        v
external source snapshot -> private managed generation -> Provider process
                                      |
                                      v
                         stable CCB conversation/history
```

The Provider process is replaced when inherited state changes, but the CCB
conversation is not erased. Native remote resume is used only when the
Provider adapter proves it safe; otherwise a linked continuation is created.

## Non-goals

- Hot-changing credentials inside a running Provider process.
- Writing managed refresh/logout/config changes back to the user's Provider
  home, shell, IDE, keyring, or remote login.
- Treating copied rotating OAuth refresh tokens as independent credentials.
- Replaying a persisted shell command as the restart authority.
- Promising native remote resume across an account switch without Provider
  evidence.

## Work packages

### A. Composite authority resolver

1. Keep the public `key/url`, `inherit_*`, and `provider_profile.env` fields.
2. Compile credential, route, account-selection, and non-auth config into one
   typed `ResolvedProviderAuthority` with per-dimension precedence and
   provenance.
3. Add a tri-state source probe and immutable/generation-checked snapshot
   handle. A transient read error is not logout.
4. Record a redacted `provider.json` authority generation and owner-only
   `auth-provenance.json` projection record.

Likely surfaces: `lib/agents/config_loader_runtime/`,
`lib/provider_profiles/materializer.py`, `lib/provider_core/registry.py`, and
new `lib/provider_auth/` resolver/adapter modules.

### B. One-way projection and refresh

1. On every stopped new generation, consume the same source snapshot used by
   classification.
2. Replace source-owned API/config/auth projections when the source is
   `present` or `authoritative_absent`.
3. Preserve independently Agent-owned credentials; mark unknown dependency as
   `reauth_required` instead of guessing.
4. Detach legacy aliases before writing and verify source fixtures remain byte,
   inode, mode, timestamp, and keyring-operation unchanged.

Provider adapter order: Codex, Claude, Gemini; then static API Providers; then
other native CLIs after capability evidence.

### C. Stable CCB conversation and generation binding

1. Introduce a stable CCB conversation id separate from native Provider
   session id and authority fingerprint.
2. Extend session records with `authority_generation`, `parent_conversation_id`,
   `continuity_status`, and `resume_compatibility`.
3. On compatible authority change, migrate/adopt the native binding in place.
4. On unknown/incompatible native resume, retain the old transcript and start
   a linked continuation generation with a summarized/imported context.
5. Make `resume` enumerate the CCB history index first, so archived/native
   lookup failure cannot make history disappear.

Likely surfaces: `lib/provider_backends/session_authority.py`, Codex/Claude/
Gemini restore and session stores, `lib/provider_core/session_binding*`, and
the CCB resume/diagnostic services.

### D. Restart and lifecycle integration

1. Treat `ccb restart <agent>` and pane-death replacement as a new Provider
   generation: quiesce, probe, project, persist prepared authority, spawn,
   verify binding, then activate.
2. Keep ordinary attach/reuse fast, but expose that it did not resynchronize
   external state.
3. If source probe/projection/rebind fails, leave the Agent stopped/degraded
   and retain all local conversation artifacts.
4. Reconcile prepared generations and writer leases after daemon restart.

Likely surfaces: `lib/ccbd/start_preparation.py`,
`lib/ccbd/handlers/project_restart.py`, runtime supervisor/authority commit,
and recovery diagnostics.

### E. v8.5.5 migration and release

1. Detect the withdrawn 8.5.5 `*-global` archive shape and restore only when
   binding/path evidence proves the archive belongs to that Agent.
2. Adopt pre-fingerprint compatible sessions without clearing them.
3. Preserve a newer current binding while merging older archived transcripts.
4. Make migration idempotent, owner-only, and fully observable in diagnostics.
5. Publish a replacement release only after the acceptance gates below pass;
   keep the withdrawn 8.5.5 release unavailable.

## Acceptance matrix

| Scenario | Required result |
| :--- | :--- |
| Explicit config API/route present | Config wins; ambient auth/API is not selected; source untouched |
| No explicit authority, source present/changed | New private generation uses the new source snapshot after stopped restart |
| Source logout/removal | Source-owned projection removed/status-only; independent Agent credential preserved |
| Source probe unknown | No stale launch; local history and source remain intact |
| Same authority restart | Native session and CCB conversation continue |
| Authority changed, native rebind proven | Same CCB conversation and native session continue under new generation |
| Authority changed, native rebind unproven | Linked continuation starts; old transcript remains in `resume` |
| Legacy/no fingerprint or v8.5.5 archive | History is adopted/restored, never silently cleared |
| `ccb clear`/`kill`/cleanup | Only CCB-owned state changes; no external logout/write |
| Visible + headless refresh | One writer lease or independently qualified credentials; no shared rotating writer |

## Verification gates

1. Unit tests for precedence, tri-state probes, provenance, and session record
   migration.
2. Provider fixture tests for one-way projection, source mutation invariance,
   source replacement/removal, and alias detachment.
3. Fake OAuth tests for rotation, reuse rejection, revocation, and independent
   derivation; unknown semantics fail closed.
4. Runtime tests from `/home/bfly/yunwei/test_ccb2` using
   `/home/bfly/yunwei/ccb_source/ccb_test` with isolated source homes.
5. Inspectable live-project tests for `ccb restart`, `resume`, pane recovery,
   and queue/workspace continuity.
6. Diagnostics tests proving no secret values enter session/start commands or
   bundles.
7. Full regression, compile, diff-check, migration idempotence, and rollback
   fixture checks before release.

## Rollback

Rollback may restore the prior binary but must preserve the CCB history index,
never recreate external aliases, never invoke remote logout, and never delete
the external source. A failed migration can be retried from the preserved
managed archive and binding manifest.
