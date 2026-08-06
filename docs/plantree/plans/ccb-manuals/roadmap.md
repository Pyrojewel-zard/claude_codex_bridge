# CCB Manuals Roadmap

Date: 2026-06-10

## Done

- Created a dedicated plan root for producing the CCB developer and user
  manuals.
- Confirmed existing planning baseline and contract docs already cover many
  architecture anchors.
- Confirmed existing Archi/Hippo artifacts are present under `.architec/`,
  current `.hippos/`, and legacy `.hippocampus/`.
- Confirmed `archi` CLI is installed and `archi --help` exposes `--full`,
  `--refresh-from-hippos`, `--check`, `--allow-static`, and `--out`.
- Ran `archi --check .`; preflight reported OK and claimed Hippos bundle
  refresh.
- Ran `archi --refresh-from-hippos --allow-static --out
  .architec/manual-architecture-analysis-20260610.json .`; confirmed current
  Hippos state is `.hippos/bundle-state.json`, generated 2026-06-10, while
  `.hippocampus/` is legacy evidence from 2026-05-29.
- Added an initial source inventory for the communication chapter covering CLI
  ask parsing/submission, ccbd submit handling, dispatcher submission, message
  bureau records, running/polling/finalization, and callback edges.
- Added a first-pass source inventory for CLI command groups, roles/tools
  management commands, and project configuration grammar.
- Added a dated evidence ledger for the initial Archi/Hippo and source
  inventory pass.
- Recorded manual production defaults for language, LaTeX source location, PDF
  commit policy, page target, Archi/Hippo evidence use, and runtime example
  validation.
- Extended the communication source inventory to cover observer commands,
  queue/inbox/ack views, trace lineage, retry/resubmit/cancel, artifacts, and
  reply delivery entrypoints.
- Created and built the developer manual source tree under
  `docs/manuals/developer-guide/`.
- Developer manual output:
  `docs/manuals/developer-guide/build/main.pdf`, A4 PDF, 82 pages.
- Created and built the user manual source tree under
  `docs/manuals/user-guide/`.
- User manual output: `docs/manuals/user-guide/build/main.pdf`, A4 PDF,
  38 pages.
- Added local `.gitignore` files under both manual directories so generated
  build artifacts remain local and the tracked source stays LaTeX-only.
- Revised the shared manual style layer with professional title pages,
  restrained blue/gray typography, custom chapter/section headings, stable page
  headers, CJK slant fallback, syntax-colored code blocks, line numbers, and
  safer inline source/command wrapping.
- Incorporated reviewer1's user-manual content review:
  `job_8906713f6caf-art_4cc0a0677a114bcb.txt`.
- Updated the user manual so current `version = 2` config remains the main
  narrative, version 1 is only a historical supplement, "legacy layout" is
  renamed to "基础布局模式", maintenance command behavior matches source, and
  command/config appendices cover the reviewed gaps.
- Added a Markdown `ccb_self` expert guide at
  `docs/manuals/ccb-self-expert-guide.md`, focused on role mission, authority
  hierarchy, config expertise, command surface, communication logic,
  diagnostics, recovery playbooks, and source navigation.
- Synchronized the developer/user communication chapters and communication
  source inventory with the memory-first prompt policy on 2026-07-30: stable
  reply/cancellation rules live in managed project memory, and per-request
  prompts carry only dynamic reply-mode metadata.

## In Progress

- No active implementation work remains for this manual-production pass.

## Next

1. Optional editorial pass: normalize long monospace path wrapping if a
   print-ready PDF requires zero overfull/underfull layout warnings.
2. Optional expansion pass: add figures beyond the current architecture and
   communication explanations if a visual-heavy edition is desired.
3. Optional release pass: decide whether generated PDFs should be published as
   release artifacts outside git.
4. Optional role-pack integration pass: decide whether the Markdown
   `ccb_self` guide should be copied or summarized into the distributable
   `agentroles.ccb_self` Role Pack after role asset review.

## Deferred

- Public release packaging for the manuals.
- Translation into a second language if the first draft chooses one primary
  language.
- Diagrams beyond the first essential architecture and communication flow
  figures.
- Any runtime refactor suggested by the manuals.

## Execution Gate

Do not start the main LaTeX draft until:

- the target output directory is selected; selected by decision as
  `docs/manuals/developer-guide/` and `docs/manuals/user-guide/`;
- the manual language and source style are decided; selected by decision as
  Chinese LaTeX prose with commands/source identifiers in English;
- Archi/Hippo evidence consumers use `.hippos/` as current evidence and label
  `.hippocampus/` as legacy evidence;
- the communication chapter source map is accepted as complete enough for a
  first draft;
- current CLI command inventory has been generated from source, with help
  output snapshots required before the final user manual reference.

## Verification Gate

Completed for this pass:

- `make` in `docs/manuals/developer-guide` completed successfully.
- `pdfinfo docs/manuals/developer-guide/build/main.pdf` reported 82 pages.
- `make` in `docs/manuals/user-guide` completed successfully.
- `pdfinfo docs/manuals/user-guide/build/main.pdf` reported 38 pages.
- Manual source trees contain 4125 non-build lines across LaTeX sources,
  READMEs, Makefiles, and local ignore files.
- Log checks found no `Overfull`, `Font Warning`, `undefined`, `Warning`,
  `Emergency`, or `Runaway` diagnostics in either manual build log after the
  style pass.
- Markdown guide checks found no trailing whitespace in
  `docs/manuals/ccb-self-expert-guide.md` and the manuals root index.
