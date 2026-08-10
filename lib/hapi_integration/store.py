from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HapiPreflightCache:
    api_url: str
    command: str = 'hapi'
    hapi_home: str = ''

    def to_record(self) -> dict[str, Any]:
        return {
            'apiUrl': self.api_url,
            'command': self.command,
            'hapiHome': self.hapi_home,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> 'HapiPreflightCache':
        return cls(
            api_url=str(record.get('apiUrl') or ''),
            command=str(record.get('command') or 'hapi') or 'hapi',
            hapi_home=str(record.get('hapiHome') or ''),
        )


def preflight_cache_path(shared_cache_dir: Path) -> Path:
    return Path(shared_cache_dir) / 'hapi_preflight.json'


def write_preflight_cache(shared_cache_dir: Path, cache: HapiPreflightCache) -> None:
    cache_dir = Path(shared_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = preflight_cache_path(cache_dir)
    tmp = target.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cache.to_record()), encoding='utf-8')
    tmp.replace(target)


def clear_preflight_cache(shared_cache_dir: Path) -> None:
    # Propagate deletion failures: aborting start is safer than allowing an old
    # successful preflight to activate wrapping under a disabled/new config.
    preflight_cache_path(Path(shared_cache_dir)).unlink(missing_ok=True)


def read_preflight_cache(shared_cache_dir: Path) -> HapiPreflightCache | None:
    target = preflight_cache_path(Path(shared_cache_dir))
    if not target.is_file():
        return None
    try:
        record = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    cache = HapiPreflightCache.from_record(record)
    if not cache.api_url:
        return None
    return cache


__all__ = [
    'HapiPreflightCache',
    'clear_preflight_cache',
    'preflight_cache_path',
    'read_preflight_cache',
    'write_preflight_cache',
]
