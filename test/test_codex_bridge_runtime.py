from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from provider_backends.codex.bridge_runtime.service import DualBridge
from provider_backends.codex.launcher_runtime.bridge import validate_bridge_bootstrap
from provider_backends.codex.launcher_runtime.runtime_state import prepare_runtime
from provider_core.transport import endpoint_for_fifo_path


class _FakeTracker:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _FakeSession:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, content: str) -> None:
        self.sent.append(content)


class _FakeReconnectAutostart:
    def __init__(self) -> None:
        self.arm_attempts = 0
        self.stop_attempts = 0

    def maybe_arm(self) -> bool:
        self.arm_attempts += 1
        return False

    def stop(self) -> None:
        self.stop_attempts += 1


def test_dual_bridge_processes_request_and_records_history(tmp_path: Path, monkeypatch) -> None:
    tracker = _FakeTracker()
    session = _FakeSession()
    monkeypatch.setenv('CODEX_TMUX_SESSION', '%7')
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.CodexBindingTracker',
        lambda runtime_dir: tracker,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.TerminalCodexSession',
        lambda pane_id: session,
    )
    runtime_dir = tmp_path / 'runtime'
    prepare_runtime(runtime_dir)
    bridge = DualBridge(runtime_dir)
    writer_errors: list[BaseException] = []

    def write_request() -> None:
        try:
            bridge._runtime.fifo_reader.send_line(
                json.dumps({'content': 'hello', 'marker': 'mk-1'})
            )
        except BaseException as exc:
            writer_errors.append(exc)

    writer = threading.Thread(target=write_request)
    writer.start()

    payload = bridge._read_request(timeout=2.0)
    writer.join(timeout=2.0)

    assert not writer.is_alive()
    assert writer_errors == []
    assert payload == {'content': 'hello', 'marker': 'mk-1'}
    bridge._process_request(payload)
    assert session.sent == ['hello']
    history = bridge.history_file.read_text(encoding='utf-8')
    assert '"role": "claude"' in history
    assert '"marker": "mk-1"' in history
    assert 'hello' in history
    assert 'mk-1' in bridge.bridge_log.read_text(encoding='utf-8')


def test_dual_bridge_handles_session_send_failure(tmp_path: Path, monkeypatch) -> None:
    tracker = _FakeTracker()

    class _FailingSession:
        def send(self, content: str) -> None:
            raise RuntimeError(f'boom:{content}')

    monkeypatch.setenv('CODEX_TMUX_SESSION', '%8')
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.CodexBindingTracker',
        lambda runtime_dir: tracker,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.TerminalCodexSession',
        lambda pane_id: _FailingSession(),
    )
    bridge = DualBridge(tmp_path / 'runtime')

    bridge._process_request({'content': 'fail-me', 'marker': 'mk-2'})

    history_lines = bridge.history_file.read_text(encoding='utf-8').splitlines()
    assert len(history_lines) == 2
    first = json.loads(history_lines[0])
    second = json.loads(history_lines[1])
    assert first['role'] == 'claude'
    assert second['role'] == 'codex'
    assert second['content'] == 'Failed to send to Codex: boom:fail-me'


def test_validate_bridge_bootstrap_accepts_platform_endpoint(tmp_path: Path) -> None:
    runtime_dir = tmp_path / 'runtime'
    prepare_runtime(runtime_dir)
    (runtime_dir / 'bridge.pid').write_text('9911\n', encoding='utf-8')
    endpoint = endpoint_for_fifo_path(runtime_dir / 'input.fifo')
    if hasattr(os, 'mkfifo'):
        assert endpoint.exists() is True
    else:
        assert endpoint.is_dir() is True

    validate_bridge_bootstrap(runtime_dir)


def test_dual_bridge_defaults_to_event_wait_instead_of_hot_idle_poll(tmp_path: Path, monkeypatch) -> None:
    tracker = _FakeTracker()
    session = _FakeSession()
    observed_timeouts: list[float] = []
    monkeypatch.delenv('CCB_BRIDGE_IDLE_SLEEP', raising=False)
    monkeypatch.setenv('CODEX_TMUX_SESSION', '%9')
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.CodexBindingTracker',
        lambda runtime_dir: tracker,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.TerminalCodexSession',
        lambda pane_id: session,
    )
    bridge = DualBridge(tmp_path / 'runtime')

    def fake_read_request(*, timeout: float = 0.0):
        observed_timeouts.append(timeout)
        bridge._running = False
        return None

    monkeypatch.setattr(bridge, '_read_request', fake_read_request)

    assert bridge.run() == 0

    assert observed_timeouts == [1.0]
    assert tracker.started == 1
    assert tracker.stopped >= 1


def test_dual_bridge_respects_explicit_idle_sleep_override(tmp_path: Path, monkeypatch) -> None:
    tracker = _FakeTracker()
    session = _FakeSession()
    observed_timeouts: list[float] = []
    monkeypatch.setenv('CCB_BRIDGE_IDLE_SLEEP', '0.05')
    monkeypatch.setenv('CODEX_TMUX_SESSION', '%10')
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.CodexBindingTracker',
        lambda runtime_dir: tracker,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.TerminalCodexSession',
        lambda pane_id: session,
    )
    bridge = DualBridge(tmp_path / 'runtime')

    def fake_read_request(*, timeout: float = 0.0):
        observed_timeouts.append(timeout)
        bridge._running = False
        return None

    monkeypatch.setattr(bridge, '_read_request', fake_read_request)

    assert bridge.run() == 0

    assert observed_timeouts == [0.05]


def test_dual_bridge_runs_reconnect_autostart_and_shutdown(tmp_path: Path, monkeypatch) -> None:
    tracker = _FakeTracker()
    session = _FakeSession()
    reconnect = _FakeReconnectAutostart()
    monkeypatch.setenv('CODEX_TMUX_SESSION', '%11')
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.CodexBindingTracker',
        lambda runtime_dir: tracker,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.runtime_state.TerminalCodexSession',
        lambda pane_id: session,
    )
    monkeypatch.setattr(
        'provider_backends.codex.bridge_runtime.service.CodexReconnectAutostart',
        lambda runtime_dir, log: reconnect,
    )
    bridge = DualBridge(tmp_path / 'runtime')

    def fake_read_request(*, timeout: float = 0.0):
        del timeout
        bridge._running = False
        return None

    monkeypatch.setattr(bridge, '_read_request', fake_read_request)

    assert bridge.run() == 0
    assert reconnect.arm_attempts == 1
    assert reconnect.stop_attempts == 1
