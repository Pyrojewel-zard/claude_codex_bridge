# Sidebar Config Entry

Date: 2026-07-10

## Goal

Expose the config UI from the native sidebar after `ccb config ui` exists and
works independently.

## Desired UI

The top-right sidebar tree controls should remain icon-only:

```text
⚙ ×
```

- `⚙`: open config UI.
- `×`: project-level kill.

The old header `↻` action is intentionally replaced, not moved. Restarting all
configured panes is too disruptive for a prominent click target. Keyboard `r`
remains the deliberate restart path for experienced users.

Do not add visible `r`, `q`, or text buttons to the sidebar chrome.

## Launch Behavior

First implementation can spawn the sibling `ccb` binary:

```bash
ccb --project <project_root> config ui
```

The sidebar helper must not block the TUI while the UI command is running. The
landed implementation spawns the sibling `ccb` command with the current project
root and reports a concise launch error in the sidebar when process creation
fails.

Later implementation may route through a daemon RPC if launch status,
single-instance behavior, or richer diagnostics are needed.

## Fallback Behavior

If automatic browser opening fails, the config UI command should print or return
the local URL. The sidebar should surface enough text for the user to copy it,
for example:

```text
config ui: http://127.0.0.1:49231/?token=...
```

The cross-platform launch path must not treat successful process creation as
proof that a browser opened. On WSL it tries the host-browser path first
(`wslview`, `cmd.exe`, then `explorer.exe`) before a Linux desktop fallback; on
macOS it prefers `open`. Each native opener is checked for an immediate
non-zero exit before the next fallback is attempted. The tmux namespace also
refreshes `BROWSER`, desktop-session IPC, and WSL/Windows Terminal variables so
the sidebar child receives the same browser transport context as the user's
shell.

If every opener fails, the CLI emits `browser_open: failed` and the sidebar
shows an explicit `open manually` warning together with the loopback URL rather
than presenting the session as an ordinary successful browser launch.

## Safety

- The sidebar button launches only the same local config editor command.
- It must not write config directly.
- It must not run reload or restart the project.
- `×` behavior remains unchanged.
- Keyboard `r` remains available for deliberate pane restart.

## Test Targets

- Header control hit testing with two controls.
- Config icon spawns the expected command without blocking.
- Spawn failure displays a sidebar error.
- WSL and macOS choose their host-native opener before generic browser
  discovery, and a non-zero native opener falls through to the next choice.
- Desktop/WSL browser transport variables survive the tmux namespace boundary.
- Browser-open failure remains visible with the ready loopback URL.
- The settings click cannot call `project_restart_panes`.
- Existing keyboard restart and kill behavior remain available.
- No keyboard shortcut labels appear in the sidebar header.

## Landed Evidence

Date: 2026-07-10

- Rust sidebar unit suite: `74 passed`.
- Python config UI/parser/phase2 focused suite: `9 passed`.
- Real source-wrapper launch from `/home/bfly/yunwei/test_ccb2` served the page
  on a random loopback port, returned project-scoped session metadata, and
  rejected a request without the launch token with HTTP `403`.

Date: 2026-07-22

- Rust sidebar suite: `79 passed`, including explicit browser-open fallback
  status parsing.
- Config UI suite: `15 passed`; namespace environment suite: `16 passed`;
  focused phase2 config UI entrypoint: `1 passed`.
- WSL and macOS opener selection is platform-simulated in unit tests, including
  generic-browser false positives, native opener non-zero exit, and delayed
  opener reaping.
- A real source-wrapper launch from `/home/bfly/yunwei/test_ccb2` again emitted
  the URL through a pipe, served the token-authorized project session, returned
  HTTP `403` without the token, and shut down cleanly.
