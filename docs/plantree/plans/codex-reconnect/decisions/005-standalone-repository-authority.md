# Standalone Repository Authority

Date: 2026-07-20
Status: Accepted and implemented

## Context

`codex-reconnect` was initially implemented under
`ccb_source/tools/codex-reconnect/` even though its runtime and product scope
are intentionally independent of CCB. A distributable project needs its own
working tree, bilingual user documentation, installation lifecycle, Git
history, and CI.

## Decision

Use `/home/bfly/workspace/agent_develop/codex-reconnect` as the authoritative
local working tree and `https://github.com/SeemSeam/codex-reconnect` as the
authoritative remote repository. New product changes, releases, and CI land
there. The earlier `/home/bfly/yunwei/codex-reconnect` path is retired.

Keep `ccb_source/tools/codex-reconnect/` as CCB's synchronized vendored copy.
Product changes land in the standalone authority first, then are copied into
CCB with matching implementation tests. Do not delete it while CCB packaging,
managed command projection, or source-test shims depend on that path.

Initial standalone evidence:

- root commit `f1aedd8` contains the migrated source, skill, 15 tests,
  bilingual READMEs, install/uninstall scripts, and CI;
- commit `eaf112f` updates official GitHub Actions to their current Node 24
  runtime generation;
- CI run `29718562585` passes formatting and Ubuntu/macOS tests on Python 3.10
  and 3.13;
- the user-local installation was refreshed from the standalone tree and
  passed version, App Server handshake, HTTPS probe, and installed-path skill
  projection checks.

## Consequences

- The standalone repository is the source of truth for future implementation.
- The CCB PlanTree remains the design and migration trail, not the release
  repository.
- The vendored copy must match the standalone implementation at each CCB
  integration point; it is not an independent feature authority.
- Cleanup remains recoverable from both the standalone Git history and GitHub
  remote when explicitly approved later.
