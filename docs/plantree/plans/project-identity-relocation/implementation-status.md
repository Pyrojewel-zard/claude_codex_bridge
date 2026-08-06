# Implementation Status

Date: 2026-07-24

## Current Phase

P0 and P1 are implemented in the working tree: stable anchor identity plus
safe inactive-runtime relocation recovery. Review/commit is pending.

## Active TODO

- Review and land the P0/P1 working-tree patch.
- Design logical `PathRef` records for durable bindings.
- Add an explicit project-fork workflow for copied anchors.
- Add identity and relocation fields to diagnostics.

## Done This Phase

- Recorded the stable identity and locator separation decision.
- Registered the implementation plan.
- Added durable `.ccb/project.identity.json` identity and stable slug records.
- Preserved legacy current-root IDs and adopted unanimous inactive moved
  runtime IDs; ambiguous or active authority fails closed.
- Reconciled stale lifecycle and lease identity before running intent and
  keeper startup.
- Preserved project identity through `ccb -n`.
- Added identity, move, copy-conflict, active-authority, reset, runtime
  reconciliation, and keeper-fence regressions.
- Verified a real stopped-project rename and a simulated pre-identity 8.3
  relocation using the external source-runtime test project.

## Blockers

- None.

## Next Commit Target

The complete P0/P1 stable identity and stopped-project relocation patch.

## Last Verified Commands

- `python -m pytest -q test/test_project_id.py
  test/test_project_identity_store.py test/test_v2_storage_paths.py
  test/test_ccbd_runtime_identity.py test/test_v2_ccbd_keeper.py
  test/test_ccbd_startup_fence.py test/test_v2_ccbd_start_flow.py
  test/test_v2_phase2_entrypoint.py test/test_v2_cli_kill.py
  test/test_v2_reset_project_service.py
  test/test_v2_project_namespace_state.py test/test_v2_project_resolver.py`
  - `238 passed in 245.25s`
- External source-runtime validation from `/home/bfly/yunwei/test_ccb2` with
  `/home/bfly/yunwei/ccb_source/ccb_test`:
  - stopped project retained project ID and stable slug after directory rename;
  - after removing only the test identity record to simulate an 8.3 anchor,
    the moved project adopted the original runtime ID and rebuilt lifecycle and
    lease at the new root;
  - final `ccb_test kill` reported unmounted state and a dead backend PID.

## Handoff Notes

Do not solve relocation by blindly replacing absolute path strings. Rebuild
transient runtime authority and preserve provider conversation identity.
The inspectable external test anchor remains at
`/home/bfly/yunwei/test_ccb2/project-identity-legacy-moved-dEiJHWrD`.
