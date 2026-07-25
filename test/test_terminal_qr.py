from __future__ import annotations

import json

from cli.services.terminal_qr import make_terminal_qr, render_terminal_qr


def test_terminal_qr_renders_scannable_shape_for_pairing_payload() -> None:
    payload = json.dumps(
        {
            "pairing_code": "pair-code",
            "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
            "route_provider": "tailnet",
            "gateway_url": "https://desktop.tailnet.ts.net:8787",
            "scopes": ["project:view", "agent:message"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    qr = make_terminal_qr(payload)
    lines = render_terminal_qr(payload, ansi=False)

    assert 1 <= qr.version <= 14
    assert qr.size == qr.version * 4 + 17
    assert len(lines) == qr.size + 8
    assert all(len(line) == (qr.size + 8) * 2 for line in lines)
    assert any("  " in line and "██" in line for line in lines)


def test_terminal_qr_can_render_compact_pairing_payload() -> None:
    payload = json.dumps(
        {
            "pairing_code": "pair-code",
            "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
            "route_provider": "tailnet",
            "gateway_url": "https://desktop.tailnet.ts.net:8787",
            "scopes": ["project:view", "agent:message"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    qr = make_terminal_qr(payload)
    lines = render_terminal_qr(payload, ansi=False, quiet_zone=2, compact=True)

    assert len(lines) == (qr.size + 4 + 1) // 2
    assert all(len(line) == qr.size + 4 for line in lines)
    assert max(len(line) for line in lines) <= 80
    assert any("▀" in line or "▄" in line for line in lines)


def test_terminal_qr_keeps_alignment_patterns_on_timing_axes() -> None:
    payload = json.dumps(
        {
            "pairing_code": "pair-code",
            "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
            "route_provider": "tailnet",
            "gateway_url": "https://desktop.tailnet.ts.net:8787",
            "scopes": ["project:view", "agent:message"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )

    qr = make_terminal_qr(payload)

    assert qr.version == 9
    for center_row, center_col in (
        (6, 26),
        (26, 6),
        (26, 26),
        (26, 46),
        (46, 26),
        (46, 46),
    ):
        assert (
            "".join(
                "#" if qr.modules[center_row - 2][col] else "."
                for col in range(center_col - 2, center_col + 3)
            )
            == "#####"
        )
        assert (
            "".join(
                "#" if qr.modules[center_row - 1][col] else "."
                for col in range(center_col - 2, center_col + 3)
            )
            == "#...#"
        )
        assert (
            "".join(
                "#" if qr.modules[center_row][col] else "."
                for col in range(center_col - 2, center_col + 3)
            )
            == "#.#.#"
        )
        assert (
            "".join(
                "#" if qr.modules[center_row + 1][col] else "."
                for col in range(center_col - 2, center_col + 3)
            )
            == "#...#"
        )
        assert (
            "".join(
                "#" if qr.modules[center_row + 2][col] else "."
                for col in range(center_col - 2, center_col + 3)
            )
            == "#####"
        )


def test_terminal_qr_can_render_ansi_blocks() -> None:
    lines = render_terminal_qr("hello", ansi=True)

    assert any("\x1b[40m" in line for line in lines)
    assert any("\x1b[47m" in line for line in lines)


def test_terminal_qr_supports_complete_relay_pairing_payload() -> None:
    payload = 'x' * 1390

    qr = make_terminal_qr(payload)
    lines = render_terminal_qr(payload, ansi=False, quiet_zone=2, compact=True)

    assert qr.version == 27
    assert qr.size == 125
    assert len(lines) == 65
    assert all(len(line) == 129 for line in lines)
