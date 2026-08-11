from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

from provider_control import ProviderQuotaService
from storage.paths import PathLayout


def _provider_home(project: Path, agent: str, provider: str) -> Path:
    home = PathLayout(project).agent_provider_state_dir(agent, provider) / 'home'
    home.mkdir(parents=True, exist_ok=True)
    return home


def test_codex_quota_is_normalized_cached_and_redacted(tmp_path: Path) -> None:
    home = _provider_home(tmp_path, 'mobile', 'codex')
    token = 'secret-access-token'
    (home / 'auth.json').write_text(
        json.dumps({'tokens': {'access_token': token, 'account_id': 'account-1'}}),
        encoding='utf-8',
    )
    calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(url: str, headers, timeout: float):
        calls.append((url, dict(headers), timeout))
        return 200, {
            'plan_type': 'plus',
            'rate_limit': {
                'primary_window': {'used_percent': 25, 'reset_at': 1_800_000_000},
                'secondary_window': {'used_percent': 75, 'reset_at': 1_800_100_000},
            },
            'credits': {'balance': 12.5},
        }

    service = ProviderQuotaService(
        fetch=fetch,
        wall_clock=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    first = service.account_quota(project_root=tmp_path, agent='mobile', provider='codex')
    second = service.account_quota(project_root=tmp_path, agent='mobile', provider='codex')

    assert first == second
    assert len(calls) == 1
    assert calls[0][1]['Authorization'] == f'Bearer {token}'
    record = first.to_record()
    assert record['status'] == 'available'
    assert record['plan_label'] == 'plus'
    assert record['windows'][0]['remaining_pct'] == 75.0
    assert record['windows'][1]['tone'] == 'warning'
    assert record['balances'][0]['remaining'] == 12.5
    assert token not in json.dumps(record)
    assert str(home) not in json.dumps(record)


def test_claude_quota_maps_scoped_limits_and_auth_failure(tmp_path: Path) -> None:
    home = _provider_home(tmp_path, 'claude-agent', 'claude')
    credentials = home / '.claude' / '.credentials.json'
    credentials.parent.mkdir(parents=True)
    credentials.write_text(
        json.dumps(
            {
                'claudeAiOauth': {
                    'accessToken': 'claude-secret',
                    'subscriptionType': 'max',
                    'rateLimitTier': 'tier_20x',
                }
            }
        ),
        encoding='utf-8',
    )
    responses = [
        (
            200,
            {
                'five_hour': {'utilization': '11', 'resets_at': '2026-08-11T12:00:00Z'},
                'seven_day': {'utilization': 72, 'resets_at': None},
                'limits': [
                    {
                        'kind': 'weekly_scoped',
                        'percent': 8,
                        'resets_at': '2026-08-15T00:00:00Z',
                        'scope': {'model': {'id': 'opus', 'display_name': 'Opus'}},
                    }
                ],
                'extra_usage': {'is_enabled': True},
            },
        ),
        (401, {}),
    ]

    def fetch(_url: str, _headers, _timeout: float):
        return responses.pop(0)

    service = ProviderQuotaService(fetch=fetch, ttl_seconds=60)
    available = service.account_quota(
        project_root=tmp_path,
        agent='claude-agent',
        provider='claude',
    )
    denied = service.account_quota(
        project_root=tmp_path,
        agent='claude-agent',
        provider='claude',
        force_refresh=True,
    )

    assert available.plan_label == 'Max 20x'
    assert [item.id for item in available.windows] == [
        'five_hour',
        'weekly',
        'weekly_model_opus',
    ]
    assert available.details[0]['value'] == 'Enabled'
    assert denied.status == 'unavailable'
    assert denied.diagnostic_code == 'authentication_required'


def test_quota_timeout_isolated_to_redacted_error(tmp_path: Path) -> None:
    home = _provider_home(tmp_path, 'mobile', 'codex')
    (home / 'auth.json').write_text(
        json.dumps({'tokens': {'access_token': 'never-echo-this'}}),
        encoding='utf-8',
    )

    def timeout(_url: str, _headers, _timeout: float):
        raise TimeoutError('contains never-echo-this')

    quota = ProviderQuotaService(fetch=timeout).account_quota(
        project_root=tmp_path,
        agent='mobile',
        provider='codex',
    )

    assert quota.status == 'error'
    assert quota.diagnostic_code == 'upstream_timeout'
    assert 'never-echo-this' not in json.dumps(quota.to_record())


def test_concurrent_quota_refreshes_share_one_bounded_fetch(tmp_path: Path) -> None:
    home = _provider_home(tmp_path, 'mobile', 'codex')
    (home / 'auth.json').write_text(
        json.dumps({'tokens': {'access_token': 'shared-secret'}}),
        encoding='utf-8',
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def fetch(_url: str, _headers, _timeout: float):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return 200, {'rate_limit': {}}

    service = ProviderQuotaService(fetch=fetch, timeout_seconds=2)

    def load():
        return service.account_quota(
            project_root=tmp_path,
            agent='mobile',
            provider='codex',
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(load) for _ in range(4)]
        assert started.wait(timeout=2)
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert calls == 1
    assert all(result.status == 'available' for result in results)
