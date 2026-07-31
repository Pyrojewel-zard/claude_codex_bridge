from __future__ import annotations

import os
from pathlib import Path

import pytest

from rust_helpers import RUST_HELPER_BIN_ENV, RUST_HELPERS_ENV
from rust_helpers_storage import RUST_STORAGE_SCAN_ENV, RUST_STORAGE_SUMMARY_ENV, scan_storage_inventory, scan_storage_summary


def _write(path: Path, text: str = 'x') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def _write_helper(path: Path, body: str) -> Path:
    path.write_text('#!/usr/bin/env python3\n' + body, encoding='utf-8')
    path.chmod(0o755)
    return path


def _storage_stub_helper(path: Path) -> Path:
    return _write_helper(
        path,
        """import json, os, sys
from pathlib import Path

if sys.argv[1:] == ['--capabilities']:
    print(json.dumps({'schema_version': 1, 'capabilities': ['contract.echo', 'storage.scan.inventory']}))
else:
    request = json.loads(sys.stdin.read())
    records = []
    seen = set()
    for root in request['payload']['roots']:
        root_path = Path(root['path'])
        if not root_path.exists():
            continue
        for current, dirs, files in os.walk(root_path, followlinks=False):
            current_path = Path(current)
            safe_dirs = []
            for dirname in dirs:
                candidate = current_path / dirname
                if candidate.is_symlink():
                    paths = [candidate]
                else:
                    safe_dirs.append(dirname)
                    paths = []
                for path in paths:
                    stat = path.lstat()
                    identity = (stat.st_dev, stat.st_ino)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    records.append({
                        'path': str(path),
                        'relative_path': str(path.relative_to(root_path)),
                        'root_kind': root['root_kind'],
                        'size_bytes': stat.st_size,
                        'is_symlink': path.is_symlink(),
                    })
            dirs[:] = safe_dirs
            for filename in files:
                path = current_path / filename
                stat = path.lstat()
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen:
                    continue
                seen.add(identity)
                records.append({
                    'path': str(path),
                    'relative_path': str(path.relative_to(root_path)),
                    'root_kind': root['root_kind'],
                    'size_bytes': stat.st_size,
                    'is_symlink': path.is_symlink(),
                })
    print(json.dumps({'schema_version': 1, 'ok': True, 'capability': request['capability'], 'payload': records}))
""",
    )


def _storage_summary_stub_helper(path: Path) -> Path:
    return _write_helper(
        path,
        """import json, sys

if sys.argv[1:] == ['--capabilities']:
    print(json.dumps({'schema_version': 1, 'capabilities': ['contract.echo', 'storage.scan.summary']}))
else:
    request = json.loads(sys.stdin.read())
    limit = request['payload'].get('top_entries_limit', 50)
    entries = [
        {
            'path': '/repo/.ccb/agents/main/provider-state/codex/home/auth.json',
            'relative_path': 'agents/main/provider-state/codex/home/auth.json',
            'storage_class': 'secret',
            'size_bytes': 5,
            'provider': 'codex',
            'agent': 'main',
            'active': None,
            'is_active_version': None,
            'reachable_from_current_symlink': None,
            'reclaimable': None,
            'reason': 'provider_secret',
            'root_kind': 'project',
        },
        {
            'path': '/repo/.ccb/ccb.config',
            'relative_path': 'ccb.config',
            'storage_class': 'authority',
            'size_bytes': 3,
            'provider': None,
            'agent': None,
            'active': None,
            'is_active_version': None,
            'reachable_from_current_symlink': None,
            'reclaimable': None,
            'reason': None,
            'root_kind': 'project',
        },
    ][:limit]
    print(json.dumps({'schema_version': 1, 'ok': True, 'capability': request['capability'], 'payload': {
        'total_bytes': 8,
        'total_count': 2,
        'by_class': {'authority': {'bytes': 3, 'count': 1}, 'secret': {'bytes': 5, 'count': 1}},
        'by_provider': {'codex': {'bytes': 5, 'count': 1}},
        'by_agent': {'main': {'bytes': 5, 'count': 1}},
        'entries': entries,
    }}))
""",
    )


def test_storage_global_zero_disables_default_auto(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')

    def should_not_discover(name: str):
        raise AssertionError(f'unexpected helper discovery: {name}')

    result = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_HELPERS_ENV: '0'},
        which=should_not_discover,
        script_root=tmp_path / 'repo',
    )

    assert result.helper_used is False
    assert [record['relative_path'] for record in result.value] == ['ccb.config']
    assert result.diagnostics[0].failure_kind == 'disabled'


def test_storage_default_auto_uses_helper_when_available(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')
    helper = _storage_stub_helper(tmp_path / 'helper.py')

    result = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_HELPER_BIN_ENV: str(helper)},
        timeout_s=2.0,
    )

    assert result.helper_used is True
    assert result.value[0]['relative_path'] == 'ccb.config'
    assert result.value[0]['root_kind'] == 'project'


def test_storage_default_auto_falls_back_when_helper_missing(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')

    result = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_HELPER_BIN_ENV: str(tmp_path / 'missing-helper')},
    )

    assert result.helper_used is False
    assert result.value[0]['relative_path'] == 'ccb.config'
    assert result.diagnostics[0].failure_kind == 'missing'


def test_storage_zero_forces_python_fallback_even_when_helper_exists(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')
    helper = _write_helper(tmp_path / 'helper.py', 'raise SystemExit(99)\n')

    result = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_STORAGE_SCAN_ENV: '0', RUST_HELPER_BIN_ENV: str(helper)},
    )

    assert result.helper_used is False
    assert result.value[0]['relative_path'] == 'ccb.config'
    assert result.diagnostics[0].failure_kind == 'disabled'


@pytest.mark.parametrize('mode', ['1', 'auto', 'required'])
def test_storage_enabled_uses_stub_helper_and_overrides_global_disabled(tmp_path: Path, mode: str) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')
    helper = _storage_stub_helper(tmp_path / 'helper.py')

    result = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_HELPERS_ENV: '0', RUST_STORAGE_SCAN_ENV: mode, RUST_HELPER_BIN_ENV: str(helper)},
    )

    assert result.helper_used is True
    assert result.value[0]['relative_path'] == 'ccb.config'
    assert result.value[0]['root_kind'] == 'project'
    assert result.diagnostics == ()


def test_python_fallback_includes_symlink_directory_without_recursing(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    outside = tmp_path / 'outside'
    _write(root / 'agents' / 'main' / 'runtime.json', '{}\n')
    _write(outside / 'secret.txt', 'secret\n')
    if not hasattr(os, 'symlink'):
        pytest.skip('symlink not available')
    os.symlink(outside, root / 'agents' / 'linked-outside')

    result = scan_storage_inventory([{'root_kind': 'project', 'path': str(root)}], env={RUST_STORAGE_SCAN_ENV: '0'})
    records = {str(record['relative_path']): record for record in result.value}

    assert 'agents/main/runtime.json' in records
    assert 'agents/linked-outside' in records
    assert records['agents/linked-outside']['is_symlink'] is True
    assert 'agents/linked-outside/secret.txt' not in records


def test_missing_and_hardlinked_roots_are_deduped(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    data = _write(root / 'ccbd' / 'state.json', '{}\n')
    if hasattr(os, 'link'):
        os.link(data, root / 'ccbd' / 'state-copy.json')

    result = scan_storage_inventory(
        [
            {'root_kind': 'project', 'path': str(root)},
            {'root_kind': 'runtime', 'path': str(tmp_path / 'missing')},
        ],
        env={RUST_STORAGE_SCAN_ENV: '0'},
    )

    relative_paths = {str(record['relative_path']) for record in result.value}
    assert 'ccbd/state.json' in relative_paths or 'ccbd/state-copy.json' in relative_paths
    if hasattr(os, 'link'):
        assert len(relative_paths & {'ccbd/state.json', 'ccbd/state-copy.json'}) == 1


def test_helper_failures_fallback_without_leaking_content(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'agents' / 'main' / 'provider-state' / 'codex' / 'home' / 'auth.json', 'provider transcript secret')

    missing = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_STORAGE_SCAN_ENV: '1'},
        which=lambda name: None,
        script_root=tmp_path / 'repo',
    )
    assert missing.value[0]['relative_path'].endswith('auth.json')
    assert missing.diagnostics[0].failure_kind == 'missing'

    crash_helper = _write_helper(
        tmp_path / 'crash.py',
        """import json, sys
if sys.argv[1:] == ['--capabilities']:
    print(json.dumps({'schema_version': 1, 'capabilities': ['storage.scan.inventory']}))
else:
    sys.stderr.write('raw secret stderr')
    raise SystemExit(2)
""",
    )
    crash = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_STORAGE_SCAN_ENV: '1', RUST_HELPER_BIN_ENV: str(crash_helper)},
    )
    assert crash.value[0]['relative_path'].endswith('auth.json')
    diagnostics = str([diagnostic.to_dict() for diagnostic in crash.diagnostics])
    assert crash.diagnostics[0].failure_kind == 'nonzero_exit'
    assert 'provider transcript secret' not in diagnostics
    assert 'raw secret stderr' not in diagnostics

    bad_payload_helper = _write_helper(
        tmp_path / 'bad_payload.py',
        """import json, sys
if sys.argv[1:] == ['--capabilities']:
    print(json.dumps({'schema_version': 1, 'capabilities': ['storage.scan.inventory']}))
else:
    print(json.dumps({'schema_version': 1, 'ok': True, 'capability': 'storage.scan.inventory', 'payload': {'leak': 'provider transcript secret'}}))
""",
    )
    bad_payload = scan_storage_inventory(
        [{'root_kind': 'project', 'path': str(root)}],
        env={RUST_STORAGE_SCAN_ENV: '1', RUST_HELPER_BIN_ENV: str(bad_payload_helper)},
    )
    assert bad_payload.helper_used is False
    assert bad_payload.value[0]['relative_path'].endswith('auth.json')
    assert bad_payload.diagnostics[0].failure_kind == 'unknown_schema'
    assert 'provider transcript secret' not in str([diagnostic.to_dict() for diagnostic in bad_payload.diagnostics])


def test_storage_required_missing_helper_raises_without_python_fallback(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')

    with pytest.raises(RuntimeError, match='no Python fallback'):
        scan_storage_inventory(
            [{'root_kind': 'project', 'path': str(root)}],
            env={RUST_STORAGE_SCAN_ENV: 'required'},
            which=lambda name: None,
            script_root=tmp_path / 'repo',
        )


def test_storage_required_bad_payload_raises_without_python_fallback(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')
    bad_payload_helper = _write_helper(
        tmp_path / 'bad_payload.py',
        """import json, sys
if sys.argv[1:] == ['--capabilities']:
    print(json.dumps({'schema_version': 1, 'capabilities': ['storage.scan.inventory']}))
else:
    print(json.dumps({'schema_version': 1, 'ok': True, 'capability': 'storage.scan.inventory', 'payload': {'invalid': True}}))
""",
    )

    with pytest.raises(RuntimeError, match='no Python fallback'):
        scan_storage_inventory(
            [{'root_kind': 'project', 'path': str(root)}],
            env={RUST_STORAGE_SCAN_ENV: 'required', RUST_HELPER_BIN_ENV: str(bad_payload_helper)},
        )


def test_storage_summary_explicit_mode_uses_helper_and_limits_entries(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')
    helper = _storage_summary_stub_helper(tmp_path / 'summary_helper.py')

    result = scan_storage_summary(
        [{'root_kind': 'project', 'path': str(root)}],
        ccb_dir=root,
        runtime_state_root=root,
        top_entries_limit=1,
        env={RUST_STORAGE_SUMMARY_ENV: '1', RUST_HELPER_BIN_ENV: str(helper)},
    )

    assert result.helper_used is True
    assert result.value['total_count'] == 2
    assert result.value['by_class']['secret'] == {'bytes': 5, 'count': 1}
    assert [entry['relative_path'] for entry in result.value['entries']] == [
        'agents/main/provider-state/codex/home/auth.json',
    ]


def test_storage_summary_default_disabled_returns_empty_fallback(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')

    result = scan_storage_summary(
        [{'root_kind': 'project', 'path': str(root)}],
        ccb_dir=root,
        runtime_state_root=root,
        env={RUST_HELPERS_ENV: '1'},
        script_root=tmp_path / 'repo',
    )

    assert result.helper_used is False
    assert result.value == {}
    assert result.diagnostics[0].failure_kind == 'disabled'


def test_storage_summary_required_missing_helper_raises_without_python_fallback(tmp_path: Path) -> None:
    root = tmp_path / '.ccb'
    _write(root / 'ccb.config', 'main:codex\n')

    with pytest.raises(RuntimeError, match='no Python fallback'):
        scan_storage_summary(
            [{'root_kind': 'project', 'path': str(root)}],
            ccb_dir=root,
            runtime_state_root=root,
            env={RUST_STORAGE_SUMMARY_ENV: 'required'},
            which=lambda name: None,
            script_root=tmp_path / 'repo',
        )
