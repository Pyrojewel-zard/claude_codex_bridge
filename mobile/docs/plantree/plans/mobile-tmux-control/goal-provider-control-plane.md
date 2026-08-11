# CCB Mobile Provider Control Plane Goal

Date: 2026-08-12
Status: Implemented and Accepted
Mode: Execute

## Purpose

Make Provider identity, model selection, thinking controls, and usage visible
and controllable in CCB Mobile without replacing CCB's existing
project/window/agent/session authority.

This goal directly aligns the Provider control plane with the open-source
Paseo implementation at commit
`b599d38a772f621e0001abfb90a769de11c8cd8b` (`getpaseo/paseo`, 2026-08-11):
runtime Provider snapshots, model definitions, confirmed model changes,
thinking options, session usage, account quota normalization, and the compact
mobile selection UI are the reference contracts.

CCB and Paseo are both AGPLv3 projects. CCB is `AGPL-3.0-only`; Paseo is
`AGPL-3.0-or-later`, which can be used under AGPLv3 for this adaptation.
Direct source adaptation is therefore allowed when attribution and source
provenance are preserved. CCB still does not import Paseo's daemon or replace
its own `ccbd`, tmux, project/window/agent, Provider session, and gateway
authority.

## Paseo Source Alignment Baseline

Use the following Paseo files as implementation references. Port their tested
contracts and state semantics into Python/Dart instead of independently
inventing a parallel design.

| Paseo authority | Semantics to align | CCB target |
| :--- | :--- | :--- |
| `packages/protocol/src/agent-types.ts` | `ProviderSnapshotEntry`, `AgentModelDefinition`, `AgentRuntimeInfo`, `AgentUsage`, thinking options and `model_changed`/`usage_updated` events | Python gateway/ccbd records plus Dart immutable models |
| `packages/protocol/src/messages.ts` | validated model-mutation and Provider usage request/response schemas | authenticated mobile gateway routes and JSON schemas |
| `packages/protocol/src/provider-manifest.ts` | Provider labels, modes, capability metadata and safe unknown-Provider behavior | CCB Provider registry layered over CCB's larger Provider list |
| `packages/server/src/server/agent/provider-snapshot-manager.ts` | bounded Provider catalog loading, status, timeout, cache, refresh and workspace scoping | host-side Provider snapshot service that never blocks ProjectView/chat |
| `packages/server/src/server/agent/agent-manager.ts` | mutation calls Provider session, drains events, then publishes confirmed runtime state | ccbd lifecycle/provider adapter with stale epoch/revision fencing |
| `packages/client/src/daemon-client.ts` | request id, accepted/rejected response and no implicit mutation replay | Flutter repository mutation contract |
| `packages/app/src/provider-selection/` and `packages/app/src/composer/agent-controls/model-sheet.tsx` | active/configured model resolution, searchable model browser, favorites, Provider grouping and error/loading states | Flutter model selector and preferences |
| `packages/app/src/provider-usage/` | compact usage cards, window/balance bars, status and refresh metadata | Flutter session/context and account-quota surfaces |
| `packages/server/src/services/quota-fetcher/` | one adapter per Provider, bounded fetch, unavailable/error isolation and normalized windows/balances | Python host-only quota adapters |
| `packages/server/src/server/agent/providers/{codex,claude,opencode,pi,omp}` | Provider-specific catalog, model mutation and usage extraction | CCB Provider adapters, adapted only where the current CCB runtime exposes equivalent evidence |

Alignment means preserving observable semantics, field meaning, failure states,
and relevant tests. It does not mean copying React Native rendering code into
Flutter or replacing CCB's process/session ownership.

## Direct Adaptation And Attribution Rules

1. Record the Paseo repository URL, pinned source commit, and original file in
   each substantially adapted source file or a nearby attribution manifest.
2. Preserve Paseo copyright notices when copying a substantial implementation
   or test vector. Mark CCB-specific modifications.
3. Add a mobile Provider-control attribution entry to CCB's NOTICE or
   equivalent third-party attribution surface before release.
4. Check any nested dependency, asset, icon, generated file, or catalog entry
   for its own license before copying; Paseo's top-level AGPL license does not
   override third-party component licenses.
5. Prefer direct adaptation of protocol types, normalization, state machines,
   test cases, and UX behavior. Reimplement platform binding code where the
   source/target frameworks differ (TypeScript/React Native versus
   Python/Flutter).
6. Keep a source-to-target mapping in the implementation evidence so future
   Paseo updates can be audited without silently overwriting CCB-specific
   safety behavior.

## User Outcome

For every selected agent, the first line of runtime identity should clearly
show:

```text
<Provider> / <active model> / <thinking option>
```

The user can:

1. see the Provider and active model actually serving the current session;
2. open a compact model selector from the agent chat header/composer area;
3. choose only models and thinking options reported as supported;
4. understand whether a change is live, starts a new session, or requires an
   agent restart;
5. see real session token/context usage and, when safely available, Provider
   account quota and reset windows;
6. continue using agents whose Provider exposes only identity and no model or
   usage controls.

## Non-Goals

- Do not replace Flutter, the Python mobile gateway, `ccbd`, tmux, or native
  Provider sessions with Paseo runtime components.
- Do not add Paseo's file browser, Git UI, schedules, voice, browser, or other
  unrelated product features under this goal.
- Do not turn an existing Codex session into a Claude session in place.
- Do not simulate a model change by blindly typing `/model` or other guessed
  text into a tmux pane.
- Do not estimate token cost or account quota when the Provider does not supply
  authoritative data.
- Do not expose Provider credentials, auth files, refresh tokens, API keys, or
  raw billing responses to the app.

## Binding Product Decisions

1. **Provider is first-class identity.** Provider name/icon and the active
   model belong in the selected-agent surface, not only in diagnostics.
2. **Configured and active state are different.** The contract must distinguish
   `configured_model`, `active_model`, and `pending_model`. The UI must never
   claim a model changed until the runtime confirms it.
3. **Capability-driven controls only.** Every Provider declares whether model
   discovery, live model switching, next-session selection, restart-required
   selection, thinking controls, session usage, and account quota are
   supported.
4. **Provider changes are session/lifecycle changes.** Changing Provider is not
   part of the first implementation. A later Provider change must create or
   restart a session through CCB lifecycle authority and preserve a visible
   context boundary.
5. **Mutations are fail-closed.** Model/thinking mutations are not replayed
   automatically after timeout, reconnect, app resume, or gateway restart.
6. **Usage has two independent scopes.** Session usage and Provider account
   quota must not be combined into one misleading percentage.
7. **Unknown remains unknown.** Missing context size, token count, price,
   balance, or reset time is represented as unavailable, never inferred as
   zero.
8. **History remains visible.** A new session or model boundary is rendered as
   a divider in the conversation; prior messages are not deleted.

## Target Architecture

```text
Provider adapters in CCB source
  -> Provider capability/catalog registry
  -> active runtime identity + session usage readers
  -> guarded model/thinking mutation service
  -> optional host-only account quota fetchers
  -> ccbd ProjectView + mobile gateway contracts/events
  -> Flutter repository/cache
  -> selected-agent identity, model selector, and usage UI
```

The source side remains authoritative. Flutter may optimistically show a
pending selection, but only a source-confirmed runtime revision can promote it
to active.

## Canonical Data Contracts

The exact route names may follow existing gateway conventions, but the data
model must provide equivalent semantics. Paseo field meaning is authoritative;
CCB JSON may use its established `snake_case` encoding while Python and Dart
adapters preserve a one-to-one mapping.

### Provider Capability

```text
provider
label
description
status: ready | loading | error | unavailable
enabled
source: builtin | custom
error
models[]
modes[]
fetched_at
default_mode_id

# CCB capability extensions
supports_model_catalog
model_change_mode: live | next_session | restart_required | unavailable
supports_thinking_options
supports_session_usage
supports_account_quota
diagnostic_code
catalog_revision
```

### Model Definition

```text
provider
id
aliases
is_selectable
label
description
is_default
context_window_max_tokens
thinking_options[]
default_thinking_option_id
```

### Agent Runtime Identity

```text
project_id
agent_name
provider
namespace_epoch
session_id
runtime_revision
configured_model
model
pending_model
thinking_option_id
mode_id
model_change_mode
extra
```

Provider-native handles must be redacted or represented by an opaque stable
identifier suitable for stale-session fencing.

### Session Usage

```text
input_tokens                 # Paseo inputTokens
cached_input_tokens          # Paseo cachedInputTokens
output_tokens                # Paseo outputTokens
total_cost_usd               # Paseo totalCostUsd
context_window_max_tokens    # Paseo contextWindowMaxTokens
context_window_used_tokens   # Paseo contextWindowUsedTokens
source
measured_at
turn_id
```

### Account Quota

```text
provider_id                  # Paseo providerId
display_name                 # Paseo displayName
status: available | unavailable | error
plan_label
source_label
fetched_at
next_refresh_at
windows[]: id, label, used_pct, remaining_pct, resets_at, runs_out_at,
           shortfall_pct, tone
balances[]: id, label, used, remaining, limit, unit, resets_at, tone
details[]: id, label, value, tone
error
```

Account quota must use a bounded host-side cache, timeout, redacted diagnostics,
and Provider-specific adapters. It must never delay ProjectView or conversation
loading.

## Provider Support Tiers

### Tier 1: Codex And Claude

Required for the first accepted release:

- Provider identity and active/configured model;
- model catalog or a truthful unavailable state;
- guarded model selection with explicit apply mode;
- thinking/reasoning option where the Provider exposes it;
- current-session token/context usage from native session data;
- real Android Emulator proof for both Providers.

### Tier 2: Gemini, OpenCode, And Kimi

Add the same contract only where native CLI/runtime evidence is stable. A
Provider may initially support identity and usage while leaving switching
unavailable.

### Tier 3: Remaining Configured Providers

Display identity and capability state first. Add catalog, mutation, and usage
adapters independently; the long tail must not block Tier 1.

## Package A: Provider Identity And Capability Contract

Scope:

- add a Provider capability registry in CCB source;
- expose configured model/thinking from `AgentSpec` and active runtime identity
  from Provider-native state;
- extend ProjectView/mobile models compatibly;
- cache catalogs by Provider/profile identity and revision;
- render Provider, active model, and thinking in the selected-agent UI;
- show clear loading/unavailable/error states without hiding the chat.

Acceptance:

- Codex and Claude agent headers show the correct Provider and active model;
- configured and active model disagreement is visible and not silently merged;
- old gateway/app combinations tolerate absent fields;
- Provider catalog failure cannot block project list, chat, Terminal, or send.

## Package B: Guarded Model And Thinking Selection

Scope:

- add authenticated, scoped model/thinking mutation endpoints;
- require project id, agent, namespace epoch, expected runtime revision, and an
  idempotency key;
- validate the selection against the current Provider catalog;
- reject stale agent/session identity before touching the runtime;
- implement Provider adapters as `live`, `next_session`,
  `restart_required`, or `unavailable`;
- emit a runtime identity event/invalidation after confirmed application;
- present searchable model selection and thinking controls in a bottom sheet;
- preserve conversation history and insert a context/model boundary when a new
  session becomes active.

Acceptance:

- no mutation is sent while the agent identity is stale;
- timeout/reconnect never replays a model change;
- unsupported models cannot be submitted by editing the client payload;
- UI pending state settles only after authoritative confirmation;
- active work is not silently interrupted; restart-required changes require an
  explicit confirmation and lifecycle-safe path.

## Package C: Session Usage

Scope:

- normalize Provider-native token data into the Session Usage contract;
- start with Codex rollout/session data and Claude native transcript/session
  data;
- attach usage to a turn/session revision without making conversation parsing
  slower;
- display a restrained context indicator in the selected-agent surface;
- provide detail for input, cached input, output, context, and exact cost when
  supplied by the Provider;
- reset or separate usage at real Provider session boundaries.

Acceptance:

- usage values match redacted Provider-native evidence for dedicated Codex and
  Claude sessions;
- cached input is not counted again as ordinary input;
- partial updates are monotonic within one turn/session revision;
- clear/new-session produces a boundary and does not attribute old usage to the
  new session;
- missing usage does not display `0 tokens` or `$0.00`.

## Package D: Provider Account Quota

Scope:

- add optional host-only quota adapters per Provider;
- read existing Provider credentials only through established CCB Provider
  profile boundaries;
- use bounded timeouts, caching, refresh backoff, and redacted errors;
- expose normalized quota windows/balances through a separate read-only route;
- show account quota in settings and an optional compact warning near the model
  selector;
- do not poll quota while the app is in the background.

Acceptance:

- no raw credential or upstream response reaches logs, mobile payloads, crash
  reports, screenshots, or evidence artifacts;
- quota endpoint latency cannot delay project or conversation endpoints;
- upstream auth/rate-limit failure degrades only the quota card;
- reset time, percentage, and balance semantics are labeled by Provider and
  remain separate from session context usage.

## Flutter UX Requirements

- Keep the selected agent, Provider, and model identity visible in one compact
  header line; do not add a permanent large card or duplicate status strip.
- Use Provider icon + text, not color alone.
- The model trigger shows the active model, not an unconfirmed preference.
- The model sheet supports search and groups models by Provider when a Provider
  itself exposes multiple upstream model families.
- Model rows may show context size and thinking availability; unavailable
  models remain non-selectable with a reason.
- Session usage uses a compact progress indicator only when both used and
  maximum context are authoritative.
- Detailed account quota belongs in settings or a dedicated sheet, not in each
  conversation bubble.
- Working, unread, connection, and error indicators must remain independent of
  Provider/model/usage state.

## Security And Correctness Requirements

- Add a dedicated device scope for Provider settings mutations; do not reuse a
  broad file or terminal scope.
- Validate project, agent, namespace epoch, Provider, runtime revision, and
  model id server-side.
- Never accept executable model flags, shell fragments, environment values, or
  arbitrary Provider commands from the phone.
- Store only model identifiers/preferences needed by CCB config/runtime; do not
  duplicate Provider credentials in mobile state.
- Redact native session handles and upstream account payloads.
- Model change audit records contain identifiers and outcome only, never
  prompts, replies, auth, terminal output, or local secret paths.
- Preserve CCB config/worktree ownership and do not overwrite unrelated dirty
  source or workflow files.

## Verification Program

### Automated

- adapt Paseo protocol fixtures for Provider snapshots, model definitions,
  runtime info, session usage, and account quota, with provenance recorded;
- add Python/Dart cross-language JSON parity tests against those fixtures;
- Provider registry and catalog normalization tests;
- ProjectView/mobile JSON compatibility tests;
- native runtime identity and usage parser fixtures for Codex and Claude;
- mutation validation, stale epoch/revision, unsupported model, auth scope,
  timeout, and no-replay tests;
- session-boundary and monotonic usage tests;
- quota timeout/cache/redaction tests;
- Flutter model parsing, selector, pending/confirmed/error, accessibility, and
  usage widget tests;
- full relevant Python tests, full Flutter tests, `flutter analyze`, debug and
  profile APK builds, and scoped `git diff --check`.

### Real Android Emulator

Use the server-wide gateway and real mounted projects. Mutations must use a
dedicated project/worktree under `/home/bfly/yunwei/test_ccb2`, never
`ccb_mobile`, `ccb_source`, or an active user project.

Required evidence:

1. Codex header showing correct Provider/model/thinking;
2. Claude header showing correct Provider/model/thinking;
3. model sheet populated from source capability data;
4. successful supported change with source-side before/after runtime evidence;
5. unsupported/stale change rejected without runtime mutation;
6. live change or explicit next-session/restart-required behavior matching the
   declared capability;
7. session usage matching redacted native records;
8. clear/new-session divider with new usage scope and retained old history;
9. project/agent switching without model state bleed;
10. logcat/gateway audit with no crash, ANR, secret, prompt, reply, path, or
    terminal-output leak.

Performance budgets:

- cached Provider identity adds no perceptible project-open delay;
- model sheet cached open <= 150 ms p95;
- catalog refresh and quota refresh never block chat rendering;
- model mutation receives an accepted/rejected response <= 2 seconds p95,
  excluding an explicitly confirmed Provider restart;
- usage updates do not trigger full conversation reparse or visible timeline
  jitter.

## Rollout And Rollback

Rollout order:

1. read-only identity/capabilities behind compatible optional fields;
2. read-only Codex/Claude session usage;
3. guarded model/thinking mutations by Provider feature flag;
4. account quota adapters independently enabled per Provider;
5. Tier 2/3 Provider expansion.

Rollback:

- hide model mutation while retaining read-only identity;
- invalidate catalog cache and fall back to Provider default/unavailable;
- disable one Provider adapter without affecting others;
- disable account quota independently from session usage;
- retain the last confirmed active runtime state until a full ProjectView
  refresh proves otherwise.

## Resolved Execution Decisions

1. A restart-required choice updates the selected agent's persistent
   `ccb.config` model/thinking fields and records a CCB restart intent. It does
   not silently restart or interrupt an active task.
2. Current managed Codex and Claude sessions are declared
   `restart_required`; neither is advertised as a live switch until a future
   provider-native control surface proves that contract.
3. Account quota is read only for Codex and Claude through their existing
   managed credential homes. Fetches are bounded, cached, redacted, and kept
   on a separate route from runtime identity/model controls.
4. Provider switching remains outside this package. It requires a later
   lifecycle/session-boundary design rather than an in-place model mutation.

## Reusable Invocation

```text
Read and execute
`/home/bfly/yunwei/ccb_source/mobile/docs/plantree/plans/mobile-tmux-control/goal-provider-control-plane.md`
as the current CCB Mobile goal.

Resume the plan tree first. Keep CCB project/window/agent/session and tmux
authority unchanged. Implement Provider identity, safe capability-driven model
selection, and truthful session/account usage in coherent packages. Codex and
Claude are the first acceptance Providers. Directly adapt the compatible Paseo
Provider contracts, normalization, state-machine behavior, tests, and compact
UX at pinned commit `b599d38`, preserving attribution and recording every
source-to-target mapping. Do not guess Provider commands, copy separately
licensed assets without review, expose credentials, replay mutations, or claim
a model change before runtime confirmation. Use a real server-wide Android
Emulator and dedicated `/home/bfly/yunwei/test_ccb2` projects for mutation
evidence.
```

## Completion Gate

Do not mark this goal complete until Packages A-D are integrated on `main`,
Codex and Claude pass the real Emulator matrix, supported model changes are
confirmed against actual runtime state, session usage matches native evidence,
quota failures remain isolated, full tests/builds pass, and plan-tree landed
evidence is updated. If Package D remains intentionally deferred, record a
decision narrowing the completion gate before declaring the goal complete.

## Completion Record

Completed on 2026-08-12 against Paseo commit `b599d38`.

- Packages A-D are implemented as compatible CCB-native Python/Dart contracts.
- Codex and Claude Provider identity, configured/active/pending model state,
  thinking options, native session identity, token/context usage, and guarded
  restart-required configuration changes were exercised through the real
  Android Emulator and server-wide gateway.
- Conversation history now carries Provider-native session identity and shows
  a presentation-only `New context` divider when `clear` starts a new session;
  prior messages remain visible.
- Account quota remains a separate bounded route. Where managed Provider
  credentials do not expose authoritative quota, the UI truthfully reports
  unavailable rather than estimating a value.
- Provider-control endpoint p95 latency dropped from about 1.06 seconds to
  38.6 ms for Codex and 33.2 ms for Claude by preventing unrelated optional
  Provider CLI discovery from entering the request path.
- Full acceptance evidence, APK hashes, test counts, and residual limits are
  recorded in
  [history/provider-control-plane-acceptance-20260812.md](history/provider-control-plane-acceptance-20260812.md).
