from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ccbd.api_models import DeliveryScope, JobRecord, JobStatus, MessageEnvelope
from cli.services.loop_orchestration_bundle import normalize_bundle_candidate
from cli.services.loop_effective_capacity import effective_capacity_digest
from cli.services.loop_runner import _mount_activation_topology
from cli.services.loop_topology import _mark_release_residue
from cli.services.role_output_import import _parse_orchestrator_reply
from project.ids import compute_project_id
from provider_execution.fake import FakeProviderAdapter


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'single_lane_multi_workgroup_smoke.py'
REQUIRES_AGENT_ROLES_RUNTIME = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason='Agent Roles runtime requires Python 3.11+',
)


def _scenario_contract(
    *,
    count: int,
    shape: str,
    scenario: str = 'pass',
) -> dict[str, object]:
    return {
        'schema': 'ccb.g5.source_fake_runtime_scenario.v1',
        'task_id': 'g5-multi-workgroup-task',
        'scenario': scenario,
        'count': count,
        'shape': shape,
        'selected_node': 'node-001',
        'restart_latency_ms': 10000 if scenario == 'restart_replay_pass' else 0,
    }


def _load_script():
    spec = importlib.util.spec_from_file_location('single_lane_multi_workgroup_smoke', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_smoke_installs_rolepacks_from_explicit_checkout_paths() -> None:
    module = _load_script()
    ccb_test = Path('/source/ccb_test')

    for role_id in module.ROLE_IDS:
        command = module._role_install_command(ccb_test, role_id)
        source_path = module.ROLE_SOURCE_ROOT / role_id
        assert command == [
            str(ccb_test),
            'roles',
            'install',
            role_id,
            '--path',
            str(source_path),
            '--skip-tools',
        ]
        assert (source_path / 'role.toml').is_file()


def _job(
    *,
    agent_name: str,
    body: str,
    workspace: Path | None = None,
    project_id: str = 'project-g5',
    body_artifact: dict[str, object] | None = None,
) -> JobRecord:
    request = MessageEnvelope(
        project_id=project_id,
        to_agent=agent_name,
        from_actor='system',
        body=body,
        task_id='g5-multi-workgroup-task',
        reply_to=None,
        message_type='ask',
        delivery_scope=DeliveryScope.SINGLE,
        body_artifact=body_artifact,
    )
    return JobRecord(
        job_id=f'job-{agent_name}',
        submission_id=None,
        agent_name=agent_name,
        provider='fake',
        request=request,
        status=JobStatus.QUEUED,
        terminal_decision=None,
        cancel_requested_at=None,
        created_at='2026-07-11T00:00:00Z',
        updated_at='2026-07-11T00:00:00Z',
        workspace_path=str(workspace) if workspace is not None else None,
    )


def _orchestrator_body(*, count: int, shape: str, task_root: str) -> str:
    marker = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=count, shape=shape),
        sort_keys=True,
    )
    refs = {
        'task_packet': f'{task_root}/task_packet.md',
        'execution_contract': f'{task_root}/execution_contract.md',
    }
    compact = {'task_packet': {'content': marker}, 'execution_contract': {'content': marker}}
    return (
        'Role: ccb_orchestrator\n'
        'Task: g5-multi-workgroup-task\n'
        f'Artifact refs: {refs}\n'
        f'Compact artifacts: {compact}\n'
        'Expected bundle revision: 1\n'
    )


def _record(project_root: Path, *, count: int, shape: str) -> dict[str, object]:
    task_root = project_root / 'docs/plantree/plans/g5/tasks/g5-multi-workgroup-task'
    paths = [f'g5_outputs/node-{index:03d}.txt' for index in range(1, count + 1)]
    marker = json.dumps(_scenario_contract(count=count, shape=shape), sort_keys=True)
    artifacts = {}
    for kind, text in (
        ('task_packet', f'g5_multi_workgroup_smoke: {marker}\n'),
        (
            'execution_contract',
            'allowed_change_paths:\n' + ''.join(f'- {path}\n' for path in paths),
        ),
    ):
        path = task_root / f'{kind}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        artifacts[kind] = {
            'path': path.relative_to(project_root).as_posix(),
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        }
    return {
        'task_id': 'g5-multi-workgroup-task',
        'task_revision': 1,
        'task_root': task_root.relative_to(project_root).as_posix(),
        'artifacts': artifacts,
    }


def _capacity() -> dict[str, object]:
    return {
        'schema': 'ccb.loop.effective_capacity_snapshot.v1',
        'config_version': 3,
        'workflow_profile': 'agentic_loop_v1',
        'workflow_mode': 'agentic-loop',
        'limits': {
            'max_workgroups': 4,
            'max_parallel_workgroups': 4,
            'max_active_dynamic_agents': 9,
        },
        'policies': {
            'node_rework': {'max_rounds': 1},
            'workspace': {'mode': 'git-worktree-required'},
            'integration': {'mode': 'controller-owned'},
            'release': {'default_lifetime': 'current_activation', 'policy': 'auto', 'idle_only': True},
            'naming': {'template': 'loop-{loop_id}-{node_id}-{profile}'},
            'execution_windows': {'policy': 'auto'},
        },
        'resident_profiles': {},
        'dynamic_profiles': {
            'orchestrator': {
                'role_id': 'agentroles.ccb_orchestrator',
                'provider': 'fake',
                'model': None,
                'workspace_mode': 'inplace',
                'release_policy': 'auto',
                'max_instances': 1,
            },
            'coder': {
                'role_id': 'agentroles.coder',
                'provider': 'fake',
                'model': None,
                'workspace_mode': 'git-worktree',
                'release_policy': 'auto',
                'max_instances': 4,
            },
            'code_reviewer': {
                'role_id': 'agentroles.code_reviewer',
                'provider': 'fake',
                'model': None,
                'workspace_mode': 'git-worktree',
                'release_policy': 'auto',
                'max_instances': 4,
            },
        },
        'profile_aliases': {'worker': 'coder'},
    }


@pytest.mark.parametrize(
    ('count', 'shape', 'expected_shape'),
    (
        (1, 'parallel', 'single_unit'),
        (2, 'parallel', 'parallel'),
        (3, 'mixed_dag', 'mixed_dag'),
        (4, 'mixed_dag', 'mixed_dag'),
    ),
)
def test_fake_orchestrator_candidate_normalizes_for_one_to_four_nodes(
    tmp_path: Path,
    count: int,
    shape: str,
    expected_shape: str,
) -> None:
    record = _record(tmp_path, count=count, shape=shape)
    task_root = str(record['task_root'])
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='orchestrator', body=_orchestrator_body(count=count, shape=shape, task_root=task_root)),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    parsed = _parse_orchestrator_reply(submission.reply)
    assert parsed['status'] == 'ok'
    candidate = parsed['orchestration_bundle_candidate']
    normalized, packets = normalize_bundle_candidate(
        candidate,
        record=record,
        project_root=tmp_path,
        capacity_snapshot=_capacity(),
    )

    assert normalized['selection']['workgroup_count'] == count
    assert normalized['selection']['execution_shape'] == expected_shape
    assert len(normalized['nodes']) == count
    assert len(packets) == count
    expected_dependencies = ['node-001'] if shape == 'mixed_dag' else []
    if count >= 3:
        assert normalized['nodes'][2]['depends_on'] == expected_dependencies
    assert [node['allowed_paths'] for node in normalized['nodes']] == [
        [f'g5_outputs/node-{index:03d}.txt'] for index in range(1, count + 1)
    ]


@pytest.mark.parametrize(
    'bundle',
    (
        '```\n{"schema": "ccb.loop.orchestration_bundle_candidate.v1"}\n```',
        '```text\n{"schema": "ccb.loop.orchestration_bundle_candidate.v1"}\n```',
        '```ccb.loop.orchestration_bundle_candidate.v1\n{}\n```',
        '```json\n{"schema": "ccb.loop.orchestration_bundle_candidate.v1"}\n```\n\norchestration_bundle:\n```json\n{"schema": "ccb.loop.orchestration_bundle_candidate.v1"}\n```',
    ),
)
def test_orchestrator_v3_rejects_nonliteral_or_ambiguous_bundle_fence(bundle: str) -> None:
    reply = f'''route: direct_execution
orchestration_notes: bounded task.
orchestration_bundle:
{bundle}
'''

    parsed = _parse_orchestrator_reply(reply)

    assert parsed == {
        'status': 'blocked',
        'reason': 'orchestrator_reply_bundle_requires_fenced_json',
    }


def test_orchestrator_v3_rejects_schema_outside_the_top_level_field() -> None:
    reply = '''route: direct_execution
orchestration_notes: bounded task.
orchestration_bundle:
```json
{"schema": "ccb.loop.orchestration_bundle_candidate.v1", "nested": {"schema": "wrong"}}
```
'''

    assert _parse_orchestrator_reply(reply) == {
        'status': 'blocked',
        'reason': 'orchestrator_reply_bundle_schema_not_top_level',
    }


def test_fake_scheduler_worker_writes_only_node_bound_allowed_path(tmp_path: Path) -> None:
    workspace = tmp_path / 'node-worktree'
    body = (
        'Loop: lp-g5\nTask: g5-multi-workgroup-task\nNode: node-002\nPurpose: worker\n'
        f'Worktree: {workspace}\n'
        'Allowed paths: ["g5_outputs/node-002.txt"]\n\n'
        'g5_multi_workgroup_smoke: '
        + json.dumps(_scenario_contract(count=2, shape='parallel'), sort_keys=True)
        + '\n'
        'allowed_change_paths:\n- g5_outputs/node-001.txt\n- g5_outputs/node-002.txt\n'
    )

    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='loop-lp-g5-node-002-coder', body=body, workspace=workspace),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert (workspace / 'g5_outputs/node-002.txt').is_file()
    assert not (workspace / 'g5_outputs/node-001.txt').exists()
    assert 'changed_files: g5_outputs/node-002.txt' in submission.reply
    assert submission.ready_at == '2026-07-11T00:00:08Z'


@pytest.mark.parametrize(
    'body',
    (
        'Role: ccb_orchestrator\nTask: ordinary-task\n',
        (
            'Role: ccb_orchestrator\nTask: g5-multi-workgroup-task\n'
            'g5_multi_workgroup_smoke: '
            '{"count": 5, "shape": "parallel", "allowed_paths": []}\n'
        ),
    ),
)
def test_fake_orchestrator_requires_valid_explicit_smoke_contract(body: str) -> None:
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='orchestrator', body=body),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert 'ccb.loop.orchestration_bundle_candidate.v1' not in submission.reply


def test_g5_contract_skips_malformed_compact_before_valid_later_contract() -> None:
    module = __import__('provider_execution.fake', fromlist=['_g5_smoke_contract'])
    valid = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=4, shape='parallel', scenario='all_workers_failed_blocked'),
        sort_keys=True,
    )
    compact = {
        'execution_contract': {'content': valid[:110]},
        'task_packet': {'content': valid},
    }

    contract = module._g5_smoke_contract(f'Compact artifacts: {compact}\n')

    assert contract is not None
    assert contract['count'] == 4
    assert contract['scenario'] == 'all_workers_failed_blocked'


def test_g5_contract_rejects_conflicting_valid_compact_contracts() -> None:
    module = __import__('provider_execution.fake', fromlist=['_g5_smoke_contract'])
    first = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=4, shape='parallel', scenario='all_workers_failed_blocked'),
        sort_keys=True,
    )
    second = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=4, shape='parallel', scenario='pass'),
        sort_keys=True,
    )
    compact = {
        'execution_contract': {'content': first},
        'task_packet': {'content': second},
    }

    with pytest.raises(ValueError, match='conflicting G5 smoke contracts'):
        module._g5_smoke_contract(f'Compact artifacts: {compact}\n')


def test_fake_orchestrator_spilled_ask_uses_same_project_durable_contract(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    artifact_dir = project / '.ccb/ccbd/artifacts/text/ask-request'
    artifact_dir.mkdir(parents=True)
    task_root = 'docs/plantree/plans/g5/tasks/g5-multi-workgroup-task'
    valid = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=4, shape='parallel', scenario='all_workers_failed_blocked'),
        sort_keys=True,
    )
    compact = {
        'execution_contract': {'content': valid[:110] + ('x' * 4300)},
        'task_packet': {'content': valid},
    }
    full_body = (
        'Role: ccb_orchestrator\n'
        'Task: g5-multi-workgroup-task\n'
        f"Artifact refs: {{'task_packet': '{task_root}/task_packet.md', "
        f"'execution_contract': '{task_root}/execution_contract.md'}}\n"
        f'Compact artifacts: {compact}\n'
        'Expected bundle revision: 1\n'
    )
    artifact_path = artifact_dir / 'system-to-orchestrator-art_spill.txt'
    artifact_path.write_text(full_body, encoding='utf-8')
    data = full_body.encode('utf-8')
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(
            agent_name='orchestrator',
            body='CCB ask request is larger than 4 KiB and was stored as an artifact.',
            project_id=compute_project_id(project),
            body_artifact={
                'kind': 'ask-request',
                'path': str(artifact_path),
                'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
            },
        ),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert len(data) > 4096
    assert submission.reply.startswith('route: direct_execution')
    parsed = _parse_orchestrator_reply(submission.reply)
    assert parsed['status'] == 'ok'
    assert parsed['route'] == 'direct_execution'
    assert parsed['orchestration_bundle_candidate']['selection']['workgroup_count'] == 4
    with pytest.raises(ValueError, match='outside the explicit project'):
        FakeProviderAdapter(latency_seconds=0).start(
            _job(
                agent_name='orchestrator',
                body='CCB ask request is larger than 4 KiB and was stored as an artifact.',
                project_id='different-project',
                body_artifact={
                    'kind': 'ask-request',
                    'path': str(artifact_path),
                    'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(),
                },
            ),
            context=None,
            now='2026-07-11T00:00:00Z',
        )


def test_fake_worker_continuation_recovers_contract_from_verified_project_artifact(
    tmp_path: Path,
) -> None:
    project = tmp_path / 'project'
    workspace = project / '.ccb/workspaces/workgroups/group/nodes/node-001'
    workspace.mkdir(parents=True)
    artifact_dir = project / '.ccb/ccbd/artifacts/text/result-chain-continuation'
    artifact_dir.mkdir(parents=True)
    full_body = (
        'CCB result-chain continuation.\n'
        'Task: g5-multi-workgroup-task\n'
        'Node: node-001\n'
        'Purpose: worker\n'
        f'Worktree: {workspace}\n'
        'Allowed paths: ["g5_outputs/node-001.txt"]\n'
        'g5_multi_workgroup_smoke: '
        + json.dumps(
            _scenario_contract(count=1, shape='parallel', scenario='reviewer_rework_pass'),
            sort_keys=True,
        )
        + '\n'
    )
    artifact_path = artifact_dir / 'cb_chain-art_verified.txt'
    artifact_path.write_text(full_body, encoding='utf-8')
    data = full_body.encode('utf-8')

    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(
            agent_name='loop-lp-g5-node-001-coder',
            body='CCB result-chain continuation was stored as an artifact.',
            workspace=workspace,
            project_id=compute_project_id(project),
            body_artifact={
                'kind': 'result-chain-continuation',
                'path': str(artifact_path),
                'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
            },
        ),
        context=SimpleNamespace(workspace_path=str(workspace)),
        now='2026-07-11T00:00:00Z',
    )

    assert submission.ready_at == '2026-07-11T00:00:08Z'
    assert 'status: done' in submission.reply


def test_fake_scenario_contract_requires_exact_versioned_shape() -> None:
    valid = 'g5_multi_workgroup_smoke: ' + json.dumps(
        _scenario_contract(count=2, shape='parallel'), sort_keys=True
    )
    extra = json.loads(valid.split(': ', 1)[1])
    extra['unexpected'] = True

    assert FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='orchestrator', body=_orchestrator_body(count=2, shape='parallel', task_root='task')),
        context=None,
        now='2026-07-11T00:00:00Z',
    ).reply.startswith('route: direct_execution')
    invalid = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='orchestrator', body='Role: ccb_orchestrator\n' + 'g5_multi_workgroup_smoke: ' + json.dumps(extra)),
        context=None,
        now='2026-07-11T00:00:00Z',
    )
    assert 'ccb.loop.orchestration_bundle_candidate.v1' not in invalid.reply


def test_g5_rework_and_provider_failure_are_strictly_scenario_gated(tmp_path: Path) -> None:
    reviewer_body = (
        'Task: g5-multi-workgroup-task\nNode: node-001\nPurpose: reviewer\n'
        'Role: code_reviewer\n'
        'g5_multi_workgroup_smoke: '
        + json.dumps(_scenario_contract(count=1, shape='parallel', scenario='reviewer_rework_pass'), sort_keys=True)
    )
    rework = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='loop-lp-node-001-code_reviewer', body=reviewer_body),
        context=None,
        now='2026-07-11T00:00:00Z',
    )
    assert rework.reply.startswith('status: rework_required')

    workspace = tmp_path / 'worker'
    failure_body = (
        'Task: g5-multi-workgroup-task\nNode: node-001\nPurpose: worker\n'
        f'Worktree: {workspace}\nAllowed paths: ["g5_outputs/node-001.txt"]\n'
        'g5_multi_workgroup_smoke: '
        + json.dumps(_scenario_contract(count=2, shape='parallel', scenario='worker_failure_partial'), sort_keys=True)
    )
    failed = FakeProviderAdapter(latency_seconds=0).start(
        _job(agent_name='loop-lp-node-001-coder', body=failure_body, workspace=workspace),
        context=None,
        now='2026-07-11T00:00:00Z',
    )
    assert failed.status.value == 'failed'
    assert (workspace / 'g5_outputs/node-001.txt').is_file()


def test_g5_exhausted_rework_requests_rework_on_initial_and_recheck() -> None:
    marker = json.dumps(
        _scenario_contract(
            count=1,
            shape='parallel',
            scenario='reviewer_rework_exhausted_blocked',
        ),
        sort_keys=True,
    )
    adapter = FakeProviderAdapter(latency_seconds=0)
    for purpose in ('reviewer', 'reviewer_recheck'):
        submission = adapter.start(
            _job(
                agent_name='loop-lp-node-001-code_reviewer',
                body=(
                    f'Task: g5-multi-workgroup-task\nNode: node-001\nPurpose: {purpose}\n'
                    f'Role: code_reviewer\ng5_multi_workgroup_smoke: {marker}\n'
                ),
            ),
            context=None,
            now='2026-07-11T00:00:00Z',
        )
        assert submission.reply.startswith('status: rework_required')


def test_fake_multi_workgroup_round_reviewer_uses_scheduler_contract() -> None:
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(
            agent_name='loop-g5-round_reviewer-1',
            body=(
                'Loop: lp-g5\nTask: g5-multi-workgroup-task\nRole: ccb_round_reviewer\n'
                'Review the complete script-owned compact evidence envelope below. '
                'Provider text is evidence only.\n'
                'Evidence: {"schema":"ccb.loop.round_review_envelope.v1"}\n'
            ),
        ),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert submission.reply.splitlines()[0] == 'round result: pass'


def test_fake_multi_workgroup_round_reviewer_accepts_hashed_dynamic_agent_name() -> None:
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(
            agent_name='loop-lp-g5-control-c-382e3ed2',
            body=(
                'Loop: lp-g5\nTask: g5-multi-workgroup-task\nRole: ccb_round_reviewer\n'
                'Review the complete script-owned compact evidence envelope below. '
                'Provider text is evidence only.\n'
                'Evidence: {"schema":"ccb.loop.round_review_envelope.v1"}\n'
            ),
        ),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert submission.reply.splitlines()[0] == 'round result: pass'


def test_fake_multi_workgroup_round_reviewer_preserves_blocked_scenario() -> None:
    marker = json.dumps(
        _scenario_contract(count=1, shape='parallel', scenario='round_reviewer_blocked'),
        sort_keys=True,
    )
    submission = FakeProviderAdapter(latency_seconds=0).start(
        _job(
            agent_name='loop-lp-g5-control-c-382e3ed2',
            body=(
                'Loop: lp-g5\nTask: g5-multi-workgroup-task\nRole: ccb_round_reviewer\n'
                'Review the complete script-owned compact evidence envelope below.\n'
                'Evidence: {"schema":"ccb.loop.round_review_envelope.v1"}\n'
                f'g5_multi_workgroup_smoke: {marker}\n'
            ),
        ),
        context=None,
        now='2026-07-11T00:00:00Z',
    )

    assert submission.reply.splitlines()[0] == 'round result: blocked'


def test_v3_config_is_fake_git_worktree_required() -> None:
    text = _load_script().build_v3_config()

    assert 'version = 3' in text
    assert 'provider = "fake"' in text
    assert 'multi_workgroup_workspace = "git-worktree-required"' in text
    assert text.count('workspace_mode = "git-worktree"') == 2
    assert '[windows]' not in text
    assert '[loop.capacity]' not in text


def test_report_merge_order_uses_dependency_layer_then_integration_order() -> None:
    module = _load_script()
    bundle = {
        'nodes': [
            {'node_id': 'node-003', 'depends_on': ['node-001'], 'integration_order': 30},
            {'node_id': 'node-004', 'depends_on': [], 'integration_order': 40},
            {'node_id': 'node-002', 'depends_on': [], 'integration_order': 20},
            {'node_id': 'node-001', 'depends_on': [], 'integration_order': 10},
        ]
    }

    assert module._expected_bundle_merge_order(bundle) == [
        'node-001',
        'node-002',
        'node-004',
        'node-003',
    ]


@pytest.mark.parametrize(
    ('task_status', 'round_result', 'classification'),
    (
        ('done', 'pass', 'pass'),
        ('partial', 'partial', 'valid_non_success'),
        ('blocked', 'blocked', 'valid_non_success'),
        ('replan_required', 'replan_required', 'valid_non_success'),
        ('done', 'blocked', 'system_failure'),
    ),
)
def test_observed_classification_is_derived_from_task_and_round_authority(
    task_status: str,
    round_result: str,
    classification: str,
) -> None:
    module = _load_script()

    assert module._observed_classification(
        task_status=task_status,
        round_result=round_result,
    ) == classification


def test_v3_role_activation_mount_has_loop_owner_and_capacity_digest(tmp_path: Path) -> None:
    capacity = _capacity()
    proposals: list[dict[str, object]] = []

    def loop_topology(_context, command):
        if command.action == 'propose':
            proposals.append(json.loads(Path(command.from_path).read_text(encoding='utf-8')))
            return {'loop_topology_status': 'ready'}
        return {'loop_topology_status': 'ready'}

    context = SimpleNamespace(
        project=SimpleNamespace(project_root=tmp_path),
        paths=SimpleNamespace(runtime_state_root=tmp_path / '.ccb'),
    )
    result = _mount_activation_topology(
        context,
        SimpleNamespace(
            effective_capacity_snapshot=lambda _context: capacity,
            loop_topology=loop_topology,
        ),
        activation_id='act-g5-owner',
        target='loop-act-g5-owner-orchestrator-1',
        profile='ccb_orchestrator',
        window_name='ccb-plan',
        configured=False,
    )

    assert result['loop_topology_status'] == 'ready'
    assert proposals == [
        {
            'schema': 'ccb.loop.agent_mount_topology.v1',
            'owner': {'kind': 'loop', 'loop_id': 'act-g5-owner'},
            'capacity_digest': effective_capacity_digest(capacity),
            'release_policy': {'policy': 'auto', 'idle_only': True},
            'windows': [
                {
                    'name': 'ccb-plan',
                    'class': 'planning',
                    'max_panes': 6,
                    'layout_policy': 'append-or-create-window',
                }
            ],
            'agents': [
                {
                    'id': 'loop-act-g5-owner-orchestrator-1',
                    'profile': 'orchestrator',
                    'desired_state': 'present',
                    'window_name': 'ccb-plan',
                    'pane_order': 0,
                    'lifecycle': 'ephemeral',
                    'release_policy': 'auto',
                }
            ],
        }
    ]


def test_clean_topology_release_records_explicit_zero_residue(tmp_path: Path) -> None:
    context = SimpleNamespace(
        paths=SimpleNamespace(runtime_state_root=tmp_path / '.ccb'),
    )
    payload = _mark_release_residue(
        context,
        'lp-g5-clean',
        payload={
            'retained_count': 0,
            'observed': {'agents': [], 'retained_count': 0},
        },
    )

    assert payload['release_incomplete_count'] == 0
    assert payload['release_incomplete_agents'] == []
    assert payload['observed']['release_incomplete_count'] == 0


def test_terminal_observation_waits_for_release_and_zero_residue(tmp_path: Path) -> None:
    module = _load_script()
    loop_dir = tmp_path / '.ccb/runtime/loops/lp-g5'
    loop_dir.mkdir(parents=True)
    state_path = loop_dir / 'workgroup_scheduler_state.json'
    release = {
        'loop_topology_status': 'released',
        'retained_count': 0,
        'release_incomplete_count': 0,
        'observed': {'agents': []},
    }
    module._find_loop_id = lambda *_args: 'lp-g5'

    for status, topology_release, expected in (
        ('result_imported', None, False),
        ('release_blocked', release, False),
        ('pass', release, True),
        ('blocked', release, True),
    ):
        state_path.write_text(
            json.dumps({'status': status, 'topology': {'release': topology_release}}),
            encoding='utf-8',
        )
        assert module._terminal_release_complete(tmp_path) is expected


def test_logged_concurrent_commands_launch_in_same_observation_window(tmp_path: Path) -> None:
    module = _load_script()
    started = tmp_path / 'first.started'
    release = tmp_path / 'release.first'
    first = (
        "from pathlib import Path\n"
        "import sys, time\n"
        "started = Path(sys.argv[1]); release = Path(sys.argv[2])\n"
        "started.write_text('1', encoding='utf-8')\n"
        "deadline = time.time() + 3\n"
        "while not release.exists():\n"
        "    if time.time() > deadline:\n"
        "        raise SystemExit('release marker missing')\n"
        "    time.sleep(0.02)\n"
        "print('first released')\n"
    )
    second = (
        "from pathlib import Path\n"
        "import sys, time\n"
        "started = Path(sys.argv[1]); release = Path(sys.argv[2])\n"
        "deadline = time.time() + 3\n"
        "while not started.exists():\n"
        "    if time.time() > deadline:\n"
        "        raise SystemExit('first marker missing')\n"
        "    time.sleep(0.02)\n"
        "release.write_text('1', encoding='utf-8')\n"
        "print('second released first')\n"
    )
    command_log: list[dict[str, object]] = []

    records = module._run_logged_concurrent(
        command_log,
        [
            ('first', [sys.executable, '-c', first, str(started), str(release)]),
            ('second', [sys.executable, '-c', second, str(started), str(release)]),
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        logs_dir=tmp_path,
        timeout_s=5,
    )

    assert [item['returncode'] for item in records] == [0, 0]
    assert [item['label'] for item in command_log] == ['first', 'second']
    assert 'first released' in (tmp_path / 'first.stdout').read_text(encoding='utf-8')
    assert 'second released first' in (tmp_path / 'second.stdout').read_text(encoding='utf-8')


def test_chain_submission_retries_only_while_parent_continuation_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    outcomes = [
        (1, '', 'error: ask --chain requires an active parent job for the sender'),
        (1, '', 'error: ask --chain requires an active parent job for the sender'),
        (0, '{"job_id":"job-recheck"}', ''),
    ]

    def run_concurrent(command_log, commands, **_kwargs):
        records = []
        for label, argv in commands:
            returncode, stdout, stderr = outcomes.pop(0)
            record = {
                'label': label,
                'argv': argv,
                'returncode': returncode,
                'stdout': stdout,
                'stderr': stderr,
            }
            command_log.append(record)
            records.append(record)
        return records

    monkeypatch.setattr(module, '_run_logged_concurrent', run_concurrent)
    command_log: list[dict[str, object]] = []

    submitted = module._run_chain_commands_with_parent_retry(
        command_log,
        [('worker_chain_node-001_2_6', ['ccb_test', 'ask', '--chain'])],
        cwd=tmp_path,
        env={},
        logs_dir=tmp_path,
        timeout_s=5,
        retry_attempts=3,
        retry_delay_s=0,
    )

    assert [item['label'] for item in command_log] == [
        'worker_chain_node-001_2_6',
        'worker_chain_node-001_2_6_parent_retry_1',
        'worker_chain_node-001_2_6_parent_retry_2',
    ]
    assert [item['label'] for item in submitted] == [
        'worker_chain_node-001_2_6_parent_retry_2'
    ]
    assert outcomes == []

    outcomes.append((1, '', 'error: permission denied'))
    command_log = []
    submitted = module._run_chain_commands_with_parent_retry(
        command_log,
        [('worker_chain_node-001_2_7', ['ccb_test', 'ask', '--chain'])],
        cwd=tmp_path,
        env={},
        logs_dir=tmp_path,
        timeout_s=5,
        retry_attempts=3,
        retry_delay_s=0,
    )

    assert [item['label'] for item in command_log] == ['worker_chain_node-001_2_7']
    assert submitted == []
    assert outcomes == []


@pytest.mark.ccb_lifecycle_smoke
@REQUIRES_AGENT_ROLES_RUNTIME
@pytest.mark.parametrize(
    ('count', 'shape'),
    ((1, 'parallel'), (2, 'parallel'), (3, 'mixed_dag'), (4, 'mixed_dag')),
)
def test_real_cli_fake_multi_workgroup_full_flow(
    tmp_path: Path,
    count: int,
    shape: str,
) -> None:
    module = _load_script()
    project_root = tmp_path / f'g5-real-cli-fullflow-{count}'

    report = module.run_smoke(
        project_root=project_root,
        count=count,
        shape=shape,
        ccb_test=Path(__file__).resolve().parents[1] / 'ccb_test',
        command_timeout_s=240,
    )

    assert report['status'] == 'pass'
    assert report['bundle']['node_count'] == count
    expected_dependencies = ['node-001'] if shape == 'mixed_dag' else []
    if count >= 3:
        assert report['bundle']['dependencies']['node-003'] == expected_dependencies
    assert report['round']['result'] == 'pass'
    assert report['release']['live_agents'] == []
    assert report['release']['dynamic_residue'] == []
    assert Path(report['paths']['report']).is_file()


@pytest.mark.ccb_lifecycle_smoke
@REQUIRES_AGENT_ROLES_RUNTIME
@pytest.mark.parametrize(
    ('scenario', 'count', 'shape', 'expected_classification'),
    (
        ('reviewer_rework_pass', 1, 'parallel', 'pass'),
        ('reviewer_rework_exhausted_blocked', 1, 'parallel', 'valid_non_success'),
        ('worker_failure_partial', 2, 'parallel', 'valid_non_success'),
        ('all_workers_failed_blocked', 4, 'parallel', 'valid_non_success'),
        ('reviewer_provider_failure', 2, 'parallel', 'valid_non_success'),
        ('round_reviewer_blocked', 4, 'mixed_dag', 'valid_non_success'),
        ('integration_verification_failure', 4, 'mixed_dag', 'valid_non_success'),
        ('root_verification_failure', 4, 'mixed_dag', 'valid_non_success'),
        ('restart_replay_pass', 2, 'parallel', 'pass'),
    ),
)
def test_real_cli_fake_runtime_scenarios(
    tmp_path: Path,
    scenario: str,
    count: int,
    shape: str,
    expected_classification: str,
) -> None:
    module = _load_script()
    project_root = tmp_path / f'g5-real-cli-{scenario}'

    report = module.run_smoke(
        project_root=project_root,
        count=count,
        shape=shape,
        scenario=scenario,
        ccb_test=Path(__file__).resolve().parents[1] / 'ccb_test',
        command_timeout_s=240,
    )

    assert report['status'] == 'pass'
    assert report['execution_mode'] == 'source_fake_runtime'
    assert report['provider'] == 'fake'
    assert report['observed']['classification'] == expected_classification
    assert report['observed']['task_status'] == report['expected']['task_status']
    assert report['observed']['round_result'] == report['expected']['round_result']
    assert report['observed']['round_source'] == report['expected']['round_source']
    assert all(report['checks'].values())
    assert report['post_cleanup'] == {
        'owned_processes': [],
        'socket_entries': [],
        'connectable_sockets': [],
        'child_worktrees': [],
    }
