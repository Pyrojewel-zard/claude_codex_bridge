from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from urllib import request as urllib_request

import pytest

from mobile_gateway import MobileGatewayPairingStore
from cli.services import mobile_host
from cli.services.mobile_host import (
    MOBILE_HOST_SERVE_COMMAND,
    MOBILE_HOST_SERVICE_RECORD_TYPE,
    MobileHostServiceError,
    PortOwner,
    detect_loopback_port_owner,
    mobile_host_service_paths,
    run_mobile_host_serve_command,
    start_or_replace_mobile_host_service,
    write_mobile_host_service_state,
)


class _FakeProcess:
    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode


def _pairing_payload() -> dict[str, object]:
    return {
        'pairing_code': 'stable-code',
        'pairing_id': 'pair-stable',
        'project_id': 'host-test',
        'route_provider': 'tailnet',
        'gateway_url': 'https://desktop.tailnet.ts.net:8787',
        'claim_endpoint': 'https://desktop.tailnet.ts.net:8787/v1/pairing/claim',
        'scopes': ['view'],
        'expires_at': '2999-07-02T00:10:00Z',
    }


def _claimable_pairing_payload(state_dir: Path) -> dict[str, object]:
    store = MobileGatewayPairingStore(
        state_dir,
        token_factory=lambda _bytes: 'stable-code',
        id_factory=lambda prefix: f'{prefix}-stable',
    )
    return store.create_pairing_payload(
        project_id='host-test',
        gateway_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        scopes=('view',),
    )


def _write_spawned_child_state(
    state_dir: Path,
    *,
    pid: int = 222,
    generation: int = 1,
    listen: str = '127.0.0.1:8787',
    gateway_url: str = 'https://desktop.tailnet.ts.net:8787',
    route_provider: str = 'tailnet',
) -> None:
    paths = mobile_host_service_paths(state_dir)
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': pid,
            'generation': generation,
            'listen': listen,
            'local_gateway_url': f'http://{listen}',
            'gateway_url': gateway_url,
            'route_provider': route_provider,
            'pairing': {
                **_pairing_payload(),
                'gateway_url': gateway_url,
                'claim_endpoint': f'{gateway_url}/v1/pairing/claim',
                'route_provider': route_provider,
            },
            'state_dir': str(state_dir),
            'command_kind': 'ccb_mobile_host_serve',
        },
    )


def test_mobile_host_service_clears_stale_state_and_starts(tmp_path: Path) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'command_kind': 'ccb_mobile_host_serve',
        },
    )
    spawned: list[dict[str, object]] = []

    def _spawn(command, **kwargs):
        spawned.append({'command': command, **kwargs})
        generation = int(command[command.index('--generation') + 1])
        _write_spawned_child_state(state_dir, generation=generation)
        return _FakeProcess(222)

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda pid: False,
        port_owner_fn=lambda _listen: None,
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
    )

    assert result.status == 'started'
    assert result.pid == 222
    assert result.generation == 1
    assert spawned
    assert spawned[0]['command'][2] == MOBILE_HOST_SERVE_COMMAND
    assert spawned[0]['cwd'] == str(Path.cwd())
    assert spawned[0]['env']['CCB_MOBILE_HOST_STATE_HOME'] == str(state_dir)
    assert spawned[0]['env']['CCB_SOURCE_RUNTIME_OK'] == '1'
    assert paths.state_path.exists()


def test_mobile_host_health_check_tolerates_server_wide_health_latency() -> None:
    class _SlowHealthyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            if self.path != '/v1/health':
                self.send_response(404)
                self.end_headers()
                return
            time.sleep(0.75)
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), _SlowHealthyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        assert mobile_host._http_health_check(f'http://{host}:{port}')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_mobile_host_health_check_bypasses_configured_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HealthyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            if self.path != '/v1/health':
                self.send_response(404)
                self.end_headers()
                return
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(('127.0.0.1', 0))
        unavailable_proxy_port = reserved.getsockname()[1]

    proxy_url = f'http://127.0.0.1:{unavailable_proxy_port}'
    proxy_names = (
        'HTTP_PROXY',
        'http_proxy',
        'HTTPS_PROXY',
        'https_proxy',
        'ALL_PROXY',
        'all_proxy',
    )
    for name in proxy_names:
        monkeypatch.setenv(name, proxy_url)
    for name in ('NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(urllib_request, '_opener', None)

    server = ThreadingHTTPServer(('127.0.0.1', 0), _HealthyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        assert mobile_host._http_health_check(f'http://{host}:{port}')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_mobile_host_service_returns_pairing_written_by_spawned_child(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'

    def _spawn(command, **_kwargs):
        generation = int(command[command.index('--generation') + 1])
        _write_spawned_child_state(state_dir, generation=generation)
        return _FakeProcess(222)

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda _pid: False,
        port_owner_fn=lambda _listen: None,
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
    )

    assert result.status == 'started'
    assert result.pid == 222
    assert result.generation == 1
    assert result.pairing == _pairing_payload()


def test_mobile_host_service_preserves_pairing_for_live_matching_process(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    pairing = _claimable_pairing_payload(state_dir)
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'host_id': 'host-test',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'https://desktop.tailnet.ts.net:8787',
            'route_provider': 'tailnet',
            'pairing': pairing,
            'state_dir': str(state_dir),
            'command_kind': 'ccb_mobile_host_serve',
        },
    )
    spawned: list[object] = []
    terminated: list[int] = []

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda pid: pid == 111,
        process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND} --state-dir {state_dir}' if pid == 111 else '',
        terminate_pid_tree_fn=lambda pid, **_kwargs: terminated.append(pid) or True,
        port_owner_fn=lambda _listen: PortOwner(pid=111, command='python ccb.py __mobile-host-serve'),
        spawn_fn=lambda *_args, **_kwargs: spawned.append(1) or _FakeProcess(222),
        health_check_fn=lambda url: url == 'http://127.0.0.1:8787',
    )

    assert result.status == 'running'
    assert result.pid == 111
    assert result.generation == 4
    assert result.replaced_pid is None
    assert terminated == []
    assert spawned == []
    assert result.pairing is not None
    assert result.pairing['pairing_code'] == pairing['pairing_code']
    assert result.pairing['expires_at'] == pairing['expires_at']
    assert result.to_record()['pairing'] == result.pairing
    store = MobileGatewayPairingStore(state_dir)
    assert store.pairing_code_is_claimable(str(pairing['pairing_code']))


def test_mobile_host_service_does_not_rotate_legacy_expired_pairing_without_update(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    expired_pairing = {
        **_pairing_payload(),
        'pairing_code': 'expired-code',
        'expires_at': '2000-01-01T00:00:00Z',
    }
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'host_id': 'host-test',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'https://desktop.tailnet.ts.net:8787',
            'route_provider': 'tailnet',
            'pairing': expired_pairing,
            'state_dir': str(state_dir),
            'command_kind': 'ccb_mobile_host_serve',
        },
    )
    spawned: list[object] = []
    terminated: list[int] = []

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda pid: pid == 111,
        process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND} --state-dir {state_dir}' if pid == 111 else '',
        terminate_pid_tree_fn=lambda pid, **_kwargs: terminated.append(pid) or True,
        port_owner_fn=lambda _listen: PortOwner(pid=111, command='python ccb.py __mobile-host-serve'),
        spawn_fn=lambda *_args, **_kwargs: spawned.append(1) or _FakeProcess(222),
        health_check_fn=lambda url: url == 'http://127.0.0.1:8787',
    )

    assert result.status == 'running'
    assert result.pid == 111
    assert result.replaced_pid is None
    assert terminated == []
    assert spawned == []
    assert result.pairing is None
    assert result.pairing_diagnostic is not None
    assert 'ccb update mobile' in result.pairing_diagnostic
    assert result.to_record()['pairing_diagnostic'] == result.pairing_diagnostic
    state = json.loads(paths.state_path.read_text(encoding='utf-8'))
    assert state['pairing'] == expired_pairing


def test_mobile_host_service_diagnoses_claimed_legacy_one_shot_pairing_without_restart(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    pairing = _claimable_pairing_payload(state_dir)
    MobileGatewayPairingStore(state_dir).claim_pairing(
        pairing_code=str(pairing['pairing_code']),
        device_name='Pixel',
    )
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'host_id': 'host-test',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'https://desktop.tailnet.ts.net:8787',
            'route_provider': 'tailnet',
            'pairing': pairing,
            'state_dir': str(state_dir),
            'command_kind': 'ccb_mobile_host_serve',
        },
    )
    spawned: list[object] = []
    terminated: list[int] = []

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda pid: pid == 111,
        process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND} --state-dir {state_dir}' if pid == 111 else '',
        terminate_pid_tree_fn=lambda pid, **_kwargs: terminated.append(pid) or True,
        port_owner_fn=lambda _listen: PortOwner(pid=111, command='python ccb.py __mobile-host-serve'),
        spawn_fn=lambda *_args, **_kwargs: spawned.append(1) or _FakeProcess(222),
        health_check_fn=lambda url: url == 'http://127.0.0.1:8787',
    )

    assert result.status == 'running'
    assert terminated == []
    assert spawned == []
    assert result.pairing is None
    assert result.pairing_diagnostic is not None
    assert 'ccb update mobile' in result.pairing_diagnostic


def test_mobile_host_update_rotation_invalidates_handoff_but_keeps_device_token(tmp_path: Path) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    store = MobileGatewayPairingStore(state_dir)
    pairing = store.ensure_reusable_pairing_payload(
        project_id='host-test',
        gateway_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        scopes=('view',),
    )
    claim = store.claim_pairing(pairing_code=str(pairing['pairing_code']), device_name='Phone')
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'host_id': 'host-test',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'https://desktop.tailnet.ts.net:8787',
            'route_provider': 'tailnet',
            'pairing': pairing,
            'state_dir': str(state_dir),
            'command_kind': 'ccb_mobile_host_serve',
        },
    )

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        rotate_pairing=True,
        process_exists_fn=lambda pid: pid == 111,
        process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND} --state-dir {state_dir}' if pid == 111 else '',
        terminate_pid_tree_fn=lambda *_args, **_kwargs: True,
        port_owner_fn=lambda _listen: PortOwner(pid=111, command='python ccb.py __mobile-host-serve'),
        spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222),
        health_check_fn=lambda _url: True,
    )

    assert result.status == 'running'
    assert result.pairing is not None
    assert result.pairing['pairing_code'] != pairing['pairing_code']
    assert not store.pairing_code_is_claimable(str(pairing['pairing_code']))
    assert store.authenticate_device(str(claim['device_token']), required_scopes=('view',)).device_id == claim['device']['device_id']


def test_mobile_host_service_replaces_live_managed_process(tmp_path: Path) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'command_kind': 'ccb_mobile_host_serve',
            'state_dir': str(state_dir),
        },
    )
    alive = {111}
    terminated: list[int] = []

    def _terminate(pid: int, **_kwargs) -> bool:
        terminated.append(pid)
        alive.discard(pid)
        return True

    def _spawn(command, **_kwargs):
        generation = int(command[command.index('--generation') + 1])
        _write_spawned_child_state(state_dir, generation=generation)
        return _FakeProcess(222)

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda pid: pid in alive,
        process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND} --state-dir {state_dir}' if pid == 111 else '',
        terminate_pid_tree_fn=_terminate,
        port_owner_fn=lambda _listen: None,
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
    )

    assert terminated == [111]
    assert result.status == 'replaced'
    assert result.replaced_pid == 111
    assert result.generation == 5


def test_mobile_host_service_waits_for_pairing_state_after_health_ready(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    reads = 0
    tick = -0.01

    def _spawn(command, **_kwargs):
        generation = int(command[command.index('--generation') + 1])
        write_mobile_host_service_state(
            paths.state_path,
            {
                'schema_version': 1,
                'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
                'pid': 222,
                'generation': generation,
                'listen': '127.0.0.1:8787',
                'local_gateway_url': 'http://127.0.0.1:8787',
                'gateway_url': 'https://desktop.tailnet.ts.net:8787',
                'route_provider': 'tailnet',
                'state_dir': str(state_dir),
                'command_kind': 'ccb_mobile_host_serve',
            },
        )
        return _FakeProcess(222)

    def _monotonic() -> float:
        nonlocal tick
        tick += 0.01
        return tick

    def _sleep(_seconds: float) -> None:
        nonlocal reads
        reads += 1
        if reads == 1:
            state = json.loads(paths.state_path.read_text(encoding='utf-8'))
            state['pairing'] = _pairing_payload()
            write_mobile_host_service_state(paths.state_path, state)

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=state_dir,
        process_exists_fn=lambda _pid: False,
        port_owner_fn=lambda _listen: None,
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
        sleep_fn=_sleep,
        monotonic_fn=_monotonic,
    )

    assert result.status == 'started'
    assert result.pairing == _pairing_payload()
    assert reads == 1


def test_mobile_host_service_refuses_external_port_owner(tmp_path: Path) -> None:
    killed: list[int] = []

    with pytest.raises(MobileHostServiceError, match='non-CCB process') as excinfo:
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='127.0.0.1:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=tmp_path / 'mobile',
            process_exists_fn=lambda _pid: True,
            process_cmdline_fn=lambda _pid: 'python /tmp/external_gateway.py',
            terminate_pid_tree_fn=lambda pid, **_kwargs: killed.append(pid) or True,
            port_owner_fn=lambda _listen: PortOwner(pid=333, command='python /tmp/external_gateway.py'),
            spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222),
            health_check_fn=lambda _url: True,
        )

    assert killed == []
    assert 'pid=333' in str(excinfo.value)


def test_mobile_host_service_replaces_legacy_foreground_gateway(tmp_path: Path) -> None:
    source_root = tmp_path / 'source'
    state_dir = tmp_path / 'mobile'
    legacy_command = (
        f'python {source_root / "ccb.py"} install mobile '
        '--listen 127.0.0.1:8787 --route-provider lan'
    )
    alive = {333}
    killed: list[int] = []

    def _terminate(pid: int, **_kwargs) -> bool:
        killed.append(pid)
        alive.discard(pid)
        return True

    def _spawn(command, **_kwargs):
        generation = int(command[command.index('--generation') + 1])
        _write_spawned_child_state(
            state_dir,
            generation=generation,
            gateway_url='http://127.0.0.1:8787',
            route_provider='lan',
        )
        return _FakeProcess(222)

    result = start_or_replace_mobile_host_service(
        script_root=source_root,
        listen='127.0.0.1:8787',
        public_url=None,
        route_provider='lan',
        state_dir=state_dir,
        process_exists_fn=lambda pid: pid in alive,
        process_cmdline_fn=lambda pid: legacy_command if pid == 333 else '',
        terminate_pid_tree_fn=_terminate,
        port_owner_fn=lambda _listen: (
            PortOwner(pid=333, command=legacy_command) if 333 in alive else None
        ),
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
    )

    assert killed == [333]
    assert result.status == 'replaced'
    assert result.replaced_pid == 333


def test_mobile_host_service_refuses_legacy_gateway_from_other_source(tmp_path: Path) -> None:
    source_root = tmp_path / 'source'
    external_command = (
        f'python {tmp_path / "other" / "ccb.py"} install mobile '
        '--listen 127.0.0.1:8787 --route-provider lan'
    )
    killed: list[int] = []

    with pytest.raises(MobileHostServiceError, match='non-CCB process'):
        start_or_replace_mobile_host_service(
            script_root=source_root,
            listen='127.0.0.1:8787',
            public_url=None,
            route_provider='lan',
            state_dir=tmp_path / 'mobile',
            process_exists_fn=lambda _pid: True,
            process_cmdline_fn=lambda _pid: external_command,
            terminate_pid_tree_fn=lambda pid, **_kwargs: killed.append(pid) or True,
            port_owner_fn=lambda _listen: PortOwner(pid=333, command=external_command),
            spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222),
            health_check_fn=lambda _url: True,
        )

    assert killed == []


def test_mobile_host_service_refuses_truncated_managed_command_from_other_state_dir(tmp_path: Path) -> None:
    state_dir = tmp_path / 'mobile'
    other_state_dir = tmp_path / 'other-mobile'
    paths = mobile_host_service_paths(state_dir)
    write_mobile_host_service_state(
        paths.state_path,
        {
            'schema_version': 1,
            'record_type': MOBILE_HOST_SERVICE_RECORD_TYPE,
            'pid': 111,
            'generation': 4,
            'command_kind': 'ccb_mobile_host_serve',
            'state_dir': str(other_state_dir),
        },
    )
    killed: list[int] = []
    spawned: list[int] = []

    with pytest.raises(MobileHostServiceError, match='non-CCB process'):
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='127.0.0.1:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=state_dir,
            process_exists_fn=lambda pid: pid == 111,
            process_cmdline_fn=lambda pid: f'python ccb.py {MOBILE_HOST_SERVE_COMMAND}' if pid == 111 else '',
            terminate_pid_tree_fn=lambda pid, **_kwargs: killed.append(pid) or True,
            port_owner_fn=lambda _listen: PortOwner(pid=111, command='python ccb.py __mobile-host-serve'),
            spawn_fn=lambda *_args, **_kwargs: spawned.append(1) or _FakeProcess(222),
            health_check_fn=lambda _url: True,
        )

    assert killed == []
    assert spawned == []


def test_mobile_host_service_lock_times_out_when_concurrent_update_stays_active(tmp_path: Path) -> None:
    paths = mobile_host_service_paths(tmp_path / 'mobile')
    paths.state_dir.mkdir(parents=True)
    paths.lock_path.write_text(json.dumps({'pid': 999}) + '\n', encoding='utf-8')

    with pytest.raises(MobileHostServiceError, match='already in progress'):
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='127.0.0.1:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=paths.state_dir,
            process_exists_fn=lambda pid: pid == 999,
            port_owner_fn=lambda _listen: None,
            spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222),
            health_check_fn=lambda _url: True,
            lock_wait_timeout_s=0.0,
        )


def test_mobile_host_service_waits_for_concurrent_update_to_finish(tmp_path: Path) -> None:
    paths = mobile_host_service_paths(tmp_path / 'mobile')
    paths.state_dir.mkdir(parents=True)
    paths.lock_path.write_text(json.dumps({'pid': 999}) + '\n', encoding='utf-8')
    spawned: list[object] = []
    sleeps: list[float] = []
    tick = -0.01

    def _monotonic() -> float:
        nonlocal tick
        tick += 0.01
        return tick

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if paths.lock_path.exists():
            paths.lock_path.unlink()

    def _spawn(*_args, **_kwargs):
        spawned.append(1)
        _write_spawned_child_state(paths.state_dir)
        return _FakeProcess(222)

    result = start_or_replace_mobile_host_service(
        script_root=tmp_path / 'source',
        listen='127.0.0.1:8787',
        public_url='https://desktop.tailnet.ts.net:8787',
        route_provider='tailnet',
        state_dir=paths.state_dir,
        process_exists_fn=lambda pid: pid == 999,
        port_owner_fn=lambda _listen: None,
        spawn_fn=_spawn,
        health_check_fn=lambda _url: True,
        sleep_fn=_sleep,
        monotonic_fn=_monotonic,
        lock_wait_timeout_s=1.0,
    )

    assert result.status == 'started'
    assert result.pid == 222
    assert spawned == [1]
    assert len(sleeps) == 1


def test_mobile_host_service_terminates_spawned_process_when_health_never_ready(tmp_path: Path) -> None:
    tick = 0.0
    terminated: list[int] = []

    def _monotonic() -> float:
        nonlocal tick
        tick += 10.0
        return tick

    with pytest.raises(MobileHostServiceError, match='did not become healthy'):
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='127.0.0.1:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=tmp_path / 'mobile',
            process_exists_fn=lambda _pid: False,
            terminate_pid_tree_fn=lambda pid, **_kwargs: terminated.append(pid) or True,
            port_owner_fn=lambda _listen: None,
            spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222),
            health_check_fn=lambda _url: False,
            sleep_fn=lambda _seconds: None,
            monotonic_fn=_monotonic,
        )

    assert terminated == [222]


def test_mobile_host_service_reports_exit_code_and_log_tail(tmp_path: Path) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    paths.state_dir.mkdir(parents=True)
    paths.log_path.write_text(
        'Refusing to run the CCB source checkout outside an allowed test project.\n'
        'Current directory: /tmp/ccb_main_direct\n',
        encoding='utf-8',
    )

    with pytest.raises(MobileHostServiceError) as excinfo:
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='127.0.0.1:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=state_dir,
            process_exists_fn=lambda _pid: False,
            terminate_pid_tree_fn=lambda _pid, **_kwargs: True,
            port_owner_fn=lambda _listen: None,
            spawn_fn=lambda *_args, **_kwargs: _FakeProcess(222, returncode=1),
            health_check_fn=lambda _url: False,
            sleep_fn=lambda _seconds: None,
        )

    message = str(excinfo.value)
    assert 'exited before becoming healthy: exit_code=1' in message
    assert 'Refusing to run the CCB source checkout' in message
    assert 'Current directory: /tmp/ccb_main_direct' in message


def test_detect_loopback_port_owner_uses_lsof_when_ss_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _which(name: str) -> str | None:
        return None if name == 'ss' else '/usr/sbin/lsof'

    def _run(command, **_kwargs):
        assert command[0] == 'lsof'
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                'COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n'
                'python3   444 user 3u IPv4 0t0 TCP 127.0.0.1:8787 (LISTEN)\n'
            ),
            stderr='',
        )

    monkeypatch.setattr(mobile_host.shutil, 'which', _which)
    monkeypatch.setattr(mobile_host.subprocess, 'run', _run)
    monkeypatch.setattr(mobile_host, '_process_cmdline', lambda pid: 'python gateway.py' if pid == 444 else '')

    owner = detect_loopback_port_owner('127.0.0.1:8787')

    assert owner == PortOwner(pid=444, command='python gateway.py')


def test_detect_loopback_port_owner_uses_windows_netstat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(command, **_kwargs):
        assert command == ['netstat', '-ano', '-p', 'tcp']
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '  Proto  Local Address          Foreign Address        State           PID\n'
                '  TCP    127.0.0.1:8787         0.0.0.0:0              LISTENING       111\n'
                '  TCP    192.168.31.155:8787    0.0.0.0:0              LISTENING       555\n'
            ),
            stderr='',
        )

    monkeypatch.setattr(mobile_host.os, 'name', 'nt')
    monkeypatch.setattr(mobile_host.subprocess, 'run', _run)
    monkeypatch.setattr(mobile_host, '_process_cmdline', lambda pid: 'python mobile.py' if pid == 555 else '')

    owner = mobile_host._detect_loopback_port_owner_netstat(
        host='192.168.31.155',
        port=8787,
    )

    assert owner == PortOwner(pid=555, command='python mobile.py')


def test_detect_loopback_port_owner_accepts_specific_private_lan_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def _detect(*, host: str, port: int):
        calls.append((host, port))
        return PortOwner(pid=445, command='python lan-gateway.py')

    monkeypatch.setattr(mobile_host, '_detect_loopback_port_owner_ss', _detect)

    owner = detect_loopback_port_owner('192.168.31.155:8787')

    assert owner == PortOwner(pid=445, command='python lan-gateway.py')
    assert calls == [('192.168.31.155', 8787)]


def test_mobile_host_service_rejects_private_listen_for_non_lan_route(
    tmp_path: Path,
) -> None:
    with pytest.raises(MobileHostServiceError, match='loopback'):
        start_or_replace_mobile_host_service(
            script_root=tmp_path / 'source',
            listen='192.168.31.155:8787',
            public_url='https://desktop.tailnet.ts.net:8787',
            route_provider='tailnet',
            state_dir=tmp_path / 'mobile',
        )


def test_detect_loopback_port_owner_reports_unknown_when_tools_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    monkeypatch.setattr(mobile_host.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(mobile_host.subprocess, 'run', _run)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        port = server.getsockname()[1]

        owner = detect_loopback_port_owner(f'127.0.0.1:{port}')

    assert owner == PortOwner(pid=0, command='unknown loopback listener')


def test_mobile_host_serve_removes_current_state_after_server_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    paths = mobile_host_service_paths(state_dir)
    closed: list[bool] = []

    class _Handle:
        summary = {
            'host_id': 'desktop',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'http://127.0.0.1:8787',
            'route_provider': 'tailnet',
            'pairing': _pairing_payload(),
        }

        def serve_forever(self) -> None:
            assert paths.state_path.exists()
            state = json.loads(paths.state_path.read_text(encoding='utf-8'))
            assert state['pairing'] == _pairing_payload()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(mobile_host, 'prepare_server_mobile_gateway', lambda *_args, **_kwargs: _Handle())

    code = run_mobile_host_serve_command(
        SimpleNamespace(
            listen='127.0.0.1:8787',
            public_url=None,
            route_provider='tailnet',
            state_dir=str(state_dir),
            generation=7,
            host_id='desktop',
        ),
        script_root=tmp_path / 'source',
    )

    assert code == 0
    assert closed == [True]
    assert not paths.state_path.exists()


def test_mobile_host_serve_closes_gateway_on_sigterm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile'
    closed: list[bool] = []

    class _Handle:
        summary = {
            'host_id': 'desktop',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'http://127.0.0.1:8787',
            'route_provider': 'lan',
            'pairing': _pairing_payload(),
        }

        def serve_forever(self) -> None:
            mobile_host._raise_mobile_host_shutdown(None, None)

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(
        mobile_host,
        'prepare_server_mobile_gateway',
        lambda *_args, **_kwargs: _Handle(),
    )

    code = run_mobile_host_serve_command(
        SimpleNamespace(
            listen='127.0.0.1:8787',
            public_url=None,
            route_provider='lan',
            state_dir=str(state_dir),
            generation=7,
            host_id='desktop',
        ),
        script_root=tmp_path / 'source',
    )

    assert code == 0
    assert closed == [True]
    assert not mobile_host_service_paths(state_dir).state_path.exists()


def test_mobile_host_serve_runs_relay_connector_with_activated_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / 'mobile-relay'
    paths = mobile_host_service_paths(state_dir)
    events: list[str] = []
    credentials = SimpleNamespace(
        host_id='host-activated',
        relay_mode='official',
    )

    class _Handle:
        summary = {
            'host_id': 'host-activated',
            'listen': '127.0.0.1:8787',
            'local_gateway_url': 'http://127.0.0.1:8787',
            'gateway_url': 'http://127.0.0.1:8787',
            'route_provider': 'relay',
            'pairing': _pairing_payload(),
        }

        def serve_forever(self) -> None:
            state = json.loads(paths.state_path.read_text(encoding='utf-8'))
            assert state['relay_outbound']['state'] == 'registered'
            events.append('serve')

        def close(self) -> None:
            events.append('gateway-stop')

    class _Runtime:
        def __init__(self, *, credentials, gateway_origin) -> None:
            assert credentials.host_id == 'host-activated'
            assert gateway_origin == 'http://127.0.0.1:8787'

        def start(self) -> None:
            events.append('relay-start')

        def stop(self) -> None:
            events.append('relay-stop')

        def diagnostics(self) -> dict[str, object]:
            return {'state': 'registered', 'host_id': 'host-activated'}

    def _prepare(_command, *, host_id, **_kwargs):
        assert host_id == 'host-activated'
        return _Handle()

    monkeypatch.setattr(mobile_host, 'load_relay_host_credentials', lambda _path: credentials)
    monkeypatch.setattr(mobile_host, 'RelayHostConnectorRuntime', _Runtime)
    monkeypatch.setattr(mobile_host, 'prepare_server_mobile_gateway', _prepare)

    code = run_mobile_host_serve_command(
        SimpleNamespace(
            listen='127.0.0.1:8787',
            public_url=None,
            route_provider='relay',
            state_dir=str(state_dir),
            generation=8,
            host_id=None,
        ),
        script_root=tmp_path / 'source',
    )

    assert code == 0
    assert events == ['relay-start', 'serve', 'relay-stop', 'gateway-stop']
    assert not paths.state_path.exists()


def test_mobile_host_serve_reports_state_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed: list[bool] = []

    class _Handle:
        summary = {'listen': '127.0.0.1:8787'}

        def serve_forever(self) -> None:
            raise AssertionError('serve_forever should not run when state write fails')

        def close(self) -> None:
            closed.append(True)

    def _fail_write(_path, _payload) -> None:
        raise OSError('disk full')

    monkeypatch.setattr(mobile_host, 'prepare_server_mobile_gateway', lambda *_args, **_kwargs: _Handle())
    monkeypatch.setattr(mobile_host, 'write_mobile_host_service_state', _fail_write)

    code = run_mobile_host_serve_command(
        SimpleNamespace(
            listen='127.0.0.1:8787',
            public_url=None,
            route_provider='tailnet',
            state_dir=str(tmp_path / 'mobile'),
            generation=7,
            host_id=None,
        ),
        script_root=tmp_path / 'source',
    )

    assert code == 1
    assert closed == [True]
    assert 'could not write state: OSError: disk full' in capsys.readouterr().err
