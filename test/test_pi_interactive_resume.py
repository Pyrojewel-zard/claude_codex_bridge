from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from provider_backends.pi.launcher import _PI_COMPLETION_EXTENSION_SOURCE
from provider_backends.pi import launcher
from provider_backends.pi.session import PiProjectSession, resume_binding_for_launch


def fixture(tmp_path):
    root = tmp_path / 'sessions'
    root.mkdir()
    for identity in ('old', 'current', 'newer-unrelated'):
        (root / f'{identity}.jsonl').write_text(json.dumps(
            dict(type='session', id=identity, cwd=str(tmp_path))) + '\n')
    events = tmp_path / 'events.jsonl'
    event = dict(schema_version=1, type='native_session', actor='pi1',
                 launch_session_id='ccb-old', runtime_instance_id='runtime-old',
                 pi_session_id='current', pi_session_path=str(root / 'current.jsonl'))
    events.write_text(json.dumps(event) + '\n')
    data = dict(agent_name='pi1', ccb_project_id='project', work_dir=str(tmp_path),
                ccb_session_id='ccb-old', pi_session_id='old',
                pi_session_path=str(root / 'old.jsonl'), pi_session_dir=str(root),
                pi_completion_event_log=str(events),
                start_cmd='pi --session old',
                pi_restart_start_cmd_template='pi __CCB_PI_EXACT_SESSION_6E9A2F41__')
    record = tmp_path / '.pi-pi1-session'
    record.write_text(json.dumps(data))
    return root, events, event, data, record


def resolve(tmp_path, root, record):
    return resume_binding_for_launch(record, agent_name='pi1', project_id='project',
                                    work_dir=tmp_path, session_dir=root)


def test_manual_switch_observation_wins_over_persisted_and_newest(tmp_path):
    root, events, event, data, record = fixture(tmp_path)
    assert resolve(tmp_path, root, record)['pi_resume_session_id'] == 'current'
    session = PiProjectSession(session_file=record, data=data)
    assert str(root / 'current.jsonl') in session.start_cmd


@pytest.mark.parametrize('field,value', [('actor', 'other'), ('launch_session_id', 'stale'),
                                        ('runtime_instance_id', ''), ('schema_version', 2)])
def test_observation_owner_mismatch_never_falls_back_to_old_session(tmp_path, field, value):
    root, events, event, data, record = fixture(tmp_path)
    event[field] = value
    events.write_text(json.dumps(event) + '\n')
    assert resolve(tmp_path, root, record)['pi_resume_status'] == 'fresh_no_current_session_observation'


@pytest.mark.parametrize('damage', ['empty-switch', 'missing-events', 'corrupt-events',
                                    'missing-transcript', 'wrong-cwd'])
def test_invalid_current_observation_never_resurrects_previous_context(tmp_path, damage):
    root, events, event, data, record = fixture(tmp_path)
    if damage == 'empty-switch':
        with events.open('a') as stream:
            stream.write(json.dumps(dict(event, pi_session_id='new', pi_session_path='')) + '\n')
    elif damage == 'missing-events':
        events.unlink()
    elif damage == 'corrupt-events':
        events.write_text('not json\n')
    elif damage == 'missing-transcript':
        (root / 'current.jsonl').unlink()
    else:
        (root / 'current.jsonl').write_text(json.dumps(dict(type='session', id='current', cwd='/other')))
    assert resolve(tmp_path, root, record)['pi_resume_status'].startswith('fresh_')


def test_no_restore_is_preserved_by_automatic_restart(tmp_path):
    root, events, event, data, record = fixture(tmp_path)
    data['pi_restore_enabled'] = False
    record.write_text(json.dumps(data))
    session = PiProjectSession(session_file=record, data=data)
    assert session.start_cmd == 'pi'
    assert session.data['pi_resume_status'] == 'fresh_restore_disabled'


def test_shared_extension_observes_manual_turns_and_switches():
    source = _PI_COMPLETION_EXTENSION_SOURCE
    assert 'pi.on("session_switch"' in source
    assert 'pi.on("input", async (event: any, ctx: any)' in source
    assert 'pi.on("turn_end", async (event: any, ctx: any)' in source
    assert source.count('observeNativeSession(ctx);') == 3


def test_observed_ccb_identity_never_enables_legacy_mtime_discovery(tmp_path):
    root, events, event, data, record = fixture(tmp_path)
    event['pi_session_id'] = 'ccb-not-a-native-id'
    events.write_text(json.dumps(event) + '\n')
    assert resolve(tmp_path, root, record)['pi_resume_status'] == 'fresh_native_session_id_invalid'


def test_reopen_reads_old_observation_before_materializing_new_sidecar(monkeypatch, tmp_path):
    root, events, event, data, record = fixture(tmp_path)
    monkeypatch.setattr(launcher, 'prepare_native_launch_context', lambda *a, **kw: {
        'workspace_path': str(tmp_path), 'pi_state_dir': str(tmp_path),
    })
    context = SimpleNamespace(paths=SimpleNamespace(ccb_dir=tmp_path),
                              project=SimpleNamespace(project_id='project'))
    prepared = launcher.prepare_launch_context(context, SimpleNamespace(name='pi1'),
                                               SimpleNamespace(workspace_path=tmp_path),
                                               tmp_path / 'runtime', {})
    assert prepared['pi_resume_session_id'] == 'current'
    launcher._materialize_completion_extension(prepared, runtime_dir=tmp_path / 'runtime',
                                               launch_session_id='ccb-new')
    assert prepared['pi_completion_event_log'] != str(events)
    assert prepared['pi_resume_session_id'] == 'current'
