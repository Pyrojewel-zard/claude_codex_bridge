# Claude native composer plugin: real CLI qualification

Date: 2026-09-28 (Asia/Shanghai; logs use 2026-09-27 UTC)
Role: evidence
Status: isolated prototype verified; not production-ready or integrated
Related: [guard contract](../topics/input-draft-delivery-guard.md),
[previous real communication tests](claude-continuous-queue-live-20260927.md)

## Scope and environment

Tested the real installed Claude Code 2.1.278 executable in new PTYs, using
an external plugin loaded through `--plugin-dir`. No existing pane, CCB
configuration, production code, credentials or business session was edited.
The temporary config home and plugin were under
`/var/tmp/claude-native-probe-i4CmyN`. A synthetic non-credential API value
and `http://127.0.0.1:9` prevented model access. These are real editor/plugin
tests, **not** model-answer, busy-turn, or CCB communication qualification.

Pinned executable: `/home/bfly/.local/share/claude/versions/2.1.278`.
SHA256 before/after audit: `5c4735937844e84f8a93306e841a5b0e12252909b07870f789b190468da147ab`.
The first CLI displayed its own “Update installed” notice. Subsequent processes
used `DISABLE_AUTOUPDATER=1`; all tests continued using the pinned executable.
The test did not audit or revert the updater's external effects. Future probes
must disable native auto-update from the first launch.

## Observed results

| Scenario | Actual observation | Meaning |
| --- | --- | --- |
| Explicit function-hook enablement | `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`; module loaded in worker environment, admitted at user tier after temporary-workspace trust | Ordinary external module entry works in this pinned build when explicitly enabled |
| Empty composer with default hint | `read()` returned `{text:"",cursor:0}` | Default display hint is not a draft |
| Typed text | `DRAFT_ONE_中文`, cursor 12; matching `prompt.edit` result | Real text readback and edit callback work |
| Three-line bracketed paste | Exact `LINE_A\nLINE_B\n第三行`, cursor 17 | Small multiline input is preserved |
| Plugin-injected native suggestion | `suggest({text:"GHOST_NATIVE_PROBE"})` returned `isShown:true`; read stayed empty | Unaccepted native suggestion is separate from draft; this is a deterministic native suggestion, not model-generated text |
| Tab acceptance | Read changed to `GHOST_NATIVE_PROBE`; recorded edit array remained empty | **Edit events alone miss a draft transition** |
| `/model` modal | Read returned empty; native fill returned `isFilled:false` | Empty read is not readiness; modal rejects fill |
| Exit modal, replace multiline | `fill(...,mode:"replace")` returned `isFilled:true`; exact `FILL_A\nFILL_B\n填充` readback | Write resumes after modal exit |
| Clear multiline | Replace with empty returned `isFilled:true`, empty text and cursor 0 | Native whole-text clear works in the tested plain composer |
| Eleven-line paste | UI and read both showed `[Pasted text #1 +10 lines]`; no new edit event was recorded | Nonempty remains detectable, but read does **not** expose expanded paste content; events miss this path too |
| Clear folded paste | Replace empty succeeded, subsequent read empty | Editor text cleared; attachment/paste storage and next submitted payload were not independently checked |
| Unicode and cursor-only motion | `abc😀中` cursor 6, left arrow cursor 5; second edit event had empty inputText | Cursor follows JS UTF-16 offsets in this case, not terminal columns; event is not exclusively text change |
| Headless `-p`, module enabled | Repeated `no prompt box bound; the empty box`; read empty; fill false | Reproduces dangerous unbound-empty fallback |
| Surface query | Headless: `surface:null,surfaces:[]`; TUI: `terminal,[terminal]` | Useful supporting binding signal in these runs |
| Surface query during modal | Still `terminal,[terminal]` with empty read | Surface query does not solve modal/readiness detection |
| Disable function hooks | Explicit value `0`: log says installed module not loaded because rollout flag is off | Missing capability must not reuse an old empty snapshot |
| New CLI sessions | IDs changed across launches; final TUI ID `43158a54-b57d-493a-9388-0cfb4c3bd35c`, headless ID `cba3800b-d0a1-411d-b964-5a6f7d949db4` | Bind observations to current process/session; restart is not continuity |

Interactive processes exited normally using their own PTY input. Headless
processes were bounded by `timeout` (exit 124 expected: no working API endpoint).
Snapshots persist after process exit and are therefore stale without liveness
and identity validation. No headless model result is claimed.

## Reproduction recipe and evidence anchors

Create `.claude-plugin/plugin.json` with a name/version and `hooks/hooks.json`
containing `{"modules":["./probe.js"]}`. The JS module exports
`register(on)`, registers `session.start` and `prompt.edit`, and returns
`next(e)` from both. The tested session-start handler installed
`$.clock.every(400, async () => { ... })`, reading `$.prompt.read()` and writing
a JSON snapshot through `$.fs.write(absoluteTestPath, JSON.stringify(snapshot))`.
The edit handler awaited `next(e)` and recorded `{text:e.text,
inputText:e.inputText,result}` without changing its result.

For controlled actions, the timer read a test-local JSON command with a unique
ID and invoked exactly once either `$.prompt.suggest({text})` or
`$.prompt.fill({text,mode:"replace"})`. This was test control only, not a
production IPC design. Later snapshots also read `$.session.surface()`,
`$.session.surfaces()` and `$.session.id()`. No hooks were registered after
`register()` returned. No vendor binary was patched.

Launch the pinned binary in the disposable directory with a private
`CLAUDE_CONFIG_DIR`, `DISABLE_AUTOUPDATER=1`, the synthetic API environment,
`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`, `--plugin-dir <plugin>` and
`--debug-file <test-log>`. Accept only this newly created test workspace.
Repeat with `-p`, bounded timeout, and then hook flag `0` for negative controls.

Sanitized log anchors from this run (UTC):

- `22:34:30.136`: module loaded; events `session.start,prompt.edit`.
- `22:34:30.138`: `plugin.register ... admitted`.
- `22:37:16.513`: headless `no prompt box bound; the empty box`.
- `22:37:48.214`: installed module skipped, rollout flag off.
- `22:38:05.370`: second headless unbound-empty observation.

Static cross-checks in this exact binary (byte offsets, not stable API names):
197365839: rollout flag `tengu_plugin_hooks_modules`, default false;
200145589: unbound read fallback; 202020601: `vPn` reads hooks modules;
202021770: `Hqo` validates module path; 218459861: edit relay;
219099047: `readDraft`/`fillDraft`/`suggestDraft` implementations.
The public [plugin reference](https://code.claude.com/docs/en/plugins-reference)
inspected during the preceding audit did not document these interfaces.
Do not equate this experiment with a published compatibility guarantee.

## Readiness consequence

Retain the existing guard. Native polling can distinguish ghost text from
drafts without model/placeholder vocabulary, and native replace is a promising
alternative to Ctrl-C. However, production promotion remains blocked by:

1. Unsupported/gray-rollout compatibility and the opt-in enablement policy.
2. Independent current-composer, modal and provider-busy validation; terminal
   surface plus empty read is insufficient.
3. Attachments, folded-paste payload retention after clear, Vim modes and
   other layouts not yet qualified. No claim of a complete attachment clear.
4. Process/session binding, fresh request/readback and plugin-loss handling.
   Neither file existence nor a cached empty snapshot proves a live editor.
5. Final read/clear/paste/Enter races: no conditional compare-and-clear or
   atomic delivery contract was established.

If prototyped further, poll native state at the existing delivery boundary;
do not rely solely on `prompt.edit` or add editing-based timer resets. Preserve
the existing provider turn detector, FIFO and fixed 180-second policy. Keep
unknown fail-closed only on enabled protected paths; no global stop or default
enablement is authorized by these tests.

## Cleanup

All six probe processes finished (three TUI, three bounded headless). The
temporary project/config/plugin/logs are moved to system Trash after recording
this evidence, recoverable. No CCB daemon was started. The report and linked
summaries are the only new durable project changes from this test campaign.
