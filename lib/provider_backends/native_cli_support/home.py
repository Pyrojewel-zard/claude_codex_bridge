from __future__ import annotations

import json
import os
import platform
import sqlite3
import tempfile
from pathlib import Path

from provider_core.keyring_read import read_keyring_password
from provider_core.one_way_inheritance import (
    copy_regular_file,
    copy_regular_tree,
    ensure_private_descendant_directory,
    ensure_private_directory,
    ensure_private_inheritance_directory,
)
from provider_core.source_home import current_provider_source_home
from storage.atomic import atomic_write_text


def materialize_native_login_state(
    provider: str,
    home_dir: Path,
    *,
    profile=None,
    source_home: Path | None = None,
    data_dir: Path | None = None,
    config_dir: Path | None = None,
) -> Path:
    """Project known native-CLI account files into a private managed HOME."""
    name = str(provider or '').strip().lower()
    ensure_native_provider_storage_isolation(name)
    explicit_source = source_home is not None or bool(os.environ.get('CCB_SOURCE_HOME'))
    source = (
        Path(source_home).expanduser()
        if source_home is not None
        else current_provider_source_home()
    )
    target_home = ensure_private_inheritance_directory(home_dir, source)
    auth_files, config_files, auth_trees = _projection_paths(name)
    if _inherits_auth(profile):
        for source_relative, target_relative in auth_files:
            ensure_private_descendant_directory(target_home, target_relative.parent)
            copy_regular_file(source / source_relative, target_home / target_relative)
        for source_relative, target_relative in auth_trees:
            ensure_private_descendant_directory(target_home, target_relative.parent)
            copy_regular_tree(source / source_relative, target_home / target_relative)
    if _inherits_config(profile):
        for source_relative, target_relative in config_files:
            ensure_private_descendant_directory(target_home, target_relative.parent)
            copy_regular_file(source / source_relative, target_home / target_relative)
    if name == 'crush':
        _materialize_crush_state(
            source,
            target_home=target_home,
            data_dir=data_dir,
            config_dir=config_dir,
            profile=profile,
            use_source_xdg_environment=not explicit_source,
        )
    elif name == 'cursor':
        _materialize_cursor_auth_state(
            source,
            target_home=target_home,
            config_dir=config_dir,
            profile=profile,
            use_source_xdg_environment=not explicit_source,
            inherit_external_keyring=not explicit_source,
        )
    elif name == 'kiro':
        _materialize_kiro_state(
            source,
            target_home=target_home,
            data_dir=data_dir,
            profile=profile,
            use_source_xdg_environment=not explicit_source,
        )
    return target_home


def build_native_private_env(
    home_dir: Path,
    *,
    data_dir: Path | None = None,
    extra_path_env_names: tuple[str, ...] = (),
    extra_raw_env_names: tuple[str, ...] = (),
) -> dict[str, str]:
    """Build a private HOME/XDG/Windows state boundary for a native CLI."""
    home = ensure_private_directory(home_dir)
    data_home = (
        ensure_private_directory(data_dir)
        if data_dir is not None
        else ensure_private_descendant_directory(home, Path('.local') / 'share')
    )
    config_home = ensure_private_descendant_directory(home, Path('.config'))
    state_home = ensure_private_descendant_directory(home, Path('.local') / 'state')
    cache_home = ensure_private_descendant_directory(home, Path('.cache'))
    env = {
        'HOME': str(home),
        'XDG_CONFIG_HOME': str(config_home),
        'XDG_DATA_HOME': str(data_home),
        'XDG_STATE_HOME': str(state_home),
        'XDG_CACHE_HOME': str(cache_home),
    }
    if 'WSL_DISTRO_NAME' in os.environ:
        env.update(
            {
                'USERPROFILE': str(home),
                'APPDATA': str(config_home),
                'LOCALAPPDATA': str(data_home),
            }
        )
        path_names = [
            'HOME',
            'USERPROFILE',
            'APPDATA',
            'LOCALAPPDATA',
            'XDG_CONFIG_HOME',
            'XDG_DATA_HOME',
            'XDG_STATE_HOME',
            'XDG_CACHE_HOME',
        ]
        for name in extra_path_env_names:
            if name and name not in path_names:
                path_names.append(name)
        raw_names = [
            name
            for name in extra_raw_env_names
            if name and name not in path_names
        ]
        additions = ':'.join(
            [
                *(f'{name}/p' for name in path_names),
                *raw_names,
            ]
        )
        existing = os.environ.get('WSLENV', '')
        env['WSLENV'] = f'{additions}:{existing}' if existing else additions
    return env


def _materialize_crush_state(
    source_home: Path,
    *,
    target_home: Path,
    data_dir: Path | None,
    config_dir: Path | None,
    profile,
    use_source_xdg_environment: bool,
) -> None:
    target_data = ensure_private_directory(data_dir or target_home / '.local' / 'share')
    target_config = ensure_private_directory(config_dir or target_home / '.config')
    source_data = _source_xdg_root(
        source_home,
        env_name='XDG_DATA_HOME',
        default_relative=Path('.local') / 'share',
        use_environment=use_source_xdg_environment,
    )
    source_config = _source_xdg_root(
        source_home,
        env_name='XDG_CONFIG_HOME',
        default_relative=Path('.config'),
        use_environment=use_source_xdg_environment,
    )
    if _inherits_auth(profile):
        # Crush stores provider API keys beside provider metadata.  Do not copy
        # projects.json because it contains source-workspace/session pointers.
        for name in ('providers.json', 'hyper.json'):
            copy_regular_file(source_data / 'crush' / name, target_data / name)
    if _inherits_config(profile):
        ensure_private_descendant_directory(target_config, Path('crush'))
        copy_regular_file(
            source_config / 'crush' / 'crush.json',
            target_config / 'crush' / 'crush.json',
        )


def _materialize_cursor_auth_state(
    source_home: Path,
    *,
    target_home: Path,
    config_dir: Path | None,
    profile,
    use_source_xdg_environment: bool,
    inherit_external_keyring: bool,
) -> None:
    if not _inherits_auth(profile):
        return
    target_config = ensure_private_directory(config_dir or target_home / '.config')
    source_config = _source_xdg_root(
        source_home,
        env_name='XDG_CONFIG_HOME',
        default_relative=Path('.config'),
        use_environment=use_source_xdg_environment,
    )
    # Linux file-store path. macOS uses ~/.cursor/auth.json, which is already
    # in the ordinary projection list below. Windows file mode uses
    # %APPDATA%/Cursor/auth.json; support its default source layout as well.
    ensure_private_descendant_directory(target_config, Path('cursor'))
    copy_regular_file(
        source_config / 'cursor' / 'auth.json',
        target_config / 'cursor' / 'auth.json',
    )
    ensure_private_descendant_directory(target_config, Path('Cursor'))
    copy_regular_file(
        source_home / 'AppData' / 'Roaming' / 'Cursor' / 'auth.json',
        target_config / 'Cursor' / 'auth.json',
    )
    if inherit_external_keyring:
        _materialize_cursor_macos_keychain_auth(target_home)


def _materialize_cursor_macos_keychain_auth(target_home: Path) -> None:
    if platform.system() != 'Darwin':
        return
    target_dir = ensure_private_descendant_directory(target_home, Path('.cursor'))
    target_auth = target_dir / 'auth.json'
    if target_auth.is_symlink():
        target_auth.unlink()
    if target_auth.is_file():
        return

    account = 'cursor-user'
    keyring_fields = (
        ('cursor-access-token', 'accessToken'),
        ('cursor-refresh-token', 'refreshToken'),
        ('cursor-api-key', 'apiKey'),
        ('cursor-bedrock-access-key', 'accessKey'),
        ('cursor-bedrock-secret-key', 'secretKey'),
        ('cursor-bedrock-session-token', 'sessionToken'),
    )
    values = {
        field: read_keyring_password(
            service,
            account,
            command_name='agent',
            module_names=('@github/keytar', 'keytar'),
        )
        for service, field in keyring_fields
    }
    payload: dict[str, object] = {
        field: value
        for field, value in values.items()
        if field in {'accessToken', 'refreshToken', 'apiKey'}
        and str(value or '').strip()
    }
    access_key = values.get('accessKey')
    secret_key = values.get('secretKey')
    if str(access_key or '').strip() and str(secret_key or '').strip():
        payload['bedrockCredentials'] = {
            field: values[field]
            for field in ('accessKey', 'secretKey', 'sessionToken')
            if str(values.get(field) or '').strip()
        }
    if not payload:
        return
    atomic_write_text(
        target_auth,
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
    )


def _materialize_kiro_state(
    source_home: Path,
    *,
    target_home: Path,
    data_dir: Path | None,
    profile,
    use_source_xdg_environment: bool,
) -> None:
    inherit_auth = _inherits_auth(profile)
    inherit_config = _inherits_config(profile)
    if not inherit_auth and not inherit_config:
        return
    source_data = _source_xdg_root(
        source_home,
        env_name='XDG_DATA_HOME',
        default_relative=Path('.local') / 'share',
        use_environment=use_source_xdg_environment,
    )
    target_data = ensure_private_directory(data_dir or target_home / '.local' / 'share')
    source_candidates = (
        source_data / 'kiro-cli' / 'data.sqlite3',
        # Kiro CLI migrates the earlier Amazon Q CLI database. Accept it as a
        # read-only inheritance source when the current database is absent.
        source_data / 'amazon-q' / 'data.sqlite3',
        source_home / 'AppData' / 'Local' / 'kiro-cli' / 'data.sqlite3',
    )
    source_database = next(
        (path for path in source_candidates if path.is_file() and not path.is_symlink()),
        None,
    )
    if source_database is None:
        return
    ensure_private_descendant_directory(target_data, Path('kiro-cli'))
    _copy_kiro_database_projection(
        source_database,
        target_data / 'kiro-cli' / 'data.sqlite3',
        inherit_auth=inherit_auth,
        inherit_config=inherit_config,
    )


def _copy_kiro_database_projection(
    source: Path,
    target: Path,
    *,
    inherit_auth: bool,
    inherit_config: bool,
) -> bool:
    """Snapshot Kiro's mixed state database without touching its live source."""
    src = Path(source).expanduser()
    dst = Path(target).expanduser()
    if not src.is_file() or src.is_symlink():
        return False
    if Path(os.path.abspath(src)) == Path(os.path.abspath(dst)):
        return False
    ensure_private_directory(dst.parent)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{dst.name}.ccb-',
        dir=str(dst.parent),
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            f'{src.absolute().as_uri()}?mode=ro',
            uri=True,
        )
        source_connection.execute('PRAGMA query_only = ON')
        target_connection = sqlite3.connect(str(temporary_path))
        source_connection.backup(target_connection)
        allowed_tables = {'migrations'}
        if inherit_auth:
            allowed_tables.add('auth_kv')
        if inherit_config:
            allowed_tables.add('state')
        tables = [
            str(row[0])
            for row in target_connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if row and str(row[0] or '').strip()
        ]
        with target_connection:
            for table in tables:
                if table in allowed_tables or table.startswith('sqlite_'):
                    continue
                quoted_table = '"' + table.replace('"', '""') + '"'
                target_connection.execute(f'DELETE FROM {quoted_table}')
        target_connection.close()
        target_connection = None
        source_connection.close()
        source_connection = None
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, dst)
        return True
    except (OSError, sqlite3.Error):
        return False
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _source_xdg_root(
    source_home: Path,
    *,
    env_name: str,
    default_relative: Path,
    use_environment: bool,
) -> Path:
    if use_environment:
        raw = str(os.environ.get(env_name) or '').strip()
        if raw:
            try:
                return Path(raw).expanduser()
            except Exception:
                pass
    return Path(source_home).expanduser() / default_relative


def _projection_paths(
    provider: str,
) -> tuple[
    tuple[tuple[Path, Path], ...],
    tuple[tuple[Path, Path], ...],
    tuple[tuple[Path, Path], ...],
]:
    if provider == 'cursor':
        return (
            tuple(
                (Path('.cursor') / name, Path('.cursor') / name)
                for name in ('auth.json', 'credentials.json')
            ),
            ((Path('.cursor') / 'cli-config.json', Path('.cursor') / 'cli-config.json'),),
            (),
        )
    if provider == 'kiro':
        return (
            (
                (Path('.kiro') / 'auth.json', Path('.kiro') / 'auth.json'),
                (Path('.kiro') / 'credentials.json', Path('.kiro') / 'credentials.json'),
                (Path('.aws') / 'credentials', Path('.aws') / 'credentials'),
            ),
            (
                (Path('.kiro') / 'config.json', Path('.kiro') / 'config.json'),
                (
                    Path('.kiro') / 'settings' / 'cli.json',
                    Path('.kiro') / 'settings' / 'cli.json',
                ),
                (Path('.aws') / 'config', Path('.aws') / 'config'),
            ),
            ((Path('.aws') / 'sso' / 'cache', Path('.aws') / 'sso' / 'cache'),),
        )
    if provider == 'zai':
        return (
            tuple(
                (Path('.zai') / name, Path('.zai') / name)
                for name in (
                    'auth.json',
                    'credentials.json',
                    'config.json',
                    # Current zai-cli stores apiKey/baseURL together with
                    # preferences in this file.
                    'user-settings.json',
                )
            ),
            (),
            (),
        )
    if provider == 'pi':
        return (
            tuple(
                (Path('.pi') / 'agent' / name, Path(name))
                for name in ('auth.json', 'oauth.json')
            ),
            tuple(
                (Path('.pi') / 'agent' / name, Path(name))
                for name in ('models.json', 'settings.json')
            ),
            (),
        )
    if provider == 'omp':
        return (
            tuple(
                (Path('.omp') / 'agent' / name, Path('.omp') / 'agent' / name)
                for name in ('auth.json', 'oauth.json')
            ),
            tuple(
                (Path('.omp') / 'agent' / name, Path('.omp') / 'agent' / name)
                for name in ('models.json', 'settings.json')
            ),
            (),
        )
    if provider in {'qoder', 'qoderclicn'}:
        source_root = Path('.qoder-cn') if provider == 'qoderclicn' else Path('.qoder')
        return (
            (),
            (),
            ((source_root / '.auth', Path('.auth')),),
        )
    return (), (), ()


def ensure_native_provider_storage_isolation(provider: str) -> None:
    if provider == 'kiro' and platform.system() == 'Darwin':
        raise RuntimeError(
            'managed Kiro is unavailable on macOS: the current Kiro CLI writes '
            'login state through the global macOS Keychain and exposes no '
            'private file-storage switch'
        )


def _inherits_auth(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_auth', True))


def _inherits_config(profile) -> bool:
    return True if profile is None else bool(getattr(profile, 'inherit_config', True))


__all__ = [
    'build_native_private_env',
    'ensure_native_provider_storage_isolation',
    'materialize_native_login_state',
]
