from __future__ import annotations

import json

from terminal_runtime.tmux_identity import apply_ccb_pane_identity, pane_visual
from terminal_runtime.tmux_theme import render_tmux_session_theme


def test_pane_visual_is_stable_for_same_project_slot() -> None:
    first = pane_visual(project_id='proj-1', slot_key='agent3', order_index=2)
    second = pane_visual(project_id='proj-1', slot_key='agent3', order_index=99)
    assert first == second


def test_pane_visual_uses_different_palette_for_cmd_pool() -> None:
    cmd_visual = pane_visual(project_id='proj-1', slot_key='cmd', is_cmd=True)
    agent_visual = pane_visual(project_id='proj-1', slot_key='cmd', is_cmd=False)
    assert cmd_visual != agent_visual


def test_pane_visual_uses_order_index_when_slot_identity_missing() -> None:
    first = pane_visual(order_index=0)
    second = pane_visual(order_index=1)
    assert first != second


def test_render_tmux_session_theme_uses_terminal_profile_overrides() -> None:
    rendered = render_tmux_session_theme(
        ccb_version='9.9.9',
        status_script=None,
        git_script=None,
        environ={'TERM_PROGRAM': 'Apple_Terminal'},
    )
    assert rendered.profile_name == 'contrast'
    assert rendered.window_options['pane-border-lines'] == 'heavy'
    assert rendered.window_options['pane-border-style'] == 'fg=#565f89,bold'
    assert rendered.window_options['window-style'] == 'bg=#181825'


def test_render_tmux_session_theme_uses_single_status_line() -> None:
    rendered = render_tmux_session_theme(
        ccb_version='9.9.9',
        status_script=None,
        git_script=None,
        environ={},
    )

    assert rendered.session_options['status'] == 'on'
    assert 'status-format[1]' not in rendered.session_options
    assert 'Copy: MouseDrag' not in ''.join(rendered.session_options.values())


def test_render_tmux_session_theme_supports_light_profile() -> None:
    rendered = render_tmux_session_theme(
        ccb_version='9.9.9',
        status_script=None,
        git_script=None,
        environ={'CCB_TMUX_THEME_PROFILE': 'light'},
    )

    assert rendered.profile_name == 'light'
    assert rendered.session_options['status-style'] == 'bg=#eff1f5 fg=#4c4f69'
    assert '#1e1e2e' not in rendered.session_options['status-format[0]']
    assert rendered.window_options['pane-border-style'] == 'fg=#bcc0cc,bold'
    assert rendered.window_options['pane-active-border-style'] == 'fg=#1e66f5,bold'
    assert 'window-style' not in rendered.window_options
    assert 'window-active-style' not in rendered.window_options


def test_render_tmux_session_theme_uses_saved_theme_preference(tmp_path) -> None:
    config_home = tmp_path / 'config'
    theme_path = config_home / 'ccb' / 'theme.json'
    theme_path.parent.mkdir(parents=True)
    theme_path.write_text(
        json.dumps({'schema_version': 1, 'theme': 'light', 'palette': 'latte', 'tmux_profile': 'light'}),
        encoding='utf-8',
    )

    rendered = render_tmux_session_theme(
        ccb_version='9.9.9',
        status_script=None,
        git_script=None,
        environ={'XDG_CONFIG_HOME': str(config_home)},
    )

    assert rendered.profile_name == 'light'
    assert rendered.session_options['status-style'] == 'bg=#eff1f5 fg=#4c4f69'


def test_render_tmux_session_theme_resolves_saved_system_preference(tmp_path) -> None:
    config_home = tmp_path / 'config'
    theme_path = config_home / 'ccb' / 'theme.json'
    theme_path.parent.mkdir(parents=True)
    theme_path.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'theme': 'system',
                'palette': 'system',
                'tmux_profile': 'system',
            }
        ),
        encoding='utf-8',
    )

    rendered = render_tmux_session_theme(
        ccb_version='9.9.9',
        status_script=None,
        git_script=None,
        environ={
            'XDG_CONFIG_HOME': str(config_home),
            'CCB_SYSTEM_THEME': 'light',
        },
    )

    assert rendered.profile_name == 'light'
    assert rendered.session_options['status-style'] == 'bg=#eff1f5 fg=#4c4f69'


def test_light_profile_uses_light_pane_and_sidebar_visuals() -> None:
    agent_visual = pane_visual(
        project_id='proj-1',
        slot_key='agent3',
        profile_name='light',
    )
    sidebar_visual = pane_visual(role='sidebar', profile_name='light')

    assert '#[fg=#eff1f5]' in agent_visual.label_style
    assert agent_visual.border_style.startswith('fg=#')
    assert sidebar_visual.label_style == '#[fg=#eff1f5]#[bg=#6c6f85]#[bold]'
    assert sidebar_visual.border_style == 'fg=#bcc0cc'


def test_apply_ccb_pane_identity_prefers_batch_setter() -> None:
    calls: list[dict[str, object]] = []

    class Backend:
        def set_pane_identity(self, pane_id: str, **kwargs) -> None:
            calls.append({'pane_id': pane_id, **kwargs})

        def set_pane_title(self, pane_id: str, title: str) -> None:
            raise AssertionError('batch setter should replace individual updates')

    apply_ccb_pane_identity(
        Backend(),
        '%3',
        title='agent1',
        agent_label='agent1',
        project_id='proj-1',
        slot_key='agent1',
        window_name='review',
        namespace_epoch=7,
    )

    assert len(calls) == 1
    assert calls[0]['pane_id'] == '%3'
    assert calls[0]['title'] == 'agent1'
    assert calls[0]['user_options']['@ccb_slot'] == 'agent1'
    assert calls[0]['user_options']['@ccb_window'] == 'review'
    assert calls[0]['user_options']['@ccb_namespace_epoch'] == '7'
