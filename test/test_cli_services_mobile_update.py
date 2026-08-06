from __future__ import annotations

import base64
import json
import stat
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


def test_suggest_lan_listen_uses_specific_private_route_address() -> None:
    class _Socket:
        def connect(self, _target) -> None:
            return None

        def getsockname(self):
            return ("192.168.31.155", 44000)

        def close(self) -> None:
            return None

    assert mobile_update.suggest_lan_listen_address(
        socket_factory=lambda *_args: _Socket(),
        getaddrinfo_fn=lambda *_args, **_kwargs: (),
        run_fn=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            (), 1, stdout="", stderr=""
        ),
    ) == "192.168.31.155:8787"


def test_suggest_lan_listen_rejects_loopback_and_uses_hostname_candidate() -> None:
    class _Socket:
        def connect(self, _target) -> None:
            return None

        def getsockname(self):
            return ("127.0.0.1", 44000)

        def close(self) -> None:
            return None

    records = ((None, None, None, None, ("10.10.0.8", 0)),)
    assert mobile_update.suggest_lan_listen_address(
        socket_factory=lambda *_args: _Socket(),
        hostname_fn=lambda: "desktop",
        getaddrinfo_fn=lambda *_args, **_kwargs: records,
        run_fn=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            (), 1, stdout="", stderr=""
        ),
    ) == "10.10.0.8:8787"


def test_suggest_lan_listen_prefers_physical_interface_over_vpn_route() -> None:
    class _Socket:
        def connect(self, _target) -> None:
            return None

        def getsockname(self):
            return ("198.18.0.1", 44000)

        def close(self) -> None:
            return None

    ip_output = "\n".join(
        (
            "2: enp4s0    inet 192.168.1.4/24 brd 192.168.1.255 scope global",
            "5: tailscale0    inet 100.107.184.75/32 scope global",
            "6: tun0    inet 10.8.0.1/24 scope global",
            "9: Mihomo    inet 198.18.0.1/30 scope global",
        )
    )
    assert mobile_update.suggest_lan_listen_address(
        socket_factory=lambda *_args: _Socket(),
        getaddrinfo_fn=lambda *_args, **_kwargs: (),
        run_fn=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            (), 0, stdout=ip_output, stderr=""
        ),
        system_fn=lambda: "Linux",
    ) == "192.168.1.4:8787"


def test_suggest_lan_listen_rejects_known_virtual_interface_fallbacks() -> None:
    class _Socket:
        def connect(self, _target) -> None:
            return None

        def getsockname(self):
            return ("10.8.0.1", 44000)

        def close(self) -> None:
            return None

    assert (
        mobile_update.suggest_lan_listen_address(
            socket_factory=lambda *_args: _Socket(),
            hostname_fn=lambda: "desktop",
            getaddrinfo_fn=lambda *_args, **_kwargs: (
                (None, None, None, None, ("10.8.0.1", 0)),
            ),
            run_fn=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                (),
                0,
                stdout="6: tun0    inet 10.8.0.1/24 scope global",
                stderr="",
            ),
            system_fn=lambda: "Linux",
        )
        is None
    )


def test_lan_onboarding_prints_qr_and_same_network_guidance(monkeypatch) -> None:
    output: list[str] = []
    qr_payloads: list[str] = []
    monkeypatch.setattr(
        mobile_update,
        "render_terminal_qr",
        lambda payload, **_kwargs: qr_payloads.append(payload) or ("QR",),
    )
    code = mobile_update.run_mobile_lan_onboarding(
        listen="192.168.31.155:8787",
        start_service_fn=lambda: {
            "route_provider": "lan",
            "listen": "192.168.31.155:8787",
            "gateway_url": "http://192.168.31.155:8787",
            "pairing": {
                "pairing_code": "pair-code",
                "claim_endpoint": "http://192.168.31.155:8787/v1/pairing/claim",
                "gateway_url": "http://192.168.31.155:8787",
                "route_provider": "lan",
                "scopes": ["view"],
            },
        },
        print_fn=output.append,
        qr_ansi=False,
    )

    text = "\n".join(output)
    assert code == 0
    assert json.loads(qr_payloads[0])["route_provider"] == "lan"
    assert "same trusted Wi-Fi" in text
    assert "guest/client-isolated Wi-Fi" in text
    assert "VPN blocks local traffic" in text
    assert "LAN IP changes" in text
    assert "run ccb update mobile again" in text
    assert "Do not expose this listener to the public Internet" in text
    assert "paste this connection code" in text
    connection_code = next(
        line
        for line in output
        if line.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    )
    assert connection_code.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    decoded = _decode_connection_code(connection_code)
    assert json.loads(decoded)["gateway_url"] == "http://192.168.31.155:8787"


@pytest.mark.parametrize(
    "listen",
    ("127.0.0.1:8787", "0.0.0.0:8787", "8.8.8.8:8787", "bad"),
)
def test_lan_onboarding_rejects_unreachable_or_unsafe_listen(listen: str) -> None:
    calls = 0

    def _start():
        nonlocal calls
        calls += 1
        return {}

    output: list[str] = []
    code = mobile_update.run_mobile_lan_onboarding(
        listen=listen,
        start_service_fn=_start,
        print_fn=output.append,
    )

    assert code == 1
    assert calls == 0


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
    assert "scan the QR or paste the connection code" in text


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
    assert "scan the QR or paste the connection code" in text
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
    assert "pairing_code: stable-code" not in text
    assert "pairing_expires_at: 2026-07-02T00:10:00Z" in text
    assert "pairing_claim_endpoint:" not in text
    assert "Scan this QR in CCB Mobile" in text
    assert "QR-LINE-1" in text
    assert "QR-LINE-2" in text
    assert "paste this connection code in CCB Mobile" in text
    connection_code = next(
        line
        for line in output
        if line.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    )
    assert connection_code.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    assert len(qr_payloads) == 1
    payload = json.loads(qr_payloads[0][0])
    assert json.loads(_decode_connection_code(connection_code)) == payload
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


def test_mobile_connection_code_is_unpadded_base64url_round_trip() -> None:
    payload = '{"claim_endpoint":"https://example.test/v1/pairing/claim","pairing_code":"synthetic"}'

    connection_code = mobile_update.build_mobile_connection_code(payload)

    assert connection_code.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    assert "=" not in connection_code
    assert _decode_connection_code(connection_code) == payload


def _decode_connection_code(value: str) -> str:
    encoded = value.removeprefix(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    encoded += "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded).decode("utf-8")


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


def test_high_density_pairing_qr_uses_owner_only_png_in_narrow_terminal(
    tmp_path,
) -> None:
    output: list[str] = []
    qr_path = tmp_path / "pairing-qr.png"

    result = mobile_update._print_pairing_qr(
        "x" * 1390,
        print_fn=output.append,
        qr_ansi=False,
        environ={},
        terminal_columns=80,
        qr_image_path=qr_path,
    )

    assert result == qr_path
    assert qr_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert stat.S_IMODE(qr_path.stat().st_mode) == 0o600
    assert any("129 columns required; 80 available" in line for line in output)
    assert any(str(qr_path) in line for line in output)
    assert not any(
        line and set(line) <= set(" █▀▄") and any(char in line for char in "█▀▄")
        for line in output
    )

    wide_output: list[str] = []
    wide_path = tmp_path / "wide-pairing-qr.png"
    mobile_update._print_pairing_qr(
        "x" * 1390,
        print_fn=wide_output.append,
        qr_ansi=False,
        environ={},
        terminal_columns=160,
        qr_image_path=wide_path,
    )

    assert wide_path.exists()
    assert any("safe inline limit" in line for line in wide_output)


def test_relay_pairing_qr_compacts_to_fit_97_column_terminal(tmp_path) -> None:
    payload = json.dumps(
        {
            "pairing_code": "p" * 24,
            "claim_endpoint": "https://47.120.71.142/v1/pairing/claim",
            "route_provider": "relay",
            "gateway_url": "https://47.120.71.142",
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
            "host_id": "h" * 28,
            "relay_mode": "official",
            "websocket_url": "wss://47.120.71.142",
            "server_fingerprint": "f" * 50,
            "relay_session_id": "s" * 29,
            "relay_client_private_key_b64": "k" * 43,
            "relay_phone_nonce_b64": "n" * 32,
            "relay_rendezvous_capability":
                f"{'a' * 15}.{'b' * 467}.{'c' * 86}",
            "relay_bootstrap_expires_at": "2026-07-27T12:00:00Z",
            "relay_bootstrap_single_use": True,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    compact_payload = mobile_update.build_compact_relay_qr_payload(payload)

    assert compact_payload is not None
    assert compact_payload.startswith(mobile_update.MOBILE_COMPACT_RELAY_QR_PREFIX)
    compact_lines = render_terminal_qr(
        compact_payload,
        ansi=False,
        quiet_zone=2,
        compact=True,
    )
    assert max(map(len, compact_lines)) == 93

    output: list[str] = []
    qr_path = tmp_path / "relay-pairing-qr.png"
    result = mobile_update._print_pairing_qr(
        payload,
        print_fn=output.append,
        qr_ansi=False,
        environ={},
        terminal_columns=97,
        qr_image_path=qr_path,
    )

    assert result == qr_path
    assert qr_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert any("Compact Relay QR shown in 93 columns" in line for line in output)
    assert any(
        len(line) == 93
        and set(line) <= set(" █▀▄")
        and any(char in line for char in "█▀▄")
        for line in output
    )
    assert not any("Terminal QR omitted" in line for line in output)
    assert any(str(qr_path) in line for line in output)


def test_dumb_terminal_disables_ansi_qr_rendering() -> None:
    assert mobile_update._terminal_supports_ansi({"TERM": "dumb"}) is False
    assert mobile_update._terminal_supports_ansi({"TERM": "xterm-256color"}) is True
    assert (
        mobile_update._terminal_supports_ansi(
            {"TERM": "xterm-256color", "NO_COLOR": "1"}
        )
        is False
    )


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
    text = '\n'.join(output)
    assert 'one-time Relay invitation stays on the computer' in text
    assert 'paste this connection code in CCB Mobile' in text
    connection_code = next(
        line
        for line in output
        if line.startswith(mobile_update.MOBILE_CONNECTION_CODE_PREFIX)
    )
    assert json.loads(_decode_connection_code(connection_code)) == json.loads(
        qr_payloads[0][0]
    )
    assert 'same host fingerprint and single-use bootstrap' in text
