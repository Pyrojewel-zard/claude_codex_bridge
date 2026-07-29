from __future__ import annotations

import hashlib
import os
from pathlib import Path

from provider_core.contracts import ProviderRuntimeLauncher

from provider_backends.native_cli_support import NativeCliLaunchConfig
from provider_backends.native_cli_support.launcher import (
    build_session_payload as build_native_session_payload,
)
from provider_backends.native_cli_support.launcher import (
    build_start_cmd as build_native_start_cmd,
)
from provider_backends.native_cli_support.launcher import (
    prepare_launch_context as prepare_native_launch_context,
)

_PI_COMPLETION_SCHEMA_VERSION = 1
_PI_EXTENSION_FILENAME = "ccb-pi-completion.ts"


def build_runtime_launcher() -> ProviderRuntimeLauncher:
    config = _launch_config()
    return ProviderRuntimeLauncher(
        provider="pi",
        launch_mode="simple_tmux",
        prepare_launch_context=lambda context, spec, plan, runtime_dir, prepared_state: (
            prepare_native_launch_context(
                config,
                context,
                spec,
                plan,
                runtime_dir,
                prepared_state,
            )
        ),
        build_start_cmd=lambda command, spec, runtime_dir, launch_session_id, prepared_state=None: (
            _build_start_cmd(
                config,
                command,
                spec,
                Path(runtime_dir),
                launch_session_id,
                prepared_state=prepared_state,
            )
        ),
        build_session_payload=lambda context, spec, plan, runtime_dir, run_cwd, pane_id, pane_title_marker, start_cmd, launch_session_id, prepared_state: (
            _build_session_payload(
                config,
                context,
                spec,
                plan,
                Path(runtime_dir),
                Path(run_cwd),
                pane_id,
                pane_title_marker,
                start_cmd,
                launch_session_id,
                prepared_state,
            )
        ),
    )


def _launch_config() -> NativeCliLaunchConfig:
    return NativeCliLaunchConfig(
        provider="pi",
        visible_args_builder=_pi_visible_args,
        visible_env_builder=_pi_visible_env,
        visible_path_env_names=(
            "PI_CODING_AGENT_DIR",
            "PI_CODING_AGENT_SESSION_DIR",
        ),
        visible_raw_env_names=(
            "PI_SKIP_VERSION_CHECK",
            "PI_TELEMETRY",
            "CCB_PI_COMPLETION_EVENTS",
            "CCB_PI_DISPATCH_EVENTS",
        ),
    )


def _build_start_cmd(
    config: NativeCliLaunchConfig,
    command,
    spec,
    runtime_dir: Path,
    launch_session_id: str,
    *,
    prepared_state: dict[str, object] | None,
) -> str:
    if prepared_state is None:
        raise RuntimeError("pi launch requires prepared_state")
    _materialize_completion_extension(
        prepared_state,
        runtime_dir=runtime_dir,
        launch_session_id=launch_session_id,
    )
    return build_native_start_cmd(
        config,
        command,
        spec,
        runtime_dir,
        launch_session_id,
        prepared_state=prepared_state,
    )


def _build_session_payload(
    config: NativeCliLaunchConfig,
    context,
    spec,
    plan,
    runtime_dir: Path,
    run_cwd: Path,
    pane_id: str,
    pane_title_marker: str,
    start_cmd: str,
    launch_session_id: str,
    prepared_state: dict[str, object],
) -> dict[str, object]:
    payload = build_native_session_payload(
        config,
        context,
        spec,
        plan,
        runtime_dir,
        run_cwd,
        pane_id,
        pane_title_marker,
        start_cmd,
        launch_session_id,
        prepared_state,
    )
    payload.update(
        {
            "pi_completion_schema_version": _PI_COMPLETION_SCHEMA_VERSION,
            "pi_completion_extension": str(
                prepared_state.get("pi_completion_extension") or ""
            ),
            "pi_completion_event_log": str(
                prepared_state.get("pi_completion_event_log") or ""
            ),
            "pi_dispatch_event_log": str(
                prepared_state.get("pi_dispatch_event_log") or ""
            ),
        }
    )
    return payload


def _pi_visible_args(prepared_state: dict[str, object]) -> tuple[str, ...]:
    session_dir = _pi_session_dir(prepared_state)
    extension_path = _path_from_prepared(prepared_state, "pi_completion_extension")
    session_dir.mkdir(parents=True, exist_ok=True)
    return (
        "--session-dir",
        str(session_dir),
        "--extension",
        str(extension_path),
        "--no-approve",
    )


def _pi_visible_env(prepared_state: dict[str, object]) -> dict[str, str]:
    home_dir = _path_from_prepared(prepared_state, "pi_home")
    session_dir = _pi_session_dir(prepared_state)
    completion_events = _path_from_prepared(
        prepared_state,
        "pi_completion_event_log",
    )
    dispatch_events = _path_from_prepared(prepared_state, "pi_dispatch_event_log")
    home_dir.mkdir(parents=True, exist_ok=True)
    session_dir.mkdir(parents=True, exist_ok=True)
    return {
        "PI_CODING_AGENT_DIR": str(home_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(session_dir),
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "CCB_PI_COMPLETION_EVENTS": str(completion_events),
        "CCB_PI_DISPATCH_EVENTS": str(dispatch_events),
    }


def _pi_session_dir(prepared_state: dict[str, object]) -> Path:
    state_dir = _path_from_prepared(prepared_state, "pi_state_dir")
    return state_dir / "sessions"


def _path_from_prepared(prepared_state: dict[str, object], key: str) -> Path:
    raw = str(prepared_state.get(key) or "").strip()
    if not raw:
        raise RuntimeError(f"pi launch requires {key} in prepared_state")
    return Path(raw).expanduser()


def _materialize_completion_extension(
    prepared_state: dict[str, object],
    *,
    runtime_dir: Path,
    launch_session_id: str,
) -> None:
    launch_id = str(launch_session_id or "").strip()
    if not launch_id:
        raise RuntimeError("pi launch requires a launch session id")
    completion_dir = runtime_dir / "completion"
    completion_dir.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(launch_id.encode("utf-8", "replace")).hexdigest()[:16]
    extension_path = completion_dir / _PI_EXTENSION_FILENAME
    completion_events = completion_dir / f"pi-pane-{token}.events.jsonl"
    dispatch_events = completion_dir / f"pi-pane-{token}.dispatch.jsonl"

    _write_owner_only(extension_path, _PI_COMPLETION_EXTENSION_SOURCE)
    _touch_owner_only(completion_events)
    _touch_owner_only(dispatch_events)
    prepared_state["pi_completion_schema_version"] = _PI_COMPLETION_SCHEMA_VERSION
    prepared_state["pi_completion_extension"] = str(extension_path)
    prepared_state["pi_completion_event_log"] = str(completion_events)
    prepared_state["pi_dispatch_event_log"] = str(dispatch_events)


def _write_owner_only(path: Path, content: str) -> None:
    current = ""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        pass
    if current != content:
        path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _touch_owner_only(path: Path) -> None:
    path.touch(exist_ok=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


_PI_COMPLETION_EXTENSION_SOURCE = r'''import { appendFileSync, readFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";

const schemaVersion = 1;
const eventPath = process.env.CCB_PI_COMPLETION_EVENTS || "";
const dispatchPath = process.env.CCB_PI_DISPATCH_EVENTS || "";
const actor = process.env.CCB_CALLER_ACTOR || "";
const launchSessionId = process.env.CCB_SESSION_ID || "";
const runtimeInstanceId = randomUUID();
const consumedDispatches = new Set<string>();
let activeReqId = "";
let latestAssistant: Record<string, unknown> | null = null;

function appendEvent(type: string, details: Record<string, unknown> = {}): void {
  if (!eventPath || !actor || !launchSessionId) return;
  const record = {
    schema_version: schemaVersion,
    type,
    actor,
    launch_session_id: launchSessionId,
    runtime_instance_id: runtimeInstanceId,
    timestamp: new Date().toISOString(),
    req_id: activeReqId,
    ...details,
  };
  try {
    appendFileSync(eventPath, JSON.stringify(record) + "\n", {
      encoding: "utf8",
      mode: 0o600,
    });
  } catch {
    // Completion instrumentation must never crash or mutate the Pi session.
  }
}

function promptHash(prompt: string): string {
  return createHash("sha256").update(prompt, "utf8").digest("hex");
}

function requestAnchor(prompt: string): string {
  const firstLine = String(prompt || "").split(/\r?\n/, 1)[0].trim();
  const match = /^CCB_REQ_ID:\s*(\S+)\s*$/.exec(firstLine);
  return match ? match[1] : "";
}

function matchingDispatch(prompt: string): Record<string, unknown> | null {
  if (!dispatchPath) return null;
  let raw = "";
  try {
    raw = readFileSync(dispatchPath, "utf8");
  } catch {
    return null;
  }
  const digest = promptHash(prompt);
  const records: Record<string, unknown>[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const value = JSON.parse(line);
      if (value && typeof value === "object") records.push(value);
    } catch {
      return null;
    }
  }
  for (let index = records.length - 1; index >= 0; index -= 1) {
    const record = records[index];
    const reqId = String(record.req_id || "");
    const dispatchId = String(record.dispatch_id || "");
    if (
      Number(record.schema_version) === schemaVersion &&
      String(record.actor || "") === actor &&
      String(record.launch_session_id || "") === launchSessionId &&
      String(record.runtime_instance_id || "") === runtimeInstanceId &&
      String(record.prompt_sha256 || "") === digest &&
      reqId &&
      dispatchId &&
      !consumedDispatches.has(dispatchId)
    ) {
      consumedDispatches.add(dispatchId);
      return record;
    }
  }
  return null;
}

function visibleText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((block) => block && typeof block === "object" && block.type === "text")
    .map((block) => String(block.text || ""))
    .join("");
}

function normalizeStopReason(value: unknown): string {
  return String(value || "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/-/g, "_")
    .toLowerCase();
}

function normalizeAssistant(message: unknown): Record<string, unknown> | null {
  if (!message || typeof message !== "object") {
    return null;
  }
  const value = message as any;
  if (value.role !== "assistant") return null;
  return {
    text: visibleText(value.content),
    stop_reason: normalizeStopReason(value.stopReason || value.stop_reason),
    error: String(value.errorMessage || value.error_message || ""),
    response_id: String(value.responseId || value.id || ""),
    timestamp: value.timestamp || null,
  };
}

function rememberAssistant(message: unknown): void {
  const normalized = normalizeAssistant(message);
  if (normalized) latestAssistant = normalized;
}

function bindDispatchedInput(prompt: string, source: string): boolean {
  const dispatch = matchingDispatch(prompt);
  if (!dispatch) return false;
  const dispatchReqId = String(dispatch.req_id || "");
  const anchorReqId = requestAnchor(prompt);
  if (activeReqId && activeReqId !== dispatchReqId) {
    appendEvent("request_superseded", {
      req_id: activeReqId,
      superseded_by: dispatchReqId,
      input_source: source,
    });
  }
  latestAssistant = null;
  activeReqId = dispatchReqId;
  if (dispatchReqId && anchorReqId && dispatchReqId !== anchorReqId) {
    appendEvent("binding_error", {
      req_id: dispatchReqId,
      dispatch_req_id: dispatchReqId,
      anchor_req_id: anchorReqId,
    });
    activeReqId = "";
  }
  appendEvent("request_start", {
    req_id: activeReqId,
    anchor_req_id: anchorReqId,
    dispatch_matched: Boolean(dispatchReqId),
    input_source: source,
  });
  return true;
}

export default function ccbPiCompletion(pi: any): void {
  appendEvent("extension_ready");

  pi.on("input", async (event: any) => {
    const prompt = String(event?.text || "");
    const source = String(event?.source || "unknown");
    if (bindDispatchedInput(prompt, source)) {
      return { action: "continue" };
    }
    if (activeReqId && source !== "extension") {
      const supersededReqId = activeReqId;
      appendEvent("request_superseded", {
        req_id: supersededReqId,
        superseded_by: "unmanaged_input",
        input_source: source,
        input_sha256: promptHash(prompt),
      });
      activeReqId = "";
      latestAssistant = null;
    }
    return { action: "continue" };
  });

  pi.on("before_agent_start", async (event: any) => {
    if (activeReqId) return;
    const prompt = String(event?.prompt || "");
    bindDispatchedInput(prompt, "before_agent_start");
  });

  pi.on("agent_start", async () => {
    appendEvent("agent_start");
  });

  pi.on("message_end", async (event: any) => {
    rememberAssistant(event?.message);
    if (activeReqId && latestAssistant) {
      appendEvent("assistant_message", { assistant: latestAssistant });
    }
  });

  pi.on("turn_end", async (event: any) => {
    rememberAssistant(event?.message);
    appendEvent("turn_end", {
      turn_index: event?.turnIndex ?? null,
      assistant: latestAssistant,
      tool_result_count: Array.isArray(event?.toolResults)
        ? event.toolResults.length
        : 0,
    });
  });

  pi.on("tool_execution_start", async (event: any) => {
    appendEvent("tool_start", {
      tool_call_id: String(event?.toolCallId || ""),
      tool_name: String(event?.toolName || ""),
    });
  });

  pi.on("tool_execution_end", async (event: any) => {
    appendEvent("tool_end", {
      tool_call_id: String(event?.toolCallId || ""),
      tool_name: String(event?.toolName || ""),
      is_error: Boolean(event?.isError),
    });
  });

  pi.on("agent_end", async (event: any) => {
    if (Array.isArray(event?.messages)) {
      for (let index = event.messages.length - 1; index >= 0; index -= 1) {
        const candidate = normalizeAssistant(event.messages[index]);
        if (candidate) {
          latestAssistant = candidate;
          break;
        }
      }
    }
    appendEvent("agent_end", { assistant: latestAssistant });
  });

  pi.on("agent_settled", async () => {
    appendEvent("agent_settled", { assistant: latestAssistant });
    activeReqId = "";
    latestAssistant = null;
  });
}
'''


__all__ = ["build_runtime_launcher"]
