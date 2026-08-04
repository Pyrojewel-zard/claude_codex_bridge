from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path

from provider_core.source_home import current_provider_source_home
from provider_profiles import provider_api_env_keys
from storage.atomic import atomic_write_text


_AUTHORITY_KEY_NAME = '.ccb-authority-hmac-key'
_AUTH_FILES: dict[str, tuple[str, ...]] = {
    'claude': (
        '.config/claude-code/auth.json',
        '.claude/.credentials.json',
    ),
    'gemini': (
        '.gemini/oauth_creds.json',
        '.gemini/google_accounts.json',
        '.gemini/gemini-credentials.json',
        '.gemini/mcp-oauth-tokens.json',
        '.gemini/a2a-oauth-tokens.json',
    ),
}
_AUTH_METADATA_FILES: dict[str, tuple[str, ...]] = {
    'claude': ('.claude.json', '.claude/.claude.json'),
    'gemini': ('.gemini/settings.json',),
}
_API_FILES: dict[str, tuple[str, ...]] = {
    'claude': ('.claude/settings.json',),
    'gemini': ('.gemini/.env',),
}


def current_provider_authority_fingerprint(provider: str, profile, runtime_dir: Path) -> str:
    """Return an agent-private, non-portable authority fingerprint.

    The persisted value is an HMAC, never a raw credential or a portable hash.
    It changes when the selected profile, API route/env, or inherited auth files
    change, which makes provider conversation restore fail closed across an
    account or API switch.
    """
    provider_name = str(provider or '').strip().lower()
    runtime = Path(runtime_dir).expanduser()
    state_dir = runtime.parent.parent / 'provider-state' / provider_name
    state_dir.mkdir(parents=True, exist_ok=True)
    key_path = state_dir / _AUTHORITY_KEY_NAME
    key = _load_or_create_key(key_path)

    inherit_api = bool(getattr(profile, 'inherit_api', True))
    inherit_auth = bool(getattr(profile, 'inherit_auth', True))
    source_home = current_provider_source_home()
    managed_home = _managed_home(runtime, profile, provider_name)
    api_keys = set(provider_api_env_keys(provider_name))
    payload = {
        'provider': provider_name,
        'profile': _profile_record(profile),
        'api_env': {
            name: str(os.environ.get(name) or '')
            for name in sorted(api_keys)
        } if inherit_api else {},
        'source_auth': _auth_file_payload(source_home, provider_name) if inherit_auth else {},
        'managed_auth': _auth_file_payload(managed_home, provider_name) if not inherit_auth else {},
        'source_auth_metadata': _metadata_file_payload(source_home, provider_name) if inherit_auth else {},
        'managed_auth_metadata': _metadata_file_payload(managed_home, provider_name) if not inherit_auth else {},
        'source_api_files': _api_file_payload(source_home, provider_name) if inherit_api else {},
        'managed_api_files': _api_file_payload(managed_home, provider_name) if not inherit_api else {},
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()[:32]


def stored_provider_authority_fingerprint(data: Mapping[str, object], provider: str) -> str:
    return str(data.get(f'{str(provider).strip().lower()}_provider_authority_fingerprint') or '').strip()


def provider_authority_matches(data: Mapping[str, object], provider: str, current: str) -> bool:
    stored = stored_provider_authority_fingerprint(data, provider)
    return bool(stored and current and hmac.compare_digest(stored, current))


def _profile_record(profile) -> dict[str, object]:
    if profile is None:
        return {}
    return {
        'provider': str(getattr(profile, 'provider', '') or ''),
        'agent_name': str(getattr(profile, 'agent_name', '') or ''),
        'mode': str(getattr(profile, 'mode', '') or ''),
        'runtime_home': str(getattr(profile, 'runtime_home', '') or ''),
        'env': dict(getattr(profile, 'env', {}) or {}),
        'inherit_api': bool(getattr(profile, 'inherit_api', True)),
        'inherit_auth': bool(getattr(profile, 'inherit_auth', True)),
        'inherit_config': bool(getattr(profile, 'inherit_config', True)),
    }


def _managed_home(runtime_dir: Path, profile, provider: str) -> Path:
    explicit = str(getattr(profile, 'runtime_home', '') or '').strip()
    if explicit:
        return Path(explicit).expanduser()
    return runtime_dir.parent.parent / 'provider-state' / provider / 'home'


def _auth_file_payload(root: Path, provider: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for relative in _AUTH_FILES.get(provider, ()):
        path = Path(root).expanduser() / relative
        try:
            if path.is_file():
                payload[relative] = path.read_bytes().hex()
        except OSError:
            continue
    return payload


def _metadata_file_payload(root: Path, provider: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    for relative in _AUTH_METADATA_FILES.get(provider, ()):
        path = Path(root).expanduser() / relative
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            continue
        if provider == 'claude' and relative in {'.claude.json', '.claude/.claude.json'}:
            selected = {key: data.get(key) for key in ('oauthAccount', 'primaryApiKey') if key in data}
        elif provider == 'gemini' and relative == '.gemini/settings.json':
            security = data.get('security') if isinstance(data, dict) else None
            auth = security.get('auth') if isinstance(security, dict) else None
            selected = (
                {'selectedType': auth.get('selectedType')}
                if isinstance(auth, dict) and 'selectedType' in auth
                else {}
            )
        else:
            selected = {}
        if selected:
            payload[relative] = selected
    return payload


def _api_file_payload(root: Path, provider: str) -> dict[str, object]:
    payload: dict[str, object] = {}
    allowed = provider_api_env_keys(provider)
    for relative in _API_FILES.get(provider, ()):
        path = Path(root).expanduser() / relative
        if relative.endswith('settings.json'):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                continue
            env = data.get('env') if isinstance(data, dict) else None
            selected = {
                str(key): str(value)
                for key, value in dict(env or {}).items()
                if str(key) in allowed
            }
        elif relative.endswith('.env'):
            selected = _selected_dotenv_values(path, allowed=allowed)
        else:
            selected = {}
        if selected:
            payload[relative] = selected
    return payload


def _selected_dotenv_values(path: Path, *, allowed: set[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    selected: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        normalized_key = key.strip()
        if separator and normalized_key in allowed:
            selected[normalized_key] = value.strip()
    return selected


def _load_or_create_key(path: Path) -> bytes:
    try:
        key = bytes.fromhex(path.read_text(encoding='ascii').strip())
        if len(key) >= 32:
            return key
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    atomic_write_text(path, key.hex() + '\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


__all__ = [
    'current_provider_authority_fingerprint',
    'provider_authority_matches',
    'stored_provider_authority_fingerprint',
]
