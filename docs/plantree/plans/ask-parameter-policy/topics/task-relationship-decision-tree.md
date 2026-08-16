# Result Intent And Dependency Decision Tree

Date: 2026-06-08

## Decision Questions

Before choosing result or artifact flags, pass the dependency gate.

1. Does the work need delegation?
   - No: answer directly.
   - Yes: continue.

2. Is this ask from an active CCB parent task that cannot finish until this
   exact child result arrives?
   - Yes: add `--chain`, then stop for CCB continuation.
   - No: do not add `--chain`; continue.

3. Is the ask mainly publishing or executing work where a successful result is
   not useful to the caller?
   - Yes: use `--silence`.
   - No: continue.

4. Does the caller want a result, but only a distilled status, finding, risk,
   blocker, or next action?
   - Yes: use `--compact`.
   - No: continue.

5. Is the ask consultation, analysis, review/report generation, or any task
   where full output should be preserved?
   - Yes: use `--artifact-reply`.
   - No: use plain `ask` only for short questions or short handoffs.

6. Does the request body include exact transient text?
   - Yes: add `--artifact-request`, or use `--artifact-io` if the reply also
     needs full preservation.
   - No: pass repo paths when the target can read files directly.

## Examples

Publish-only execution:

```text
user -> A
A --silence -> B
B runs; success is routine, failures still surface.
```

Execution with short result:

```text
user -> A
A --compact -> B
B returns pass/fail, risks, blockers, or next actions.
```

Active parent needs short child result:

```text
user -> A
A --chain --compact -> B
B completes
CCB continues A with a distilled result.
```

Consultation or analysis:

```text
user -> A
A --artifact-reply -> B
B full report is stored as a completion-reply artifact.
```

Active parent needs full child report:

```text
A --chain --artifact-reply -> B
B full result is stored as artifact
CCB continues A with the artifact reference.
```

Exact input plus full output:

```text
A --artifact-io -> B
```

Add `--chain` when A is an active parent that depends on B.

Root/top-level delegation:

```text
user -> A
A -> B
```

Do not add `--chain` to the root A-to-B ask merely because A wants B's final
answer. `--chain` starts at the first dependent child ask made by an already
active agent.

## Nested Routing

An upstream silent edge does not decide downstream routing:

```text
A --silence -> B
```

B still runs an active job. If B needs C's result to finish, B uses chain. If
B is only dispatching independent work to C, B uses silence.

Chain dependencies still require each dependent child ask to create its own
chain edge:

```text
user -> A
A -> B
B --chain -> C
```

CCB propagates continuations after those edges exist.

Communication tests, batch sends, notifications, and independent asks are not
chain dependencies merely because replies are requested. Do not retry a
rejected plain ask by mechanically adding `--chain`; use `--silence` only when
no successful result is needed, otherwise report the routing limitation.
