# Native CLI Providers

Date: 2026-06-13

## Purpose

Add first-class CCB provider support for recently requested native terminal
coding CLIs:

- `kimi`: Moonshot AI Kimi Code CLI, command `kimi`.
- `deepseek`: DeepSeek-oriented Deep Code CLI, command `deepcode`.
- `mimo`: Xiaomi MiMo Code CLI, command `mimo`.

Next-wave research also covers additional requested CLIs:

- `qwen`: Qwen Code CLI, command `qwen`.
- `qoder`: Qoder CLI, command `qodercli`.
- `qoderclicn`: Qoder CLI CN, npm package `@qodercn-ai/qoderclicn`, command
  `qoderclicn`, Node `>=20`.
- `copilot`: GitHub Copilot CLI, command `copilot`.
- `cursor`: Cursor Agent CLI, command `agent`.
- `kiro`: Kiro CLI, command `kiro-cli`.
- `crush`: Charm Crush CLI, command `crush`.
- `pi`: Pi coding agent, command `pi`.
- `grok`: xAI Grok Build CLI, command `grok`.

The current landing slice makes these providers usable in `.ccb/ccb.config`,
mounts them in managed tmux panes, sends CCB ask prompts, detects replies via
provider-native session/event logs, and exposes diagnostics consistent with
existing pane-backed providers.

## Authority

Product/runtime contracts remain authoritative:

- [../../../ccbd-startup-supervision-contract.md](../../../ccbd-startup-supervision-contract.md)
- [../../../ccb-config-layout-contract.md](../../../ccb-config-layout-contract.md)
- [../../../managed-provider-completion-reliability-plan.md](../../../managed-provider-completion-reliability-plan.md)

This plan root records the active provider onboarding slice and does not
override the shipped contracts.

## File Map

- [roadmap.md](roadmap.md): current phase, landed work, next tasks, and
  deferred follow-ups.
- [implementation-status.md](implementation-status.md): operational handoff for
  the in-progress implementation.
- [open-questions.md](open-questions.md): unresolved provider behavior or
  rollout questions.
- [topics/source-research.md](topics/source-research.md): upstream CLI source,
  package, install, command, and auth findings.
- [topics/integration-design.md](topics/integration-design.md): CCB provider
  architecture, completion detection, configuration, and testing plan.
- [topics/grok-ask-skill-test-plan.md](topics/grok-ask-skill-test-plan.md):
  staged verification for native Grok ask-skill projection and cross-window
  routing isolation.
- [topics/grok-ccb-skills-design.md](topics/grok-ccb-skills-design.md): native
  Grok `ask` and `ccb-clear` skill content, projection ownership, caller
  identity, permission, and acceptance contracts.
- [topics/kimi-receipt-and-diagnostics-hardening.md](topics/kimi-receipt-and-diagnostics-hardening.md):
  landed Kimi-only receipt, no-captured-reply, trace, and restore-diagnostics
  hardening notes with explicit non-impact constraints for other providers.
- [topics/agy-delivery-stability-hardening.md](topics/agy-delivery-stability-hardening.md):
  AGY ready-gated prompt delivery, late transcript/pane fallback, and
  coalesced-request diagnostics needed to approach OpenCode-style reply
  attribution stability.
- [topics/pi-visible-pane-completion.md](topics/pi-visible-pane-completion.md):
  active Pi visible-pane execution, exact `agent_settled` completion, legacy
  headless migration, timeout, restore, rollback, and test contract.
- [../../../plans/2026-08-11-cursor-visible-pane-execution-design.md](../../../plans/2026-08-11-cursor-visible-pane-execution-design.md):
  landed Cursor visible-pane execution, anchored transcript completion,
  readiness fencing, timeout, cancellation, and headless rollback contract.
- [history/next-wave-cli-lab-2026-06-13.md](history/next-wave-cli-lab-2026-06-13.md):
  local install/source lab record for Qwen, Copilot, Cursor, Kiro, and Crush.
- [history/pi-provider-landing-2026-06-13.md](history/pi-provider-landing-2026-06-13.md):
  Pi provider evidence, implementation, and validation record.

## Scope

In scope:

- Provider keys `kimi`, `deepseek`, and `mimo`.
- Next-wave provider keys `qwen`, `qoder`, `qoderclicn`, `copilot`, `cursor`, `kiro`, `crush`,
  `pi`, and `grok`, plus Z.ai CLI provider key `zai`.
- Default executables `kimi`, `deepcode`, and `mimo`.
- Default next-wave executables `qwen`, `qodercli`, `qoderclicn`, `copilot`, `agent`, `kiro-cli`,
  `crush`, `pi`, `grok`, and `zai`.
- `KIMI_START_CMD`, `DEEPSEEK_START_CMD`, and `MIMO_START_CMD` overrides.
- Next-wave command overrides `QWEN_START_CMD`, `QODER_START_CMD`,
  `QODERCLICN_START_CMD`, `COPILOT_START_CMD`,
  `CURSOR_START_CMD`, `KIRO_START_CMD`, `CRUSH_START_CMD`,
  `GROK_START_CMD`, and `PI_START_CMD`; Z.ai uses `ZAI_START_CMD`.
- Managed tmux pane startup using the existing simple tmux runtime path.
- Native completion detection using `CCB_REQ_ID` binding plus provider-owned
  Kimi `wire.jsonl` and DeepCode session stores.
- Provider capability projection for CCB ask usage, including Kimi native
  skills-dir injection, OpenCode generated instruction injection, and MiMo
  generated instruction injection.
- MiMo ask execution through native `mimo run --format json` result events,
  using `part.text` plus `step_finish` / `part.reason=stop` as completion
  evidence.
- Pi ask execution in the managed visible pane, using an exact-request
  provider-local lifecycle sidecar and `agent_settled` as terminal authority;
  the 8.5.0 `pi --mode json` subprocess remains the explicit rollback and
  persisted-job compatibility path.
- Cursor ask execution in the managed visible pane by default, with stable-idle
  delivery, exact `CCB_REQ_ID` top-level transcript binding, matching
  `turn_ended` terminal authority, and explicit
  `CCB_CURSOR_EXECUTION_MODE=headless` rollback.
- AGY completion alignment to Antigravity transcript logs, so AGY no longer
  relies on `CCB_DONE` as its primary completion signal.
- AGY prompt delivery hardening so CCB waits for an input-ready Antigravity pane
  before sending, avoids coalescing multiple CCB jobs into one AGY turn, and
  falls back to stable pane evidence when transcript writes lag.
- Empty-reply and timeout diagnostics aligned with existing pane-backed
  providers.
- Kimi-specific receipt hardening, no-captured-reply diagnostics, trace
  visibility, and execution-resume metadata clarification.
- Kimi provider-conversation continuity through observation-bound per-agent
  native session ownership and exact-session restart, without workdir-global
  `--continue` inference.
- Z.ai CLI (`zai`) provider registration using the shared native CLI subprocess
  path and `zai --prompt` headless execution.
- Grok Build CLI (`grok`) provider registration using the shared native CLI
  subprocess path and official `grok --no-auto-update -p ... --output-format
  streaming-json --session-id ...` headless execution.
- Unit and isolated source-runtime validation in `/home/bfly/yunwei/test_ccb2`.
- Local install/source research under
  `/home/bfly/yunwei/test_ccb2/cli-integration-lab` before source integration.

Out of scope for the first slice:

- Automatic API key acquisition or account registration.
- Provider-specific key/url shortcut projection in `.ccb/ccb.config`.
- Switching Kimi to a noninteractive `kimi --prompt` execution adapter.
- Supporting multiple DeepSeek community CLIs under one provider key.
- Publishing next-wave provider support before each CLI has command, state,
  auth, completion, and skill-injection validation.
