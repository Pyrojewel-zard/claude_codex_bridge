# Callback Ledger Read Amplification

Date: 2026-08-01

## Incident

A long-lived project running CCB 8.5.2 accumulated a callback edge ledger with
2,953 records, 816 distinct edges, and a size of about 18.8 MB. Its latest edge
states were 301 `continuation_submitted`, 510 `done`, and 5 `timed_out`.

The idle daemon spent about 26.8 seconds in `dispatcher_tick` during each
30-second full heartbeat. `/proc/<pid>/io` sampling observed about 4.17 GB/s of
logical cached reads and 44,000 read syscalls per second while the tick was
active, producing a long-run CPU average near 91%.

The amplification had two causes:

1. every hot-work check and dispatcher repair rebuilt latest callback state by
   parsing the full append-only ledger;
2. repair then revisited every historical `continuation_submitted` edge and
   performed per-edge reverse ledger and agent job-history searches.

The pane-exit log count from the incident was historical generation residue,
not evidence that the current high-CPU daemon was repeatedly crashing panes.

## Simplified Design

JSONL remains the only durable callback authority. This change deliberately
does not add SQLite, a sidecar index, a new schema, or an online compactor.

`CallbackEdgeStore` owns one process-local latest-edge view:

- the first latest-state query parses the ledger once;
- successful appends through the owning store update the view directly;
- inode, size, and nanosecond mtime form a cheap invalidation signature, so a
  replace, truncate, or append through another store causes one safe rebuild;
- restart naturally rebuilds the view from durable JSONL.

Callback repair uses one snapshot under the existing chain-transition lock:

- `done`, `failed`, and `timed_out` edges are ignored;
- `continuation_submitted` edges are inspected only when their linked job is
  still queued, or when malformed legacy state lacks the linked job id;
- normal `pending` edges are ignored while the child remains active or queued;
- `child_completed` and terminal-or-orphaned `pending` edges retain crash-window
  recovery;
- discovery of an already-created continuation scans each relevant target's
  job history at most once per repair tick, not once per edge.

This keeps durable recovery semantics while changing steady-state work from
history-dependent O(N²) scans to an initial O(N) rebuild followed by O(1)
latest-by-id access and bounded candidate processing.

## Safety Boundaries

- The project ccbd remains the callback ledger's single runtime writer.
- The in-memory view is derived data and can always be discarded.
- A failed durable append never advances cached state.
- External sequential appends are detected by the file signature and covered
  by regression tests.
- Callback completion, cancellation, duplicate continuation prevention, and
  both interrupted-submission crash windows remain covered by integration
  tests.
- Existing ledgers require no migration and must not be manually deleted.

## Verification

- 94 message-bureau and callback integration tests passed.
- 169 ccbd socket, restart, ProjectView, control-queue, retry-lineage, and
  submission-fastpath tests passed.
- A read-only replay of the production 18.8 MB ledger built its latest view in
  68.8 ms. One thousand cached latest-state calls took 9.89 ms and performed no
  further ledger reads; 301 latest-by-id lookups took 1.58 ms.
- An external source-runtime smoke used a production-shape fixture with 2,953
  records, 816 edges, and 18.51 MB of JSONL. The daemon remained healthy;
  `dispatcher_tick` measured about 0.25 ms, and a 10-second idle sample used
  0.04 CPU seconds (0.4%), read about 341 KB logically, performed no physical
  reads, and wrote 8 KB.

## Rollout And Rollback

The code change is migration-free. Rollout requires a normal CCB release and a
controlled restart of the affected project after installation. Restarting on
an unfixed build is not a mitigation because the same ledger is re-read.

Rollback is code-only: removing the derived view and candidate filtering
restores the previous behavior without transforming persistent state, but also
restores the CPU regression on large ledgers.
