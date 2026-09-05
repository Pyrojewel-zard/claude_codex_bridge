from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ccbd.models import CcbdStartupAgentResult, CcbdStartupReport
from ccbd.start_preparation import PreparedStartAgent, _prepare_provider_launch_set
from ccbd.supervisor_runtime.reporting import record_startup_report
from cli.services.tmux_project_cleanup_runtime.cleanup import cleanup_project_tmux_orphans_by_socket
from runtime_observability import (
    collect_startup_operations,
    record_startup_operation,
    startup_operation_counts,
    startup_operation_scope,
)
from provider_backends.claude.launcher_runtime.history import latest_session_id_for_candidates
from provider_backends.codex.launcher_runtime.session_paths import (
    load_resume_session_id,
    read_session_payload,
)
from storage.atomic import atomic_write_text, atomic_write_text_if_changed
from terminal_runtime import TmuxBackend


def _startup_report(**overrides) -> CcbdStartupReport:
    fields = {
        'project_id': 'project-1',
        'generated_at': '2026-07-16T00:00:00Z',
        'trigger': 'start_command',
        'status': 'ok',
        'requested_agents': ('demo',),
        'desired_agents': ('demo',),
        'restore_requested': False,
        'auto_permission': False,
    }
    fields.update(overrides)
    return CcbdStartupReport(**fields)


def test_startup_operation_collector_is_nested_and_request_scoped() -> None:
    assert startup_operation_counts() == {}
    with collect_startup_operations() as outer:
        record_startup_operation('tmux_backend_command_count')
        with collect_startup_operations() as inner:
            assert inner is outer
            record_startup_operation('tmux_backend_command_count', 2)
        assert outer.snapshot() == {'tmux_backend_command_count': 3}
    assert startup_operation_counts() == {}


def test_startup_operation_collector_resets_after_failure() -> None:
    with pytest.raises(RuntimeError, match='boom'):
        with collect_startup_operations():
            record_startup_operation('tmux_backend_command_count')
            raise RuntimeError('boom')
    assert startup_operation_counts() == {}


def test_atomic_startup_counts_distinguish_write_skip_and_provider_prepare_scope(tmp_path: Path) -> None:
    target = tmp_path / 'state.json'
    with collect_startup_operations() as collector:
        with startup_operation_scope('provider_prepare'):
            atomic_write_text(target, 'hello')
            assert atomic_write_text_if_changed(target, 'hello') is False

    assert collector.snapshot() == {
        'atomic_durable_read_byte_count': 5,
        'atomic_durable_read_count': 1,
        'atomic_durable_write_attempt_count': 1,
        'atomic_durable_write_byte_count': 5,
        'atomic_durable_write_count': 1,
        'atomic_durable_write_skip_byte_count': 5,
        'atomic_durable_write_skip_count': 1,
        'provider_prepare_atomic_read_byte_count': 5,
        'provider_prepare_atomic_read_count': 1,
        'provider_prepare_atomic_write_byte_count': 5,
        'provider_prepare_atomic_write_count': 1,
        'provider_prepare_atomic_write_skip_byte_count': 5,
        'provider_prepare_atomic_write_skip_count': 1,
    }


def test_session_history_counters_classify_payload_and_absent_binding(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    runtime_dir = ccb_dir / 'agents' / 'demo' / 'runtime'
    runtime_dir.mkdir(parents=True)
    session_path = ccb_dir / '.codex-demo-session'
    payload = '{"codex_session_id":"sid-1"}'
    session_path.write_text(payload, encoding='utf-8')

    with collect_startup_operations() as collector:
        assert read_session_payload(session_path) == {'codex_session_id': 'sid-1'}
        assert load_resume_session_id(SimpleNamespace(name='missing'), runtime_dir) is None

    assert collector.snapshot() == {
        'session_decision_no_binding_count': 1,
        'session_history_binding_path_probe_count': 1,
        'session_history_payload_parse_attempt_count': 1,
        'session_history_payload_parse_count': 1,
        'session_history_payload_read_attempt_count': 1,
        'session_history_payload_read_byte_count': len(payload.encode('utf-8')),
        'session_history_payload_read_count': 1,
    }


def test_session_history_counters_classify_parse_failure_and_claude_absence(tmp_path: Path) -> None:
    malformed = tmp_path / 'malformed-session.json'
    malformed.write_text('{', encoding='utf-8')
    missing_project = tmp_path / 'missing-project'
    home_dir = tmp_path / 'home'

    with collect_startup_operations() as collector:
        assert read_session_payload(malformed) is None
        assert latest_session_id_for_candidates(
            candidates=[missing_project],
            home_dir=home_dir,
            project_binding_fn=lambda work_dir: (home_dir / 'projects' / 'missing', work_dir),
        ) == (None, False, None)

    assert collector.snapshot() == {
        'session_history_directory_absent_count': 1,
        'session_history_directory_probe_count': 1,
        'session_history_payload_parse_attempt_count': 1,
        'session_history_payload_parse_failure_count': 1,
        'session_history_payload_read_attempt_count': 1,
        'session_history_payload_read_byte_count': 1,
        'session_history_payload_read_count': 1,
    }


def test_tmux_counts_only_proven_subprocess_spawns_on_success_and_failure(monkeypatch) -> None:
    outcomes = iter(
        (
            subprocess.CompletedProcess(['tmux'], 0),
            subprocess.CalledProcessError(1, ['tmux']),
            FileNotFoundError('tmux missing'),
        )
    )

    def fake_run(*_args, **_kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr('terminal_runtime.tmux_backend._run', fake_run)
    monkeypatch.setattr('terminal_runtime.tmux_backend._isolated_tmux_env', lambda: {})
    backend = TmuxBackend()

    with collect_startup_operations() as collector:
        backend._tmux_run(['list-panes'])
        with pytest.raises(subprocess.CalledProcessError):
            backend._tmux_run(['has-session'], check=True)
        with pytest.raises(FileNotFoundError):
            backend._tmux_run(['display-message'])

    assert collector.snapshot() == {
        'tmux_backend_command_attempt_count': 3,
        'tmux_backend_command_count': 2,
        'tmux_backend_subprocess_spawn_count': 2,
        'tracked_startup_subprocess_spawn_attempt_count': 3,
        'tracked_startup_subprocess_spawn_count': 2,
    }


def test_provider_prepare_counts_attempt_completion_and_scoped_atomic_writes(tmp_path: Path, monkeypatch) -> None:
    item = PreparedStartAgent(
        agent_name='demo',
        spec=SimpleNamespace(name='demo', provider='codex'),
        plan=SimpleNamespace(workspace_path=tmp_path),
        window_name=None,
        raw_binding=None,
        binding=None,
        stale_binding=False,
    )
    runtime_dir = tmp_path / 'runtime'
    paths = SimpleNamespace(agent_provider_runtime_dir=lambda *_args: runtime_dir)
    context = SimpleNamespace(command=SimpleNamespace(auto_permission=False))
    monkeypatch.setattr(
        'ccbd.start_preparation.provider_workspace_path_for_prepare',
        lambda **_kwargs: tmp_path,
    )

    def prepare_provider_workspace(**_kwargs) -> None:
        atomic_write_text(runtime_dir / 'profile.json', '{}\n')

    monkeypatch.setattr('ccbd.start_preparation.prepare_provider_workspace', prepare_provider_workspace)

    with collect_startup_operations() as collector:
        prepared = _prepare_provider_launch_set((item,), paths=paths, context=context)

    assert prepared[0].provider_prepared is True
    assert collector.snapshot() == {
        'atomic_durable_write_attempt_count': 1,
        'atomic_durable_write_byte_count': 3,
        'atomic_durable_write_count': 1,
        'provider_prepare_atomic_write_byte_count': 3,
        'provider_prepare_atomic_write_count': 1,
        'provider_prepare_attempt_count': 1,
        'provider_prepare_count': 1,
    }


def test_orphan_cleanup_counts_scans_and_observed_panes() -> None:
    killed: list[str] = []

    class FakeBackend:
        def __init__(self, **_kwargs) -> None:
            pass

        def list_panes_by_user_options(self, _options):
            return ('%1', '%2')

        def kill_tmux_pane(self, pane_id: str) -> None:
            killed.append(pane_id)

    with collect_startup_operations() as collector:
        summaries = cleanup_project_tmux_orphans_by_socket(
            project_id='project-1',
            active_panes_by_socket={'socket-a': ('%1',)},
            backend_factory=FakeBackend,
            tmux_available_fn=lambda _name: '/usr/bin/tmux',
            current_pane_id=None,
        )

    assert len(summaries) == 2
    assert killed == ['%2', '%1', '%2']
    assert collector.snapshot() == {
        'orphan_cleanup_killed_pane_count': 3,
        'orphan_cleanup_orphan_pane_count': 3,
        'orphan_cleanup_owned_pane_count': 4,
        'orphan_cleanup_socket_scan_count': 2,
    }


def test_failed_startup_report_retains_request_operation_snapshot_and_excludes_own_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: list[CcbdStartupReport] = []
    report_path = tmp_path / 'startup-report.json'

    def save_report(report: CcbdStartupReport) -> None:
        captured.append(report)
        atomic_write_text(report_path, 'persisted\n')

    inspection = SimpleNamespace(generation=7, to_record=lambda: {'generation': 7})
    supervisor = SimpleNamespace(
        _project_id='project-1',
        _clock=lambda: '2026-07-16T00:00:00Z',
        _ownership_guard=SimpleNamespace(inspect=lambda: inspection),
        _config=SimpleNamespace(agents={'demo': object()}),
        _config_identity={'config_signature': 'sig-1'},
        _paths=SimpleNamespace(
            runtime_state_payload=lambda: {},
            ccbd_socket_placement=None,
            ccbd_tmux_socket_placement=None,
        ),
        _startup_report_store=SimpleNamespace(save=save_report),
    )
    monkeypatch.setattr(
        'ccbd.supervisor_runtime.reporting.socket_placement_payload',
        lambda _placement, prefix=None: {},
    )

    with collect_startup_operations() as collector:
        record_startup_operation('tmux_backend_command_count', 2)
        record_startup_report(
            supervisor,
            requested_agents=('demo',),
            restore=False,
            auto_permission=False,
            status='failed',
            actions_taken=('start_flow_failed',),
            cleanup_summaries=(),
            agent_results=(),
            failure_reason='boom',
        )

    assert len(captured) == 1
    assert captured[0].status == 'failed'
    assert captured[0].operation_counts == {
        'startup_report_write_attempt_count': 1,
        'tmux_backend_command_count': 2,
    }
    assert collector.snapshot()['atomic_durable_write_count'] == 1
    assert 'atomic_durable_write_count' not in captured[0].operation_counts


def test_startup_report_operation_counts_are_backward_compatible_and_sanitized() -> None:
    legacy = _startup_report().to_record()
    legacy.pop('operation_counts')
    assert CcbdStartupReport.from_record(legacy).operation_counts == {}

    record = _startup_report().to_record()
    record['operation_counts'] = {
        'valid_count': '2',
        'fractional': 1.5,
        'negative': -1,
        'boolean': True,
        'infinite': float('inf'),
        '': 3,
    }
    restored = CcbdStartupReport.from_record(record)
    assert restored.operation_counts == {'valid_count': 2}
    assert restored.summary_fields()['startup_last_operation_counts'] == {'valid_count': 2}


def test_startup_agent_readiness_evidence_marks_native_id_pending_without_exposing_it() -> None:
    report = _startup_report(
        agent_results=(
            CcbdStartupAgentResult(
                agent_name='demo',
                provider='codex',
                action='launched',
                health='healthy',
                workspace_path='/workspace',
                input_readiness_status='not_observed_at_startup',
                native_session_id_status='pending',
            ),
        ),
    )

    record = report.to_record()
    agent = record['agent_results'][0]
    assert agent['input_readiness_status'] == 'not_observed_at_startup'
    assert agent['native_session_id_status'] == 'pending'
    assert 'native_session_id' not in agent
    restored = CcbdStartupReport.from_record(record)
    assert restored.agent_results[0].native_session_id_status == 'pending'
