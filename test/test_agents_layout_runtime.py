from __future__ import annotations

import pytest

from agents.models import build_balanced_layout, iter_layout_names, parse_layout_spec, prune_layout
from agents.models_runtime.config_runtime.validation import resolve_layout_spec


def test_parse_layout_spec_roundtrip_with_parentheses() -> None:
    layout = parse_layout_spec('cmd; (agent1:codex, agent2:claude)')

    assert layout.render() == 'cmd; agent1:codex, agent2:claude'
    assert iter_layout_names(layout) == ('cmd', 'agent1', 'agent2')


def test_parse_layout_spec_roundtrip_with_worktree_workspace_marker() -> None:
    layout = parse_layout_spec('cmd; agent1:codex(worktree), agent2:claude')

    assert layout.render() == 'cmd; agent1:codex(worktree), agent2:claude'
    assert iter_layout_names(layout) == ('cmd', 'agent1', 'agent2')


def test_parse_layout_spec_accepts_role_id_leaf_token() -> None:
    layout = parse_layout_spec('agent1:codex, agentroles.archi:codex')
    leaves = layout.iter_leaves()

    assert leaves[1].name == 'agentroles.archi'
    assert leaves[1].provider == 'codex'
    assert layout.render() == 'agent1:codex, agentroles.archi:codex'


@pytest.mark.parametrize(
    'spec, expected_percent',
    [
        ('debugger:agy@30', 30),
        ('reviewer:claude@50', 50),
        ('worker:codex(worktree)@40', 40),
        ('debugger:agy', None),
    ],
)
def test_parse_layout_spec_percent_token(spec: str, expected_percent: int | None) -> None:
    # @percent 令牌:显式指定 pane 分屏百分比,渲染往返保持
    layout = parse_layout_spec(spec)
    assert layout.kind == 'leaf'
    assert layout.leaf is not None
    assert layout.leaf.percent == expected_percent
    assert layout.render() == spec


def test_prune_layout_preserves_branch_shape_when_possible() -> None:
    layout = parse_layout_spec('cmd; (agent1:codex, agent2:claude)')

    pruned = prune_layout(layout, include_names=('cmd', 'agent2'))

    assert pruned is not None
    assert pruned.render() == 'cmd; agent2:claude'


def test_prune_layout_is_case_insensitive_on_agent_name() -> None:
    # include_names 来自 normalize_agent_name（小写），布局 leaf 保留原始大小写（Main_Code）。
    # 修复前 'main_code' 匹配不上 'Main_Code'，被裁剪为 None →
    # "layout_spec does not include any visible panes"（2026-08-06 采集暴露）。
    layout = parse_layout_spec('Main_Code:codex, code_reviewer:codex')

    pruned = prune_layout(layout, include_names=('main_code',))

    assert pruned is not None
    assert pruned.render() == 'Main_Code:codex'


def test_prune_layout_keeps_mixed_case_layout_after_normalized_include() -> None:
    layout = parse_layout_spec('Main_Code:codex, code_reviewer:codex')

    pruned = prune_layout(layout, include_names=('main_code', 'code_reviewer'))

    assert pruned is not None
    assert pruned.render() == 'Main_Code:codex, code_reviewer:codex'


def test_build_balanced_layout_adds_cmd_leaf_first() -> None:
    layout = build_balanced_layout(
        ('agent1', 'agent2', 'agent3'),
        providers_by_agent={'agent1': 'codex', 'agent2': 'claude', 'agent3': 'gemini'},
        workspace_modes_by_agent={'agent2': 'worktree'},
        cmd_enabled=True,
    )

    assert layout.render() == 'cmd, agent1:codex; agent2:claude(worktree), agent3:gemini'


def test_parse_layout_spec_rejects_invalid_leaf_token() -> None:
    with pytest.raises(Exception, match='agent:provider.*@N'):
        parse_layout_spec('cmd; ???')


def test_resolve_layout_spec_preserves_percent_token() -> None:
    rendered = resolve_layout_spec(
        default_agents=('agent1',),
        normalized_agents={},
        cmd_enabled=True,
        layout_spec='cmd; agent1:codex@65',
    )

    assert rendered == 'cmd; agent1:codex@65'
