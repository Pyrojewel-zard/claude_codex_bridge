from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from agents.config_identity import project_config_identity_payload
from agents.config_loader import load_project_config
from ccbd.services.mount import MountManager
from cli.services.config_restart_intent import (
    clear_applied_config_restart_intent,
    config_restart_required_for_inspection,
    load_config_restart_intent,
    record_config_restart_intent,
)
from storage.paths import PathLayout


def _write_config(project_root: Path, text: str = 'agent1:codex\n') -> str:
    path = project_root / '.ccb' / 'ccb.config'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_signature(project_root: Path) -> str:
    return str(
        project_config_identity_payload(load_project_config(project_root).config)[
            'config_signature'
        ]
    )


def _mark_mounted(
    layout: PathLayout,
    *,
    generation: int,
    daemon_instance_id: str,
) -> None:
    MountManager(layout).mark_mounted(
        project_id=layout.project_id,
        pid=12000 + generation,
        socket_path=layout.ccbd_socket_path,
        generation=generation,
        config_signature=_config_signature(layout.project_root),
        daemon_instance_id=daemon_instance_id,
    )


def test_config_restart_intent_is_bound_to_source_daemon_and_clears_after_fresh_start(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'repo'
    digest = _write_config(
        project_root,
        'version = 2\n\n'
        '[windows]\n'
        'main = "agent1:codex"\n\n'
        '[agents.agent1]\n'
        'key = "secret-key-that-must-not-be-copied"\n'
        'url = "https://custom.example.test"\n',
    )
    layout = PathLayout(project_root)
    _mark_mounted(layout, generation=7, daemon_instance_id='daemon-old')

    intent = record_config_restart_intent(
        project_root,
        target_config_digest=digest,
        affected_agents=('agent1',),
        reason='provider_launch_config_changed',
        layout=layout,
        clock=lambda: '2026-07-25T00:00:00Z',
    )

    assert intent.source_daemon_instance_id == 'daemon-old'
    assert intent.source_generation == 7
    persisted = layout.ccbd_config_restart_intent_path.read_text(encoding='utf-8')
    assert 'secret-key-that-must-not-be-copied' not in persisted
    assert 'https://custom.example.test' not in persisted

    context = SimpleNamespace(paths=layout)
    old_lease = MountManager(layout).load_state()
    old_inspection = SimpleNamespace(lease=old_lease)
    assert config_restart_required_for_inspection(context, old_inspection) is True
    assert clear_applied_config_restart_intent(context) is False

    _mark_mounted(layout, generation=8, daemon_instance_id='daemon-new')
    new_lease = MountManager(layout).load_state()
    new_inspection = SimpleNamespace(lease=new_lease)
    assert config_restart_required_for_inspection(context, new_inspection) is False
    assert clear_applied_config_restart_intent(context) is True
    assert load_config_restart_intent(layout) is None


def test_config_restart_intent_does_not_apply_after_active_config_changes_again(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / 'repo-changed-target'
    digest = _write_config(project_root)
    layout = PathLayout(project_root)
    _mark_mounted(layout, generation=3, daemon_instance_id='daemon-current')
    record_config_restart_intent(
        project_root,
        target_config_digest=digest,
        reason='active_config_saved',
        layout=layout,
    )

    _write_config(project_root, 'agent1:claude\n')
    inspection = SimpleNamespace(lease=MountManager(layout).load_state())
    context = SimpleNamespace(paths=layout)

    assert config_restart_required_for_inspection(context, inspection) is False
    assert clear_applied_config_restart_intent(context) is False
    assert load_config_restart_intent(layout) is not None
