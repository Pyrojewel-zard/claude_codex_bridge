from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import json
import secrets
import ssl
import time
from dataclasses import dataclass, field
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
from .relay_stream import (
    RELAY_STREAM_INITIAL_WINDOW_BYTES,
    RELAY_STREAM_MAX_MESSAGE_BYTES,
    RELAY_STREAM_MAX_WINDOW_BYTES,
    RelayInnerMessage,
    RelayStreamProtocolError,
    relay_inner_payload_size,
)


_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
_BINARY_RESPONSE_BYTES = 128 * 1024 * 1024
_UPLOAD_BYTES = 25 * 1024 * 1024
_JSON_CONTENT_TYPES = ('application/json', '+json')
_RELAY_INNER_OPERATION = 'relay.inner.v1'
_RELAY_OUTER_MAX_MESSAGE_BYTES = RELAY_STREAM_MAX_MESSAGE_BYTES + 32 * 1024


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
    stream_write_timeout_seconds: float = 5.0
    max_concurrent_streams: int = 16
    stream_window_bytes: int = RELAY_STREAM_INITIAL_WINDOW_BYTES

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
        if self.stream_write_timeout_seconds <= 0:
            raise ValueError('relay host connector stream timeout must be positive')
        if self.max_concurrent_streams <= 0 or self.max_concurrent_streams > 128:
            raise ValueError('relay host connector stream limit is invalid')
        if self.stream_window_bytes <= 0 or self.stream_window_bytes > RELAY_STREAM_MAX_WINDOW_BYTES:
            raise ValueError('relay host connector stream window is invalid')

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
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    streams: dict[str, '_RelayHostStream'] = field(default_factory=dict)
    tasks: set[asyncio.Task[object]] = field(default_factory=set)
    closed: bool = False


@dataclass
class _RelayHostStream:
    stream_id: str
    operation: str
    outbound_credit: int
    inbound_credit: int
    credit_changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    upstream_client: aiohttp.ClientSession | None = None
    upstream_ws: aiohttp.ClientWebSocketResponse | None = None
    task: asyncio.Task[object] | None = None
    closed: bool = False
    last_event_id: str | None = None


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
                max_msg_size=_RELAY_OUTER_MAX_MESSAGE_BYTES,
            ) as ws:
                self._ws = ws
                try:
                    await self._register(ws)
                    await self._read_loop(ws)
                finally:
                    self._ws = None
                    await self._close_sessions()
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
            session = self._sessions.pop(frame.session_id, None)
            if session is not None:
                await self._close_session(session)
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
        previous = self._sessions.pop(frame.session_id, None)
        if previous is not None:
            await self._close_session(previous)
        self._sessions[frame.session_id] = _RelayHostSession(crypto=schedule.session(role='host'))
        self._diagnostics['sessions_opened'] = int(self._diagnostics.get('sessions_opened') or 0) + 1
        self._diagnostics['state'] = 'ready'
        await ws.send_str(_canonical_json(host_hello.to_json()))

    async def _handle_gateway_envelope(self, ws: aiohttp.ClientWebSocketResponse, frame: RelayFrame) -> None:
        session = self._sessions.get(frame.session_id)
        if session is None or session.closed:
            raise MobileRelayError('relay host connector session is not established')
        envelope = RelayV2Envelope.from_json(_object_map(frame.payload.get('envelope'), 'gateway_envelope.envelope'))
        try:
            if envelope.op != _RELAY_INNER_OPERATION:
                raise RelayStreamProtocolError('operation_not_allowed')
            message = RelayInnerMessage.from_bytes(session.crypto.open(envelope))
            await self._dispatch_inner_message(ws, frame.session_id, session, message)
        except (RelayHostConnectorError, RelayCryptoError, RelayStreamProtocolError) as exc:
            self._diagnostics['requests_rejected'] = int(self._diagnostics.get('requests_rejected') or 0) + 1
            await self._send_protocol_error(ws, frame.session_id, session, exc)

    async def _dispatch_inner_message(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        if message.kind == 'request':
            self._spawn_session_task(
                session,
                self._handle_unary_request(ws, session_id, session, message),
            )
            return
        if message.kind == 'stream_open':
            await self._open_stream(ws, session_id, session, message)
            return
        if message.kind == 'stream_data':
            await self._handle_stream_data(ws, session_id, session, message)
            return
        if message.kind == 'stream_window':
            await self._handle_stream_window(session, message)
            return
        if message.kind in {'stream_cancel', 'stream_close'}:
            await self._finish_stream(
                ws,
                session_id,
                session,
                str(message.stream_id),
                notify=message.kind == 'stream_cancel',
                code='stream_not_found' if message.kind == 'stream_cancel' else 'stream_upstream_error',
            )
            return
        raise RelayStreamProtocolError('stream_protocol_error')

    async def _handle_unary_request(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        try:
            response_payload = await self._proxy_gateway_operation(str(message.operation), message.payload)
            self._diagnostics['requests_proxied'] = int(self._diagnostics.get('requests_proxied') or 0) + 1
        except (RelayHostConnectorError, RelayCryptoError, json.JSONDecodeError) as exc:
            response_payload = _safe_error_payload(exc)
            self._diagnostics['requests_rejected'] = int(self._diagnostics.get('requests_rejected') or 0) + 1
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='response',
                request_id=message.request_id,
                payload=response_payload,
            ),
        )

    async def _send_inner(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        if session.closed or ws.closed:
            raise RelayHostConnectorError('relay session is closed')
        async with session.send_lock:
            envelope = session.crypto.seal(
                op=_RELAY_INNER_OPERATION,
                plaintext=message.to_bytes(),
            )
            response_frame = RelayFrame(
                session_id=session_id,
                seq=session.next_outer_seq,
                kind='gateway_envelope',
                payload={'envelope': envelope.to_json()},
            )
            session.next_outer_seq += 1
            await asyncio.wait_for(
                ws.send_str(_canonical_json(response_frame.to_json())),
                timeout=self.config.stream_write_timeout_seconds,
            )

    async def _send_protocol_error(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        exc: BaseException,
    ) -> None:
        if isinstance(exc, RelayStreamProtocolError):
            code = exc.code
        elif isinstance(exc, RelayHostConnectorError) and 'size limit' in str(exc):
            code = 'payload_too_large'
        else:
            code = 'bad_request'
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='error',
                request_id=f'error-{secrets.token_hex(8)}',
                payload={'code': code},
            ),
        )

    def _spawn_session_task(
        self,
        session: _RelayHostSession,
        coroutine: object,
    ) -> asyncio.Task[object]:
        task = asyncio.create_task(coroutine)  # type: ignore[arg-type]
        session.tasks.add(task)
        task.add_done_callback(session.tasks.discard)
        return task

    async def _open_stream(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        stream_id = str(message.stream_id)
        if stream_id in session.streams:
            await self._send_stream_error(ws, session_id, session, stream_id, 'stream_conflict')
            return
        if len(session.streams) >= self.config.max_concurrent_streams:
            await self._send_stream_error(ws, session_id, session, stream_id, 'stream_limit')
            return
        state = _RelayHostStream(
            stream_id=stream_id,
            operation=str(message.operation),
            outbound_credit=int(message.credit_bytes or 0),
            inbound_credit=self.config.stream_window_bytes,
        )
        session.streams[stream_id] = state
        if state.operation == 'terminal':
            coroutine = self._run_terminal_stream(ws, session_id, session, state, message.payload)
        elif state.operation == 'notifications':
            coroutine = self._run_notification_stream(ws, session_id, session, state, message.payload)
        else:
            session.streams.pop(stream_id, None)
            await self._send_stream_error(ws, session_id, session, stream_id, 'operation_not_allowed')
            return
        state.task = self._spawn_session_task(session, coroutine)

    async def _handle_stream_data(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        stream_id = str(message.stream_id)
        state = session.streams.get(stream_id)
        if state is None or state.closed:
            await self._send_stream_error(ws, session_id, session, stream_id, 'stream_not_found')
            return
        payload_size = relay_inner_payload_size(message.payload)
        if payload_size > state.inbound_credit:
            await self._finish_stream(
                ws,
                session_id,
                session,
                stream_id,
                notify=True,
                code='stream_protocol_error',
            )
            return
        state.inbound_credit -= payload_size
        if state.operation != 'terminal':
            await self._finish_stream(
                ws,
                session_id,
                session,
                stream_id,
                notify=True,
                code='stream_protocol_error',
            )
            return
        try:
            await asyncio.wait_for(state.ready.wait(), timeout=self.config.request_timeout_seconds)
            upstream = state.upstream_ws
            if upstream is None or upstream.closed:
                raise RelayHostConnectorError('relay terminal upstream is closed')
            frame = _object_map(message.payload.get('frame'), 'stream_data.frame')
            await asyncio.wait_for(
                upstream.send_str(_canonical_json(frame)),
                timeout=self.config.stream_write_timeout_seconds,
            )
        except (asyncio.TimeoutError, RelayHostConnectorError):
            await self._finish_stream(
                ws,
                session_id,
                session,
                stream_id,
                notify=True,
                code='stream_upstream_error',
            )
            return
        state.inbound_credit += payload_size
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='stream_window',
                stream_id=stream_id,
                credit_bytes=payload_size,
                payload={},
            ),
        )

    async def _handle_stream_window(
        self,
        session: _RelayHostSession,
        message: RelayInnerMessage,
    ) -> None:
        state = session.streams.get(str(message.stream_id))
        if state is None or state.closed:
            return
        credit = int(message.credit_bytes or 0)
        async with state.credit_changed:
            if state.outbound_credit + credit > RELAY_STREAM_MAX_WINDOW_BYTES:
                raise RelayStreamProtocolError('stream_protocol_error')
            state.outbound_credit += credit
            state.credit_changed.notify_all()

    async def _send_stream_payload(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        state: _RelayHostStream,
        payload: Mapping[str, object],
    ) -> None:
        size = relay_inner_payload_size(payload)
        if size > RELAY_STREAM_MAX_MESSAGE_BYTES:
            raise RelayStreamProtocolError('payload_too_large')
        async with state.credit_changed:
            await asyncio.wait_for(
                state.credit_changed.wait_for(lambda: state.closed or state.outbound_credit >= size),
                timeout=self.config.stream_write_timeout_seconds,
            )
            if state.closed:
                raise RelayHostConnectorError('relay stream is closed')
            state.outbound_credit -= size
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='stream_data',
                stream_id=state.stream_id,
                payload=payload,
            ),
        )

    async def _grant_stream_input(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        state: _RelayHostStream,
    ) -> None:
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='stream_window',
                stream_id=state.stream_id,
                credit_bytes=state.inbound_credit,
                payload={},
            ),
        )

    async def _run_terminal_stream(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        state: _RelayHostStream,
        payload: Mapping[str, object],
    ) -> None:
        try:
            terminal_id = _required_text(payload.get('terminal_id'), 'terminal_id')
            token = _required_text(payload.get('terminal_token'), 'terminal_token')
            resume_cursor = payload.get('resume_cursor')
            gateway_ws_url = self._gateway_websocket_url(f'/v1/terminals/{quote(terminal_id, safe="")}')
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.config.request_timeout_seconds)
            client = aiohttp.ClientSession(timeout=timeout, raise_for_status=True)
            state.upstream_client = client
            upstream = await client.ws_connect(
                gateway_ws_url,
                max_msg_size=RELAY_STREAM_MAX_MESSAGE_BYTES,
                heartbeat=20,
            )
            state.upstream_ws = upstream
            await upstream.send_json(
                {
                    'type': 'open',
                    'terminal_id': terminal_id,
                    'token': token,
                    **({'resume_cursor': int(resume_cursor)} if resume_cursor is not None else {}),
                }
            )
            first = await upstream.receive(timeout=self.config.request_timeout_seconds)
            if first.type != aiohttp.WSMsgType.TEXT:
                raise RelayHostConnectorError('relay terminal upstream rejected open')
            first_frame = _json_object(first.data)
            await self._send_stream_payload(ws, session_id, session, state, {'frame': first_frame})
            if first_frame.get('type') != 'open':
                raise RelayHostConnectorError('relay terminal upstream rejected open')
            state.ready.set()
            await self._grant_stream_input(ws, session_id, session, state)
            async for incoming in upstream:
                if state.closed:
                    break
                if incoming.type == aiohttp.WSMsgType.TEXT:
                    await self._send_stream_payload(
                        ws,
                        session_id,
                        session,
                        state,
                        {'frame': _json_object(incoming.data)},
                    )
                elif incoming.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
            if not state.closed:
                await self._send_stream_close(ws, session_id, session, state.stream_id, 'stream_upstream_error')
        except asyncio.CancelledError:
            raise
        except Exception:
            if not state.closed and not session.closed:
                with contextlib.suppress(Exception):
                    await self._send_stream_close(ws, session_id, session, state.stream_id, 'stream_upstream_error')
        finally:
            await self._finish_stream(ws, session_id, session, state.stream_id, notify=False)

    async def _run_notification_stream(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        state: _RelayHostStream,
        payload: Mapping[str, object],
    ) -> None:
        retry_seconds = 1.0
        state.last_event_id = _optional_text(payload.get('last_event_id'))
        state.ready.set()
        await self._grant_stream_input(ws, session_id, session, state)
        try:
            while not state.closed and not session.closed:
                headers = {
                    'accept': 'text/event-stream, application/x-ndjson',
                    'cache-control': 'no-cache',
                }
                token = _optional_text(payload.get('device_token'))
                if token:
                    headers['authorization'] = f'Bearer {token}'
                if state.last_event_id:
                    headers['Last-Event-ID'] = state.last_event_id
                query = _only(
                    payload,
                    ('watch_project_id', 'watch_agent', 'watch_namespace_epoch', 'watch_provider'),
                )
                timeout = aiohttp.ClientTimeout(
                    total=None,
                    sock_connect=self.config.request_timeout_seconds,
                    sock_read=None,
                )
                client = aiohttp.ClientSession(timeout=timeout, raise_for_status=False)
                state.upstream_client = client
                try:
                    async with client.get(
                        self.config.gateway_url('/v1/mobile/notifications', query=query),
                        headers=headers,
                    ) as response:
                        if response.status < 200 or response.status >= 300:
                            raise RelayHostConnectorError('relay notification upstream rejected stream')
                        async for event in _iter_sse_events(response.content):
                            if state.closed:
                                break
                            event_id = _optional_text(event.get('id'))
                            if event_id:
                                state.last_event_id = event_id
                            retry_ms = event.get('retry')
                            if isinstance(retry_ms, int):
                                retry_seconds = min(15.0, max(0.5, retry_ms / 1000.0))
                            await self._send_stream_payload(
                                ws,
                                session_id,
                                session,
                                state,
                                {'event': event},
                            )
                finally:
                    if state.upstream_client is client:
                        state.upstream_client = None
                    await client.close()
                if not state.closed:
                    await asyncio.sleep(retry_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not state.closed and not session.closed:
                with contextlib.suppress(Exception):
                    await self._send_stream_close(ws, session_id, session, state.stream_id, 'stream_upstream_error')
        finally:
            await self._finish_stream(ws, session_id, session, state.stream_id, notify=False)

    async def _send_stream_error(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        stream_id: str,
        code: str,
    ) -> None:
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='error',
                stream_id=stream_id,
                payload={'code': code},
            ),
        )

    async def _send_stream_close(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        session_id: str,
        session: _RelayHostSession,
        stream_id: str,
        code: str,
    ) -> None:
        await self._send_inner(
            ws,
            session_id,
            session,
            RelayInnerMessage(
                kind='stream_close',
                stream_id=stream_id,
                payload={'code': code},
            ),
        )

    async def _finish_stream(
        self,
        ws: aiohttp.ClientWebSocketResponse | None,
        session_id: str,
        session: _RelayHostSession,
        stream_id: str,
        *,
        notify: bool,
        code: str = 'stream_upstream_error',
    ) -> None:
        state = session.streams.pop(stream_id, None)
        if state is None:
            if notify and not session.closed:
                await self._send_stream_error(ws, session_id, session, stream_id, 'stream_not_found')
            return
        state.closed = True
        state.ready.set()
        async with state.credit_changed:
            state.credit_changed.notify_all()
        if notify and ws is not None and not session.closed and not ws.closed:
            with contextlib.suppress(Exception):
                await self._send_stream_close(ws, session_id, session, stream_id, code)
        upstream_ws = state.upstream_ws
        if upstream_ws is not None and not upstream_ws.closed:
            with contextlib.suppress(Exception):
                await upstream_ws.close()
        client = state.upstream_client
        if client is not None and not client.closed:
            with contextlib.suppress(Exception):
                await client.close()
        task = state.task
        current = asyncio.current_task()
        if task is not None and task is not current and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _close_session(self, session: _RelayHostSession) -> None:
        if session.closed:
            return
        session.closed = True
        for stream_id in list(session.streams):
            await self._finish_stream(
                None,
                '',
                session,
                stream_id,
                notify=False,
            )
        for task in list(session.tasks):
            if not task.done():
                task.cancel()
        if session.tasks:
            await asyncio.gather(*session.tasks, return_exceptions=True)
        session.crypto.close()

    def _gateway_websocket_url(self, path: str) -> str:
        parsed = urlparse(self.config.gateway_origin)
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        return urlunparse((scheme, parsed.netloc, path, '', '', ''))

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

    async def _close_sessions(self) -> None:
        for session in list(self._sessions.values()):
            await self._close_session(session)
        self._sessions.clear()


async def _iter_sse_events(content: aiohttp.StreamReader):
    event_id: str | None = None
    event_name: str | None = None
    retry_ms: int | None = None
    data_lines: list[str] = []

    def flush() -> dict[str, object] | None:
        nonlocal event_id, event_name, retry_ms, data_lines
        if not data_lines:
            event_name = None
            retry_ms = None
            return None
        data_text = '\n'.join(data_lines)
        data_lines = []
        try:
            decoded = json.loads(data_text)
        except json.JSONDecodeError as exc:
            raise RelayHostConnectorError('relay notification event JSON invalid') from exc
        if not isinstance(decoded, Mapping):
            raise RelayHostConnectorError('relay notification event must be an object')
        result: dict[str, object] = {'data': {str(key): value for key, value in decoded.items()}}
        if event_id is not None:
            result['id'] = event_id
        if event_name is not None:
            result['event'] = event_name
        if retry_ms is not None:
            result['retry'] = retry_ms
        event_name = None
        retry_ms = None
        return result

    async for raw_line in content:
        if len(raw_line) > RELAY_STREAM_MAX_MESSAGE_BYTES:
            raise RelayHostConnectorError('relay notification event exceeds size limit')
        try:
            line = raw_line.decode('utf-8').rstrip('\r\n')
        except UnicodeDecodeError as exc:
            raise RelayHostConnectorError('relay notification stream is not UTF-8') from exc
        if not line:
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(':'):
            continue
        if line.startswith('{'):
            if data_lines:
                raise RelayHostConnectorError('relay notification stream framing invalid')
            data_lines.append(line)
            event = flush()
            if event is not None:
                yield event
            continue
        field, separator, value = line.partition(':')
        if separator and value.startswith(' '):
            value = value[1:]
        if field == 'data':
            data_lines.append(value)
        elif field == 'id' and '\x00' not in value:
            event_id = value
        elif field == 'event':
            event_name = value
        elif field == 'retry':
            try:
                parsed_retry = int(value)
            except ValueError:
                continue
            if parsed_retry >= 0:
                retry_ms = parsed_retry
    event = flush()
    if event is not None:
        yield event


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
