# CCB + HAPI Integration Design

Date: 2026-08-01

## 1. Objective

Add an opt-in CCB runtime mode that launches each configured Claude or Codex teammate through the user's global HAPI CLI. Each teammate appears as a distinct HAPI session and remains remotely usable for chat, permissions, terminal, files, slash commands, and skills.

Phase 1 prioritizes a working vertical slice. CCB remains the sole authority for project topology, workspaces, provider homes, tmux panes, recovery, reload, restart, and local cleanup. HAPI remains the authority for Hub registration, remote session transport, Hub persistence, and Web interaction.

## 2. Scope

### In scope

- Project-level `[hapi]` opt-in configuration.
- Claude and Codex providers only.
- Existing global HAPI installation, authentication, machine identity, namespace, and Hub.
- Machine-readable HAPI integration preflight.
- argv-level wrapping of CCB-generated provider commands.
- CCB identity in HAPI session metadata.
- CCB-aware grouping and labels in HAPI Web.
- Start, reload, restart, reconnect, graceful stop, and forced-cleanup behavior.
- Focused unit, integration, and smoke tests across both repositories.

### Out of scope

- HAPI runner spawning CCB teammates.
- CCB starting or stopping the HAPI Hub.
- Providers other than Claude and Codex.
- Project-specific HAPI auth namespaces.
- Mirroring CCB queue, inbox, trace, jobs, or mailbox records into HAPI.
- A new CCB team dashboard or replacement for the CCB sidebar.
- Persisting the HAPI session id in CCB `AgentRuntime`.
- Composing HAPI mode with a user-defined `provider_command_template`.

## 3. Authority Model

```text
ccb.config
    |
    v
ccbd (project lifecycle authority)
    |  creates workspace, managed home, tmux pane, runtime generation
    v
HapiCommandDecorator
    |  hapi claude|codex --started-by terminal <provider args>
    v
HAPI CLI wrapper
    |  registers session, starts provider, exposes RPC/terminal/files/skills
    v
existing global HAPI Hub and Web
```

There is no second CCB-side Hub registration or teardown client. The HAPI wrapper owns its Hub session from bootstrap through archival. CCB owns the wrapper process because it owns the containing pane and process group.

## 4. Configuration

The project configuration adds one optional block:

```toml
[hapi]
enabled = true
command = "hapi"
```

`enabled` defaults to `false`. `command` defaults to `hapi` and exists for explicit installations and tests.

The block does not store the Hub URL, token, namespace, machine id, or HAPI home. Those remain global HAPI configuration. All CCB projects remain visible in the same HAPI user namespace and are separated in the UI by CCB metadata.

When enabled, configuration validation rejects:

- Any configured startup agent whose provider is not `claude` or `codex`.
- Any participating agent with an explicit `provider_command_template`.
- An empty or structurally invalid HAPI command.

The model must be carried through CCB parsing, validation, immutable config copies/overlays, serialization, config identity/signature, defaults, `config validate`, reload planning, and tests.

## 5. HAPI Preflight Contract

CCB runs one project-level preflight before mounting any teammate. HAPI exposes a machine-readable status command, such as `hapi doctor --json`, with a versioned contract containing:

- HAPI version.
- Effective API URL, without credentials.
- Authentication configured status, without exposing the token.
- Hub reachability.
- CCB metadata contract version.
- Support for disabling Claude runner auto-start.

CCB requires a compatible contract, configured auth, and a reachable existing Hub. Failure aborts startup before any teammate pane is launched. There is no silent local-only fallback.

The effective Hub URL is passed explicitly to wrapped processes so HAPI cannot auto-start a Hub. CCB also injects `HAPI_DISABLE_RUNNER_AUTO_START=1`; the HAPI Claude command must honor this before its unconditional runner check. Codex receives the environment harmlessly.

## 6. Command Decoration

The integration uses a shared argv-level `HapiCommandDecorator`. It does not use `provider_command_template` and does not change `provider_start_parts`, provider selection, or executable preflight.

For each provider launcher:

1. Build the native provider argv using existing CCB policy.
2. Preserve the native provider executable for normal availability checks.
3. Remove the executable token from the argv passed downstream.
4. Render the configured HAPI command, flavor, `--started-by terminal`, and the remaining provider arguments.
5. Apply CCB's existing environment prefix and managed-home environment to the wrapper process.

Examples:

```text
claude --settings ... --continue
=> hapi claude --started-by terminal --settings ... --continue

codex -c disable_paste_burst=true --sandbox read-only
=> hapi codex --started-by terminal -c disable_paste_burst=true --sandbox read-only
```

No `--` wrapper delimiter is inserted because the current HAPI flavor parsers do not implement one. The original `claude` or `codex` executable token is not forwarded.

Only the Claude and Codex launchers call the shared decorator in phase 1. Codex HAPI mode deliberately disables CCB's managed app-server optimization and uses HAPI's normal Codex path.

## 7. Identity and Persistence

CCB injects these environment variables for every wrapped teammate:

- `HAPI_CCB_PROJECT_ID`
- `HAPI_CCB_AGENT_NAME`
- `HAPI_CCB_PROVIDER`
- `HAPI_CCB_SESSION_ID`
- `HAPI_CCB_WORKGROUP`, when available

HAPI reads them at the shared `buildSessionMetadata` point and stores these optional metadata fields:

- `ccbProjectId`
- `ccbAgentName`
- `ccbProvider`
- `ccbSessionId`
- `ccbWorkgroup`

`ccbSessionId` is CCB's launch-session identifier and identifies one runtime generation. It joins HAPI metadata to CCB's provider session file without requiring HAPI session-id backwrite.

The fields are added to the shared metadata schema, Hub metadata carry-forward logic, CLI resume preservation, Hub cache merge behavior, and session-summary conversion. HAPI stores metadata as JSON, so no SQLite migration is required. Existing REST, Socket.IO, and SSE envelopes remain unchanged.

## 8. Lifecycle

### Start

1. Load and validate CCB configuration.
2. Run HAPI project preflight once.
3. Materialize each workspace and managed provider home.
4. Build native Claude/Codex argv.
5. Decorate argv and inject HAPI/CCB environment.
6. Launch the wrapper in the CCB-owned pane.
7. HAPI registers its Hub session and starts the native provider.
8. CCB resolves the native provider binding and commits `AgentRuntime` authority as today.

A wrapper or Hub bootstrap failure causes normal CCB startup failure reporting. A HAPI session is not separate CCB runtime authority.

### Reload and restart

Replacement follows the existing CCB start path. The old wrapper archives its HAPI session; the new runtime generation receives a new `ccbSessionId` and creates a new HAPI session. HAPI Web groups generations by CCB project and agent, with the active generation first and archived history retained.

### Stop

The HAPI-enabled stop sequence is:

1. Send SIGTERM to collected wrapper process groups before tmux pane cleanup.
2. Wait up to three seconds for HAPI metadata/session-end flush and exit.
3. Run existing tmux pane cleanup.
4. Run existing residual PID-tree cleanup and force termination.
5. Complete normal CCB authority and namespace cleanup.

HAPI handles SIGINT, SIGTERM, and SIGHUP through the same idempotent archive/close path. Hub inactivity timeout is an abnormal-exit fallback, not the normal stop mechanism. HAPI cleanup failure never prevents CCB from reclaiming local resources.

## 9. HAPI Web Presentation

The existing session application remains the first screen. No new dashboard is introduced.

Session-list behavior becomes:

- Ordinary HAPI sessions retain current machine/directory grouping.
- CCB sessions group by `ccbProjectId`, then optional `ccbWorkgroup`.
- Each row displays the CCB agent name and existing provider flavor/status.
- Active generations sort before archived generations.
- Search includes project id, agent name, provider, workgroup, path, and current title/summary fields.
- Session detail header shows CCB project, agent, and workgroup as compact metadata.

The existing chat, files, terminal, permissions, slash-command, and skill surfaces are reused without CCB-specific variants.

## 10. Error Handling

### Configuration errors

Fail before launch with field-specific messages for unsupported providers, conflicting command templates, or invalid HAPI command configuration.

### Preflight errors

Report distinct failures for missing executable, incompatible version/contract, missing auth, unreachable Hub, and missing no-runner capability. `ccb doctor` exposes the same facts without secrets.

### Runtime errors

- HAPI bootstrap/provider launch failure appears as normal agent startup failure.
- Socket disconnect uses HAPI's existing infinite reconnect and backfill behavior.
- Metadata version conflicts use existing optimistic retry and carry-forward behavior.
- Graceful shutdown timeout proceeds to local force cleanup and relies on Hub inactivity reconciliation.
- Web parsing treats CCB metadata as optional so old sessions and mixed HAPI versions remain readable.

## 11. Testing Strategy

### CCB unit tests

- HAPI config defaults, parsing, unknown keys, serialization, overlays, and config signatures.
- Claude/Codex-only validation and explicit-template conflict.
- Decorator removes the original executable, preserves quoting/order, and leaves disabled mode unchanged.
- Preflight result parsing and each failure class.
- HAPI environment and identity injection.
- Stop ordering: graceful process termination precedes pane cleanup, with residual cleanup always executed.
- Reload/restart produces a new `ccbSessionId`.

### HAPI unit tests

- JSON doctor contract and secret redaction.
- `HAPI_DISABLE_RUNNER_AUTO_START=1` prevents Claude runner spawn.
- `HAPI_CCB_*` metadata injection for new, lazy, and existing-session bootstrap.
- Metadata carry-forward, resume preservation, cache merge, and summary conversion.
- SIGINT/SIGTERM/SIGHUP share one idempotent cleanup path.
- CCB session grouping, active-generation ordering, search, row label, and detail metadata.

### Cross-system integration tests

- Global Hub preflight followed by two wrapped teammates appearing under one CCB project.
- Claude remote message, permission decision, files, terminal, and skills.
- Codex remote message, permission/config change, files, terminal, and skills.
- Managed Claude/Codex homes and inherited CCB skills remain effective inside wrapped providers.
- Disconnect/reconnect backfill has no message loss or duplicate delivery.
- Reload/restart archives the prior generation and activates the new generation.
- Stop archives sessions within the graceful window; forced termination converges through Hub timeout.
- Codex process-tree live identity, resume, completion detection, and CCB `ask` result delivery.
- Claude pane completion markers and CCB `ask` result delivery remain valid through the wrapper.

Codex is not released in the phase-1 switch until its live-identity/resume/completion integration test passes. Claude and Codex remain the declared phase-1 scope; failure blocks release rather than silently dropping Codex.

## 12. Parallel Implementation Boundaries

### Worker 1: CCB

- CCB config model/parser/serializer/validation.
- Project-level HAPI preflight client and doctor reporting.
- Shared argv decorator and Claude/Codex launcher integration.
- HAPI environment/identity injection.
- Graceful stop ordering and tests.
- CCB-side reload, resume, completion, and smoke coverage.

Worker 1 must not modify `hapi/`.

### Worker 2: HAPI

- Machine-readable doctor/preflight contract.
- Runner auto-start disable contract.
- CCB metadata schema, injection, preservation, cache, and summaries.
- SIGINT/SIGTERM/SIGHUP lifecycle handling.
- CCB-aware Web grouping, labels, search, and detail metadata.
- HAPI-side unit and integration tests.

Worker 2 must only modify `hapi/` and must preserve its repository conventions.

### Lead integration

- Resolve cross-boundary contract mismatches.
- Review both diffs for duplicate authority or secret leakage.
- Run focused suites, then broader CCB and HAPI checks.
- Perform a real Hub + Claude/Codex smoke test when credentials and binaries are available.

## 13. Acceptance Criteria

The feature is complete when:

1. Disabled mode has no behavioral change.
2. Enabled mode fails before launch when its global HAPI dependency is unusable.
3. A CCB project with Claude and Codex launches one active HAPI session per teammate.
4. Each session is remotely usable for chat and existing HAPI workspace capabilities.
5. HAPI Web groups sessions by CCB project/workgroup and identifies each teammate.
6. CCB reload/restart/stop semantics remain authoritative and leave no indefinitely active HAPI session.
7. CCB restore, completion detection, and `ask` delivery pass for both providers.
8. No token or credential is written to `ccb.config`, CCB runtime records, logs, Web metadata, or committed files.

