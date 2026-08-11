from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import cli.services.start_foreground as start_foreground_service
from ccbd.socket_client import CcbdClientError
from cli.context import CliContextBuilder
from cli.models import ParsedStartCommand
from cli.services.start_foreground import ForegroundAttachError, ForegroundAttachSummary, attach_started_project_namespace
from project.resolver import bootstrap_project


@pytest.fixture(autouse=True)
def _clear_tmux_config_env(monkeypatch) -> None:
    monkeypatch.delenv('CCB_TMUX_CONFIG', raising=False)


def _context(project_root: Path):
    command = ParsedStartCommand(project=None, agent_names=(), restore=True, auto_permission=True)
    return CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)


def _assert_call_subsequence(actual: list[list[str]], expected: list[list[str]]) -> None:
    index = 0
    for call in actual:
        if call == expected[index]:
            index += 1
            if index == len(expected):
                return
    raise AssertionError(f'expected call subsequence {expected!r}; actual={actual!r}')


def _tmux_cmd(context, *args: str) -> list[str]:
    return ['tmux', '-f', '/dev/null', '-S', str(context.paths.ccbd_tmux_socket_path), *args]


def test_foreground_attach_summary_exposes_restore_token_presence_only() -> None:
    summary = ForegroundAttachSummary(
        project_id='proj-herdr',
        tmux_socket_path='',
        tmux_session_name='ccb-herdr',
        backend_impl='herdr',
        namespace_id='workspace-1',
        session_name='ccb-herdr',
        ipc_kind='herdr_socket',
        ipc_ref='herdr://ccb-herdr',
        namespace_restore_token_present=True,
    )

    assert summary.backend_impl == 'herdr'
    assert summary.namespace_restore_token_present is True
    assert not hasattr(summary, 'namespace_restore_token')
    assert 'ccb-herdr::workspace-1' not in str(summary)


def test_start_foreground_herdr_attach_uses_builder_without_tmux_binary(monkeypatch) -> None:
    context = SimpleNamespace(project=SimpleNamespace(project_id='proj-herdr'))
    payload = {
        'namespace_backend_family': 'herdr-native',
        'namespace_backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'namespace_session_name': 'ccb-herdr',
        'namespace_ipc_kind': 'herdr_socket',
        'namespace_ipc_ref': 'herdr://workspace-1',
        'namespace_restore_token_present': True,
        'namespace_workspace_window_name': 'main',
        'namespace_ui_attachable': True,
    }
    builder_calls: list[dict[str, object]] = []
    attach_calls: list[tuple[dict[str, object], str | None]] = []

    class _FakeClient:
        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return payload

    class _FakeHerdrAttachBackend:
        def attach_namespace(self, namespace_ref: dict[str, object], *, window_name: str | None = None) -> None:
            attach_calls.append((dict(namespace_ref), window_name))

    def _build_herdr_attach_backend(*, namespace_ref, backend_selection):
        builder_calls.append(
            {
                'namespace_ref': dict(namespace_ref),
                'backend_selection': dict(backend_selection),
            }
        )
        return _FakeHerdrAttachBackend()

    monkeypatch.setattr(start_foreground_service, '_foreground_attach_client', lambda _context: _FakeClient())
    monkeypatch.setattr(start_foreground_service, '_attach_env', lambda: {})
    monkeypatch.setattr(
        start_foreground_service.shutil,
        'which',
        lambda _name: (_ for _ in ()).throw(AssertionError('tmux should not be queried')),
    )
    monkeypatch.setattr(
        start_foreground_service.subprocess,
        'Popen',
        lambda *_, **__: (_ for _ in ()).throw(AssertionError('tmux subprocess should not run')),
    )
    monkeypatch.setattr(start_foreground_service, '_launch_herdr_ui', lambda _namespace_ref: None)
    monkeypatch.setattr(start_foreground_service, '_build_herdr_attach_backend', _build_herdr_attach_backend)

    summary = attach_started_project_namespace(context)  # type: ignore[arg-type]

    assert summary.backend_impl == 'herdr'
    assert summary.namespace_id == 'workspace-1'
    assert summary.session_name == 'ccb-herdr'
    assert summary.ipc_kind == 'herdr_socket'
    assert summary.namespace_restore_token_present is True
    assert builder_calls == [
        {
            'namespace_ref': {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'namespace_id': 'workspace-1',
                'session_name': 'ccb-herdr',
                'ipc_kind': 'herdr_socket',
                'ipc_ref': 'herdr://workspace-1',
                'restore_token': None,
            },
            'backend_selection': {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'ipc_kind': 'herdr_socket',
                'ipc_ref_present': True,
                'namespace_restore_token_present': True,
            },
        }
    ]
    assert attach_calls == [
        (
            {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'namespace_id': 'workspace-1',
                'session_name': 'ccb-herdr',
                'ipc_kind': 'herdr_socket',
                'ipc_ref': 'herdr://workspace-1',
                'restore_token': None,
            },
            'main',
        )
    ]
    assert 'restore-token' not in str(builder_calls)


def test_start_foreground_herdr_attach_real_builder_accepts_matching_backend_ref(monkeypatch) -> None:
    context = SimpleNamespace(project=SimpleNamespace(project_id='proj-herdr'))
    payload = {
        'namespace_backend_family': 'herdr-native',
        'namespace_backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'namespace_session_name': 'ccb-herdr',
        'namespace_ipc_kind': 'herdr_socket',
        'namespace_ipc_ref': 'herdr://workspace-1',
        'namespace_restore_token_present': True,
        'namespace_workspace_window_name': 'main',
        'namespace_ui_attachable': True,
    }
    attach_calls: list[tuple[dict[str, object], str | None]] = []

    class _FakeClient:
        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return payload

    backend_calls: list[object] = []

    class _MatchingHerdrBackend:
        def namespace_ref(self, session_name: str, namespace_id: str) -> dict[str, object]:
            return {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'namespace_id': namespace_id,
                'session_name': session_name,
                'ipc_kind': 'herdr_socket',
                'ipc_ref': 'herdr://workspace-1',
                'restore_token': None,
            }

        def attach_namespace(self, namespace_ref: dict[str, object], *, window_name: str | None = None) -> None:
            attach_calls.append((dict(namespace_ref), window_name))

    monkeypatch.setattr(start_foreground_service, '_foreground_attach_client', lambda _context: _FakeClient())
    monkeypatch.setattr(start_foreground_service, '_attach_env', lambda: {})
    monkeypatch.setattr(
        start_foreground_service.shutil,
        'which',
        lambda _name: (_ for _ in ()).throw(AssertionError('tmux should not be queried')),
    )
    monkeypatch.setattr(
        start_foreground_service.subprocess,
        'Popen',
        lambda *_, **__: (_ for _ in ()).throw(AssertionError('tmux subprocess should not run')),
    )
    monkeypatch.setattr(start_foreground_service, '_launch_herdr_ui', lambda _namespace_ref: None)
    monkeypatch.setattr(
        'terminal_runtime.api.get_backend',
        lambda terminal_type=None: backend_calls.append(terminal_type) or _MatchingHerdrBackend(),
    )

    summary = attach_started_project_namespace(context)  # type: ignore[arg-type]

    assert summary.backend_impl == 'herdr'
    assert backend_calls == ['herdr']
    assert attach_calls == [
        (
            {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'namespace_id': 'workspace-1',
                'session_name': 'ccb-herdr',
                'ipc_kind': 'herdr_socket',
                'ipc_ref': 'herdr://workspace-1',
                'restore_token': None,
            },
            'main',
        )
    ]


def test_launch_herdr_ui_hides_windows_control_wrapper(monkeypatch) -> None:
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    class _FakeProcess:
        pid = 1234

    def _fake_popen(args, **kwargs):
        popen_calls.append((list(args), dict(kwargs)))
        return _FakeProcess()

    monkeypatch.setattr(start_foreground_service.sys, 'platform', 'win32')
    monkeypatch.setattr(start_foreground_service.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setenv('CCB_HERDR_EXE', 'C:/Herdr/herdr.exe')
    monkeypatch.setattr(
        start_foreground_service.shutil,
        'which',
        lambda name: 'C:/WezTerm/wezterm.exe' if name == 'wezterm' else None,
    )
    monkeypatch.setattr(start_foreground_service.os, 'getcwd', lambda: 'C:/repo')
    monkeypatch.setattr(start_foreground_service.subprocess, 'Popen', _fake_popen)

    start_foreground_service._launch_herdr_ui({'session_name': 'ccb-proj-abc'})

    assert popen_calls == [
        (
            [
                'C:/WezTerm/wezterm.exe',
                'cli',
                'spawn',
                '--cwd',
                'C:/repo',
                '--',
                'C:/Herdr/herdr.exe',
                'session',
                'attach',
                'ccb-proj-abc',
            ],
            {
                'stdout': start_foreground_service.subprocess.DEVNULL,
                'stderr': start_foreground_service.subprocess.DEVNULL,
                'creationflags': 0x08000000,
            },
        )
    ]


def test_start_foreground_herdr_attach_rejects_missing_payload_without_tmux_fallback(monkeypatch) -> None:
    payload = {
        'namespace_backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'namespace_session_name': 'ccb-herdr',
        'namespace_ipc_kind': 'herdr_socket',
        'namespace_ui_attachable': True,
    }

    ready, error = start_foreground_service._attach_target_ready(payload, env={})

    assert ready is False
    assert 'ipc_ref_present=False' in error


def test_start_foreground_herdr_attach_blocked_error_includes_projection() -> None:
    payload = {
        'namespace_backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'namespace_session_name': 'ccb-herdr',
        'namespace_ipc_kind': 'herdr_socket',
        'namespace_ipc_ref': 'herdr://workspace-1',
        'namespace_ui_attachable': False,
        'herdr_surface_projection': {
            'backend_impl': 'herdr',
            'capability_status': 'blocked',
            'support_tier_projection': 'experimental',
            'support_tier_projection_source': 'validation_pending',
            'beta_gaps': ['foreground-attach-validation-pending'],
            'blocking_gaps': ['attach_unsupported'],
            'degraded_next_action': 'collect-validation-transcript',
            'evidence_refs': {},
        },
    }

    ready, error = start_foreground_service._attach_target_ready(payload, env={})

    assert ready is False
    assert 'capability_status=blocked' in error
    assert 'beta_gaps=foreground-attach-validation-pending' in error
    assert 'blocking_gaps=attach_unsupported' in error
    assert 'next_action=collect-validation-transcript' in error


def test_start_foreground_herdr_attach_builder_rejects_backend_ipc_ref_mismatch(monkeypatch) -> None:
    namespace_ref = {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'namespace_id': 'workspace-1',
        'session_name': 'ccb-herdr',
        'ipc_kind': 'herdr_socket',
        'ipc_ref': 'herdr://workspace-1',
        'restore_token': None,
    }
    backend_selection = {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'ipc_kind': 'herdr_socket',
        'ipc_ref_present': True,
        'namespace_restore_token_present': True,
    }

    class _MismatchedHerdrBackend:
        def namespace_ref(self, session_name: str, namespace_id: str) -> dict[str, object]:
            return {
                'backend_family': 'herdr-native',
                'backend_impl': 'herdr',
                'namespace_id': namespace_id,
                'session_name': session_name,
                'ipc_kind': 'herdr_socket',
                'ipc_ref': 'herdr://other-session',
                'restore_token': None,
            }

    monkeypatch.setattr(
        'terminal_runtime.api.get_backend',
        lambda terminal_type=None: _MismatchedHerdrBackend(),
    )

    with pytest.raises(ForegroundAttachError, match='namespace ref mismatch'):
        start_foreground_service._build_herdr_attach_backend(
            namespace_ref=namespace_ref,
            backend_selection=backend_selection,
        )


class _FakeAttachProcess:
    def __init__(self, *, pid: int, returncode: int | None = None):
        self.pid = pid
        self.returncode = returncode
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def wait(self):
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_start_foreground_attaches_to_namespace_tmux_session(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)
    client_timeouts: list[float | None] = []

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s
            client_timeouts.append(timeout_s)

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_backend_impl': 'tmux',
                'namespace_id': context.paths.ccbd_tmux_session_name,
                'namespace_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_ipc_kind': 'socket_path',
                'namespace_ipc_ref': str(context.paths.ccbd_tmux_socket_path),
                'namespace_restore_token_present': False,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

    run_calls: list[list[str]] = []
    attach_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=4242, returncode=0)

    def _run(args, **kwargs):
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='4242\t/dev/pts/55\n')
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='4242\n')
        return subprocess.CompletedProcess(args=args, returncode=0)

    def _popen(args, **kwargs):
        del kwargs
        attach_calls.append(list(args))
        return attach_process

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', _popen)

    summary = attach_started_project_namespace(context)

    assert summary.project_id == context.project.project_id
    assert summary.tmux_socket_path == str(context.paths.ccbd_tmux_socket_path)
    assert summary.tmux_session_name == context.paths.ccbd_tmux_session_name
    assert summary.backend_impl == 'tmux'
    assert summary.namespace_id == context.paths.ccbd_tmux_session_name
    assert summary.session_name == context.paths.ccbd_tmux_session_name
    assert summary.ipc_kind == 'socket_path'
    assert summary.ipc_ref == str(context.paths.ccbd_tmux_socket_path)
    assert summary.namespace_restore_token_present is False
    assert client_timeouts == [start_foreground_service.FOREGROUND_ATTACH_RPC_TIMEOUT_S]
    assert 'CONTROL_PLANE_RPC_TIMEOUT_S' not in start_foreground_service.__dict__
    _assert_call_subsequence(run_calls, [
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}\t#{client_tty}'),
        _tmux_cmd(context, 'refresh-client', '-t', '/dev/pts/55'),
    ])
    assert _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name) in attach_calls
    assert attach_calls.count(
        _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name)
    ) == 1


def test_start_foreground_normalizes_ghostty_term_for_tmux(monkeypatch) -> None:
    monkeypatch.setenv('TERM', 'xterm-ghostty')
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/default,123,0')
    monkeypatch.setenv('TMUX_PANE', '%77')

    env = start_foreground_service._attach_env()

    assert env['TERM'] == 'xterm-256color'
    assert 'TMUX' not in env
    assert 'TMUX_PANE' not in env


def test_start_foreground_waits_for_workspace_window_visibility_before_attach(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach-delayed-window'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s
            self.calls = 0

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            self.calls += 1
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

    run_calls: list[list[str]] = []
    attach_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=4343, returncode=0)
    select_attempts = 0

    def _run(args, **kwargs):
        nonlocal select_attempts
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='4343\t/dev/pts/88\n')
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='4343\n')
        if 'select-window' in call:
            select_attempts += 1
            return subprocess.CompletedProcess(args=args, returncode=0 if select_attempts >= 2 else 1)
        return subprocess.CompletedProcess(args=args, returncode=0)

    def _popen(args, **kwargs):
        del kwargs
        attach_calls.append(list(args))
        return attach_process

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', _popen)
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_POLL_INTERVAL_S', 0.0)

    summary = attach_started_project_namespace(context)

    assert summary.project_id == context.project.project_id
    _assert_call_subsequence(run_calls, [
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}\t#{client_tty}'),
        _tmux_cmd(context, 'refresh-client', '-t', '/dev/pts/88'),
    ])
    assert _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name) in attach_calls
    assert attach_calls.count(
        _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name)
    ) == 1


def test_start_foreground_retries_transient_ccbd_ping_timeouts_before_attach(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-attach-delayed-ping'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s
            self.calls = 0

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            self.calls += 1
            if self.calls < 3:
                raise CcbdClientError('timed out')
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

    client_holder: list[_FakeClient] = []
    run_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=4444, returncode=0)

    def _client(socket_path, *, timeout_s=None):
        client = _FakeClient(socket_path, timeout_s=timeout_s)
        client_holder.append(client)
        return client

    def _run(args, **kwargs):
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='4444\t/dev/pts/44\n')
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='4444\n')
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _client)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', lambda *args, **kwargs: attach_process)
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_POLL_INTERVAL_S', 0.0)

    summary = attach_started_project_namespace(context)

    assert summary.tmux_session_name == context.paths.ccbd_tmux_session_name
    assert len(client_holder) == 1
    assert client_holder[0].calls == 3
    assert any('refresh-client' in call for call in run_calls)


def test_start_foreground_ping_timeout_error_reports_foreground_attach_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'repo-attach-ping-timeout'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)
    current = {'t': 0.0}

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            current['t'] = 0.2
            raise CcbdClientError('timed out')

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.time.monotonic', lambda: current['t'])
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_TIMEOUT_S', 0.1)

    with pytest.raises(
        ForegroundAttachError,
        match=r'foreground attach timed out: ccbd did not respond.*rpc_timeout=.*attempts=1',
    ):
        attach_started_project_namespace(context)


def test_start_foreground_caps_each_attach_ping_to_remaining_ready_budget(monkeypatch) -> None:
    current = {'t': 0.0}

    def _monotonic() -> float:
        return current['t']

    def _sleep(seconds: float) -> None:
        current['t'] += float(seconds)

    class _FakeClient:
        def __init__(self) -> None:
            self.timeouts: list[float] = []
            self.calls = 0

        def with_timeout(self, timeout_s: float):
            self.timeouts.append(timeout_s)
            return self

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            self.calls += 1
            current['t'] += 1.4
            raise CcbdClientError('timed out')

    client = _FakeClient()

    monkeypatch.setattr('cli.services.start_foreground.time.monotonic', _monotonic)
    monkeypatch.setattr('cli.services.start_foreground.time.sleep', _sleep)
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_TIMEOUT_S', 2.0)
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_POLL_INTERVAL_S', 0.0)
    monkeypatch.setattr('cli.services.start_foreground.FOREGROUND_ATTACH_RPC_TIMEOUT_S', 3.0)

    with pytest.raises(ForegroundAttachError, match=r'rpc_timeout=0\.6s'):
        start_foreground_service._wait_for_attach_target(client, env={})

    assert client.calls == 2
    assert client.timeouts[0] == 2.0
    assert 0.5 <= client.timeouts[1] <= 0.7


def test_start_foreground_reports_clean_error_when_session_exits_before_attach(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach-fail'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

    run_calls: list[list[str]] = []
    attach_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=5151, returncode=1)

    def _run(args, **kwargs):
        del kwargs
        call = list(args)
        run_calls.append(call)
        if len(run_calls) in {1, 2}:
            return subprocess.CompletedProcess(args=args, returncode=0)
        if len(run_calls) == 3:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout='')
        if len(run_calls) == 4:
            return subprocess.CompletedProcess(args=args, returncode=1)
        raise AssertionError(f'unexpected subprocess call: {call}')

    def _popen(args, **kwargs):
        del kwargs
        attach_calls.append(list(args))
        return attach_process

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', _popen)

    with pytest.raises(ForegroundAttachError, match='session exited before foreground attach completed'):
        attach_started_project_namespace(context)

    assert run_calls == [
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}'),
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
    ]
    assert attach_calls == [
        _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name)
    ]


def test_start_foreground_keeps_backend_when_session_survives_post_attach_exit(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach-killed-later'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        stop_all_calls = 0

        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

        def stop_all(self, *, force: bool):
            del force
            type(self).stop_all_calls += 1

    run_calls: list[list[str]] = []
    attach_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=6161, returncode=None)

    def _run(args, **kwargs):
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='6161\t/dev/pts/61\n')
            attach_process.returncode = 1
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='6161\n')
        return subprocess.CompletedProcess(args=args, returncode=0)

    def _popen(args, **kwargs):
        del kwargs
        attach_calls.append(list(args))
        return attach_process

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', _popen)

    summary = attach_started_project_namespace(context)

    assert summary.project_id == context.project.project_id
    assert attach_process.wait_calls == 1
    assert run_calls == [
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}\t#{client_tty}'),
        _tmux_cmd(context, 'refresh-client', '-t', '/dev/pts/61'),
    ]
    assert attach_calls == [
        _tmux_cmd(context, 'attach-session', '-t', context.paths.ccbd_tmux_session_name)
    ]
    assert _FakeClient.stop_all_calls == 0


def test_start_foreground_does_not_stop_backend_when_session_disappears_after_attach(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach-server-exited'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        stop_all_calls: list[bool] = []

        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

        def stop_all(self, *, force: bool):
            type(self).stop_all_calls.append(force)

    run_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=7171, returncode=None)

    def _run(args, **kwargs):
        del kwargs
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='7171\t/dev/pts/71\n')
            attach_process.returncode = 1
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='7171\n')
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', lambda *args, **kwargs: attach_process)

    summary = attach_started_project_namespace(context)

    assert summary.project_id == context.project.project_id
    assert _FakeClient.stop_all_calls == []
    assert run_calls == [
        _tmux_cmd(context, 'has-session', '-t', context.paths.ccbd_tmux_session_name),
        _tmux_cmd(context, 'select-window', '-t', f'{context.paths.ccbd_tmux_session_name}:{context.paths.ccbd_tmux_workspace_window_name}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}'),
        _tmux_cmd(context, 'list-clients', '-t', context.paths.ccbd_tmux_session_name, '-F', '#{client_pid}\t#{client_tty}'),
        _tmux_cmd(context, 'refresh-client', '-t', '/dev/pts/71'),
    ]


def test_start_foreground_requires_attachable_namespace(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-not-attachable'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)
    current = {'t': 0.0}

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            current['t'] = 0.2
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': False,
            }

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.time.monotonic', lambda: current['t'])
    monkeypatch.setattr('cli.services.start_foreground._ATTACH_TARGET_READY_TIMEOUT_S', 0.1)

    with pytest.raises(ForegroundAttachError, match='not attachable after successful `ccb` start'):
        attach_started_project_namespace(context)


def test_start_foreground_skips_refresh_when_client_tty_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / 'repo-attach-no-tty'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = _context(project_root)

    class _FakeClient:
        def __init__(self, socket_path, *, timeout_s=None):
            self.socket_path = socket_path
            self.timeout_s = timeout_s

        def ping(self, target: str) -> dict[str, object]:
            assert target == 'ccbd'
            return {
                'namespace_tmux_socket_path': str(context.paths.ccbd_tmux_socket_path),
                'namespace_tmux_session_name': context.paths.ccbd_tmux_session_name,
                'namespace_workspace_window_name': context.paths.ccbd_tmux_workspace_window_name,
                'namespace_ui_attachable': True,
            }

    run_calls: list[list[str]] = []
    attach_process = _FakeAttachProcess(pid=7171, returncode=0)

    def _run(args, **kwargs):
        call = list(args)
        run_calls.append(call)
        if 'list-clients' in call:
            if call[-1] == '#{client_pid}\t#{client_tty}':
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='7171\t\n')
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='7171\n')
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr('cli.services.start_foreground.shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('cli.services.start_foreground.CcbdClient', _FakeClient)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.run', _run)
    monkeypatch.setattr('cli.services.start_foreground.subprocess.Popen', lambda *args, **kwargs: attach_process)

    attach_started_project_namespace(context)

    assert not any('refresh-client' in call for call in run_calls)
