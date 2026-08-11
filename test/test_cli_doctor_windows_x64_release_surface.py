from __future__ import annotations

from pathlib import Path

from cli.context import CliContextBuilder
from cli.models import ParsedDoctorCommand
from cli.render_runtime.ops_views_doctor import render_doctor
from cli.services import doctor as doctor_service
from cli.services.daemon_runtime.models import LocalPingSummary
from project.resolver import bootstrap_project
from terminal_runtime.windows_x64_release_surface import default_blocked_projection


def _local_ping(context) -> LocalPingSummary:
    return LocalPingSummary(
        project_id=context.project.project_id,
        mount_state='unmounted',
        desired_state='stopped',
        health='unknown',
        generation=0,
        project_anchor_path=str(context.paths.ccb_dir),
        runtime_state_root=str(context.paths.runtime_state_root),
        runtime_root_kind=context.paths.runtime_state_placement.root_kind,
        runtime_relocation_reason=context.paths.runtime_state_placement.relocation_reason,
        runtime_filesystem_hint=context.paths.runtime_state_placement.filesystem_hint,
        runtime_marker_status=context.paths.runtime_marker_status,
        socket_path=str(context.paths.ccbd_socket_path),
        preferred_socket_path=str(context.paths.ccbd_socket_placement.preferred_path),
        effective_socket_path=str(context.paths.ccbd_socket_placement.effective_path),
        socket_root_kind=context.paths.ccbd_socket_placement.root_kind,
        socket_fallback_reason=context.paths.ccbd_socket_placement.fallback_reason,
        socket_filesystem_hint=context.paths.ccbd_socket_placement.filesystem_hint,
        tmux_socket_path=str(context.paths.ccbd_tmux_socket_path),
        tmux_preferred_socket_path=str(context.paths.ccbd_tmux_socket_placement.preferred_path),
        tmux_effective_socket_path=str(context.paths.ccbd_tmux_socket_placement.effective_path),
        tmux_socket_root_kind=context.paths.ccbd_tmux_socket_placement.root_kind,
        tmux_socket_fallback_reason=context.paths.ccbd_tmux_socket_placement.fallback_reason,
        tmux_socket_filesystem_hint=context.paths.ccbd_tmux_socket_placement.filesystem_hint,
        last_heartbeat_at=None,
        pid_alive=False,
        socket_connectable=False,
        heartbeat_fresh=False,
        takeover_allowed=True,
        reason='not_started',
    )


def _minimal_doctor_payload(projection: dict[str, object]) -> dict[str, object]:
    return {
        'project': '/tmp/repo',
        'project_id': 'proj-1',
        'installation': {},
        'entrypoint': {},
        'runtime': {},
        'requirements': {},
        'windows_x64_release_surface': projection,
        'ccbd': {
            'state': 'unmounted',
            'health': 'unknown',
            'generation': 0,
            'last_heartbeat_at': None,
            'pid_alive': False,
            'socket_connectable': False,
            'heartbeat_fresh': False,
            'takeover_allowed': True,
            'reason': 'not_started',
            'active_execution_count': 0,
            'recoverable_execution_count': 0,
            'nonrecoverable_execution_count': 0,
            'pending_items_count': 0,
            'terminal_pending_count': 0,
            'recoverable_execution_providers': [],
            'nonrecoverable_execution_providers': [],
        },
        'active_inbound_diagnostics': [],
        'agents': [],
    }


def test_doctor_summary_includes_windows_x64_release_surface_projection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'repo-doctor-windows-release-surface'
    (project_root / '.ccb').mkdir(parents=True, exist_ok=True)
    (project_root / '.ccb' / 'ccb.config').write_text('demo:codex\n', encoding='utf-8')
    bootstrap_project(project_root)
    context = CliContextBuilder().build(ParsedDoctorCommand(project=None), cwd=project_root, bootstrap_if_missing=False)
    install_root = tmp_path / 'install-root'
    install_root.mkdir()
    projection = default_blocked_projection(
        failure_reason='upstream-not-admitted',
        diagnostic='Windows x64 release route is blocked by upstream evidence.',
        next_action='Use install.ps1 for source/dev checkout installs.',
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(doctor_service, 'installation_summary', lambda: {'path': str(install_root)})
    monkeypatch.setattr(doctor_service, 'ping_local_state', lambda _context: _local_ping(context))

    def _load_projection(root, host_evidence):
        calls.append({'root': root, 'host_evidence': dict(host_evidence)})
        return projection

    monkeypatch.setattr(doctor_service, 'load_windows_x64_release_surface_projection', _load_projection)

    payload = doctor_service.doctor_summary(context)

    assert payload['windows_x64_release_surface'] == projection
    assert calls == [
        {
            'root': install_root,
            'host_evidence': {
                'os_platform': 'win32',
                'cpu_arch': 'x64',
                'process_arch': 'x64',
                'wow64': False,
                'python_executable': None,
                'python_bitness': 'unknown',
                'installer_entrypoint': 'doctor',
            },
        }
    ]


def test_render_doctor_includes_windows_x64_release_surface_rows() -> None:
    projection = default_blocked_projection(
        failure_reason='upstream-not-admitted',
        diagnostic='Windows x64 release route is blocked by upstream evidence.',
        next_action='Use install.ps1 for source/dev checkout installs.',
    )

    lines = render_doctor(_minimal_doctor_payload(projection))

    assert (
        'windows_x64_release_surface: '
        'surface_state=blocked failure_reason=upstream-not-admitted '
        'release_install_entry=diagnostic_only source_install_allowed=True '
        'source_install_entry=install_ps1 update_entry=diagnostic_only '
        'managed_python_status=unknown native_helper_status=unknown'
    ) in lines
    assert (
        'windows_x64_release_surface_detail: '
        'implementation_admission=admitted '
        'baseline_version_status=v8.5.2 upstream_gate_status=blocked '
        'upstream_failure_ref=None upstream_detail_reason=upstream-not-admitted '
        'beta_gaps=none'
    ) in lines
    assert (
        'windows_x64_release_surface_next_action: '
        'diagnostic=Windows x64 release route is blocked by upstream evidence. '
        'next_action=Use install.ps1 for source/dev checkout installs.'
    ) in lines


def test_docs_and_readme_document_windows_x64_release_surface_contract() -> None:
    docs = Path('docs/ccbd-diagnostics-contract.md').read_text(encoding='utf-8')
    readme = Path('README.md').read_text(encoding='utf-8')

    for text in (docs, readme):
        assert 'windows_x64_release_surface' in text
        assert 'release_install_entry' in text
        assert 'source_install_allowed' in text
        assert 'source_install_entry' in text
        assert 'update_entry' in text
        assert 'managed_python_status' in text
        assert 'native_helper_status' in text
        assert 'next_action' in text

    bad_bundle_lines = [
        (index + 1, line)
        for index, line in enumerate(docs.splitlines())
        if 'doctor --bundle' in line.lower()
        and not any(word in line.lower() for word in ('deprecated', 'unsupported', 'no longer supported', 'not supported'))
    ]
    assert bad_bundle_lines == []
