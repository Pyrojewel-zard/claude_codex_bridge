from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from project.ids import compute_legacy_project_id, compute_project_id, project_slug
from project.identity_store import (
    ProjectIdentityConflictError,
    ensure_project_identity,
    load_project_identity,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def _legacy_lifecycle(project_id: str, socket_path: Path) -> dict[str, object]:
    return {
        'schema_version': 2,
        'record_type': 'ccbd_lifecycle',
        'project_id': project_id,
        'desired_state': 'stopped',
        'phase': 'failed',
        'generation': 7,
        'phase_started_at': '2026-07-24T00:00:00Z',
        'socket_path': str(socket_path),
    }


def _legacy_lease(project_id: str, socket_path: Path) -> dict[str, object]:
    return {
        'schema_version': 2,
        'record_type': 'ccbd_lease',
        'api_version': 2,
        'project_id': project_id,
        'ccbd_pid': 999999,
        'socket_path': str(socket_path),
        'owner_uid': 1000,
        'boot_id': 'boot-1',
        'started_at': '2026-07-24T00:00:00Z',
        'last_heartbeat_at': '2026-07-24T00:00:00Z',
        'mount_state': 'mounted',
        'generation': 7,
    }


def test_new_identity_and_slug_survive_directory_rename(tmp_path: Path) -> None:
    original = tmp_path / 'old-name'
    (original / '.ccb').mkdir(parents=True)
    identity = ensure_project_identity(
        original,
        clock=lambda: '2026-07-24T00:00:00Z',
        id_factory=lambda: 'a' * 64,
    )

    moved = tmp_path / 'new-name'
    original.rename(moved)
    rebound = ensure_project_identity(
        moved,
        clock=lambda: '2026-07-24T00:01:00Z',
    )

    assert rebound.project_id == identity.project_id == 'a' * 64
    assert rebound.project_slug == identity.project_slug == 'old-name-aaaaaaaa'
    assert rebound.bound_root == str(moved)
    assert rebound.binding_epoch == 2
    assert compute_project_id(moved) == identity.project_id
    assert project_slug(moved) == identity.project_slug


def test_existing_legacy_runtime_keeps_current_path_id(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    ccb_dir = project_root / '.ccb'
    legacy_id = compute_legacy_project_id(project_root)
    socket_path = ccb_dir / 'ccbd' / 'ccbd.sock'
    _write_json(
        ccb_dir / 'ccbd' / 'lifecycle.json',
        _legacy_lifecycle(legacy_id, socket_path),
    )

    identity = ensure_project_identity(
        project_root,
        clock=lambda: '2026-07-24T00:00:00Z',
        id_factory=lambda: 'b' * 64,
    )

    assert identity.project_id == legacy_id
    assert identity.identity_origin == 'legacy-current-root'
    assert identity.legacy_project_ids == ()


def test_existing_legacy_anchor_without_runtime_keeps_current_path_id(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'repo'
    ccb_dir = project_root / '.ccb'
    ccb_dir.mkdir(parents=True)
    (ccb_dir / 'ccb.config').write_text('agents: []\n', encoding='utf-8')
    legacy_id = compute_legacy_project_id(project_root)

    identity = ensure_project_identity(
        project_root,
        clock=lambda: '2026-07-24T00:00:00Z',
        id_factory=lambda: 'b' * 64,
    )

    assert identity.project_id == legacy_id
    assert identity.identity_origin == 'legacy-current-root'


def test_inactive_moved_legacy_runtime_adopts_recorded_id(tmp_path: Path) -> None:
    original = tmp_path / 'legacy-root'
    ccb_dir = original / '.ccb'
    legacy_id = compute_legacy_project_id(original)
    socket_path = ccb_dir / 'ccbd' / 'ccbd.sock'
    _write_json(
        ccb_dir / 'ccbd' / 'lifecycle.json',
        _legacy_lifecycle(legacy_id, socket_path),
    )
    _write_json(
        ccb_dir / 'ccbd' / 'lease.json',
        _legacy_lease(legacy_id, socket_path),
    )
    moved = tmp_path / 'moved-root'
    original.rename(moved)

    identity = ensure_project_identity(
        moved,
        clock=lambda: '2026-07-24T00:00:00Z',
        id_factory=lambda: 'c' * 64,
        process_exists_fn=lambda _pid: False,
        socket_connectable_fn=lambda _path: False,
    )

    assert identity.project_id == legacy_id
    assert identity.project_slug == f'legacy-root-{legacy_id[:8]}'
    assert identity.identity_origin == 'legacy-relocated-runtime'
    assert identity.bound_root == str(moved)


def test_active_moved_legacy_runtime_fails_closed(tmp_path: Path) -> None:
    original = tmp_path / 'legacy-root'
    ccb_dir = original / '.ccb'
    legacy_id = compute_legacy_project_id(original)
    socket_path = ccb_dir / 'ccbd' / 'ccbd.sock'
    _write_json(
        ccb_dir / 'ccbd' / 'lifecycle.json',
        _legacy_lifecycle(legacy_id, socket_path),
    )
    _write_json(
        ccb_dir / 'ccbd' / 'lease.json',
        _legacy_lease(legacy_id, socket_path),
    )
    moved = tmp_path / 'moved-root'
    original.rename(moved)

    with pytest.raises(ProjectIdentityConflictError, match='still active'):
        ensure_project_identity(
            moved,
            clock=lambda: '2026-07-24T00:00:00Z',
            id_factory=lambda: 'd' * 64,
            process_exists_fn=lambda _pid: True,
            socket_connectable_fn=lambda _path: False,
        )


def test_copied_persisted_identity_fails_closed(tmp_path: Path) -> None:
    original = tmp_path / 'original'
    (original / '.ccb').mkdir(parents=True)
    ensure_project_identity(
        original,
        clock=lambda: '2026-07-24T00:00:00Z',
        id_factory=lambda: 'e' * 64,
    )
    copied = tmp_path / 'copied'
    shutil.copytree(original, copied)

    with pytest.raises(ProjectIdentityConflictError, match='explicit fork'):
        ensure_project_identity(copied)

    assert load_project_identity(original) is not None
    assert load_project_identity(copied) is not None


def test_conflicting_legacy_runtime_ids_fail_closed(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    ccb_dir = project_root / '.ccb'
    socket_path = ccb_dir / 'ccbd' / 'ccbd.sock'
    _write_json(
        ccb_dir / 'ccbd' / 'lifecycle.json',
        _legacy_lifecycle('a' * 64, socket_path),
    )
    _write_json(
        ccb_dir / 'ccbd' / 'lease.json',
        _legacy_lease('b' * 64, socket_path),
    )

    with pytest.raises(ProjectIdentityConflictError, match='records disagree'):
        ensure_project_identity(
            project_root,
            process_exists_fn=lambda _pid: False,
            socket_connectable_fn=lambda _path: False,
        )


def test_unproven_foreign_legacy_binding_fails_closed(tmp_path: Path) -> None:
    project_root = tmp_path / 'repo'
    ccb_dir = project_root / '.ccb'
    socket_path = ccb_dir / 'ccbd' / 'ccbd.sock'
    _write_json(
        ccb_dir / 'ccbd' / 'lifecycle.json',
        _legacy_lifecycle('a' * 64, socket_path),
    )

    with pytest.raises(ProjectIdentityConflictError, match='cannot safely bind'):
        ensure_project_identity(
            project_root,
            process_exists_fn=lambda _pid: False,
            socket_connectable_fn=lambda _path: False,
        )
