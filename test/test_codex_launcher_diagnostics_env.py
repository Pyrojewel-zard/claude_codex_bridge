from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from provider_backends.codex.launcher_runtime.command_runtime.service import build_start_cmd


def test_build_start_cmd_disables_codex_rust_diagnostic_logging(tmp_path: Path) -> None:
    command = SimpleNamespace(auto_permission=False, restore=False)
    spec = SimpleNamespace(
        name='agent1',
        startup_args=[],
        provider_command_template='',
        restore_default=False,
        env={},
    )

    cmd = build_start_cmd(
        command,
        spec,
        tmp_path / 'runtime',
        'launch-1',
        load_resolved_provider_profile_fn=lambda _: None,
        prepare_codex_home_overrides_fn=lambda *_, **__: {
            'CODEX_HOME': str(tmp_path / 'home'),
            'CODEX_SESSION_ROOT': str(tmp_path / 'home' / 'sessions'),
        },
        provider_start_parts_fn=lambda _: ['codex'],
        load_resume_session_id_fn=lambda *_, **__: None,
        build_codex_shell_prefix_fn=lambda **_: [],
        prepared_state={'project_root': str(tmp_path)},
    )

    assert 'RUST_LOG=off' in cmd


def test_build_start_cmd_preserves_explicit_rust_log(tmp_path: Path) -> None:
    command = SimpleNamespace(auto_permission=False, restore=False)
    spec = SimpleNamespace(
        name='agent1',
        startup_args=[],
        provider_command_template='',
        restore_default=False,
        env={'RUST_LOG': 'debug'},
    )

    cmd = build_start_cmd(
        command,
        spec,
        tmp_path / 'runtime',
        'launch-1',
        load_resolved_provider_profile_fn=lambda _: None,
        prepare_codex_home_overrides_fn=lambda *_, **__: {
            'CODEX_HOME': str(tmp_path / 'home'),
            'CODEX_SESSION_ROOT': str(tmp_path / 'home' / 'sessions'),
        },
        provider_start_parts_fn=lambda _: ['codex'],
        load_resume_session_id_fn=lambda *_, **__: None,
        build_codex_shell_prefix_fn=lambda **_: [],
        prepared_state={'project_root': str(tmp_path)},
    )

    assert 'RUST_LOG=debug' in cmd
    assert 'RUST_LOG=off' not in cmd


def test_build_start_cmd_exports_ccb_session_binding_for_reconnect_skill(tmp_path: Path) -> None:
    command = SimpleNamespace(auto_permission=False, restore=False)
    spec = SimpleNamespace(
        name='agent1',
        startup_args=[],
        provider_command_template='',
        restore_default=False,
        env={},
    )
    runtime_dir = (
        tmp_path
        / 'project'
        / '.ccb'
        / 'agents'
        / 'agent1'
        / 'provider-runtime'
        / 'codex'
    )

    cmd = build_start_cmd(
        command,
        spec,
        runtime_dir,
        'launch-1',
        load_resolved_provider_profile_fn=lambda _: None,
        prepare_codex_home_overrides_fn=lambda *_, **__: {
            'CODEX_HOME': str(tmp_path / 'home'),
            'CODEX_SESSION_ROOT': str(tmp_path / 'home' / 'sessions'),
        },
        provider_start_parts_fn=lambda _: ['codex'],
        load_resume_session_id_fn=lambda *_, **__: None,
        build_codex_shell_prefix_fn=lambda **_: [],
        prepared_state={'project_root': str(tmp_path / 'project')},
    )

    expected = tmp_path / 'project' / '.ccb' / '.codex-agent1-session'
    assert f'CCB_SESSION_FILE={expected}' in cmd
