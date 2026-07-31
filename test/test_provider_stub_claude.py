from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

from provider_backends.claude.comm_runtime.parsing import structured_event
from provider_backends.claude.execution_runtime.state_machine_runtime.system_events import (
    has_outer_request_anchor,
)


STUB_PATH = Path(__file__).resolve().parent / "stubs" / "provider_stub.py"


def _stub_namespace() -> dict[str, Any]:
    return runpy.run_path(str(STUB_PATH))


def test_claude_stub_emits_activatable_native_session_records(tmp_path: Path) -> None:
    handler = _stub_namespace()["_handle_claude"]
    session_path = tmp_path / "session.jsonl"
    request_id = "job_exact"
    prompt = f"CCB_REQ_ID: {request_id}\n\nRun the requested task."

    handler(request_id, prompt, 0.0, session_path)

    records = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]
    events = [structured_event(record) for record in records]

    assert [record["type"] for record in records] == ["user", "assistant", "system"]
    assert events[0] is not None
    assert events[0]["role"] == "user"
    assert has_outer_request_anchor(events[0]["text"], request_anchor=request_id)
    assert events[1] is not None
    assert events[1]["role"] == "assistant"
    assert events[1]["stop_reason"] == "end_turn"
    assert events[2] is not None
    assert events[2]["role"] == "system"
    assert events[2]["subtype"] == "turn_duration"
    assert records[2]["parentUuid"] == records[1]["uuid"]


def test_claude_stub_starts_sequential_request_after_unconsumed_prompt_tail() -> None:
    namespace = _stub_namespace()
    sync_request = namespace["_sync_prompt_buffer_request"]
    looks_complete = namespace["_looks_like_exact_turn_prompt"]
    stream = (
        "CCB_REQ_ID: job_first\n\n"
        "first request\n\n"
        "CCB reply guidance:\n"
        "- Keep the reply concise.\n\n"
        "Reply in English.\n\n"
        "CCB_REQ_ID: job_second\n\n"
        "second request\n\n"
    )
    current_lines: list[str] = []
    current_req = ""
    completed: list[tuple[str, str]] = []

    for line in stream.splitlines():
        if not line and not current_lines:
            continue
        current_lines, current_req = sync_request(line, current_lines, current_req)
        current_lines.append(line)
        if looks_complete("claude", line, current_lines, current_req):
            completed.append((current_req, "\n".join(current_lines).strip()))
            current_lines = []
            current_req = ""

    assert completed == [
        ("job_first", "CCB_REQ_ID: job_first\n\nfirst request"),
        ("job_second", "CCB_REQ_ID: job_second\n\nsecond request"),
    ]
