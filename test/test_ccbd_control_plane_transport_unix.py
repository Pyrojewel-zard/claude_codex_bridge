from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccbd.control_plane_transport.endpoint import endpoint_from_legacy_socket_path, endpoint_from_record, endpoint_to_record
from ccbd.control_plane_transport.factory import transport_for_endpoint
from ccbd.control_plane_transport.unix import UnixControlPlaneListener
from ccbd.models import CcbdLease, MountState
from ccbd.services.lifecycle import CcbdLifecycle, build_lifecycle
from ccbd.services.project_inspection import ProjectDaemonInspection
from ccbd.socket_client_runtime import CcbdClientError, connect_socket


def test_endpoint_legacy_projection_roundtrips() -> None:
    endpoint = endpoint_from_legacy_socket_path('C:/tmp/ccbd.sock')
    expected = str(Path('C:/tmp/ccbd.sock'))

    assert endpoint['kind'] == 'unix_socket'
    assert endpoint['legacy_socket_path'] == expected
    assert endpoint_to_record(endpoint)['address'] == expected
    assert endpoint_to_record(endpoint)['socket_path'] == expected


def test_endpoint_record_normalizes_unix_socket_path_like_legacy_path() -> None:
    endpoint = endpoint_from_record({'kind': 'unix_socket', 'address': '  C:/tmp/ccbd.sock  '})

    assert endpoint == endpoint_from_legacy_socket_path('C:/tmp/ccbd.sock')


def test_transport_factory_accepts_legacy_socket_path_record(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory.os.name', 'posix')

    transport = transport_for_endpoint({'socket_path': str(tmp_path / 'ccbd.sock')})

    assert transport.endpoint['kind'] == 'unix_socket'
    assert str(transport.socket_path) == str(tmp_path / 'ccbd.sock')


def test_unix_listener_exposes_selectable_file_descriptor() -> None:
    class _Socket:
        def fileno(self) -> int:
            return 42

        def close(self) -> None:
            pass

    listener = UnixControlPlaneListener(
        endpoint=endpoint_from_legacy_socket_path('/tmp/ccbd.sock'),
        socket_path=Path('/tmp/ccbd.sock'),
        socket=_Socket(),
        bound_socket_stat=(1, 2),
    )

    assert listener.fileno() == 42


def test_unix_connect_adapter_retries_transient_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory.os.name', 'posix')
    monkeypatch.setattr('ccbd.control_plane_transport.unix.socket.AF_UNIX', object(), raising=False)
    current = {'t': 0.0}
    attempts: list[object] = []
    sleeps: list[float] = []

    class _FakeSocket:
        def __init__(self) -> None:
            self.timeout = None

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, path: str) -> None:
            attempts.append((path, self.timeout))
            if len(attempts) == 1:
                raise OSError(errno.EAGAIN, 'Resource temporarily unavailable')

        def close(self) -> None:
            pass

    monkeypatch.setattr('ccbd.control_plane_transport.unix.time.monotonic', lambda: current['t'])

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current['t'] += float(seconds)

    monkeypatch.setattr('ccbd.control_plane_transport.unix.time.sleep', _sleep)
    monkeypatch.setattr('ccbd.control_plane_transport.unix.socket.socket', lambda *args, **kwargs: _FakeSocket())

    sock = connect_socket(tmp_path / 'ccbd.sock', timeout_s=0.5)

    assert isinstance(sock, _FakeSocket)
    assert len(attempts) == 2
    assert sleeps == [0.05]


def test_unix_connect_adapter_wraps_unsupported_platform(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr('ccbd.control_plane_transport.factory.os.name', 'posix')
    monkeypatch.delattr('ccbd.control_plane_transport.unix.socket.AF_UNIX', raising=False)

    with pytest.raises(CcbdClientError, match='unix domain sockets are not supported'):
        connect_socket(tmp_path / 'ccbd.sock', timeout_s=0.1)


def test_lease_record_keeps_socket_path_and_adds_endpoint_descriptor(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    lease = CcbdLease(
        project_id='proj',
        ccbd_pid=123,
        socket_path=str(socket_path),
        owner_uid=1,
        boot_id='boot',
        started_at='2026-07-20T00:00:00Z',
        last_heartbeat_at='2026-07-20T00:00:00Z',
        mount_state=MountState.MOUNTED,
    )

    record = lease.to_record()

    assert record['socket_path'] == str(socket_path)
    assert record['control_plane_endpoint']['kind'] == 'unix_socket'
    assert record['control_plane_endpoint']['legacy_socket_path'] == str(socket_path)


def test_lifecycle_from_record_derives_endpoint_descriptor_from_legacy_socket_path(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    record = build_lifecycle(
        project_id='proj',
        occurred_at='2026-07-20T00:00:00Z',
        desired_state='running',
        phase='mounted',
        generation=1,
        socket_path=socket_path,
    ).to_record()
    record.pop('control_plane_endpoint')

    lifecycle = CcbdLifecycle.from_record(record)

    assert lifecycle.control_plane_endpoint['kind'] == 'unix_socket'
    assert lifecycle.control_plane_endpoint['legacy_socket_path'] == str(socket_path)


def test_project_inspection_normalizes_legacy_endpoint_record(tmp_path: Path) -> None:
    socket_path = tmp_path / 'ccbd.sock'
    inspection = ProjectDaemonInspection(
        lease=None,
        health='healthy',
        pid_alive=True,
        socket_connectable=True,
        heartbeat_fresh=True,
        takeover_allowed=False,
        reason='healthy',
        phase='mounted',
        desired_state='running',
        lifecycle=SimpleNamespace(control_plane_endpoint={'socket_path': str(socket_path)}, socket_path=None),
    )

    endpoint = inspection.control_plane_endpoint

    assert endpoint['kind'] == 'unix_socket'
    assert endpoint['legacy_socket_path'] == str(socket_path)


def test_ownership_guard_default_probe_uses_endpoint_descriptor(monkeypatch, tmp_path: Path) -> None:
    from ccbd.services.ownership import OwnershipGuard

    class _MountManager:
        def load_state(self):
            return None

    seen: list[dict] = []
    monkeypatch.setattr(
        'ccbd.services.ownership.endpoint_connectable',
        lambda endpoint: seen.append(dict(endpoint)) or True,
    )
    socket_path = tmp_path / 'ccbd.sock'
    lease = CcbdLease(
        project_id='proj',
        ccbd_pid=123,
        socket_path=str(socket_path),
        owner_uid=1,
        boot_id='boot',
        started_at='2026-07-20T00:00:00Z',
        last_heartbeat_at='2026-07-20T00:00:00Z',
        mount_state=MountState.MOUNTED,
        control_plane_endpoint=endpoint_to_record(endpoint_from_legacy_socket_path(socket_path)),
    )
    guard = OwnershipGuard(tmp_path, _MountManager(), pid_exists=lambda _pid: True)

    assert guard._mounted_socket_connectable(lease) is True
    assert seen[0]['legacy_socket_path'] == str(socket_path)
