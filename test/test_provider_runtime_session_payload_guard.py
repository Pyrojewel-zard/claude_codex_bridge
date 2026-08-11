from __future__ import annotations

from completion.models import CompletionSourceKind
from provider_runtime.session_payload import (
    build_provider_runtime_backend_ref,
    completion_source_for_kind,
    namespace_restore_token_present,
    redacted_namespace_ref,
)


def test_completion_source_for_kind_preserves_roadmap_projection_without_losing_exact_kind() -> None:
    assert completion_source_for_kind(CompletionSourceKind.PROTOCOL_EVENT_STREAM) == 'provider_event_stream'
    assert completion_source_for_kind(CompletionSourceKind.SESSION_EVENT_LOG) == 'provider_native_log'
    assert completion_source_for_kind(CompletionSourceKind.SESSION_SNAPSHOT) == 'provider_native_log'
    assert completion_source_for_kind(CompletionSourceKind.STRUCTURED_RESULT_STREAM) == 'provider_native_log'
    assert completion_source_for_kind(CompletionSourceKind.TERMINAL_TEXT) == 'terminal_capture'


def test_provider_runtime_backend_ref_redacts_namespace_restore_token() -> None:
    namespace_ref = {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'namespace_id': 'ns-1',
        'session_name': 'ccb-demo',
        'ipc_kind': 'herdr_socket',
        'ipc_ref': '127.0.0.1:54321',
        'restore_token': 'raw-token-1',
    }
    pane_ref = {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'pane_id': 'pane-1',
    }

    redacted = redacted_namespace_ref(namespace_ref)
    backend_ref = build_provider_runtime_backend_ref(
        provider='codex',
        agent_slug='agent1',
        backend_impl='herdr',
        namespace_ref=namespace_ref,
        pane_ref=pane_ref,
        managed_home='D:/tmp/codex-home',
        completion_source_kind=CompletionSourceKind.PROTOCOL_EVENT_STREAM,
    )

    assert namespace_restore_token_present(namespace_ref) is True
    assert redacted == {
        'backend_family': 'herdr-native',
        'backend_impl': 'herdr',
        'namespace_id': 'ns-1',
        'session_name': 'ccb-demo',
        'ipc_kind': 'herdr_socket',
        'ipc_ref': '127.0.0.1:54321',
    }
    assert backend_ref['namespace_ref'] == redacted
    assert backend_ref['pane_ref'] == pane_ref
    assert backend_ref['completion_source'] == 'provider_event_stream'
    assert backend_ref['completion_source_kind'] == 'protocol_event_stream'
