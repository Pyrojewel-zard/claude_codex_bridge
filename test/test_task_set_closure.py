from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccbd.api_models import DeliveryScope, JobRecord, JobStatus, MessageEnvelope


@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch) -> None:
    """Pin runtime state under .ccb so artifact paths stay project-relative.

    Production defaults to ~/.local/ccb relocation; covered in
    test_path_relocation_defaults.py.
    """
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')
from jobs.store import JobStore
from message_bureau import AttemptRecord, AttemptState, AttemptStore, MessageRecord, MessageState, MessageStore
from storage.paths import PathLayout
from cli.services.plan_tasks import (
    detail_ready_stop_contract_authority,
    find_first_actionable_task,
    plan_task,
    settle_task_set_parent,
)
from cli.services.planner_feedback import (
    frontdesk_status_envelope,
    parse_planner_feedback_reply,
    planner_feedback_digest,
)
from cli.services.planner_feedback_apply import apply_planner_feedback
from cli.services.task_set_feedback_runtime import (
    _frontdesk_message,
    _planner_message,
    _prepared_transport,
    _runtime_digest,
)
from cli.services.ask_runtime.submission import _artifact_request_body
from cli.services.task_set_closure import (
    create_task_set_authority,
    evaluate_task_set_closure,
    find_pending_task_set_closures,
    revise_task_set_authority,
    settle_task_set_closure_feedback,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _context(tmp_path: Path):
    root = tmp_path / 'project'
    _write(root / 'docs/plantree/plans/demo/README.md', '# Demo Plan\n')
    return SimpleNamespace(
        project=SimpleNamespace(project_root=root, project_id='project-task-set'),
    )


def _create_task(context, task_id: str, *, ready: bool = True) -> dict[str, object]:
    created = plan_task(
        context,
        SimpleNamespace(
            action='task-create',
            plan_slug='demo',
            title=task_id,
            task_id=task_id,
        ),
    )
    if not ready:
        return created['task']
    drafts = Path(context.project.project_root) / 'drafts' / task_id
    revision = created['task']['task_revision']
    for kind in ('task_packet', 'execution_contract'):
        path = drafts / f'{kind}.md'
        _write(path, f'# {kind}\nTask: {task_id}\n')
        imported = plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id=task_id,
                artifact_kind=kind,
                file_path=str(path),
                expected_task_revision=revision,
            ),
        )
        revision = imported['task']['task_revision']
    ready_payload = plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id=task_id,
            status='ready_for_orchestration',
            next_owner='orchestrator',
            expected_task_revision=revision,
        ),
    )
    return ready_payload['task']


def _create_set(context, child_specs: list[tuple[str, bool]]) -> dict[str, object]:
    _create_task(context, 'source-intake', ready=False)
    for task_id, _required in child_specs:
        _create_task(context, task_id)
    return create_task_set_authority(
        context,
        plan_slug='demo',
        source_task_id='source-intake',
        source_request={
            'source_job_id': 'job-frontdesk',
            'sha256': hashlib.sha256(b'user request').hexdigest(),
            'bytes': len(b'user request'),
        },
        planner_job={
            'job_id': 'job-planner',
            'reply_sha256': hashlib.sha256(b'planner reply').hexdigest(),
        },
        children=[
            {'task_id': task_id, 'required': required}
            for task_id, required in child_specs
        ],
        plan_task_fn=plan_task,
    )


def _complete(
    context,
    task_id: str,
    result: str,
    *,
    release_clean: bool = True,
    cleanup_complete: bool = True,
    multi: bool = False,
) -> None:
    shown = plan_task(context, SimpleNamespace(action='task-show', task_id=task_id))
    revision = shown['task']['task_revision']
    loop_id = f'loop-{task_id}'
    plan_task(
        context,
        SimpleNamespace(
            action='task-bind-loop',
            task_id=task_id,
            loop_id=loop_id,
            expected_task_revision=revision,
        ),
    )
    summary = Path(context.project.project_root) / 'rounds' / f'{task_id}.md'
    _write(summary, f'round result: {result}\n')
    plan_task(
        context,
        SimpleNamespace(
            action='task-import-round',
            task_id=task_id,
            loop_id=loop_id,
            result=result,
            file_path=str(summary),
            expected_task_revision=revision,
        ),
    )
    release = {
        'loop_topology_status': 'released' if release_clean else 'release_incomplete',
        'released_count': 2 if release_clean else 0,
        'retained_count': 0 if release_clean else 1,
        'release_incomplete_count': 0 if release_clean else 1,
    }
    round_record: dict[str, object] = {
        'schema': 'ccb.loop.round_state.v1',
        'task_id': task_id,
        'loop_id': loop_id,
        'round_result': result,
        'dispatch_source': 'multi_workgroup_scheduler' if multi else 'ask_first_direct_execution',
        'release': release,
    }
    if multi:
        round_record['cleanup'] = (
            {'result': {'status': 'complete'}}
            if cleanup_complete
            else {'readiness': {'eligible': False}}
        )
    path = Path(context.project.project_root) / '.ccb/runtime/loops' / loop_id / 'round.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(round_record, sort_keys=True) + '\n', encoding='utf-8')


def _planner_proposal(
    task_set_id: str,
    closure: dict[str, object],
    plan_revision: str,
    *,
    notification_required: bool = False,
):
    evidence = [f'docs/plantree/plans/demo/task-sets/{task_set_id}/closure.json']
    next_milestone = {'kind': 'workflow_terminal', 'ref': 'done', 'rationale': 'Done.'}
    payload = {
        'schema': 'ccb.planner.backfill_proposal.v1',
        'mode': 'task_set_closure',
        'expected_plan_revision': plan_revision,
        'task_or_task_set_id': task_set_id,
        'task_or_task_set_revision': 1,
        'closure_evidence_digest': closure['ordered_terminal_evidence_digest'],
        'aggregate_result': 'pass',
        'result': 'closure_complete',
        'brief_summary': 'Closed.',
        'roadmap_transitions': [],
        'todo_transitions': [],
        'decision_refs': [],
        'open_question_refs': [],
        'evidence_refs': evidence,
        'accepted_scope': ['landed'],
        'unresolved_scope': [],
        'blockers': [],
        'replan_inputs': [],
        'next_milestone': next_milestone,
        'frontdesk_notification_required': notification_required,
        'frontdesk_status': {
            'schema': 'ccb.planner.frontdesk_status.v1',
            'notification_identity': f'{task_set_id}-r1',
            'aggregate_result': 'pass',
            'accepted_scope': ['landed'],
            'unresolved_scope': [],
            'blockers': [],
            'next_milestone': next_milestone,
            'evidence_refs': evidence,
            'user_report_body': 'Done.',
        },
    }
    reply = '**planner-backfill.json**\n```json\n' + json.dumps(payload) + '\n```\n'
    return parse_planner_feedback_reply(reply)


def _completed_job(
    context, *, target: str, job_id: str, task_id: str, message: str, reply: str,
    provider_options: dict[str, object] | None = None,
) -> None:
    request = MessageEnvelope(
        project_id=context.project.project_id,
        to_agent=target,
        from_actor='system',
        body=message,
        task_id=task_id,
        reply_to=None,
        message_type='task',
        delivery_scope=DeliveryScope.SINGLE,
        silence_on_success=target == 'planner',
    )
    JobStore(PathLayout(context.project.project_root)).append(JobRecord(
        job_id=job_id,
        submission_id=None,
        agent_name=target,
        provider='codex',
        request=request,
        status=JobStatus.COMPLETED,
        terminal_decision={'terminal': True, 'status': 'completed', 'reply': reply},
        cancel_requested_at=None,
        created_at='2026-07-12T00:00:00Z',
        updated_at='2026-07-12T00:00:01Z',
        provider_options=provider_options or {},
    ))


def _failed_job(context, *, target: str, job_id: str, task_id: str, message: str) -> None:
    request = MessageEnvelope(
        project_id=context.project.project_id, to_agent=target, from_actor='system',
        body=message, task_id=task_id, reply_to=None, message_type='task',
        delivery_scope=DeliveryScope.SINGLE, silence_on_success=target == 'planner',
    )
    JobStore(PathLayout(context.project.project_root)).append(JobRecord(
        job_id=job_id, submission_id=None, agent_name=target, provider='codex',
        request=request, status=JobStatus.FAILED,
        terminal_decision={'terminal': True, 'status': 'failed', 'reply': 'failed'},
        cancel_requested_at=None, created_at='2026-07-12T00:00:00Z',
        updated_at='2026-07-12T00:00:01Z',
    ))


def _retry_authority(context, *, target: str, jobs: list[str]) -> list[dict[str, object]]:
    layout = PathLayout(context.project.project_root)
    message_id = f'msg_{target}_retry'
    MessageStore(layout).append(MessageRecord(
        message_id=message_id, origin_message_id=None, from_actor='system',
        target_scope='single', target_agents=(target,), message_class='ask',
        retry_policy={'mode': 'auto', 'max_attempts': 3},
        created_at='2026-07-12T00:00:00Z', updated_at='2026-07-12T00:00:03Z',
        message_state=MessageState.COMPLETED,
    ))
    attempts = AttemptStore(layout)
    records = []
    for index, job_id in enumerate(jobs):
        attempt_id = f'att_{target}_{index}'
        attempts.append(AttemptRecord(
            attempt_id=attempt_id, message_id=message_id, agent_name=target,
            provider='codex', job_id=job_id, retry_index=index,
            health_snapshot_ref=None, started_at=f'2026-07-12T00:00:0{index}Z',
            updated_at=f'2026-07-12T00:00:0{index + 1}Z',
            attempt_state=(AttemptState.COMPLETED if index == len(jobs) - 1 else AttemptState.FAILED),
        ))
        if index:
            records.append({
                'message_id': message_id,
                'source_attempt_id': f'att_{target}_{index - 1}',
                'successor_attempt_id': attempt_id,
                'retry_source_job_id': jobs[index - 1],
                'retry_successor_job_id': job_id,
                'retry_index': index,
            })
    return records


def _closure_ref(task_set_id: str, closure: dict[str, object]) -> dict[str, object]:
    return {
        'path': f'docs/plantree/plans/demo/task-sets/{task_set_id}/closure.json',
        'closure_digest': closure['closure_digest'],
        'ordered_terminal_evidence_digest': closure['ordered_terminal_evidence_digest'],
    }


def _settlement_fixture(
    context,
    *,
    notification_required: bool = False,
    planner_retry: bool = False,
    frontdesk_retry: bool = False,
    retry_chain: bool = False,
):
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    closed = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    intent = closed['closure_intent']
    root = Path(context.project.project_root)
    task_set_root = root / 'docs/plantree/plans/demo/task-sets' / task_set_id
    task_set = json.loads((task_set_root / 'task-set.json').read_text(encoding='utf-8'))
    proposal = _planner_proposal(
        task_set_id,
        closed['closure'],
        task_set['plan_revision']['digest'],
        notification_required=notification_required,
    )
    feedback_digest = planner_feedback_digest(proposal)
    planner_source_job_id = 'job_planner_source' if planner_retry else 'job_planner'
    planner_jobs = ([planner_source_job_id, 'job_planner_retry'] + (
        ['job_planner_retry_2'] if retry_chain else []
    )) if planner_retry else [planner_source_job_id]
    planner_job_id = planner_jobs[-1]
    planner_lineage = (_retry_authority(
        context, target='planner', jobs=planner_jobs
    ) if planner_retry else [])
    imported = apply_planner_feedback(context, proposal, {
        'task_set_id': task_set_id,
        'task_set_revision': 1,
        'closure_intent_id': intent['intent_id'],
        'closure_digest': closed['closure']['closure_digest'],
        'ordered_terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
        'expected_plan_revision': task_set['plan_revision']['digest'],
        'planner_job_id': planner_job_id,
        'planner_source_job_id': planner_source_job_id,
        'planner_effective_job_id': planner_job_id,
        'planner_retry_lineage': planner_lineage,
        'planner_feedback_digest': feedback_digest,
        'plan_slug': 'demo',
    })
    planner_message = _planner_message(
        closed['closure'], intent, _closure_ref(task_set_id, closed['closure'])
    )
    planner = _prepared_transport(
        target='planner', purpose='planner_backfill',
        task_id=f'task-set-feedback-{intent["intent_id"]}',
        message=planner_message, silent=True,
    )
    proposal_reply = '**planner-backfill.json**\n```json\n' + json.dumps(proposal.to_record()) + '\n```\n'
    planner.update({
        'job_id': planner_source_job_id, 'source_job_id': planner_source_job_id,
        'effective_job_id': planner_job_id, 'retry_lineage': [],
        'status': 'completed', 'reply': proposal_reply,
    })
    planner['retry_lineage'] = planner_lineage
    if planner_retry:
        for failed_job_id in planner_jobs[:-1]:
            _failed_job(
                context, target='planner', job_id=failed_job_id,
                task_id=str(planner['task_id']), message=planner_message,
            )
    _completed_job(
        context, target='planner', job_id=planner_job_id,
        task_id=str(planner['task_id']), message=planner_message, reply=proposal_reply,
        provider_options=(
            {'retry_source_job_id': planner_jobs[-2]} if planner_retry else None
        ),
    )
    frontdesk = None
    notification = {'status': 'notification_not_required'}
    frontdesk_job_id = None
    if notification_required:
        frontdesk_source_job_id = 'job_frontdesk_source' if frontdesk_retry else 'job_frontdesk'
        frontdesk_jobs = ([frontdesk_source_job_id, 'job_frontdesk_retry'] + (
            ['job_frontdesk_retry_2'] if retry_chain else []
        )) if frontdesk_retry else [frontdesk_source_job_id]
        frontdesk_job_id = frontdesk_jobs[-1]
        frontdesk_lineage = (_retry_authority(
            context, target='frontdesk', jobs=frontdesk_jobs
        ) if frontdesk_retry else [])
        frontdesk_message = _frontdesk_message(frontdesk_status_envelope(proposal))
        frontdesk = _prepared_transport(
            target='frontdesk', purpose='frontdesk_status',
            task_id=f'task-set-status-{intent["intent_id"]}',
            message=frontdesk_message, silent=False,
        )
        frontdesk.update({
            'job_id': frontdesk_source_job_id, 'source_job_id': frontdesk_source_job_id,
            'effective_job_id': frontdesk_job_id, 'retry_lineage': frontdesk_lineage,
            'status': 'completed', 'reply': 'delivered',
        })
        if frontdesk_retry:
            for failed_job_id in frontdesk_jobs[:-1]:
                _failed_job(
                    context, target='frontdesk', job_id=failed_job_id,
                    task_id=str(frontdesk['task_id']), message=frontdesk_message,
                )
        _completed_job(
            context, target='frontdesk', job_id=frontdesk_job_id,
            task_id=str(frontdesk['task_id']), message=frontdesk_message, reply='delivered',
            provider_options=(
                {'retry_source_job_id': frontdesk_jobs[-2]} if frontdesk_retry else None
            ),
        )
        notification = {'status': 'delivered', 'job_id': frontdesk_job_id}
    runtime_path = root / '.ccb/runtime/task-sets' / task_set_id / 'feedback-r1.json'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = {
        'schema': 'ccb.plan.task_set_feedback_runtime.v1',
        'schema_version': 1,
        'task_set_id': task_set_id,
        'task_set_revision': 1,
        'closure_intent_id': intent['intent_id'],
        'closure_digest': closed['closure']['closure_digest'],
        'terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
        'stage': 'closed',
        'planner': planner,
        'frontdesk': frontdesk,
        'backfill_import': {
            'task_set_id': task_set_id,
            'task_set_revision': 1,
            'closure_intent_id': intent['intent_id'],
            'closure_digest': closed['closure']['closure_digest'],
            'ordered_terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
            'expected_plan_revision': task_set['plan_revision']['digest'],
            'planner_job_id': planner_job_id,
            'planner_source_job_id': planner_source_job_id,
            'planner_effective_job_id': planner_job_id,
            'planner_retry_lineage': planner_lineage,
            'planner_feedback_digest': feedback_digest,
            'plan_slug': 'demo',
            **imported,
        },
        'notification': notification,
    }
    runtime['runtime_digest'] = _runtime_digest(runtime)
    runtime_path.write_text(json.dumps(runtime), encoding='utf-8')
    authority = {
        'task_set_id': task_set_id,
        'task_set_revision': 1,
        'intent_id': intent['intent_id'],
        'ordered_terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
        'transport_ref': {
            'runtime_state_path': str(runtime_path),
            'planner_job_id': planner_job_id,
            'planner_source_job_id': planner_source_job_id,
            'planner_effective_job_id': planner_job_id,
            'planner_retry_lineage': planner_lineage,
            'frontdesk_job_id': frontdesk_job_id,
            'planner_backfill_path': imported['planner_backfill_path'],
            'planner_feedback_digest': feedback_digest,
            'notification_status': notification['status'],
            'backfill_digest': imported['backfill_digest'],
            'frontdesk_source_job_id': (
                frontdesk.get('source_job_id') if frontdesk else None
            ),
            'frontdesk_effective_job_id': frontdesk_job_id,
            'frontdesk_retry_lineage': (
                frontdesk.get('retry_lineage') if frontdesk else None
            ),
        },
    }
    if frontdesk_job_id is None:
        authority['transport_ref'].pop('frontdesk_job_id')
    return authority, runtime_path, Path(imported['planner_backfill_path'])


def test_task_set_parent_is_decomposed_and_children_are_revision_bound(tmp_path: Path) -> None:
    context = _context(tmp_path)

    created = _create_set(context, [('child-a', True), ('child-b', False)])

    parent = plan_task(context, SimpleNamespace(action='task-show', task_id='source-intake'))['task']
    required = plan_task(context, SimpleNamespace(action='task-show', task_id='child-a'))['task']
    optional = plan_task(context, SimpleNamespace(action='task-show', task_id='child-b'))['task']
    assert parent['status'] == 'decomposed'
    assert parent['next_owner'] == 'planner'
    assert 'completion' not in parent['artifacts']
    assert parent['task_set_parent']['task_set_revision'] == 1
    assert required['task_set'] == {
        'schema': 'ccb.plan.task_set_binding.v1',
        'task_set_id': created['task_set']['task_set_id'],
        'task_set_revision': 1,
        'binding_role': 'child',
        'bound_task_revision': 1,
        'required': True,
        'order': 0,
    }
    assert optional['task_set']['required'] is False
    assert created['task_set']['state'] == 'running'
    assert find_first_actionable_task(context, task_id='source-intake') is None


def test_large_spilled_source_request_is_normalized_project_relative(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _create_task(context, 'source-intake', ready=False)
    _create_task(context, 'child-a')
    body = 'x' * (1024 * 1024 + 1)
    _stub, artifact = _artifact_request_body(
        PathLayout(context.project.project_root),
        body,
        owner_id='job-frontdesk',
        force=True,
    )
    created = create_task_set_authority(
        context,
        plan_slug='demo',
        source_task_id='source-intake',
        source_request={
            'source_job_id': 'job-frontdesk',
            'sha256': hashlib.sha256(body.encode()).hexdigest(),
            'bytes': len(body.encode()),
            'body_artifact': artifact,
        },
        planner_job={'job_id': 'job-planner', 'reply_sha256': 'a' * 64},
        children=[{'task_id': 'child-a', 'required': True}],
        plan_task_fn=plan_task,
    )

    normalized = created['task_set']['source_request']['body_artifact']
    assert normalized == {
        'kind': 'ask-request',
        'path': str(Path(artifact['path']).relative_to(context.project.project_root)),
        'bytes': len(body.encode()),
        'sha256': hashlib.sha256(body.encode()).hexdigest(),
    }
    assert not Path(normalized['path']).is_absolute()
    _complete(context, 'child-a', 'pass')
    closed = evaluate_task_set_closure(
        context, task_set_id=created['task_set']['task_set_id'], plan_task_fn=plan_task
    )
    envelope = json.loads(
        _planner_message(
            closed['closure'],
            closed['closure_intent'],
            _closure_ref(created['task_set']['task_set_id'], closed['closure']),
        ).split('```json\n', 1)[1].rsplit('\n```', 1)[0]
    )
    assert envelope['closure']['source_request']['body_artifact'] == normalized


@pytest.mark.parametrize(
    'case',
    ('outside', 'traversal', 'symlink', 'wrong_kind', 'bytes', 'digest', 'missing', 'malformed'),
)
def test_source_request_artifact_invalid_authority_fails_closed(
    tmp_path: Path, case: str
) -> None:
    context = _context(tmp_path)
    from cli.services import task_set_closure as service
    body = 'source artifact body'
    _stub, artifact = _artifact_request_body(
        PathLayout(context.project.project_root), body,
        owner_id='job-frontdesk', force=True,
    )
    artifact = dict(artifact)
    source = {
        'source_job_id': 'job-frontdesk',
        'sha256': hashlib.sha256(body.encode()).hexdigest(),
        'bytes': len(body.encode()),
        'body_artifact': artifact,
    }
    if case == 'outside':
        outside = tmp_path / 'outside.txt'
        outside.write_text(body, encoding='utf-8')
        artifact['path'] = str(outside)
    elif case == 'traversal':
        artifact['path'] = '.ccb/ccbd/artifacts/text/ask-request/../ask-request/' + Path(artifact['path']).name
    elif case == 'symlink':
        path = Path(artifact['path'])
        target = tmp_path / 'artifact-target.txt'
        path.replace(target)
        path.symlink_to(target)
    elif case == 'wrong_kind':
        artifact['kind'] = 'completion-reply'
    elif case == 'bytes':
        artifact['bytes'] += 1
    elif case == 'digest':
        artifact['sha256'] = 'f' * 64
    elif case == 'missing':
        Path(artifact['path']).unlink()
    else:
        artifact.pop('kind')

    with pytest.raises(ValueError, match='task-set source request artifact'):
        service._source_request(context, source)


@pytest.mark.parametrize(
    ('aggregate_result', 'expected_status', 'expected_owner'),
    (
        ('pass', 'done', 'frontdesk'),
        ('partial', 'partial', 'planner'),
        ('replan_required', 'replan_required', 'planner'),
        ('blocked', 'blocked', 'frontdesk'),
    ),
)
def test_task_set_parent_settlement_maps_each_aggregate_exactly_once(
    tmp_path: Path,
    aggregate_result: str,
    expected_status: str,
    expected_owner: str,
) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    authority = dict(
        task_id='source-intake',
        task_set_id=task_set_id,
        task_set_revision=1,
        aggregate_result=aggregate_result,
        closure_digest='sha256:' + 'c' * 64,
        planner_feedback_digest='sha256:' + 'f' * 64,
    )

    first = settle_task_set_parent(context, **authority)
    replay = settle_task_set_parent(context, **authority)

    assert first['idempotent'] is False
    assert replay['idempotent'] is True
    assert replay['task']['status'] == expected_status
    assert replay['task']['owner'] == expected_owner


@pytest.mark.parametrize(
    ('results', 'expected', 'reason'),
    (
        (('pass', 'pass'), 'pass', 'all_required_children_passed'),
        (('pass', 'replan_required'), 'replan_required', 'one_or_more_required_children_require_replan'),
        (('pass', 'partial'), 'partial', 'one_or_more_required_children_are_partial'),
        (('pass', 'blocked'), 'partial', 'required_children_include_pass_and_blocked'),
        (('blocked', 'blocked'), 'blocked', 'all_required_children_are_blocked'),
    ),
)
def test_task_set_aggregate_precedence_rows(
    tmp_path: Path,
    results: tuple[str, str],
    expected: str,
    reason: str,
) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True), ('child-b', True)])
    for task_id, result in zip(('child-a', 'child-b'), results):
        _complete(context, task_id, result)

    closed = evaluate_task_set_closure(
        context,
        task_set_id=created['task_set']['task_set_id'],
        plan_task_fn=plan_task,
    )

    assert closed['status'] == 'closure_pending'
    assert closed['closure']['expected_plan_revision'].startswith('sha256:')
    assert closed['closure']['aggregate_result'] == expected
    assert closed['closure']['reason'] == reason
    assert closed['closure_intent']['status'] == 'pending_planner_backfill'


def test_task_set_closure_accepts_verified_detail_ready_terminal_evidence(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _create_task(context, 'source-intake', ready=False)
    child_ids = (
        'child-pass-one',
        'child-pass-two',
        'child-detail-ready',
        'child-replan',
        'child-blocked',
    )
    for task_id in child_ids:
        _create_task(context, task_id)
    _complete(context, 'child-pass-one', 'pass')
    _complete(context, 'child-pass-two', 'pass')
    _complete(context, 'child-replan', 'replan_required')
    _complete(context, 'child-blocked', 'blocked')
    root = Path(context.project.project_root)
    revision = plan_task(
        context,
        SimpleNamespace(action='task-show', task_id='child-detail-ready'),
    )['task']['task_revision']
    for kind, text in (
        (
            'task_packet',
            '# Task: child-detail-ready\nRoute: needs_detail\nExpected stop: detail_ready.\n',
        ),
        (
            'execution_contract',
            '# Execution Contract\nRoute: needs_detail\nExpected stop: detail_ready.\n',
        ),
        (
            'orchestration_notes',
            'Task: child-detail-ready\nRoute: needs_detail\nExpected stop: detail_ready.\n',
        ),
    ):
        path = root / 'drafts' / f'{kind}.md'
        _write(path, text)
        imported = plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='child-detail-ready',
                artifact_kind=kind,
                file_path=str(path),
                expected_task_revision=revision,
                route='needs_detail' if kind == 'orchestration_notes' else None,
            ),
        )
        revision = imported['task']['task_revision']
    detailer_job_id = 'job_child_detail_ready'
    activation_id = 'act-child-detail-ready'
    _write(
        root / '.ccb/runtime/loops/activations' / f'{activation_id}.json',
        json.dumps(
            {
                'activation_id': activation_id,
                'task_id': 'child-detail-ready',
                'task_revision': revision,
                'ask': {'target': 'task_detailer', 'job_id': detailer_job_id},
            },
            sort_keys=True,
        )
        + '\n',
    )
    imported_detail: dict[str, dict[str, object]] = {}
    role_output_root = root / '.ccb/runtime/role-output-imports' / detailer_job_id
    for kind, filename, text in (
        ('detail_design', 'task-detail-design.md', '# Detail Design\nResolved.\n'),
        ('detail_summary', 'brief-update-summary.md', '# Detail Summary\nResolved.\n'),
        (
            'detail_packet',
            'detail-packet.manifest.json',
            '{"detail_readiness_recommendation":"detail_ready"}\n',
        ),
    ):
        path = role_output_root / filename
        _write(path, text)
        imported = plan_task(
            context,
            SimpleNamespace(
                action='task-artifact',
                task_id='child-detail-ready',
                artifact_kind=kind,
                file_path=str(path),
                expected_task_revision=revision,
                actor_source='loop_runner_role_output_import',
                actor='loop_runner',
                job_id=detailer_job_id,
            ),
        )
        revision = imported['task']['task_revision']
        imported_detail[kind] = imported['artifact']
    _write(
        root / '.ccb/runtime/role-output-imports.jsonl',
        json.dumps(
            {
                'action': 'imported_task_detailer_detail_authority',
                'task_id': 'child-detail-ready',
                'source_job': {'job_id': detailer_job_id},
                'artifacts': {
                    kind: {'sha256': artifact['sha256']}
                    for kind, artifact in imported_detail.items()
                },
            },
            sort_keys=True,
        )
        + '\n',
    )
    plan_task(
        context,
        SimpleNamespace(
            action='task-status',
            task_id='child-detail-ready',
            status='detail_ready',
            next_owner='planner',
            expected_task_revision=revision,
        ),
    )
    created = create_task_set_authority(
        context,
        plan_slug='demo',
        source_task_id='source-intake',
        source_request={
            'source_job_id': 'job-frontdesk',
            'sha256': hashlib.sha256(b'user request').hexdigest(),
            'bytes': len(b'user request'),
        },
        planner_job={
            'job_id': 'job-planner',
            'reply_sha256': hashlib.sha256(b'planner reply').hexdigest(),
        },
        children=[{'task_id': task_id, 'required': True} for task_id in child_ids],
        plan_task_fn=plan_task,
    )
    detail_task = plan_task(
        context,
        SimpleNamespace(action='task-show', task_id='child-detail-ready'),
    )['task']
    stop_authority = detail_ready_stop_contract_authority(detail_task, project_root=root)
    assert stop_authority is not None
    assert stop_authority['basis']['detail_provenance']['job_id'] == detailer_job_id
    assert stop_authority['basis']['detail_provenance']['activation_id'] == activation_id
    for kind, artifact in imported_detail.items():
        recorded = stop_authority['basis']['artifacts'][kind]
        assert recorded['sha256'] == artifact['sha256']
        assert recorded['sha256'] == hashlib.sha256(
            (root / recorded['path']).read_bytes()
        ).hexdigest()
    closed = evaluate_task_set_closure(
        context,
        task_set_id=created['task_set']['task_set_id'],
        plan_task_fn=plan_task,
    )

    assert closed['status'] == 'closure_pending'
    assert closed['closure']['aggregate_result'] == 'replan_required'
    assert closed['closure']['reason'] == 'one_or_more_required_children_require_replan'
    detail = next(item for item in closed['closure']['ordered_children'] if item['task_id'] == 'child-detail-ready')
    assert detail['status'] == 'detail_ready'
    assert detail['result'] == 'pass'
    assert detail['authority']['artifact_kind'] == 'detail_ready_stop_contract'
    assert detail['authority']['authority_digest'] == stop_authority['authority_digest']
    assert detail['authority']['basis_digest'] == stop_authority['basis_digest']


def test_optional_pending_child_does_not_block_required_closure(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('required-child', True), ('optional-child', False)])
    _complete(context, 'required-child', 'pass')

    closed = evaluate_task_set_closure(
        context,
        task_set_id=created['task_set']['task_set_id'],
        plan_task_fn=plan_task,
    )

    assert closed['closure']['aggregate_result'] == 'pass'
    assert [item['task_id'] for item in closed['closure']['ordered_children']] == ['required-child']


@pytest.mark.parametrize(
    ('release_clean', 'cleanup_complete', 'expected_reason'),
    (
        (False, True, 'terminal_child_release_incomplete'),
        (True, False, 'terminal_child_cleanup_incomplete'),
    ),
)
def test_incomplete_release_or_cleanup_is_system_failure_without_semantic_intent(
    tmp_path: Path,
    release_clean: bool,
    cleanup_complete: bool,
    expected_reason: str,
) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    _complete(
        context,
        'child-a',
        'pass',
        release_clean=release_clean,
        cleanup_complete=cleanup_complete,
        multi=True,
    )

    failed = evaluate_task_set_closure(
        context,
        task_set_id=created['task_set']['task_set_id'],
        plan_task_fn=plan_task,
    )

    assert failed['status'] == 'system_failure'
    assert failed['closure']['aggregate_result'] is None
    assert failed['failures'][0]['reason'] == expected_reason
    assert failed['planner_intent_created'] is False


def test_last_child_creates_one_exact_once_closure_intent_and_replay_reuses_it(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True), ('child-b', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    pending = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    assert pending['status'] == 'pending'
    assert pending['child_task_ids'] == ['child-b']
    _complete(context, 'child-b', 'pass')

    first = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    replay = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    discovered = find_pending_task_set_closures(context)

    assert first['planner_intent_created'] is True
    assert replay['idempotent'] is True
    assert replay['closure_intent']['intent_id'] == first['closure_intent']['intent_id']
    assert discovered['pending_count'] == 1
    assert discovered['pending'][0]['intent_id'] == first['closure_intent']['intent_id']


def test_feedback_settlement_removes_intent_from_pending_discovery(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    closed = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    intent = closed['closure_intent']
    root = Path(context.project.project_root)
    task_set_root = root / 'docs/plantree/plans/demo/task-sets' / task_set_id
    planner_job_id = 'job_planner'
    task_set = json.loads((task_set_root / 'task-set.json').read_text(encoding='utf-8'))
    proposal = _planner_proposal(task_set_id, closed['closure'], task_set['plan_revision']['digest'])
    feedback_digest = planner_feedback_digest(proposal)
    imported = apply_planner_feedback(context, proposal, {
        'task_set_id': task_set_id,
        'task_set_revision': 1,
        'closure_intent_id': intent['intent_id'],
        'closure_digest': closed['closure']['closure_digest'],
        'ordered_terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
        'expected_plan_revision': task_set['plan_revision']['digest'],
        'planner_job_id': planner_job_id,
        'planner_feedback_digest': feedback_digest,
        'plan_slug': 'demo',
    })
    backfill_path = Path(imported['planner_backfill_path'])
    planner_message = _planner_message(
        closed['closure'], intent, _closure_ref(task_set_id, closed['closure'])
    )
    planner = _prepared_transport(
        target='planner',
        purpose='planner_backfill',
        task_id=f'task-set-feedback-{intent["intent_id"]}',
        message=planner_message,
        silent=True,
    )
    proposal_reply = '**planner-backfill.json**\n```json\n' + json.dumps(proposal.to_record()) + '\n```\n'
    planner.update({
        'job_id': planner_job_id, 'source_job_id': planner_job_id,
        'effective_job_id': planner_job_id, 'retry_lineage': [],
        'status': 'completed', 'reply': proposal_reply,
    })
    _completed_job(
        context,
        target='planner',
        job_id=planner_job_id,
        task_id=str(planner['task_id']),
        message=planner_message,
        reply=proposal_reply,
    )
    runtime_path = root / '.ccb/runtime/task-sets' / task_set_id / 'feedback-r1.json'
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = {
        'schema': 'ccb.plan.task_set_feedback_runtime.v1',
        'schema_version': 1,
        'task_set_id': task_set_id,
        'task_set_revision': 1,
        'closure_intent_id': intent['intent_id'],
        'closure_digest': closed['closure']['closure_digest'],
        'terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
        'stage': 'closed',
        'planner': planner,
        'frontdesk': None,
        'backfill_import': {
            'task_set_id': task_set_id,
            'task_set_revision': 1,
            'closure_intent_id': intent['intent_id'],
            'closure_digest': closed['closure']['closure_digest'],
            'ordered_terminal_evidence_digest': intent['ordered_terminal_evidence_digest'],
            'expected_plan_revision': task_set['plan_revision']['digest'],
            'planner_job_id': planner_job_id,
            'planner_source_job_id': planner_job_id,
            'planner_effective_job_id': planner_job_id,
            'planner_retry_lineage': [],
            'planner_feedback_digest': feedback_digest,
            'plan_slug': 'demo',
            **imported,
        },
        'notification': {'status': 'notification_not_required'},
    }
    runtime['runtime_digest'] = _runtime_digest(runtime)
    runtime_path.write_text(json.dumps(runtime), encoding='utf-8')
    authority = dict(
        task_set_id=task_set_id,
        task_set_revision=1,
        intent_id=intent['intent_id'],
        ordered_terminal_evidence_digest=intent['ordered_terminal_evidence_digest'],
        transport_ref={
            'runtime_state_path': str(runtime_path),
            'planner_job_id': planner_job_id,
            'planner_source_job_id': planner_job_id,
            'planner_effective_job_id': planner_job_id,
            'planner_retry_lineage': [],
            'planner_backfill_path': str(backfill_path),
            'planner_feedback_digest': feedback_digest,
            'notification_status': 'notification_not_required',
            'backfill_digest': imported['backfill_digest'],
        },
    )

    with pytest.raises(ValueError, match='intent not found'):
        settle_task_set_closure_feedback(context, **{**authority, 'intent_id': 'tsi-wrong'})
    assert plan_task(
        context, SimpleNamespace(action='task-show', task_id='source-intake')
    )['task']['status'] == 'decomposed'

    first = settle_task_set_closure_feedback(context, **authority)
    replay = settle_task_set_closure_feedback(context, **authority)
    discovered = find_pending_task_set_closures(context)

    assert first['idempotent'] is False
    assert replay['idempotent'] is True
    assert discovered['pending_count'] == 0
    assert first['intent']['status'] == 'feedback_closed'
    assert plan_task(context, SimpleNamespace(action='task-show', task_id='source-intake'))['task']['status'] == 'done'


@pytest.mark.parametrize('authority_path', ('runtime_state_path', 'planner_backfill_path'))
def test_settlement_rejects_external_runtime_or_backfill_authority(
    tmp_path: Path, authority_path: str
) -> None:
    context = _context(tmp_path)
    authority, runtime_path, backfill_path = _settlement_fixture(context)
    source = runtime_path if authority_path == 'runtime_state_path' else backfill_path
    external = tmp_path / f'external-{source.name}'
    external.write_bytes(source.read_bytes())
    authority['transport_ref'][authority_path] = str(external)

    with pytest.raises(ValueError, match='path authority mismatch'):
        settle_task_set_closure_feedback(context, **authority)
    assert plan_task(
        context, SimpleNamespace(action='task-show', task_id='source-intake')
    )['task']['status'] == 'decomposed'


def test_settlement_rejects_notification_required_bypass(tmp_path: Path) -> None:
    context = _context(tmp_path)
    authority, runtime_path, _backfill_path = _settlement_fixture(
        context, notification_required=True
    )
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    runtime['frontdesk'] = None
    runtime['notification'] = {'status': 'notification_not_required'}
    runtime['runtime_digest'] = _runtime_digest(runtime)
    runtime_path.write_text(json.dumps(runtime), encoding='utf-8')
    authority['transport_ref']['notification_status'] = 'notification_not_required'
    authority['transport_ref'].pop('frontdesk_job_id')

    with pytest.raises(ValueError, match='notification authority invalid'):
        settle_task_set_closure_feedback(context, **authority)
    assert plan_task(
        context, SimpleNamespace(action='task-show', task_id='source-intake')
    )['task']['status'] == 'decomposed'


def test_settlement_accepts_completed_required_frontdesk_delivery(tmp_path: Path) -> None:
    context = _context(tmp_path)
    authority, _runtime_path, _backfill_path = _settlement_fixture(
        context, notification_required=True
    )

    settled = settle_task_set_closure_feedback(context, **authority)

    assert settled['status'] == 'feedback_closed'
    assert plan_task(
        context, SimpleNamespace(action='task-show', task_id='source-intake')
    )['task']['status'] == 'done'


def test_settlement_accepts_completed_planner_and_frontdesk_retry_successors(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    authority, _runtime_path, _backfill_path = _settlement_fixture(
        context,
        notification_required=True,
        planner_retry=True,
        frontdesk_retry=True,
    )

    settled = settle_task_set_closure_feedback(context, **authority)

    assert settled['status'] == 'feedback_closed'
    transport = settled['intent']['transport_ref']
    assert transport['planner_source_job_id'] == 'job_planner_source'
    assert transport['planner_effective_job_id'] == 'job_planner_retry'
    assert transport['frontdesk_source_job_id'] == 'job_frontdesk_source'
    assert transport['frontdesk_effective_job_id'] == 'job_frontdesk_retry'


def test_settlement_accepts_authoritative_planner_and_frontdesk_retry_chains(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    authority, _runtime_path, _backfill_path = _settlement_fixture(
        context, notification_required=True, planner_retry=True,
        frontdesk_retry=True, retry_chain=True,
    )

    settled = settle_task_set_closure_feedback(context, **authority)

    transport = settled['intent']['transport_ref']
    assert transport['planner_effective_job_id'] == 'job_planner_retry_2'
    assert transport['frontdesk_effective_job_id'] == 'job_frontdesk_retry_2'
    assert [edge['retry_index'] for edge in transport['planner_retry_lineage']] == [1, 2]
    assert [edge['retry_index'] for edge in transport['frontdesk_retry_lineage']] == [1, 2]


@pytest.mark.parametrize('target', ('planner', 'frontdesk'))
def test_settlement_rejects_forged_or_missing_completed_job(
    tmp_path: Path, target: str
) -> None:
    context = _context(tmp_path)
    authority, runtime_path, _backfill_path = _settlement_fixture(
        context, notification_required=target == 'frontdesk'
    )
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    runtime[target]['job_id'] = f'job_forged_{target}'
    runtime['runtime_digest'] = _runtime_digest(runtime)
    runtime_path.write_text(json.dumps(runtime), encoding='utf-8')
    authority['transport_ref'][f'{target}_job_id'] = f'job_forged_{target}'

    with pytest.raises(
        ValueError,
        match=(
            'persisted job is not terminal completed|imported backfill authority mismatch|'
            'Frontdesk delivery is incomplete'
        ),
    ):
        settle_task_set_closure_feedback(context, **authority)


def test_settlement_rejects_mismatched_planner_message_identity(tmp_path: Path) -> None:
    context = _context(tmp_path)
    authority, runtime_path, _backfill_path = _settlement_fixture(context)
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    runtime['planner']['message'] = 'forged message'
    runtime['planner']['message_sha256'] = hashlib.sha256(b'forged message').hexdigest()
    runtime['runtime_digest'] = _runtime_digest(runtime)
    runtime_path.write_text(json.dumps(runtime), encoding='utf-8')

    with pytest.raises(ValueError, match='Planner message authority mismatch'):
        settle_task_set_closure_feedback(context, **authority)


def test_settlement_rejects_nonterminal_planner_job(tmp_path: Path) -> None:
    context = _context(tmp_path)
    authority, runtime_path, _backfill_path = _settlement_fixture(context)
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    planner = runtime['planner']
    request = MessageEnvelope(
        project_id=context.project.project_id,
        to_agent='planner',
        from_actor='system',
        body=planner['message'],
        task_id=planner['task_id'],
        reply_to=None,
        message_type='task',
        delivery_scope=DeliveryScope.SINGLE,
        silence_on_success=True,
    )
    JobStore(PathLayout(context.project.project_root)).append(JobRecord(
        job_id=planner['job_id'], submission_id=None, agent_name='planner',
        provider='codex', request=request, status=JobStatus.RUNNING,
        terminal_decision=None, cancel_requested_at=None,
        created_at='2026-07-12T00:00:00Z', updated_at='2026-07-12T00:00:02Z',
    ))

    with pytest.raises(ValueError, match='persisted job is not terminal completed'):
        settle_task_set_closure_feedback(context, **authority)


@pytest.mark.parametrize('target', ('planner', 'frontdesk'))
def test_settlement_rejects_persisted_reply_mismatch(
    tmp_path: Path, target: str
) -> None:
    context = _context(tmp_path)
    authority, runtime_path, _backfill_path = _settlement_fixture(
        context, notification_required=target == 'frontdesk'
    )
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    transport = runtime[target]
    request = MessageEnvelope(
        project_id=context.project.project_id, to_agent=target, from_actor='system',
        body=transport['message'], task_id=transport['task_id'], reply_to=None,
        message_type='task', delivery_scope=DeliveryScope.SINGLE,
        silence_on_success=target == 'planner',
    )
    JobStore(PathLayout(context.project.project_root)).append(JobRecord(
        job_id=transport['job_id'], submission_id=None, agent_name=target,
        provider='codex', request=request, status=JobStatus.COMPLETED,
        terminal_decision={
            'terminal': True, 'status': 'completed', 'reply': 'forged persisted reply',
        },
        cancel_requested_at=None, created_at='2026-07-12T00:00:00Z',
        updated_at='2026-07-12T00:00:03Z',
    ))

    with pytest.raises(ValueError, match='persisted job reply mismatch'):
        settle_task_set_closure_feedback(context, **authority)


def test_settlement_rejects_task_set_revision_race_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    authority, _runtime_path, backfill_path = _settlement_fixture(context)
    task_set_path = backfill_path.parent / 'task-set.json'
    from cli.services import task_set_closure as service
    original = service._validate_feedback_transport

    def validate_then_race(*args, **kwargs):
        result = original(*args, **kwargs)
        record = json.loads(task_set_path.read_text(encoding='utf-8'))
        record['task_set_revision'] = 2
        record['state'] = 'running'
        record['updated_at'] = '2026-07-12T00:00:02Z'
        task_set_path.write_text(json.dumps(record), encoding='utf-8')
        return result

    monkeypatch.setattr(service, '_validate_feedback_transport', validate_then_race)

    with pytest.raises(ValueError, match='authority changed during validation'):
        settle_task_set_closure_feedback(context, **authority)
    persisted = json.loads(task_set_path.read_text(encoding='utf-8'))
    assert persisted['task_set_revision'] == 2
    assert persisted['state'] == 'running'
    assert plan_task(
        context, SimpleNamespace(action='task-show', task_id='source-intake')
    )['task']['status'] == 'decomposed'


def test_same_revision_conflicting_terminal_digest_fails_closed(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    round_path = Path(context.project.project_root) / '.ccb/runtime/loops/loop-child-a/round.json'
    record = json.loads(round_path.read_text(encoding='utf-8'))
    record['diagnostic'] = 'changed-after-closure'
    round_path.write_text(json.dumps(record, sort_keys=True) + '\n', encoding='utf-8')

    with pytest.raises(ValueError, match='conflicts with existing terminal evidence digest'):
        evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)


def test_corrupt_existing_closure_fails_closed(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    closure_path = (
        Path(context.project.project_root)
        / 'docs/plantree/plans/demo/task-sets'
        / task_set_id
        / 'closure.json'
    )
    closure = json.loads(closure_path.read_text(encoding='utf-8'))
    closure['unexpected'] = 'authority-drift'
    closure_path.write_text(json.dumps(closure, sort_keys=True) + '\n', encoding='utf-8')

    with pytest.raises(ValueError, match='invalid task-set closure schema or fields'):
        evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)


def test_revision_race_stales_old_intent_and_requires_new_child(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    task_set_id = created['task_set']['task_set_id']
    _complete(context, 'child-a', 'pass')
    first = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    _create_task(context, 'child-b')

    revised = revise_task_set_authority(
        context,
        task_set_id=task_set_id,
        expected_revision=1,
        children=[
            {'task_id': 'child-a', 'required': True},
            {'task_id': 'child-b', 'required': True},
        ],
        plan_task_fn=plan_task,
    )

    assert revised['task_set']['task_set_revision'] == 2
    with pytest.raises(ValueError, match='stale task-set revision'):
        evaluate_task_set_closure(
            context,
            task_set_id=task_set_id,
            expected_revision=1,
            plan_task_fn=plan_task,
        )
    pending = evaluate_task_set_closure(
        context,
        task_set_id=task_set_id,
        expected_revision=2,
        plan_task_fn=plan_task,
    )
    assert pending['status'] == 'pending'
    assert pending['child_task_ids'] == ['child-b']
    _complete(context, 'child-b', 'pass')
    second = evaluate_task_set_closure(context, task_set_id=task_set_id, plan_task_fn=plan_task)
    store_path = Path(context.project.project_root) / '.ccb/runtime/task-sets' / task_set_id / 'closure-intents.json'
    intents = json.loads(store_path.read_text(encoding='utf-8'))['intents']
    discovered = find_pending_task_set_closures(context)
    assert first['closure_intent']['intent_id'] != second['closure_intent']['intent_id']
    assert [intent['status'] for intent in intents] == ['stale', 'pending_planner_backfill']
    assert second['closure']['task_set_revision'] == 2
    assert discovered['pending_count'] == 1
    assert discovered['stale_count'] == 1


def test_child_revision_drift_is_system_failure_until_task_set_revision_advances(tmp_path: Path) -> None:
    context = _context(tmp_path)
    created = _create_set(context, [('child-a', True)])
    replacement = Path(context.project.project_root) / 'drafts/replacement.md'
    _write(replacement, '# changed task packet\n')
    plan_task(
        context,
        SimpleNamespace(
            action='task-artifact',
            task_id='child-a',
            artifact_kind='task_packet',
            file_path=str(replacement),
            expected_task_revision=1,
        ),
    )

    failed = evaluate_task_set_closure(
        context,
        task_set_id=created['task_set']['task_set_id'],
        plan_task_fn=plan_task,
    )

    assert failed['status'] == 'system_failure'
    assert failed['failures'][0]['reason'] == 'stale_child_revision'
