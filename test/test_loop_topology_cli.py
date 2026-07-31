from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.config_loader import load_project_config
from ccbd.reload_plan import build_reload_dry_run_plan
from cli.models import ParsedLoopTopologyCommand
from cli.parser import CliParser
from cli.phase2 import maybe_handle_phase2
import cli.services.agent_lifecycle as agent_lifecycle_module
import cli.services.loop_topology as loop_topology_module


@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch) -> None:
    """Pin runtime state under .ccb for project-anchored path assertions."""
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def _topology_agent_ids(payload: dict[str, object]) -> set[str]:
    ids = {
        str(agent.get('id') or agent.get('name') or '')
        for agent in tuple(payload.get('agents') or ())
        if isinstance(agent, dict)
    }
    for node in tuple(payload.get('nodes') or ()):
        if not isinstance(node, dict):
            continue
        ids.update(
            str(agent.get('id') or agent.get('name') or '')
            for agent in tuple(node.get('agents') or ())
            if isinstance(agent, dict)
        )
    return {name for name in ids if name}


def _write_installed_role(store_root: Path, role_id: str, *, default_agent_name: str) -> None:
    _write(
        store_root / 'installed' / role_id / 'current' / 'role.toml',
        f'''id = "{role_id}"
version = "0.1.0"

[identity]
default_agent_name = "{default_agent_name}"
''',
    )


def _project_with_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-loop-topology'
    role_store = tmp_path / 'roles'
    _write_installed_role(role_store, 'agentroles.coder', default_agent_name='coder')
    _write_installed_role(role_store, 'agentroles.code_reviewer', default_agent_name='code_reviewer')
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "main"

[windows]
main = "ccb_orchestrator:codex"

[loop.capacity]
enabled = true
max_nodes = 3
default_lifetime = "current_round"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.coder]
role = "agentroles.coder"
provider = "codex"
thinking = "high"
workspace_mode = "git-worktree"
workspace_group = "coder_pool"
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


def _project_with_long_lived_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-loop-topology-long-lived'
    role_store = tmp_path / 'roles-long-lived'
    _write_installed_role(role_store, 'agentroles.ccb_planner', default_agent_name='ccb_planner')
    monkeypatch.setenv('AGENT_ROLES_STORE', str(role_store))
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "main"

[windows]
main = "ccb_orchestrator:codex"

[loop.capacity]
enabled = true
max_nodes = 1
default_lifetime = "current_loop"
name_template = "loop-{loop_id}-{profile}-{index}"
reuse = "prefer_idle"

[loop.role_profiles.ccb_planner]
role = "agentroles.ccb_planner"
provider = "codex"
thinking = "high"
workspace_mode = "inplace"
max_instances = 1
""",
    )
    return project_root


def _project_with_workflow_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / 'repo-loop-workflow-topology'
    role_store = tmp_path / 'roles-workflow'
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
    _write(
        project_root / '.ccb' / 'ccb.config',
        """version = 2
entry_window = "ccb-user"

[windows]
ccb-user = "bootstrap:codex"

[loop.capacity]
enabled = true
max_nodes = 13
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
max_instances = 4

[loop.role_profiles.code_reviewer]
role = "agentroles.code_reviewer"
provider = "codex"
workspace_mode = "git-worktree"
max_instances = 4
""",
    )
    return project_root


def _run_phase2(argv: list[str], *, cwd: Path) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    result = maybe_handle_phase2(argv, cwd=cwd, stdout=stdout, stderr=stderr)
    payload = json.loads(stdout.getvalue()) if stdout.getvalue().strip() else {}
    return result, payload, stderr.getvalue()


def _proposal() -> dict[str, object]:
    return {
        'nodes': [
            {
                'id': 'node1',
                'agents': [
                    {
                        'id': 'loop-round1-coder-1',
                        'profile': 'coder',
                        'desired_state': 'present',
                    },
                    {
                        'id': 'loop-round1-code_reviewer-1',
                        'profile': 'code_reviewer',
                        'desired_state': 'present',
                    },
                ],
            }
        ],
        'edges': [],
        'artifacts': {},
        'gates': [],
    }


def _mount_schema_proposal() -> dict[str, object]:
    return {
        'schema': 'ccb.loop.agent_mount_topology.v1',
        'windows': [
            {
                'name': 'ccb-exec',
                'class': 'execution',
                'max_panes': 6,
                'layout_policy': 'append-or-create-window',
            }
        ],
        'agents': [
            {
                'id': 'loop-round1-coder-1',
                'profile': 'coder',
                'role': 'agentroles.coder',
                'provider': 'codex',
                'model': 'gpt-5',
                'thinking': 'high',
                'provider_profile': {'sandbox': 'workspace-write'},
                'desired_state': 'present',
                'window_name': 'ccb-exec',
                'pane_order': 0,
                'lifecycle': 'ephemeral',
                'release_policy': 'auto',
            }
        ],
        'edges': [],
        'gates': [],
    }


def _workflow_partition_proposal(*, absent_pair: int | None = None) -> dict[str, object]:
    control_agents = [
        ('wf-ccb-frontdesk', 'ccb_frontdesk', 'present'),
        ('wf-ccb-task-detailer', 'ccb_task_detailer', 'present'),
        ('wf-ccb-planner', 'ccb_planner', 'present'),
        ('wf-ccb-orchestrator', 'ccb_orchestrator', 'present'),
        ('wf-ccb-round-reviewer', 'ccb_round_reviewer', 'present'),
    ]
    nodes: list[dict[str, object]] = [
        {
            'id': 'control',
            'agents': [
                {'id': agent_id, 'profile': profile, 'desired_state': state}
                for agent_id, profile, state in control_agents
            ],
        }
    ]
    for index in range(1, 5):
        state = 'absent' if absent_pair == index else 'present'
        nodes.append(
            {
                'id': f'work-{index}',
                'agents': [
                    {'id': f'wf-coder-{index}', 'profile': 'coder', 'desired_state': state},
                    {'id': f'wf-code-reviewer-{index}', 'profile': 'code_reviewer', 'desired_state': state},
                ],
            }
        )
    return {'nodes': nodes, 'edges': []}


def _window_agents(project_root: Path) -> dict[str, tuple[str, ...]]:
    loaded = load_project_config(project_root).config
    return {str(window.name): tuple(window.agent_names) for window in loaded.windows}


def _namespace(project_id: str = 'proj-1') -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project_id,
        tmux_socket_path='/tmp/ccb-tmux.sock',
        tmux_session_name='ccb-project-test',
        namespace_epoch=1,
        ui_attachable=True,
    )


def _workflow_pair_proposal(pair_count: int) -> dict[str, object]:
    nodes: list[dict[str, object]] = [
        {
            'id': 'user-layer',
            'agents': [
                {'id': 'wf-ccb-frontdesk', 'profile': 'ccb_frontdesk', 'desired_state': 'present'},
                {'id': 'wf-ccb-task-detailer', 'profile': 'ccb_task_detailer', 'desired_state': 'present'},
            ],
        },
        {
            'id': 'plan',
            'agents': [
                {'id': 'wf-ccb-planner', 'profile': 'ccb_planner', 'desired_state': 'present'},
                {'id': 'wf-ccb-orchestrator', 'profile': 'ccb_orchestrator', 'desired_state': 'present'},
            ],
        },
    ]
    for index in range(1, pair_count + 1):
        nodes.append(
            {
                'id': f'work-{index}',
                'agents': [
                    {'id': f'wf-coder-{index}', 'profile': 'coder', 'desired_state': 'present'},
                    {'id': f'wf-code-reviewer-{index}', 'profile': 'code_reviewer', 'desired_state': 'present'},
                ],
            }
        )
    return {'nodes': nodes, 'edges': []}


def test_loop_topology_parser_supports_scriptable_json_commands() -> None:
    parser = CliParser()

    assert parser.parse(
        ['loop', 'topology', 'propose', '--loop-id', 'round1', '--from', 'graph.json', '--proposal-id', 'p1', '--json']
    ) == ParsedLoopTopologyCommand(
        project=None,
        action='propose',
        loop_id='round1',
        from_path='graph.json',
        proposal_id='p1',
        json_output=True,
    )
    assert parser.parse(
        ['loop', 'topology', 'validate', '--loop-id', 'round1', '--proposal', 'p1', '--json']
    ) == ParsedLoopTopologyCommand(project=None, action='validate', loop_id='round1', proposal_id='p1', json_output=True)
    assert parser.parse(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'p1', '--apply', '--json']
    ) == ParsedLoopTopologyCommand(
        project=None,
        action='commit',
        loop_id='round1',
        proposal_id='p1',
        apply=True,
        json_output=True,
    )
    assert parser.parse(
        ['loop', 'topology', 'reconcile', '--loop-id', 'round1', '--json']
    ) == ParsedLoopTopologyCommand(project=None, action='reconcile', loop_id='round1', json_output=True)
    assert parser.parse(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--policy', 'auto', '--json']
    ) == ParsedLoopTopologyCommand(project=None, action='release', loop_id='round1', policy='auto', json_output=True)


def test_loop_topology_accepts_mount_schema_windows_agents_and_provider_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'mount-topology.json'
    proposal = _mount_schema_proposal()
    for key in ('edges', 'artifacts', 'gates'):
        proposal.pop(key, None)
    _write_json(proposal_path, proposal)

    result, proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'mount1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert proposed['validation']['window_count'] == 1
    assert proposed['validation']['edge_count'] == 0
    normalized_proposal = json.loads(Path(proposed['proposal_path']).read_text(encoding='utf-8'))
    assert 'edges' not in normalized_proposal
    assert 'artifacts' not in normalized_proposal
    assert 'gates' not in normalized_proposal

    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'mount1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    desired_path = Path(committed['desired_path'])
    assert desired_path.name == 'agent_mount_topology.desired.json'
    desired = json.loads(desired_path.read_text(encoding='utf-8'))
    assert desired['schema'] == 'ccb.loop.agent_mount_topology.v1'
    assert desired['record_type'] == 'ccb_loop_agent_mount_topology_desired'
    assert desired['windows'][0]['name'] == 'ccb-exec'
    assert desired['agents'][0]['provider'] == 'codex'
    assert 'edges' not in desired
    assert 'artifacts' not in desired
    assert 'gates' not in desired
    assert 'edges' not in committed['reconcile']['observed']
    observed_agent = committed['reconcile']['observed']['agents'][0]
    assert observed_agent['provider_profile'] == {'sandbox': 'workspace-write'}
    assert observed_agent['lifecycle'] == 'ephemeral'
    assert observed_agent['lifetime'] == 'current_round'
    assert observed_agent['release_policy'] == 'auto'
    assert observed_agent['pane_order'] == 0


def test_loop_topology_mount_schema_rejects_dispatch_dsl_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    cases = [
        (
            'edge',
            {
                **_mount_schema_proposal(),
                'edges': [{'id': 'ask-coder', 'from': 'user', 'to': 'loop-round1-coder-1', 'type': 'ask'}],
            },
            'mount topology does not accept communication or dispatch edges',
        ),
        (
            'artifact',
            {
                **_mount_schema_proposal(),
                'artifacts': {'round': 'round.md'},
            },
            'mount topology does not accept topology dispatch artifacts',
        ),
        (
            'gate',
            {
                **_mount_schema_proposal(),
                'gates': [{'id': 'round-complete', 'type': 'all_edges_complete'}],
            },
            'mount topology does not accept topology dispatch gates',
        ),
    ]
    for proposal_id, proposal, expected in cases:
        proposal_path = project_root / f'{proposal_id}.json'
        _write_json(proposal_path, proposal)

        result, payload, stderr = _run_phase2(
            [
                'loop',
                'topology',
                'propose',
                '--loop-id',
                'round1',
                '--from',
                str(proposal_path),
                '--proposal-id',
                proposal_id,
                '--json',
            ],
            cwd=project_root,
        )

        assert result == 1
        assert payload == {}
        assert expected in stderr


def test_loop_topology_status_reads_legacy_agent_topology_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    loop_dir = project_root / '.ccb' / 'runtime' / 'loops' / 'round1'
    desired = {
        'schema': 'ccb.loop.agent_topology.v1',
        'record_type': 'ccb_loop_agent_topology_desired',
        'topology_status': 'committed',
        'project_id': 'test',
        'project_root': str(project_root),
        'loop_id': 'round1',
        'revision': 4,
        'nodes': _proposal()['nodes'],
        'edges': [],
        'release_policy': {'policy': 'auto', 'idle_only': True},
    }
    observed = {
        'schema': 'ccb.loop.agent_topology.observed.v1',
        'record_type': 'ccb_loop_agent_topology_observed',
        'last_reconcile_status': 'reconciled',
        'project_id': 'test',
        'project_root': str(project_root),
        'loop_id': 'round1',
        'desired_revision': 4,
        'agents': [
            {
                'id': 'loop-round1-coder-1',
                'profile': 'coder',
                'desired_state': 'present',
                'observed_state': 'present',
            },
            {
                'id': 'loop-round1-code_reviewer-1',
                'profile': 'code_reviewer',
                'desired_state': 'present',
                'observed_state': 'present',
            },
        ],
        'drift': {'mismatched_agents': []},
    }
    _write_json(loop_dir / 'agent_topology.desired.json', desired)
    _write_json(loop_dir / 'agent_topology.observed.json', observed)

    result, status, stderr = _run_phase2(
        ['loop', 'topology', 'status', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert status['loop_topology_status'] == 'ready'
    assert status['desired_path'].endswith('agent_topology.desired.json')
    assert status['observed_path'].endswith('agent_topology.observed.json')
    assert status['desired']['revision'] == 4
    assert status['observed']['revision'] == 4


def test_loop_topology_commit_apply_and_release_manage_dynamic_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())

    result, proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert proposed['loop_topology_status'] == 'proposed'
    assert proposed['validation']['profile_counts'] == {'code_reviewer': 1, 'coder': 1}
    assert Path(proposed['proposal_path']).is_file()

    result, valid, stderr = _run_phase2(
        ['loop', 'topology', 'validate', '--loop-id', 'round1', '--proposal', 'proposal1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert valid['validation']['topology_validation_status'] == 'valid'

    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['loop_topology_status'] == 'committed'
    reconcile = committed['reconcile']
    assert reconcile['loop_topology_status'] == 'reconciled'
    assert reconcile['agent_count'] == 2
    assert Path(committed['desired_path']).is_file()
    assert Path(reconcile['observed_path']).is_file()
    assert {action['action'] for action in reconcile['actions']} >= {'add', 'reflow'}

    loaded = load_project_config(project_root).config
    assert set(loaded.agents) >= {'loop-round1-coder-1', 'loop-round1-code_reviewer-1'}
    assert ('loop-round1-coder-1', 'loop-round1-code_reviewer-1') in {
        tuple(window.agent_names) for window in loaded.windows
    }

    result, status, stderr = _run_phase2(
        ['loop', 'topology', 'status', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert status['loop_topology_status'] == 'ready'
    assert status['desired']['revision'] == 1
    assert status['observed']['revision'] == 1

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert released['loop_topology_status'] == 'released'
    assert released['released_count'] == 2
    assert released['released_agents'] == ['loop-round1-code_reviewer-1', 'loop-round1-coder-1']
    assert released['retained_count'] == 0
    desired_after_release = json.loads(Path(str(released['desired_path'])).read_text(encoding='utf-8'))
    observed_after_release = json.loads(Path(str(released['observed_path'])).read_text(encoding='utf-8'))
    assert _topology_agent_ids(desired_after_release) == set()
    assert [agent['id'] for agent in observed_after_release['agents']] == []
    assert observed_after_release['released_agents'] == released['released_agents']
    loaded_after_release = load_project_config(project_root).config
    assert 'loop-round1-coder-1' not in loaded_after_release.agents
    assert 'loop-round1-code_reviewer-1' not in loaded_after_release.agents


def test_loop_topology_defaults_workflow_roles_to_window_partitions_and_reflows_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'workflow-topology.json'
    _write_json(proposal_path, _workflow_partition_proposal())

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
            'workflow1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'workflow1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'
    windows = _window_agents(project_root)
    assert list(windows)[:4] == ['ccb-user', 'ccb-plan', 'ccb-exec', 'ccb-exec-2']
    assert windows['ccb-user'] == ('bootstrap', 'wf-ccb-frontdesk', 'wf-ccb-task-detailer')
    assert windows['ccb-plan'] == ('wf-ccb-planner', 'wf-ccb-orchestrator', 'wf-ccb-round-reviewer')
    assert windows['ccb-exec'] == (
        'wf-coder-1',
        'wf-code-reviewer-1',
        'wf-coder-2',
        'wf-code-reviewer-2',
        'wf-coder-3',
        'wf-code-reviewer-3',
    )
    assert windows['ccb-exec-2'] == ('wf-coder-4', 'wf-code-reviewer-4')
    observed_windows = {
        str(agent['id']): str(agent['window_name'])
        for agent in committed['reconcile']['observed']['agents']
    }
    assert observed_windows['wf-ccb-frontdesk'] == 'ccb-user'
    assert observed_windows['wf-ccb-task-detailer'] == 'ccb-user'
    assert observed_windows['wf-ccb-planner'] == 'ccb-plan'
    assert observed_windows['wf-ccb-orchestrator'] == 'ccb-plan'
    assert observed_windows['wf-ccb-round-reviewer'] == 'ccb-plan'
    assert observed_windows['wf-coder-4'] == 'ccb-exec-2'
    assert observed_windows['wf-code-reviewer-4'] == 'ccb-exec-2'
    observed_states = {
        str(agent['id']): str(agent['desired_state'])
        for agent in committed['reconcile']['observed']['agents']
    }
    assert all(state == 'present' for state in observed_states.values())

    compact_path = project_root / 'workflow-topology-compact.json'
    _write_json(compact_path, _workflow_partition_proposal(absent_pair=2))
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(compact_path),
            '--proposal-id',
            'workflow2',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, compacted, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'workflow2', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert compacted['reconcile']['loop_topology_status'] == 'reconciled'
    action_pairs = {(action['action'], action.get('agent')) for action in compacted['reconcile']['actions']}
    assert ('release', 'wf-coder-2') in action_pairs
    assert ('release', 'wf-code-reviewer-2') in action_pairs
    assert ('move', 'wf-coder-4') in action_pairs
    assert ('move', 'wf-code-reviewer-4') in action_pairs
    windows_after = _window_agents(project_root)
    assert 'ccb-exec-2' not in windows_after
    assert windows_after['ccb-exec'] == (
        'wf-coder-1',
        'wf-code-reviewer-1',
        'wf-coder-3',
        'wf-code-reviewer-3',
        'wf-coder-4',
        'wf-code-reviewer-4',
    )


def test_loop_topology_batches_missing_workflow_agents_before_mounted_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'workflow-topology.json'
    _write_json(proposal_path, _workflow_partition_proposal())
    apply_windows: list[dict[str, tuple[str, ...]]] = []
    add_commands: list[SimpleNamespace] = []

    original_add_lifecycle_agents = loop_topology_module.add_lifecycle_agents

    def capture_add_lifecycle_agents(context, commands, *, action: str):
        add_commands.extend(commands)
        return original_add_lifecycle_agents(context, commands, action=action)

    def fake_apply(context, *, action: str) -> dict[str, object]:
        assert action == 'topology-agent-add-batch'
        windows = _window_agents(project_root)
        apply_windows.append(windows)
        loaded = load_project_config(project_root).config
        return {
            'apply_status': 'applied',
            'action': action,
            'plan_class': 'add_window',
            'namespace_agent_panes': {agent_name: f'%{index}' for index, agent_name in enumerate(loaded.agents, start=1)},
        }

    monkeypatch.setattr(loop_topology_module, 'add_lifecycle_agents', capture_add_lifecycle_agents)
    monkeypatch.setattr(agent_lifecycle_module, '_apply_reload_if_mounted', fake_apply)

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
            'workflow1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'workflow1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'
    assert add_commands
    assert {command.visibility for command in add_commands} == {'visible'}
    command_windows = {str(command.agent_name): str(command.window_name) for command in add_commands}
    assert command_windows['wf-ccb-frontdesk'] == 'ccb-user'
    assert command_windows['wf-ccb-task-detailer'] == 'ccb-user'
    assert command_windows['wf-ccb-planner'] == 'ccb-plan'
    assert command_windows['wf-ccb-orchestrator'] == 'ccb-plan'
    assert command_windows['wf-ccb-round-reviewer'] == 'ccb-plan'
    assert command_windows['wf-coder-1'] == 'ccb-exec'
    assert command_windows['wf-code-reviewer-3'] == 'ccb-exec'
    assert command_windows['wf-coder-4'] == 'ccb-exec-2'
    assert command_windows['wf-code-reviewer-4'] == 'ccb-exec-2'
    assert len(apply_windows) == 1
    assert apply_windows[0]['ccb-user'] == ('bootstrap', 'wf-ccb-frontdesk', 'wf-ccb-task-detailer')
    assert apply_windows[0]['ccb-plan'] == ('wf-ccb-planner', 'wf-ccb-orchestrator', 'wf-ccb-round-reviewer')
    assert apply_windows[0]['ccb-exec'] == (
        'wf-coder-1',
        'wf-code-reviewer-1',
        'wf-coder-2',
        'wf-code-reviewer-2',
        'wf-coder-3',
        'wf-code-reviewer-3',
    )
    assert apply_windows[0]['ccb-exec-2'] == ('wf-coder-4', 'wf-code-reviewer-4')


def test_loop_topology_passes_node_workspace_group_to_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal = _proposal()
    proposal['nodes'][0]['agents'][0]['workspace_group'] = 'coder_pool'  # type: ignore[index]
    proposal['nodes'][0]['agents'][1]['workspace_group'] = 'review_pool'  # type: ignore[index]
    proposal_path = project_root / 'workspace-groups.json'
    _write_json(proposal_path, proposal)
    commands: list[SimpleNamespace] = []
    original_add = loop_topology_module.add_lifecycle_agents

    def capture(context, staged, *, action: str):
        commands.extend(staged)
        return original_add(context, staged, action=action)

    monkeypatch.setattr(loop_topology_module, 'add_lifecycle_agents', capture)
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'workspace-groups',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'workspace-groups', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'
    assert {command.workspace_group for command in commands} == {'coder_pool', 'review_pool'}
    records = {
        name: json.loads(
            (project_root / '.ccb' / 'runtime' / 'agents' / name / 'lifecycle.json').read_text(encoding='utf-8')
        )
        for name in ('loop-round1-coder-1', 'loop-round1-code_reviewer-1')
    }
    assert records['loop-round1-coder-1']['workspace_group'] == 'coder_pool'
    assert records['loop-round1-code_reviewer-1']['workspace_group'] == 'review_pool'


def test_loop_topology_execution_window_growth_remains_append_patchable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    first_path = project_root / 'workflow-one-pair.json'
    second_path = project_root / 'workflow-two-pairs.json'
    _write_json(first_path, _workflow_pair_proposal(1))
    _write_json(second_path, _workflow_pair_proposal(2))

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(first_path),
            '--proposal-id',
            'one-pair',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'one-pair', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    current = load_project_config(project_root).config

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(second_path),
            '--proposal-id',
            'two-pairs',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'two-pairs', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    updated = load_project_config(project_root).config

    plan = build_reload_dry_run_plan(current, updated, project_id='proj-1', current_namespace=_namespace())

    assert plan['plan_class'] == 'add_agent'
    assert plan['namespace_patch_plan']['status'] == 'planned'
    assert [
        step['agent']
        for step in plan['namespace_patch_plan']['steps']
        if step['action'] == 'create_agent_pane' and step['window'] == 'ccb-exec'
    ] == ['wf-coder-2', 'wf-code-reviewer-2']


def test_loop_topology_compacts_when_execution_agents_are_omitted_from_next_desired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    first_path = project_root / 'workflow-two-pairs.json'
    second_path = project_root / 'workflow-one-pair.json'
    _write_json(first_path, _workflow_pair_proposal(2))
    _write_json(second_path, _workflow_pair_proposal(1))

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(first_path),
            '--proposal-id',
            'two-pairs',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'two-pairs', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'wf1',
            '--from',
            str(second_path),
            '--proposal-id',
            'one-pair',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'wf1', '--proposal', 'one-pair', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    reconcile = committed['reconcile']
    assert reconcile['loop_topology_status'] == 'reconciled'
    assert reconcile['released_count'] == 2
    assert reconcile['released_agents'] == ['wf-code-reviewer-2', 'wf-coder-2']
    action_pairs = {(action['action'], action.get('agent')) for action in reconcile['actions']}
    assert ('release', 'wf-coder-2') in action_pairs
    assert ('release', 'wf-code-reviewer-2') in action_pairs
    windows = _window_agents(project_root)
    assert windows['ccb-exec'] == ('wf-coder-1', 'wf-code-reviewer-1')
    assert 'wf-coder-2' not in load_project_config(project_root).config.agents
    assert 'wf-code-reviewer-2' not in load_project_config(project_root).config.agents


def test_loop_topology_reconcile_moves_parks_reflows_and_releases_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    first_path = project_root / 'graph-first.json'
    _write_json(first_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(first_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    second = {
        'nodes': [
            {
                'id': 'node2',
                'agents': [
                    {
                        'id': 'loop-round1-coder-1',
                        'profile': 'coder',
                        'desired_state': 'parked',
                        'window_name': 'ccb-exec-2',
                    },
                    {
                        'id': 'loop-round1-code_reviewer-1',
                        'profile': 'code_reviewer',
                        'desired_state': 'absent',
                    },
                ],
            }
        ],
        'edges': [],
    }
    second_path = project_root / 'graph-second.json'
    _write_json(second_path, second)

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(second_path),
            '--proposal-id',
            'proposal2',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal2', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    reconcile = committed['reconcile']
    assert reconcile['loop_topology_status'] == 'reconciled'
    action_pairs = {(action['action'], action.get('agent')) for action in reconcile['actions']}
    assert ('move', 'loop-round1-coder-1') in action_pairs
    assert ('park', 'loop-round1-coder-1') in action_pairs
    assert ('release', 'loop-round1-code_reviewer-1') in action_pairs
    assert any(action['action'] == 'reflow' and action['window_name'] == 'ccb-exec-2' for action in reconcile['actions'])

    coder_state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-coder-1' / 'lifecycle.json').read_text(
            encoding='utf-8'
        )
    )
    reviewer_state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-code_reviewer-1' / 'lifecycle.json').read_text(
            encoding='utf-8'
        )
    )
    assert coder_state['lifecycle_state'] == 'parked'
    assert coder_state['resolved_window_name'] == 'ccb-exec-2'
    assert reviewer_state['lifecycle_state'] == 'unloaded'


def test_loop_topology_reconcile_is_idempotent_for_existing_desired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, reconciled, stderr = _run_phase2(
        ['loop', 'topology', 'reconcile', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert reconciled['loop_topology_status'] == 'reconciled'
    assert {action['action'] for action in reconciled['actions']} <= {'noop', 'reflow'}


def test_loop_topology_absent_uses_auto_release_policy_for_long_lived_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_long_lived_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'ccb-planner-present.json'
    _write_json(
        proposal_path,
        {
            'nodes': [
                {
                    'id': 'node1',
                    'agents': [
                        {
                            'id': 'loop-round1-ccb_planner-1',
                            'profile': 'ccb_planner',
                            'desired_state': 'present',
                        }
                    ],
                }
            ],
            'edges': [],
        },
    )
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    absent_path = project_root / 'ccb-planner-absent.json'
    _write_json(
        absent_path,
        {
            'nodes': [
                {
                    'id': 'node1',
                    'agents': [
                        {
                            'id': 'loop-round1-ccb_planner-1',
                            'profile': 'ccb_planner',
                            'desired_state': 'absent',
                        }
                    ],
                }
            ],
            'edges': [],
        },
    )
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(absent_path),
            '--proposal-id',
            'proposal2',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal2', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'
    state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-ccb_planner-1' / 'lifecycle.json').read_text(
            encoding='utf-8'
        )
    )
    assert state['lifecycle_state'] == 'parked'
    assert committed['reconcile']['observed']['drift']['mismatched_agents'] == []


def test_loop_topology_release_retains_busy_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    monkeypatch.setattr(
        agent_lifecycle_module,
        'ping_local_state',
        lambda _context: SimpleNamespace(mount_state='mounted', socket_connectable=True),
    )

    class BusyRuntimeStore:
        def __init__(self, _paths) -> None:
            pass

        def load_best_effort(self, name: str):
            if name == 'loop-round1-coder-1':
                return SimpleNamespace(state='busy', queue_depth=0)
            return SimpleNamespace(state='idle', queue_depth=0)

    monkeypatch.setattr(agent_lifecycle_module, 'AgentRuntimeStore', BusyRuntimeStore)
    monkeypatch.setattr(
        agent_lifecycle_module,
        'reload_config',
        lambda _context, _command: {'status': 'ok'},
    )
    monkeypatch.setattr(
        agent_lifecycle_module,
        'reload_apply_summary',
        lambda _payload, *, action: {'apply_status': 'applied', 'action': action},
    )

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert released['loop_topology_status'] == 'retained_busy'
    assert released['retained_count'] == 1
    assert released['released_agents'] == ['loop-round1-code_reviewer-1']
    assert released['retained_agents'] == ['loop-round1-coder-1']
    assert released['retain_reasons'] == {'loop-round1-coder-1': 'runtime_state=busy'}
    release_actions = {
        str(action.get('agent')): action
        for action in released['actions']
        if action.get('action') == 'release'
    }
    assert release_actions['loop-round1-coder-1']['status'] == 'retained_busy'
    assert release_actions['loop-round1-coder-1']['retain_reason'] == 'runtime_state=busy'
    desired_after_release = json.loads(Path(str(released['desired_path'])).read_text(encoding='utf-8'))
    observed_after_release = json.loads(Path(str(released['observed_path'])).read_text(encoding='utf-8'))
    assert _topology_agent_ids(desired_after_release) == {'loop-round1-coder-1'}
    assert [agent['id'] for agent in observed_after_release['agents']] == ['loop-round1-coder-1']
    assert observed_after_release['released_agents'] == ['loop-round1-code_reviewer-1']
    assert observed_after_release['retained_agents'] == ['loop-round1-coder-1']
    coder_state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-coder-1' / 'lifecycle.json').read_text(
            encoding='utf-8'
        )
    )
    reviewer_state = json.loads(
        (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-code_reviewer-1' / 'lifecycle.json').read_text(
            encoding='utf-8'
        )
    )
    assert coder_state['agent_lifecycle_status'] == 'retained_busy'
    assert coder_state['lifecycle_state'] == 'visible'
    assert reviewer_state['lifecycle_state'] == 'unloaded'


def test_loop_topology_release_drains_residents_and_unloads_immaculate_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_workflow_topology(tmp_path, monkeypatch)
    proposal_a = {
        'nodes': [
            {
                'id': 'user-boundary',
                'agents': [
                    {
                        'id': 'p6bl0b-frontdesk',
                        'profile': 'ccb_frontdesk',
                        'desired_state': 'present',
                        'release_policy': 'auto',
                    },
                    {
                        'id': 'p6bl0b-detailer',
                        'profile': 'ccb_task_detailer',
                        'desired_state': 'present',
                        'release_policy': 'auto',
                    },
                ],
            },
            {
                'id': 'planning',
                'agents': [
                    {
                        'id': 'p6bl0b-planner',
                        'profile': 'ccb_planner',
                        'desired_state': 'present',
                        'release_policy': 'auto',
                    },
                    {
                        'id': 'p6bl0b-orchestrator',
                        'profile': 'ccb_orchestrator',
                        'desired_state': 'present',
                        'release_policy': 'auto',
                    },
                ],
            }
        ],
        'release_policy': {'policy': 'auto', 'idle_only': True},
    }
    proposal_b = {
        'nodes': [
            {
                'id': 'planning',
                'agents': [
                    {
                        'id': 'p6bl0c-orchestrator',
                        'profile': 'ccb_orchestrator',
                        'desired_state': 'present',
                        'release_policy': 'auto',
                    }
                ],
            }
        ],
        'release_policy': {'policy': 'auto', 'idle_only': True},
    }
    proposal_a_path = project_root / 'proposal-a.json'
    proposal_b_path = project_root / 'proposal-b.json'
    _write_json(proposal_a_path, proposal_a)
    _write_json(proposal_b_path, proposal_b)

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'p6bl0a',
            '--from',
            str(proposal_a_path),
            '--proposal-id',
            'p6bl0a-plan',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'p6bl0a', '--proposal', 'p6bl0a-plan', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'p6bl0a', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert released['loop_topology_status'] == 'released'
    assert released['released_count'] == 2
    assert released['released_agents'] == ['p6bl0b-detailer', 'p6bl0b-orchestrator']
    expected_drained = ['p6bl0b-frontdesk', 'p6bl0b-planner']
    assert released['drained_count'] == 2
    assert released['drained_agents'] == expected_drained
    assert released['drain_reasons'] == {name: 'parked_after_release' for name in expected_drained}
    observed_after_release = json.loads(Path(str(released['observed_path'])).read_text(encoding='utf-8'))
    desired_after_release = json.loads(Path(str(released['desired_path'])).read_text(encoding='utf-8'))
    assert observed_after_release['last_reconcile_status'] == 'reconciled'
    assert observed_after_release['drained_agents'] == expected_drained
    assert _topology_agent_ids(observed_after_release) == set()
    assert _topology_agent_ids(desired_after_release) == set()
    assert 'edges' not in desired_after_release
    assert 'gates' not in desired_after_release
    assert 'artifacts' not in desired_after_release
    assert not (project_root / '.ccb' / 'runtime' / 'loops' / 'p6bl0a' / 'topology_dispatch.json').exists()
    for agent_name in expected_drained:
        retained_state = json.loads(
            (
                project_root
                / '.ccb'
                / 'runtime'
                / 'agents'
                / agent_name
                / 'lifecycle.json'
            ).read_text(encoding='utf-8')
        )
        assert retained_state['lifecycle_state'] == 'parked'
        assert retained_state['dispatch_disabled'] is True
    for agent_name in ('p6bl0b-detailer', 'p6bl0b-orchestrator'):
        released_state = json.loads(
            (
                project_root
                / '.ccb'
                / 'runtime'
                / 'agents'
                / agent_name
                / 'lifecycle.json'
            ).read_text(encoding='utf-8')
        )
        assert released_state['lifecycle_state'] == 'unloaded'
        assert released_state['role_class'] == 'short_lived_execution'
    result, status, stderr = _run_phase2(
        ['loop', 'topology', 'status', '--loop-id', 'p6bl0a', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert status['loop_topology_status'] == 'released'

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'p6bl0c',
            '--from',
            str(proposal_b_path),
            '--proposal-id',
            'p6bl0c-plan',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed_b, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'p6bl0c', '--proposal', 'p6bl0c-plan', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert committed_b['loop_topology_status'] == 'committed'


def test_loop_topology_release_keeps_other_loop_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    first = _proposal()
    second = {
        'nodes': [
            {
                'id': 'node1',
                'agents': [
                    {
                        'id': 'loop-round2-coder-1',
                        'profile': 'coder',
                        'desired_state': 'present',
                    }
                ],
            }
        ],
        'edges': [],
    }
    for loop_id, proposal_id, payload in (('round1', 'proposal1', first), ('round2', 'proposal2', second)):
        proposal_path = project_root / f'{proposal_id}.json'
        _write_json(proposal_path, payload)
        result, _proposed, stderr = _run_phase2(
            [
                'loop',
                'topology',
                'propose',
                '--loop-id',
                loop_id,
                '--from',
                str(proposal_path),
                '--proposal-id',
                proposal_id,
                '--json',
            ],
            cwd=project_root,
        )
        assert result == 0, stderr
        result, _committed, stderr = _run_phase2(
            ['loop', 'topology', 'commit', '--loop-id', loop_id, '--proposal', proposal_id, '--apply', '--json'],
            cwd=project_root,
        )
        assert result == 0, stderr

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert released['loop_topology_status'] == 'released'
    loaded = load_project_config(project_root).config
    assert 'loop-round1-coder-1' not in loaded.agents
    assert 'loop-round1-code_reviewer-1' not in loaded.agents
    assert 'loop-round2-coder-1' in loaded.agents


def test_loop_topology_release_batches_dynamic_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    original_agent_lifecycle = loop_topology_module.agent_lifecycle
    release_calls: list[tuple[str, ...]] = []

    def batch_only_agent_lifecycle(context, command):
        if getattr(command, 'action', None) != 'release':
            return original_agent_lifecycle(context, command)
        names = tuple(str(item) for item in tuple(getattr(command, 'agent_names', ()) or ()))
        assert names == ('loop-round1-code_reviewer-1', 'loop-round1-coder-1')
        release_calls.append(names)
        records = []
        for name in names:
            path = project_root / '.ccb' / 'runtime' / 'agents' / name / 'lifecycle.json'
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['agent_lifecycle_status'] = 'removed'
            payload['lifecycle_state'] = 'unloaded'
            payload['visibility_state'] = 'unloaded'
            payload['dispatch_disabled'] = False
            _write_json(path, payload)
            records.append({'agent': name, 'agent_lifecycle_status': 'removed', 'retained_busy': False})
        return {
            'agent_lifecycle_status': 'removed',
            'action': 'release',
            'requested_policy': 'auto',
            'removed_agents': list(names),
            'agents': records,
            'apply': {'apply_status': 'applied'},
        }

    monkeypatch.setattr(loop_topology_module, 'agent_lifecycle', batch_only_agent_lifecycle)

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert release_calls == [('loop-round1-code_reviewer-1', 'loop-round1-coder-1')]
    assert released['loop_topology_status'] == 'released'
    assert released['released_count'] == 2
    assert released['released_agents'] == ['loop-round1-code_reviewer-1', 'loop-round1-coder-1']

    result, reconciled, stderr = _run_phase2(
        ['loop', 'topology', 'reconcile', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert release_calls == [('loop-round1-code_reviewer-1', 'loop-round1-coder-1')]
    assert reconciled['released_count'] == 0
    assert reconciled['released_agents'] == []
    assert reconciled['agent_count'] == 0


def test_loop_topology_releases_obsolete_wave_before_adding_replacement_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    first_path = project_root / 'graph-first.json'
    _write_json(first_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(first_path),
            '--proposal-id',
            'proposal-first',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal-first', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    replacement = json.loads(json.dumps(_proposal()))
    replacement_agents = replacement['nodes'][0]['agents']
    replacement_agents[0]['id'] = 'loop-round1-coder-2'
    replacement_agents[1]['id'] = 'loop-round1-code_reviewer-2'
    second_path = project_root / 'graph-second.json'
    _write_json(second_path, replacement)

    calls: list[str] = []
    original_release_agents = loop_topology_module._release_agents
    original_add_agents = loop_topology_module._add_agents

    def recording_release(context, names, *, policy: str):
        calls.append('release')
        return original_release_agents(context, names, policy=policy)

    def recording_add(context, agents):
        calls.append('add')
        return original_add_agents(context, agents)

    monkeypatch.setattr(loop_topology_module, '_release_agents', recording_release)
    monkeypatch.setattr(loop_topology_module, '_add_agents', recording_add)

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(second_path),
            '--proposal-id',
            'proposal-second',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal-second', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert calls == ['release', 'add']
    action_kinds = [str(action.get('action')) for action in committed['reconcile']['actions']]
    assert action_kinds[:2] == ['release', 'release']
    assert action_kinds[2:] == ['add', 'add', 'reflow']
    desired = json.loads(Path(str(committed['reconcile']['desired_path'])).read_text(encoding='utf-8'))
    assert _topology_agent_ids(desired) == {
        'loop-round1-coder-2',
        'loop-round1-code_reviewer-2',
    }

    blocked_replacement = json.loads(json.dumps(_proposal()))
    blocked_agents = blocked_replacement['nodes'][0]['agents']
    blocked_agents[0]['id'] = 'loop-round1-coder-3'
    blocked_agents[1]['id'] = 'loop-round1-code_reviewer-3'
    blocked_path = project_root / 'graph-blocked.json'
    _write_json(blocked_path, blocked_replacement)

    def retain_busy(_context, names, *, policy: str):
        return [
            {
                'action': 'release',
                'agent': name,
                'status': 'retained_busy',
                'policy': policy,
                'reason': 'runtime_state=busy',
                'retain_reason': 'runtime_state=busy',
                'apply_status': 'not_applied',
            }
            for name in names
        ]

    def forbid_add(_context, _agents):
        raise AssertionError('replacement agents must not be added while obsolete agents are retained busy')

    monkeypatch.setattr(loop_topology_module, '_release_agents', retain_busy)
    monkeypatch.setattr(loop_topology_module, '_add_agents', forbid_add)
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(blocked_path),
            '--proposal-id',
            'proposal-blocked',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, blocked, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal-blocked', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert blocked['reconcile']['loop_topology_status'] == 'retained_busy'
    deferred = [
        action
        for action in blocked['reconcile']['actions']
        if action.get('status') == 'deferred_retained_busy'
    ]
    assert {action['agent'] for action in deferred} == {
        'loop-round1-coder-3',
        'loop-round1-code_reviewer-3',
    }


def test_loop_topology_commit_rejects_stale_base_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    first_path = project_root / 'graph-first.json'
    _write_json(first_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(first_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    stale = _proposal()
    stale['base_revision'] = 0
    stale_path = project_root / 'graph-stale.json'
    _write_json(stale_path, stale)
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(stale_path),
            '--proposal-id',
            'stale1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, payload, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'stale1', '--json'],
        cwd=project_root,
    )

    assert result == 1
    assert payload == {}
    assert 'does not match desired revision=1' in stderr


def test_loop_topology_rejects_unknown_profile_capacity_overflow_and_duplicate_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    cases = [
        (
            'unknown-profile',
            {
                'nodes': [{'id': 'node1', 'agents': [{'id': 'loop-round1-search-1', 'profile': 'search'}]}],
                'edges': [],
            },
            'requires explicit window_name/window_class',
        ),
        (
            'capacity-overflow',
            {
                'nodes': [
                    {
                        'id': 'node1',
                        'agents': [
                            {'id': 'loop-round1-coder-1', 'profile': 'coder'},
                            {'id': 'loop-round1-coder-2', 'profile': 'coder'},
                            {'id': 'loop-round1-coder-3', 'profile': 'coder'},
                        ],
                    }
                ],
                'edges': [],
            },
            'exceeds max_instances=2',
        ),
        (
            'duplicate-node',
            {
                'nodes': [
                    {'id': 'node1', 'agents': [{'id': 'loop-round1-coder-1', 'profile': 'coder'}]},
                    {'id': 'node1', 'agents': [{'id': 'loop-round1-code_reviewer-1', 'profile': 'code_reviewer'}]},
                ],
                'edges': [],
            },
            'duplicate topology node id',
        ),
    ]
    for proposal_id, payload, expected_error in cases:
        proposal_path = project_root / f'{proposal_id}.json'
        _write_json(proposal_path, payload)
        result, parsed, stderr = _run_phase2(
            [
                'loop',
                'topology',
                'propose',
                '--loop-id',
                'round1',
                '--from',
                str(proposal_path),
                '--proposal-id',
                proposal_id,
                '--json',
            ],
            cwd=project_root,
        )
        assert result == 1
        assert parsed == {}
        assert expected_error in stderr


def test_loop_topology_can_reactivate_released_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    for proposal_id in ('proposal1',):
        result, _proposed, stderr = _run_phase2(
            [
                'loop',
                'topology',
                'propose',
                '--loop-id',
                'round1',
                '--from',
                str(proposal_path),
                '--proposal-id',
                proposal_id,
                '--json',
            ],
            cwd=project_root,
        )
        assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal2',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal2', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert committed['reconcile']['loop_topology_status'] == 'reconciled'
    assert any(action['action'] == 'add' for action in committed['reconcile']['actions'])
    loaded = load_project_config(project_root).config
    assert set(loaded.agents) >= {'loop-round1-coder-1', 'loop-round1-code_reviewer-1'}


def test_loop_topology_missing_and_empty_release_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)

    result, missing, stderr = _run_phase2(
        ['loop', 'topology', 'reconcile', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert missing['loop_topology_status'] == 'missing'

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    assert released['loop_topology_status'] == 'released'
    assert released['agent_count'] == 0


def test_loop_topology_release_retries_transient_failure_and_clears_dynamic_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr

    original_release_agents = loop_topology_module._release_agents
    call_count = 0

    def flaky_release_agents(context, commands, *, policy: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError('timed out')
        return original_release_agents(context, commands, policy=policy)

    monkeypatch.setattr(loop_topology_module, '_release_agents', flaky_release_agents)

    result, released, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert call_count == 2
    assert released['loop_topology_status'] == 'released'
    assert released['released_count'] == 2
    assert released['retained_count'] == 0
    assert released['observed']['agents'] == []
    observed_path = Path(released['observed_path'])
    observed = json.loads(observed_path.read_text(encoding='utf-8'))
    assert observed['last_reconcile_status'] == 'reconciled'
    assert observed['agents'] == []
    assert observed['released_count'] == 2
    assert observed['retained_count'] == 0
    loaded = load_project_config(project_root, include_loop_overlays=True).config
    assert 'loop-round1-coder-1' not in loaded.agents
    assert 'loop-round1-code_reviewer-1' not in loaded.agents


def test_loop_topology_release_replay_is_idempotent_after_full_unload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, first, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    first_desired = json.loads(Path(first['desired_path']).read_text(encoding='utf-8'))

    result, replay, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    replay_desired = json.loads(Path(replay['desired_path']).read_text(encoding='utf-8'))
    assert replay['loop_topology_status'] == 'released'
    assert replay['released_count'] == 0
    assert replay['retained_count'] == 0
    assert replay['agent_count'] == 0
    assert replay_desired['revision'] == first_desired['revision']


def test_loop_topology_release_persistent_failure_stays_failed_and_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr
    result, _committed, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )
    assert result == 0, stderr
    calls = 0

    def always_fail(_context, _names, *, policy: str):
        nonlocal calls
        calls += 1
        raise RuntimeError(f'persistent release failure ({policy})')

    monkeypatch.setattr(loop_topology_module, '_release_agents', always_fail)
    result, payload, stderr = _run_phase2(
        ['loop', 'topology', 'release', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 1
    assert payload == {}
    assert calls == 2
    assert 'persistent release failure' in stderr
    observed_path = project_root / '.ccb' / 'runtime' / 'loops' / 'round1' / 'agent_mount_topology.observed.json'
    observed = json.loads(observed_path.read_text(encoding='utf-8'))
    assert observed['last_reconcile_status'] == 'failed'
    assert observed['error'] == 'persistent release failure (auto)'
    assert {agent['observed_state'] for agent in observed['agents']} == {'present'}


def test_loop_topology_partial_reconcile_failure_writes_observed_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    original_add_lifecycle_agents = loop_topology_module.add_lifecycle_agents

    def flaky_add_lifecycle_agents(context, commands, *, action: str):
        assert action == 'topology-agent-add-batch'
        assert {getattr(command, 'agent_name', None) for command in commands} == {
            'loop-round1-coder-1',
            'loop-round1-code_reviewer-1',
        }
        raise RuntimeError('synthetic batch add failure')

    monkeypatch.setattr(loop_topology_module, 'add_lifecycle_agents', flaky_add_lifecycle_agents)

    result, payload, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 1
    assert payload == {}
    assert 'synthetic batch add failure' in stderr
    observed_path = project_root / '.ccb' / 'runtime' / 'loops' / 'round1' / 'agent_mount_topology.observed.json'
    observed = json.loads(observed_path.read_text(encoding='utf-8'))
    assert observed['last_reconcile_status'] == 'failed'
    assert observed['error'] == 'synthetic batch add failure'
    assert not (project_root / '.ccb' / 'runtime' / 'agents' / 'loop-round1-coder-1' / 'lifecycle.json').is_file()

    result, status, stderr = _run_phase2(
        ['loop', 'topology', 'status', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )
    assert result == 1, stderr
    assert status['loop_topology_status'] == 'failed'
    assert status['observed']['status'] == 'failed'

    monkeypatch.setattr(loop_topology_module, 'add_lifecycle_agents', original_add_lifecycle_agents)
    result, recovered, stderr = _run_phase2(
        ['loop', 'topology', 'reconcile', '--loop-id', 'round1', '--json'],
        cwd=project_root,
    )

    assert result == 0, stderr
    assert recovered['loop_topology_status'] == 'reconciled'
    assert {agent['observed_state'] for agent in recovered['observed']['agents']} == {'present'}
    assert any(action['action'] == 'add' and action['agent'] == 'loop-round1-code_reviewer-1' for action in recovered['actions'])


def test_loop_topology_add_batch_reload_failure_restores_state_without_add_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal_path = project_root / 'graph.json'
    _write_json(proposal_path, _proposal())
    result, _proposed, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'proposal1',
            '--json',
        ],
        cwd=project_root,
    )
    assert result == 0, stderr

    def fail_reload(_context, *, action: str):
        assert action == 'topology-agent-add-batch'
        raise RuntimeError('namespace_patch_plan_not_planned')

    monkeypatch.setattr(agent_lifecycle_module, '_apply_reload_if_mounted', fail_reload)
    result, payload, stderr = _run_phase2(
        ['loop', 'topology', 'commit', '--loop-id', 'round1', '--proposal', 'proposal1', '--apply', '--json'],
        cwd=project_root,
    )

    assert result == 1
    assert payload == {}
    assert 'namespace_patch_plan_not_planned' in stderr
    agents = ('loop-round1-coder-1', 'loop-round1-code_reviewer-1')
    assert all(
        not (project_root / '.ccb' / 'runtime' / 'agents' / agent / 'lifecycle.json').exists()
        for agent in agents
    )
    events_path = project_root / '.ccb' / 'runtime' / 'agents' / 'events.jsonl'
    events = (
        [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()]
        if events_path.is_file()
        else []
    )
    assert not any(event.get('event') == 'add' and event.get('agent') in agents for event in events)


def test_loop_topology_propose_rejects_edge_dependency_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_with_topology(tmp_path, monkeypatch)
    proposal = _proposal()
    proposal['dispatch_compatibility'] = 'legacy'
    proposal['edges'] = [
        {'id': 'a', 'from': 'ccb_orchestrator', 'to': 'loop-round1-coder-1', 'type': 'ask', 'after': ['b']},
        {
            'id': 'b',
            'from': 'loop-round1-coder-1',
            'to': 'loop-round1-code_reviewer-1',
            'type': 'ask_after',
            'after': ['a'],
        },
    ]
    proposal_path = project_root / 'cycle.json'
    _write_json(proposal_path, proposal)

    result, payload, stderr = _run_phase2(
        [
            'loop',
            'topology',
            'propose',
            '--loop-id',
            'round1',
            '--from',
            str(proposal_path),
            '--proposal-id',
            'cycle1',
            '--json',
        ],
        cwd=project_root,
    )

    assert result == 1
    assert payload == {}
    assert 'topology edge dependency cycle detected' in stderr
