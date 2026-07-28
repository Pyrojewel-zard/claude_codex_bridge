# Install Update Flow

Date: 2026-06-04

## Fresh Install

Fresh install is owned by `install.sh install`.

Required flow:

1. Detect language with `CCB_LANG`, `LANG`, `LC_ALL`, or `LC_MESSAGES`.
2. Confirm root/sudo profile if effective uid is root.
3. Refuse temporary-prefix installs that would write wrappers into an external
   bin directory, unless explicitly overridden.
4. Check WSL compatibility and backend environment.
5. Select Python 3.10+.
6. Install required or optional Python packages only when missing.
7. Check terminal backend requirements.
8. Prepare install tree:
   - source/dev mode uses a live source root
   - release mode copies release content to the install prefix
9. Create managed venv when policy says to use one.
10. Write install metadata for release installs.
11. Install wrappers and bin links.
12. Run real installed entrypoint smoke checks.
13. Install inherited skills, settings, tmux helpers, and other static assets.
14. Provision optional Role Packs and tools.
15. Print install identity and next actions.

Core install success stops at step 13. Role Pack and tool provisioning are
post-install checks unless the user explicitly forces them as required.

## Managed Update

Managed update is routed by Python `ccb update`, but mutation authority depends
on install provenance.

For an npm install, the outer `@seemseam/ccb` package owns the vendored release:

1. The npm runner passes the package name, root, and manifest version to the
   Python child on every invocation.
2. Python accepts npm provenance only when the outer `package.json` matches and
   the executing release is below that package's `.ccb-release` directory.
3. npm `postinstall` downloads the manifest-pinned release and calls only the
   release installer's restricted `runtime-bootstrap` command. That command
   creates and validates `.ccb-release/<platform>/.venv`; it must not install
   global wrappers, skills, settings, tmux assets, tools, or Role Packs.
4. The npm runner validates the release-local managed Python before launching
   CCB and repeats the same idempotent bootstrap under the package install lock
   when postinstall was interrupted, disabled, or left an unhealthy runtime.
5. A vendored payload is complete only when `VERSION` exactly matches the outer
   manifest, the `ccb` entrypoint is executable, and the managed Python can
   import CCB's required TOML, Mobile, and Relay dependencies.
6. `ccb update` prints `npm install -g @seemseam/ccb@<target>` and does not
   download, extract, install, or relaunch a vendored payload.
7. Startup update acceptance prints the same command and defers the current
   prompt window without reporting a successful in-place update.
8. The npm runner continues requiring exact equality between the manifest
   version and vendored `VERSION`; equality is safe because only npm mutates
   that payload.

For release-package and source/dev installs, the transactional tarball path is:

Required flow:

1. Resolve supported platform and target version.
2. Download the matching release artifact.
3. Extract to a temporary staging root.
4. Run the staged release `install.sh install` with optional provisioning
   disabled:
   - `CCB_INSTALL_ROLES=0`
   - `CCB_INSTALL_NEOVIM=0`
5. Verify the newly installed entrypoint and read new build metadata.
6. Print update outcome.
7. Run post-update provisioning through the newly installed `ccb`, not through
   the old updater process.
8. Check installed provider CLIs once through the explicit update flow:
   - default TTY mode prompts only when a newer provider version exists
   - `--providers check` reports without mutation
   - `--providers all` explicitly updates all safely managed candidates
   - `--providers none` disables the check for that run
   - non-interactive default mode never prompts or performs provider network
     checks
9. Run the bounded retired-cache migration:
   - one user-level lock deduplicates simultaneous update windows
   - a stopped current project may be cleaned under its startup lock
   - active/current and other existing projects are deferred to their next
     successful `ccb kill`
   - only per-Provider manifest-valid buckets whose recorded project root no
     longer exists are removed cross-project
   - `--no-cache-cleanup` skips the migration for that update
10. Report optional provisioning warnings without making the core update look
   failed unless the user forced required provisioning.

The key boundary is step 7. Once release files are installed, Role Pack and
tool semantics belong to the new release. The old updater process should only
bootstrap the new post-update runner.

Update does not perform an unverified recursive cache purge. The newly
installed runner may delete the stopped current project's retired
Claude/Gemini cache under its project startup lock. Its cross-project scan
deletes only known Provider directories with their own schema-v1 manifest,
matching absolute project root and recomputed project id, and a recorded root
that no longer exists. Other existing projects are deferred, not stopped; the
new release removes their retired cache after their next successful
`ccb kill`. The explicit maintenance equivalent remains:

```text
ccb cleanup --legacy-provider-caches
```

That broader mode must verify the cache manifest, absolute recorded project
root, recomputed project id, and non-existence of the recorded root before
deleting only the known Claude/Gemini directories.

Unknown Provider entries, malformed or symlinked manifests, Provider-directory
symlinks, foreign Claude links, session/auth state, and the user-scoped Gemini
cache are preserved. Automatic migration avoids a separate recursive byte-size
walk for very large caches. It records its bounded result under
`$XDG_STATE_HOME/ccb/provider-cache-cleanup.json`, falling back to
`~/.local/state/ccb/provider-cache-cleanup.json`.

## Post-Update Runner

The post-update runner should be a CLI entrypoint in the newly installed CCB,
for example an internal command such as:

```text
ccb __post-update --from-version <old> --to-version <new>
```

Responsibilities:

- Refresh or locate the `agent-roles-spec` catalog.
- Canonicalize legacy Role Pack ids before status comparison.
- Refresh installed Role Packs only when source version or digest changed.
- Skip Role Pack updates when status is already `current`.
- Install newly available Role Packs only after interactive confirmation.
- Provision Neovim only when requested or accepted.
- Run provider update discovery only when the parent `ccb update` explicitly
  authorizes the internal provider-update flow.
- Resolve provider executables from the real user environment, identify npm,
  Bun, Homebrew, native, Snap, or custom-wrapper ownership, and update only
  when a safe owner-specific command exists.
- For npm-owned providers, derive the global install prefix from the resolved
  package path and pass that exact prefix to npm. A system npm executable must
  not redirect a user-prefix Provider into `/usr/local`; a non-writable
  detected prefix is report-only with an actionable ownership message.
- Treat packages under `<BUN_INSTALL>/install/global/node_modules` as
  Bun-owned rather than npm-owned. Use the matching Bun executable, preserve
  the detected `BUN_INSTALL` during execution, and keep a non-writable Bun home
  report-only.
- Treat an npm registry release that declares `file:`, `link:`, or `workspace:`
  runtime dependencies as non-installable from the registry. Report that exact
  version without executing npm or Bun, so a malformed upstream publication
  cannot repeatedly damage an existing Provider installation.
- Use a provider-native read-only latest check only when the CLI exposes a
  documented non-mutating check (currently `droid update --check`); never run
  a mutating updater merely to discover whether an update exists.
- Persist decline/update evidence and exact muted provider versions under
  `$XDG_STATE_HOME/ccb/provider-updates.json` (falling back to
  `~/.local/state/ccb/provider-updates.json`). A muted version becomes
  promptable again when the registry reports a newer version.
- Verify the installed provider version after every accepted update. Never
  restart active provider panes automatically.
- Run retired-cache migration only when authorized by the parent update
  process; serialize it with a user-level stale-owner-aware lock, keep cleanup
  failures non-blocking, and skip it when required post-update failure will
  roll the release back.
- Emit bilingual summary and remediation messages.

Provider update failures are optional provisioning warnings. They must not
roll back a successfully installed CCB release. CCB must not invoke `npm
install -g` merely because a provider name is known: npm management is allowed
only when the resolved executable itself is owned by the detected global npm
package. Snap, WSL Windows-interop, and custom-wrapper installations are
report-only unless a separate safe adapter exists.

## Failure Classification

Failures must be separated:

- blocking core update failure:
  download failed, extraction unsafe, installer failed, installed entrypoint
  smoke check failed
- non-blocking optional provisioning warning:
  catalog unavailable, Role Pack tool install failed in optional mode, Neovim
  unavailable in optional mode, Droid registration failed
- required provisioning failure:
  user set a force/required env var and the dependency failed

User output should make this distinction explicit. A successful core update
with optional Role Pack warning should say the update completed and then show
the optional warning plus retry command.

## Current Known Drift

The v7.2.9 incident showed that old updater code can continue after installing
new files and try to update a legacy `ccb.archi` source that no longer exists.
Moving post-update provisioning into the new installed entrypoint prevents this
class of old-code/new-layout mismatch.

Issue 268 exposed a separate ownership collision: in-place tarball update of an
npm-vendored release changed only its inner `VERSION`; the next npm invocation
then correctly restored the manifest-pinned payload. Package provenance and
npm delegation remove that competing writer rather than weakening the runner's
version check.

The 2026-06-15 stable-entrypoint audit found a separate drift class: a
temporary release simulation prefix under `/tmp/ccb-v7.2.1-install-smoke` was
left as the user's bare `ccb` authority. The real `~/.local/bin/ccb` symlink
pointed into that temporary prefix, and multiple live project daemons were
running from the same prefix. Install/update validation must therefore prove
that isolated `CODEX_INSTALL_PREFIX` and `CODEX_BIN_DIR` runs cannot mutate the
real user wrapper or persistent shell startup files unless that real install is
the explicit target.

Closed for direct shell installs on 2026-06-15: `install.sh install` now fails
before preparing the install tree when `CODEX_INSTALL_PREFIX` is temporary and
`CODEX_BIN_DIR` is outside the same temporary prefix or temporary HOME. Use
`CCB_ALLOW_TEMP_INSTALL_GLOBAL_BIN=1` only when intentionally writing from a
temporary install prefix into an external bin directory.
