# Pi Session History Recovery

## Feature Overview

CCB keeps its launch identity (`ccb_session_id`) separate from Pi's native
conversation identity. A managed Pi launch records the native JSONL session
id and path from the `extension_ready` event emitted at `session_start`.

## Supported Flow

- A restore launch selects the exact validated `--session <jsonl-path>`.
- A fresh launch, `--new-context`, and explicit Pi session controls preserve
  their existing semantics and do not receive automatic CCB resume arguments.
- Older `.pi-session` records with a legacy `ccb-*` id or a missing native path
  scan only the managed Pi session directory and resume the latest valid JSONL
  transcript for the matching agent, project, and working directory.
- Invalid bindings fall back to a fresh native session.

## Backend Design

`lib/provider_backends/pi/launcher.py` owns managed session-directory setup,
marker-based command rendering, and CCB session payload projection.
`lib/provider_backends/pi/pane_events.py` exposes the native identity captured
in `extension_ready`; `lib/provider_backends/pi/pane_execution.py` persists it
before prompt dispatch can advance the event offset.

## Persistence Contract

The `.pi-session` record stores `ccb_session_id` plus `pi_session_id`,
`pi_session_path`, normalized working directory, binding timestamp, and binding
source. Native paths must be direct files in the managed session directory,
have a matching JSONL `session` header and id, and match the recorded cwd.

## Verification Status

Focused session-history, pane-execution, and runtime-launch checks pass:
`155 passed` with Python 3.13 using:
`python3 -m pytest -q test/test_pi_session_history.py
test/test_pi_pane_execution.py test/test_v2_runtime_launch.py`.
`python3 -m compileall -q lib test` and `git diff --check` also pass. The
regression suite specifically covers initial ready-event persistence, explicit
session controls, and legacy records without a native path.

## Known Limitations

If Pi does not emit a valid `session_start` identity or the managed JSONL file
fails validation, CCB intentionally starts a fresh native session.
