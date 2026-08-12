from __future__ import annotations

import json
from pathlib import Path

import pytest

import project_command_trust
from ccbd.app import CcbdApp
from project_command_trust import (
    ProjectCommandApprovalRequired,
    approve_project_commands,
    inspect_project_command_approval,
    project_command_receipt_path,
    require_project_command_approval,
    require_runtime_provider_command_approval,
)


def _write_config(project_root: Path, *, tool_command: str = 'touch marker', extra: str = '') -> None:
    path = project_root / '.ccb' / 'ccb.config'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''version = 2
entry_window = "main"
{extra}

[windows]
main = "main:codex"

[agents.main]
provider_command_template = "env SAFE=1 {{command}}"

[tool_windows.files]
command = "{tool_command}"
''',
        encoding='utf-8',
    )


def test_project_commands_require_external_exact_receipt(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    state = tmp_path / 'state'
    _write_config(project)
    env = {'XDG_STATE_HOME': str(state)}

    approval = inspect_project_command_approval(project, environ=env)

    assert approval.status == 'approval_required'
    assert [field.path for field in approval.fields] == [
        'agents.main.provider_command_template',
        'tool_windows.files.command',
    ]
    assert approval.receipt_path.parent == state / 'ccb' / 'trust' / 'project-commands'
    assert project not in approval.receipt_path.parents
    with pytest.raises(ProjectCommandApprovalRequired):
        require_project_command_approval(project, environ=env)

    approved = approve_project_commands(project, environ=env)

    assert approved.status == 'approved'
    assert inspect_project_command_approval(project, environ=env).status == 'approved'
    payload = json.loads(approved.receipt_path.read_text(encoding='utf-8'))
    assert payload['project_root'] == str(project.resolve())
    assert payload['command_authority_digest'] == approved.digest
    assert approved.receipt_path.stat().st_mode & 0o777 == 0o600
    assert approved.receipt_path.parent.stat().st_mode & 0o777 == 0o700


def test_unrelated_config_change_keeps_approval_but_command_change_invalidates_it(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}
    _write_config(project)
    initial = approve_project_commands(project, environ=env)

    _write_config(project, extra='# unrelated config comment')
    unchanged = inspect_project_command_approval(project, environ=env)
    assert unchanged.status == 'approved'
    assert unchanged.digest == initial.digest

    _write_config(project, tool_command='touch marker-v2', extra='# unrelated config comment')
    changed = inspect_project_command_approval(project, environ=env)
    assert changed.status == 'stale'
    with pytest.raises(ProjectCommandApprovalRequired):
        require_project_command_approval(project, environ=env)


def test_no_project_command_fields_need_no_receipt(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    config = project / '.ccb' / 'ccb.config'
    config.parent.mkdir(parents=True)
    config.write_text('main:codex\n', encoding='utf-8')

    approval = inspect_project_command_approval(
        project,
        environ={'XDG_STATE_HOME': str(tmp_path / 'state')},
    )

    assert approval.status == 'not_required'
    assert approval.fields == ()
    require_project_command_approval(project, environ={'XDG_STATE_HOME': str(tmp_path / 'state')})
    assert not approval.receipt_path.exists()


def test_exact_execution_gate_rejects_config_to_runtime_race(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}
    _write_config(project)
    approve_project_commands(project, environ=env)

    require_project_command_approval(
        project,
        field_path='tool_windows.files.command',
        field_value='touch marker',
        environ=env,
    )
    with pytest.raises(RuntimeError, match='changed before execution'):
        require_project_command_approval(
            project,
            field_path='tool_windows.files.command',
            field_value='touch other-marker',
            environ=env,
        )


def test_approval_write_rejects_fields_changed_after_review(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}
    _write_config(project)
    reviewed = inspect_project_command_approval(project, environ=env)
    _write_config(project, tool_command='touch changed-after-review')

    with pytest.raises(RuntimeError, match='changed during approval'):
        approve_project_commands(
            project,
            expected_digest=reviewed.digest,
            environ=env,
        )

    assert not reviewed.receipt_path.exists()


def test_receipt_name_binds_canonical_project_root(tmp_path: Path) -> None:
    project = tmp_path / 'repo'
    project.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(project, target_is_directory=True)
    env = {'XDG_STATE_HOME': str(tmp_path / 'state')}

    assert project_command_receipt_path(project, environ=env) == project_command_receipt_path(alias, environ=env)


def test_windows_receipts_use_local_app_data(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / 'repo'
    project.mkdir()
    local_app_data = tmp_path / 'LocalAppData'
    monkeypatch.setattr(project_command_trust, '_is_windows_platform', lambda: True)

    receipt = project_command_receipt_path(
        project,
        environ={'LOCALAPPDATA': str(local_app_data)},
    )

    assert receipt.parent == local_app_data / 'CCB' / 'trust' / 'project-commands'


def test_user_default_provider_template_does_not_require_project_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / 'repo'
    project.mkdir()
    user_home = tmp_path / 'home'
    config = user_home / '.ccb' / 'ccb.config'
    config.parent.mkdir(parents=True)
    config.write_text(
        '''version = 2
default_agents = ["main"]

[agents.main]
provider = "codex"
target = "."
workspace_mode = "inplace"
restore = "auto"
permission = "manual"
provider_command_template = "env USER_DEFAULT=1 {command}"
''',
        encoding='utf-8',
    )
    monkeypatch.setenv('HOME', str(user_home))

    approval = require_runtime_provider_command_approval(
        project,
        agent_name='main',
        template='env USER_DEFAULT=1 {command}',
    )

    assert approval.status == 'not_required'
    assert not approval.receipt_path.exists()


def test_ccbd_bootstrap_is_an_independent_noninteractive_gate(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / 'repo'
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    _write_config(project)

    with pytest.raises(ProjectCommandApprovalRequired):
        CcbdApp(project, clock=lambda: 1.0, pid=1234)

    # The gate runs before project identity/runtime publication.
    assert not (project / '.ccb' / 'project.identity.json').exists()
    approve_project_commands(project)
    app = CcbdApp(project, clock=lambda: 1.0, pid=1234)
    assert app.project_root == project.resolve()
