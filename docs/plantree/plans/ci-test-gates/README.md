# CI Test Gates

Date: 2026-08-12

Status: Implemented locally; remote CI pending

## Purpose

Reduce pull-request gate latency and duplicated runner work without weakening
CCB's Python compatibility, macOS behavior, WSL mounted-drive behavior,
provider blackbox, Rust helper, installer, or lifecycle coverage.

This plan refines the project-wide
[test and release baseline](../../baseline/test-and-release-gates.md). Runtime
and platform behavior remain governed by their existing contracts, including
the [WSL compatibility plan](../../../ccb-wsl-compatibility-plan.md).

## Measured Baseline

GitHub Actions run `31560253078` on 2026-08-12 executed the same approximately
6,700-test suite six times on Linux/macOS and once more in WSL.

| Lane | Pytest time |
| :--- | ---: |
| Ubuntu Python 3.10 | 9m47s |
| Ubuntu Python 3.11 | 23m43s |
| Ubuntu Python 3.12 | 24m17s |
| macOS Python 3.10 | 15m06s |
| macOS Python 3.11 | 26m35s |
| macOS Python 3.12 | 28m02s |
| WSL full suite | 47m06s, plus about 5m setup |

Thirteen `ccb_lifecycle_smoke` cases in
`test/test_single_lane_multi_workgroup_smoke.py` accounted for about 13
minutes on Ubuntu/macOS and about 17 minutes in WSL. The WSL full-suite lane
was the approximately 52-minute critical path even though
`.github/workflows/ccbd-real-platform.yml` already owns real WSL lifecycle,
path relocation, communication, soak, and stress validation.

## Gate Design

### Required unit compatibility

`.github/workflows/test.yml` uses an orthogonal matrix:

- Ubuntu on Python 3.10, 3.11, and 3.12 owns interpreter compatibility.
- macOS on Python 3.11 owns operating-system compatibility.
- The regular unit lane excludes `provider_blackbox` and
  `ccb_lifecycle_smoke`; both have explicit specialist owners.

This keeps every ordinary test on all supported Python versions and one real
macOS interpreter without paying for every OS-by-Python permutation.

### Lifecycle and specialist lanes

- One Ubuntu/Python 3.11 lifecycle job runs all 21
  `ccb_lifecycle_smoke` cases.
- Provider blackbox, Rust helpers, and macOS install/package smoke remain
  independent jobs.
- Existing guarded fake-runtime steps remain in the Ubuntu/Python 3.11 unit
  lane and therefore remain part of the required aggregate result.

### Platform lanes

- The duplicate WSL full-suite job is removed from `test.yml`.
- Its unique `/mnt/c` startup and relocation assertion moves into the existing
  real WSL job, beside WSL path, lifecycle, communication, soak, and stress
  checks.
- The legacy cross-platform workflow remains a default-branch/release evidence
  lane, but no longer repeats on every pull request because the required unit
  and real-platform workflows already cover Linux, macOS, and WSL.

### Stability and authority

- Superseded runs for the same pull request or branch are cancelled.
- Push events are limited to `main` and `dev`; feature branches are covered by
  pull-request events, avoiding duplicate push and pull-request runs for the
  same internal branch. Manual dispatch remains available.
- A stable `Required test gate` check aggregates all jobs owned by the `Tests`
  workflow. It fails closed when any dependency is failed, cancelled, or
  skipped.
- Timing tests use events or other deterministic synchronization; retries,
  wider sleeps, and `continue-on-error` are not substitutes for correctness.
- GitHub branch protection is external repository state. It should require the
  aggregate `Required test gate` plus the two real-platform job checks after
  the optimized workflows pass remotely.

## Expected Effect

Historical timings project approximately a 60% reduction in Python test
runner minutes and a critical path of roughly 16–20 minutes instead of about
52 minutes. Remote CI is authoritative for the actual result.

Local validation of the split on 2026-08-12 completed the regular lane in
6m31s (`6716 passed, 3 skipped, 42 deselected`) and the lifecycle lane in
11m32s (`21 passed, 6740 deselected`). These measurements ran concurrently and
used the same source tree and Python environment; remote hosted-runner timing
remains the acceptance measurement.

## Non-goals

- Do not path-filter product tests based on changed files.
- Do not turn platform or lifecycle failures into warnings.
- Do not introduce automatic flaky-test retries.
- Do not parallelize pane-backed lifecycle tests with `pytest-xdist` until
  namespace and process isolation are independently proven.

## Reading Path

- [Roadmap](roadmap.md)
- [Tests workflow](../../../../.github/workflows/test.yml)
- [Real-platform workflow](../../../../.github/workflows/ccbd-real-platform.yml)
- [Cross-platform workflow](../../../../.github/workflows/cross-platform-test.yml)
