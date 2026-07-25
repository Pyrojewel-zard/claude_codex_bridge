from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from completion.models import CompletionSourceKind
from provider_backends.kimi.execution import _persist_observed_native_session
from provider_backends.kimi.launcher import (
    _has_session_control,
    _resolve_exact_resume_flag,
    prepare_launch_context,
)
from provider_backends.kimi.native_log import (
    KimiTurnObservation,
    kimi_code_project_dirname,
    kimi_project_hash,
    kimi_share_dir,
)
from provider_backends.kimi.session import (
    KIMI_RESTART_SESSION_MARKER,
    KimiProjectSession,
    persist_native_session_binding,
    prepare_restart_start_cmd,
    resume_binding_for_launch,
)
from provider_execution.base import ProviderSubmission
from project.identity import normalize_work_dir


NOW = "2026-07-21T12:00:00Z"


def _ccb_session_file(
    root: Path,
    *,
    agent_name: str,
    work_dir: Path,
    ccb_session_id: str,
    project_id: str = "project-1",
) -> Path:
    path = root / f".kimi-{agent_name}-session"
    path.write_text(
        json.dumps(
            {
                "active": True,
                "agent_name": agent_name,
                "ccb_project_id": project_id,
                "ccb_session_id": ccb_session_id,
                "work_dir": str(work_dir),
                "work_dir_norm": normalize_work_dir(work_dir),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _native_wire(share_dir: Path, work_dir: Path, session_id: str) -> Path:
    path = share_dir / "sessions" / kimi_project_hash(work_dir) / session_id / "wire.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def _kimi_code_wire(code_home: Path, work_dir: Path, session_id: str, agent_id: str) -> Path:
    path = (
        code_home
        / "sessions"
        / kimi_code_project_dirname(work_dir)
        / session_id
        / "agents"
        / agent_id
        / "wire.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def _bind(
    session_file: Path,
    *,
    agent_name: str,
    work_dir: Path,
    share_dir: Path,
    ccb_session_id: str,
    native_session_id: str,
) -> Path:
    wire = _native_wire(share_dir, work_dir, native_session_id)
    ok, error = persist_native_session_binding(
        session_file,
        expected_ccb_session_id=ccb_session_id,
        agent_name=agent_name,
        work_dir=work_dir,
        share_dir=share_dir,
        native_session_id=native_session_id,
        native_session_path=wire,
        observed_at=NOW,
    )
    assert ok is True, error
    return wire


def test_observed_native_session_becomes_exact_resume_authority(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )

    assert binding == {
        "kimi_resume_status": "exact_session_ready",
        "kimi_resume_session_id": "native-one",
        "kimi_resume_session_path": str(wire),
        "kimi_resume_session_bound_at": NOW,
        "kimi_resume_binding_source": "native_req_id_observation",
    }


def test_kimi_code_observation_becomes_exact_resume_authority(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / ".kimi"
    code_home = tmp_path / ".kimi-code"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _kimi_code_wire(code_home, work_dir, "native-code-one", "main")

    ok, error = persist_native_session_binding(
        session_file,
        expected_ccb_session_id="ccb-launch-1",
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        code_home=code_home,
        native_session_id="native-code-one",
        native_session_path=wire,
        observed_at=NOW,
    )
    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
        code_home=code_home,
    )

    assert ok is True, error
    assert binding["kimi_resume_status"] == "exact_session_ready"
    assert binding["kimi_resume_session_id"] == "native-code-one"
    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["kimi_session_store"] == "kimi_code"
    assert persisted["kimi_code_home"] == str(code_home)


def test_kimi_code_binding_rejects_other_code_home_and_symlink(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / ".kimi"
    code_home = tmp_path / ".kimi-code"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _kimi_code_wire(code_home, work_dir, "native-code-one", "main")
    ok, error = persist_native_session_binding(
        session_file,
        expected_ccb_session_id="ccb-launch-1",
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        code_home=code_home,
        native_session_id="native-code-one",
        native_session_path=wire,
        observed_at=NOW,
    )
    assert ok is True, error

    changed = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
        code_home=tmp_path / "other-code-home",
    )
    assert changed == {"kimi_resume_status": "fresh_code_home_changed"}

    target = tmp_path / "wire-target.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    wire.unlink()
    wire.symlink_to(target)
    symlinked = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
        code_home=code_home,
    )
    assert symlinked == {"kimi_resume_status": "fresh_native_session_path_symlinked"}


def test_same_workdir_agents_keep_distinct_owned_session_ids(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    first = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    second = _ccb_session_file(
        tmp_path,
        agent_name="kimi2",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-2",
    )
    _bind(
        first,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    _bind(
        second,
        agent_name="kimi2",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-2",
        native_session_id="native-two",
    )

    first_binding = resume_binding_for_launch(
        first,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )
    second_binding = resume_binding_for_launch(
        second,
        agent_name="kimi2",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )

    assert first_binding["kimi_resume_session_id"] == "native-one"
    assert second_binding["kimi_resume_session_id"] == "native-two"


def test_ccb_launch_id_is_not_a_native_kimi_session_id(tmp_path: Path) -> None:
    session_file = tmp_path / ".kimi-kimi1-session"
    session = KimiProjectSession(
        session_file=session_file,
        data={"ccb_session_id": "ccb-launch-is-not-native"},
    )

    assert session.kimi_session_id == ""
    assert session.kimi_session_path == str(session_file)


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    (
        ("missing_native", "fresh_native_session_missing"),
        ("share_changed", "fresh_share_dir_changed"),
        ("work_dir_changed", "fresh_work_dir_mismatch"),
        ("agent_changed", "fresh_agent_mismatch"),
        ("project_changed", "fresh_project_mismatch"),
    ),
)
def test_invalid_or_mismatched_binding_fails_fresh(
    tmp_path: Path,
    mutation: str,
    expected_status: str,
) -> None:
    work_dir = tmp_path / "repo"
    other_work_dir = tmp_path / "other"
    work_dir.mkdir()
    other_work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    if mutation == "missing_native":
        wire.unlink()

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi-other" if mutation == "agent_changed" else "kimi1",
        project_id="project-other" if mutation == "project_changed" else "project-1",
        work_dir=other_work_dir if mutation == "work_dir_changed" else work_dir,
        share_dir=tmp_path / "other-share" if mutation == "share_changed" else share_dir,
    )

    assert binding == {"kimi_resume_status": expected_status}
    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["kimi_session_id"] == "native-one"


def test_malformed_session_record_fails_fresh(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    session_file = tmp_path / ".kimi-kimi1-session"
    session_file.write_text("{not-json\n", encoding="utf-8")

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=tmp_path / "share",
    )

    assert binding == {"kimi_resume_status": "fresh_invalid_session_record"}


def test_invalid_native_session_id_fails_fresh(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["kimi_session_id"] = "../escape"
    data["kimi_session_path"] = str(wire)
    session_file.write_text(json.dumps(data) + "\n", encoding="utf-8")

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )

    assert binding == {"kimi_resume_status": "fresh_native_session_id_invalid"}


def test_symlinked_native_session_layout_fails_fresh(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    target = tmp_path / "wire-target.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    wire.unlink()
    wire.symlink_to(target)

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )

    assert binding == {"kimi_resume_status": "fresh_native_session_path_symlinked"}


def test_alternate_symlink_path_to_expected_wire_fails_fresh(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    alias = tmp_path / "wire-alias.jsonl"
    alias.symlink_to(wire)
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["kimi_session_path"] = str(alias)
    session_file.write_text(json.dumps(data) + "\n", encoding="utf-8")

    binding = resume_binding_for_launch(
        session_file,
        agent_name="kimi1",
        project_id="project-1",
        work_dir=work_dir,
        share_dir=share_dir,
    )

    assert binding == {"kimi_resume_status": "fresh_native_session_path_symlinked"}


def test_stale_execution_cannot_rebind_new_launch_record(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-new",
    )
    wire = _native_wire(share_dir, work_dir, "native-old")

    ok, error = persist_native_session_binding(
        session_file,
        expected_ccb_session_id="ccb-launch-old",
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        native_session_id="native-old",
        native_session_path=wire,
        observed_at=NOW,
    )

    assert ok is False
    assert error == "ccb_launch_session_changed"
    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert "kimi_session_id" not in persisted


def test_restart_command_selects_validated_owned_session(monkeypatch, tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data.update(
        {
            "start_cmd": "export TEST=1; kimi --auto-approve  --skills-dir /tmp/skills",
            "kimi_restart_start_cmd_template": (
                f"export TEST=1; kimi --auto-approve {KIMI_RESTART_SESSION_MARKER} --skills-dir /tmp/skills"
            ),
            "kimi_capability_command_parts": ["kimi"],
        }
    )
    session_file.write_text(json.dumps(data) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "provider_backends.kimi.session.resolve_exact_resume_flag",
        lambda parts, environ: "--session",
    )
    session = KimiProjectSession(session_file=session_file, data=data)

    cmd = prepare_restart_start_cmd(session)

    assert cmd == "export TEST=1; kimi --auto-approve --session native-one --skills-dir /tmp/skills"
    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["start_cmd"] == cmd
    assert persisted["kimi_resume_status"] == "exact_session_selected"
    assert persisted["kimi_session_id"] == "native-one"


def test_restart_command_fails_fresh_when_owned_native_session_disappears(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data.update(
        {
            "start_cmd": "kimi",
            "kimi_restart_start_cmd_template": f"kimi {KIMI_RESTART_SESSION_MARKER}",
            "kimi_capability_command_parts": ["kimi"],
        }
    )
    session_file.write_text(json.dumps(data) + "\n", encoding="utf-8")
    wire.unlink()
    session = KimiProjectSession(session_file=session_file, data=data)

    cmd = prepare_restart_start_cmd(session)

    assert cmd == "kimi"
    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["kimi_resume_status"] == "fresh_native_session_missing"
    assert "kimi_session_id" not in persisted
    assert "kimi_session_path" not in persisted


def test_execution_observation_persists_binding_to_matching_launch(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    wire = _native_wire(share_dir, work_dir, "native-one")
    state: dict[str, object] = {
        "project_session_file": str(session_file),
        "ccb_launch_session_id": "ccb-launch-1",
        "kimi_share_dir": str(share_dir),
    }
    submission = ProviderSubmission(
        job_id="job-1",
        agent_name="kimi1",
        provider="kimi",
        accepted_at=NOW,
        ready_at=NOW,
        source_kind=CompletionSourceKind.SESSION_EVENT_LOG,
        reply="",
        runtime_state={},
    )
    observation = KimiTurnObservation(
        request_seen=True,
        completed=False,
        reply="",
        session_id="native-one",
        session_path=str(wire),
        provider_turn_ref="native-one",
        line_count=1,
    )

    _persist_observed_native_session(
        submission,
        state,
        observation,
        work_dir=work_dir,
        now=NOW,
    )

    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["kimi_session_id"] == "native-one"
    assert state["bound_native_session_id"] == "native-one"
    assert "kimi_session_binding_error" not in state


def test_later_observed_native_session_switch_rebinds_same_agent(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        tmp_path,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    first_wire = _native_wire(share_dir, work_dir, "native-one")
    second_wire = _native_wire(share_dir, work_dir, "native-two")
    state: dict[str, object] = {
        "project_session_file": str(session_file),
        "ccb_launch_session_id": "ccb-launch-1",
        "kimi_share_dir": str(share_dir),
    }
    submission = ProviderSubmission(
        job_id="job-1",
        agent_name="kimi1",
        provider="kimi",
        accepted_at=NOW,
        ready_at=NOW,
        source_kind=CompletionSourceKind.SESSION_EVENT_LOG,
        reply="",
        runtime_state={},
    )

    for session_id, wire in (("native-one", first_wire), ("native-two", second_wire)):
        _persist_observed_native_session(
            submission,
            state,
            KimiTurnObservation(
                request_seen=True,
                completed=False,
                reply="",
                session_id=session_id,
                session_path=str(wire),
                provider_turn_ref=session_id,
                line_count=1,
            ),
            work_dir=work_dir,
            now=NOW,
        )

    persisted = json.loads(session_file.read_text(encoding="utf-8"))
    assert persisted["kimi_session_id"] == "native-two"
    assert persisted["kimi_session_path"] == str(second_wire)
    assert state["bound_native_session_id"] == "native-two"


def test_prepare_launch_context_selects_only_valid_agent_binding(monkeypatch, tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    ccb_dir = work_dir / ".ccb"
    work_dir.mkdir()
    ccb_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        ccb_dir,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    paths = SimpleNamespace(
        ccb_dir=ccb_dir,
        agent_events_path=lambda name: ccb_dir / "agents" / name / "events.jsonl",
        agent_provider_state_dir=lambda name, provider: ccb_dir / "agents" / name / "provider-state" / provider,
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_id="project-1", project_root=work_dir),
        paths=paths,
    )
    spec = SimpleNamespace(name="kimi1", env={"KIMI_SHARE_DIR": str(share_dir)})
    plan = SimpleNamespace(workspace_path=work_dir)
    monkeypatch.setattr(
        "provider_backends.kimi.launcher._resolve_exact_resume_flag",
        lambda parts, environ: "--session",
    )

    prepared = prepare_launch_context(
        context,
        spec,
        plan,
        ccb_dir / "agents" / "kimi1" / "provider-runtime" / "kimi",
        {"run_cwd": str(work_dir)},
    )

    assert prepared["kimi_share_dir"] == str(share_dir)
    assert prepared["kimi_resume_status"] == "exact_session_ready"
    assert prepared["kimi_resume_session_id"] == "native-one"
    assert prepared["kimi_resume_flag"] == "--session"


def test_prepare_launch_context_fails_fresh_without_exact_session_capability(monkeypatch, tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    ccb_dir = work_dir / ".ccb"
    work_dir.mkdir()
    ccb_dir.mkdir()
    share_dir = tmp_path / "share"
    session_file = _ccb_session_file(
        ccb_dir,
        agent_name="kimi1",
        work_dir=work_dir,
        ccb_session_id="ccb-launch-1",
    )
    _bind(
        session_file,
        agent_name="kimi1",
        work_dir=work_dir,
        share_dir=share_dir,
        ccb_session_id="ccb-launch-1",
        native_session_id="native-one",
    )
    paths = SimpleNamespace(
        ccb_dir=ccb_dir,
        agent_events_path=lambda name: ccb_dir / "agents" / name / "events.jsonl",
        agent_provider_state_dir=lambda name, provider: ccb_dir / "agents" / name / "provider-state" / provider,
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_id="project-1", project_root=work_dir),
        paths=paths,
    )
    spec = SimpleNamespace(name="kimi1", env={"KIMI_SHARE_DIR": str(share_dir)})
    plan = SimpleNamespace(workspace_path=work_dir)
    monkeypatch.setattr(
        "provider_backends.kimi.launcher._resolve_exact_resume_flag",
        lambda parts, environ: None,
    )

    prepared = prepare_launch_context(
        context,
        spec,
        plan,
        ccb_dir / "agents" / "kimi1" / "provider-runtime" / "kimi",
        {"run_cwd": str(work_dir)},
    )

    assert prepared["kimi_resume_status"] == "fresh_exact_session_unsupported"
    assert "kimi_resume_session_id" not in prepared
    assert "kimi_resume_session_path" not in prepared


def test_kimi_share_dir_honors_explicit_store_and_home(tmp_path: Path) -> None:
    assert kimi_share_dir(environ={"KIMI_SHARE_DIR": str(tmp_path / "share")}) == tmp_path / "share"
    assert kimi_share_dir(environ={"HOME": str(tmp_path / "home")}) == tmp_path / "home" / ".kimi"


def test_prepare_launch_context_resolves_relative_share_against_agent_workdir(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    ccb_dir = work_dir / ".ccb"
    work_dir.mkdir()
    ccb_dir.mkdir()
    paths = SimpleNamespace(
        ccb_dir=ccb_dir,
        agent_events_path=lambda name: ccb_dir / "agents" / name / "events.jsonl",
        agent_provider_state_dir=lambda name, provider: ccb_dir / "agents" / name / "provider-state" / provider,
    )
    context = SimpleNamespace(
        project=SimpleNamespace(project_id="project-1", project_root=work_dir),
        paths=paths,
    )
    spec = SimpleNamespace(name="kimi1", env={"KIMI_SHARE_DIR": "relative-share"})

    prepared = prepare_launch_context(
        context,
        spec,
        SimpleNamespace(workspace_path=work_dir),
        ccb_dir / "agents" / "kimi1" / "provider-runtime" / "kimi",
        {"run_cwd": str(work_dir)},
    )

    assert prepared["kimi_share_dir"] == str(work_dir / "relative-share")
    assert prepared["kimi_resume_status"] == "fresh_no_binding"


@pytest.mark.parametrize(
    "parts",
    (
        ["kimi", "--session", "abc"],
        ["kimi", "--resume=abc"],
        ["kimi", "--continue"],
        ["kimi", "-S", "abc"],
        ["kimi", "-r", "abc"],
        ["kimi", "-C"],
        ["kimi", "-c", "legacy-or-prompt"],
    ),
)
def test_explicit_versioned_session_controls_are_fenced(parts: list[str]) -> None:
    assert _has_session_control(parts) is True


def test_exact_resume_capability_prefers_stable_long_session_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "provider_backends.kimi.session.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Options: --session,--resume TEXT", stderr=""),
    )

    assert _resolve_exact_resume_flag(["kimi"], environ={}) == "--session"


def test_exact_resume_capability_fails_closed_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "provider_backends.kimi.session.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Options: --continue", stderr=""),
    )

    assert _resolve_exact_resume_flag(["kimi"], environ={}) is None
