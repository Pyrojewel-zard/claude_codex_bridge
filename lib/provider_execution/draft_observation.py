"""Read only the current default tmux composer; unknown layouts fail closed."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SGR = re.compile(r'\x1b\[([0-9;]*)m')
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_BORDER = re.compile(r'^─{8,}\s*$')


@dataclass(frozen=True)
class Observation:
    state: str
    binding: str
    reason: str


def _styled_lines(text: str) -> list[list[tuple[str, bool, bool]]]:
    lines = [[]]
    dim = inverse = False
    pos = 0
    while pos < len(text):
        match = _SGR.match(text, pos)
        if match:
            codes = [int(value or 0) for value in match.group(1).split(';')]
            index = 0
            while index < len(codes):
                code = codes[index]
                if code == 0:
                    dim = inverse = False
                elif code == 2:
                    dim = True
                elif code == 22:
                    dim = False
                elif code == 7:
                    inverse = True
                elif code == 27:
                    inverse = False
                elif code in {38, 48, 58} and index+1 < len(codes):
                    index += 4 if codes[index+1] == 2 else 2
                index += 1
            pos = match.end()
            continue
        other = _ANSI.match(text, pos)
        if other:
            pos = other.end()
            continue
        char = text[pos]
        if char == '\n':
            lines.append([])
        else:
            lines[-1].append((char, dim, inverse))
        pos += 1
    return lines


def inspect_screen(provider: str, screen: dict, *, binding: str) -> Observation:
    styled = _styled_lines(screen['text'])
    lines = [''.join(char for char, _, _ in line) for line in styled]
    cursor_x, cursor_y = screen['cursor_x'], screen['cursor_y']
    def result(state, reason):
        return Observation(state, binding, reason)
    if provider == 'codex':
        arrows = [i for i, line in enumerate(lines) if line.startswith('›') and i <= cursor_y]
        if not arrows:
            return result('unknown', 'composer_missing')
        top = arrows[-1]
        # The phrase alone also occurs in ordinary answers and user drafts.
        # Only the native animated status row outside the composer vetoes send.
        # Join its continuation rows for narrow terminals.
        if any(re.match(r'^[•◦]\s', line) and re.search(
                r'\([^)]*esc to interrupt', ' '.join(lines[i:min(i+3, top)]), re.I)
               for i, line in enumerate(lines[:top])):
            return result('unknown', 'provider_busy')
        # Default main composer has a status footer below the cursor. Selection
        # menus use the same arrow; their confirmation footer is not accepted.
        footer = _codex_footer(lines, styled, cursor_y)
        if footer is None:
            return result('unknown', 'composer_layout_unknown')
        if _editor_mode_in_footer(lines[footer:]):
            return result('unknown', 'unsupported_editor_mode')
        content = lines[top][2:]
        # Styled terminal rows may retain right-hand padding. This is still
        # the fixed placeholder at its initial cursor, not a typed draft.
        if content.rstrip(' ') == 'Ask Codex to do anything' and cursor_y == top and cursor_x == 2:
            if all(not line.strip() for line in lines[top+1:footer]):
                return result('empty', 'codex_placeholder')
        if any(line.strip() for line in [content, *lines[top+1:footer]]) or cursor_y != top or cursor_x > 2:
            return result('nonempty', 'codex_draft')
        return result('unknown', 'codex_no_placeholder')
    if provider != 'claude':
        return result('unknown', 'unsupported_provider')
    borders = [i for i, line in enumerate(lines) if _BORDER.fullmatch(line)]
    pairs = [(a, b) for a, b in zip(borders, borders[1:]) if a < cursor_y < b]
    if not pairs:
        return result('unknown', 'composer_layout_unknown')
    top, bottom = pairs[-1]
    if not lines[top+1].startswith('❯'):
        return result('unknown', 'composer_not_focused')
    # Claude may show elapsed time/tokens without an "esc to interrupt" hint.
    # Its animated flower + ellipsis is distinct from completed "Worked for"
    # status and normal assistant bullets. Never inspect the draft for status.
    if any(re.match(r'^[✢✳✶✻✽·]\s+.*(?:…|\.\.\.)', line) for line in lines[:top]):
        return result('unknown', 'provider_busy')
    if _editor_mode_in_footer(lines[bottom+1:]):
        return result('unknown', 'unsupported_editor_mode')
    content = styled[top+1][2:] + [cell for row in styled[top+2:bottom] for cell in row]
    visible = [cell for cell in content if not cell[0].isspace()]
    if not visible:
        if bottom == top+2 and cursor_y == top+1 and cursor_x == 2:
            return result('empty', 'claude_blank')
        return result('nonempty', 'claude_whitespace_draft')
    # A virtual cursor may render the first ghost character in inverse video.
    # Require the rest to be dim, and at least one actual dim glyph.
    ghost = all(dim or (index == 0 and inverse) for index, (_, dim, inverse) in enumerate(visible))
    if ghost and any(dim for _, dim, _ in visible) and cursor_x == 2 and cursor_y == top+1:
        if 'Press up to edit queued messages' in lines[top+1]:
            return result('unknown', 'provider_native_queue_pending')
        return result('empty', 'claude_ghost')
    return result('nonempty', 'claude_draft')


# A labelled bar row starts at the two-space margin; a wrapped continuation
# row has no label and is set back deeper.
_CODEX_STATUS_LABEL_RE = re.compile(r'^  \S')
_CODEX_STATUS_CONTINUATION_RE = re.compile(r'^ {4,}\S')
# A wrapped bar field keeps its separator aligned with the row above, so it
# sits well past where a short dotted draft would put its own separator.
_CODEX_STATUS_MIN_SEPARATOR_COLUMN = 12
# `tui.status_line` takes at most four fields; allow one spare wrapped row.
_CODEX_STATUS_MAX_BAR_ROWS = 3


def _codex_status_like(row: str, styled_row: list) -> bool:
    """One row of the Codex status bar below the editor.

    A bar row is separated by a spaced middle dot, as upstream already
    requires. Codex does not reliably keep the dim attribute on that
    separator, so when the styling is absent fall back to layout: the fields
    of a bar row are spread out, well past where a short dotted draft would
    put its separator. A model label never decides the verdict.
    """
    if not row.startswith('  '):
        return False
    if re.match(r'^  (?:\d+% [Cc]ontext\b|Context \d+% used\b|\? for shortcuts\b)', row):
        return True
    separators = [
        index for index, (char, _, _) in enumerate(styled_row)
        if char == '·' and 0 < index < len(row) - 1 and row[index-1:index+2] == ' · '
    ]
    if not separators:
        return False
    if any(styled_row[index][1] for index in separators):
        return True
    labelled = bool(_CODEX_STATUS_LABEL_RE.match(row))
    continuation = bool(_CODEX_STATUS_CONTINUATION_RE.match(row))
    return any(
        index >= _CODEX_STATUS_MIN_SEPARATOR_COLUMN and (labelled or continuation)
        for index in separators
    )


def _codex_footer(lines, styled, cursor_y: int) -> int | None:
    """First row of the status bar below the editor, or None when unsupported.

    The bar ends the screen and is separated from the editor by one blank row.
    `tui.status_line` accepts up to four fields, so the bar may wrap onto
    several rows; only its first row anchors the composer boundary and the
    wrapped rows below are ignored. A dotted or trailing-text row that is not
    a bar row never ends the screen, so a draft below the bar still fails
    closed.
    """
    footer = next((i for i in range(len(lines)-1, cursor_y, -1) if lines[i].strip()), None)
    if footer is None or not _codex_status_like(lines[footer], styled[footer]):
        return None
    first = footer
    while (first - 1 > cursor_y
           and first - footer < _CODEX_STATUS_MAX_BAR_ROWS - 1
           and lines[first-1].strip() and lines[first-1].startswith('  ')):
        first -= 1
    if first <= cursor_y+1 or lines[first-1].strip():
        return None
    return first


def _editor_mode_in_footer(lines: list[str]) -> bool:
    return any(re.search(r'\b(?:INSERT|NORMAL|VISUAL)\b', line) for line in lines)
