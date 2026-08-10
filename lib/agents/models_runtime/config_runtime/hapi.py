from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..names import AgentValidationError

DEFAULT_HAPI_COMMAND = 'hapi'
DEFAULT_HAPI_ENABLED = False

# Forbidden shell metacharacters: the command must be a single executable token
# (or an explicit path to one). Pipelines, redirection, command separators,
# and job control are rejected so CCB never spawns a shell snippet.
_HAPI_COMMAND_FORBIDDEN = frozenset('|&;\n\r`$<>')

# Allowed characters for an executable name or path: alphanumerics plus the
# path separators and common executable-name punctuation. This is a structural
# guard; the executable is still resolved via PATH/preflight at runtime.
_HAPI_COMMAND_ALLOWED_EXTRA = frozenset('/._-=+:@,')


@dataclass(frozen=True)
class HapiConfig:
    enabled: bool = DEFAULT_HAPI_ENABLED
    command: str = DEFAULT_HAPI_COMMAND

    def __post_init__(self) -> None:
        enabled = _bool_value(self.enabled, field_name='hapi.enabled')
        command = _normalize_command(self.command)
        object.__setattr__(self, 'enabled', enabled)
        object.__setattr__(self, 'command', command)

    def to_record(self) -> dict[str, Any]:
        return {
            'enabled': self.enabled,
            'command': self.command,
        }


def _bool_value(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise AgentValidationError(f'{field_name} must be a boolean')
    return value


def _normalize_command(value: object) -> str:
    raw = str(value or '').strip()
    if not raw:
        raise AgentValidationError('hapi.command must not be empty')
    if any(ch in _HAPI_COMMAND_FORBIDDEN for ch in raw):
        raise AgentValidationError(
            'hapi.command must be an executable name or path without shell pipelines or redirection'
        )
    # Reject whitespace inside the command: a single executable token only.
    if any(ch.isspace() for ch in raw):
        raise AgentValidationError(
            'hapi.command must be a single executable token without whitespace'
        )
    for ch in raw:
        if not (ch.isalnum() or ch in _HAPI_COMMAND_ALLOWED_EXTRA):
            raise AgentValidationError(
                f'hapi.command contains an unsupported character: {ch!r}'
            )
    return raw


__all__ = [
    'DEFAULT_HAPI_COMMAND',
    'DEFAULT_HAPI_ENABLED',
    'HapiConfig',
]
