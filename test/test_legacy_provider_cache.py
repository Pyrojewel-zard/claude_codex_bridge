from __future__ import annotations

import json
import os
from pathlib import Path

from cli.services import legacy_provider_cache as cache_service
from project.ids import compute_project_id


def _write(path: Path, text: str = 'payload') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _provider_cache(projects_root: Path, project_root: Path) -> Path:
    project_id = compute_project_id(project_root)
    return projects_root / project_id[:16] / 'provider-cache'


def _manifest(cache_dir: Path, *, provider: str, project_root: Path) -> None:
    project_id = compute_project_id(project_root)
    _write(
        cache_dir / 'MANIFEST.json',
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_external_provider_cache_manifest',
                'provider': provider,
                'project_id': project_id,
                'project_root': str(project_root),
            }
        ),
    )


def test_orphan_sweep_removes_only_manifest_valid_known_providers(tmp_path: Path) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    provider_cache = _provider_cache(projects_root, missing_project)
    for provider in ('claude', 'gemini'):
        cache_dir = provider_cache / provider
        _write(cache_dir / 'payload')
        _manifest(cache_dir, provider=provider, project_root=missing_project)
    unknown = provider_cache / 'other-provider'
    _write(unknown / 'payload')

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(projects_root)

    assert {item.provider for item in summary.removals} == {'claude', 'gemini'}
    assert not (provider_cache / 'claude').exists()
    assert not (provider_cache / 'gemini').exists()
    assert (unknown / 'payload').is_file()
    assert any(item.reason == 'unknown_provider' for item in summary.preserved)


def test_orphan_sweep_preserves_existing_project_cache(tmp_path: Path) -> None:
    projects_root = tmp_path / 'projects'
    existing_project = tmp_path / 'existing-project'
    existing_project.mkdir()
    cache_dir = _provider_cache(projects_root, existing_project) / 'claude'
    _write(cache_dir / 'payload')
    _manifest(cache_dir, provider='claude', project_root=existing_project)

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(projects_root)

    assert not summary.removals
    assert (cache_dir / 'payload').is_file()
    assert summary.preserved[0].reason == 'project_root_exists'
    assert summary.preserved[0].project_root == str(existing_project)


def test_orphan_sweep_validates_each_provider_manifest_independently(tmp_path: Path) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    provider_cache = _provider_cache(projects_root, missing_project)
    claude = provider_cache / 'claude'
    gemini = provider_cache / 'gemini'
    _write(claude / 'payload')
    _manifest(claude, provider='claude', project_root=missing_project)
    _write(gemini / 'payload')
    _write(gemini / 'MANIFEST.json', '{invalid')

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(projects_root)

    assert [item.provider for item in summary.removals] == ['claude']
    assert not claude.exists()
    assert (gemini / 'payload').is_file()
    assert any(
        item.provider == 'gemini' and item.reason == 'manifest_unreadable'
        for item in summary.preserved
    )


def test_orphan_sweep_preserves_symlinked_provider_cache(tmp_path: Path) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    provider_cache = _provider_cache(projects_root, missing_project)
    outside = tmp_path / 'outside'
    _write(outside / 'payload')
    provider_cache.mkdir(parents=True)
    os.symlink(outside, provider_cache / 'claude')

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(projects_root)

    assert not summary.removals
    assert (outside / 'payload').is_file()
    assert summary.preserved[0].reason == 'cache_dir_not_owned_directory'


def test_orphan_sweep_preserves_symlinked_manifest(tmp_path: Path) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    cache_dir = _provider_cache(projects_root, missing_project) / 'claude'
    _write(cache_dir / 'payload')
    outside_manifest = tmp_path / 'outside-manifest.json'
    _manifest(tmp_path, provider='claude', project_root=missing_project)
    (tmp_path / 'MANIFEST.json').replace(outside_manifest)
    os.symlink(outside_manifest, cache_dir / 'MANIFEST.json')

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(projects_root)

    assert not summary.removals
    assert (cache_dir / 'payload').is_file()
    assert summary.preserved[0].reason == 'manifest_not_owned_file'


def test_orphan_sweep_can_skip_expensive_size_walk(tmp_path: Path, monkeypatch) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    cache_dir = _provider_cache(projects_root, missing_project) / 'claude'
    _write(cache_dir / 'payload')
    _manifest(cache_dir, provider='claude', project_root=missing_project)
    monkeypatch.setattr(
        cache_service,
        '_tree_size',
        lambda _path: (_ for _ in ()).throw(AssertionError('size scan must be skipped')),
    )

    summary = cache_service.cleanup_orphaned_legacy_provider_caches(
        projects_root,
        measure_bytes=False,
    )

    assert summary.removed_count == 1
    assert summary.removed_bytes == 0
