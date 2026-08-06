# Communication Source Inventory

Date: 2026-06-10

## Status

Initial source inventory for the developer manual communication chapter.
This is a first pass, not yet a complete chapter.

## End-To-End Ask Path

High-level flow observed from source:

```text
CLI tokens
  -> parse_ask
  -> submit_ask
  -> MessageEnvelope
  -> ccbd submit handler
  -> dispatcher submission plan
  -> JobRecord / JobEvent / queue
  -> message bureau MessageRecord / AttemptRecord / InboundEventRecord
  -> dispatcher tick starts running job
  -> provider execution service
  -> completion polling and tracker
  -> finalization
  -> message bureau AttemptRecord / ReplyRecord / reply inbound event
  -> watch/queue/inbox/trace render state back to caller
```

## CLI Layer

Primary files:

- `lib/cli/parser_runtime/ask.py`
- `lib/cli/services/ask.py`
- `lib/cli/services/ask_runtime/submission.py`

Observed responsibilities:

- `parse_ask` handles removed flags, route options, stdin appending, route
  parsing, and `ParsedAskCommand` construction.
- `--compact`, `--silence`, `--chain`, `--artifact-request`,
  `--artifact-reply`, and `--artifact-io` are parsed before route parsing.
- `submit_ask` validates target and sender against loaded project config.
- role ids can be used as ask targets only when they resolve to exactly one
  configured project-local agent.
- `message_with_reply_guidance` preserves its compatibility name but leaves
  ordinary ask bodies unchanged. Stable reply/cancel policy lives in managed
  provider memory; `--compact` and `--silence` add only one
  `CCB_REPLY_MODE` line unless explicit output requirements are detected.
- request bodies can be artifact-backed explicitly or automatically spilled
  when larger than 4 KiB.
- the CLI submits a `MessageEnvelope` through the mounted ccbd client.

Manual implication:

- The user manual should teach flags as route/content policy decisions.
- The developer manual should treat artifacts and callback as route options on
  the envelope, not as separate message types.

## Submit Handler And Envelope

Primary files:

- `lib/ccbd/handlers/submit.py`
- `lib/ccbd/api_models_runtime/messages.py`

Observed responsibilities:

- The submit handler reconstructs a `MessageEnvelope` from payload fields and
  delegates to `dispatcher.submit(envelope)`.
- `MessageEnvelope` normalizes `to_agent` and `from_actor`, preserves
  `silence_on_success`, `route_options`, and optional `body_artifact`, and
  enforces single-vs-broadcast delivery scope.

Manual implication:

- The envelope is the boundary object between CLI submission and daemon
  dispatch.
- Delivery scope validation belongs to the API model, not only to CLI parsing.

## Dispatcher Submission

Primary files:

- `lib/ccbd/services/dispatcher_runtime/facade.py`
- `lib/ccbd/services/dispatcher_runtime/submission_service.py`
- `lib/ccbd/services/dispatcher_runtime/submission_recording.py`
- `lib/ccbd/services/dispatcher_runtime/state.py`

Observed responsibilities:

- `_plan_agent_submission` validates sender, body artifact, callback request,
  resolved targets, and target availability.
- broadcast submissions receive a submission id; single-target submissions do
  not need one.
- `_drafts_for_agents` converts target agents into `_JobDraft` values with
  provider and request details.
- `_submit_plan` creates job ids, appends `JobRecord` rows, appends
  `job_accepted` or `job_queued` events, enqueues dispatcher state, and records
  the message-bureau submission.
- `register_callback_edge` runs after message-bureau submission when the route
  option requests callback behavior.
- dispatcher state is queue-oriented: each target slot has a queue and at most
  one active job tracked by `DispatcherState`.

Manual implication:

- The communication chapter should distinguish dispatcher queue state from
  message-bureau mailbox state.
- A single ask can create multiple jobs in broadcast mode but one logical
  message submission.

## Message Bureau And Mailbox State

Primary files:

- `lib/message_bureau/models.py`
- `lib/message_bureau/facade.py`
- `lib/message_bureau/facade_recording_submission.py`
- `lib/message_bureau/facade_recording_terminal_attempts.py`
- `lib/message_bureau/facade_recording_terminal_replies.py`
- `lib/message_bureau/store.py`
- `lib/mailbox_kernel/`

Observed responsibilities:

- `MessageRecord` represents a logical request with target agents, reply
  policy, retry policy, state, and submission linkage.
- `AttemptRecord` links a message to an agent/provider/job attempt and retry
  index.
- `ReplyRecord` stores terminal status, reply text, optional reply artifact,
  diagnostics, and finish time.
- `record_submission` writes a `MessageRecord`, one `AttemptRecord` per job,
  and one queued `InboundEventRecord` per target agent.
- `mark_attempt_started` moves attempts to running, claims mailbox inbound
  events, and sets message state to running.
- `record_attempt_terminal` updates attempt state, consumes or abandons inbound
  events, and refreshes message state.
- `record_reply` writes `ReplyRecord` and queues a reply-delivery inbound event
  to the caller mailbox when a caller mailbox exists.

Manual implication:

- Mailbox/inbox views are not just job queues; they are backed by message,
  attempt, reply, inbound event, and mailbox summary records.
- The same underlying state supports `queue`, `inbox`, `ack`, `trace`, and
  watch-style user views.

## Running, Polling, And Finalization

Primary files:

- `lib/ccbd/services/dispatcher_runtime/lifecycle_start_runtime/tick.py`
- `lib/ccbd/services/dispatcher_runtime/lifecycle_start_runtime/start.py`
- `lib/ccbd/services/dispatcher_runtime/polling_service.py`
- `lib/ccbd/services/dispatcher_runtime/finalization_runtime/service.py`
- `lib/ccbd/services/dispatcher_runtime/finalization_runtime/message_bureau.py`

Observed responsibilities:

- `tick_jobs` iterates runnable slots and starts the next queued job.
- `start_running_job` persists running state, marks the message-bureau attempt
  started, writes completion snapshots, marks dispatcher active state, syncs
  runtime busy state, and starts provider execution when the runtime binding is
  actionable.
- `poll_completion_updates` ingests provider execution updates, appends
  completion item events, acknowledges execution items, updates the completion
  tracker, and completes jobs when a terminal decision appears.
- `complete_job` persists terminal completion, records message-bureau
  completion, resolves reply-delivery terminal state, and may prepare automatic
  reply deliveries.
- `record_message_bureau_completion` handles delegated parent callbacks,
  automatic retry, reply artifact spill, normal reply recording, callback child
  continuation, and callback done marking.

Manual implication:

- Provider execution and reply detection are separated from final message
  delivery.
- Completion decisions drive terminal job state; reply records are a later
  communication-layer projection of that terminal result.

## Callback Path

Primary files:

- `lib/ccbd/services/dispatcher_runtime/callbacks.py`
- `lib/message_bureau/callback_edges.py`
- `lib/ccbd/services/dispatcher_runtime/finalization_runtime/message_bureau.py`

Observed responsibilities:

- callback mode is represented by `route_options["mode"] == "callback"`.
- plain nested asks from an active CCB task are rejected unless the child result
  is routed with `--chain` or the child is fire-and-forget with `--silence`.
- callback requires exactly one target, an active parent job, a parent message,
  message-bureau support, and no existing outstanding callback for the parent.
- `CallbackEdgeRecord` links parent job/message, child job/message, original
  caller/task, callback target, timeout, child reply, and continuation job.
- on child completion, CCB records the child reply without delivering it to the
  original caller, submits a continuation back to the parent agent, and updates
  the callback edge.
- repair and timeout sweeps can recover or fail pending callback edges.

Manual implication:

- The callback chapter should emphasize that callback is not a synchronous
  wait. It is a persisted edge plus a continuation submission.
- The user manual should retain the policy from the ask skill: use callback
  only when the parent task needs the child result to finish.

## Observer Commands And Daemon RPC

Primary files:

- `lib/cli/services/watch.py`
- `lib/cli/services/watch_runtime.py`
- `lib/cli/services/pend.py`
- `lib/cli/services/queue.py`
- `lib/cli/services/inbox.py`
- `lib/cli/services/ack.py`
- `lib/cli/services/trace.py`
- `lib/ccbd/socket_client_runtime/endpoints.py`
- `lib/ccbd/handlers/watch.py`
- `lib/ccbd/handlers/queue.py`
- `lib/ccbd/handlers/inbox.py`
- `lib/ccbd/handlers/ack.py`
- `lib/ccbd/handlers/trace.py`

Observed responsibilities:

- CLI observer services are deliberately thin. They connect to the mounted
  daemon and call typed client endpoints such as `watch`, `queue`, `inbox`,
  `ack`, and `trace`.
- `watch` polls `client.watch(target, cursor=...)` with defaults
  `CCB_WATCH_TIMEOUT_S=10.0` and `CCB_WATCH_POLL_INTERVAL_S=0.1`, yielding
  event batches until terminal state. It can fall back to a persisted terminal
  watch payload if the daemon becomes unavailable.
- `pend` is a hybrid observer. A `job_` target reads job state through `get`;
  an agent target overlays mailbox head/reply state when available, including
  summary degradation if mailbox summary is missing or unreadable.
- ccbd handlers validate the minimal payload fields and delegate to dispatcher
  facade methods. They do not own communication semantics.

Manual implication:

- The user manual should explain observer commands as daemon queries, not as
  direct file readers.
- The developer manual should put most observer semantics in dispatcher facade
  plus message-bureau control views, not in CLI service wrappers.

## Queue, Inbox, And Ack Views

Primary files:

- `lib/ccbd/services/dispatcher_runtime/facade.py`
- `lib/message_bureau/control_queue.py`
- `lib/message_bureau/control_queue_runtime/views_runtime/summary.py`
- `lib/message_bureau/control_queue_runtime/views_runtime/agent.py`
- `lib/message_bureau/control_queue_runtime/views_runtime/inbox.py`
- `lib/message_bureau/control_queue_runtime/events.py`
- `lib/message_bureau/control_queue_runtime/ack.py`
- `lib/cli/render_runtime/mailbox_views_runtime/queue.py`
- `lib/cli/render_runtime/mailbox_views_runtime/inbox.py`

Observed responsibilities:

- `dispatcher.queue` asks the message-bureau control layer for queue summary
  data, then overlays runtime state and runtime health from the agent registry.
- `queue all` aggregates per-agent mailbox summaries into agent count,
  queued-agent count, active-agent count, total queue depth, and total pending
  reply count.
- `queue <agent>` and `queue --detail <agent>` derive mailbox state from the
  persisted mailbox summary and pending inbound events. If the persisted
  mailbox summary is missing or unreadable, detail views degrade and can still
  reconstruct useful event-level state from inbound event records.
- `inbox <agent>` returns mailbox summary, head event, and optionally detailed
  pending items. Reply heads are enriched with `reply_id`, source actor,
  terminal status, notice metadata, job id, progress timestamps, and reply
  text.
- `ack <agent> [inbound_event_id]` only acknowledges the current head event.
  It supports task replies and terminal task-request head events. It rejects
  non-head events and rejects replies after automatic reply delivery has been
  scheduled.
- Pending event filtering discards terminal event states and ignores stale
  records whose message, attempt, or reply link can no longer be resolved.

Manual implication:

- The communication chapter should distinguish dispatcher job queue state from
  mailbox queue state. The visible `queue` command is mailbox-centric with
  runtime overlays.
- The user manual should warn that `ack` is intentionally head-only to preserve
  inbox ordering and avoid skipping earlier pending communication.

## Trace Lineage

Primary files:

- `lib/message_bureau/control_trace.py`
- `lib/message_bureau/control_trace_runtime/service.py`
- `lib/message_bureau/control_trace_runtime/collections.py`
- `lib/message_bureau/control_trace_runtime/summaries.py`
- `lib/cli/render_runtime/mailbox_views_runtime/trace.py`

Observed responsibilities:

- `trace` resolves target kind by id prefix: `sub_`, `msg_`, `att_`, `rep_`,
  or `job_`.
- Submission traces collect latest messages for the submission, attempts for
  those messages, replies for those messages, inbound events, and job
  summaries.
- Message, attempt, reply, and job traces walk the same lineage from different
  starting points and return a normalized payload containing counts plus
  selected summaries.
- Event summaries are gathered by scanning configured agents' inbound stores
  for matching message ids.
- Job summaries are looked up through job stores, using an agent hint when
  known and otherwise scanning configured agents.

Manual implication:

- The trace chapter should present lineage entities as a graph:
  submission -> message -> attempt -> job -> event/reply.
- The user manual can teach trace as the canonical way to connect a visible
  `job_id` back to mailbox and message-bureau records.

## Retry, Resubmit, And Cancel

Primary files:

- `lib/cli/services/retry.py`
- `lib/cli/services/resubmit.py`
- `lib/cli/services/cancel.py`
- `lib/ccbd/handlers/retry.py`
- `lib/ccbd/handlers/resubmit.py`
- `lib/ccbd/handlers/cancel.py`
- `lib/ccbd/services/dispatcher_runtime/lifecycle.py`
- `lib/ccbd/services/dispatcher_runtime/cancellation.py`
- `lib/ccbd/services/dispatcher_runtime/finalization_retry.py`
- `lib/ccbd/services/dispatcher_runtime/finalization_retry_runtime/`

Observed responsibilities:

- `resubmit <message_id>` plans a fresh message resubmission, calls the normal
  submit plan path, and returns the original message id, new message id,
  submission id, and new jobs.
- `retry <job_id|attempt_id>` resolves an attempt, requires it to be terminal,
  rejects completed attempts, requires the latest attempt for that agent, and
  creates a new job plus a message-bureau retry attempt under the original
  message.
- Retry may send the original request again or convert ask retries to
  `continue` when the prior attempt had already seen the provider anchor or
  started a reply.
- Automatic retry is separate from manual retry. It depends on message
  `retry_policy.mode == "auto"`, retryable failure reason/error type, provider
  resume support for runtime failures, and max-attempt limits.
- `cancel <job_id>` marks queued or active jobs cancel-requested, removes them
  from dispatcher queue/active state, asks the execution service to cancel,
  writes a cancelled completion decision, records message-bureau terminal
  state, and resolves any reply-delivery terminal state.

Manual implication:

- The user manual should contrast `retry` and `resubmit`: retry extends a
  message's attempt lineage, while resubmit creates a new message/submission
  chain derived from an earlier message.
- The developer manual should connect manual retry, automatic retry, and
  cancellation to finalization because they all project back into
  message-bureau state.

## Artifacts And Reply Delivery

Primary files:

- `lib/ccbd/services/dispatcher_runtime/finalization_runtime/artifacts.py`
- `lib/ccbd/services/dispatcher_runtime/reply_delivery.py`
- `lib/ccbd/services/dispatcher_runtime/reply_delivery_runtime/`
- `lib/ccbd/services/dispatcher_runtime/artifact_maintenance.py`

Observed responsibilities:

- Terminal replies can be forced into text artifacts by route option
  `artifact_reply`, or automatically spilled when larger than 4 KiB.
- Artifact spill updates completion diagnostics with `reply_artifact` and
  replaces the visible reply body with an artifact stub.
- Reply delivery is a dedicated dispatcher subsystem with preparation,
  claiming, start-completion, terminal, head, and repair steps.
- Text artifacts are periodically swept by `sweep_text_artifacts_if_due`, using
  a 5 minute interval and the shared text artifact storage sweep.

Manual implication:

- The communication chapter should treat artifacts as payload storage
  indirection, not a separate communication channel.
- The user manual should tie `--artifact-request`, `--artifact-reply`, and
  `--artifact-io` to the artifact stub behavior visible in replies.

## Remaining Inventory

Not yet fully analyzed:

- provider-specific execution and reply detection for Codex, Claude, Gemini,
  and OpenCode.
- tests that should be cited in the chapter.
- detailed reply-delivery repair and automatic delivery scheduling internals.
- runtime recovery path in `lib/ccbd/services/dispatcher_runtime/comms_recover.py`.
