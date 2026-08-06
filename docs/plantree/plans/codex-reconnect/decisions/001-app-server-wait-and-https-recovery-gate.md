# App-server Wait Semantics And HTTPS Recovery Gate

Date: 2026-07-18
Status: Partially superseded by Decision 002

## Context

The reconnection requirement mentions the interactive Codex prompt that offers
to keep waiting on the selected model or switch to a faster model. The plan
also requires operation without tmux, pane scraping, or blind key injection.
Transient network recovery additionally needs to distinguish broad network
loss from an OpenAI-specific path failure without treating ICMP as proof that
the application path works.

## Decision

The original V1 was a standalone headless Codex app-server client. It implements Continue as a policy:
keep the pinned model, honor Codex internal retries, wait with bounded backoff,
and reconcile the same thread before starting any continuation. It does not
render the Codex TUI or inject a Continue key.

The active Codex provider HTTPS origin is the authoritative recovery probe. For
CCB-managed sessions, the materialized Codex config route takes precedence over
ambient API route variables; the standard OpenAI/Codex origin is the fallback.
A public HTTPS endpoint is an optional diagnostic discriminator. Recovery is
allowed whenever the primary probe is stable, regardless of the public probe.
Local app-server restart is reserved for local process or stdio failure.

Decision 002 replaces the headless goal-runner product form with a transparent
managed-TUI bridge and removes usage-limit/normal-goal continuation from the
supported surface. The HTTPS authority and no-key-injection conclusions remain
in force.

## Consequences

- TUI wording, localization, focus, and keymaps cannot cause an unintended
  model switch in V1.
- A future TUI adapter remains possible, but requires an exact versioned
  fixture and a separate acceptance gate.
- HTTP errors still establish transport reachability; ICMP success or failure
  does not drive the state machine.
- The supervisor can wait indefinitely for the pinned model but cannot promise
  when service capacity will return.
