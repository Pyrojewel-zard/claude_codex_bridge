# Claude `queue-operation` Prompt 完成检测死锁 · 根因诊断

Date: 2026-07-13
Version observed: ccb 8.0.19 (`60b3c3d`)
Provider impacted: claude (`session_boundary` completion, no BEGIN/DONE wrapping)
Symptom agent in observed run: `pm` (the central coordinator, highest async-reply fan-in, deadlocks ~5 times/day)

## 1. TL;DR

Claude Code CLI has two ways to record a prompt submitted via tmux paste-buffer into the session JSONL:

| REPL state when prompt arrives | entry in session JSONL | CCB structured_event parses it? |
|---|---|---|
| Idle at `❯` prompt | `{"type":"user","message":{"role":"user","content":...}}` | yes |
| Busy (cooking / tool_use / assistant turn) | `{"type":"queue-operation","operation":"enqueue","content":...}` + later `{"type":"attachment","attachment":{"type":"queued_command",...}}` | **no — dropped on the floor** |

When the prompt lands as `queue-operation`:

1. `handle_user_event()` never fires → `poll.anchor_seen` stays `False` forever.
2. `poll_submission._process_event` short-circuits: `if role == "assistant" and poll.anchor_seen: handle_assistant_event(...)` → assistant events stop being ingested entirely.
3. `maybe_append_assistant_end_turn_boundary` returns early on `not poll.anchor_seen`.
4. `last_assistant_uuid` is never updated, so `is_turn_boundary_event(turn_duration)` hits `if not last_assistant_uuid: return False` and the real turn boundary (which *does* exist in the log as `subtype:"turn_duration"`) is ignored.
5. `session_boundary` claude prompts use `wrap_claude_turn_prompt` (no CCB_BEGIN/CCB_DONE markers), so the text-based `maybe_append_turn_boundary(is_done_text(...))` fallback also can't fire.
6. The attempt stays `running`, the mailbox head stays `delivering`, all subsequent `task_reply`s queue up behind it, and the agent appears frozen until a human `ccb clear`/`ccb restart`.

## 2. Evidence

### 2.1 Runtime snapshot (project `MiniMES`, pm stuck job `job_006fe7f3bdad`)

- ccbd: healthy, generation 29, heartbeat fresh, fault list empty.
- pm mailbox: `state=delivering`, `queue_depth=5`, `pending_reply_count=4`, head event `iev_f9faa3fd62f9` delivering since 09:57:20Z (≈47 min at time of diagnosis).
- Queued behind the head: 4 `task_reply`s (from gate, agent1, agent2) that never get processed.
- All other agents idle.
- pm pane text: the turn actually finished — assistant emitted `三条并行在跑: agent1(is_qc 调查) + agent2(archi 终验) + gate 回执`, then `turn_duration 117037ms`, then `away_summary`, then the `❯` prompt.
- pm session JSONL ends with exactly the expected completion sequence: `assistant(stop_reason=end_turn, uuid=8a6a7...) → system(turn_duration, parentUuid=8a6a7...) → system(away_summary) → last-prompt`.
- ccbd persisted execution state for the job (`executions/job_006fe7f3bdad.json`): `status=incomplete, reason=in_progress, state.offset=30707195` — offset has advanced to end-of-file, no terminal decision recorded.

### 2.2 Quantitative: how often the bad path fires

Scanning the entire pm session log (`de07c1c5-…jsonl`, 10665 entries, 183 CCB jobs):

- Entry types carrying `CCB_REQ_ID:` —
  - `last-prompt`: 483 (meta, not data)
  - `user/text_string`: 175 (normal path)
  - `queue-op/enqueue`: **14** (bad path)
  - `user/tool_result`: 12 (CCB_REQ_ID appears inside a tool-result string, i.e. subagent mentions, not our prompt)
  - `attachment/queued_command`: 9 (companion to queue-op)
  - `attachment/file`: 8
- First entry per job (the path CCB first sees the anchor via):
  - `user/text_string`: 160 — these complete normally.
  - `queue-op/enqueue`: **14** — these hit the deadlock.
  - `user/tool_result`: 9 (secondary references inside tool output, not anchor carriers).

Attempt-state history for the 14 queue-op jobs from `ccbd/attempts/attempts.jsonl`:

| job_id | states | outcome |
|---|---|---|
| job_a4fdbb39ef03 | pending→running→incomplete | deadlocked, timed out |
| job_abc2a6f0e759 | pending→running→incomplete | deadlocked |
| job_ac6c57ed0ccb | pending→running→incomplete | deadlocked |
| job_bacfdca6a8f0 | pending→running→completed | lucky (pm happened to re-echo anchor text? fallback?) |
| job_ca6350bfe4b9 | pending→running→incomplete | deadlocked (pane-crash log shows pm confused about how to reply) |
| job_d634fca7b17f | pending→running→completed | lucky |
| job_1b6b0e0b6d7b | pending→running→completed | lucky |
| job_5db11acfa941 | pending→running→cancelled | human recovery |
| job_0410ed6e216d | pending→running→cancelled | human recovery |
| job_7e1630c61912 | pending→running→completed | lucky |
| job_80e20e2ec2d6 | pending→running→incomplete | deadlocked |
| job_f1657ae7f198 | pending→running→incomplete | deadlocked |
| job_cd4f813fc5c2 | pending→running→incomplete | deadlocked (previous jam today) |
| job_006fe7f3bdad | pending→running | **current jam** |

→ 9 out of 14 queue-op prompt deliveries failed to complete automatically; the 4 "completed" ones likely closed via non-anchor paths (e.g. pm output CCB_DONE by coincidence after subagent replies, or were rescued by later prompt injections). There is no reliable self-recovery.

### 2.3 Code trail (main branch `60b3c3d`)

- `lib/provider_backends/claude/comm_runtime/parsing_runtime/structured.py:8-53`
  `structured_event()` only recognizes `type ∈ {user, assistant, system}`. `queue-operation` and `attachment` are not handled and yield `None`, so they never become events.
- `lib/provider_backends/claude/execution_runtime/state_machine_runtime/system_events.py:19-35`
  `handle_user_event()` is the only site that sets `poll.anchor_seen = True`; it fires only on `role == "user"` events and only when `f"{REQ_ID_PREFIX} {poll.request_anchor}" in text`.
- `lib/provider_backends/claude/execution_runtime/polling.py:302-304`
  ```python
  if role == "assistant" and poll.anchor_seen:
      handle_assistant_event(submission, poll, event, now=now)
  ```
  Assistant events are ignored entirely before the anchor is seen.
- `lib/provider_backends/claude/execution_runtime/state_machine_runtime/assistant_events_runtime.py:169-173`
  ```python
  if poll.reached_turn_boundary: return
  if is_subagent or not poll.anchor_seen or not poll.request_anchor: return
  if assistant_stop_reason(event) != "end_turn": return
  ```
  End-of-turn via assistant `stop_reason=end_turn` requires anchor_seen.
- `lib/provider_backends/claude/execution_runtime/event_reading_runtime/turns.py:4-12`
  ```python
  if entry_type != "system" or subtype != "turn_duration": return False
  if not last_assistant_uuid: return False
  return parent_uuid == last_assistant_uuid
  ```
  `last_assistant_uuid` is only set by `append_chunk_item` in `assistant_events_runtime.py:94`, which sits behind the same `poll.anchor_seen` gate. So it stays empty and the turn_duration boundary is discarded.
- `lib/provider_backends/claude/protocol_runtime/prompt.py:20-22`
  `wrap_claude_turn_prompt()` (used for `session_boundary` providers when a completion dir is registered) emits only `CCB_REQ_ID: <id>\n\n<body>` — no CCB_BEGIN/CCB_DONE pair. The text-marker fallback in `maybe_append_turn_boundary(is_done_text(...))` therefore cannot close the turn either.
- `lib/provider_hooks/artifacts_runtime/transcript.py:219-227`
  There *is* explicit handling for `queue-operation` records in the offline artifact transcript code:
  ```python
  def _queue_operation_text(record):
      if str(record.get('type') or '').strip().lower() != 'queue-operation': return None
      return str(record.get('content') or '')
  ```
  This proves the record type is known to CCB, but the handling never made it into the live completion-detection pipeline.

### 2.4 Why pm is the most visible victim

- pm is the dispatch hub; almost every gate reply and subagent completion is routed back to pm.
- pm is almost never idle (it is constantly dispatching, reading tool results, sending `ask --silence`, etc.), so when CCB injects a new message via tmux paste-buffer, Claude REPL is almost always busy → the prompt *consistently* lands as `queue-operation`.
- Other claude agents (agent2, agent6) are lower-throughput; their prompts more often arrive at idle REPL → `user/text_string` → normal completion.
- Other providers (codex, kimi, opencode) use different completion detectors (`protocol_turn` for codex; native turn-log polling for kimi; etc.) and are not on this code path.

## 3. Root causes (two compounding defects)

### Defect A — Parser blind spot (primary)
`structured_event()` does not synthesize a synthetic `role=user` event from `type=queue-operation` records whose `content` contains the prompt text. The anchor text is *physically present* in the JSONL (in the `content` field) but never converted into an event, so the rest of the state machine has no idea the prompt was delivered.

### Defect B — No upper-bound watchdog (secondary, amplifies A into a user-visible hang)
Once a submission is `prompt_sent=true`, there is no attempt-level timeout/watchdog that forces the attempt to a terminal state (`failed` / `incomplete` with diagnostic `turn_boundary_timeout`) if no completion decision is produced after N seconds. The only timeout in the loop is `ready_timeout_s` (8 s) which gates prompt *dispatch*, not completion.

Without B, defect A causes silent indefinite deadlock instead of a loud, diagnostic, recoverable failure.

## 4. Additional robustness gaps observed

1. **`anchor_seen` is monotonic within a poll but never cross-validated against session-log offset.** If the parser misses the anchor on first pass (because it was a queue-op), it will never look backward for it.
2. **Assistant events before anchor are fully dropped** (`polling.py:302`). When the anchor arrives via queue-op, the assistant has already started emitting tool_use events (sending the `ask`s); those assistant chunks are lost, which means even if we later set anchor_seen (e.g., via a fallback scan), `last_assistant_uuid` is stale relative to the turn_duration event — matching still fails unless the scanner is willing to look back at the last assistant message.
3. **Restart/resume does not repair anchor state.** When ccbd restarts and resumes a `session_boundary` attempt, `runtime_state.anchor_seen` is whatever it was persisted as (False in the bad path) and the log reader's `offset` is at EOF; there is no "catch up on anchor / last assistant uuid by re-scanning recent log" step.
4. **There is no health metric for "active attempt age without TURN_BOUNDARY item".** A single `dispatcher_poll_completions` step that finds `active_execution_count>0` but oldest attempt age > threshold should raise a fault / auto-repair.

## 5. Proposed fix

Minimum viable patch (upstream-worthy):

1. **Emit a synthetic user event for `queue-operation` enqueued prompts.**
   In `parsing_runtime/structured.py`, add a branch after the `system` check:
   ```python
   if entry_type == "queue-operation":
       op = _optional_text(entry.get("operation"))
       text = str(entry.get("content") or "")
       if op == "enqueue" and text.strip():
           return _event_record(
               role="user",
               text=text,
               entry_type=entry_type,
               subtype=subtype,
               uuid=uuid,
               parent_uuid=parent_uuid,
               stop_reason=None,
               entry=entry,
           )
   ```
   This carries the prompt through to `handle_user_event`, which sets `anchor_seen=True` when the REQ_ID prefix matches.

2. **Allow assistant-event ingestion before anchor_seen, but only for uuid bookkeeping.**
   Change `polling.py:302-304` so that assistant events are still fed to a reduced `handle_assistant_event_pre_anchor` path that at least tracks `last_assistant_uuid` (and nothing else — no chunk items, no reply_buffer, no early turn boundary emission). This ensures `is_turn_boundary_event`'s parent_uuid check has the right uuid even when the anchor arrives mid-turn after some assistant events already exist.

3. **Add an attempt-level completion watchdog.**
   In the dispatcher's poll loop, for each active attempt older than `CCB_ATTEMPT_TIMEOUT_S` (default e.g. 600 s) with no TURN_BOUNDARY/ERROR/PANE_DEAD item ever produced, force-terminalize it with `status=incomplete, reason=turn_boundary_timeout, confidence=degraded`, and move on to the next queue item. Publish a fault entry and leave enough diagnostics (session_path, last_offset, last_seen_entry_type) to diagnose without re-running.

4. **Resume-time anchor catch-up.**
   When a `session_boundary` attempt is resumed, scan the last N KiB (or last ~200 entries) of the session log backward from the persisted offset to find (a) the anchor marker and (b) the latest assistant uuid, so a missed anchor across ccbd restart does not strand the job.

5. **Telemetry.**
   Emit a counter metric `ccb.completion.anchor_missing_after_seconds` and fault-inject self-test for the queue-op path so this class of bug has regression coverage.

## 6. Verification plan

- Add a fixture session log containing a `queue-operation/enqueue` prompt followed by assistant tool_use events and a `turn_duration` system event. Assert the detector yields `decision.terminal=True, status=COMPLETED, reason in {turn_duration, assistant_end_turn}`.
- Unit-test `structured_event()` for `queue-operation/enqueue` → role=user, text=content.
- Fault-injection test: simulate prompt delivery while REPL busy → confirm the watchdog trips within the configured timeout instead of hanging forever.
- Live soak on the `pm` agent in the MiniMES project for ≥4 hours; assert zero attempts stay in `running` > watchdog threshold, and that the 14 historical deadlocked jobs listed in §2.2 would have completed under the patched parser.

## 7. Workaround for users until the fix ships

- `ccb restart pm` (or the stuck claude agent) unblocks the queue but loses in-flight agent context.
- `ccb repair` can in some cases advance the head event; unreliable for this specific bug because the underlying completion detector never sees the boundary.
- Avoid sending messages to a busy claude agent (wait for its mailbox to go idle before ask); not practical for pm which is the hub.
