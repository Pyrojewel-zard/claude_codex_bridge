from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from cli.services import mobile_update
from cli.services.terminal_qr import render_terminal_qr


class _FakeGatewayHandle:
    def __init__(self) -> None:
        self.closed = False
        self.served = False
        self.summary = {
            "mobile_status": "serving",
            "listen": "127.0.0.1:8787",
            "gateway_url": "https://desktop.tailnet.ts.net:8787",
            "route_provider": "tailnet",
            "mode": "loopback_server_registry",
            "project_count": 2,
            "projects": [
                {"id": "proj-one", "display_name": "test_ccb2", "health": "healthy"},
                {"id": "proj-two", "display_name": "ccb_mobile", "health": "healthy"},
            ],
            "pairing": {
                "pairing_code": "pair-code",
                "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
                "route_provider": "tailnet",
                "gateway_url": "https://desktop.tailnet.ts.net:8787",
                "scopes": ["project:view", "agent:message"],
            },
        }

    def serve_forever(self) -> None:
        self.served = True

    def close(self) -> None:
        self.closed = True


def _force_linux_tailscale_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mobile_update,
        "_tailscale_install_command",
        lambda: mobile_update.TAILSCALE_LINUX_INSTALL_COMMAND,
    )


def test_detect_tailscale_reports_not_installed() -> None:
    status = mobile_update.detect_tailscale(which_fn=lambda _name: None)

    assert status.installed is False
    assert status.logged_in is False


def test_detect_tailscale_reports_installed_not_logged_in() -> None:
    def _run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Logged out")

    status = mobile_update.detect_tailscale(
        which_fn=lambda _name: "/usr/bin/tailscale",
        run_fn=_run,
    )

    assert status.installed is True
    assert status.path == "/usr/bin/tailscale"
    assert status.logged_in is False
    assert status.detail == "Logged out"


def test_detect_tailscale_reports_logged_in_tailnet_identity() -> None:
    payload = {
        "BackendState": "Running",
        "Self": {"DNSName": "desktop.tailnet.ts.net.", "HostName": "desktop"},
        "CurrentTailnet": {"Name": "example.ts.net"},
    }

    def _run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    status = mobile_update.detect_tailscale(
        which_fn=lambda _name: "/usr/bin/tailscale",
        run_fn=_run,
    )

    assert status.installed is True
    assert status.logged_in is True
    assert status.hostname == "desktop.tailnet.ts.net"
    assert status.tailnet == "example.ts.net"


def test_build_tailnet_commands_keep_gateway_loopback_and_no_funnel() -> None:
    commands = mobile_update.build_tailnet_onboarding_commands(
        status=mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=True,
            hostname="desktop.tailnet.ts.net",
        ),
    )

    assert commands.mobile_serve == (
        "ccb",
        "mobile",
        "serve",
        "--listen",
        "127.0.0.1:8787",
        "--public-url",
        "https://desktop.tailnet.ts.net:8787",
        "--route-provider",
        "tailnet",
    )
    assert commands.tailscale_serve == (
        "tailscale",
        "serve",
        "--bg",
        "--https=8787",
        "http://127.0.0.1:8787",
    )
    public_port = commands.mobile_serve[
        commands.mobile_serve.index("--public-url") + 1
    ].rsplit(":", 1)[1]
    serve_https_port = commands.tailscale_serve[
        commands.tailscale_serve.index("--https=8787")
    ].split("=", 1)[1]
    assert serve_https_port == public_port
    for command in (
        commands.mobile_serve,
        commands.tailscale_serve,
        commands.health_smoke,
        commands.route_diagnostics_smoke,
        commands.terminal_websocket_smoke,
    ):
        joined = " ".join(command)
        assert "0.0.0.0" not in joined
        assert "funnel" not in joined.lower()


def test_build_tailnet_commands_reject_public_listen() -> None:
    with pytest.raises(ValueError, match="loopback-only"):
        mobile_update.build_tailnet_onboarding_commands(
            status=mobile_update.TailscaleStatus(installed=True, logged_in=True),
            listen="0.0.0.0:8787",
        )


def test_onboarding_not_installed_prints_install_and_phone_steps() -> None:
    output: list[str] = []
    install_calls = 0

    def _install() -> int:
        nonlocal install_calls
        install_calls += 1
        return 0

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(installed=False),
        install_tailscale_fn=_install,
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 0
    assert install_calls == 0
    assert "Step 1/3: install Tailscale on this computer" in text
    assert mobile_update.TAILSCALE_DOWNLOAD_URL in text
    assert "Skipping automatic install" in text
    assert "Install Tailscale and sign in to the same tailnet" in text
    assert f"Download APK: {mobile_update.DEFAULT_CCB_MOBILE_APP_DOWNLOAD_URL}" in text
    assert "adb install -r build/app/outputs/flutter-apk/app-debug.apk" not in text
    assert mobile_update.CCB_MOBILE_APP_DOWNLOAD_URL_ENV in text
    assert "no Funnel, tokens, ACLs, or grants" in text


def test_onboarding_not_installed_can_install_after_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_linux_tailscale_install(monkeypatch)
    output: list[str] = []
    prompts: list[str] = []
    install_calls = 0

    def _install() -> int:
        nonlocal install_calls
        install_calls += 1
        return 0

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(installed=False),
        install_tailscale_fn=_install,
        prompt_fn=lambda prompt: prompts.append(prompt) or "y",
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 0
    assert prompts == ["Install Tailscale now? [y/N] "]
    assert install_calls == 1
    assert "curl -fsSL https://tailscale.com/install.sh | sh" in text
    assert "official Tailscale install script" in text
    assert "Tailscale install command completed" in text
    assert "Next: run `tailscale up`" in text
    assert "The QR appears after this computer is signed in to Tailscale" in text


def test_onboarding_not_installed_can_install_from_explicit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_linux_tailscale_install(monkeypatch)
    output: list[str] = []
    install_calls = 0

    def _install() -> int:
        nonlocal install_calls
        install_calls += 1
        return 0

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(installed=False),
        install_tailscale_fn=_install,
        environ={"CCB_UPDATE_MOBILE_INSTALL_TAILSCALE": "1"},
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 0
    assert install_calls == 1
    assert "Installing because CCB_UPDATE_MOBILE_INSTALL_TAILSCALE=1 is set" in text
    assert "Tailscale install command completed" in text


def test_onboarding_not_installed_returns_install_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_linux_tailscale_install(monkeypatch)
    output: list[str] = []

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(installed=False),
        install_tailscale_fn=lambda: 17,
        prompt_fn=lambda _prompt: "yes",
        print_fn=output.append,
    )

    assert code == 17
    assert "Tailscale install command failed with exit code 17" in "\n".join(output)


def test_onboarding_logged_out_prints_login_and_can_open_url() -> None:
    output: list[str] = []
    opened: list[str] = []

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=False,
        ),
        environ={"CCB_UPDATE_MOBILE_OPEN_LOGIN": "1"},
        open_url_fn=opened.append,
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 0
    assert opened == [mobile_update.TAILSCALE_LOGIN_URL]
    assert "tailscale up" in text
    assert "Login/register" in text
    assert "Next: run `ccb update mobile` again" in text
    assert "starts the gateway and prints the QR" in text
    assert "After the next `ccb update mobile` prints a QR" in text


def test_onboarding_prints_configured_mobile_app_download_url() -> None:
    output: list[str] = []
    handle = _FakeGatewayHandle()

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=True,
            hostname="desktop.tailnet.ts.net.",
        ),
        prepare_gateway_fn=lambda _command: handle,
        run_fn=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
        environ={
            mobile_update.CCB_MOBILE_APP_DOWNLOAD_URL_ENV: "https://example.test/ccb-mobile.apk"
        },
        print_fn=output.append,
        serve_forever=False,
        qr_ansi=False,
    )

    text = "\n".join(output)
    assert code == 0
    assert "Download APK: https://example.test/ccb-mobile.apk" in text
    assert mobile_update.DEFAULT_CCB_MOBILE_APP_DOWNLOAD_URL not in text
    assert "adb install -r build/app/outputs/flutter-apk/app-debug.apk" not in text
    assert "Open CCB Mobile, tap Scan computer QR" in text


def test_onboarding_logged_in_starts_gateway_serve_and_prints_qr() -> None:
    output: list[str] = []
    prepared: list[SimpleNamespace] = []
    run_commands: list[tuple[str, ...]] = []
    handle = _FakeGatewayHandle()

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=True,
            hostname="desktop.tailnet.ts.net.",
        ),
        prepare_gateway_fn=lambda command: prepared.append(command) or handle,
        run_fn=lambda command, **_kwargs: run_commands.append(tuple(command))
        or subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
        print_fn=output.append,
        serve_forever=False,
        qr_ansi=False,
    )

    text = "\n".join(output)
    assert code == 0
    assert prepared == [
        SimpleNamespace(
            listen="127.0.0.1:8787",
            public_url="https://desktop.tailnet.ts.net:8787",
            route_provider="tailnet",
        )
    ]
    assert ("tailscale", "serve", "status", "--json") in run_commands
    assert (
        "tailscale",
        "serve",
        "--bg",
        "--https=8787",
        "http://127.0.0.1:8787",
    ) in run_commands
    assert "Computer gateway: https://desktop.tailnet.ts.net:8787" in text
    assert "Open CCB Mobile, tap Scan computer QR" in text
    assert "Scan this QR in CCB Mobile" in text
    assert "loopback-only gateway" in text
    assert "no Funnel" in text
    command_lines = [
        line for line in output if line.startswith("   ccb ") or line.startswith("   tailscale ")
    ]
    assert all("0.0.0.0" not in line for line in command_lines)


def test_onboarding_logged_in_starts_managed_mobile_service_when_callback_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output: list[str] = []
    calls: list[tuple[mobile_update.TailnetOnboardingCommands, mobile_update.TailscaleStatus]] = []
    qr_payloads: list[tuple[str, dict[str, object]]] = []

    def _render_qr(payload: str, **kwargs):
        qr_payloads.append((payload, dict(kwargs)))
        return ("QR-LINE-1", "QR-LINE-2")

    monkeypatch.setattr(mobile_update, "render_terminal_qr", _render_qr)

    def _start_service(commands, status):
        calls.append((commands, status))
        return {
            'service_status': 'started',
            'pid': 1234,
            'listen': '127.0.0.1:8787',
            'gateway_url': 'https://desktop.tailnet.ts.net:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'route_provider': 'tailnet',
            'mobile_state_dir': '/tmp/mobile-state',
            'service_log_path': '/tmp/mobile-state/service.log',
            'pairing': {
                'pairing_code': 'stable-code',
                'expires_at': '2026-07-02T00:10:00Z',
                'claim_endpoint': 'https://desktop.tailnet.ts.net:8787/v1/pairing/claim',
            },
        }

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=True,
            hostname="desktop.tailnet.ts.net.",
        ),
        start_service_fn=_start_service,
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 0
    assert len(calls) == 1
    assert calls[0][0].mobile_serve[:4] == ('ccb', 'mobile', 'serve', '--listen')
    assert "Starting or refreshing the loopback-only CCB Mobile gateway" in text
    assert "status: started" in text
    assert "pid: 1234" in text
    assert "service_log: /tmp/mobile-state/service.log" in text
    assert "pairing_code: stable-code" in text
    assert "pairing_expires_at: 2026-07-02T00:10:00Z" in text
    assert "pairing_claim_endpoint: https://desktop.tailnet.ts.net:8787/v1/pairing/claim" in text
    assert "Scan this QR in CCB Mobile" in text
    assert "QR-LINE-1" in text
    assert "QR-LINE-2" in text
    assert "If scanning fails, use Manual Pairing in CCB Mobile" in text
    assert "Gateway URL: https://desktop.tailnet.ts.net:8787" in text
    assert "Pairing Code: stable-code" in text
    assert len(qr_payloads) == 1
    payload = json.loads(qr_payloads[0][0])
    assert payload == {
        "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
        "expires_at": "2026-07-02T00:10:00Z",
        "gateway_url": "https://desktop.tailnet.ts.net:8787",
        "pairing_code": "stable-code",
        "route_provider": "tailnet",
        "scopes": [],
    }
    assert qr_payloads[0][1]["quiet_zone"] == 2
    assert qr_payloads[0][1]["compact"] is True
    assert "Start the loopback-only CCB Mobile gateway in one terminal" not in text


def test_onboarding_managed_service_qr_keeps_full_payload_and_scanner_safe_border() -> None:
    payload = json.dumps(
        {
            "claim_endpoint": "https://desktop.tailnet.ts.net:8787/v1/pairing/claim",
            "gateway_url": "https://desktop.tailnet.ts.net:8787",
            "pairing_code": "stable-code-with-realistic-length",
            "route_provider": "tailnet",
            "scopes": [
                "ask",
                "content",
                "file_download",
                "file_upload",
                "focus",
                "lifecycle",
                "message_submit",
                "notify",
                "terminal_input",
                "view",
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    scanner_safe_qr = render_terminal_qr(payload, quiet_zone=2, compact=True)
    uncompact_qr = render_terminal_qr(payload, quiet_zone=2, compact=False)
    scanner_safe_area = len(scanner_safe_qr) * len(scanner_safe_qr[0])
    uncompact_area = len(uncompact_qr) * len(uncompact_qr[0])

    assert json.loads(payload)["pairing_code"] == "stable-code-with-realistic-length"
    assert scanner_safe_area < uncompact_area
    assert scanner_safe_qr[0].strip("█") == ""
    assert scanner_safe_qr[-1].strip("█") == ""


def test_onboarding_reports_non_mapping_mobile_service_result() -> None:
    output: list[str] = []

    code = mobile_update.run_mobile_update_onboarding(
        detect_tailscale_fn=lambda: mobile_update.TailscaleStatus(
            installed=True,
            path="/usr/bin/tailscale",
            logged_in=True,
            hostname="desktop.tailnet.ts.net.",
        ),
        start_service_fn=lambda _commands, _status: None,  # type: ignore[return-value]
        print_fn=output.append,
    )

    text = "\n".join(output)
    assert code == 1
    assert "CCB Mobile gateway update failed: TypeError: mobile service starter must return a mapping" in text


def test_relay_onboarding_prints_full_mode_bound_pairing_qr(monkeypatch) -> None:
    output: list[str] = []
    qr_payloads: list[tuple[str, dict[str, object]]] = []

    def _render_qr(payload: str, **kwargs: object) -> tuple[str, ...]:
        qr_payloads.append((payload, dict(kwargs)))
        return ('QR',)

    monkeypatch.setattr(mobile_update, 'render_terminal_qr', _render_qr)
    code = mobile_update.run_mobile_relay_onboarding(
        start_service_fn=lambda: {
            'route_provider': 'relay',
            'pairing': {
                'pairing_code': 'pair-code',
                'claim_endpoint': 'https://47.120.71.142/v1/pairing/claim',
                'gateway_url': 'https://47.120.71.142',
                'websocket_url': 'wss://47.120.71.142',
                'relay_mode': 'official',
                'scopes': ['view'],
            },
        },
        print_fn=output.append,
        qr_ansi=False,
    )

    assert code == 0
    assert json.loads(qr_payloads[0][0])['relay_mode'] == 'official'
    assert qr_payloads[0][1] == {'ansi': False, 'quiet_zone': 2, 'compact': True}
    assert 'one-time Relay invitation stays on the computer' in '\n'.join(output)
