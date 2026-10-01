# Model-independent composer observation

Date: 2026-09-27
Role: evidence
Status: locally verified; not committed, published or installed
Related: [contract](../topics/input-draft-delivery-guard.md)

Owner requirement: switching model names must not determine whether CCB can
recognize the input box. PR #361 fixed capitalization only; this follow-up
removes the model-prefix dependency instead of extending its vocabulary.

## Source changes and audit

- `lib/provider_execution/draft_observation.py:inspect_screen` delegates Codex
  footer detection to `_codex_footer`. The boundary is the last nonblank row,
  below the cursor and a blank separator. Recognized evidence is a shortcut or
  context hint, or an ANSI-dim middle-dot field separator. Configurable labels
  are not matched. Placeholder, continuation, cursor and busy checks remain.
- Claude's same parser uses horizontal borders and dim/inverse ghost input;
  its send/poll composer helpers use arrows, boxes and status hints, not model
  names. No Claude production change was needed.
- `lib/provider_execution/draft_guard.py:DraftTarget.observe` checks OMP's
  default Status Band editor focus and requests native state.
  `lib/provider_backends/omp/composer_bridge.py:editorReply` uses `isIdle()` and
  `getEditorText()`, bound to actor/launch/runtime/session. No model-name check
  or OMP production change was needed.

## Verification

`uv run --no-project --with pytest python -m pytest -q
test/test_composer_model_independence.py test/test_input_draft_guard.py
test/test_input_draft_fifo.py`: **178 passed**.

Tests replay captured Codex layouts with capitalized, unrelated, custom,
Unicode and absent model labels; cover Claude blank/multiline input with those
labels and mocked OMP native empty/nonempty/unknown plus menu focus. Existing
captures include busy, model picker, wrapping, whitespace, collapsed paste
and narrow panes. New adversarial checks reject model-only footers and plain
draft middle dots, avoid ignoring content after a footer-like line, and retain
multiline and editor-mode protection. These are fixture/unit tests, not live
provider-switch or real terminal qualification.

## Limits and next gate

Unknown remains blocked; 180 seconds and FIFO semantics are unchanged. A
custom single-field status bar without a recognized hint or dim separator is
not qualified, even if its sole field happens to be a model name. Wrapped or
additional-row footer layouts also remain unknown. No claim covers arbitrary
themes/layouts. Validate supported native layouts in a disposable project
before publishing; no existing panes, external provider state or installed
runtime were changed. Reverting this source slice restores the prior parser
without changing persisted state.
