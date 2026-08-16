# CCB Self Role Implementation Status

Date: 2026-06-11

## Current Phase

7.4.0 release validation is in progress. The preview Role is mounted in the
current CCB project as `ccb_self`; public inherited `ccb-config` residue has
been collected; and the current implementation prepares `agentroles.ccb_self`
as a recommended default Role Pack during install/update provisioning while the
built-in blank-project config binds `ccb_self` for immediate `ccb-config`
access.

The v1 CCB expert upgrade has now been materialized in the local
`agent-roles-spec` role source. `ccb_self` is no longer only a maintenance
operator: role version `0.2.0` includes `ccb-expert-reference`, role-level
GitHub/source/manual/command/runtime/release references, and compact memory
routing for source-backed CCB answers.

The public inherited control-skill slice now also materializes
`ccb-diagnose` (user alias `$ccb_diagnose`) beside `ccb-clear` for the managed
Codex, Claude, Droid, Gemini, Grok, Kimi, and Qoder providers. Its workflow is
pane-first for named-agent incidents, uses bounded recovery gates, and asks
before any redacted GitHub issue submission.

## Last Landed

- 2026-06-09: Added reviewable draft Role Pack content under
  [drafts/agentroles.ccb_self/](drafts/agentroles.ccb_self/) with four Codex
  built-in skill drafts, role memory, references, and a draft read-only
  `tools/doctor.py` contract.
- 2026-06-09: Captured initial isolated runtime evidence in
  [topics/skill-drafts-review-test-evidence.md](topics/skill-drafts-review-test-evidence.md).
- 2026-06-09: Processed coworker review findings, fixed accepted blockers in
  the skill drafts, and replaced the placeholder doctor helper with a read-only
  JSON collector.
- 2026-06-09: Processed reviewer3 findings, fixed the chain cancel-failure
  blocker, clarified low-risk diagnose/recover/chain/config wording, and
  validated `doctor logs` plus `fault clear` syntax in the isolated test
  project.
- 2026-06-09: Reworked the accepted draft for the updated Agent Roles protocol
  and materialized it at
  `/home/bfly/yunwei/agent-roles-spec/roles/ccb-self` with host-neutral
  `skills/`, CCB adapter metadata under `adapters/ccb/`, catalog aliases, and
  `tests/test_ccb_self_role.py`.
- 2026-06-09: Moved full `ccb-config` ownership to the `agentroles.ccb_self`
  Role source and removed the full public inherited `ccb-config` skill from
  `inherit_skills/{codex_skills,claude_skills}`. Install/materialization now
  treats old public `ccb-config` as legacy residue to clean.
- 2026-06-09: Implemented user-facing `ccb restart <agent>` through the mounted
  ccbd graph with single-agent target authority, busy/pending/callback gates,
  old/new runtime evidence, and no force/all/window restart surface.
- 2026-06-09: Polished the local `agent-roles-spec` catalog source for
  `agentroles.ccb_self`, including aliases, roles index entry, mount-oriented
  wording, local install/resolve/doctor checks, and full `agent-roles-spec`
  test coverage.
- 2026-06-10: Collected legacy public `ccb-config` residue from user-level
  Codex/Claude skill homes and current project provider-state homes into
  `/home/bfly/.ccb/deprecated/ccb-config-public-20260610T081814+0800`, then
  restored only `ccb_self` with a Role-owned private `ccb-config` symlink and
  projection marker.
- 2026-06-10: Added the 7.4.0 default install direction for
  `agentroles.ccb_self`: install/update Role Pack provisioning installs or
  refreshes recommended default roles, the built-in blank-project default binds
  `ccb_self:codex` to `agentroles.ccb_self`, and
  [decisions/004-default-recommended-install.md](decisions/004-default-recommended-install.md)
  records that existing project topology changes remain explicit.
- 2026-06-10: Added the draft `ccb-comm-reply-recover` skill to capture the
  observed "reply not received" communication recovery pattern: trace lineage,
  inspect mailbox head-of-line state, cross-check provider pane evidence, cancel
  stale active jobs, preserve valid running work, and cancel duplicate retries
  after a successful reply.
- 2026-06-10: Captured the user direction that `ccb_self` should become the
  project-local CCB expert, with architecture navigation, command usage,
  release/update awareness, knowledge refresh, and bounded pane-view diagnosis
  planned in
  [topics/ccb-expert-knowledge-role.md](topics/ccb-expert-knowledge-role.md).
- 2026-06-10: Refined self-supervision around real pane text view: use
  `tmux capture-pane` bottom/current prompt content and activity sampling as
  the v1 primary evidence path, with screenshot/OCR only as fallback. See
  [topics/pane-view-self-supervision.md](topics/pane-view-self-supervision.md).
- 2026-06-11: Materialized the v1 expert knowledge database in
  `/home/bfly/yunwei/agent-roles-spec/roles/ccb-self`: bumped role version to
  `0.2.0`, added `ccb-expert-reference`, declared eleven role references,
  added GitHub/source/manual/command/runtime/config/release/refresh indexes,
  updated role memory/README/adapter notes, and updated role tests.
- 2026-06-11: Processed coworker design review for the v0.2.0 memory/skill
  system. No blockers were found. Fixed the high/medium/low follow-ups by
  adding memory skill routing, documenting `doctor logs`, sharpening
  fault-clear and reload aftermath rules, reducing chain/comm-reply routing
  ambiguity, adding non-source-checkout fallback for expert lookup, adding
  role-version knowledge-refresh trigger, and updating validation notes/tests.
- 2026-06-11: Recorded future `ccb_self` modification guardrails in
  [decisions/006-future-modification-guardrails.md](decisions/006-future-modification-guardrails.md):
  new behavior must use canonical `agentroles.ccb_self`, and maintenance
  heartbeat remains disabled by default unless manually enabled in config.
- 2026-08-07: Materialized the inherited `ccb-diagnose` skill for all current
  required-control providers, added installer/uninstaller lists and Grok
  command permissions, and validated the projection/skill regression slice:
  `59 passed`; all seven `quick_validate.py` checks passed; `bash -n install.sh`
  and `git diff --check` passed.

## Active TODO

1. Validate the updated `agentroles.ccb_self` through CCB install/refresh and
   provider-home materialization when source runtime validation is requested.
2. Add handoff matrix tests for diagnose/recover/chain/config/comm-reply/expert
   routing.
3. Define or implement the first structured MCP/control-plane helper surface
   used by pane-first `ccb_diagnose` when a provider pane cannot be resolved.
4. Decide whether non-self agents need a separate delegation stub; the full
   public inherited `ccb-config` source has been removed.
5. Finish any remaining targeted/full 7.4.0 validation tied to the Role Pack
   release line, including an installed-project smoke for inherited
   `ccb-diagnose` discovery.

## Blocked By

- No current implementation blocker. Full current-project rebuild was skipped
  earlier because dirty managed worktrees (`archi`, `worker1`, `worker2`,
  `worker3`) made `ccb -n` unsafe; the cleanup used deprecation collection plus
  targeted Role-owned `ccb_self` symlink repair instead.

## Last Verified

2026-06-09 from `/home/bfly/yunwei/test_ccb2` with:

```bash
HOME=/home/bfly/yunwei/test_ccb2/source_home \
CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home \
/home/bfly/yunwei/ccb_source/ccb_test ...
```

Verified source runtime isolation, config validation, reload dry-run, daemon
doctor/ps/queue/fault/log evidence, lineage trace evidence, repair/cancel
command availability, draft static role/skill/tool shape, read-only doctor
helper JSON, markdown links, no source-test paths in distributable skills, and
blocked restart/catalog surfaces. Main-agent spot check also re-ran
`ccb_test --diagnose`, `doctor logs codexer`, `fault list`, and draft
`tools/doctor.py` with `CCB_BIN=/home/bfly/yunwei/ccb_source/ccb_test`.

2026-06-09 from `/home/bfly/yunwei/agent-roles-spec`:

```bash
python -m pytest tests/test_ccb_self_role.py
python -m pytest
```

Result: `tests/test_ccb_self_role.py` passed `4/4`; full suite passed `28/28`.
Validated updated Role loading, aliases (`ccb-self`, `ccb_self`, `ccb.self`),
CCB adapter metadata, catalog install/resolve, no local source paths in
distributable skill text, and the read-only CCB Self doctor helper command set.

2026-06-09 after moving full `ccb-config` out of public inherited skills:

```bash
python -m pytest test/test_repo_hygiene.py \
  test/test_install_source_dev_mode.py \
  test/test_provider_profiles.py::test_materialize_codex_home_config_repairs_owned_skills_in_user_asset_dir
python -m pytest
```

Result: targeted CCB source tests passed `18/18`; full CCB source suite passed
`2478/2478` with `2` skipped. `agent-roles-spec` full suite still passed
`28/28`.

2026-06-09 after implementing guarded restart:

```bash
pytest -q test/test_ccb_restart.py
pytest -q test/test_v2_phase2_clear.py test/test_v2_cli_render.py \
  test/test_v2_ccbd_start_flow.py::test_project_restart_panes_handler_schedules_in_place_pane_restart
pytest -q test/test_ccbd_project_clear.py \
  test/test_v2_ccbd_socket.py::test_ccbd_socket_roundtrip_and_shutdown
HOME=/home/bfly/yunwei/test_ccb2/source_home \
CCB_SOURCE_HOME=/home/bfly/yunwei/test_ccb2/source_home \
/home/bfly/yunwei/ccb_source/ccb_test restart codexer
```

Result: focused restart tests passed `8/8`; related regression tests passed
`24/24` and `6/6`; source runtime validation from `/home/bfly/yunwei/test_ccb2`
returned `restart_status: ok` for `codexer` with busy gate passed and old/new
runtime evidence.

2026-06-09 from `/home/bfly/yunwei/agent-roles-spec` after mounting the Role
into the local catalog:

```bash
python -m agent_roles list --json
AGENT_ROLES_STORE=/tmp/agent-roles-ccb-self.8eoQFU/store \
AGENT_ROLES_SPEC_HOME=/home/bfly/yunwei/agent-roles-spec \
AGENT_ROLES_NO_REMOTE=1 \
python -m agent_roles install ccb-self --json
AGENT_ROLES_STORE=/tmp/agent-roles-ccb-self.8eoQFU/store \
AGENT_ROLES_SPEC_HOME=/home/bfly/yunwei/agent-roles-spec \
AGENT_ROLES_NO_REMOTE=1 \
python -m agent_roles resolve ccb_self --json
AGENT_ROLES_STORE=/tmp/agent-roles-ccb-self.8eoQFU/store \
AGENT_ROLES_SPEC_HOME=/home/bfly/yunwei/agent-roles-spec \
AGENT_ROLES_NO_REMOTE=1 \
python -m agent_roles doctor ccb-self --json
python -m pytest
```

Result: `agentroles.ccb_self` appears as available in the local catalog;
temporary-store install returned `role_status: installed`; resolve returned
`installed: true`; doctor returned `status: ok`; full suite passed `28/28`.

2026-06-10 after public `ccb-config` deprecation collection in the current
project:

```bash
find .ccb/agents -path '*/provider-state/*/home/skills/ccb-config' -maxdepth 8 -print
find .ccb/agents -path '*/provider-state/*/home/skills/ccb-config.ccb-projection.json' -maxdepth 8 -print
ccb ping ccb_self
```

Result: user-level `/home/bfly/.codex/skills/ccb-config` and
`/home/bfly/.claude/skills/ccb-config` are absent; the deprecation archive
contains `12` collected `ccb-config` copies; only
`.ccb/agents/ccb_self/provider-state/codex/home/skills/ccb-config` remains in
the current project, and it points to
`/home/bfly/.roles/installed/agentroles.ccb_self/.../skills/ccb-config` with a
`codex-role-skill:agentroles.ccb_self:ccb-config` projection marker. `ccb ping
ccb_self` returned mounted/idle/restored.

2026-06-11 from `/home/bfly/yunwei/agent-roles-spec` after the v1 expert
upgrade:

```bash
python -m pytest -q tests/test_ccb_self_role.py
python -m py_compile agent_roles/manifest.py tests/test_ccb_self_role.py roles/ccb-self/adapters/ccb/tools/doctor.py
python - <<'PY'
from pathlib import Path
from agent_roles.manifest import load_role
role = load_role(Path('roles/ccb-self'))
print(role.id, role.version)
print(len(role.table('contents')['skills']), len(role.table('contents')['references']))
PY
python -m pytest -q
git diff --check
```

Result: focused role tests passed `5/5`; manifest/doctor/test py_compile
passed; manifest load reported `agentroles.ccb_self 0.2.0` with `6` skills and
`11` references; full `agent-roles-spec` suite passed `32/32`; whitespace diff
check passed. `ccb_source` plan-tree whitespace diff check also passed.

2026-06-11 after coworker review follow-ups:

```bash
python -m pytest -q tests/test_ccb_self_role.py
python -m py_compile agent_roles/manifest.py tests/test_ccb_self_role.py roles/ccb-self/adapters/ccb/tools/doctor.py
git diff --check
python -m pytest -q
```

Result: focused role tests passed `6/6`; py_compile passed; whitespace diff
check passed; full `agent-roles-spec` suite passed `33/33`.
