"""CCB fork regression: wrapped Codex status bars must not block delivery.

Upstream's draft observation accepts a single-row Codex status bar. Codex
renders `tui.status_line` fields on continuation rows when the configured
field list does not fit one terminal row, and the pre-claim draft guard then
reports `composer_layout_unknown`, which refuses to send *any* job to that
agent.

These cases pin the fork's wrapped-bar support. The upstream fixtures in
`test/fixtures/composer/native-20260920.json` keep their original verdicts;
only the wrap is added here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from provider_execution.draft_observation import inspect_screen

_FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'composer' / 'native-20260920.json'
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_DIM = '\x1b[2m'
_RESET = '\x1b[0m'

# The status line Codex renders for a four-field `tui.status_line` such as
# ["context-used", "model-with-reasoning", "weekly-limit", "five-hour-limit"].
_WRAPPED_ROW = f'  Context 39% used {_DIM}·{_RESET} gpt-5.6-luna max fast {_DIM}·{_RESET} w…'
_WRAPPED_CONTINUATION = f'                                      ⚠ 4 {_DIM}·{_RESET} f2'


def _initial_fixture() -> dict:
    fixtures = json.loads(_FIXTURES.read_text(encoding='utf-8'))
    return next(entry for entry in fixtures if entry['provider'] == 'codex' and entry['case'] == 'initial')


def _wrap_status_line(text: str) -> str:
    """Replace the fixture's single-row status bar with a wrapped one."""
    lines = text.split('\n')
    for index, line in enumerate(lines):
        if 'default' in _ANSI.sub('', line):
            lines[index] = _WRAPPED_ROW
            lines.insert(index + 1, _WRAPPED_CONTINUATION)
            return '\n'.join(lines)
    raise AssertionError('fixture no longer contains the single-row status bar')


def _screen(text: str, cursor_x: int, cursor_y: int) -> dict:
    return {'text': text, 'cursor_x': cursor_x, 'cursor_y': cursor_y}


def test_wrapped_status_line_keeps_idle_composer_sendable() -> None:
    fixture = _initial_fixture()
    wrapped = _wrap_status_line(fixture['text'])

    observation = inspect_screen(
        'codex', _screen(wrapped, fixture['cursor_x'], fixture['cursor_y']), binding='pane',
    )

    assert observation.state == 'empty'
    assert observation.reason == 'codex_placeholder'


def test_wrapped_status_line_still_detects_a_draft() -> None:
    fixture = _initial_fixture()
    lines = _wrap_status_line(fixture['text']).split('\n')
    cursor_y = fixture['cursor_y']
    lines[cursor_y] = '› hello from user'

    observation = inspect_screen('codex', _screen('\n'.join(lines), 18, cursor_y), binding='pane')

    assert observation.state == 'nonempty'
    assert observation.reason == 'codex_draft'


def test_single_row_status_line_is_unchanged() -> None:
    fixture = _initial_fixture()

    observation = inspect_screen(
        'codex', _screen(fixture['text'], fixture['cursor_x'], fixture['cursor_y']), binding='pane',
    )

    assert observation.state == 'empty'
    assert observation.reason == 'codex_placeholder'


@pytest.mark.parametrize(
    'footer',
    [
        '› Ask Codex to do anything\n\n  draft · text',
        '› Ask Codex to do anything\n\n  model · name',
        '› Ask Codex to do anything\n\n  ? for shortcuts\n  remaining draft',
    ],
)
def test_dot_text_below_composer_is_still_unknown(footer: str) -> None:
    """Text that merely contains a dot must not become a status bar.

    A wrapped continuation row is set back under the field it continues (four
    spaces or more), beyond the two-space bar margin, and a row below a
    complete status bar is never part of it.
    """
    observation = inspect_screen('codex', _screen(footer, 2, 0), binding='pane')

    assert observation.state == 'unknown'