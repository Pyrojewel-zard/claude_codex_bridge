# CCB Self Role Plan

Date: 2026-06-09

## Purpose

Plan the `agentroles.ccb_self` Role Pack: a CCB-specific self-maintenance and
expert agent that helps users and other agents understand CCB architecture,
use CCB features, diagnose CCB runtime state, repair tmux/provider/message
faults, and keep CCB knowledge current as new features land.

`ccb_self` is an auxiliary role. It does not own product or coding task
outcomes, and its own failure must not stop any other configured agent from
running. The role behaves like a human operator embedded in the project: it can
inspect evidence, recommend safe repair, and perform bounded maintenance under
the user's maintenance objective, but it must not become a daemon authority or
business task executor.

## File Map

- [roadmap.md](roadmap.md): current design and implementation sequence.
- [implementation-status.md](implementation-status.md): current draft,
  evidence, review, and blocker handoff.
- [open-questions.md](open-questions.md): unresolved product and safety
  questions only.
- [topics/operating-model.md](topics/operating-model.md): role identity,
  failure isolation, authority boundaries, and activation model.
- [topics/skills-and-tools.md](topics/skills-and-tools.md): `ccb_self`
  built-in skills, references, local helper scripts, and MCP tool surface.
- [topics/ccb-expert-knowledge-role.md](topics/ccb-expert-knowledge-role.md):
  next-stage design for making `ccb_self` the project-local CCB expert across
  architecture, usage, feature updates, and bounded pane-view diagnosis.
- [topics/pane-view-self-supervision.md](topics/pane-view-self-supervision.md):
  self-supervision direction that uses real CCB-owned pane text view, especially
  bottom/current prompt capture, as primary evidence for ambiguous execution
  progress, with screenshots only as fallback.
- [topics/memory-and-mcp-tools.md](topics/memory-and-mcp-tools.md): built-in
  role memory, MCP diagnostic layers, screenshot/visual evidence, and tool
  safety boundaries.
- [topics/autonomy-and-permissions.md](topics/autonomy-and-permissions.md):
  autonomous action tiers, confirmation boundaries, and safe repair policy.
- [topics/first-slice-blueprint.md](topics/first-slice-blueprint.md): v1 Role
  Pack package shape, built-in skill contents, MCP priorities, validation
  gates, and rollout sequence.
- [topics/recovery-runbooks.md](topics/recovery-runbooks.md): diagnostic and
  recovery flows for broken contexts, panes, restarts, and message chains.
- [topics/skill-drafts-review-test-evidence.md](topics/skill-drafts-review-test-evidence.md):
  current built-in skill draft paths, review status, test scenarios, command
  evidence, blocked contracts, and helper/tool needs.
- [decisions/001-auxiliary-self-agent.md](decisions/001-auxiliary-self-agent.md):
  decision that `ccb_self` is a failure-contained auxiliary agent, not runtime
  authority.
- [decisions/002-built-in-ccb-config-skill.md](decisions/002-built-in-ccb-config-skill.md):
  decision to make `ccb-config` a built-in `agentroles.ccb_self` skill instead
  of shipping it as a universally inherited skill.
- [decisions/003-bounded-autonomy.md](decisions/003-bounded-autonomy.md):
  decision to give `ccb_self` stronger bounded autonomy for maintenance tasks.
- [decisions/004-default-recommended-install.md](decisions/004-default-recommended-install.md):
  decision to install or refresh `agentroles.ccb_self` by default, include
  `ccb_self` in the built-in blank-project default, and keep existing project
  config binding explicit.
- [decisions/005-expert-knowledge-database.md](decisions/005-expert-knowledge-database.md):
  decision to make `ccb_self` a CCB expert through compact memory routing,
  role references, talk1 manuals indexes, and source-backed lookup instead of
  embedding full manuals or the whole source tree in role memory.
- [decisions/006-future-modification-guardrails.md](decisions/006-future-modification-guardrails.md):
  decision that future `ccb_self` changes must preserve the canonical
  `agentroles.ccb_self` id and keep maintenance heartbeat disabled unless
  manually enabled.
- [decisions/007-unified-diagnose-entrypoint.md](decisions/007-unified-diagnose-entrypoint.md):
  decision to expose one `ccb_diagnose <agentname>` workflow that diagnoses,
  performs bounded recovery, verifies, and requests authorization before
  submitting a redacted GitHub issue.
- [drafts/agentroles.ccb_self/](drafts/agentroles.ccb_self/): reviewable draft
  Role Pack payload for `agentroles.ccb_self`; production content should move
  to the role catalog or an accepted local role source after review.
- [../../../manuals/ccb-self-expert-guide.md](../../../manuals/ccb-self-expert-guide.md):
  Markdown expert guide for `ccb_self` covering CCB architecture, command
  surface, config, communication, diagnosis, recovery, source navigation, and
  knowledge refresh.

## Related Sources

- [../rolepack-system/README.md](../rolepack-system/README.md)
- [../ccbd-agent-hot-reload/README.md](../ccbd-agent-hot-reload/README.md)
- [../../../ccbd-startup-supervision-contract.md](../../../ccbd-startup-supervision-contract.md)
- [../../../ccbd-lifecycle-stability-plan.md](../../../ccbd-lifecycle-stability-plan.md)
- [../../../ccbd-diagnostics-contract.md](../../../ccbd-diagnostics-contract.md)
- [../../../ccb-config-layout-contract.md](../../../ccb-config-layout-contract.md)
- [../../../ccbd-pane-recovery-continuous-attach-plan.md](../../../ccbd-pane-recovery-continuous-attach-plan.md)
- [../../../managed-provider-completion-reliability-plan.md](../../../managed-provider-completion-reliability-plan.md)
- [../../../ccb-provider-state-storage-boundary-plan.md](../../../ccb-provider-state-storage-boundary-plan.md)

## Scope

In scope:

- Role identity, memory, skills, and reference docs for `agentroles.ccb_self`.
- CCB expert knowledge support: source architecture navigation, command and
  config usage explanation, feature/release status awareness, and knowledge
  refresh after landed changes.
- Diagnosis of mounted daemon, configured agents, tmux namespace, panes,
  provider runtime evidence, queues, inboxes, replies, artifacts, logs, config
  reload state, and storage boundaries.
- Recovery guidance for provider context corruption, stuck panes, missing
  mounts, interrupted job chains, pending callbacks, and broken replies.
- Private CCB configuration ownership through the built-in `ccb-config` skill:
  config design/editing, grammar and schema validation, role binding,
  reload readiness, and disk-config versus live daemon graph drift.
- Controlled use of existing CCB commands such as `doctor`, `ps`, `logs`,
  `trace`, `repair retry`, `repair resubmit`, `repair ack`, `clear`, `reload`,
  and `restart <agent>`.
- Autonomous low-risk and gated maintenance actions when the user asks
  `ccb_self` to diagnose, fix, recover, maintain, or apply a CCB config change.
- Read-only MCP tools for CCB/tmux runtime snapshots and lineage tracing.
- Read-only screen evidence tools, including text capture first and bounded
  screenshot capture for CCB-owned panes/windows when visual state matters,
  especially when text capture cannot classify ambiguous agent progress.
- Mutating MCP tools only when they call CCB control-plane commands and satisfy
  the bounded-autonomy policy.
- User-facing tmux quickstart reference for CCB-managed sessions.

Out of scope:

- Making `ccb_self` mandatory for daemon startup or agent supervision.
- Letting `ccb_self` replace `ccbd` as lifecycle authority.
- Letting `ccb_self` complete the original coding/product task after another
  agent failed.
- Treating `ccb_self` as a general product engineer for non-CCB business
  features.
- Duplicating the entire CCB source tree or long implementation docs into role
  memory instead of using compact expert references and source-backed lookup.
- Keeping CCB config design/edit skills universally inherited by every agent.
- Using the built-in `ccb-config` skill to execute `ccb reload` without
  validation, dry-run review, and maintenance intent.
- Using the built-in `ccb-config` skill to execute restart or kill; those
  remain separate recovery/control-plane actions.
- Fully autonomous project-wide shutdown, force repair, restart-all, or
  destructive cleanup.
- Raw destructive tmux operations exposed to the role, including `kill-pane`,
  `kill-window`, `kill-server`, `respawn-pane`, ad hoc `send-keys`, and manual
  pane creation.
- Arbitrary desktop screenshots or screenshots outside the current CCB project
  namespace.
- Reading provider secrets or auth material.
- Treating `.ccb/agents/*`, tmux pane facts, provider session files, or pid
  files as authority.

## Naming

- Stable role id: `agentroles.ccb_self`
- Default project-local agent name: `ccb_self`
- Display name: `CCB Self Maintainer`
- Expected config shorthand:

```toml
[windows]
ops = "agentroles.ccb_self:codex"
```

The role id is package identity. Runtime surfaces use the project-local agent
name `ccb_self` unless the user explicitly binds the role to another name.
