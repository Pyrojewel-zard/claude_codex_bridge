# CCB Agent Sidebar Integration Plan

## 1. Document Position

This document is the planning baseline for deep-forking `hiroppy/tmux-agent-sidebar` into a CCB-native project console.

The target is not a generic tmux plugin. The target is a built-in CCB namespace UI that solves the current "many agents squeezed into one foreground split layout" problem by combining:

- freely designed project windows
- managed agent panes in those windows
- a stable sidebar projected into each managed window
- read-only project monitoring
- keyboard and mouse navigation between windows and agents
- a compact CCB communication feed

The sidebar must consume `ccbd` authority. It must not become a second authority for project identity, agent identity, window layout, pane ownership, runtime lifecycle, worktree lifecycle, or message/job state.

Related authority documents:

- [docs/ccbd-startup-supervision-contract.md](ccbd-startup-supervision-contract.md)
- [docs/ccbd-project-namespace-lifecycle-plan.md](ccbd-project-namespace-lifecycle-plan.md)
- [docs/ccb-config-layout-contract.md](ccb-config-layout-contract.md)
- [docs/ccbd-diagnostics-contract.md](ccbd-diagnostics-contract.md)

This plan proposes a future `.ccb/ccb.config` topology extension. When implementation starts, [docs/ccb-config-layout-contract.md](ccb-config-layout-contract.md) must be updated in the same patch to promote the new grammar from plan to contract.

## 2. Product Decision

The fork should become `ccb-agent-sidebar`: a CCB built-in project console.

Confirmed decisions:

- It is built into CCB project namespaces, not installed as a user-global TPM plugin.
- It is a deep fork; keep useful upstream TUI patterns, replace the state and topology model.
- Phase 1 supports one project only.
- Phase 1 is read-only monitoring plus window/pane switching.
- It is deeply coupled to `ccbd` state.
- It does not depend on extra provider hooks for authority.
- It does not track or preserve user-created manual split panes.
- Phase 1 supports keyboard navigation and mouse clicking for window/agent focus.
- It is distributed as part of the CCB release, not as a separately installed user tool.
- Sidebar focus/switch operations go through `ccbd` RPC, not direct Rust-side tmux control.
- The release bundles the runtime binary at `bin/ccb-agent-sidebar`.
- Phase 1 release artifacts support Linux x86_64 and macOS universal helper binaries. Windows and psmux parity remain deferred until there is a concrete supported tmux/runtime target.

Deferred:

- multi-project dashboard
- mutating controls such as ask, cancel, restart, reflow, and worktree creation/removal
- desktop notifications
- provider hook enrichment beyond existing CCB completion/runtime state
- Windows/psmux parity
- scrolling inside sidebar panels

Provider-native activity enrichment is tracked in the plan tree:

- [Sidebar Provider Activity Plan](plantree/plans/sidebar-provider-activity/README.md)

## 3. Upstream Baseline

Upstream `tmux-agent-sidebar` is an MIT-licensed Rust/tmux plugin with:

- ratatui rendering
- keyboard and mouse interaction patterns
- tmux pane/window manipulation helpers
- a sidebar row model
- bottom panels
- hook adapters for Claude Code, Codex, and OpenCode

Useful parts to keep or adapt:

- ratatui layout/rendering structure
- input handling
- mouse click handling
- list navigation
- pane/window focus mechanics
- color/style utilities

Parts to replace:

- global tmux session scanning
- generic `@pane_*` state model
- provider hook setup wizard
- hook-first agent status
- direct worktree lifecycle
- desktop notification ownership
- global TPM plugin lifecycle

Upstream topology is a toggle-created sidebar pane in the current tmux window. That does not satisfy CCB's target because the sidebar disappears when switching to a different window unless every window is separately toggled. CCB needs a stable project sidebar projected into managed windows.

## 4. Config Model

### 4.1 Target Shape

The next config model should make `windows` first-class. The examples below use the readable target shape, but Phase 1 implementation should keep using `.ccb/ccb.config` and the existing rich-config parser path rather than introducing a separate `.ccb/config.yaml`.

```toml
entry_window = "main"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20

[windows]
main = "agent1:codex, agent2:codex, agent3:claude, ccb_self:codex"
```

Rules:

- `windows` defines the managed project tmux windows.
- Each window value uses the existing split grammar:
  - `;` for left-to-right split
  - `,` for top-to-bottom split
  - `(...)` for grouping
- Agent leaves continue to use `agent_name:provider`.
- All agent leaves across all windows form the desired agent set.
- Each agent name must be globally unique and appear exactly once.
- Window names are logical names managed by `ccbd`.
- `entry_window` controls the default selected window when `ccb` creates or attaches to the project namespace.
- `cmd` is removed from the new grammar.
- Manual user-created panes are outside CCB and are not represented in config, sidebar state, diagnostics rows, or restore guarantees.
- New-project bootstrap should preserve the current default of three configured agents, all initially placed in `main`.

### 4.2 Sidebar Projection

The sidebar should not be hand-written into every window layout.

Instead:

```toml
[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
```

means the namespace controller materializes each managed window as:

```text
sidebar pane + configured window layout
```

This gives the user a stable sidebar while switching windows without polluting the agent layout grammar.

Phase 1 sidebar modes:

- `every_window`: project a sidebar pane into every managed window.
- `off`: do not project sidebar panes.

Default sidebar options:

- `mode`: `every_window`
- `width`: `"15%"`, matching upstream `tmux-agent-sidebar` behavior
- `bottom_height`: `20`, matching upstream `tmux-agent-sidebar` behavior

`width` accepts either:

- a percentage string such as `"15%"`
- a fixed column count such as `32`

Deferred sidebar modes:

- `selected_windows`
- `console_only`
- per-window width overrides
- temporary overlay/toggle mode

### 4.2.1 ProjectView Performance Boundary

The sidebar polls `ccbd` `project_view`, so `project_view` is an online UI read
path and must stay bounded even when job/message JSONL histories are large.

Current implementation constraints:

- server responses carry a 1000ms TTL and the sidebar refresh loop must respect
  that TTL instead of clamping normal refreshes to a sub-second interval
- a single ProjectView build owns one tmux namespace backend and one pane-text
  cache, so focus/window/sidebar snapshots and provider prompt checks do not
  instantiate the backend or `capture-pane` per agent path
- comms rows are computed from active/queued jobs plus a bounded recent job tail,
  then message-bureau metadata is resolved lazily for those candidate jobs
- the ProjectView path must not rebuild reply/attempt/message indexes by full
  `list_all()` scans during normal sidebar refreshes

Longer-term storage compaction or read-model snapshots can improve cold-start
latency and disk usage, but the online sidebar read path must remain bounded
without waiting for compaction to exist.

### 4.3 Existing Config Compatibility

Existing compact single-layout configs remain accepted during migration.

Migration interpretation:

```text
cmd; agent1:codex, agent2:claude
```

becomes logically:

```toml
entry_window = "main"

[ui.sidebar]
mode = "every_window"

[windows]
main = "agent1:codex, agent2:claude"
```

The old `cmd` leaf is ignored for the new window topology because command shells are user-managed panes, not CCB-managed config leaves.

This migration behavior is the default compatibility path. Users with legacy compact config do not need to manually rewrite `cmd; agent1:codex,...` before the first sidebar-capable version starts.

If `.ccb/ccb.config` is missing, bootstrap should use the built-in default:

```toml
entry_window = "main"

[windows]
main = "demo:codex"
```

The provider shown above is the fallback. Runtime config loading selects the
first locally available supported provider CLI and keeps exactly one `demo`
agent. The sidebar defaults are implicit and need not be written unless the
user overrides them.

### 4.4 Parser And Normalization Rules

The config loader should accept both:

- legacy compact single-layout config
- new rich TOML window topology config

Both inputs normalize into one internal model:

```text
ProjectConfig
  windows: tuple[WindowSpec]
  agents: dict[str, AgentSpec]
  entry_window: str
  ui.sidebar: SidebarSpec
```

Window name rules:

- must match `^[A-Za-z][A-Za-z0-9_-]*$`
- no spaces
- no `/`
- no `.`
- no non-ASCII names in Phase 1

Agent rules:

- agent leaves continue to use `agent_name:provider`
- provider is declared only in the layout leaf
- every agent name must be globally unique across all windows
- each configured agent appears exactly once

New `windows` topology `cmd` rule:

- `cmd` is not supported in new `windows` topology
- if a new rich `windows` layout contains `cmd`, validation fails clearly

Legacy compact `cmd` compatibility:

- legacy compact layouts may still contain `cmd`
- during normalization, the legacy `cmd` leaf is ignored
- if removing `cmd` leaves no agent leaves, validation fails

`entry_window` rules:

- if omitted, it defaults to the first configured window
- if present, it must reference an existing window

Sidebar validation:

- `ui.sidebar.mode`: `every_window` or `off`
- `ui.sidebar.width`: positive integer columns or a percentage string such as `"15%"`
- `ui.sidebar.bottom_height`: non-negative integer
- defaults are applied during normalization and need not be written to the config file

The normalized topology signature must include:

- ordered window names
- each window's normalized layout render
- `entry_window`
- sidebar mode, width, and bottom height

Changing sidebar width or bottom height changes the realized tmux topology and should invalidate the namespace layout signature.

## 5. Multi-Window Namespace Materialization

The project namespace should materialize config windows directly as tmux windows:

```text
Project namespace tmux session
  window main
    sidebar pane + agent1/agent2/agent3 layout
  window research
    sidebar pane + agent4 layout
  window review
    sidebar pane + agent5/agent6 layout
```

Creation order:

1. create or recreate the project tmux session
2. create managed tmux windows in config order
3. materialize each window with its projected sidebar plus configured agent layout
4. select `entry_window` for the user-facing `ccb` entry path

If `entry_window` is not the first configured window, config order still controls tmux window order; `entry_window` only controls the final selected window.

Each managed window should be planned as:

```text
WindowMaterializationPlan
  window_name: main
  sidebar: enabled
  user_layout: agent1,agent2,agent3
  realized_layout: sidebar ; (agent1,agent2,agent3)
```

The projected `sidebar` pane is not part of the user's layout expression.

Sidebar sizing:

- percentage width such as `"15%"` uses that share of the tmux window width
- integer width such as `32` uses fixed columns
- if the window is narrow, the sidebar may shrink to a minimum of `24` columns
- if the window is still too narrow, startup should continue and allow truncation rather than fail only because of sidebar width

Runtime binding additions:

- agent runtime records should include `tmux_window_id` and `tmux_window_name`
- CCB-owned panes should set `@ccb_window`
- agent panes should set `@ccb_role=agent` and `@ccb_slot=<agent>`
- sidebar panes should set `@ccb_role=sidebar` and `@ccb_sidebar_instance=<window_name>`

Config change behavior:

- Phase 1 should recreate the project namespace whenever the normalized topology signature changes.
- Do not attempt partial in-place mutation of tmux windows in Phase 1.
- The topology signature includes window order, each window layout, `entry_window`, sidebar mode, sidebar width, and sidebar bottom height.

Changes that trigger namespace recreation:

- window add/remove/rename/reorder
- agent add/remove/rename
- agent moves between windows
- per-window layout changes
- `entry_window` changes
- sidebar mode/width/bottom-height changes

Recovery behavior:

- agent pane recovery must restore the agent in its configured `tmux_window_name`
- namespace reflow recreates all configured windows from the normalized topology
- sidebar pane death is not agent runtime failure
- missing sidebar panes should be recreated by namespace reconciliation
- a missing configured agent pane is not directly an `offline` UI state while `ccbd` owns recovery
- if `ccbd` is recovering or reflowing a missing configured agent pane, ProjectView should report `pending` with a reason such as `pane_missing_recovering`
- if pane recovery fails or is exhausted, ProjectView should report `failed` with a recovery failure reason
- only intentionally stopped or unmounted agents should report `offline`

`ProjectView.windows` must be built from config windows plus namespace/runtime state. It must not be inferred by scanning arbitrary tmux windows.

## 6. Namespace And Pane Ownership

`ccbd` remains the only owner of the project namespace.

Managed resources:

- configured windows
- projected sidebar panes
- configured agent panes
- tmux window names and pane identities for those resources

Unmanaged resources:

- user-created manual split panes
- ad hoc shells
- panes not declared by config and not created by the namespace controller

Rules:

- Manual panes must not enter CCB authority.
- Manual panes are not shown in the sidebar.
- Manual panes are not preserved across namespace recreate/reflow.
- Manual panes may be destroyed when the project namespace is recreated.
- Sidebar navigation targets only configured windows and configured agents.

Pane identity for CCB-owned panes should use CCB-scoped tmux options:

- `@ccb_project_id`
- `@ccb_role`
- `@ccb_agent`
- `@ccb_slot`
- `@ccb_window`
- `@ccb_namespace_epoch`
- `@ccb_managed_by`
- `@ccb_sidebar_instance`

Generic upstream keys such as `@pane_status` are compatibility facts only and must not become CCB authority.

## 7. Phase 1 UI

### 7.1 Top Panel

The top panel is a project navigation tree:

```text
CCB project-name                       ccbd ●
▾ main
  ● agent1 codex
  ○ agent2 claude
▾ research
  ◐ agent3 gemini
▾ review
  ✕ agent4 claude
  · agent5 codex
```

Hierarchy:

- level 1: managed window
- level 2: agents in that window

Required UI signals:

- current tmux window highlight
- current focused agent highlight when focus is on a managed agent pane
- provider label
- simplified activity status symbol

All windows are shown expanded in Phase 1. Collapse/expand behavior is deferred.

### 7.2 Status Symbols

Phase 1 status is an `agent activity state`. It is not only CCB job state, because users may manually give work to a provider pane outside the CCB job path.

State resolver priority:

```text
blocking runtime/reconcile facts > current CCB job > provider/session signal > pane/process liveness
```

`current CCB job` remains the strongest work-intent signal. The only things that override it are facts that prove the configured agent cannot currently do that work, such as recovery failure, missing pane with no recovery owner, or runtime fault.

| Symbol | Color | UI State | Meaning |
| --- | --- | --- | --- |
| `●` | green | `active` | current CCB job is running, runtime is busy, or provider/session activity is advancing |
| `◐` | yellow | `pending` | job is queued/accepted, agent is starting/recovering, a missing pane is under daemon-owned recovery, provider is waiting, or active work has gone stale |
| `○` | blue | `idle` | agent is online and no current work is detected |
| `✕` | red | `failed` | current CCB job failed/incomplete/cancelled, provider reported abort/failure, pane recovery failed, or runtime fault blocks the current work |
| `·` | gray | `offline` | agent is intentionally stopped, unmounted, or the project namespace is not mounted |

When multiple compatible facts remain inside the same resolver layer, use this display severity order:

```text
failed > active > pending > idle > offline
```

Default timing:

- `active_stale_after`: `120s`; active work with no progress after this becomes `pending`
- `failed_visible_for`: `300s`; recent current-work failures remain red briefly so they are not missed

Older historical failures belong in the Comms feed rather than keeping the top row red indefinitely.

### 7.3 Bottom Panel: Comms Feed

The bottom panel should initially show a compact CCB communication feed:

```text
Comms
agent2>agent1 work
  review routing result
agent1>agent3 done
  D13R_OK
agent4>agent1 fail
  timeout
```

Content:

- sender
- target
- status
- timestamp or age
- short failure reason when present
- callback marker when present

Filtering behavior:

- when a window row is selected, show communication involving agents in that window
- when an agent row is selected, show communication involving that agent
- when the header is selected, show recent project-wide communication

Do not show raw `ccbd` logs in Phase 1. The feed should use normalized CCB job/message events.

## 8. State Source And Accuracy

Phase 1 must define status as unified activity state, not provider-specific UI state.

Primary state inputs:

- configured windows and agents from `.ccb/ccb.config`
- namespace state from `.ccb/ccbd`
- runtime state from `.ccb/agents/<agent>/runtime.json`
- job records and job events
- completion snapshots/decisions
- dispatcher state
- provider/session activity signals normalized by `ccbd`
- pane liveness inside the project-owned tmux socket/session

### 8.1 ProjectView Generation Pipeline

`ccbd` should generate ProjectView from one authoritative snapshot per request:

1. Load normalized config topology: ordered windows, configured agents, providers, `entry_window`, and sidebar settings.
2. Read namespace state: namespace epoch, project tmux socket/session, managed tmux windows, active window, active pane, and sidebar panes.
3. Inspect only the project-owned tmux socket/session for configured CCB panes. Do not scan arbitrary tmux sessions.
4. Load runtime records for configured agents.
5. Build the Comms list from dispatcher state, current job records, queue depth, and recent terminal job events.
6. Build a provider overlay from provider/session activity signals already normalized by `ccbd`.
7. Build a liveness overlay from pane existence, process liveness, runtime health, and reconcile state.
8. Resolve each configured agent into one `activity_state`, `activity_source`, `activity_reason`, and optional provider/runtime progress timestamp.
9. Build `windows` from config order plus known tmux window ids.
10. Build `comms` from compact CCB job/message records, not raw logs.

ProjectView generation must be read-only. It must not start recovery, mutate tmux layout, create panes, or update provider state. Recovery remains the existing supervision/reconcile loop's job.

If one input source is temporarily unavailable, `ccbd` should still return the best snapshot it can, with conservative status:

- stale job/provider data should not create `active`
- unknown runtime health on a desired configured agent should become `pending` if reconcile is active, otherwise `failed`
- an unavailable project namespace should be reflected at the namespace/header level; configured agents may report `offline` only when the project is intentionally unmounted

### 8.2 Agent Activity Resolver

For each configured agent, resolve status in this order:

1. Intentional lifecycle stop:
   - `runtime_state=stopped` or agent unmounted intentionally -> `offline`, reason `agent_stopped` or `agent_unmounted`
   - project namespace intentionally unmounted -> `offline`, reason `namespace_unmounted`
2. Blocking reconcile/runtime failure:
   - `reconcile_state=failed` -> `failed`, reason `reconcile_failed`
   - `runtime_health=faulted` or equivalent blocking health -> `failed`, reason `runtime_fault`
   - configured pane is missing and there is no active recovery/reflow owner -> `failed`, reason `pane_missing_unowned`
3. Active recovery/startup:
   - `reconcile_state=starting`, `recovering`, or `reflowing` -> `pending`
   - configured pane is missing and recovery/reflow is active -> `pending`, reason `pane_missing_recovering`
4. Provider/session signal:
   - recent assistant/provider output or user-submitted provider work -> `active`, reason `provider_progress`
   - provider waiting for permission/input/notification -> `pending`, reason `provider_waiting`
   - provider abort/failure event within `failed_visible_for` -> `failed`, reason `provider_failed`
   - provider stop/idle signal -> continue to liveness checks
5. Pane/process liveness:
   - healthy configured pane exists and no work is detected -> `idle`, reason `pane_alive`
   - process exists but health is stale or ambiguous -> `pending`, reason `health_unknown`
   - missing configured pane after the checks above should be `failed`, reason `pane_missing_unowned`

This resolver intentionally treats a missing desired pane as a supervision problem, not as normal offline state. CCB ask/job state is not an agent activity source; queued, running, completed, failed, retry, and callback status belongs in the Comms list. A job id may be used only as a correlation hint for Comms recoverability, never as authority for the top agent row.

### 8.3 Reason Codes

The sidebar should render only the five states and symbols by default. `activity_reason` exists for diagnostics, tests, and future tooltips.

Initial reason code set:

- Active: `provider_progress`, `provider_working`
- Pending: `agent_starting`, `pane_missing_recovering`, `namespace_reflowing`, `provider_waiting`, `health_unknown`, `runtime_busy_unverified`
- Idle: `pane_alive`, `provider_idle`
- Failed: `provider_failed`, `turn_aborted`, `reconcile_failed`, `runtime_fault`, `pane_recovery_failed`, `pane_missing_unowned`
- Offline: `agent_stopped`, `agent_unmounted`, `namespace_unmounted`

Reason codes should be stable enough for tests, but UI wording should not depend on displaying them in Phase 1.

For Claude and Codex:

- Claude has richer provider/session signals, but Phase 1 should still render the same simplified CCB task states.
- Codex is accurate for CCB tasks via job state, protocol-turn completion, session event logs, and runtime/pane health.
- Codex is not expected to expose fine-grained provider-internal states such as permission prompts, background shell state, or arbitrary manual user input without future enrichment.
- Manual provider interactions may be shown as weak provider/session activity when `ccbd` can observe user/assistant/session progress. They must not become job authority.

Provider activity expectations:

- Claude: user prompt/session activity can mark active; Stop can return to idle; Notification/Permission-style events can mark pending; StopFailure/abort can mark failed when available.
- Codex: user message and assistant chunks can mark active; `task_complete` can return to idle; `turn_aborted` can mark failed; long activity gaps can mark pending.

## 9. ProjectView Boundary

The sidebar must consume a normalized `ProjectView` exposed by `ccbd` RPC rather than assembled independently by the Rust TUI from many files.

Phase 1 `ProjectView` schema draft:

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-20T12:00:00Z",
  "project": {
    "id": "abc123",
    "root": "/home/bfly/yunwei/ccb_source",
    "display_name": "ccb_source"
  },
  "ccbd": {
    "state": "mounted",
    "health": "healthy",
    "generation": 7,
    "last_heartbeat_at": "2026-05-20T12:00:00Z"
  },
  "namespace": {
    "epoch": 4,
    "socket_path": "/home/bfly/yunwei/ccb_source/.ccb/ccbd/tmux.sock",
    "session_name": "ccb-abc123",
    "active_window": "main",
    "active_pane_id": "%12",
    "entry_window": "main",
    "sidebar": {
      "mode": "every_window",
      "width": "15%",
      "bottom_height": 20
    }
  },
  "windows": [
    {
      "name": "main",
      "order": 0,
      "tmux_window_id": "@1",
      "tmux_window_index": 0,
      "active": true,
      "sidebar_pane_id": "%10",
      "agents": ["agent1", "agent2", "agent3"]
    }
  ],
  "agents": [
    {
      "name": "agent1",
      "provider": "codex",
      "window": "main",
      "order": 0,
      "pane_id": "%11",
      "active": false,
      "activity_state": "active",
      "activity_symbol": "●",
      "activity_color": "green",
      "activity_source": "provider_pane",
      "activity_reason": "provider_working",
      "last_progress_at": "2026-05-20T12:00:00Z",
      "runtime_state": "busy",
      "runtime_health": "healthy",
      "reconcile_state": "steady",
      "workspace_path": "/home/bfly/yunwei/ccb_source"
    }
  ],
  "comms": [
    {
      "id": "job_abc123",
      "short_id": "a123",
      "created_at": "2026-05-20T11:59:00Z",
      "updated_at": "2026-05-20T12:00:00Z",
      "sender": "agent2",
      "target": "agent1",
      "status": "running",
      "execution_phase": "executing",
      "execution_phase_reason": "provider_active",
      "execution_evidence": {
        "job_id": "job_abc123",
        "attempt_job_id": "job_abc123",
        "completion_job_id": "job_abc123",
        "completion_anchor_seen": true,
        "provider_state": "active",
        "provider_identity_current": true
      },
      "callback": true,
      "short_reason": null
    }
  ]
}
```

Schema rules:

- fields listed under "Minimal Phase 1 payload fields" are required for the first usable implementation
- fields listed under "Recommended optional fields for Phase 1" may be omitted at first, but if present they must follow the same meanings and stable types
- `agents` is an ordered list, not a map. The order follows config traversal.
- `windows[].agents` stores agent names only; agent details live in the top-level `agents` list.
- `activity_state`, `activity_symbol`, `activity_color`, and `activity_reason` are computed by `ccbd`, not by the Rust sidebar.
- if optional `activity_symbol` or `activity_color` is omitted, the TUI may map from `activity_state` using the fixed Phase 1 status-symbol table; that is presentation mapping, not state recomputation.
- `activity_state` is one of `active`, `pending`, `idle`, `failed`, or `offline`.
- `activity_source` is one of `provider_signal`, `provider_pane`, `provider_prompt`, `pane_liveness`, `runtime_health`, `reconcile`, `namespace`, or `none`.
- `activity_source` identifies the winning resolver layer, while `activity_reason` gives the stable reason code.
- `last_progress_at` means the last known provider/runtime progress time used by the resolver. It may be null when no progress source exists.
- Top agent rows must not display CCB ask job ids or queue depth. Those are Comms fields.
- `reconcile_state` is exposed for diagnostics, but the TUI must not recompute status from it.
- `comms` is a compact business ask summary list, not a raw job or full event stream.
- each business ask appears at most once in `comms`; reply-delivery jobs only update the originating ask row's reply fields and must not be counted again as a separate receive row.
- reply-delivery folding should prefer structured CCB reply/attempt/message-origin records; parsing display body text such as `job=...` is only a compatibility fallback.
- reply-delivery jobs are folded into the originating ask row instead of appearing as `system -> agent`.
- `body_preview` carries a compact original ask preview for sidebar display.
- `body_preview` strips common instruction-only prefixes such as `Reply exactly:` and `只回复` before display.
- Comms renders as a fixed compact two-line row: `sender>target status_label`, then a cleaned single-line preview when present.
- Long previews are truncated to the Comms panel width instead of relying on terminal wrapping.
- minimal Comms rendering may show only `sender>target status_label` when optional preview fields are absent.
- `comms.status` follows CCB job status values: `accepted`, `queued`, `running`, `completed`, `cancelled`, `failed`, or `incomplete`.
- `comms.business_status` is the internal display phase, while `status_label` stays short for the sidebar: `send`, `work`, `back`, `done`, or `fail`.
- `comms.execution_phase` is an optional correlated projection and is one of `queued`, `injecting`, `executing`, `provider_idle_pending_terminal`, `reply_queued`, `reply_delivering`, `orphaned`, `terminal`, or `unknown`.
- when `execution_phase` is present, the sidebar prefers it for Comms status text and color; older producers may omit it, so the client falls back to `status_label`, `business_status`, and `status` in that order.
- `execution_phase_reason` is a stable diagnostic reason, and `execution_evidence` contains the compact job/attempt/inbound/mailbox/lease/completion/provider/reply identity facts used by `ccbd`; the sidebar must not rederive a phase from those facts.
- `active_inbound_diagnostic` is an optional bounded R8 envelope for `orphaned_active_inbound`. The sidebar deserializes its condition, reason, exact ids, observation window, manual recommendation, and `automatic_action=none`; it displays `condition:reason` and does not extend the observation window.
- `unknown` is the required fail-closed phase for missing, stale, contradictory, or non-exact identity evidence. `orphaned` is diagnostic and must not make the sidebar trigger automatic cancel, retry, restart, resend, or terminalization.
- the sidebar colors only the preferred compact phase or legacy status label: active execution is green, pending/delivery phases are yellow, terminal is blue, orphaned is red, and unknown is gray.
- normal terminal rows hide routine `short_reason` values such as `hook_stop` or `task_complete`; abnormal rows keep their short reason.

The TUI may inspect tmux only for its own pane identity or terminal sizing when needed. State rendering and focus changes should go through `ccbd`; the TUI should not scan arbitrary tmux sessions to create state.

## 10. ProjectView RPC Contract

### 10.1 Socket Operation

Phase 1 should add a read-only `ccbd` socket operation:

```json
{"api_version": 2, "op": "project_view", "request": {"schema_version": 1}}
```

Successful response payload:

```json
{
  "view": {},
  "cache": {
    "generated_at": "2026-05-20T12:00:00Z",
    "ttl_ms": 1000,
    "sequence": 42
  }
}
```

Minimal Phase 1 payload fields:

- `schema_version`
- `generated_at`
- `project.id`
- `project.root`
- `project.display_name`
- `ccbd.state`
- `ccbd.health`
- `namespace.epoch`
- `namespace.socket_path`
- `namespace.session_name`
- `namespace.active_window`
- `namespace.entry_window`
- `namespace.sidebar.mode`
- `namespace.sidebar.width`
- `namespace.sidebar.bottom_height`
- `windows[].name`
- `windows[].order`
- `windows[].agents`
- `agents[].name`
- `agents[].provider`
- `agents[].window`
- `agents[].order`
- `agents[].activity_state`
- `comms[].id`
- `comms[].sender`
- `comms[].target`
- `comms[].status`

Recommended optional fields for Phase 1:

- `ccbd.generation`
- `ccbd.last_heartbeat_at`
- `namespace.active_window_index`
- `namespace.active_pane_id`
- `windows[].tmux_window_id`
- `windows[].tmux_window_index`
- `windows[].active`
- `windows[].sidebar_pane_id`
- `agents[].pane_id`
- `agents[].active`
- `agents[].activity_symbol`
- `agents[].activity_color`
- `agents[].activity_source`
- `agents[].activity_reason`
- `agents[].last_progress_at`
- `agents[].runtime_state`
- `agents[].runtime_health`
- `agents[].reconcile_state`
- `agents[].workspace_path`
- `comms[].short_id`
- `comms[].created_at`
- `comms[].updated_at`
- `comms[].callback`
- `comms[].short_reason`
- `comms[].execution_phase`
- `comms[].execution_phase_reason`
- `comms[].execution_evidence`
- `comms[].active_inbound_diagnostic`

Rules:

- `project_view` is a non-mutating operation.
- It must not trigger an extra dispatcher tick, provider poll, recovery action, namespace reflow, or tmux mutation.
- It should run through the existing `CcbdClient` JSON-line socket protocol.
- It should reuse the mounted project socket path already known to `ccb`/sidebar startup.
- It returns one snapshot for the current project only.
- It should fail with the normal `ccbd` RPC failure envelope when the backend is unavailable or the request is malformed.
- The request may include `schema_version`; unsupported major schema versions should fail clearly.

The Python client should grow a convenience method equivalent to:

```python
client.project_view(schema_version=1)
```

The Rust sidebar may either call the socket protocol directly or use a small CCB adapter process/library, but it must treat the returned payload as the source of truth.

### 10.2 Refresh Model

Phase 1 refresh should be polling, not streaming.

Recommended defaults:

- normal poll interval: `1000ms`
- fast poll interval after keyboard focus/switch action: `250ms` for one refresh
- RPC timeout: `500ms` for sidebar UI calls
- first failure backoff: `2000ms`
- repeated failure backoff: `5000ms`
- explicit refresh remains available through terminal redraw / `Ctrl-L`; normal
  ProjectView freshness is polling-driven

Rationale:

- the sidebar should feel current without putting constant pressure on `ccbd`
- `ccbd` heartbeat/reconcile already runs independently
- Phase 1 does not need long-lived watch subscriptions

`cache.sequence` is a monotonic `ccbd` ProjectView sequence number for UI diffing. It increments when the generated view content changes. The TUI may skip redraw when the sequence is unchanged.

`cache.ttl_ms` tells the sidebar when the snapshot should be considered fresh. It is advisory; the sidebar may keep showing stale data when the backend is temporarily unavailable. Because focus can change outside the sidebar by normal tmux window navigation, the sidebar caps its own refresh interval below the ProjectView TTL so the header and active window rows follow cross-window focus quickly.

### 10.3 Sidebar Degraded Display

The sidebar should keep the last good ProjectView in memory.

If `project_view` fails:

- keep rendering the last good window/agent tree
- mark the header as degraded, for example `ccbd ✕`
- do not change agent rows to failed/offline just because one RPC failed
- show an empty or stale-marked Comms area rather than raw error logs
- retry using the backoff schedule

If there is no last good ProjectView:

- render a minimal degraded screen with the project name if known
- show `ccbd ✕`
- show no agent rows unless they came from a successful ProjectView

If the backend returns a valid ProjectView where `namespace` is unmounted or unavailable:

- render the header state from ProjectView
- render agent states from ProjectView
- do not invent local fallback states in the TUI

### 10.4 Focus And Switch Operations

Phase 1 navigation requires focus/switch actions, but not arbitrary tmux control.

Recommended RPC operations:

```json
{"api_version": 2, "op": "project_focus_window", "request": {"window": "main", "namespace_epoch": 4}}
{"api_version": 2, "op": "project_focus_agent", "request": {"agent": "agent1", "namespace_epoch": 4}}
```

Successful response payload:

```json
{
  "focused": true,
  "kind": "agent",
  "window": "main",
  "agent": "agent1",
  "namespace_epoch": 4,
  "tmux_window_id": "@1",
  "pane_id": "%11"
}
```

For `project_focus_window`, `kind` is `window` and `agent` may be null. For `project_focus_agent`, `kind` is `agent`.

Rules:

- focus operations change tmux focus only; they do not mutate CCB job, runtime, config, or namespace ownership state.
- they should be treated as UI navigation operations, not lifecycle/job mutations that force an immediate heartbeat, provider poll, or reconcile tick.
- request routing uses logical `window` or `agent` names plus optional `namespace_epoch`; the sidebar does not need pane ids in the minimal ProjectView payload to request focus.
- they must target only configured managed windows or configured managed agents from the current ProjectView/config.
- they must use only the project-owned tmux socket/session.
- they must reject manual panes, unknown windows, unknown agents, stale namespace epochs, and mismatched project ids.
- `project_focus_window` should select the tmux window and then focus the last focused managed agent pane in that window when known; otherwise the first configured managed agent in that window.
- `project_focus_agent` should select the agent's configured tmux window and then focus the agent pane.
- if the target pane disappeared, the operation should fail clearly and rely on supervision/reconcile to recover it. It should not create a replacement pane.

The request may include an optional `namespace_epoch` from the current ProjectView. If supplied and stale, the handler should reject with a stale-view error so the sidebar refreshes before retrying.

Focus error codes:

| Code | Meaning | Sidebar behavior |
| --- | --- | --- |
| `stale_view` | supplied `namespace_epoch` does not match current namespace epoch | refresh ProjectView and retry the original focus action once |
| `namespace_unavailable` | project namespace is not mounted or tmux session/socket is unavailable | keep current selection, mark header degraded, resume normal polling |
| `unknown_window` | requested window is not in current config | refresh ProjectView; if still absent, keep current selection |
| `unknown_agent` | requested agent is not in current config | refresh ProjectView; if still absent, keep current selection |
| `unmanaged_target` | target exists in tmux but is not CCB-managed | reject silently or show a short status message; do not focus it |
| `target_missing` | configured target pane/window is missing in tmux | refresh ProjectView and let supervision/reconcile repair; do not create panes |
| `tmux_focus_failed` | tmux select-window/select-pane command failed for an otherwise valid target | keep current selection, refresh ProjectView, surface a short degraded hint |
| `invalid_request` | request shape is malformed or missing required fields | treat as sidebar bug; log locally and keep current selection |

Error response shape should fit the existing `ccbd` RPC failure envelope, but the error string or payload must preserve the stable code. Recommended payload shape if the protocol is extended:

```json
{
  "ok": false,
  "error": "stale_view",
  "payload": {
    "code": "stale_view",
    "message": "ProjectView namespace epoch is stale",
    "current_namespace_epoch": 5
  }
}
```

Focus retry rules:

- retry at most once after `stale_view`
- do not retry `invalid_request`
- do not retry `unmanaged_target`
- do not retry `target_missing` until a later ProjectView shows the target as available again
- after any successful focus response, trigger one fast ProjectView refresh using the `250ms` fast refresh interval

### 10.5 CLI Surface

No user-facing CLI command is required for Phase 1.

Internal or debug-only helpers may exist during development, but the product surface remains:

- `ccb` starts/attaches the project namespace
- the sidebar pane runs inside managed project windows
- the sidebar talks to `ccbd` through internal RPC

If a debug command is added later, prefer a hidden or explicit diagnostic form such as `ccb debug project-view --json` rather than a main workflow command.

## 11. Interaction

Keyboard Phase 1:

- `j` / `Down`: move selection down
- `k` / `Up`: move selection up
- `Enter`: switch to selected window or selected agent pane
- `Tab`: move focus between sidebar and the last focused managed pane in the same window when possible
- `r`: deliberately restart configured agent panes through `ccbd`
- `Ctrl-L`: force an immediate ProjectView refresh

Header controls:

- `⚙`: launch the current project's loopback-only `ccb config ui`
- `×`: kill the current project

Both controls share the same mouse-down routing and right-aligned hit-test
surface. The settings action additionally launches an asynchronous child and
must therefore expose `opening`, ready URL, browser-open fallback, and process
failure states instead of silently suppressing a second click while its child
is active. The project tmux environment must carry desktop and WSL interop
state into the sidebar. WSL host openers (`wslview`, then Windows shell
fallbacks) and macOS `open` take priority over the generic Python browser
registry, and an opener counts as successful only after it avoids an immediate
non-zero exit.

Restart is intentionally keyboard-only because it is disruptive and should not
share the prominent header click surface with ordinary settings access.

Window row behavior:

- selecting a window row and pressing `Enter` switches to that window
- focus should land on the last focused managed agent pane in that window when known
- if no previous managed focus is known, focus should land on the first managed agent pane in that window

Mouse behavior:

- click window row: switch to that window
- click agent row: switch to that agent pane
- scroll inside sidebar: deferred

All mutating project actions other than focus/switch navigation remain deferred.

## 12. Architecture

Recommended source placement:

```text
tools/
  ccb-agent-sidebar/
    Cargo.toml
    src/
      main.rs
      args.rs
      app.rs
      client.rs
      model.rs
      render.rs
      input.rs
      theme.rs
      widgets/
        mod.rs
        tree.rs
        comms.rs
        status.rs
      tests/
        fixtures/
    README.md
    LICENSE.upstream
```

Release packaging:

- the source lives in-repo for development and review
- the built `ccb-agent-sidebar` binary is shipped in the CCB release at `bin/ccb-agent-sidebar`
- Phase 1 release automation publishes the Linux x86_64 helper tarball and ships a macOS universal helper inside `ccb-macos-universal.tar.gz`
- managed sidebar panes should launch the release-bundled binary
- users should not need a Rust toolchain or upstream plugin install to use Phase 1
- release/build tests should verify the sidebar binary is included and discoverable by the runtime launcher

Sidebar launch arguments:

```text
ccb-agent-sidebar --ccbd-socket <path> --project-root <path> --pane-window <name>
```

- `--ccbd-socket` points at the project-owned `ccbd` socket
- `--project-root` identifies the current project anchor
- `--pane-window` identifies the managed window whose sidebar pane is being launched
- additional flags should be avoided in Phase 1 unless they are required for deterministic startup

The code should split into:

```text
TUI layer
  render ProjectView
  manage local sidebar selection/scroll/popups
  handle keyboard input first; keep the input layer suitable for future mouse support

CCB adapter layer
  fetch ProjectView through `project_view`
  request focus/switch through `project_focus_window` and `project_focus_agent`
  keep a last-good ProjectView cache for degraded rendering
  apply polling/backoff policy

ccbd focus handler layer
  execute project-socket-only focus/window commands inside ccbd handlers
  keep tmux mutation out of the Rust TUI process
```

Sidebar pane instances:

- share project data through the same `ProjectView`
- keep local cursor/scroll/popup state per sidebar pane
- may share global focused window/agent because that is namespace state

### 12.1 Rust Module Boundaries

`main.rs`:

- parse launch arguments
- initialize terminal
- create the CCB client and app state
- run the event loop
- restore terminal on exit

`args.rs`:

- parse exactly `--ccbd-socket`, `--project-root`, and `--pane-window`
- validate required arguments
- keep future flags out unless required for deterministic startup

`model.rs`:

- define `ProjectView`, `WindowView`, `AgentView`, `CommsItem`, and cache metadata structs
- deserialize the `project_view` payload
- provide small helpers for fixed status-symbol/color presentation mapping
- avoid reading local CCB files or tmux state

`client.rs`:

- implement the JSON-line Unix socket RPC client
- call `project_view`
- call `project_focus_window`
- call `project_focus_agent`
- normalize focus errors into stable Rust enums
- own request timeout and retry/backoff policy inputs, but not UI state

`app.rs`:

- own last-good ProjectView
- own local cursor, scroll offsets, selected row, and refresh schedule
- handle degraded state when RPC fails
- decide whether Enter means focus window or focus agent
- perform one fast refresh after successful focus

`input.rs`:

- map keyboard events into app actions
- Phase 1 supports `j`, `k`, arrows, `Enter`, `Tab`, `r`, and left-click focus on window/agent rows
- keep mouse event parsing isolated from rendering and backend RPC code

`render.rs` and `widgets/*`:

- render the top window/agent tree
- render simplified status symbols
- render the Comms feed or empty placeholder
- render degraded header state
- avoid business logic beyond presentation mapping

`theme.rs`:

- define color/style constants for the five activity states
- keep the palette small and readable in tmux

### 12.2 Upstream Code Treatment

Keep or adapt:

- ratatui terminal setup and teardown patterns
- list navigation patterns
- keyboard event loop structure
- mouse hit-testing for window/agent row focus
- status/icon style helpers when they fit the simplified state model

Delete or replace:

- provider hook setup and hook event readers
- global tmux pane/window/session scanning
- upstream `@pane_status` authority
- upstream worktree lifecycle actions
- upstream notification ownership
- upstream plugin install/toggle lifecycle
- direct tmux focus from Rust
- mutating actions such as ask/cancel/restart/reflow

The fork should compile without upstream provider hook commands or TPM/plugin assumptions.

### 12.3 Rust Test Plan

Unit tests:

- deserialize minimal `project_view` payload
- deserialize full optional `project_view` payload
- map `activity_state` to fixed symbol/color when optional symbol/color are omitted
- preserve server-provided symbol/color when present
- build row order from `windows[].agents` plus top-level `agents`
- selection moves over expanded window/agent rows
- Enter on a window row calls `project_focus_window`
- Enter on an agent row calls `project_focus_agent`
- `stale_view` triggers exactly one refresh-and-retry
- `target_missing` does not retry until a later ProjectView says the target is available
- RPC failure keeps last-good ProjectView
- no-last-good degraded state renders without panicking

Fixture tests:

- minimal one-window/three-agent ProjectView
- multi-window ProjectView
- degraded `ccbd` header case
- empty Comms feed
- Comms feed with minimal fields only

Integration smoke tests:

- fake Unix socket server returns ProjectView and records focus requests
- sidebar can start with required launch args and perform one refresh
- release packaging includes `bin/ccb-agent-sidebar`

Deferred tests:

- mouse click routing
- ask/cancel/restart controls
- multi-project dashboard

## 13. Python Backend Implementation Slices

The backend should land before the Rust TUI becomes the main integration target. Each slice should be independently testable.

Dependency rule:

- config topology is the first real implementation slice
- ProjectView may be prototyped with fixtures, but production ProjectView must consume normalized config topology
- Rust TUI integration should wait until `project_view` and focus RPC have stable tests

Contract update rule:

- when the config topology slice is implemented, promote the relevant config grammar from this plan into [docs/ccb-config-layout-contract.md](ccb-config-layout-contract.md)
- when namespace materialization or focus RPC is implemented, update [docs/ccbd-startup-supervision-contract.md](ccbd-startup-supervision-contract.md)
- when updating startup/supervision contract for this work, align command wording with the current user-facing entry path: `ccb` creates/attaches the project namespace; do not introduce `ccb open` as a required surface for Phase 1
- when ProjectView becomes a supported diagnostics/read path, update [docs/ccbd-diagnostics-contract.md](ccbd-diagnostics-contract.md) if `doctor` or support bundles expose it
- when release packaging lands, update release/build documentation and tests in the same patch

### 13.1 Config Topology Slice

Owned areas:

- `agents.models`
- `agents.config_loader_runtime`
- config identity/signature helpers
- config rendering/default generation
- config validation tests

Target model:

```text
ProjectConfig
  version: int
  default_agents: tuple[str, ...]             # compatibility/default target order
  agents: dict[str, AgentSpec]
  cmd_enabled: bool                           # legacy compatibility only
  layout_spec: str | None                     # legacy compatibility only
  windows: tuple[WindowSpec, ...]             # normalized topology authority
  entry_window: str
  sidebar: SidebarSpec
  source_path: str | None

WindowSpec
  name: str
  order: int
  layout_spec: str                            # user layout only, no sidebar leaf
  agent_names: tuple[str, ...]                # traversal order from layout

SidebarSpec
  mode: "every_window" | "off"
  width: str | int                            # `"15%"` or fixed columns
  bottom_height: int
```

Normalization invariants:

- `windows` is the only topology authority after config load.
- `default_agents` remains as compatibility/default target order and should match the config traversal of `windows`.
- legacy `cmd_enabled` and `layout_spec` may remain in `ProjectConfig` for old call sites, but new namespace/sidebar code must read `windows`.
- `WindowSpec.layout_spec` never includes the projected sidebar pane.
- `WindowSpec.agent_names` contains only configured agent names, no `cmd`.
- `SidebarSpec` defaults are applied during load even when absent from config text.

Input forms:

- legacy compact layout text
- existing rich TOML fields: `version`, `default_agents`, `agents`, `cmd_enabled`, `layout`
- new rich TOML topology fields: `ui.sidebar`, `windows`, `entry_window`

Legacy normalization:

1. parse compact or existing rich config with the current parser path
2. parse the resulting `layout_spec`
3. drop any `cmd` leaf
4. validate that at least one agent leaf remains
5. create one `WindowSpec(name="main", layout_spec=<layout without cmd>, agent_names=<agent leaves>)`
6. set `entry_window="main"`
7. apply sidebar defaults
8. preserve legacy fields for compatibility

New topology normalization:

1. parse `windows` as an ordered mapping
2. validate window names and preserve config order
3. parse each window layout with the existing layout parser
4. reject `cmd` leaves
5. collect agent leaves and provider declarations
6. build or validate `AgentSpec` records from the layout leaves
7. reject duplicate agent names across all windows
8. default `entry_window` to the first configured window
9. validate explicit `entry_window`
10. apply sidebar defaults and validate `SidebarSpec`

Migration compatibility:

- if new `windows` topology is present, it is authoritative
- if `windows` topology is present, `layout` and `cmd_enabled` should be rejected or ignored only after a deliberate migration decision; Phase 1 should prefer clear validation failure for mixed old/new topology
- legacy compact and existing rich config still load through the compatibility path
- render/default generation for missing config should emit the new topology form with `main`

Topology signature payload:

```json
{
  "version": 1,
  "windows": [
    {
      "name": "main",
      "order": 0,
      "layout": "agent1:codex,agent2:codex,agent3:claude",
      "agents": ["agent1", "agent2", "agent3"]
    }
  ],
  "entry_window": "main",
  "sidebar": {
    "mode": "every_window",
    "width": "15%",
    "bottom_height": 20
  }
}
```

Signature rules:

- use normalized rendered layout strings, not raw config text
- preserve ordered windows
- preserve agent traversal order per window
- include `entry_window`
- include sidebar mode, width, and bottom height
- do not include runtime pane ids, tmux window ids, namespace epoch, or current focus
- do not include legacy `cmd_enabled` after it has been normalized away
- hash or stable-json encode this payload for namespace layout comparison

Suggested implementation layout:

```text
lib/agents/models_runtime/config_runtime/topology.py
  WindowSpec
  SidebarSpec
  ProjectTopology helpers

lib/agents/config_loader_runtime/parsing_runtime/topology.py
  parse_new_topology_document
  normalize_legacy_topology
  validate_window_name

lib/agents/config_identity.py
  include topology signature payload
```

Work:

- add `WindowSpec` and `SidebarSpec` model types
- extend `ProjectConfig` with ordered `windows`, `entry_window`, and `ui.sidebar`
- extend rich-config allowed top-level keys with `ui`, `windows`, and `entry_window`
- keep legacy `layout_spec` and `cmd_enabled` compatibility during migration
- normalize legacy compact config into one `main` window while ignoring legacy `cmd`
- resolve missing config as built-in `main` with `agent1`, `agent2`, `agent3`,
  and `ccb_self`
- reject `cmd` inside new rich `windows`
- reject duplicate agent leaves across windows
- validate Phase 1 window names with `^[A-Za-z][A-Za-z0-9_-]*$`
- compute topology signature from ordered windows, normalized layouts, `entry_window`, and sidebar settings

Tests:

Parser/model tests:

- missing config generates `main` with `agent1:codex`, `agent2:codex`, and `agent3:claude`
- compact config with `cmd` normalizes to `main` without `cmd`
- existing rich TOML `layout` normalizes to one `main` window
- new topology config with multiple windows preserves window order
- new topology config builds `AgentSpec` provider declarations from agent leaves
- new rich topology `windows` with `cmd` fails
- duplicate agent across windows fails
- invalid window name fails
- provider missing from an agent leaf fails
- `entry_window` missing defaults to first window
- `entry_window` unknown fails
- sidebar defaults are applied but not required in config text
- sidebar `off` validates and produces no projected sidebar requirement
- sidebar width validates both `"15%"` and fixed integer columns
- negative `bottom_height` fails

Signature tests:

- topology signature changes when window order changes
- topology signature changes when a window layout changes
- topology signature changes when an agent moves windows
- topology signature changes when `entry_window` changes
- topology signature changes when sidebar mode/width/bottom-height changes
- topology signature does not change when raw formatting/comments change but normalized topology is identical
- topology signature does not include runtime pane ids or current focus

Compatibility tests:

- old compact config still renders/loads for existing non-sidebar code paths
- mixed new `windows` plus old `layout` fails clearly
- legacy `cmd_enabled=true` does not leak into normalized `windows`
- `default_agents` follows normalized topology traversal order

### 13.2 Namespace Materialization Slice

Owned areas:

- `ccbd.services.project_namespace`
- `ccbd.start_flow_runtime`
- `cli.services.tmux_start_layout` or its replacement path for multi-window plans
- tmux UI/project cleanup tests

Work:

- introduce a window materialization plan derived from normalized config
- create managed tmux windows in config order
- project the sidebar pane into each managed window when sidebar mode is `every_window`
- materialize each window's agent layout next to the sidebar pane
- tag managed panes with `@ccb_role`, `@ccb_window`, `@ccb_slot`, `@ccb_sidebar_instance`, and `@ccb_namespace_epoch`
- record `tmux_window_id` and `tmux_window_name` in runtime binding where needed
- select `entry_window` after materialization
- recreate namespace on topology signature changes
- do not preserve unmanaged/manual panes during namespace recreate

Materialization model:

```text
NamespaceMaterializationPlan
  session_name: str
  socket_path: str
  topology_signature: str
  entry_window: str
  windows: tuple[WindowMaterializationPlan, ...]

WindowMaterializationPlan
  name: str
  order: int
  user_layout: LayoutNode
  realized_layout: LayoutNode
  sidebar: SidebarPanePlan | None
  agents: tuple[AgentPanePlan, ...]

SidebarPanePlan
  window_name: str
  width: str | int
  bottom_height: int
  launch_command: tuple[str, ...]

AgentPanePlan
  agent_name: str
  provider: str
  slot_key: str
  window_name: str
```

Materialization flow:

1. compute normalized topology signature
2. ensure/recreate project tmux session if signature changed
3. create tmux windows in config order
4. for each window, create a silent placeholder root pane
5. if sidebar is enabled, split sidebar as the left pane using configured width
6. materialize the user layout in the remaining area
7. assign agent panes by logical leaf name, not tmux pane order alone
8. launch or bind agent runtimes into their assigned panes
9. launch sidebar pane with `bin/ccb-agent-sidebar --ccbd-socket <path> --project-root <path> --pane-window <name>`
10. apply pane options and visible labels after panes exist
11. select `entry_window`
12. persist namespace state with window ids, sidebar pane ids, layout signature, and epoch

Sizing rules:

- percentage sidebar width applies to the tmux window width
- fixed sidebar width uses columns
- minimum sidebar width is `24` columns when possible
- if a window is too narrow, prefer truncation over startup failure
- `bottom_height` is reserved for sidebar internal layout only; it does not change tmux pane geometry

Ownership rules:

- managed tmux windows are exactly the normalized config windows
- manual panes are not part of the materialization plan
- unmanaged panes may be destroyed during recreate
- sidebar pane death is repaired by namespace reconciliation, not agent recovery
- agent pane death is repaired by existing runtime supervision in its configured window

Suggested implementation layout:

```text
lib/ccbd/services/project_namespace_runtime/materialization.py
  NamespaceMaterializationPlan
  WindowMaterializationPlan
  build_namespace_materialization_plan

lib/ccbd/services/project_namespace_runtime/window_ops.py
  create_or_select_window
  materialize_window_layout
  tag_managed_panes

lib/ccbd/services/project_namespace_runtime/sidebar.py
  sidebar_launch_command
  sidebar_width_to_tmux_size
```

Tests:

Plan tests:

- one `main` window with three agents creates one window plan with sidebar plus agent leaves
- multiple windows are planned in config order
- sidebar enabled inserts sidebar outside the user layout
- sidebar disabled leaves realized layout equal to user layout
- launch command uses `bin/ccb-agent-sidebar` and exactly the documented args
- `bottom_height` does not affect tmux split geometry

tmux materialization tests:

- one `main` window with three agents and sidebar is materialized
- multiple windows are created in config order
- each window receives exactly one sidebar pane when enabled
- sidebar disabled mode creates no sidebar panes
- panes get `@ccb_role`, `@ccb_window`, and slot/sidebar options
- `entry_window` is selected after startup

Recovery/recreate tests:

- agent runtime records include configured window identity
- topology signature change recreates namespace
- sidebar pane death triggers sidebar reconciliation, not agent failure
- agent pane recovery restores into the configured window
- manual panes are not included in ProjectView and are not preserved across recreate

### 13.3 ProjectView Slice

Owned areas:

- new `ccbd` ProjectView service/module
- `ccbd.handlers`
- `CcbdClient`
- socket tests

Work:

- add ProjectView dataclasses or serialization helpers
- add read-only `project_view` handler
- add `CcbdClient.project_view(schema_version=1)`
- generate minimal Phase 1 payload first
- compute activity state through the resolver in this plan
- build `windows` and `agents` from normalized config plus runtime/namespace state
- build minimal `comms` from CCB job/message records
- return cache metadata with `generated_at`, `ttl_ms`, and `sequence`
- keep generation read-only and side-effect free

Service inputs:

- normalized `ProjectConfig.windows`
- `ProjectNamespaceStateStore`
- active tmux namespace inspection limited to the project socket/session
- `AgentRegistry` runtime records
- dispatcher/job state
- message/job stores for compact Comms rows
- optional provider/session signals already normalized by `ccbd`
- supervision/reconcile state

Service output:

```text
ProjectViewResponse
  view: ProjectView
  cache: ProjectViewCache

ProjectViewCache
  generated_at: str
  ttl_ms: int
  sequence: int
```

Sequence rules:

- sequence is scoped to the current daemon generation
- sequence increments when the stable serialized `view` content changes
- sequence does not need to increment when only `cache.generated_at` changes
- a daemon restart may reset sequence to `1`
- sidebar must not rely on sequence for authority; it is only redraw optimization

Minimal payload construction:

- `project` comes from `project_root` and `project_id`
- `ccbd.state` and `ccbd.health` come from mounted/backend inspection
- `namespace` comes from persisted namespace state plus current focus inspection when available
- `windows` are emitted from normalized config order
- `agents` are emitted in config traversal order
- `activity_state` is always present for each configured agent
- `comms` may be empty

Activity resolver implementation notes:

- implement resolver as a pure function over a small `AgentActivityFacts` struct
- do not let the Rust TUI inspect `runtime_state` to recompute status
- keep `activity_reason/source` optional in payload but available internally for tests
- stale active jobs use `active_stale_after`
- recent terminal failures use `failed_visible_for`
- pane missing under active recovery maps to `pending`
- pane missing without recovery owner maps to `failed`

Suggested implementation layout:

```text
lib/ccbd/project_view/models.py
  ProjectView
  WindowView
  AgentView
  CommsView
  ProjectViewCache

lib/ccbd/project_view/service.py
  ProjectViewService
  build_project_view

lib/ccbd/project_view/activity.py
  AgentActivityFacts
  resolve_agent_activity

lib/ccbd/project_view/sequence.py
  ProjectViewSequenceCache

lib/ccbd/handlers/project_view.py
  build_project_view_handler
```

Tests:

Service tests:

- `project_view` returns minimal schema for default config
- `project_view` returns windows in normalized config order
- `project_view` returns agents in config traversal order
- `project_view` does not call recovery/reflow/provider polling
- `activity_symbol/color` may be omitted while `activity_state` remains present
- Comms rows include original ask `id`, `sender`, `target`, raw `status`, display `status_label`, and compact `body_preview`

Resolver tests:

- queued/accepted job maps to pending
- running job with progress maps to active
- running stale job maps to pending
- recent failed/incomplete/cancelled job maps to failed
- completed job with healthy pane maps to idle
- `pane_missing` with active recovery maps to pending
- `pane_missing` without recovery owner maps to failed
- intentionally stopped/unmounted agent maps to offline

Cache tests:

- `cache.sequence` is stable when view content is unchanged
- `cache.sequence` changes when window/agent/activity/comms content changes
- `cache.sequence` ignores only `cache.generated_at`
- daemon restart may reset sequence without breaking schema

### 13.4 Focus RPC Slice

Owned areas:

- `ccbd.handlers`
- `CcbdClient`
- project namespace focus helpers
- tmux backend action tests

Work:

- add `project_focus_window` handler
- add `project_focus_agent` handler
- add `CcbdClient.project_focus_window(...)`
- add `CcbdClient.project_focus_agent(...)`
- validate logical window/agent targets against normalized config
- reject stale `namespace_epoch`
- select tmux window/pane through the project-owned tmux socket/session only
- never create panes from focus handlers
- return stable success payload and stable error codes

Handler flow:

`project_focus_window`:

1. validate request shape and logical window name
2. load normalized config and namespace state
3. reject stale `namespace_epoch` when supplied
4. find `WindowSpec`
5. inspect project tmux socket/session for that managed tmux window
6. select tmux window
7. focus last focused managed agent pane in that window when known
8. otherwise focus first configured agent pane in that window
9. return success payload

`project_focus_agent`:

1. validate request shape and logical agent name
2. load normalized config and namespace state
3. reject stale `namespace_epoch` when supplied
4. find the agent's `WindowSpec`
5. inspect project tmux socket/session for the agent pane
6. select tmux window
7. select tmux pane
8. return success payload

Focus helper requirements:

- resolve targets by CCB-managed pane options, not by visible pane title alone
- verify `@ccb_project_id`, `@ccb_role`, `@ccb_window`, and `@ccb_slot`
- never select a pane whose options do not match current project/config authority
- use the project-owned tmux socket path from namespace state
- return `target_missing` when the logical target is configured but no matching tmux pane/window exists

Error implementation:

- keep stable error codes as constants
- if the current RPC protocol only supports string errors, encode the stable code at the start of the error string
- when protocol payload errors are added, include `code`, `message`, and optional diagnostic fields
- do not expose raw tmux command stderr as the stable code

Suggested implementation layout:

```text
lib/ccbd/project_focus/models.py
  FocusErrorCode
  FocusSuccess

lib/ccbd/project_focus/service.py
  focus_window
  focus_agent

lib/ccbd/project_focus/tmux.py
  inspect_managed_windows
  select_managed_window
  select_managed_agent_pane

lib/ccbd/handlers/project_focus.py
  build_project_focus_window_handler
  build_project_focus_agent_handler
```

Tests:

Handler tests:

- focus window selects configured window
- focus window falls back to first agent pane when last focused pane is unknown
- focus agent selects configured window and agent pane
- success payload includes `focused`, `kind`, `window`, `agent`, and `namespace_epoch`
- stale namespace epoch returns `stale_view`
- unknown window/agent return stable errors
- missing target returns `target_missing`
- namespace missing returns `namespace_unavailable`
- unmanaged tmux pane cannot be focused

Side-effect tests:

- focus handlers do not trigger provider polling
- focus handlers do not trigger runtime reconciliation
- focus handlers do not create panes
- focus handlers do not mutate runtime records except optional last-focused UI metadata if that is later added

### 13.5 Sidebar Launch And Packaging Slice

Owned areas:

- release/build packaging scripts
- namespace sidebar pane launcher
- runtime path resolution
- release tests

Work:

- build `tools/ccb-agent-sidebar` as part of release
- package it as `bin/ccb-agent-sidebar`
- resolve release-bundled helper path at runtime
- launch sidebar panes with `--ccbd-socket`, `--project-root`, and `--pane-window`
- mark sidebar panes as managed sidebar panes
- ensure `ccb kill` tears down sidebar panes with the namespace

Runtime path resolution:

- release install path should expose `bin/ccb-agent-sidebar`
- development checkout resolves repository `bin/ccb-agent-sidebar` or an explicit `CCB_AGENT_SIDEBAR_BIN`
- `PATH` is accepted only as the last discovery source
- namespace materialization should keep the sidebar pane alive with a visible short error when sidebar mode is enabled but no helper binary is discoverable
- helper discovery must not download or install upstream tools at runtime

Sidebar pane command:

```text
<helper> --ccbd-socket <ccbd_socket_path> --project-root <project_root> --pane-window <window_name>
```

Pane setup:

- sidebar pane starts as a managed CCB pane, not a user shell
- pane options include `@ccb_role=sidebar`
- pane options include `@ccb_sidebar_instance=<window_name>`
- pane options include `@ccb_window=<window_name>`
- visible pane label should be stable, for example `sidebar`
- sidebar pane death should be reconciled without marking any agent failed

Suggested implementation layout:

```text
lib/ccbd/services/project_namespace_runtime/sidebar.py
  resolve_sidebar_helper
  sidebar_launch_command
  sidebar_pane_options

release/build scripts
  build tools/ccb-agent-sidebar
  copy binary to bin/ccb-agent-sidebar
```

Tests:

- release artifact contains `bin/ccb-agent-sidebar`
- launcher resolves bundled helper path
- missing helper fails clearly when sidebar mode is enabled
- sidebar pane command contains only the documented Phase 1 arguments
- sidebar panes are tagged with `@ccb_role=sidebar`
- sidebar panes are tagged with `@ccb_sidebar_instance`
- kill destroys sidebar panes with the project namespace

## 14. Execution Work Packages

These work packages are the recommended implementation order. Each package should leave the tree testable before the next starts.

### 14.1 WP1 Config Topology

Status: implemented in the first sidebar integration slice.

Current implementation notes:

- `ProjectConfig` now normalizes `windows`, `entry_window`, `sidebar`, and `topology_signature` for both legacy compact config and new TOML topology config.
- New missing-config bootstrap uses the built-in topology shape:
  - `entry_window = "main"`
  - `[windows] main = "demo:<first-available-provider>"`
- Existing compact configs remain accepted and are normalized into one logical `main` window with the legacy `cmd` leaf pruned out of `ProjectConfig.windows`.
- New TOML `windows` topology rejects `cmd`, duplicate agents across windows, missing provider declarations, unknown `entry_window`, mixed `layout`, mixed `cmd_enabled`, and explicit `default_agents`.
- Explicit `windows` config may still use `[agents.<name>]` for richer agent fields, but the provider declared in that table must not conflict with the provider declared in the window leaf.
- Focused coverage currently lives in `test/test_v2_config_loader.py`; the related layout regressions remain covered by `test/test_v2_layout_plan.py` and `test/test_agents_layout_runtime.py`.

Primary write scope:

- `lib/agents/models_runtime/config_runtime/project.py`
- `lib/agents/models_runtime/config_runtime/topology.py`
- `lib/agents/models_runtime/config_runtime/__init__.py`
- `lib/agents/models_runtime/config.py`
- `lib/agents/models.py`
- `lib/agents/config_loader_runtime/common.py`
- `lib/agents/config_loader_runtime/parsing_runtime/validation.py`
- `lib/agents/config_loader_runtime/parsing_runtime/topology.py`
- `lib/agents/config_loader_runtime/defaults_runtime/`
- `lib/agents/config_identity.py`
- `docs/ccb-config-layout-contract.md`

Primary tests:

- `test/test_v2_config_loader.py`
- `test/test_v2_layout_plan.py`
- new focused tests if needed: `test/test_v2_config_topology.py`

Exit criteria:

- existing compact configs still pass
- new TOML `windows` topology loads and normalizes
- `ProjectConfig.windows`, `entry_window`, and `sidebar` exist for all loaded configs
- topology signature is stable and covered by tests
- `docs/ccb-config-layout-contract.md` documents the promoted grammar

Do not include:

- tmux namespace materialization
- ProjectView RPC
- Rust sidebar source

### 14.2 WP2 Namespace Materialization

Status: tmux materialization, runtime/window metadata, helper resolution, missing-sidebar full-recreate, and Linux sidebar release-artifact workflow slices implemented.

Current implementation notes:

- `lib/ccbd/services/project_namespace_runtime/topology_plan.py` derives a pure namespace topology plan from normalized `ProjectConfig.windows` and `ProjectConfig.sidebar`.
- The plan emits config-ordered window plans, logical user layouts, realized layouts with projected sidebar leaves, and sidebar launch arguments for `ccb-agent-sidebar --ccbd-socket ... --project-root ... --pane-window ...`.
- Sidebar `off` leaves realized layouts equal to user layouts; sidebar `every_window` inserts the sidebar outside the user layout.
- Interactive namespace lifecycle now uses `ProjectConfig.topology_signature` as the namespace layout signature, so requested foreground agent subsets no longer redefine long-lived namespace topology.
- `ProjectNamespaceController.ensure(topology_plan=...)` materializes configured tmux windows in config order, renames the first window, creates additional managed windows, projects sidebar panes for `every_window`, tags sidebar panes with `@ccb_role=sidebar`, `@ccb_window`, and `@ccb_sidebar_instance`, and selects `entry_window`.
- `start_flow` now materializes explicit window topology per managed window root, so agents in later windows are launched in their configured window instead of being pruned against only the first layout.
- `start_flow` records project-namespace scaffold panes before orphan cleanup, so sidebar panes and command/user-root panes created by namespace materialization are not killed as stale start-flow residue.
- CCB pane identity now carries optional `@ccb_window`; reused project-namespace bindings remain backward compatible with older panes that lack this option.
- Agent runtime records and startup agent results now persist configured `tmux_window_name`; `tmux_window_id` is available as a non-authoritative optional fact but is not required to drive topology.
- `ProjectView.windows` now best-effort exposes tmux window ids, tmux window indexes, and sidebar pane ids from a read-only tmux snapshot filtered to the project namespace.
- Sidebar pane respawn now resolves the helper from `CCB_AGENT_SIDEBAR_BIN`, repository/install `bin/ccb-agent-sidebar`, or `PATH`; if unavailable, it respawns a keepalive shell with a visible short error instead of crashing namespace creation.
- Existing namespace reuse checks now treat a missing configured sidebar pane as a namespace-topology problem and recreate the project namespace with reason `sidebar_missing`. This keeps sidebar death separate from agent runtime failure.
- `build_project_layout_plan` can select agents from explicit later windows by using the normalized window layout set as the pruning source.
- Focused coverage currently lives in `test/test_ccbd_namespace_topology_plan.py` plus startup-flow regressions in `test/test_v2_ccbd_start_flow.py`.
- The dedicated release workflow builds the Rust helper with `bin/build-ccb-agent-sidebar`, uploads `ccb-agent-sidebar-linux-x86_64.tar.gz`, and attaches it to GitHub Releases for tag builds.
- The main release-artifacts workflow builds the macOS helper for `x86_64-apple-darwin` and `aarch64-apple-darwin`, combines them with `lipo`, verifies the result is a universal binary, and ships it inside `ccb-macos-universal.tar.gz`.
- A PTY-backed `ccb open` smoke against an isolated temporary project attaches to the real tmux namespace with `TERM=xterm-256color`, times out only because the UI remains attached, and confirms sidebar panes keep rendering the window/agent tree after attach.
- `bin/package-ccb-agent-sidebar-release` stages the Linux x86_64 helper tarball and checksum, and a temporary-repo dry-run test verifies the tarball contains `bin/ccb-agent-sidebar`.

Primary write scope:

- `lib/ccbd/services/project_namespace_runtime/`
- `lib/ccbd/services/project_namespace_state_runtime/models.py`
- `lib/ccbd/start_flow_runtime/`
- `lib/cli/services/tmux_start_layout.py` or replacement multi-window materializer
- `docs/ccbd-startup-supervision-contract.md`

Primary tests:

- `test/test_v2_project_namespace_state.py`
- `test/test_v2_tmux_start_layout.py`
- `test/test_v2_tmux_ui.py`
- `test/test_v2_daemon_config_drift.py`
- new focused tests if needed: `test/test_ccbd_namespace_windows.py`

Exit criteria:

- project namespace can represent multiple managed windows
- sidebar pane projection is planned and tagged
- topology signature changes force recreate
- entry window selection is deterministic
- manual panes are outside the plan and not preserved on recreate

Do not include:

- full Rust TUI import
- Comms feed rendering
- ask/cancel/restart actions

### 14.3 WP3 ProjectView And Focus RPC

Status: ProjectView slice and minimal focus RPC slice are implemented.

Current ProjectView implementation notes:

- `project_view` is registered as a read-only ccbd socket operation.
- `CcbdClient.project_view(schema_version=1)` is available.
- `lib/ccbd/project_view/` provides the activity resolver, stable sequence cache, and ProjectView service.
- The payload includes project metadata, ccbd lease state, namespace summary, config-window rows, ordered agent rows, five-state activity fields, and compact current comms rows from active/queued jobs.
- When `ProjectViewService` receives the project namespace controller, it best-effort reads current tmux window, active pane id, and active managed agent for highlight fields.
- When namespace tmux metadata is available, window rows include `tmux_window_id`, `tmux_window_index`, and `sidebar_pane_id` without making those facts topology authority.
- The handler does not call `health_monitor.check_all()`, dispatcher ticks, completion polling, recovery, namespace reflow, or provider polling.
- `project_focus_window` and `project_focus_agent` are registered as ccbd socket operations.
- `CcbdClient.project_focus_window(...)` and `CcbdClient.project_focus_agent(...)` are available.
- Focus RPC validates logical targets against config, checks optional namespace epoch, uses only the project namespace tmux socket/session, resolves managed agent panes by CCB pane options, and never creates panes.
- Focused coverage currently lives in `test/test_ccbd_project_view.py` and `test/test_ccbd_project_focus.py`.
- Current limitations:
  - provider/session manual-work signals are not included yet
  - `project_focus_window` focuses the first configured agent in the window when available; persisted last-focused-per-window UI state is not implemented yet

Primary write scope:

- `lib/ccbd/project_view/`
- `lib/ccbd/project_focus/`
- `lib/ccbd/handlers/project_view.py`
- `lib/ccbd/handlers/project_focus.py`
- `lib/ccbd/handlers/__init__.py`
- `lib/ccbd/app.py`
- `lib/ccbd/socket_client.py`

Primary tests:

- `test/test_v2_ccbd_socket.py`
- `test/test_ccbd_socket_client.py`
- new focused tests if needed: `test/test_ccbd_project_view.py`
- new focused tests if needed: `test/test_ccbd_project_focus.py`

Exit criteria:

- `project_view` returns minimal Phase 1 payload
- ProjectView generation is read-only
- activity resolver is covered
- focus RPC returns stable success/error behavior
- focus RPC does not create panes or trigger provider/reconcile work

Do not include:

- Rust ratatui rendering
- release packaging
- provider hook enrichment

### 14.4 WP4 Rust Sidebar Fork

Status: initial CCB-native Rust crate skeleton implemented.

Current implementation notes:

- `tools/ccb-agent-sidebar` is an independent Rust crate, not a root Cargo workspace.
- The binary parses `--ccbd-socket`, `--project-root`, and `--pane-window`.
- The client sends ccbd RPC requests using the existing newline-delimited JSON protocol and reads `project_view`.
- The model layer deserializes the Phase 1 ProjectView window, agent, and Comms rows, including compact job id/reason, display status, correlated execution phase, bounded active-inbound diagnostic, reply-delivery, and body-preview fields when present.
- The TUI renders the window/agent tree plus compact two-line Comms panel. It preserves `activity_symbol`/`activity_color` supplied by ProjectView, prefers optional correlated execution phases for compact Comms text/color, displays a bounded active-inbound `condition:reason`, and falls back to legacy status fields when the phase is absent.
- Keyboard navigation supports `j`/`k`/arrows, deliberate `r` pane restart,
  `Ctrl-L` refresh, `Enter` focus through ccbd RPC, `Tab`
  return-to-current-window focus through ccbd RPC, and `q`/`Esc` exit for
  development. Mouse navigation supports left-click focus on window and agent
  rows plus `⚙` settings and `×` project kill header actions. `stale_view`
  focus failures refresh ProjectView and retry the original target once;
  `target_missing` does not retry until a later ProjectView can show recovery.
- The tree header and border are focus-aware: green when the sidebar's own window is focused, yellow with `focus:<window>` when another managed window has focus, and yellow degraded styling when ProjectView/RPC is stale.
- In narrow sidebars, the tree header uses compact focus titles such as `review>main` instead of the full project name so cross-window focus remains visible.
- Rust unit tests include fake Unix socket coverage for `project_view`, `project_focus_window`, `project_focus_agent`, window-row `Enter`, `Tab`, `stale_view` refresh/retry, and `target_missing` no-retry behavior over newline-delimited JSON RPC, plus `ratatui::TestBackend` coverage for the rendered tree, status symbol/color, focus-aware header/border, degraded header, last-good ProjectView retention, no-last-good fallback screen, half-height Comms panel, and mouse row hit testing.
- The ProjectView Comms feed now combines active jobs, queued jobs, and recent terminal jobs from the job store, deduplicates by job id, folds reply-delivery jobs into the source ask, sorts by update time, and caps the Phase 1 payload.
- ProjectView RPC failures keep the last good window/agent tree visible, mark the header as `ccbd ✕`, show stale/unavailable status in the Comms panel, and use the Phase 1 2s/5s retry backoff.
- ProjectView sequence caching ignores volatile generated timestamps and increments only when stable view content changes.
- `LICENSE.upstream` preserves the upstream MIT license from `hiroppy/tmux-agent-sidebar`; hook/global tmux scan/worktree modules are intentionally not imported.
- `bin/ccb-agent-sidebar` exists in source installs as a wrapper that delegates to the built Rust binary or shows a visible keepalive error. `install.sh` builds/copies the real Rust binary over that path when Cargo or a prebuilt release binary is available.
- `bin/build-ccb-agent-sidebar` is the explicit release/developer build entrypoint for compiling `tools/ccb-agent-sidebar` and replacing `bin/ccb-agent-sidebar` with the real binary.
- `.github/workflows/test.yml` runs Rust sidebar tests and the build script on Ubuntu.
- `.github/workflows/release-sidebar.yml` builds and publishes the Linux x86_64 sidebar helper tarball on manual dispatch and tag pushes, with a SHA-256 checksum and GitHub Release attachment for tagged releases. Artifact staging goes through `bin/package-ccb-agent-sidebar-release`.
- `cargo test --manifest-path tools/ccb-agent-sidebar/Cargo.toml` passes with Rust sidebar coverage. `cargo fmt` could not be run on the current host because the `rustfmt` component is not installed.

Primary write scope:

- `tools/ccb-agent-sidebar/Cargo.toml`
- `tools/ccb-agent-sidebar/src/`
- `tools/ccb-agent-sidebar/README.md`
- `tools/ccb-agent-sidebar/LICENSE.upstream`

Primary tests:

- Rust unit tests under `tools/ccb-agent-sidebar`
- Rust fixture tests under `tools/ccb-agent-sidebar/src/tests/fixtures`
- fake Unix socket smoke test for ProjectView and focus calls

Exit criteria:

- binary parses documented launch args
- binary renders minimal ProjectView
- keyboard and mouse navigation call focus RPC
- RPC failure keeps last-good view
- no upstream provider hooks, global tmux scan, TPM lifecycle, or direct tmux focus remain active

Do not include:

- release packaging changes unless needed for local binary path smoke
- mutating ask/cancel/restart controls
- provider hook enrichment, now tracked in
  [docs/plantree/plans/sidebar-provider-activity/README.md](plantree/plans/sidebar-provider-activity/README.md)

### 14.5 WP5 Launch And Release Packaging

Primary write scope:

- release/build scripts
- namespace sidebar launch helper path resolution
- `lib/ccbd/services/project_namespace_runtime/sidebar.py`
- release/repo hygiene tests

Primary tests:

- release packaging tests, including `test/test_build_linux_release_script.py` if applicable
- namespace launch command tests
- repo hygiene tests

Exit criteria:

- release artifact includes `bin/ccb-agent-sidebar`
- namespace materialization launches the bundled helper with documented args
- missing helper failure is clear
- `ccb kill` tears down sidebar panes with the namespace

Do not include:

- new user-facing install command
- runtime download/install of upstream plugin assets

### 14.6 Parallelization Boundaries

Can run in parallel after WP1 model shape is stable:

- WP3 ProjectView fixture/prototype work
- WP4 Rust model/client/render work using fixture JSON
- WP5 release script exploration

Should not run in parallel without coordination:

- WP1 and WP2 if both mutate layout/config signature assumptions
- WP2 and WP3 if ProjectView reads namespace state shape being changed
- WP4 and WP3 if RPC schema or focus error codes are still changing

Hard sequencing:

1. WP1 must land before production WP2/WP3.
2. WP3 focus RPC must stabilize before WP4 keyboard integration is considered complete.
3. WP5 must land after WP4 produces a binary target.

### 14.7 Implementation Risks To Guard

- Do not add `.ccb/config.yaml`; Phase 1 extends `.ccb/ccb.config`.
- Do not make `cmd` part of new `windows` topology.
- Do not let manual panes enter ProjectView or sidebar navigation.
- Do not let Rust TUI scan tmux or local `.ccb` files to derive state.
- Do not let focus RPC create panes or trigger provider/reconcile work.
- Do not let provider reader empty-poll paths crash `ccbd`; a temporary no-match must preserve cursor state and let ProjectView remain conservative.
- Do not make sidebar pane death an agent runtime failure.
- Do not let optional ProjectView diagnostic fields become required by the Rust TUI.
- Do not add runtime download/install of upstream `tmux-agent-sidebar`.
- Do not add ask/cancel/restart controls in Phase 1.
- Do not introduce `ccb open` as a required entry path for this feature.

## 15. Roadmap

### Done

- Upstream plugin behavior inspected.
- CCB namespace/layout authority constraints identified.
- Product shape clarified: built-in project console, not plugin.
- MVP clarified: read-only monitoring plus switching.
- Config topology model and default TOML bootstrap implemented.
- ProjectView read-only RPC and minimal focus RPC implemented.
- Namespace topology planning model and topology-signature recreate boundary implemented.
- Multi-window namespace creation, per-window agent pane materialization, sidebar pane projection, and `@ccb_window` pane tagging implemented for the first tmux slice.
- Runtime records/startup reports persist configured window identity, and ProjectView exposes tmux window/sidebar pane metadata from read-only namespace snapshots.
- Codex reader empty-match crash fixed so delayed provider output does not restart `ccbd`.
- Sidebar release packaging path, source wrapper, CI Rust job, ProjectView color preservation, stable ProjectView sequence caching, degraded/last-good rendering, business-level compact Comms feed, fake-socket focus routing tests, `stale_view` retry, `target_missing` no-retry behavior, and ratatui render fixture are implemented.
- Release packaging tests now exercise the sidebar build script in a temporary repo with fake Cargo output, proving the copy/chmod path without overwriting the source wrapper in the working tree.
- Installer tests now exercise the prebuilt release-binary path, proving `install.sh` replaces the source wrapper with an existing `tools/ccb-agent-sidebar/target/release/ccb-agent-sidebar` binary when present.
- Live tmux smoke tests now use isolated temporary projects and project-scoped tmux sockets to verify both namespace materialization and a real `ccb` start flow: `ccbd` materializes multiple managed windows, projects one sidebar pane into each managed window, preserves user-root pane tagging, launches agents in their configured windows, protects sidebar panes from orphan cleanup, and keeps a sidebar present after switching windows.
- A manual non-interactive helper smoke with `CCB_AGENT_SIDEBAR_BIN` pointed at the locally built Rust binary confirms real sidebar panes execute `ccb-agent-sidebar` and render the window/agent tree plus empty Comms panel under tmux capture.
- A PTY-backed `ccb open` smoke confirms the real attach path enters the project tmux namespace and that sidebar panes continue rendering after attach.
- Keyboard `Tab` now switches from a sidebar pane back to the current managed window through `project_focus_window`; direct Rust-side tmux mutation remains out of scope.
- A dedicated release workflow now publishes a Linux x86_64 `ccb-agent-sidebar` tarball and checksum, and attaches them to GitHub Releases on tag builds.
- A scripted release dry-run now packages the Linux x86_64 sidebar tarball in a temporary repo and verifies the archive contains `bin/ccb-agent-sidebar`.
- Final Phase 1 acceptance audit completed against the criteria below. Evidence includes full Python regression, Rust sidebar unit tests, isolated live tmux namespace/start/open smokes, release dry-run packaging, and source/docs consistency checks.
- The follow-up sidebar presentation slice now renders a three-panel sidebar with compact 5-row Comms, a bottom tmux Tips panel, and UI-only `[ui.sidebar.view]` settings delivered through `project_view`; detailed planning lives in [docs/plantree/plans/sidebar-tips-layout/README.md](plantree/plans/sidebar-tips-layout/README.md).

### Next

1. Integrate provider-native manual-work signals for sidebar status using the
   plan-tree root in
   [docs/plantree/plans/sidebar-provider-activity/README.md](plantree/plans/sidebar-provider-activity/README.md).
2. Dogfood the integrated sidebar in normal CCB project usage and decide which
   additional deferred item, if any, should be promoted into the next slice.

### Deferred

- ask/cancel/restart controls
- namespace reflow controls from sidebar
- worktree controls
- desktop notifications
- selected-window sidebar mode
- cross-project dashboard
- Windows/psmux parity
- mouse target routing

## 16. Acceptance Criteria For Phase 1

Phase 1 is complete when:

- `.ccb/ccb.config` can describe multiple managed windows.
- `cmd` is no longer required in the new window topology.
- legacy compact config with `cmd` migrates to `main` by ignoring `cmd`.
- every configured agent appears exactly once across all managed windows.
- `ccbd` materializes every managed window in the project namespace.
- sidebar panes are automatically projected into every managed window when enabled.
- switching tmux windows keeps a sidebar visible.
- the sidebar top panel shows window rows and agent child rows.
- the sidebar shows only configured CCB agents, not manual panes.
- status symbols use the simplified activity-state model.
- sidebar state comes from `project_view`, not local file scans or tmux discovery.
- bottom panel shows a basic Comms feed or a clearly empty feed placeholder.
- keyboard can switch to selected windows/agents.
- keyboard switching goes through project-scoped focus operations and rejects unmanaged panes.
- the release includes a runnable `ccb-agent-sidebar` binary used by managed sidebar panes.
- the runtime launcher can invoke `bin/ccb-agent-sidebar` with the documented launch arguments.
- `ccb kill` destroys sidebar panes with the project namespace.
- manual user-created split panes are not tracked or restored by CCB.
