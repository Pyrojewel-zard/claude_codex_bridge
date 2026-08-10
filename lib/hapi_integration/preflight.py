from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

EXPECTED_SCHEMA_VERSION = 1
DEFAULT_PREFLIGHT_TIMEOUT_S = 10.0


class HapiPreflightError(RuntimeError):
    """Raised when the HAPI preflight contract is not satisfied.

    The message is safe for user-facing output; it never includes tokens,
    command output, or other secrets.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class HapiPreflight:
    schema_version: int
    hapi_version: str
    api_url: str
    auth_configured: bool
    hub_reachable: bool
    ccb_metadata_v1: bool
    disable_runner_auto_start: bool

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> 'HapiPreflight':
        if not isinstance(payload, dict):
            raise HapiPreflightError('preflight output must be a JSON object')
        try:
            schema_version = int(payload.get('schemaVersion'))
        except (TypeError, ValueError) as exc:
            raise HapiPreflightError('preflight schemaVersion must be an integer') from exc
        if schema_version != EXPECTED_SCHEMA_VERSION:
            raise HapiPreflightError(
                f'preflight schemaVersion must be {EXPECTED_SCHEMA_VERSION}, got {schema_version}'
            )
        hapi_version = str(payload.get('hapiVersion') or '').strip()
        if not hapi_version:
            raise HapiPreflightError('preflight hapiVersion is required')
        api_url = _validate_api_url(payload.get('apiUrl'))
        auth_configured = _require_bool(payload, 'authConfigured')
        hub_reachable = _require_bool(payload, 'hubReachable')
        capabilities = payload.get('capabilities')
        if not isinstance(capabilities, dict):
            raise HapiPreflightError('preflight capabilities object is required')
        ccb_metadata_v1 = _require_capability(capabilities, 'ccbMetadataV1')
        disable_runner_auto_start = _require_capability(capabilities, 'disableRunnerAutoStart')
        return cls(
            schema_version=schema_version,
            hapi_version=hapi_version,
            api_url=api_url,
            auth_configured=auth_configured,
            hub_reachable=hub_reachable,
            ccb_metadata_v1=ccb_metadata_v1,
            disable_runner_auto_start=disable_runner_auto_start,
        )

    def require_ready(self) -> None:
        if not self.auth_configured:
            raise HapiPreflightError('HAPI authentication is not configured')
        if not self.hub_reachable:
            raise HapiPreflightError('HAPI Hub is not reachable')
        if not self.ccb_metadata_v1:
            raise HapiPreflightError('HAPI does not advertise ccbMetadataV1 capability')
        if not self.disable_runner_auto_start:
            raise HapiPreflightError('HAPI does not advertise disableRunnerAutoStart capability')


def run_hapi_preflight(
    command: str,
    *,
    timeout_s: float = DEFAULT_PREFLIGHT_TIMEOUT_S,
    runner: 'HapiPreflightRunner | None' = None,
) -> HapiPreflight:
    """Run `<command> doctor --json` and parse the frozen preflight contract.

    Never persists tokens. Raises ``HapiPreflightError`` with a redacted message
    on any failure class: missing executable, timeout, nonzero exit, malformed
    JSON, wrong schema, secret-bearing URL, missing auth, unreachable Hub, or
    missing capabilities.
    """
    resolved_runner = runner or _default_runner
    try:
        result = resolved_runner(command, timeout_s=timeout_s)
    except FileNotFoundError as exc:
        raise HapiPreflightError(f'HAPI executable not found: {command}') from exc
    except subprocess.TimeoutExpired as exc:
        raise HapiPreflightError(f'HAPI preflight timed out after {timeout_s:.0f}s') from exc
    return _interpret_result(result, command=command)


@dataclass(frozen=True)
class _PreflightResult:
    returncode: int
    stdout: str
    stderr: str


def _interpret_result(result: _PreflightResult, *, command: str) -> HapiPreflight:
    if result.returncode != 0:
        raise HapiPreflightError(f'HAPI preflight exited with code {result.returncode}')
    text = result.stdout.strip()
    if not text:
        raise HapiPreflightError('HAPI preflight produced no JSON output')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HapiPreflightError('HAPI preflight output is not valid JSON') from exc
    preflight = HapiPreflight.from_json(payload)
    preflight.require_ready()
    return preflight


def _default_runner(command: str, *, timeout_s: float) -> _PreflightResult:
    proc = subprocess.run(
        [command, 'doctor', '--json'],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return _PreflightResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


# A subprocess boundary injected by tests. Production code uses ``_default_runner``.
HapiPreflightRunner = Any


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HapiPreflightError(f'preflight {key} must be a boolean')
    return value


def _require_capability(capabilities: dict[str, Any], key: str) -> bool:
    value = capabilities.get(key)
    if not isinstance(value, bool):
        raise HapiPreflightError(f'preflight capabilities.{key} must be a boolean')
    if not value:
        raise HapiPreflightError(f'HAPI does not advertise capability {key}')
    return value


def _validate_api_url(value: object) -> str:
    raw = str(value or '').strip()
    if not raw:
        raise HapiPreflightError('preflight apiUrl is required')
    if '\n' in raw or '\r' in raw:
        raise HapiPreflightError('preflight apiUrl must be a single line')
    parts = urlsplit(raw)
    if parts.scheme not in ('http', 'https'):
        raise HapiPreflightError('preflight apiUrl must use http or https')
    if not parts.netloc:
        raise HapiPreflightError('preflight apiUrl must include a host')
    # Reject userinfo (credentials embedded in the URL).
    if parts.username or parts.password:
        raise HapiPreflightError('preflight apiUrl must not carry credentials')
    if parts.query or parts.fragment:
        raise HapiPreflightError('preflight apiUrl must not carry a query or fragment')
    normalized_path = parts.path.rstrip('/')
    normalized = urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, ''))
    return normalized


__all__ = [
    'DEFAULT_PREFLIGHT_TIMEOUT_S',
    'EXPECTED_SCHEMA_VERSION',
    'HapiPreflight',
    'HapiPreflightError',
    'run_hapi_preflight',
]
