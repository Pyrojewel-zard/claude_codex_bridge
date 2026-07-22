from __future__ import annotations

import os
from pathlib import Path

from mobile_gateway import mobile_host_state_dir
from mobile_gateway.relay_host_credentials import activate_relay_host


def relay_host_activate_command(context, command) -> dict[str, object]:
    del context
    invitation = _invitation(command)
    relay_origin = (
        str(getattr(command, 'relay_origin', '') or '').strip()
        or str(os.environ.get('CCB_RELAY_PUBLIC_ORIGIN') or '').strip()
        or 'wss://relay.seemlab.top'
    )
    credential_path = _credential_path(command)
    credentials = activate_relay_host(
        relay_origin=relay_origin,
        invitation=invitation,
        credential_path=credential_path,
    )
    return credentials.public_summary(credential_path=credential_path)


def _invitation(command) -> str:
    direct = str(getattr(command, 'invitation', '') or '').strip()
    if direct:
        return direct
    path_text = str(getattr(command, 'invitation_file', '') or '').strip()
    if path_text:
        path = Path(path_text).expanduser()
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise ValueError('relay invitation file must be owner-only')
        invitation = path.read_text(encoding='utf-8').strip()
        if invitation:
            return invitation
    environment = str(os.environ.get('CCB_RELAY_INVITATION') or '').strip()
    if environment:
        return environment
    raise ValueError(
        'relay host activate requires --invitation-file, --invitation, or CCB_RELAY_INVITATION'
    )


def _credential_path(command) -> Path:
    explicit = str(getattr(command, 'credential_path', '') or '').strip()
    configured = str(os.environ.get('CCB_RELAY_HOST_CREDENTIALS') or '').strip()
    return Path(explicit or configured or (mobile_host_state_dir() / 'relay-host-credentials.json')).expanduser()


__all__ = ['relay_host_activate_command']
