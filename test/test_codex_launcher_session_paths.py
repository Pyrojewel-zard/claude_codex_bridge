from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from provider_profiles.codex_home_config import codex_provider_authority_fingerprint
from provider_backends.codex.launcher_runtime.session_paths import (
    load_linked_continuation_session_id,
    load_resume_session_id,
    state_dir_for_runtime_dir,
)


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


def test_load_resume_session_id_repairs_one_missed_native_fork_chain(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    work_dir = tmp_path / 'repo'
    runtime_dir = ccb_dir / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    session_root = ccb_dir / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home' / 'sessions'
    runtime_dir.mkdir(parents=True)
    old_log = _rollout(session_root, 'sid-old', work_dir=work_dir)
    child_log = _rollout(session_root, 'sid-child', work_dir=work_dir, parent='sid-old')
    grandchild_log = _rollout(session_root, 'sid-latest', work_dir=work_dir, parent='sid-child')
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'work_dir': str(work_dir),
                'codex_session_root': str(session_root),
                'codex_session_id': 'sid-old',
                'codex_session_path': str(old_log),
                'start_cmd': 'codex resume sid-old',
                'codex_start_cmd': 'codex resume sid-old',
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(SimpleNamespace(name='agent1'), runtime_dir) == 'sid-latest'
    persisted = json.loads(session_file.read_text(encoding='utf-8'))
    assert persisted['codex_session_id'] == 'sid-latest'
    assert persisted['codex_session_path'] == str(grandchild_log)
    assert persisted['old_codex_session_id'] == 'sid-old'
    assert child_log.is_file()


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


def test_load_linked_continuation_uses_latest_unambiguous_native_descendant(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    work_dir = tmp_path / 'repo'
    runtime_dir = ccb_dir / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    session_root = ccb_dir / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home' / 'sessions'
    runtime_dir.mkdir(parents=True)
    old_log = _rollout(session_root, 'sid-old', work_dir=work_dir)
    latest_log = _rollout(session_root, 'sid-latest', work_dir=work_dir, parent='sid-old')
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'work_dir': str(work_dir),
                'codex_session_root': str(session_root),
                'old_codex_session_id': 'sid-old',
                'old_codex_session_path': str(old_log),
                'codex_provider_authority_fingerprint': 'fp-new',
                'ccb_resume_compatibility': 'linked_continuation',
            }
        ),
        encoding='utf-8',
    )

    assert load_linked_continuation_session_id(
        SimpleNamespace(name='agent1'),
        runtime_dir,
        current_fingerprint='fp-new',
    ) == 'sid-latest'
    persisted = json.loads(session_file.read_text(encoding='utf-8'))
    assert persisted['old_codex_session_id'] == 'sid-latest'
    assert persisted['old_codex_session_path'] == str(latest_log)


def test_prelaunch_reconciliation_fails_closed_on_fork_branch(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    work_dir = tmp_path / 'repo'
    runtime_dir = ccb_dir / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    session_root = ccb_dir / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home' / 'sessions'
    runtime_dir.mkdir(parents=True)
    old_log = _rollout(session_root, 'sid-old', work_dir=work_dir)
    _rollout(session_root, 'sid-child-a', work_dir=work_dir, parent='sid-old')
    _rollout(session_root, 'sid-child-b', work_dir=work_dir, parent='sid-old')
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'work_dir': str(work_dir),
                'codex_session_root': str(session_root),
                'codex_session_id': 'sid-old',
                'codex_session_path': str(old_log),
                'start_cmd': 'codex resume sid-old',
                'codex_start_cmd': 'codex resume sid-old',
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(SimpleNamespace(name='agent1'), runtime_dir) == 'sid-old'
    assert json.loads(session_file.read_text(encoding='utf-8'))['codex_session_id'] == 'sid-old'


def test_load_resume_repairs_claimed_native_fork_with_missing_parent_evidence(tmp_path: Path) -> None:
    ccb_dir = tmp_path / '.ccb'
    work_dir = tmp_path / 'repo'
    runtime_dir = ccb_dir / 'agents' / 'agent1' / 'provider-runtime' / 'codex'
    session_root = ccb_dir / 'agents' / 'agent1' / 'provider-state' / 'codex' / 'home' / 'sessions'
    runtime_dir.mkdir(parents=True)
    old_log = _rollout(session_root, 'sid-old', work_dir=work_dir)
    good_log = _rollout(session_root, 'sid-good', work_dir=work_dir, parent='sid-old')
    blank_log = _rollout(session_root, 'sid-blank', work_dir=work_dir)
    session_file = ccb_dir / '.codex-agent1-session'
    session_file.write_text(
        json.dumps(
            {
                'work_dir': str(work_dir),
                'codex_session_root': str(session_root),
                'codex_session_id': 'sid-blank',
                'codex_session_path': str(blank_log),
                'old_codex_session_id': 'sid-old',
                'old_codex_session_path': str(old_log),
                'ccb_resume_compatibility': 'native_fork_continuation',
                'ccb_continuity_status': 'continued_on_new_authority',
                'start_cmd': 'codex resume sid-blank',
                'codex_start_cmd': 'codex resume sid-blank',
            }
        ),
        encoding='utf-8',
    )

    assert load_resume_session_id(SimpleNamespace(name='agent1'), runtime_dir) == 'sid-good'
    persisted = json.loads(session_file.read_text(encoding='utf-8'))
    assert persisted['codex_session_id'] == 'sid-good'
    assert persisted['codex_session_path'] == str(good_log)
    assert persisted['old_codex_session_id'] == 'sid-old'
    assert persisted['rejected_codex_session_id'] == 'sid-blank'
    assert persisted['rejected_codex_session_path'] == str(blank_log)
    assert persisted['codex_binding_recovery_reason'] == 'native_fork_parent_mismatch'
    assert persisted['ccb_resume_compatibility'] == 'recovered_native_fork_mismatch'
    assert persisted['ccb_continuity_status'] == 'recovered'


def _rollout(root: Path, session_id: str, *, work_dir: Path, parent: str = '') -> Path:
    path = root / '2026' / '08' / '12' / f'rollout-{session_id}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                'type': 'session_meta',
                'payload': {
                    'session_id': session_id,
                    'id': session_id,
                    'forked_from_id': parent or None,
                    'cwd': str(work_dir),
                    'thread_source': 'user',
                },
            }
        )
        + '\n',
        encoding='utf-8',
    )
    return path
