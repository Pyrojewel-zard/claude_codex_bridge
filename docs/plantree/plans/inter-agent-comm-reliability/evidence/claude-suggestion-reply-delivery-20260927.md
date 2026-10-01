# Claude dynamic suggestions and return delivery

Date: 2026-09-27
Role: evidence
Status: automated verification and real Claude work/result-chain passed; live suggestion transitions pending
Related: [contract](../topics/input-draft-delivery-guard.md),
[earlier native probe](codex-claude-composer-deep-probe-20260920.md)

## Rule

Claude suggestion text is dynamic, not a fixed placeholder. Within the
recognized bordered composer, unaccepted dim ghost text at the initial cursor
is empty. Tab acceptance makes it a real draft even if the cursor returns to
the start. Typed prefixes, multiline text and accepted suggestions must hold
delivery. Busy and native queue vetoes take precedence over ghost detection.

## Automated evidence

- `test/test_claude_dynamic_suggestion_observation.py`: 12 cases cover changing
  English/Chinese/multiline suggestions, Tab-rendering transitions, typed
  prefix plus ghost suffix, multiline drafts, busy and native queue vetoes.
  An inverse-only single character lacks enough ghost evidence and remains
  nonempty; this is a conservative false-block possibility.
- `test/test_claude_suggestion_reply_delivery.py`: six cases use the actual
  observation/guard/dispatcher FIFO code with captured Claude screens and a
  controlled execution service/backend. Return delivery is released by ghost
  recognition, early manual clear, or one simulated clear after 180 seconds.
  The next ask stays behind the return until its processing-turn completion.
  Three-theme final-sender tests keep the same deferred submission and send
  exactly once when an accepted draft becomes an unaccepted suggestion.
- Combined model-independence, dynamic-suggestion, delivery, guard and FIFO
  suites: **211 passed**. Tests use a fake clock for the 180-second boundary;
  they do not wait in or clear a real terminal.
- Adjacent Claude start/polling, queued activation, activation-Enter recovery,
  reply-delivery start/completion and polling gates, plus execution-service
  runtime suites: **111 passed**. Combined verification: **322 passed**.

## Scope and limitations

The previous native probe recorded actual Tab acceptance and three themes on
Claude 2.1.278 with a local mock API. This run replays those captures and adds
synthetic transitions; it is not a new live provider-switch or API round trip.
No production Claude behavior was changed by this verification. Existing
model-independent Codex edits remain a separate uncommitted source slice.

Screen attributes are version-sensitive evidence, not native editor-buffer
authority. Custom themes, lost styling, overlays, native queue hint changes,
and human input between final capture and paste/Enter are remaining limits.
The tests establish that the covered suggestions do not strand return delivery;
they do not prove all Claude reply stalls fixed. Existing send-uncertainty and
clear-primitive review concerns are not resolved by these tests. No model,
authentication, current pane or shared runtime was modified.

## Real-provider attempt (2026-09-27)

An independent disposable project launched two actual Claude Code 2.1.278
agents (`cl1`, `cl2`, native display Sonnet 5) against the user's existing
provider route, without mocks or reading/changing credentials. The candidate
checkout's `ccb_test` wrapper passed explicit external-root diagnostics and
config validation. Tasks requested a shell computation, file write/readback
and exact reply marker.

- `job_92b994ae1d29` and `job_d5df28330108` reached their respective Claude
  panes with the exact CCB request IDs. Trace confirmed running/delivering,
  one attempt for the inspected first job, and no reply.
- Both CLIs displayed `502 Upstream access forbidden, please contact
  administrator` and native retries. Neither result file was created. This
  proves initial real message delivery only, not model execution or return.
- The first pane also recorded a nonblocking startup-hook failure referencing
  an expired uv temporary interpreter. The harness subsequently pinned
  `CCB_PYTHON` to its active interpreter; a clean new-hook success was not
  established (the resumed pane retained the historical error). This remains
  a harness qualification item, not a fixed product defect claim.
- Both jobs were explicitly cancelled through the CCB control plane before
  stopping the disposable project. A bounded restart for harness inspection
  preserved the cancelled sessions; no duplicate task was submitted.
- Final control-plane checks showed both jobs cancelled, both mailboxes idle,
  zero queued jobs and zero pending replies. `ccb kill` returned unmounted
  without force; no test process or global mobile discovery entry remained.
  The disposable project, managed homes and harness were moved to system
  Trash (recoverable); the original temporary path is absent. This sanitized
  evidence is retained in the source checkout.

Real tool execution, Claude-to-Claude return/continuation and live suggestion
transitions remain unverified. Resume with a user-confirmed working provider
profile/route, resolve the harness hook interpreter, then require actual files,
exact replies, one-attempt lineage and drained mailboxes. Do not infer passing
communication from pane liveness or an accepted/running job.

## Successful rerun after owner route switch (2026-09-27)

A new independent project inherited the owner's newly switched source. Both
actual Claude Code 2.1.278 instances displayed Sonnet 5. No mock API or fake
provider was used. The harness used a dedicated persistent temporary venv,
pinned `CCB_PYTHON`, and removed inherited `VIRTUAL_ENV`; the fresh pane showed
no startup hook error. Worker and continuation completed via `hook_stop`.

| Stage | Job | Verified result |
| --- | --- | --- |
| Simple question | `job_336894bd4b1e` | completed / assistant_end_turn; `CLAUDE_SOURCE_OK_42` |
| Parent tool and delegation | `job_f73e29a2502e` | shell wrote `PARENT_STARTED`; callback_pending, subsequently resolved |
| Real Claude worker | `job_7379ffeb49f2` | shell computed/wrote/read `5050`; completed / hook_stop; `WORKER_REAL_OK_5050` |
| Parent result continuation | `job_c3b74ff2add2` | read worker file; completed / hook_stop; `CLAUDE_CHAIN_REAL_OK_5050` |
| Subsequent request | `job_f13e1368a2b2` | completed / assistant_end_turn; `CLAUDE_AFTER_CHAIN_OK` |

Independent file reads confirmed `PARENT_STARTED\n` and `5050\n`. Child and
continuation traces each showed one attempt. The model initially placed
`--chain` after the target twice; both commands were rejected before admission.
It corrected the syntax to `ask --chain worker`; exactly one child was accepted.
This syntax usability issue was observed, not silently counted as a clean first
command success or changed as part of this verification.

Final queue: both agents idle, no active or queued jobs, zero pending replies.
The test establishes real question answering, shell execution, Claude-to-Claude
delegation, result continuation, and subsequent delivery with the candidate
source. It does not newly qualify Tab/ghost transitions: the final live
composer was blank, and those transitions remain capture-replay evidence.

Cleanup: CCB reported unmounted without force; no test processes or global
mobile discovery entries remained. The new project, managed provider homes,
venv and harness were moved to system Trash (recoverable). No shared working
pane or installed runtime was changed.
