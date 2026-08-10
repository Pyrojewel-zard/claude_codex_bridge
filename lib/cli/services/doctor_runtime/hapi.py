from __future__ import annotations

import shutil
from typing import Any
from urllib.parse import urlsplit

from hapi_integration.preflight import HapiPreflightError, run_hapi_preflight


def hapi_summary(config, *, preflight_fn=run_hapi_preflight) -> dict[str, Any]:
    """Non-mutating HAPI section for `ccb doctor`.

    Reports the configured command's availability, the preflight contract,
    auth, and Hub reachability without exposing secrets. A disabled or absent
    HAPI block reports ``enabled=False`` and performs no subprocess call.
    """
    hapi = getattr(config, 'hapi', None)
    enabled = bool(getattr(hapi, 'enabled', False))
    command = str(getattr(hapi, 'command', '') or '')
    payload: dict[str, Any] = {
        'enabled': enabled,
        'command': command,
        'available': False,
        'contract': None,
    }
    if not enabled:
        return payload
    payload['available'] = shutil.which(command) is not None
    try:
        preflight = preflight_fn(command)
    except HapiPreflightError as exc:
        payload['contract'] = {
            'ok': False,
            'reason': exc.reason,
            'schemaVersion': None,
            'hapiVersion': None,
            'apiUrl': None,
            'authConfigured': None,
            'hubReachable': None,
            'capabilities': None,
        }
        return payload
    api_url = str(preflight.api_url or '').strip()
    parts = urlsplit(api_url)
    if parts.query or parts.fragment:
        payload['contract'] = {
            'ok': False,
            'reason': 'HAPI preflight apiUrl contains a query or fragment',
            'schemaVersion': preflight.schema_version,
            'hapiVersion': preflight.hapi_version,
            'apiUrl': None,
            'authConfigured': preflight.auth_configured,
            'hubReachable': preflight.hub_reachable,
            'capabilities': None,
        }
        return payload
    payload['contract'] = {
        'ok': True,
        'schemaVersion': preflight.schema_version,
        'hapiVersion': preflight.hapi_version,
        'apiUrl': api_url,
        'authConfigured': preflight.auth_configured,
        'hubReachable': preflight.hub_reachable,
        'capabilities': {
            'ccbMetadataV1': preflight.ccb_metadata_v1,
            'disableRunnerAutoStart': preflight.disable_runner_auto_start,
        },
    }
    return payload


__all__ = ['hapi_summary']
