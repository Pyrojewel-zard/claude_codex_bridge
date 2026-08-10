from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from hapi_integration.preflight import (
    HapiPreflight,
    HapiPreflightError,
    run_hapi_preflight,
)

# Anchor runtime state so hardcoded `.ccb/...` paths stay stable under this
# fork's default relocation to ~/.local/ccb.
@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


def _result(*, returncode: int = 0, stdout: str = '', stderr: str = ''):
    from hapi_integration.preflight import _PreflightResult

    return _PreflightResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _ok_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'schemaVersion': 1,
        'hapiVersion': '0.25.1',
        'apiUrl': 'https://hub.example.invalid',
        'authConfigured': True,
        'hubReachable': True,
        'capabilities': {
            'ccbMetadataV1': True,
            'disableRunnerAutoStart': True,
        },
    }
    payload.update(overrides)
    return payload


def _runner_returning(result):
    def _runner(command, *, timeout_s):
        return result

    return _runner


def _runner_raising(exc):
    def _runner(command, *, timeout_s):
        raise exc

    return _runner


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_run_hapi_preflight_success() -> None:
    result = run_hapi_preflight(
        'hapi',
        runner=_runner_returning(_result(stdout=json.dumps(_ok_payload()))),
    )
    assert isinstance(result, HapiPreflight)
    assert result.schema_version == 1
    assert result.hapi_version == '0.25.1'
    assert result.api_url == 'https://hub.example.invalid'
    assert result.auth_configured is True
    assert result.hub_reachable is True
    assert result.ccb_metadata_v1 is True
    assert result.disable_runner_auto_start is True


def test_run_hapi_preflight_rejects_fragment() -> None:
    payload = _ok_payload(apiUrl='https://hub.example.invalid/path#frag')
    with pytest.raises(HapiPreflightError, match='query or fragment'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_strips_trailing_slash_for_hapi_string_concatenation() -> None:
    payload = _ok_payload(apiUrl='https://hub.example.invalid/base/')
    result = run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))
    assert result.api_url == 'https://hub.example.invalid/base'


# ---------------------------------------------------------------------------
# Failure classes
# ---------------------------------------------------------------------------


def test_run_hapi_preflight_missing_executable() -> None:
    with pytest.raises(HapiPreflightError, match='executable not found'):
        run_hapi_preflight('definitely-not-on-path-xyz', runner=_runner_raising(FileNotFoundError('nope')))


def test_run_hapi_preflight_timeout() -> None:
    with pytest.raises(HapiPreflightError, match='timed out'):
        run_hapi_preflight(
            'hapi',
            timeout_s=2.0,
            runner=_runner_raising(subprocess.TimeoutExpired(cmd=['hapi'], timeout=2.0)),
        )


def test_run_hapi_preflight_nonzero_exit() -> None:
    with pytest.raises(HapiPreflightError, match='exited with code 2'):
        run_hapi_preflight(
            'hapi',
            runner=_runner_returning(_result(returncode=2, stderr='boom')),
        )


def test_run_hapi_preflight_malformed_json() -> None:
    with pytest.raises(HapiPreflightError, match='not valid JSON'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout='not json{')))


def test_run_hapi_preflight_empty_output() -> None:
    with pytest.raises(HapiPreflightError, match='no JSON output'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout='   ')))


def test_run_hapi_preflight_wrong_schema_version() -> None:
    payload = _ok_payload(schemaVersion=2)
    with pytest.raises(HapiPreflightError, match='schemaVersion must be 1'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_missing_auth() -> None:
    payload = _ok_payload(authConfigured=False)
    with pytest.raises(HapiPreflightError, match='authentication is not configured'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_unreachable_hub() -> None:
    payload = _ok_payload(hubReachable=False)
    with pytest.raises(HapiPreflightError, match='Hub is not reachable'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_missing_capability() -> None:
    payload = _ok_payload(capabilities={'ccbMetadataV1': True, 'disableRunnerAutoStart': False})
    with pytest.raises(HapiPreflightError, match='disableRunnerAutoStart'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_missing_capabilities_object() -> None:
    payload = _ok_payload()
    del payload['capabilities']
    with pytest.raises(HapiPreflightError, match='capabilities'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


# ---------------------------------------------------------------------------
# Secret-bearing URL rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'url',
    [
        'https://user:pass@hub.example.invalid',
        'https://hub.example.invalid/?token=secret',
        'https://hub.example.invalid/?api_key=secret',
        'https://hub.example.invalid/?accesstoken=x',
        'https://hub.example.invalid/?key=secret',
        'https://hub.example.invalid/?jwt=secret',
        'https://hub.example.invalid/?page=1',
    ],
)
def test_run_hapi_preflight_rejects_secret_url(url: str) -> None:
    payload = _ok_payload(apiUrl=url)
    with pytest.raises(HapiPreflightError, match='apiUrl must not carry'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_rejects_non_http_scheme() -> None:
    payload = _ok_payload(apiUrl='file:///etc/passwd')
    with pytest.raises(HapiPreflightError, match='http or https'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_rejects_multiline_url() -> None:
    payload = _ok_payload(apiUrl='https://hub.example.invalid\nx')
    with pytest.raises(HapiPreflightError, match='single line'):
        run_hapi_preflight('hapi', runner=_runner_returning(_result(stdout=json.dumps(payload))))


def test_run_hapi_preflight_redacts_subprocess_output_from_message() -> None:
    # Subprocess output may contain credentials and must not be retained.
    result = _result(returncode=2, stderr='SECRET-STDERR-VALUE', stdout='irrelevant')
    with pytest.raises(HapiPreflightError) as exc_info:
        run_hapi_preflight('hapi', runner=_runner_returning(result))
    assert 'SECRET-STDERR-VALUE' not in str(exc_info.value)
    assert not hasattr(exc_info.value, 'detail')


# ---------------------------------------------------------------------------
# Preflight cache (apiUrl carry-forward to launchers)
# ---------------------------------------------------------------------------


def test_preflight_cache_round_trips(tmp_path) -> None:
    from hapi_integration.store import HapiPreflightCache, read_preflight_cache, write_preflight_cache

    cache_dir = tmp_path / 'cache'
    write_preflight_cache(
        cache_dir,
        HapiPreflightCache(
            api_url='https://hub.example.invalid',
            hapi_home='/home/caller/.hapi',
        ),
    )
    restored = read_preflight_cache(cache_dir)
    assert restored is not None
    assert restored.api_url == 'https://hub.example.invalid'
    assert restored.hapi_home == '/home/caller/.hapi'


def test_resolve_hapi_home_prefers_explicit_caller_value(tmp_path) -> None:
    from hapi_integration.command import resolve_hapi_home

    explicit = tmp_path / 'global-hapi'
    assert resolve_hapi_home(environ={'HAPI_HOME': str(explicit)}) == str(explicit)


def test_resolve_hapi_home_uses_original_user_home_when_unset(tmp_path) -> None:
    from hapi_integration.command import resolve_hapi_home

    assert resolve_hapi_home(
        environ={},
        source_home_fn=lambda: tmp_path / 'caller-home',
    ) == str(tmp_path / 'caller-home' / '.hapi')


def test_preflight_cache_missing_returns_none(tmp_path) -> None:
    from hapi_integration.store import read_preflight_cache

    assert read_preflight_cache(tmp_path / 'nope') is None


def test_preflight_cache_corrupt_returns_none(tmp_path) -> None:
    from hapi_integration.store import preflight_cache_path, read_preflight_cache

    cache_dir = tmp_path / 'cache'
    cache_dir.mkdir()
    preflight_cache_path(cache_dir).write_text('not json', encoding='utf-8')
    assert read_preflight_cache(cache_dir) is None


def test_clear_preflight_cache_prevents_stale_launch_context(tmp_path) -> None:
    from hapi_integration.store import (
        HapiPreflightCache,
        clear_preflight_cache,
        read_preflight_cache,
        write_preflight_cache,
    )

    cache_dir = tmp_path / 'cache'
    write_preflight_cache(cache_dir, HapiPreflightCache(api_url='https://hub.example.invalid'))
    clear_preflight_cache(cache_dir)

    assert read_preflight_cache(cache_dir) is None


def test_graceful_process_tree_termination_never_escalates_to_sigkill(monkeypatch) -> None:
    from cli.kill_runtime import processes

    force_values: list[bool] = []
    monkeypatch.setattr(
        processes,
        '_kill_pid_tree_once',
        lambda pid, *, force: force_values.append(force) or True,
    )
    monkeypatch.setattr(processes, '_wait_for_pid_exit', lambda *args, **kwargs: False)

    exited = processes.terminate_pid_tree_gracefully(
        123,
        timeout_s=3.0,
        is_pid_alive_fn=lambda pid: True,
    )

    assert exited is False
    assert force_values == [False]


def test_wrapper_identity_requires_matching_session_environment_and_pgid(tmp_path) -> None:
    from hapi_integration.runtime import load_current_wrapper_identity

    record = tmp_path / 'hapi-wrapper.json'
    record.write_text(
        json.dumps({'schemaVersion': 1, 'sessionId': 'generation-2', 'pid': 4242, 'pgid': 4200}),
        encoding='utf-8',
    )
    identity = load_current_wrapper_identity(
        record,
        is_pid_alive_fn=lambda pid: pid == 4242,
        getpgid_fn=lambda pid: 4200,
        read_environ_fn=lambda pid: {'HAPI_CCB_SESSION_ID': 'generation-2'},
    )
    assert identity is not None
    assert (identity.pid, identity.pgid, identity.session_id) == (4242, 4200, 'generation-2')

    assert load_current_wrapper_identity(
        record,
        is_pid_alive_fn=lambda pid: True,
        getpgid_fn=lambda pid: 4200,
        read_environ_fn=lambda pid: {'HAPI_CCB_SESSION_ID': 'provider-runtime-session'},
    ) is None


def test_wrapper_graceful_stop_terms_all_groups_before_one_shared_deadline(tmp_path) -> None:
    from hapi_integration.runtime import HapiWrapperIdentity, graceful_stop_wrapper_records

    now = [0.0]
    records = (tmp_path / 'one.json', tmp_path / 'two.json')
    identities = {
        records[0]: HapiWrapperIdentity('s1', 101, 1001, records[0]),
        records[1]: HapiWrapperIdentity('s2', 202, 2002, records[1]),
    }
    signals: list[tuple[float, int]] = []

    def _load(path, **kwargs):
        return identities[path]

    def _signal(identity):
        signals.append((now[0], identity.pgid))
        return True

    def _sleep(seconds):
        now[0] += seconds

    signaled, exited = graceful_stop_wrapper_records(
        records,
        timeout_s=3.0,
        load_identity_fn=_load,
        signal_group_fn=_signal,
        is_pid_alive_fn=lambda pid: True,
        monotonic_fn=lambda: now[0],
        sleep_fn=_sleep,
    )

    assert (signaled, exited) == (2, 0)
    assert signals == [(0.0, 1001), (0.0, 2002)]
    assert now[0] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Start-flow preflight gate
# ---------------------------------------------------------------------------


def _ok_preflight(*args, **kwargs):
    from hapi_integration.preflight import HapiPreflight

    return HapiPreflight(
        schema_version=1,
        hapi_version='0.25.1',
        api_url='https://hub.example.invalid',
        auth_configured=True,
        hub_reachable=True,
        ccb_metadata_v1=True,
        disable_runner_auto_start=True,
    )


def test_start_flow_preflight_gate_disabled_skips_subprocess(monkeypatch) -> None:
    # A disabled [hapi] block must never spawn the preflight subprocess.
    import ccbd.start_flow as start_flow_mod

    calls: list[str] = []

    def _spy(command, *, timeout_s=10.0):
        calls.append(command)
        return _ok_preflight()

    from agents.models import HapiConfig

    class _Cfg:
        hapi = HapiConfig()

    result = start_flow_mod._run_hapi_preflight_if_enabled(_Cfg(), preflight_fn=_spy)
    assert result is None
    assert calls == []


def test_start_flow_preflight_gate_enabled_runs_and_caches(monkeypatch, tmp_path) -> None:
    import ccbd.start_flow as start_flow_mod

    def _spy(command, *, timeout_s=10.0):
        assert command == '/opt/hapi/bin/hapi'
        return _ok_preflight()

    from agents.models import HapiConfig
    from hapi_integration.store import read_preflight_cache

    class _Paths:
        def __init__(self, cache_dir):
            self._cache_dir = cache_dir

        @property
        def shared_cache_dir(self):
            return self._cache_dir

    class _Cfg:
        hapi = HapiConfig(enabled=True, command='/opt/hapi/bin/hapi')

    cache_dir = tmp_path / 'shared-cache'
    preflight = start_flow_mod._run_hapi_preflight_if_enabled(_Cfg(), preflight_fn=_spy)
    assert preflight is not None
    start_flow_mod.write_preflight_cache(cache_dir, start_flow_mod.HapiPreflightCache(api_url=preflight.api_url))
    restored = read_preflight_cache(cache_dir)
    assert restored is not None
    assert restored.api_url == 'https://hub.example.invalid'


def test_start_flow_preflight_gate_failure_aborts(monkeypatch) -> None:
    import ccbd.start_flow as start_flow_mod

    def _failing(command, *, timeout_s=10.0):
        raise HapiPreflightError('HAPI authentication is not configured')

    from agents.models import HapiConfig

    class _Cfg:
        hapi = HapiConfig(enabled=True, command='hapi')

    with pytest.raises(HapiPreflightError, match='authentication is not configured'):
        start_flow_mod._run_hapi_preflight_if_enabled(_Cfg(), preflight_fn=_failing)


def test_disabled_start_flow_clears_stale_preflight_cache(monkeypatch, tmp_path) -> None:
    import ccbd.start_flow as start_flow_mod
    from agents.models import HapiConfig
    from hapi_integration.store import HapiPreflightCache, read_preflight_cache, write_preflight_cache

    cache_dir = tmp_path / 'shared-cache'
    write_preflight_cache(cache_dir, HapiPreflightCache(api_url='https://old.example.invalid'))
    monkeypatch.setattr(start_flow_mod, 'run_start_flow_impl', lambda **kwargs: 'started')

    result = start_flow_mod.run_start_flow(
        project_root=tmp_path,
        project_id='project-1',
        paths=SimpleNamespace(shared_cache_dir=cache_dir),
        config=SimpleNamespace(hapi=HapiConfig(enabled=False)),
        runtime_service=object(),
        requested_agents=(),
        restore=False,
        auto_permission=False,
    )

    assert result == 'started'
    assert read_preflight_cache(cache_dir) is None


# ---------------------------------------------------------------------------
# Doctor HAPI section
# ---------------------------------------------------------------------------


def test_doctor_hapi_summary_disabled_performs_no_subprocess() -> None:
    from agents.models import HapiConfig
    from cli.services.doctor_runtime import hapi_summary

    class _Cfg:
        hapi = HapiConfig()

    summary = hapi_summary(_Cfg())
    assert summary == {
        'enabled': False,
        'command': 'hapi',
        'available': False,
        'contract': None,
    }


def test_doctor_hapi_summary_enabled_reports_contract(monkeypatch) -> None:
    from agents.models import HapiConfig
    from cli.services.doctor_runtime import hapi_summary

    monkeypatch.setattr('shutil.which', lambda cmd: '/usr/local/bin/hapi' if cmd == 'hapi' else None)

    class _Cfg:
        hapi = HapiConfig(enabled=True, command='hapi')

    summary = hapi_summary(_Cfg(), preflight_fn=_ok_preflight)
    assert summary['enabled'] is True
    assert summary['available'] is True
    assert summary['contract']['ok'] is True
    assert summary['contract']['apiUrl'] == 'https://hub.example.invalid'
    assert summary['contract']['capabilities'] == {
        'ccbMetadataV1': True,
        'disableRunnerAutoStart': True,
    }


def test_doctor_hapi_summary_reports_failure_without_secrets(monkeypatch) -> None:
    from agents.models import HapiConfig
    from cli.services.doctor_runtime import hapi_summary

    def _failing(command, *, timeout_s=10.0):
        raise HapiPreflightError('HAPI authentication is not configured')

    monkeypatch.setattr('shutil.which', lambda cmd: '/usr/local/bin/hapi')

    class _Cfg:
        hapi = HapiConfig(enabled=True, command='hapi')

    summary = hapi_summary(_Cfg(), preflight_fn=_failing)
    assert summary['contract']['ok'] is False
    assert summary['contract']['reason'] == 'HAPI authentication is not configured'
    assert 'SECRET-TOKEN' not in str(summary)


def test_doctor_hapi_summary_never_projects_query_url(monkeypatch) -> None:
    from agents.models import HapiConfig
    from cli.services.doctor_runtime import hapi_summary

    monkeypatch.setattr('shutil.which', lambda cmd: '/usr/local/bin/hapi')
    unsafe = _ok_preflight()
    object.__setattr__(unsafe, 'api_url', 'https://hub.example.invalid/?jwt=secret')
    summary = hapi_summary(
        SimpleNamespace(hapi=HapiConfig(enabled=True)),
        preflight_fn=lambda command: unsafe,
    )

    assert summary['contract']['ok'] is False
    assert summary['contract']['apiUrl'] is None
    assert 'jwt=secret' not in str(summary)
