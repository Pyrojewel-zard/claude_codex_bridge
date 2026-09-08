from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from provider_backends.codex.launcher_runtime import session_decision, session_paths
from provider_backends.codex.launcher_runtime.command_runtime import service
from provider_backends.claude.launcher_runtime import restore as claude_restore
from provider_backends.claude.launcher_runtime.home import resolve_claude_home_layout
from agents.models import RestoreMode
from provider_backends.session_start import (
    SessionStartDecision, SessionStartReason as Reason, create_pristine_managed_home,
)
from runtime_observability import collect_startup_operations


@pytest.fixture(autouse=True)
def _anchor_runtime_state_for_tests(monkeypatch):
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')


@pytest.fixture
def launch(tmp_path):
    runtime = tmp_path / '.ccb' / 'agents' / 'demo' / 'provider-runtime' / 'codex'
    runtime.mkdir(parents=True)
    return SimpleNamespace(
        runtime=runtime,
        binding=tmp_path / '.ccb' / '.codex-demo-session',
        spec=SimpleNamespace(name='demo'),
        authority=Mock(return_value='fp'),
        memory=Mock(return_value='memory-fp'),
    )


def _resolve(launch, **overrides):
    kwargs = dict(
        restore=True, profile=None,
        authority_fingerprint_fn=launch.authority,
        memory_fingerprint_fn=launch.memory,
        resume_fn=session_paths.load_resume_session_id,
        linked_fn=session_paths.load_linked_continuation_session_id,
        supports_fork_fn=lambda: True,
    )
    return session_decision.resolve_session_start(
        launch.spec, launch.runtime, **{**kwargs, **overrides},
    )


def _binding(launch, **fields):
    data = {
        'codex_provider_authority_fingerprint': 'fp',
        'codex_session_authority_fingerprint': 'fp',
        **fields,
    }
    launch.binding.write_text(json.dumps(data))
    return data


def _rollout(launch, sid='private-session-id', *, parent=None, provider='openai'):
    root = launch.runtime.parent.parent / 'provider-state' / 'codex' / 'home' / 'sessions'
    root.mkdir(parents=True, exist_ok=True)
    path = root / f'{sid}.jsonl'
    path.write_text(json.dumps({'type': 'session_meta', 'payload': {
        'id': sid, 'cwd': str(launch.runtime), 'model_provider': provider,
        'forked_from_id': parent,
    }}) + '\n')
    return path


def test_explicit_new_preserves_binding_and_skips_all_loaders(launch):
    _binding(launch, codex_session_id='private-session-id')
    before = launch.binding.read_bytes()
    resume, linked = Mock(), Mock()
    decision, args = _resolve(launch, restore=False, resume_fn=resume, linked_fn=linked)
    assert decision.reason is Reason.NEW_EXPLICIT and args == []
    assert launch.binding.read_bytes() == before
    for call in (resume, linked, launch.authority, launch.memory):
        call.assert_not_called()
    assert asdict(decision) == {'reason': Reason.NEW_EXPLICIT}
    with pytest.raises(FrozenInstanceError):
        decision.reason = Reason.RESUME


def test_missing_binding_skips_fingerprints_linked_and_descendants(launch, monkeypatch):
    descendant = Mock(side_effect=AssertionError('must not scan'))
    linked = Mock(side_effect=AssertionError('must not inspect linked history'))
    monkeypatch.setattr(session_paths, '_latest_linear_descendant', descendant)
    monkeypatch.setattr(session_decision, 'resolve_linked_continuation_payload', linked)
    with collect_startup_operations() as counts:
        decision, args = _resolve(launch)
    assert decision.reason is Reason.NEW_NO_BINDING and args == []
    assert counts.snapshot() == {
        'session_history_binding_path_probe_count': 1,
        'session_decision_no_binding_count': 1,
    }
    launch.authority.assert_not_called()
    launch.memory.assert_not_called()
    assert not launch.binding.exists()
    descendant.assert_not_called()
    linked.assert_not_called()
    descendant.side_effect = None
    descendant.return_value = None
    # Absence is launch-local: a subsequently published binding must be used.
    _binding(launch, codex_session_id='next-session')
    assert _resolve(launch)[1] == ['resume', 'next-session']


@pytest.mark.parametrize('raw', ['', '{}', '[]', 'null', '{broken'])
def test_invalid_record_is_unknown_and_preserved(launch, raw):
    launch.binding.write_text(raw)
    with collect_startup_operations() as counts:
        decision, args = _resolve(launch)
    assert decision.reason is Reason.UNKNOWN_INVALID and args == []
    assert launch.binding.read_text() == raw
    assert counts.snapshot().get('session_decision_no_binding_count', 0) == 0
    assert counts.snapshot()['session_history_payload_read_attempt_count'] == 1


@pytest.mark.parametrize('error', [PermissionError, TimeoutError, OSError, FileNotFoundError])
def test_read_error_or_disappearance_after_probe_is_unknown(launch, monkeypatch, error):
    _binding(launch, codex_session_id='private-session-id')
    before = launch.binding.read_bytes()
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == launch.binding:
            raise error('injected')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read)
    decision, args = _resolve(launch)
    assert decision.reason is Reason.UNKNOWN_INVALID and args == []
    assert launch.binding.read_bytes() == before


def test_probe_permission_error_is_unknown_not_absent(launch, monkeypatch):
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == launch.binding:
            raise PermissionError('injected')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    assert _resolve(launch)[0].reason is Reason.UNKNOWN_INVALID


@pytest.mark.parametrize('kind', ['directory', 'dangling_symlink', 'fifo'])
def test_nonregular_binding_is_unknown(launch, kind):
    if kind == 'directory':
        launch.binding.mkdir()
    elif kind == 'dangling_symlink':
        launch.binding.symlink_to(launch.binding.parent / 'missing-target')
    else:
        import os
        os.mkfifo(launch.binding)
    decision, args = _resolve(launch)
    assert decision.reason is Reason.UNKNOWN_INVALID and args == []
    launch.binding.lstat()  # The original directory/link/FIFO remains intact.


def test_resume_reuses_payload_and_fingerprints_and_redacts_metadata(launch):
    _binding(launch, codex_session_id='private-session-id', secret='private-secret')
    before = launch.binding.read_bytes()
    with collect_startup_operations() as counts:
        decision, args = _resolve(launch)
    assert decision.reason is Reason.RESUME
    assert args == ['resume', 'private-session-id']
    assert counts.snapshot()['session_history_payload_read_attempt_count'] == 1
    launch.authority.assert_called_once_with(None, runtime_dir=launch.runtime)
    launch.memory.assert_called_once_with(launch.runtime)
    assert launch.binding.read_bytes() == before
    assert 'private' not in repr(decision)
    assert 'fp' not in repr(decision)


@pytest.mark.parametrize('supports_fork', [True, False])
def test_linked_fork_uses_same_payload_and_fingerprint(launch, supports_fork):
    old = _rollout(launch, 'old')
    _binding(launch, old_codex_session_id='old', old_codex_session_path=str(old),
             codex_session_root=str(old.parent), work_dir=str(launch.runtime),
             ccb_resume_compatibility='linked_continuation')
    before = launch.binding.read_bytes()
    with collect_startup_operations() as counts:
        decision, args = _resolve(launch, supports_fork_fn=lambda: supports_fork)
    assert decision.reason is (Reason.FORK if supports_fork else Reason.NEW_INCOMPATIBLE)
    assert args == (['fork', 'old'] if supports_fork else [])
    assert counts.snapshot()['session_history_payload_read_attempt_count'] == 1
    launch.authority.assert_called_once()
    launch.memory.assert_called_once()
    assert launch.binding.read_bytes() == before


@pytest.mark.parametrize('mismatch', ['authority', 'provider', 'missing_transcript'])
def test_incompatible_or_unusable_binding_preserves_existing_record(launch, mismatch):
    log = _rollout(launch)
    (log.parent.parent / 'config.toml').write_text('model_provider = "openai"\n')
    _binding(launch, codex_session_id='private-session-id', codex_session_path=str(log),
             codex_session_root=str(log.parent))
    if mismatch == 'authority':
        launch.authority.return_value = 'different-authority'
    elif mismatch == 'provider':
        (log.parent.parent / 'config.toml').write_text('model_provider = "custom"\n')
    else:
        log.unlink()
    before = launch.binding.read_bytes()
    decision, args = _resolve(launch)
    assert decision.reason is (Reason.UNKNOWN_INVALID if mismatch == 'missing_transcript' else Reason.NEW_INCOMPATIBLE)
    assert args == [] and launch.binding.read_bytes() == before


def test_injected_loaders_keep_contract_even_with_no_binding(launch):
    resume = Mock(return_value=None)
    linked = Mock(return_value='injected-old')
    decision, args = _resolve(launch, resume_fn=resume, linked_fn=linked)
    assert decision.reason is Reason.FORK and args == ['fork', 'injected-old']
    resume.assert_called_once_with(launch.spec, launch.runtime, None,
                                   current_fingerprint='fp', current_memory_fingerprint='memory-fp')
    linked.assert_called_once_with(launch.spec, launch.runtime, current_fingerprint='fp')
    launch.authority.assert_called_once()


def test_command_carries_decision_and_always_prepares_home(launch, monkeypatch):
    prepare = Mock(return_value={})
    monkeypatch.setattr(service, 'current_provider_authority_fingerprint', launch.authority)
    monkeypatch.setattr(service, 'current_memory_projection_fingerprint', launch.memory)
    context = {'project_root': str(launch.runtime.parent)}
    cmd = service.build_start_cmd(
        SimpleNamespace(restore=True, auto_permission=False),
        SimpleNamespace(name='demo', startup_args=[], provider_command_template='',
                        restore_default=RestoreMode.AUTO, env={}),
        launch.runtime, 'launch-id', prepared_state=context,
        load_resolved_provider_profile_fn=lambda _: None,
        prepare_codex_home_overrides_fn=prepare,
        provider_start_parts_fn=lambda _: ['codex'],
        load_resume_session_id_fn=session_paths.load_resume_session_id,
        load_linked_continuation_session_id_fn=session_paths.load_linked_continuation_session_id,
        build_codex_shell_prefix_fn=lambda **_: [],
    )
    assert context['session_start_decision'].reason is Reason.NEW_NO_BINDING
    assert ' resume ' not in cmd and ' fork ' not in cmd
    prepare.assert_called_once()
    launch.authority.assert_not_called()


def test_claude_pristine_requires_exclusive_creation_then_uses_normal_path(tmp_path, monkeypatch):
    runtime = tmp_path / '.ccb' / 'agents' / 'demo' / 'provider-runtime' / 'claude'
    runtime.mkdir(parents=True)
    authority = Mock(return_value='fp')
    monkeypatch.setattr(claude_restore, 'current_provider_authority_fingerprint', authority)
    project = Mock(return_value=None)
    history = Mock(return_value=(None, False, None))
    kwargs = dict(spec=SimpleNamespace(name='demo'), runtime_dir=runtime, restore=True,
                  project_session_restore_target_fn=project, claude_history_state_fn=history,
                  claude_home_layout_fn=resolve_claude_home_layout, load_profile_fn=lambda _: None)
    target = claude_restore.resolve_claude_restore_target(**kwargs)
    assert target.session_start_decision == SessionStartDecision(Reason.NEW_PRISTINE)
    assert target.has_history is False
    for call in (authority, project, history):
        call.assert_not_called()
    claude_restore.resolve_claude_restore_target(**kwargs)
    authority.assert_called_once()
    project.assert_called_once()
    history.assert_called_once()


def test_pristine_proof_rechecks_binding_publication_race(tmp_path, monkeypatch):
    binding, home = tmp_path / 'binding', tmp_path / 'home'
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path == home:
            binding.write_text('{"concurrent":true}')

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    assert create_pristine_managed_home(home, binding_path=binding) is False
    assert binding.read_text() == '{"concurrent":true}'


@pytest.mark.parametrize('raw', ['', '{}', '{broken'])
def test_pristine_proof_never_hides_present_binding(tmp_path, raw):
    binding, home = tmp_path / 'binding', tmp_path / 'home'
    binding.write_text(raw)
    assert create_pristine_managed_home(home, binding_path=binding) is False
    assert not home.exists() and binding.read_text() == raw


@pytest.mark.parametrize('shape', ['linear', 'branch', 'cycle'])
@pytest.mark.parametrize('linked', [False, True])
def test_shared_payload_preserves_descendant_selection(launch, shape, linked):
    old = _rollout(launch, 'old', parent='child' if shape == 'cycle' else None)
    child = _rollout(launch, 'child', parent='old')
    if shape == 'branch':
        _rollout(launch, 'sibling', parent='old')
    fields = dict(codex_session_root=str(old.parent), work_dir=str(launch.runtime))
    if linked:
        fields = {**fields, 'old_codex_session_id': 'old', 'old_codex_session_path': str(old),
                  'ccb_resume_compatibility': 'linked_continuation'}
    else:
        fields = {**fields, 'codex_session_id': 'old', 'codex_session_path': str(old)}
    _binding(launch, **fields)
    decision, args = _resolve(launch)
    if shape == 'cycle' and not linked:
        assert decision.reason is Reason.UNKNOWN_INVALID and args == []
        persisted = json.loads(launch.binding.read_text())
        assert persisted['codex_binding_recovery_reason'] == 'lineage_cycle'
        assert persisted['ccb_continuity_status'] == 'recovery_required'
        assert old.is_file() and child.is_file()
        return
    assert decision.reason is (Reason.FORK if linked else Reason.RESUME)
    expected_id = 'child' if shape == 'linear' else 'old'
    assert args == ['fork' if linked else 'resume', expected_id]
    persisted = json.loads(launch.binding.read_text())
    assert persisted['old_codex_session_id' if linked else 'codex_session_id'] == expected_id
    assert old.is_file() and child.is_file()


@pytest.mark.parametrize('failure', ['concurrent_binding', 'write_failed'])
def test_native_fork_repair_keeps_locked_reread_and_fails_closed(launch, monkeypatch, failure):
    old = _rollout(launch, 'old')
    blank = _rollout(launch, 'blank')
    _binding(launch, codex_session_id='blank', codex_session_path=str(blank),
             old_codex_session_id='old', old_codex_session_path=str(old),
             codex_session_root=str(old.parent), work_dir=str(launch.runtime),
             ccb_resume_compatibility='native_fork_continuation')
    original = session_paths._persist_invalid_native_fork_repair
    replacement = json.dumps({'codex_session_id': 'concurrent-writer', 'keep': 'untouched'})
    before = launch.binding.read_bytes()
    if failure == 'concurrent_binding':
        def repair(*args, **kwargs):
            launch.binding.write_text(replacement)
            return original(*args, **kwargs)
        monkeypatch.setattr(session_paths, '_persist_invalid_native_fork_repair', repair)
    else:
        monkeypatch.setattr(session_paths, 'safe_write_session', lambda *_: (False, 'injected'))
    with collect_startup_operations() as counts:
        decision, args = _resolve(launch)
    assert decision.reason is Reason.UNKNOWN_INVALID and args == []
    assert counts.snapshot()['session_history_payload_read_attempt_count'] == 2
    assert launch.binding.read_bytes() == (replacement.encode() if failure == 'concurrent_binding' else before)
    assert old.is_file() and blank.is_file()


def test_relocated_binding_and_unknown_anchor(tmp_path, monkeypatch):
    from storage.paths import PathLayout

    monkeypatch.delenv('CCB_RUNTIME_STATE_ANCHOR')
    monkeypatch.setenv('CCB_RUNTIME_STATE_HOME', str(tmp_path / 'state'))
    root = tmp_path / 'project'
    root.mkdir()
    layout = PathLayout(root)
    layout.ensure_runtime_state_root()
    runtime = layout.agent_provider_runtime_dir('demo', 'codex')
    runtime.mkdir(parents=True, exist_ok=True)
    launch = SimpleNamespace(runtime=runtime, spec=SimpleNamespace(name='demo'),
                             binding=layout.ccb_dir / '.codex-demo-session',
                             authority=Mock(return_value='fp'), memory=Mock(return_value=''))
    assert _resolve(launch)[0].reason is Reason.NEW_NO_BINDING
    _binding(launch, codex_session_id='relocated-session')
    assert _resolve(launch)[1] == ['resume', 'relocated-session']
    launch.runtime = tmp_path / 'unmapped-runtime'
    assert _resolve(launch)[0].reason is Reason.UNKNOWN_INVALID


def test_claude_existing_home_cross_slug_fallback_remains(tmp_path, monkeypatch):
    from provider_backends.claude.launcher_runtime.restore import claude_history_state
    import uuid

    runtime = tmp_path / '.ccb' / 'agents' / 'demo' / 'provider-runtime' / 'claude'
    runtime.mkdir(parents=True)
    layout = resolve_claude_home_layout(runtime, None)
    old_slug = layout.projects_root / 'old-workspace-slug'
    old_slug.mkdir(parents=True)
    sid = str(uuid.uuid4())
    (old_slug / f'{sid}.jsonl').write_text('{}\n')
    monkeypatch.setattr(claude_restore, 'current_provider_authority_fingerprint', lambda *_: 'fp')

    def history(**kwargs):
        return claude_history_state(
            invocation_dir=kwargs['invocation_dir'], project_root=kwargs['project_root'],
            home_dir=kwargs['home_dir'], env={},
        )

    target = claude_restore.resolve_claude_restore_target(
        spec=SimpleNamespace(name='demo'), runtime_dir=runtime, restore=True,
        project_session_restore_target_fn=lambda *_, **__: None,
        claude_history_state_fn=history, claude_home_layout_fn=resolve_claude_home_layout,
        load_profile_fn=lambda _: None,
    )
    assert target.has_history is True and target.session_start_decision is None
