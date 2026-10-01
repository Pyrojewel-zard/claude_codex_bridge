"""Opt-in real Claude CLI qualification; loopback only, synthetic credentials.

Run with CCB_TEST_CLAUDE_BIN=/absolute/path/to/claude. No CCB pane is created.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import threading
from types import SimpleNamespace

import pytest

from agents.models import RestoreMode
from provider_backends.claude.launcher import _claude_history_state
from provider_backends.claude.launcher_runtime.restore import (
    project_session_restore_target,
)
from provider_backends.claude.launcher_runtime.service import build_start_cmd
from provider_backends.claude.session import ClaudeProjectSession


@contextmanager
def _endpoint():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
            if self.path.startswith('/v1/messages/count_tokens'):
                body = json.dumps({'input_tokens': 10}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self.path.startswith('/v1/messages'):
                self.send_error(404)
                return
            requests.append({'body': data, 'key': self.headers.get('x-api-key')})
            message = {'id': 'msg_loopback', 'type': 'message', 'role': 'assistant',
                       'model': data.get('model', 'test-model'),
                       'content': [{'type': 'text', 'text': 'continuity-loopback-ok'}],
                       'stop_reason': 'end_turn', 'stop_sequence': None,
                       'usage': {'input_tokens': 10, 'output_tokens': 5}}
            if data.get('stream'):
                events = [
                    ('message_start', {'type': 'message_start', 'message': {
                        **message, 'content': [], 'stop_reason': None}}),
                    ('content_block_start', {'type': 'content_block_start', 'index': 0,
                        'content_block': {'type': 'text', 'text': ''}}),
                    ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                        'delta': {'type': 'text_delta', 'text': 'continuity-loopback-ok'}}),
                    ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                    ('message_delta', {'type': 'message_delta',
                        'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                        'usage': {'output_tokens': 5}}),
                    ('message_stop', {'type': 'message_stop'}),
                ]
                body = ''.join(f'event: {name}\ndata: {json.dumps(value)}\n\n'
                               for name, value in events).encode()
                content_type = 'text/event-stream'
            else:
                body, content_type = json.dumps(message).encode(), 'application/json'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _native(binary, args, env, cwd):
    result = subprocess.run(
        [binary, '--print', '--output-format', 'json', '--tools', '',
         '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
         '--setting-sources', '', '--model', 'claude-sonnet-4-6', *args],
        env=env, cwd=cwd, text=True, capture_output=True, timeout=45,
    )
    return result


@pytest.fixture
def native_sandbox(tmp_path):
    with tempfile.TemporaryDirectory(prefix='claude-continuity-', dir=tmp_path) as directory:
        yield Path(directory)


def test_native_cli_continues_across_key_and_route_change_and_missing_history(native_sandbox):
    tmp_path = native_sandbox
    binary = os.environ.get('CCB_TEST_CLAUDE_BIN')
    if not binary:
        pytest.skip('opt-in: CCB_TEST_CLAUDE_BIN requires an installed native Claude CLI')
    assert Path(binary).is_absolute() and Path(binary).is_file()
    home = tmp_path / 'managed-home'
    config = home / '.claude'
    config.mkdir(parents=True)
    workspace = tmp_path / 'project'
    workspace.mkdir()
    # Whitelist environment; never project ambient auth, plugins, MCP, or CCB state.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
    env.update({
        'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(config),
        'CLAUDE_PROJECTS_ROOT': str(config / 'projects'),
        'CLAUDE_SESSION_ENV_ROOT': str(config / 'session-env'),
        'DISABLE_AUTOUPDATER': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
        'DISABLE_TELEMETRY': '1', 'DISABLE_ERROR_REPORTING': '1',
        'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1', 'IS_SANDBOX': '1',
        'NO_PROXY': '127.0.0.1,localhost',
    })
    with _endpoint() as (route_a, requests_a), _endpoint() as (route_b, requests_b):
        env.update(ANTHROPIC_API_KEY='fake-account-a', ANTHROPIC_BASE_URL=route_a)
        first = _native(binary, ['Remember continuity-marker-4821.'], env, workspace)
        assert first.returncode == 0, (first.stdout[-1500:], first.stderr[-1500:])
        first_result = json.loads(first.stdout)
        assert not first_result.get('is_error'), first_result
        native_id = first_result['session_id']
        transcripts = list((config / 'projects').rglob(f'{native_id}.jsonl'))
        assert len(transcripts) == 1
        original_history = transcripts[0].read_text()
        assert 'continuity-marker-4821' in original_history
        assert requests_a and any(r['key'] == 'fake-account-a' for r in requests_a)

        session = ClaudeProjectSession(tmp_path / 'session.json', {
            'work_dir': str(workspace), 'claude_home': str(home),
            'claude_session_id': native_id, 'claude_session_path': str(transcripts[0]),
            'ccb_conversation_id': 'same-conversation',
            'claude_provider_authority_fingerprint': 'authority-a',
        })
        target = project_session_restore_target(
            workspace, 'reviewer', load_project_session_fn=lambda *a, **kw: session,
            claude_history_state_fn=_claude_history_state,
            managed_home=home, authority_fingerprint='authority-b',
        )
        prepared = {}
        start = build_start_cmd(
            SimpleNamespace(restore=True, auto_permission=False),
            SimpleNamespace(name='reviewer', restore_default=RestoreMode.AUTO,
                            startup_args=(), env={}, provider_command_template=None),
            tmp_path, 'launch-b',
            load_profile_fn=lambda *_: None,
            prepare_home_overrides_fn=lambda *a, **kw: {},
            write_settings_overlay_fn=lambda *a, **kw: None,
            build_env_prefix_fn=lambda **kw: '',
            resolve_restore_target_fn=lambda **kw: target,
            provider_start_parts_fn=lambda *_: [binary],
            cli_supports_flag_fn=lambda *a: False,
            is_root_user_fn=lambda: False, prepared_state=prepared,
        )
        # Execute the actual CCB-selected native argv, with isolated env above.
        args = shlex.split(start.rsplit(';', 1)[-1])[1:]
        assert args == ['--continue']
        env.update(ANTHROPIC_API_KEY='fake-account-b', ANTHROPIC_BASE_URL=route_b)
        second = _native(binary, [*args, 'What was the marker?'], env, target.run_cwd)
        assert second.returncode == 0, (second.stdout[-1500:], second.stderr[-1500:])
        second_result = json.loads(second.stdout)
        assert not second_result.get('is_error'), second_result
        assert second_result['session_id'] == native_id
        assert any(r['key'] == 'fake-account-b'
                   and 'continuity-marker-4821' in json.dumps(r['body'].get('messages'))
                   and 'continuity-loopback-ok' in json.dumps(r['body'].get('messages'))
                   for r in requests_b)
        assert session.data['ccb_conversation_id'] == 'same-conversation'
        assert session.data['ccb_authority_generation'] == 2

        # In print mode this CLI version starts fresh itself when history is
        # absent. Pane missing-conversation repair is separately unit tested.
        empty_project = tmp_path / 'empty-project'
        empty_project.mkdir()
        empty_home = tmp_path / 'empty-home'
        empty_config = empty_home / '.claude'
        empty_config.mkdir(parents=True)
        env.update(HOME=str(empty_home), CLAUDE_CONFIG_DIR=str(empty_config),
                   CLAUDE_PROJECTS_ROOT=str(empty_config / 'projects'),
                   CLAUDE_SESSION_ENV_ROOT=str(empty_config / 'session-env'))
        before_count = len(requests_b)
        missing = _native(binary, ['--continue', 'hello'], env, empty_project)
        assert missing.returncode == 0, (
            missing.returncode, missing.stdout[-1500:], missing.stderr[-1500:])
        fresh_result = json.loads(missing.stdout)
        assert not fresh_result.get('is_error')
        assert fresh_result['session_id'] != native_id
        assert len(requests_b) > before_count
        assert all('continuity-marker-4821' not in json.dumps(r['body'].get('messages'))
                   for r in requests_b[before_count:])
        assert 'continuity-marker-4821' in transcripts[0].read_text()
