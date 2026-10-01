"""Replay suggestion rendering transitions without driving a live pane."""
import pytest

from provider_execution.draft_observation import inspect_screen


def observe(content, *, x=2, y=1, prefix=''):
    screen = {'text': prefix + '────────────\n❯ ' + content + '\n────────────\n',
              'cursor_x': x, 'cursor_y': y + prefix.count('\n')}
    return inspect_screen('claude', screen, binding='test')


@pytest.mark.parametrize('text', ['Run the tests', 'Explain this error', '继续检查代码',
                                 'Review changes\n  then run tests', 'x'])
def test_dynamic_suggestion_text_is_not_a_fixed_placeholder(text):
    assert observe('\x1b[2m' + text + '\x1b[0m').state == 'empty'
    assert observe(text).state == 'nonempty'


@pytest.mark.parametrize('text', ['Run the tests', 'Explain this error', '继续检查代码'])
def test_tab_acceptance_with_cursor_returned_to_start(text):
    ghost = '\x1b[7m' + text[0] + '\x1b[0;2m' + text[1:] + '\x1b[0m'
    accepted = '\x1b[7m' + text[0] + '\x1b[0m' + text[1:]
    assert observe(ghost).state == 'empty'
    assert observe(accepted).state == 'nonempty'
    assert observe(accepted, x=8).state == 'nonempty'


def test_typed_prefix_and_ghost_suffix_remains_draft():
    assert observe('Run\x1b[2m the tests\x1b[0m', x=5).state == 'nonempty'


def test_multiline_draft_after_ghost_remains_draft():
    assert observe('\x1b[2mRun tests\x1b[0m\n  typed text').state == 'nonempty'


def test_ghost_does_not_override_busy_or_native_queue():
    ghost = '\x1b[2mRun tests\x1b[0m'
    assert observe(ghost, prefix='✻ Thinking…\n').reason == 'provider_busy'
    queued = '\x1b[2mPress up to edit queued messages\x1b[0m'
    assert observe(queued).reason == 'provider_native_queue_pending'


def test_inverse_only_single_character_is_not_proven_ghost():
    assert observe('\x1b[7mx\x1b[0m').state == 'nonempty'
