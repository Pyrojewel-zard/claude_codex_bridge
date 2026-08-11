# Paseo-Aligned Provider Control Plane Acceptance

Date: 2026-08-12
Status: Accepted

## Baseline And Scope

- CCB source baseline: `origin/main` at `41c880f5`.
- Paseo reference: `getpaseo/paseo` at
  `b599d38a772f621e0001abfb90a769de11c8cd8b`.
- Adaptation provenance and source mapping:
  `mobile/THIRD_PARTY_NOTICES.md` and Decision 025.
- CCB retains Flutter, Python gateway, ccbd, tmux, project/window/agent, and
  Provider-session authority. No Paseo daemon, React Native UI, asset, icon,
  credential, or runtime process is bundled.

The accepted surface includes Provider identity, capability-driven model and
thinking controls, explicit configured/active/pending state, native session
usage, isolated account quota, guarded mutation, and visible native-session
boundaries. Current Codex and Claude mutations are truthfully declared
`restart_required`; no guessed live Provider command is sent.

## Real Android Emulator

- Device: `emulator-5554`, Android 15, AVD `ccb_api35`, 1080 x 2400.
- Gateway: independent server-wide loopback instance on
  `http://127.0.0.1:18892` through `adb reverse`.
- Acceptance project: disposable mounted project under
  `/home/bfly/yunwei/test_ccb2`, with dedicated `codex_probe` and
  `claude_probe` agents. No prompt was sent to `ccb_mobile`, `ccb_source`, or
  another active user project.
- App: `8.5.7+8050007`.

Accepted behaviors:

1. Codex and Claude sheets display the actual Provider, active/configured
   model, thinking option, apply mode, and native session usage.
2. Supported selections persist through the authenticated app path; stale
   epoch/revision mutation is rejected without changing configuration.
3. Switching agents does not bleed model or usage state.
4. A real Codex `clear` creates a second native session. Existing history is
   retained and a single `New context` divider appears at the boundary.
5. Claude native usage resolves from the managed session binding rather than
   terminal fallback.
6. The final clean logcat window contains no crash, ANR, OOM, or error entry.

Key local evidence is under
`/tmp/ccb-mobile-provider-control-20260812/emulator/`:

- `codex-provider-sheet.png`
- `codex-session-usage-metrics.png`
- `claude-provider-sheet.png`
- `claude-real-session-usage-metrics.png`
- `claude-selection-confirmed.png`
- `session-boundary-after-refresh.png`
- `codex-provider-control-final-redacted.json`
- `claude-provider-control-real-redacted.json`
- `codex-session-boundary-redacted.json`
- `stale-mutation-redacted.json`
- `logcat-final-window.txt`
- `logcat-final-window-errors.txt`

Pairing secrets, device tokens, raw prompts/replies, and raw Provider session
identifiers are not included in this plan-tree record.

## Performance

Twenty authenticated samples were recorded for each Provider before and after
the request-path correction. Every sample returned HTTP 200.

| Provider | Before p50 | Before p95 | After p50 | After p95 | p95 improvement |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Codex | 1042.6 ms | 1062.8 ms | 27.6 ms | 38.6 ms | 96.37% |
| Claude | 1046.9 ms | 1062.8 ms | 27.9 ms | 33.2 ms | 96.87% |

The old delay came from probing unrelated optional OpenCode and Mimo CLIs on
every Codex/Claude Provider-control request. The fixed path supplies the
already-known matching catalog and leaves full optional-Provider discovery in
the configuration UI. Account quota remains independently cached and cannot
delay chat or Provider identity.

Machine-readable measurements:

- `provider-control-latency-before.csv`
- `provider-control-latency-before-summary.json`
- `provider-control-latency-after.csv`
- `provider-control-latency-after-summary.json`
- `provider-control-latency-comparison.json`

## Verification

- Provider/source focused suites: 224 passed.
- Flutter Provider/session focused suites: 49 passed.
- Full Flutter suite: 743 passed, 1 skipped.
- `flutter analyze`: no issues.
- Full Python non-blackbox run: 6657 passed, 3 skipped, 21 deselected, with one
  unrelated two-worker workflow smoke race; that exact smoke passed on the
  immediate isolated rerun in 42.84 seconds.
- Python compilation and scoped diff checks: passed.
- Debug APK SHA-256:
  `f6253556b7aae0108994330b62ce75e9ca9313626cf6efe9c9392030b4b8f1f7`.
- Profile APK SHA-256:
  `49ba09f53e2b71886f1d768ca22a8ead36acca610baa3b39968228ad4d1543f6`.

## Residual Limits

- Provider account quota is unavailable when the host lacks an authoritative
  managed credential/adapter. Unavailable is a supported truthful state.
- Codex and Claude model/thinking changes require a managed restart; hot switch
  is not advertised.
- Built-in model catalogs can age and require ordinary source updates.
- Real Emulator acceptance used the Direct route. Encrypted Relay contract
  parity is covered by automated transport tests, not this manual matrix.
- One real Claude response took roughly two minutes; endpoint timing and
  native transcript evidence identify that delay as Provider execution, not
  Provider-control request latency.
