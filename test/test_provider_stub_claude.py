from __future__ import annotations

import json
import runpy
from pathlib import Path

from provider_backends.claude.comm_runtime.parsing import structured_event
from provider_backends.claude.execution_runtime.state_machine_runtime.system_events import (
    has_outer_request_anchor,
)


STUB_PATH = Path(__file__).resolve().parent / "stubs" / "provider_stub.py"


def test_claude_stub_emits_activatable_native_session_records(tmp_path: Path) -> None:
    handler = runpy.run_path(str(STUB_PATH))["_handle_claude"]
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
