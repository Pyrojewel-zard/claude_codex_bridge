from __future__ import annotations

import json
import os
import sys

from agents.config_loader import StructuredConfigValidationError

from cli.services.start_foreground import attach_started_project_namespace


def _stream_is_tty(stream: object) -> bool:
    checker = getattr(stream, 'isatty', None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def handle_config_validate(context, command, out, services) -> int:
    try:
        if command.action == 'effective':
            payload = services.effective_config_context(context)
        elif command.action == 'migrate':
            payload = services.migrate_config_context(
                context,
                to_version=command.to_version,
                dry_run=command.dry_run,
            )
        else:
            summary = services.validate_config_context(context)
            if not command.json_output:
                services.write_lines(out, services.render_config_validate(summary))
                return 0
            payload = summary.to_record()
    except StructuredConfigValidationError as exc:
        if not command.json_output:
            raise
        print(
            json.dumps(
                {'config_status': 'invalid', 'errors': [exc.to_record()]},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=out,
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=out)
    return 0


def handle_config_ui(context, command, out, services) -> int:
    handle = services.prepare_config_ui(context, command)
    launch_summary = dict(handle.summary)
    # The token-free URL in ConfigUiHandle.summary is safe for diagnostics, but
    # this command's stdout is also the sidebar/manual-open handoff.  That
    # consumer needs the authenticated URL or every copied fallback link is
    # guaranteed to receive HTTP 403.
    launch_summary['url'] = handle.url
    services.write_lines(
        out,
        tuple(f'{key}: {value}' for key, value in launch_summary.items()),
    )
    flush = getattr(out, 'flush', None)
    if callable(flush):
        flush()
    if not command.no_open and not services.open_config_ui_url(handle.url):
        services.write_lines(
            out,
            ('browser_open: failed; open the authenticated loopback URL above manually',),
        )
        if callable(flush):
            flush()
    try:
        handle.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        handle.close()
    return 0


def handle_start(context, command, out, services) -> int:
    interactive_attach = (
        not _env_truthy('CCB_NO_ATTACH')
        and _stream_is_tty(sys.stdin)
        and _stream_is_tty(out)
    )
    terminal_size = _terminal_size_for_streams(out, sys.stdin) if interactive_attach else None
    if terminal_size is not None:
        summary = services.start_agents(context, command, terminal_size=terminal_size)
    else:
        summary = services.start_agents(context, command)
    if interactive_attach:
        attach_started_project_namespace(context)
        return 0
    services.write_lines(out, services.render_start(summary))
    return 0


def _env_truthy(name: str) -> bool:
    value = str(os.environ.get(name) or '').strip().lower()
    return value in {'1', 'true', 'yes', 'on'}


def _terminal_size_for_streams(*streams: object) -> tuple[int, int] | None:
    for stream in streams:
        fileno = getattr(stream, 'fileno', None)
        if not callable(fileno):
            continue
        try:
            fd = int(fileno())
        except Exception:
            continue
        try:
            size = os.get_terminal_size(fd)
        except OSError:
            continue
        columns = int(getattr(size, 'columns', 0) or 0)
        lines = int(getattr(size, 'lines', 0) or 0)
        if columns > 0 and lines > 0:
            return columns, lines
    return None


__all__ = ['handle_config_ui', 'handle_config_validate', 'handle_start']
