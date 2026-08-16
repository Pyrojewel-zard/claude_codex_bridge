from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ccbd.start_runtime.binding import (
    declared_binding_tmux_socket_path,
    relabel_project_namespace_pane,
    usable_agent_only_project_binding,
    usable_project_namespace_binding,
)
from ccbd.services.project_namespace_pane import ProjectNamespacePaneRecord
from provider_core.session_binding_evidence import AgentBinding


def _binding(**overrides):
    values = {
        'runtime_ref': 'tmux:%41',
        'pane_state': 'alive',
        'active_pane_id': '%41',
        'pane_id': '%41',
        'tmux_socket_path': '/tmp/ccb.sock',
        'session_file': '',
        'ccb_session_id': 'ccb-session-1',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_declared_binding_tmux_socket_path_prefers_session_file_authority(tmp_path: Path) -> None:
    session_file = tmp_path / 'session.json'
    session_file.write_text('{"tmux_socket_path": "/tmp/from-session.sock"}', encoding='utf-8')

    declared, socket_path = declared_binding_tmux_socket_path(_binding(session_file=str(session_file), tmux_socket_path=''))

    assert declared is True
    assert socket_path == '/tmp/from-session.sock'


def test_usable_project_namespace_binding_requires_matching_namespace_record() -> None:
    binding = _binding()
    record = SimpleNamespace(matches=lambda **kwargs: kwargs['slot_key'] == 'agent1' and kwargs['project_id'] == 'proj-1')

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@2',
        agent_name='agent1',
        project_id='proj-1',
        tmux_backend_factory=lambda socket_path=None: SimpleNamespace(socket_path=socket_path),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: record,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is binding


def test_usable_agent_only_project_binding_accepts_undeclared_socket_binding() -> None:
    binding = _binding(session_file='', tmux_socket_path='', pane_state='unknown')

    usable = usable_agent_only_project_binding(
        binding,
        tmux_socket_path='/tmp/current.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@2',
        agent_name='agent1',
        project_id='proj-1',
        tmux_backend_factory=lambda socket_path=None: SimpleNamespace(socket_path=socket_path),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: None,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is binding


def test_relabel_project_namespace_pane_applies_identity_for_project_socket() -> None:
    applied: list[tuple[str, str, dict[str, object]]] = []

    class Backend:
        def set_pane_title(self, pane_id: str, title: str) -> None:
            return None

        def set_pane_user_option(self, pane_id: str, key: str, value: str) -> None:
            return None

    pane_id = relabel_project_namespace_pane(
        binding=_binding(),
        agent_name='agent1',
        project_id='proj-1',
        style_index=2,
        tmux_socket_path='/tmp/ccb.sock',
        namespace_epoch=5,
        tmux_backend_factory=lambda socket_path=None: Backend(),
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
        apply_ccb_pane_identity_fn=lambda backend, pane, **kwargs: applied.append((pane, kwargs['title'], kwargs)),
    )

    assert pane_id == '%41'
    assert applied == [
        (
            '%41',
            'agent1',
            {
                'title': 'agent1',
                'agent_label': 'agent1',
                'project_id': 'proj-1',
                'order_index': 2,
                'slot_key': 'agent1',
                'window_name': None,
                'session_id': 'ccb-session-1',
                'namespace_epoch': 5,
                'managed_by': 'ccbd',
            },
        )
    ]


def test_usable_project_namespace_binding_rejects_old_workspace_window() -> None:
    binding = _binding()
    record = SimpleNamespace(matches=lambda **kwargs: kwargs.get('window_id') == '@2')

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@3',
        agent_name='agent1',
        project_id='proj-1',
        tmux_backend_factory=lambda socket_path=None: SimpleNamespace(socket_path=socket_path),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: record,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is None


def test_usable_project_namespace_binding_accepts_declared_secondary_window() -> None:
    binding = AgentBinding(
        runtime_ref='tmux:%41',
        session_ref='session-41',
        pane_id='%41',
        active_pane_id='%41',
        pane_state='alive',
        tmux_socket_path='/tmp/ccb.sock',
        terminal='tmux',
    )
    record = ProjectNamespacePaneRecord(
        pane_id='%41',
        session_name='ccb-demo',
        window_id='@1',
        window_name='review',
        role='agent',
        slot_key='agent1',
        ccb_window='review',
        project_id='proj-1',
        managed_by='ccbd',
        namespace_epoch=7,
        alive=True,
    )

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@0',
        agent_name='agent1',
        project_id='proj-1',
        window_name='review',
        namespace_epoch=7,
        namespace_pane_records={'%41': record},
        tmux_backend_factory=lambda socket_path=None: (_ for _ in ()).throw(
            AssertionError('snapshot should avoid tmux inspection')
        ),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: None,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is not None
    assert usable.tmux_window_id == '@1'
    assert usable.tmux_window_name == 'review'


def test_usable_project_namespace_binding_accepts_mux_runtime_ref_with_mux_pane_id() -> None:
    binding = AgentBinding(
        runtime_ref='mux:w7V:p3',
        session_ref='session-41',
        pane_id='w7V:p3',
        active_pane_id='w7V:p3',
        pane_state='unknown',
        terminal='mux',
    )

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@0',
        agent_name='agent1',
        project_id='proj-1',
        window_name='main',
        namespace_epoch=7,
        assigned_pane_id='w7V:p3',
        namespace_pane_records=None,
        tmux_backend_factory=lambda socket_path=None: (_ for _ in ()).throw(
            AssertionError('mux snapshot binding must not require tmux inspection')
        ),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: None,
        same_tmux_socket_path_fn=lambda left, right: False,
    )

    assert usable is not None
    assert usable is binding


def test_usable_project_namespace_binding_rejects_wrong_declared_window_or_epoch() -> None:
    binding = AgentBinding(
        runtime_ref='tmux:%41',
        session_ref='session-41',
        pane_id='%41',
        active_pane_id='%41',
        pane_state='alive',
        tmux_socket_path='/tmp/ccb.sock',
        terminal='tmux',
    )
    record = ProjectNamespacePaneRecord(
        pane_id='%41',
        session_name='ccb-demo',
        window_id='@1',
        window_name='review',
        role='agent',
        slot_key='agent1',
        ccb_window='review',
        project_id='proj-1',
        managed_by='ccbd',
        namespace_epoch=6,
        alive=True,
    )

    common = {
        'tmux_socket_path': '/tmp/ccb.sock',
        'tmux_session_name': 'ccb-demo',
        'workspace_window_id': '@0',
        'agent_name': 'agent1',
        'project_id': 'proj-1',
        'namespace_pane_records': {'%41': record},
        'tmux_backend_factory': lambda socket_path=None: object(),
        'inspect_project_namespace_pane_fn': lambda backend, pane_id: None,
        'same_tmux_socket_path_fn': lambda left, right: str(left or '') == str(right or ''),
    }

    assert usable_project_namespace_binding(
        binding,
        window_name='other',
        namespace_epoch=6,
        **common,
    ) is None
    assert usable_project_namespace_binding(
        binding,
        window_name='review',
        namespace_epoch=7,
        **common,
    ) is None
    assert usable_project_namespace_binding(
        binding,
        window_name='review',
        namespace_epoch=None,
        **common,
    ) is None


def test_usable_project_namespace_binding_trusts_snapshot_pane_absence() -> None:
    binding = _binding()

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@2',
        agent_name='agent1',
        project_id='proj-1',
        namespace_pane_records={},
        tmux_backend_factory=lambda socket_path=None: (_ for _ in ()).throw(
            AssertionError('an authoritative snapshot must not be rescanned')
        ),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: (_ for _ in ()).throw(
            AssertionError('an authoritative snapshot must not be rescanned')
        ),
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is None


def test_usable_project_namespace_binding_rejects_provider_identity_mismatch() -> None:
    binding = _binding(
        provider='codex',
        provider_identity_state='mismatch',
        provider_identity_reason='live_codex_process_not_running_bound_resume_session',
    )
    record = SimpleNamespace(matches=lambda **kwargs: True)

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@2',
        agent_name='agent1',
        project_id='proj-1',
        tmux_backend_factory=lambda socket_path=None: SimpleNamespace(socket_path=socket_path),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: record,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is None


def test_usable_project_namespace_binding_rejects_unproven_provider_identity() -> None:
    binding = _binding(
        provider='codex',
        provider_identity_state='unknown',
        provider_identity_reason='pane_pid_unavailable',
    )
    record = SimpleNamespace(matches=lambda **kwargs: True)

    usable = usable_project_namespace_binding(
        binding,
        tmux_socket_path='/tmp/ccb.sock',
        tmux_session_name='ccb-demo',
        workspace_window_id='@2',
        agent_name='agent1',
        project_id='proj-1',
        tmux_backend_factory=lambda socket_path=None: SimpleNamespace(socket_path=socket_path),
        inspect_project_namespace_pane_fn=lambda backend, pane_id: record,
        same_tmux_socket_path_fn=lambda left, right: str(left or '') == str(right or ''),
    )

    assert usable is None
