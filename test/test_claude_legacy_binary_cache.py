from __future__ import annotations

import json
from pathlib import Path

from provider_backends.claude.launcher_runtime.legacy_binary_cache import (
    detach_legacy_claude_binary_cache,
)


def _legacy_layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    home = tmp_path / 'managed-home'
    cache_root = tmp_path / 'ccb-cache' / 'claude'
    versions_root = cache_root / 'versions'
    binary = versions_root / '2.1.218'
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text('claude binary\n', encoding='utf-8')
    versions_link = home / '.local' / 'share' / 'claude' / 'versions'
    versions_link.parent.mkdir(parents=True, exist_ok=True)
    versions_link.symlink_to(versions_root, target_is_directory=True)
    executable_link = home / '.local' / 'bin' / 'claude'
    executable_link.parent.mkdir(parents=True, exist_ok=True)
    executable_link.symlink_to(binary)
    return home, cache_root, versions_link, executable_link


def test_detach_legacy_claude_binary_cache_removes_only_managed_links(tmp_path: Path) -> None:
    home, cache_root, versions_link, executable_link = _legacy_layout(tmp_path)
    marker = Path(f'{versions_link}.ccb-projection.json')
    marker.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_projected_asset',
                'label': 'claude-binary-versions',
                'mode': 'symlink',
                'source': str(cache_root / 'versions'),
            }
        )
        + '\n',
        encoding='utf-8',
    )

    result = detach_legacy_claude_binary_cache(home, cache_roots=(cache_root,))

    assert result['status'] == 'ok'
    assert result['reason'] == 'legacy_ccb_binary_cache_detached'
    assert not versions_link.exists()
    assert not versions_link.is_symlink()
    assert not executable_link.exists()
    assert not executable_link.is_symlink()
    assert not marker.exists()
    assert (cache_root / 'versions' / '2.1.218').is_file()


def test_detach_legacy_claude_binary_cache_handles_broken_cache_target(tmp_path: Path) -> None:
    home = tmp_path / 'managed-home'
    cache_root = tmp_path / 'missing-cache' / 'claude'
    versions_link = home / '.local' / 'share' / 'claude' / 'versions'
    versions_link.parent.mkdir(parents=True, exist_ok=True)
    versions_link.symlink_to(cache_root / 'versions', target_is_directory=True)

    result = detach_legacy_claude_binary_cache(home, cache_roots=(cache_root,))

    assert result['status'] == 'ok'
    assert not versions_link.is_symlink()


def test_detach_legacy_claude_binary_cache_preserves_foreign_symlink(tmp_path: Path) -> None:
    home, _cache_root, versions_link, executable_link = _legacy_layout(tmp_path)
    allowed_root = tmp_path / 'different-cache' / 'claude'

    result = detach_legacy_claude_binary_cache(home, cache_roots=(allowed_root,))

    assert result['status'] == 'skipped'
    assert result['reason'] == 'versions_dir_not_legacy_ccb_cache'
    assert versions_link.is_symlink()
    assert executable_link.is_symlink()


def test_detach_legacy_claude_binary_cache_preserves_external_executable_link(tmp_path: Path) -> None:
    home, cache_root, versions_link, executable_link = _legacy_layout(tmp_path)
    global_binary = tmp_path / 'user-home' / '.local' / 'bin' / 'claude'
    global_binary.parent.mkdir(parents=True, exist_ok=True)
    global_binary.write_text('global binary\n', encoding='utf-8')
    executable_link.unlink()
    executable_link.symlink_to(global_binary)

    result = detach_legacy_claude_binary_cache(home, cache_roots=(cache_root,))

    assert result['status'] == 'ok'
    assert not versions_link.is_symlink()
    assert executable_link.is_symlink()
    assert executable_link.resolve() == global_binary.resolve()


def test_detach_legacy_claude_binary_cache_reports_unlink_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home, cache_root, versions_link, executable_link = _legacy_layout(tmp_path)
    real_unlink = Path.unlink

    def _failing_unlink(path: Path, *args, **kwargs):
        if path == executable_link:
            raise PermissionError('read only')
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', _failing_unlink)

    result = detach_legacy_claude_binary_cache(home, cache_roots=(cache_root,))

    assert result['status'] == 'skipped'
    assert result['reason'] == 'legacy_ccb_binary_cache_detach_failed'
    assert versions_link.is_symlink()
    assert executable_link.is_symlink()
