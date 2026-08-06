# Project Identity And Relocation

Date: 2026-07-24

## Purpose

Make a CCB project retain one stable identity when its `.ccb` anchor is moved
or renamed. Absolute paths remain runtime locators and diagnostics, but no
longer define `project_id` or the stable project slug.

## Scope

Current implementation scope:

- persist stable project identity and slug under the `.ccb` anchor;
- adopt unanimous inactive legacy runtime identity after a proven move;
- rebind the identity when its previous root no longer exists;
- reconcile stale lifecycle and lease identity before keeper startup;
- preserve identity through `ccb -n`;
- fail closed when foreign runtime authority is still live.

Deferred:

- logical `PathRef` records for workspace, session, socket, and runtime paths;
- an explicit project-fork command for copied anchors;
- automatic active-daemon relocation across a live directory move;
- host-level project binding registry.

## File Map

- [roadmap.md](roadmap.md): implementation sequence and deferred work.
- [implementation-status.md](implementation-status.md): current handoff and
  verification state.
- [decisions/001-stable-anchor-identity.md](decisions/001-stable-anchor-identity.md):
  stable identity and locator separation.

## Authority

Shipped startup and recovery behavior remains governed by
[../../../ccbd-startup-supervision-contract.md](../../../ccbd-startup-supervision-contract.md).
Storage behavior remains governed by
[../../../ccb-provider-state-storage-boundary-plan.md](../../../ccb-provider-state-storage-boundary-plan.md).

## Related Baseline

- [../../baseline/storage-and-state.md](../../baseline/storage-and-state.md)
- [../../baseline/runtime-flows.md](../../baseline/runtime-flows.md)
- [../../baseline/test-and-release-gates.md](../../baseline/test-and-release-gates.md)
