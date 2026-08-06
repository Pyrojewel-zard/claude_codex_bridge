# Native Windows Support

Date: 2026-07-20
Status: Deferred; legacy bridge analysis, not the current product transport
Mode: Reference analysis

Decision 006 selected tmux attachment as the primary product mode. Therefore
this earlier App Server/loopback-WebSocket proposal is not approved for
implementation in the current release. Native Windows consoles without tmux
remain out of scope; running Codex and tmux together in WSL2 is the supported
Windows-hosted route. A future native-Windows effort requires a new accepted
decision rather than silently reviving this proposal.

## Outcome

Native Windows support is feasible without changing the recovery state machine
or the `$reconnect on/off` user contract. The required work is a platform
boundary around the TUI-facing local WebSocket, state/runtime paths, file
permissions, installation, and qualification.

The recommended native Windows transport is an authenticated WebSocket bound
only to `127.0.0.1` on an operating-system-selected port. Codex CLI officially
accepts `ws://host:port` and `wss://host:port` for `--remote`, and accepts a
bearer token through `--remote-auth-token-env`. The bridge-to-App-Server side
should remain stdio JSONL.

## Current Portability Boundary

Portable without redesign:

- App Server JSONL protocol and bridge event routing;
- terminal network/overload classification;
- HTTPS readiness gate, same-thread reconciliation, and bounded continuation;
- `$reconnect on/off` interception and skill projection;
- process supervision and per-instance control semantics.

POSIX-specific today:

- the TUI-facing listener uses `socket.AF_UNIX` and a filesystem socket path;
- the managed CLI starts with `codex --remote unix://...`;
- runtime/state protection assumes `chmod`, `fchmod`, UID ownership, and short
  Unix socket paths;
- default state placement follows XDG/`~/.local/state`;
- installation and removal are shell scripts using a Unix executable link;
- transport tests create Unix-domain sockets, and CI has no Windows runner.

## Proposed Runtime Shape

```text
native Windows Codex TUI
        |
  ws://127.0.0.1:<ephemeral-port>
  Authorization: Bearer <per-instance-token>
        |
codex-reconnect bridge
  - loopback-only authenticated listener
  - existing control/event/recovery state machine
        |
  stdio JSONL
        |
  codex app-server --stdio
```

Linux, macOS, and WSL2 retain the existing Unix-domain-socket path. Native
Windows selects the loopback implementation through a small local-transport
abstraction; the recovery policy must not branch by platform.

## Transport and Security Contract

1. Bind IPv4 `127.0.0.1` with port `0`, then read the assigned port before
   starting the TUI. Never bind `0.0.0.0`, a LAN address, or an externally
   supplied host.
2. Generate a distinct 256-bit-or-stronger random token for every managed CLI
   instance.
3. Put the token only in the child TUI environment and launch Codex with
   `--remote-auth-token-env`. Do not place it in argv, control files, audit
   logs, or the App Server environment.
4. Validate `Authorization: Bearer ...` with a constant-time comparison before
   returning WebSocket HTTP 101. Missing or incorrect authentication fails
   closed; there is no unauthenticated fallback.
5. Accept one TUI client, preserve current frame/size/protocol validation, and
   close the listener when the managed instance ends.
6. Each concurrent `codex-reconnect open` owns its own port and token. Control
   remains thread-scoped and `$reconnect off` continues to win pending races.

Windows named pipes are not the first implementation because Codex CLI does
not expose a named-pipe `--remote` URL contract. Windows `AF_UNIX` alone is
also insufficient: the present implementation still relies on POSIX ownership,
mode, and path behavior. Authenticated loopback WebSocket uses Codex's public
remote surface and is independently testable on every CI platform.

## Filesystem and Process Contract

- Use `%LOCALAPPDATA%\codex-reconnect` as the default persistent state root.
- Put per-run runtime artifacts below a user-local runtime/temp directory and
  delete only the exact instance directory during normal cleanup.
- Isolate mode/ownership operations behind platform helpers. POSIX retains its
  current `0600`/`0700` behavior; Windows must not call `fchmod`, depend on
  UID checks, or advertise POSIX owner-only modes.
- For the first native release, rely on the inherited per-user LocalAppData
  ACL and verify the effective ACL during Windows acceptance. A later explicit
  DACL reset may harden this, but must account for enterprise policy and
  localized Windows installations.
- Keep the bearer token memory-only. The control file contains no transport
  credential.
- Preserve TUI exit, signal/console interruption, child termination, and audit
  redaction semantics on Windows; test these rather than assuming POSIX signal
  behavior.

## Installation Contract

Add native `install.ps1` and `uninstall.ps1` entry points:

- install the bundle under a per-user LocalAppData program directory;
- generate or install a `codex-reconnect.cmd` launcher that selects a supported
  Python 3 interpreter;
- update the user PATH idempotently and conservatively, explaining that a new
  shell may be required;
- verify both `codex` and supported Python before declaring success;
- preserve state and logs by default during uninstall;
- leave the current POSIX installer unchanged.

Packaging as a standalone `.exe` is not required for the first native release.
It can be evaluated after Python-based native behavior passes qualification.

## Implementation Blocks

1. Extract the common WebSocket handshake/framing code behind a local-listener
   interface and implement authenticated loopback TCP alongside Unix sockets.
2. Add platform path, permission, cleanup, and process helpers; preserve
   current Linux/macOS behavior with regression tests.
3. Select the transport in the managed launcher and pass the per-instance
   bearer token only to the TUI child environment.
4. Add PowerShell installation/removal and bilingual native Windows usage and
   security documentation.
5. Add Windows CI and complete native-machine qualification.

## Required Verification

Automated:

- missing, malformed, and incorrect bearer tokens are rejected before HTTP
  101; the correct token connects;
- listener is loopback-only, uses an OS-assigned port, and concurrent instances
  have different ports and tokens;
- tokens never appear in argv, audit output, logs, exceptions, or files;
- both listener implementations pass the same WebSocket protocol suite,
  including malformed and oversized handshakes/frames;
- existing disconnect/overload, reconciliation, circuit-breaker, reroute, and
  `$reconnect off` race suites pass over the TCP listener;
- Windows path/control/audit behavior has no unguarded POSIX calls;
- PowerShell install, update, uninstall, PATH idempotence, and state
  preservation tests pass;
- GitHub Actions covers `windows-latest` with the supported Python matrix while
  retaining Linux/macOS jobs.

Inspectable native Windows acceptance:

- installed Codex CLI and `codex app-server --stdio` complete the real
  initialization and thread smoke path;
- `$reconnect on/off` affects only the current managed CLI;
- two simultaneous managed CLIs remain isolated;
- injected `serverOverloaded` traverses the real bridge and produces one
  same-model bounded continuation;
- a real network interruption waits for primary OpenAI/Codex HTTPS recovery
  before continuing, without duplicate side effects;
- console close/Ctrl+C and ordinary TUI exit leave no listener or child process;
- effective state/log ACLs and token redaction are manually inspectable.

WSL2 is a separate qualification target. Running both Codex and
`codex-reconnect` inside WSL2 should continue through the POSIX path, but that
does not count as native Windows acceptance.

## Risks and Open Points

- Windows ACL inheritance varies under managed enterprise policy. The first
  release must describe its actual guarantee and must not claim POSIX `0600`
  equivalence without evidence.
- Python discovery and PATH updates differ between Store Python, the `py`
  launcher, and standard installers. The PowerShell installer needs explicit
  precedence and diagnostic output.
- Console interruption and subprocess-tree cleanup need real Windows evidence;
  POSIX signal tests do not prove them.
- Official Codex CLI flags are current external contracts and must be checked
  again immediately before implementation and release qualification.

## Historical Decision Gate

The design is implementation-ready if the following V1 choices are accepted:

- authenticated `127.0.0.1` ephemeral WebSocket for native Windows;
- memory-only per-instance bearer token passed through the TUI child
  environment;
- inherited per-user LocalAppData ACL plus explicit acceptance verification;
- Python/PowerShell distribution first, standalone executable deferred.

This gate is closed for the tmux release. If native Windows is reopened, record
a new transport and security decision before changing the standalone product
repository, and revalidate all cited Codex transport contracts at that time.
