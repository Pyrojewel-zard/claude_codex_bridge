from __future__ import annotations

import json

import pytest

from mobile_gateway.relay_stream import (
    RELAY_STREAM_INITIAL_WINDOW_BYTES,
    RELAY_STREAM_MAX_MESSAGE_BYTES,
    RELAY_STREAM_MAX_WINDOW_BYTES,
    RelayInnerMessage,
    RelayStreamProtocolError,
    relay_inner_payload_size,
)


def test_relay_inner_protocol_round_trips_fixed_request_and_stream_frames() -> None:
    request = RelayInnerMessage(
        kind='request',
        request_id='request-demo-0001',
        operation='agent_conversation',
        payload={
            'project_id': 'project-demo',
            'agent': 'worker1',
            'namespace_epoch': 7,
        },
    )
    opened = RelayInnerMessage(
        kind='stream_open',
        stream_id='stream-demo-0001',
        operation='terminal',
        credit_bytes=RELAY_STREAM_INITIAL_WINDOW_BYTES,
        payload={'terminal_id': 'terminal-demo'},
    )

    assert RelayInnerMessage.from_bytes(request.to_bytes()) == request
    assert RelayInnerMessage.from_bytes(opened.to_bytes()) == opened
    assert relay_inner_payload_size({'data': 'abc'}) == len(b'{"data":"abc"}')


@pytest.mark.parametrize(
    ('payload', 'code'),
    [
        (
            {
                'schema_version': 0,
                'kind': 'request',
                'request_id': 'request-demo-0001',
                'operation': 'health',
                'payload': {},
            },
            'bad_request',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'request',
                'request_id': 'request-demo-0001',
                'operation': 'arbitrary_proxy',
                'payload': {},
            },
            'operation_not_allowed',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'request',
                'request_id': 'request-demo-0001',
                'operation': 'upload_file',
                'payload': {},
            },
            'operation_not_allowed',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'stream_open',
                'stream_id': 'stream-demo-0001',
                'operation': 'notifications',
                'credit_bytes': RELAY_STREAM_MAX_WINDOW_BYTES + 1,
                'payload': {},
            },
            'stream_protocol_error',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'error',
                'request_id': 'request-demo-0001',
                'stream_id': 'stream-demo-0001',
                'payload': {'code': 'bad_request'},
            },
            'stream_protocol_error',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'stream_data',
                'stream_id': 'stream-demo-0001',
                'credit_bytes': 1,
                'payload': {},
            },
            'stream_protocol_error',
        ),
        (
            {
                'schema_version': 1,
                'kind': 'stream_window',
                'stream_id': 'stream-demo-0001',
                'credit_bytes': 1.5,
                'payload': {},
            },
            'bad_request',
        ),
    ],
)
def test_relay_inner_protocol_rejects_downgrade_proxying_and_ambiguous_identity(
    payload: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(RelayStreamProtocolError) as raised:
        RelayInnerMessage.from_json(payload)

    assert raised.value.code == code


def test_relay_inner_protocol_rejects_oversized_and_non_object_payloads() -> None:
    with pytest.raises(RelayStreamProtocolError, match='payload_too_large'):
        RelayInnerMessage.from_bytes(b'{' + b' ' * RELAY_STREAM_MAX_MESSAGE_BYTES + b'}')

    with pytest.raises(RelayStreamProtocolError, match='bad_request'):
        RelayInnerMessage.from_bytes(json.dumps(['not', 'an', 'object']).encode())


def test_relay_inner_error_codes_are_fixed_and_redacted() -> None:
    with pytest.raises(RelayStreamProtocolError, match='stream_protocol_error'):
        RelayInnerMessage.from_json(
            {
                'schema_version': 1,
                'kind': 'error',
                'request_id': 'request-demo-0001',
                'payload': {'code': '/secret/project/path'},
            }
        )
