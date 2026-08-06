from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from agents.config_loader import load_project_config
from ccbd.api_models import AcceptedJobReceipt, JobStatus, SubmitReceipt
from ccbd.frontdesk_handler import build_frontdesk_forward_planner_handler
from ccbd.frontdesk_session_observer import observe_frontdesk_session
from ccbd.reload_plan import build_reload_dry_run_plan
from cli.context import CliContextBuilder
from cli.models import (
    ParsedAskCommand,
    ParsedFrontdeskCommand,
    ParsedLoopCapacityCommand,
    ParsedLoopRunOnceCommand,
    ParsedLoopRunnerCommand,
)
from cli.parser import CliParser, CliUsageError
from cli.phase2 import maybe_handle_phase2
from cli.phase2_runtime.handlers_ops import handle_loop_run_once
from cli.services import ask as ask_service
import cli.services.frontdesk_intake as frontdesk_intake_module
from cli.services import loop_ask_first as loop_ask_first_module
from cli.services import loop_runner as loop_runner_module
from cli.services import role_output_import as role_output_import_module
from cli.services.ask_runtime import AskSummary
from cli.services.loop_run_once import loop_run_once
from cli.services.loop_runner import loop_runner_auto, loop_runner_once
from cli.services.loop_orchestration_bundle import build_single_node_candidate
from cli.services.loop_effective_capacity import (
    compile_project_effective_capacity_snapshot,
    effective_capacity_digest,
)
from cli.services.plan_tasks import detail_ready_reconcile_authority, find_first_actionable_task, plan_task
import cli.services.plan_tasks as plan_tasks_module
from cli.services.frontdesk_intake import frontdesk_intake
import cli.services.frontdesk_intake_command as frontdesk_intake_command_module
from cli.services.frontdesk_intake_command import frontdesk_intake_command
from cli.services.watch import WatchEventBatch
import cli.services.loop_capacity as loop_capacity_module
from storage.paths import PathLayout
from storage.text_artifacts import write_text_artifact


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def _write_source_ask_job(
    project_root: Path,
    *,
    job_id: str,
    body: str,
    agent_name: str = 'frontdesk',
) -> None:
    _write(
        project_root / '.ccb' / 'agents' / agent_name / 'jobs.jsonl',
        json.dumps(
            {
                'job_id': job_id,
                'agent_name': agent_name,
                'request': {
                    'project_id': PathLayout(project_root).project_id,
                    'to_agent': agent_name,
                    'from_actor': 'user',
                    'message_type': 'ask',
                    'body': body,
                    'body_artifact': None,
                    'task_id': None,
                },
            }
        )
        + '\n',
    )


def _seed_copy_workspace_binding(context, project_root: Path, target: str) -> Path:
    workspace = project_root / '.ccb' / 'workspaces' / target
    for path in sorted(project_root.rglob('*')):
        try:
            relative = path.relative_to(project_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == '.ccb':
            continue
        if path.is_dir():
            continue
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    _write_json(
        workspace / '.ccb-workspace.json',
        {
            'agent_name': target,
            'workspace_mode': 'copy',
            'workspace_path': str(workspace),
            'target_project': str(project_root),
            'project_id': context.project.project_id,
        },
    )
    return workspace


def _seed_group_workspace_binding(
    context,
    project_root: Path,
    target: str,
    *,
    group: str = 'worker_pool',
) -> Path:
    workspace = project_root / '.ccb' / 'workspaces' / 'groups' / group
    for path in sorted(project_root.rglob('*')):
        try:
            relative = path.relative_to(project_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == '.ccb':
            continue
        if path.is_dir():
            continue
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    _write_json(
        project_root / '.ccb' / 'agents' / target / 'agent.json',
        {
            'schema_version': 2,
            'record_type': 'agent_spec',
            'name': target,
            'provider': 'codex',
            'workspace_mode': 'git-worktree',
            'workspace_group': group,
        },
    )
    _write_json(
        workspace / '.ccb-workspace.json',
        {
            'agent_name': target,
            'workspace_mode': 'git-worktree',
            'workspace_path': str(workspace),
            'target_project': str(project_root),
            'project_id': context.project.project_id,
        },
    )
    return workspace


def _seed_group_git_workspace_binding(
    context,
    project_root: Path,
    target: str,
    *,
    tracked_paths: tuple[str, ...],
    group: str = 'worker_pool',
) -> Path:
    workspace = project_root / '.ccb' / 'workspaces' / 'groups' / group
    for tracked_path in tracked_paths:
        relative = Path(tracked_path)
        source = project_root / relative
        if not source.is_file():
            continue
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    subprocess.run(['git', 'init'], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            'git',
            '-c',
            'user.email=ccb-test@example.invalid',
            '-c',
            'user.name=CCB Test',
            'commit',
            '-m',
            'workspace baseline',
        ],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    _write_json(
        project_root / '.ccb' / 'agents' / target / 'agent.json',
        {
            'schema_version': 2,
            'record_type': 'agent_spec',
            'name': target,
            'provider': 'codex',
            'workspace_mode': 'git-worktree',
            'workspace_group': group,
        },
    )
    _write_json(
        workspace / '.ccb-workspace.json',
        {
            'agent_name': target,
            'workspace_mode': 'git-worktree',
            'workspace_path': str(workspace),
            'target_project': str(project_root),
            'project_id': context.project.project_id,
        },
    )
    return workspace


def _completed_watch_batch(job_id: str, target: str, reply: str) -> WatchEventBatch:
    return WatchEventBatch(
        target=job_id,
        job_id=job_id,
        agent_name=target,
        target_kind='job',
        target_name=job_id,
        provider='codex',
        provider_instance=None,
        cursor=1,
        generation=1,
        terminal=True,
        status='completed',
        reply=reply,
        events=(),
    )


def _persisted_terminal_payload(
    job_id: str,
    target: str,
    *,
    status: str = 'completed',
    reply: str = 'done',
) -> dict[str, object]:
    return {
        'job_id': job_id,
        'agent_name': target,
        'target_kind': 'job',
        'target_name': job_id,
        'provider': 'codex',
        'provider_instance': None,
        'cursor': 1,
        'generation': None,
        'terminal': True,
        'status': status,
        'reply': reply,
        'visible_reply_source': 'snapshot',
        'events': [],
    }


def _write_completion_snapshot(
    project_root: Path,
    *,
    job_id: str,
    agent_name: str,
    reply: str,
    status: str = 'completed',
    terminal: bool = True,
) -> Path:
    path = project_root / '.ccb' / 'ccbd' / 'snapshots' / f'{job_id}.json'
    _write_json(
        path,
        {
            'schema_version': 2,
            'record_type': 'completion_snapshot',
            'job_id': job_id,
            'agent_name': agent_name,
            'state': {'terminal': terminal},
            'latest_decision': {
                'terminal': terminal,
                'status': status,
                'reason': 'task_complete' if status == 'completed' else status,
                'reply': reply,
                'finished_at': '2026-07-05T00:00:00Z' if terminal else None,
            },
        },
    )
    return path


def _write_installed_role(store_root: Path, role_id: str, *, default_agent_name: str) -> None:
    _write(
        store_root / 'installed' / role_id / 'current' / 'role.toml',
        f'''id = "{role_id}"
version = "0.1.0"

[identity]
default_agent_name = "{default_agent_name}"
''',
    )


def _project_with_loop_capacity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-loop-capacity'
    role_store = tmp_path / 'roles'
    _write_installed_role(role_store, 'agentroles.coder', default_agent_name='coder')
    _write_installed_role(role_store, 'agentroles.code_reviewer', default_agent_name='code_reviewer')
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))

    def clear_immaculate_test_agent(_context, clear_command):
        return {
            'status': 'ok',
            'results': [
                {'agent': name, 'status': 'cleared', 'pane_id': f'%{index}', 'command': '/clear'}
                for index, name in enumerate(clear_command.agent_names, start=1)
            ],
        }

    monkeypatch.setattr(loop_runner_module, 'clear_agent_context', clear_immaculate_test_agent)
    _write(
        project_root / '.ccb' / 'ccb.config',
        """cmd; orchestrator:codex; task_detailer:codex

[loop.capacity]
enabled = true
max_nodes = 3
default_lifetime = "current_round"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.worker]
role = "agentroles.coder"
provider = "codex"
thinking = "high"
workspace_mode = "git-worktree"
workspace_group = "worker_pool"
max_instances = 2
reuse = "prefer_idle"

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
thinking = "medium"
workspace_mode = "git-worktree"
workspace_group = "review_pool"
max_instances = 1
""",
    )
    return project_root


def _project_with_workflow_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-loop-workflow-dispatch'
    role_store = tmp_path / 'roles-workflow-dispatch'
    for role_id, default_agent_name in (
        ('agentroles.ccb_frontdesk', 'ccb_frontdesk'),
        ('agentroles.ccb_task_detailer', 'ccb_task_detailer'),
        ('agentroles.ccb_planner', 'ccb_planner'),
        ('agentroles.ccb_orchestrator', 'ccb_orchestrator'),
        ('agentroles.ccb_round_reviewer', 'ccb_round_reviewer'),
        ('agentroles.coder', 'coder'),
        ('agentroles.code_reviewer', 'code_reviewer'),
    ):
        _write_installed_role(role_store, role_id, default_agent_name=default_agent_name)
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))

    def clear_immaculate_test_agent(_context, clear_command):
        return {
            'status': 'ok',
            'results': [
                {'agent': name, 'status': 'cleared', 'pane_id': f'%{index}', 'command': '/clear'}
                for index, name in enumerate(clear_command.agent_names, start=1)
            ],
        }

    monkeypatch.setattr(loop_ask_first_module, 'clear_agent_context', clear_immaculate_test_agent)
    monkeypatch.setattr(loop_runner_module, 'clear_agent_context', clear_immaculate_test_agent)
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "ccb-user"

[windows]
ccb-user = "bootstrap:codex"

[loop.capacity]
enabled = true
max_nodes = 4
default_lifetime = "current_loop"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.ccb_frontdesk]
role = "agentroles.ccb_frontdesk"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.ccb_task_detailer]
role = "agentroles.ccb_task_detailer"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.ccb_planner]
role = "agentroles.ccb_planner"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.ccb_orchestrator]
role = "agentroles.ccb_orchestrator"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.ccb_round_reviewer]
role = "agentroles.ccb_round_reviewer"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.coder]
role = "agentroles.coder"
provider = "codex"
workspace_mode = "git-worktree"
max_instances = 2

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
workspace_mode = "git-worktree"
max_instances = 2
""",
    )
    return project_root


def test_v2_effective_capacity_snapshot_preserves_physical_nodes_and_limits_workgroups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)

    first = compile_project_effective_capacity_snapshot(project_root)
    second = compile_project_effective_capacity_snapshot(project_root)

    assert first['schema'] == 'ccb.loop.effective_capacity_snapshot.v1'
    assert first['config_version'] == 2
    assert first['workflow_mode'] == 'route_only'
    assert first['limits'] == {
        'max_workgroups': 1,
        'max_parallel_workgroups': 1,
        'max_active_dynamic_agents': 4,
    }
    assert set(first['dynamic_profiles']) >= {'coder', 'code_reviewer'}
    assert effective_capacity_digest(first) == effective_capacity_digest(second)


def _multi_workgroup_capacity_snapshot(*, max_workgroups: int = 4) -> dict[str, object]:
    return {
        'schema': 'ccb.loop.effective_capacity_snapshot.v1',
        'config_version': 3,
        'workflow_profile': 'single_lane_multi_workgroup',
        'workflow_mode': 'adaptive_workgroups',
        'limits': {
            'max_workgroups': max_workgroups,
            'max_parallel_workgroups': max_workgroups,
            'max_active_dynamic_agents': max_workgroups * 2,
        },
        'policies': {
            'node_rework': {'max_rounds': 1},
            'workspace': {'mode': 'git_worktree'},
            'integration': {'mode': 'controller_owned'},
            'release': {'default_lifetime': 'current_loop', 'policy': 'auto', 'idle_only': True},
            'naming': {'template': 'loop-{loop_id}-{profile}-{index}'},
            'execution_windows': {'policy': 'six_pane_overflow'},
        },
        'resident_profiles': {},
        'dynamic_profiles': {
            'coder': {
                'role_id': 'agentroles.coder',
                'provider': 'codex',
                'model': None,
                'workspace_mode': 'git-worktree',
                'release_policy': 'current_loop',
                'max_instances': max_workgroups,
            },
            'code_reviewer': {
                'role_id': 'agentroles.code_reviewer',
                'provider': 'codex',
                'model': None,
                'workspace_mode': 'git-worktree',
                'release_policy': 'current_loop',
                'max_instances': max_workgroups,
            },
        },
        'profile_aliases': {},
    }


def _v3_two_node_candidate(task_id: str, contract_ref: str) -> dict[str, object]:
    return {
        'schema': 'ccb.loop.orchestration_bundle_candidate.v1',
        'task_id': task_id,
        'bundle_revision': 1,
        'selection': {
            'workgroup_count': 2,
            'complexity': 'bounded',
            'cutability': 'high',
            'execution_shape': 'parallel',
            'rationale': 'Core and CLI scopes are independently reviewable.',
        },
        'nodes': [
            {
                'node_id': 'node-001',
                'workgroup_id': 'wg-core',
                'worker_profile': 'coder',
                'reviewer_profile': 'code_reviewer',
                'depends_on': [],
                'parallel_group': 'wave-1',
                'work_packet': 'Implement the core slice.',
                'allowed_paths': ['src/core/'],
                'acceptance_refs': [contract_ref],
                'verification_refs': [contract_ref],
                'integration_order': 10,
            },
            {
                'node_id': 'node-002',
                'workgroup_id': 'wg-cli',
                'worker_profile': 'coder',
                'reviewer_profile': 'code_reviewer',
                'depends_on': [],
                'parallel_group': 'wave-1',
                'work_packet': 'Implement the CLI slice.',
                'allowed_paths': ['src/cli/'],
                'acceptance_refs': [contract_ref],
                'verification_refs': [contract_ref],
                'integration_order': 20,
            },
        ],
        'integration': {
            'verification_refs': [contract_ref],
            'project_root_verification_refs': [contract_ref],
        },
        'policy': {
            'max_node_rework_rounds': 1,
            'on_required_node_failure': 'partial_or_blocked',
            'on_structural_failure': 'replan_required',
        },
    }


def _project_with_default_orchestrator_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-default-orchestrator-agent'
    role_store = tmp_path / 'roles-default-orchestrator-agent'
    for role_id, default_agent_name in (
        ('agentroles.ccb_frontdesk', 'frontdesk'),
        ('agentroles.ccb_planner', 'planner'),
        ('agentroles.ccb_orchestrator', 'orchestrator'),
        ('agentroles.ccb_round_reviewer', 'ccb_round_reviewer'),
        ('agentroles.coder', 'coder'),
        ('agentroles.code_reviewer', 'code_reviewer'),
    ):
        _write_installed_role(role_store, role_id, default_agent_name=default_agent_name)
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))

    def clear_immaculate_test_agent(_context, clear_command):
        return {
            'status': 'ok',
            'results': [
                {'agent': name, 'status': 'cleared', 'pane_id': f'%{index}', 'command': '/clear'}
                for index, name in enumerate(clear_command.agent_names, start=1)
            ],
        }

    monkeypatch.setattr(loop_ask_first_module, 'clear_agent_context', clear_immaculate_test_agent)
    monkeypatch.setattr(loop_runner_module, 'clear_agent_context', clear_immaculate_test_agent)
    _write(
        project_root / '.ccb' / 'ccb.config',
        """frontdesk:codex; planner:codex; orchestrator:codex; ccb_round_reviewer:codex

[agents.frontdesk]
role = "agentroles.ccb_frontdesk"

[agents.planner]
role = "agentroles.ccb_planner"

[agents.orchestrator]
role = "agentroles.ccb_orchestrator"

[agents.ccb_round_reviewer]
role = "agentroles.ccb_round_reviewer"

[loop.capacity]
enabled = true
max_nodes = 4
default_lifetime = "current_loop"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.ccb_orchestrator]
role = "agentroles.ccb_orchestrator"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.ccb_round_reviewer]
role = "agentroles.ccb_round_reviewer"
provider = "codex"
workspace_mode = "inplace"
max_instances = 1

[loop.role_profiles.coder]
role = "agentroles.coder"
provider = "codex"
workspace_mode = "copy"
max_instances = 1

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
workspace_mode = "copy"
max_instances = 1
""",
    )
    return project_root


def _add_ready_plan_task(
    project_root: Path,
    *,
    task_id: str = 'task-001',
    task_packet_text: str = 'task packet text\n',
    execution_contract_text: str = 'execution contract text\n',
) -> None:
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan'
    task_root = plan_root / 'tasks' / task_id
    _write(plan_root / 'README.md', '# Demo Plan\n')
    artifacts: dict[str, dict[str, object]] = {}
    for kind, filename, text in (
        ('task_packet', 'task_packet.md', task_packet_text),
        ('execution_contract', 'execution_contract.md', execution_contract_text),
    ):
        path = task_root / filename
        _write(path, text)
        artifacts[kind] = {
            'kind': kind,
            'artifact_kind': kind,
            'path': str(path.relative_to(project_root)),
            'artifact_path': str(path.relative_to(project_root)),
            'source_path': str(path.relative_to(project_root)),
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'bytes': len(text.encode('utf-8')),
            'imported_at': '2026-06-27T00:00:00Z',
            'task_revision': 1,
        }
    record = {
        'task_id': task_id,
        'title': 'Task id bridge',
        'plan_slug': 'demo-plan',
        'plan_root': 'docs/plantree/plans/demo-plan',
        'status': 'ready_for_orchestration',
        'task_revision': 1,
        'current_loop': None,
        'owner': 'loop_runner',
        'next_owner': 'orchestrator',
        'activation_reason': 'test_ready_for_orchestration',
        'created_at': '2026-06-27T00:00:00Z',
        'updated_at': '2026-06-27T00:00:00Z',
        'task_root': str(task_root.relative_to(project_root)),
        'artifacts': artifacts,
    }
    _write(
        plan_root / 'tasks' / 'index.json',
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_plan_task_index',
                'plan_slug': 'demo-plan',
                'plan_root': str(plan_root),
                'updated_at': '2026-06-27T00:00:00Z',
                'tasks': [record],
            },
            ensure_ascii=False,
            indent=2,
        )
        + '\n',
    )


def _add_legacy_ready_plan_task(project_root: Path, *, task_id: str = 'task-legacy-ready') -> None:
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan'
    task_root = plan_root / 'tasks' / task_id
    _write(plan_root / 'README.md', '# Demo Plan\n')
    artifacts: dict[str, dict[str, object]] = {}
    for kind, filename, text in (
        ('requirements', 'requirements.md', 'requirements text\n'),
        ('acceptance', 'acceptance-criteria.md', 'acceptance text\n'),
        ('verification', 'verification-contract.md', 'verification text\n'),
        ('handoff', 'handoff.md', 'handoff text\n'),
        ('review', 'review.md', 'review text\n'),
    ):
        path = task_root / filename
        _write(path, text)
        artifacts[kind] = {
            'kind': kind,
            'artifact_kind': kind,
            'path': str(path.relative_to(project_root)),
            'artifact_path': str(path.relative_to(project_root)),
            'source_path': str(path.relative_to(project_root)),
            'sha256': 'test',
            'bytes': len(text.encode('utf-8')),
            'imported_at': '2026-06-27T00:00:00Z',
        }
    record = {
        'task_id': task_id,
        'title': 'Legacy ready task',
        'plan_slug': 'demo-plan',
        'plan_root': 'docs/plantree/plans/demo-plan',
        'status': 'ready',
        'current_loop': None,
        'owner': 'loop_runner',
        'created_at': '2026-06-27T00:00:00Z',
        'updated_at': '2026-06-27T00:00:00Z',
        'task_root': str(task_root.relative_to(project_root)),
        'artifacts': artifacts,
    }
    _write(
        plan_root / 'tasks' / 'index.json',
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_plan_task_index',
                'plan_slug': 'demo-plan',
                'plan_root': str(plan_root),
                'updated_at': '2026-06-27T00:00:00Z',
                'tasks': [record],
            },
            ensure_ascii=False,
            indent=2,
        )
        + '\n',
    )


def _add_plan_task_record(
    project_root: Path,
    *,
    task_id: str,
    status: str,
    artifacts: dict[str, dict[str, object]] | None = None,
    current_loop: str | None = None,
    next_owner: str | None = None,
    activation_reason: str | None = None,
) -> None:
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan'
    task_root = plan_root / 'tasks' / task_id
    _write(plan_root / 'README.md', '# Demo Plan\n')
    record = {
        'task_id': task_id,
        'title': f'{status} task',
        'plan_slug': 'demo-plan',
        'plan_root': 'docs/plantree/plans/demo-plan',
        'status': status,
        'current_loop': current_loop,
        'owner': 'planner' if status in {'draft', 'partial', 'replan_required'} else 'frontdesk',
        'created_at': '2026-06-27T00:00:00Z',
        'updated_at': '2026-06-27T00:00:00Z',
        'task_root': str(task_root.relative_to(project_root)),
        'artifacts': artifacts or {},
    }
    if next_owner is not None:
        record['next_owner'] = next_owner
    if activation_reason is not None:
        record['activation_reason'] = activation_reason
    index_path = plan_root / 'tasks' / 'index.json'
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        index = {
            'schema_version': 1,
            'record_type': 'ccb_plan_task_index',
            'plan_slug': 'demo-plan',
            'plan_root': str(plan_root),
            'updated_at': '2026-06-27T00:00:00Z',
            'tasks': [],
        }
    index['tasks'].append(record)
    _write(index_path, json.dumps(index, ensure_ascii=False, indent=2) + '\n')


def _import_orchestration_notes(
    context,
    project_root: Path,
    *,
    task_id: str,
    route: str,
    text: str | None = None,
) -> dict[str, object]:
    notes = project_root / 'drafts' / f'{task_id}-{route}-orchestration-notes.md'
    _write(notes, text or f'route: {route}\n')
    imported = plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id=task_id,
            artifact_kind='orchestration_notes',
            file_path=str(notes),
            route=route,
        ),
    )
    if route in {'direct_execution', 'partial_completion'}:
        candidate = build_single_node_candidate(
            imported['task'],
            project_root=project_root,
        )
        candidate_path = project_root / 'drafts' / f'{task_id}-{route}-orchestration-bundle.json'
        _write_json(candidate_path, candidate)
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id=task_id,
                artifact_kind='orchestration_bundle',
                file_path=str(candidate_path),
                actor_source='test_deterministic_single_node',
                actor='loop_runner',
            ),
        )
        imported = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    return imported


def _run_phase2(argv: list[str], *, cwd: Path) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    result = maybe_handle_phase2(argv, cwd=cwd, stdout=stdout, stderr=stderr)
    payload = json.loads(stdout.getvalue()) if stdout.getvalue().strip() else {}
    return result, payload, stderr.getvalue()


def _workflow_dispatch_proposal() -> dict[str, object]:
    return {
        'dispatch_compatibility': 'legacy',
        'nodes': [
            {
                'id': 'plan',
                'agents': [
                    {'id': 'wf-ccb-orchestrator', 'profile': 'ccb_orchestrator', 'desired_state': 'present'},
                    {'id': 'wf-ccb-round-reviewer', 'profile': 'ccb_round_reviewer', 'desired_state': 'present'},
                ],
            },
            {
                'id': 'work-1',
                'agents': [
                    {'id': 'wf-coder-1', 'profile': 'coder', 'desired_state': 'present'},
                    {'id': 'wf-code-reviewer-1', 'profile': 'code_reviewer', 'desired_state': 'present'},
                ],
            },
        ],
        'edges': [
            {
                'id': 'coder-ask',
                'from': 'wf-ccb-orchestrator',
                'to': 'wf-coder-1',
                'type': 'ask',
                'order': 10,
                'output_artifact': 'coder.md',
            },
            {
                'id': 'reviewer-ask',
                'from': 'wf-coder-1',
                'to': 'wf-code-reviewer-1',
                'type': 'ask_after',
                'after': ['coder-ask'],
                'order': 20,
                'input_artifact': 'coder.md',
                'output_artifact': 'review.md',
            },
            {
                'id': 'round-review',
                'from': 'wf-code-reviewer-1',
                'to': 'wf-ccb-round-reviewer',
                'type': 'ask_after',
                'after': ['reviewer-ask'],
                'order': 30,
                'input_artifact': 'review.md',
                'output_artifact': 'round.md',
            },
        ],
        'artifacts': {'round': 'round.md'},
    }


def _manual_dispatch_desired(*, loop_id: str, edges: list[dict[str, object]], revision: int = 1) -> dict[str, object]:
    return {
        'schema': 'ccb.loop.agent_topology.v1',
        'record_type': 'ccb_loop_agent_topology_desired',
        'topology_status': 'committed',
        'loop_id': loop_id,
        'revision': revision,
        'nodes': [],
        'edges': edges,
        'artifacts': {},
    }


def _manual_dispatch_observed(
    *,
    loop_id: str,
    desired_revision: int = 1,
    coder_state: str = 'present',
) -> dict[str, object]:
    coder_lifecycle = {'present': 'visible', 'hidden': 'hidden'}.get(coder_state, 'parked')
    agents = [
        ('wf-ccb-orchestrator', 'ccb_orchestrator', 'present', 'visible'),
        ('wf-coder-1', 'coder', coder_state, coder_lifecycle),
        ('wf-code-reviewer-1', 'code_reviewer', 'present', 'visible'),
        ('wf-ccb-round-reviewer', 'ccb_round_reviewer', 'present', 'visible'),
    ]
    return {
        'schema': 'ccb.loop.agent_topology.observed.v1',
        'record_type': 'ccb_loop_agent_topology_observed',
        'last_reconcile_status': 'reconciled',
        'loop_id': loop_id,
        'desired_revision': desired_revision,
        'agents': [
            {
                'id': agent_id,
                'profile': profile,
                'desired_state': 'present',
                'observed_state': observed_state,
                'lifecycle_state': lifecycle_state,
                'ask_target': agent_id,
            }
            for agent_id, profile, observed_state, lifecycle_state in agents
        ],
        'edges': [],
        'drift': {'mismatched_agents': [], 'agent_count': len(agents)},
    }


def _namespace(project_id: str):
    return SimpleNamespace(
        project_id=project_id,
        namespace_epoch=1,
        tmux_socket_path='/tmp/ccb-test-tmux.sock',
        tmux_session_name='ccb-test-session',
        workspace_window_name='main',
        workspace_window_id='@main',
        workspace_epoch=1,
        ui_attachable=True,
    )


def test_loop_capacity_parser_supports_scriptable_json_commands() -> None:
    parser = CliParser()

    assert parser.parse(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'worker=2',
            '--profile',
            'code_reviewer',
            '--json',
        ]
    ) == ParsedLoopCapacityCommand(
        project=None,
        action='ensure',
        loop_id='round1',
        profile_counts=(('worker', 2), ('code_reviewer', 1)),
        json_output=True,
    )
    assert parser.parse(
        ['loop', 'capacity', 'status', '--loop-id', 'round1', '--json']
    ) == ParsedLoopCapacityCommand(project=None, action='status', loop_id='round1', json_output=True)
    assert parser.parse(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--idle-only', '--json']
    ) == ParsedLoopCapacityCommand(project=None, action='release', loop_id='round1', idle_only=True, json_output=True)
    assert parser.parse(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--policy', 'auto', '--json']
    ) == ParsedLoopCapacityCommand(project=None, action='release', loop_id='round1', policy='auto', json_output=True)
    assert parser.parse(
        [
            'loop',
            'run-once',
            '--loop-id',
            'round1',
            '--task',
            'ship the slice',
            '--worker-profile',
            'worker',
            '--reviewer-profile',
            'code_reviewer',
            '--orchestrator',
            'orchestrator',
            '--round-checker',
            'round_checker',
            '--timeout',
            '5',
            '--json',
        ]
    ) == ParsedLoopRunOnceCommand(
        project=None,
        loop_id='round1',
        task='ship the slice',
        worker_profile='worker',
        reviewer_profile='code_reviewer',
        orchestrator='orchestrator',
        round_checker='round_checker',
        timeout_s=5.0,
        json_output=True,
    )
    assert parser.parse(
        ['loop', 'run-once', '--task-id', 'task-001', '--json']
    ) == ParsedLoopRunOnceCommand(project=None, task_id='task-001', json_output=True)
    assert parser.parse(
        ['loop', 'runner', '--once', '--timeout', '5', '--json']
    ) == ParsedLoopRunnerCommand(project=None, once=True, timeout_s=5.0, json_output=True)
    assert parser.parse(
        ['loop', 'runner', '--once', '--task', 'task-001', '--timeout', '5', '--json']
    ) == ParsedLoopRunnerCommand(project=None, once=True, task_id='task-001', timeout_s=5.0, json_output=True)
    assert parser.parse(
        ['loop', 'runner', '--once', '--task-id', 'task-001', '--json']
    ) == ParsedLoopRunnerCommand(project=None, once=True, task_id='task-001', json_output=True)
    assert parser.parse(
        ['loop', 'runner', '--auto', '--wait-job', 'job_planner', '--poll-interval', '0', '--max-steps', '7', '--json']
    ) == ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner',
        max_steps=7,
        poll_interval_s=0.0,
        json_output=True,
    )
    with pytest.raises(CliUsageError, match='loop runner requires exactly one of --once or --auto'):
        parser.parse(['loop', 'runner', '--json'])
    with pytest.raises(CliUsageError, match='loop runner requires exactly one of --once or --auto'):
        parser.parse(['loop', 'runner', '--once', '--auto'])
    with pytest.raises(CliUsageError, match='loop runner --wait-job requires --auto'):
        parser.parse(['loop', 'runner', '--once', '--wait-job', 'job_planner'])
    with pytest.raises(CliUsageError, match='loop runner --task requires a non-empty task id'):
        parser.parse(['loop', 'runner', '--once', '--task', ''])
    with pytest.raises(CliUsageError, match='loop runner --task-id requires a non-empty task id'):
        parser.parse(['loop', 'runner', '--once', '--task-id', '   '])
    with pytest.raises(CliUsageError, match='loop run-once --task-id requires a non-empty task id'):
        parser.parse(['loop', 'run-once', '--task-id', ''])
    assert parser.parse(
        [
            'loop',
            'runner',
            '--once',
            '--consume-role-output',
            '--job',
            'job_frontdesk',
            '--plan',
            'demo-plan',
            '--timeout',
            '5',
            '--json',
        ]
    ) == ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_frontdesk',
        timeout_s=5.0,
        consume_role_output=True,
        json_output=True,
    )
    with pytest.raises(CliUsageError, match='loop runner --consume-role-output requires --job <job_id>'):
        parser.parse(['loop', 'runner', '--once', '--consume-role-output'])
    with pytest.raises(CliUsageError, match='loop runner --job requires --consume-role-output'):
        parser.parse(['loop', 'runner', '--once', '--job', 'job_frontdesk'])


def test_loop_capacity_ensure_places_worker_and_reviewer_in_execution_node_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "main"

[windows]
main = "orchestrator:codex"

[loop.capacity]
enabled = true
max_nodes = 3
default_lifetime = "current_round"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.worker]
role = "agentroles.coder"
provider = "codex"
thinking = "high"
workspace_mode = "git-worktree"
workspace_group = "worker_pool"
max_instances = 2
reuse = "prefer_idle"

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
thinking = "medium"
workspace_mode = "git-worktree"
workspace_group = "review_pool"
max_instances = 1
""",
    )
    current = load_project_config(project_root, include_loop_overlays=False).config

    result, payload, stderr = _run_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'worker=1',
            '--profile',
            'code_reviewer=1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert [(agent['name'], agent['node_id'], agent['placement']['window_name']) for agent in payload['agents']] == [
        ('loop-round1-worker-1', 'node1', 'node-round1-node1'),
        ('loop-round1-code_reviewer-1', 'node1', 'node-round1-node1'),
    ]
    loaded = load_project_config(project_root).config
    assert [(window.name, window.agent_names, window.layout_spec) for window in loaded.windows] == [
        ('main', ('orchestrator',), 'orchestrator:codex'),
        (
            'node-round1-node1',
            ('loop-round1-worker-1', 'loop-round1-code_reviewer-1'),
            'loop-round1-worker-1:codex(worktree); loop-round1-code_reviewer-1:codex(worktree)',
        ),
    ]
    plan = build_reload_dry_run_plan(current, loaded, project_id='proj-1', current_namespace=_namespace('proj-1'))
    assert plan['plan_class'] == 'add_window'
    assert [step['action'] for step in plan['namespace_patch_plan']['steps']] == [
        'create_window',
        'create_sidebar_pane',
        'create_agent_pane',
        'create_agent_pane',
    ]


def test_loop_capacity_ensure_places_multiple_nodes_in_separate_windows_and_release_cleans_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / 'repo-loop-capacity-explicit-multi-node'
    role_store = tmp_path / 'roles'
    _write_installed_role(role_store, 'agentroles.coder', default_agent_name='coder')
    _write_installed_role(role_store, 'agentroles.code_reviewer', default_agent_name='code_reviewer')
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "main"

[windows]
main = "orchestrator:codex"

[loop.capacity]
enabled = true
max_nodes = 4
default_lifetime = "current_round"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.worker]
role = "agentroles.coder"
provider = "codex"
thinking = "high"
workspace_mode = "git-worktree"
workspace_group = "worker_pool"
max_instances = 2
reuse = "prefer_idle"

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
thinking = "medium"
workspace_mode = "git-worktree"
workspace_group = "review_pool"
max_instances = 2
""",
    )
    current = load_project_config(project_root, include_loop_overlays=False).config

    result, payload, stderr = _run_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round2',
            '--profile',
            'worker=2',
            '--profile',
            'code_reviewer=2',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert [(agent['name'], agent['node_id'], agent['created_sequence']) for agent in payload['agents']] == [
        ('loop-round2-worker-1', 'node1', 1),
        ('loop-round2-worker-2', 'node2', 2),
        ('loop-round2-code_reviewer-1', 'node1', 3),
        ('loop-round2-code_reviewer-2', 'node2', 4),
    ]
    loaded = load_project_config(project_root).config
    assert [(window.name, window.agent_names) for window in loaded.windows] == [
        ('main', ('orchestrator',)),
        ('node-round2-node1', ('loop-round2-worker-1', 'loop-round2-code_reviewer-1')),
        ('node-round2-node2', ('loop-round2-worker-2', 'loop-round2-code_reviewer-2')),
    ]
    plan = build_reload_dry_run_plan(current, loaded, project_id='proj-1', current_namespace=_namespace('proj-1'))
    assert plan['plan_class'] == 'add_window'
    assert [step['action'] for step in plan['namespace_patch_plan']['steps']] == [
        'create_window',
        'create_sidebar_pane',
        'create_agent_pane',
        'create_agent_pane',
        'create_window',
        'create_sidebar_pane',
        'create_agent_pane',
        'create_agent_pane',
    ]

    result, status_payload, stderr = _run_phase2(['layout', 'status', '--json'], cwd=project_root)

    assert result == 0, stderr
    assert status_payload['loop_agent_count'] == 4
    windows = {window['name']: window for window in status_payload['windows']}
    assert windows['node-round2-node1']['agent_names'] == [
        'loop-round2-worker-1',
        'loop-round2-code_reviewer-1',
    ]
    assert windows['node-round2-node2']['agent_names'] == [
        'loop-round2-worker-2',
        'loop-round2-code_reviewer-2',
    ]
    assert {agent['source'] for agent in windows['node-round2-node1']['agents']} == {'loop'}
    assert {agent['source'] for agent in windows['node-round2-node2']['agents']} == {'loop'}

    result, release_payload, stderr = _run_phase2(
        ['loop', 'capacity', 'release', '--loop-id', 'round2', '--idle-only', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert release_payload['released_count'] == 4
    released = load_project_config(project_root).config
    assert [(window.name, window.agent_names) for window in released.windows] == [
        ('main', ('orchestrator',)),
    ]
    result, released_status, stderr = _run_phase2(['layout', 'status', '--json'], cwd=project_root)
    assert result == 0, stderr
    assert released_status['loop_agent_count'] == 0
    assert [(window['name'], window['agent_names']) for window in released_status['windows']] == [
        ('main', ['orchestrator']),
    ]


def test_loop_run_once_writes_round_artifacts_and_releases_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunOnceCommand(project=None, loop_id='round1', task='ship the slice', timeout_s=7.0)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    calls: list[tuple[str, object]] = []

    def fake_loop_capacity(_context, capacity_command):
        calls.append(('capacity', capacity_command.action))
        if capacity_command.action == 'ensure':
            assert capacity_command.profile_counts == (('worker', 1), ('code_reviewer', 1))
            return {
                'loop_capacity_status': 'ensured',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'agents': [
                    {'name': 'loop-round1-worker-1', 'profile': 'worker', 'state': 'planned'},
                    {'name': 'loop-round1-code_reviewer-1', 'profile': 'code_reviewer', 'state': 'planned'},
                ],
                'apply': {'apply_status': 'applied', 'action': 'add_agent'},
            }
        if capacity_command.action == 'release':
            assert capacity_command.policy == 'auto'
            assert capacity_command.idle_only is False
            return {
                'loop_capacity_status': 'released',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'released_count': 2,
                'retained_count': 0,
                'release_policy': 'auto',
                'idle_only': True,
                'agents': [
                    {'name': 'loop-round1-worker-1', 'profile': 'worker', 'state': 'released'},
                    {'name': 'loop-round1-code_reviewer-1', 'profile': 'code_reviewer', 'state': 'released'},
                ],
                'apply': {'apply_status': 'applied', 'action': 'remove_agent'},
            }
        raise AssertionError(f'unexpected capacity action {capacity_command.action}')

    def fake_submit_ask(_context, ask_command):
        calls.append(('ask', ask_command.target))
        if ask_command.target == 'round_checker':
            assert ask_command.sender == 'system'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{ask_command.target}',
            jobs=(
                {
                    'job_id': f'job_{ask_command.target}',
                    'agent_name': ask_command.target,
                    'status': 'accepted',
                },
            ),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        calls.append(('watch', job_id))
        assert timeout == 7.0
        assert emit_output is False
        target = str(job_id).removeprefix('job_')
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=f'reply from {target}',
            events=(),
        )

    payload = loop_run_once(
        context,
        command,
        services=SimpleNamespace(
            loop_capacity=fake_loop_capacity,
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
        ),
    )

    assert payload['loop_run_status'] == 'ok'
    assert payload['agents'] == {
        'worker': 'loop-round1-worker-1',
        'reviewer': 'loop-round1-code_reviewer-1',
        'orchestrator': 'orchestrator',
        'round_checker': 'round_checker',
    }
    assert calls == [
        ('capacity', 'ensure'),
        ('ask', 'loop-round1-worker-1'),
        ('watch', 'job_loop-round1-worker-1'),
        ('ask', 'loop-round1-code_reviewer-1'),
        ('watch', 'job_loop-round1-code_reviewer-1'),
        ('ask', 'orchestrator'),
        ('watch', 'job_orchestrator'),
        ('ask', 'round_checker'),
        ('watch', 'job_round_checker'),
        ('capacity', 'release'),
    ]

    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / 'round1'
    round_payload = json.loads((loop_dir / 'round.json').read_text(encoding='utf-8'))
    asks = [json.loads(line) for line in (loop_dir / 'asks.jsonl').read_text(encoding='utf-8').splitlines()]
    events = [json.loads(line) for line in (loop_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert round_payload['loop_run_status'] == 'ok'
    assert round_payload['capacity']['release']['release_policy'] == 'auto'
    assert round_payload['capacity']['release']['idle_only'] is True
    assert [ask['purpose'] for ask in asks] == ['worker', 'reviewer', 'aggregate', 'round_checker']
    assert [event['kind'] for event in events] == [
        'loop_run_started',
        'ask_terminal',
        'ask_terminal',
        'ask_terminal',
        'ask_terminal',
        'loop_run_finished',
    ]
    assert (loop_dir / 'breadcrumb.md').read_text(encoding='utf-8').startswith('Loop: round1\n')
    assert (loop_dir / 'artifacts' / 'worker-reply.md').read_text(encoding='utf-8') == 'reply from loop-round1-worker-1'
    assert (loop_dir / 'artifacts' / 'reviewer-reply.md').read_text(encoding='utf-8') == 'reply from loop-round1-code_reviewer-1'
    assert (loop_dir / 'artifacts' / 'aggregate-reply.md').read_text(encoding='utf-8') == 'reply from orchestrator'
    assert (loop_dir / 'artifacts' / 'round_checker-reply.md').read_text(encoding='utf-8') == 'reply from round_checker'


def test_loop_run_once_task_id_binds_ready_task_and_reads_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-bridge')
    command = ParsedLoopRunOnceCommand(project=None, loop_id='loop-a', task_id='task-bridge', timeout_s=7.0)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    worker_messages: list[str] = []

    def fake_loop_capacity(_context, capacity_command):
        if capacity_command.action == 'ensure':
            return {
                'loop_capacity_status': 'ensured',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'agents': [
                    {'name': 'loop-loop-a-worker-1', 'profile': 'worker', 'state': 'planned'},
                    {'name': 'loop-loop-a-code_reviewer-1', 'profile': 'code_reviewer', 'state': 'planned'},
                ],
                'apply': {'apply_status': 'applied', 'action': 'add_agent'},
            }
        if capacity_command.action == 'release':
            return {
                'loop_capacity_status': 'released',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'released_count': 2,
                'retained_count': 0,
                'release_policy': 'auto',
                'idle_only': True,
                'agents': [],
                'apply': {'apply_status': 'applied', 'action': 'remove_agent'},
            }
        raise AssertionError(f'unexpected capacity action {capacity_command.action}')

    def fake_submit_ask(_context, ask_command):
        if ask_command.target == 'loop-loop-a-worker-1':
            worker_messages.append(ask_command.message)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{ask_command.target}',
            jobs=(
                {
                    'job_id': f'job_{ask_command.target}',
                    'agent_name': ask_command.target,
                    'status': 'accepted',
                },
            ),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        target = str(job_id).removeprefix('job_')
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply='round result: pass' if target == 'round_checker' else f'reply from {target}',
            events=(),
        )

    payload = loop_run_once(
        context,
        command,
        services=SimpleNamespace(
            loop_capacity=fake_loop_capacity,
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
        ),
    )

    assert payload['loop_run_status'] == 'ok'
    assert payload['task_id'] == 'task-bridge'
    assert worker_messages
    assert 'Task Packet:\ntask packet text' in worker_messages[0]
    assert 'Execution Contract:\nexecution contract text' in worker_messages[0]
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-bridge'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == 'loop-a'
    breadcrumb = (project_root / '.ccb' / 'runtime' / 'loops' / 'loop-a' / 'breadcrumb.md').read_text(encoding='utf-8')
    assert 'Task: task-bridge\n' in breadcrumb


def test_loop_runner_once_ready_for_orchestration_activates_orchestrator_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-runner')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    ready = plan_task(context, SimpleNamespace(action='task-show', task_id='task-runner'))
    assert ready['task']['status'] == 'ready_for_orchestration'
    assert ready['task']['next_owner'] == 'orchestrator'
    seen: dict[str, object] = {}

    def fake_submit_ask(_context, ask_command):
        seen['calls'] = int(seen.get('calls') or 0) + 1
        seen['target'] = ask_command.target
        seen['sender'] = ask_command.sender
        seen['task_id'] = ask_command.task_id
        seen['artifact_request'] = ask_command.artifact_request
        seen['inline_request'] = ask_command.inline_request
        seen['message'] = ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=(
                {
                    'job_id': 'job_orchestrator',
                    'agent_name': 'orchestrator',
                    'status': 'completed',
                    'reply': 'route: blocked\nstatus: done\nround result: pass\n',
                },
            ),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('ready_for_orchestration must not run the fixed execution bridge')

    def forbidden_watch_ask_job(*_args, **_kwargs):
        raise AssertionError('orchestrator route/status must not be parsed from provider replies')

    def forbidden_plan_task(*_args, **_kwargs):
        raise AssertionError('orchestrator activation must not bind loops or import status artifacts')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=forbidden_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            plan_task=forbidden_plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok', payload
    assert payload['action'] == 'activated_orchestrator'
    assert payload['task_id'] == 'task-runner'
    assert payload['task_status'] == 'ready_for_orchestration'
    assert payload['next_owner'] == 'orchestrator'
    assert payload['ask'] == {'target': 'orchestrator', 'job_id': 'job_orchestrator', 'status': 'completed'}
    assert payload['next_activation'] == 'stop_after_one_activation'
    assert seen['target'] == 'orchestrator'
    assert seen['sender'] == 'system'
    assert seen['artifact_request'] is False
    assert seen['inline_request'] is False
    assert seen['calls'] == 1
    message = str(seen['message'])
    assert 'Allowed routes: direct_execution, needs_detail, macro_adjustment_request, blocked, partial_completion' in message
    assert (
        'route: <one of direct_execution|needs_detail|macro_adjustment_request|blocked|partial_completion>'
        in message
    )
    assert 'Reply only; do not run ccb, ccb_test, artifact import commands, or wrapper commands.' in message
    assert (
        'Supervisor/script-owned import validates and records orchestration_notes, work packets, and '
        'orchestration_bundle.' in message
    )
    assert 'ccb.loop.orchestration_bundle_candidate.v1' in message
    assert 'Config V2 may omit it only for one deterministic workgroup' in message
    assert 'candidate root fields are exactly schema, task_id, bundle_revision, selection, nodes, integration, and policy' in message
    assert 'choose the smallest justified count from 1 to 4 without trying to fill capacity' in message
    assert '"workgroup_count":1' not in message
    assert 'Effective capacity snapshot:' in message
    assert 'Expected bundle revision: 1' in message
    assert 'do not rely on provider reply text' in message
    assert 'do not start task_detailer, worker, reviewer, loop_run_once, or topology dispatch' in message
    assert 'ccb plan task-artifact' not in message
    assert 'plan task-artifact' not in message
    assert 'route_import_command' not in message
    assert 'import the stable decision' not in message
    assert 'use CCB plan commands or host-provided wrappers for authoritative writes' not in message
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['record_type'] == 'ccb_loop_orchestrator_activation'
    assert activation['task_id'] == 'task-runner'
    assert 'route_import_command' not in activation
    assert (
        activation['required_next_output']
        == (
            'reply-only route decision, compact orchestration notes, and an orchestration bundle candidate '
            'for Config V3 execution routes or any decomposed Config V2 execution route'
        )
    )
    assert activation['expected_bundle_revision'] == 1
    assert activation['effective_capacity_snapshot']['limits']['max_workgroups'] == 1
    assert activation['artifact_refs'] == {
        'execution_contract': 'docs/plantree/plans/demo-plan/tasks/task-runner/execution_contract.md',
        'task_packet': 'docs/plantree/plans/demo-plan/tasks/task-runner/task_packet.md',
    }
    assert activation['compact_artifacts']['task_packet']['content'] == 'task packet text'
    assert activation['compact_artifacts']['execution_contract']['content'] == 'execution contract text'
    assert activation['allowed_routes'] == [
        'direct_execution',
        'needs_detail',
        'macro_adjustment_request',
        'blocked',
        'partial_completion',
    ]
    script_write_rules = '\n'.join(str(rule) for rule in activation['script_write_rules'])
    assert 'Reply only; do not run ccb, ccb_test, artifact import commands, or wrapper commands.' in script_write_rules
    assert (
        'Supervisor/script-owned import validates and records orchestration_notes, work packets, and '
        'orchestration_bundle; provider text is not authority.' in script_write_rules
    )
    assert 'always include one fenced JSON orchestration_bundle candidate' in script_write_rules
    assert 'ccb plan task-artifact' not in script_write_rules
    assert 'plan task-artifact' not in script_write_rules
    assert 'Import the stable route' not in script_write_rules
    assert 'authoritative writes' not in script_write_rules
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-runner'))
    assert shown['task']['status'] == 'ready_for_orchestration'
    assert shown['task']['current_loop'] is None
    assert shown['task']['next_owner'] == 'orchestrator'
    assert set(shown['task']['artifacts']) == {'task_packet', 'execution_contract'}


def test_loop_runner_orchestrator_clear_failure_blocks_before_provider_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-clear-blocked')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submissions: list[object] = []

    def failed_clear(_context, _clear_command):
        return {
            'status': 'partial',
            'results': [
                {
                    'agent': 'orchestrator',
                    'status': 'failed',
                    'reason': 'provider clear was not acknowledged',
                }
            ],
        }

    def forbidden_submit(_context, ask_command):
        submissions.append(ask_command)
        raise AssertionError('orchestrator ask must not run without proven freshness')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            clear_agent_context=failed_clear,
            submit_ask=forbidden_submit,
            plan_task=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('freshness failure must not mutate task authority')
            ),
        ),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'activation_freshness_not_ready'
    assert payload['freshness']['status'] == 'failed'
    assert payload['next_activation'] == 'repair_activation_freshness'
    assert submissions == []
    activation = json.loads(Path(payload['activation_path']).read_text(encoding='utf-8'))
    assert activation['freshness']['status'] == 'failed'
    assert 'ask' not in activation


def test_loop_runner_dynamic_orchestrator_mounts_imports_and_unloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-dynamic-orchestrator')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[object] = []

    def fake_clear_agent_context(_context, clear_command):
        return {
            'status': 'ok',
            'results': [
                {
                    'agent': clear_command.agent_names[0],
                    'status': 'cleared',
                    'pane_id': '%7',
                    'command': '/clear',
                }
            ],
        }

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_dynamic_orchestrator', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            clear_agent_context=fake_clear_agent_context,
            submit_ask=fake_submit_ask,
            plan_task=plan_task,
        ),
    )

    assert activated['action'] == 'activated_orchestrator'
    assert activated['ask']['target'] == 'orchestrator'
    assert activated['topology']['mode'] == 'dynamic'
    assert activated['topology']['loop_topology_status'] == 'ready'
    proposal = json.loads(Path(str(activated['topology']['propose']['proposal_path'])).read_text(encoding='utf-8'))
    assert len(proposal['agents']) == 1
    assert proposal['agents'][0] == {
        'desired_state': 'present',
        'id': 'orchestrator',
        'lifecycle': 'ephemeral',
        'pane_order': 0,
        'profile': 'ccb_orchestrator',
        'release_policy': 'auto',
        'window_name': 'ccb-plan',
    }
    lifecycle_path = project_root / '.ccb' / 'runtime' / 'agents' / 'orchestrator' / 'lifecycle.json'
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    assert lifecycle['lifecycle_state'] == 'visible'
    assert lifecycle['role_class'] == 'short_lived_execution'

    _write_completion_snapshot(
        project_root,
        job_id='job_dynamic_orchestrator',
        agent_name='orchestrator',
        reply='route: direct_execution\norchestration_notes: Ready for bounded execution.\n',
    )
    imported = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('completed orchestrator activation must not be resubmitted')
            ),
            plan_task=plan_task,
        ),
    )

    assert imported['action'] == 'imported_orchestration_notes'
    assert imported['route'] == 'direct_execution'
    assert imported['orchestration_bundle']['bundle_schema'] == 'ccb.loop.orchestration_bundle.v1'
    assert imported['orchestration_bundle']['bundle_source'] == 'loop_runner_deterministic_single_node'
    assert imported['orchestration_bundle']['node_count'] == 1
    assert imported['activation_topology_release']['loop_topology_status'] == 'released'
    assert imported['activation_topology_release']['released_agents'] == ['orchestrator']
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    assert lifecycle['lifecycle_state'] == 'unloaded'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-dynamic-orchestrator'))
    assert set(shown['task']['artifacts']) == {
        'task_packet',
        'execution_contract',
        'orchestration_notes',
        'orchestration_bundle',
    }


def test_loop_runner_multi_workgroup_bundle_binds_and_enters_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    task_id = 'task-multi-workgroup'
    _add_ready_plan_task(
        project_root,
        task_id=task_id,
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths:\n'
            '- src/core/\n'
            '- src/cli/\n'
        ),
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        timeout_s=11.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    notes_path = project_root / 'drafts' / f'{task_id}-orchestration-notes.md'
    _write(notes_path, 'route: direct_execution\norchestration_notes: two independent workgroups\n')
    imported = plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id=task_id,
            artifact_kind='orchestration_notes',
            file_path=str(notes_path),
            route='direct_execution',
        ),
    )
    task_root = str(imported['task']['task_root'])
    execution_contract_ref = f'{task_root}/execution_contract.md'
    candidate_path = project_root / 'drafts' / f'{task_id}-orchestration-bundle.json'
    _write_json(
        candidate_path,
            {
                'schema': 'ccb.loop.orchestration_bundle_candidate.v1',
                'task_id': task_id,
                'bundle_revision': 1,
                'selection': {
                    'workgroup_count': 2,
                    'complexity': 'bounded',
                    'cutability': 'high',
                    'execution_shape': 'parallel',
                    'rationale': 'Core and CLI scopes are independently reviewable.',
                },
                'nodes': [
                {
                    'node_id': 'node-001',
                    'workgroup_id': 'wg-core',
                    'worker_profile': 'coder',
                    'reviewer_profile': 'code_reviewer',
                    'depends_on': [],
                    'parallel_group': 'wave-1',
                    'work_packet': 'Implement the bounded core change.',
                    'allowed_paths': ['src/core/'],
                    'acceptance_refs': [execution_contract_ref],
                    'verification_refs': [execution_contract_ref],
                    'integration_order': 10,
                },
                {
                    'node_id': 'node-002',
                    'workgroup_id': 'wg-cli',
                    'worker_profile': 'coder',
                    'reviewer_profile': 'code_reviewer',
                    'depends_on': [],
                    'parallel_group': 'wave-1',
                    'work_packet': 'Implement the bounded CLI change.',
                    'allowed_paths': ['src/cli/'],
                    'acceptance_refs': [execution_contract_ref],
                    'verification_refs': [execution_contract_ref],
                    'integration_order': 20,
                },
            ],
            'integration': {
                'verification_refs': [execution_contract_ref],
                'project_root_verification_refs': [execution_contract_ref],
            },
            'policy': {
                'max_node_rework_rounds': 1,
                'on_required_node_failure': 'partial_or_blocked',
                'on_structural_failure': 'replan_required',
            },
        },
    )
    bundle_import = plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id=task_id,
            artifact_kind='orchestration_bundle',
            file_path=str(candidate_path),
            actor_source='test_multi_workgroup_bundle',
            actor='loop_runner',
            effective_capacity_snapshot=_multi_workgroup_capacity_snapshot(),
        ),
    )
    assert bundle_import['artifact']['node_count'] == 2

    scheduler_calls: list[dict[str, object]] = []

    def fake_scheduler(_context, **kwargs):
        scheduler_calls.append(kwargs)
        return {
            'schema': 'ccb.loop.workgroup_round_state.v1',
            'loop_runner_status': 'pending',
            'action': 'multi_workgroup_execution_pending',
            'task_id': task_id,
            'loop_id': kwargs['loop_id'],
            'round_result': 'pending',
            'round_result_source': 'scheduler_pending',
        }

    payload = loop_runner_once(
        context,
        command,
            services=SimpleNamespace(
                multi_workgroup_scheduler=fake_scheduler,
                plan_task=plan_task,
                effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
            ),
        )

    assert payload['loop_runner_status'] == 'pending'
    assert payload['action'] == 'multi_workgroup_execution_pending'
    assert payload['orchestration_bundle']['node_count'] == 2
    assert payload['orchestration_bundle']['node_ids'] == ['node-001', 'node-002']
    assert len(scheduler_calls) == 1
    assert scheduler_calls[0]['bundle']['selection']['workgroup_count'] == 2
    assert scheduler_calls[0]['task_record']['task_id'] == task_id
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == payload['loop_id']


def test_loop_runner_dynamic_task_detailer_mounts_imports_and_unloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-dynamic-detailer')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-dynamic-detailer', route='needs_detail')

    def fake_clear_agent_context(_context, clear_command):
        return {
            'status': 'ok',
            'results': [
                {
                    'agent': clear_command.agent_names[0],
                    'status': 'cleared',
                    'pane_id': '%8',
                    'command': '/clear',
                }
            ],
        }

    def fake_submit_ask(_context, ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_dynamic_detailer', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            clear_agent_context=fake_clear_agent_context,
            submit_ask=fake_submit_ask,
            plan_task=plan_task,
        ),
    )

    assert activated['action'] == 'activated_task_detailer'
    assert activated['ask']['target'] == 'task_detailer'
    assert activated['topology']['mode'] == 'dynamic'
    assert activated['topology']['window_name'] == 'ccb-user'
    assert activated['topology']['loop_topology_status'] == 'ready'
    lifecycle_path = project_root / '.ccb' / 'runtime' / 'agents' / 'task_detailer' / 'lifecycle.json'
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    assert lifecycle['lifecycle_state'] == 'visible'
    assert lifecycle['role_class'] == 'short_lived_execution'

    _write_completion_snapshot(
        project_root,
        job_id='job_dynamic_detailer',
        agent_name='task_detailer',
        reply="""**task-detail-design.md**

Design:
- Keep the implementation bounded to the declared task paths.

**brief-update-summary.md**

The missing task detail is now resolved.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```

Recommended route: `direct_execution`
""",
    )
    imported = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('completed detailer activation must not be resubmitted')
            ),
            plan_task=plan_task,
        ),
    )

    assert imported['action'] == 'imported_task_detailer_detail_authority'
    assert imported['task_status'] == 'detail_ready'
    assert imported['activation_topology_release']['loop_topology_status'] == 'released'
    assert imported['activation_topology_release']['released_agents'] == ['task_detailer']
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    assert lifecycle['lifecycle_state'] == 'unloaded'


def test_loop_runner_once_waits_for_existing_same_task_orchestrator_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-runner')
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-existing-orchestrator.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_orchestrator_activation',
            'activation_id': 'act-existing-orchestrator',
            'action': 'activate_orchestrator',
            'task_id': 'task-runner',
            'ask': {'target': 'orchestrator', 'job_id': 'job_orchestrator_existing', 'status': 'accepted'},
        },
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[str] = []

    def forbidden_submit_ask(_context, ask_command):
        submitted.append(ask_command.target)
        raise AssertionError('existing same-task orchestrator activation must be consumed or awaited')

    pending = loop_runner_once(context, command, services=SimpleNamespace(submit_ask=forbidden_submit_ask))

    assert pending['loop_runner_status'] == 'pending'
    assert pending['action'] == 'role_output_pending'
    assert pending['job_id'] == 'job_orchestrator_existing'
    assert pending['task_id'] == 'task-runner'
    assert submitted == []

    _write_completion_snapshot(
        project_root,
        job_id='job_orchestrator_existing',
        agent_name='orchestrator',
        reply='route: direct_execution\norchestration_notes: Task is ready for direct execution.\n',
    )

    imported = loop_runner_once(context, command, services=SimpleNamespace(submit_ask=forbidden_submit_ask))

    assert imported['loop_runner_status'] == 'ok'
    assert imported['action'] == 'imported_orchestration_notes'
    assert imported['task_id'] == 'task-runner'
    assert imported['route'] == 'direct_execution'
    assert submitted == []
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-runner'))
    assert shown['task']['artifacts']['orchestration_notes']['orchestrator_route'] == 'direct_execution'


def test_loop_runner_task_filter_ignores_unrelated_pending_role_output_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-runner')
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-pending-planner.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-pending-planner',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_pending_planner', 'status': 'submitted'},
        },
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, task_id='task-runner', json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    def fake_submit_ask(_context, ask_command):
        seen['target'] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator', 'agent_name': 'orchestrator', 'status': 'submitted'},),
        )

    payload = loop_runner_once(context, command, services=SimpleNamespace(submit_ask=fake_submit_ask))

    assert payload['action'] == 'activated_orchestrator'
    assert payload['task_id'] == 'task-runner'
    assert seen['target'] == 'orchestrator'


def test_loop_runner_explicit_task_resumes_scheduler_release_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id='task-release-resume',
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen = []

    def resume(_context, *, task_id, services):
        seen.append((task_id, services))
        return {
            'loop_runner_status': 'pending',
            'action': 'multi_workgroup_execution_pending',
            'controller_status': 'release_blocked',
            'task_id': task_id,
            'pending_job_ids': [],
        }

    services = SimpleNamespace(resume_multi_workgroup_scheduler=resume)
    payload = loop_runner_once(context, command, services=services)

    assert payload['controller_status'] == 'release_blocked'
    assert seen == [('task-release-resume', services)]


def test_loop_runner_auto_waits_for_seed_and_activation_jobs_without_duplicate_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner',
        max_steps=4,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    loop_payloads = [
        {'loop_runner_status': 'ok', 'action': 'imported_planner_task_authority', 'task_id': 'task-auto'},
        {
            'loop_runner_status': 'ok',
            'action': 'activated_orchestrator',
            'task_id': 'task-auto',
            'ask': {'target': 'orchestrator', 'job_id': 'job_orchestrator'},
        },
        {'loop_runner_status': 'ok', 'action': 'imported_orchestration_notes', 'task_id': 'task-auto'},
        {'loop_runner_status': 'idle', 'action': 'none', 'reason': 'no_actionable_task'},
    ]
    runner_calls: list[str] = []
    trace_calls: list[str] = []
    trace_statuses = {
        'job_planner': ['running', 'completed'],
        'job_orchestrator': ['running', 'completed'],
    }

    def fake_loop_runner_once(_context, _command, _services):
        runner_calls.append('once')
        return loop_payloads.pop(0)

    def fake_trace(_context, trace_command):
        job_id = trace_command.target
        trace_calls.append(job_id)
        statuses = trace_statuses[job_id]
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return {'job': {'job_id': job_id, 'status': status}}

    monkeypatch.setattr(loop_runner_module, 'loop_runner_once', fake_loop_runner_once)

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(trace_target=fake_trace, sleep=lambda _seconds: None),
    )

    assert payload['action'] == 'auto_runner_finished'
    assert payload['final_action'] == 'none'
    assert runner_calls == ['once', 'once', 'once', 'once']
    assert trace_calls == ['job_planner', 'job_planner', 'job_orchestrator', 'job_orchestrator']
    assert [step['action'] for step in payload['steps']] == [
        'imported_planner_task_authority',
        'activated_orchestrator',
        'imported_orchestration_notes',
        'none',
    ]
    assert not (project_root / '.ccb' / 'runtime' / 'loops' / 'auto-runner.lock').exists()


def test_loop_runner_auto_failed_seed_job_does_not_consume_stale_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='stale-ready-task')
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner_failed',
        max_steps=4,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_trace(_context, trace_command):
        assert trace_command.target == 'job_planner_failed'
        return {
            'job': {
                'job_id': trace_command.target,
                'status': 'failed',
                'terminal_decision': {'reason': 'runtime_unavailable'},
            }
        }

    def forbidden_runner_once(*_args, **_kwargs):
        raise AssertionError('a failed seed job must not consume an older actionable task')

    monkeypatch.setattr(loop_runner_module, 'loop_runner_once', forbidden_runner_once)

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(trace_target=fake_trace, sleep=lambda _seconds: None),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'auto_runner_seed_job_failed'
    assert payload['wait_job_id'] == 'job_planner_failed'
    assert payload['wait_job_status'] == 'failed'
    assert payload['wait_job_reason'] == 'runtime_unavailable'
    assert payload['steps'] == []
    assert payload['next_activation'] == 'repair_or_resubmit_seed_job'


def test_loop_runner_auto_pending_later_frontdesk_handoff_does_not_starve_ready_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    activations = project_root / '.ccb' / 'runtime' / 'loops' / 'activations'
    _write_json(
        activations / 'act-frontdesk-first.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-first',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_first', 'status': 'submitted'},
        },
    )
    _write_json(
        activations / 'act-frontdesk-second.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-second',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_second', 'status': 'submitted'},
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_planner_first',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: First Frontdesk Task
Route: direct_execution
## Goal
Complete the first frontdesk task.
## Acceptance Criteria
- README change is verified.
## Interface Contracts
- None declared.
## Constraints And Non-Goals
- Change only README.md.
## Execution Decomposition Inputs
- Independently reviewable surfaces: README.md.
- Real predecessor dependencies: none.
Allowed paths:
- README.md
Verification:
- python -m pytest
```

**readiness.json**
```json
{"readiness":"ready","route":"direct_execution","blockers":[],"allowed_paths":["README.md"],"verification":["python -m pytest"]}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner_first',
        max_steps=2,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[str] = []
    trace_calls: list[str] = []

    def fake_trace(_context, trace_command):
        trace_calls.append(trace_command.target)
        return {'job': {'job_id': trace_command.target, 'status': 'completed'}}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command.target)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_first', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(trace_target=fake_trace, sleep=lambda _seconds: None, submit_ask=fake_submit_ask),
    )

    assert payload['action'] == 'auto_runner_step_limit_reached'
    assert [step['action'] for step in payload['steps']] == [
        'imported_planner_task_authority',
        'activated_orchestrator',
    ]
    assert submitted == ['orchestrator']
    assert trace_calls == ['job_planner_first', 'job_orchestrator_first']


def test_loop_runner_auto_waits_for_pending_frontdesk_activation_job_then_consumes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-frontdesk-second.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-second',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_second', 'status': 'submitted'},
        },
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        max_steps=2,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    trace_calls: list[str] = []

    def fake_trace(_context, trace_command):
        trace_calls.append(trace_command.target)
        if trace_command.target == 'job_planner_second':
            _write_completion_snapshot(
                project_root,
                job_id='job_planner_second',
                agent_name='planner',
                reply="""**task-packet.md**
```markdown
# Task: Second Frontdesk Task
Route: direct_execution
## Goal
Complete the second frontdesk task.
## Acceptance Criteria
- README change is verified.
## Interface Contracts
- None declared.
## Constraints And Non-Goals
- Change only README.md.
## Execution Decomposition Inputs
- Independently reviewable surfaces: README.md.
- Real predecessor dependencies: none.
Allowed paths:
- README.md
Verification:
- python -m pytest
```

**readiness.json**
```json
{"readiness":"ready","route":"direct_execution","blockers":[],"allowed_paths":["README.md"],"verification":["python -m pytest"]}
```
""",
            )
        return {'job': {'job_id': trace_command.target, 'status': 'completed'}}

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(trace_target=fake_trace, sleep=lambda _seconds: None, plan_task=plan_task),
    )

    assert payload['action'] == 'auto_runner_step_limit_reached'
    assert [step['action'] for step in payload['steps']] == [
        'role_output_pending',
        'imported_planner_task_authority',
    ]
    assert payload['steps'][0]['job_id'] == 'job_planner_second'
    assert trace_calls == ['job_planner_second']


def test_loop_runner_auto_imports_completed_retry_successor_for_failed_activation_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-frontdesk-retry.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-retry',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_failed', 'status': 'accepted'},
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_planner_failed',
        agent_name='planner',
        status='failed',
        reply='',
    )
    _write(
        project_root / '.ccb' / 'agents' / 'planner' / 'jobs.jsonl',
        json.dumps(
            {
                'schema_version': 2,
                'record_type': 'job_record',
                'job_id': 'job_planner_retry',
                'agent_name': 'planner',
                'provider_options': {'retry_source_job_id': 'job_planner_failed'},
                'status': 'completed',
            },
            sort_keys=True,
        )
        + '\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_planner_retry',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Retry Successor Task
Route: direct_execution
## Goal
Complete the retried frontdesk task.
## Acceptance Criteria
- README change is verified.
## Interface Contracts
- None declared.
## Constraints And Non-Goals
- Change only README.md.
## Execution Decomposition Inputs
- Independently reviewable surfaces: README.md.
- Real predecessor dependencies: none.
Allowed paths:
- README.md
Verification:
- python -m pytest
```

**readiness.json**
```json
{"readiness":"ready","route":"direct_execution","blockers":[],"allowed_paths":["README.md"],"verification":["python -m pytest"]}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner_failed',
        max_steps=2,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    trace_calls: list[str] = []
    submitted: list[str] = []

    def fake_trace(_context, trace_command):
        trace_calls.append(trace_command.target)
        return {'job': {'job_id': trace_command.target, 'status': 'completed'}}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command.target)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_retry', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(
            trace_target=fake_trace,
            sleep=lambda _seconds: None,
            submit_ask=fake_submit_ask,
            plan_task=plan_task,
        ),
    )

    assert payload['action'] == 'auto_runner_step_limit_reached'
    assert [step['action'] for step in payload['steps']] == [
        'imported_planner_task_authority',
        'activated_orchestrator',
    ]
    assert payload['steps'][0]['job_id'] == 'job_planner_retry'
    assert payload['steps'][0]['retry_source_job_id'] == 'job_planner_failed'
    assert submitted == ['orchestrator']
    assert trace_calls == ['job_planner_failed', 'job_orchestrator_retry']
    import_records = [
        json.loads(line)
        for line in (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert any(
        record.get('status') == 'ok'
        and (record.get('source_job') or {}).get('job_id') == 'job_planner_retry'
        and (record.get('source_job') or {}).get('retry_source_job_id') == 'job_planner_failed'
        for record in import_records
    )


def test_loop_runner_auto_stops_after_non_pass_direct_round_before_next_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        max_steps=3,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    calls = []

    def fake_once(_context, _command, _services):
        calls.append('once')
        if len(calls) > 1:
            raise AssertionError('auto-runner must stop before activating the next task after a blocked round')
        return {
            'schema_version': 1,
            'record_type': 'ccb_loop_runner_once',
            'loop_runner_status': 'ok',
            'action': 'ran_one_round',
            'task_id': 'phase6b-l1-doc-direct-execution',
            'task_status': 'blocked',
            'round_result': 'blocked',
            'round_result_source': 'round_reviewer_reply',
        }

    monkeypatch.setattr(loop_runner_module, 'loop_runner_once', fake_once)

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(sleep=lambda _seconds: None),
    )

    assert calls == ['once']
    assert payload['action'] == 'auto_runner_finished'
    assert payload['steps'] == [
        {
            'loop_runner_status': 'ok',
            'action': 'ran_one_round',
            'task_id': 'phase6b-l1-doc-direct-execution',
            'task_status': 'blocked',
            'round_result': 'blocked',
            'round_result_source': 'round_reviewer_reply',
        }
    ]
    assert payload['final_action'] == 'ran_one_round'


def test_loop_runner_auto_skips_settled_blocked_frontdesk_activation_for_wait_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    activations = project_root / '.ccb' / 'runtime' / 'loops' / 'activations'
    _write_json(
        activations / 'act-frontdesk-a-failed.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-a-failed',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_failed', 'status': 'accepted'},
        },
    )
    _write_json(
        activations / 'act-frontdesk-b-success.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-frontdesk-b-success',
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'ask': {'target': 'planner', 'job_id': 'job_planner_success', 'status': 'accepted'},
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_planner_failed',
        agent_name='planner',
        status='failed',
        reply='provider failed before producing planner artifacts',
    )
    _write(
        project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl',
        json.dumps(
            {
                'schema_version': 1,
                'record_type': 'ccb_loop_role_output_import',
                'imported_at': '2026-07-07T00:00:00Z',
                'action': 'role_output_import_blocked',
                'status': 'blocked',
                'job_id': 'job_planner_failed',
                'agent_name': 'planner',
                'reason': 'terminal_job_not_completed',
                'evidence': {'terminal_status': 'failed'},
            },
            sort_keys=True,
        )
        + '\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_planner_success',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Successful Frontdesk Task
Route: direct_execution
## Goal
Complete the successful frontdesk task.
## Acceptance Criteria
- README change is verified.
## Interface Contracts
- None declared.
## Constraints And Non-Goals
- Change only README.md.
## Execution Decomposition Inputs
- Independently reviewable surfaces: README.md.
- Real predecessor dependencies: none.
Allowed paths:
- README.md
Verification:
- python -m pytest
```

**readiness.json**
```json
{"readiness":"ready","route":"direct_execution","blockers":[],"allowed_paths":["README.md"],"verification":["python -m pytest"]}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        wait_job_id='job_planner_success',
        max_steps=2,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[str] = []
    trace_calls: list[str] = []

    def fake_trace(_context, trace_command):
        trace_calls.append(trace_command.target)
        return {'job': {'job_id': trace_command.target, 'status': 'completed'}}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command.target)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_success', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(
            trace_target=fake_trace,
            sleep=lambda _seconds: None,
            submit_ask=fake_submit_ask,
            plan_task=plan_task,
        ),
    )

    assert payload['action'] == 'auto_runner_step_limit_reached'
    assert [step['action'] for step in payload['steps']] == [
        'imported_planner_task_authority',
        'activated_orchestrator',
    ]
    assert payload['steps'][0]['job_id'] == 'job_planner_success'
    assert submitted == ['orchestrator']
    assert trace_calls == ['job_planner_success', 'job_orchestrator_success']
    import_records = [
        json.loads(line)
        for line in (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    failed_records = [record for record in import_records if record.get('job_id') == 'job_planner_failed']
    assert len(failed_records) == 1
    assert failed_records[0]['status'] == 'blocked'
    assert any(
        record.get('status') == 'ok'
        and (record.get('source_job') or {}).get('job_id') == 'job_planner_success'
        for record in import_records
    )


def test_loop_runner_auto_recovers_dead_pid_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    lock_path = project_root / '.ccb' / 'runtime' / 'loops' / 'auto-runner.lock'
    _write(lock_path, '99999999\n')
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        max_steps=1,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_loop_runner_once(_context, _command, _services):
        return {'loop_runner_status': 'idle', 'action': 'none', 'reason': 'no_actionable_task'}

    monkeypatch.setattr(loop_runner_module, 'loop_runner_once', fake_loop_runner_once)

    payload = loop_runner_auto(context, command, services=SimpleNamespace())

    assert payload['action'] == 'auto_runner_finished'
    assert payload['final_action'] == 'none'
    assert not lock_path.exists()


def test_loop_runner_once_explicit_project_from_outer_cwd_submits_orchestrator_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    outer_project = tmp_path / 'outer-ccb-project'
    _write(outer_project / '.ccb' / 'ccb.config', 'cmd; outer:codex\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-runner',
        task_packet_text='Task Packet:\n' + ('完整语义' * 1200),
        execution_contract_text='Execution Contract:\n' + ('验收约束' * 1200),
    )
    command = ParsedLoopRunnerCommand(project=str(project_root), once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=outer_project, bootstrap_if_missing=False)
    captured: dict[str, object] = {}

    class _FakeClient:
        def submit(self, envelope) -> dict:
            if len(envelope.body.encode('utf-8')) > 4096 and envelope.body_artifact is None:
                raise ValueError('ask body exceeds 4 KiB and must be submitted with a CCB body artifact')
            captured['project_id'] = envelope.project_id
            captured['to_agent'] = envelope.to_agent
            captured['from_actor'] = envelope.from_actor
            captured['task_id'] = envelope.task_id
            captured['route_options'] = envelope.route_options
            captured['body'] = envelope.body
            captured['body_artifact'] = envelope.body_artifact
            return {
                'job_id': 'job_orchestrator',
                'agent_name': envelope.to_agent,
                'target_name': envelope.to_agent,
                'status': 'submitted',
            }

    monkeypatch.setattr(
        ask_service,
        'invoke_mounted_daemon',
        lambda context, allow_restart_stale, request_fn: request_fn(_FakeClient()),
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(submit_ask=ask_service.submit_ask))

    assert context.project.project_root == project_root.resolve()
    assert context.project.source == 'explicit'
    assert context.cwd == outer_project
    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_orchestrator'
    assert payload['ask'] == {'target': 'orchestrator', 'job_id': 'job_orchestrator', 'status': 'submitted'}
    assert captured['project_id'] == context.project.project_id
    assert captured['to_agent'] == 'orchestrator'
    assert captured['from_actor'] == 'system'
    assert captured['route_options'] == {}
    assert str(captured['task_id']).startswith('act-')
    artifact = captured['body_artifact']
    assert isinstance(artifact, dict)
    artifact_path = Path(str(artifact['path']))
    assert artifact['kind'] == 'ask-request'
    assert artifact_path.name.startswith('system-to-orchestrator-')
    assert artifact_path.is_relative_to(project_root / '.ccb' / 'ccbd' / 'artifacts' / 'text' / 'ask-request')
    assert artifact_path.stat().st_mode & 0o777 == 0o600
    message = artifact_path.read_text(encoding='utf-8')
    assert len(message.encode('utf-8')) == artifact['bytes']
    assert hashlib.sha256(message.encode('utf-8')).hexdigest() == artifact['sha256']
    assert 'Required reply-only output:' in message
    assert 'ccb plan task-artifact' not in message
    assert 'plan task-artifact' not in message


@pytest.mark.parametrize(
    'failure',
    [RuntimeError('connection lost after submit boundary'), ValueError('request validation failed')],
)
def test_loop_runner_orchestrator_submit_failure_reuses_activation_identity_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='task-runner',
        task_packet_text='Task Packet:\n' + ('完整语义' * 1200),
        execution_contract_text='Execution Contract:\n' + ('验收约束' * 1200),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[object] = []

    class _FailingClient:
        def submit(self, envelope) -> dict:
            submitted.append(envelope)
            assert isinstance(envelope.body_artifact, dict)
            raise failure

    monkeypatch.setattr(
        ask_service,
        'invoke_mounted_daemon',
        lambda context, allow_restart_stale, request_fn: request_fn(_FailingClient()),
    )

    with pytest.raises(type(failure), match=str(failure)):
        loop_runner_once(context, command, services=SimpleNamespace(submit_ask=ask_service.submit_ask))

    activation_paths = sorted((project_root / '.ccb' / 'runtime' / 'loops' / 'activations').glob('act-*.json'))
    assert len(activation_paths) == 1
    activation = json.loads(activation_paths[0].read_text(encoding='utf-8'))
    assert activation['submission']['status'] == 'unknown'
    assert activation['submission']['error'] == f'{type(failure).__name__}: {failure}'
    assert len(submitted) == 1

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('unknown submission must not be duplicated')
            )
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'activation_submission_unknown'
    assert payload['reason'] == 'activation ask has no receipt authority; submission outcome requires manual audit'
    assert payload['activation_id'] == activation['activation_id']
    assert len(list((project_root / '.ccb' / 'runtime' / 'loops' / 'activations').glob('act-*.json'))) == 1
    assert len(submitted) == 1


@pytest.mark.parametrize('interrupt', [KeyboardInterrupt('stop'), SystemExit('stop')])
def test_loop_runner_orchestrator_interrupt_preserves_prepared_authority_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: BaseException,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-runner')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[object] = []

    def interrupted_submit(_context, ask_command):
        submitted.append(ask_command)
        raise interrupt

    with pytest.raises(type(interrupt), match='stop'):
        loop_runner_once(context, command, services=SimpleNamespace(submit_ask=interrupted_submit))

    activation_paths = sorted((project_root / '.ccb' / 'runtime' / 'loops' / 'activations').glob('act-*.json'))
    assert len(activation_paths) == 1
    activation = json.loads(activation_paths[0].read_text(encoding='utf-8'))
    assert activation['submission'] == {'status': 'prepared', 'target': 'orchestrator'}

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('prepared submission must not be duplicated')
            )
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'activation_submission_unknown'
    assert payload['reason'] == 'activation ask has no receipt authority; submission outcome requires manual audit'
    assert payload['submission'] == {'status': 'prepared', 'target': 'orchestrator'}
    assert len(submitted) == 1


def test_loop_runner_once_selects_ready_task_despite_committed_legacy_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-runner')
    proposal_path = project_root / 'workflow-dispatch.json'
    _write_json(proposal_path, _workflow_dispatch_proposal())

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'dispatch1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'dispatch1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'

    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    def forbidden_topology_task(*_args, **_kwargs):
        raise AssertionError('runner mainline must not consult topology dispatch task discovery')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('runner mainline must not execute topology dispatch')

    def fake_submit_ask(_context, ask_command):
        seen['target'] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_topology', 'agent_name': 'orchestrator', 'status': 'submitted'},),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('new ready_for_orchestration task must not run the fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            find_topology_dispatch_task=forbidden_topology_task,
            topology_dispatch=forbidden_topology_dispatch,
            loop_run_once=forbidden_loop_run_once,
            submit_ask=fake_submit_ask,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'activation_topology_not_ready'
    assert payload['task_id'] == 'task-runner'
    assert 'agent profile ccb_orchestrator exceeds max_instances=1' in payload['reason']
    assert seen == {}
    dispatch_path = project_root / '.ccb' / 'runtime' / 'loops' / 'wf1' / 'topology_dispatch.json'
    assert not dispatch_path.exists()


def test_loop_runner_once_pauses_bound_topology_loop_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-topology')
    proposal_path = project_root / 'workflow-dispatch.json'
    _write_json(proposal_path, _workflow_dispatch_proposal())

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'dispatch1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'dispatch1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'

    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    plan_task(context, SimpleNamespace(action='task-bind-loop', task_id='task-topology', loop_id='wf1'))

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('bound topology loop must not submit topology dispatch asks')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('bound topology loop must not fall back to fixed runner')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('topology dispatch is legacy/disabled for loop runner mainline')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_not_ready'
    assert 'Phase 4 ask-first execution can only start from an unbound direct_execution task' in payload['reason']
    assert payload['loop_id'] == 'wf1'
    assert payload['task_id'] == 'task-topology'
    assert payload['task_status'] == 'running'
    assert payload['next_owner'] == 'orchestrator'
    assert payload['next_activation'] == 'phase4_ask_first_runner_required'
    dispatch_path = project_root / '.ccb' / 'runtime' / 'loops' / 'wf1' / 'topology_dispatch.json'
    assert not dispatch_path.exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-topology'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == 'wf1'
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_bound_loop_without_ask_resumes_on_existing_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    plan_task(context, SimpleNamespace(action='task-bind-loop', task_id='task-direct', loop_id='wf-resume'))
    submitted: list[object] = []
    plan_actions: list[tuple[str, str | None]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id='sub_1',
            jobs=({'job_id': 'job_1', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert job_id == 'job_1'
        assert timeout == 11.0
        assert emit_output is False
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    def recording_plan_task(_context, plan_command):
        plan_actions.append((str(plan_command.action), getattr(plan_command, 'loop_id', None)))
        if plan_command.action == 'task-bind-loop':
            raise AssertionError('bound direct_execution resume must reuse the current_loop without rebinding')
        return plan_task(_context, plan_command)

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('bound direct_execution task must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('bound direct_execution task must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=recording_plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['loop_id'] == 'wf-resume'
    assert payload['pending']['purpose'] == 'worker'
    assert payload['pending']['job_id'] == 'job_1'
    assert len(submitted) == 1
    assert submitted[0].target.startswith('loop-wf-resume-coder-')
    assert not any(action == 'task-bind-loop' for action, _loop_id in plan_actions)
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / 'wf-resume'
    ask_lines = (loop_dir / 'asks.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(ask_lines) == 1
    ask_record = json.loads(ask_lines[0])
    assert ask_record['record_type'] == 'ccb_loop_ask_first_ask'
    assert ask_record['loop_id'] == 'wf-resume'
    assert ask_record['purpose'] == 'worker'
    assert ask_record['job_id'] == 'job_1'
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert state['status'] == 'executing'
    assert state['legacy_status'] == 'pending'
    assert state['task_id'] == 'task-direct'
    assert state['loop_id'] == 'wf-resume'
    assert state['stage'] == 'worker_ask'
    assert state['purpose'] == 'worker'
    assert state['job_id'] == 'job_1'
    assert state['workgroup_state_schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert state['orchestration_bundle']['node_ids'] == ['node-001']
    assert set(state['current_artifacts']['nodes']) == {'node-001'}
    assert state['current_artifacts']['nodes']['node-001']['worker']['job_id'] == 'job_1'
    assert not (loop_dir / 'round.json').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == 'wf-resume'
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_crash_during_submit_pauses_submission_unknown_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    first_submissions: list[object] = []

    def crashing_submit(_context, ask_command):
        first_submissions.append(ask_command)
        raise SystemExit('process died during daemon submission')

    with pytest.raises(SystemExit):
        loop_runner_once(
            context,
            command,
            services=SimpleNamespace(
                submit_ask=crashing_submit,
                watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError('crashed submit must not watch')
                ),
                plan_task=plan_task,
            ),
        )

    assert len(first_submissions) == 1
    loop_id = first_submissions[0].target.split('-')[1]
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / loop_id
    assert not (loop_dir / 'asks.jsonl').exists()
    intent_path = loop_dir / 'ask_first_submission_intents.jsonl'
    prepared = [json.loads(line) for line in intent_path.read_text(encoding='utf-8').splitlines()]
    assert [(item['bundle_revision'], item['node_id'], item['purpose'], item['attempt'], item['status']) for item in prepared] == [
        (1, 'node-001', 'worker', 1, 'prepared')
    ]
    resume_submissions: list[object] = []

    def forbidden_duplicate_submit(_context, ask_command):
        resume_submissions.append(ask_command)
        raise AssertionError('submission_unknown resume must not submit a duplicate worker ask')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_duplicate_submit,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('submission_unknown without job_id must not watch')
            ),
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['loop_id'] == loop_id
    assert payload['pending']['source'] == 'ask_submission_unknown'
    assert payload['pending']['purpose'] == 'worker'
    assert payload['pending']['watch_observation'] == 'submission_unknown'
    assert payload['pending']['job_id'] is None
    assert resume_submissions == []
    assert 'release' not in payload
    assert 'import' not in payload
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['pending']['source'] == 'ask_submission_unknown'
    assert state['pending']['watch_observation'] == 'submission_unknown'
    intents = [json.loads(line) for line in intent_path.read_text(encoding='utf-8').splitlines()]
    assert [item['status'] for item in intents] == ['prepared', 'unknown']
    assert all(
        (item['bundle_revision'], item['node_id'], item['purpose'], item['attempt'])
        == (1, 'node-001', 'worker', 1)
        for item in intents
    )
    assert not (loop_dir / 'round.json').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == loop_id
    assert 'round_summary' not in shown['task']['artifacts']


def test_ask_first_submission_identity_is_serialized_across_concurrent_once_callers(
    tmp_path: Path,
) -> None:
    loop_dir = tmp_path / 'runtime' / 'loops' / 'lp-concurrent'
    submit_started = threading.Event()
    release_submit = threading.Event()
    submissions: list[object] = []

    def fake_clear(_context, clear_command):
        return {
            'status': 'ok',
            'results': [{'agent': clear_command.agent_names[0], 'status': 'cleared'}],
        }

    def fake_submit(_context, ask_command):
        submissions.append(ask_command)
        submit_started.set()
        assert release_submit.wait(timeout=2.0)
        return AskSummary(
            project_id='project-concurrent',
            submission_id='sub-concurrent',
            jobs=({'job_id': 'job-concurrent', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name='loop-lp-concurrent-coder-1',
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=0,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    deps = SimpleNamespace(
        clear_agent_context=fake_clear,
        submit_ask=fake_submit,
        watch_ask_job=fake_watch,
        load_persisted_terminal_watch_payload=lambda *_args, **_kwargs: None,
    )
    call_args = {
        'loop_dir': loop_dir,
        'loop_id': 'lp-concurrent',
        'target': 'loop-lp-concurrent-coder-1',
        'sender': 'ccb_orchestrator',
        'purpose': 'worker',
        'bundle_revision': 1,
        'node_id': 'node-001',
        'attempt': 1,
        'task_id': 'lp-concurrent-worker',
        'message': 'execute node-001',
        'timeout': None,
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(loop_ask_first_module._submit_and_watch, None, deps, **call_args)
        assert submit_started.wait(timeout=2.0)
        second = executor.submit(loop_ask_first_module._submit_and_watch, None, deps, **call_args)
        release_submit.set()
        first_result = first.result(timeout=3.0)
        second_result = second.result(timeout=3.0)

    assert len(submissions) == 1
    assert first_result['job_id'] == 'job-concurrent'
    assert second_result['job_id'] == 'job-concurrent'
    assert second_result['watch_source'] == 'persisted_terminal'
    intents = [
        json.loads(line)
        for line in (loop_dir / 'ask_first_submission_intents.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert [item['status'] for item in intents] == ['prepared', 'accepted']
    asks = [json.loads(line) for line in (loop_dir / 'asks.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(asks) == 1
    assert asks[0]['job_id'] == 'job-concurrent'


def test_ask_first_immaculate_clear_failure_blocks_before_intent_or_provider_submit(
    tmp_path: Path,
) -> None:
    loop_dir = tmp_path / 'runtime' / 'loops' / 'lp-clear-failed'
    submissions: list[object] = []

    def failed_clear(_context, _clear_command):
        return {
            'status': 'partial',
            'results': [
                {
                    'agent': 'loop-lp-clear-failed-coder-1',
                    'status': 'failed',
                    'reason': 'provider clear command was not acknowledged',
                }
            ],
        }

    def forbidden_submit(_context, ask_command):
        submissions.append(ask_command)
        raise AssertionError('provider ask must not run without proven immaculate freshness')

    deps = SimpleNamespace(
        clear_agent_context=failed_clear,
        submit_ask=forbidden_submit,
        watch_ask_job=lambda *_args, **_kwargs: None,
        load_persisted_terminal_watch_payload=lambda *_args, **_kwargs: None,
    )

    with pytest.raises(
        loop_ask_first_module._ImmaculateActivationError,
        match='immaculate activation freshness is not proven',
    ):
        loop_ask_first_module._submit_and_watch(
            None,
            deps,
            loop_dir=loop_dir,
            loop_id='lp-clear-failed',
            target='loop-lp-clear-failed-coder-1',
            sender='ccb_orchestrator',
            purpose='worker',
            bundle_revision=1,
            node_id='node-001',
            attempt=1,
            task_id='lp-clear-failed-worker',
            message='execute node-001',
            timeout=None,
        )

    assert submissions == []
    assert not (loop_dir / 'ask_first_submission_intents.jsonl').exists()


@pytest.mark.parametrize(
    ('purpose', 'target', 'node_id'),
    (
        ('worker', 'loop-lp-fresh-worker', 'node-001'),
        ('ccb_round_reviewer', 'loop-lp-fresh-round', 'round'),
    ),
)
def test_public_submit_once_structures_immaculate_freshness_failure_without_ask(
    tmp_path: Path,
    purpose: str,
    target: str,
    node_id: str,
) -> None:
    loop_dir = tmp_path / 'runtime' / 'loops' / 'lp-freshness'
    submissions = []

    def failed_clear(_context, clear_command):
        return {
            'status': 'partial',
            'results': [
                {
                    'agent': clear_command.agent_names[0],
                    'status': 'failed',
                    'reason': 'freshness unavailable',
                }
            ],
        }

    def forbidden_submit(_context, command):
        submissions.append(command)
        raise AssertionError('freshness failure must block before ask')

    result = loop_ask_first_module.submit_or_recover_ask_once(
        None,
        loop_dir=loop_dir,
        loop_id='lp-freshness',
        target=target,
        sender='system',
        purpose=purpose,
        bundle_revision=1,
        node_id=node_id,
        attempt=1,
        task_id=f'lp-freshness-{purpose}',
        message='bounded activation',
        services=SimpleNamespace(
            clear_agent_context=failed_clear,
            submit_ask=forbidden_submit,
        ),
    )

    assert result['terminal'] is True
    assert result['status'] == 'failed'
    assert result['failure_source'] == 'immaculate_activation_failed'
    assert result['failure_stage'] == f'{purpose}_ask'
    assert result['freshness']['status'] == 'failed'
    assert result['job_id'] is None
    assert submissions == []
    assert not (loop_dir / 'ask_first_submission_intents.jsonl').exists()
    freshness_events = [
        json.loads(line)
        for line in (loop_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert freshness_events[-1]['kind'] == 'immaculate_activation_freshness'
    assert freshness_events[-1]['status'] == 'failed'


def test_loop_runner_direct_execution_crash_after_submit_before_ask_append_resumes_job_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'append_crash_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/append_crash_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    first_submissions: list[object] = []
    original_append_ask = loop_ask_first_module._append_ask

    def fake_submit_ask(_context, ask_command):
        first_submissions.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id='sub_1',
            jobs=({'job_id': 'job_1', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def crash_before_ask_log(*_args, **_kwargs):
        raise SystemExit('process died after daemon accepted job before local ask append')

    monkeypatch.setattr(loop_ask_first_module, '_append_ask', crash_before_ask_log)
    with pytest.raises(SystemExit):
        loop_runner_once(
            context,
            command,
            services=SimpleNamespace(
                submit_ask=fake_submit_ask,
                watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError('crashed append must not watch')
                ),
                plan_task=plan_task,
            ),
        )

    assert len(first_submissions) == 1
    worker_target = first_submissions[0].target
    loop_id = worker_target.split('-')[1]
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / loop_id
    assert not (loop_dir / 'asks.jsonl').exists()
    intent_path = loop_dir / 'ask_first_submission_intents.jsonl'
    accepted = [json.loads(line) for line in intent_path.read_text(encoding='utf-8').splitlines()]
    assert [item['status'] for item in accepted] == ['prepared', 'accepted']
    assert all(
        (item['bundle_revision'], item['node_id'], item['purpose'], item['attempt'])
        == (1, 'node-001', 'worker', 1)
        for item in accepted
    )
    assert accepted[-1]['job_id'] == 'job_1'
    monkeypatch.setattr(loop_ask_first_module, '_append_ask', original_append_ask)
    worker_workspace = _seed_copy_workspace_binding(context, project_root, worker_target)
    _write(worker_workspace / 'lab_docs' / 'append_crash_note.md', 'status: worker-recovered\n')
    resume_submissions: list[object] = []

    def resume_submit_ask(_context, ask_command):
        if ask_command.target == worker_target:
            raise AssertionError('resume must not submit a duplicate worker ask after accepted daemon job')
        resume_submissions.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id='sub_2',
            jobs=({'job_id': 'job_2', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert cursor == 0
        if job_id == 'job_1':
            return _persisted_terminal_payload('job_1', worker_target, reply='worker completed after append crash')
        return None

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=resume_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('resume after persisted terminal must advance one stage without live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['loop_id'] == loop_id
    assert payload['pending']['purpose'] == 'reviewer'
    assert payload['pending']['job_id'] == 'job_2'
    assert len(resume_submissions) == 1
    assert resume_submissions[0].target.startswith(f'loop-{loop_id}-code_reviewer-')
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['current_artifacts']['worker']['job_id'] == 'job_1'
    assert state['current_artifacts']['worker']['watch_source'] == 'persisted_terminal'
    assert state['pending']['purpose'] == 'reviewer'
    assert state['pending']['job_id'] == 'job_2'
    intents = [json.loads(line) for line in intent_path.read_text(encoding='utf-8').splitlines()]
    worker_intents = [item for item in intents if item['purpose'] == 'worker']
    reviewer_intents = [item for item in intents if item['purpose'] == 'reviewer']
    assert [item['status'] for item in worker_intents] == ['prepared', 'accepted', 'terminal', 'consumed']
    assert all(
        (item['bundle_revision'], item['node_id'], item['attempt']) == (1, 'node-001', 1)
        for item in worker_intents
    )
    assert [item['status'] for item in reviewer_intents] == ['prepared', 'accepted']
    assert not (loop_dir / 'round.json').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == loop_id
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_route_runs_ask_first_round_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'direct_execution_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/direct_execution_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    cleared_targets: list[str] = []

    def fake_clear_agent_context(_context, clear_command):
        names = list(clear_command.agent_names)
        cleared_targets.extend(names)
        return {
            'status': 'ok',
            'results': [
                {'agent': name, 'status': 'cleared', 'pane_id': f'%{len(cleared_targets)}', 'command': '/clear'}
                for name in names
            ],
        }

    def fake_submit_ask(_context, ask_command):
        next_index = len(submitted) + 1
        if next_index == 2 and ask_command.callback:
            raise RuntimeError('ask --chain requires an active parent job for the sender')
        if next_index == 2 and ask_command.sender != 'system':
            raise RuntimeError('plain ask from an active CCB task requires --chain')
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'direct_execution_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            clear_agent_context=fake_clear_agent_context,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'ran_one_round'
    assert payload['execution_mode'] == 'ask_first_direct_execution'
    assert payload['dispatch_source'] == 'ask_first_mount_topology'
    assert payload['task_id'] == 'task-direct'
    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_reply'
    assert payload['task_status'] == 'done'
    assert payload['next_activation'] == 'stop'
    assert payload['orchestration_bundle']['node_count'] == 1
    assert payload['orchestration_bundle']['node_ids'] == ['node-001']
    assert payload['release']['released_count'] == 3
    assert payload['release']['retained_count'] == 0
    assert payload['topology']['status'] == 'ready'
    assert (project_root / 'lab_docs' / 'direct_execution_note.md').read_text(encoding='utf-8') == 'status: reviewed\n'
    targets = [command.target for command in submitted]
    assert len(targets) == 3
    assert targets[0].startswith(f'loop-{payload["loop_id"]}-coder-')
    assert targets[1].startswith(f'loop-{payload["loop_id"]}-code_reviewer-')
    assert targets[2] == 'ccb_round_reviewer'
    assert cleared_targets == targets
    assert all(command.sender == 'system' for command in submitted)
    assert all(command.callback is False for command in submitted)
    assert all(command.silence is False for command in submitted)
    assert 'task_detailer' not in targets
    worker_message = submitted[0].message
    reviewer_message = submitted[1].message
    assert 'task_packet:' in worker_message
    assert 'execution_contract:' in worker_message
    assert 'Node: node-001' in worker_message
    assert 'node_work_packet:' in worker_message
    assert 'Canonical node work packet:' in worker_message
    assert 'Task Packet:\ntask packet text' in worker_message
    assert 'Execution Contract:\nexecution contract text' in worker_message
    assert 'After completing the required verification, stop tool use and send one final answer.' in worker_message
    assert 'Do not run optional final diff/status commands unless the execution contract explicitly requires them.' in worker_message
    assert 'The next assistant response after the final required verification command must be the final answer, not a progress update.' in worker_message
    assert 'Final answer must include: status: done|blocked|needs_rework' in worker_message
    assert 'Final answer must include: changed_files: <paths or none>' in worker_message
    assert 'Final answer must include: verification: <commands run and result>' in worker_message
    assert 'Do not leave the job at a progress update such as checking final diff or preparing summary.' in worker_message
    assert 'explicitly check execution_contract' in reviewer_message
    assert 'Node: node-001' in reviewer_message
    assert 'Canonical node work packet:' in reviewer_message
    assert 'reject hidden fallback, scope shrink, and fake success' in reviewer_message
    round_reviewer_message = submitted[2].message
    assert round_reviewer_message.startswith('FINAL ANSWER FORMAT - parser enforced:\n')
    assert 'Do not describe what you are about to do.' in round_reviewer_message
    assert 'Do not run tests, tools, shell commands, or verification steps' in round_reviewer_message
    assert 'Do not write a preamble such as "I have reviewed the evidence".' in round_reviewer_message
    assert 'Do not write a test-running preamble such as "Now let me run the tests".' in round_reviewer_message
    assert 'The first non-empty line MUST be exactly one standalone machine field:' in round_reviewer_message
    assert 'round result: <pass|partial|replan_required|blocked>' in round_reviewer_message
    assert 'Do not write analysis, headings, greetings, or any other preamble before that line.' in round_reviewer_message
    assert 'Do not wrap the machine line in Markdown fences, bullets, quotes, or backticks.' in round_reviewer_message
    assert 'If the first non-empty line is not this field, the runner must block the round.' in round_reviewer_message
    assert 'A later `round result: pass` is ignored by the runner and blocks the round.' in round_reviewer_message
    assert 'validate final result against project-root evidence, not isolated worker workspace evidence' in round_reviewer_message
    assert 'Supplied round evidence artifacts:' in round_reviewer_message
    assert 'Worker reply content:' in round_reviewer_message
    assert 'Reviewer reply content:' in round_reviewer_message
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert round_json['workgroup_state_schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert round_json['orchestration_bundle']['node_count'] == 1
    assert set(round_json['workgroups']) == {'node-001'}
    assert set(round_json['nodes']) == {'node-001'}
    assert round_json['nodes']['node-001']['status'] == 'integrated'
    assert round_json['workgroups']['node-001']['worker_agent'].startswith(f'loop-{payload["loop_id"]}-coder-')
    assert round_json['workgroups']['node-001']['reviewer_agent'].startswith(
        f'loop-{payload["loop_id"]}-code_reviewer-'
    )
    assert round_json['worker']['freshness']['status'] == 'cleared'
    assert round_json['reviewer']['freshness']['status'] == 'cleared'
    assert round_json['orchestrator'] == {}
    assert round_json['ccb_round_reviewer']['freshness']['status'] == 'cleared'
    assert f'reply from loop-{payload["loop_id"]}-coder-1' in round_reviewer_message
    assert f'reply from loop-{payload["loop_id"]}-code_reviewer-1' in round_reviewer_message
    normalized_proposal = json.loads(Path(str(payload['topology']['proposal_path'])).read_text(encoding='utf-8'))
    desired = json.loads(Path(str(payload['topology']['desired_path'])).read_text(encoding='utf-8'))
    observed = json.loads(Path(str(payload['topology']['observed_path'])).read_text(encoding='utf-8'))
    assert [agent['profile'] for agent in normalized_proposal['agents']] == [
        'coder',
        'code_reviewer',
        'ccb_round_reviewer',
    ]
    assert {
        agent['id']: agent['window_name']
        for agent in normalized_proposal['agents']
    } == {
        f'loop-{payload["loop_id"]}-coder-1': 'ccb-exec',
        f'loop-{payload["loop_id"]}-code_reviewer-1': 'ccb-exec',
        'ccb_round_reviewer': 'ccb-plan',
    }
    assert [window['name'] for window in normalized_proposal['windows']] == ['ccb-exec', 'ccb-plan']
    for persisted in (normalized_proposal, desired, observed):
        assert 'edges' not in persisted
        assert 'artifacts' not in persisted
        assert 'gates' not in persisted
    assert not (project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id'] / 'topology_dispatch.json').exists()
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['agents']['ccb_round_reviewer'] == 'ccb_round_reviewer'
    assert round_json['ccb_round_reviewer']['target'] == 'ccb_round_reviewer'


def test_loop_runner_ask_first_round_reviewer_malformed_reply_gets_bounded_correction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'direct_execution_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/direct_execution_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    task_ids_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        task_ids_by_job[job_id] = ask_command.task_id
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'direct_execution_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer' and str(task_ids_by_job[str(job_id)]).endswith('-round-reviewer'):
            reply = '根据提供的证据，执行合约审计通过。\n'
        elif target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'correction_of_job: job_3\n'
                'verification performed: corrected first-line machine result for same evidence\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'ran_one_round'
    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_correction_reply'
    assert payload['task_status'] == 'done'
    assert payload['release']['released_count'] == 3
    targets = [command.target for command in submitted]
    assert len(targets) == 4
    assert targets[2:] == ['ccb_round_reviewer', 'ccb_round_reviewer']
    assert submitted[3].task_id.endswith('-round-reviewer-correction')
    assert 'Previous reviewer job: job_3' in submitted[3].message
    assert 'Previous first non-empty line: 根据提供的证据，执行合约审计通过。' in submitted[3].message
    assert 'FINAL ANSWER FORMAT - parser enforced:' in submitted[3].message
    assert 'If that evidence is insufficient, the first line must be exactly: round result: blocked' in submitted[3].message
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['ccb_round_reviewer']['purpose'] == 'ccb_round_reviewer_correction'
    assert round_json['ccb_round_reviewer']['correction_source_job_id'] == 'job_3'
    loop_dir = Path(str(payload['round']['round_json_path'])).parent
    asks = [json.loads(line) for line in (loop_dir / 'asks.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [ask['purpose'] for ask in asks][-2:] == [
        'round_reviewer',
        'round_reviewer',
    ]
    assert [ask['attempt'] for ask in asks][-2:] == [1, 2]
    events = [json.loads(line) for line in (loop_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(event['kind'] == 'round_reviewer_result_correction_requested' for event in events)


@pytest.mark.parametrize('first_terminal_status', ['failed', 'incomplete'])
def test_loop_runner_ask_first_uses_completed_auto_retry_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_terminal_status: str,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'direct_execution_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/direct_execution_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    watched: list[str] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def _watch_batch(job_id: str, *, target: str, status: str, reply: str) -> WatchEventBatch:
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status=status,
            reply=reply,
            events=(),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        watched.append(str(job_id))
        target = targets_by_job.get(str(job_id), 'ccb_round_reviewer')
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'direct_execution_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer' and str(job_id) == 'job_3':
            retry_jobs = project_root / '.ccb' / 'agents' / 'ccb_round_reviewer' / 'jobs.jsonl'
            retry_jobs.parent.mkdir(parents=True, exist_ok=True)
            retry_jobs.write_text(
                json.dumps(
                    {
                        'record_type': 'job_record',
                        'job_id': 'job_3_retry',
                        'provider_options': {'retry_source_job_id': 'job_3'},
                        'created_at': '2026-07-07T07:29:11Z',
                    }
                )
                + '\n',
                encoding='utf-8',
            )
            targets_by_job['job_3_retry'] = 'ccb_round_reviewer'
            return _watch_batch(
                str(job_id),
                target=target,
                status=first_terminal_status,
                reply='delivery failed before retry',
            )
        if str(job_id) == 'job_3_retry':
            return _watch_batch(
                str(job_id),
                target='ccb_round_reviewer',
                status='completed',
                reply='round result: pass\nverification performed: retry successor evidence\n',
            )
        if target == 'ccb_round_reviewer':
            return _watch_batch(
                str(job_id),
                target=target,
                status='completed',
                reply=(
                    'round result: pass\n'
                    'verification performed: direct execution fake review\n'
                    'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                    'evidence refs: task_packet execution_contract\n'
                ),
            )
        return _watch_batch(str(job_id), target=target, status='completed', reply=f'reply from {target}')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'pass'
    assert watched == ['job_1', 'job_2', 'job_3', 'job_3_retry']
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['ccb_round_reviewer']['job_id'] == 'job_3_retry'
    assert round_json['ccb_round_reviewer']['status'] == 'completed'
    assert round_json['ccb_round_reviewer']['retry_source_job_id'] == 'job_3'
    assert round_json['ccb_round_reviewer']['retry_successor_job_id'] == 'job_3_retry'
    assert round_json['ccb_round_reviewer']['retry_lineage'] == ['job_3']


def test_loop_runner_ask_first_without_explicit_timeout_waits_for_natural_ask_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'direct_execution_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/direct_execution_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=None, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    observed_timeouts: list[float | None] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        observed_timeouts.append(timeout)
        assert timeout == 0.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'direct_execution_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'pass'
    assert observed_timeouts == [0.0, 0.0, 0.0]
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert 'round_checker' not in round_json['agents']
    assert 'round_checker' not in round_json
    assert round_json['legacy_aliases']['round_checker']['field'] == 'ccb_round_reviewer'
    assert round_json['topology']['release']['released_count'] == 3
    assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
    assert round_json['authority_update']['changed_files'] == ['lab_docs/direct_execution_note.md']
    assert round_json['authority_update']['allowed_change_paths'] == ['lab_docs/direct_execution_note.md']
    assert round_json['authority_update']['verified_project_root'] is True
    assert round_json['authority_import']['status'] == 'done'
    assert (Path(str(round_json['paths']['artifacts'])) / 'ccb_round_reviewer-reply.md').is_file()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'done'
    assert shown['task']['current_loop'] is None
    assert shown['task']['artifacts']['orchestration_notes']['orchestrator_route'] == 'direct_execution'
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'pass'
    assert shown['task']['artifacts']['round_summary']['actor'] == {
        'source': 'loop_runner',
        'actor': 'loop_runner',
        'job_id': 'job_1',
    }


def test_loop_runner_direct_execution_promotes_root_file_allowed_by_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text=(
            'execution contract text\n'
            'Allowed Change Paths:\n'
            '- slug_utils.py\n'
            '- tests/test_slug_utils.py\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'slug_utils.py', 'def slugify(value):\n    return value.lower()\n')
            _write(workspace / 'tests' / 'test_slug_utils.py', 'from slug_utils import slugify\n')
            _write(project_root / 'logs' / 'direct_execution.stderr', 'supervisor log after workspace seed\n')
            _write(project_root / 'evidence' / 'frontdesk.job_id', 'job_frontdesk\n')
            _write(project_root / 'command_log.tsv', 'timestamp\tcommand\n')
            _write(
                project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'task-direct' / 'README.md',
                'script-owned task status after workspace seed\n',
            )
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'pass'
    assert payload['task_status'] == 'done'
    assert (project_root / 'slug_utils.py').read_text(encoding='utf-8') == (
        'def slugify(value):\n    return value.lower()\n'
    )
    assert (project_root / 'tests' / 'test_slug_utils.py').read_text(encoding='utf-8') == (
        'from slug_utils import slugify\n'
    )
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['authority_update']['changed_files'] == ['slug_utils.py', 'tests/test_slug_utils.py']
    assert round_json['authority_update']['allowed_change_paths'] == ['slug_utils.py', 'tests/test_slug_utils.py']
    assert round_json['authority_update']['ignored_control_deleted_files'] == [
        'command_log.tsv',
        'evidence/frontdesk.job_id',
        'logs/direct_execution.stderr',
    ]
    assert 'failure' not in round_json


def test_loop_runner_direct_execution_uses_configured_orchestrator_agent_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_default_orchestrator_agent(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'direct_execution_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/direct_execution_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'direct_execution_note.md', 'status: reviewed\n')
        reply = 'round result: pass\n' if target == 'ccb_round_reviewer' else f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    targets = [command.target for command in submitted]
    assert targets == [
        f'loop-{payload["loop_id"]}-coder-1',
        f'loop-{payload["loop_id"]}-code_reviewer-1',
        'ccb_round_reviewer',
    ]
    assert 'orchestrator' not in targets
    assert payload['round_result'] == 'pass'
    assert payload['task_status'] == 'done'
    assert payload['release']['released_count'] == 2
    proposal = json.loads(Path(str(payload['topology']['proposal_path'])).read_text(encoding='utf-8'))
    assert [agent['profile'] for agent in proposal['agents']] == ['coder', 'code_reviewer']
    assert [window['name'] for window in proposal['windows']] == ['ccb-exec']
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['agents']['orchestrator'] == 'orchestrator'
    assert round_json['orchestrator'] == {}


def test_loop_runner_direct_execution_pending_worker_ask_pauses_without_import_or_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'resume_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/resume_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    def forbidden_release(*_args, **_kwargs):
        raise AssertionError('pending ask must not release topology')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            ask_first_release=forbidden_release,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['pending']['purpose'] == 'worker'
    assert payload['pending']['job_id'] == 'job_1'
    assert len(submitted) == 1
    assert submitted[0].target.startswith(f'loop-{payload["loop_id"]}-coder-')
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id']
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert state['status'] == 'executing'
    assert state['legacy_status'] == 'pending'
    assert state['task_id'] == 'task-direct'
    assert state['loop_id'] == payload['loop_id']
    assert state['stage'] == 'worker_ask'
    assert state['purpose'] == 'worker'
    assert state['target'] == submitted[0].target
    assert state['job_id'] == 'job_1'
    assert state['current_artifacts']['artifact_refs']['task_packet'].endswith('task_packet.md')
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == payload['loop_id']
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_resumes_persisted_worker_reply_and_submits_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'resume_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/resume_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    watch_calls: list[str] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        watch_calls.append(str(job_id))
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'

    def forbidden_watch_after_resume(*_args, **_kwargs):
        raise AssertionError('resume must inspect persisted terminal state without live watch')

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        assert cursor == 0
        workspace = _seed_copy_workspace_binding(context, project_root, submitted[0].target)
        _write(workspace / 'lab_docs' / 'resume_note.md', 'status: worker-complete\n')
        return {
            'job_id': 'job_1',
            'agent_name': submitted[0].target,
            'target_kind': 'job',
            'target_name': 'job_1',
            'provider': 'codex',
            'provider_instance': None,
            'cursor': 2,
            'generation': 1,
            'terminal': True,
            'status': 'completed',
            'reply': 'status: done\nworker evidence: persisted reply\n',
            'events': [],
        }

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=forbidden_watch_after_resume,
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert second['loop_runner_status'] == 'paused'
    assert second['action'] == 'ask_first_execution_pending'
    assert second['pending']['purpose'] == 'reviewer'
    assert second['pending']['job_id'] == 'job_2'
    assert watch_calls == ['job_1']
    assert len(submitted) == 2
    assert submitted[1].target.startswith(f'loop-{second["loop_id"]}-code_reviewer-')
    assert 'Worker job: job_1' in submitted[1].message
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / second['loop_id']
    worker_artifact = loop_dir / 'artifacts' / 'worker-reply.md'
    assert worker_artifact.read_text(encoding='utf-8') == 'status: done\nworker evidence: persisted reply\n'
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['schema'] == 'ccb.loop.workgroup_round_state.v1'
    assert state['status'] == 'executing'
    assert state['legacy_status'] == 'pending'
    assert state['purpose'] == 'reviewer'
    assert state['current_artifacts']['worker']['job_id'] == 'job_1'
    assert state['current_artifacts']['worker']['artifact'] == str(worker_artifact)
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == second['loop_id']
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_promotes_group_workspace_binding_before_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'group_resume_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/group_resume_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'
    worker_target = submitted[0].target
    workspace = _seed_group_workspace_binding(context, project_root, worker_target)
    _write(workspace / 'lab_docs' / 'group_resume_note.md', 'status: worker-complete\n')

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        assert cursor == 0
        return _persisted_terminal_payload('job_1', worker_target, reply='status: done\ngroup binding reply\n')

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('resume must inspect persisted terminal state without live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert second['loop_runner_status'] == 'paused'
    assert second['action'] == 'ask_first_execution_pending'
    assert second['pending']['purpose'] == 'reviewer'
    assert second['pending']['job_id'] == 'job_2'
    assert len(submitted) == 2
    assert submitted[1].target.startswith(f'loop-{second["loop_id"]}-code_reviewer-')
    assert (project_root / 'lab_docs' / 'group_resume_note.md').read_text(encoding='utf-8') == (
        'status: worker-complete\n'
    )
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / second['loop_id']
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    authority_update = state['current_artifacts']['authority_update']
    assert authority_update['source'] == 'isolated_workspace_changes_promoted'
    assert authority_update['workspace_binding'].endswith(
        '.ccb/workspaces/groups/worker_pool/.ccb-workspace.json'
    )


def test_loop_runner_direct_execution_git_workspace_ignores_late_control_files_before_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_code/calculator.py\n',
    )
    _write(
        project_root / 'supervisor_imports' / 'task-direct' / 'task_packet.md',
        'late script-owned task packet import\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'
    worker_target = submitted[0].target
    workspace = _seed_group_git_workspace_binding(
        context,
        project_root,
        worker_target,
        tracked_paths=('lab_code/calculator.py',),
    )
    _write(workspace / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a + b\n')

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        assert cursor == 0
        return _persisted_terminal_payload('job_1', worker_target, reply='status: done\ntracked git worktree\n')

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('resume must inspect persisted terminal state without live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert second['loop_runner_status'] == 'paused'
    assert second['action'] == 'ask_first_execution_pending'
    assert second['pending']['purpose'] == 'reviewer'
    assert second['pending']['job_id'] == 'job_2'
    assert (project_root / 'lab_code' / 'calculator.py').read_text(encoding='utf-8') == (
        'def add(a, b):\n    return a + b\n'
    )
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / second['loop_id']
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    authority_update = state['current_artifacts']['authority_update']
    assert authority_update['source'] == 'isolated_workspace_changes_promoted'
    assert authority_update['changed_files'] == ['lab_code/calculator.py']
    assert 'deleted_files' not in authority_update


def test_loop_runner_direct_execution_git_workspace_tracked_deletion_still_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_code/calculator.py\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'
    worker_target = submitted[0].target
    workspace = _seed_group_git_workspace_binding(
        context,
        project_root,
        worker_target,
        tracked_paths=('lab_code/calculator.py',),
    )
    (workspace / 'lab_code' / 'calculator.py').unlink()

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        assert cursor == 0
        return _persisted_terminal_payload('job_1', worker_target, reply='status: done\ntracked deletion\n')

    blocked = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('resume must inspect persisted terminal state without live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert blocked['loop_runner_status'] == 'ok'
    assert blocked['round_result'] == 'blocked'
    assert blocked['round_result_source'] == 'isolated_workspace_deletions_unsupported'
    assert blocked['task_status'] == 'blocked'
    assert (project_root / 'lab_code' / 'calculator.py').is_file()
    round_json = json.loads(Path(str(blocked['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'isolated_workspace_deletions_unsupported'
    assert round_json['failure']['deleted_files'] == ['lab_code/calculator.py']
    assert 'authority_update' not in round_json


def test_loop_runner_direct_execution_allows_extensionless_allowed_file_stem_before_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        task_packet_text='# Task Packet\n\n## Allowed Change Paths\n\n- `lab_code/calculator`\n',
        execution_contract_text='# Execution Contract\n\nAllowed change paths:\n\n- `lab_code/calculator`\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'
    worker_target = submitted[0].target
    workspace = _seed_group_git_workspace_binding(
        context,
        project_root,
        worker_target,
        tracked_paths=('lab_code/calculator.py',),
    )
    _write(workspace / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a + b\n')

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        assert cursor == 0
        return _persisted_terminal_payload('job_1', worker_target, reply='status: done\nstem scope\n')

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('resume must inspect persisted terminal state without live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert second['loop_runner_status'] == 'paused'
    assert second['action'] == 'ask_first_execution_pending'
    assert second['pending']['purpose'] == 'reviewer'
    assert (project_root / 'lab_code' / 'calculator.py').read_text(encoding='utf-8') == (
        'def add(a, b):\n    return a + b\n'
    )
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / second['loop_id']
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    authority_update = state['current_artifacts']['authority_update']
    assert authority_update['source'] == 'isolated_workspace_changes_promoted'
    assert authority_update['changed_files'] == ['lab_code/calculator.py']
    assert authority_update['allowed_change_paths'] == ['lab_code/calculator']


def test_loop_runner_direct_execution_extensionless_scope_does_not_match_prefixes() -> None:
    assert loop_ask_first_module._path_allowed_by_scope('lab_code/calculator.py', ['lab_code/calculator'])
    assert loop_ask_first_module._path_allowed_by_scope('finance_cli/storage.py', ['finance_cli/'])
    assert loop_ask_first_module._path_allowed_by_scope('monthly_finance/cli.py', ['monthly_finance/**'])
    assert loop_ask_first_module._path_allowed_by_scope('tests/test_cli.py', ['tests/**'])
    assert loop_ask_first_module._path_allowed_by_scope('requirements-dev.txt', ['requirements*.txt'])
    assert not loop_ask_first_module._path_allowed_by_scope('finance_cli/cli.py', ['finance_cli'])
    assert loop_ask_first_module._declared_allowed_change_paths('Allowed Change Paths:\n- finance_cli/\n') == [
        'finance_cli/'
    ]
    assert not loop_ask_first_module._path_allowed_by_scope('monthly_finance_extra/cli.py', ['monthly_finance/**'])
    assert not loop_ask_first_module._path_allowed_by_scope(
        'lab_code/calculator_extra.py',
        ['lab_code/calculator'],
    )
    assert not loop_ask_first_module._path_allowed_by_scope('finance_cli_extra.py', ['finance_cli'])
    assert not loop_ask_first_module._path_allowed_by_scope(
        'lab_code/calculator/helpers.py',
        ['lab_code/calculator'],
    )


def test_loop_runner_direct_execution_resume_terminal_worker_failure_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def first_watch(_context, job_id, _out, *, timeout, emit_output):
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=submitted[-1].target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=False,
            status='running',
            reply='',
            events=(),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=first_watch,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )
    assert first['action'] == 'ask_first_execution_pending'

    def fake_load_terminal(_context, job_id, *, cursor=0):
        assert job_id == 'job_1'
        return {
            'job_id': 'job_1',
            'agent_name': submitted[0].target,
            'target_kind': 'job',
            'target_name': 'job_1',
            'provider': 'codex',
            'provider_instance': None,
            'cursor': 2,
            'generation': 1,
            'terminal': True,
            'status': 'failed',
            'reply': 'provider failed before completing the task\n',
            'events': [],
        }

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('failed persisted terminal state must not require live watch')
            ),
            load_persisted_terminal_watch_payload=fake_load_terminal,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            plan_task=plan_task,
        ),
    )

    assert second['loop_runner_status'] == 'ok'
    assert second['round_result'] == 'blocked'
    assert second['round_result_source'] == 'ask_job_incomplete'
    assert second['task_status'] == 'blocked'
    assert second['release']['released_count'] == 3
    assert len(submitted) == 1
    round_json = json.loads(Path(str(second['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['worker']['status'] == 'failed'
    assert round_json['failure']['source'] == 'ask_job_incomplete'
    assert round_json['failure']['job_id'] == 'job_1'
    assert round_json['failure']['job_status'] == 'failed'
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['current_loop'] is None


def test_loop_runner_direct_execution_promotes_isolated_workspace_changes_before_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/l1_release_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'l1_release_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_reply'
    assert payload['task_status'] == 'done'
    assert payload['release']['released_count'] == 3
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: reviewed\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['round_result'] == 'pass'
    assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
    assert round_json['authority_update']['changed_files'] == ['lab_docs/l1_release_note.md']
    assert round_json['authority_update']['verified_project_root'] is True
    assert round_json['authority_import']['status'] == 'done'
    summary_text = Path(str(round_json['paths']['round'])).read_text(encoding='utf-8')
    assert 'round result: pass' in summary_text
    assert '## Authority Update' in summary_text
    assert '- changed_files: lab_docs/l1_release_note.md' in summary_text
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'done'
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'pass'


def test_loop_runner_direct_execution_promotes_before_project_root_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/l1_release_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    reviewer_project_root_seen: list[str] = []
    round_reviewer_project_root_seen: list[str] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'l1_release_note.md', 'status: reviewed\n')
            reply = 'status: done\nchanged_files: lab_docs/l1_release_note.md\n'
        elif target.startswith('loop-') and '-code_reviewer-' in target:
            content = (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8')
            reviewer_project_root_seen.append(content)
            reply = (
                'status: pass\n'
                f'project-root evidence: lab_docs/l1_release_note.md -> {content.strip()}\n'
            )
        elif target == 'ccb_round_reviewer':
            content = (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8')
            round_reviewer_project_root_seen.append(content)
            if content == 'status: reviewed\n':
                reply = (
                    'round result: pass\n'
                    'verification performed: project root contains reviewed release note\n'
                    'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                )
            else:
                reply = (
                    'round result: rework_node\n'
                    'fake success evidence: worker workspace changed but project root is still draft\n'
                )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_reply'
    assert payload['task_status'] == 'done'
    assert reviewer_project_root_seen == ['status: reviewed\n']
    assert round_reviewer_project_root_seen == ['status: reviewed\n']
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: reviewed\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
    assert round_json['authority_update']['changed_files'] == ['lab_docs/l1_release_note.md']
    assert round_json['authority_update']['verified_project_root'] is True


def test_loop_runner_direct_execution_accepts_declared_file_already_in_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: risk_register.py\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}
    reviewer_seen: list[str] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'risk_register.py', 'print("ok")\n')
            _write(project_root / 'risk_register.py', 'print("ok")\n')
            reply = 'status: done\nchanged_files: risk_register.py\n'
        elif target.startswith('loop-') and '-code_reviewer-' in target:
            reviewer_seen.append((project_root / 'risk_register.py').read_text(encoding='utf-8'))
            reply = 'status: pass\nproject-root evidence: risk_register.py exists\n'
        elif target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: project root contains risk_register.py\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'pass'
    assert payload['task_status'] == 'done'
    assert reviewer_seen == ['print("ok")\n']
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['authority_update']['source'] == 'isolated_workspace_declared_changes_already_project_root'
    assert round_json['authority_update']['changed_files'] == ['risk_register.py']
    assert round_json['authority_update']['verified_project_root'] is True


def test_loop_runner_direct_execution_blocks_when_workspace_promotion_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/l1_release_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'l1_release_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def blocked_copy(*_args, **_kwargs):
        raise RuntimeError('promotion blocked by test')

    monkeypatch.setattr(loop_ask_first_module, '_copy_workspace_files', blocked_copy)

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'isolated_workspace_promotion_failed'
    assert payload['task_status'] == 'blocked'
    assert payload['release']['released_count'] == 3
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: draft\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['round_result'] == 'blocked'
    assert round_json['failure']['source'] == 'isolated_workspace_promotion_failed'
    assert round_json['failure']['changed_files'] == ['lab_docs/l1_release_note.md']
    assert round_json['authority_import']['status'] == 'blocked'
    summary_text = Path(str(round_json['paths']['round'])).read_text(encoding='utf-8')
    assert 'round result: blocked' in summary_text
    assert '- changed_files: lab_docs/l1_release_note.md' in summary_text
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'


def test_loop_runner_direct_execution_blocks_isolated_workspace_pass_without_project_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            _seed_copy_workspace_binding(context, project_root, target)
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'isolated_workspace_no_project_root_effect'
    assert payload['task_status'] == 'blocked'
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: draft\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'isolated_workspace_no_project_root_effect'
    assert round_json['failure']['changed_files'] == []
    assert 'authority_update' not in round_json
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'


def test_loop_runner_direct_execution_blocks_when_change_scope_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'l1_release_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = 'round result: pass\nverification performed: direct execution fake review\n'
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'isolated_workspace_change_scope_missing'
    assert payload['task_status'] == 'blocked'
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: draft\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'isolated_workspace_change_scope_missing'
    assert round_json['failure']['changed_files'] == ['lab_docs/l1_release_note.md']
    assert round_json['failure']['allowed_change_paths'] == []
    assert 'authority_update' not in round_json


def test_loop_runner_direct_execution_blocks_out_of_scope_workspace_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _write(project_root / 'lab_docs' / 'unrelated.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/l1_release_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'l1_release_note.md', 'status: reviewed\n')
            _write(workspace / 'lab_docs' / 'unrelated.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = 'round result: pass\nverification performed: direct execution fake review\n'
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'isolated_workspace_change_scope_violation'
    assert payload['task_status'] == 'blocked'
    assert (project_root / 'lab_docs' / 'l1_release_note.md').read_text(encoding='utf-8') == 'status: draft\n'
    assert (project_root / 'lab_docs' / 'unrelated.md').read_text(encoding='utf-8') == 'status: draft\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'isolated_workspace_change_scope_violation'
    assert round_json['failure']['allowed_change_paths'] == ['lab_docs/l1_release_note.md']
    assert round_json['failure']['out_of_scope_files'] == ['lab_docs/unrelated.md']
    assert 'authority_update' not in round_json


def test_loop_runner_direct_execution_blocks_delete_or_rename_workspace_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'l1_release_note.md', 'status: draft\n')
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            (workspace / 'lab_docs' / 'l1_release_note.md').unlink()
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'isolated_workspace_deletions_unsupported'
    assert payload['task_status'] == 'blocked'
    assert (project_root / 'lab_docs' / 'l1_release_note.md').is_file()
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'isolated_workspace_deletions_unsupported'
    assert round_json['failure']['deleted_files'] == ['lab_docs/l1_release_note.md']
    assert 'authority_update' not in round_json
    summary_text = Path(str(round_json['paths']['round'])).read_text(encoding='utf-8')
    assert '- deleted_files: lab_docs/l1_release_note.md' in summary_text
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'


def test_loop_runner_direct_execution_blocks_when_copy_workspace_binding_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'workspace_binding_missing'
    assert payload['task_status'] == 'blocked'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'workspace_binding_missing'
    assert round_json['failure']['workspace_mode_configured'] == 'git-worktree'
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'


def test_loop_runner_direct_execution_blocks_when_workspace_binding_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            _write(project_root / '.ccb' / 'workspaces' / target / '.ccb-workspace.json', '{not-json')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'workspace_binding_invalid'
    assert payload['task_status'] == 'blocked'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'workspace_binding_invalid'
    assert round_json['authority_import']['status'] == 'blocked'


def test_loop_runner_direct_execution_blocks_when_project_root_test_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _write(
        project_root / 'tests' / 'test_calculator.py',
        'import unittest\n\n'
        'from lab_code.calculator import add\n\n'
        'class CalculatorTest(unittest.TestCase):\n'
        '    def test_add(self):\n'
        '        self.assertEqual(add(2, 3), 5)\n',
    )
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths: lab_code/calculator.py\n'
            'test_command: python -m unittest discover -s tests -p test_calculator.py\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a * b\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'project_root_test_failed'
    assert payload['task_status'] == 'blocked'
    assert (project_root / 'lab_code' / 'calculator.py').read_text(encoding='utf-8') == 'def add(a, b):\n    return a - b\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'project_root_test_failed'
    assert round_json['failure']['test_result'] == 'fail'
    assert round_json['failure']['test_command'] == 'python -m unittest discover -s tests -p test_calculator.py'
    assert round_json['failure']['test_cwd'] == str(project_root)
    assert round_json['failure']['test_file_resolved_to_lab'] is True
    assert round_json['failure']['test_sys_path_project_first'] is True
    assert round_json['project_root_test']['test_result'] == 'fail'
    assert Path(str(round_json['project_root_test']['test_resolution_path'])).is_file()
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'


def test_loop_runner_direct_execution_pass_requires_verified_project_root_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _write(
        project_root / 'tests' / 'test_calculator.py',
        'import unittest\n\n'
        'from lab_code.calculator import add\n\n'
        'class CalculatorTest(unittest.TestCase):\n'
        '    def test_add(self):\n'
        '        self.assertEqual(add(2, 3), 5)\n',
    )
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths: lab_code/calculator.py\n'
            'test_command: python -m unittest discover -s tests -p test_calculator.py\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a + b\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_reply'
    assert payload['task_status'] == 'done'
    assert (project_root / 'lab_code' / 'calculator.py').read_text(encoding='utf-8') == 'def add(a, b):\n    return a + b\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
    assert round_json['authority_update']['verified_project_root'] is True
    assert round_json['authority_update']['changed_files'] == ['lab_code/calculator.py']
    assert round_json['project_root_test']['test_result'] == 'pass'
    assert round_json['project_root_test']['test_command'] == 'python -m unittest discover -s tests -p test_calculator.py'
    assert round_json['project_root_test']['test_cwd'] == str(project_root)
    assert round_json['project_root_test']['test_file_resolved_to_lab'] is True
    assert round_json['project_root_test']['test_sys_path_project_first'] is True
    assert Path(str(round_json['project_root_test']['test_resolution_path'])).is_file()
    assert round_json['authority_import']['status'] == 'done'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'done'


def test_loop_runner_direct_execution_pass_accepts_explicit_pytest_file_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a - b\n')
    _write(
        project_root / 'tests' / 'test_calculator_reporting.py',
        'from lab_code.calculator import add\n\n'
        'def test_add():\n'
        '    assert add(2, 3) == 5\n',
    )
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths: lab_code/calculator.py\n'
            'test_command: python -m pytest tests/test_calculator_reporting.py\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_code' / 'calculator.py', 'def add(a, b):\n    return a + b\n')
        if target == 'ccb_round_reviewer':
            reply = (
                'round result: pass\n'
                'verification performed: direct execution fake review\n'
                'hidden degradation audit: no hidden fallback, scope shrink, or fake success\n'
                'evidence refs: task_packet execution_contract\n'
            )
        else:
            reply = f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not run the legacy fixed bridge')
            ),
            topology_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('direct_execution route must not execute topology dispatch')
            ),
            plan_task=plan_task,
        ),
    )

    assert payload['round_result'] == 'pass'
    assert payload['round_result_source'] == 'round_reviewer_reply'
    assert payload['task_status'] == 'done'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['project_root_test']['test_result'] == 'pass'
    assert round_json['project_root_test']['test_command'] == 'python -m pytest tests/test_calculator_reporting.py'
    assert round_json['project_root_test']['test_cwd'] == str(project_root)
    assert round_json['project_root_test']['test_file_resolved_to_lab'] is True
    assert round_json['project_root_test']['test_sys_path_project_first'] is True
    assert round_json['project_root_test']['test_file'] == str(project_root / 'tests' / 'test_calculator_reporting.py')
    assert round_json['authority_import']['status'] == 'done'


def test_loop_runner_partial_completion_route_imports_partial_without_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-partial')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-partial', route='partial_completion')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        reply = 'round result: partial\nunfinished step evidence: step-2 open\n' if target == 'ccb_round_reviewer' else f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'ran_one_round'
    assert payload['round_result'] == 'partial'
    assert payload['task_status'] == 'partial'
    assert payload['next_activation'] == 'planner'
    assert len(submitted) == 3
    assert all(command.sender == 'system' for command in submitted)
    assert all(command.callback is False for command in submitted)
    assert all(command.silence is False for command in submitted)
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-partial'))
    assert shown['task']['status'] == 'partial'
    assert shown['task']['next_owner'] == 'planner'
    assert shown['task']['current_loop'] is None
    assert shown['task']['artifacts']['orchestration_notes']['orchestrator_route'] == 'partial_completion'
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'partial'


@pytest.mark.parametrize(
    ('round_reviewer_reply', 'expected_result', 'expected_status', 'reviewer_recheck_status'),
    (
        ('round result: pass\n', 'pass', 'done', 'pass'),
        ('round result: replan_required\n', 'replan_required', 'replan_required', 'rework_required'),
    ),
)
def test_loop_runner_direct_execution_uses_one_bounded_rework_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_reviewer_reply: str,
    expected_result: str,
    expected_status: str,
    reviewer_recheck_status: str,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'bounded_rework_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-rework',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/bounded_rework_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-rework', route='direct_execution')
    submitted: list[object] = []
    commands_by_job: dict[str, object] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        commands_by_job[job_id] = ask_command
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        ask_command = commands_by_job[str(job_id)]
        target = ask_command.target
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'bounded_rework_note.md', 'status: reviewed\n')
        if target == 'ccb_round_reviewer':
            reply = round_reviewer_reply
        elif str(ask_command.task_id).endswith('-reviewer'):
            reply = 'status: rework_required\nexecution_contract audit: fail\n'
        elif str(ask_command.task_id).endswith('-reviewer-recheck'):
            reply = f'status: {reviewer_recheck_status}\nexecution_contract audit: fail\n'
        else:
            reply = f'status: done\nreply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == expected_result
    assert payload['task_status'] == expected_status
    assert payload['release']['released_count'] == 3
    assert [command.task_id for command in submitted] == [
        f'{payload["loop_id"]}-worker',
        f'{payload["loop_id"]}-reviewer',
        f'{payload["loop_id"]}-worker-rework',
        f'{payload["loop_id"]}-reviewer-recheck',
        f'{payload["loop_id"]}-round-reviewer',
    ]
    assert all(command.sender == 'system' for command in submitted)
    assert all(command.callback is False for command in submitted)
    assert all(command.silence is False for command in submitted)
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert set(round_json['rework']) == {'worker_rework', 'reviewer_recheck'}
    assert round_json['rework']['worker_rework']['status'] == 'completed'
    assert round_json['rework']['reviewer_recheck']['status'] == 'completed'
    if expected_result == 'pass':
        assert (project_root / 'lab_docs' / 'bounded_rework_note.md').read_text(encoding='utf-8') == 'status: reviewed\n'
        assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
        assert round_json['authority_update']['changed_files'] == ['lab_docs/bounded_rework_note.md']
        assert round_json['authority_update']['allowed_change_paths'] == ['lab_docs/bounded_rework_note.md']
        assert round_json['authority_update']['verified_project_root'] is True
    else:
        assert (project_root / 'lab_docs' / 'bounded_rework_note.md').read_text(encoding='utf-8') == 'status: draft\n'
        assert round_json['authority_update']['source'] == 'isolated_workspace_changes_promoted'
        assert round_json['authority_update']['changed_files'] == ['lab_docs/bounded_rework_note.md']
        assert round_json['authority_update']['authority_rollback'] == 'restored_project_root'
        assert round_json['authority_update']['authority_rollback_reason'] == 'non_pass_round_result:replan_required'
    asks = [
        json.loads(line)['purpose']
        for line in (project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id'] / 'asks.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert asks == ['worker', 'reviewer', 'worker_rework', 'reviewer_recheck', 'round_reviewer']
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-rework'))
    assert shown['task']['status'] == expected_status
    assert shown['task']['current_loop'] is None


def test_loop_runner_direct_execution_blocks_without_asks_when_topology_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    topology_calls: list[str] = []

    def fake_loop_topology(_context, topology_command):
        action = str(topology_command.action)
        topology_calls.append(action)
        loop_id = str(topology_command.loop_id)
        loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / loop_id
        proposal_path = loop_dir / 'topology_proposals' / 'ask-first-execution.json'
        desired_path = loop_dir / 'agent_mount_topology.desired.json'
        observed_path = loop_dir / 'agent_mount_topology.observed.json'
        if action == 'propose':
            _write_json(
                proposal_path,
                {
                    'schema': 'ccb.loop.agent_mount_topology.proposal.v1',
                    'loop_id': loop_id,
                    'agents': [],
                    'windows': [],
                },
            )
            return {
                'loop_topology_status': 'proposed',
                'loop_id': loop_id,
                'proposal_id': 'ask-first-execution',
                'proposal_path': str(proposal_path),
                'validation': {'agent_count': 2},
            }
        if action == 'commit':
            _write_json(
                desired_path,
                {
                    'schema': 'ccb.loop.agent_mount_topology.v1',
                    'loop_id': loop_id,
                    'revision': 1,
                    'agents': [],
                    'windows': [],
                },
            )
            _write_json(
                observed_path,
                {
                    'schema': 'ccb.loop.agent_mount_topology.observed.v1',
                    'loop_id': loop_id,
                    'desired_revision': 1,
                    'last_reconcile_status': 'failed',
                    'agents': [],
                    'windows': [],
                },
            )
            return {
                'loop_topology_status': 'committed',
                'loop_id': loop_id,
                'desired_path': str(desired_path),
                'reconcile': {
                    'loop_topology_status': 'failed',
                    'loop_id': loop_id,
                    'observed_path': str(observed_path),
                    'agent_count': 2,
                    'released_count': 0,
                    'retained_count': 0,
                },
            }
        if action == 'status':
            return {
                'loop_topology_status': 'failed',
                'loop_id': loop_id,
                'desired_path': str(desired_path),
                'observed_path': str(observed_path),
            }
        if action == 'release':
            return {
                'loop_topology_status': 'released',
                'loop_id': loop_id,
                'desired_path': str(desired_path),
                'observed_path': str(observed_path),
                'released_count': 0,
                'retained_count': 0,
                'released_agents': [],
            }
        raise AssertionError(f'unexpected topology action: {action}')

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('topology-not-ready must stop before worker/reviewer asks')

    def forbidden_watch_ask_job(*_args, **_kwargs):
        raise AssertionError('topology-not-ready must not watch ask jobs')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            loop_topology=fake_loop_topology,
            submit_ask=forbidden_submit_ask,
            watch_ask_job=forbidden_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['execution_mode'] == 'ask_first_direct_execution'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'topology_not_ready'
    assert payload['task_status'] == 'blocked'
    assert payload['next_activation'] == 'terminal'
    assert payload['topology']['status'] == 'failed'
    assert payload['release']['released_count'] == 0
    assert payload['release']['retained_count'] == 0
    assert topology_calls == ['propose', 'commit', 'status', 'release']
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id']
    assert not (loop_dir / 'asks.jsonl').exists()
    summary_text = Path(str(payload['round']['round_path'])).read_text(encoding='utf-8')
    assert 'round result: blocked' in summary_text
    assert 'source: topology_not_ready' in summary_text
    assert 'mount topology status failed; expected ready' in summary_text
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'topology_not_ready'
    assert round_json['failure']['stage'] == 'topology'
    assert round_json['failure']['reason'] == 'mount topology status failed; expected ready'
    assert round_json['failure']['loop_topology_status'] == 'failed'
    assert round_json['failure']['topology_status']['loop_topology_status'] == 'failed'
    assert round_json['topology']['release']['released_count'] == 0
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['current_loop'] is None
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'blocked'


def test_loop_runner_direct_execution_submit_failure_blocks_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        raise RuntimeError('submit transport failed')

    def forbidden_watch_ask_job(*_args, **_kwargs):
        raise AssertionError('submit failure must not watch ask jobs')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=forbidden_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'ask_submission_failed'
    assert payload['task_status'] == 'blocked'
    assert payload['release']['released_count'] == 3
    assert payload['release']['retained_count'] == 0
    assert len(submitted) == 1
    assert submitted[0].target.startswith(f'loop-{payload["loop_id"]}-coder-')
    assert submitted[0].sender == 'system'
    assert submitted[0].callback is False
    assert submitted[0].silence is False
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id']
    assert not (loop_dir / 'asks.jsonl').exists()
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['failure']['source'] == 'ask_submission_failed'
    assert round_json['failure']['stage'] == 'worker_ask'
    assert round_json['failure']['reason'] == 'submit transport failed'
    assert round_json['topology']['release']['released_count'] == 3
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['current_loop'] is None


def test_loop_runner_direct_execution_watch_error_stays_pending_without_round_import_or_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, _job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        raise RuntimeError('watch transport failed')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['round_result'] == 'pending'
    assert payload['round_result_source'] == 'ask_job_pending'
    assert payload['task_status'] == 'running'
    assert payload['pending']['source'] == 'ask_job_pending'
    assert payload['pending']['job_id'] == 'job_1'
    assert payload['pending']['watch_observation'] == 'error'
    assert payload['pending']['reason'] == 'watch transport failed'
    assert 'release' not in payload
    assert 'import' not in payload
    assert len(submitted) == 1
    assert submitted[0].target.startswith(f'loop-{payload["loop_id"]}-coder-')
    assert submitted[0].sender == 'system'
    assert submitted[0].callback is False
    assert submitted[0].silence is False
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id']
    asks = (loop_dir / 'asks.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(asks) == 1
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['pending']['watch_observation'] == 'error'
    assert state['pending']['reason'] == 'watch transport failed'
    assert (loop_dir / 'round.pending.json').is_file()
    assert not (loop_dir / 'round_summary.md').exists()
    assert not (loop_dir / 'round.json').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == payload['loop_id']


def test_loop_runner_direct_execution_watch_timeout_stays_pending_without_round_import_or_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': f'job_{len(submitted)}', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, _job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        raise TimeoutError('watch timed out waiting for job_1')

    def no_persisted_terminal(_context, _job_id, *, cursor=0):
        assert cursor == 0
        return None

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            load_persisted_terminal_watch_payload=no_persisted_terminal,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'paused'
    assert payload['action'] == 'ask_first_execution_pending'
    assert payload['round_result'] == 'pending'
    assert payload['round_result_source'] == 'ask_job_pending'
    assert payload['task_status'] == 'running'
    assert payload['pending']['source'] == 'ask_job_pending'
    assert payload['pending']['job_id'] == 'job_1'
    assert payload['pending']['watch_observation'] == 'timeout'
    assert 'release' not in payload
    assert 'import' not in payload
    assert len(submitted) == 1
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / payload['loop_id']
    assert (loop_dir / 'asks.jsonl').is_file()
    assert (loop_dir / 'round.pending.json').is_file()
    assert not (loop_dir / 'round_summary.md').exists()
    assert not (loop_dir / 'round.json').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == payload['loop_id']
    assert 'round_summary' not in shown['task']['artifacts']


def test_loop_runner_direct_execution_resumes_persisted_completion_without_rewatching_existing_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'resume_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/resume_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    targets_by_job: dict[str, str] = {}

    def initial_submit_ask(_context, ask_command):
        job_id = 'job_1'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id='sub_1',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def timeout_watch(_context, job_id, _out, *, timeout, emit_output):
        assert str(job_id) == 'job_1'
        assert timeout == 11.0
        assert emit_output is False
        raise TimeoutError('watch timed out waiting for job_1')

    pending = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=initial_submit_ask,
            watch_ask_job=timeout_watch,
            load_persisted_terminal_watch_payload=lambda *_args, **_kwargs: None,
            plan_task=plan_task,
        ),
    )
    assert pending['action'] == 'ask_first_execution_pending'
    loop_id = str(pending['loop_id'])
    worker_target = targets_by_job['job_1']
    workspace = _seed_copy_workspace_binding(context, project_root, worker_target)
    _write(workspace / 'lab_docs' / 'resume_note.md', 'status: resumed\n')
    submitted_after_resume: list[object] = []

    def resume_submit_ask(_context, ask_command):
        if ask_command.target == worker_target:
            raise AssertionError('persisted worker completion must not submit a duplicate worker ask')
        submitted_after_resume.append(ask_command)
        job_id = f'job_{len(targets_by_job) + 1}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(targets_by_job)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def resume_watch_ask_job(*_args, **_kwargs):
        raise AssertionError('resume must not synchronously watch after advancing one persisted stage')

    def persisted_terminal(_context, job_id, *, cursor=0):
        assert cursor == 0
        if str(job_id) == 'job_1':
            return _persisted_terminal_payload('job_1', worker_target, reply='worker completed from persisted reply')
        return None

    resumed = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=resume_submit_ask,
            watch_ask_job=resume_watch_ask_job,
            load_persisted_terminal_watch_payload=persisted_terminal,
            plan_task=plan_task,
        ),
    )

    assert resumed['loop_runner_status'] == 'paused'
    assert resumed['action'] == 'ask_first_execution_pending'
    assert resumed['loop_id'] == loop_id
    assert resumed['round_result'] == 'pending'
    assert resumed['round_result_source'] == 'ask_job_pending'
    assert resumed['task_status'] == 'running'
    assert resumed['pending']['purpose'] == 'reviewer'
    assert resumed['pending']['job_id'] == 'job_2'
    assert [command.target for command in submitted_after_resume] == [
        f'loop-{loop_id}-code_reviewer-1',
    ]
    assert (project_root / 'lab_docs' / 'resume_note.md').read_text(encoding='utf-8') == 'status: resumed\n'
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / loop_id
    state = json.loads((loop_dir / 'ask_first_stage_state.json').read_text(encoding='utf-8'))
    assert state['purpose'] == 'reviewer'
    assert state['current_artifacts']['worker']['job_id'] == 'job_1'
    assert state['current_artifacts']['worker']['watch_source'] == 'persisted_terminal'
    assert state['current_artifacts']['worker']['visible_reply_source'] == 'snapshot'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'running'
    assert shown['task']['current_loop'] == loop_id


def test_loop_runner_direct_execution_persisted_failed_terminal_blocks_with_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    targets_by_job: dict[str, str] = {}

    def initial_submit_ask(_context, ask_command):
        targets_by_job['job_1'] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id='sub_1',
            jobs=({'job_id': 'job_1', 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def timeout_watch(_context, job_id, _out, *, timeout, emit_output):
        assert str(job_id) == 'job_1'
        assert timeout == 11.0
        assert emit_output is False
        raise TimeoutError('watch timed out waiting for job_1')

    pending = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=initial_submit_ask,
            watch_ask_job=timeout_watch,
            load_persisted_terminal_watch_payload=lambda *_args, **_kwargs: None,
            plan_task=plan_task,
        ),
    )
    assert pending['action'] == 'ask_first_execution_pending'
    worker_target = targets_by_job['job_1']

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('failed persisted worker job must block before submitting downstream asks')

    def forbidden_watch_ask_job(*_args, **_kwargs):
        raise AssertionError('failed persisted worker job must be consumed without watch_ask_job')

    def persisted_failed(_context, job_id, *, cursor=0):
        assert cursor == 0
        if str(job_id) == 'job_1':
            return _persisted_terminal_payload(
                'job_1',
                worker_target,
                status='failed',
                reply='provider failed after submission',
            )
        return None

    blocked = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            watch_ask_job=forbidden_watch_ask_job,
            load_persisted_terminal_watch_payload=persisted_failed,
            plan_task=plan_task,
        ),
    )

    assert blocked['loop_runner_status'] == 'ok'
    assert blocked['round_result'] == 'blocked'
    assert blocked['round_result_source'] == 'ask_job_incomplete'
    assert blocked['task_status'] == 'blocked'
    assert blocked['release']['released_count'] == 3
    round_json = json.loads(Path(str(blocked['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['worker']['status'] == 'failed'
    assert round_json['worker']['watch_source'] == 'persisted_terminal'
    assert round_json['failure']['source'] == 'ask_job_incomplete'
    assert round_json['failure']['job_id'] == 'job_1'
    assert round_json['failure']['job_status'] == 'failed'
    assert round_json['failure']['watch_source'] == 'persisted_terminal'
    assert round_json['failure']['visible_reply_source'] == 'snapshot'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['current_loop'] is None


def test_loop_runner_direct_execution_missing_round_result_blocks_before_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-direct')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    release_seen: list[str] = []

    def fake_ask_first_execution(_context, run_command, _services):
        loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / run_command.loop_id
        loop_dir.mkdir(parents=True, exist_ok=True)
        round_path = loop_dir / 'round_summary.md'
        round_json_path = loop_dir / 'round.json'
        _write(round_path, 'round checker completed without a machine result line\n')
        payload = {
            'schema_version': 1,
            'record_type': 'ccb_loop_ask_first_execution_round',
            'loop_run_status': 'ok',
            'dispatch_source': 'ask_first_mount_topology',
            'loop_id': run_command.loop_id,
            'task_id': run_command.task_id,
            'worker': {'job_id': 'job_worker'},
            'ccb_round_reviewer': {'reply': 'round reviewer completed without a machine result line\n'},
            'paths': {'round': str(round_path), 'round_json': str(round_json_path)},
        }
        _write(round_json_path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        return payload

    def fake_ask_first_release(_context, round_payload, _services):
        shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
        assert shown['task']['status'] == 'blocked'
        assert shown['task']['current_loop'] is None
        release_seen.append(str(round_payload['loop_id']))
        return {
            'loop_topology_status': 'released',
            'loop_id': round_payload['loop_id'],
            'released_count': 2,
            'retained_count': 0,
            'released_agents': ['loop-x-code_reviewer-1', 'loop-x-coder-1'],
        }

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            ask_first_execution=fake_ask_first_execution,
            ask_first_release=fake_ask_first_release,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['execution_mode'] == 'ask_first_direct_execution'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'missing_round_reviewer_result'
    assert payload['task_status'] == 'blocked'
    assert payload['release']['released_count'] == 2
    assert release_seen == [payload['loop_id']]
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'blocked'


def test_loop_runner_round_result_accepts_first_line_machine_field() -> None:
    payload = {
        'loop_run_status': 'ok',
        'ccb_round_reviewer': {
            'reply': (
                'round result: pass\n'
                '轮次审阅完成。所有证据已验证，项目根目录变更正确，验证命令通过。'
            ),
        },
    }

    assert loop_ask_first_module._round_result(payload) == ('pass', 'round_reviewer_reply', None)


def test_loop_runner_round_result_rejects_preamble_before_machine_field() -> None:
    payload = {
        'loop_run_status': 'ok',
        'ccb_round_reviewer': {
            'reply': (
                '现在我已经掌握了所有证据。让我进行最终的综合分析。\n\n'
                '```\n'
                'round result: pass\n'
                '```\n'
            ),
        },
    }

    assert loop_ask_first_module._round_result(payload) == ('blocked', 'missing_round_reviewer_result', None)


def test_loop_runner_round_result_rejects_sequence38_late_pass_after_test_preamble() -> None:
    payload = {
        'loop_run_status': 'ok',
        'ccb_round_reviewer': {
            'reply': (
                'Now let me run the tests to verify the implementation against the execution contract:\n'
                'All tests pass and the evidence looks complete.\n\n'
                'round result: pass\n'
            ),
        },
    }

    assert loop_ask_first_module._round_result(payload) == ('blocked', 'missing_round_reviewer_result', None)


def test_loop_runner_round_result_rejects_backticked_first_line_value() -> None:
    payload = {
        'loop_run_status': 'ok',
        'ccb_round_reviewer': {
            'reply': 'round result: `pass`\nverification performed: fake review\n',
        },
    }

    assert loop_ask_first_module._round_result(payload) == ('blocked', 'missing_round_reviewer_result', None)


def test_round_reviewer_message_highlights_contract_expected_round_result() -> None:
    message = loop_ask_first_module._round_reviewer_message(
        loop_id='lp-test',
        task_id='task-partial',
        task_text=(
            '# Execution Contract\n\n'
            'expected_round_result: partial\n'
            'expected_final_status: partial\n'
        ),
        artifact_refs={'task_packet': 'tasks/task/task_packet.md', 'execution_contract': 'tasks/task/execution_contract.md'},
        worker={'job_id': 'job_worker', 'status': 'completed'},
        reviewer={'job_id': 'job_reviewer', 'status': 'completed'},
        rework={},
        authority_update=None,
    )

    assert message.startswith('FINAL ANSWER FORMAT - parser enforced:\n')
    assert 'Contract-declared expected round result: partial' in message
    assert (
        'If the supplied evidence supports that contract expectation, '
        'your first line must be exactly: round result: partial'
    ) in message
    assert 'If the evidence does not support that expectation, your first line must still be one of:' in message


def test_round_reviewer_message_highlights_converged_expected_round_result() -> None:
    message = loop_ask_first_module._round_reviewer_message(
        loop_id='lp-test',
        task_id='task-pass',
        task_text=(
            '# Execution Contract\n\n'
            'expected_round_result_if_converged: pass\n'
            'expected_final_status: done\n'
        ),
        artifact_refs={'task_packet': 'tasks/task/task_packet.md', 'execution_contract': 'tasks/task/execution_contract.md'},
        worker={'job_id': 'job_worker', 'status': 'completed'},
        reviewer={'job_id': 'job_reviewer', 'status': 'completed'},
        rework={},
        authority_update=None,
    )

    assert 'Contract-declared expected round result: pass' in message
    assert 'your first line must be exactly: round result: pass' in message


def test_round_reviewer_message_includes_worker_and_reviewer_reply_artifacts(tmp_path: Path) -> None:
    worker_artifact = tmp_path / 'worker-reply.md'
    reviewer_artifact = tmp_path / 'reviewer-reply.md'
    worker_artifact.write_text('worker says verification passed\n', encoding='utf-8')
    reviewer_artifact.write_text('reviewer says status: pass\n', encoding='utf-8')
    message = loop_ask_first_module._round_reviewer_message(
        loop_id='lp-test',
        task_id='task-pass',
        task_text='# Execution Contract\n\nexpected_round_result_if_converged: pass\n',
        artifact_refs={'task_packet': 'tasks/task/task_packet.md', 'execution_contract': 'tasks/task/execution_contract.md'},
        worker={'job_id': 'job_worker', 'status': 'completed', 'artifact': str(worker_artifact)},
        reviewer={'job_id': 'job_reviewer', 'status': 'completed', 'artifact': str(reviewer_artifact)},
        rework={},
        authority_update=None,
    )

    assert 'Supplied round evidence artifacts:' in message
    assert f'Worker reply artifact: {worker_artifact}' in message
    assert 'worker says verification passed' in message
    assert f'Reviewer reply artifact: {reviewer_artifact}' in message
    assert 'reviewer says status: pass' in message
    assert 'Orchestrator reply artifact:' not in message


def test_planning_role_prompts_are_reply_only_authority() -> None:
    task_detailer_message = loop_runner_module._task_detailer_message(
        {
            'activation_id': 'act-1',
            'task_id': 'task-detail',
            'task_status': 'ready_for_orchestration',
            'reason_for_activation': 'route:needs_detail',
            'plan_brief_ref': 'brief.md',
            'task_packet_root': 'tasks/task-detail',
            'detail_root': 'tasks/task-detail/details',
            'artifact_refs': {'task_packet': 'tasks/task-detail/task_packet.md'},
        }
    )
    planner_message = loop_runner_module._planner_message(
        {
            'activation_id': 'act-2',
            'task_id': 'task-planner',
            'task_status': 'detail_ready',
            'reason_for_activation': 'detail_ready',
            'task_packet_root': 'tasks/task-planner',
            'artifact_refs': {'task_packet': 'tasks/task-planner/task_packet.md'},
            'open_question_refs': [],
            'round_evidence_refs': [],
        }
    )

    plan_reviewer_message = loop_runner_module._plan_reviewer_message(
        {
            'activation_id': 'act-3',
            'task_id': 'task-review',
            'task_status': 'detail_ready',
            'reason_for_activation': 'review',
            'task_packet_root': 'tasks/task-review',
            'artifact_refs': {'task_packet': 'tasks/task-review/task_packet.md'},
        }
    )

    for message in (task_detailer_message, planner_message, plan_reviewer_message):
        assert 'reply only' in message.lower()
        assert 'do not run ccb' in message.lower()
        assert 'ccb_test' in message
        assert 'supervisor/runner' in message or 'runner owns' in message
        assert 'use CCB plan commands' not in message
        assert 'host-provided wrappers' not in message
        assert 'for authoritative writes' not in message
        assert 'ccb loop capacity status' not in message


def test_loop_runner_direct_execution_unknown_round_result_blocks_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    _write(project_root / 'lab_docs' / 'unknown_round_note.md', 'status: draft\n')
    _add_ready_plan_task(
        project_root,
        task_id='task-direct',
        execution_contract_text='execution contract text\nallowed_change_paths: lab_docs/unknown_round_note.md\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-direct', route='direct_execution')
    submitted: list[object] = []
    targets_by_job: dict[str, str] = {}

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        job_id = f'job_{len(submitted)}'
        targets_by_job[job_id] = ask_command.target
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{len(submitted)}',
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'accepted'},),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        assert timeout == 11.0
        assert emit_output is False
        target = targets_by_job[str(job_id)]
        if target.startswith('loop-') and '-coder-' in target:
            workspace = _seed_copy_workspace_binding(context, project_root, target)
            _write(workspace / 'lab_docs' / 'unknown_round_note.md', 'status: reviewed\n')
        reply = 'round_result: mystery\n' if target == 'ccb_round_reviewer' else f'reply from {target}'
        return WatchEventBatch(
            target=job_id,
            job_id=job_id,
            agent_name=target,
            target_kind='job',
            target_name=job_id,
            provider='codex',
            provider_instance=None,
            cursor=1,
            generation=1,
            terminal=True,
            status='completed',
            reply=reply,
            events=(),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('direct_execution route must not run the legacy fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'unknown_round_result'
    assert payload['task_status'] == 'blocked'
    assert payload['release']['released_count'] == 3
    assert payload['release']['retained_count'] == 0
    assert len(submitted) == 4
    assert submitted[3].target == 'ccb_round_reviewer'
    assert submitted[3].task_id.endswith('-round-reviewer-correction')
    assert 'Unknown first-line value observed: mystery' in submitted[3].message
    assert (project_root / 'lab_docs' / 'unknown_round_note.md').read_text(encoding='utf-8') == 'status: draft\n'
    round_json = json.loads(Path(str(payload['round']['round_json_path'])).read_text(encoding='utf-8'))
    assert round_json['ccb_round_reviewer']['purpose'] == 'ccb_round_reviewer_correction'
    assert round_json['ccb_round_reviewer']['correction_source_job_id'] == 'job_3'
    assert round_json['ccb_round_reviewer']['correction_source_round_result_source'] == 'unknown_round_result'
    assert round_json['failure']['source'] == 'unknown_round_result'
    assert round_json['failure']['reason'] == "unknown round result 'mystery'"
    assert round_json['failure']['unknown_round_result'] == 'mystery'
    assert round_json['failure']['authority_rollback'] == 'restored_project_root'
    assert round_json['authority_update']['authority_rollback'] == 'restored_project_root'
    assert round_json['topology']['release']['released_count'] == 3
    assert round_json['authority_import']['status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-direct'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['current_loop'] is None
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'blocked'


def test_loop_runner_needs_detail_route_activates_detailer_only_after_route_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: list[str] = []
    cleared: list[str] = []

    def fake_clear_agent_context(_context, clear_command):
        names = list(clear_command.agent_names)
        cleared.extend(names)
        return {
            'status': 'ok',
            'results': [{'agent': name, 'status': 'cleared', 'pane_id': '%1', 'command': '/clear'} for name in names],
        }

    def fake_submit_before_route(_context, ask_command):
        seen.append(ask_command.target)
        assert ask_command.inline_request is False
        assert ask_command.artifact_request is False
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_before_route', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('needs_detail task must not execute before route import')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_before_route,
            clear_agent_context=fake_clear_agent_context,
            loop_run_once=forbidden_loop_run_once,
        ),
    )
    assert payload['action'] == 'activated_orchestrator'
    assert seen == ['orchestrator']
    assert payload['freshness']['status'] == 'cleared'
    assert cleared == ['orchestrator']

    _import_orchestration_notes(context, project_root, task_id='task-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        seen.append(ask_command.target)
        assert ask_command.target == 'task_detailer'
        assert ask_command.inline_request is True
        assert ask_command.artifact_request is False
        assert 'Artifact refs:' in ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_detailer,
            clear_agent_context=fake_clear_agent_context,
            loop_run_once=forbidden_loop_run_once,
        ),
    )
    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_task_detailer'
    assert payload['reason'] == 'orchestrator_route_needs_detail'
    assert payload['next_owner'] == 'orchestrator'
    assert seen == ['orchestrator', 'task_detailer']
    assert payload['freshness']['status'] == 'cleared'
    assert cleared == ['orchestrator', 'task_detailer']

    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.json'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(action='task-artifact', task_id='task-detail', artifact_kind=kind, file_path=str(source)),
        )

    def fake_submit_orchestrator_after_detail(_context, ask_command):
        seen.append(ask_command.target)
        assert ask_command.target == 'orchestrator'
        assert ask_command.inline_request is False
        assert ask_command.artifact_request is False
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator_after_detail', 'agent_name': 'orchestrator', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_orchestrator_after_detail,
            clear_agent_context=fake_clear_agent_context,
            loop_run_once=forbidden_loop_run_once,
        ),
    )
    assert payload['action'] == 'activated_orchestrator'
    assert payload['reason'] == 'orchestrator_route_needs_detail_detail_ready'
    assert seen == ['orchestrator', 'task_detailer', 'orchestrator']
    assert payload['freshness']['status'] == 'cleared'
    assert cleared == ['orchestrator', 'task_detailer', 'orchestrator']


def test_loop_runner_detailer_prompt_preserves_detail_ready_stop_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=(
            '# Task: phase6b-l3-needs-detail\n'
            'Route: needs_detail\n'
            'This validation case must preserve the needs_detail route and stop at detail_ready.\n'
        ),
        execution_contract_text=(
            '# Execution Contract\n'
            'Route: needs_detail\n'
            'The controller-visible task outcome remains detail_ready.\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(
        context,
        project_root,
        task_id='phase6b-l3-needs-detail',
        route='needs_detail',
        text='route: needs_detail\nscript-owned route authority must stop at detail_ready\n',
    )
    seen: dict[str, object] = {}

    def fake_submit_detailer(_context, ask_command):
        seen['target'] = ask_command.target
        seen['message'] = ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('needs_detail task must not execute while collecting task details')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, loop_run_once=forbidden_loop_run_once),
    )

    assert payload['action'] == 'activated_task_detailer'
    assert seen['target'] == 'task_detailer'
    message = str(seen['message'])
    assert 'Compact artifacts:' in message
    assert 'This validation case must preserve the needs_detail route and stop at detail_ready.' in message
    assert 'Detail-ready stop contract:' in message
    assert 'controller-visible stop/status detail_ready' in message
    assert 'use "detail readiness recommendation: detail_ready"' in message
    assert 'Do not downgrade to needs_clarification' in message
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    contract = activation['detail_ready_stop_contract']
    assert contract['status'] == 'detail_ready'
    assert {item['kind'] for item in contract['evidence']} == {
        'execution_contract',
        'orchestration_notes',
        'task_packet',
    }


def test_loop_runner_task_detailer_inline_prompt_stays_under_mailbox_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    long_middle = 'middle detail that should be compacted\n' * 160
    _add_ready_plan_task(
        project_root,
        task_id='task-long-detail',
        task_packet_text=(
            '# Task: Clarify external sync integration requirements\n'
            'Route: needs_detail\n'
            f'{long_middle}'
            'Blockers:\n'
            '- External system API protocol is not specified.\n'
            '- Authentication scheme is not specified.\n'
            '- Retry and idempotency semantics are not specified.\n'
        ),
        execution_contract_text=(
            '# Execution Contract\n'
            'Route: needs_detail\n'
            f'{long_middle}'
            'Verification tail: confirm mocks cover auth failure and retryable failure.\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(
        context,
        project_root,
        task_id='task-long-detail',
        route='needs_detail',
        text=(
            'route: needs_detail\n'
            f'{long_middle}'
            'orchestration tail: implementation is not authorized until missing API details are clarified.\n'
        ),
    )
    seen: dict[str, object] = {}

    def fake_submit_detailer(_context, ask_command):
        seen['target'] = ask_command.target
        seen['message'] = ask_command.message
        assert ask_command.inline_request is True
        assert ask_command.artifact_request is False
        assert len(ask_command.message.encode('utf-8')) < 4096
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer),
    )

    assert payload['action'] == 'activated_task_detailer'
    assert seen['target'] == 'task_detailer'
    message = str(seen['message'])
    assert 'Clarify external sync integration requirements' in message
    assert 'External system API protocol is not specified.' in message
    assert 'orchestration tail: implementation is not authorized' in message
    assert "'truncated': True" in message


def test_loop_runner_imports_local_detail_ready_without_planner_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-detail', route='needs_detail')
    seen: list[str] = []

    def fake_submit_detailer(_context, ask_command):
        seen.append(ask_command.target)
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""**task-detail-design.md**

Mode: `ready-check`; write surface: reply-only detail artifacts.

Design:
- Add `lab_code/approval_import.py`.
- Add `tests/test_approval_import.py`.

**brief-update-summary.md**

External approval import detail is now scoped to a small lab-local Python validator plus focused unittest coverage.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    def record_submit(_context, ask_command):
        seen.append(ask_command.target)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=(
                {
                    'job_id': f'job_{ask_command.target}',
                    'agent_name': ask_command.target,
                    'status': 'submitted',
                },
            ),
        )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=record_submit, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_detail_authority'
    assert second['task_status'] == 'detail_ready'
    assert second['next_owner'] == 'planner'
    assert second['next_activation'] == 'orchestrator'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-detail'))
    assert shown['task']['status'] == 'detail_ready'
    assert shown['task']['next_owner'] == 'planner'
    assert shown['task']['artifacts']['detail_design']['actor']['job_id'] == 'job_task_detailer'
    assert shown['task']['artifacts']['detail_summary']['actor']['job_id'] == 'job_task_detailer'
    assert shown['task']['artifacts']['detail_packet']['actor']['job_id'] == 'job_task_detailer'
    assert seen == ['task_detailer']


def test_loop_runner_imports_task_detailer_markdown_heading_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""## task-detail-design.md

# Task Detail Design

Task: `phase6b-l3-needs-detail`
Route: `needs_detail`

## Scope

This task validates the needs-detail route and must stop at detail_ready.

## Readiness Recommendation

detail_ready

## Macro Adjustment Request

None.

## brief-update-summary.md

# Brief Update Summary

The task-local detail is sufficient for the needs-detail route validation.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_detail_authority'
    assert second['task_status'] == 'detail_ready'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['status'] == 'detail_ready'
    assert shown['task']['next_owner'] == 'planner'
    design_path = project_root / shown['task']['artifacts']['detail_design']['path']
    assert '# Task Detail Design' in design_path.read_text(encoding='utf-8')
    assert 'Brief Update Summary' not in design_path.read_text(encoding='utf-8')


def test_loop_runner_imports_task_detailer_artifact_heading_fenced_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""Detail readiness recommendation: `detail_ready`

## Artifact: `task-detail-design.md`

```markdown
# Task Detail Design

The missing detail has been resolved without authorizing direct implementation.
```

## Artifact: `brief-update-summary.md`

```markdown
# Brief Update Summary

The task is now detailed enough for planner follow-up.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_detail_authority'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['status'] == 'detail_ready'
    design_path = project_root / shown['task']['artifacts']['detail_design']['path']
    design = design_path.read_text(encoding='utf-8')
    assert '# Task Detail Design' in design
    assert 'Brief Update Summary' not in design


@pytest.mark.parametrize(
    'stop_contract',
    (
        'Preserve terminal expectation detail_ready.',
        'Continue with terminal status detail_ready.',
    ),
)
def test_loop_runner_keeps_real_needs_detail_sequence_at_explicit_terminal_detail_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop_contract: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=f'# Task: phase6b-l3-needs-detail\nRoute: needs_detail\n{stop_contract}\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        assert "'status': 'detail_ready'" in ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert activated['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""Detail result: `local_detail_ready`
Detail readiness recommendation: `detail_ready`

## Artifact: `task-detail-design.md`
```markdown
# Detail Design
The missing task detail is resolved.
```

## Artifact: `brief-update-summary.md`
```markdown
# Detail Summary
The task is locally detail-ready.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    imported = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert imported['action'] == 'imported_task_detailer_detail_authority'
    assert imported['task_status'] == 'detail_ready'

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('explicit terminal detail_ready must not activate Planner or Orchestrator')

    settled = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert settled['loop_runner_status'] == 'idle'
    assert settled['reason'] == 'no_actionable_task'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['status'] == 'detail_ready'


def _prepare_root8_reset_detail_ready_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop_contract: str = 'Preserve terminal expectation detail_ready.',
):
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=(
            '# Task: phase6b-l3-needs-detail\n'
            'Route: needs_detail\n'
            f'{stop_contract}\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    for kind, filename, text in (
        (
            'task_packet',
            'root8-task-packet.md',
            f'# Task: phase6b-l3-needs-detail\nRoute: needs_detail\n{stop_contract}\n',
        ),
        ('execution_contract', 'root8-execution-contract.md', '# Execution Contract\nRoute: needs_detail\n'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, text)
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_2b89867387e4', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert activated['action'] == 'activated_task_detailer'
    _write_completion_snapshot(
        project_root,
        job_id='job_2b89867387e4',
        agent_name='task_detailer',
        reply="""Detail result: `local_detail_ready`
Detail readiness recommendation: `detail_ready`

## Artifact: `task-detail-design.md`
```markdown
# Detail Design
Resolved.
```

## Artifact: `brief-update-summary.md`
```markdown
# Detail Summary
Resolved.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )
    imported = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))
    assert imported['action'] == 'imported_task_detailer_detail_authority'
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='ready_for_orchestration',
            activation_reason='planner_task_packet_imported',
        ),
    )
    return project_root, context, command


def test_loop_runner_reconciles_root8_shaped_reset_detail_ready_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, context, command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('root8-shaped reset must reconcile without Planner or Orchestrator activation')

    reconciled = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert reconciled['action'] == 'reconciled_detail_ready'
    assert reconciled['task_status'] == 'detail_ready'
    assert reconciled['activation_reason'] == 'reconciled_detail_ready_stop_contract'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    for kind in ('detail_design', 'detail_summary', 'detail_packet'):
        artifact = shown['task']['artifacts'][kind]
        assert artifact['actor'] == {
            'source': 'loop_runner_role_output_import',
            'actor': 'loop_runner',
            'job_id': 'job_2b89867387e4',
        }
        assert artifact['source_path'].startswith('.ccb/runtime/role-output-imports/job_2b89867387e4/')

    settled = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert settled['loop_runner_status'] == 'idle'
    assert settled['reason'] == 'no_actionable_task'


@pytest.mark.parametrize(
    'stop_contract',
    (
        '1. > Expected stop: detail_ready.',
        'Task: other-task\nExpected stop: detail_ready.',
        'task_id: other-task\nExpected stop: detail_ready.',
        'Task: [other-task](tasks/other-task)\nExpected stop: detail_ready.',
        'task-id: other-task\nExpected stop: detail_ready.',
        'Task: <other-task>\nExpected stop: detail_ready.',
    ),
)
def test_real_provenance_record_with_unsafe_stop_corpus_never_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop_contract: str,
) -> None:
    project_root, context, command = _prepare_root8_reset_detail_ready_task(
        tmp_path,
        monkeypatch,
        stop_contract=stop_contract,
    )
    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is None or candidate['runner_action'] != 'reconcile_detail_ready'

    def fake_submit(_context, ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit, plan_task=plan_task),
    )
    assert payload['action'] != 'reconciled_detail_ready'
    assert project_root.exists()


@pytest.mark.parametrize(
    'scope_label',
    (
        'Task: [phase6b-l3-needs-detail](tasks/phase6b-l3-needs-detail)',
        'task-id: `phase6b-l3-needs-detail`',
        'Task: <phase6b-l3-needs-detail>',
        'Task: **phase6b-l3-needs-detail**',
    ),
)
def test_real_provenance_record_with_wrapped_current_scope_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_label: str,
) -> None:
    _project_root, context, command = _prepare_root8_reset_detail_ready_task(
        tmp_path,
        monkeypatch,
        stop_contract=f'{scope_label}\nExpected stop: detail_ready.',
    )
    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is not None
    assert candidate['runner_action'] == 'reconcile_detail_ready'

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('an exact current-task scope label must reconcile without activation')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert payload['action'] == 'reconciled_detail_ready'


@pytest.mark.parametrize('kind', ('task_packet', 'execution_contract', 'orchestration_notes'))
def test_post_detail_contract_revision_change_rejects_old_detail_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    project_root, context, command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    source = project_root / 'drafts' / f'changed-{kind}.md'
    if kind == 'task_packet':
        _write(source, '# Task: L3 needs-detail\nRoute: needs_detail\nPreserve terminal expectation detail_ready.\nUpdated.\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    elif kind == 'execution_contract':
        _write(source, '# Execution Contract\nPreserve terminal expectation detail_ready.\nUpdated.\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    else:
        _write(source, 'route: needs_detail\nPreserve terminal expectation detail_ready.\nUpdated.\n')
        _import_orchestration_notes(
            context,
            project_root,
            task_id='phase6b-l3-needs-detail',
            route='needs_detail',
            text=source.read_text(encoding='utf-8'),
        )

    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is None or candidate['runner_action'] != 'reconcile_detail_ready'

    def fake_submit(_context, ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_orchestrator', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit, plan_task=plan_task),
    )
    assert payload['action'] != 'reconciled_detail_ready'


@pytest.mark.parametrize('kind', ('task_packet', 'execution_contract', 'orchestration_notes'))
def test_real_task_detailer_reimport_restores_authority_at_current_contract_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    project_root, context, command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    before = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))['task']
    assert {
        before['artifacts'][detail_kind]['task_revision']
        for detail_kind in ('detail_design', 'detail_summary', 'detail_packet')
    } == {before['task_revision']}
    source = project_root / 'drafts' / f'redetail-{kind}.md'
    if kind == 'task_packet':
        _write(source, '# Task: phase6b-l3-needs-detail\nRoute: needs_detail\nPreserve terminal expectation detail_ready.\nV2.\n')
        plan_task(
            context,
            SimpleNamespace(action='task-artifact', task_id='phase6b-l3-needs-detail', artifact_kind=kind, file_path=str(source)),
        )
    elif kind == 'execution_contract':
        _write(source, '# Execution Contract\nPreserve terminal expectation detail_ready.\nV2.\n')
        plan_task(
            context,
            SimpleNamespace(action='task-artifact', task_id='phase6b-l3-needs-detail', artifact_kind=kind, file_path=str(source)),
        )
    else:
        _import_orchestration_notes(
            context,
            project_root,
            task_id='phase6b-l3-needs-detail',
            route='needs_detail',
            text='route: needs_detail\nPreserve terminal expectation detail_ready.\nV2.\n',
        )
    changed = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))['task']
    assert changed['task_revision'] == before['task_revision'] + 1

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_re_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    re_detail_command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id='phase6b-l3-needs-detail',
        timeout_s=11.0,
        json_output=True,
    )
    activated = loop_runner_once(
        context,
        re_detail_command,
        services=SimpleNamespace(
            submit_ask=fake_submit_detailer,
            plan_task=plan_task,
            consume_activation_role_output=lambda *_args: None,
            resume_multi_workgroup_scheduler=lambda *_args, **_kwargs: None,
        ),
    )
    assert activated['action'] == 'activated_task_detailer'
    _write_completion_snapshot(
        project_root,
        job_id='job_re_detailer',
        agent_name='task_detailer',
        reply="""Detail result: `local_detail_ready`
Detail readiness recommendation: `detail_ready`

## Artifact: `task-detail-design.md`
```markdown
# Detail Design V2
```

## Artifact: `brief-update-summary.md`
```markdown
# Detail Summary V2
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )
    imported = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(
            project=None,
            once=True,
            role_job_id='job_re_detailer',
            consume_role_output=True,
            json_output=True,
        ),
        services=SimpleNamespace(plan_task=plan_task),
    )
    assert imported['action'] == 'imported_task_detailer_detail_authority'
    refreshed = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))['task']
    assert {
        refreshed['artifacts'][detail_kind]['task_revision']
        for detail_kind in ('detail_design', 'detail_summary', 'detail_packet')
    } == {refreshed['task_revision']}
    assert detail_ready_reconcile_authority(refreshed, project_root=project_root) is None

    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='ready_for_orchestration',
            activation_reason='planner_reset_after_refreshed_detail',
        ),
    )
    reopened = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))['task']
    assert detail_ready_reconcile_authority(reopened, project_root=project_root) is not None
    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is not None
    assert candidate['runner_action'] == 'reconcile_detail_ready'


@pytest.mark.parametrize('tampered_kind', ('task_packet', 'execution_contract', 'orchestration_notes'))
def test_detail_ready_stop_rejects_unrecorded_contract_file_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_kind: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    for kind, filename, text in (
        ('task_packet', 'recorded-task-packet.md', '# Task: L3\nRoute: needs_detail\n'),
        ('execution_contract', 'recorded-execution-contract.md', '# Execution Contract\nRoute: needs_detail\n'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, text)
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact', task_id='phase6b-l3-needs-detail', artifact_kind=kind, file_path=str(source)),
        )
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')
    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.md'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact', task_id='phase6b-l3-needs-detail', artifact_kind=kind, file_path=str(source)),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    path = project_root / shown['task']['artifacts'][tampered_kind]['path']
    path.write_text('Task: other-task\nExpected stop: detail_ready.\n', encoding='utf-8')

    def fake_submit_planner(_context, ask_command):
        assert ask_command.target == 'planner'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_planner, plan_task=plan_task),
    )
    assert payload['action'] == 'activated_planner'


def test_plan_task_detail_ready_reconcile_is_idempotent_for_same_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, context, _command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is not None
    record = candidate['record']
    authority = detail_ready_reconcile_authority(record, project_root=project_root)
    assert authority is not None
    reconcile_command = SimpleNamespace(
        action='task-reconcile-detail-ready',
        task_id='phase6b-l3-needs-detail',
        expected_status=record['status'],
        expected_owner=record['owner'],
        expected_next_owner=record['next_owner'],
        expected_current_loop=record['current_loop'],
        expected_task_revision=record['task_revision'],
        expected_state_version=record['state_version'],
        expected_activation_reason=record['activation_reason'],
        expected_authority_digest=authority['authority_digest'],
    )

    first = plan_task(context, reconcile_command)
    first_updated_at = first['task']['updated_at']
    second = plan_task(context, reconcile_command)

    assert first['idempotent'] is False
    assert second['idempotent'] is True
    assert second['task']['owner'] == 'plan_reviewer'
    assert second['task']['next_owner'] == 'planner'
    assert second['task']['current_loop'] is None
    assert second['task']['activation_reason'] == 'reconciled_detail_ready_stop_contract'
    assert second['task']['updated_at'] == first_updated_at

    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='ready_for_orchestration',
            activation_reason='managed_post_reconcile_reset',
        ),
    )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='managed_post_reconcile_restore',
        ),
    )
    with pytest.raises(ValueError, match='stale detail_ready reconciliation'):
        plan_task(context, reconcile_command)


def test_plan_task_detail_ready_reconcile_replay_rejects_tampered_post_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, context, _command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is not None
    record = candidate['record']
    authority = detail_ready_reconcile_authority(record, project_root=project_root)
    assert authority is not None
    reconcile_command = SimpleNamespace(
        action='task-reconcile-detail-ready',
        task_id='phase6b-l3-needs-detail',
        expected_status=record['status'],
        expected_owner=record['owner'],
        expected_next_owner=record['next_owner'],
        expected_current_loop=record['current_loop'],
        expected_task_revision=record['task_revision'],
        expected_state_version=record['state_version'],
        expected_activation_reason=record['activation_reason'],
        expected_authority_digest=authority['authority_digest'],
    )
    plan_task(context, reconcile_command)
    index_path = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    index['tasks'][0]['owner'] = 'worker'
    _write_json(index_path, index)

    with pytest.raises(ValueError, match='stale detail_ready reconciliation'):
        plan_task(context, reconcile_command)


@pytest.mark.parametrize('max_steps', (1, 2, 3))
def test_loop_runner_auto_reconciles_detail_ready_without_step_limit_or_agent_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_steps: int,
) -> None:
    project_root, _context, _command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        max_steps=max_steps,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('reconcile auto sequence must not submit Planner or Orchestrator')

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )

    assert payload['action'] == 'auto_runner_finished'
    assert payload['final_action'] == 'reconciled_detail_ready'
    assert [step['action'] for step in payload['steps']] == ['reconciled_detail_ready']
    settled = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(project=None, once=True, json_output=True),
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert settled['loop_runner_status'] == 'idle'


@pytest.mark.parametrize(
    'mutation',
    (
        'missing_artifact',
        'non_needs_detail',
        'bound_loop',
        'no_contract',
        'cli_actor',
        'missing_job',
        'mixed_job',
        'wrong_source',
        'wrong_actor',
        'noncanonical_path',
        'wrong_detail_revision',
        'missing_completion_authority',
        'sha_mismatch',
    ),
)
def test_loop_runner_does_not_reconcile_incomplete_or_nonmatching_detail_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    project_root, context, _command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    index_path = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    record = index['tasks'][0]
    if mutation == 'missing_artifact':
        record['artifacts'].pop('detail_packet')
    elif mutation == 'non_needs_detail':
        record['artifacts']['orchestration_notes']['orchestrator_route'] = 'direct_execution'
    elif mutation == 'bound_loop':
        record['current_loop'] = 'lp-stale'
    elif mutation == 'no_contract':
        packet = project_root / record['artifacts']['task_packet']['path']
        packet.write_text('# Task: ordinary detail work\nRoute: needs_detail\n', encoding='utf-8')
        record['artifacts']['task_packet']['sha256'] = hashlib.sha256(packet.read_bytes()).hexdigest()
    elif mutation == 'cli_actor':
        record['artifacts']['detail_packet']['actor'] = {'source': 'cli', 'actor': 'user'}
    elif mutation == 'missing_job':
        record['artifacts']['detail_packet']['actor'].pop('job_id')
    elif mutation == 'mixed_job':
        record['artifacts']['detail_packet']['actor']['job_id'] = 'job_other_detailer'
    elif mutation == 'wrong_source':
        record['artifacts']['detail_packet']['actor']['source'] = 'manual_import'
    elif mutation == 'wrong_actor':
        record['artifacts']['detail_packet']['actor']['actor'] = 'task_detailer'
    elif mutation == 'noncanonical_path':
        record['artifacts']['detail_packet']['path'] = record['artifacts']['detail_packet']['source_path']
    elif mutation == 'wrong_detail_revision':
        record['artifacts']['detail_packet']['task_revision'] += 1
    elif mutation == 'missing_completion_authority':
        (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').unlink()
    else:
        record['artifacts']['detail_packet']['sha256'] = '0' * 64
    _write_json(index_path, index)

    candidate = find_first_actionable_task(context, task_id='phase6b-l3-needs-detail')
    assert candidate is None or candidate['runner_action'] != 'reconcile_detail_ready'


@pytest.mark.parametrize(
    'mutation',
    ('status', 'loop', 'route', 'revision', 'owner', 'reason', 'artifact', 'contract'),
)
def test_loop_runner_reconcile_fails_closed_when_selected_authority_becomes_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    project_root, context, command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    index_path = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json'

    def stale_plan_task(call_context, task_command):
        if task_command.action != 'task-reconcile-detail-ready':
            return plan_task(call_context, task_command)
        index = json.loads(index_path.read_text(encoding='utf-8'))
        record = index['tasks'][0]
        if mutation == 'status':
            record['status'] = 'draft'
            record['owner'] = 'planner'
            record['next_owner'] = 'planner'
        elif mutation == 'loop':
            record['current_loop'] = 'lp-stale'
        elif mutation == 'route':
            record['artifacts']['orchestration_notes']['orchestrator_route'] = 'direct_execution'
        elif mutation == 'revision':
            record['task_revision'] += 1
        elif mutation == 'owner':
            record['owner'] = 'planner'
        elif mutation == 'reason':
            record['activation_reason'] = 'rewritten_after_selection'
        elif mutation == 'artifact':
            path = project_root / record['artifacts']['detail_packet']['path']
            path.write_text('replaced detail packet\n', encoding='utf-8')
        else:
            path = project_root / record['artifacts']['task_packet']['path']
            path.write_text('# Task: contract removed\nRoute: needs_detail\n', encoding='utf-8')
            record['artifacts']['task_packet']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        _write_json(index_path, index)
        return plan_task(call_context, task_command)

    with pytest.raises(ValueError, match='stale detail_ready reconciliation'):
        loop_runner_once(
            context,
            command,
            services=SimpleNamespace(plan_task=stale_plan_task),
        )


def test_loop_runner_reconcile_rejects_same_second_status_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, context, command = _prepare_root8_reset_detail_ready_task(tmp_path, monkeypatch)
    before = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))['task']
    monkeypatch.setattr(plan_tasks_module, '_utc_now', lambda: before['updated_at'])

    def advancing_plan_task(call_context, task_command):
        if task_command.action != 'task-reconcile-detail-ready':
            return plan_task(call_context, task_command)
        updated = plan_task(
            call_context,
            SimpleNamespace(
                action='task-status',
                task_id='phase6b-l3-needs-detail',
                status='ready_for_orchestration',
                activation_reason='same_second_self_transition',
                expected_task_revision=before['task_revision'],
            ),
        )
        assert updated['task']['updated_at'] == before['updated_at']
        assert updated['task']['state_version'] == before['state_version'] + 1
        return plan_task(call_context, task_command)

    with pytest.raises(ValueError, match='stale detail_ready reconciliation'):
        loop_runner_once(
            context,
            command,
            services=SimpleNamespace(plan_task=advancing_plan_task),
        )


@pytest.mark.parametrize(
    'non_contract',
    (
        'detail_ready is not the terminal expectation.',
        'Do not change terminal expectations.',
        'Do not preserve terminal expectation detail_ready.',
    ),
)
def test_loop_runner_does_not_treat_negated_or_generic_terminal_text_as_detail_ready_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    non_contract: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=f'# Task: L3 needs-detail\nRoute: needs_detail\n{non_contract}\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.md'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )

    def fake_submit_planner(_context, ask_command):
        assert ask_command.target == 'planner'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_planner, plan_task=plan_task),
    )
    assert payload['action'] == 'activated_planner'
    assert payload['reason'] == 'detail_ready_task'


def test_loop_runner_and_plan_selection_reject_same_cross_artifact_stop_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text='# Task: L3\nRoute: needs_detail\nExpected stop: detail_ready.\n',
        execution_contract_text='# Execution Contract\nDo not stop at detail_ready.\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert "Detail-ready stop contract: None" in ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert activated['action'] == 'activated_task_detailer'
    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.md'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )

    def fake_submit_planner(_context, ask_command):
        assert ask_command.target == 'planner'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_planner, plan_task=plan_task),
    )
    assert payload['action'] == 'activated_planner'


@pytest.mark.parametrize(
    'legacy_contract',
    (
        'Expected controller-visible task outcome is detail_ready.',
        'The task stops at detail_ready.',
    ),
)
def test_loop_runner_preserves_legacy_detail_ready_stop_contract_grammar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_contract: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=f'# Task: phase6b-l3-needs-detail\nRoute: needs_detail\n{legacy_contract}\n',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.md'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('legacy explicit detail_ready stop must remain settled')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert payload['loop_runner_status'] == 'idle'


def test_loop_runner_task_detailer_artifact_heading_needs_clarification_is_not_detail_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='external-sync-contract')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='external-sync-contract', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""Detail readiness recommendation: `needs_clarification`

## Artifact: `task-detail-design.md`

```markdown
# Task Detail Design

External API, auth, data mapping, and sync policy are not specified.
```

## Artifact: `brief-update-summary.md`

```markdown
# Brief Update Summary

Clarification is still required before implementation.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"needs_clarification","readiness":"needs_clarification","global_impact":"bounded"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_clarification_authority'
    assert second['loop_runner_status'] == 'paused'
    assert second['task_status'] == 'needs_clarification'
    assert second['next_owner'] == 'task_detailer'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='external-sync-contract'))
    assert shown['task']['status'] == 'needs_clarification'
    assert shown['task']['owner'] == 'task_detailer'
    assert shown['task']['next_owner'] == 'task_detailer'
    assert shown['task']['artifacts']['detail_design']['actor']['job_id'] == 'job_task_detailer'
    design_path = project_root / shown['task']['artifacts']['detail_design']['path']
    assert 'External API, auth' in design_path.read_text(encoding='utf-8')


def test_loop_runner_imports_task_detailer_detail_readiness_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""## task-detail-design.md

# L3 Provider Readiness Detail Design

Task: `phase6b-l3-needs-detail`
Recommendation: `detail_ready`

## Resolved Scope

Create only `lab_docs/l3_provider_readiness.md`.

## brief-update-summary.md

L3 is detail-ready. No macro adjustment is required.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_detail_authority'
    assert second['task_status'] == 'detail_ready'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['status'] == 'detail_ready'


def test_loop_runner_imports_task_detailer_controller_expected_stop_detail_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=(
                '# Task: phase6b-l3-needs-detail\n'
            'Route: needs_detail\n'
            'Expected stop: detail_ready\n'
            'No worker implementation is authorized for this validation case.\n'
        ),
        execution_contract_text=(
            '# Execution Contract\n'
            'Route: needs_detail\n'
            'Readiness: needs_clarification\n'
            'The controller must stop this case at detail_ready.\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(
        context,
        project_root,
        task_id='phase6b-l3-needs-detail',
        route='needs_detail',
        text='route: needs_detail\nscript-owned route authority must stop at detail_ready\n',
    )

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        assert 'Detail-ready stop contract' in ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""**task-detail-design.md**
```markdown
# Task Detail Design: phase6b-l3-needs-detail

## Recommendation
detail_readiness: needs_clarification
controller_expected_stop: detail_ready

## Design
Do not authorize implementation for this task. Preserve the route as `needs_detail`.
```

**brief-update-summary.md**
```markdown
# Brief Update Summary

This remains a needs-detail validation case with a controller-level detail_ready stop.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )

    assert second['action'] == 'imported_task_detailer_detail_authority'
    assert second['task_status'] == 'detail_ready'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['status'] == 'detail_ready'
    assert shown['task']['next_owner'] == 'planner'


def test_loop_runner_task_detailer_blocked_reply_does_not_reactivate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')
    submitted: list[str] = []

    def fake_submit_detailer(_context, ask_command):
        submitted.append(ask_command.target)
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""## task-detail-design.md

Design exists, but this activation has no explicit detail-ready stop contract.
readiness: needs_clarification
controller_expected_stop: detail_ready

## brief-update-summary.md

Summary exists.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"needs_clarification","readiness":"needs_clarification","global_impact":"bounded"}
```
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert second['action'] == 'imported_task_detailer_clarification_authority'
    assert second['loop_runner_status'] == 'paused'
    assert second['task_status'] == 'needs_clarification'
    assert second['next_owner'] == 'task_detailer'

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('needs_clarification task_detailer output must not submit a duplicate task_detailer ask')

    third = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert third['action'] == 'paused'
    assert third['reason'] == 'needs_clarification'
    assert third['next_owner'] == 'task_detailer'
    assert submitted == ['task_detailer']


def test_loop_runner_task_detailer_terminal_blocker_imports_task_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='external-contract-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='external-contract-detail', route='needs_detail')
    submitted: list[str] = []

    def fake_submit_detailer(_context, ask_command):
        submitted.append(ask_command.target)
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""detail readiness recommendation: blocked

**task-detail-design.md**

The task cannot be refined into implementation until the approved external API contract exists.

**brief-update-summary.md**

The task remains blocked on missing external integration details.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"blocked","readiness":"blocked","global_impact":"none"}
```

## Worker Handoff

Do not dispatch implementation. Obtain approved API/auth/source evidence first.
""",
    )

    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert second['action'] == 'imported_task_detailer_blocker_authority'
    assert second['task_status'] == 'blocked'
    assert second['next_owner'] == 'terminal'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='external-contract-detail'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['next_owner'] == 'terminal'
    artifacts = shown['task']['artifacts']
    assert artifacts['blocker_evidence']['actor']['job_id'] == 'job_task_detailer'
    assert artifacts['detail_design']['actor']['job_id'] == 'job_task_detailer'
    assert artifacts['detail_summary']['actor']['job_id'] == 'job_task_detailer'
    assert artifacts['detail_packet']['actor']['job_id'] == 'job_task_detailer'

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('terminal task_detailer blocker must not submit a duplicate task_detailer ask')

    third = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit, plan_task=plan_task),
    )
    assert third['action'] in {'role_output_already_consumed', 'blocked'}
    assert submitted == ['task_detailer']


def test_loop_runner_skips_duplicate_task_detailer_output_after_detail_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='phase6b-l3-needs-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    first = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert first['action'] == 'activated_task_detailer'

    _write_completion_snapshot(
        project_root,
        job_id='job_task_detailer',
        agent_name='task_detailer',
        reply="""**task-detail-design.md**

Original detail design.

**brief-update-summary.md**

Original summary.

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )
    second = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert second['action'] == 'imported_task_detailer_detail_authority'

    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-duplicate-detailer.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_task_detailer_activation',
            'activation_id': 'act-duplicate-detailer',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'task_id': 'phase6b-l3-needs-detail',
            'task_status': 'ready_for_orchestration',
            'action': 'activate_task_detailer',
            'reason_for_activation': 'orchestrator_route_needs_detail',
            'ask': {
                'target': 'task_detailer',
                'job_id': 'job_duplicate_task_detailer',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_duplicate_task_detailer',
        agent_name='task_detailer',
        reply="""**task-detail-design.md**

Duplicate detail design that must not replace authority.

**brief-update-summary.md**

Duplicate summary.

**detail-packet.md**

Readiness recommendation: `detail_ready`
""",
    )

    def fake_submit_after_detail_ready(_context, ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': f'job_{ask_command.target}', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    third = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_after_detail_ready, plan_task=plan_task),
    )

    assert third['action'] != 'imported_task_detailer_detail_authority'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    assert shown['task']['artifacts']['detail_design']['actor']['job_id'] == 'job_task_detailer'
    detail_design = project_root / shown['task']['artifacts']['detail_design']['path']
    assert 'Original detail design' in detail_design.read_text(encoding='utf-8')
    trace = (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8')
    assert 'job_duplicate_task_detailer' not in trace


def test_loop_runner_unscoped_needs_detail_route_preempts_prior_replan_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-detail')
    _add_plan_task_record(
        project_root,
        task_id='task-macro',
        status='replan_required',
        next_owner='planner',
        activation_reason='macro_adjustment_request',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-detail', route='needs_detail')
    seen: list[str] = []

    def fake_submit_detailer(_context, ask_command):
        seen.append(ask_command.target)
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_task_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('needs_detail task must not run execution')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_detailer,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_task_detailer'
    assert payload['task_id'] == 'task-detail'
    assert payload['reason'] == 'orchestrator_route_needs_detail'
    assert seen == ['task_detailer']


@pytest.mark.parametrize(
    ('route', 'expected_action', 'expected_reason', 'expected_status', 'expected_owner', 'expected_artifact', 'expected_next_activation'),
    (
        (
            'macro_adjustment_request',
            'imported_macro_adjustment_request',
            'orchestrator_route_macro_adjustment_request',
            'replan_required',
            'planner',
            'macro_adjustment_request',
            'planner',
        ),
        (
            'blocked',
            'imported_blocker_evidence',
            'orchestrator_route_blocked',
            'blocked',
            'terminal',
            'blocker_evidence',
            'terminal',
        ),
    ),
)
def test_loop_runner_unscoped_macro_and_blocked_routes_finalize_before_prior_replan_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    expected_action: str,
    expected_reason: str,
    expected_status: str,
    expected_owner: str,
    expected_artifact: str,
    expected_next_activation: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = f'task-{route.replace("_", "-")}'
    _add_ready_plan_task(project_root, task_id=task_id)
    _add_plan_task_record(
        project_root,
        task_id='task-prior-macro',
        status='replan_required',
        next_owner='planner',
        activation_reason='macro_adjustment_request',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id=task_id, route=route)

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('route continuation must not activate prior replan planner task')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('route continuation must not run execution')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == expected_action
    assert payload['task_id'] == task_id
    assert payload['reason'] == expected_reason
    assert payload['task_status'] == expected_status
    assert payload['next_owner'] == expected_owner
    assert payload['next_activation'] == expected_next_activation
    assert payload['import']['status'] == expected_status
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['status'] == expected_status
    assert shown['task']['next_owner'] == expected_owner
    assert expected_artifact in shown['task']['artifacts']
    prior = plan_task(context, SimpleNamespace(action='task-show', task_id='task-prior-macro'))
    assert prior['task']['status'] == 'replan_required'


@pytest.mark.parametrize(
    ('route', 'expected_action', 'expected_reason', 'expected_status', 'expected_owner', 'expected_artifact', 'expected_next_activation'),
    (
        (
            'macro_adjustment_request',
            'imported_macro_adjustment_request',
            'orchestrator_route_macro_adjustment_request',
            'replan_required',
            'planner',
            'macro_adjustment_request',
            'planner',
        ),
        (
            'blocked',
            'imported_blocker_evidence',
            'orchestrator_route_blocked',
            'blocked',
            'terminal',
            'blocker_evidence',
            'terminal',
        ),
    ),
)
def test_loop_runner_macro_and_blocked_routes_finalize_without_mounting_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    expected_action: str,
    expected_reason: str,
    expected_status: str,
    expected_owner: str,
    expected_artifact: str,
    expected_next_activation: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = f'task-{route.replace("_", "-")}'
    _add_ready_plan_task(project_root, task_id=task_id)
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id=task_id, route=route)

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError(f'{route} route must not ask detailer, worker, or reviewer')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError(f'{route} route must not run the fixed bridge')

    def forbidden_topology_dispatch(*_args, **_kwargs):
        raise AssertionError(f'{route} route must not execute topology dispatch')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            loop_run_once=forbidden_loop_run_once,
            topology_dispatch=forbidden_topology_dispatch,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == expected_action
    assert payload['reason'] == expected_reason
    assert payload['task_status'] == expected_status
    assert payload['next_owner'] == expected_owner
    assert payload['next_activation'] == expected_next_activation
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['status'] == expected_status
    assert shown['task']['next_owner'] == expected_owner
    assert shown['task']['current_loop'] is None
    assert shown['task']['artifacts']['orchestration_notes']['orchestrator_route'] == route
    artifact = shown['task']['artifacts'][expected_artifact]
    assert artifact['actor'] == {'source': 'loop_runner/script-owned', 'actor': 'loop_runner'}
    notes = shown['task']['artifacts']['orchestration_notes']
    artifact_text = (project_root / artifact['path']).read_text(encoding='utf-8')
    if route == 'macro_adjustment_request':
        evidence = json.loads(artifact_text)
        assert evidence['task_id'] == task_id
        assert evidence['route'] == route
        assert evidence['source'] == 'loop_runner/script-owned'
        assert evidence['reason'] == expected_reason
        assert evidence['orchestration_notes']['path'] == notes['path']
        assert evidence['orchestration_notes']['sha256'] == notes['sha256']
    else:
        assert f'task_id: {task_id}' in artifact_text
        assert 'route: blocked' in artifact_text
        assert 'source: loop_runner/script-owned' in artifact_text
        assert f'reason: {expected_reason}' in artifact_text
        assert f'orchestration_notes_path: {notes["path"]}' in artifact_text
        assert f'orchestration_notes_sha256: {notes["sha256"]}' in artifact_text
    assert 'round_summary' not in shown['task']['artifacts']


@pytest.mark.parametrize(
    ('first_route', 'second_route'),
    (
        ('macro_adjustment_request', 'blocked'),
        ('blocked', 'macro_adjustment_request'),
    ),
)
def test_loop_runner_auto_continues_after_macro_and_blocked_route_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_route: str,
    second_route: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)

    def ready_artifacts(task_id: str) -> dict[str, dict[str, object]]:
        task_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / task_id
        artifacts: dict[str, dict[str, object]] = {}
        for kind, filename, text in (
            ('task_packet', 'task_packet.md', f'task packet for {task_id}\n'),
            ('execution_contract', 'execution_contract.md', f'execution contract for {task_id}\n'),
        ):
            path = task_root / filename
            _write(path, text)
            artifacts[kind] = {
                'kind': kind,
                'artifact_kind': kind,
                'path': str(path.relative_to(project_root)),
                'artifact_path': str(path.relative_to(project_root)),
                'source_path': str(path.relative_to(project_root)),
                'sha256': 'test',
                'bytes': len(text.encode('utf-8')),
                'imported_at': '2026-06-27T00:00:00Z',
            }
        return artifacts

    first_task = f'task-{first_route.replace("_", "-")}-first'
    second_task = f'task-{second_route.replace("_", "-")}-second'
    _add_ready_plan_task(project_root, task_id=first_task)
    _add_plan_task_record(
        project_root,
        task_id=second_task,
        status='ready_for_orchestration',
        artifacts=ready_artifacts(second_task),
        next_owner='orchestrator',
        activation_reason='test_ready_for_orchestration',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=False,
        auto=True,
        max_steps=2,
        poll_interval_s=0.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id=first_task, route=first_route)
    _import_orchestration_notes(context, project_root, task_id=second_task, route=second_route)

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('macro/blocked route finalization must not activate planner, worker, or reviewer')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('macro/blocked route finalization must not run execution')

    payload = loop_runner_auto(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
            sleep=lambda _seconds: None,
        ),
    )

    action_by_route = {
        'macro_adjustment_request': 'imported_macro_adjustment_request',
        'blocked': 'imported_blocker_evidence',
    }
    assert payload['action'] == 'auto_runner_step_limit_reached'
    assert [step['action'] for step in payload['steps']] == [
        action_by_route[first_route],
        action_by_route[second_route],
    ]
    assert [step['loop_runner_status'] for step in payload['steps']] == ['ok', 'ok']
    first = plan_task(context, SimpleNamespace(action='task-show', task_id=first_task))
    second = plan_task(context, SimpleNamespace(action='task-show', task_id=second_task))
    expected_status = {'macro_adjustment_request': 'replan_required', 'blocked': 'blocked'}
    assert first['task']['status'] == expected_status[first_route]
    assert second['task']['status'] == expected_status[second_route]


def test_loop_runner_task_scoped_macro_route_ignores_prior_detail_ready_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-macro')
    _add_plan_task_record(
        project_root,
        task_id='task-prior-detail',
        status='detail_ready',
        next_owner='planner',
        activation_reason='detail_ready',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id='task-macro',
        timeout_s=11.0,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='task-macro', route='macro_adjustment_request')

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('task-scoped macro runner must not activate planner for another task')

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('macro route must not run the fixed bridge')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=forbidden_submit_ask,
            loop_run_once=forbidden_loop_run_once,
            plan_task=plan_task,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_macro_adjustment_request'
    assert payload['task_id'] == 'task-macro'
    assert payload['reason'] == 'orchestrator_route_macro_adjustment_request'
    assert payload['task_status'] == 'replan_required'
    assert payload['next_owner'] == 'planner'
    assert payload['next_activation'] == 'planner'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-macro'))
    assert shown['task']['status'] == 'replan_required'
    assert 'macro_adjustment_request' in shown['task']['artifacts']
    prior = plan_task(context, SimpleNamespace(action='task-show', task_id='task-prior-detail'))
    assert prior['task']['status'] == 'detail_ready'
    assert 'round_summary' not in prior['task']['artifacts']


def test_loop_runner_once_does_not_infer_pass_without_round_checker_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_legacy_ready_plan_task(project_root, task_id='task-runner')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_loop_run_once(_context, run_command, _services):
        loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / run_command.loop_id
        loop_dir.mkdir(parents=True, exist_ok=True)
        round_path = loop_dir / 'round.json'
        payload = {
            'schema_version': 1,
            'record_type': 'ccb_loop_run_once_round',
            'loop_run_status': 'ok',
            'loop_id': run_command.loop_id,
            'task_id': run_command.task_id,
            'round_checker': {'reply': 'round checker completed without a machine result line\n'},
            'paths': {'round': str(round_path)},
        }
        _write(round_path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        return payload

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(loop_run_once=fake_loop_run_once, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['round_result'] == 'blocked'
    assert payload['round_result_source'] == 'missing_round_checker_result'
    assert payload['task_status'] == 'blocked'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-runner'))
    assert shown['task']['status'] == 'blocked'
    assert shown['task']['artifacts']['round_summary']['round_result'] == 'blocked'


def test_loop_runner_once_rejects_unknown_round_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_legacy_ready_plan_task(project_root, task_id='task-runner')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_loop_run_once(_context, run_command, _services):
        loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / run_command.loop_id
        loop_dir.mkdir(parents=True, exist_ok=True)
        round_path = loop_dir / 'round.json'
        payload = {
            'schema_version': 1,
            'record_type': 'ccb_loop_run_once_round',
            'loop_run_status': 'ok',
            'loop_id': run_command.loop_id,
            'task_id': run_command.task_id,
            'round_checker': {'reply': 'round result: mystery\n'},
            'paths': {'round': str(round_path)},
        }
        _write(round_path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
        return payload

    with pytest.raises(RuntimeError, match="unknown round result 'mystery'"):
        loop_runner_once(
            context,
            command,
            services=SimpleNamespace(loop_run_once=fake_loop_run_once, plan_task=plan_task),
        )


def test_loop_runner_once_returns_idle_when_no_ready_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(project=None, once=True, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace())

    assert payload['loop_runner_status'] == 'idle'
    assert payload['reason'] == 'no_actionable_task'


def test_loop_runner_once_activates_planner_for_draft_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_plan_task_record(project_root, task_id='task-draft', status='draft')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    def fake_submit_ask(_context, ask_command):
        seen['target'] = ask_command.target
        seen['sender'] = ask_command.sender
        seen['task_id'] = ask_command.task_id
        seen['artifact_request'] = ask_command.artifact_request
        seen['inline_request'] = ask_command.inline_request
        seen['message'] = ask_command.message
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    def forbidden_loop_run_once(*_args, **_kwargs):
        raise AssertionError('draft task must not start execution')

    def forbidden_clear_agent_context(*_args, **_kwargs):
        raise AssertionError('planner is a long-lived context role and must not be cleared before activation')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            clear_agent_context=forbidden_clear_agent_context,
            loop_run_once=forbidden_loop_run_once,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner'
    assert payload['reason'] == 'draft_task'
    assert payload['task_id'] == 'task-draft'
    assert payload['next_owner'] == 'planner'
    assert payload['ask']['job_id'] == 'job_planner'
    assert seen['target'] == 'planner'
    assert seen['sender'] == 'system'
    assert seen['artifact_request'] is False
    assert seen['inline_request'] is True
    assert 'Status: draft' in str(seen['message'])
    assert 'Optional machine import bundle' not in str(seen['message'])
    assert 'ccb.loop.planner_artifact_bundle/v1' not in str(seen['message'])
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['task_id'] == 'task-draft'
    assert activation['ask']['job_id'] == 'job_planner'
    assert 'freshness' not in activation
    assert 'freshness' not in payload
    assert activation['script_write_rules']
    script_write_rules = '\n'.join(str(rule) for rule in activation['script_write_rules'])
    assert 'Reply only; do not run ccb, ccb_test, artifact import commands, or wrapper commands.' in script_write_rules
    assert 'Supervisor/runner scripts own authoritative writes and route/status imports.' in script_write_rules
    assert 'ccb plan task-artifact' not in script_write_rules
    assert 'ccb plan task-status' not in script_write_rules
    assert 'Use ccb plan' not in script_write_rules


def test_loop_runner_once_activates_plan_reviewer_without_immaculate_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'task-review'
    artifacts: dict[str, dict[str, object]] = {}
    for kind, filename in (
        ('requirements', 'requirements.md'),
        ('acceptance', 'acceptance-criteria.md'),
        ('verification', 'verification-contract.md'),
        ('handoff', 'handoff.md'),
    ):
        path = task_root / filename
        _write(path, f'{kind} text\n')
        artifacts[kind] = {
            'kind': kind,
            'path': str(path.relative_to(project_root)),
            'source_path': str(path.relative_to(project_root)),
            'sha256': 'test',
            'bytes': len(f'{kind} text\n'.encode('utf-8')),
            'imported_at': '2026-06-27T00:00:00Z',
        }
    _add_plan_task_record(project_root, task_id='task-review', status='draft', artifacts=artifacts)
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    seen: dict[str, object] = {}

    def fake_submit_ask(_context, ask_command):
        seen['target'] = ask_command.target
        seen['sender'] = ask_command.sender
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_plan_reviewer', 'agent_name': 'plan_reviewer', 'status': 'submitted'},),
        )

    def forbidden_clear_agent_context(*_args, **_kwargs):
        raise AssertionError('plan_reviewer activation must not clear task_detailer or unrelated agents')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            clear_agent_context=forbidden_clear_agent_context,
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_plan_reviewer'
    assert payload['ask']['job_id'] == 'job_plan_reviewer'
    assert seen == {'target': 'plan_reviewer', 'sender': 'system'}
    assert 'freshness' not in payload
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['ask']['job_id'] == 'job_plan_reviewer'
    assert 'freshness' not in activation


def test_loop_runner_new_activation_metadata_ignores_legacy_artifact_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'task-new-draft'
    artifacts: dict[str, dict[str, object]] = {}
    for kind, filename, text in (
        ('requirements', 'requirements.md', 'requirements text\n'),
        ('acceptance', 'acceptance-criteria.md', 'acceptance text\n'),
        ('verification', 'verification-contract.md', 'verification text\n'),
        ('handoff', 'handoff.md', 'handoff text\n'),
    ):
        path = task_root / filename
        _write(path, text)
        artifacts[kind] = {
            'kind': kind,
            'path': str(path.relative_to(project_root)),
            'source_path': str(path.relative_to(project_root)),
            'sha256': 'test',
            'bytes': len(text.encode('utf-8')),
            'imported_at': '2026-06-27T00:00:00Z',
        }
    _add_plan_task_record(
        project_root,
        task_id='task-new-draft',
        status='draft',
        artifacts=artifacts,
        next_owner='planner',
        activation_reason='test_new_activation_contract',
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_submit_ask(_context, ask_command):
        assert ask_command.target == 'planner'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_new', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = loop_runner_once(context, command, services=SimpleNamespace(submit_ask=fake_submit_ask))

    assert payload['action'] == 'activated_planner'
    assert payload['next_owner'] == 'planner'


def _valid_frontdesk_intake() -> str:
    return """**Intake Evidence**

CCB_REQ_ID: `req_frontdesk_direct`

Macro request: Build a compact local task list feature.

Scope:
- `lab_tasks/task_list.py`
- `tests/test_task_list.py`

Required behavior:
- Add, list, complete, and filter tasks.
- Reject blank titles and invalid ids with useful exceptions.

Constraints:
- Planner and runner own task authority and execution.
- Frontdesk must not implement or mutate CCB authority state.
"""


def _route_mix_frontdesk_intake() -> str:
    return """**Intake Evidence**

CCB_REQ_ID: `req_frontdesk_route_mix`

Macro request: Run L1-L4 route-mix validation as a bounded task set.

Scope:
- L1 direct_execution documentation task.
- L2 direct_execution Python CLI task with unittest and README.
- L3 needs_detail task.
- L4 macro_adjustment_request task.
- L4 blocked task.

Required behavior:
- Planner must propose multiple tasks as a task set, not one controller-owned report task.
- Preserve routes direct_execution, needs_detail, macro_adjustment_request, and blocked.
- Runner scripts own task authority imports, route imports, round imports, evidence rows, and cleanup.

Constraints:
- Do not ask worker/provider roles to generate B7, rows, cleanup, or harness reports.
- Do not fake provider output or mutate authority from provider prose.
"""


def _complex_financial_report_frontdesk_intake() -> str:
    return """**Intake Evidence**

CCB_REQ_ID: `req_frontdesk_financial_report`

Macro request: Turn this expense tracker into a fuller monthly financial report tool.

Scope:
- `expense_tracker.py`
- `README.md`
- `tests/test_expense_tracker.py`

Required behavior:
- Generate a report for a specified month.
- Combine ordinary expenses and recurring monthly expenses.
- Show budget comparison and category trend information.
- Show over-budget alerts.
- Export the report as JSON and CSV.
- Add typical README usage examples.
- Cover the main usage paths with tests.

Constraints:
- Planner and runner own task authority and execution.
- Frontdesk must not implement or mutate CCB authority state.
"""


def _exact_four_surface_user_request() -> str:
    return """Extend the inventory project with four independent batch reporting surfaces.

1. Add `inventory/batch_manifest.py`. Expose `build_batch_manifest(items)` returning a dictionary with exactly
`record_count`, `total_quantity`, `categories`, and `records`. Normalize through
`inventory.schema.normalize_item`; categories are sorted and records preserve input order.

2. Add `inventory/jsonl_archive.py`. Expose `write_jsonl_archive(path, items)` returning
`{"record_count": int, "path": str}` and `read_jsonl_archive(path)` returning normalized records in file order.

3. Add `inventory/report_cli.py`. Expose `main(argv=None) -> int` for
`python -m inventory.report_cli INPUT_JSON OUTPUT_JSON`; invalid input returns nonzero and writes English stderr.

4. Add `docs/inventory-batch-reporting.md` and a focused documentation contract test.

All four surfaces have disjoint allowed paths and may run independently from the same baseline. Preserve existing
behavior, use the standard library, run focused tests and the full suite, and do not duplicate schema or summary logic.
"""


def _frontdesk_auto_runner_stub(calls: list[dict[str, str]]):
    def fake_start_auto_runner(_context, *, activation_id: str, wait_job_id: str):
        calls.append({'activation_id': activation_id, 'wait_job_id': wait_job_id})
        return {'status': 'started', 'pid': 12345, 'wait_job_id': wait_job_id}

    return fake_start_auto_runner


def test_frontdesk_forward_planner_submits_silent_planner_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_direct',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[object] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_from_frontdesk', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['action'] == 'forwarded_to_planner'
    assert payload['plan_slug'] == 'demo-plan'
    assert payload['request_id'] == 'req_frontdesk_direct'
    assert payload['ask']['target'] == 'planner'
    assert payload['ask']['job_id'] == 'job_planner_from_frontdesk'
    assert payload['ask']['sender'] == 'frontdesk'
    assert payload['ask']['silence'] is True
    assert payload['silence'] is True
    assert payload['auto_runner']['status'] == 'started'
    assert payload['auto_runner']['wait_job_id'] == 'job_planner_from_frontdesk'
    assert len(submitted) == 1
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_direct', 'wait_job_id': 'job_planner_from_frontdesk'}
    ]
    ask_command = submitted[0]
    assert ask_command.target == 'planner'
    assert ask_command.sender == 'frontdesk'
    assert ask_command.silence is True
    assert ask_command.compact is True
    assert ask_command.artifact_request is False
    assert ask_command.inline_request is False
    assert ask_command.task_id == 'act-frontdesk-req_frontdesk_direct'
    assert 'Frontdesk intake evidence:' in ask_command.message
    assert 'Planner contract: single_task' in ask_command.message
    assert 'Do not run ccb, ccb_test, ccb plan, ccb loop, ccb ask' in ask_command.message
    assert '**task-packet.md**' in ask_command.message
    assert '**task-set.json**' not in ask_command.message
    assert '## Acceptance Criteria' in ask_command.message
    assert '## Interface Contracts' in ask_command.message
    assert '## Execution Decomposition Inputs' in ask_command.message
    assert 'Stable interfaces available:' in ask_command.message
    assert 'Unresolved ordering constraints requiring predecessor output:' in ask_command.message
    assert 'A behavioral requirement alone is not a stable cross-node interface.' in ask_command.message
    assert 'would have to guess a new symbol or output contract' in ask_command.message
    activation_path = Path(str(payload['activation_path']))
    activation = json.loads(activation_path.read_text(encoding='utf-8'))
    assert activation['record_type'] == 'ccb_loop_frontdesk_planner_activation'
    assert activation['action'] == 'activate_planner_from_frontdesk'
    assert activation['planner_contract'] == 'single_task'
    assert activation['status'] == 'planner_submitted'
    assert activation['ask']['job_id'] == 'job_planner_from_frontdesk'
    assert activation['auto_runner']['wait_job_id'] == 'job_planner_from_frontdesk'
    assert activation['intake_sha256'] == hashlib.sha256(command.intake_text.encode('utf-8')).hexdigest()
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json').exists()


def test_frontdesk_forward_planner_keeps_complex_cohesive_project_request_as_one_task_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_financial_report',
        intake_text=_complex_financial_report_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[ParsedAskCommand] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_financial_report', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert len(submitted) == 1
    ask_command = submitted[0]
    assert ask_command.target == 'planner'
    assert ask_command.sender == 'frontdesk'
    assert ask_command.silence is True
    assert 'Planner contract: single_task' in ask_command.message
    assert '**task-packet.md**' in ask_command.message
    assert '**task-set.json**' not in ask_command.message
    assert 'phase6b-' not in ask_command.message
    assert 'one task object for each bounded task requested by frontdesk' not in ask_command.message
    assert 'execution_contract must declare Allowed Change Paths matching allowed_paths' not in ask_command.message
    assert 'Do not collapse this into a controller-owned validation task' not in ask_command.message
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['planner_contract'] == 'single_task'
    assert activation['expected_task_ids'] == []
    assert activation['required_next_output'] == 'reply-only task-packet.md plus readiness.json for supervisor-owned import'
    assert any('Return explicit fenced **task-packet.md**' in rule for rule in activation['script_write_rules'])
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_financial_report', 'wait_job_id': 'job_planner_financial_report'}
    ]


def test_frontdesk_forward_planner_uses_task_set_contract_for_route_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_route_mix',
        intake_text=_route_mix_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[ParsedAskCommand] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_route_mix', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert len(submitted) == 1
    ask_command = submitted[0]
    assert ask_command.target == 'planner'
    assert ask_command.sender == 'frontdesk'
    assert ask_command.silence is True
    assert 'Planner contract: task_set' in ask_command.message
    assert '**task-set.json**' in ask_command.message
    assert '**task-packet.md**' not in ask_command.message
    assert 'Do not collapse this into a controller-owned validation task' in ask_command.message
    assert 'Use exactly these task_id values, once each, and no other task_id values' in ask_command.message
    assert 'Do not require git diff, git status, or any git-only scope check' in ask_command.message
    assert 'Scope verification must be repo-independent' in ask_command.message
    assert 'phase6b-l3-needs-detail' in ask_command.message
    assert 'phase6b-l3-needs-detail-detail-ready' not in ask_command.message
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['planner_contract'] == 'task_set'
    assert activation['required_next_output'] == 'reply-only task-set.json with exact bounded task IDs for supervisor-owned import'
    assert activation['expected_task_ids'] == [
        'phase6b-l1-doc-direct-execution',
        'phase6b-l2-code-test-direct-execution',
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
        'phase6b-l4-blocked-prerequisite',
    ]
    assert any('Return exactly one fenced **task-set.json** section' in rule for rule in activation['script_write_rules'])
    assert any('Use exactly these task_id values and no others' in rule for rule in activation['script_write_rules'])
    assert any('Do not require git diff, git status, or any git-only scope check' in rule for rule in activation['script_write_rules'])
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_route_mix', 'wait_job_id': 'job_planner_route_mix'}
    ]


def test_frontdesk_forward_planner_uses_exact_ids_for_reworded_l1_l4_route_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    intake_text = """**Intake Evidence**

CCB_REQ_ID: `req_frontdesk_route_mix_reworded`

Macro request: Start a fresh real-provider L1-L4 deployment-readiness route-mix validation.

Scope:
- Controller-owned route-mix validation workflow for the lab project.
- Bounded L1-L4 task set prepared and routed by planner/orchestrator.

Required behavior:
- Include L1 document-only direct execution.
- Include L2 code-and-test direct execution.
- Include L3 needs-detail case stopping at `detail_ready`.
- Include L4 macro-adjustment case stopping at `replan_required`.
- Include L4 blocked-prerequisite case remaining blocked.

Constraints:
- Treat as controller-owned route-mix validation, not worker implementation.
- Do not ask workers to run the retest harness, generate B7 reports, write evidence rows, clean up runtime, or modify plan authority files.
"""
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_route_mix_reworded',
        intake_text=intake_text,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[ParsedAskCommand] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_route_mix_reworded', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    expected_task_ids = [
        'phase6b-l1-doc-direct-execution',
        'phase6b-l2-code-test-direct-execution',
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
        'phase6b-l4-blocked-prerequisite',
    ]
    assert payload['frontdesk_intake_status'] == 'ok'
    assert len(submitted) == 1
    for task_id in expected_task_ids:
        assert task_id in submitted[0].message
    assert 'Do not append route/status suffixes' in submitted[0].message
    assert 'Do not require git diff, git status, or any git-only scope check' in submitted[0].message
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['expected_task_ids'] == expected_task_ids
    assert activation['required_next_output'] == 'reply-only task-set.json with exact bounded task IDs for supervisor-owned import'


def test_frontdesk_forward_planner_live_auto_runner_lock_records_existing_runner_without_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    lock_path = project_root / '.ccb' / 'runtime' / 'loops' / 'auto-runner.lock'
    _write(lock_path, f'{os.getpid()}\n')
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_live_lock',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_submit_ask(_context, ask_command):
        assert ask_command.target == 'planner'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_live_lock', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    def forbidden_popen(*_args, **_kwargs):
        raise AssertionError('live auto-runner lock must not spawn a duplicate runner')

    monkeypatch.setattr(frontdesk_intake_module.subprocess, 'Popen', forbidden_popen)

    payload = frontdesk_intake(context, command, services=SimpleNamespace(submit_ask=fake_submit_ask))

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['ask']['job_id'] == 'job_planner_live_lock'
    assert payload['auto_runner']['status'] == 'already_active'
    assert payload['auto_runner']['pid'] == os.getpid()
    assert payload['auto_runner']['wait_job_id'] == 'job_planner_live_lock'
    assert payload['auto_runner']['next_activation'] == 'existing_auto_runner'
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['ask']['job_id'] == 'job_planner_live_lock'
    assert activation['auto_runner']['status'] == 'already_active'


def test_frontdesk_forward_planner_resolves_single_project_plan_without_plan_arg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write(project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'README.md', '# Demo Plan\n')
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug=None,
        request_id='req_frontdesk_direct',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[object] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_from_frontdesk', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['action'] == 'forwarded_to_planner'
    assert payload['plan_slug'] == 'demo-plan'
    assert len(submitted) == 1
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_direct', 'wait_job_id': 'job_planner_from_frontdesk'}
    ]
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['plan_slug'] == 'demo-plan'
    assert activation['ask']['target'] == 'planner'


def test_frontdesk_forward_planner_bootstraps_default_plan_without_plan_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'frontdesk-intake'
    assert not plan_root.exists()
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug=None,
        request_id='req_frontdesk_default_plan',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[ParsedAskCommand] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_default_plan', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['plan_slug'] == 'frontdesk-intake'
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['plan_slug'] == 'frontdesk-intake'
    assert activation['ask']['job_id'] == 'job_planner_default_plan'
    assert len(submitted) == 1
    assert submitted[0].target == 'planner'
    assert submitted[0].sender == 'frontdesk'
    assert submitted[0].silence is True
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_default_plan', 'wait_job_id': 'job_planner_default_plan'}
    ]
    assert (plan_root / 'README.md').exists()
    assert (plan_root / 'brief.md').exists()


def test_frontdesk_forward_planner_is_idempotent_for_same_intake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_direct',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted_count = 0
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, _ask_command):
        nonlocal submitted_count
        submitted_count += 1
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_from_frontdesk', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    services = SimpleNamespace(
        submit_ask=fake_submit_ask,
        start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
    )
    first = frontdesk_intake(context, command, services=services)
    second = frontdesk_intake(context, command, services=services)

    assert first['action'] == 'forwarded_to_planner'
    assert second['frontdesk_intake_status'] == 'ok'
    assert second['action'] == 'already_forwarded_to_planner'
    assert second['idempotent'] is True
    assert second['planner_job_id'] == 'job_planner_from_frontdesk'
    assert submitted_count == 1
    assert len(auto_runner_calls) == 1


def test_frontdesk_forward_planner_rejects_request_id_conflict_without_duplicate_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_direct',
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted_count = 0
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, _ask_command):
        nonlocal submitted_count
        submitted_count += 1
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_from_frontdesk', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    first = frontdesk_intake(
        context,
        command,
        services=SimpleNamespace(
            submit_ask=fake_submit_ask,
            start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
        ),
    )
    conflict = frontdesk_intake(
        context,
        ParsedFrontdeskCommand(
            project=None,
            action='forward-planner',
            plan_slug='demo-plan',
            request_id='req_frontdesk_direct',
            intake_text=_valid_frontdesk_intake().replace('compact local task list', 'different local task list'),
            json_output=True,
        ),
        services=SimpleNamespace(submit_ask=fake_submit_ask),
    )

    assert first['action'] == 'forwarded_to_planner'
    assert conflict['frontdesk_intake_status'] == 'blocked'
    assert conflict['reason'] == 'frontdesk_activation_request_id_conflict'
    assert submitted_count == 1
    assert len(auto_runner_calls) == 1


def test_frontdesk_forward_planner_rejects_weak_intake_without_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_weak',
        intake_text='**Intake Evidence**\n\nMacro request: Build something.\n',
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('weak frontdesk intake must not submit planner ask')

    payload = frontdesk_intake(context, command, services=SimpleNamespace(submit_ask=forbidden_submit_ask))

    assert payload['frontdesk_intake_status'] == 'blocked'
    assert payload['action'] == 'rejected'
    assert payload['reason'] == 'frontdesk_intake_missing_required_anchors'
    assert payload['evidence']['missing_fields'] == [
        'Execution Contract, Acceptance Criteria, or Required behavior with Scope/Constraints'
    ]
    assert not (project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-frontdesk-req_weak.json').exists()


def test_frontdesk_forward_planner_parser_accepts_file_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake_path = tmp_path / 'intake.md'
    _write(intake_path, _valid_frontdesk_intake())

    class _TtyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, 'stdin', _TtyStdin())
    command = CliParser().parse(
        [
            'frontdesk',
            'forward-planner',
            '--request-id',
            'req_frontdesk_direct',
            '--file',
            str(intake_path),
            '--json',
        ]
    )

    assert isinstance(command, ParsedFrontdeskCommand)
    assert command.action == 'forward-planner'
    assert command.plan_slug is None
    assert command.request_id == 'req_frontdesk_direct'
    assert command.file_path == str(intake_path)
    assert command.intake_text == ''
    assert command.json_output is True


def test_frontdesk_forward_planner_parser_accepts_base64_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake_base64 = base64.b64encode(_valid_frontdesk_intake().encode('utf-8')).decode('ascii')

    class _TtyStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, 'stdin', _TtyStdin())
    command = CliParser().parse(
        [
            'frontdesk',
            'forward-planner',
            '--request-id',
            'req_frontdesk_base64',
            '--intake-base64',
            intake_base64,
            '--json',
        ]
    )

    assert isinstance(command, ParsedFrontdeskCommand)
    assert command.action == 'forward-planner'
    assert command.request_id == 'req_frontdesk_base64'
    assert command.file_path is None
    assert command.intake_base64 == intake_base64
    assert command.intake_text == ''
    assert command.json_output is True


def test_frontdesk_forward_planner_accepts_base64_input_without_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan'
    plan_root.mkdir(parents=True)
    intake_text = _valid_frontdesk_intake()
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug=None,
        request_id='req_frontdesk_base64',
        intake_base64=base64.b64encode(intake_text.encode('utf-8')).decode('ascii'),
        intake_text='',
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[ParsedAskCommand] = []
    auto_runner_calls: list[dict[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append(ask_command)
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_base64', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    services = SimpleNamespace(
        submit_ask=fake_submit_ask,
        start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
    )

    payload = frontdesk_intake(context, command, services=services)

    assert payload['frontdesk_intake_status'] == 'ok'
    assert submitted
    assert 'Frontdesk intake evidence:' in submitted[0].message
    assert 'compact local task list' in submitted[0].message
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_base64', 'wait_job_id': 'job_planner_base64'}
    ]


def test_frontdesk_forward_planner_cli_proxies_to_mounted_daemon_without_local_runtime_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    intake_text = _valid_frontdesk_intake()
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug='demo-plan',
        request_id='req_frontdesk_daemon_proxy',
        intake_base64=base64.b64encode(intake_text.encode('utf-8')).decode('ascii'),
        intake_text='',
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    socket_path = Path(context.paths.ccbd_socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.write_text('not-a-real-socket\n', encoding='utf-8')
    client_calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, path):
            client_calls.append({'socket_path': str(path)})

        def frontdesk_forward_planner(self, **payload):
            client_calls.append({'payload': payload})
            return {
                'schema_version': 1,
                'record_type': 'ccb_frontdesk_intake',
                'frontdesk_intake_status': 'ok',
                'project_id': context.project.project_id,
                'project_root': str(project_root),
                'action': 'forwarded_to_planner',
                'request_id': payload['request_id'],
                'activation_id': 'act-frontdesk-req_frontdesk_daemon_proxy',
                'planner_job_id': 'job_planner_daemon_proxy',
                'silence': True,
            }

    monkeypatch.setattr(frontdesk_intake_command_module, 'CcbdClient', FakeClient)

    payload = frontdesk_intake_command(context, command, services=SimpleNamespace())

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['planner_job_id'] == 'job_planner_daemon_proxy'
    assert client_calls[0] == {'socket_path': str(socket_path)}
    assert client_calls[1]['payload']['request_id'] == 'req_frontdesk_daemon_proxy'
    assert client_calls[1]['payload']['intake_base64'] == command.intake_base64
    assert not (
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-frontdesk-req_frontdesk_daemon_proxy.json'
    ).exists()


def test_frontdesk_forward_planner_daemon_handler_writes_activation_and_submits_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    submitted: list[object] = []
    auto_runner_calls: list[dict[str, str]] = []

    class FakeDispatcher:
        _layout = PathLayout(project_root)

        def submit(self, envelope):
            submitted.append(envelope)
            return SubmitReceipt(
                accepted_at='2026-07-09T00:00:00Z',
                jobs=(
                    AcceptedJobReceipt(
                        job_id='job_planner_daemon_handler',
                        agent_name='planner',
                        status=JobStatus.QUEUED,
                        accepted_at='2026-07-09T00:00:00Z',
                    ),
                ),
            )

    handler = build_frontdesk_forward_planner_handler(
        FakeDispatcher(),
        start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
    )
    payload = handler(
        {
            'plan_slug': 'demo-plan',
            'request_id': 'req_frontdesk_daemon_handler',
            'intake_base64': base64.b64encode(_valid_frontdesk_intake().encode('utf-8')).decode('ascii'),
            'json_output': True,
        }
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert payload['action'] == 'forwarded_to_planner'
    assert payload['planner_job_id'] == 'job_planner_daemon_handler'
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_daemon_handler', 'wait_job_id': 'job_planner_daemon_handler'}
    ]
    assert len(submitted) == 1
    envelope = submitted[0]
    assert envelope.to_agent == 'planner'
    assert envelope.from_actor == 'frontdesk'
    assert envelope.task_id == 'act-frontdesk-req_frontdesk_daemon_handler'
    assert envelope.silence_on_success is True
    assert envelope.route_options == {}
    assert envelope.body_artifact is None
    assert 'Frontdesk intake evidence:' in envelope.body
    assert 'CCB ask request was stored as an artifact' not in envelope.body
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['status'] == 'planner_submitted'
    assert activation['ask']['job_id'] == 'job_planner_daemon_handler'


def test_frontdesk_daemon_handler_preserves_exact_source_job_request_for_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    source_job_id = 'job_frontdesk_exact_contracts'
    source_body = _exact_four_surface_user_request()
    submitted: list[object] = []
    auto_runner_calls: list[dict[str, str]] = []

    class FakeDispatcher:
        _layout = PathLayout(project_root)

        def get(self, job_id):
            assert job_id == source_job_id
            return SimpleNamespace(
                agent_name='frontdesk',
                request=SimpleNamespace(
                    project_id=self._layout.project_id,
                    to_agent='frontdesk',
                    from_actor='user',
                    message_type='ask',
                    body=source_body + '\n\nCCB_REPLY_MODE: compact',
                    body_artifact=None,
                ),
            )

        def submit(self, envelope):
            submitted.append(envelope)
            return SubmitReceipt(
                accepted_at='2026-07-11T00:00:00Z',
                jobs=(
                    AcceptedJobReceipt(
                        job_id='job_planner_exact_contracts',
                        agent_name='planner',
                        status=JobStatus.QUEUED,
                        accepted_at='2026-07-11T00:00:00Z',
                    ),
                ),
            )

    handler = build_frontdesk_forward_planner_handler(
        FakeDispatcher(),
        start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
    )
    payload = handler(
        {
            'plan_slug': 'demo-plan',
            'request_id': source_job_id,
            'source_job_id': source_job_id,
            'intake_base64': base64.b64encode(
                _complex_financial_report_frontdesk_intake().encode('utf-8')
            ).decode('ascii'),
            'json_output': True,
        }
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert len(submitted) == 1
    envelope = submitted[0]
    assert envelope.body_artifact is not None
    planner_body = Path(str(envelope.body_artifact['path'])).read_text(encoding='utf-8')
    assert 'Original user request (controller-loaded source-job evidence):' in planner_body
    assert '<original-user-request>' in planner_body
    assert 'build_batch_manifest(items)' in planner_body
    assert '`record_count`, `total_quantity`, `categories`, and `records`' in planner_body
    assert 'write_jsonl_archive(path, items)' in planner_body
    assert 'main(argv=None) -> int' in planner_body
    assert 'CCB_REPLY_MODE:' not in planner_body
    assert 'Frontdesk intake evidence:' in planner_body
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['source_job']['job_id'] == source_job_id
    assert activation['source_request']['source_job_id'] == source_job_id
    assert activation['source_request']['sha256'] == hashlib.sha256(source_body.encode('utf-8')).hexdigest()
    assert activation['source_request']['bytes'] == len(source_body.encode('utf-8'))


def test_frontdesk_daemon_handler_blocks_invalid_source_request_artifact_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    source_job_id = 'job_frontdesk_missing_artifact'
    submitted: list[object] = []

    class FakeDispatcher:
        _layout = PathLayout(project_root)

        def get(self, job_id):
            assert job_id == source_job_id
            return SimpleNamespace(
                agent_name='frontdesk',
                request=SimpleNamespace(
                    project_id=self._layout.project_id,
                    to_agent='frontdesk',
                    from_actor='user',
                    message_type='ask',
                    body='artifact stub',
                    body_artifact={
                        'path': str(project_root / '.ccb' / 'ccbd' / 'text-artifacts' / 'missing.txt'),
                        'bytes': 100,
                        'sha256': '0' * 64,
                    },
                ),
            )

        def submit(self, envelope):
            submitted.append(envelope)
            raise AssertionError('invalid source request must not submit planner ask')

    handler = build_frontdesk_forward_planner_handler(FakeDispatcher())
    payload = handler(
        {
            'plan_slug': 'demo-plan',
            'request_id': source_job_id,
            'source_job_id': source_job_id,
            'intake_base64': base64.b64encode(_valid_frontdesk_intake().encode('utf-8')).decode('ascii'),
            'json_output': True,
        }
    )

    assert payload['frontdesk_intake_status'] == 'blocked'
    assert payload['reason'] == 'frontdesk_source_request_artifact_invalid'
    assert payload['evidence']['source_job_id'] == source_job_id
    assert submitted == []
    assert not (
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / f'act-frontdesk-{source_job_id}.json'
    ).exists()


def test_frontdesk_daemon_handler_reads_and_verifies_source_request_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    source_job_id = 'job_frontdesk_artifact_request'
    source_body = _exact_four_surface_user_request() + ('Exact retained constraint.\n' * 160)
    layout = PathLayout(project_root)
    source_artifact = write_text_artifact(
        layout,
        text=source_body,
        kind='ask-request',
        owner_id=source_job_id,
    )
    submitted: list[object] = []

    class FakeDispatcher:
        _layout = layout

        def get(self, job_id):
            assert job_id == source_job_id
            return SimpleNamespace(
                agent_name='frontdesk',
                request=SimpleNamespace(
                    project_id=self._layout.project_id,
                    to_agent='frontdesk',
                    from_actor='user',
                    message_type='ask',
                    body='CCB ask request was stored as an artifact.',
                    body_artifact=source_artifact,
                ),
            )

        def submit(self, envelope):
            submitted.append(envelope)
            return SubmitReceipt(
                accepted_at='2026-07-11T00:00:00Z',
                jobs=(
                    AcceptedJobReceipt(
                        job_id='job_planner_artifact_request',
                        agent_name='planner',
                        status=JobStatus.QUEUED,
                        accepted_at='2026-07-11T00:00:00Z',
                    ),
                ),
            )

    handler = build_frontdesk_forward_planner_handler(
        FakeDispatcher(),
        start_auto_runner=_frontdesk_auto_runner_stub([]),
    )
    payload = handler(
        {
            'plan_slug': 'demo-plan',
            'request_id': source_job_id,
            'source_job_id': source_job_id,
            'intake_base64': base64.b64encode(_valid_frontdesk_intake().encode('utf-8')).decode('ascii'),
        }
    )

    assert payload['frontdesk_intake_status'] == 'ok'
    assert len(submitted) == 1
    planner_artifact = submitted[0].body_artifact
    assert planner_artifact is not None
    planner_body = Path(str(planner_artifact['path'])).read_text(encoding='utf-8')
    assert source_body.strip() in planner_body
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['source_request']['sha256'] == source_artifact['sha256']
    assert activation['source_request']['bytes'] == source_artifact['bytes']
    assert activation['source_request']['body_artifact']['path'] == source_artifact['path']


def test_frontdesk_session_observer_handoffs_latest_codex_intake_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    session_jsonl = (
        project_root
        / '.ccb'
        / 'agents'
        / 'frontdesk'
        / 'provider-state'
        / 'codex'
        / 'home'
        / 'sessions'
        / '2026'
        / '07'
        / '09'
        / 'rollout.jsonl'
    )
    session_jsonl.parent.mkdir(parents=True)
    intake_text = _valid_frontdesk_intake()
    _write(
        session_jsonl,
        json.dumps(
            {
                'type': 'response_item',
                'payload': {
                    'type': 'message',
                    'role': 'user',
                    'content': [
                        {
                            'type': 'input_text',
                            'text': 'CCB_REQ_ID: req_frontdesk_direct\n\nBuild a compact local task list feature.',
                        }
                    ],
                    'internal_chat_message_metadata_passthrough': {
                        'turn_id': 'turn_frontdesk_observer_1'
                    },
                },
            }
        )
        + '\n'
        +
        json.dumps(
            {
                'type': 'event_msg',
                'payload': {
                    'type': 'task_complete',
                    'turn_id': 'turn_frontdesk_observer_1',
                    'last_agent_message': intake_text,
                },
            }
        )
        + '\n',
    )
    session_info = project_root / '.ccb' / '.codex-frontdesk-session'
    _write_json(session_info, {'codex_session_path': str(session_jsonl)})
    submitted: list[object] = []
    auto_runner_calls: list[dict[str, str]] = []

    class FakeRegistry:
        def get(self, agent_name):
            assert agent_name == 'frontdesk'
            return SimpleNamespace(provider='codex', session_file=str(session_info))

    class FakeDispatcher:
        _layout = PathLayout(project_root)

        def submit(self, envelope):
            submitted.append(envelope)
            job_id = (
                'job_planner_observed_frontdesk'
                if len(submitted) == 1
                else f'job_planner_observed_frontdesk_{len(submitted)}'
            )
            return SubmitReceipt(
                accepted_at='2026-07-09T00:00:00Z',
                jobs=(
                    AcceptedJobReceipt(
                        job_id=job_id,
                        agent_name='planner',
                        status=JobStatus.QUEUED,
                        accepted_at='2026-07-09T00:00:00Z',
                    ),
                ),
            )

    app = SimpleNamespace(
        paths=PathLayout(project_root),
        registry=FakeRegistry(),
        dispatcher=FakeDispatcher(),
        clock=lambda: '2026-07-09T00:00:00Z',
        frontdesk_observer_start_auto_runner=_frontdesk_auto_runner_stub(auto_runner_calls),
    )

    first = observe_frontdesk_session(app)
    second = observe_frontdesk_session(app)

    assert first['status'] == 'ok'
    assert first['turn_id'] == 'turn_frontdesk_observer_1'
    assert first['frontdesk_intake']['frontdesk_intake_status'] == 'ok'
    assert first['frontdesk_intake']['planner_job_id'] == 'job_planner_observed_frontdesk'
    assert second is None
    assert len(submitted) == 1
    assert submitted[0].to_agent == 'planner'
    assert submitted[0].from_actor == 'frontdesk'
    assert submitted[0].silence_on_success is True
    assert auto_runner_calls == [
        {'activation_id': 'act-frontdesk-req_frontdesk_direct', 'wait_job_id': 'job_planner_observed_frontdesk'}
    ]
    state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'frontdesk-session-observer' / 'state.json').read_text(encoding='utf-8')
    )
    assert state['turn_id'] == 'turn_frontdesk_observer_1'
    activation = json.loads(
        (
            project_root
            / '.ccb'
            / 'runtime'
            / 'loops'
            / 'activations'
            / 'act-frontdesk-req_frontdesk_direct.json'
        ).read_text(encoding='utf-8')
    )
    assert activation['ask']['job_id'] == 'job_planner_observed_frontdesk'

    with session_jsonl.open('a', encoding='utf-8') as fh:
        fh.write(
            json.dumps(
                {
                    'type': 'event_msg',
                    'payload': {
                        'type': 'task_complete',
                        'turn_id': 'turn_frontdesk_observer_delivery_notice',
                        'last_agent_message': '',
                    },
                }
            )
            + '\n'
        )

    ignored_after_success = observe_frontdesk_session(app)

    assert ignored_after_success['status'] == 'ok'
    assert ignored_after_success['turn_id'] == 'turn_frontdesk_observer_1'
    assert ignored_after_success['frontdesk_intake']['planner_job_id'] == 'job_planner_observed_frontdesk'
    assert ignored_after_success['last_observed_turn_id'] == 'turn_frontdesk_observer_delivery_notice'
    assert ignored_after_success['last_ignored']['turn_id'] == 'turn_frontdesk_observer_delivery_notice'
    assert len(submitted) == 1
    state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'frontdesk-session-observer' / 'state.json').read_text(encoding='utf-8')
    )
    assert state['status'] == 'ok'
    assert state['frontdesk_intake']['planner_job_id'] == 'job_planner_observed_frontdesk'
    assert state['last_ignored']['reason'] == 'frontdesk_reply_not_intake_evidence'

    second_turn_id = 'turn_frontdesk_observer_2'
    stale_id_intake = _valid_frontdesk_intake().replace(
        'Build a compact local task list feature.',
        'Extend the compact task list with deterministic archive support.',
    )
    with session_jsonl.open('a', encoding='utf-8') as fh:
        fh.write(
            json.dumps(
                {
                    'type': 'response_item',
                    'payload': {
                        'type': 'message',
                        'role': 'user',
                        'content': [
                            {
                                'type': 'input_text',
                                'text': 'Extend the compact task list with deterministic archive support.',
                            }
                        ],
                        'internal_chat_message_metadata_passthrough': {'turn_id': second_turn_id},
                    },
                }
            )
            + '\n'
        )
        fh.write(
            json.dumps(
                {
                    'type': 'event_msg',
                    'payload': {
                        'type': 'task_complete',
                        'turn_id': second_turn_id,
                        'last_agent_message': stale_id_intake,
                    },
                }
            )
            + '\n'
        )

    second_handoff = observe_frontdesk_session(app)

    assert second_handoff['status'] == 'ok'
    assert second_handoff['request_id'] == 'frontdesk-turn_frontdesk_observer_2'
    assert second_handoff['request_id_source'] == 'codex_turn_id'
    assert second_handoff['frontdesk_intake']['planner_job_id'] == 'job_planner_observed_frontdesk_2'
    assert len(submitted) == 2
    assert submitted[1].task_id == 'act-frontdesk-frontdesk-turn_frontdesk_observer_2'
    assert 'CCB_REQ_ID: frontdesk-turn_frontdesk_observer_2' in submitted[1].body
    assert 'CCB_REQ_ID: `req_frontdesk_direct`' not in submitted[1].body
    assert auto_runner_calls[-1] == {
        'activation_id': 'act-frontdesk-frontdesk-turn_frontdesk_observer_2',
        'wait_job_id': 'job_planner_observed_frontdesk_2',
    }


def test_frontdesk_session_observer_binds_original_job_request_to_planner_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    source_job_id = 'job_frontdesk_observed_source'
    source_body = _exact_four_surface_user_request()
    session_jsonl = project_root / '.ccb' / 'agents' / 'frontdesk' / 'provider-state' / 'codex' / 'session.jsonl'
    _write(
        session_jsonl,
        json.dumps(
            {
                'type': 'response_item',
                'payload': {
                    'type': 'message',
                    'role': 'user',
                    'content': [{'type': 'input_text', 'text': f'CCB_REQ_ID: {source_job_id}\n\n{source_body}'}],
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'turn_exact_source'},
                },
            }
        )
        + '\n'
        + json.dumps(
            {
                'type': 'event_msg',
                'payload': {
                    'type': 'task_complete',
                    'turn_id': 'turn_exact_source',
                    'last_agent_message': _complex_financial_report_frontdesk_intake(),
                },
            }
        )
        + '\n',
    )
    session_info = project_root / '.ccb' / '.codex-frontdesk-session'
    _write_json(session_info, {'codex_session_path': str(session_jsonl)})
    submitted: list[object] = []

    class FakeRegistry:
        def get(self, agent_name):
            assert agent_name == 'frontdesk'
            return SimpleNamespace(provider='codex', session_file=str(session_info))

    class FakeDispatcher:
        _layout = PathLayout(project_root)

        def get(self, job_id):
            assert job_id == source_job_id
            return SimpleNamespace(
                agent_name='frontdesk',
                request=SimpleNamespace(
                    project_id=self._layout.project_id,
                    to_agent='frontdesk',
                    from_actor='user',
                    message_type='ask',
                    body=source_body,
                    body_artifact=None,
                ),
            )

        def submit(self, envelope):
            submitted.append(envelope)
            return SubmitReceipt(
                accepted_at='2026-07-11T00:00:00Z',
                jobs=(
                    AcceptedJobReceipt(
                        job_id='job_planner_observed_source',
                        agent_name='planner',
                        status=JobStatus.QUEUED,
                        accepted_at='2026-07-11T00:00:00Z',
                    ),
                ),
            )

    app = SimpleNamespace(
        paths=PathLayout(project_root),
        registry=FakeRegistry(),
        dispatcher=FakeDispatcher(),
        clock=lambda: '2026-07-11T00:00:00Z',
        frontdesk_observer_start_auto_runner=_frontdesk_auto_runner_stub([]),
    )

    observed = observe_frontdesk_session(app)

    assert observed['status'] == 'ok'
    assert observed['source_job_id'] == source_job_id
    assert len(submitted) == 1
    envelope = submitted[0]
    planner_body = (
        Path(str(envelope.body_artifact['path'])).read_text(encoding='utf-8')
        if envelope.body_artifact
        else envelope.body
    )
    assert 'build_batch_manifest(items)' in planner_body
    assert 'write_jsonl_archive(path, items)' in planner_body
    assert 'main(argv=None) -> int' in planner_body
    activation = json.loads(
        (
            project_root
            / '.ccb'
            / 'runtime'
            / 'loops'
            / 'activations'
            / f'act-frontdesk-{source_job_id}.json'
        ).read_text(encoding='utf-8')
    )
    assert activation['source_request']['source_job_id'] == source_job_id


def test_frontdesk_forward_planner_rejects_mixed_base64_and_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').mkdir(parents=True)
    command = ParsedFrontdeskCommand(
        project=None,
        action='forward-planner',
        plan_slug=None,
        request_id='req_frontdesk_mixed',
        intake_base64=base64.b64encode(_valid_frontdesk_intake().encode('utf-8')).decode('ascii'),
        intake_text=_valid_frontdesk_intake(),
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = frontdesk_intake(context, command, services=SimpleNamespace(submit_ask=lambda *_args: None))

    assert payload['frontdesk_intake_status'] == 'blocked'
    assert payload['reason'] == 'frontdesk_intake_cannot_combine_input_sources'


def test_loop_runner_consumes_completed_role_outputs_into_script_owned_task_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    plan_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan'
    assert not plan_root.exists()
    frontdesk_reply = """**Macro Task Request**

Implement a compact task list feature.

**Execution Contract**

Build a Python module and pytest coverage.
"""
    original_request = (
        'Implement `add_task(title) -> int` and `complete_task(task_id) -> bool`; '
        'reject blank titles with ValueError and preserve stable integer ids.\n'
    )
    _write(
        project_root / '.ccb' / 'agents' / 'frontdesk' / 'jobs.jsonl',
        json.dumps(
            {
                'job_id': 'job_frontdesk',
                'agent_name': 'frontdesk',
                'request': {
                    'project_id': PathLayout(project_root).project_id,
                    'to_agent': 'frontdesk',
                    'from_actor': 'user',
                    'message_type': 'ask',
                    'body': original_request,
                    'body_artifact': None,
                    'task_id': None,
                },
            }
        )
        + '\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_frontdesk',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[tuple[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append((ask_command.target, ask_command.message))
        if ask_command.target == 'planner':
            job_id = 'job_planner'
        elif ask_command.target == 'orchestrator':
            job_id = 'job_orchestrator'
        else:
            raise AssertionError(f'unexpected target: {ask_command.target}')
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': job_id, 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner_from_frontdesk'
    assert payload['job_id'] == 'job_frontdesk'
    assert payload['plan_slug'] == 'demo-plan'
    assert payload['ask'] == {'target': 'planner', 'job_id': 'job_planner', 'status': 'submitted'}
    assert submitted[0][0] == 'planner'
    assert '**task-packet.md**' in submitted[0][1]
    assert original_request.strip() in submitted[0][1]
    assert 'Original user request (controller-loaded source-job evidence):' in submitted[0][1]
    assert 'Do not run ccb, ccb_test, ccb plan, ccb loop, ccb ask' in submitted[0][1]
    assert plan_root.is_dir()
    assert not (plan_root / 'tasks' / 'index.json').exists()

    planner_reply = """**Conclusion:** ready for one `direct_execution` task.

**task-packet.md**
```markdown
    # Task: Implement Task List

    Route: direct_execution
    ## Goal
    Implement the compact task-list feature.
    ## Acceptance Criteria
    - The task-list module and focused tests pass.
    ## Interface Contracts
    - The module API is defined by its focused tests.
    ## Constraints And Non-Goals
    - Change only the declared module and test.
    ## Execution Decomposition Inputs
    - Independently reviewable surfaces: module and focused test as one unit.
    - Real predecessor dependencies: none.
    Allowed paths:
- lab_tasks/task_list.py
- tests/test_task_list.py

Verification:
- python -m pytest tests/test_task_list.py
```

**readiness.json**
```json
{
  "readiness": "ready",
  "route": "direct_execution",
  "blockers": [],
  "allowed_paths": ["lab_tasks/task_list.py", "tests/test_task_list.py"],
  "verification": ["python -m pytest tests/test_task_list.py"]
}
```
"""
    _write_completion_snapshot(
        project_root,
        job_id='job_planner',
        agent_name='planner',
        reply=planner_reply,
    )

    payload = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(project=None, once=True, json_output=True),
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['job_id'] == 'job_planner'
    assert payload['task_status'] == 'ready_for_orchestration'
    task_id = str(payload['task_id'])
    assert task_id != 'None'
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'None').exists()
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['status'] == 'ready_for_orchestration'
    assert shown['task']['next_owner'] == 'orchestrator'
    assert shown['task']['authority_trace']['source'] == 'loop_runner_role_output_import'
    assert shown['task']['authority_trace']['source_job']['job_id'] == 'job_planner'
    artifacts = shown['task']['artifacts']
    assert set(artifacts) == {'execution_contract', 'task_packet'}
    assert artifacts['task_packet']['actor'] == {
        'source': 'loop_runner_role_output_import',
        'actor': 'loop_runner',
        'job_id': 'job_planner',
    }
    assert artifacts['execution_contract']['actor']['source'] == 'loop_runner_role_output_import'
    assert 'Allowed Change Paths:' in (
        project_root / artifacts['execution_contract']['path']
    ).read_text(encoding='utf-8')

    replay_payload = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(
            project=None,
            once=True,
            plan_slug='demo-plan',
            role_job_id='job_planner',
            consume_role_output=True,
            json_output=True,
        ),
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )
    assert replay_payload['action'] == 'role_output_already_consumed'
    assert replay_payload['consumed_action'] == 'imported_planner_task_authority'
    assert replay_payload['job_id'] == 'job_planner'
    assert replay_payload['agent_name'] == 'planner'
    assert replay_payload['task_id'] == task_id
    assert replay_payload['task_status'] == 'ready_for_orchestration'
    assert replay_payload['next_owner'] == 'orchestrator'
    assert replay_payload['next_activation'] == 'orchestrator'

    payload = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(project=None, once=True, json_output=True),
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )
    assert payload['action'] == 'activated_orchestrator'
    assert payload['task_id'] == task_id
    assert payload['ask'] == {'target': 'orchestrator', 'job_id': 'job_orchestrator', 'status': 'submitted'}

    _write_completion_snapshot(
        project_root,
        job_id='job_orchestrator',
        agent_name='orchestrator',
        reply='route: direct_execution\n\norchestration_notes: Task packet and contract are ready.\n',
    )
    payload = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(project=None, once=True, json_output=True),
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )
    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_orchestration_notes'
    assert payload['task_id'] == task_id
    assert payload['route'] == 'direct_execution'
    assert payload['next_activation'] == 'ask_first_execution'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['status'] == 'ready_for_orchestration'
    assert shown['task']['artifacts']['orchestration_notes']['orchestrator_route'] == 'direct_execution'
    assert shown['task']['artifacts']['orchestration_notes']['actor'] == {
        'source': 'loop_runner_role_output_import',
        'actor': 'loop_runner',
        'job_id': 'job_orchestrator',
    }

    trace = (
        project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl'
    ).read_text(encoding='utf-8')
    assert 'job_frontdesk' in trace
    assert 'job_planner' in trace
    assert 'job_orchestrator' in trace


def test_loop_runner_does_not_duplicate_planner_when_frontdesk_handoff_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    frontdesk_reply = """**Intake Evidence**
CCB_REQ_ID: job_frontdesk
Macro request: Build a compact local task list feature.
Scope: `tasks.py`; `test_tasks.py`
Required behavior: Add, list, and complete tasks.
Constraints: Frontdesk must not mutate CCB authority; planner will create task authority.
"""
    _write_completion_snapshot(
        project_root,
        job_id='job_frontdesk',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    marker_path = project_root / '.ccb' / 'runtime' / 'frontdesk-handoff' / 'job_frontdesk.json'
    stdout_path = project_root / '.ccb' / 'runtime' / 'frontdesk-handoff' / 'logs' / 'job_frontdesk.stdout.log'
    _write_json(
        stdout_path,
        {
            'action': 'forwarded_to_planner',
            'frontdesk_intake_status': 'ok',
            'plan_slug': 'frontdesk-intake',
            'planner_job_id': 'job_planner_from_frontdesk',
            'ask': {
                'target': 'planner',
                'job_id': 'job_planner_from_frontdesk',
                'sender': 'frontdesk',
                'silence': True,
                'status': 'accepted',
            },
        },
    )
    _write_json(
        marker_path,
        {
            'schema_version': 1,
            'record_type': 'ccb_frontdesk_auto_handoff',
            'status': 'started',
            'job_id': 'job_frontdesk',
            'agent_name': 'frontdesk',
            'project_root': str(project_root),
            'plan_slug': 'frontdesk-intake',
            'stdout_path': str(stdout_path),
            'stderr_path': str(stdout_path.with_suffix('.stderr.log')),
            'pid': 12345,
            'recorded_at': '2026-07-07T00:00:00Z',
        },
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='deploy-dynamic-unload-stress',
        role_job_id='job_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('frontdesk role-output import must not submit a second planner ask')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'frontdesk_handoff_already_started'
    assert payload['next_activation'] == 'stop_after_existing_frontdesk_handoff'
    assert payload['handoff']['plan_slug'] == 'frontdesk-intake'
    assert payload['ask']['job_id'] == 'job_planner_from_frontdesk'
    assert payload['planner_job_id'] == 'job_planner_from_frontdesk'
    assert payload['handoff_result']['planner_job_id'] == 'job_planner_from_frontdesk'
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'deploy-dynamic-unload-stress').exists()
    imports = [
        json.loads(line)
        for line in (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert imports[-1]['action'] == 'frontdesk_handoff_already_started'


@pytest.mark.parametrize(
    ('config_version', 'activation_source', 'expects_task_set_authority'),
    (
        (2, None, False),
        (3, None, True),
        (2, 'frontdesk_direct_silence_ask', True),
    ),
)
def test_loop_runner_imports_planner_task_set_as_script_owned_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_version: int,
    activation_source: str | None,
    expects_task_set_authority: bool,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    monkeypatch.setattr(
        role_output_import_module,
        'compile_project_effective_capacity_snapshot',
        lambda _root: {'config_version': config_version},
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_route_mix_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write(project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'README.md', '# Demo Plan\n')
    plan_task(
        context,
        SimpleNamespace(
            action='task-create',
            plan_slug='demo-plan',
            title='Frontdesk route mix intake',
            task_id='route-mix-intake',
        ),
    )
    _write(
        project_root / '.ccb' / 'agents' / 'frontdesk' / 'jobs.jsonl',
        json.dumps(
            {
                'job_id': 'job_frontdesk_route_mix',
                'agent_name': 'frontdesk',
                'request': {'task_id': 'route-mix-intake'},
                'status': 'accepted',
            },
            ensure_ascii=False,
        )
        + '\n',
    )
    activation = {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-route-mix',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'source_task_id': 'route-mix-intake',
            'source_job': {'job_id': 'job_frontdesk_route_mix', 'agent_name': 'frontdesk'},
            'source_intake': {'preview': _route_mix_frontdesk_intake()[:400]},
            'source_request': {
                'source_job_id': 'job_frontdesk_route_mix',
                'sha256': hashlib.sha256(_route_mix_frontdesk_intake().encode('utf-8')).hexdigest(),
                'bytes': len(_route_mix_frontdesk_intake().encode('utf-8')),
            },
            'ask': {
                'target': 'planner',
                'job_id': 'job_route_mix_planner',
                'status': 'accepted',
            },
        }
    if activation_source is not None:
        activation['source'] = activation_source
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-route-mix.json',
        activation,
    )
    tasks = [
        {
            'task_id': 'phase6b-l1-doc-direct-execution',
            'title': 'L1 documentation direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L1 documentation direct execution\nRoute: direct_execution\n',
            'execution_contract': '# Execution Contract\nRoute: direct_execution\n\nCreate the L1 documentation file.\n',
            'allowed_paths': ['docs/l1-smoke.md'],
            'verification': ['test -f docs/l1-smoke.md'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l2-code-direct-execution',
            'title': 'L2 CLI direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L2 CLI direct execution\nRoute: direct_execution\n',
            'allowed_paths': ['src/l2_cli.py', 'tests/test_l2_cli.py', 'README.md'],
            'verification': ['python -m unittest discover -s tests'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l3-needs-detail',
            'title': 'L3 detail request',
            'route': 'needs_detail',
            'readiness': 'needs_clarification',
            'task_packet': '# Task: L3 detail request\nRoute: needs_detail\n',
            'allowed_paths': [],
            'verification': ['Detail packet review confirms unresolved requirements are answered.'],
            'blockers': ['The exact persistence format is not specified.'],
        },
        {
            'task_id': 'phase6b-l4-macro-adjustment',
            'title': 'L4 macro adjustment',
            'route': 'macro_adjustment_request',
            'readiness': 'ready',
            'task_packet': '# Task: L4 macro adjustment\nRoute: macro_adjustment_request\n',
            'allowed_paths': [],
            'verification': ['Macro adjustment request is recorded for planner handling.'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l4-blocked',
            'title': 'L4 blocked external dependency',
            'route': 'blocked',
            'readiness': 'blocked',
            'required': False,
            'task_packet': '# Task: L4 blocked external dependency\nRoute: blocked\n',
            'allowed_paths': [],
            'verification': ['Blocker evidence identifies the missing external credential.'],
            'blockers': ['Required external credential is unavailable.'],
        },
    ]
    _write_completion_snapshot(
        project_root,
        job_id='job_route_mix_planner',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': tasks}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    expected_task_ids = [task['task_id'] for task in tasks]
    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_set_authority'
    assert payload['planner_contract'] == 'task_set'
    assert payload['task_count'] == 5
    assert payload['task_ids'] == expected_task_ids
    assert payload['source_task_settlement']['status'] == (
        'decomposed' if expects_task_set_authority else 'done'
    )
    assert payload['source_task_settlement']['task_id'] == 'route-mix-intake'
    task_set = (
        payload['task_set_authority']['task_set']
        if expects_task_set_authority
        else None
    )
    if task_set is not None:
        assert task_set['schema'] == 'ccb.plan.task_set.v1'
        assert task_set['state'] == 'running'
        assert task_set['task_set_revision'] == 1
        assert task_set['ordered_required_children'] == expected_task_ids[:-1]
        assert task_set['planner_job']['job_id'] == 'job_route_mix_planner'
        assert task_set['source_request']['source_job_id'] == 'job_frontdesk_route_mix'
    else:
        assert 'task_set_authority' not in payload
    for task_order, task_id in enumerate(expected_task_ids):
        shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
        assert shown['task']['status'] == 'ready_for_orchestration'
        assert shown['task']['next_owner'] == 'orchestrator'
        assert shown['task']['authority_trace']['source'] == 'loop_runner_role_output_import'
        assert shown['task']['authority_trace']['source_job']['job_id'] == 'job_route_mix_planner'
        artifacts = shown['task']['artifacts']
        assert set(artifacts) == {'execution_contract', 'task_packet'}
        assert artifacts['task_packet']['actor']['job_id'] == 'job_route_mix_planner'
        assert artifacts['execution_contract']['actor']['source'] == 'loop_runner_role_output_import'
        if task_set is not None:
            assert shown['task']['task_set']['task_set_id'] == task_set['task_set_id']
            assert shown['task']['task_set']['task_set_revision'] == 1
            assert shown['task']['task_set']['required'] is (task_id != 'phase6b-l4-blocked')
            assert shown['task']['task_set']['order'] == task_order
        else:
            assert 'task_set' not in shown['task']
    l1_contract_path = project_root / plan_task(
        context,
        SimpleNamespace(action='task-show', task_id='phase6b-l1-doc-direct-execution'),
    )['task']['artifacts']['execution_contract']['path']
    l1_contract = l1_contract_path.read_text(encoding='utf-8')
    assert 'Allowed Change Paths:' in l1_contract
    assert '- docs/l1-smoke.md' in l1_contract
    trace = (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8')
    assert 'imported_planner_task_set_authority' in trace
    assert 'phase6b-l2-code-direct-execution' in trace
    source = plan_task(context, SimpleNamespace(action='task-show', task_id='route-mix-intake'))
    if task_set is not None:
        assert source['task']['status'] == 'decomposed'
        assert source['task']['next_owner'] == 'planner'
        assert source['task']['activation_reason'].startswith('task_set_decomposed:')
        assert 'completion' not in source['task']['artifacts']
        assert source['task']['task_set_parent']['task_set_id'] == task_set['task_set_id']
    else:
        assert source['task']['status'] == 'done'
        assert source['task']['next_owner'] == 'terminal'
        assert source['task']['activation_reason'] == 'planner_task_set_decomposed_source_task'
        completion = source['task']['artifacts']['completion']
        assert completion['actor']['source'] == 'loop_runner_role_output_import'
    if expects_task_set_authority:
        import_log = project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl'
        import_log.unlink()
        post_commit_replay = loop_runner_once(
            context, command, services=SimpleNamespace(plan_task=plan_task)
        )
        assert post_commit_replay['action'] == 'imported_planner_task_set_authority'
        assert post_commit_replay['task_ids'] == expected_task_ids
    replay = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))
    assert replay['action'] == 'role_output_already_consumed'
    assert replay['task_ids'] == expected_task_ids
    if expects_task_set_authority:
        task_set_paths = list(
            (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'task-sets').glob(
                '*/task-set.json'
            )
        )
        assert len(task_set_paths) == 1
        index = json.loads(
            (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json').read_text(
                encoding='utf-8'
            )
        )
        assert len(index['tasks']) == len(expected_task_ids) + 1


def _planner_transaction_crash_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    monkeypatch.setattr(
        role_output_import_module, 'compile_project_effective_capacity_snapshot',
        lambda _root: {'config_version': 3},
    )
    command = ParsedLoopRunnerCommand(
        project=None, once=True, plan_slug='demo-plan', role_job_id='job-crash-planner',
        consume_role_output=True, json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write(project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'README.md', '# Demo Plan\n')
    plan_task(context, SimpleNamespace(
        action='task-create', plan_slug='demo-plan', title='Crash intake', task_id='crash-intake',
    ))
    intake = 'Crash recovery intake'
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-crash.json',
        {
            'schema_version': 1, 'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-crash', 'project_id': context.project.project_id,
            'project_root': str(project_root), 'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan', 'planner_contract': 'task_set',
            'source_task_id': 'crash-intake',
            'source_job': {'job_id': 'job-frontdesk-crash', 'agent_name': 'frontdesk'},
            'source_request': {
                'source_job_id': 'job-frontdesk-crash',
                'sha256': hashlib.sha256(intake.encode()).hexdigest(),
                'bytes': len(intake.encode()),
            },
            'ask': {'target': 'planner', 'job_id': 'job-crash-planner', 'status': 'accepted'},
        },
    )
    tasks = [
        {
            'task_id': f'crash-child-{index}', 'title': f'Crash child {index}',
            'route': 'direct_execution', 'readiness': 'ready',
            'task_packet': f'# Task: Crash child {index}\nRoute: direct_execution\n',
            'execution_contract': f'# Execution Contract\nRoute: direct_execution\nChild {index}.\n',
            'allowed_paths': [f'child-{index}.txt'], 'verification': [f'test -f child-{index}.txt'],
            'blockers': [],
        }
        for index in range(2)
    ]
    _write_completion_snapshot(
        project_root, job_id='job-crash-planner', agent_name='planner',
        reply='**task-set.json**\n```json\n' + json.dumps({'tasks': tasks}) + '\n```\n',
    )
    return project_root, context, command, [task['task_id'] for task in tasks]


@pytest.mark.parametrize(
    ('failure_stage', 'binding_crash_after'),
    (
        ('prepared', None),
        ('child_created:0', None),
        ('artifact_task_packet:0', None),
        ('artifact_execution_contract:0', None),
        (None, 1),
        (None, 2),
        ('child_ready:0', None),
        ('committed_before_log', None),
    ),
)
def test_planner_task_set_import_crash_replay_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str | None,
    binding_crash_after: int | None,
) -> None:
    project_root, context, command, child_ids = _planner_transaction_crash_case(tmp_path, monkeypatch)
    original_plan_task = plan_task
    binding_calls = 0

    def crash_hook(stage: str) -> None:
        if stage == failure_stage:
            raise SystemExit(f'crash:{stage}')

    def crash_plan_task(ctx, cmd):
        nonlocal binding_calls
        result = original_plan_task(ctx, cmd)
        if getattr(cmd, 'action', None) == 'task-bind-task-set':
            binding_calls += 1
            if binding_calls == binding_crash_after:
                raise SystemExit(f'crash:binding:{binding_calls}')
        return result

    monkeypatch.setattr(role_output_import_module, '_planner_task_set_import_failure_point', crash_hook)
    with pytest.raises(SystemExit, match='crash:'):
        loop_runner_once(
            context, command,
            services=SimpleNamespace(plan_task=crash_plan_task if binding_crash_after else original_plan_task),
        )
    journal_path = (
        project_root / '.ccb' / 'runtime' / 'role-output-imports' / 'job-crash-planner'
        / 'planner-task-set-import.transaction.json'
    )
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    expected_status = 'committed' if failure_stage == 'committed_before_log' else 'prepared'
    assert journal['status'] == expected_status
    source = plan_task(context, SimpleNamespace(action='task-show', task_id='crash-intake'))['task']
    assert source['status'] != 'done'
    for task_id in child_ids:
        try:
            child = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))['task']
        except ValueError:
            continue
        if child['status'] == 'ready_for_orchestration' and expected_status == 'prepared':
            assert find_first_actionable_task(context, task_id=task_id) is None

    monkeypatch.setattr(role_output_import_module, '_planner_task_set_import_failure_point', lambda _stage: None)
    replay = loop_runner_once(context, command, services=SimpleNamespace(plan_task=original_plan_task))
    assert replay['action'] == 'imported_planner_task_set_authority'
    assert replay['task_ids'] == child_ids
    committed = json.loads(journal_path.read_text(encoding='utf-8'))
    assert committed['status'] == 'committed'
    assert [child['task_id'] for child in committed['authority']['children']] == child_ids
    task_set_paths = list(
        (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'task-sets').glob('*/task-set.json')
    )
    assert len(task_set_paths) == 1
    index = json.loads(
        (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json').read_text()
    )
    assert [task['task_id'] for task in index['tasks']] == ['crash-intake', *child_ids]
    for task_id in child_ids:
        task = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))['task']
        assert set(task['artifacts']) == {'task_packet', 'execution_contract'}
        assert task['task_set']['task_set_id'] == committed['identity']['task_set_id']
        assert find_first_actionable_task(context, task_id=task_id) is not None
    import_lines = (
        project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl'
    ).read_text().splitlines()
    assert len([line for line in import_lines if 'job-crash-planner' in line]) == 1


def test_loop_runner_imports_single_planner_task_settles_frontdesk_source_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_single_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write(project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'README.md', '# Demo Plan\n')
    plan_task(
        context,
        SimpleNamespace(
            action='task-create',
            plan_slug='demo-plan',
            title='Frontdesk sync intake',
            task_id='sync-intake',
        ),
    )
    _write(
        project_root / '.ccb' / 'agents' / 'frontdesk' / 'jobs.jsonl',
        json.dumps(
            {
                'job_id': 'job_frontdesk_single',
                'agent_name': 'frontdesk',
                'request': {'task_id': 'sync-intake'},
                'status': 'accepted',
            },
            ensure_ascii=False,
        )
        + '\n',
    )
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-single-planner.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-single-planner',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'single_task',
            'source_job': {'job_id': 'job_frontdesk_single', 'agent_name': 'frontdesk'},
            'source_task_id': 'sync-intake',
            'ask': {
                'target': 'planner',
                'job_id': 'job_single_planner',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_single_planner',
        agent_name='planner',
        reply=(
            '**task-packet.md**\n'
            '```markdown\n'
            '# Task: Clarify external sync integration requirements\n'
            'Route: needs_detail\n'
            '## Goal\n'
            'Clarify the external sync integration before implementation.\n'
            '## Acceptance Criteria\n'
            '- The external API contract is explicit.\n'
            '## Interface Contracts\n'
            '- External API contract is currently unknown.\n'
            '## Constraints And Non-Goals\n'
            '- Do not implement before clarification.\n'
            '## Execution Decomposition Inputs\n'
            '- Independently reviewable surfaces: none before clarification.\n'
            '- Real predecessor dependencies: clarified API contract.\n'
            'Allowed paths:\n\n'
            'Verification:\n'
            '- Clarify external API contract.\n'
            '```\n\n'
            '**readiness.json**\n'
            '```json\n'
            '{"readiness":"needs_clarification","route":"needs_detail","blockers":["External API unknown"],'
            '"allowed_paths":[],"verification":["Clarify external API contract."]}\n'
            '```\n'
        ),
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['source_task_settlement']['status'] == 'done'
    assert payload['source_task_settlement']['task_id'] == 'sync-intake'
    child_task_id = payload['task_id']
    assert child_task_id != 'sync-intake'
    child = plan_task(context, SimpleNamespace(action='task-show', task_id=child_task_id))
    assert child['task']['status'] == 'ready_for_orchestration'
    source = plan_task(context, SimpleNamespace(action='task-show', task_id='sync-intake'))
    assert source['task']['status'] == 'done'
    assert source['task']['next_owner'] == 'terminal'
    assert source['task']['activation_reason'] == 'planner_single_task_handoff_source_task'
    completion = source['task']['artifacts']['completion']
    assert completion['actor']['job_id'] == 'job_single_planner'
    completion_text = (project_root / completion['path']).read_text(encoding='utf-8')
    assert '# Single Task Handoff Complete' in completion_text
    assert 'child_task_count: 1' in completion_text
    assert f'- {child_task_id}' in completion_text


def test_frontdesk_single_task_import_rejects_semantic_section_loss() -> None:
    activation = {
        'record_type': 'ccb_loop_frontdesk_planner_activation',
        'action': 'activate_planner_from_frontdesk',
    }
    parsed = {
        'task_packet': (
            '# Task: Flattened packet\n'
            'Route: direct_execution\n'
            'Allowed paths:\n'
            '- app.py\n'
            'Verification:\n'
            '- python -m unittest\n'
        )
    }

    result = role_output_import_module._validate_frontdesk_single_task_semantics(parsed, activation=activation)

    assert result['status'] == 'blocked'
    assert result['reason'] == 'planner_task_packet_missing_semantic_sections'
    assert result['missing_fields'] == [
        'task_packet.goal',
        'task_packet.acceptance criteria',
        'task_packet.interface contracts',
        'task_packet.constraints and non-goals',
        'task_packet.execution decomposition inputs',
    ]


def test_frontdesk_single_task_import_accepts_unambiguous_single_edit_heading_typo() -> None:
    activation = {
        'record_type': 'ccb_loop_frontdesk_planner_activation',
        'action': 'activate_planner_from_frontdesk',
    }
    parsed = {
        'task_packet': (
            '# Task: Preserve complete semantics\n'
            'Route: direct_execution\n'
            '## Goal\n'
            'Ship the requested behavior.\n'
            '## Acceptance Criteria\n'
            '- The behavior is observable.\n'
            '## Interface Contracts\n'
            '- Keep the stable API.\n'
            '## Constraints And Non-GGoals\n'
            '- Do not lower acceptance.\n'
            '## Execution Decomposition Inputs\n'
            '- Independently reviewable surfaces: implementation and tests.\n'
        )
    }

    result = role_output_import_module._validate_frontdesk_single_task_semantics(parsed, activation=activation)

    assert result['status'] == 'ok'
    assert result['semantic_sections'] == [
        'goal',
        'acceptance criteria',
        'interface contracts',
        'constraints and non-goals',
        'execution decomposition inputs',
    ]


def test_frontdesk_single_task_import_rejects_semantically_different_heading() -> None:
    activation = {
        'record_type': 'ccb_loop_frontdesk_planner_activation',
        'action': 'activate_planner_from_frontdesk',
    }
    parsed = {
        'task_packet': (
            '# Task: Missing non-goals\n'
            'Route: direct_execution\n'
            '## Goal\nvalue\n'
            '## Acceptance Criteria\nvalue\n'
            '## Interface Contracts\nvalue\n'
            '## Constraints And Goals\nvalue\n'
            '## Execution Decomposition Inputs\nvalue\n'
        )
    }

    result = role_output_import_module._validate_frontdesk_single_task_semantics(parsed, activation=activation)

    assert result['status'] == 'blocked'
    assert result['missing_fields'] == ['task_packet.constraints and non-goals']


def test_loop_runner_single_task_set_exposes_task_id_for_supervisor_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_single_task_set_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-single-task-set.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-single-task-set',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'ask': {
                'target': 'planner',
                'job_id': 'job_single_task_set_planner',
                'status': 'accepted',
            },
        },
    )
    task = {
        'task_id': 'local-risk-register-cli',
        'title': 'Build local project risk register CLI',
        'route': 'direct_execution',
        'readiness': 'ready',
        'task_packet': '# Task: Build local project risk register CLI\nRoute: direct_execution\n',
        'execution_contract': (
            '# Execution Contract\n'
            'Route: direct_execution\n\n'
            'Implement the CLI.\n\n'
            'Verification:\n'
            '- python -m unittest tests/test_risk_register_cli.py\n'
        ),
        'allowed_paths': ['scripts/risk_register.py', 'tests/test_risk_register_cli.py', 'README.md'],
        'verification': ['python -m unittest tests/test_risk_register_cli.py'],
        'blockers': [],
    }
    _write_completion_snapshot(
        project_root,
        job_id='job_single_task_set_planner',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': [task]}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['action'] == 'imported_planner_task_set_authority'
    assert payload['task_count'] == 1
    assert payload['task_ids'] == ['local-risk-register-cli']
    assert payload['task_id'] == 'local-risk-register-cli'
    assert payload['task_status'] == 'ready_for_orchestration'
    assert payload['next_owner'] == 'orchestrator'
    assert payload['route'] == 'direct_execution'
    assert payload['role_output_import']['task_id'] == 'local-risk-register-cli'
    assert payload['role_output_import']['task_status'] == 'ready_for_orchestration'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='local-risk-register-cli'))
    contract = (
        project_root / shown['task']['artifacts']['execution_contract']['path']
    ).read_text(encoding='utf-8')
    assert 'python -m unittest discover -s tests -p test_risk_register_cli.py' in contract
    assert 'python -m unittest tests/test_risk_register_cli.py' not in contract
    assert '- scripts/risk_register.py' in contract
    assert '- tests/test_risk_register_cli.py' in contract

    replay = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert replay['action'] == 'role_output_already_consumed'
    assert replay['consumed_action'] == 'imported_planner_task_set_authority'
    assert replay['task_count'] == 1
    assert replay['task_ids'] == ['local-risk-register-cli']
    assert replay['task_id'] == 'local-risk-register-cli'
    assert replay['task_status'] == 'ready_for_orchestration'
    assert replay['next_owner'] == 'orchestrator'
    assert replay['next_activation'] == 'orchestrator'


def test_planner_task_set_membership_defaults_required_and_validates_optional_boolean() -> None:
    base = {
        'task_id': 'child-a',
        'title': 'Child A',
        'route': 'direct_execution',
        'readiness': 'ready',
        'task_packet': '# Task: Child A\n',
        'allowed_paths': ['child-a.txt'],
        'verification': ['test -f child-a.txt'],
        'blockers': [],
    }

    required = role_output_import_module._parse_planner_task_set_item(base, index=0)
    optional = role_output_import_module._parse_planner_task_set_item(
        {**base, 'task_id': 'child-b', 'required': False},
        index=1,
    )
    invalid = role_output_import_module._parse_planner_task_set_item(
        {**base, 'task_id': 'child-c', 'required': 'optional'},
        index=2,
    )

    assert required['required'] is True
    assert optional['required'] is False
    assert invalid['status'] == 'blocked'
    assert invalid['reason'] == 'planner_task_set_invalid_membership'


def test_loop_runner_task_set_contract_appends_direct_verification_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_task_set_verification_contract_heading',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-task-set-verification-contract.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-task-set-verification-contract',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'ask': {
                'target': 'planner',
                'job_id': 'job_task_set_verification_contract_heading',
                'status': 'accepted',
            },
        },
    )
    task = {
        'task_id': 'todo-cli-core-persistence',
        'title': 'Implement TODO CLI with JSON persistence',
        'route': 'direct_execution',
        'readiness': 'ready',
        'task_packet': '# Task: Implement TODO CLI with JSON persistence\nRoute: direct_execution\n',
        'execution_contract': (
            '# Execution Contract\n'
            'Route: direct_execution\n\n'
            'Allowed Change Paths:\n'
            '- todo_cli/\n'
            '- pyproject.toml\n\n'
            'Verification Contract:\n'
            '- Exercise add/list/complete/stats/remove with isolated storage.\n'
        ),
        'allowed_paths': ['todo_cli/', 'pyproject.toml'],
        'verification': [
            'test -d todo_cli',
            'python -m unittest tests/test_todo_cli.py',
        ],
        'blockers': [],
    }
    _write_completion_snapshot(
        project_root,
        job_id='job_task_set_verification_contract_heading',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': [task]}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['action'] == 'imported_planner_task_set_authority'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='todo-cli-core-persistence'))
    contract = (
        project_root / shown['task']['artifacts']['execution_contract']['path']
    ).read_text(encoding='utf-8')
    assert 'Verification Contract:' in contract
    assert '\nVerification:\n- test -d todo_cli\n' in contract
    assert 'python -m unittest discover -s tests -p test_todo_cli.py' in contract


def test_loop_runner_task_set_uniquifies_existing_child_task_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_plan_task_record(
        project_root,
        task_id='todo-cli-core-persistence',
        status='replan_required',
        next_owner='planner',
        activation_reason='round_summary:replan_required',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_task_set_repeat_collision',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-task-set-repeat-collision.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-task-set-repeat-collision',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'ask': {
                'target': 'planner',
                'job_id': 'job_task_set_repeat_collision',
                'status': 'accepted',
            },
        },
    )
    task = {
        'task_id': 'todo-cli-core-persistence',
        'title': 'Implement TODO CLI with JSON persistence',
        'route': 'direct_execution',
        'readiness': 'ready',
        'task_packet': '# Task: Implement TODO CLI with JSON persistence\nRoute: direct_execution\n',
        'execution_contract': (
            '# Execution Contract\n'
            'Route: direct_execution\n\n'
            'Allowed Change Paths:\n'
            '- todo_cli/\n'
        ),
        'allowed_paths': ['todo_cli/'],
        'verification': ['test -d todo_cli'],
        'blockers': [],
    }
    _write_completion_snapshot(
        project_root,
        job_id='job_task_set_repeat_collision',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': [task]}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['action'] == 'imported_planner_task_set_authority'
    assert payload['task_count'] == 1
    assert payload['task_ids'] == ['todo-cli-core-persistence-jtasksetrepeat']
    old_task = plan_task(context, SimpleNamespace(action='task-show', task_id='todo-cli-core-persistence'))
    assert old_task['task']['status'] == 'replan_required'
    new_task = plan_task(context, SimpleNamespace(action='task-show', task_id='todo-cli-core-persistence-jtasksetrepeat'))
    assert new_task['task']['status'] == 'ready_for_orchestration'
    assert new_task['task']['activation_reason'] == 'planner_task_set_imported'


def test_loop_runner_task_set_rejects_shell_compound_verification_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_task_set_shell_verification',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-task-set-shell-verification.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-task-set-shell-verification',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'ask': {
                'target': 'planner',
                'job_id': 'job_task_set_shell_verification',
                'status': 'accepted',
            },
        },
    )
    task = {
        'task_id': 'todo-cli-core-persistence',
        'title': 'Implement TODO CLI with JSON persistence',
        'route': 'direct_execution',
        'readiness': 'ready',
        'task_packet': '# Task: Implement TODO CLI with JSON persistence\nRoute: direct_execution\n',
        'execution_contract': '# Execution Contract\nRoute: direct_execution\n\nAllowed Change Paths:\n- todo_cli/\n',
        'allowed_paths': ['todo_cli/'],
        'verification': [
            'tmpfile=$(mktemp) && python -m todo_cli --data-file "$tmpfile" add sample-task',
        ],
        'blockers': [],
    }
    _write_completion_snapshot(
        project_root,
        job_id='job_task_set_shell_verification',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': [task]}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_task_set_invalid_verification'
    assert 'shell command substitution' in payload['evidence']['error']
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_blocks_route_mix_task_set_with_drifted_task_ids_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_route_mix_planner_drifted_ids',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    expected_task_ids = [
        'phase6b-l1-doc-direct-execution',
        'phase6b-l2-code-test-direct-execution',
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
        'phase6b-l4-blocked-prerequisite',
    ]
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-route-mix.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-route-mix',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'expected_task_ids': expected_task_ids,
            'source_intake': {'preview': _route_mix_frontdesk_intake()[:400]},
            'ask': {
                'target': 'planner',
                'job_id': 'job_route_mix_planner_drifted_ids',
                'status': 'accepted',
            },
        },
    )
    drifted_tasks = [
        {
            'task_id': 'phase6b-l1-doc-direct-execution',
            'title': 'L1 documentation direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L1 documentation direct execution\nRoute: direct_execution\n',
            'allowed_paths': ['docs/l1-smoke.md'],
            'verification': ['test -f docs/l1-smoke.md'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l2-code-test-direct-execution',
            'title': 'L2 CLI direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L2 CLI direct execution\nRoute: direct_execution\n',
            'allowed_paths': ['src/l2_cli.py', 'tests/test_l2_cli.py'],
            'verification': ['python -m unittest discover -s tests'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l3-needs-detail-detail-ready',
            'title': 'L3 detail request',
            'route': 'needs_detail',
            'readiness': 'needs_clarification',
            'task_packet': '# Task: L3 detail request\nRoute: needs_detail\n',
            'allowed_paths': [],
            'verification': ['Detail packet review confirms unresolved requirements are answered.'],
            'blockers': ['The exact persistence format is not specified.'],
        },
        {
            'task_id': 'phase6b-l4-macro-adjust-replan-required',
            'title': 'L4 macro adjustment',
            'route': 'macro_adjustment_request',
            'readiness': 'not_ready',
            'task_packet': '# Task: L4 macro adjustment\nRoute: macro_adjustment_request\n',
            'allowed_paths': [],
            'verification': ['Macro adjustment request is recorded for planner handling.'],
            'blockers': ['Macro route needs replanning.'],
        },
        {
            'task_id': 'phase6b-l4-blocked-prerequisite',
            'title': 'L4 blocked external dependency',
            'route': 'blocked',
            'readiness': 'blocked',
            'task_packet': '# Task: L4 blocked external dependency\nRoute: blocked\n',
            'allowed_paths': [],
            'verification': ['Blocker evidence identifies the missing external credential.'],
            'blockers': ['Required external credential is unavailable.'],
        },
    ]
    _write_completion_snapshot(
        project_root,
        job_id='job_route_mix_planner_drifted_ids',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': drifted_tasks}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_task_set_unexpected_task_ids'
    assert payload['evidence']['expected_task_ids'] == expected_task_ids
    assert payload['evidence']['missing_task_ids'] == [
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
    ]
    assert payload['evidence']['unexpected_task_ids'] == [
        'phase6b-l3-needs-detail-detail-ready',
        'phase6b-l4-macro-adjust-replan-required',
    ]
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()
    trace = (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8')
    assert 'planner_task_set_unexpected_task_ids' in trace
    assert 'phase6b-l3-needs-detail-detail-ready' in trace


def test_loop_runner_blocks_route_mix_git_scope_contract_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_route_mix_planner_git_scope',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    expected_task_ids = [
        'phase6b-l1-doc-direct-execution',
        'phase6b-l2-code-test-direct-execution',
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
        'phase6b-l4-blocked-prerequisite',
    ]
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-route-mix-git-scope.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-route-mix-git-scope',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'expected_task_ids': expected_task_ids,
            'source_intake': {'preview': _route_mix_frontdesk_intake()[:400]},
            'ask': {
                'target': 'planner',
                'job_id': 'job_route_mix_planner_git_scope',
                'status': 'accepted',
            },
        },
    )
    tasks = [
        {
            'task_id': 'phase6b-l1-doc-direct-execution',
            'title': 'L1 documentation direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L1 documentation direct execution\nRoute: direct_execution\n',
            'execution_contract': (
                '# Execution Contract\n'
                'Route: direct_execution\n'
                'Allowed paths:\n'
                '- lab_docs/phase6b_l1_doc_direct_execution.md\n'
                'Verification:\n'
                '- test -f lab_docs/phase6b_l1_doc_direct_execution.md\n'
                '- git diff --name-only\n'
            ),
            'allowed_paths': ['lab_docs/phase6b_l1_doc_direct_execution.md'],
            'verification': ['test -f lab_docs/phase6b_l1_doc_direct_execution.md', 'git diff --name-only'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l2-code-test-direct-execution',
            'title': 'L2 CLI direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L2 CLI direct execution\nRoute: direct_execution\n',
            'allowed_paths': ['src/l2_cli.py', 'tests/test_l2_cli.py'],
            'verification': ['python -m unittest discover -s tests'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l3-needs-detail',
            'title': 'L3 detail request',
            'route': 'needs_detail',
            'readiness': 'needs_clarification',
            'task_packet': '# Task: L3 detail request\nRoute: needs_detail\n',
            'allowed_paths': [],
            'verification': ['Detail packet review confirms unresolved requirements are answered.'],
            'blockers': ['The exact persistence format is not specified.'],
        },
        {
            'task_id': 'phase6b-l4-macro-adjustment-request',
            'title': 'L4 macro adjustment',
            'route': 'macro_adjustment_request',
            'readiness': 'not_ready',
            'task_packet': '# Task: L4 macro adjustment\nRoute: macro_adjustment_request\n',
            'allowed_paths': [],
            'verification': ['Macro adjustment request is recorded for planner handling.'],
            'blockers': ['Macro route needs replanning.'],
        },
        {
            'task_id': 'phase6b-l4-blocked-prerequisite',
            'title': 'L4 blocked external dependency',
            'route': 'blocked',
            'readiness': 'blocked',
            'task_packet': '# Task: L4 blocked external dependency\nRoute: blocked\n',
            'allowed_paths': [],
            'verification': ['Blocker evidence identifies the missing external credential.'],
            'blockers': ['Required external credential is unavailable.'],
        },
    ]
    _write_completion_snapshot(
        project_root,
        job_id='job_route_mix_planner_git_scope',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': tasks}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_task_set_git_scope_check_unsupported'
    assert payload['evidence']['unsupported_scope_checks'] == [
        {
            'task_id': 'phase6b-l1-doc-direct-execution',
            'route': 'direct_execution',
            'fields': ['execution_contract', 'verification'],
        }
    ]
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_imports_route_mix_task_set_with_negative_git_scope_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_route_mix_planner_negative_git_scope',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    expected_task_ids = [
        'phase6b-l1-doc-direct-execution',
        'phase6b-l2-code-test-direct-execution',
        'phase6b-l3-needs-detail',
        'phase6b-l4-macro-adjustment-request',
        'phase6b-l4-blocked-prerequisite',
    ]
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-route-mix-negative-git-scope.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-route-mix-negative-git-scope',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': 'task_set',
            'expected_task_ids': expected_task_ids,
            'source_intake': {'preview': _route_mix_frontdesk_intake()[:400]},
            'ask': {
                'target': 'planner',
                'job_id': 'job_route_mix_planner_negative_git_scope',
                'status': 'accepted',
            },
        },
    )
    tasks = [
        {
            'task_id': 'phase6b-l1-doc-direct-execution',
            'title': 'L1 documentation direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L1 documentation direct execution\nRoute: direct_execution\n',
            'execution_contract': (
                '# Execution Contract\n'
                'Route: direct_execution\n'
                'Worker may edit only lab_docs/phase6b_l1_doc_direct_execution.md.\n'
                'Do not require git diff, git status, or any git-only scope check.\n'
            ),
            'allowed_paths': ['lab_docs/phase6b_l1_doc_direct_execution.md'],
            'verification': ['test -f lab_docs/phase6b_l1_doc_direct_execution.md'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l2-code-test-direct-execution',
            'title': 'L2 CLI direct execution',
            'route': 'direct_execution',
            'readiness': 'ready',
            'task_packet': '# Task: L2 CLI direct execution\nRoute: direct_execution\n',
            'execution_contract': (
                '# Execution Contract\n'
                'Route: direct_execution\n'
                'Verification is repo-independent and must use unittest, not git status.\n'
            ),
            'allowed_paths': ['src/l2_cli.py', 'tests/test_l2_cli.py'],
            'verification': ['python -m unittest discover -s tests -p test_l2_cli.py'],
            'blockers': [],
        },
        {
            'task_id': 'phase6b-l3-needs-detail',
            'title': 'L3 detail request',
            'route': 'needs_detail',
            'readiness': 'needs_clarification',
            'task_packet': '# Task: L3 detail request\nRoute: needs_detail\n',
            'allowed_paths': [],
            'verification': ['Detail packet review confirms unresolved requirements are answered.'],
            'blockers': ['The exact persistence format is not specified.'],
        },
        {
            'task_id': 'phase6b-l4-macro-adjustment-request',
            'title': 'L4 macro adjustment',
            'route': 'macro_adjustment_request',
            'readiness': 'not_ready',
            'task_packet': '# Task: L4 macro adjustment\nRoute: macro_adjustment_request\n',
            'allowed_paths': [],
            'verification': ['Macro adjustment request is recorded for planner handling.'],
            'blockers': ['Macro route needs replanning.'],
        },
        {
            'task_id': 'phase6b-l4-blocked-prerequisite',
            'title': 'L4 blocked external dependency',
            'route': 'blocked',
            'readiness': 'blocked',
            'task_packet': '# Task: L4 blocked external dependency\nRoute: blocked\n',
            'allowed_paths': [],
            'verification': ['Blocker evidence identifies the missing external credential.'],
            'blockers': ['Required external credential is unavailable.'],
        },
    ]
    _write_completion_snapshot(
        project_root,
        job_id='job_route_mix_planner_negative_git_scope',
        agent_name='planner',
        reply='**task-set.json**\n```json\n'
        + json.dumps({'tasks': tasks}, indent=2)
        + '\n```\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_set_authority'
    assert payload['task_ids'] == expected_task_ids
    for task_id in expected_task_ids:
        shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
        assert shown['task']['authority_trace']['source'] == 'loop_runner_role_output_import'
        assert shown['task']['status'] == 'ready_for_orchestration'


def test_loop_runner_blocks_route_mix_planner_meta_task_only_reply_without_mutating_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_sequence19_meta_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-sequence19.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_frontdesk_planner_activation',
            'activation_id': 'act-sequence19',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'action': 'activate_planner_from_frontdesk',
            'plan_slug': 'demo-plan',
            'planner_contract': None,
            'source_intake': {'preview': _route_mix_frontdesk_intake()[:400]},
            'ask': {
                'target': 'planner',
                'job_id': 'job_sequence19_meta_planner',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_sequence19_meta_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Controller-owned real-provider L1-L4 route-mix validation
Route: direct_execution
Allowed paths:
- docs/plantree/plans/agentic-loop-workflow/topics/sequence19-b7.md
Verification:
- python scripts/phase6b_l1_l4_frontdesk_runner.py b7
```

**readiness.json**
```json
{
  "readiness": "ready",
  "route": "direct_execution",
  "blockers": [],
  "allowed_paths": ["docs/plantree/plans/agentic-loop-workflow/topics/sequence19-b7.md"],
  "verification": ["python scripts/phase6b_l1_l4_frontdesk_runner.py b7"]
}
```
""",
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_task_set_required'
    assert payload['evidence']['single_task_reply_detected'] is True
    assert payload['evidence']['missing_fields'] == ['task-set.json fenced section']
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()
    trace = (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8')
    assert 'planner_task_set_required' in trace
    assert 'job_sequence19_meta_planner' in trace


def test_loop_runner_consumes_post_detail_planner_activation_even_with_existing_task_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-detail')
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.json'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(action='task-artifact', task_id='task-detail', artifact_kind=kind, file_path=str(source)),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='task-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )

    activation_path = project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-post-detail.json'
    _write_json(
        activation_path,
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_planner_activation',
            'activation_id': 'act-post-detail',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'task_id': 'task-detail',
            'task_status': 'detail_ready',
            'action': 'activate_planner',
            'reason_for_activation': 'detail_ready_task',
            'ask': {
                'target': 'planner',
                'job_id': 'job_post_detail_planner',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_post_detail_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Implement detail-ready work

Route: direct_execution
Validation: L3 needs_detail path reached detail_ready before implementation.
Allowed paths:
- lab_detail/work.py
- tests/test_work.py

Verification:
- python -m pytest tests/test_work.py
```

**readiness.json**
```json
{
  "readiness": "ready",
  "route": "direct_execution",
  "blockers": [],
  "allowed_paths": ["lab_detail/work.py", "tests/test_work.py"],
  "verification": ["python -m pytest tests/test_work.py"]
}
```
""",
    )

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('completed post-detail planner activation must be consumed before submitting another planner ask')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['job_id'] == 'job_post_detail_planner'
    assert payload['task_id'] == 'task-detail'
    assert payload['task_status'] == 'ready_for_orchestration'
    assert payload['next_owner'] == 'orchestrator'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-detail'))
    assert shown['task']['status'] == 'ready_for_orchestration'
    assert shown['task']['next_owner'] == 'orchestrator'
    assert shown['task']['artifacts']['task_packet']['actor']['job_id'] == 'job_post_detail_planner'
    assert shown['task']['artifacts']['execution_contract']['actor']['job_id'] == 'job_post_detail_planner'
    trace = (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8')
    assert 'job_post_detail_planner' in trace


@pytest.mark.parametrize(
    ('reply_mutation', 'constraint_mutation', 'expected_reason'),
    (
        (None, None, None),
        ('missing_recommendation', None, 'planner_terminal_status_reply_mismatch'),
        ('conflicting_recommendation', None, 'planner_terminal_status_reply_mismatch'),
        ('conflicting_reason', None, 'planner_terminal_status_reply_mismatch'),
        ('invalid_reason', None, 'planner_readiness_invalid_reason'),
        ('conflicting_route', None, 'planner_terminal_status_reply_mismatch'),
        ('nonempty_allowed_paths', None, 'planner_terminal_status_reply_mismatch'),
        (None, 'stale_revision', 'stale_managed_activation_task_revision'),
        (None, 'tampered_digest', 'planner_terminal_status_constraint_stale_authority'),
        (None, 'tampered_provenance', 'planner_terminal_status_constraint_stale_authority'),
    ),
)
def test_loop_runner_keeps_root13_shaped_bounded_post_detail_planner_reply_at_detail_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reply_mutation: str | None,
    constraint_mutation: str | None,
    expected_reason: str | None,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='root13-detail-bound',
        task_packet_text=(
            '# Task: root13-detail-bound\n'
            'Route: needs_detail\n'
            'Expected stop: detail_ready.\n'
        ),
        execution_contract_text=(
            '# Execution Contract\n'
            'Route: needs_detail\n'
            'The controller-visible task outcome remains detail_ready.\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='root13-detail-bound', route='needs_detail')

    def fake_submit_detailer(_context, ask_command):
        assert ask_command.target == 'task_detailer'
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_root13_detailer', 'agent_name': 'task_detailer', 'status': 'submitted'},),
        )

    activated = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_detailer, plan_task=plan_task),
    )
    assert activated['action'] == 'activated_task_detailer'
    _write_completion_snapshot(
        project_root,
        job_id='job_root13_detailer',
        agent_name='task_detailer',
        reply="""Detail result: `local_detail_ready`
Detail readiness recommendation: `detail_ready`

## Artifact: `task-detail-design.md`
```markdown
# Detail Design
Resolved.
```

## Artifact: `brief-update-summary.md`
```markdown
# Detail Summary
Resolved.
```

detail-packet.manifest.json:
```json
{"schema":"ccb.detail_packet_manifest.v1","detail_result":"local_detail_ready","readiness":"detail_ready","global_impact":"none"}
```
""",
    )
    imported = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))
    assert imported['action'] == 'imported_task_detailer_detail_authority'
    before = plan_task(context, SimpleNamespace(action='task-show', task_id='root13-detail-bound'))['task']
    authority = plan_tasks_module.detail_ready_stop_contract_authority(
        before,
        project_root=project_root,
    )
    assert authority is not None
    generated = loop_runner_module._planner_activation_packet(
        context,
        before,
        activation_id='act-generated-root13-post-detail',
        action='activate_planner',
        reason='detail_ready_task',
    )
    assert generated['terminal_status_constraint']['authority_digest'] == authority['authority_digest']
    constrained_message = loop_runner_module._planner_message(generated)
    assert 'Terminal status constraint:' in constrained_message
    assert 'route `needs_detail`, status_recommendation `detail_ready`' in constrained_message
    assert 'empty allowed_paths list and no blockers' in constrained_message
    ordinary = dict(before)
    ordinary['status'] = 'draft'
    ordinary_activation = loop_runner_module._planner_activation_packet(
        context,
        ordinary,
        activation_id='act-ordinary-planner',
        action='activate_planner',
        reason='draft_task',
    )
    assert 'terminal_status_constraint' not in ordinary_activation
    assert 'Terminal status constraint:' not in loop_runner_module._planner_message(ordinary_activation)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-root13-post-detail.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_planner_activation',
            'activation_id': 'act-root13-post-detail',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'plan_slug': 'demo-plan',
            'task_id': 'root13-detail-bound',
            'task_revision': before['task_revision'],
            'task_status': 'detail_ready',
            'action': 'activate_planner',
            'reason_for_activation': 'detail_ready_task',
            'terminal_status_constraint': {
                'schema_version': 1,
                'status': 'detail_ready',
                'basis': 'verified_detail_ready_stop_contract',
                'task_id': 'root13-detail-bound',
                'task_revision': before['task_revision'],
                'state_version': before['state_version'],
                'authority_digest': authority['authority_digest'],
                'basis_digest': authority['basis_digest'],
                'required_reason': 'detail_ready_task',
            },
            'ask': {
                'target': 'planner',
                'job_id': 'job_root13_post_detail_planner',
                'status': 'accepted',
            },
        },
    )
    activation_path = project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-root13-post-detail.json'
    activation = json.loads(activation_path.read_text(encoding='utf-8'))
    if constraint_mutation == 'stale_revision':
        activation['task_revision'] += 1
        activation['terminal_status_constraint']['task_revision'] += 1
    elif constraint_mutation == 'tampered_digest':
        activation['terminal_status_constraint']['authority_digest'] = '0' * 64
    elif constraint_mutation == 'tampered_provenance':
        detail_packet = project_root / before['artifacts']['detail_packet']['path']
        detail_packet.write_text('tampered detail packet\n', encoding='utf-8')
    _write_json(activation_path, activation)
    readiness = {
        'readiness': 'ready',
        'route': 'needs_detail',
        'status_recommendation': 'detail_ready',
        'reason': 'detail_ready_task',
        'blockers': [],
        'allowed_paths': [],
        'verification': ['python -m pytest tests/test_bounded_detail.py'],
    }
    if reply_mutation == 'missing_recommendation':
        readiness.pop('status_recommendation')
    elif reply_mutation == 'conflicting_recommendation':
        readiness['status_recommendation'] = 'ready_for_orchestration'
    elif reply_mutation == 'conflicting_reason':
        readiness['reason'] = 'other_reason'
    elif reply_mutation == 'invalid_reason':
        readiness['reason'] = 'not a valid reason'
    elif reply_mutation == 'conflicting_route':
        readiness['route'] = 'direct_execution'
        readiness['allowed_paths'] = ['bounded_detail/work.py']
    elif reply_mutation == 'nonempty_allowed_paths':
        readiness['allowed_paths'] = ['bounded_detail/work.py']
    _write_completion_snapshot(
        project_root,
        job_id='job_root13_post_detail_planner',
        agent_name='planner',
        reply=(
            '**task-packet.md**\n'
            '```markdown\n'
            '# Task: root13-detail-bound\n'
            'Route: needs_detail\n'
            'Expected stop: detail_ready.\n\n'
            'Allowed paths:\n\n'
            'Verification:\n'
            '- python -m pytest tests/test_bounded_detail.py\n'
            '```\n\n'
            '**readiness.json**\n'
            '```json\n'
            + json.dumps(readiness, indent=2)
            + '\n```\n'
        ),
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='root13-detail-bound'))
    assert shown['task']['status'] == 'detail_ready'
    assert shown['task']['task_revision'] == before['task_revision']
    assert shown['task']['state_version'] == before['state_version']
    if expected_reason is not None:
        assert payload['loop_runner_status'] == 'blocked'
        assert payload['action'] == 'role_output_import_blocked'
        assert payload['reason'] == expected_reason
        return

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'settled_planner_terminal_status_constraint'
    assert payload['task_status'] == 'detail_ready'
    assert payload['next_owner'] == 'planner'
    replay = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(
            project=None,
            once=True,
            plan_slug='demo-plan',
            role_job_id='job_root13_post_detail_planner',
            consume_role_output=True,
            json_output=True,
        ),
        services=SimpleNamespace(plan_task=plan_task),
    )
    assert replay['action'] == 'role_output_already_consumed'
    assert replay['idempotent'] is True
    assert replay['consumed_action'] == 'settled_planner_terminal_status_constraint'
    assert plan_task(context, SimpleNamespace(action='task-show', task_id='root13-detail-bound'))['task'] == shown['task']
    stale_activation = json.loads(activation_path.read_text(encoding='utf-8'))
    stale_activation['task_revision'] += 1
    stale_activation['terminal_status_constraint']['task_revision'] += 1
    _write_json(activation_path, stale_activation)

    restarted_context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def forbidden_submit_after_restart(_context, ask_command):
        raise AssertionError(
            f'settled bounded detail_ready task must not reactivate {ask_command.target} after restart'
        )

    restarted_replay = loop_runner_once(
        restarted_context,
        ParsedLoopRunnerCommand(
            project=None,
            once=True,
            plan_slug='demo-plan',
            role_job_id='job_root13_post_detail_planner',
            consume_role_output=True,
            json_output=True,
        ),
        services=SimpleNamespace(submit_ask=forbidden_submit_after_restart, plan_task=plan_task),
    )
    assert restarted_replay['action'] == 'role_output_already_consumed'
    assert restarted_replay['idempotent'] is True
    assert restarted_replay['consumed_action'] == 'settled_planner_terminal_status_constraint'
    assert (
        plan_task(restarted_context, SimpleNamespace(action='task-show', task_id='root13-detail-bound'))['task']
        == shown['task']
    )
    restarted_command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    settled = loop_runner_once(
        restarted_context,
        restarted_command,
        services=SimpleNamespace(submit_ask=forbidden_submit_after_restart, plan_task=plan_task),
    )
    assert settled['loop_runner_status'] == 'idle'
    assert settled['reason'] == 'no_actionable_task'
    assert (
        plan_task(restarted_context, SimpleNamespace(action='task-show', task_id='root13-detail-bound'))['task']
        == shown['task']
    )
    assert find_first_actionable_task(restarted_context, task_id='root13-detail-bound') is None


def test_loop_runner_leaves_explicit_non_success_stop_contracts_settled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(
        project_root,
        task_id='phase6b-l3-needs-detail',
        task_packet_text=(
            '# Task: phase6b-l3-needs-detail\n'
            'Route: needs_detail\n'
            'This validation case must preserve the needs_detail route and stop at detail_ready.\n'
        ),
        execution_contract_text=(
            '# Execution Contract\n'
            'Route: needs_detail\n'
            'The controller-visible task outcome remains detail_ready.\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _import_orchestration_notes(context, project_root, task_id='phase6b-l3-needs-detail', route='needs_detail')
    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.json'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l3-needs-detail',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l3-needs-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )
    plan_task(
        context,
        SimpleNamespace(
            action='task-create',
            plan_slug='demo-plan',
            task_id='phase6b-l4-macro-adjustment-request',
            title='L4 macro-adjustment stop at replan_required',
        ),
    )
    for kind, filename, text in (
        (
            'task_packet',
            'macro-task-packet.md',
            '# Task: L4 macro-adjustment stop at replan_required\nRoute: macro_adjustment_request\n',
        ),
        (
            'execution_contract',
            'macro-execution-contract.md',
            '# Execution Contract\nExpected controller-visible stop is replan_required.\n',
        ),
    ):
        source = project_root / 'drafts' / filename
        _write(source, text)
        plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='phase6b-l4-macro-adjustment-request',
                artifact_kind=kind,
                file_path=str(source),
            ),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l4-macro-adjustment-request',
            status='ready_for_orchestration',
            activation_reason='planner_task_set_imported',
        ),
    )
    _import_orchestration_notes(
        context,
        project_root,
        task_id='phase6b-l4-macro-adjustment-request',
        route='macro_adjustment_request',
    )
    macro_source = project_root / 'drafts' / 'macro-adjustment-request.json'
    _write(macro_source, '{"status_transition":"replan_required"}\n')
    plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id='phase6b-l4-macro-adjustment-request',
            artifact_kind='macro_adjustment_request',
            file_path=str(macro_source),
        ),
    )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='phase6b-l4-macro-adjustment-request',
            status='replan_required',
            activation_reason='orchestrator_route_macro_adjustment_request:script_owned_route',
        ),
    )

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('explicit stop-at-status tasks must not reactivate planner')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'idle'
    assert payload['reason'] == 'no_actionable_task'
    detail = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l3-needs-detail'))
    macro = plan_task(context, SimpleNamespace(action='task-show', task_id='phase6b-l4-macro-adjustment-request'))
    assert detail['task']['status'] == 'detail_ready'
    assert macro['task']['status'] == 'replan_required'


def test_loop_runner_explicit_consume_uses_matching_activation_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-detail')
    context = CliContextBuilder().build(
        ParsedLoopRunnerCommand(project=None, once=True, json_output=True),
        cwd=project_root,
        bootstrap_if_missing=False,
    )

    for kind, filename in (
        ('detail_design', 'detail-design.md'),
        ('detail_summary', 'detail-summary.md'),
        ('detail_packet', 'detail-packet.json'),
    ):
        source = project_root / 'drafts' / filename
        _write(source, f'{kind}\n')
        plan_task(
            context,
            SimpleNamespace(action='task-artifact', task_id='task-detail', artifact_kind=kind, file_path=str(source)),
        )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='task-detail',
            status='detail_ready',
            activation_reason='detail_ready_from_task_detailer',
        ),
    )
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-post-detail.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_planner_activation',
            'activation_id': 'act-post-detail',
            'project_id': context.project.project_id,
            'project_root': str(project_root),
            'plan_slug': 'demo-plan',
            'task_id': 'task-detail',
            'task_status': 'detail_ready',
            'action': 'activate_planner',
            'reason_for_activation': 'detail_ready_task',
            'ask': {
                'target': 'planner',
                'job_id': 'job_post_detail_planner',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_post_detail_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Implement detail-ready work

Route: direct_execution
Allowed paths:
- lab_detail/work.py
- tests/test_work.py

Verification:
- python -m pytest tests/test_work.py
```

**readiness.json**
```json
{
  "readiness": "ready",
  "route": "direct_execution",
  "blockers": [],
  "allowed_paths": ["lab_detail/work.py", "tests/test_work.py"],
  "verification": ["python -m pytest tests/test_work.py"]
}
```
""",
    )

    payload = loop_runner_once(
        context,
        ParsedLoopRunnerCommand(
            project=None,
            once=True,
            plan_slug='demo-plan',
            role_job_id='job_post_detail_planner',
            consume_role_output=True,
            json_output=True,
        ),
        services=SimpleNamespace(plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['job_id'] == 'job_post_detail_planner'
    assert payload['created_task'] is False
    assert payload['task_id'] == 'task-detail'
    assert payload['task_status'] == 'ready_for_orchestration'
    assert payload['next_owner'] == 'orchestrator'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-detail'))
    assert shown['task']['status'] == 'ready_for_orchestration'
    assert shown['task']['next_owner'] == 'orchestrator'
    assert shown['task']['artifacts']['task_packet']['actor']['job_id'] == 'job_post_detail_planner'
    assert shown['task']['artifacts']['execution_contract']['actor']['job_id'] == 'job_post_detail_planner'
    tasks_root = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks'
    assert sorted(path.name for path in tasks_root.iterdir() if path.is_dir()) == ['task-detail']


def test_loop_runner_accepts_frontdesk_intake_evidence_shape_from_real_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    frontdesk_reply = """**Intake Evidence**

CCB_REQ_ID: `job_97346115f59e`

Macro request: Build a small local Python task-list feature.

Scope:
- Implement `lab_tasks/task_list.py`
- Add tests in `tests/test_task_list.py`

Required behavior:
- Add, list, complete, and filter tasks by status/tag
- Stable positive integer task IDs
- Useful exceptions for blank titles and invalid IDs
- Normalize tags to lowercase, stripped, unique strings
- Focused pytest coverage for add/list/complete/filter/validation

    Constraints:
- Keep implementation small and local
- Downstream planner/orchestrator/runner should create task authority and route execution
- Provider/frontdesk should not implement or mutate CCB authority state
"""
    _write_source_ask_job(
        project_root,
        job_id='job_real_frontdesk',
        body='Build a small local Python task-list feature with stable ids, normalized tags, validation, and tests.\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_real_frontdesk',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_real_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[tuple[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append((ask_command.target, ask_command.message))
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_real', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner_from_frontdesk'
    assert payload['ask'] == {'target': 'planner', 'job_id': 'job_planner_real', 'status': 'submitted'}
    assert submitted[0][0] == 'planner'
    assert 'Frontdesk intake evidence:' in submitted[0][1]
    assert 'Macro request: Build a small local Python task-list feature.' in submitted[0][1]
    assert (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').is_dir()


def test_loop_runner_frontdesk_file_creation_request_hands_off_without_file_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    frontdesk_reply = """**Intake Evidence**

CCB_REQ_ID: `job_runtime_retest_a`

Macro request: Create a small runtime retest note at docs/runtime-retest-a.md.

Scope:
- `docs/runtime-retest-a.md`

Required behavior:
- The requested document should contain a concise runtime retest note.

Constraints:
- Frontdesk must not create, edit, inspect, or verify the file.
- Planner/orchestrator/worker flow owns task authority, implementation, and verification.
"""
    _write_source_ask_job(
        project_root,
        job_id='job_runtime_retest_a',
        body='Create `docs/runtime-retest-a.md` containing a concise runtime retest note.\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_runtime_retest_a',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_runtime_retest_a',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[tuple[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append((ask_command.target, ask_command.message))
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_runtime_retest_a', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner_from_frontdesk'
    assert payload['ask'] == {'target': 'planner', 'job_id': 'job_planner_runtime_retest_a', 'status': 'submitted'}
    assert submitted[0][0] == 'planner'
    assert 'docs/runtime-retest-a.md' in submitted[0][1]
    assert not (project_root / 'docs' / 'runtime-retest-a.md').exists()


def test_loop_runner_accepts_frontdesk_labeled_intake_without_heading_from_real_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    frontdesk_reply = """CCB_REQ_ID: job_a587a6cdc4aa

Macro request: Build a small Python task-list module with tests for adding, listing, completing, and filtering tasks.

Scope:
- `lab_tasks/task_list.py`
- `tests/test_task_list.py`

Required behavior:
- Provide functions to add tasks, list tasks, complete tasks, and filter by status/tag.
- Use stable positive integer task ids.
- Reject blank task titles and invalid ids with useful exceptions.
- Normalize tags to lowercase, stripped, unique strings.
- Include focused pytest coverage for add/list/complete/filter/validation behavior.

Constraints:
- Keep implementation small and local.
- Downstream planner/orchestrator/runner should create task authority and route execution.
- Provider must not run shell commands, mutate CCB authority, create/import/update plans or tasks, or run CCB/runtime/status/cleanup commands.
"""
    _write_source_ask_job(
        project_root,
        job_id='job_labeled_frontdesk',
        body='Build a small Python task-list module with add/list/complete/filter behavior and focused tests.\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_labeled_frontdesk',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_labeled_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_submit_ask(_context, ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_labeled', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner_from_frontdesk'
    assert payload['ask'] == {'target': 'planner', 'job_id': 'job_planner_labeled', 'status': 'submitted'}


def test_loop_runner_accepts_structured_frontdesk_blocked_evidence_for_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    frontdesk_reply = """**Blocked Evidence**

Requested validation: Validate a private production billing integration requiring `PRIVATE_BILLING_ROUTE_TOKEN`.

Blocker: Required production credential and private endpoint access are unavailable in this lab.

Routing recommendation: Route to blocked before implementation or worker execution.

Prohibited actions: Do not fake credentials, bypass the private endpoint, or implement simulated success.
"""
    _write_source_ask_job(
        project_root,
        job_id='job_structured_blocked_frontdesk',
        body='Validate the private production billing integration using `PRIVATE_BILLING_ROUTE_TOKEN`.\n',
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_structured_blocked_frontdesk',
        agent_name='frontdesk',
        reply=frontdesk_reply,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_structured_blocked_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    submitted: list[tuple[str, str]] = []

    def fake_submit_ask(_context, ask_command):
        submitted.append((ask_command.target, ask_command.message))
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_blocked', 'agent_name': ask_command.target, 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask, plan_task=plan_task),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'activated_planner_from_frontdesk'
    assert payload['ask'] == {'target': 'planner', 'job_id': 'job_planner_blocked', 'status': 'submitted'}
    assert submitted[0][0] == 'planner'
    assert '**Blocked Evidence**' in submitted[0][1]
    assert 'Route: <direct_execution|needs_detail|macro_adjustment_request|blocked|partial_completion>' in submitted[0][1]


def test_loop_runner_role_output_import_blocks_frontdesk_intake_without_execution_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_weak_frontdesk',
        agent_name='frontdesk',
        reply="""**Intake Evidence**

Macro request: Build something useful.
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_weak_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'frontdesk_reply_missing_required_anchors'
    assert payload['evidence']['missing_fields'] == [
        'Execution Contract, Acceptance Criteria, or Required behavior with Scope/Constraints'
    ]
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_blocks_weak_frontdesk_blocked_freeform_without_mutating_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_weak_blocked_frontdesk',
        agent_name='frontdesk',
        reply='**Blocked Evidence**\n\nCannot do this because credentials are missing.\n',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_weak_blocked_frontdesk',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'frontdesk_reply_missing_required_anchors'
    assert 'Macro request or User request detail' in payload['evidence']['missing_fields']
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_role_output_import_blocks_ambiguous_planner_reply_without_mutating_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_bad_planner',
        agent_name='planner',
        reply='**task-packet.md**\n```markdown\n# Task: Missing readiness\n```\n',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_bad_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_reply_missing_required_sections'
    assert payload['evidence']['missing_fields'] == ['readiness.json fenced section']
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_role_output_import_blocks_unsafe_planner_allowed_paths_without_mutating_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_unsafe_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Unsafe Scope
```

**readiness.json**
```json
{
  "readiness": "ready",
  "route": "direct_execution",
  "allowed_paths": ["../outside.py", ".ccb/runtime/authority.json"],
  "verification": ["python -m pytest"]
}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_unsafe_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_readiness_invalid_allowed_paths'
    assert payload['evidence']['invalid_allowed_paths'] == ['../outside.py', '.ccb/runtime/authority.json']
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_imports_needs_detail_planner_reply_without_execution_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_needs_detail_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Local file import/export task manager
Route: needs_detail
Allowed paths:
- <none until detail is resolved>
Verification:
- Detail packet review confirms file format, persistence policy, conflict behavior, malformed-file validation, duplicate task id handling, and CLI/API surface are specified.
```

**readiness.json**
```json
{
  "readiness": "needs_clarification",
  "route": "needs_detail",
  "blockers": [
    "Import/export file format is unspecified.",
    "Persistence path or directory policy is unspecified."
  ],
  "allowed_paths": [],
  "verification": [
    "Detail packet review confirms all required product decisions are answered before implementation."
  ]
}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_needs_detail_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['task_status'] == 'ready_for_orchestration'
    assert payload['next_owner'] == 'orchestrator'
    task_id = str(payload['task_id'])
    assert task_id != 'None'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    artifacts = shown['task']['artifacts']
    assert set(artifacts) == {'execution_contract', 'task_packet'}
    contract = (project_root / artifacts['execution_contract']['path']).read_text(encoding='utf-8')
    assert 'Route: needs_detail' in contract
    assert 'Detail packet review confirms all required product decisions' in contract


def test_loop_runner_imports_real_sequence37_needs_detail_planner_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_sequence37_needs_detail_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Clarify local task manager import/export behavior
Route: needs_detail
Allowed paths:

Blockers:
- Import/export file format is unspecified, including encoding, schema, required fields, optional fields, schema versioning, and whether task metadata must round-trip exactly.
- Persistence policy is unresolved, including default directory/path, whether paths are configurable, directory creation behavior, and handling of missing/unwritable locations.

Acceptance criteria for clarification:
- Define the import/export file format and a minimal example payload.
- Define where exported/imported data is read or written by default and how custom paths are handled.

Verification:
- Manual requirements review: confirm answers cover file format, persistence path policy, conflict handling, validation rules, duplicate id policy, and CLI/API expectations.
```

**readiness.json**
```json
{
  "readiness": "needs_clarification",
  "route": "needs_detail",
  "blockers": [
    "Import/export file format is unspecified, including schema, encoding, versioning, and task fields.",
    "Persistence location and directory/path policy are unresolved."
  ],
  "allowed_paths": [],
  "verification": [
    "Manual requirements review: confirm all blockers have explicit accepted answers before implementation."
  ]
}
```

**candidate-questions.jsonl**
```jsonl
{"id":"import_export_format","question":"What file format and schema should import/export use?","why":"Implementation needs a stable parsing contract."}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_sequence37_needs_detail_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['task_status'] == 'ready_for_orchestration'
    task_id = str(payload['task_id'])
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    artifacts = shown['task']['artifacts']
    assert set(artifacts) == {'execution_contract', 'task_packet'}
    task_packet = (project_root / artifacts['task_packet']['path']).read_text(encoding='utf-8')
    assert 'Route: needs_detail' in task_packet
    assert shown['task']['next_owner'] == 'orchestrator'


def test_loop_runner_resolves_large_reply_artifact_for_planner_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    artifact_text = """**task-packet.md**
```markdown
# Task: Clarify local task manager import/export behavior
Route: needs_detail
Allowed paths:

Blockers:
- Import/export file format is unspecified.

Verification:
- Manual requirements review confirms all import/export blockers are answered.
```

**readiness.json**
```json
{
  "readiness": "needs_clarification",
  "route": "needs_detail",
  "blockers": ["Import/export file format is unspecified."],
  "allowed_paths": [],
  "verification": ["Manual requirements review confirms all import/export blockers are answered."]
}
```
"""
    artifact_path = (
        project_root
        / '.ccb'
        / 'ccbd'
        / 'artifacts'
        / 'text'
        / 'completion-reply'
        / 'job_large_planner-art_reply.txt'
    )
    _write(artifact_path, artifact_text)
    digest = hashlib.sha256(artifact_text.encode('utf-8')).hexdigest()
    preview_only = """CCB completion reply for job job_large_planner is larger than 4 KiB and was stored as an artifact.
Full text: {artifact_path}
Bytes: {bytes_count}
SHA256: {digest}

Preview:
**task-packet.md**
```markdown
# Task: Clarify local task manager import/export behavior
Route: needs_detail
Allowed paths:

Blockers:
- Import/export file format is unspecified.
""".format(artifact_path=artifact_path, bytes_count=len(artifact_text.encode('utf-8')), digest=digest)
    _write_completion_snapshot(
        project_root,
        job_id='job_large_planner',
        agent_name='planner',
        reply=preview_only,
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_large_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_planner_task_authority'
    assert payload['task_status'] == 'ready_for_orchestration'


def test_loop_runner_blocks_large_reply_artifact_sha_mismatch_without_mutating_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    artifact_path = (
        project_root
        / '.ccb'
        / 'ccbd'
        / 'artifacts'
        / 'text'
        / 'completion-reply'
        / 'job_bad_large_planner-art_reply.txt'
    )
    _write(artifact_path, '**task-packet.md**\n```markdown\n# Task: Tampered\n```\n')
    _write_completion_snapshot(
        project_root,
        job_id='job_bad_large_planner',
        agent_name='planner',
        reply=f"""CCB completion reply for job job_bad_large_planner is larger than 4 KiB and was stored as an artifact.
Full text: {artifact_path}
Bytes: 52
SHA256: {'0' * 64}

Preview:
**task-packet.md**
```markdown
# Task: Tampered
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_bad_large_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'completion_reply_artifact_sha256_mismatch'
    assert payload['evidence']['artifact_path'] == str(artifact_path)
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_blocks_direct_execution_planner_reply_when_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _write_completion_snapshot(
        project_root,
        job_id='job_not_ready_direct_planner',
        agent_name='planner',
        reply="""**task-packet.md**
```markdown
# Task: Unsafe direct execution
Route: direct_execution
```

**readiness.json**
```json
{
  "readiness": "needs_clarification",
  "route": "direct_execution",
  "blockers": ["Scope is underspecified."],
  "allowed_paths": ["lab.py"],
  "verification": ["python -m pytest"]
}
```
""",
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        plan_slug='demo-plan',
        role_job_id='job_not_ready_direct_planner',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'planner_readiness_not_ready'
    assert payload['evidence']['readiness'] == 'needs_clarification'
    assert payload['evidence']['route'] == 'direct_execution'
    assert not (project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan').exists()


def test_loop_runner_role_output_import_blocks_unknown_orchestrator_route_without_artifact_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_ready_plan_task(project_root, task_id='task-route')
    _write_completion_snapshot(
        project_root,
        job_id='job_bad_orchestrator',
        agent_name='orchestrator',
        reply='route: mystery\n\norchestration_notes: unsupported route.\n',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id='task-route',
        role_job_id='job_bad_orchestrator',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'unknown_route'
    assert payload['evidence']['route'] == 'mystery'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id='task-route'))
    assert set(shown['task']['artifacts']) == {'task_packet', 'execution_contract'}


def test_loop_runner_v3_orchestrator_missing_bundle_blocks_without_semantic_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-v3-bundle-required'
    _add_ready_plan_task(project_root, task_id=task_id)
    _write_completion_snapshot(
        project_root,
        job_id='job_v3_missing_bundle',
        agent_name='orchestrator',
        reply='route: direct_execution\n\norchestration_notes: implement the bounded task.\n',
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_v3_missing_bundle',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'orchestrator_bundle_candidate_required'
    assert payload['evidence']['config_version'] == 3
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['task_revision'] == 1
    assert set(shown['task']['artifacts']) == {'task_packet', 'execution_contract'}


def test_loop_runner_root14_schema_as_fence_blocks_without_authority_mutation_then_json_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-root14-schema-fence'
    _add_ready_plan_task(project_root, task_id=task_id)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_root14_schema_fence',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    before = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))['task']
    index_path = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'index.json'
    before_index = index_path.read_bytes()
    candidate = build_single_node_candidate(before, project_root=project_root)
    schema_fence = 'ccb.loop.orchestration_bundle_candidate.v1'
    schema_fence_reply = (
        'route: direct_execution\n\n'
        'orchestration_notes: the bounded root14 task is ready for direct execution.\n\n'
        'orchestration_bundle:\n'
        f'```{schema_fence}\n'
        f'{json.dumps(candidate, ensure_ascii=False, indent=2)}\n'
        '```\n'
    )
    literal_json_reply = schema_fence_reply.replace(f'```{schema_fence}', '```json', 1)
    assert literal_json_reply.replace('```json', f'```{schema_fence}', 1) == schema_fence_reply
    _write_completion_snapshot(
        project_root,
        job_id='job_root14_schema_fence',
        agent_name='orchestrator',
        reply=schema_fence_reply,
    )

    def forbidden_submit_ask(*_args, **_kwargs):
        raise AssertionError('blocked orchestrator import must not submit a Worker or other provider job')

    def forbidden_plan_task(*_args, **_kwargs):
        raise AssertionError('schema-as-fence reply must be rejected before task authority mutation')

    blocked_services = SimpleNamespace(
        submit_ask=forbidden_submit_ask,
        plan_task=forbidden_plan_task,
        effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
    )
    first = loop_runner_once(context, command, services=blocked_services)

    assert first['loop_runner_status'] == 'blocked'
    assert first['action'] == 'role_output_import_blocked'
    assert first['reason'] == 'orchestrator_reply_bundle_requires_fenced_json'
    after_first = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))['task']
    assert {
        key: after_first[key]
        for key in ('status', 'task_revision', 'state_version', 'artifacts')
    } == {
        key: before[key]
        for key in ('status', 'task_revision', 'state_version', 'artifacts')
    }
    assert index_path.read_bytes() == before_index
    assert not (project_root / '.ccb' / 'runtime' / 'loops').exists()
    assert not (project_root / '.ccb' / 'runtime' / 'role-output-imports' / 'job_root14_schema_fence').exists()

    restarted_context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    replay = loop_runner_once(restarted_context, command, services=blocked_services)

    assert replay['loop_runner_status'] == 'blocked'
    assert replay['action'] == 'role_output_import_blocked'
    assert replay['reason'] == 'orchestrator_reply_bundle_requires_fenced_json'
    after_replay = plan_task(restarted_context, SimpleNamespace(action='task-show', task_id=task_id))['task']
    assert {
        key: after_replay[key]
        for key in ('status', 'task_revision', 'state_version', 'artifacts')
    } == {
        key: before[key]
        for key in ('status', 'task_revision', 'state_version', 'artifacts')
    }
    assert index_path.read_bytes() == before_index
    import_records = [
        json.loads(line)
        for line in (project_root / '.ccb' / 'runtime' / 'role-output-imports.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert [
        (record['action'], record['status'], record['reason'], record['job_id'])
        for record in import_records
    ] == [
        (
            'role_output_import_blocked',
            'blocked',
            'orchestrator_reply_bundle_requires_fenced_json',
            'job_root14_schema_fence',
        ),
        (
            'role_output_import_blocked',
            'blocked',
            'orchestrator_reply_bundle_requires_fenced_json',
            'job_root14_schema_fence',
        ),
    ]

    _write_completion_snapshot(
        project_root,
        job_id='job_root14_literal_json',
        agent_name='orchestrator',
        reply=literal_json_reply,
    )
    literal_command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_root14_literal_json',
        consume_role_output=True,
        json_output=True,
    )
    imported = loop_runner_once(
        restarted_context,
        literal_command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert imported['loop_runner_status'] == 'ok'
    assert imported['action'] == 'imported_orchestration_notes'
    assert imported['route'] == 'direct_execution'
    assert imported['next_activation'] == 'ask_first_execution'
    assert imported['orchestration_bundle']['bundle_source'] == 'loop_runner_role_output_import'
    assert imported['orchestration_bundle']['node_count'] == 1
    shown = plan_task(restarted_context, SimpleNamespace(action='task-show', task_id=task_id))['task']
    assert shown['status'] == 'ready_for_orchestration'
    assert set(shown['artifacts']) == {
        'task_packet',
        'execution_contract',
        'orchestration_notes',
        'orchestration_bundle',
    }


def test_loop_runner_rejects_stale_managed_orchestrator_activation_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-stale-orchestrator'
    _add_ready_plan_task(project_root, task_id=task_id)
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_stale_orchestrator',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-stale-orchestrator.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_orchestrator_activation',
            'activation_id': 'act-stale-orchestrator',
            'action': 'activate_orchestrator',
            'task_id': task_id,
            'task_revision': 1,
            'ask': {
                'target': 'orchestrator',
                'job_id': 'job_stale_orchestrator',
                'status': 'accepted',
            },
        },
    )
    replacement = project_root / 'drafts' / 'stale-task-packet.md'
    _write(replacement, 'replacement task packet after activation\n')
    changed = plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id=task_id,
            artifact_kind='task_packet',
            file_path=str(replacement),
        ),
    )
    assert changed['task']['task_revision'] == 2
    _write_completion_snapshot(
        project_root,
        job_id='job_stale_orchestrator',
        agent_name='orchestrator',
        reply='route: direct_execution\n\norchestration_notes: stale output must not import.\n',
    )

    payload = loop_runner_once(context, command, services=SimpleNamespace(plan_task=plan_task))

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'stale_managed_activation_task_revision'
    assert payload['evidence'] == {
        'task_id': task_id,
        'expected_task_revision': 1,
        'current_task_revision': 2,
    }
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert shown['task']['task_revision'] == 2
    assert 'orchestration_notes' not in shown['task']['artifacts']
    assert 'orchestration_bundle' not in shown['task']['artifacts']


def test_loop_runner_rejects_invalid_v3_orchestrator_bundle_before_notes_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-invalid-bundle'
    _add_ready_plan_task(
        project_root,
        task_id=task_id,
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths:\n'
            '- src/core/\n'
            '- src/cli/\n'
        ),
    )
    task_root = f'docs/plantree/plans/demo-plan/tasks/{task_id}'
    contract_ref = f'{task_root}/execution_contract.md'
    candidate = _v3_two_node_candidate(task_id, contract_ref)
    candidate['nodes'][0].pop('worker_profile')
    candidate['nodes'][0].pop('reviewer_profile')
    candidate['nodes'][0]['coder'] = {'profile': 'coder'}
    candidate['nodes'][0]['code_reviewer'] = {'profile': 'code_reviewer'}
    _write_completion_snapshot(
        project_root,
        job_id='job_invalid_nested_bundle',
        agent_name='orchestrator',
        reply=(
            'route: direct_execution\n\n'
            'orchestration_notes: invalid nested role profile objects must not partially import.\n\n'
            'orchestration_bundle:\n'
            '```json\n'
            f'{json.dumps(candidate, ensure_ascii=False, indent=2)}\n'
            '```\n'
        ),
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_invalid_nested_bundle',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'orchestrator_bundle_candidate_invalid'
    assert 'nodes[0] contains unknown fields: code_reviewer, coder' in payload['evidence']['error']
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert set(shown['task']['artifacts']) == {'task_packet', 'execution_contract'}


def test_loop_runner_rejects_structured_v3_work_packet_before_notes_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-structured-work-packet'
    _add_ready_plan_task(
        project_root,
        task_id=task_id,
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths:\n'
            '- src/core/\n'
            '- src/cli/\n'
        ),
    )
    task_root = f'docs/plantree/plans/demo-plan/tasks/{task_id}'
    contract_ref = f'{task_root}/execution_contract.md'
    candidate = _v3_two_node_candidate(task_id, contract_ref)
    candidate['nodes'][0]['work_packet'] = {'goal': 'nested objects are not a bundle v1 work packet'}
    _write_completion_snapshot(
        project_root,
        job_id='job_structured_work_packet',
        agent_name='orchestrator',
        reply=(
            'route: direct_execution\n\n'
            'orchestration_notes: invalid structured work packet must not partially import.\n\n'
            'orchestration_bundle:\n'
            '```json\n'
            f'{json.dumps(candidate, ensure_ascii=False, indent=2)}\n'
            '```\n'
        ),
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_structured_work_packet',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert payload['loop_runner_status'] == 'blocked'
    assert payload['action'] == 'role_output_import_blocked'
    assert payload['reason'] == 'orchestrator_bundle_candidate_invalid'
    assert payload['evidence']['error'] == 'nodes[0].work_packet must be a string'
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert set(shown['task']['artifacts']) == {'task_packet', 'execution_contract'}


def test_loop_runner_auto_consumes_v3_orchestrator_activation_with_partial_notes_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-half-import'
    _add_ready_plan_task(
        project_root,
        task_id=task_id,
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths:\n'
            '- src/core/\n'
            '- src/cli/\n'
        ),
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, timeout_s=11.0, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    notes_path = project_root / 'drafts' / 'half-import-orchestration-notes.md'
    _write(notes_path, 'route: direct_execution\norchestration_notes: previous crash left only notes.\n')
    notes_import = plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id=task_id,
            artifact_kind='orchestration_notes',
            file_path=str(notes_path),
            route='direct_execution',
            actor_source='loop_runner_role_output_import',
            actor='loop_runner',
            job_id='job_half_import_orchestrator',
            expected_task_revision=1,
        ),
    )
    assert set(notes_import['task']['artifacts']) == {
        'task_packet',
        'execution_contract',
        'orchestration_notes',
    }
    task_root = f'docs/plantree/plans/demo-plan/tasks/{task_id}'
    contract_ref = f'{task_root}/execution_contract.md'
    candidate = _v3_two_node_candidate(task_id, contract_ref)
    _write_json(
        project_root / '.ccb' / 'runtime' / 'loops' / 'activations' / 'act-half-import.json',
        {
            'schema_version': 1,
            'record_type': 'ccb_loop_orchestrator_activation',
            'activation_id': 'act-half-import',
            'action': 'activate_orchestrator',
            'task_id': task_id,
            'task_revision': 1,
            'reason_for_activation': 'ready_for_orchestration',
            'ask': {
                'target': 'orchestrator',
                'job_id': 'job_half_import_orchestrator',
                'status': 'accepted',
            },
        },
    )
    _write_completion_snapshot(
        project_root,
        job_id='job_half_import_orchestrator',
        agent_name='orchestrator',
        reply=(
            'route: direct_execution\n\n'
            'orchestration_notes: retry should complete the missing bundle import.\n\n'
            'orchestration_bundle:\n'
            '```json\n'
            f'{json.dumps(candidate, ensure_ascii=False, indent=2)}\n'
            '```\n'
        ),
    )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_orchestration_notes'
    assert payload['route'] == 'direct_execution'
    assert payload['orchestration_bundle']['bundle_source'] == 'loop_runner_role_output_import'
    assert payload['orchestration_bundle']['node_count'] == 2
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert set(shown['task']['artifacts']) == {
        'task_packet',
        'execution_contract',
        'orchestration_notes',
        'orchestration_bundle',
    }


def test_loop_runner_role_output_imports_explicit_multi_workgroup_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    task_id = 'task-explicit-bundle'
    _add_ready_plan_task(
        project_root,
        task_id=task_id,
        execution_contract_text=(
            'execution contract text\n'
            'allowed_change_paths:\n'
            '- src/core/\n'
            '- src/cli/\n'
        ),
    )
    task_root = f'docs/plantree/plans/demo-plan/tasks/{task_id}'
    contract_ref = f'{task_root}/execution_contract.md'
    candidate = {
        'schema': 'ccb.loop.orchestration_bundle_candidate.v1',
        'task_id': task_id,
        'bundle_revision': 1,
        'selection': {
            'workgroup_count': 2,
            'complexity': 'bounded',
            'cutability': 'high',
            'execution_shape': 'parallel',
            'rationale': 'Core and CLI scopes are independently reviewable.',
        },
        'nodes': [
            {
                'node_id': 'node-001',
                'workgroup_id': 'wg-core',
                'worker_profile': 'coder',
                'reviewer_profile': 'code_reviewer',
                'depends_on': [],
                'parallel_group': 'wave-1',
                'work_packet': 'Implement the core slice.',
                'allowed_paths': ['src/core/'],
                'acceptance_refs': [contract_ref],
                'verification_refs': [contract_ref],
                'integration_order': 10,
            },
            {
                'node_id': 'node-002',
                'workgroup_id': 'wg-cli',
                'worker_profile': 'coder',
                'reviewer_profile': 'code_reviewer',
                'depends_on': [],
                'parallel_group': 'wave-1',
                'work_packet': 'Implement the CLI slice.',
                'allowed_paths': ['src/cli/'],
                'acceptance_refs': [contract_ref],
                'verification_refs': [contract_ref],
                'integration_order': 20,
            },
        ],
        'integration': {
            'verification_refs': [contract_ref],
            'project_root_verification_refs': [contract_ref],
        },
        'policy': {
            'max_node_rework_rounds': 1,
            'on_required_node_failure': 'partial_or_blocked',
            'on_structural_failure': 'replan_required',
        },
    }
    _write_completion_snapshot(
        project_root,
        job_id='job_explicit_bundle',
        agent_name='orchestrator',
        reply=(
            'route: direct_execution\n\n'
            'orchestration_notes: two independent bounded workgroups.\n\n'
            'orchestration_bundle:\n'
            '```json\n'
            f'{json.dumps(candidate, ensure_ascii=False, indent=2)}\n'
            '```\n'
        ),
    )
    command = ParsedLoopRunnerCommand(
        project=None,
        once=True,
        task_id=task_id,
        role_job_id='job_explicit_bundle',
        consume_role_output=True,
        json_output=True,
    )
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(
            plan_task=plan_task,
            effective_capacity_snapshot=lambda _context: _multi_workgroup_capacity_snapshot(),
        ),
    )

    assert payload['loop_runner_status'] == 'ok'
    assert payload['action'] == 'imported_orchestration_notes'
    assert payload['route'] == 'direct_execution'
    assert payload['orchestration_bundle']['bundle_source'] == 'loop_runner_role_output_import'
    assert payload['orchestration_bundle']['node_count'] == 2
    assert payload['orchestration_bundle']['node_ids'] == ['node-001', 'node-002']
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    assert set(shown['task']['artifacts']) == {
        'task_packet',
        'execution_contract',
        'orchestration_notes',
        'orchestration_bundle',
    }


def test_loop_runner_once_activates_planner_with_round_evidence_for_partial_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    round_path = project_root / 'docs' / 'plantree' / 'plans' / 'demo-plan' / 'tasks' / 'task-partial' / 'round-partial.md'
    _write(round_path, 'round result: partial\n')
    _add_plan_task_record(
        project_root,
        task_id='task-partial',
        status='partial',
        artifacts={
            'round_partial': {
                'kind': 'round_partial',
                'path': str(round_path.relative_to(project_root)),
                'source_path': str(round_path.relative_to(project_root)),
                'sha256': 'test',
                'bytes': 22,
                'imported_at': '2026-06-27T00:00:00Z',
                'loop_id': 'loop-prev',
                'round_result': 'partial',
            }
        },
    )
    command = ParsedLoopRunnerCommand(project=None, once=True, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def fake_submit_ask(_context, _ask_command):
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=None,
            jobs=({'job_id': 'job_planner_partial', 'agent_name': 'planner', 'status': 'submitted'},),
        )

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=fake_submit_ask),
    )

    assert payload['action'] == 'activated_planner'
    assert payload['reason'] == 'partial_task'
    activation = json.loads(Path(str(payload['activation_path'])).read_text(encoding='utf-8'))
    assert activation['round_evidence_refs'] == [
        {
            'kind': 'round_partial',
            'path': str(round_path.relative_to(project_root)),
            'round_result': 'partial',
            'loop_id': 'loop-prev',
        }
    ]


@pytest.mark.parametrize(
    ('status', 'expected_action', 'expected_runner_status', 'expected_owner'),
    (
        ('needs_clarification', 'paused', 'paused', 'task_detailer'),
        ('blocked', 'blocked', 'blocked', 'terminal'),
        ('done', 'terminal', 'terminal', 'terminal'),
    ),
)
def test_loop_runner_once_stops_without_provider_activation_for_paused_or_terminal_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected_action: str,
    expected_runner_status: str,
    expected_owner: str,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    _add_plan_task_record(project_root, task_id=f'task-{status}', status=status)
    command = ParsedLoopRunnerCommand(project=None, once=True, json_output=True)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)

    def forbidden_submit(*_args, **_kwargs):
        raise AssertionError('paused or terminal tasks must not submit asks')

    payload = loop_runner_once(
        context,
        command,
        services=SimpleNamespace(submit_ask=forbidden_submit),
    )

    assert payload['loop_runner_status'] == expected_runner_status
    assert payload['action'] == expected_action
    assert payload['task_id'] == f'task-{status}'
    assert payload['next_owner'] == expected_owner


def test_loop_run_once_records_failure_and_releases_after_watch_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    command = ParsedLoopRunOnceCommand(project=None, loop_id='round1', task='ship the slice', timeout_s=7.0)
    context = CliContextBuilder().build(command, cwd=project_root, bootstrap_if_missing=False)
    calls: list[tuple[str, object]] = []

    def fake_loop_capacity(_context, capacity_command):
        calls.append(('capacity', capacity_command.action))
        if capacity_command.action == 'ensure':
            return {
                'loop_capacity_status': 'ensured',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'agents': [
                    {'name': 'loop-round1-worker-1', 'profile': 'worker', 'state': 'planned'},
                    {'name': 'loop-round1-code_reviewer-1', 'profile': 'code_reviewer', 'state': 'planned'},
                ],
                'apply': {'apply_status': 'applied', 'action': 'add_agent'},
            }
        if capacity_command.action == 'release':
            return {
                'loop_capacity_status': 'released',
                'loop_id': capacity_command.loop_id,
                'project_id': context.project.project_id,
                'agent_count': 2,
                'released_count': 2,
                'retained_count': 0,
                'release_policy': 'auto',
                'idle_only': True,
                'agents': [
                    {'name': 'loop-round1-worker-1', 'profile': 'worker', 'state': 'released'},
                    {'name': 'loop-round1-code_reviewer-1', 'profile': 'code_reviewer', 'state': 'released'},
                ],
                'apply': {'apply_status': 'applied', 'action': 'remove_agent'},
            }
        raise AssertionError(f'unexpected capacity action {capacity_command.action}')

    def fake_submit_ask(_context, ask_command):
        calls.append(('ask', ask_command.target))
        return AskSummary(
            project_id=context.project.project_id,
            submission_id=f'sub_{ask_command.target}',
            jobs=(
                {
                    'job_id': f'job_{ask_command.target}',
                    'agent_name': ask_command.target,
                    'status': 'accepted',
                },
            ),
        )

    def fake_watch_ask_job(_context, job_id, _out, *, timeout, emit_output):
        calls.append(('watch', job_id))
        raise RuntimeError('watch transport failed')

    payload = loop_run_once(
        context,
        command,
        services=SimpleNamespace(
            loop_capacity=fake_loop_capacity,
            submit_ask=fake_submit_ask,
            watch_ask_job=fake_watch_ask_job,
        ),
    )

    assert payload['loop_run_status'] == 'failed'
    assert payload['failure'] == {
        'stage': 'execution',
        'error_type': 'RuntimeError',
        'error': 'watch transport failed',
    }
    assert payload['capacity']['release']['loop_capacity_status'] == 'released'
    assert payload['capacity']['release']['release_policy'] == 'auto'
    assert payload['capacity']['release']['idle_only'] is True
    assert calls == [
        ('capacity', 'ensure'),
        ('ask', 'loop-round1-worker-1'),
        ('watch', 'job_loop-round1-worker-1'),
        ('capacity', 'release'),
    ]

    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / 'round1'
    round_payload = json.loads((loop_dir / 'round.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (loop_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    breadcrumb = (loop_dir / 'breadcrumb.md').read_text(encoding='utf-8')
    assert round_payload['loop_run_status'] == 'failed'
    assert round_payload['failure']['error'] == 'watch transport failed'
    assert [event['kind'] for event in events] == [
        'loop_run_started',
        'loop_run_failed',
        'loop_run_finished',
    ]
    assert 'Phase: blocked\n' in breadcrumb
    assert 'Blocked: failed\n' in breadcrumb


def test_loop_run_once_json_handler_returns_nonzero_for_incomplete_round() -> None:
    out = StringIO()
    command = ParsedLoopRunOnceCommand(project=None, loop_id='round1', task='ship', json_output=True)

    exit_code = handle_loop_run_once(
        SimpleNamespace(),
        command,
        out,
        SimpleNamespace(
            loop_run_once=lambda _context, _command, _services: {'loop_run_status': 'incomplete'},
            render_loop_run_once=lambda _payload: (),
            write_lines=lambda _out, _lines: None,
        ),
    )

    assert exit_code == 1
    assert json.loads(out.getvalue()) == {'loop_run_status': 'incomplete'}


def test_loop_run_once_does_not_bootstrap_missing_project(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = maybe_handle_phase2(
        ['loop', 'run-once', '--loop-id', 'round1', '--task', 'ship', '--json'],
        cwd=tmp_path,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ''
    assert not (tmp_path / '.ccb').exists()
    assert 'command_status: failed' in stderr.getvalue()


def test_loop_capacity_ensure_status_release_json_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)

    result, ensured, err = _run_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'worker=1',
            '--profile',
            'code_reviewer=1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert ensured['loop_capacity_status'] == 'ensured'
    assert ensured['loop_id'] == 'round1'
    assert ensured['agent_count'] == 2
    assert [agent['name'] for agent in ensured['agents']] == [
        'loop-round1-worker-1',
        'loop-round1-code_reviewer-1',
    ]
    assert ensured['agents'][0]['role'] == 'agentroles.coder'
    assert ensured['agents'][0]['workspace_group'] == 'worker_pool'
    assert ensured['apply']['apply_status'] == 'deferred_until_start'
    assert Path(str(ensured['state_path'])).is_file()

    validate_out = StringIO()
    validate_err = StringIO()
    validate_result = maybe_handle_phase2(
        ['config', 'validate'],
        cwd=project_root,
        stdout=validate_out,
        stderr=validate_err,
    )
    assert validate_result == 0
    assert validate_err.getvalue() == ''
    assert 'agents: loop-round1-code_reviewer-1, loop-round1-worker-1, orchestrator' in validate_out.getvalue()

    result, status, err = _run_phase2(
        ['loop', 'capacity', 'status', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert status['loop_capacity_status'] == 'ensured'
    assert status['agent_count'] == 2
    assert [agent['state'] for agent in status['agents']] == ['planned', 'planned']

    result, released, err = _run_phase2(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--idle-only', '--json'],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert released['loop_capacity_status'] == 'released'
    assert released['release_policy'] == 'idle-only'
    assert released['idle_only'] is True
    assert released['released_count'] == 2
    assert released['apply']['apply_status'] == 'deferred_until_start'
    assert [agent['state'] for agent in released['agents']] == ['released', 'released']

    result, rerelease, err = _run_phase2(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--policy', 'auto', '--json'],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert rerelease['loop_capacity_status'] == 'released'
    assert rerelease['release_policy'] == 'auto'
    assert rerelease['idle_only'] is True
    assert rerelease['released_count'] == 2

    state = json.loads(Path(str(released['state_path'])).read_text(encoding='utf-8'))
    events = [
        json.loads(line)
        for line in Path(str(released['events_path'])).read_text(encoding='utf-8').splitlines()
    ]
    assert state['loop_capacity_status'] == 'released'
    assert [event['event'] for event in events] == ['ensure', 'release', 'release']

    validate_out = StringIO()
    validate_err = StringIO()
    validate_result = maybe_handle_phase2(
        ['config', 'validate'],
        cwd=project_root,
        stdout=validate_out,
        stderr=validate_err,
    )
    assert validate_result == 0
    assert validate_err.getvalue() == ''
    assert 'agents: orchestrator' in validate_out.getvalue()
    assert 'loop-round1-worker-1' not in validate_out.getvalue()


def test_loop_capacity_ensure_while_mounted_reports_pane_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    worker = 'loop-round1-worker-1'
    reviewer = 'loop-round1-code_reviewer-1'
    monkeypatch.setattr(
        loop_capacity_module,
        'ping_local_state',
        lambda _context: SimpleNamespace(mount_state='mounted', socket_connectable=True, reason=None),
    )
    monkeypatch.setattr(
        loop_capacity_module,
        'reload_config',
        lambda _context, _command: {
            'status': 'published',
            'stage': 'publish_transaction',
            'plan_class': 'add_window',
            'published_graph_version': 7,
            'namespace_patch': {
                'status': 'applied',
                'agent_panes': {worker: '%2', reviewer: '%3'},
                'preserved_before': {'orchestrator': '%1'},
                'preserved_after': {'orchestrator': '%1'},
            },
            'runtime_mount': {
                'status': 'mounted',
                'mounted_agents': [worker, reviewer],
                'runtime_authority_written_agents': [worker, reviewer],
            },
        },
    )

    result, ensured, err = _run_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'worker=1',
            '--profile',
            'code_reviewer=1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert ensured['apply']['apply_status'] == 'applied'
    assert ensured['apply']['plan_class'] == 'add_window'
    assert ensured['apply']['namespace_agent_panes'] == {worker: '%2', reviewer: '%3'}
    assert ensured['apply']['namespace_preserved_before'] == {'orchestrator': '%1'}
    assert ensured['apply']['namespace_preserved_after'] == {'orchestrator': '%1'}
    assert ensured['apply']['runtime_mount_status'] == 'mounted'
    assert ensured['apply']['pane_identity_report']['added_agents'] == [
        {'agent': reviewer, 'pane_id': '%3', 'pane_identity_source': 'namespace_agent_panes'},
        {'agent': worker, 'pane_id': '%2', 'pane_identity_source': 'namespace_agent_panes'},
    ]
    assert ensured['apply']['pane_identity_report']['preserved_agents'] == [
        {
            'agent': 'orchestrator',
            'before_pane_id': '%1',
            'after_pane_id': '%1',
            'pane_identity_source': 'namespace_preserved_before_after',
            'changed': False,
        }
    ]
    assert ensured['apply']['pane_identity_report']['mounted_agents'] == [worker, reviewer]


def test_loop_capacity_ensure_rejects_unknown_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)

    stdout = StringIO()
    stderr = StringIO()
    result = maybe_handle_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'unknown=1',
            '--json',
        ],
        cwd=project_root,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ''
    assert 'command_status: failed' in stderr.getvalue()
    assert "unknown loop role profile 'unknown'" in stderr.getvalue()


def test_loop_capacity_release_retains_busy_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_loop_capacity(tmp_path, monkeypatch)
    result, ensured, err = _run_phase2(
        [
            'loop',
            'capacity',
            'ensure',
            '--loop-id',
            'round1',
            '--profile',
            'worker=1',
            '--profile',
            'code_reviewer=1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0
    assert err == ''
    assert ensured['agent_count'] == 2

    class FakeRuntimeStore:
        def __init__(self, _paths):
            pass

        def load_best_effort(self, agent_name):
            if agent_name == 'loop-round1-worker-1':
                return SimpleNamespace(state=SimpleNamespace(value='busy'), queue_depth=0)
            return SimpleNamespace(state=SimpleNamespace(value='idle'), queue_depth=0)

    monkeypatch.setattr(loop_capacity_module, 'AgentRuntimeStore', FakeRuntimeStore)
    monkeypatch.setattr(
        loop_capacity_module,
        'ping_local_state',
        lambda _context: SimpleNamespace(mount_state='mounted', socket_connectable=True, reason=None),
    )
    monkeypatch.setattr(
        loop_capacity_module,
        '_apply_reload_if_mounted',
        lambda _context, *, action: {'apply_status': 'applied', 'action': action, 'reload_status': 'noop'},
    )

    result, released, err = _run_phase2(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--policy', 'auto', '--json'],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert released['loop_capacity_status'] == 'ensured'
    assert released['release_policy'] == 'auto'
    assert released['idle_only'] is True
    assert released['released_count'] == 1
    assert released['retained_count'] == 1
    assert released['retained'] == [
        {
            'name': 'loop-round1-worker-1',
            'queue_depth': 0,
            'reason': 'runtime_state=busy',
            'runtime_state': 'busy',
        }
    ]
    states = {agent['name']: agent['state'] for agent in released['agents']}
    assert states == {
        'loop-round1-worker-1': 'retained',
        'loop-round1-code_reviewer-1': 'released',
    }

    validate_out = StringIO()
    validate_err = StringIO()
    validate_result = maybe_handle_phase2(
        ['config', 'validate'],
        cwd=project_root,
        stdout=validate_out,
        stderr=validate_err,
    )
    assert validate_result == 0
    assert validate_err.getvalue() == ''
    assert 'loop-round1-worker-1' in validate_out.getvalue()
    assert 'loop-round1-code_reviewer-1' not in validate_out.getvalue()

    class IdleRuntimeStore:
        def __init__(self, _paths):
            pass

        def load_best_effort(self, _agent_name):
            return SimpleNamespace(state=SimpleNamespace(value='idle'), queue_depth=0)

    monkeypatch.setattr(loop_capacity_module, 'AgentRuntimeStore', IdleRuntimeStore)
    result, final_release, err = _run_phase2(
        ['loop', 'capacity', 'release', '--loop-id', 'round1', '--policy', 'auto', '--json'],
        cwd=project_root,
    )

    assert result == 0
    assert err == ''
    assert final_release['loop_capacity_status'] == 'released'
    assert final_release['release_policy'] == 'auto'
    assert final_release['retained_count'] == 0
    final_worker = next(agent for agent in final_release['agents'] if agent['name'] == 'loop-round1-worker-1')
    assert final_worker['state'] == 'released'
    assert 'retain_reason' not in final_worker
    assert 'runtime_state' not in final_worker
    assert 'queue_depth' not in final_worker
