from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from io import StringIO

from cli.management_runtime import provider_cache_cleanup as migration
from project.ids import compute_project_id


def _write(path: Path, text: str = 'payload') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _orphan_cache(projects_root: Path, project_root: Path, provider: str) -> Path:
    project_id = compute_project_id(project_root)
    cache_dir = projects_root / project_id[:16] / 'provider-cache' / provider
    _write(cache_dir / 'payload')
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
    return cache_dir


def test_post_update_migration_removes_orphans_and_records_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projects_root = tmp_path / 'projects'
    state_path = tmp_path / 'state' / 'provider-cache-cleanup.json'
    orphan = _orphan_cache(projects_root, tmp_path / 'deleted-project', 'claude')
    output = StringIO()
    monkeypatch.setenv('CCB_LANG', 'en')

    summary = migration.run_post_update_provider_cache_cleanup(
        from_version='8.3.0',
        to_version='8.4.0',
        cwd=tmp_path,
        stdout=output,
        projects_root=projects_root,
        state_path=state_path,
    )

    assert summary.status == 'complete'
    assert summary.removed_count == 1
    assert not orphan.exists()
    payload = json.loads(state_path.read_text(encoding='utf-8'))
    assert payload['migration_id'] == migration.MIGRATION_ID
    assert payload['from_version'] == '8.3.0'
    assert payload['to_version'] == '8.4.0'
    assert payload['removed_cache_count'] == 1
    assert 'safely removed 1' in output.getvalue()


def test_post_update_migration_cleans_stopped_current_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'project'
    (project_root / '.ccb').mkdir(parents=True)
    state_path = tmp_path / 'state' / 'provider-cache-cleanup.json'
    calls: list[object] = []
    cleanup_summary = SimpleNamespace(
        actions=(SimpleNamespace(kind='legacy_project_cache'),),
        skipped=(),
    )
    monkeypatch.setattr(migration, 'current_project_legacy_provider_cache_present', lambda _layout: True)
    monkeypatch.setattr(
        migration,
        'cleanup_current_project_legacy_provider_caches',
        lambda context, *, measure_bytes: calls.append((context, measure_bytes)) or cleanup_summary,
    )
    monkeypatch.setattr(
        migration,
        'CliContextBuilder',
        lambda: SimpleNamespace(
            build=lambda command, cwd: SimpleNamespace(command=command, cwd=cwd),
        ),
    )

    summary = migration.run_post_update_provider_cache_cleanup(
        cwd=project_root,
        projects_root=tmp_path / 'projects',
        state_path=state_path,
        stdout=StringIO(),
    )

    assert summary.status == 'complete'
    assert summary.removed_count == 1
    assert len(calls) == 1
    assert calls[0][1] is False


def test_post_update_migration_defers_active_current_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / 'project'
    (project_root / '.ccb').mkdir(parents=True)
    state_path = tmp_path / 'state' / 'provider-cache-cleanup.json'
    monkeypatch.setattr(migration, 'current_project_legacy_provider_cache_present', lambda _layout: True)
    monkeypatch.setattr(
        migration,
        'cleanup_current_project_legacy_provider_caches',
        lambda _context, *, measure_bytes: (_ for _ in ()).throw(
            RuntimeError('ccb cleanup requires stopped ccbd')
        ),
    )
    monkeypatch.setattr(
        migration,
        'CliContextBuilder',
        lambda: SimpleNamespace(build=lambda command, cwd: SimpleNamespace()),
    )

    summary = migration.run_post_update_provider_cache_cleanup(
        cwd=project_root,
        projects_root=tmp_path / 'projects',
        state_path=state_path,
        stdout=StringIO(),
    )

    assert summary.status == 'partial'
    assert summary.deferred_project_roots == (str(project_root),)
    payload = json.loads(state_path.read_text(encoding='utf-8'))
    assert payload['deferred_project_roots'] == [str(project_root)]


def test_post_update_migration_preserves_unverifiable_cache(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / 'projects'
    missing_project = tmp_path / 'deleted-project'
    project_id = compute_project_id(missing_project)
    cache_dir = projects_root / project_id[:16] / 'provider-cache' / 'gemini'
    _write(cache_dir / 'payload')
    _write(cache_dir / 'MANIFEST.json', '{invalid')
    state_path = tmp_path / 'state' / 'provider-cache-cleanup.json'

    summary = migration.run_post_update_provider_cache_cleanup(
        cwd=tmp_path,
        projects_root=projects_root,
        state_path=state_path,
        stdout=StringIO(),
    )

    assert summary.status == 'partial'
    assert summary.preserved_count == 1
    assert (cache_dir / 'payload').is_file()
    payload = json.loads(state_path.read_text(encoding='utf-8'))
    assert payload['preserved'][0]['reason'] == 'manifest_unreadable'


def test_post_update_migration_global_lock_prevents_duplicate_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projects_root = tmp_path / 'projects'
    cache_dir = _orphan_cache(projects_root, tmp_path / 'deleted-project', 'claude')
    state_path = tmp_path / 'state' / 'provider-cache-cleanup.json'
    state_path.parent.mkdir(parents=True)
    lock_path = state_path.with_name(migration.LOCK_FILE_NAME)
    lock_path.write_text(f'{os.getpid()} now\n', encoding='utf-8')
    output = StringIO()
    monkeypatch.setenv('CCB_LANG', 'en')

    summary = migration.run_post_update_provider_cache_cleanup(
        cwd=tmp_path,
        projects_root=projects_root,
        state_path=state_path,
        stdout=output,
    )

    assert summary.status == 'locked'
    assert (cache_dir / 'payload').is_file()
    assert lock_path.is_file()
    assert 'Another CCB update window' in output.getvalue()


def test_state_path_uses_source_home_not_managed_provider_home(tmp_path: Path) -> None:
    path = migration.provider_cache_cleanup_state_path(
        env={},
        home=tmp_path / 'source-home',
    )

    assert path == tmp_path / 'source-home' / '.local' / 'state' / 'ccb' / migration.STATE_FILE_NAME
