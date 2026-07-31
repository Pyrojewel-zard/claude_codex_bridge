from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cli.services import mobile_route_onboarding


def _reader(*answers: str):
    remaining = iter(answers)
    return lambda _prompt: next(remaining)


def test_route_selection_maps_all_four_choices() -> None:
    expected = (
        ("tailnet", None),
        ("lan", None),
        ("relay", "official"),
        ("relay", "self_hosted"),
    )
    for answer, route in zip(("1", "2", "3", "4"), expected, strict=True):
        selection = mobile_route_onboarding.prompt_mobile_route_selection(
            read_fn=_reader(answer),
            print_fn=lambda _line: None,
        )
        assert selection is not None
        assert (selection.route_provider, selection.relay_mode) == route


def test_route_selection_retries_then_stops_without_route() -> None:
    output: list[str] = []

    selection = mobile_route_onboarding.prompt_mobile_route_selection(
        read_fn=_reader("x", "0", "relay"),
        print_fn=output.append,
    )

    assert selection is None
    assert output.count("Enter 1, 2, 3, or 4.") == 3
    assert output[-1] == "Mobile setup stopped after three invalid selections."


def test_route_selection_empty_answer_cancels() -> None:
    output: list[str] = []

    selection = mobile_route_onboarding.prompt_mobile_route_selection(
        read_fn=_reader(""),
        print_fn=output.append,
    )

    assert selection is None
    assert output[-1] == "Mobile setup cancelled; no gateway was changed."


def test_official_relay_reuses_matching_credentials(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "relay-host-credentials.json"
    credential_path.write_text("synthetic", encoding="utf-8")
    prompts: list[str] = []

    result = mobile_route_onboarding.ensure_guided_relay_credentials(
        relay_mode="official",
        read_fn=lambda prompt: prompts.append(prompt) or "",
        print_fn=lambda _line: None,
        environ={"CCB_RELAY_HOST_CREDENTIALS": str(credential_path)},
        load_credentials_fn=lambda _path: SimpleNamespace(
            relay_mode="official",
            host_id="host-official",
        ),
        activate_fn=lambda *_args: (_ for _ in ()).throw(
            AssertionError("matching credentials must not reactivate")
        ),
    )

    assert result.ready is True
    assert result.cancelled is False
    assert prompts == []


def test_official_relay_missing_key_prints_contact_and_does_not_activate(
    tmp_path: Path,
) -> None:
    output: list[str] = []

    result = mobile_route_onboarding.ensure_guided_relay_credentials(
        relay_mode="official",
        read_fn=_reader(""),
        print_fn=output.append,
        environ={
            "CCB_RELAY_HOST_CREDENTIALS": str(tmp_path / "relay-host-credentials.json")
        },
        activate_fn=lambda *_args: (_ for _ in ()).throw(
            AssertionError("empty key path must not activate")
        ),
    )

    text = "\n".join(output)
    assert result.ready is False
    assert result.cancelled is True
    assert mobile_route_onboarding.OFFICIAL_RELAY_CONTACT_EMAIL in text
    assert "WeChat" in text
    assert "No invitation was consumed" in text


def test_official_relay_activates_from_file_path_without_reading_it_here(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "relay-host-credentials.json"
    invitation_path = tmp_path / "ccb-relay.key"
    captured: dict[str, object] = {}

    def _activate(context, command):
        captured["context"] = context
        captured["command"] = command
        return {"host_id": "host-new"}

    result = mobile_route_onboarding.ensure_guided_relay_credentials(
        relay_mode="official",
        read_fn=_reader(str(invitation_path)),
        print_fn=lambda _line: None,
        environ={"CCB_RELAY_HOST_CREDENTIALS": str(credential_path)},
        activate_fn=_activate,
    )

    command = captured["command"]
    assert result.ready is True
    assert command.relay_mode == "official"
    assert command.relay_origin is None
    assert command.invitation is None
    assert command.invitation_file == str(invitation_path)
    assert command.credential_path == str(credential_path)


def test_self_hosted_relay_collects_origin_and_key_path(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _activate(_context, command):
        captured["command"] = command
        return {"host_id": "host-self"}

    result = mobile_route_onboarding.ensure_guided_relay_credentials(
        relay_mode="self-hosted",
        read_fn=_reader(
            "wss://relay.example.com",
            "/tmp/self-hosted-invitation",
        ),
        print_fn=lambda _line: None,
        environ={
            "CCB_RELAY_HOST_CREDENTIALS": str(tmp_path / "relay-host-credentials.json")
        },
        activate_fn=_activate,
    )

    command = captured["command"]
    assert result.ready is True
    assert command.relay_mode == "self_hosted"
    assert command.relay_origin == "wss://relay.example.com"
    assert command.invitation_file == "/tmp/self-hosted-invitation"


def test_relay_mode_mismatch_never_overwrites_existing_credentials(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "relay-host-credentials.json"
    credential_path.write_text("synthetic", encoding="utf-8")
    output: list[str] = []

    result = mobile_route_onboarding.ensure_guided_relay_credentials(
        relay_mode="official",
        read_fn=_reader("/tmp/unused"),
        print_fn=output.append,
        environ={"CCB_RELAY_HOST_CREDENTIALS": str(credential_path)},
        load_credentials_fn=lambda _path: SimpleNamespace(
            relay_mode="self-hosted",
            host_id="host-self",
        ),
        activate_fn=lambda *_args: (_ for _ in ()).throw(
            AssertionError("mode mismatch must not overwrite")
        ),
    )

    assert result.ready is False
    assert result.cancelled is False
    assert "retire the old Relay host" in "\n".join(output)
