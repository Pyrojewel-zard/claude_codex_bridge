# Unified Diagnose Entry Point

Date: 2026-08-07

## Context

Several narrow maintenance skills would expose CCB internals to users and
force them to choose whether a problem is a diagnostics, message-chain, or
provider-recovery issue. The intended workflow is one command that can inspect
one agent, apply a bounded repair when the evidence supports it, verify the
result, and optionally report the incident upstream.

## Decision

Expose one user-facing entry point:

```text
ccb_diagnose <agentname>
```

`agentname` is required and must resolve to a current configured agent in the
mounted daemon graph. The command runs these phases in order:

1. collect redacted runtime, queue, inbox, trace, provider, and pane evidence;
2. classify the likely stall or failure and select the least disruptive
   supported repair;
3. execute only bounded CCB control-plane actions for that agent when the
   evidence and maintenance intent permit it;
4. verify the new trace/queue/reply/runtime state and stop on any blocker;
5. create a local redacted incident bundle with a stable failure fingerprint;
6. show the proposed GitHub issue body and request explicit user
   authorization before any network submission.

The internal implementation may reuse `ccb-self-diagnose`,
`ccb-self-chain`, `ccb-comm-reply-recover`, and `ccb-self-recover`; those are
implementation modules, not additional user-facing choices.

## Agent Normality Contract

The distilled command must preserve `ccb_self`'s existing evidence model. A
successful CLI invocation is not proof that the target agent is healthy.

For `ccb_diagnose <agentname>`, evaluate in this order:

1. **Authority**: the name exists in the current mounted daemon service graph;
   the project daemon is mounted with a current generation, connectable socket,
   live PID, and fresh heartbeat.
2. **Runtime binding**: the target runtime record is present; its state is not
   stopped/failed; health is `healthy` or `restored` (or an explicitly
   explainable active/recovery state); binding and pane identity are current.
3. **Work progress**: an active job is allowed to be busy when provider/runtime
   progress is current. A queued job is not itself a fault. A running job that
   exceeds the stale threshold, or an idle provider pane after a submitted
   request, is suspicious.
4. **Communication integrity**: mailbox summary is readable and consistent;
   queue depth, active/head event, pending reply, callback, and artifact state
   agree with the authoritative trace. Missing or mismatched observer data is a
   warning, not permission to repair from guesswork.
5. **Provider evidence**: provider runtime/pane evidence may classify active,
   idle, waiting-for-user, terminal-error, or unknown. Pane text is supporting
   evidence and never replaces daemon/job authority.

## Pane-First Deep Diagnosis

Because the command is normally invoked after a user observes that an Agent
is not executing, pane inspection is mandatory for a named target whenever a
current pane can be resolved. The minimum pane sequence is:

1. resolve the pane id and tmux socket from the current runtime record and
   verify that the pane belongs to the target CCB slot;
2. capture a bounded bottom/current-screen view, with a bounded recent
   scrollback capture when the current screen does not contain the request;
3. compare two captures over a short bounded interval and record a normalized
   content fingerprint plus activity result;
4. classify visible provider state: working, waiting for input, stale prompt,
   provider update, auth/quota/rate-limit/API error, dead/blank, misframed, or
   unknown;
5. correlate the visible request/anchor with the active job and trace before
   selecting a repair.

The pane capture is redacted before it enters an incident bundle or GitHub
issue. Raw pane text may remain only in the local CCB-owned diagnostic artifact
when the storage contract permits it. If text is blank or cannot distinguish a
layout/visual failure, use the bounded CCB-owned screenshot fallback; never
capture arbitrary desktop or unrelated tmux targets.

Pane evidence is a required diagnostic input, but it remains evidence only:
it cannot create an Agent, authorize a restart, redefine job lineage, or
override lifecycle/mailbox/provider-session authority.

The result should map to the existing `ccb_self` report shape:

```text
Status: ok|warn|error
Suspected domain: ...
Authority: ...
Evidence: ...
Residue: ...
Confidence: high|medium|low
Next action: ...
Blocked by: ...
```

The current draft helper at
`drafts/agentroles.ccb_self/tools/doctor.py` is therefore only a raw evidence
collector. It must not be reused as the final health predicate: it currently
checks broad command exit codes and `queue --detail all`, rather than resolving
the named agent and applying the authority/progress/lineage rules above.

## Safety Boundaries

- Read-only diagnosis and supported low-risk recovery may proceed under the
  user's maintenance request.
- Ambiguous, destructive, project-wide, restart-all, raw tmux, direct
  authority-file, secret-related, or business-task resubmission actions must
  stop and report a blocker.
- A retry/resubmit that can duplicate external business effects is never an
  automatic repair; it requires a separate explicit confirmation.
- GitHub issue creation is always an external side effect and requires a
  fresh confirmation after the redacted body is displayed. No API keys,
  tokens, full prompts, complete pane captures, or private absolute paths may
  enter the bundle or issue.
- The command must never treat observer snapshots or pane text as lifecycle,
  lease, mailbox, or provider-session authority.

## Interface Semantics

- `ccb_diagnose <agentname>` targets exactly one agent.
- An explicit future `all` mode, if added, must be a separate guarded design;
  it is not implied by omitting the agent name.
- Exit status distinguishes healthy/no-op, recovered, blocked, and failed
  diagnosis so scripts cannot mistake a completed diagnosis for a fixed issue.

## Consequences

- Users learn one command while the existing specialized recovery logic stays
  reusable and testable behind it.
- Incident reporting becomes reproducible and deduplicated through the
  fingerprint rather than ad-hoc issue text.
- The command is not a background self-healer; maintenance heartbeat may only
  trigger diagnosis according to its separate opt-in policy.

## Acceptance Criteria

- A named agent can be diagnosed without inspecting secrets.
- At least one representative stuck lineage is repaired through supported
  control-plane commands and verified by a follow-up trace.
- Ambiguous and unsafe cases stop without mutation and explain the blocker.
- The same incident produces the same fingerprint and a redacted local bundle.
- GitHub submission cannot occur without explicit confirmation of the exact
  rendered issue body.
