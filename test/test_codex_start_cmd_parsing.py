from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from hapi_integration.command import render_recorded_hapi_command
from provider_backends.codex.start_cmd_runtime.parsing import (
    extract_resume_session_id,
    looks_like_bare_resume_cmd,
)
from provider_backends.codex.start_cmd_runtime.rewriting import (
    build_resume_start_cmd,
    strip_resume_start_cmd,
)


def test_extract_resume_session_id_prefers_regex_match() -> None:
    command = 'export X=1; codex -c disable_paste_burst=true resume sess-123'

    assert extract_resume_session_id(command) == 'sess-123'


def test_extract_resume_session_id_falls_back_to_token_scan() -> None:
    command = '/usr/local/bin/codex resume sess-456'

    assert extract_resume_session_id(command) == 'sess-456'


def test_extract_resume_session_id_rejects_invalid_shell_syntax() -> None:
    command = 'codex "unterminated'

    assert extract_resume_session_id(command) is None


def test_extract_resume_session_id_ignores_codex_paths_in_environment_assignments() -> None:
    command = (
        'export CCB_CODEX_RUNTIME_DIR=/tmp/provider-runtime/codex '
        'CCB_CALLER_PROJECT_ID=project-1; '
        'codex -c disable_paste_burst=true resume sess-exact'
    )

    assert extract_resume_session_id(command) == 'sess-exact'


def test_looks_like_bare_resume_cmd_accepts_simple_resume() -> None:
    assert looks_like_bare_resume_cmd('/usr/local/bin/codex resume sess-789') is True


def test_looks_like_bare_resume_cmd_rejects_shell_wrapped_command() -> None:
    assert looks_like_bare_resume_cmd('export CODEX_HOME=/tmp; codex resume sess-789') is False


def test_strip_resume_start_cmd_removes_resume_suffix_from_shell_wrapped_command() -> None:
    command = 'export CODEX_HOME=/tmp/home CODEX_SESSION_ROOT=/tmp/home/sessions; codex -m gpt-5.4 resume sess-789'

    assert strip_resume_start_cmd(command) == (
        'export CODEX_HOME=/tmp/home CODEX_SESSION_ROOT=/tmp/home/sessions; '
        'codex -m gpt-5.4'
    )


def test_build_resume_start_cmd_preserves_quoted_hapi_script() -> None:
    rendered = render_recorded_hapi_command(
        wrapper_argv=['hapi', 'codex', '--started-by', 'terminal'],
        record_path=Path('/tmp/ccb-hapi-wrapper.json'),
        launch_session_id='launch-session',
    )
    command = f'export CODEX_HOME=/tmp/home; {rendered}'

    rewritten = build_resume_start_cmd(command, 'resume-session')

    result = subprocess.run(
        ['/bin/bash', '-n'],
        input=rewritten,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    parts = shlex.split(rewritten)
    assert parts[-2:] == ['resume', 'resume-session']
