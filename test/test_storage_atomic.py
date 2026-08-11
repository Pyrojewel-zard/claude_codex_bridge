from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from storage import atomic


def _is_directory_fd(fd: int) -> bool:
    return stat.S_ISDIR(os.fstat(fd).st_mode)


def _track_open_directories(monkeypatch) -> dict[int, Path]:
    opened: dict[int, Path] = {}
    real_open_directory = atomic._open_directory

    def tracking_open_directory(path: Path) -> int:
        fd = real_open_directory(path)
        opened[fd] = Path(path)
        return fd

    monkeypatch.setattr(atomic, '_open_directory', tracking_open_directory)
    return opened


def test_atomic_write_text_orders_file_and_directory_sync(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    class TrackingHandle:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, text):
            events.append('write')
            return self.handle.write(text)

        def flush(self):
            events.append('flush')
            return self.handle.flush()

        def fileno(self):
            return self.handle.fileno()

    real_fdopen = os.fdopen

    def tracking_fdopen(*args, **kwargs):
        return TrackingHandle(real_fdopen(*args, **kwargs))

    def tracking_fsync(fd):
        events.append('dir-fsync' if _is_directory_fd(fd) else 'file-fsync')
        return real_fsync(fd)

    def tracking_replace(*args, **kwargs):
        events.append('replace')
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(os, 'fdopen', tracking_fdopen)
    monkeypatch.setattr(os, 'fsync', tracking_fsync)
    monkeypatch.setattr(os, 'replace', tracking_replace)

    atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'new'
    assert events == ['write', 'flush', 'file-fsync', 'replace', 'dir-fsync']


def test_failure_before_replace_preserves_old_target(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    target.write_text('old')
    real_fsync = os.fsync

    def fail_file_fsync(fd):
        if not _is_directory_fd(fd):
            raise OSError('file fsync failed')
        return real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', fail_file_fsync)

    with pytest.raises(OSError, match='file fsync failed'):
        atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'old'
    assert list(tmp_path.glob('.state.txt.*.tmp')) == []


def test_directory_fsync_failure_surfaces_after_complete_replace(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.json'
    target.write_text('{"version": "old"}\n')
    real_fsync = os.fsync

    def fail_directory_fsync(fd):
        if _is_directory_fd(fd):
            raise OSError('directory fsync failed')
        return real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', fail_directory_fsync)

    with pytest.raises(OSError, match='directory fsync failed'):
        atomic.atomic_write_json(target, {'version': 'new'})

    assert json.loads(target.read_text()) == {'version': 'new'}


def test_nested_parent_entries_are_synced(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'one' / 'two' / 'state.txt'
    synced_directories: list[Path] = []
    opened_directories = _track_open_directories(monkeypatch)
    real_fsync = os.fsync

    def tracking_fsync(fd):
        if fd in opened_directories:
            synced_directories.append(opened_directories[fd])
        return real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', tracking_fsync)

    atomic.atomic_write_text(target, 'value')

    assert target.read_text() == 'value'
    assert synced_directories == [tmp_path, tmp_path / 'one', tmp_path / 'one' / 'two']


def test_ensure_durable_directory_orders_parent_syncs(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'one' / 'two'
    events: list[Path] = []
    opened_directories = _track_open_directories(monkeypatch)
    real_fsync = os.fsync

    def tracking_fsync(fd):
        events.append(opened_directories[fd])
        return real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', tracking_fsync)

    atomic.ensure_durable_directory(target)

    assert target.is_dir()
    assert events == [tmp_path, tmp_path / 'one']


def test_ensure_durable_directory_existing_is_noop(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'existing'
    target.mkdir()
    monkeypatch.setattr(os, 'fsync', lambda fd: pytest.fail(f'unexpected fsync: {fd}'))

    atomic.ensure_durable_directory(target)


def test_ensure_durable_directory_rejects_file_and_symlink_parent(tmp_path: Path) -> None:
    file_parent = tmp_path / 'file'
    file_parent.write_text('not a directory')
    with pytest.raises(NotADirectoryError):
        atomic.ensure_durable_directory(file_parent / 'child')

    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='cannot contain symlinks'):
        atomic.ensure_durable_directory(link / 'child')
    assert not (outside / 'child').exists()


def test_ensure_durable_directory_surfaces_parent_fsync_failure(monkeypatch, tmp_path: Path) -> None:
    def fail_fsync(_fd):
        raise OSError('parent fsync failed')

    monkeypatch.setattr(os, 'fsync', fail_fsync)

    with pytest.raises(OSError, match='parent fsync failed'):
        atomic.ensure_durable_directory(tmp_path / 'new')


def test_temp_cleanup_does_not_replace_original_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    target.write_text('old')
    real_unlink = os.unlink

    def fail_replace(*args, **kwargs):
        raise OSError('replace failed')

    def fail_cleanup(path, *args, **kwargs):
        if str(path).endswith('.tmp'):
            raise OSError('cleanup failed')
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, 'replace', fail_replace)
    monkeypatch.setattr(os, 'unlink', fail_cleanup)

    with pytest.raises(OSError, match='replace failed'):
        atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'old'
    assert len(list(tmp_path.glob('.state.txt.*.tmp'))) == 1


def test_directory_close_failure_is_surfaced(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    real_close = os.close

    def fail_directory_close(fd):
        if _is_directory_fd(fd):
            real_close(fd)
            raise OSError('directory close failed')
        return real_close(fd)

    monkeypatch.setattr(os, 'close', fail_directory_close)

    with pytest.raises(OSError, match='directory close failed'):
        atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'new'


def test_directory_close_failure_does_not_replace_original_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    target.write_text('old')
    real_close = os.close

    def fail_replace(*args, **kwargs):
        raise OSError('replace failed')

    def fail_directory_close(fd):
        if _is_directory_fd(fd):
            real_close(fd)
            raise OSError('directory close failed')
        return real_close(fd)

    monkeypatch.setattr(os, 'replace', fail_replace)
    monkeypatch.setattr(os, 'close', fail_directory_close)

    with pytest.raises(OSError, match='replace failed'):
        atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'old'


def test_parent_replacement_is_detected(monkeypatch, tmp_path: Path) -> None:
    parent = tmp_path / 'parent'
    parent.mkdir()
    target = parent / 'state.txt'
    target.write_text('old')
    moved_parent = tmp_path / 'moved-parent'
    real_replace = os.replace

    def replace_after_parent_move(*args, **kwargs):
        parent.rename(moved_parent)
        parent.mkdir()
        (parent / 'state.txt').write_text('canonical-old')
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(os, 'replace', replace_after_parent_move)

    with pytest.raises(RuntimeError, match='parent directory was replaced'):
        atomic.atomic_write_text(target, 'new')

    assert target.read_text() == 'canonical-old'
    assert (moved_parent / 'state.txt').read_text() == 'new'


def test_atomic_write_json_format_is_unchanged(tmp_path: Path) -> None:
    target = tmp_path / 'state.json'

    atomic.atomic_write_json(target, {'z': '雪', 'a': 1})

    assert target.read_text() == '{\n  "z": "雪",\n  "a": 1\n}\n'


def test_atomic_write_text_if_changed_skips_identical_target(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    target.write_text('same', encoding='utf-8')
    monkeypatch.setattr(os, 'fsync', lambda fd: pytest.fail(f'unexpected fsync: {fd}'))
    monkeypatch.setattr(os, 'replace', lambda *args, **kwargs: pytest.fail('unexpected replace'))

    changed = atomic.atomic_write_text_if_changed(target, 'same')

    assert changed is False
    assert target.read_text(encoding='utf-8') == 'same'


def test_atomic_write_json_if_changed_reports_material_change(tmp_path: Path) -> None:
    target = tmp_path / 'state.json'

    assert atomic.atomic_write_json_if_changed(target, {'value': 1}) is True
    assert atomic.atomic_write_json_if_changed(target, {'value': 1}) is False
    assert atomic.atomic_write_json_if_changed(target, {'value': 2}) is True
    assert json.loads(target.read_text(encoding='utf-8')) == {'value': 2}


def test_windows_atomic_replace_retries_transient_sharing_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / 'state.txt'
    target.write_text('old', encoding='utf-8')
    real_replace = os.replace
    attempts = 0
    sleeps: list[float] = []

    def replace_after_sharing_failure(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            error = PermissionError(5, 'Access is denied')
            error.winerror = 32
            raise error
        return real_replace(source, destination)

    monkeypatch.setattr(atomic.os, 'name', 'nt')
    monkeypatch.setattr(os, 'replace', replace_after_sharing_failure)
    monkeypatch.setattr(atomic.time, 'sleep', sleeps.append)

    atomic.atomic_write_text(target, 'new')

    assert target.read_text(encoding='utf-8') == 'new'
    assert attempts == 3
    assert sleeps == [0.025, 0.05]
