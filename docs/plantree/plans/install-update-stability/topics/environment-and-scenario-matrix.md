# Environment And Scenario Matrix

Date: 2026-06-04

## Axes

Platform:

- Linux x86_64
- Linux aarch64
- macOS universal
- WSL Linux runtime
- unsupported Windows native

Install mode:

- npm package with a manifest-pinned vendored release
- source/dev checkout
- official release tarball
- preview release tarball
- existing pre-v6 install
- existing v7+ install

User profile:

- normal user
- root
- sudo to root with `SUDO_USER`
- custom `CODEX_INSTALL_PREFIX`
- custom `CODEX_BIN_DIR`
- custom `XDG_DATA_HOME`, `XDG_CACHE_HOME`, and `XDG_STATE_HOME`

Interactivity:

- TTY interactive
- non-interactive CI or pipe
- env-forced install, for example `CCB_INSTALL_ROLES=1`
- env-skipped install, for example `CCB_INSTALL_ROLES=0`
- provider update modes `prompt`, `check`, `all`, and `none`

Provider installation owner:

- global npm/NVM package discoverable from the resolved executable
- provider-native self-updater
- provider-native read-only latest-version probe, currently Droid
- Homebrew formula or cask with a known package mapping
- Snap-managed executable
- Windows interop executable or shim resolved from WSL
- custom `*_START_CMD` wrapper or unknown package owner

Provider cache state:

- no prior CCB Provider cache
- current-project legacy Claude/Gemini cache
- recognized CCB-owned Claude cache links in a managed home
- foreign or malformed Claude cache links
- another existing project's legacy cache
- deleted project's manifest-valid legacy cache
- malformed or project-id-mismatched orphan cache
- user-scoped Gemini npm/XDG cache

Network:

- GitHub reachable
- GitHub unavailable
- catalog cache already present
- role/tool package source unavailable

Python:

- Python 3.10+ on PATH
- multiple Python versions where `/usr/bin/env python3` is too old
- Python without pip
- externally managed Python requiring `--break-system-packages`
- managed venv enabled
- managed venv disabled

Role state:

- no installed Role Packs
- installed canonical `agentroles.archi` and current catalog digest
- installed canonical `agentroles.archi` and changed catalog digest
- legacy installed `ccb.archi`
- stale legacy `source_path` pointing at removed CCB source-tree roles
- project lock pinned to older installed digest
- catalog unavailable

Tool state:

- no Neovim wrapper
- managed Neovim wrapper present and healthy
- system Neovim present
- LazyVim profile broken
- Architec wrapper present and current
- Architec wrapper missing or old

Language:

- `CCB_LANG=zh`
- `CCB_LANG=en`
- locale auto-detect Chinese
- fallback English

## Required Outcomes

Fresh install:

- Missing required Python or terminal backend fails before mutation where
  possible, with bilingual remediation.
- Optional `tomli`, `watchdog`, Droid, Role Pack, and Neovim failures do not
  fail install unless explicitly required.
- Already installed optional dependencies are reported as ready or current.
- Root install requires explicit confirmation and clearly states root profile
  boundaries.

Managed update:

- npm-managed updates print an exact package-manager command and do not mutate
  `.ccb-release`; accepting the startup prompt must not relaunch or immediately
  prompt again.
- Missing, malformed, stale, or foreign npm provenance never suppresses the
  normal release/source update path.
- Unsupported platform fails early.
- Failed download, extraction, staged installer, or new entrypoint smoke check
  fails the update.
- Post-update optional provisioning can warn but must not make a successful
  core update appear broken.
- Non-interactive update skips optional provisioning and prints exact follow-up
  commands.
- Source/dev update installs the selected release into the managed prefix while
  leaving `./ccb` in the checkout as live source.
- A current CCB release skips tarball reinstallation and still runs the
  requested provider update check.
- Default non-interactive update performs no provider prompt or provider
  mutation.
- Declining a provider update offers it again on the next `ccb update`;
  skipping records only the exact available version.
- A newer provider version clears the older muted-version state.
- npm updates use the npm executable adjacent to the resolved provider command
  when available and always pin the global prefix derived from the resolved
  package path, preserving user-prefix and NVM/version-manager ownership even
  when only a system npm executable is on `PATH`.
- A detected npm prefix that is not writable by the current user is reported
  without attempting an update or invoking privilege escalation.
- Bun global packages are updated with the Bun executable belonging to the
  detected Bun home, with that exact `BUN_INSTALL` preserved; the generic
  `node_modules` path check must not misclassify them as npm packages.
- A detected Bun home that is not writable by the current user is report-only.
- A registry release containing non-published local runtime dependencies is
  shown as available but report-only until the publisher replaces the release.
- Snap, Windows interop, custom wrapper, and unsupported native owners are
  reported without mutation.
- Successful provider updates are version-verified and do not automatically
  restart active panes.
- A transient provider-native latest-check failure is retried once, then
  reported without blocking the CCB update.
- New Claude/Gemini startup never creates the retired project-scoped Provider
  cache route.
- A real version update removes only stopped-current or manifest-valid
  deleted-project legacy caches. Active/current and other existing projects
  remain until their next successful `ccb kill`.
- Concurrent update windows serialize legacy cache migration; malformed,
  unknown, or symlinked content and the user-scoped Gemini cache are preserved.
- `--no-cache-cleanup` disables update-time migration without disabling the
  core or Provider update flow.
- Managed Claude uses the user installation and detaches only exact CCB-owned
  legacy cache links; foreign links are preserved.
- Managed Gemini uses one user-scoped npm/XDG cache without recursive
  `.../xdg/ccb/provider-cache/...` nesting.
- Default stopped-project cleanup removes only the current project's legacy
  Claude/Gemini cache; it does not scan other project buckets.
- Explicit orphan cleanup preserves existing projects and malformed or
  mismatched manifests, and removes only known Provider directories from a
  manifest-valid deleted-project bucket.
- Cleanup refuses while `ccbd` is active or ask work is pending.

Role Pack update:

- `current` Role Packs are not reinstalled or re-run through update hooks.
- `update_available` Role Packs update from the canonical catalog source.
- Legacy `ccb.archi` metadata is migrated or treated as an alias for
  `agentroles.archi`.
- Stale installed `source_path` values do not block catalog fallback.
- Project locks are not changed by install/update/sync unless the user runs an
  explicit adopt/add command.

Language:

- Prompts that ask the user to decide must be available in Chinese and English.
- Warning summaries and follow-up commands must be available in Chinese and
  English.
- Machine-readable tokens can remain stable ASCII, for example
  `roles_status: ok`.
