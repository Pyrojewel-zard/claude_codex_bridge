from __future__ import annotations

import shlex
import re

from .parsing import find_codex_token_index


def build_resume_start_cmd(command: object, session_id: object) -> str:
    normalized_session_id = str(session_id or '').strip()
    if not normalized_session_id:
        return str(command or '').strip()
    raw = str(command or '').strip()
    if not raw:
        return f'codex resume {shlex.quote(normalized_session_id)}'
    if 'CCB_CODEX_MANAGED_REMOTE=1' in raw:
        return _replace_managed_resume_id(raw, normalized_session_id)
    shell_prefix, codex_segment = split_last_shell_segment(raw)
    rebuilt_segment = rewrite_codex_segment(codex_segment, normalized_session_id)
    if not rebuilt_segment:
        rebuilt_segment = f'codex resume {shlex.quote(normalized_session_id)}'
    if shell_prefix:
        return f'{shell_prefix}; {rebuilt_segment}'
    return rebuilt_segment


def strip_resume_start_cmd(command: object) -> str:
    raw = str(command or '').strip()
    if not raw:
        return ''
    if 'CCB_CODEX_MANAGED_REMOTE=1' in raw:
        return _replace_managed_resume_id(raw, '')
    shell_prefix, codex_segment = split_last_shell_segment(raw)
    stripped_segment = strip_resume_from_codex_segment(codex_segment)
    if stripped_segment is None:
        stripped_segment = codex_segment
    if shell_prefix:
        return f'{shell_prefix}; {stripped_segment}'
    return stripped_segment


def split_last_shell_segment(command: str) -> tuple[str, str]:
    raw = str(command or '').strip()
    separator_index = _last_top_level_separator(raw, ';')
    if separator_index < 0:
        return '', raw
    prefix = raw[:separator_index]
    tail = raw[separator_index + 1:]
    if not prefix.strip() or not tail.strip():
        return '', raw
    return prefix.strip(), tail.strip()


def _last_top_level_separator(command: str, separator: str) -> int:
    """Return the last separator outside shell quotes.

    Resume commands can contain a quoted ``sh -c`` script (notably the HAPI
    wrapper), whose body legitimately contains semicolons.  A plain
    ``str.rpartition(';')`` therefore cuts the command inside that script and
    leaves an unterminated quote.  This small scanner is intentionally limited
    to the quoting rules needed for command segmentation; tokenization and
    validation remain delegated to ``shlex`` below.
    """
    quote: str | None = None
    escaped = False
    last_index = -1
    for index, char in enumerate(str(command or '')):
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if char == "'":
                quote = None
            continue
        if quote == '"':
            if char == '\\':
                escaped = True
            elif char == '"':
                quote = None
            continue
        if char == '\\':
            escaped = True
        elif char in {"'", '"'}:
            quote = char
        elif char == separator:
            last_index = index
    return last_index


def strip_resume_from_codex_segment(segment: str) -> str | None:
    try:
        tokens = shlex.split(segment)
    except Exception:
        return None
    if not tokens:
        return None
    codex_index = find_codex_token_index(tokens)
    if codex_index is None:
        return None
    resume_index = None
    for index in range(codex_index + 1, len(tokens)):
        if tokens[index] == 'resume':
            resume_index = index
            break
    base_tokens = tokens[:resume_index] if resume_index is not None else list(tokens)
    if not base_tokens:
        return None
    return ' '.join(shlex.quote(str(token)) for token in base_tokens)


def rewrite_codex_segment(segment: str, session_id: str) -> str | None:
    try:
        tokens = shlex.split(segment)
    except Exception:
        return None
    if not tokens:
        return None
    codex_index = find_codex_token_index(tokens)
    if codex_index is None:
        return None
    resume_index = None
    for index in range(codex_index + 1, len(tokens)):
        if tokens[index] == 'resume':
            resume_index = index
            break
    base_tokens = tokens[:resume_index] if resume_index is not None else list(tokens)
    base_tokens.extend(['resume', session_id])
    return ' '.join(shlex.quote(str(token)) for token in base_tokens)


_MANAGED_RESUME_ASSIGNMENT_RE = re.compile(
    r'(?P<prefix>\bCCB_CODEX_RESUME_ID=)(?:\'[^\']*\'|"[^"]*"|[^;\s]*)'
)


def _replace_managed_resume_id(command: str, session_id: str) -> str:
    replacement = rf'\g<prefix>{shlex.quote(session_id)}'
    return _MANAGED_RESUME_ASSIGNMENT_RE.sub(replacement, command, count=1)


__all__ = [
    'build_resume_start_cmd',
    'rewrite_codex_segment',
    'split_last_shell_segment',
    'strip_resume_from_codex_segment',
    'strip_resume_start_cmd',
]
