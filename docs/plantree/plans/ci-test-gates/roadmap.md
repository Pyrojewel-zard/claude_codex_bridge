# CI Test Gates Roadmap

Date: 2026-08-12

## Done

- Measured the successful pre-change CI run and attributed its critical path.
- Defined orthogonal Python/OS coverage and explicit lifecycle ownership.
- Implemented the workflow split, WSL smoke consolidation, superseded-run
  cancellation, stable aggregate check, and deterministic Config UI probe
  fixture in the local tree.
- Prevented duplicate feature-branch push and pull-request executions while
  preserving `main`, `dev`, pull-request, and manual coverage.
- Locally passed the optimized regular gate (`6716 passed, 3 skipped, 42
  deselected`, 6m31s) and lifecycle gate (`21 passed, 6740 deselected`,
  11m32s), plus workflow contracts and repeated timing-fixture checks.

## Next

- Push the change and record remote job durations and conclusions.
- After a green remote run, configure repository rules to require
  `Required test gate`, `macOS real ccbd/ask smoke`, and
  `WSL mounted-drive ccbd/ask smoke`.
- Reassess whether the default-branch-only cross-platform workflow still adds
  evidence beyond the optimized and real-platform gates.

## Deferred

- Parallel pytest workers for process/tmux-backed tests, pending proof of
  namespace and resource isolation.
