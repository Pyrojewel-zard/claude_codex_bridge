# Decision 003: Kimi Resume Uses An Observed Per-Agent Session

Date: 2026-07-21
Status: Accepted for R6

## Context

PR258 adds `--continue` whenever generic CCB restore is requested. Kimi 1.47.0
resolves that flag to the most recent session for the working directory, so two
CCB agents sharing an in-place workspace can resume each other's context. The
same flag exits with `No previous session found` on a fresh working directory.
Kimi supports exact `--session <id>` resume, stores sessions by work-directory
hash and native session ID, and exposes the selected ID in the session path and
native `wire.jsonl` observations.

CCB's `.kimi-<agent>-session` file currently stores only the CCB pane launch
ID. That launch ID is not a Kimi session ID and must not be passed to Kimi.
Kimi's `supports_resume=false` manifest field continues to describe in-flight
CCB execution restore; R6 concerns provider conversation continuity between
managed pane launches.

Kimi deployments also expose a second native layout under
`.kimi-code/sessions/wd_<basename>_<sha256-prefix>/<session>/agents/<agent>/wire.jsonl`.
It carries the same observed-session authority but has a distinct state root
and deeper agent-owned wire path.

## Decision

The per-agent `.kimi-<agent>-session` record owns a native Kimi session only
after the Kimi completion reader observes that agent's exact outer
`CCB_REQ_ID` in the native session's `wire.jsonl`. The binding stores the native
session ID, exact wire path, normalized work directory, legacy Kimi share root,
current `.kimi-code` state root, storage layout, and observation time. CCB
never infers ownership from work-directory recency, directory ordering, pane
text, or the CCB launch ID.

The launcher records both state roots used for observation. A restart validates
the recorded layout and all non-symlinked path components before selecting the
observed native session.

On a normal managed restart, CCB validates that the persisted record still
matches the current project, agent, normalized work directory, share root, and
native session layout. It then capability-checks the configured Kimi executable
and emits the stable long form `--session <owned-id>`. It never synthesizes
`--continue`.

These paths start fresh and clear the carried binding from the new launch
record:

- first launch or a session that has not yet produced an observed CCB turn;
- explicit CCB clear/reset (`restore=false`);
- missing, malformed, mismatched, symlinked, or storage-drifted binding;
- a configured Kimi executable without exact-session capability.

Starting fresh is the documented missing/corrupt-session behavior. It must be
reported in the session payload rather than silently falling back to another
session. Provider-owned old session data is not deleted.

Explicit user session controls in provider startup arguments take precedence.
CCB recognizes stable long options and known versioned short aliases, adds no
second resume flag, clears any previously carried automatic binding, and binds
the actually observed native session after the next CCB turn.

## Consequences

Two agents in the same workspace can retain distinct exact Kimi sessions
because each agent-specific CCB record is updated only by its own request
observation. A restart before any CCB turn starts fresh because no useful
conversation authority exists yet. `/new`, user-selected sessions, and other
native session switches become the new owned binding only after a subsequent
exact CCB turn is observed.

The Kimi share directory may still contain user authentication and other
provider-owned state. R6 records and validates its path but does not copy,
rewrite, delete, or inspect credentials or conversation content.

## Rejected Alternatives

Generic `--continue` guesses by work-directory recency and fails fresh launch.
Selecting the newest session directory has the same cross-agent ambiguity.
Using CCB's pane launch ID invents a native identity. Giving each agent a new
`KIMI_SHARE_DIR` would also isolate configuration and authentication, expanding
R6 into credential projection and provider-state migration.

## Verification

R6 must cover fresh launch, exact restart, clear/reset, missing and malformed
bindings, share/work-directory mismatch, explicit long and versioned short
session flags, two same-workdir agents, observation-time persistence, native
session switching, and an isolated real Kimi 1.47.0 project. The real gate must
prove each agent resumes only its own sentinel-bearing session and leaves the
candidate source and external runtime clean.
