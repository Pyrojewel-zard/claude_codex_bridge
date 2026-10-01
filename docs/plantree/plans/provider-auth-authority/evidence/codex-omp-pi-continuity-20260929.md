# Codex, OMP, And Pi Continuity Qualification

Date: 2026-09-29
Role: evidence
Status: Pre-release verification snapshot; subsequently published in v8.7.4

Publication and installation evidence: [release receipt](v8.7.4-release-20260929.md).
Related: [decision 008](../decisions/008-continuity-first-native-restore.md)

## Scope And Source

Continuation of the Claude slice in `fix/claude-continuity-first-20260929`,
based on `8888fc6f2`. No original working pane or external Provider state was
modified. This slice includes relevant Pi/OMP resume repairs previously left
in the separate ask-stall worktree, without its keyboard or unrelated changes.

- Codex `lib/provider_backends/codex/launcher_runtime/command_runtime/home.py`,
  `_link_project_session_binding`: a current native transcript inside the
  managed session root, with matching metadata id and no subagent identity,
  is rebound to the new authority and remains eligible for exact resume.
  Invalid/absent/foreign binding handling remains unchanged. The existing
  `resume_authority_matches` check still checks the newly prepared generation;
  it is not globally disabled.
- Codex `launcher_runtime/command_runtime/service.py`, `_codex_args`, and
  `launcher.py::build_session_payload`: record whether automatic restore was
  selected. Shared session persistence preserves native/conversation/generation
  continuity for restore and does not merge the old binding into fresh startup.
- Pi `lib/provider_backends/pi/launcher.py`: record native session observations
  on session switch, manual input, and completed turns, and persist restore
  disablement for automatic restarts.
- Pi `lib/provider_backends/pi/session.py::resume_binding_for_launch`: the
  current launch's fenced observation wins over an older persisted binding or
  an unrelated newer file; invalid observations never resurrect an old session.
- OMP `lib/provider_backends/omp/session.py::resume_binding_for_launch`: enable
  the narrowly typed OMP v1 title-slot parser before validating the real header.
  The shared Pi validator retains its strict first-line contract by default.

No transcript content rewriting, OAuth migration, remote login operation,
generic retry framework, or arbitrary newest-file fallback was added.

## Real Native CLI Test

Reproduce with `test/test_provider_continuity_native.py`, using pytest with
`pyyaml`, `cryptography`, and `aiohttp`, and absolute binary paths in
`CCB_TEST_CODEX_BIN`, `CCB_TEST_PI_BIN`, and `CCB_TEST_OMP_BIN`.

| CLI | Version | Result |
| --- | --- | --- |
| Codex | 0.157.1 | Three process launches; same native thread after route/key change and another reopen. |
| Pi | 0.87.1 | Three process launches; CCB exact path selection and extension observations preserve same session. |
| OMP | 18.3.5 | Three process launches; CCB exact resume and extension observations preserve same session. |

Initial real test run: **3 passed in 38.65s**. Each provider sends a first
message to local endpoint A using fake key A, finishes a native turn and exits,
then reopens through CCB's selection on endpoint B using fake key B. A third
process resumes again on B. Assertions inspect B's actual HTTP request for the
old user marker and prior assistant reply, correct B authentication, and
unchanged native identity. Codex's stable conversation and authority generation
are also checked. The local server supplies deterministic replies: this proves
history transport and restoration, not remote model intelligence or recall.

Pi/OMP use their real CCB completion extensions and startup/history observation
formats. This is native print/JSON mode, not a new tmux/ask/FIFO end-to-end test.
Codex uses native `exec resume` after CCB namespace preparation and exact-id
selection; managed app-server/interactive behavior is covered by regression
tests, not declared live-qualified by this harness.

All new real-test homes/projects live in `TemporaryDirectory` fixtures and are
removed on exit. Processes have bounded timeouts; loopback servers are closed
in `finally`. The environment is whitelisted, keys are synthetic, external
auth/config is not copied, and the mock response never requests a tool call.

## Regression And Boundaries

Final combined run: **402 passed in 82.44s**, no skips. Native opt-ins:
`CCB_TEST_CODEX_BIN`, `CCB_TEST_PI_BIN`, `CCB_TEST_OMP_BIN`, and
`CCB_OMP_NATIVE_SMOKE` point to the installed executables. Command prefix:
`uv run --no-project --with pytest --with pyyaml --with cryptography --with aiohttp python -m pytest -q`.
Selected files under `test/`:

```text
test_provider_continuity_native.py test_codex_session_authority.py
test_codex_launcher_session_paths.py test_pi_session_history.py
test_pi_interactive_resume.py test_omp_session_history.py test_pi_omp_completion.py
test_v2_runtime_launch.py test_pi_pane_execution.py test_omp_pane_execution.py
test_omp_provider.py test_ccb_restart.py test_claude_continuity_first.py
test_provider_session_authority.py test_v2_provider_restore_launchers.py
test_claude_session_fields.py test_pane_crash_reason.py test_claude_launcher_env.py
test_claude_session_ensure_pane.py
```

Automated coverage includes changed key/route/inherited synthetic account,
stable generations, session payload persistence, explicit fresh, missing or
corrupt transcripts, wrong id/path/subagent identity, manual Pi session
switches, stale/foreign sidecars, OMP title-slot schema, header id/cwd mismatch,
normal provider execution and restart, and the earlier Claude repair.

The OMP native RPC smoke additionally loads both legacy and title-slot session
formats without a model request (`CCB_OMP_NATIVE_SMOKE` opt-in).

Remaining limits: Gemini is not changed; already-lost current bindings are not
blindly recovered from `old_*`; unsaved composer content and in-flight model
operations are not restored. Real commercial OAuth accounts, provider-switch
tool/reasoning compatibility, and arbitrary gateway protocols still require
qualification. Authentication/network errors are not evidence of unusable
history and no new fresh-on-auth-error behavior was introduced.

Review/integrate before installation or release. Rollback is source-only on
stopped agents and requires no transcript deletion or external auth rollback.
