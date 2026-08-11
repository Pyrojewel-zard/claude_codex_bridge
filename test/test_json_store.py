from __future__ import annotations

import json

import pytest

from storage.json_store import JsonStore


def test_json_store_load_reports_invalid_json_path(tmp_path) -> None:
    path = tmp_path / "lifecycle.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError) as excinfo:
        JsonStore().load(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "invalid JSON" in message
