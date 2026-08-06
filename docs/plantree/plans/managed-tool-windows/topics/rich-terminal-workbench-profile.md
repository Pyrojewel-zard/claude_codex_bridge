# Rich Terminal Workbench Profile

Date: 2026-06-15

Related:

- [../roadmap.md](../roadmap.md)
- [neovim-system-optimization.md](neovim-system-optimization.md)
- [config-and-topology-contract.md](config-and-topology-contract.md)
- [../decisions/004-optional-rich-terminal-workbench.md](../decisions/004-optional-rich-terminal-workbench.md)
- [../decisions/005-rich-owns-neovim.md](../decisions/005-rich-owns-neovim.md)

## Purpose

Define an optional recommended CCB tool-workbench profile that combines
WezTerm, Yazi, and the CCB-managed LazyVim profile for users who want richer
project file browsing, Markdown rendering, PDF/page preview, image preview, and
video thumbnail preview.

This profile must not become a hard runtime dependency for CCB. The safe
default must keep working in plain terminals, tmux, SSH, WSL, and terminals
without an image protocol.

## User Intent

The desired personal workflow is a richer terminal workspace:

- `LazyVim` is the primary editor and Markdown authoring surface.
- `Yazi` is the project file browser and preview surface.
- `WezTerm` is the recommended rich-media terminal for image, PDF page, and
  video thumbnail preview.
- `tmux` and CCB continue to own project session/window lifecycle, but rich
  media is enabled only when the terminal path proves it can display it.

## Design Principle

Do not ask "which terminal does CCB require?"

Ask "which capabilities are available in this terminal path?"

The profile should be capability-gated:

- default-safe behavior everywhere;
- richer behavior in WezTerm, Kitty, Ghostty, or another verified image-capable
  terminal;
- explicit degraded behavior when the terminal or tmux path cannot render
  images reliably.

The user-facing workbench should be one bundle, not a loose checklist of
unrelated tools. A user should be able to install, enable, launch, disable, and
uninstall the bundle as a unit while CCB keeps generated configs and runtime
state under CCB-owned paths.

Neovim/LazyVim is part of this bundle. It is not a normal CCB feature and must
not be installed or updated by ordinary `ccb install` or `ccb update`.

## Bundle Semantics

`ccb-workbench-rich` is the product unit. It composes terminal launcher,
file-browser profile, editor profile, Markdown preview, PDF/video/image helper
tools, doctor output, and CCB-owned config projection.

The bundle includes:

- a terminal launcher policy, with WezTerm as the recommended rich terminal;
- a CCB-owned Yazi profile and wrapper;
- a CCB-owned LazyVim profile and wrapper;
- Markdown preview/rendering helpers shared by Yazi and Neovim where possible;
- PDF/video/image helper detection and generated previewer configuration;
- a manifest recording component versions, install roots, config roots, wrapper
  paths, helper tools, enabled state, and degraded reasons;
- lifecycle records for CCB-launched tool windows and WezTerm processes.

The bundle must be closed over configuration:

- do not modify `~/.config/yazi`, `~/.config/nvim`, `~/.config/wezterm`, or the
  user's tmux config;
- launch Yazi with `YAZI_CONFIG_HOME` or the equivalent generated profile path;
- launch Neovim with the managed LazyVim profile and CCB-owned XDG paths;
- launch WezTerm with a generated config file or explicit command-line config;
- add helper binaries through wrapper-local `PATH` only, not global shell files;
- make all generated paths discoverable through `doctor` and the bundle
  manifest.

## Public Lifecycle Boundary

The public lifecycle boundary is rich, not Neovim.

Normal CCB:

- does not install, update, or repair `ccb-nvim`;
- does not expose Neovim as a recommended normal tool command;
- may report that rich is missing when a config uses the `rich` alias.

Rich CCB:

- `ccb update rich` installs or updates the rich bundle;
- the rich bundle owns WezTerm integration, bundled Yazi where available,
  LazyVim/Neovim, Markdown rendering, PDF/image/video helpers, generated
  config, wrappers, and doctor output;
- `ccb rich` launches the already-installed rich bundle and should fail with a
  clear instruction when the bundle is missing;
- `ccb rich-install` is not a compatibility alias; the single install/update
  entry is `ccb update rich`.

## Dependency Encapsulation Contract

The rich bundle should minimize system mutation.

`ccb update rich` dependency order:

1. Prefer CCB-owned binaries under `$XDG_DATA_HOME/ccb/tools/workbench/bin`.
2. Validate downloaded binaries before marking them installed.
3. Use the platform package manager only for dependencies that are not safely
   bundled yet, or as a fallback when a bundled binary is unavailable or
   incompatible.

Current bundled binary contract:

- Yazi/ya are downloaded from the official Yazi GitHub release assets when
  `CCB_RICH_DOWNLOAD_BINARIES` is not false.
- Linux x86_64/aarch64 prefer `unknown-linux-musl` assets before GNU assets so
  older stable distributions do not fail on newer glibc requirements.
- Downloaded `yazi` and `ya` must pass `--version` validation before they are
  copied into the CCB workbench `bin` directory.
- A failed bundled Yazi install must remove invalid CCB-owned binaries so
  dependency detection can fall back to a system `yazi` or package manager
  install instead of treating a broken binary as available.
- `CCB_RICH_DOWNLOAD_BINARIES=0` disables bundled binary download.

Current package-managed dependency contract:

- WezTerm, Poppler, FFmpeg, image helpers, Markdown helpers, and fonts can
  still be installed through apt/dnf/yum/pacman/zypper/apk/Homebrew when
  missing.
- Yazi remains package-managed only as fallback when a bundled binary is
  skipped, unsupported, or fails validation.
- `CCB_RICH_INSTALL_DEPS=0` disables package-manager installation.

WSL terminal contract:

- When running under WSL, rich launchers prefer Windows-native `wezterm.exe`
  from `CCB_WORKBENCH_WEZTERM_EXE`, `PATH`, or common Windows install paths.
- Windows WezTerm launches `wsl.exe --cd "$PWD" -- env ...` so the visible
  terminal is native Windows, while `ccb-workbench`, Yazi, preview helpers, and
  provider commands continue running inside the current Linux distro.
- If the current shell is already inside a CCB-managed rich WezTerm session,
  the launcher may reuse that process with `wezterm cli spawn`.
- If the current shell is inside a user/global WezTerm that was not launched by
  the CCB rich bundle, the launcher must still start a new WezTerm window with
  the generated CCB config so managed IME, font, theme, and preview settings do
  not depend on user-global WezTerm state.

## WezTerm Visual Encapsulation

The rich bundle owns WezTerm visual defaults through its generated
`profiles/wezterm/wezterm.lua`. The launcher must use that file via
`wezterm --config-file ...` and must not rely on, merge with, or mutate the
user's global `~/.wezterm.lua`.

Current visual contract:

- use `wezterm.config_builder()` when available;
- enable managed-config reload so CCB theme changes apply, while disabling
  WezTerm update prompts for the managed workbench profile;
- set compact workbench geometry with `initial_cols = 132`,
  `initial_rows = 38`, and tight window padding;
- keep tab chrome simple with `use_fancy_tab_bar = false` and
  `hide_tab_bar_if_only_one_tab = true`;
- default to the quiet CCB dark workbench palette and expose only the complete
  CCB-owned presets selected by `ccb theme` or **Appearance** in
  `ccb config ui`; presets include ANSI/bright colors, and user-global WezTerm
  themes never leak into CCB rich windows;
- support an explicit `system` selection that maps OS dark/light appearance to
  the CCB dark/latte palettes through `wezterm.gui.get_appearance()`;
- launch with `start --always-new-process --no-auto-connect --cwd "$PWD"` so
  old WezTerm GUI/mux state does not silently reuse user-global or stale rich
  config, and the project directory remains the cwd authority;
- launch the CCB-owned GUI in a new process session with stdin, stdout, and
  stderr detached from the invoking shell. A long-lived WezTerm process must
  not retain the parent TTY, write GUI diagnostics into `cmd`, receive its
  foreground job-control signals, or cause unrelated stopped shell jobs to be
  resumed or signalled;
- on Linux Wayland, provision a private XCursor compatibility asset and prepend
  a CCB-owned overlay to `XCURSOR_PATH`. The overlay supplies WezTerm's missing
  `hand` name for the currently selected `XCURSOR_THEME`; it must not replace
  that theme, force XWayland, or edit `~/.icons`, system icon themes, or desktop
  settings;
- never pass `-n` / `--skip-config` with `--config-file`.

Current font contract:

- main font: `JetBrains Mono`;
- fallback stack: `Fira Code`, `Noto Sans Mono`,
  `Noto Sans Mono CJK SC`, `Symbols Nerd Font Mono`, `Symbols Nerd Font`,
  `Apple Color Emoji`, `Segoe UI Emoji`, `Noto Color Emoji`, and `monospace`;
- use family-only fallback entries rather than pinning
  `weight = "Regular"` so WezTerm can resolve bold and italic faces correctly;
- disable terminal ligatures with `calt=0`, `clig=0`, and `liga=0` for
  predictable code/path/prompt rendering;
- set `font_size = 10.5`, `line_height = 1.05`, `cell_width = 1.0`, and a
  smaller window-frame font.

Current tmux visual contract:

- rich/tool panes participate in active window border coloring, not only agent
  panes;
- the CCB pane border hook must be installed on the project tmux session so
  focus changes apply the active pane's `@ccb_active_border_style`;
- `pane-border-lines = heavy` is applied where supported, giving rich/tool
  split lines the same visible focus treatment as provider panes;
- all tmux settings remain project/session/window scoped and must not edit user
  global tmux configuration.

The bundle lifecycle is atomic at the CCB product level. Installing the bundle
prepares all required wrappers and configs; enabling it records the desired
workbench profile; launching it starts the CCB-owned tool windows; disabling it
closes or detaches only CCB-owned workbench windows and marks the profile
disabled. Disabling must not kill provider panes, agent sessions, user-created
WezTerm windows, or user files.

Individual preview capabilities can still degrade inside the bundle. For
example, Markdown preview should continue when PDF image preview is unavailable.
The boundary is: the bundle is managed as one unit, while rich surfaces are
capability-gated inside that unit.

## Capability Tiers

### Tier 0: Safe Terminal

Examples:

- `xterm-256color`;
- generic tmux;
- SSH terminal;
- WSL terminal without verified image protocol;
- unknown terminal.

Behavior:

- Yazi is available for navigation.
- Markdown is rendered as formatted terminal text through a renderer such as
  Rich, Glow, or mdcat.
- PDF preview uses `pdfinfo` and `pdftotext` instead of page images.
- Video preview uses `ffprobe` metadata instead of thumbnails.
- LazyVim opens folders and renders Markdown, but images/PDF/video use external
  open or reveal commands.

### Tier 1: Rich Terminal Direct

Examples:

- WezTerm direct GUI session;
- Kitty direct GUI session;
- Ghostty direct GUI session when its graphics protocol path is detected.

Behavior:

- Yazi may use image-capable preview for PNG/JPEG/WebP/SVG where supported.
- Yazi may use Poppler plus image preview for PDF pages.
- Yazi may use FFmpeg plus image preview for video thumbnails.
- LazyVim may enable inline image support when Snacks and the terminal report
  support.
- Markdown remains rendered through the terminal Markdown renderer and/or
  LazyVim's `render-markdown.nvim`.

### Tier 2: Rich Terminal Through tmux

Examples:

- WezTerm plus tmux with passthrough verified;
- Kitty plus tmux with passthrough verified;
- Ghostty plus tmux if a reliable passthrough path is proven.

Behavior:

- Same target as Tier 1 only after CCB doctor confirms tmux passthrough.
- Before passthrough is confirmed, fall back to Tier 0.

## Recommended Profiles

### `ccb-yazi`

Default safe Yazi wrapper/profile.

Capabilities:

- project navigation;
- Markdown formatted text preview;
- PDF metadata/text preview;
- video metadata preview;
- no hard dependency on image protocols;
- no modification of the user's existing Yazi config.

Suggested dependencies:

- `yazi`, `ya`;
- `file`;
- `pdftotext`, `pdfinfo`;
- `ffprobe`;
- Markdown renderer: Rich, Glow, or mdcat.

### `ccb-yazi-rich`

Optional rich-media Yazi wrapper/profile.

Capabilities:

- all `ccb-yazi` behavior;
- a compact two-column layout that hides the parent-directory column and keeps
  the current-directory and preview columns at the default `4:3` proportion;
- image preview when terminal support passes;
- PDF page preview through Poppler image conversion;
- video thumbnail preview through FFmpeg;
- fallback to safe preview when terminal support fails.

Suggested dependencies:

- `pdftoppm`;
- `ffmpeg`;
- `ffprobe`;
- terminal image path: WezTerm/Kitty/Ghostty or verified tmux passthrough;
- safe fallback helpers that report metadata rather than emitting character-art
  image output in non-image-protocol terminals.

### `ccb-nvim` (Internal Rich Component)

Internal LazyVim wrapper/profile generated for the rich bundle.

Capabilities:

- isolated CCB-owned LazyVim profile;
- folder opening;
- in-buffer Markdown rendering when parser readiness passes;
- external open/reveal commands for images/PDF/video and URLs;
- inline image disabled unless terminal support is proven.

### `ccb-nvim-rich` (Internal Rich Mode)

Optional rich-media LazyVim mode.

Capabilities:

- all `ccb-nvim` behavior;
- Snacks image enabled only when terminal/tmux capability and helper readiness
  pass;
- fallback to external open/reveal when inline rendering is unavailable.

This can be a wrapper flag, environment variable, or generated profile variant.
The implementation should avoid duplicating the full LazyVim profile if a small
overlay can switch behavior safely.

### `ccb-workbench-rich`

Recommended personal bundle for rich terminal users.

Composition:

- WezTerm as the recommended terminal launcher;
- `ccb-yazi-rich` as a managed file-browser tool window;
- `ccb-nvim-rich` as the managed editor tool window;
- optional `lazygit` and `btop` tool windows in later slices;
- CCB provider panes remain separate from tool windows.

Lifecycle commands should target this bundle directly. The preferred public
entry is:

- `ccb update rich`.

Lower-level workbench diagnostics can remain available for implementation and
testing, for example:

- `ccb tools install workbench --profile rich`;
- `ccb tools doctor workbench --profile rich`;
- `ccb tools enable workbench --profile rich`;
- `ccb tools launch workbench`;
- `ccb tools disable workbench`;
- `ccb tools uninstall workbench --profile rich`.

The exact CLI grammar can change, but the contract should remain one user
intent and one CCB-owned bundle state, not separate manual setup steps for
WezTerm, Yazi, LazyVim, and Markdown preview.

## Doctor Surface

Add a terminal/workbench capability report before automatically enabling rich
media. This can be `ccb tools doctor terminal`, `ccb tools doctor workbench`,
or an extension of individual tool doctors.

Suggested fields:

- `terminal_program`: `wezterm`, `kitty`, `ghostty`, `tmux`, `unknown`;
- `terminal_direct_status`: `ok`, `unknown`, `degraded`;
- `terminal_image_protocol`: `ok`, `candidate`, `degraded`;
- `tmux_status`: `not_tmux`, `tmux_detected`, `passthrough_ok`,
  `passthrough_unknown`, `passthrough_failed`;
- `opener_status` and `opener_tool`;
- `markdown_renderer_status` and `markdown_renderer_tool`;
- `pdf_text_status`, `pdf_text_tool`;
- `pdf_image_status`, `pdf_image_tool`;
- `video_metadata_status`, `video_metadata_tool`;
- `video_thumbnail_status`, `video_thumbnail_tool`;
- `yazi_status`, `yazi_version`;
- `wezterm_status`, `wezterm_version`;
- `lazyvim_rich_status`.

Doctor checks must be read-only unless the command name explicitly says
`install`, `repair`, or `setup`.

## Configuration Model

Keep rich media opt-in explicit.

Candidate user-facing forms:

```toml
[tools.workbench]
profile = "safe"        # default
# profile = "rich"      # recommended for WezTerm/Kitty/Ghostty users

[tools.yazi]
enabled = true
profile = "safe"

[tools.neovim]
enabled = true
profile = "safe"
```

or:

```toml
[tool_windows.files]
preset = "yazi"
profile = "rich"

[tool_windows.editor]
preset = "neovim"
profile = "rich"
```

The exact grammar should align with
[config-and-topology-contract.md](config-and-topology-contract.md). The
important product contract is that a rich profile is requested explicitly, and
CCB may still degrade individual surfaces after doctor checks.

Bundle state should be stored separately from user dotfiles. A generated
manifest can use a shape like:

```toml
[bundle]
name = "workbench"
profile = "rich"
enabled = true

[components.wezterm]
status = "ok"
binary = "/usr/bin/wezterm"
config = ".../tools/workbench/wezterm/wezterm.lua"

[components.yazi]
status = "ok"
binary = ".../bin/yazi"
config_home = ".../tools/workbench/yazi"

[components.neovim]
status = "ok"
wrapper = ".../tools/neovim/bin/ccb-nvim"
profile = ".../tools/neovim/lazyvim/profile"

[renderers.markdown]
status = "ok"
tool = "rich"

[previews.pdf]
status = "degraded"
reason = "terminal image protocol unavailable"
fallback = "pdftotext"
```

This manifest is not proposed as the final schema; it captures the needed
ownership boundary: generated config, selected binaries, capability results,
and enabled state are CCB-owned and auditable.

## Atomic Lifecycle

Install:

- locate or provision required binaries and helpers;
- generate CCB-owned profiles for WezTerm, Yazi, LazyVim, and preview helpers;
- write the bundle manifest;
- run read-only doctor checks after provisioning.

Enable:

- record that the project or user selected the workbench bundle;
- make the bundle eligible for CCB-managed tool-window launch;
- do not start provider agents or mutate provider runtime authority.

Launch/use:

- start WezTerm only through the CCB wrapper when the rich launcher is selected;
- start Yazi and LazyVim with generated config homes;
- tag launched windows/processes so later disable/close only affects CCB-owned
  workbench surfaces.

Disable/close:

- close or detach CCB-owned workbench tool windows as a group;
- remove the desired active profile from project runtime state;
- leave installed binaries, caches, and generated configs intact unless the
  user asks for uninstall or cleanup;
- never close unrelated user WezTerm windows or CCB provider panes.

Uninstall/cleanup:

- remove generated bundle configs and wrappers owned by CCB;
- optionally preserve downloaded binary caches with `--keep-cache`;
- report any user-local or system package dependency that CCB did not install
  and therefore will not remove.

## Provisioning Model

Safe default provisioning:

- install or locate `yazi` and `ya`;
- generate CCB-owned Yazi profile paths;
- install or locate Markdown renderer;
- locate Poppler text tools and FFmpeg metadata tools;
- never overwrite `~/.config/yazi`.

Rich provisioning:

- locate or install WezTerm when requested, preferring Windows-native
  `wezterm.exe` under WSL when available;
- download and validate CCB-owned Yazi/ya binaries where feasible before using
  package managers;
- locate Poppler image tools such as `pdftoppm`;
- locate FFmpeg thumbnail support;
- locate terminal image support;
- optionally install helper tools such as `chafa` only as a fallback, not as a
  substitute for terminal image capability.

No provisioning step should require global dotfile edits. When system package
installation needs root privileges, the command should report exact
instructions or use user-local binaries where feasible.

## Local Prototype Evidence

Local exploratory setup on 2026-06-14 and 2026-06-15 validated the user-facing
shape:

- `yazi` and `ya` can run from `~/.local/bin`.
- Poppler tools on the test host:
  - `pdftoppm`;
  - `pdftotext`;
  - `pdfinfo`.
- FFmpeg tools on the test host:
  - `ffmpeg`;
  - `ffprobe`.
- Markdown preview can be routed through Yazi `piper` plus a Rich-based
  renderer.
- Safe Yazi PDF preview can use text extraction to avoid unreadable character
  image output in plain tmux.
- Safe Yazi video preview can use `ffprobe` metadata.
- WezTerm is available on the test host and can be used as the rich terminal
  candidate.

This evidence is local-prototype evidence, not shipped behavior.

## Landed First Slice

The first source implementation landed on 2026-06-15. See
[../history/workbench-bundle-slice-2026-06-15.md](../history/workbench-bundle-slice-2026-06-15.md).

Implemented:

- `ccb tools doctor/install/update/enable/launch/disable/uninstall workbench`
  with `--profile safe|rich` parsing.
- `ccb update rich` as the installer/updater/enabler for the recommended rich
  profile.
- Independent CCB-owned workbench root under
  `$XDG_DATA_HOME/ccb/tools/workbench`.
- CCB-owned Yazi safe and rich profiles, with generated piper-compatible
  preview plugin.
- Generated Markdown, PDF text, and video metadata preview helpers.
- Generated WezTerm config and `ccb-workbench` launcher wrapper, including the
  family-only font stack, compact geometry, quiet theme, isolated
  `--config-file` launch, and `--always-new-process --no-auto-connect`.
- JSON manifest with schema version, component statuses, generated paths,
  enabled state, and degraded reasons.
- Rich/tool tmux pane styling participates in active border coloring, and CCB
  applies `pane-border-lines = heavy` where supported.
- Unit tests and live Linux/tmux source-wrapper validation from
  `/home/bfly/yunwei/test_ccb2`.
- `rich` as a reserved `[windows]` layout alias that starts
  `CCB_WORKBENCH_PROFILE=rich CCB_WORKBENCH_FORCE_RICH=1 ccb-workbench files`
  as a CCB-owned tool pane without creating an agent. See
  [../history/rich-layout-alias-slice-2026-06-15.md](../history/rich-layout-alias-slice-2026-06-15.md).
- Binary-first rich dependency hardening: CCB-owned Yazi/ya release download,
  Linux musl preference, executable validation, invalid-binary cleanup,
  package-manager fallback, status output for binary install results, and WSL
  Windows-native WezTerm launch routing. See
  [../history/rich-binary-dependency-slice-2026-06-15.md](../history/rich-binary-dependency-slice-2026-06-15.md).

Not yet implemented:

- Broader direct GUI WezTerm validation outside tmux across multiple hosts.
- Platform-specific GUI close hardening beyond recorded launch PIDs.
- macOS and additional WSL GUI validation.

## Implementation Slices

1. Terminal capability doctor:
   - detect WezTerm/Kitty/Ghostty/tmux/unknown;
   - detect direct image protocol candidates and tmux passthrough state;
   - expose machine-readable degraded reasons.
2. Workbench bundle manifest and lifecycle:
   - define install/doctor/enable/launch/disable/uninstall states;
   - track CCB-owned config roots and launched tool-window/process records;
   - ensure disable affects the whole bundle but not provider panes or
     user-created terminal windows.
3. Yazi safe profile:
   - add `ccb tools install/doctor yazi`;
   - generate isolated `ccb-yazi` profile;
   - add Markdown formatted preview;
   - add PDF text preview;
   - add video metadata preview.
4. Yazi rich profile:
   - add `ccb-yazi-rich`;
   - use default image/PDF/video preview only when terminal capability passes;
   - fall back to safe preview otherwise.
5. Workbench preset:
   - define recommended config for `neovim` plus `yazi`;
   - define the WezTerm launcher as part of the rich bundle, not a loose
     external prerequisite;
   - optionally add `lazygit` and `btop` later;
   - ensure tool windows still do not become agents.
6. LazyVim rich mode:
   - align Neovim image/PDF/video fallback behavior with terminal doctor;
   - keep Markdown rendering in the safe default.
7. Cross-platform validation:
   - Linux X11 direct WezTerm;
   - Linux tmux;
   - macOS WezTerm or Ghostty;
   - WSL home and WSL mounted-drive cases;
   - SSH or unknown terminal degraded behavior.

## Acceptance Criteria

- A user can opt into a recommended rich workbench without editing personal
  Yazi, Neovim, WezTerm, or tmux dotfiles.
- A user can install, enable, launch, disable, and uninstall the workbench as a
  single CCB-owned bundle.
- Disabling the bundle closes or detaches CCB-owned Yazi/LazyVim/WezTerm
  surfaces together without touching provider panes or user-created terminal
  windows.
- Doctor output can explain every generated config root, selected binary, and
  degraded preview surface from the bundle manifest.
- The safe profile works in ordinary tmux and does not produce unreadable
  character-image output for images, PDF, or video by default.
- The rich profile enables page/thumbnail/image preview only where terminal
  support is detected or explicitly requested.
- Markdown preview works in both safe and rich Yazi profiles.
- LazyVim and Yazi share the same terminal capability truth instead of making
  independent optimistic assumptions.
- Missing optional dependencies degrade individual surfaces, not the whole tool
  window or CCB project.
- Tool windows remain outside agent/provider runtime, ask routing, completion
  detection, and Comms.

## Risks

- Terminal image support differs substantially across WezTerm, Kitty, Ghostty,
  tmux, SSH, and WSL.
- Yazi, Snacks, and terminal graphics behavior can drift across upstream
  versions.
- Local prototype behavior can be misleading if it uses personal dotfiles; CCB
  must validate generated isolated profiles.
- User-local binary provisioning can create PATH confusion if not surfaced by
  doctor output.
- Rich media helpers can be expensive on large PDFs or videos; previewers need
  reasonable limits.
- Closing a GUI terminal is more sensitive than closing a tmux pane; CCB must
  only target windows/processes it launched and recorded.
- A partially failed bundle install can be confusing unless required components,
  optional preview helpers, rollback state, and cleanup behavior are explicit.
