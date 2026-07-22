from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import secrets
import ssl
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote, urlencode, urlparse, urlunparse

import aiohttp
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from .relay import MobileRelayError, RelayFrame, RelayHandshakeTranscript
from .relay_admission import sign_host_session_proof
from .relay_crypto import (
    RELAY_PROTOCOL_VERSION,
    RelayCryptoError,
    RelayCryptoSession,
    RelayV2Envelope,
    derive_relay_v2_key_schedule,
    host_fingerprint_for_public_key,
    public_key_b64,
)


_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
_BINARY_RESPONSE_BYTES = 128 * 1024 * 1024
_UPLOAD_BYTES = 25 * 1024 * 1024
_JSON_CONTENT_TYPES = ('application/json', '+json')


class RelayHostConnectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class RelayHostConnectorConfig:
    relay_origin: str
    gateway_origin: str
    host_id: str
    host_signing_key: ed25519.Ed25519PrivateKey
    host_crypto_private_key: x25519.X25519PrivateKey
    tls_context: ssl.SSLContext | None = None
    request_timeout_seconds: float = 5.0
    min_reconnect_delay_seconds: float = 0.5
    max_reconnect_delay_seconds: float = 15.0

    def __post_init__(self) -> None:
        object.__setattr__(self, 'relay_origin', _safe_relay_origin(self.relay_origin))
        object.__setattr__(self, 'gateway_origin', _safe_gateway_origin(self.gateway_origin))
        if not str(self.host_id or '').strip():
            raise ValueError('relay host connector requires host_id')
        if self.request_timeout_seconds <= 0:
            raise ValueError('relay host connector request timeout must be positive')
        if self.min_reconnect_delay_seconds <= 0 or self.max_reconnect_delay_seconds <= 0:
            raise ValueError('relay host connector reconnect delays must be positive')
        if self.min_reconnect_delay_seconds > self.max_reconnect_delay_seconds:
            raise ValueError('relay host connector reconnect delay bounds are invalid')

    @property
    def host_public_key_b64(self) -> str:
        return public_key_b64(self.host_crypto_private_key)

    @property
    def host_fingerprint(self) -> str:
        return host_fingerprint_for_public_key(self.host_public_key_b64)

    def relay_url(self, path: str) -> str:
        if not path.startswith('/'):
            raise ValueError('relay path must be absolute')
        parsed = urlparse(self.relay_origin)
        return urlunparse((parsed.scheme, parsed.netloc, path, '', '', ''))

    def gateway_url(self, path: str, *, query: Mapping[str, object] | None = None) -> str:
        if not path.startswith('/'):
            raise RelayHostConnectorError('gateway path must be absolute')
        parsed = urlparse(self.gateway_origin)
        query_text = urlencode({key: str(value) for key, value in (query or {}).items() if value is not None})
        return urlunparse((parsed.scheme, parsed.netloc, path, '', query_text, ''))


@dataclass
class _RelayHostSession:
    crypto: RelayCryptoSession
    next_outer_seq: int = 3


class RelayHostConnector:
    def __init__(self, config: RelayHostConnectorConfig) -> None:
        self.config = config
        self._stop = asyncio.Event()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._sessions: dict[str, _RelayHostSession] = {}
        self._diagnostics: dict[str, object] = {
            'state': 'initialized',
            'host_id': config.host_id,
            'relay_origin': config.relay_origin,
            'gateway_origin': config.gateway_origin,
            'host_fingerprint': config.host_fingerprint,
            'sessions_opened': 0,
            'requests_proxied': 0,
            'requests_rejected': 0,
            'last_error_code': '',
        }

    def diagnostics(self) -> dict[str, object]:
        return dict(self._diagnostics)

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None and not ws.closed:
            asyncio.create_task(ws.close())

    async def run_forever(self) -> None:
        delay = self.config.min_reconnect_delay_seconds
        while not self._stop.is_set():
            try:
                await self.connect_once()
                delay = self.config.min_reconnect_delay_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set_error('relay_connect_failed', exc)
                await self._sleep(delay)
                delay = min(self.config.max_reconnect_delay_seconds, delay * 2)

    async def connect_once(self) -> None:
        self._diagnostics['state'] = 'connecting'
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.config.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, raise_for_status=True) as client:
            async with client.ws_connect(
                self.config.relay_url('/v2/host'),
                ssl=self.config.tls_context,
                heartbeat=20,
                max_msg_size=0,
            ) as ws:
                self._ws = ws
                try:
                    await self._register(ws)
                    await self._read_loop(ws)
                finally:
                    self._ws = None
                    self._close_sessions()
                    if self._diagnostics.get('state') not in {'auth_rejected', 'stopped'}:
                        self._diagnostics['state'] = 'disconnected'

    async def _register(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        await ws.send_str(_canonical_json(self._host_register_frame().to_json()))
        message = await ws.receive(timeout=self.config.request_timeout_seconds)
        if message.type != aiohttp.WSMsgType.TEXT:
            self._diagnostics['state'] = 'auth_rejected'
            self._diagnostics['last_error_code'] = 'relay_auth_rejected'
            return
        raw_frame = _json_object(message.data)
        if raw_frame.get('kind') == 'error':
            code = _error_code(raw_frame)
            self._diagnostics['state'] = 'auth_rejected'
            self._diagnostics['last_error_code'] = code
            return
        frame = RelayFrame.from_json(raw_frame)
        if frame.kind == 'ack':
            self._diagnostics['state'] = 'registered'
            self._diagnostics['last_error_code'] = ''
            return
        self._diagnostics['state'] = 'auth_rejected'
        self._diagnostics['last_error_code'] = 'relay_auth_rejected'

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        if self._diagnostics.get('state') == 'auth_rejected':
            return
        while not self._stop.is_set():
            message = await ws.receive(timeout=None)
            if message.type == aiohttp.WSMsgType.TEXT:
                raw_frame = _json_object(message.data)
                if raw_frame.get('kind') == 'error':
                    self._diagnostics['last_error_code'] = _error_code(raw_frame)
                    continue
                await self._handle_frame(ws, RelayFrame.from_json(raw_frame))
            elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                break

    async def _handle_frame(self, ws: aiohttp.ClientWebSocketResponse, frame: RelayFrame) -> None:
        if frame.kind == 'client_hello':
            await self._handle_client_hello(ws, frame)
            return
        if frame.kind == 'gateway_envelope':
            await self._handle_gateway_envelope(ws, frame)
            return
        if frame.kind == 'heartbeat':
            await ws.send_str(_canonical_json(_ack_frame(frame).to_json()))
            return
        if frame.kind == 'close':
            self._sessions.pop(frame.session_id, None)
            return
        raise MobileRelayError(f'relay host connector frame is not allowed: {frame.kind}')

    async def _handle_client_hello(self, ws: aiohttp.ClientWebSocketResponse, frame: RelayFrame) -> None:
        if str(frame.payload.get('host_id') or '') != self.config.host_id:
            raise MobileRelayError('relay host connector client_hello host mismatch')
        host_hello = RelayFrame(
            session_id=frame.session_id,
            seq=frame.seq + 1,
            kind='host_hello',
            payload={
                'host_id': self.config.host_id,
                'server_fingerprint': self.config.host_fingerprint,
                'host_pubkey_b64': self.config.host_public_key_b64,
                'accepted_version': RELAY_PROTOCOL_VERSION,
            },
        )
        RelayHandshakeTranscript.negotiate(client_hello=frame, host_hello=host_hello)
        schedule = derive_relay_v2_key_schedule(
            local_private_key=self.config.host_crypto_private_key,
            peer_public_key_b64=str(frame.payload.get('client_pubkey_b64') or ''),
            role='host',
            session_id=frame.session_id,
            client_public_key_b64=str(frame.payload.get('client_pubkey_b64') or ''),
            host_public_key_b64=self.config.host_public_key_b64,
            expected_host_fingerprint=self.config.host_fingerprint,
        )
        self._sessions[frame.session_id] = _RelayHostSession(crypto=schedule.session(role='host'))
        self._diagnostics['sessions_opened'] = int(self._diagnostics.get('sessions_opened') or 0) + 1
        self._diagnostics['state'] = 'ready'
        await ws.send_str(_canonical_json(host_hello.to_json()))

    async def _handle_gateway_envelope(self, ws: aiohttp.ClientWebSocketResponse, frame: RelayFrame) -> None:
        session = self._sessions.get(frame.session_id)
        if session is None:
            raise MobileRelayError('relay host connector session is not established')
        envelope = RelayV2Envelope.from_json(_object_map(frame.payload.get('envelope'), 'gateway_envelope.envelope'))
        try:
            request_payload = json.loads(session.crypto.open(envelope).decode('utf-8'))
            if not isinstance(request_payload, dict):
                raise RelayHostConnectorError('relay gateway request must be an object')
            response_payload = await self._proxy_gateway_operation(envelope.op, request_payload)
            self._diagnostics['requests_proxied'] = int(self._diagnostics.get('requests_proxied') or 0) + 1
        except (RelayHostConnectorError, RelayCryptoError, json.JSONDecodeError) as exc:
            response_payload = _safe_error_payload(exc)
            self._diagnostics['requests_rejected'] = int(self._diagnostics.get('requests_rejected') or 0) + 1
        response_envelope = session.crypto.seal(
            op=f'{envelope.op}.response',
            plaintext=_canonical_json(response_payload).encode('utf-8'),
        )
        response_frame = RelayFrame(
            session_id=frame.session_id,
            seq=session.next_outer_seq,
            kind='gateway_envelope',
            payload={'envelope': response_envelope.to_json()},
        )
        session.next_outer_seq += 1
        await ws.send_str(_canonical_json(response_frame.to_json()))

    async def _proxy_gateway_operation(self, operation: str, payload: Mapping[str, object]) -> dict[str, object]:
        request = _gateway_request(operation, payload)
        headers = {'accept': request.accept, **request.headers}
        device_token = _optional_text(payload.get('device_token'))
        if device_token:
            headers['authorization'] = f'Bearer {device_token}'
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, raise_for_status=False) as client:
            body = request.body
            if body is not None:
                headers['content-type'] = request.content_type
            async with client.request(
                request.method,
                self.config.gateway_url(request.path, query=request.query),
                data=body,
                headers=headers,
            ) as response:
                return await _response_payload(response, max_bytes=request.max_response_bytes)

    def _host_register_frame(self) -> RelayFrame:
        nonce_b64 = _b64(secrets.token_bytes(24))
        expires_at = int(time.time()) + 60
        return RelayFrame(
            session_id='host-control',
            seq=1,
            kind='host_register',
            payload={
                'host_id': self.config.host_id,
                'nonce_b64': nonce_b64,
                'proof_expires_at': expires_at,
                'signature_b64': sign_host_session_proof(
                    self.config.host_signing_key,
                    host_id=self.config.host_id,
                    nonce_b64=nonce_b64,
                    expires_at=expires_at,
                ),
                'supported_versions': [RELAY_PROTOCOL_VERSION],
                'capabilities': ['relay.forward'],
                'diagnostics': {
                    'connector': 'ccb_mobile_host_connector',
                    'host_fingerprint': self.config.host_fingerprint,
                },
            },
        )

    async def _sleep(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return

    def _set_error(self, code: str, exc: BaseException) -> None:
        self._diagnostics['state'] = code
        self._diagnostics['last_error_code'] = code
        self._diagnostics['last_error_class'] = exc.__class__.__name__

    def _close_sessions(self) -> None:
        for session in self._sessions.values():
            session.crypto.close()
        self._sessions.clear()


@dataclass(frozen=True)
class _GatewayRequest:
    method: str
    path: str
    query: Mapping[str, object]
    headers: Mapping[str, str] | None = None
    body: bytes | None = None
    content_type: str = 'application/json'
    accept: str = 'application/json'
    max_response_bytes: int = _JSON_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(self, 'headers', {})


def _gateway_request(operation: str, payload: Mapping[str, object]) -> _GatewayRequest:
    op = str(operation or '').strip()
    if op == 'health':
        return _GatewayRequest('GET', '/v1/health', {})
    if op == 'device':
        return _GatewayRequest('GET', '/v1/devices/me', {})
    if op == 'list_projects':
        return _GatewayRequest('GET', '/v1/projects', {})
    if op == 'get_project_view':
        return _GatewayRequest('GET', f'/v1/projects/{_segment(payload, "project_id")}/view', {})
    if op == 'focus_agent':
        project = _segment(payload, 'project_id')
        return _json_request('POST', f'/v1/projects/{project}/focus-agent', _only(payload, ('agent', 'namespace_epoch')))
    if op == 'focus_window':
        project = _segment(payload, 'project_id')
        return _json_request('POST', f'/v1/projects/{project}/focus-window', _only(payload, ('window', 'namespace_epoch')))
    if op == 'terminal_history':
        project = _segment(payload, 'project_id')
        return _GatewayRequest(
            'GET',
            f'/v1/projects/{project}/terminal-history',
            _only(payload, ('agent', 'namespace_epoch', 'max_lines')),
        )
    if op == 'agent_conversation':
        project = _segment(payload, 'project_id')
        agent = _segment(payload, 'agent')
        return _GatewayRequest(
            'GET',
            f'/v1/projects/{project}/agents/{agent}/conversation',
            _only(payload, ('namespace_epoch', 'limit', 'cursor')),
        )
    if op == 'submit_agent_message':
        project = _segment(payload, 'project_id')
        agent = _segment(payload, 'agent_name')
        return _json_request('POST', f'/v1/projects/{project}/agents/{agent}/messages', dict(payload))
    if op == 'lifecycle':
        project = _segment(payload, 'project_id')
        return _json_request('POST', f'/v1/projects/{project}/lifecycle', _only(payload, ('project_id', 'action')))
    if op == 'open_terminal':
        target = _object_map(payload.get('target'), 'target')
        project = _segment(target, 'project_id')
        return _json_request('POST', f'/v1/projects/{project}/terminals', dict(payload))
    if op == 'upload_file':
        project = _segment(payload, 'project_id')
        agent = _segment(payload, 'agent')
        file_name = _required_text(payload.get('file_name'), 'file_name')
        body = _b64decode(_required_text(payload.get('body_b64'), 'body_b64'))
        if len(body) > _UPLOAD_BYTES:
            raise RelayHostConnectorError('relay upload exceeds size limit')
        return _GatewayRequest(
            'POST',
            f'/v1/projects/{project}/agents/{agent}/files',
            {},
            {'X-Ccb-File-Name': quote(file_name, safe='')},
            body=body,
            content_type=_required_text(payload.get('mime_type'), 'mime_type'),
            max_response_bytes=_JSON_RESPONSE_BYTES,
        )
    if op == 'download_file':
        project = _segment(payload, 'project_id')
        agent = _segment(payload, 'agent')
        file_id = _segment(payload, 'file_id')
        return _GatewayRequest(
            'GET',
            f'/v1/projects/{project}/agents/{agent}/files/{file_id}',
            {},
            accept='*/*',
            max_response_bytes=_BINARY_RESPONSE_BYTES,
        )
    if op == 'notification_events':
        return _GatewayRequest(
            'GET',
            '/v1/mobile/notifications',
            _only(payload, ('last_event_id', 'once', 'project_id', 'agent', 'namespace_epoch')),
        )
    raise RelayHostConnectorError('relay operation is not allowlisted')


def _json_request(method: str, path: str, payload: Mapping[str, object]) -> _GatewayRequest:
    return _GatewayRequest(method, path, {}, body=_canonical_json(payload).encode('utf-8'))


async def _response_payload(response: aiohttp.ClientResponse, *, max_bytes: int) -> dict[str, object]:
    body = await response.content.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise RelayHostConnectorError('relay gateway response exceeds size limit')
    content_type = response.headers.get('content-type', '')
    if response.status < 200 or response.status >= 300:
        return {
            'ok': False,
            'status': int(response.status),
            'error': _safe_gateway_error_code(response.status),
        }
    if _is_json_content_type(content_type):
        try:
            decoded = json.loads(body.decode('utf-8') if body else '{}')
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RelayHostConnectorError('relay gateway JSON response invalid') from exc
        if not isinstance(decoded, dict):
            raise RelayHostConnectorError('relay gateway JSON response must be an object')
        return {'ok': True, 'status': int(response.status), 'body': decoded}
    return {
        'ok': True,
        'status': int(response.status),
        'body_b64': _b64(body),
        'content_type': content_type.split(';', 1)[0] or 'application/octet-stream',
    }


def _safe_error_payload(exc: BaseException) -> dict[str, object]:
    if isinstance(exc, RelayHostConnectorError):
        if 'allowlisted' in str(exc):
            return {'ok': False, 'status': 400, 'error': 'relay_operation_not_allowed'}
        if 'size limit' in str(exc):
            return {'ok': False, 'status': 413, 'error': 'relay_payload_too_large'}
    return {'ok': False, 'status': 400, 'error': 'relay_gateway_request_rejected'}


def _safe_gateway_error_code(status: int) -> str:
    if status in {401, 403}:
        return 'gateway_auth_rejected'
    if status == 404:
        return 'gateway_not_found'
    if status == 409:
        return 'gateway_conflict'
    if status == 429:
        return 'gateway_rate_limited'
    if status >= 500:
        return 'gateway_unavailable'
    return 'gateway_rejected'


def _safe_relay_origin(value: str) -> str:
    parsed = urlparse(str(value or '').strip())
    if parsed.scheme != 'wss':
        raise ValueError('relay host connector requires a wss:// relay origin')
    if not parsed.hostname:
        raise ValueError('relay host connector relay origin requires hostname')
    if parsed.username or parsed.password:
        raise ValueError('relay host connector relay origin must not contain credentials')
    if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('relay host connector requires an origin-only relay URL')
    return urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))


def _safe_gateway_origin(value: str) -> str:
    parsed = urlparse(str(value or '').strip())
    if parsed.scheme not in {'http', 'https'}:
        raise ValueError('relay host connector gateway origin must be http(s)')
    if not parsed.hostname:
        raise ValueError('relay host connector gateway origin requires hostname')
    if parsed.username or parsed.password:
        raise ValueError('relay host connector gateway origin must not contain credentials')
    if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('relay host connector gateway URL must be an origin')
    if not _is_loopback_host(parsed.hostname):
        raise ValueError('relay host connector gateway origin must be loopback')
    return urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))


def _is_loopback_host(value: str) -> bool:
    host = value.strip().strip('[]').lower()
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ack_frame(frame: RelayFrame) -> RelayFrame:
    return RelayFrame(
        session_id=frame.session_id,
        seq=frame.seq + 1,
        kind='ack',
        payload={'ack_seq': frame.seq},
    )


def _only(payload: Mapping[str, object], keys: tuple[str, ...]) -> dict[str, object]:
    return {key: payload[key] for key in keys if key in payload and payload[key] is not None}


def _object_map(value: object, name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise RelayHostConnectorError(f'relay gateway request missing object: {name}')


def _json_object(value: str) -> dict[str, object]:
    decoded = json.loads(value)
    if isinstance(decoded, Mapping):
        return {str(key): item for key, item in decoded.items()}
    raise RelayHostConnectorError('relay frame must be a JSON object')


def _error_code(frame: Mapping[str, object]) -> str:
    payload = frame.get('payload')
    if isinstance(payload, Mapping):
        text = str(payload.get('code') or '').strip()
        if text:
            return text
    return 'relay_auth_rejected'


def _segment(payload: Mapping[str, object], name: str) -> str:
    return quote(_required_text(payload.get(name), name), safe='')


def _required_text(value: object, name: str) -> str:
    text = str(value or '').strip()
    if not text:
        raise RelayHostConnectorError(f'relay gateway request missing field: {name}')
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or '').strip()
    return text or None


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _is_json_content_type(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in _JSON_CONTENT_TYPES)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(value)).decode('ascii').rstrip('=')


def _b64decode(value: str) -> bytes:
    try:
        text = str(value).strip()
        return base64.urlsafe_b64decode((text + '=' * (-len(text) % 4)).encode('ascii'))
    except Exception as exc:
        raise RelayHostConnectorError('relay gateway request field must be base64url') from exc


__all__ = [
    'RelayHostConnector',
    'RelayHostConnectorConfig',
    'RelayHostConnectorError',
]
