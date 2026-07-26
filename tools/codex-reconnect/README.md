# codex-reconnect

`codex-reconnect` is an independent, disconnect-only supervisor for the
interactive Codex CLI. It has no CCB, tmux, pane, or Workbench dependency.

## Start and activate

Open Codex through the supervisor:

```sh
tools/codex-reconnect/codex-reconnect open
```

Forward normal Codex arguments after `--`:

```sh
tools/codex-reconnect/codex-reconnect open -- -m MODEL_ID -C /path/to/project
tools/codex-reconnect/codex-reconnect open -- resume SESSION_ID
```

Inside that Codex CLI, use only:

```text
$reconnect on
$reconnect off
```

The skill is projected into this App Server process at startup. It does not
modify the user's global Codex skill or plugin configuration. Each `open`
process has a separate socket, control record, and thread-scoped switch, so
multiple managed Codex CLIs can be armed independently.

An ordinary Codex CLI that was opened without `codex-reconnect open` cannot be
hot-attached: its existing App Server connection cannot be replaced safely.

## Exact scope

When armed for the current `threadId`, the supervisor reacts only to terminal
turn failures classified as:

- `httpConnectionFailed`;
- `responseStreamConnectionFailed`;
- `responseStreamDisconnected`;
- `responseTooManyFailedAttempts`;
- `serverOverloaded`.

It does not continue a normally completed turn. It also does not handle usage
quota exhaustion, billing, authentication, authorization, policy/safety,
context-window limits, ordinary task continuation, or persistent goals.

Codex's own retry remains authoritative. An `error` event with
`willRetry=true` causes no duplicate turn; recovery begins only after the turn
is terminally `failed`.

## Recovery contract

1. Keep the exact model observed for the current thread. No fallback or model
   downgrade is requested.
2. For a network failure, probe the OpenAI/Codex HTTPS path until it succeeds
   twice consecutively. Google `generate_204` is an optional diagnostic probe;
   it is not a substitute for OpenAI reachability.
3. For `serverOverloaded`, wait with jitter, then pass the same HTTPS gate.
4. Call `thread/read(includeTurns=true)` through the original TUI/App Server
   connection.
5. If a user turn is already active or newer progress exists, do nothing.
6. If the same failed turn is still latest, start exactly one continuation:

   ```text
   上一轮因网络中断或模型服务高负载而失败。先检查本会话现有进度和工作区状态，只继续尚未完成的部分，不重复已经完成的操作。
   ```

7. If that recovery turn also fails, open the circuit and require user action.
   If the server reroutes that recovery turn to another model, interrupt it.

The bridge is transparent: TUI requests and notifications stay on one logical
App Server connection, so normal approval requests remain visible in the same
CLI.

## Diagnostics and logs

Probe connectivity without starting Codex:

```sh
tools/codex-reconnect/codex-reconnect probe
```

Check the installed App Server handshake without creating a thread:

```sh
tools/codex-reconnect/codex-reconnect handshake
```

Managed-session audit and App Server stderr logs are written owner-only under:

```text
${XDG_STATE_HOME:-~/.local/state}/codex-reconnect/managed/
```

## Verification

```sh
python3 -m unittest discover -s tools/codex-reconnect/tests -v
```

The 15-test deterministic suite covers the UDS WebSocket bridge, skill
projection, exact on/off interception, structured failure classification,
two-success network gate, reconciliation races, same-model continuation, and
recovery circuit breaker. Its injected `serverOverloaded` path additionally
proves that internal retry does not trigger early recovery, model rerouting is
interrupted, a failed recovery opens the circuit, and `$reconnect off` cancels
overload backoff. A live no-turn smoke test also verifies the bridge and exact
`$reconnect` skill name against the installed App Server.

Linux and macOS are the current supported platforms because the local bridge
uses Unix-domain sockets. Real induced network-fault and high-demand acceptance
remains a production-qualification gate.

## Related projects checked

No drop-in GitHub project was found for this exact current-TUI behavior. The
nearest projects or issue patterns are:

- [OpenAI Codex App Server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md):
  the structured protocol and Unix-socket foundation used here;
- [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc):
  persistent Codex threads and background delegation from Claude Code, not
  in-place Codex TUI disconnect recovery;
- [OpenClaw watchdog issue](https://github.com/openclaw/openclaw/issues/77984):
  an App Server watchdog pattern for idle/completion timeout, not network-gated
  same-session continuation;
- [AICTX](https://github.com/oldskultxo/aictx): durable context handoff across
  sessions and agents, not recovery of one failed live Codex turn.
