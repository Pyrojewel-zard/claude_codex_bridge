# Decision 008: Permissive Baseline Until AGPL Approval

Date: 2026-06-18
Status: Accepted for Batch 1; superseded for Provider control by Decision 025
Depends on: [Decision 005](005-native-flutter-tmux-first-client.md),
[Decision 007](007-native-baseline-before-ccb-gateway.md)

## Decision

Until the user explicitly accepts an AGPL mobile app component, Batch 1 will
start from a small permissive Flutter source baseline under `app/` and will
not copy or fork ServerBox or Paseo source.

ServerBox and Paseo remain active references. MuxPod, tmux-mobile, ConnectBot,
ttyd, and package dependencies with compatible licenses can be reused or
adapted when their exact source files, licenses, and attribution requirements
are recorded.

## Rationale

The current goal requires progress toward implementation and prefers
open-source reuse over greenfield work. The main unresolved license risk is
direct reuse of AGPL mobile app source. A permissive baseline avoids blocking
model, fixture, repository, and socket-aware tmux command work while preserving
the option to fork ServerBox later.

The first Batch 1 artifacts are mostly CCB-specific:

- CCB data models;
- fake ProjectView fixtures;
- transport/repository boundaries;
- socket-aware tmux command builder;
- tests that reject pane-id-only terminal targets.

These are valuable regardless of whether the final UI shell is a ServerBox
fork or a smaller Flutter app.

## Consequences

- No AGPL source is imported into `app/` during Batch 1.
- The first app scaffold may still depend on permissive pub packages such as
  `xterm`, `dartssh2`, `flutter_secure_storage`, and `flutter_riverpod`.
- ServerBox remains the preferred fork candidate if AGPL is later accepted.
- MuxPod remains the primary tmux UX and command-strategy reference.
- The app architecture must keep module boundaries compatible with a later
  fork or code import.

## Validation Path

This decision is validated when Batch 1 lands:

1. `app/` contains CCB-first models, fake repository, fixture, and tmux command
   builder code.
2. Tests prove `pane_id` alone cannot authorize terminal input.
3. Tmux command tests generate socket-aware attach/paste commands.
4. No ServerBox or Paseo source files are copied into `app/`.
5. Plan tree records any copied or adapted open-source source files before
   they are committed.
