from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from cli.services.role_command_policy import role_command_policy_disables_inherited_assets
from provider_core.memory_projection import (
    materialize_provider_memory_file,
    memory_projection_result,
    record_memory_projection_event,
)
from provider_core.keyring_read import read_keyring_password
from provider_core.one_way_inheritance import (
    copy_regular_file,
    ensure_private_directory,
    ensure_private_inheritance_directory,
)
from provider_core.inherited_skills import materialize_required_control_skills
from provider_core.projected_assets import seed_projected_tree
from provider_core.source_home import current_provider_source_home
from provider_profiles import provider_api_env_keys
from storage.atomic import atomic_write_text
from storage.paths import ensure_provider_user_cache_dir

from ..home_layout import GeminiHomeLayout, gemini_layout_for_home, gemini_layout_from_session_data
from .session_paths import read_session_payload, session_file_for_runtime_dir, state_dir_for_runtime_dir

_GEMINI_LOGIN_AUTH_FILENAMES = (
    'oauth_creds.json',
    'google_accounts.json',
    # Gemini uses this encrypted file when OS keychain access is disabled.
    'gemini-credentials.json',
    # Preserve existing MCP/A2A authorization only as private ordinary files.
    'mcp-oauth-tokens.json',
    'a2a-oauth-tokens.json',
)
_GEMINI_EXTENSIONS_PROJECTION_LABEL = 'gemini-inherited-extensions'


def resolve_gemini_home_layout(runtime_dir: Path, profile) -> GeminiHomeLayout:
    explicit_runtime_home = _profile_runtime_home(profile)
    if explicit_runtime_home is not None:
        return gemini_layout_for_home(explicit_runtime_home)

    managed_home = _managed_isolated_home(runtime_dir)
    existing = _existing_layout(runtime_dir, managed_home=managed_home)
    if existing is not None:
        return existing

    return gemini_layout_for_home(managed_home)


def prepare_gemini_home_overrides(
    runtime_dir: Path,
    profile,
    *,
    refresh_home: bool = True,
    project_root: Path | None = None,
    agent_name: str | None = None,
    workspace_path: Path | None = None,
    memory_projection_event_path: Path | None = None,
    memory_projection_marker_path: Path | None = None,
    command_policy=None,
) -> dict[str, str]:
    layout = resolve_gemini_home_layout(runtime_dir, profile)
    if refresh_home:
        materialize_gemini_home_config(
            layout.home_root,
            profile=profile,
            project_root=project_root,
            agent_name=agent_name,
            workspace_path=workspace_path,
            memory_projection_event_path=memory_projection_event_path,
            memory_projection_marker_path=memory_projection_marker_path,
            command_policy=command_policy,
        )
    materialize_required_control_skills(
        provider='gemini',
        target_dir=layout.gemini_dir / 'skills',
    )
    cache_root = _gemini_shared_cache_root()
    overrides = {
        'HOME': str(layout.home_root),
        'GEMINI_CLI_HOME': str(layout.home_root),
        'GEMINI_ROOT': str(layout.tmp_root),
        'NPM_CONFIG_CACHE': str(cache_root / 'npm'),
        'npm_config_cache': str(cache_root / 'npm'),
        'XDG_CACHE_HOME': str(cache_root / 'xdg'),
        # Gemini's supported file-storage switch prevents managed MCP/OAuth
        # refresh or logout from mutating the user's OS keychain.
        'GEMINI_FORCE_FILE_STORAGE': 'true',
        'GEMINI_FORCE_ENCRYPTED_FILE_STORAGE': 'true',
    }
    if "WSL_DISTRO_NAME" in os.environ:
        overrides['USERPROFILE'] = str(layout.home_root)
        wslenv_additions = (
            "HOME/p:USERPROFILE/p:GEMINI_CLI_HOME/p:GEMINI_ROOT/p:"
            "NPM_CONFIG_CACHE/p:npm_config_cache/p:XDG_CACHE_HOME/p:"
            "GEMINI_FORCE_FILE_STORAGE:GEMINI_FORCE_ENCRYPTED_FILE_STORAGE"
        )
        existing_wslenv = os.environ.get("WSLENV", "")
        overrides['WSLENV'] = (
            f"{wslenv_additions}:{existing_wslenv}"
            if existing_wslenv
            else wslenv_additions
        )
    return overrides


def _profile_runtime_home(profile) -> Path | None:
    del profile
    return None


def _existing_layout(runtime_dir: Path, *, managed_home: Path) -> GeminiHomeLayout | None:
    session_file = session_file_for_runtime_dir(runtime_dir)
    if session_file is None or not session_file.is_file():
        return None
    data = read_session_payload(session_file)
    if not isinstance(data, dict):
        return None
    layout = gemini_layout_from_session_data(data)
    if layout is None:
        return None
    return layout if _is_within_home_root(layout.home_root, managed_home) else None


def _managed_isolated_home(runtime_dir: Path) -> Path:
    state_dir = state_dir_for_runtime_dir(runtime_dir)
    if state_dir is not None:
        return state_dir / 'home'
    return Path(runtime_dir).expanduser() / 'gemini-home'


def _gemini_shared_cache_root() -> Path:
    root = ensure_provider_user_cache_dir('gemini')
    (root / 'npm').mkdir(parents=True, exist_ok=True)
    (root / 'xdg').mkdir(parents=True, exist_ok=True)
    return root


def _is_within_home_root(candidate: Path, managed_home: Path) -> bool:
    normalized_candidate = _normalize_path(candidate)
    normalized_managed = _normalize_path(managed_home)
    if normalized_candidate is None or normalized_managed is None:
        return False
    try:
        normalized_candidate.relative_to(normalized_managed)
        return True
    except Exception:
        return False


def _normalize_path(value: object) -> Path | None:
    try:
        return Path(value).expanduser().resolve()
    except Exception:
        try:
            return Path(value).expanduser()
        except Exception:
            return None


def _prepare_managed_home(layout: GeminiHomeLayout, *, source_home: Path) -> None:
    ensure_private_inheritance_directory(layout.home_root, source_home)
    ensure_private_directory(layout.gemini_dir)
    ensure_private_directory(layout.tmp_root)
    _ensure_json_file(layout.settings_path)
    _ensure_json_file(layout.trusted_folders_path)


def _ensure_json_file(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        return
    atomic_write_text(path, '{}\n')


def materialize_gemini_home_config(
    target_home: Path,
    *,
    profile=None,
    source_home: Path | None = None,
    project_root: Path | None = None,
    agent_name: str | None = None,
    workspace_path: Path | None = None,
    memory_projection_event_path: Path | None = None,
    memory_projection_marker_path: Path | None = None,
    command_policy=None,
) -> GeminiHomeLayout:
    layout = gemini_layout_for_home(target_home)
    inherit_external_keyring = (
        source_home is None
        and not os.environ.get('CCB_SOURCE_HOME')
    )
    source_root = Path(source_home).expanduser() if source_home is not None else _system_home_root()
    _prepare_managed_home(layout, source_home=source_root)
    _materialize_settings(source_root, layout, profile=profile)
    _materialize_env_file(source_root, layout, profile=profile)
    _materialize_trusted_folders(source_root, layout)
    _materialize_auth(
        source_root,
        layout,
        profile=profile,
        inherit_external_keyring=inherit_external_keyring,
    )
    seed_projected_tree(
        source_root / '.gemini' / 'extensions',
        layout.gemini_dir / 'extensions',
        enabled=(
            _inherits_config(profile)
            and not role_command_policy_disables_inherited_assets(command_policy)
        ),
        label=_GEMINI_EXTENSIONS_PROJECTION_LABEL,
    )
    materialize_required_control_skills(
        provider='gemini',
        target_dir=layout.gemini_dir / 'skills',
    )
    memory_result = _materialize_gemini_memory(
        source_root,
        layout,
        profile=profile,
        project_root=project_root,
        agent_name=agent_name,
        workspace_path=workspace_path,
    )
    record_memory_projection_event(
        memory_result,
        provider='gemini',
        event_path=memory_projection_event_path,
        marker_path=memory_projection_marker_path,
        agent_name=agent_name,
    )
    return layout


def _materialize_settings(source_home: Path, layout: GeminiHomeLayout, *, profile) -> None:
    projected = _projected_settings_payload(source_home / '.gemini' / 'settings.json', profile=profile)
    existing = _read_json_object(layout.settings_path)
    merged = _merge_settings_payload(projected, existing=existing)
    if merged is None:
        return
    _write_json_object(layout.settings_path, merged)


def _materialize_trusted_folders(source_home: Path, layout: GeminiHomeLayout) -> None:
    projected = _read_json_object(source_home / '.gemini' / 'trustedFolders.json')
    existing = _read_json_object(layout.trusted_folders_path)
    merged = _merge_object_payload(projected, existing=existing)
    if merged is None:
        return
    _write_json_object(layout.trusted_folders_path, merged)


def _materialize_env_file(source_home: Path, layout: GeminiHomeLayout, *, profile) -> None:
    target_env = layout.gemini_dir / '.env'
    env_payload = _projected_dotenv_payload(source_home / '.gemini' / '.env', profile=profile)
    if not env_payload:
        _remove_file(target_env)
        return
    _write_env_file(target_env, env_payload)


def _materialize_auth(
    source_home: Path,
    layout: GeminiHomeLayout,
    *,
    profile,
    inherit_external_keyring: bool,
) -> None:
    if not _should_project_login_auth(source_home / '.gemini' / 'settings.json', profile=profile):
        for filename in _GEMINI_LOGIN_AUTH_FILENAMES:
            _remove_file(layout.gemini_dir / filename)
        return
    for filename in _GEMINI_LOGIN_AUTH_FILENAMES:
        source = source_home / '.gemini' / filename
        target = layout.gemini_dir / filename
        if not source.is_file() or source.is_symlink():
            _remove_file(target)
            continue
        try:
            copy_regular_file(source, target)
        except OSError:
            pass
    if inherit_external_keyring:
        _materialize_external_keyring_oauth(layout)


def _materialize_external_keyring_oauth(layout: GeminiHomeLayout) -> None:
    if any(
        (layout.gemini_dir / filename).is_file()
        for filename in ('oauth_creds.json', 'gemini-credentials.json')
    ):
        return
    raw = read_keyring_password(
        'gemini-cli-oauth',
        'main-account',
        command_name='gemini',
        module_names=('@github/keytar', 'keytar'),
    )
    payload = _gemini_keyring_oauth_payload(raw)
    if payload is None:
        return
    # Current Gemini migrates this legacy OAuth shape into its encrypted file
    # backend inside the already-private managed HOME.  The source keychain is
    # read only and is never selected by the managed process.
    _write_json_object(layout.gemini_dir / 'oauth_creds.json', payload)


def _gemini_keyring_oauth_payload(raw: str | None) -> dict[str, object] | None:
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except Exception:
        return None
    if not isinstance(stored, dict):
        return None
    token = stored.get('token')
    if not isinstance(token, dict):
        return None
    access_token = token.get('accessToken')
    refresh_token = token.get('refreshToken')
    if not str(access_token or '').strip() and not str(refresh_token or '').strip():
        return None
    field_map = (
        ('accessToken', 'access_token'),
        ('refreshToken', 'refresh_token'),
        ('tokenType', 'token_type'),
        ('scope', 'scope'),
        ('expiresAt', 'expiry_date'),
    )
    payload = {
        target: token[source]
        for source, target in field_map
        if token.get(source) is not None
    }
    return payload or None


def _projected_settings_payload(source_settings_path: Path, *, profile) -> dict[str, object] | None:
    source_payload = _read_json_object(source_settings_path)
    if not source_payload:
        return _disable_managed_gemini_autoupdate({})

    source_env = dict(source_payload.get('env') or {}) if isinstance(source_payload.get('env'), dict) else {}
    env_payload = dict(source_env) if _inherits_config(profile) else {}
    if _inherits_api(profile):
        for key in provider_api_env_keys('gemini'):
            value = source_env.get(key)
            if value is not None:
                env_payload[key] = value
    else:
        for key in provider_api_env_keys('gemini'):
            env_payload.pop(key, None)

    payload: dict[str, object] = dict(source_payload) if _inherits_config(profile) else {}
    projected_selected_type = _projected_auth_selected_type(_selected_auth_type(source_payload), profile=profile)
    if projected_selected_type is not None:
        _set_selected_auth_type(payload, projected_selected_type)
    else:
        _clear_selected_auth_type(payload)
    if env_payload:
        payload['env'] = env_payload
    else:
        payload.pop('env', None)
    return _disable_managed_gemini_autoupdate(payload)


def _disable_managed_gemini_autoupdate(payload: dict[str, object]) -> dict[str, object]:
    managed = dict(payload)
    raw_general = managed.get('general')
    general = dict(raw_general) if isinstance(raw_general, dict) else {}
    general['enableAutoUpdate'] = False
    general['enableAutoUpdateNotification'] = False
    managed['general'] = general
    return managed


def _merge_settings_payload(
    projected: dict[str, object] | None,
    *,
    existing: dict[str, object] | None,
) -> dict[str, object] | None:
    projected_payload = dict(projected or {})
    existing_payload = dict(existing or {})
    merged = dict(projected_payload)
    hooks = existing_payload.get('hooks')
    if hooks is not None:
        merged['hooks'] = hooks
    context_file_name = existing_payload.get('contextFileName')
    if context_file_name is not None:
        merged['contextFileName'] = context_file_name
    if merged:
        return merged
    if existing_payload:
        return existing_payload
    return None


def _merge_object_payload(
    projected: dict[str, object] | None,
    *,
    existing: dict[str, object] | None,
) -> dict[str, object] | None:
    merged = dict(projected or {})
    merged.update(dict(existing or {}))
    return merged if merged else None


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_object(path: Path, payload: dict[str, object]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def _projected_dotenv_payload(source_env_path: Path, *, profile) -> dict[str, str]:
    if not _inherits_api(profile):
        return {}
    source_payload = _read_env_file(source_env_path)
    if not source_payload:
        return {}
    allowed = provider_api_env_keys('gemini')
    return {
        key: value
        for key, value in source_payload.items()
        if key in allowed and str(value).strip()
    }


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return {}
    payload: dict[str, str] = {}
    for line in lines:
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        payload[key] = value
    return payload


def _parse_env_line(line: str) -> tuple[str, str] | None:
    raw = str(line or '').strip()
    if not raw or raw.startswith('#'):
        return None
    if raw.startswith('export '):
        raw = raw[len('export ') :].lstrip()
    if '=' not in raw:
        return None
    key, value = raw.split('=', 1)
    key = key.strip()
    if not _is_env_key(key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def _is_env_key(value: str) -> bool:
    if not value:
        return False
    first = value[0]
    if not (first == '_' or first.isalpha()):
        return False
    return all(ch == '_' or ch.isalnum() for ch in value)


def _write_env_file(path: Path, payload: dict[str, str]) -> None:
    lines = [f'{key}={_quote_env_value(value)}' for key, value in sorted(payload.items())]
    atomic_write_text(path, '\n'.join(lines) + '\n')
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _quote_env_value(value: object) -> str:
    raw = str(value)
    escaped = raw.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    return f'"{escaped}"'


def _inherits_api(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_api', True))


def _inherits_auth(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_auth', True))


def _inherits_config(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_config', True))


def _inherits_memory(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_memory', True))


def _materialize_gemini_memory(
    source_home: Path,
    layout: GeminiHomeLayout,
    *,
    profile,
    project_root: Path | None,
    agent_name: str | None,
    workspace_path: Path | None,
) -> dict[str, object]:
    target = layout.gemini_dir / 'GEMINI.md'
    if not _inherits_memory(profile):
        _remove_file(target)
        _clear_context_file_name(layout)
        return memory_projection_result(
            status='skipped',
            reason='inherit_memory_disabled',
            path=target,
        )
    if project_root is None or agent_name is None:
        return memory_projection_result(
            status='failed',
            reason='missing_project_context',
            path=target,
        )
    result = materialize_provider_memory_file(
        project_root=project_root,
        agent_name=agent_name,
        provider='gemini',
        target=target,
        provider_memory_path=source_home / '.gemini' / 'GEMINI.md',
        provider_memory_title='Provider User Memory',
        workspace_path=workspace_path,
    )
    if result.get('status') in {'ok', 'skipped'}:
        _ensure_context_file_name(layout)
    return result

def _ensure_context_file_name(layout: GeminiHomeLayout) -> None:
    payload = _read_json_object(layout.settings_path) or {}
    if payload.get('contextFileName') == 'GEMINI.md':
        return
    payload['contextFileName'] = 'GEMINI.md'
    _write_json_object(layout.settings_path, payload)


def _clear_context_file_name(layout: GeminiHomeLayout) -> None:
    payload = _read_json_object(layout.settings_path) or {}
    if payload.get('contextFileName') != 'GEMINI.md':
        return
    payload.pop('contextFileName', None)
    _write_json_object(layout.settings_path, payload)

def _should_project_login_auth(source_settings_path: Path, *, profile) -> bool:
    if not _inherits_auth(profile):
        return False
    selected_type = _selected_auth_type(_read_json_object(source_settings_path))
    return selected_type in {'oauth-personal'}


def _selected_auth_type(payload: dict[str, object] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    security = payload.get('security')
    if not isinstance(security, dict):
        return None
    auth = security.get('auth')
    if not isinstance(auth, dict):
        return None
    raw = str(auth.get('selectedType') or '').strip()
    return raw or None


def _projected_auth_selected_type(selected_type: str | None, *, profile) -> str | None:
    normalized = str(selected_type or '').strip()
    if not normalized:
        return None
    if normalized in {'oauth-personal', 'compute-default-credentials'}:
        return normalized if _inherits_auth(profile) else None
    if normalized in {'gemini-api-key', 'vertex-ai'}:
        return normalized if _inherits_api(profile) else None
    return normalized if (_inherits_api(profile) or _inherits_auth(profile)) else None


def _set_selected_auth_type(payload: dict[str, object], selected_type: str) -> None:
    security = payload.get('security')
    if not isinstance(security, dict):
        security = {}
    auth = security.get('auth')
    if not isinstance(auth, dict):
        auth = {}
    auth['selectedType'] = selected_type
    security['auth'] = auth
    payload['security'] = security


def _clear_selected_auth_type(payload: dict[str, object]) -> None:
    security = payload.get('security')
    if not isinstance(security, dict):
        return
    auth = security.get('auth')
    if isinstance(auth, dict):
        auth.pop('selectedType', None)
        if auth:
            security['auth'] = auth
        else:
            security.pop('auth', None)
    if security:
        payload['security'] = security
    else:
        payload.pop('security', None)


def _sync_file(source: Path, target: Path) -> None:
    if not source.is_file():
        _remove_file(target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except Exception:
        pass


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _system_home_root() -> Path:
    return current_provider_source_home()


__all__ = [
    'materialize_gemini_home_config',
    'prepare_gemini_home_overrides',
    'resolve_gemini_home_layout',
]
