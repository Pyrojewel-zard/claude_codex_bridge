from __future__ import annotations


def resume_with_fresh_fallback(*, resume_command: str, fresh_command: str) -> str:
    """Run one continuation attempt and replace it with a fresh context on failure."""
    return (
        f'if ( {resume_command} ); then exit 0; else '
        '_ccb_resume_status=$?; '
        'case "$_ccb_resume_status" in 130|131|143) exit "$_ccb_resume_status";; esac; '
        "printf '%s\\n' 'CCB: Codex resume failed; starting a fresh context.' >&2; "
        'export CCB_CODEX_RESUME_FALLBACK=1; '
        f'exec {fresh_command}; fi'
    )


__all__ = ['resume_with_fresh_fallback']
