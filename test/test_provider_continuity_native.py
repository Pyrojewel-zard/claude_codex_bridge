"""Opt-in native CLI history replay, synthetic accounts and loopback routes only."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
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

from provider_backends.codex.launcher_runtime.command_runtime.home import _ensure_session_namespace_authority
from provider_backends.codex.launcher_runtime.session_paths import load_resume_session_id
from provider_backends.codex.session_authority import current_provider_authority_fingerprint
from provider_profiles.models import ResolvedProviderProfile


@contextmanager
def endpoint():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
            requests.append((self.path, self.headers.get('Authorization'), body))
            if '/responses' in self.path:
                item = {'type': 'message', 'id': 'msg_replay', 'role': 'assistant',
                        'status': 'completed', 'content': [{'type': 'output_text',
                        'text': 'NATIVE_HISTORY_REPLY_82', 'annotations': []}]}
                response = {'id': 'resp_replay', 'object': 'response', 'status': 'completed',
                            'output': [item], 'usage': {'input_tokens': 10, 'output_tokens': 5,
                            'total_tokens': 15}}
                events = [
                    {'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                    {'type': 'response.output_item.added', 'output_index': 0,
                     'item': {**item, 'status': 'in_progress', 'content': []}},
                    {'type': 'response.content_part.added', 'item_id': 'msg_replay', 'output_index': 0,
                     'content_index': 0, 'part': {'type': 'output_text', 'text': '', 'annotations': []}},
                    {'type': 'response.output_text.delta', 'item_id': 'msg_replay', 'output_index': 0,
                     'content_index': 0, 'delta': 'NATIVE_HISTORY_REPLY_82'},
                    {'type': 'response.output_text.done', 'item_id': 'msg_replay', 'output_index': 0,
                     'content_index': 0, 'text': 'NATIVE_HISTORY_REPLY_82'},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    {'type': 'response.completed', 'response': response},
                ]
                payload = ''.join(f'event: {e["type"]}\ndata: {json.dumps(e)}\n\n' for e in events)
            else:
                common = {'id': 'chat_replay', 'object': 'chat.completion.chunk',
                          'created': 1, 'model': body.get('model', 'replay')}
                chunks = [{**common, 'choices': [{'index': 0, 'delta': {
                    'role': 'assistant', 'content': 'NATIVE_HISTORY_REPLY_82'}, 'finish_reason': None}]},
                    {**common, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                     'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}]
                payload = ''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n'
            encoded = payload.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def sandbox(tmp_path):
    with tempfile.TemporaryDirectory(prefix='native-continuity-', dir=tmp_path) as root:
        yield Path(root)


def environment(home):
    home.mkdir(parents=True, exist_ok=True)
    return {'PATH': os.environ['PATH'], 'HOME': str(home), 'TERM': 'dumb',
            'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_DATA_HOME': str(home / '.local/share'),
            'XDG_STATE_HOME': str(home / '.local/state'), 'XDG_CACHE_HOME': str(home / '.cache'),
            'NO_PROXY': '127.0.0.1,localhost', 'PI_OFFLINE': '1', 'OMP_SKIP_SETUP': '1'}


def execute(binary, args, env, cwd):
    result = subprocess.run([binary, *args], cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=45)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-2000:])
    assert 'NATIVE_HISTORY_REPLY_82' in result.stdout, (result.stdout[-2000:], result.stderr[-2000:])
    return result


@pytest.mark.parametrize('provider', ['pi', 'omp'])
def test_native_pi_omp_replay_after_account_route_change(sandbox, provider):
    binary = os.environ.get(f'CCB_TEST_{provider.upper()}_BIN')
    if not binary:
        pytest.skip(f'opt-in: CCB_TEST_{provider.upper()}_BIN')
    if provider == 'pi':
        from provider_backends.pi import launcher, session
    else:
        from provider_backends.omp import launcher, session
    home = sandbox / 'home'
    env = environment(home)
    cwd = sandbox / 'project'
    cwd.mkdir()
    native_root = sandbox / 'sessions'
    native_root.mkdir()
    agent_dir = home / f'.{provider}' / 'agent'
    agent_dir.mkdir(parents=True)
    env.update(PI_CODING_AGENT_DIR=str(agent_dir), PI_CODING_AGENT_SESSION_DIR=str(native_root),
               CCB_CALLER_ACTOR='demo')
    record = sandbox / f'.{provider}-demo-session'
    native_id = None
    with endpoint() as (route_a, requests_a), endpoint() as (route_b, requests_b):
        for turn, (route, key, requests) in enumerate([
            (route_a, 'fake-account-a', requests_a),
            (route_b, 'fake-account-b', requests_b),
            (route_b, 'fake-account-b', requests_b),
        ]):
            model = {'providers': {'ccb-test': {'baseUrl': route, 'api': 'openai-completions',
                'apiKey': key, 'models': [{'id': 'replay', 'name': 'Replay', 'reasoning': False,
                'input': ['text'], 'contextWindow': 32000, 'maxTokens': 1000,
                'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}}
            (agent_dir / ('models.json' if provider == 'pi' else 'models.yml')).write_text(json.dumps(model))
            resume_args = []
            if turn:
                binding = session.resume_binding_for_launch(record, agent_name='demo', project_id='test',
                                                           work_dir=cwd, session_dir=native_root)
                assert binding[f'{provider}_resume_status'] == 'exact_session_ready', binding
                assert binding[f'{provider}_resume_session_id'] == native_id
                if provider == 'pi':
                    rendered = session.render_restart_command(
                        f'{shlex.quote(binary)} {session.PI_RESTART_SESSION_MARKER}',
                        exact_args=f'--session {shlex.quote(binding["pi_resume_session_path"])}')
                else:
                    rendered = session.render_restart_command(
                        f'{shlex.quote(binary)} {session.OMP_RESTART_SESSION_MARKER}',
                        binding['omp_resume_session_path'])
                resume_args = shlex.split(rendered)[1:]
            prepared = {f'{provider}_state_dir': str(sandbox / 'state'), f'{provider}_home': str(home)}
            launch_id = f'ccb-turn-{turn}'
            launcher._materialize_completion_extension(prepared, runtime_dir=sandbox / 'runtime',
                                                       launch_session_id=launch_id)
            env.update(CCB_SESSION_ID=launch_id)
            env[f'CCB_{provider.upper()}_COMPLETION_EVENTS'] = prepared[f'{provider}_completion_event_log']
            env[f'CCB_{provider.upper()}_DISPATCH_EVENTS'] = prepared[f'{provider}_dispatch_event_log']
            args = ['--print', '--mode', 'json', '--provider', 'ccb-test', '--model', 'replay',
                    '--thinking', 'off', '--no-tools', '--no-skills', '--no-extensions',
                    '--extension', prepared[f'{provider}_completion_extension'],
                    '--session-dir', str(native_root), *resume_args]
            args += ['--no-context-files', '--no-prompt-templates'] if provider == 'pi' else [
                '--no-lsp', '--no-rules', '--no-title']
            before = len(requests)
            execute(binary, [*args, 'Remember NATIVE_MARKER_4821' if not turn else f'Continue turn {turn}'], env, cwd)
            sent = requests[before:]
            assert sent and all(row[1] == f'Bearer {key}' for row in sent)
            if turn:
                assert any('NATIVE_MARKER_4821' in json.dumps(row[2])
                           and 'NATIVE_HISTORY_REPLY_82' in json.dumps(row[2]) for row in sent)
            events = [json.loads(line) for line in Path(prepared[f'{provider}_completion_event_log']).read_text().splitlines()]
            observations = [e for e in events if e['type'] in ('native_session', 'extension_ready')
                            and e.get(f'{provider}_session_path')]
            assert observations
            last = observations[-1]
            if native_id is None:
                native_id = last[f'{provider}_session_id']
            assert last[f'{provider}_session_id'] == native_id
            record.write_text(json.dumps({
                'agent_name': 'demo', 'ccb_project_id': 'test', 'work_dir': str(cwd),
                'ccb_session_id': launch_id, f'{provider}_session_id': native_id,
                f'{provider}_session_path': last[f'{provider}_session_path'],
                f'{provider}_completion_event_log': prepared[f'{provider}_completion_event_log'],
            }))


def test_native_codex_replay_after_account_route_change(sandbox):
    binary = os.environ.get('CCB_TEST_CODEX_BIN')
    if not binary:
        pytest.skip('opt-in: CCB_TEST_CODEX_BIN')
    cwd = sandbox / 'project'
    cwd.mkdir()
    runtime = cwd / '.ccb/agents/demo/provider-runtime/codex'
    runtime.mkdir(parents=True)
    home = cwd / '.ccb/agents/demo/provider-state/codex/home'
    env = environment(sandbox / 'source-home')
    home.mkdir(parents=True)
    env.update(CODEX_HOME=str(home), CODEX_SQLITE_HOME=str(home),
               CODEX_SESSION_ROOT=str(home / 'sessions'))
    record = cwd / '.ccb/.codex-demo-session'
    profile = ResolvedProviderProfile(provider='codex', agent_name='demo', mode='isolated',
        profile_root=str(home), runtime_home=str(home), inherit_api=False, inherit_auth=False,
        inherit_config=False, env={})
    native_id = None
    with endpoint() as (route_a, requests_a), endpoint() as (route_b, requests_b):
        for turn, (route, key, requests) in enumerate([
            (route_a, 'fake-account-a', requests_a), (route_b, 'fake-account-b', requests_b),
            (route_b, 'fake-account-b', requests_b),
        ]):
            profile = replace(profile, env={'OPENAI_API_KEY': key, 'OPENAI_BASE_URL': route})
            _ensure_session_namespace_authority(runtime, home, home / 'sessions', profile=profile)
            fingerprint = current_provider_authority_fingerprint(profile, runtime_dir=runtime)
            resume = load_resume_session_id(SimpleNamespace(name='demo'), runtime, profile,
                                           current_fingerprint=fingerprint)
            assert resume == native_id
            env['OPENAI_API_KEY'] = key
            (home / 'config.toml').write_text(
                'model = "gpt-5.4"\nmodel_provider = "ccb-test"\n'
                'model_reasoning_effort = "low"\n'
                '[model_providers.ccb-test]\nname = "Loopback"\n'
                f'base_url = "{route}"\nwire_api = "responses"\nenv_key = "OPENAI_API_KEY"\n'
                'requires_openai_auth = false\nsupports_websockets = false\n')
            args = ['exec', '--skip-git-repo-check', '--json']
            if resume:
                args += ['resume', resume]
            before = len(requests)
            result = execute(binary, [*args, 'Remember NATIVE_MARKER_4821' if not turn else f'Continue turn {turn}'], env, cwd)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            started = next(e for e in events if e.get('type') == 'thread.started')
            if native_id is None:
                native_id = started['thread_id']
            assert started['thread_id'] == native_id
            sent = requests[before:]
            assert sent and all(row[1] == f'Bearer {key}' for row in sent)
            if turn:
                assert any('NATIVE_MARKER_4821' in json.dumps(row[2]) and
                           'NATIVE_HISTORY_REPLY_82' in json.dumps(row[2]) for row in sent)
                persisted = json.loads(record.read_text())
                assert persisted['ccb_conversation_id'] == 'stable-conversation'
                assert persisted['ccb_authority_generation'] == 2
            transcripts = list((home / 'sessions').rglob(f'*{native_id}*.jsonl'))
            assert len(transcripts) == 1
            data = json.loads(record.read_text()) if record.exists() else {}
            data.update(codex_home=str(home), codex_session_root=str(home / 'sessions'),
                        codex_session_id=native_id, codex_session_path=str(transcripts[0]),
                        codex_provider_authority_fingerprint=fingerprint,
                        codex_session_authority_fingerprint=fingerprint,
                        ccb_conversation_id='stable-conversation')
            record.write_text(json.dumps(data))
