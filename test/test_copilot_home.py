from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.services.role_command_policy import RoleCommandPolicy
import provider_backends.copilot.home as copilot_home
from provider_backends.copilot.home import materialize_copilot_home_config
from provider_core.projected_assets import tree_content_fingerprint
from provider_profiles.models import ProviderProfileSpec


_HEADER = '// User settings belong in settings.json.\n// This file is managed automatically.\n'


def _write_config(home: Path, payload: dict[str, object], *, header: str = _HEADER) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / 'config.json'
    path.write_text(header + json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def _read_config(home: Path) -> dict[str, object]:
    text = (home / 'config.json').read_text(encoding='utf-8')
    return json.loads(text[text.index('{'):])


def _write_plugin(
    source_home: Path,
    *,
    name: str = 'fixture-plugin',
    marketplace: str = 'fixture-marketplace',
    direct_id: str | None = None,
    version: str = '1.0.0',
    content: str = 'source skill\n',
) -> tuple[dict[str, object], Path]:
    if marketplace:
        relative = Path(marketplace) / name
    else:
        relative = Path('_direct') / (direct_id or name)
    plugin_dir = source_home / 'installed-plugins' / relative
    skill = plugin_dir / 'skills' / 'fixture-skill' / 'SKILL.md'
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(content, encoding='utf-8')
    (plugin_dir / 'plugin.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': version,
                'skills': ['./skills/fixture-skill'],
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )
    entry: dict[str, object] = {
        'name': name,
        'marketplace': marketplace,
        'version': version,
        'installed_at': f'2026-07-21T00:00:0{version[-1]}Z',
        'enabled': True,
        'cache_path': str(plugin_dir),
        'source': {'source': 'local', 'path': '/source/descriptor/must-not-copy'},
        'unknown': 'must-not-copy',
    }
    return entry, plugin_dir


def _projected_entry(home: Path, *, name: str = 'fixture-plugin') -> dict[str, object]:
    entries = _read_config(home).get('installedPlugins')
    assert isinstance(entries, list)
    return next(entry for entry in entries if isinstance(entry, dict) and entry.get('name') == name)


def _aggregate_marker(home: Path) -> Path:
    return home / '.ccb-installed-plugins-projection.json'


def _tree_marker(plugin_dir: Path) -> Path:
    return Path(f'{plugin_dir}.ccb-projection.json')


def _hard_role_policy(tmp_path: Path) -> RoleCommandPolicy:
    return RoleCommandPolicy(
        role_id='test.hard',
        path=tmp_path / 'command-surface.toml',
        mode='deny_all_except',
        enforcement='required',
        if_unsupported='fail_mount',
        generic_shell=False,
        generic_ccb=False,
        supported_providers=('claude',),
        provider_tools=(),
        allowed_effects=(),
        forbidden_effects=(),
        allowed=(),
    )


def test_materialize_copilot_projects_only_plugin_entries_and_local_tree(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, source_plugin = _write_plugin(source_home)
    _write_config(
        source_home,
        {
            'installedPlugins': [entry],
            'loggedInUsers': [{'host': 'source.invalid', 'login': 'source-user'}],
            'copilotTokens': {'source.invalid': 'not-copied'},
            'trustedFolders': ['/source-only'],
        },
    )
    (source_home / 'settings.json').write_text(
        '{"enabledPlugins":{"source-only":true}}\n',
        encoding='utf-8',
    )
    target_payload = {
        'loggedInUsers': [{'host': 'target.invalid', 'login': 'target-user'}],
        'trustedFolders': ['/target-only'],
        'installedPlugins': [
            {
                'name': 'user-plugin',
                'marketplace': 'user-marketplace',
                'installed_at': '2026-07-20T00:00:00Z',
                'enabled': False,
                'cache_path': '/user/owned/plugin',
            }
        ],
    }
    _write_config(target_home, target_payload)
    protected = {
        target_home / 'settings.json': '{"theme":"dark"}\n',
        target_home / 'permissions-config.json': '{"approved":true}\n',
        target_home / 'session-state/session/events.jsonl': '{}\n',
        target_home / 'plugin-data/user/data.txt': 'local plugin data\n',
    }
    for path, text in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    source_hash = tree_content_fingerprint(source_home)

    materialize_copilot_home_config(target_home, source_home=source_home)

    payload = _read_config(target_home)
    assert payload['loggedInUsers'] == target_payload['loggedInUsers']
    assert payload['trustedFolders'] == target_payload['trustedFolders']
    assert 'copilotTokens' not in payload
    entries = payload['installedPlugins']
    assert isinstance(entries, list) and len(entries) == 2
    projected = _projected_entry(target_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    assert projected == {
        'name': 'fixture-plugin',
        'marketplace': 'fixture-marketplace',
        'version': '1.0.0',
        'installed_at': '2026-07-21T00:00:00Z',
        'enabled': True,
        'cache_path': str(target_plugin),
    }
    assert target_plugin.is_dir() and not target_plugin.is_symlink()
    assert (target_plugin / 'skills/fixture-skill/SKILL.md').read_text(encoding='utf-8') == 'source skill\n'
    assert _aggregate_marker(target_home).is_file()
    assert _tree_marker(target_plugin).is_file()
    for path, text in protected.items():
        assert path.read_text(encoding='utf-8') == text
    assert tree_content_fingerprint(source_home) == source_hash
    assert source_plugin.is_dir()


def test_materialize_copilot_supports_direct_entries_and_two_agent_isolation(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    entry, source_plugin = _write_plugin(source_home, marketplace='', direct_id='source-id')
    _write_config(source_home, {'installedPlugins': [entry]})
    first = tmp_path / 'agent-1-home'
    second = tmp_path / 'agent-2-home'

    materialize_copilot_home_config(first, source_home=source_home)
    materialize_copilot_home_config(second, source_home=source_home)

    first_plugin = first / 'installed-plugins/_direct/source-id'
    second_plugin = second / 'installed-plugins/_direct/source-id'
    assert _projected_entry(first)['cache_path'] == str(first_plugin)
    assert _projected_entry(second)['cache_path'] == str(second_plugin)
    assert first_plugin.is_dir() and second_plugin.is_dir()
    assert not first_plugin.is_symlink() and not second_plugin.is_symlink()
    (first_plugin / 'skills/fixture-skill/SKILL.md').write_text('agent one local\n', encoding='utf-8')
    assert (second_plugin / 'skills/fixture-skill/SKILL.md').read_text(encoding='utf-8') == 'source skill\n'
    assert (source_plugin / 'skills/fixture-skill/SKILL.md').read_text(encoding='utf-8') == 'source skill\n'


def test_materialize_copilot_is_idempotent_when_source_is_unchanged(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    materialize_copilot_home_config(target_home, source_home=source_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    tracked = (
        target_home / 'config.json',
        _aggregate_marker(target_home),
        _tree_marker(target_plugin),
        target_plugin / 'skills/fixture-skill/SKILL.md',
    )
    snapshots = {
        path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in tracked
    }

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert {
        path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in tracked
    } == snapshots


def test_materialize_copilot_metadata_refresh_does_not_recopy_unchanged_tree(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    materialize_copilot_home_config(target_home, source_home=source_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    tree_marker = _tree_marker(target_plugin)
    skill = target_plugin / 'skills/fixture-skill/SKILL.md'
    tree_snapshot = (
        tree_marker.read_bytes(),
        tree_marker.stat().st_ino,
        tree_marker.stat().st_mtime_ns,
        skill.read_bytes(),
        skill.stat().st_ino,
        skill.stat().st_mtime_ns,
    )
    refreshed = dict(entry)
    refreshed['version'] = '2.0.0'
    refreshed['installed_at'] = '2026-07-21T00:00:02Z'
    _write_config(source_home, {'installedPlugins': [refreshed]})

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert _projected_entry(target_home)['version'] == '2.0.0'
    assert (
        tree_marker.read_bytes(),
        tree_marker.stat().st_ino,
        tree_marker.stat().st_mtime_ns,
        skill.read_bytes(),
        skill.stat().st_ino,
        skill.stat().st_mtime_ns,
    ) == tree_snapshot


def test_materialize_copilot_refreshes_and_removes_only_owned_entry(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, source_plugin = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    _write_config(target_home, {'staff': False})
    materialize_copilot_home_config(target_home, source_home=source_home)

    updated = dict(entry)
    updated['version'] = '2.0.0'
    updated['installed_at'] = '2026-07-21T00:00:02Z'
    (source_plugin / 'skills/fixture-skill/SKILL.md').write_text('updated source\n', encoding='utf-8')
    _write_config(source_home, {'installedPlugins': [updated]})
    materialize_copilot_home_config(target_home, source_home=source_home)

    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    assert _projected_entry(target_home)['version'] == '2.0.0'
    assert (target_plugin / 'skills/fixture-skill/SKILL.md').read_text(encoding='utf-8') == 'updated source\n'

    (source_home / 'config.json').unlink()
    before = tree_content_fingerprint(target_home)
    materialize_copilot_home_config(target_home, source_home=source_home)
    assert tree_content_fingerprint(target_home) == before

    _write_config(source_home, {'loggedInUsers': []})
    materialize_copilot_home_config(target_home, source_home=source_home)
    assert tree_content_fingerprint(target_home) == before

    _write_config(source_home, {'installedPlugins': []})
    materialize_copilot_home_config(target_home, source_home=source_home)
    assert _read_config(target_home) == {'staff': False}
    assert not target_plugin.exists()
    assert not _tree_marker(target_plugin).exists()
    assert not _aggregate_marker(target_home).exists()


@pytest.mark.parametrize('disable_kind', ('profile', 'hard-role'))
def test_materialize_copilot_explicit_opt_out_removes_only_owned_state(
    tmp_path: Path,
    disable_kind: str,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    _write_config(target_home, {'trustedFolders': ['/keep']})
    materialize_copilot_home_config(target_home, source_home=source_home)

    kwargs = (
        {'profile': ProviderProfileSpec(inherit_config=False)}
        if disable_kind == 'profile'
        else {'command_policy': _hard_role_policy(tmp_path)}
    )
    materialize_copilot_home_config(target_home, source_home=source_home, **kwargs)

    assert _read_config(target_home) == {'trustedFolders': ['/keep']}
    assert not (target_home / 'installed-plugins/fixture-marketplace/fixture-plugin').exists()
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_preserves_diverged_entry_and_relinquishes_tree(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    materialize_copilot_home_config(target_home, source_home=source_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'

    payload = _read_config(target_home)
    projected = payload['installedPlugins'][0]
    projected['enabled'] = False
    projected['localNote'] = 'user takeover'
    _write_config(target_home, payload)
    local_skill = target_plugin / 'skills/fixture-skill/SKILL.md'
    local_skill.write_text('user local\n', encoding='utf-8')
    _write_config(source_home, {'installedPlugins': []})

    materialize_copilot_home_config(target_home, source_home=source_home)
    materialize_copilot_home_config(target_home, source_home=source_home)

    assert _projected_entry(target_home)['localNote'] == 'user takeover'
    assert local_skill.read_text(encoding='utf-8') == 'user local\n'
    assert not _tree_marker(target_plugin).exists()
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_preserves_locally_changed_tree_and_relinquishes_ownership(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    materialize_copilot_home_config(target_home, source_home=source_home)
    original_entry = _projected_entry(target_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    local_skill = target_plugin / 'skills/fixture-skill/SKILL.md'
    local_skill.write_text('user local\n', encoding='utf-8')

    refreshed = dict(entry)
    refreshed['version'] = '2.0.0'
    refreshed['installed_at'] = '2026-07-21T00:00:02Z'
    _write_config(source_home, {'installedPlugins': [refreshed]})
    materialize_copilot_home_config(target_home, source_home=source_home)

    assert _projected_entry(target_home) == original_entry
    assert local_skill.read_text(encoding='utf-8') == 'user local\n'
    assert not _tree_marker(target_plugin).exists()
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_metadata_deletion_creates_persistent_local_opt_out(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    _write_config(target_home, {'staff': False})
    materialize_copilot_home_config(target_home, source_home=source_home)
    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'

    _write_config(target_home, {'staff': False})
    materialize_copilot_home_config(target_home, source_home=source_home)
    materialize_copilot_home_config(target_home, source_home=source_home)

    assert _read_config(target_home) == {'staff': False}
    assert not target_plugin.exists()
    marker = json.loads(_aggregate_marker(target_home).read_text(encoding='utf-8'))
    assert next(iter(marker['managed'].values()))['suppressed'] is True

    _write_config(source_home, {'installedPlugins': []})
    materialize_copilot_home_config(target_home, source_home=source_home)
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_preserves_unmarked_conflicting_tree(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    conflict = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    conflict.mkdir(parents=True)
    (conflict / 'user.txt').write_text('user owned\n', encoding='utf-8')

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert (conflict / 'user.txt').read_text(encoding='utf-8') == 'user owned\n'
    assert not (target_home / 'config.json').exists()
    assert not _aggregate_marker(target_home).exists()
    assert not _tree_marker(conflict).exists()


@pytest.mark.parametrize('failure_kind', ('malformed-list', 'escape', 'root-symlink', 'nested-symlink'))
def test_materialize_copilot_rejects_malformed_or_escaping_source(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, plugin_dir = _write_plugin(source_home)
    payload: dict[str, object] = {'installedPlugins': [entry]}
    if failure_kind == 'malformed-list':
        payload['installedPlugins'] = {'bad': True}
    elif failure_kind == 'escape':
        outside = tmp_path / 'outside-plugin'
        outside.mkdir()
        (outside / 'plugin.json').write_text('{}\n', encoding='utf-8')
        entry['cache_path'] = str(outside)
    elif failure_kind == 'root-symlink':
        real = tmp_path / 'real-plugin'
        plugin_dir.rename(real)
        plugin_dir.symlink_to(real, target_is_directory=True)
    elif failure_kind == 'nested-symlink':
        (plugin_dir / 'escape').symlink_to(tmp_path, target_is_directory=True)
    _write_config(source_home, payload)

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert not (target_home / 'config.json').exists()
    assert not (target_home / 'installed-plugins').exists()
    assert not _aggregate_marker(target_home).exists()


@pytest.mark.parametrize('marker_kind', ('foreign', 'malformed', 'symlink'))
def test_materialize_copilot_foreign_aggregate_marker_blocks_all_mutation(
    tmp_path: Path,
    marker_kind: str,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    target_home.mkdir()
    marker = _aggregate_marker(target_home)
    if marker_kind == 'foreign':
        marker.write_text('{"record_type":"foreign"}\n', encoding='utf-8')
    elif marker_kind == 'malformed':
        marker.write_text('{broken\n', encoding='utf-8')
    else:
        foreign = tmp_path / 'foreign-marker.json'
        foreign.write_text('{}\n', encoding='utf-8')
        marker.symlink_to(foreign)
    marker_bytes = marker.read_bytes()

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert marker.read_bytes() == marker_bytes
    assert not (target_home / 'config.json').exists()
    assert not (target_home / 'installed-plugins').exists()


def test_materialize_copilot_malformed_target_config_fails_closed(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    target_home.mkdir()
    target_config = target_home / 'config.json'
    target_config.write_text('// header\n{broken\n', encoding='utf-8')

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert target_config.read_text(encoding='utf-8') == '// header\n{broken\n'
    assert not (target_home / 'installed-plugins').exists()


def test_materialize_copilot_malformed_target_entry_fails_closed(tmp_path: Path) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    original = _write_config(target_home, {'installedPlugins': [{'name': 'missing-marketplace'}]})
    original_text = original.read_text(encoding='utf-8')

    materialize_copilot_home_config(target_home, source_home=source_home)

    assert original.read_text(encoding='utf-8') == original_text
    assert not (target_home / 'installed-plugins').exists()
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_rolls_back_tree_config_and_markers_on_commit_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [entry]})
    original = _write_config(target_home, {'staff': False}).read_text(encoding='utf-8')
    real_atomic_write = copilot_home.atomic_write_text

    def fail_aggregate(path, text):
        if Path(path).name == '.ccb-installed-plugins-projection.json':
            raise OSError('aggregate marker denied')
        return real_atomic_write(path, text)

    monkeypatch.setattr(copilot_home, 'atomic_write_text', fail_aggregate)

    materialize_copilot_home_config(target_home, source_home=source_home)

    target_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    assert (target_home / 'config.json').read_text(encoding='utf-8') == original
    assert not target_plugin.exists()
    assert not _tree_marker(target_plugin).exists()
    assert not _aggregate_marker(target_home).exists()


def test_materialize_copilot_rollback_preserves_abandoned_local_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_home = tmp_path / 'source-home'
    target_home = tmp_path / 'target-home'
    first_entry, _ = _write_plugin(source_home)
    _write_config(source_home, {'installedPlugins': [first_entry]})
    materialize_copilot_home_config(target_home, source_home=source_home)
    first_plugin = target_home / 'installed-plugins/fixture-marketplace/fixture-plugin'
    local_skill = first_plugin / 'skills/fixture-skill/SKILL.md'
    local_skill.write_text('user local\n', encoding='utf-8')
    target_payload = _read_config(target_home)
    target_payload['installedPlugins'][0]['enabled'] = False
    _write_config(target_home, target_payload)
    original_config = (target_home / 'config.json').read_text(encoding='utf-8')
    original_aggregate = _aggregate_marker(target_home).read_text(encoding='utf-8')
    original_tree_marker = _tree_marker(first_plugin).read_text(encoding='utf-8')

    second_entry, _ = _write_plugin(source_home, name='second-plugin')
    _write_config(source_home, {'installedPlugins': [first_entry, second_entry]})
    real_atomic_write = copilot_home.atomic_write_text

    def fail_aggregate(path, text):
        if Path(path).name == '.ccb-installed-plugins-projection.json':
            raise OSError('aggregate marker denied')
        return real_atomic_write(path, text)

    monkeypatch.setattr(copilot_home, 'atomic_write_text', fail_aggregate)
    materialize_copilot_home_config(target_home, source_home=source_home)

    second_plugin = target_home / 'installed-plugins/fixture-marketplace/second-plugin'
    assert (target_home / 'config.json').read_text(encoding='utf-8') == original_config
    assert _aggregate_marker(target_home).read_text(encoding='utf-8') == original_aggregate
    assert _tree_marker(first_plugin).read_text(encoding='utf-8') == original_tree_marker
    assert local_skill.read_text(encoding='utf-8') == 'user local\n'
    assert not second_plugin.exists()
    assert not _tree_marker(second_plugin).exists()
