from __future__ import annotations

import pytest

from ccbd.socket_server_runtime.loop import maintenance_worker_loop, next_timeout, next_worker_timeout, post_request_tick, run_after_response_actions, run_queued_maintenance_ticks, run_tick_if_needed, start_maintenance_worker, start_worker, stop_maintenance_worker, stop_worker, worker_loop
from ccbd.socket_server_runtime.server import CcbdSocketServer


def test_request_maintenance_ticks_tracks_submit_policy() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    assert server.request_maintenance_ticks('submit') == 1
    assert server.request_maintenance_ticks('cancel') == 1
    assert server.request_maintenance_ticks('resubmit') == 1
    assert server.request_maintenance_ticks('retry') == 1
    assert server.request_maintenance_ticks('get') == 0


def test_request_maintenance_ticks_honors_double_tick_ops() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    assert server.request_maintenance_ticks('submit') == 1


def test_queue_post_request_maintenance_tracks_submit_policy() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    server.queue_post_request_maintenance('submit')

    assert server.maintenance_pending() is True
    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is False


def test_post_request_tick_submit_only_signals_single_tick() -> None:
    calls: list[str] = []
    server = CcbdSocketServer('/tmp/test.sock')
    server.queue_maintenance_ticks(1)

    next_tick_at = post_request_tick(
        server=server,
        on_tick=lambda: calls.append('tick'),
        next_tick_at=999999.0,
        interval=0.2,
    )

    assert calls == ['tick']
    assert next_tick_at > 0.0


def test_post_request_tick_non_submit_mutation_still_ticks_once() -> None:
    calls: list[str] = []
    server = CcbdSocketServer('/tmp/test.sock')
    server.queue_maintenance_ticks(1)

    next_tick_at = post_request_tick(
        server=server,
        on_tick=lambda: calls.append('tick'),
        next_tick_at=999999.0,
        interval=0.2,
    )

    assert calls == ['tick']
    assert next_tick_at > 0.0


def test_post_request_tick_periodic_tick_still_runs_when_deadline_passed() -> None:
    calls: list[str] = []
    server = CcbdSocketServer('/tmp/test.sock')

    next_tick_at = post_request_tick(
        server=server,
        on_tick=lambda: calls.append('tick'),
        next_tick_at=0.0,
        interval=0.2,
    )

    assert calls == ['tick']
    assert next_tick_at > 0.0
    assert server.take_queued_maintenance_ticks() == 0


def test_request_worker_queue_empty_no_longer_runs_periodic_tick() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    calls: list[str] = []
    server._stop_event.set()

    worker_loop(server, interval=0.2, on_tick=lambda: calls.append('tick'))

    assert calls == []


def test_start_worker_starts_single_worker_lane() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    start_worker(server, interval=0.2, on_tick=None)
    try:
        assert server._worker_thread is not None
        assert server._worker_thread.is_alive()
    finally:
        stop_worker(server)

    assert server._worker_thread is None


def test_finish_runtime_bootstrap_requires_publication_callback(tmp_path) -> None:
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    server.listen()
    start_worker(server, interval=0.2, on_tick=None)
    server.begin_runtime_bootstrap()

    try:
        with pytest.raises(TypeError, match='requires a publication callback'):
            server.finish_runtime_bootstrap(None)

        assert server._runtime_bootstrap_active is True
        assert server._stop_event.is_set() is False
    finally:
        server.shutdown()


def test_finish_runtime_bootstrap_callback_failure_stops_serving(tmp_path) -> None:
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    server.listen()
    start_worker(server, interval=0.2, on_tick=None)
    server.begin_runtime_bootstrap()

    def fail_publication() -> None:
        raise OSError('planned mounted publication failure')

    try:
        with pytest.raises(OSError, match='planned mounted publication failure'):
            server.finish_runtime_bootstrap(fail_publication)

        assert server._runtime_bootstrap_active is True
        assert server._stop_event.is_set() is True
    finally:
        server.shutdown()


def test_finish_runtime_bootstrap_rejects_sticky_worker_error(tmp_path) -> None:
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    publication_calls: list[str] = []
    server.listen()
    start_worker(server, interval=0.2, on_tick=None)
    server.begin_runtime_bootstrap()
    server._record_worker_error(RuntimeError('planned request worker failure'))

    try:
        with pytest.raises(RuntimeError, match='request serving failed'):
            server.finish_runtime_bootstrap(lambda: publication_calls.append('published'))

        assert publication_calls == []
        assert server._runtime_bootstrap_active is True
        assert server._stop_event.is_set() is True
    finally:
        server.shutdown()


def test_finish_runtime_bootstrap_rejects_inactive_gate(tmp_path) -> None:
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    publication_calls: list[str] = []
    server.listen()
    start_worker(server, interval=0.2, on_tick=None)

    try:
        with pytest.raises(RuntimeError, match='runtime bootstrap is not active'):
            server.finish_runtime_bootstrap(lambda: publication_calls.append('published'))

        assert publication_calls == []
        assert server._stop_event.is_set() is True
    finally:
        server.shutdown()


def test_serve_forever_preserves_worker_error_recorded_before_serving(tmp_path) -> None:
    server = CcbdSocketServer(tmp_path / 'ccbd.sock')
    serving_calls: list[str] = []
    failure = RuntimeError('pre-serving worker failed')
    server.listen()
    server._record_worker_error(failure)
    server._stop_event.set()

    try:
        with pytest.raises(RuntimeError) as caught:
            server.serve_forever(
                poll_interval=0.01,
                on_serving=lambda: serving_calls.append('serving'),
            )
    finally:
        server.shutdown()

    assert caught.value is failure
    assert serving_calls == []


def test_maintenance_worker_runs_periodic_tick_until_stop() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    calls: list[str] = []

    def _tick():
        calls.append('tick')
        server._stop_event.set()
        server._maintenance_pending_event.set()

    maintenance_worker_loop(server, interval=0.0, on_tick=_tick)

    assert calls == ['tick']


def test_maintenance_worker_drains_post_request_maintenance() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    calls: list[str] = []
    server.queue_maintenance_ticks(1)

    def _tick():
        calls.append('tick')
        server._stop_event.set()
        server._maintenance_pending_event.set()

    maintenance_worker_loop(server, interval=999999.0, on_tick=_tick)

    assert calls == ['tick']


def test_maintenance_worker_drains_after_response_actions_without_tick_callback() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    seen: list[str] = []

    def _action() -> None:
        seen.append('done')
        server._stop_event.set()
        server._maintenance_pending_event.set()

    server.queue_after_response_action(_action)

    start_maintenance_worker(server, interval=999999.0, on_tick=None)
    stop_maintenance_worker(server)

    assert seen == ['done']
    assert server.maintenance_pending() is False


def test_maintenance_shutdown_drains_finalizer_queued_after_stop_signal() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    seen: list[str] = []
    server._stop_event.set()
    server.queue_after_response_action(
        lambda: seen.append('done'),
        run_during_shutdown=True,
    )

    start_maintenance_worker(server, interval=999999.0, on_tick=None)
    stop_maintenance_worker(server)

    assert seen == ['done']
    assert server.maintenance_pending() is False


def test_post_request_tick_discards_queued_maintenance_when_on_tick_missing() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    server.queue_maintenance_ticks(2)

    next_tick_at = post_request_tick(
        server=server,
        on_tick=None,
        next_tick_at=999999.0,
        interval=0.2,
    )

    assert next_tick_at == 999999.0
    assert server.take_queued_maintenance_ticks() == 0


def test_queue_periodic_maintenance_tick_tracks_one_tick() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    server.queue_periodic_maintenance_tick()

    assert server.maintenance_pending() is True
    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is False


def test_run_tick_if_needed_queues_and_drains_periodic_maintenance() -> None:
    calls: list[str] = []
    server = CcbdSocketServer('/tmp/test.sock')

    next_tick_at = run_tick_if_needed(
        server=server,
        on_tick=lambda: calls.append('tick'),
        next_tick_at=0.0,
        interval=0.2,
    )

    assert calls == ['tick']
    assert next_tick_at > 0.0
    assert server.take_queued_maintenance_ticks() == 0
    assert server.maintenance_pending() is False


def test_run_tick_if_needed_defers_periodic_tick_when_request_backlog_exists() -> None:
    calls: list[str] = []
    server = CcbdSocketServer('/tmp/test.sock')
    server._connection_queue.put_nowait((object(), 0.0))

    next_tick_at = run_tick_if_needed(
        server=server,
        on_tick=lambda: calls.append('tick'),
        next_tick_at=0.0,
        interval=0.2,
    )

    assert calls == []
    assert next_tick_at > 0.0
    assert server.take_queued_maintenance_ticks() == 0


def test_run_queued_maintenance_ticks_runs_requested_count() -> None:
    calls: list[str] = []

    run_queued_maintenance_ticks(on_tick=lambda: calls.append('tick'), tick_count=3)

    assert calls == ['tick', 'tick', 'tick']


def test_maintenance_pending_reflects_manual_queue_and_drain() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    assert server.maintenance_pending() is False
    server.queue_maintenance_ticks(2)
    assert server.maintenance_pending() is True
    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is False


def test_queue_maintenance_ticks_coalesces_multiple_dirty_signals() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    server.queue_maintenance_ticks(1)
    server.queue_maintenance_ticks(1)
    server.queue_maintenance_ticks(3)

    assert server.maintenance_pending() is True
    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is False


def test_queue_after_response_action_marks_maintenance_pending() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    seen: list[str] = []

    server.queue_after_response_action(lambda: seen.append('done'))

    assert server.maintenance_pending() is True
    run_after_response_actions(server)
    assert seen == ['done']
    assert server.maintenance_pending() is False


def test_take_pending_maintenance_ticks_preserves_after_response_pending() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    seen: list[str] = []

    server.queue_maintenance_ticks(1)
    server.queue_after_response_action(lambda: seen.append('done'))

    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is True
    run_after_response_actions(server)
    assert seen == ['done']
    assert server.maintenance_pending() is False


def test_pop_after_response_actions_preserves_pending_maintenance_tick() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    server.queue_maintenance_ticks(1)
    server.queue_after_response_action(lambda: None)

    actions = server.pop_after_response_actions()

    assert len(actions) == 1
    assert server.maintenance_pending() is True
    assert server.take_pending_maintenance_ticks() == 1
    assert server.maintenance_pending() is False


def test_next_worker_timeout_returns_immediate_when_maintenance_pending() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    server.queue_maintenance_ticks(1)

    timeout = next_worker_timeout(server=server, next_tick_at=999999.0, on_tick=lambda: None)

    assert timeout == 0.0


def test_next_worker_timeout_matches_base_timeout_without_pending_maintenance() -> None:
    server = CcbdSocketServer('/tmp/test.sock')

    worker_timeout = next_worker_timeout(server=server, next_tick_at=999999.0, on_tick=lambda: None)
    base_timeout = next_timeout(next_tick_at=999999.0, on_tick=lambda: None)

    assert worker_timeout == pytest.approx(base_timeout)


def test_shutdown_style_handler_contract_allows_after_response_finalize() -> None:
    order: list[str] = []

    class _Conn:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self._recv_count = 0

        def settimeout(self, timeout):
            del timeout

        def recv(self, size):
            del size
            self._recv_count += 1
            if self._recv_count == 1:
                return b'{"api_version":2,"op":"shutdown","request":{}}\n'
            return b''

        def sendall(self, data: bytes) -> None:
            order.append('sendall')
            self.writes.append(data)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    server = CcbdSocketServer('/tmp/test.sock')

    def _handler(_payload):
        order.append('handler')
        return {'state': 'unmounted'}, lambda: order.append('finalize')

    server.register_handler('shutdown', _handler)
    handled = server._handle_connection(_Conn())

    assert handled == 'shutdown'
    assert order == ['handler', 'sendall']
    actions = server.pop_after_response_actions()
    assert len(actions) == 1
    actions[0]()
    assert order == ['handler', 'sendall', 'finalize']


def test_stop_all_style_handler_contract_allows_after_response_finalize() -> None:
    order: list[str] = []

    class _Conn:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self._recv_count = 0

        def settimeout(self, timeout):
            del timeout

        def recv(self, size):
            del size
            self._recv_count += 1
            if self._recv_count == 1:
                return b'{"api_version":2,"op":"stop-all","request":{"force":false}}\n'
            return b''

        def sendall(self, data: bytes) -> None:
            order.append('sendall')
            self.writes.append(data)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    server = CcbdSocketServer('/tmp/test.sock')

    def _handler(payload):
        order.append('handler')
        assert payload == {'force': False}
        return {'state': 'unmounted'}, lambda: order.append('finalize')

    server.register_handler('stop-all', _handler)
    handled = server._handle_connection(_Conn())

    assert handled == 'stop-all'
    assert order == ['handler', 'sendall']
    actions = server.pop_after_response_actions()
    assert len(actions) == 1
    actions[0]()
    assert order == ['handler', 'sendall', 'finalize']


def test_stop_all_after_response_finalize_is_queued_when_response_write_fails() -> None:
    order: list[str] = []

    class _Conn:
        def __init__(self) -> None:
            self._recv_count = 0

        def settimeout(self, timeout):
            del timeout

        def recv(self, size):
            del size
            self._recv_count += 1
            if self._recv_count == 1:
                return b'{"api_version":2,"op":"stop-all","request":{"force":true}}\n'
            return b''

        def sendall(self, data: bytes) -> None:
            del data
            order.append('sendall_failed')
            raise OSError('client disconnected')

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    server = CcbdSocketServer('/tmp/test.sock')

    def _handler(payload):
        order.append('handler')
        assert payload == {'force': True}
        return {'state': 'unmounted'}, lambda: order.append('finalize')

    server.register_handler('stop-all', _handler)
    handled = server._handle_connection(_Conn())

    assert handled == 'stop-all'
    assert order == ['handler', 'sendall_failed']
    server._stop_event.set()
    run_after_response_actions(server, shutdown_only=True)
    assert order == ['handler', 'sendall_failed', 'finalize']


def test_stop_all_destructive_finalize_runs_after_response_write() -> None:
    order: list[str] = []

    class _Conn:
        def __init__(self) -> None:
            self._recv_count = 0

        def settimeout(self, timeout):
            del timeout

        def recv(self, size):
            del size
            self._recv_count += 1
            if self._recv_count == 1:
                return b'{"api_version":2,"op":"stop-all","request":{"force":false}}\n'
            return b''

        def sendall(self, data: bytes) -> None:
            del data
            order.append('sendall')

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    server = CcbdSocketServer('/tmp/test.sock')

    def _handler(payload):
        order.append('prepare')
        assert payload == {'force': False}
        return {'state': 'unmounted'}, lambda: order.append('destroy_namespace')

    server.register_handler('stop-all', _handler)
    handled = server._handle_connection(_Conn())

    assert handled == 'stop-all'
    assert order == ['prepare', 'sendall']

    run_after_response_actions(server)

    assert order == ['prepare', 'sendall', 'destroy_namespace']


def test_run_after_response_actions_drains_all_actions_once() -> None:
    server = CcbdSocketServer('/tmp/test.sock')
    seen: list[str] = []
    server.queue_after_response_action(lambda: seen.append('a'))
    server.queue_after_response_action(lambda: seen.append('b'))

    run_after_response_actions(server)

    assert seen == ['a', 'b']
    assert server.pop_after_response_actions() == ()
