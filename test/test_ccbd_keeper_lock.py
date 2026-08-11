from __future__ import annotations

from pathlib import Path

from ccbd.keeper_runtime.support import try_acquire_keeper_lock


def test_keeper_lock_acquired_once(tmp_path: Path) -> None:
    """两个并发获取者只能有一个胜出。

    回归背景（2026-08-06-herdr-windows-keeper-mutex-config-runtime G2）：
    修复前 Windows 上 `import fcntl` 缺失时直接返回未加锁的 handle，
    第二个获取者也拿到"锁"，导致双 keeper 并发、状态文件互相覆盖。
    """
    lock_path = tmp_path / "keeper.lock"
    first = try_acquire_keeper_lock(lock_path)
    try:
        assert first is not None, "first keeper should acquire the lock"
        second = try_acquire_keeper_lock(lock_path)
        try:
            assert second is None, "second keeper must not acquire an already-held lock"
        finally:
            if second is not None:
                second.close()
    finally:
        if first is not None:
            first.close()


def test_keeper_lock_released_after_close(tmp_path: Path) -> None:
    """持有者 close 后锁必须释放，后续获取者可重新拿到。"""
    lock_path = tmp_path / "keeper.lock"
    first = try_acquire_keeper_lock(lock_path)
    assert first is not None, "first keeper should acquire the lock"
    first.close()

    second = try_acquire_keeper_lock(lock_path)
    try:
        assert second is not None, "lock should be reacquirable after release"
    finally:
        if second is not None:
            second.close()


def test_keeper_lock_returns_none_when_file_locked_elsewhere(tmp_path: Path) -> None:
    """不同 handle 对同一锁文件区域并发获取时，后到者返回 None（fail-closed）。

    覆盖 msvcrt（Windows）与 fcntl（POSIX）两条实现路径的互斥语义。
    """
    lock_path = tmp_path / "keeper.lock"
    held = lock_path.open("a+b")
    try:
        if held.tell() == 0 and lock_path.stat().st_size == 0:
            held.write(b"\0")
            held.flush()
        held.seek(0)
        try:
            import msvcrt  # type: ignore

            msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, 1)
        except ModuleNotFoundError:
            import fcntl  # type: ignore

            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        contender = try_acquire_keeper_lock(lock_path)
        try:
            assert contender is None, "contender must fail when lock is held elsewhere"
        finally:
            if contender is not None:
                contender.close()
    finally:
        held.close()
