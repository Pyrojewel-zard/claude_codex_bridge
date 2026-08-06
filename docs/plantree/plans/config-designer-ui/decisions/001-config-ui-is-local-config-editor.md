# Config UI Is A Local Config Editor

Date: 2026-06-06

## Context

CCB configuration has grown enough that a menu-style skill and optional visual
editor would help users discover supported fields. At the same time, CCB already
has clear authority boundaries: `.ccb/ccb.config` owns project config, memory
files own workflow context, and `ccbd` owns runtime state.

## Decision

The config UI will be a local, optional editor for `.ccb/ccb.config`. It will be
launched by CLI, bind only to `127.0.0.1`, validate through the existing config
loader, and write only after preview and confirmation.

The UI and `ccb-config` skill will not edit workflow memory, provider-state
homes, installed role stores, or runtime records during ordinary config work.

The panel may also expose the global CCB Appearance preference as a narrowly
scoped exception. That control writes only
`$XDG_CONFIG_HOME/ccb/theme.json` through the same service as `ccb theme`; it
does not add theme fields to project TOML and does not read or write user
terminal-emulator configuration.

The sidebar may expose a config icon, but that icon will launch the same config
UI command instead of becoming a second configuration authority.

## Consequences

- Config remains file-backed and reviewable.
- User appearance remains separately file-backed and global; it cannot drift
  into a project config slot.
- The browser UI can be added without making `ccbd` a web server.
- Sidebar integration can stay thin and optional.
- Workflow memory remains a separate explicit user request.
- Future remote or shared configuration tools would need a separate decision.
