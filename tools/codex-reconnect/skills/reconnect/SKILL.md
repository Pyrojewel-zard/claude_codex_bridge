---
name: reconnect
description: Toggle disconnect recovery for the current Codex CLI session. Use only when the user explicitly invokes `$reconnect on` or `$reconnect off` in a codex-reconnect-managed CLI.
---

# Reconnect

Treat the exact invocation as a control command already applied by the managed local transport.

- For `$reconnect on`, reply that reconnect recovery is on for this session.
- For `$reconnect off`, reply that reconnect recovery is off for this session.
- For any other argument, reply with the exact usage: `$reconnect on` or `$reconnect off`.

Do not run tools, change files, start a goal, continue normal work, or claim coverage for quota,
authentication, policy, context-window, or ordinary task-completion conditions.
