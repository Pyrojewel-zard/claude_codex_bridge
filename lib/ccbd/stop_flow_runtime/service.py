from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agents.models import AgentState
from agents.store import AgentRuntimeStore
from cli.services.tmux_cleanup_history import TmuxCleanupHistoryStore
from cli.services.tmux_project_cleanup import cleanup_project_tmux_orphans_by_socket
from hapi_integration.command import hapi_enabled
from hapi_integration.runtime import graceful_stop_wrapper_records, wrapper_identity_path
from hapi_integration.store import read_preflight_cache
from provider_backends.codex.runtime_artifacts import cleanup_codex_app_server_shutdown_artifacts
from provider_runtime.helper_manifest import clear_helper_manifest
from terminal_runtime.tmux import normalize_socket_name

from .models import StopAllExecution, StopAllSummary
from .pid_cleanup import collect_pid_candidates, terminate_runtime_pids
from .runtime_records import best_effort_runtime, extra_agent_dir_names
from .tmux_cleanup import cleanup_stop_tmux_orphans

_HAPI_GRACEFUL_STOP_TIMEOUT_S = 3.0


def stop_all_project(
    *,
    project_root: Path,
    project_id: str,
    paths,
    registry,
    project_namespace,
    clock,
    force: bool,
    config=None,
    cleanup_project_tmux_orphans_by_socket_fn=cleanup_project_tmux_orphans_by_socket,
    tmux_cleanup_history_store_cls=TmuxCleanupHistoryStore,
    graceful_stop_wrappers_fn=graceful_stop_wrapper_records,
) -> StopAllExecution:
    tmux_sockets: set[str | None] = set()
    pid_candidates: dict[int, list[Path]] = {}
    stopped_agents: list[str] = []
    runtime_store = AgentRuntimeStore(paths)
    configured_agent_names = tuple(registry.list_known_agents())
    extra_agent_names = extra_agent_dir_names(paths, configured_agent_names)
    actions_taken: list[str] = []
    deferred_actions = []
    codex_runtime_dirs: list[Path] = []
    hapi_wrapper_records: list[Path] = []

    if project_namespace is not None:
        def _destroy_namespace() -> None:
            project_namespace.destroy(reason='stop_all', force=force)

        deferred_actions.append(_destroy_namespace)
        actions_taken.append('destroy_namespace:deferred')

    for agent_name in (*configured_agent_names, *extra_agent_names):
        runtime = best_effort_runtime(
            agent_name=agent_name,
            configured_agent_names=configured_agent_names,
            registry=registry,
            runtime_store=runtime_store,
        )
        if str(getattr(runtime, 'provider', '') or '').strip().lower() == 'codex':
            codex_runtime_dirs.append(paths.agent_dir(agent_name) / 'provider-runtime' / 'codex')
        provider = str(getattr(runtime, 'provider', '') or '').strip().lower()
        if provider in {'claude', 'codex'}:
            hapi_wrapper_records.append(
                wrapper_identity_path(paths.agent_dir(agent_name) / 'provider-runtime' / provider)
            )
        if (
            runtime is not None
            and str(runtime.runtime_ref or '').startswith('tmux:')
            and getattr(runtime, 'tmux_socket_path', None) is None
        ):
            socket_name = normalize_socket_name(runtime.tmux_socket_name)
            if socket_name is not None:
                tmux_sockets.add(socket_name)
        for pid, sources in collect_pid_candidates(
            paths.agent_dir(agent_name),
            runtime=runtime,
            fallback_to_agent_dir=force,
        ).items():
            pid_candidates.setdefault(pid, []).extend(sources)
        if runtime is None or agent_name not in configured_agent_names:
            continue
        registry.upsert_authority(
            replace(
                runtime,
                state=AgentState.STOPPED,
                pid=None,
                runtime_ref=None,
                session_ref=None,
                queue_depth=0,
                socket_path=None,
                health='stopped',
                runtime_pid=None,
                runtime_root=None,
                pane_id=None,
                active_pane_id=None,
                pane_title_marker=None,
                pane_state=None,
                tmux_socket_name=None,
                tmux_socket_path=None,
                session_file=None,
                session_id=None,
                lifecycle_state='stopped',
                desired_state='stopped',
                reconcile_state='stopped',
                last_failure_reason=None,
            )
        )
        stopped_agents.append(agent_name)
        actions_taken.append(f'mark_runtime_stopped:{agent_name}')

    hapi_active = _project_hapi_active(config, paths)
    if hapi_active and hapi_wrapper_records:
        _graceful_terminate_hapi_wrappers(
            tuple(hapi_wrapper_records),
            timeout_s=_HAPI_GRACEFUL_STOP_TIMEOUT_S,
            graceful_stop_wrappers_fn=graceful_stop_wrappers_fn,
            actions_taken=actions_taken,
        )

    cleanup_summaries = cleanup_stop_tmux_orphans(
        project_id=project_id,
        paths=paths,
        tmux_sockets=tmux_sockets,
        clock=clock,
        actions_taken=actions_taken,
        cleanup_project_tmux_orphans_by_socket_fn=cleanup_project_tmux_orphans_by_socket_fn,
        tmux_cleanup_history_store_cls=tmux_cleanup_history_store_cls,
    )
    terminate_runtime_pids(project_root=project_root, pid_candidates=pid_candidates)
    cleaned_codex_artifacts = sum(
        len(cleanup_codex_app_server_shutdown_artifacts(runtime_dir))
        for runtime_dir in codex_runtime_dirs
    )
    if codex_runtime_dirs:
        actions_taken.append(f'cleanup_codex_app_server_artifacts:{cleaned_codex_artifacts}')
    for agent_name in (*configured_agent_names, *extra_agent_names):
        clear_helper_manifest(paths.agent_helper_path(agent_name))
    actions_taken.append(f'terminate_runtime_pids:{len(pid_candidates)}')
    summary = StopAllSummary(
        project_id=project_id,
        state='unmounted',
        socket_path=str(paths.ccbd_socket_path),
        forced=force,
        stopped_agents=tuple(stopped_agents),
        cleanup_summaries=cleanup_summaries,
    )
    return StopAllExecution(
        summary=summary,
        stopped_agents=tuple(stopped_agents),
        actions_taken=tuple(actions_taken),
        cleanup_summaries=cleanup_summaries,
        deferred_actions=tuple(deferred_actions),
    )


def _project_hapi_active(config, paths) -> bool:
    """True when HAPI mode is active for this project.

    Prefers the loaded project config; falls back to the per-project preflight
    cache so stop still performs graceful HAPI teardown when the caller did not
    pass a config but HAPI wrappers were launched this generation.
    """
    if config is not None:
        return hapi_enabled(config)
    try:
        return read_preflight_cache(paths.shared_cache_dir) is not None
    except Exception:
        return False


def _graceful_terminate_hapi_wrappers(
    wrapper_records: tuple[Path, ...],
    *,
    timeout_s: float,
    graceful_stop_wrappers_fn,
    actions_taken: list[str],
) -> None:
    try:
        signaled, exited = graceful_stop_wrappers_fn(wrapper_records, timeout_s=timeout_s)
    except Exception:
        signaled, exited = 0, 0
    actions_taken.append(f'hapi_graceful_stop:{exited}/{signaled}')


__all__ = ['stop_all_project']
