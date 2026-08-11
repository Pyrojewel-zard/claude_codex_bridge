from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


def _load_dod_runner():
    path = Path(__file__).resolve().parents[1] / '.codestable/tools/codestable-dod-runner.py'
    previous = os.environ.get('PYTHONDONTWRITEBYTECODE')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path.insert(0, str(path.parent.resolve()))
    try:
        spec = importlib.util.spec_from_file_location('codestable_dod_runner', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        if previous is None:
            os.environ.pop('PYTHONDONTWRITEBYTECODE', None)
        else:
            os.environ['PYTHONDONTWRITEBYTECODE'] = previous


def test_dod_runner_marks_manual_test_status_without_shell_execution() -> None:
    runner = _load_dod_runner()
    command = {
        'id': 'CMD-MANUAL',
        'command': 'echo should-not-run',
        'test_status': 'manual',
    }

    assert runner.is_manual_command(command) is True
    run = runner.manual_run(command)

    assert run['exit_code'] is None
    assert run['manual'] is True
    assert run['status'] == 'manual-pending'
    assert run['stdout'] == ''
    assert run['stderr'] == ''


def test_dod_runner_marks_manual_action_prefix_without_shell_execution() -> None:
    runner = _load_dod_runner()

    assert runner.is_manual_command({'command': 'MANUAL-ACTION capture transcript'}) is True
    assert runner.is_manual_command({'command': 'MANUAL Native Windows x64 capture transcript'}) is True
    assert runner.is_manual_command({'command': '  manual-action capture transcript'}) is True
    assert runner.is_manual_command({'command': 'python -m pytest -q test/example.py'}) is False


def test_dod_runner_main_blocks_core_manual_without_running_shell(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
    - id: CMD-AUTO
      command: sentinel command
      core: true
""",
        encoding='utf-8',
    )
    calls = []

    def fail_if_called(command, cwd):
        calls.append((command, cwd))
        raise AssertionError('manual command must not reach run_command')

    monkeypatch.setattr(runner, 'run_command', fail_if_called)
    monkeypatch.setattr(
        sys,
        'argv',
        ['codestable-dod-runner.py', '--checklist', str(checklist), '--only', 'CMD-MANUAL'],
    )

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'blocked'
    assert payload['evidence'][0]['status'] == 'manual-pending'
    assert payload['evidence'][0]['exit_code'] is None
    assert calls == []


def test_dod_runner_main_consumes_valid_manual_evidence_manifest(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    source = tmp_path / 'source-transcript.md'
    source.write_text('blocked downstream namespace lifecycle evidence', encoding='utf-8')
    manifest = tmp_path / 'evidence.json'
    manifest.write_text(
        json.dumps(
            {
                'feature': 'test-feature',
                'command_id': 'CMD-MANUAL',
                'status': 'passed',
                'scope': 'control-plane-transport',
                'source_ref': 'source-transcript.md',
                'observations': {'transport_blocker': 'resolved'},
                'verdict': 'transport blocker removed',
            }
        ),
        encoding='utf-8',
    )
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
feature: test-feature
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
      evidence_ref: evidence.json
      evidence_scope: control-plane-transport
      evidence_observations:
        transport_blocker: resolved
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(runner, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(
        sys,
        'argv',
        ['codestable-dod-runner.py', '--checklist', str(checklist)],
    )

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 0
    assert payload['status'] == 'passed'
    assert payload['blocking'] == []
    assert payload['evidence'][0]['status'] == 'manual-evidence-present'
    assert payload['evidence'][0]['manual_evidence'] is True
    assert payload['evidence'][0]['evidence_ref'] == 'evidence.json'
    assert payload['evidence'][0]['source_ref'] == 'source-transcript.md'
    assert payload['evidence'][0]['evidence_scope'] == 'control-plane-transport'
    assert payload['evidence'][0]['evidence_observations']['transport_blocker'] == 'resolved'
    assert payload['evidence'][0]['evidence_verdict'] == 'transport blocker removed'


def test_dod_runner_main_blocks_blocked_manual_evidence_manifest(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    source = tmp_path / 'source-transcript.md'
    source.write_text('blocked downstream namespace lifecycle evidence', encoding='utf-8')
    manifest = tmp_path / 'evidence.json'
    manifest.write_text(
        json.dumps(
            {
                'feature': 'test-feature',
                'command_id': 'CMD-MANUAL',
                'status': 'blocked',
                'source_ref': 'source-transcript.md',
            }
        ),
        encoding='utf-8',
    )
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
feature: test-feature
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
      evidence_ref: evidence.json
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(runner, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(
        sys,
        'argv',
        ['codestable-dod-runner.py', '--checklist', str(checklist)],
    )

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'blocked'
    assert payload['evidence'][0]['status'] == 'manual-evidence-blocked'
    assert payload['evidence'][0].get('manual_evidence') is not True


def test_dod_runner_main_blocks_manual_evidence_observation_mismatch(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    source = tmp_path / 'source-transcript.md'
    source.write_text('transcript', encoding='utf-8')
    manifest = tmp_path / 'evidence.json'
    manifest.write_text(
        json.dumps(
            {
                'feature': 'test-feature',
                'command_id': 'CMD-MANUAL',
                'status': 'passed',
                'scope': 'control-plane-transport',
                'source_ref': 'source-transcript.md',
                'observations': {'transport_blocker': 'unknown'},
            }
        ),
        encoding='utf-8',
    )
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
feature: test-feature
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
      evidence_ref: evidence.json
      evidence_scope: control-plane-transport
      evidence_observations:
        transport_blocker: resolved
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(runner, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['codestable-dod-runner.py', '--checklist', str(checklist)])

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'blocked'
    assert 'observation mismatch' in payload['blocking'][0]


def test_dod_runner_main_blocks_manual_evidence_feature_mismatch(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    source = tmp_path / 'source-transcript.md'
    source.write_text('transcript', encoding='utf-8')
    manifest = tmp_path / 'evidence.json'
    manifest.write_text(
        json.dumps(
            {
                'feature': 'other-feature',
                'command_id': 'CMD-MANUAL',
                'status': 'passed',
                'source_ref': 'source-transcript.md',
            }
        ),
        encoding='utf-8',
    )
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
feature: test-feature
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
      evidence_ref: evidence.json
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(runner, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['codestable-dod-runner.py', '--checklist', str(checklist)])

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'blocked'
    assert 'feature mismatch' in payload['blocking'][0]


def test_dod_runner_main_blocks_markdown_manual_evidence(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    transcript = tmp_path / 'transcript.md'
    transcript.write_text('status: blocked', encoding='utf-8')
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
feature: test-feature
dod:
  commands:
    - id: CMD-MANUAL
      command: MANUAL capture transcript
      core: true
      test_status: manual
      evidence_ref: transcript.md
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(runner, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['codestable-dod-runner.py', '--checklist', str(checklist)])

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'blocked'
    assert 'JSON manifest' in payload['blocking'][0]


def test_dod_runner_main_preserves_automatic_exit_code(tmp_path, monkeypatch, capsys) -> None:
    runner = _load_dod_runner()
    checklist = tmp_path / 'checklist.yaml'
    checklist.write_text(
        """\
dod:
  commands:
    - id: CMD-AUTO
      command: sentinel command
      core: true
""",
        encoding='utf-8',
    )

    monkeypatch.setattr(
        runner,
        'run_command',
        lambda command, cwd: {
            'command': command,
            'exit_code': 7,
            'stdout': '',
            'stderr': 'sentinel failure',
        },
    )
    monkeypatch.setattr(
        sys,
        'argv',
        ['codestable-dod-runner.py', '--checklist', str(checklist)],
    )

    with pytest.raises(SystemExit) as raised:
        runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload['status'] == 'failed'
    assert payload['evidence'][0]['exit_code'] == 7
