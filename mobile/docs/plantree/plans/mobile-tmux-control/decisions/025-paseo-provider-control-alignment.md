# Decision 025: Paseo Provider Control Alignment

Date: 2026-08-11
Status: Accepted
Supersedes: Decision 008 for the Provider-control scope only

## Decision

CCB Mobile will directly adapt the compatible Provider-control contracts and
observable behavior from `getpaseo/paseo` at commit
`b599d38a772f621e0001abfb90a769de11c8cd8b`.

The aligned scope is Provider identity, model definitions, thinking options,
configured-versus-active runtime state, confirmed model mutation, session
usage, account quota normalization, and the compact selection UX. CCB keeps
its Flutter application, Python gateway, ccbd, tmux panes, configuration,
device scopes, and project/window/agent/session ownership.

## License And Attribution

CCB is AGPL-3.0 and Paseo is AGPL-3.0-or-later. The user explicitly approved
direct Paseo source alignment for this feature. Substantial adaptations must
retain attribution and a pinned source mapping in
`mobile/THIRD_PARTY_NOTICES.md`; separately licensed assets or dependencies
are not implicitly approved by this decision.

## Safety Boundary

- Model/thinking controls are capability driven and validated server-side.
- Current Codex/Claude changes are `restart_required`; no guessed `/model`
  command or silent process restart is allowed.
- Mutations require a dedicated scope, namespace/provider/runtime/config
  fencing, and an idempotency key, and are never replayed after uncertainty.
- Session usage and account quota remain distinct; unknown values stay
  unknown.
- Provider credentials and raw upstream responses remain host-only.
- Provider switching is deferred to a later lifecycle/session-boundary design.

## Consequences

Decision 008 remains historical authority for the original permissive Batch 1
baseline, but its prohibition on Paseo adaptation no longer applies to this
Provider-control package. Future Paseo upgrades require an explicit provenance
diff and cannot overwrite CCB-specific lifecycle or security behavior.
