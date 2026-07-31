# Validation Runbook

Date: 2026-06-04

## Automated Tests

Targeted suites:

```bash
pytest -q \
  test/test_install_identity_output.py \
  test/test_install_root_confirmation.py \
  test/test_install_script_sidebar.py \
  test/test_cli_management_update.py \
  test/test_cli_startup_update.py \
  test/test_npm_runner.py \
  test/test_provider_updates.py \
  test/test_provider_profiles.py \
  test/test_gemini_launcher_env.py \
  test/test_claude_legacy_binary_cache.py \
  test/test_cleanup_service.py \
  test/test_storage_classification.py \
  test/test_runtime_env_user_session.py \
  test/test_v2_runtime_launch.py \
  test/test_rolepacks.py \
  test/test_source_runtime_guard.py \
  test/test_build_linux_release_script.py
```

Covered by targeted tests:

- update post-provisioning delegates to newly installed `ccb`
- old updater does not run Role Pack update semantics after install
- post-update delegation prefers the installed bin wrapper or explicit
  `CODEX_BIN_DIR` before falling back to the raw install entrypoint
- post-update optional provisioning failure stays a warning, while forced
  provisioning failure returns failure
- forced Role Pack provisioning returns failure when catalog refresh fails,
  installed role update fails, or a selected new role install fails
- `CCB_POST_UPDATE_REQUIRED=1` auto-accepts Role Pack provisioning and marks
  Neovim provisioning required without prompting in TTY sessions
- legacy installed `ccb.archi` migrates to `agentroles.archi`
- legacy installed `ccb.archi` also migrates on direct role status queries
- stale `source_path` falls back to catalog
- Role Pack `current` skips update hooks
- inherited `ccb-config` Codex and Claude skill docs use canonical
  `agentroles.archi` examples and mention `ccb.archi` only as a legacy input
  alias
- npm runner provenance overrides inherited stale marker values
- npm-managed explicit updates leave the vendored payload byte-identical
- npm-managed startup acceptance prints the exact target command, does not
  call the tarball updater or relaunch, and respects the defer window on the
  next invocation
- managed Codex, Claude, Gemini, Droid, AGY, Grok, OpenCode, MiMo, and Pi
  launches disable their known provider-native update checks/notifications
  without modifying global provider settings; Gemini's auto-update and
  update-notification switches are independently forced off
- provider npm ownership is derived from the resolved executable and updated
  with the matching npm installation
- Droid's native read-only update check is retried once on transient failure
  and produces a pinned native self-update command
- default non-TTY provider update mode performs no network check or mutation
- accept, decline, select, and exact-version mute state are bilingual and
  version-scoped
- accepted provider updates must pass a post-update version probe
- managed Claude preparation does not create/copy/hash a project cache and
  detaches only exact CCB-owned legacy links
- managed Gemini cache is user scoped and cannot recursively nest when CCB is
  called from a managed Gemini environment
- default cleanup is current-project bounded; cross-project cleanup requires
  `--legacy-provider-caches`, a valid manifest, a matching recomputed project
  id, and a missing recorded project root
- storage diagnostics expose the retired current-project cache separately and
  identify the user-scoped cache without recursively scanning shared scope

Remaining tests to add:

- tool manifest current skips repeated install
- non-interactive update skips optional provisioning and prints retry commands

## Local Release Simulation

Use isolated homes:

```bash
export HOME=/tmp/ccb-install-home
export XDG_DATA_HOME=/tmp/ccb-install-home/.local/share
export XDG_CACHE_HOME=/tmp/ccb-install-home/.cache
export CODEX_INSTALL_PREFIX=/tmp/ccb-install-home/.local/share/codex-dual
export CODEX_BIN_DIR=/tmp/ccb-install-home/.local/bin
```

Scenarios:

1. Fresh release install with default optional prompts accepted.
2. Fresh release install with `CCB_INSTALL_ROLES=0` and `CCB_INSTALL_NEOVIM=0`.
3. Non-interactive fresh install.
4. Update from an older release with no Role Packs installed.
5. Update from an older release with canonical `agentroles.archi` installed.
6. Update from an older release with legacy `ccb.archi` installed.
7. Update with catalog unavailable but cache already present.
8. Update with catalog unavailable and no cache.
9. Root install non-interactive failure.
10. Root install explicit override.

## Real Project Smoke

Use the dedicated disposable project outside `ccb_source` at
`/home/bfly/yunwei/test_ccb2`. When validating current source changes from this
checkout, use the absolute source wrapper
`/home/bfly/yunwei/ccb_source/ccb_test`, not the installed `ccb`. Do not rely
on a bare `ccb_test` until `command -v ccb_test` and `readlink -f` prove it is
the source wrapper.

Commands:

```bash
cd /home/bfly/yunwei/test_ccb2
export HOME=/home/bfly/yunwei/test_ccb2/source_home
export CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home
/home/bfly/yunwei/ccb_source/ccb_test --diagnose
/home/bfly/yunwei/ccb_source/ccb_test doctor
/home/bfly/yunwei/ccb_source/ccb_test roles list
/home/bfly/yunwei/ccb_source/ccb_test roles install agentroles.archi
/home/bfly/yunwei/ccb_source/ccb_test roles doctor agentroles.archi
/home/bfly/yunwei/ccb_source/ccb_test roles add agentroles.archi:codex --window main
/home/bfly/yunwei/ccb_source/ccb_test
/home/bfly/yunwei/ccb_source/ccb_test reload
/home/bfly/yunwei/ccb_source/ccb_test doctor
/home/bfly/yunwei/ccb_source/ccb_test kill
```

Expected:

- no `ccb.archi` user-facing failure
- no repeated role/tool installation when role/tool is current
- `archi` appears as project agent name
- role id remains `agentroles.archi`
- runtime can mount and cleanly stop

### Cache-retirement smoke

Use a disposable project below `/home/bfly/yunwei/test_ccb2` with an isolated
`HOME` and one managed Gemini agent:

1. Run `ccb_test --diagnose` from the external test root.
2. Start the project and confirm
   `~/.cache/ccb/projects/<project-id>/provider-cache` does not exist.
3. Confirm npm/XDG directories exist only below
   `~/.cache/ccb/provider-cache/gemini/`.
4. Run `ccb_test doctor storage` and require
   `storage_legacy_provider_cache_present: False`.
5. Run a warm start and then `ccb_test kill`.
6. Inject synthetic current-project legacy Claude/Gemini cache plus an exact
   managed Claude link; run `ccb_test cleanup` and confirm only that cache and
   link are removed.
7. Inject one manifest-valid deleted-project bucket plus an unknown Provider
   directory; run `ccb_test cleanup --legacy-provider-caches` and confirm
   Claude/Gemini are removed while the unknown directory remains.
8. Start the backend again and confirm cleanup is refused until `ccb_test
   kill` succeeds.
9. Exercise the post-update runner with isolated `HOME`, `XDG_CACHE_HOME`, and
   `XDG_STATE_HOME`: verify that a manifest-valid deleted-project bucket is
   removed, an active current project is preserved, and
   `provider-cache-cleanup.json` records the deferred project.
10. Complete `ccb_test kill` for the deferred project and verify its retired
    cache is then removed. Repeat with `--no-cache-cleanup` and confirm no
    update-time deletion occurs.
11. Hold the user-level migration lock from one test process and confirm a
    second update runner skips without touching cache. Inject malformed
    manifests, unknown Providers, Provider-directory symlinks, and a manifest
    symlink; all must remain.

Latest local evidence, 2026-07-23:

- syntax compilation and whitespace validation passed
- 496 broad Provider/storage/CLI tests passed
- 79 phase-2 entrypoint tests passed
- repository-wide pytest: 5933 passed, 15 skipped, one OpenCode shutdown
  `ENOENT`; the exact failed test passed on isolated rerun
- external source-wrapper Gemini cold start mounted successfully in about
  907 ms; warm start completed in about 123 ms; a later real Claude+Gemini
  dual-provider mount also succeeded, and all normal kills succeeded
- the Claude pane used the user installation at
  `/home/bfly/.local/share/claude/versions/2.1.206`; its managed HOME contained
  no `.local/share/claude/versions` tree or managed binary link
- no project-scoped Provider cache was generated; current and orphan cleanup
  boundaries matched the steps above
- bounded automatic-cleanup follow-up passed 636
  update/provider/storage/kill/install/release regressions plus 11 repository
  hygiene checks, syntax compilation, and whitespace validation
- an isolated external `ccb_test kill` removed one synthetic current-project
  legacy cache and reported `cleanup_legacy_provider_cache:deleted=1`
- an isolated, parent-authorized `ccb_test __post-update` removed one
  manifest-valid deleted-project cache, preserved an unknown Provider and the
  user-scoped Gemini sentinel, wrote the migration state file, emitted Chinese
  output, and left a second orphan intact when `--no-cache-cleanup` was passed
- the final clean-environment repository run completed with 5806 passed,
  2 skipped, and zero failures

## Release Gate

Before publishing:

- targeted suites pass
- `compileall` or equivalent syntax check passes
- `git diff --check` passes
- Linux release build passes
- update from previous stable release passes in an isolated home
- update from a legacy Role Pack state passes in an isolated home
- Chinese and English prompt checks pass
- post-update cache migration runs only through the newly installed,
  parent-authorized runner and serializes concurrent update windows
- automatic migration avoids a separate exact-size traversal, preserves
  unsafe content and the user-scoped Gemini cache, and remains non-blocking
- a required post-update failure that selects rollback does not run cache
  migration
- `ccb update --no-cache-cleanup` reaches the new runner and suppresses the
  migration
- `inherit_skills/{codex_skills,claude_skills}/ccb-config/` is synchronized
  with any config/usage changes introduced by the release
