# CCB UI Theme Preference

Date: 2026-06-26

## Purpose

Define a single user-facing theme command for CCB-owned UI surfaces:

```text
ccb theme
ccb theme +
ccb theme -
ccb theme system
ccb theme light
ccb theme dark
```

The theme preference is global user state, not project `.ccb/ccb.config`
state. Users may open different projects in different terminals, but the
preference is still a CCB user preference and should not drift per project
unless a later explicit project override is designed.

## Product Boundary

For ordinary terminals, `ccb theme` changes only CCB's own UI:

- tmux status bar;
- tmux pane borders and pane labels;
- sidebar palette;
- CCB CLI color tokens where applicable.

It must not rewrite user terminal configuration for WezTerm, Kitty, Ghostty,
Alacritty, macOS Terminal, or another emulator. Users keep ownership of their
terminal dotfiles and can choose the CCB theme that best matches them.

For the CCB-owned rich WezTerm bundle, `ccb theme` also drives the generated
WezTerm theme because that profile is owned by CCB and launched with an
isolated `--config-file`. Every selectable theme resolves to a complete
CCB-owned palette, including ANSI and bright colors; it never imports or
merges the user's global WezTerm theme.

`ccb config ui` exposes the same user preference under **Appearance**. This is
an explicit user-preference exception to the panel's normal project-config
write boundary: the endpoint may write only `theme.json` through the shared
theme service and may not write another user-global file.

## Storage Authority

Store the selected theme under user config, not workbench-private state:

```text
$XDG_CONFIG_HOME/ccb/theme.json
```

Fallback when `XDG_CONFIG_HOME` is unset:

```text
~/.config/ccb/theme.json
```

Shape:

```json
{
  "schema_version": 1,
  "theme": "light",
  "palette": "latte",
  "tmux_profile": "light"
}
```

`theme` is the public semantic name. `palette` is the CCB-owned rich WezTerm
palette key. `tmux_profile` is the coarse CCB/tmux profile consumed by tmux
and sidebar logic.

System-following shape:

```json
{
  "schema_version": 1,
  "theme": "system",
  "palette": "system",
  "tmux_profile": "system"
}
```

The stored `system` values preserve intent. Runtime consumers resolve them to
the effective CCB `dark`/`latte` palette and `default`/`light` tmux profile.
They do not copy a system terminal application's color scheme.

The persisted preference is authoritative. Theme profile environment variables
are launch-time bootstrap values for processes that have no readable
`theme.json`; a value inherited from an older daemon or terminal must not
override a newer saved preference.

## Theme Set

Primary public themes:

- `system`
- `dark`
- `light`

Additional accepted aliases may map to richer palettes:

- `solarized`
- `tokyo`
- `gruvbox`
- `rose-pine`

`ccb theme +` cycles through the supported set. `ccb theme -` cycles backward.
The command output should show the semantic theme, rich palette, tmux profile,
effective theme/palette/profile, and config path so support/debugging remains
straightforward without exposing workbench internals as the primary UX.

## Runtime Behavior

When `ccb theme <value>` runs:

1. Normalize `<value>` or cycle from the current saved preference.
2. Write `theme.json`.
3. Resolve `system` from the operating-system light/dark preference. WezTerm
   uses `wezterm.gui.get_appearance()`; Python consumers use platform settings
   with a dark fallback for headless/unknown environments.
4. If running inside tmux, update the tmux environment and reapply the CCB
   tmux UI with the effective `tmux_profile`.
5. The sidebar rechecks `theme.json` on its normal ProjectView refresh and
   updates its palette without treating its launch-time environment as
   persistent authority.
6. If running inside CCB rich WezTerm, rely on the generated WezTerm config
   watching `theme.json` and reloading the CCB-owned WezTerm palette.
7. If not running inside rich WezTerm, do not mutate terminal emulator config.
   The rich WezTerm palette will apply next time the rich bundle is launched.
8. Generated workbench launchers read `theme.json` before inherited
   `CCB_WORKBENCH_THEME` or `CCB_TMUX_THEME_PROFILE` values, so a terminal
   opened before the preference changed cannot overwrite the new choice.

The old `ccb-workbench theme ...` surface should not be public. The public
entry is `ccb theme ...`; the workbench wrapper may consume the same
preference internally.

## Acceptance Criteria

- `ccb theme` works outside a CCB project and does not require `.ccb`.
- `ccb theme light` makes current CCB tmux/sidebar surfaces light when inside
  tmux.
- `ccb theme dark` restores the dark CCB/tmux profile and clears stale light or
  contrast window styles where needed.
- `ccb theme system` follows OS appearance while retaining CCB-owned dark/light
  palettes, with explicit selected and effective values in diagnostics.
- `ccb config ui` lists all supported themes, saves through the token-guarded
  local `/api/theme` endpoint, and follows browser system appearance when the
  saved selection is `system`.
- In CCB rich WezTerm, generated `wezterm.lua` reloads from `theme.json`.
- Rich WezTerm defines foreground/background, cursor, selection, tab, ANSI,
  and bright colors for every preset.
- In ordinary terminals, CCB never writes user terminal dotfiles.
- `ccb update rich` preserves the current theme preference and regenerates a
  config that follows it.

## Verification

- Unit tests for theme normalization, persistence, and cycle behavior.
- Entry-point tests proving `ccb theme` routes before project discovery.
- Workbench tests proving generated WezTerm config watches `theme.json`.
- tmux UI tests proving stale window styles are cleared when switching to a
  profile without explicit window styles.
- Source-wrapper validation from `/home/bfly/yunwei/test_ccb2` using
  `/home/bfly/yunwei/ccb_source/ccb_test`.

## Landing Evidence

2026-06-26 implementation slice:

- Added public `ccb theme` handling before project discovery.
- Added user-level theme preference storage at
  `$XDG_CONFIG_HOME/ccb/theme.json`.
- Made tmux theme selection treat the saved preference as authoritative and
  environment values as bootstrap fallback only.
- Made generated rich WezTerm config watch and parse `theme.json`.
- Removed the temporary public `ccb-workbench theme` path from the generated
  wrapper; workbench now consumes the global preference internally.
- Verified with:
  - `python -m py_compile lib/terminal_runtime/ui_theme.py lib/cli/services/theme.py lib/cli/tools_runtime/workbench.py lib/terminal_runtime/tmux_theme.py lib/cli/entrypoint_runtime.py`
  - `python -m pytest -q test/test_ui_theme_preference.py test/test_v2_cli_router.py test/test_cli_tools_workbench.py test/test_tmux_identity.py test/test_v2_tmux_ui.py`
  - `HOME=/home/bfly/yunwei/test_ccb2/source_home CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home /home/bfly/yunwei/ccb_source/ccb_test theme light`
  - `HOME=/home/bfly/yunwei/test_ccb2/source_home CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home CCB_RICH_DOWNLOAD_BINARIES=0 CCB_RICH_INSTALL_DEPS=0 /home/bfly/yunwei/ccb_source/ccb_test update rich`
  - `wezterm --config-file /home/bfly/yunwei/test_ccb2/source_home/.local/share/ccb/tools/workbench/profiles/wezterm/wezterm.lua ls-fonts`
