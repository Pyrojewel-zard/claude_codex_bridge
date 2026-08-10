from __future__ import annotations

import os
from pathlib import Path
import shlex
from typing import Any

from provider_core.source_home import current_provider_source_home

from .store import read_preflight_cache

_HAPI_FLAVORS = frozenset({'claude', 'codex'})
_HAPI_STARTED_BY = 'terminal'
_HAPI_DISABLE_RUNNER_VALUE = '1'


def decorate_hapi_argv(*, command: str, flavor: str, provider_argv: list[str]) -> list[str]:
    """Render the HAPI wrapper argv from a native provider argv.

    Frozen contract::

        claude <args>  -> <command> claude --started-by terminal <args>
        codex  <args>  -> <command> codex  --started-by terminal <args>

    The actual provider executable token is stripped exactly once from the
    head of ``provider_argv``. No ``--`` wrapper delimiter is
    inserted. The returned argv is quoted by the caller using CCB's existing
    ``shlex.quote`` conventions before it reaches a shell.
    """
    hapi_command = str(command or '').strip()
    if not hapi_command:
        raise ValueError('hapi command must not be empty')
    normalized_flavor = str(flavor or '').strip().lower()
    if normalized_flavor not in _HAPI_FLAVORS:
        raise ValueError(f'hapi mode supports only claude and codex flavors; got {flavor!r}')
    argv = list(provider_argv)
    if not argv or not str(argv[0]).strip():
        raise ValueError('provider executable must not be empty in hapi mode')
    argv = argv[1:]
    return [hapi_command, normalized_flavor, '--started-by', _HAPI_STARTED_BY, *argv]


def render_recorded_hapi_command(
    *,
    wrapper_argv: list[str],
    record_path: Path,
    launch_session_id: str,
) -> str:
    """Render an exec wrapper that atomically records its own PID and PGID."""
    if not wrapper_argv:
        raise ValueError('hapi wrapper argv must not be empty')
    session_id = _required_str(launch_session_id, 'launch_session_id')
    script = (
        'record=$1; session=$2; shift 2; tmp="${record}.tmp.$$"; '
        'pgid=$(ps -o pgid= -p "$$") || exit 125; pgid=${pgid##* }; '
        'umask 077; '
        'printf \'{"schemaVersion":1,"sessionId":"%s","pid":%s,"pgid":%s}\\n\' '
        '"$session" "$$" "$pgid" > "$tmp" || exit 125; '
        'mv -f -- "$tmp" "$record" || exit 125; exec "$@"'
    )
    argv = [
        'sh',
        '-c',
        script,
        'ccb-hapi-wrapper',
        str(record_path),
        session_id,
        *wrapper_argv,
    ]
    return ' '.join(shlex.quote(str(part)) for part in argv)


def resolve_hapi_home(
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    source_home_fn=current_provider_source_home,
) -> str:
    source = os.environ if environ is None else environ
    explicit = str(source.get('HAPI_HOME') or '').strip()
    if explicit:
        return str(Path(explicit).expanduser())
    return str(Path(source_home_fn()).expanduser() / '.hapi')


def hapi_identity_env(
    *,
    project_id: str,
    agent_name: str,
    provider: str,
    launch_session_id: str,
    workgroup: str | None,
    api_url: str,
    hapi_home: str,
) -> dict[str, str]:
    """Build the frozen CCB identity + runner-disable environment block.

    ``HAPI_CCB_WORKGROUP`` is present only when a nonempty workgroup exists; it
    is never emitted as an empty string. ``HAPI_API_URL`` carries the preflight
    ``apiUrl`` so the wrapper cannot auto-start a Hub.
    """
    env: dict[str, str] = {
        'HAPI_DISABLE_RUNNER_AUTO_START': _HAPI_DISABLE_RUNNER_VALUE,
        'HAPI_CCB_PROJECT_ID': _required_str(project_id, 'project_id'),
        'HAPI_CCB_AGENT_NAME': _required_str(agent_name, 'agent_name'),
        'HAPI_CCB_PROVIDER': _required_str(provider, 'provider'),
        'HAPI_CCB_SESSION_ID': _required_str(launch_session_id, 'launch_session_id'),
        'HAPI_API_URL': _required_str(api_url, 'api_url'),
        'HAPI_HOME': _required_str(hapi_home, 'hapi_home'),
    }
    workgroup_value = str(workgroup or '').strip()
    if workgroup_value:
        env['HAPI_CCB_WORKGROUP'] = workgroup_value
    return env


def hapi_enabled(config: Any) -> bool:
    hapi = getattr(config, 'hapi', None)
    return bool(getattr(hapi, 'enabled', False))


def hapi_command(config: Any) -> str:
    hapi = getattr(config, 'hapi', None)
    return str(getattr(hapi, 'command', '') or 'hapi')


def load_hapi_launch_context(
    context: Any,
    spec: Any,
) -> dict[str, object] | None:
    """Read the per-project HAPI preflight cache and build the launch context.

    Returns ``None`` when HAPI mode is not active (no preflight cache). When
    active, returns a dict carrying the wrapper ``command``, the ``api_url``,
    the ``flavor``, and the static identity fields. Launchers store this in
    ``prepared_state`` so ``build_start_cmd`` can decorate the argv and inject
    the identity environment (which only needs the runtime
    ``launch_session_id`` filled in) after the managed-home/provider env.
    """
    shared_cache_dir = getattr(getattr(context, 'paths', None), 'shared_cache_dir', None)
    if shared_cache_dir is None:
        return None
    cache = read_preflight_cache(shared_cache_dir)
    if cache is None:
        return None
    flavor = str(getattr(spec, 'provider', '') or '').strip().lower()
    if flavor not in _HAPI_FLAVORS:
        return None
    project_id = str(getattr(getattr(context, 'project', None), 'project_id', '') or '').strip()
    agent_name = str(getattr(spec, 'name', '') or '').strip()
    workgroup = str(getattr(spec, 'workspace_group', '') or '').strip() or None
    return {
        'enabled': True,
        'command': cache.command,
        'flavor': flavor,
        'api_url': cache.api_url,
        'hapi_home': cache.hapi_home,
        'project_id': project_id,
        'agent_name': agent_name,
        'workgroup': workgroup,
    }


def hapi_identity_env_from_context(
    launch_context: dict[str, object] | None,
    launch_session_id: str,
) -> dict[str, str] | None:
    """Build the frozen identity env from a launch context + runtime session id.

    Returns ``None`` when HAPI mode is not active.
    """
    if not launch_context:
        return None
    return hapi_identity_env(
        project_id=str(launch_context.get('project_id') or ''),
        agent_name=str(launch_context.get('agent_name') or ''),
        provider=str(launch_context.get('flavor') or ''),
        launch_session_id=launch_session_id,
        workgroup=launch_context.get('workgroup'),
        api_url=str(launch_context.get('api_url') or ''),
        hapi_home=str(launch_context.get('hapi_home') or ''),
    )


def _required_str(value: object, field_name: str) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError(f'hapi identity {field_name} must not be empty')
    return text


__all__ = [
    'decorate_hapi_argv',
    'hapi_command',
    'hapi_enabled',
    'hapi_identity_env',
    'hapi_identity_env_from_context',
    'load_hapi_launch_context',
    'render_recorded_hapi_command',
    'resolve_hapi_home',
]
