# Ask Parameter Policy Roadmap

Date: 2026-06-07

## Done

- Landed the public rename from `--callback` to `--chain` with no public
  callback flag compatibility path; inherited ask skills and command usage now
  present `--chain` as the dependent-child flag.
- Clarified that top-level/root delegation (`A -> B`) is plain `ask`; `--chain`
  is only used when the sender is an active CCB parent task and needs a child
  result to finish.
- Added dispatcher/message-bureau regression coverage for repeated sequential
  chain calls to the same child before returning to the original caller, and
  fixed prior chain-edge state convergence so earlier continuation edges close
  as `DONE`.
- Removed the duplicate "supported CLI" table from every README language
  variant because provider badges already carry that first-viewport signal.
- Clarified that `--chain` and `--silence` express task relationship, not
  content transport.
- Clarified that result intent is now the first selector: `--silence` for
  publish/execute without successful result needs, `--compact` for distilled
  results, `--artifact-reply` for full text results, and plain `ask` only for
  short inline work.
- Clarified that artifact flags are orthogonal to route flags: artifacts
  preserve content, while chain and silence describe dependency shape.
- Clarified that automatic 4 KiB artifact spill is fallback behavior, not the
  primary smart-selection policy.
- Clarified that `A --silence -> B` does not auto-complete B; B still runs an
  active job, and B-to-C routing depends on whether B needs C's result.
- Clarified that each dependent child ask from an active parent uses `--chain`;
  CCB owns continuation propagation after chain edges exist.
- Moved stable reply and cancellation policy into managed CCB project memory.
  Ordinary asks now preserve the user body, while `--compact` and `--silence`
  add only a one-line mode marker; native-provider duplicate guidance and the
  per-job cancellation paragraph were removed.
- Aligned inherited ask skills, compatibility cleaners, developer/user manual
  chapters, and focused tests with the memory-first prompt policy.

## In Progress

- Keep docs and inherited ask skill wording aligned around result-intent-first
  selection and proactive use of `--silence`, `--compact`, and
  `--artifact-reply`.
- Coordinate chain-continuation finalization wording with
  [callback-continuation-safety](../callback-continuation-safety/README.md).
  That plan owns the runtime guard; this plan owns inherited ask skill wording.

## Next

- Keep Codex, Claude, and Droid inherited ask skill policy wording aligned.
- Project the chain-continuation finalization rule from
  [topics/skill-update-draft.md](topics/skill-update-draft.md) into inherited
  ask skill templates after the runtime guard contract is implementation-ready.
- Add or maintain template checks for result-intent and artifact-policy text.
- Add static assertions that each inherited ask skill template includes the
  chain-continuation finalization rule where an ask skill is projected.
- Run focused unit tests for ask skill templates and ask route option mapping.
- Re-run external source-under-test validation from
  `/home/bfly/yunwei/test_ccb2` when the matrix or skill wording changes.

## Deferred

- Any automatic callback routing behavior in `ccbd`.
- Any CLI warning for suspicious flag combinations.
- Any README expansion beyond a short mention of artifact ask modes.

## Release Gate

This policy update is ready when:

- inherited ask skills explain result intent before request fidelity;
- no inherited ask skill contains Chinese text or the old `ccb ask` command form;
- static template tests pass;
- ask route option mapping tests still pass;
- external `ccb_test` starts from an isolated project and projects updated ask
  skill text into managed provider homes where those providers are configured.

Latest verification (2026-07-30):

- 990 related unit and integration tests passed;
- source compilation and `git diff --check` passed.
