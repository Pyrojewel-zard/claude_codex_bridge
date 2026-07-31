from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil

import pytest

from agents.config_loader import (
    StructuredConfigValidationError,
    load_project_config,
    render_project_config_text,
)
from cli.context import CliContextBuilder
from cli.models import ParsedConfigValidateCommand
from cli.parser import CliParser, CliUsageError
from cli.phase2 import maybe_handle_phase2
from cli.services.config_validate import effective_config_context, migrate_config_context, validate_config_context
from cli.services.loop_effective_capacity import (
    compile_project_effective_capacity_snapshot,
    effective_capacity_digest,
    normalize_effective_capacity_snapshot,
)


@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch) -> None:
    """Pin runtime state under .ccb for project-anchored path assertions."""
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


REQUIRED_ROLES = (
    ('agentroles.ccb_frontdesk', 'frontdesk'),
    ('agentroles.ccb_planner', 'planner'),
    ('agentroles.ccb_task_detailer', 'task_detailer'),
    ('agentroles.ccb_orchestrator', 'orchestrator'),
    ('agentroles.coder', 'coder'),
    ('agentroles.code_reviewer', 'code_reviewer'),
    ('agentroles.ccb_round_reviewer', 'ccb_round_reviewer'),
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _install_roles(root: Path, monkeypatch: pytest.MonkeyPatch, *, omit: str | None = None) -> Path:
    role_store = root / 'roles'
    for role_id, name in REQUIRED_ROLES:
        if role_id == omit:
            continue
        _write(
            role_store / 'installed' / role_id / 'current' / 'role.toml',
            'schema = "rolepack/v1"\n'
            f'id = "{role_id}"\n'
            f'name = "{name}"\n'
            'version = "0.1.0"\n'
            f'description = "Test {name} role"\n\n'
            '[identity]\n'
            f'default_agent_name = "{name}"\n\n'
            '[compatibility]\n'
            'providers = ["codex", "claude", "gemini", "opencode", "kimi", "mimo", "qwen", "zai", "droid"]\n',
        )
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))
    return role_store


def _valid_v3_text() -> str:
    return '''version = 3

[workflow]
mode = "agentic-loop"
profile = "agentic_loop_v1"
entry_role = "frontdesk"

[workflow.defaults]
provider = "codex"
model = "gpt5.5"
thinking = "medium"

[workflow.defaults.resident]
workspace_mode = "inplace"

[workflow.defaults.dynamic]
workspace_mode = "inplace"
reuse = "always_new"

[workflow.runtime]
max_workgroups = 2
max_parallel_workgroups = 2
max_active_dynamic_agents = 5
max_node_rework_rounds = 1
execution_window_max_panes = 6
multi_workgroup_workspace = "git-worktree-required"
integration_policy = "controller-owned"
default_lifetime = "current_activation"
name_template = "loop-{loop_id}-{node_id}-{profile}"
release_policy = "auto"
window_policy = "auto"

[workflow.resident.frontdesk]
role = "agentroles.ccb_frontdesk"
env = { FRONTDESK_TOKEN = "must-not-be-reported" }

[workflow.resident.planner]
role = "agentroles.ccb_planner"

[workflow.dynamic.task_detailer]
role = "agentroles.ccb_task_detailer"
max_instances = 1

[workflow.dynamic.orchestrator]
role = "agentroles.ccb_orchestrator"
max_instances = 1

[workflow.dynamic.coder]
role = "agentroles.coder"
workspace_mode = "git-worktree"
max_instances = 2
legacy_aliases = ["worker"]

[workflow.dynamic.code_reviewer]
role = "agentroles.code_reviewer"
workspace_mode = "git-worktree"
max_instances = 2

[workflow.dynamic.ccb_round_reviewer]
role = "agentroles.ccb_round_reviewer"
provider = "claude"
model = "Claude Sonnet 4.6 (Thinking)"
max_instances = 1
'''


def _replace_defaults_with_false(text: str) -> str:
    start = text.index('[workflow.defaults]')
    end = text.index('[workflow.runtime]')
    return text[:start] + 'defaults = false\n\n' + text[end:]


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, text: str | None = None) -> Path:
    project_root = tmp_path / 'repo-v3'
    _install_roles(tmp_path, monkeypatch)
    _write(project_root / '.ccb' / 'ccb.config', text or _valid_v3_text())
    return project_root


def _install_source_rolepacks(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    role_store = root / 'source-roles'
    drafts = (
        Path(__file__).resolve().parents[1]
        / 'docs'
        / 'plantree'
        / 'plans'
        / 'agentic-loop-workflow'
        / 'drafts'
    )
    for role_id, _name in REQUIRED_ROLES:
        shutil.copytree(
            drafts / role_id,
            role_store / 'installed' / role_id / 'current',
        )
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))
    return role_store


def test_v3_loads_compiled_residents_dynamic_profiles_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)

    loaded = load_project_config(project_root)
    config = loaded.config

    assert config.version == 3
    assert tuple(config.agents) == ('frontdesk', 'planner')
    assert config.default_agents == ('frontdesk', 'planner')
    assert [window.name for window in config.windows] == ['ccb-user', 'ccb-plan']
    assert config.entry_window == 'ccb-user'
    assert set(config.loop_capacity.role_profiles) == {
        'task_detailer',
        'orchestrator',
        'coder',
        'code_reviewer',
        'ccb_round_reviewer',
    }
    assert config.workflow.profile_aliases == {'worker': 'coder'}
    assert config.workflow.resident['frontdesk'].model == 'gpt-5.5'
    assert config.workflow.dynamic['ccb_round_reviewer'].provider == 'claude'
    assert config.workflow.dynamic['ccb_round_reviewer'].raw_model == 'Claude Sonnet 4.6 (Thinking)'
    assert config.workflow.dynamic['ccb_round_reviewer'].model == 'claude-sonnet-4.6-(thinking)'
    assert render_project_config_text(config) == _valid_v3_text()


def test_v3_loads_real_agent_role_preview_manifests_through_ccb_adapters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-v3-source-rolepacks'
    _install_source_rolepacks(tmp_path, monkeypatch)
    _write(project_root / '.ccb' / 'ccb.config', _valid_v3_text())

    workflow = load_project_config(project_root, include_loop_overlays=False).config.workflow

    assert workflow is not None
    assert workflow.resident['frontdesk'].provider == 'codex'
    assert workflow.dynamic['ccb_round_reviewer'].provider == 'claude'


def test_v3_effective_capacity_snapshot_is_stable_bound_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)

    first = compile_project_effective_capacity_snapshot(project_root)
    second = compile_project_effective_capacity_snapshot(project_root)

    assert first == second
    assert first['config_version'] == 3
    assert first['workflow_mode'] == 'agentic-loop'
    assert first['workflow_profile'] == 'agentic_loop_v1'
    assert first['limits'] == {
        'max_workgroups': 2,
        'max_parallel_workgroups': 2,
        'max_active_dynamic_agents': 5,
    }
    assert first['profile_aliases'] == {'worker': 'coder'}
    assert first['resident_profiles']['frontdesk']['release_policy'] == 'resident'
    assert first['dynamic_profiles']['ccb_round_reviewer']['provider'] == 'claude'
    assert first['dynamic_profiles']['ccb_round_reviewer']['model'] == 'claude-sonnet-4.6-(thinking)'
    assert effective_capacity_digest(first) == effective_capacity_digest(second)
    assert 'must-not-be-reported' not in json.dumps(first, sort_keys=True)


def test_effective_capacity_rejects_alias_to_missing_dynamic_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)
    snapshot = compile_project_effective_capacity_snapshot(project_root)
    snapshot['profile_aliases'] = {'worker': 'missing'}

    with pytest.raises(ValueError, match='target missing dynamic profile: missing'):
        normalize_effective_capacity_snapshot(snapshot)


def test_v3_capacity_digest_binds_semantics_but_not_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)
    config_path = project_root / '.ccb' / 'ccb.config'
    baseline = effective_capacity_digest(compile_project_effective_capacity_snapshot(project_root))

    secret_only = _valid_v3_text().replace('must-not-be-reported', 'different-secret')
    _write(config_path, secret_only)
    assert effective_capacity_digest(compile_project_effective_capacity_snapshot(project_root)) == baseline

    changed_policy = secret_only.replace('release_policy = "auto"', 'release_policy = "unload"')
    _write(config_path, changed_policy)
    assert effective_capacity_digest(compile_project_effective_capacity_snapshot(project_root)) != baseline


def test_v3_active_loop_overlay_preserves_workflow_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)
    _write(
        project_root / '.ccb' / 'runtime' / 'loops' / 'loop-v3' / 'capacity.json',
        json.dumps(
            {
                'loop_capacity_status': 'ensured',
                'loop_id': 'loop-v3',
                'agents': [
                    {
                        'name': 'loop-loop-v3-coder-1',
                        'profile': 'coder',
                        'role': 'agentroles.coder',
                        'provider': 'codex',
                        'workspace_mode': 'git-worktree',
                        'window_name': 'ccb-exec',
                        'state': 'planned',
                    }
                ],
            }
        ),
    )

    config = load_project_config(project_root).config

    assert config.version == 3
    assert config.workflow is not None
    assert config.workflow.profile == 'agentic_loop_v1'
    assert 'loop-loop-v3-coder-1' in config.agents
    assert config.windows[-1].name == 'ccb-exec'


def test_v3_provider_defaults_resolve_models_per_effective_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace('model = "gpt5.5"\n', '').replace(
        '[workflow.defaults.resident]',
        '[workflow.provider_defaults.codex]\nmodel = "gpt5.5"\n\n'
        '[workflow.provider_defaults.claude]\nmodel = "Claude Sonnet 4.6 (Thinking)"\n\n'
        '[workflow.defaults.resident]',
    ).replace('model = "Claude Sonnet 4.6 (Thinking)"\nmax_instances', 'max_instances')
    project_root = _project(tmp_path, monkeypatch, text=text)

    workflow = load_project_config(project_root, include_loop_overlays=False).config.workflow

    assert workflow.resident['frontdesk'].model == 'gpt-5.5'
    assert workflow.dynamic['coder'].model == 'gpt-5.5'
    assert workflow.dynamic['ccb_round_reviewer'].provider == 'claude'
    assert workflow.dynamic['ccb_round_reviewer'].model == 'claude-sonnet-4.6-(thinking)'


def test_v3_validate_and_effective_reports_are_deterministic_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace(
        'role = "agentroles.ccb_frontdesk"\nenv',
        'role = "agentroles.ccb_frontdesk"\nstartup_args = ["--api-key", "startup-secret"]\nenv',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)
    context = CliContextBuilder().build(
        ParsedConfigValidateCommand(project=None),
        cwd=project_root,
        bootstrap_if_missing=False,
    )

    summary = validate_config_context(context)
    effective = effective_config_context(context)

    assert summary.config_version == 3
    assert summary.workflow == {
        'mode': 'agentic-loop',
        'profile': 'agentic_loop_v1',
        'entry_role': 'frontdesk',
    }
    assert [item['slot'] for item in summary.resident_roles] == ['frontdesk', 'planner']
    assert [item['profile'] for item in summary.dynamic_profiles] == [
        'task_detailer',
        'orchestrator',
        'coder',
        'code_reviewer',
        'ccb_round_reviewer',
    ]
    assert summary.compiled_topology['resident_windows'][0] == {
        'name': 'ccb-user',
        'agents': ['frontdesk'],
    }
    assert effective['record_type'] == 'ccb_config_effective'
    assert effective['config_digest'].startswith('sha256:')
    assert effective['capacity_digest'] == summary.capacity_digest
    assert 'must-not-be-reported' not in json.dumps(effective, sort_keys=True)
    assert 'startup-secret' not in json.dumps(effective, sort_keys=True)
    frontdesk = next(item for item in summary.resident_roles if item['slot'] == 'frontdesk')
    assert frontdesk['env_keys'] == ['FRONTDESK_TOKEN']
    assert frontdesk['startup_arg_count'] == 2


def test_v3_internal_authority_record_binds_dynamic_sensitive_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace(
        'role = "agentroles.coder"\nworkspace_mode',
        'role = "agentroles.coder"\nstartup_args = ["--profile-token", "authority-secret"]\n'
        'env = { PROFILE_TOKEN = "authority-env-secret" }\nworkspace_mode',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)

    record = load_project_config(project_root, include_loop_overlays=False).config.to_record()
    coder = record['workflow']['dynamic']['coder']

    assert coder['startup_args'] == ['--profile-token', 'authority-secret']
    assert coder['env'] == {'PROFILE_TOKEN': 'authority-env-secret'}


def test_v3_kind_default_without_provider_applies_to_explicit_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace('model = "gpt5.5"\n', '').replace(
        '[workflow.defaults.resident]\nworkspace_mode = "inplace"',
        '[workflow.defaults.resident]\nmodel = "Claude Sonnet 4.6 (Thinking)"\nworkspace_mode = "inplace"',
    ).replace(
        'role = "agentroles.ccb_frontdesk"\nenv',
        'role = "agentroles.ccb_frontdesk"\nmodel = "gpt5.5"\nenv',
    ).replace(
        'role = "agentroles.ccb_planner"',
        'role = "agentroles.ccb_planner"\nprovider = "claude"',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)

    workflow = load_project_config(project_root, include_loop_overlays=False).config.workflow

    assert workflow.resident['frontdesk'].model == 'gpt-5.5'
    assert workflow.resident['planner'].provider == 'claude'
    assert workflow.resident['planner'].raw_model == 'Claude Sonnet 4.6 (Thinking)'


def test_v3_accepts_fake_provider_for_source_owned_workflow_smokes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CCB_TEST_ENTRYPOINT', '1')
    text = _valid_v3_text().replace('provider = "codex"', 'provider = "fake"').replace(
        'model = "gpt5.5"\nthinking = "medium"\n',
        '',
    ).replace(
        'provider = "claude"\nmodel = "Claude Sonnet 4.6 (Thinking)"',
        'provider = "fake"',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)

    workflow = load_project_config(project_root, include_loop_overlays=False).config.workflow

    assert {role.provider for role in workflow.resident.values()} == {'fake'}
    assert {role.provider for role in workflow.dynamic.values()} == {'fake'}


def test_v3_rejects_fake_provider_outside_source_test_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('CCB_TEST_ENTRYPOINT', raising=False)
    text = _valid_v3_text().replace('provider = "codex"', 'provider = "fake"')
    project_root = _project(tmp_path, monkeypatch, text=text)

    with pytest.raises(StructuredConfigValidationError) as exc_info:
        load_project_config(project_root, include_loop_overlays=False)

    assert exc_info.value.code == 'v3_provider_unknown'
    assert exc_info.value.path == 'workflow.defaults.provider'


@pytest.mark.parametrize(
    ('mutate', 'code', 'path'),
    (
        (lambda text: text + '\n[windows]\nmain = "frontdesk:codex"\n', 'v3_static_layout_field_forbidden', 'windows'),
        (lambda text: text.replace('version = 3', 'version = 3.0'), 'v3_version_invalid', 'version'),
        (_replace_defaults_with_false, 'v3_type_invalid', 'workflow.defaults'),
        (lambda text: text.replace('[workflow.resident.frontdesk]', '[workflow.resident.frontdesk_removed]'), 'v3_required_resident_missing', 'workflow.resident.frontdesk'),
        (lambda text: text.replace('[workflow.dynamic.orchestrator]', '[workflow.dynamic.orchestrator_removed]'), 'v3_required_dynamic_missing', 'workflow.dynamic.orchestrator'),
        (lambda text: text.replace('entry_role = "frontdesk"', 'entry_role = "frontdesk"\nunknown = true'), 'v3_unknown_field', 'workflow.unknown'),
        (lambda text: text.replace('thinking = "medium"', 'thinking = 3'), 'v3_type_invalid', 'workflow.defaults.thinking'),
        (lambda text: text.replace('legacy_aliases = ["worker"]', 'legacy_aliases = ["worker", 3]'), 'v3_type_invalid', 'workflow.dynamic.coder.legacy_aliases'),
        (lambda text: text.replace('env = { FRONTDESK_TOKEN = "must-not-be-reported" }', 'env = { FRONTDESK_TOKEN = 3 }'), 'v3_type_invalid', 'workflow.resident.frontdesk.env'),
        (lambda text: text.replace('provider = "claude"', 'provider = "not-a-provider"'), 'v3_provider_unknown', 'workflow.dynamic.ccb_round_reviewer.provider'),
        (lambda text: text.replace('provider = "claude"', 'provider = "qwen"'), 'v3_model_unsupported_for_provider', 'workflow.dynamic.ccb_round_reviewer.model'),
        (lambda text: text.replace('release_policy = "auto"', 'release_policy = "explode"'), 'v3_release_policy_invalid', 'workflow.runtime.release_policy'),
        (lambda text: text.replace('role = "agentroles.coder"\nworkspace_mode', 'role = "agentroles.coder"\nwindow_class = "plan"\nworkspace_mode'), 'v3_window_class_invalid', 'workflow.dynamic.coder.window_class'),
        (lambda text: text.replace('name_template = "loop-{loop_id}-{node_id}-{profile}"', 'name_template = ""'), 'v3_type_invalid', 'workflow.runtime.name_template'),
        (lambda text: text.replace('max_parallel_workgroups = 2', 'max_parallel_workgroups = 3'), 'v3_workgroup_limit_invalid', 'workflow.runtime.max_parallel_workgroups'),
        (lambda text: text.replace('max_active_dynamic_agents = 5', 'max_active_dynamic_agents = 4'), 'v3_dynamic_agent_limit_invalid', 'workflow.runtime.max_active_dynamic_agents'),
        (lambda text: text.replace('max_active_dynamic_agents = 5', 'max_active_dynamic_agents = 8'), 'v3_dynamic_agent_limit_invalid', 'workflow.runtime.max_active_dynamic_agents'),
        (lambda text: text.replace('workspace_mode = "git-worktree"\nmax_instances = 2\nlegacy_aliases', 'workspace_mode = "inplace"\nmax_instances = 2\nlegacy_aliases'), 'v3_multi_workgroup_requires_git_worktree', 'workflow.dynamic.coder.workspace_mode'),
        (lambda text: text.replace('workspace_mode = "git-worktree"\nmax_instances = 2\nlegacy_aliases', 'workspace_mode = "git-worktree"\nworkspace_group = "shared"\nmax_instances = 2\nlegacy_aliases'), 'v3_workspace_group_controller_owned', 'workflow.dynamic.coder.workspace_group'),
        (lambda text: text.replace('max_instances = 2\nlegacy_aliases', 'max_instances = 1\nlegacy_aliases'), 'v3_capacity_exceeds_profiles', 'workflow.dynamic.coder.max_instances'),
        (lambda text: text.replace('role = "agentroles.ccb_frontdesk"\nenv', 'role = "agentroles.ccb_frontdesk"\nlifecycle = "immaculate"\nenv'), 'v3_immaculate_role_declared_resident', 'workflow.resident.frontdesk.lifecycle'),
        (lambda text: text.replace('legacy_aliases = ["worker"]', 'legacy_aliases = ["code_reviewer"]'), 'v3_profile_alias_conflict', 'workflow.dynamic.coder.legacy_aliases'),
        (lambda text: text.replace('role = "agentroles.ccb_planner"', 'role = "agentroles.ccb_frontdesk"'), 'v3_duplicate_logical_role', 'workflow.resident.planner.role'),
        (lambda text: text.replace('model = "Claude Sonnet 4.6 (Thinking)"', 'model = "Claude Sonnet 4.6 (Thinking)"\nstartup_args = ["--model", "other"]'), 'v3_model_startup_args_conflict', 'workflow.dynamic.ccb_round_reviewer.startup_args'),
        (lambda text: text + '\n[workflow.dynamic.frontdesk]\nrole = "agentroles.ccb_task_detailer"\nmax_instances = 1\n', 'v3_resident_dynamic_conflict', 'workflow.dynamic.frontdesk'),
    ),
)
def test_v3_rejects_invalid_authority_before_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    code: str,
    path: str,
) -> None:
    project_root = _project(tmp_path, monkeypatch, text=mutate(_valid_v3_text()))

    with pytest.raises(StructuredConfigValidationError) as exc_info:
        load_project_config(project_root, include_loop_overlays=False)

    assert exc_info.value.code == code
    assert exc_info.value.path == path


def test_v3_missing_rolepack_is_a_structured_pre_start_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-v3-missing-role'
    _install_roles(tmp_path, monkeypatch, omit='agentroles.ccb_frontdesk')
    _write(project_root / '.ccb' / 'ccb.config', _valid_v3_text())

    with pytest.raises(StructuredConfigValidationError) as exc_info:
        load_project_config(project_root, include_loop_overlays=False)

    assert exc_info.value.code == 'v3_rolepack_not_installed'
    assert exc_info.value.path == 'workflow.resident.frontdesk.role'
    assert 'agentroles.ccb_frontdesk' in exc_info.value.message


def test_v3_rejects_provider_not_supported_by_installed_rolepack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace(
        'provider = "claude"\nmodel = "Claude Sonnet 4.6 (Thinking)"',
        'provider = "grok"',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)

    with pytest.raises(StructuredConfigValidationError) as exc_info:
        load_project_config(project_root, include_loop_overlays=False)

    assert exc_info.value.code == 'v3_role_provider_unsupported'
    assert exc_info.value.path == 'workflow.dynamic.ccb_round_reviewer.provider'
    assert 'agentroles.ccb_round_reviewer does not support provider grok' in exc_info.value.message


def test_v3_cross_provider_default_model_inheritance_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = _valid_v3_text().replace(
        'provider = "claude"\nmodel = "Claude Sonnet 4.6 (Thinking)"',
        'provider = "claude"',
    )
    project_root = _project(tmp_path, monkeypatch, text=text)

    with pytest.raises(StructuredConfigValidationError) as exc_info:
        load_project_config(project_root, include_loop_overlays=False)

    assert exc_info.value.code == 'v3_cross_provider_model_inheritance'
    assert exc_info.value.path == 'workflow.dynamic.ccb_round_reviewer.model'


def test_config_cli_supports_v3_validate_and_effective_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(tmp_path, monkeypatch)
    for argv, expected_type in (
        (['config', 'validate', '--json'], None),
        (['config', 'effective', '--json'], 'ccb_config_effective'),
    ):
        stdout = StringIO()
        stderr = StringIO()
        code = maybe_handle_phase2(argv, cwd=project_root, stdout=stdout, stderr=stderr)
        assert code == 0, stderr.getvalue()
        payload = json.loads(stdout.getvalue())
        assert payload['config_status'] == 'valid'
        assert payload['config_version'] == 3
        if expected_type is not None:
            assert payload['record_type'] == expected_type

    text_stdout = StringIO()
    text_stderr = StringIO()
    code = maybe_handle_phase2(
        ['config', 'validate'],
        cwd=project_root,
        stdout=text_stdout,
        stderr=text_stderr,
    )
    assert code == 0, text_stderr.getvalue()
    assert 'config_version: 3' in text_stdout.getvalue()
    assert 'workflow_mode: agentic-loop' in text_stdout.getvalue()
    assert 'resident_roles: frontdesk, planner' in text_stdout.getvalue()
    assert 'max_workgroups=2 max_parallel_workgroups=2 max_active_dynamic_agents=5' in text_stdout.getvalue()


def test_config_parser_exposes_effective_and_dry_run_only_migration() -> None:
    parser = CliParser()

    assert parser.parse(['config', 'effective', '--json']) == ParsedConfigValidateCommand(
        project=None,
        action='effective',
        json_output=True,
    )
    assert parser.parse(['config', 'migrate', '--to', '3', '--dry-run', '--json']) == ParsedConfigValidateCommand(
        project=None,
        action='migrate',
        json_output=True,
        to_version=3,
        dry_run=True,
    )
    with pytest.raises(CliUsageError, match='requires --dry-run'):
        parser.parse(['config', 'migrate', '--to', '3'])


def test_config_cli_v3_json_error_has_code_path_and_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project(
        tmp_path,
        monkeypatch,
        text=_valid_v3_text().replace('max_active_dynamic_agents = 5', 'max_active_dynamic_agents = 2'),
    )
    stdout = StringIO()
    stderr = StringIO()

    code = maybe_handle_phase2(
        ['config', 'validate', '--json'],
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stderr.getvalue() == ''
    payload = json.loads(stdout.getvalue())
    assert payload['config_status'] == 'invalid'
    assert payload['errors'] == [
        {
            'code': 'v3_dynamic_agent_limit_invalid',
            'path': 'workflow.runtime.max_active_dynamic_agents',
            'message': 'must be at least 5 for configured parallel workgroups and control review',
        }
    ]


def test_v2_to_v3_migration_is_deterministic_dry_run_and_never_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-v2-migrate'
    _install_roles(tmp_path, monkeypatch)
    source = '''version = 2
entry_window = "ccb-user"

[windows]
ccb-user = "frontdesk:codex"
ccb-plan = "planner:codex"

[agents.frontdesk]
role = "agentroles.ccb_frontdesk"
env = { FRONTDESK_TOKEN = "migration-secret" }
startup_args = ["--api-key", "migration-startup-secret"]

[agents.planner]
role = "agentroles.ccb_planner"

[loop.capacity]
enabled = true
max_nodes = 5

[loop.role_profiles.worker]
role = "agentroles.coder"
provider = "codex"
workspace_mode = "git-worktree"
max_instances = 3

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
workspace_mode = "git-worktree"
max_instances = 2
'''
    config_path = project_root / '.ccb' / 'ccb.config'
    _write(config_path, source)
    context = CliContextBuilder().build(
        ParsedConfigValidateCommand(project=None, action='migrate', to_version=3, dry_run=True),
        cwd=project_root,
        bootstrap_if_missing=False,
    )

    first = migrate_config_context(context, to_version=3, dry_run=True)
    second = migrate_config_context(context, to_version=3, dry_run=True)

    assert first == second
    assert first['status'] == 'manual_required'
    assert first['wrote_config'] is False
    assert config_path.read_text(encoding='utf-8') == source
    assert first['target_document']['workflow']['dynamic']['coder']['legacy_aliases'] == ['worker']
    assert first['target_document']['workflow']['runtime']['max_active_dynamic_agents'] == 5
    assert any(item['code'] == 'ambiguous_v2_max_nodes' for item in first['manual_required'])
    assert any(item['code'] == 'missing_required_dynamic' for item in first['manual_required'])
    assert any(item['code'] == 'sensitive_env_requires_manual_mapping' for item in first['manual_required'])
    assert any(item['code'] == 'startup_args_require_manual_mapping' for item in first['manual_required'])
    assert 'migration-secret' not in json.dumps(first, sort_keys=True)
    assert 'migration-startup-secret' not in json.dumps(first, sort_keys=True)
    assert 'max_workgroups' not in first['target_document']['workflow']['runtime']

    stdout = StringIO()
    stderr = StringIO()
    code = maybe_handle_phase2(
        ['config', 'migrate', '--to', '3', '--dry-run', '--json'],
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue()) == first


def test_v2_to_v3_migration_reports_repeated_role_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-v2-repeated-roles'
    _install_roles(tmp_path, monkeypatch)
    _write(
        project_root / '.ccb' / 'ccb.config',
        '''version = 2

[windows]
ccb-user = "frontdesk-a:codex"
ccb-plan = "frontdesk-b:codex"

[agents.frontdesk-a]
role = "agentroles.ccb_frontdesk"

[agents.frontdesk-b]
role = "agentroles.ccb_frontdesk"

[loop.capacity]
enabled = true
max_nodes = 2

[loop.role_profiles.coder]
role = "agentroles.coder"
provider = "codex"
max_instances = 1

[loop.role_profiles.worker]
role = "agentroles.coder"
provider = "codex"
max_instances = 1
''',
    )
    context = CliContextBuilder().build(
        ParsedConfigValidateCommand(project=None, action='migrate', to_version=3, dry_run=True),
        cwd=project_root,
        bootstrap_if_missing=False,
    )

    preview = migrate_config_context(context, to_version=3, dry_run=True)

    codes = {item['code'] for item in preview['manual_required']}
    assert 'ambiguous_repeated_resident_role' in codes
    assert 'ambiguous_repeated_dynamic_role' in codes
    assert list(preview['target_document']['workflow']['resident']) == ['frontdesk']
    assert list(preview['target_document']['workflow']['dynamic']) == ['coder']


def test_v2_effective_capacity_semantics_remain_one_workgroup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-v2-frozen'
    _install_roles(tmp_path, monkeypatch)
    _write(
        project_root / '.ccb' / 'ccb.config',
        '''version = 2
entry_window = "main"
[windows]
main = "worker:codex"
[loop.capacity]
enabled = true
max_nodes = 7
[loop.role_profiles.coder]
role = "agentroles.coder"
provider = "codex"
max_instances = 4
[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
max_instances = 3
''',
    )

    loaded = load_project_config(project_root, include_loop_overlays=False).config
    snapshot = compile_project_effective_capacity_snapshot(project_root)

    assert loaded.version == 2
    assert loaded.workflow is None
    assert snapshot['config_version'] == 2
    assert snapshot['workflow_mode'] == 'route_only'
    assert snapshot['limits'] == {
        'max_workgroups': 1,
        'max_parallel_workgroups': 1,
        'max_active_dynamic_agents': 7,
    }
