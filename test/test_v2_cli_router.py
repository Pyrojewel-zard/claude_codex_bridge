from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import cli.entrypoint_runtime as entrypoint_runtime
import cli.phase2_runtime.handlers_start as handlers_start
from cli.entrypoint import run_cli_entrypoint
from cli.router import (
    dispatch_auxiliary_command,
    dispatch_management_command,
    parse_start_args,
    print_command_help,
)


def test_dispatch_auxiliary_command_routes_droid_only() -> None:
    calls: list[tuple[str, list[str]]] = []

    def droid_handler(argv):
        calls.append(("droid", list(argv)))
        return 11

    assert dispatch_auxiliary_command(
        ["droid", "setup-delegation"],
        droid_handler=droid_handler,
    ) == 11
    assert dispatch_auxiliary_command(
        ["version"],
        droid_handler=droid_handler,
    ) is None
    assert calls == [("droid", ["setup-delegation"])]


def test_dispatch_management_command_parses_and_routes() -> None:
    calls: list[tuple[str, argparse.Namespace]] = []

    def make_handler(name: str):
        def _handler(args: argparse.Namespace) -> int:
            calls.append((name, args))
            return len(calls)
        return _handler

    result = dispatch_management_command(
        ["update", "5.3.0"],
        install_handler=make_handler("install"),
        update_handler=make_handler("update"),
        version_handler=make_handler("version"),
        uninstall_handler=make_handler("uninstall"),
        reinstall_handler=make_handler("reinstall"),
    )

    assert result == 1
    assert len(calls) == 1
    name, args = calls[0]
    assert name == "update"
    assert args.command == "update"
    assert args.target == "5.3.0"
    assert args.providers is None
    assert args.cache_cleanup is True


def test_dispatch_management_command_parses_provider_update_mode() -> None:
    calls: list[argparse.Namespace] = []

    def update_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 7

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        ["update", "--providers", "all"],
        install_handler=fail,
        update_handler=update_handler,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    )

    assert result == 7
    assert calls[0].target is None
    assert calls[0].providers == "all"


def test_dispatch_management_command_can_skip_post_update_cache_cleanup() -> None:
    calls: list[argparse.Namespace] = []

    def update_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 0

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        ["update", "--no-cache-cleanup"],
        install_handler=fail,
        update_handler=update_handler,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    )

    assert result == 0
    assert calls[0].cache_cleanup is False


def test_dispatch_management_command_routes_update_rich() -> None:
    calls: list[argparse.Namespace] = []

    def update_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 23

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        ["update", "rich"],
        install_handler=fail,
        update_handler=update_handler,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    )

    assert result == 23
    assert len(calls) == 1
    assert calls[0].command == "update"
    assert calls[0].target == "rich"


def test_dispatch_management_command_routes_update_mobile() -> None:
    calls: list[argparse.Namespace] = []

    def update_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 25

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        ["update", "mobile"],
        install_handler=fail,
        update_handler=update_handler,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    )

    assert result == 25
    assert len(calls) == 1
    assert calls[0].command == "update"
    assert calls[0].target == "mobile"


def test_dispatch_management_command_routes_uninstall_rich() -> None:
    calls: list[argparse.Namespace] = []

    def uninstall_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 24

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        ["uninstall", "rich"],
        install_handler=fail,
        update_handler=fail,
        version_handler=fail,
        uninstall_handler=uninstall_handler,
        reinstall_handler=fail,
    )

    assert result == 24
    assert len(calls) == 1
    assert calls[0].command == "uninstall"
    assert calls[0].target == "rich"


def test_dispatch_management_command_routes_install_mobile() -> None:
    calls: list[argparse.Namespace] = []

    def install_handler(args: argparse.Namespace) -> int:
        calls.append(args)
        return 25

    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    result = dispatch_management_command(
        [
            "install",
            "mobile",
            "--listen",
            "127.0.0.1:0",
            "--public-url",
            "https://mobile.example.com",
            "--route-provider",
            "tailnet",
        ],
        install_handler=install_handler,
        update_handler=fail,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    )

    assert result == 25
    assert len(calls) == 1
    assert calls[0].command == "install"
    assert calls[0].target == "mobile"
    assert calls[0].listen == "127.0.0.1:0"
    assert calls[0].public_url == "https://mobile.example.com"
    assert calls[0].route_provider == "tailnet"


def test_dispatch_management_command_returns_none_for_non_management() -> None:
    def fail(_args: argparse.Namespace) -> int:
        raise AssertionError("handler should not be called")

    assert dispatch_management_command(
        ["codex", "claude"],
        install_handler=fail,
        update_handler=fail,
        version_handler=fail,
        uninstall_handler=fail,
        reinstall_handler=fail,
    ) is None


def test_parse_start_args_supports_safe_and_new_context() -> None:
    args = parse_start_args(["-n", "-s"])
    assert args.new_context is True
    assert args.safe is True


def test_reload_help_describes_idle_replace_boundary() -> None:
    stdout = StringIO()

    assert print_command_help("reload", file=stdout) is True

    text = stdout.getvalue()
    assert "idle same-slot replace_agent" in text
    assert "Busy remove_agent and replace_agent record bounded drain state" in text
    assert "replace and full kill/reflow of existing panes are not implemented" not in text


def test_run_cli_entrypoint_prints_start_help_without_phase2() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb [-s] [-n]" in stdout.getvalue()
    assert "Primary workflow:" in stdout.getvalue()
    assert "ccb -s" in stdout.getvalue()
    assert "ccb clear [agent...]" in stdout.getvalue()
    assert "ccb maintenance status Show maintenance heartbeat config and stored status." in stdout.getvalue()
    assert "ccb theme [system|dark|light|+|-|PRESET]" in stdout.getvalue()
    assert "Core commands:" in stdout.getvalue()
    assert "ccb ask <agent> [from <sender>] <message>" in stdout.getvalue()
    assert "ccb doctor" in stdout.getvalue()
    assert "Diagnostics-only control-plane status:" in stdout.getvalue()
    assert "Diagnostics-only observer:" in stdout.getvalue()
    assert "ccb pend <agent|job_id> [N]" in stdout.getvalue()
    assert "ccb pend --queue [--detail] <agent|all>" in stdout.getvalue()
    assert "Advanced views:" in stdout.getvalue()
    assert "ccb queue [--detail] <agent|all>" in stdout.getvalue()
    assert "ccb trace <id>" in stdout.getvalue()
    assert "Advanced recovery:" in stdout.getvalue()
    assert "ccb repair <ack|retry|resubmit> ..." in stdout.getvalue()
    assert "ccb install mobile" in stdout.getvalue()
    assert "ccb rich" in stdout.getvalue()
    assert "ccb update rich" in stdout.getvalue()
    assert "ccb update mobile" in stdout.getvalue()
    assert "ccb rich-install" not in stdout.getvalue()
    assert "ccb watch <agent|job_id>" not in stdout.getvalue()
    assert "ccb inbox [--detail] <agent>" not in stdout.getvalue()
    assert "ccb ps | ccb logs <agent>" not in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_version_before_dispatch(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()

    def fail_if_dispatched(*_args, **_kwargs):
        raise AssertionError("--print-version must return before CLI dispatch")

    monkeypatch.setattr(
        entrypoint_runtime,
        "maybe_handle_sidebar_click_command",
        fail_if_dispatched,
    )

    result = entrypoint_runtime.run_cli_entrypoint(
        ["--print-version"],
        version="8.2.1",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert stdout.getvalue() == "v8.2.1\n"
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_rejects_removed_rich_install() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["rich-install"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 2
    assert stdout.getvalue() == ""
    assert "`ccb rich-install` has been removed" in stderr.getvalue()
    assert "ccb update rich" in stderr.getvalue()


def test_run_cli_entrypoint_routes_install_mobile_before_phase2(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    calls: list[argparse.Namespace] = []

    def _install(args, *, script_root):
        calls.append(args)
        assert script_root == Path("/tmp/ccb")
        return 41

    monkeypatch.setattr(entrypoint_runtime, "cmd_install", _install)
    monkeypatch.setattr(
        entrypoint_runtime,
        "maybe_handle_phase2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("phase2 should not run")),
    )

    result = run_cli_entrypoint(
        ["install", "mobile", "--listen", "127.0.0.1:0"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/not-a-project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 41
    assert len(calls) == 1
    assert calls[0].command == "install"
    assert calls[0].target == "mobile"
    assert calls[0].listen == "127.0.0.1:0"


def test_run_cli_entrypoint_routes_internal_mobile_host_serve_before_phase2(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    calls: list[tuple[list[str], Path]] = []

    def _mobile_host(tokens, *, script_root):
        calls.append((list(tokens), script_root))
        return 37

    monkeypatch.setattr(entrypoint_runtime, "maybe_handle_mobile_host_serve_command", _mobile_host)
    monkeypatch.setattr(
        entrypoint_runtime,
        "maybe_handle_phase2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("phase2 should not run")),
    )

    result = run_cli_entrypoint(
        ["__mobile-host-serve", "--listen", "127.0.0.1:8787"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/not-a-project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 37
    assert calls == [(["__mobile-host-serve", "--listen", "127.0.0.1:8787"], Path("/tmp/ccb"))]


def test_run_cli_entrypoint_routes_rich(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    calls: list[tuple[Path, Path, object, object]] = []

    def _rich(*, script_root, cwd, stdout, stderr):
        calls.append((script_root, cwd, stdout, stderr))
        print("rich launch ok", file=stdout)
        return 19

    monkeypatch.setattr(entrypoint_runtime, "cmd_rich", _rich)

    result = run_cli_entrypoint(
        ["rich"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 19
    assert stdout.getvalue() == "rich launch ok\n"
    assert stderr.getvalue() == ""
    assert calls == [(Path("/tmp/ccb"), Path("/tmp/project"), stdout, stderr)]


def test_run_cli_entrypoint_routes_theme_without_project_discovery(monkeypatch, tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        entrypoint_runtime,
        "maybe_handle_phase2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("theme should not discover a project")),
    )

    result = run_cli_entrypoint(
        ["theme", "light"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/not-a-project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    payload = json.loads((config_home / "ccb" / "theme.json").read_text(encoding="utf-8"))
    assert payload == {
        "palette": "latte",
        "schema_version": 1,
        "theme": "light",
        "tmux_profile": "light",
    }
    assert "theme_status: ok" in stdout.getvalue()
    assert "theme: light" in stdout.getvalue()
    assert "tmux_refresh: skipped" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_theme_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["theme", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb theme" in stdout.getvalue()
    assert "ccb theme +" in stdout.getvalue()
    assert "ccb theme system" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_rich_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["rich", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb rich" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_routes_rich_uninstall(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    calls: list[str] = []

    monkeypatch.setattr(
        entrypoint_runtime,
        "uninstall_workbench",
        lambda **_kwargs: calls.append("uninstall") or {"status": "ok", "uninstalled": True},
    )

    result = run_cli_entrypoint(
        ["rich", "uninstall"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert calls == ["uninstall"]
    assert "workbench_status: ok" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_auto_launches_rich_for_plain_start(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()
    calls: list[tuple[Path, Path, tuple[str, ...]]] = []

    monkeypatch.setattr(entrypoint_runtime, "rich_auto_start_allowed", lambda: True)
    monkeypatch.setattr(
        entrypoint_runtime,
        "launch_rich_ccb",
        lambda *, script_root, cwd, start_args: calls.append((script_root, cwd, tuple(start_args)))
        or {"status": "ok", "launch_status": "started"},
    )

    result = run_cli_entrypoint(
        ["--project", "/tmp/project", "-n"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/elsewhere"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert calls == [(Path("/tmp/ccb"), Path("/tmp/elsewhere"), ("--project", "/tmp/project", "-n"))]
    assert "launch_status: started" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_does_not_auto_launch_rich_when_guard_blocks(monkeypatch) -> None:
    stdout = StringIO()
    stderr = StringIO()

    monkeypatch.setattr(entrypoint_runtime, "rich_auto_start_allowed", lambda: False)
    monkeypatch.setattr(
        entrypoint_runtime,
        "launch_rich_ccb",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("auto rich should not launch")),
    )
    monkeypatch.setattr(entrypoint_runtime, "maybe_handle_startup_release_update", lambda *_, **__: None)
    monkeypatch.setattr(entrypoint_runtime, "maybe_handle_phase2", lambda *_args, **_kwargs: 31)

    result = run_cli_entrypoint(
        [],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 31


def test_handle_start_invokes_foreground_attach_in_interactive_terminal(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeStream:
        def isatty(self) -> bool:
            return True

    class _FakeServices:
        def start_agents(self, context, command, terminal_size=None):
            del context, command, terminal_size
            calls.append("start_agents")
            return {"status": "ok"}

        def write_lines(self, *_args, **_kwargs):
            raise AssertionError("interactive attach should skip text output")

    monkeypatch.setattr(handlers_start.sys, "stdin", _FakeStream())
    monkeypatch.setattr(handlers_start, "_stream_is_tty", lambda stream: True)
    monkeypatch.setattr(
        handlers_start,
        "attach_started_project_namespace",
        lambda context: calls.append(f"attach:{type(context).__name__}") or None,
    )

    result = handlers_start.handle_start(object(), argparse.Namespace(), StringIO(), _FakeServices())

    assert result == 0
    assert calls == ["start_agents", "attach:object"]


def test_run_cli_entrypoint_rejects_rich_install_help_as_removed() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["rich-install", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 2
    assert stdout.getvalue() == ""
    assert "`ccb rich-install` has been removed" in stderr.getvalue()
    assert "ccb update rich" in stderr.getvalue()


def test_run_cli_entrypoint_prints_kill_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["kill", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb kill [-f]" in stdout.getvalue()
    assert "Project runtime cleanup:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_start_help_for_start_flags() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["-s", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb [-s] [-n]" in stdout.getvalue()
    assert "Primary workflow:" in stdout.getvalue()
    assert "Core commands:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_clear_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["clear", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb clear [agent_name|all]..." in stdout.getvalue()
    assert "Send /clear to every configured mounted agent pane." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ping_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ping", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb ping <agent|all|ccbd>" in stdout.getvalue()
    assert "Diagnostics-only control-plane status:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_pend_help_as_supplementary_status() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["pend", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb pend [--watch|--inbox|--queue] [--detail] <agent|job_id|all> [N]" in stdout.getvalue()
    assert "Diagnostics-only weak observer surface:" in stdout.getvalue()
    assert "These commands are not part of normal ask workflows." in stdout.getvalue()
    assert "ccb pend --watch <agent|job_id>" in stdout.getvalue()
    assert "ccb pend --queue <agent|all>" in stdout.getvalue()
    assert "ccb pend --queue --detail <agent>" in stdout.getvalue()
    assert "Use `ccb trace <id>` for lineage when needed." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_watch_help_with_project_prefix() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["--project", "/tmp/demo", "watch", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb watch <agent|job_id>" in stdout.getvalue()
    assert "Diagnostics-only weak observer compatibility entrypoint:" in stdout.getvalue()
    assert "This is not part of normal ask workflows." in stdout.getvalue()
    assert "Prefer `ccb pend --watch <agent|job_id>` as the converged observer entrypoint." in stdout.getvalue()
    assert "Do not treat non-terminal watch output as authoritative completion." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_watch_help_when_help_follows_operand() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["watch", "job_123", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb watch <agent|job_id>" in stdout.getvalue()
    assert "Diagnostics-only weak observer compatibility entrypoint:" in stdout.getvalue()
    assert "This is not part of normal ask workflows." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_watch_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["watch", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb watch <agent|job_id>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ps_help_as_runtime_diagnostics_view() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ps", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb ps" in stdout.getvalue()
    assert "Runtime diagnostics compatibility view:" in stdout.getvalue()
    assert "Prefer `ccb doctor ps` as the converged diagnostics entrypoint." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ps_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ps", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb ps" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_logs_help_as_runtime_diagnostics_view() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["logs", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb logs <agent>" in stdout.getvalue()
    assert "Runtime diagnostics compatibility view:" in stdout.getvalue()
    assert "Prefer `ccb doctor logs <agent>` as the converged diagnostics entrypoint." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_logs_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["logs", "demo", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb logs <agent>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_help_with_converged_subviews() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor [ps|logs <agent>|storage] [--output [PATH]]" in stdout.getvalue()
    assert "ccb doctor ps" in stdout.getvalue()
    assert "ccb doctor logs <agent>" in stdout.getvalue()
    assert "ccb doctor storage" in stdout.getvalue()
    assert "`ccb ps` and `ccb logs <agent>` remain compatibility entrypoints." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor [ps|logs <agent>|storage] [--output [PATH]]" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_storage_subview_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "storage", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor storage [--json]" in stdout.getvalue()
    assert "ccb doctor storage --json" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_cleanup_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["cleanup", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb cleanup" in stdout.getvalue()
    assert "Use `ccb doctor storage` before cleanup" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_ps_subview_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "ps", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor ps" in stdout.getvalue()
    assert "Runtime diagnostics subview:" in stdout.getvalue()
    assert "`ccb ps` remains a compatibility alias." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_ps_subview_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "ps", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor ps" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_runtime_alias_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "--runtime", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor ps" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_logs_subview_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "logs", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor logs <agent>" in stdout.getvalue()
    assert "Runtime log diagnostics subview:" in stdout.getvalue()
    assert "`ccb logs <agent>` remains a compatibility alias." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_logs_subview_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "logs", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor logs <agent>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_logs_alias_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "--logs", "demo", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor logs <agent>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_doctor_logs_subview_help_when_help_follows_agent() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["doctor", "logs", "demo", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb doctor logs <agent>" in stdout.getvalue()
    assert "Runtime log diagnostics subview:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_queue_help_as_advanced_view() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["queue", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb queue [--detail] <agent_name|all>" in stdout.getvalue()
    assert "Advanced backlog view:" in stdout.getvalue()
    assert "`ccb pend --queue [--detail] <agent|all>` remains the equivalent weak-observer form." in stdout.getvalue()
    assert "ccb queue --detail <agent_name>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_queue_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["queue", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb queue [--detail] <agent_name|all>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_maintenance_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["maintenance", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb maintenance <status|tick|schedule>" in stdout.getvalue()
    assert "non-healthy tick may submit one silent ask to the configured assessor" in stdout.getvalue()
    assert "enable and disable are config-authority in v1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_pend_help_with_converged_observer_modes() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["pend", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb pend [--watch|--inbox|--queue] [--detail] <agent|job_id|all> [N]" in stdout.getvalue()
    assert "ccb pend --watch <agent|job_id>" in stdout.getvalue()
    assert "ccb pend --inbox --detail <agent>" in stdout.getvalue()
    assert "ccb pend --queue --detail <agent>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_trace_help_as_advanced_view() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["trace", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb trace <submission_id|message_id|attempt_id|reply_id|job_id>" in stdout.getvalue()
    assert "Advanced lineage view:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_cancel_help_as_job_control_view() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["cancel", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb cancel <job_id>" in stdout.getvalue()
    assert "Job control view:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_inbox_help_as_supplementary_status() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["inbox", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb inbox [--detail] <agent_name>" in stdout.getvalue()
    assert "Weak observer compatibility entrypoint:" in stdout.getvalue()
    assert "Prefer `ccb pend --inbox [--detail] <agent>` as the converged observer entrypoint." in stdout.getvalue()
    assert "ccb inbox --detail <agent_name>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_inbox_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["inbox", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb inbox [--detail] <agent_name>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ack_help_as_advanced_recovery() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ack", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert "Advanced recovery compatibility entrypoint:" in stdout.getvalue()
    assert "Prefer `ccb repair ack <agent_name> [inbound_event_id]` as the converged recovery entrypoint." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ack_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ack", "demo", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_retry_help_as_advanced_recovery() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["retry", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb retry <job_id|attempt_id>" in stdout.getvalue()
    assert "Advanced recovery compatibility entrypoint:" in stdout.getvalue()
    assert "Prefer `ccb repair retry <job_id|attempt_id>` as the converged recovery entrypoint." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_retry_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["retry", "job_1", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb retry <job_id|attempt_id>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_resubmit_help_as_advanced_recovery() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["resubmit", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb resubmit <message_id>" in stdout.getvalue()
    assert "Advanced recovery compatibility entrypoint:" in stdout.getvalue()
    assert "Prefer `ccb repair resubmit <message_id>` as the converged recovery entrypoint." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_resubmit_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["resubmit", "msg_1", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb resubmit <message_id>" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_help_as_primary_advanced_recovery() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair <ack|retry|resubmit> ..." in stdout.getvalue()
    assert "Advanced recovery:" in stdout.getvalue()
    assert "ccb repair ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert "ccb repair retry <job_id|attempt_id>" in stdout.getvalue()
    assert "ccb repair resubmit <message_id>" in stdout.getvalue()
    assert "Legacy `ack` / `retry` / `resubmit` commands remain compatibility entrypoints." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair <ack|retry|resubmit> ..." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_ack_subcommand_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "ack", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert "Advanced recovery subcommand:" in stdout.getvalue()
    assert "`ccb ack <agent_name> [inbound_event_id]` remains a compatibility alias." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_ack_subcommand_help_with_plain_help_token() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "ack", "help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_ack_subcommand_help_when_help_follows_operand() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "ack", "demo", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair ack <agent_name> [inbound_event_id]" in stdout.getvalue()
    assert "Advanced recovery subcommand:" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_retry_subcommand_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "retry", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair retry <job_id|attempt_id>" in stdout.getvalue()
    assert "Advanced recovery subcommand:" in stdout.getvalue()
    assert "`ccb retry <job_id|attempt_id>` remains a compatibility alias." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_repair_resubmit_subcommand_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["repair", "resubmit", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "usage: ccb repair resubmit <message_id>" in stdout.getvalue()
    assert "Advanced recovery subcommand:" in stdout.getvalue()
    assert "`ccb resubmit <message_id>` remains a compatibility alias." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_prints_ask_help() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["ask", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "Usage:" in stdout.getvalue()
    assert (
        "ccb ask [--compact] [--silence] [--chain] [--artifact-request] [--inline-request] [--artifact-reply] <target> [--] <message...>"
        in stdout.getvalue()
    )
    assert "--compact request a distilled reply that preserves key information" in stdout.getvalue()
    assert "--silence request silent-on-success delivery; failures/blockers still surface" in stdout.getvalue()
    assert "--chain mark this ask as part of the current active task chain" in stdout.getvalue()
    assert "--artifact-request force the request body into a CCB text artifact" in stdout.getvalue()
    assert "--inline-request keep the request body inline and disable automatic artifact spill" in stdout.getvalue()
    assert "--artifact-reply force the final reply into a CCB text artifact" in stdout.getvalue()
    assert "--artifact-io enable both --artifact-request and --artifact-reply" in stdout.getvalue()
    assert "ccb ask --compact agent1 review latest diff" in stdout.getvalue()
    assert "ccb ask --silence agent1 run smoke check" in stdout.getvalue()
    assert "ccb ask --chain agent2 collect evidence for this task" in stdout.getvalue()
    assert "ccb ask --chain --artifact-reply agent2 collect long evidence" in stdout.getvalue()
    legacy_chain_flag = "--" + "call" + "back"
    assert legacy_chain_flag not in stdout.getvalue()
    assert "ccb ask get <job_id>    diagnostics-only: inspect one submitted job" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_run_cli_entrypoint_rejects_removed_provider_command() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["provider", "ping", "--help"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 2
    assert stdout.getvalue() == ""
    assert "`ccb provider` has been removed" in stderr.getvalue()
    assert "Use `ccb ask` for task submission/results, `ccb doctor` for diagnostics, and `ccb trace` for lineage details." in stderr.getvalue()


def test_run_cli_entrypoint_rejects_removed_mail_command() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_cli_entrypoint(
        ["mail", "status"],
        version="5.2.8",
        script_root=Path("/tmp/ccb"),
        cwd=Path("/tmp/project"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 2
    assert stdout.getvalue() == ""
    assert "`ccb mail` has been removed" in stderr.getvalue()
    assert "Use `ccb ask` for task submission/results, `ccb doctor` for diagnostics, and `ccb trace` for lineage details." in stderr.getvalue()
