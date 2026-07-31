from __future__ import annotations

from agents.models import AgentState
from agents.config_identity import project_config_identity_payload
from provider_execution.capabilities import execution_restore_capability
from storage.path_helpers import socket_placement_payload


def build_agent_payload(*, project_id: str, agent_name: str, registry, inspection, execution_registry) -> dict:
    spec = registry.spec_for(agent_name)
    runtime = registry.get(agent_name)
    adapter = execution_registry.get(spec.provider) if execution_registry is not None else None
    capability = execution_restore_capability(adapter, provider=spec.provider)
    return {
        'project_id': project_id,
        'agent_name': spec.name,
        'provider': spec.provider,
        'mount_state': _agent_mount_state(runtime, inspection=inspection),
        'runtime_state': runtime.state.value if runtime is not None else 'stopped',
        'health': runtime.health if runtime is not None else inspection.health.value,
        'diagnostics': {
            'ccbd_generation': inspection.generation,
            'last_heartbeat_at': inspection.lease.last_heartbeat_at if inspection.lease else None,
            'desired_state': _inspection_desired_state(inspection),
            'reconcile_state': getattr(runtime, 'reconcile_state', None) if runtime is not None else None,
            'restart_count': getattr(runtime, 'restart_count', 0) if runtime is not None else 0,
            'recovery_failure_count': (
                getattr(runtime, 'recovery_failure_count', 0) if runtime is not None else 0
            ),
            'last_reconcile_at': getattr(runtime, 'last_reconcile_at', None) if runtime is not None else None,
            'last_failure_reason': getattr(runtime, 'last_failure_reason', None) if runtime is not None else None,
            **capability,
        },
    }


def build_ccbd_payload(
    *,
    project_id: str,
    config,
    paths,
    inspection,
    execution_summary: dict,
    restore_summary: dict,
    namespace_summary: dict,
    namespace_event_summary: dict,
    start_policy_summary: dict,
    control_plane_metrics=None,
    serving_identity: dict[str, object] | None = None,
) -> dict:
    identity = project_config_identity_payload(config)
    socket_path = inspection.socket_path if hasattr(inspection, 'socket_path') else None
    if socket_path is None and inspection.lease is not None:
        socket_path = inspection.lease.socket_path
    process_metrics = _process_metrics(control_plane_metrics)
    serving = dict(serving_identity or {})
    return {
        'project_id': project_id,
        'mount_state': _inspection_phase(inspection),
        'desired_state': _inspection_desired_state(inspection),
        'health': inspection.health.value,
        'generation': inspection.generation,
        'socket_path': socket_path,
        'tmux_socket_path': str(paths.ccbd_tmux_socket_placement.effective_path),
        **(paths.runtime_state_payload() if hasattr(paths, 'runtime_state_payload') else {}),
        **socket_placement_payload(paths.ccbd_socket_placement),
        **socket_placement_payload(paths.ccbd_tmux_socket_placement, prefix='tmux'),
        'known_agents': list(identity['known_agents']),
        'config_signature': identity['config_signature'],
        'serving_pid': serving.get('serving_pid'),
        'serving_daemon_instance_id': serving.get('serving_daemon_instance_id'),
        'serving_lease_generation': serving.get('serving_lease_generation'),
        'serving_startup_generation': serving.get('serving_startup_generation'),
        'accepted_startup_id': serving.get('accepted_startup_id'),
        **namespace_summary,
        **namespace_event_summary,
        **start_policy_summary,
        'diagnostics': {
            'pid_alive': inspection.pid_alive,
            'socket_connectable': inspection.socket_connectable,
            'heartbeat_fresh': inspection.heartbeat_fresh,
            'takeover_allowed': inspection.takeover_allowed,
            'reason': inspection.reason,
            'startup_id': str(getattr(inspection, 'startup_id', '') or '').strip() or None,
            'startup_stage': str(getattr(inspection, 'startup_stage', '') or '').strip() or None,
            'last_progress_at': str(getattr(inspection, 'last_progress_at', '') or '').strip() or None,
            'startup_deadline_at': str(getattr(inspection, 'startup_deadline_at', '') or '').strip() or None,
            'last_failure_reason': str(getattr(inspection, 'last_failure_reason', '') or '').strip() or None,
            'shutdown_intent': str(getattr(inspection, 'shutdown_intent', '') or '').strip() or None,
            'last_request_queue_wait_s': getattr(control_plane_metrics, 'last_request_queue_wait_s', None),
            'last_submit_duration_s': getattr(control_plane_metrics, 'last_submit_duration_s', None),
            'last_ping_duration_s': getattr(control_plane_metrics, 'last_ping_duration_s', None),
            'last_handler_latency_s_by_op': dict(
                getattr(control_plane_metrics, 'last_handler_latency_s_by_op', {}) or {}
            ),
            'last_maintenance_duration_s': getattr(control_plane_metrics, 'last_maintenance_duration_s', None),
            'last_heartbeat_duration_s': getattr(control_plane_metrics, 'last_heartbeat_duration_s', None),
            'heartbeat_step_duration_s': dict(
                getattr(control_plane_metrics, 'heartbeat_step_duration_s', {}) or {}
            ),
            'last_heartbeat_agents_inspected': getattr(
                control_plane_metrics,
                'last_heartbeat_agents_inspected',
                None,
            ),
            'last_heartbeat_runtime_store_writes': getattr(
                control_plane_metrics,
                'last_heartbeat_runtime_store_writes',
                None,
            ),
            'pending_maintenance_ticks': getattr(control_plane_metrics, 'pending_maintenance_ticks', None),
            'last_project_view_response_duration_s': getattr(
                control_plane_metrics,
                'last_project_view_response_duration_s',
                None,
            ),
            'last_project_view_build_duration_s': getattr(
                control_plane_metrics,
                'last_project_view_build_duration_s',
                None,
            ),
            'project_view_cache_hits': getattr(control_plane_metrics, 'project_view_cache_hits', None),
            'project_view_cache_misses': getattr(control_plane_metrics, 'project_view_cache_misses', None),
            'last_project_view_tmux_command_count': getattr(
                control_plane_metrics,
                'last_project_view_tmux_command_count',
                None,
            ),
            'last_project_view_capture_pane_count': getattr(
                control_plane_metrics,
                'last_project_view_capture_pane_count',
                None,
            ),
            'last_project_view_store_scan_count': getattr(
                control_plane_metrics,
                'last_project_view_store_scan_count',
                None,
            ),
            'rss_bytes': process_metrics.get('rss_bytes'),
            'virtual_memory_bytes': process_metrics.get('virtual_memory_bytes'),
            'fd_count': process_metrics.get('fd_count'),
            'thread_count': process_metrics.get('thread_count'),
            'service_graph_version': getattr(control_plane_metrics, 'service_graph_version', None),
            'service_graph_created_at': getattr(control_plane_metrics, 'service_graph_created_at', None),
            'service_graph_retained_count': getattr(control_plane_metrics, 'service_graph_retained_count', None),
            'service_graph_retained_count_scope': getattr(
                control_plane_metrics,
                'service_graph_retained_count_scope',
                None,
            ),
            'last_reload_duration_s': getattr(control_plane_metrics, 'last_reload_duration_s', None),
            'last_reload_plan_class': getattr(control_plane_metrics, 'last_reload_plan_class', None),
            'last_reload_error': getattr(control_plane_metrics, 'last_reload_error', None),
            **execution_summary,
            **restore_summary,
        },
    }


def _process_metrics(control_plane_metrics) -> dict[str, int | None]:
    snapshot = getattr(control_plane_metrics, 'process_snapshot', None)
    if not callable(snapshot):
        return {}
    try:
        value = snapshot()
    except Exception:
        return {}
    return dict(value or {}) if isinstance(value, dict) else {}


def _inspection_phase(inspection) -> str:
    phase = str(getattr(inspection, 'phase', '') or '').strip()
    if phase:
        return phase
    lease = getattr(inspection, 'lease', None)
    return str(getattr(getattr(lease, 'mount_state', None), 'value', '') or 'unmounted')


def _inspection_desired_state(inspection) -> str | None:
    desired_state = str(getattr(inspection, 'desired_state', '') or '').strip()
    return desired_state or None


def _agent_mount_state(runtime, *, inspection) -> str:
    if runtime is None:
        return _inspection_phase(inspection)
    if runtime.state is AgentState.STARTING:
        return 'starting'
    if runtime.state is AgentState.FAILED:
        return 'failed'
    if runtime.state is AgentState.STOPPED:
        return 'unmounted'
    return 'mounted'


__all__ = ['build_agent_payload', 'build_ccbd_payload']
