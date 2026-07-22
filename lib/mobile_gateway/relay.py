from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Mapping

from .relay_crypto import RELAY_PROHIBITED_PLAINTEXT_FIELDS


_SCHEMA_VERSION = 1

_PROHIBITED_CLEARTEXT_KEYS = set(RELAY_PROHIBITED_PLAINTEXT_FIELDS)


class MobileRelayError(RuntimeError):
    pass


@dataclass(frozen=True)
class RelayHostRegistration:
    host_id: str
    server_fingerprint: str
    host_pubkey_b64: str
    capabilities: tuple[str, ...] = ()
    diagnostics: Mapping[str, str] | None = None
    schema_version: int = _SCHEMA_VERSION

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> 'RelayHostRegistration':
        _reject_cleartext_keys(payload, 'relay_host_registration')
        registration_type = _optional_text(payload.get('type'))
        if registration_type and registration_type != 'relay_host_registration':
            raise MobileRelayError(f'unknown relay host registration type: {registration_type}')
        host_pubkey = _required_base64_text(payload.get('host_pubkey_b64'), 'host_pubkey_b64')
        return cls(
            schema_version=_int(payload.get('schema_version'), fallback=_SCHEMA_VERSION),
            host_id=_required_text(payload.get('host_id'), 'host_id'),
            server_fingerprint=_required_text(payload.get('server_fingerprint'), 'server_fingerprint'),
            host_pubkey_b64=host_pubkey,
            capabilities=tuple(sorted(_string_set(payload.get('capabilities')))),
            diagnostics=_string_map(payload.get('diagnostics')),
        )._validate()

    def to_json(self) -> dict[str, object]:
        self._validate()
        payload: dict[str, object] = {
            'schema_version': self.schema_version,
            'type': 'relay_host_registration',
            'host_id': self.host_id,
            'server_fingerprint': self.server_fingerprint,
            'host_pubkey_b64': self.host_pubkey_b64,
            'capabilities': sorted(self.capabilities),
        }
        diagnostics = _string_map(self.diagnostics or {})
        if diagnostics:
            payload['diagnostics'] = diagnostics
        return payload

    def _validate(self) -> 'RelayHostRegistration':
        if self.schema_version < 1:
            raise MobileRelayError('relay host registration schema_version invalid')
        _required_text(self.host_id, 'host_id')
        _required_text(self.server_fingerprint, 'server_fingerprint')
        _required_base64_text(self.host_pubkey_b64, 'host_pubkey_b64')
        return self


@dataclass(frozen=True)
class RelayFrame:
    session_id: str
    seq: int
    kind: str
    payload: Mapping[str, object]
    schema_version: int = _SCHEMA_VERSION

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> 'RelayFrame':
        frame = cls(
            schema_version=_int(payload.get('schema_version'), fallback=_SCHEMA_VERSION),
            session_id=_required_text(payload.get('session_id'), 'session_id'),
            seq=_positive_int(payload.get('seq'), 'seq'),
            kind=_required_text(payload.get('kind'), 'kind'),
            payload=_object_map(payload.get('payload'), 'payload'),
        )
        frame.validate()
        return frame

    def to_json(self) -> dict[str, object]:
        self.validate()
        return {
            'schema_version': self.schema_version,
            'session_id': self.session_id,
            'seq': self.seq,
            'kind': self.kind,
            'payload': dict(self.payload),
        }

    def validate(self) -> None:
        if self.schema_version < 1:
            raise MobileRelayError('relay frame schema_version invalid')
        _required_text(self.session_id, 'session_id')
        _positive_int(self.seq, 'seq')
        if self.kind not in {'client_hello', 'host_hello', 'gateway_envelope', 'ack', 'close'}:
            raise MobileRelayError(f'unknown relay frame kind: {self.kind}')
        _reject_cleartext_keys(self.payload, f'{self.kind}.payload')
        if self.kind == 'client_hello':
            _required_text(self.payload.get('host_id'), 'client_hello.host_id')
            _required_text(self.payload.get('device_id'), 'client_hello.device_id')
            _required_base64_text(self.payload.get('client_pubkey_b64'), 'client_hello.client_pubkey_b64')
            versions = _positive_int_list(self.payload.get('supported_versions'), 'client_hello.supported_versions')
            if not versions:
                raise MobileRelayError('client_hello.supported_versions is required')
        elif self.kind == 'host_hello':
            _required_text(self.payload.get('host_id'), 'host_hello.host_id')
            _required_text(self.payload.get('server_fingerprint'), 'host_hello.server_fingerprint')
            _required_base64_text(self.payload.get('host_pubkey_b64'), 'host_hello.host_pubkey_b64')
            _positive_int(self.payload.get('accepted_version'), 'host_hello.accepted_version')
        elif self.kind == 'gateway_envelope':
            envelope = _object_map(self.payload.get('envelope'), 'envelope')
            if _required_text(envelope.get('session_id'), 'envelope.session_id') != self.session_id:
                raise MobileRelayError('relay gateway envelope session mismatch')
            _positive_int(envelope.get('seq'), 'envelope.seq')
            _required_text(envelope.get('op'), 'envelope.op')
            _required_base64_text(envelope.get('ciphertext_b64'), 'envelope.ciphertext_b64')
            _required_base64_text(envelope.get('nonce_b64'), 'envelope.nonce_b64')
        elif self.kind == 'ack' and 'ack_seq' in self.payload:
            _positive_int(self.payload.get('ack_seq'), 'ack.ack_seq')
        elif self.kind == 'close' and 'reason' in self.payload:
            _required_text(self.payload.get('reason'), 'close.reason')


@dataclass(frozen=True)
class RelayHandshakeTranscript:
    session_id: str
    host_id: str
    device_id: str
    accepted_version: int
    client_pubkey_b64: str
    host_pubkey_b64: str
    server_fingerprint: str

    @classmethod
    def negotiate(cls, *, client_hello: RelayFrame, host_hello: RelayFrame) -> 'RelayHandshakeTranscript':
        client_hello.validate()
        host_hello.validate()
        if client_hello.kind != 'client_hello':
            raise MobileRelayError('relay handshake must start with client_hello')
        if host_hello.kind != 'host_hello':
            raise MobileRelayError('relay handshake requires host_hello')
        if client_hello.session_id != host_hello.session_id:
            raise MobileRelayError('relay handshake session mismatch')
        client_host_id = _required_text(client_hello.payload.get('host_id'), 'client_hello.host_id')
        host_id = _required_text(host_hello.payload.get('host_id'), 'host_hello.host_id')
        if client_host_id != host_id:
            raise MobileRelayError('relay handshake host mismatch')
        supported_versions = _positive_int_list(
            client_hello.payload.get('supported_versions'),
            'client_hello.supported_versions',
        )
        accepted_version = _positive_int(host_hello.payload.get('accepted_version'), 'host_hello.accepted_version')
        if accepted_version not in supported_versions:
            raise MobileRelayError('relay handshake version mismatch')
        return cls(
            session_id=client_hello.session_id,
            host_id=host_id,
            device_id=_required_text(client_hello.payload.get('device_id'), 'client_hello.device_id'),
            accepted_version=accepted_version,
            client_pubkey_b64=_required_base64_text(
                client_hello.payload.get('client_pubkey_b64'),
                'client_hello.client_pubkey_b64',
            ),
            host_pubkey_b64=_required_base64_text(host_hello.payload.get('host_pubkey_b64'), 'host_hello.host_pubkey_b64'),
            server_fingerprint=_required_text(host_hello.payload.get('server_fingerprint'), 'host_hello.server_fingerprint'),
        )

    def to_json(self) -> dict[str, object]:
        return {
            'session_id': self.session_id,
            'host_id': self.host_id,
            'device_id': self.device_id,
            'accepted_version': self.accepted_version,
            'server_fingerprint': self.server_fingerprint,
        }


class LocalRelayServerHarness:
    """In-memory relay harness for source tests; never opens a public listener."""

    def __init__(self) -> None:
        self._hosts: dict[str, RelayHostRegistration] = {}
        self._sessions: dict[str, RelayHandshakeTranscript] = {}
        self._forwarded: list[dict[str, object]] = []
        self._disconnected_hosts: set[str] = set()
        self._stale_devices: set[tuple[str, str]] = set()
        self._relay_unreachable = False

    def register_host(self, registration_payload: Mapping[str, object]) -> dict[str, object]:
        registration = RelayHostRegistration.from_json(registration_payload)
        self._hosts[registration.host_id] = registration
        self._disconnected_hosts.discard(registration.host_id)
        return {
            'status': 'registered',
            'host_id': registration.host_id,
            'server_fingerprint': registration.server_fingerprint,
            'capabilities': sorted(registration.capabilities),
        }

    def host_hello_for(self, client_hello_payload: Mapping[str, object]) -> dict[str, object]:
        client_hello = RelayFrame.from_json(client_hello_payload)
        if client_hello.kind != 'client_hello':
            raise MobileRelayError('relay client hello required')
        host_id = _required_text(client_hello.payload.get('host_id'), 'client_hello.host_id')
        registration = self._require_host(host_id)
        if host_id in self._disconnected_hosts:
            raise MobileRelayError('relay host disconnected')
        supported_versions = _positive_int_list(
            client_hello.payload.get('supported_versions'),
            'client_hello.supported_versions',
        )
        accepted_version = 1 if 1 in supported_versions else max(supported_versions)
        frame = RelayFrame(
            session_id=client_hello.session_id,
            seq=client_hello.seq + 1,
            kind='host_hello',
            payload={
                'host_id': registration.host_id,
                'server_fingerprint': registration.server_fingerprint,
                'host_pubkey_b64': registration.host_pubkey_b64,
                'accepted_version': accepted_version,
            },
        )
        transcript = RelayHandshakeTranscript.negotiate(client_hello=client_hello, host_hello=frame)
        self._sessions[transcript.session_id] = transcript
        return frame.to_json()

    def forward_from_phone(self, frame_payload: Mapping[str, object]) -> dict[str, object]:
        frame = RelayFrame.from_json(frame_payload)
        transcript = self._sessions.get(frame.session_id)
        if transcript is None:
            raise MobileRelayError('relay session is not established')
        if transcript.host_id in self._disconnected_hosts:
            raise MobileRelayError('relay host disconnected')
        if frame.kind != 'gateway_envelope':
            raise MobileRelayError('relay forwards only opaque gateway envelopes in this harness')
        record = {'direction': 'phone_to_host', 'host_id': transcript.host_id, 'frame': frame.to_json()}
        self._forwarded.append(record)
        return {
            'schema_version': _SCHEMA_VERSION,
            'session_id': frame.session_id,
            'seq': frame.seq + 1,
            'kind': 'ack',
            'payload': {'ack_seq': frame.seq},
        }

    def disconnect_host(self, host_id: str) -> None:
        self._require_host(host_id)
        self._disconnected_hosts.add(host_id)

    def mark_device_stale(self, *, host_id: str, device_id: str) -> None:
        self._require_host(host_id)
        device = _required_text(device_id, 'device_id')
        self._stale_devices.add((host_id, device))

    def set_relay_unreachable(self, unreachable: bool = True) -> None:
        self._relay_unreachable = bool(unreachable)

    def diagnostics_for_host(
        self,
        host_id: str,
        *,
        device_id: str | None = None,
        expected_host_fingerprint: str | None = None,
    ) -> dict[str, object]:
        base_host_id = _required_text(host_id, 'host_id')
        if self._relay_unreachable:
            return {
                'host_id': base_host_id,
                'state': 'relay_unreachable',
                'ready': False,
                'reason': 'relay control plane is unreachable from this harness',
            }
        registration = self._hosts.get(base_host_id)
        if registration is None:
            return {'host_id': base_host_id, 'state': 'unknown_host', 'ready': False}
        expected = _optional_text(expected_host_fingerprint)
        if expected and registration.server_fingerprint != expected:
            return {
                'host_id': base_host_id,
                'state': 'host_fingerprint_mismatch',
                'ready': False,
                'expected_host_fingerprint': expected,
                'observed_host_fingerprint': registration.server_fingerprint,
            }
        device = _optional_text(device_id)
        if device and (base_host_id, device) in self._stale_devices:
            return {
                'host_id': base_host_id,
                'device_id': device,
                'state': 'stale_device',
                'ready': False,
            }
        if base_host_id in self._disconnected_hosts:
            return {'host_id': base_host_id, 'state': 'host_disconnected', 'ready': False}
        sessions = [item for item in self._sessions.values() if item.host_id == base_host_id]
        return {
            'host_id': base_host_id,
            'state': 'ready' if sessions else 'registered',
            'ready': bool(sessions),
            'session_count': len(sessions),
            'forwarded_count': len([item for item in self._forwarded if item['host_id'] == base_host_id]),
        }

    @property
    def forwarded(self) -> tuple[dict[str, object], ...]:
        return tuple(self._forwarded)

    def _require_host(self, host_id: str) -> RelayHostRegistration:
        registration = self._hosts.get(host_id)
        if registration is None:
            raise MobileRelayError('relay host is not registered')
        return registration


class MobileGatewayRelayOutboundClient:
    """Source-side fake outbound relay client used by local tests and harnesses."""

    def __init__(
        self,
        *,
        relay: LocalRelayServerHarness,
        host_id: str,
        server_fingerprint: str,
        host_pubkey_b64: str,
        capabilities: tuple[str, ...] = ('http_json', 'project_view', 'relay_tunnel'),
        diagnostics: Mapping[str, str] | None = None,
    ) -> None:
        self._relay = relay
        self._registration = RelayHostRegistration(
            host_id=host_id,
            server_fingerprint=server_fingerprint,
            host_pubkey_b64=host_pubkey_b64,
            capabilities=capabilities,
            diagnostics=diagnostics or {},
        )

    def connect(self) -> dict[str, object]:
        return self._relay.register_host(self._registration.to_json())

    def diagnostics(
        self,
        *,
        device_id: str | None = None,
        expected_host_fingerprint: str | None = None,
    ) -> dict[str, object]:
        return self._relay.diagnostics_for_host(
            self._registration.host_id,
            device_id=device_id,
            expected_host_fingerprint=expected_host_fingerprint,
        )


def _reject_cleartext_keys(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            text_key = str(key)
            if text_key in _PROHIBITED_CLEARTEXT_KEYS:
                raise MobileRelayError(f'relay cleartext field is prohibited: {path}.{text_key}')
            _reject_cleartext_keys(item, f'{path}.{text_key}')
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_cleartext_keys(item, f'{path}[{index}]')


def _object_map(value: object, name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if value is None:
        return {}
    raise MobileRelayError(f'relay field must be an object: {name}')


def _required_text(value: object, name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise MobileRelayError(f'relay field is required: {name}')
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or '').strip()
    return text or None


def _required_base64_text(value: object, name: str) -> str:
    text = _required_text(value, name)
    try:
        base64.b64decode(_base64_padding(text), altchars=b'-_', validate=True)
    except Exception as exc:  # pragma: no cover - exact exception varies by Python version
        raise MobileRelayError(f'relay field must be base64url: {name}') from exc
    return text


def _base64_padding(value: str) -> bytes:
    text = value.strip()
    return (text + '=' * (-len(text) % 4)).encode('ascii')


def _int(value: object, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _positive_int(value: object, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MobileRelayError(f'relay field must be a positive integer: {name}') from exc
    if parsed < 1:
        raise MobileRelayError(f'relay field must be a positive integer: {name}')
    return parsed


def _positive_int_list(value: object, name: str) -> list[int]:
    if not isinstance(value, (list, tuple)):
        raise MobileRelayError(f'relay field must be an integer list: {name}')
    return [_positive_int(item, f'{name}.item') for item in value]


def _string_set(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {text for item in value if (text := _optional_text(item))}


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


__all__ = [
    'LocalRelayServerHarness',
    'MobileGatewayRelayOutboundClient',
    'MobileRelayError',
    'RelayFrame',
    'RelayHandshakeTranscript',
    'RelayHostRegistration',
]
