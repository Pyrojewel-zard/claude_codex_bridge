from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_profiles.codex_home_config import codex_provider_authority_fingerprint
from provider_backends.codex.launcher_runtime.session_paths import load_resume_session_id, state_dir_for_runtime_dir


def test_load_resume_session_id_prefers_session_field_then_start_cmd(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    agent_dir = ccb_dir / "agents" / "agent1" / "runtime"
    agent_dir.mkdir(parents=True, exist_ok=True)
    session_file = ccb_dir / ".codex-agent1-session"
    session_file.write_text(json.dumps({"codex_session_id": "sid-1"}), encoding="utf-8")

    spec = SimpleNamespace(name="agent1")

    assert load_resume_session_id(spec, agent_dir) == "sid-1"

    session_file.write_text(json.dumps({"start_cmd": "codex resume sid-2"}), encoding="utf-8")

    assert load_resume_session_id(spec, agent_dir) == "sid-2"


def test_load_resume_session_id_rejects_session_path_outside_bound_root(tmp_path: Path) -> None:
    ccb_dir = tmp_path / ".ccb"
    agent_dir = ccb_dir / "agents" / "agent1" / "runtime"
    agent_dir.mkdir(parents=True, exist_ok=True)
    managed_root = ccb_dir / "agents" / "agent1" / "provider-state" / "codex" / "home" / "sessions"
    legacy_path = ccb_dir / "provider-profiles" / "agent1" / "codex" / "sessions" / "2026" / "05" / "10" / "legacy.jsonl"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text('{"type":"session"}\n', encoding="utf-8")
    session_file = ccb_dir / ".codex-agent1-session"
    session_file.write_text(
        json.dumps(
            {
                "codex_session_id": "sid-legacy",
                "codex_session_root": str(managed_root),
                "codex_session_path": str(legacy_path),
                "start_cmd": "codex resume sid-legacy",
            }
        ),
        encoding="utf-8",
    )

    spec = SimpleNamespace(name="agent1")

    assert load_resume_session_id(spec, agent_dir) is None


def test_load_resume_session_id_skips_legacy_resume_when_explicit_provider_authority_is_new(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    agent_dir = ccb_dir / 'agents' / 'agent1' / 'runtime'
    agent_dir.mkdir(parents=True, exist_ok=True)
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(json.dumps({'codex_session_id': 'sid-1'}), encoding='utf-8')

    spec = SimpleNamespace(name='agent1')
    profile = SimpleNamespace(
        inherit_api=False,
        env={
            'OPENAI_API_KEY': 'profile-key',
            'OPENAI_BASE_URL': 'https://api.rootflowai.com',
        },
    )

    assert load_resume_session_id(spec, agent_dir, profile) is None

    session_file.write_text(
        json.dumps(
            {
                'codex_session_id': 'sid-1',
                'codex_provider_authority_fingerprint': codex_provider_authority_fingerprint(profile),
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(spec, agent_dir, profile) is None

    session_file.write_text(
        json.dumps(
            {
                'codex_session_id': 'sid-1',
                'codex_provider_authority_fingerprint': codex_provider_authority_fingerprint(profile),
                'codex_session_authority_fingerprint': codex_provider_authority_fingerprint(profile),
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(spec, agent_dir, profile) == 'sid-1'


def _provider_runtime_dir(ccb_dir: Path, agent_name: str = 'agent1') -> Path:
    agent_dir = ccb_dir / 'agents' / agent_name
    runtime_dir = agent_dir / 'provider-runtime' / 'codex'
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _write_managed_config(runtime_dir: Path, provider: str | None) -> None:
    state_dir = state_dir_for_runtime_dir(runtime_dir)
    assert state_dir is not None
    home = state_dir / 'home'
    home.mkdir(parents=True, exist_ok=True)
    lines = ['model_reasoning_effort = "medium"']
    if provider is not None:
        lines.append(f'model_provider = "{provider}"')
    (home / 'config.toml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _write_rollout(runtime_dir: Path, session_id: str, provider: str) -> Path:
    state_dir = state_dir_for_runtime_dir(runtime_dir)
    assert state_dir is not None
    session_path = state_dir / 'home' / 'sessions' / '2026' / '08' / '16' / f'rollout-{session_id}.jsonl'
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                'timestamp': '2026-08-16T00:00:00.000Z',
                'type': 'session_meta',
                'payload': {'session_id': session_id, 'model_provider': provider},
            }
        )
        + '\n',
        encoding='utf-8',
    )
    return session_path


def _write_session_file(ccb_dir: Path, agent_name: str, session_id: str, rollout: Path) -> None:
    session_file = ccb_dir / f'.codex-{agent_name}-session'
    session_file.write_text(
        json.dumps(
            {
                'codex_session_id': session_id,
                'codex_session_root': str(rollout.parent),
                'codex_session_path': str(rollout),
            }
        ),
        encoding='utf-8',
    )


def test_load_resume_session_id_rejects_provider_mismatch_with_custom_home(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    agent_dir = _provider_runtime_dir(ccb_dir)
    _write_managed_config(agent_dir, 'custom')
    rollout = _write_rollout(agent_dir, 'sid-openai', 'openai')
    _write_session_file(ccb_dir, 'agent1', 'sid-openai', rollout)

    spec = SimpleNamespace(name='agent1')

    assert load_resume_session_id(spec, agent_dir) is None


def test_load_resume_session_id_allows_matching_custom_provider(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    agent_dir = _provider_runtime_dir(ccb_dir)
    _write_managed_config(agent_dir, 'custom')
    rollout = _write_rollout(agent_dir, 'sid-custom', 'custom')
    _write_session_file(ccb_dir, 'agent1', 'sid-custom', rollout)

    spec = SimpleNamespace(name='agent1')

    assert load_resume_session_id(spec, agent_dir) == 'sid-custom'


def test_load_resume_session_id_allows_matching_openai_provider(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    agent_dir = _provider_runtime_dir(ccb_dir)
    _write_managed_config(agent_dir, None)  # no explicit provider -> openai default
    rollout = _write_rollout(agent_dir, 'sid-openai', 'openai')
    _write_session_file(ccb_dir, 'agent1', 'sid-openai', rollout)

    spec = SimpleNamespace(name='agent1')

    assert load_resume_session_id(spec, agent_dir) == 'sid-openai'


def test_load_resume_session_id_allows_missing_rollout(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    agent_dir = _provider_runtime_dir(ccb_dir)
    _write_managed_config(agent_dir, 'custom')
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(json.dumps({'codex_session_id': 'sid-missing'}), encoding='utf-8')

    spec = SimpleNamespace(name='agent1')

    assert load_resume_session_id(spec, agent_dir) == 'sid-missing'
