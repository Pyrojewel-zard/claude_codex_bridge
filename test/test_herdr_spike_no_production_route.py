from __future__ import annotations

import json
from pathlib import Path

import pytest

import terminal_runtime.api as terminal_api
from terminal_runtime.backend_selection import TerminalBackendSelection
from terminal_runtime.mux_backend_contract import MuxCommandErrorV2


class _FakeBackend:
    pass


def test_herdr_terminal_type_is_not_registered_during_spike(monkeypatch) -> None:
    selection = TerminalBackendSelection(
        detect_terminal_fn=lambda: "herdr",
        tmux_backend_factory=lambda: _FakeBackend(),
    )

    assert selection.get_backend() is None
    assert selection.get_backend("herdr") is None
    monkeypatch.setattr(terminal_api, "_backend_cache", None)
    with pytest.raises(MuxCommandErrorV2) as exc_info:
        terminal_api.get_backend("herdr")
    assert exc_info.value.operation == "select_backend"


def test_production_runtime_limits_herdr_native_contract_to_v2_contract_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    production_roots = [root / "lib" / "terminal_runtime", root / "lib" / "ccbd", root / "lib" / "provider_backends"]
    expected_contract_modules = {
        root / "lib" / "terminal_runtime" / "mux_backend_contract.py",
        root / "lib" / "terminal_runtime" / "backend_resolver.py",
    }

    matches: list[Path] = []
    for production_root in production_roots:
        if not production_root.exists():
            continue
        for path in production_root.rglob("*.py"):
            if "herdr-native" in path.read_text(encoding="utf-8", errors="ignore"):
                matches.append(path.relative_to(root))

    assert {root / path for path in matches} == expected_contract_modules


def test_scope_gate_records_no_production_or_package_diff() -> None:
    root = Path(__file__).resolve().parents[1]
    scope_gate = json.loads(
        (
            root
            / ".codestable"
            / "features"
            / "2026-07-31-mux-backend-contract-herdr-v2"
            / "evidence"
            / "scope-gate.json"
        ).read_text(encoding="utf-8")
    )
    changed_files = scope_gate["evidence"][0]["changed_files"]
    allowed_prefixes = tuple(scope_gate["evidence"][0]["allowed_prefixes"])

    assert "package.json" not in changed_files
    assert all(
        any(path == prefix or path.startswith(prefix + "/") for prefix in allowed_prefixes)
        for path in changed_files
    )
