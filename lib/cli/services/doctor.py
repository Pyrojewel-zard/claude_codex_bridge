from __future__ import annotations

from agents.config_loader import load_project_config
from ccbd.socket_client import CcbdClient
from provider_core.catalog import build_default_provider_catalog
from provider_execution.registry import build_default_execution_registry

from .daemon import ping_local_state
from .daemon_runtime.policy import CONTROL_PLANE_RPC_TIMEOUT_S
from .config_validate import validate_config_context
from .doctor_runtime import (
    agent_summaries,
    ccbd_summary,
    doctor_stores,
    entrypoint_summary,
    installation_summary,
    requirements_summary,
    runtime_identity_summary,
)


def doctor_summary(context) -> dict:
    config = load_project_config(context.project.project_root).config
    config_validation = validate_config_context(context)
    stores = doctor_stores(context)
    installation = installation_summary()
    catalog = build_default_provider_catalog()
    execution_registry = build_default_execution_registry()
    local = ping_local_state(context)
    errors: list[str] = []
    remote_client, remote_client_error = _load_remote_client(context, local=local)
    remote_ccbd, remote_error = _load_remote_ccbd_summary(
        context,
        local=local,
        client=remote_client,
        client_error=remote_client_error,
    )
    if remote_error is not None:
        errors.append(f'remote_ccbd_probe:{remote_error}')
    active_inbound_diagnostics, project_view_error = _load_remote_project_view_diagnostics(
        context,
        local=local,
        client=remote_client,
        client_error=remote_client_error,
    )
    if project_view_error is not None:
        errors.append(f'remote_project_view_probe:{project_view_error}')
    agents = agent_summaries(
        context,
        config=config,
        stores=stores,
        catalog=catalog,
        execution_registry=execution_registry,
        errors=errors,
    )
    return {
        'project': str(context.project.project_root),
        'project_id': context.project.project_id,
        'installation': installation,
        'entrypoint': entrypoint_summary(installation=installation),
        'runtime': runtime_identity_summary(
            context.project.project_root,
            ccb_dir=context.paths.ccb_dir,
            installation=installation,
        ),
        'requirements': requirements_summary(),
        'config': config_validation.to_record(),
        'ccbd': ccbd_summary(local=local, stores=stores, errors=errors, remote=remote_ccbd),
        'active_inbound_diagnostics': active_inbound_diagnostics,
        'agents': agents,
    }


def _load_remote_client(context, *, local) -> tuple[object | None, str | None]:
    if local.mount_state == 'unmounted':
        return None, None
    if not local.socket_connectable:
        return None, None
    try:
        return CcbdClient(context.paths.ccbd_socket_path, timeout_s=CONTROL_PLANE_RPC_TIMEOUT_S), None
    except Exception as exc:
        return None, str(exc)


def _load_remote_ccbd_summary(
    context,
    *,
    local,
    client: object | None = None,
    client_error: str | None = None,
) -> tuple[dict | None, str | None]:
    if local.mount_state == 'unmounted' or not local.socket_connectable:
        return None, None
    if client_error is not None:
        return None, client_error
    if client is None:
        client, client_error = _load_remote_client(context, local=local)
        if client_error is not None or client is None:
            return None, client_error
    try:
        payload = client.ping('ccbd')
    except Exception as exc:
        return None, str(exc)
    return (payload if isinstance(payload, dict) else None), None


def _load_remote_project_view_diagnostics(
    context,
    *,
    local,
    client: object | None = None,
    client_error: str | None = None,
) -> tuple[list[dict[str, object]], str | None]:
    if local.mount_state == 'unmounted' or not local.socket_connectable:
        return [], None
    if client_error is not None:
        return [], client_error
    try:
        if client is None:
            client, client_error = _load_remote_client(context, local=local)
            if client_error is not None or client is None:
                return [], client_error
        project_view = getattr(client, 'project_view', None)
        if not callable(project_view):
            return [], None
        payload = project_view(schema_version=1)
    except Exception as exc:
        return [], str(exc)
    return _active_inbound_diagnostics_from_project_view(payload), None


def _active_inbound_diagnostics_from_project_view(payload: object) -> list[dict[str, object]]:
    view = payload.get('view') if isinstance(payload, dict) else None
    comms = view.get('comms') if isinstance(view, dict) else None
    result: list[dict[str, object]] = []
    for comm in comms or ():
        if not isinstance(comm, dict):
            continue
        diagnostic = comm.get('active_inbound_diagnostic')
        if not isinstance(diagnostic, dict):
            continue
        comm_job_id = str(comm.get('id') or '').strip()
        diagnostic_job_id = str(diagnostic.get('job_id') or '').strip()
        if (
            comm_job_id
            and diagnostic_job_id == comm_job_id
            and str(diagnostic.get('condition_kind') or '').strip() == 'orphaned_active_inbound'
        ):
            result.append(dict(diagnostic))
    return result
