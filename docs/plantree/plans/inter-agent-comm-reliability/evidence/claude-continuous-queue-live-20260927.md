# Real Claude continuous communication and simulated input

Date: 2026-09-27
Role: evidence
Status: real-provider scenarios passed on local candidate; not published
Related: [contract](../topics/input-draft-delivery-guard.md),
[earlier reply verification](claude-suggestion-reply-delivery-20260927.md)

## Environment and scope

A new disposable project ran two real Claude agents through the candidate
checkout's `ccb_test`, after explicit external-root diagnostics and config
validation. A persistent temporary Python venv supplied daemon and hook
dependencies. Provider configuration was inherited one-way from the owner's
working source; no credentials were read or changed. No mock provider/API was
used. Simulated typing and keys targeted only this test project's socket/pane,
as explicitly requested by the owner. Existing working panes were untouched.

## Results

| Scenario | Evidence | Result |
| --- | --- | --- |
| Three consecutive Claude-to-Claude result chains in the same sessions | parents `job_9ca74f319822`, `job_f50f59679d83`, `job_e6d867c425dc`; continuations `job_0934c984b7af`, `job_093a567cae6b`, `job_d0b1317a1201` | worker wrote/read three distinct files; parent read each and returned `CHAIN_1_OK` through `CHAIN_3_OK`; each round drained |
| Human-initiated tool turn | simulated direct prompt wrote a marker then ran sleep 25; queued `job_79b949e02c50`, `job_86dee7a268c8` | native `provider_busy` held both unclaimed; both completed in order after the human turn |
| Early manual draft clear | `job_e0ce8e2c9f8a`, `job_445139bf3543` | both held while a single-line draft was present; simulated Ctrl-U emptied it; first released at 4.55 s and both returned |
| Real 180-second two-line draft | `job_00aa0bdfb5ef`, `job_f5c9cf674b5f` | at 3/60/120/175 s both remained pending and draft remained nonempty; release observed at 182.13 s, followed by two successful replies |
| Worker return blocked by recipient draft | producer `job_5c7ada0a3e8a`, return `job_d8a8a736f6dd`, later ask `job_ed3e27f8e6ff` | return and later ask held together; after manual clear the return completed before the ask began |
| Model-selection menu | `job_3a726565104a` | `/model` produced `composer_layout_unknown`; task stayed pending; Escape restored delivery and successful reply |

All **19 CCB jobs** reached completed with **one attempt each**. This count
includes chain parents and continuations; business acceptance additionally
used exact reply markers and independent worker-file readback, not status alone.
Both final mailboxes were idle with zero queued jobs and zero pending replies.

## Durable FIFO checks

The second job's first RUNNING journal timestamp followed the first job's
terminal timestamp for all four relevant pairs:

| Pair | First ended (UTC) | Second started (UTC) |
| --- | --- | --- |
| Busy queued requests | 13:41:33.961072 | 13:41:35.019353 |
| Early-clear requests | 13:41:56.790764 | 13:41:58.053263 |
| Deadline requests | 13:45:36.558205 | 13:45:37.952212 |
| Return then ask | 13:46:40.776436 | 13:46:41.841157 |

Read-only inspection of 27 parent and 10 worker native user-message records
found no synthetic draft marker submitted to the model. These counts include
native tool-result user records and are not counts of CCB requests.

## Limits

This qualifies the listed observed runs, not all themes, CLI versions, failure
modes or arbitrary user typing races. Live Tab/ghost acceptance transitions
were not generated in this run; their evidence remains the earlier captured
native probes and automated replay. The 182.13 s value includes polling and
clear/readback latency and does not change the fixed 180-second policy.
Successful timed clearing does not establish atomic input ownership or remove
the separately documented Ctrl-C/paste-to-Enter race concerns.

No production code was changed during this campaign. The candidate and earlier
automated tests remain local and uncommitted; no runtime upgrade or release
was performed.

Cleanup completed through `ccb kill` (unmounted, forced=false). No test
process or global Mobile discovery entry remained. The disposable project,
provider homes, venv and harness were moved to system Trash, recoverable;
the original temporary path is absent. This sanitized record is retained.
