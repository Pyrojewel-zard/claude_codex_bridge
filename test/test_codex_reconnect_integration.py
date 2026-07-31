from __future__ import annotations

from pathlib import Path
import sqlite3
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_ROOT = REPO_ROOT / 'tools' / 'codex-reconnect'
sys.path.insert(0, str(TOOL_ROOT))

from codex_reconnect.tmux_watch import read_codex_terminal_logs
from provider_backends.codex.launcher_runtime.command_runtime.diagnostics import (
    install_codex_diagnostic_log_filter,
)


def test_ccb_filtered_symlink_log_preserves_exact_reconnect_terminal_error(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / 'managed-home'
    shared_db = tmp_path / 'ccb-codex-logs' / 'logs_2.sqlite'
    codex_home.mkdir(parents=True)
    shared_db.parent.mkdir(parents=True)
    (codex_home / 'logs_2.sqlite').symlink_to(shared_db)
    with sqlite3.connect(shared_db) as connection:
        connection.execute(
            '''
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                target TEXT,
                feedback_log_body TEXT,
                thread_id TEXT
            )
            '''
        )

    assert install_codex_diagnostic_log_filter(codex_home) is True

    thread_id = '019f729b-d4d0-7610-98cd-62562042a0c0'
    message = (
        'stream disconnected before completion: error sending request for url '
        '(https://chatgpt.com/backend-api/codex/responses)'
    )
    body = (
        f'session_loop{{thread_id={thread_id}}}:'
        'turn{otel.name=session_task.turn turn.id=failed-turn}:'
        f'session_task.run:run_turn: Turn error: {message}'
    )
    with sqlite3.connect(shared_db) as connection:
        connection.execute(
            '''
            INSERT INTO logs(level, target, feedback_log_body, thread_id)
            VALUES ('TRACE', 'codex_api::endpoint::responses_websocket', 'retrying', ?)
            ''',
            (thread_id,),
        )
        cursor = connection.execute(
            '''
            INSERT INTO logs(level, target, feedback_log_body, thread_id)
            VALUES ('ERROR', 'codex_core::session::turn', ?, ?)
            ''',
            (body, thread_id),
        )
        terminal_row_id = cursor.lastrowid

    cursor, records = read_codex_terminal_logs(
        codex_home / 'logs_2.sqlite',
        thread_id,
        0,
    )

    assert cursor == terminal_row_id
    assert [(record.turn_id, record.message) for record in records] == [
        ('failed-turn', message)
    ]
