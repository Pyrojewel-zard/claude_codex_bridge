from __future__ import annotations

import json
import shlex
from pathlib import Path
from types import SimpleNamespace

from provider_backends.pi import launcher
from provider_backends.pi.session import (
    PiProjectSession,
    persist_native_session_binding,
    resume_binding_for_launch,
    validate_native_session_binding,
)


def _pi_file(root: Path, *, session_id: str, cwd: Path) -> Path:
    path = root / f"2026-08-08T00-00-00-000Z_{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "session",
                "version": 3,
                "id": session_id,
                "timestamp": "2026-08-08T00:00:00.000Z",
                "cwd": str(cwd),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _ccb_record(path: Path, *, ccb_session_id: str, work_dir: Path, **extra: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ccb_session_id": ccb_session_id,
                "agent_name": "pi1",
                "ccb_project_id": "project-1",
                "work_dir": str(work_dir),
                **extra,
            }
        ),
        encoding="utf-8",
    )


def test_pi_resume_binding_requires_matching_managed_session_header(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(
        ccb_file,
        ccb_session_id="ccb-launch-1",
        work_dir=work_dir,
        pi_session_id=native_id,
        pi_session_path=str(native_path),
    )

    binding = resume_binding_for_launch(
        ccb_file,
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
    )

    assert binding["pi_resume_status"] == "exact_session_ready"
    assert binding["pi_resume_session_id"] == native_id
    assert binding["pi_resume_session_path"] == str(native_path)

    native_path.write_text(native_path.read_text(encoding="utf-8").replace(str(work_dir), str(tmp_path / "other")), encoding="utf-8")
    invalid = resume_binding_for_launch(
        ccb_file,
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
    )
    assert invalid["pi_resume_status"] == "fresh_native_work_dir_mismatch"


def test_legacy_ccb_record_discovers_latest_valid_pi_session(tmp_path: Path) -> None:
    import os

    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    older_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    newer_id = "019fdd1e-a08d-75b6-a64f-6ce980692624"
    older_path = _pi_file(session_dir, session_id=older_id, cwd=work_dir)
    newer_path = _pi_file(session_dir, session_id=newer_id, cwd=work_dir)
    os.utime(older_path, (10, 10))
    os.utime(newer_path, (20, 20))
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(
        ccb_file,
        ccb_session_id="ccb-new-launch",
        work_dir=work_dir,
        pi_session_id="ccb-old-launch",
    )

    binding = resume_binding_for_launch(
        ccb_file,
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
    )

    assert binding["pi_resume_status"] == "exact_session_ready"
    assert binding["pi_resume_session_id"] == newer_id
    assert binding["pi_resume_session_path"] == str(newer_path)
    assert binding["pi_resume_binding_source"] == "legacy_native_session_discovery"


def test_legacy_record_with_native_id_but_missing_path_discovers_pi_session(tmp_path: Path) -> None:
    import os

    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    newer_path = _pi_file(
        session_dir,
        session_id="019fdd1e-a08d-75b6-a64f-6ce980692624",
        cwd=work_dir,
    )
    os.utime(native_path, (10, 10))
    os.utime(newer_path, (20, 20))
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(
        ccb_file,
        ccb_session_id="ccb-launch-1",
        work_dir=work_dir,
        pi_session_id=native_id,
    )

    binding = resume_binding_for_launch(
        ccb_file,
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
    )

    assert binding["pi_resume_status"] == "exact_session_ready"
    assert binding["pi_resume_session_id"] == native_id
    assert binding["pi_resume_session_path"] == str(native_path)


def test_legacy_ccb_id_ignores_stale_path_and_discovers_native_session(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(
        ccb_file,
        ccb_session_id="ccb-launch-1",
        work_dir=work_dir,
        pi_session_id="ccb-old-launch",
        pi_session_path=str(native_path),
    )

    binding = resume_binding_for_launch(
        ccb_file,
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
    )

    assert binding["pi_resume_status"] == "exact_session_ready"
    assert binding["pi_resume_session_id"] == native_id
    assert binding["pi_resume_session_path"] == str(native_path)
    assert binding["pi_resume_binding_source"] == "legacy_native_session_discovery"


def test_pi_persists_observed_native_session_only_for_current_ccb_launch(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(ccb_file, ccb_session_id="ccb-launch-1", work_dir=work_dir)

    ok, error = persist_native_session_binding(
        ccb_file,
        expected_ccb_session_id="ccb-launch-1",
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
        native_session_id=native_id,
        native_session_path=native_path,
        observed_at="2026-08-08T00:00:01Z",
    )

    assert (ok, error) == (True, None)
    data = json.loads(ccb_file.read_text(encoding="utf-8"))
    assert data["pi_session_id"] == native_id
    assert data["pi_session_path"] == str(native_path)
    assert data["pi_resume_status"] == "exact_session_bound"

    stale, reason = persist_native_session_binding(
        ccb_file,
        expected_ccb_session_id="ccb-launch-2",
        agent_name="pi1",
        project_id="project-1",
        work_dir=work_dir,
        session_dir=session_dir,
        native_session_id=native_id,
        native_session_path=native_path,
        observed_at="2026-08-08T00:00:02Z",
    )
    assert stale is False
    assert reason == "ccb_launch_session_changed"


def test_pi_native_binding_rejects_wrong_project(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(ccb_file, ccb_session_id="ccb-launch-1", work_dir=work_dir)

    ok, reason = persist_native_session_binding(
        ccb_file,
        expected_ccb_session_id="ccb-launch-1",
        agent_name="pi1",
        project_id="different-project",
        work_dir=work_dir,
        session_dir=session_dir,
        native_session_id=native_id,
        native_session_path=native_path,
        observed_at="2026-08-08T00:00:01Z",
    )

    assert ok is False
    assert reason == "project_mismatch"


def test_pi_restart_command_selects_exact_session_and_falls_back_safely(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    session_dir = tmp_path / "state with space" / "sessions"
    native_id = "019fdd2b-8362-7958-9e85-d0a5eed17084"
    native_path = _pi_file(session_dir, session_id=native_id, cwd=work_dir)
    ccb_file = tmp_path / ".ccb" / ".pi-pi1-session"
    _ccb_record(
        ccb_file,
        ccb_session_id="ccb-launch-1",
        work_dir=work_dir,
        pi_session_id=native_id,
        pi_session_path=str(native_path),
    )
    session = PiProjectSession(
        session_file=ccb_file,
        data={
            "ccb_session_id": "ccb-launch-1",
            "agent_name": "pi1",
            "ccb_project_id": "project-1",
            "work_dir": str(work_dir),
            "pi_session_dir": str(session_dir),
            "pi_restart_start_cmd_template": "pi --session-dir managed __CCB_PI_EXACT_SESSION_6E9A2F41__",
            "start_cmd": "pi --session-dir managed",
        },
    )

    assert session.provider_name == "pi"
    assert session.provider_session_id == "ccb-launch-1"
    assert session.pi_session_path == ""
    restored = session.start_cmd

    assert shlex.split(restored) == ["pi", "--session-dir", "managed", "--session", str(native_path)]
    assert json.loads(ccb_file.read_text(encoding="utf-8"))["pi_resume_status"] == "exact_session_selected"


def test_pi_launcher_injects_exact_session_path_only_for_restore(monkeypatch, tmp_path: Path) -> None:
    marker = launcher.PI_RESTART_SESSION_MARKER
    original_materialize = launcher._materialize_completion_extension
    original_build = launcher.build_native_start_cmd
    launcher._materialize_completion_extension = lambda *args, **kwargs: None
    launcher.build_native_start_cmd = lambda *args, **kwargs: f"pi --session-dir managed {marker}"
    try:
        command = SimpleNamespace(restore=True)
        spec = SimpleNamespace(startup_args=())
        prepared = {
            "pi_resume_status": "exact_session_ready",
            "pi_resume_session_path": str(tmp_path / "session.jsonl"),
        }
        exact = launcher._build_start_cmd(
            launcher._launch_config(),
            command,
            spec,
            tmp_path,
            "ccb-launch-2",
            prepared_state=prepared,
        )
        assert exact == f"pi --session-dir managed --session {tmp_path / 'session.jsonl'}"

        fresh = launcher._build_start_cmd(
            launcher._launch_config(),
            command,
            spec,
            tmp_path,
            "ccb-launch-3",
            prepared_state={"pi_resume_status": "fresh_no_binding"},
        )
        assert fresh == "pi --session-dir managed"
    finally:
        launcher._materialize_completion_extension = original_materialize
        launcher.build_native_start_cmd = original_build


def test_pi_launcher_does_not_inject_resume_for_explicit_session_control() -> None:
    args = launcher._pi_visible_args(
        {
            "pi_state_dir": "/tmp/ccb-pi-state",
            "pi_completion_extension": "/tmp/ccb-pi-extension.ts",
            "pi_explicit_session_control": True,
        }
    )
    assert "__CCB_PI_EXACT_SESSION_6E9A2F41__" not in args


def test_pi_launcher_preserves_explicit_session_control(monkeypatch, tmp_path: Path) -> None:
    marker = launcher.PI_RESTART_SESSION_MARKER
    original_materialize = launcher._materialize_completion_extension
    original_build = launcher.build_native_start_cmd
    launcher._materialize_completion_extension = lambda *args, **kwargs: None
    launcher.build_native_start_cmd = lambda *args, **kwargs: f"pi --resume user-session"
    try:
        prepared = {
            "pi_resume_status": "exact_session_ready",
            "pi_resume_session_path": str(tmp_path / "managed session.jsonl"),
        }
        command = SimpleNamespace(restore=True)
        spec = SimpleNamespace(startup_args=("--resume", "user-session"))
        command_line = launcher._build_start_cmd(
            launcher._launch_config(),
            command,
            spec,
            tmp_path,
            "ccb-launch-3",
            prepared_state=prepared,
        )
        assert command_line == "pi --resume user-session"
        assert prepared["pi_resume_status"] == "explicit_session_control"
        assert prepared["pi_explicit_session_control"] is True
        assert marker not in command_line
    finally:
        launcher._materialize_completion_extension = original_materialize
        launcher.build_native_start_cmd = original_build


def test_validate_pi_session_rejects_path_outside_managed_session_dir(tmp_path: Path) -> None:
    work_dir = tmp_path / "workspace"
    managed = tmp_path / "managed" / "sessions"
    outside = _pi_file(tmp_path / "outside", session_id="native-session", cwd=work_dir)

    valid, reason = validate_native_session_binding(
        session_id="native-session",
        session_path=outside,
        work_dir=work_dir,
        session_dir=managed,
    )

    assert valid is False
    assert reason == "native_session_path_mismatch"
