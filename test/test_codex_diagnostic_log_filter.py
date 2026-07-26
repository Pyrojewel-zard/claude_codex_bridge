from __future__ import annotations

import sqlite3
from pathlib import Path

from provider_backends.codex.launcher_runtime.command_runtime.diagnostics import (
    DB_NAME,
    TRIGGER_NAME,
    ensure_codex_diagnostic_log_filter,
    install_codex_diagnostic_log_filter,
)


def _create_logs_db(codex_home: Path) -> Path:
    codex_home.mkdir(parents=True, exist_ok=True)
    db_path = codex_home / DB_NAME
    with sqlite3.connect(str(db_path)) as conn:
        _create_logs_table(conn)
    return db_path


def _create_logs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
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


def _create_codex_migrated_logs_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            '''
            CREATE TABLE _sqlx_migrations (
                version BIGINT PRIMARY KEY,
                description TEXT NOT NULL,
                installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN NOT NULL,
                checksum BLOB NOT NULL,
                execution_time BIGINT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO _sqlx_migrations(version, description, success, checksum, execution_time)
            VALUES (1, 'create_logs', 1, X'', 0)
            '''
        )
        _create_logs_table(conn)


def test_install_codex_diagnostic_log_filter_keeps_only_terminal_turn_errors(tmp_path: Path) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)

    assert install_codex_diagnostic_log_filter(codex_home) is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('TRACE', 'trace-row')")
        conn.execute("INSERT INTO logs(level, target) VALUES ('debug', 'debug-row')")
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        conn.execute("INSERT INTO logs(level, target) VALUES ('ERROR', 'error-row')")
        conn.execute(
            '''
            INSERT INTO logs(level, target, feedback_log_body, thread_id)
            VALUES (
                'ERROR',
                'codex_core::session::turn',
                'session_task.run:run_turn: Turn error: stream disconnected before completion',
                'thread-1'
            )
            '''
        )
        rows = conn.execute(
            'SELECT level, target, feedback_log_body, thread_id FROM logs ORDER BY id'
        ).fetchall()
        trigger = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
            (TRIGGER_NAME,),
        ).fetchone()

    assert trigger == (TRIGGER_NAME,)
    assert rows == [
        (
            'ERROR',
            'codex_core::session::turn',
            'session_task.run:run_turn: Turn error: stream disconnected before completion',
            'thread-1',
        )
    ]


def test_install_codex_diagnostic_log_filter_is_schema_noop_when_current(tmp_path: Path) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)

    assert install_codex_diagnostic_log_filter(codex_home) is True
    with sqlite3.connect(str(db_path)) as conn:
        schema_version = conn.execute('PRAGMA schema_version').fetchone()[0]

    assert install_codex_diagnostic_log_filter(codex_home) is True

    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute('PRAGMA schema_version').fetchone()[0] == schema_version


def test_ensure_codex_diagnostic_log_filter_removes_trigger_when_diagnostics_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)
    assert install_codex_diagnostic_log_filter(codex_home) is True
    monkeypatch.setenv('CCB_CODEX_DIAGNOSTIC_LOGS', '1')

    assert ensure_codex_diagnostic_log_filter(codex_home) is True

    with sqlite3.connect(str(db_path)) as conn:
        trigger = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
            (TRIGGER_NAME,),
        ).fetchone()
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert trigger is None
    assert rows == [('INFO', 'info-row')]


def test_ensure_codex_diagnostic_log_filter_redirects_logs_db_to_temp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)
    (codex_home / f'{DB_NAME}-wal').write_text('wal', encoding='utf-8')
    (codex_home / f'{DB_NAME}-shm').write_text('shm', encoding='utf-8')
    logs_tmp = tmp_path / 'tmp-logs'
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)
    monkeypatch.setenv('CCB_CODEX_LOGS_TMPDIR', str(logs_tmp))

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is False

    target = db_path.resolve(strict=False)
    assert not target.exists()
    assert db_path.is_symlink()
    assert target.is_relative_to(logs_tmp)
    assert (codex_home / f'{DB_NAME}.bak').is_file()
    assert (codex_home / f'{DB_NAME}-wal.bak').is_file()
    assert (codex_home / f'{DB_NAME}-shm.bak').is_file()

    _create_codex_migrated_logs_db(db_path)
    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()
        trigger = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
            (TRIGGER_NAME,),
        ).fetchone()

    assert trigger == (TRIGGER_NAME,)
    assert rows == []


def test_ensure_codex_diagnostic_log_filter_redirects_before_lazy_db_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = codex_home / DB_NAME
    logs_tmp = tmp_path / 'tmp-logs'
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)
    monkeypatch.setenv('CCB_CODEX_LOGS_TMPDIR', str(logs_tmp))

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is False

    target = db_path.resolve(strict=False)
    assert db_path.is_symlink()
    assert target.parent.is_relative_to(logs_tmp)

    _create_codex_migrated_logs_db(db_path)

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert rows == []


def test_ensure_codex_diagnostic_log_filter_repairs_missing_symlink_target_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = codex_home / DB_NAME
    logs_tmp = tmp_path / 'tmp-logs'
    target = logs_tmp / 'cleared-target' / DB_NAME
    codex_home.mkdir(parents=True)
    db_path.symlink_to(target)
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)
    monkeypatch.setenv('CCB_CODEX_LOGS_TMPDIR', str(logs_tmp))

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is False

    assert db_path.is_symlink()
    assert target.parent.is_dir()

    _create_codex_migrated_logs_db(db_path)
    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert rows == []


def test_ensure_codex_diagnostic_log_filter_repairs_preinitialized_symlink_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = codex_home / DB_NAME
    logs_tmp = tmp_path / 'tmp-logs'
    target = logs_tmp / 'broken-target' / DB_NAME
    codex_home.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    db_path.symlink_to(target)
    with sqlite3.connect(str(target)) as conn:
        _create_logs_table(conn)
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)
    monkeypatch.setenv('CCB_CODEX_LOGS_TMPDIR', str(logs_tmp))

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is False

    assert db_path.is_symlink()
    assert not target.exists()
    assert (target.parent / f'{DB_NAME}.bak').is_file()

    _create_codex_migrated_logs_db(db_path)
    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert rows == []


def test_ensure_codex_diagnostic_log_filter_restores_db_when_symlink_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)

    def fail_symlink(*_args, **_kwargs) -> None:
        raise OSError()

    monkeypatch.setattr(Path, 'symlink_to', fail_symlink)

    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert not db_path.is_symlink()
    assert db_path.is_file()
    assert rows == []


def test_ensure_codex_diagnostic_log_filter_restores_backup_when_diagnostics_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    codex_home = tmp_path / 'codex-home'
    db_path = _create_logs_db(codex_home)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'original-row')")
    monkeypatch.delenv('CCB_CODEX_DIAGNOSTIC_LOGS', raising=False)
    monkeypatch.setenv('CCB_CODEX_LOGS_TMPDIR', str(tmp_path / 'tmp-logs'))
    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is False
    assert db_path.is_symlink()

    monkeypatch.setenv('CCB_CODEX_DIAGNOSTIC_LOGS', '1')
    assert ensure_codex_diagnostic_log_filter(codex_home, runtime_dir=tmp_path / 'runtime') is True

    with sqlite3.connect(str(db_path)) as conn:
        trigger = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
            (TRIGGER_NAME,),
        ).fetchone()
        conn.execute("INSERT INTO logs(level, target) VALUES ('INFO', 'info-row')")
        rows = conn.execute('SELECT level, target FROM logs ORDER BY id').fetchall()

    assert not db_path.is_symlink()
    assert trigger is None
    assert rows == [('INFO', 'original-row'), ('INFO', 'info-row')]


def test_install_codex_diagnostic_log_filter_skips_missing_db(tmp_path: Path) -> None:
    assert install_codex_diagnostic_log_filter(tmp_path / 'missing-home') is False
