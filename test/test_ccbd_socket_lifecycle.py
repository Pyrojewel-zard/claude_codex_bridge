from __future__ import annotations

import os
from pathlib import Path
import socket

import pytest

from ccbd.socket_server import CcbdSocketServer
import ccbd.control_plane_transport.unix as unix_transport


def test_listen_refuses_to_replace_non_socket_path(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    socket_path.write_text('operator-owned', encoding='utf-8')
    server = CcbdSocketServer(socket_path)

    with pytest.raises(RuntimeError, match='refusing to replace non-socket'):
        server.listen()

    assert socket_path.read_text(encoding='utf-8') == 'operator-owned'
    assert server._server is None


def test_listen_refuses_to_replace_live_foreign_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    foreign = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    foreign.bind(str(socket_path))
    foreign.listen(1)
    original_identity = _path_identity(socket_path)
    server = CcbdSocketServer(socket_path)
    try:
        with pytest.raises(RuntimeError, match='refusing to replace live ccbd socket'):
            server.listen()

        assert _path_identity(socket_path) == original_identity
        assert server._server is None
    finally:
        foreign.close()
        socket_path.unlink(missing_ok=True)


def test_listen_replaces_only_a_stale_socket_inode(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()
    server = CcbdSocketServer(socket_path)
    try:
        server.listen()

        assert server._bound_socket_stat == _path_identity(socket_path)
        assert server._server is not None
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(socket_path))
        finally:
            probe.close()
    finally:
        server.shutdown()
    assert not socket_path.exists()


@pytest.mark.parametrize('failure_stage', ('listen', 'settimeout'))
def test_listen_failure_closes_fd_and_unlinks_only_its_bound_inode(
    tmp_path: Path,
    monkeypatch,
    failure_stage: str,
) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    real_socket_factory = socket.socket
    created = []

    class FailingSocket:
        def __init__(self, family, kind):
            self.inner = real_socket_factory(family, kind)
            created.append(self)

        def bind(self, path: str) -> None:
            self.inner.bind(path)

        def listen(self, backlog: int) -> None:
            if failure_stage == 'listen':
                raise OSError('planned listen failure')
            self.inner.listen(backlog)

        def settimeout(self, timeout: float) -> None:
            if failure_stage == 'settimeout':
                raise OSError('planned settimeout failure')
            self.inner.settimeout(timeout)

        def close(self) -> None:
            self.inner.close()

    monkeypatch.setattr(unix_transport.socket, 'socket', FailingSocket)
    server = CcbdSocketServer(socket_path)

    with pytest.raises(OSError, match=f'planned {failure_stage} failure'):
        server.listen()

    assert len(created) == 1
    assert created[0].inner.fileno() == -1
    assert server._server is None
    assert server._bound_socket_stat is None
    assert not socket_path.exists()


def _path_identity(path: Path) -> tuple[int, int]:
    record = os.stat(path)
    return int(record.st_dev), int(record.st_ino)
