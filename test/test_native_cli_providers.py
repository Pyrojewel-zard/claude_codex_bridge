from __future__ import annotations

from pathlib import Path
import shlex
from types import SimpleNamespace

from agents.models import (
    AgentSpec,
    PermissionMode,
    ProviderProfileSpec,
    QueuePolicy,
    RestoreMode,
    RuntimeMode,
    SkillOverlaySpec,
    WorkspaceMode,
)
from cli.models import ParsedStartCommand
from provider_backends.deepseek.launcher import build_start_cmd as build_deepseek_start_cmd
from provider_backends.kimi.launcher import (
    build_session_payload as build_kimi_session_payload,
    build_start_cmd as build_kimi_start_cmd,
)
from provider_backends.kimi.session import KIMI_RESTART_SESSION_MARKER
from provider_backends.kimi.skills import kimi_skill_dirs_for_launch, materialize_kimi_skills
from provider_backends.mimo.launcher import build_start_cmd as build_mimo_start_cmd


def _spec(
    name: str,
    provider: str,
    *,
    startup_args: tuple[str, ...] = (),
    provider_command_template: str | None = None,
    model: str | None = None,
    thinking: str | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec:
    return AgentSpec(
        name=name,
        provider=provider,
        target=".",
        workspace_mode=WorkspaceMode.GIT_WORKTREE,
        workspace_root=None,
        runtime_mode=RuntimeMode.PANE_BACKED,
        restore_default=RestoreMode.AUTO,
        permission_default=PermissionMode.MANUAL,
        queue_policy=QueuePolicy.SERIAL_PER_AGENT,
        startup_args=startup_args,
        provider_command_template=provider_command_template,
        model=model,
        thinking=thinking,
        env=env or {},
    )


def test_kimi_start_cmd_uses_env_override_and_auto_without_implicit_restore(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KIMI_START_CMD", "/tmp/stub-kimi --profile test")
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=True)
    spec = _spec("kimi_agent", "kimi", startup_args=("--model", "kimi-k2"))

    cmd = build_kimi_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert cmd.endswith("/tmp/stub-kimi --profile test --auto-approve --model kimi-k2")
    assert "--continue" not in cmd


def test_kimi_start_cmd_preserves_explicit_user_restore_and_does_not_duplicate_auto_flags(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=True)
    spec = _spec("kimi_agent", "kimi", startup_args=("--yolo", "--session", "abc"))

    cmd = build_kimi_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert cmd.endswith("kimi --yolo --session abc")
    assert "--auto-approve" not in cmd
    assert "--continue" not in cmd


def test_kimi_start_cmd_treats_legacy_auto_flag_as_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=True)
    spec = _spec("kimi_agent", "kimi", startup_args=("--auto", "--session", "abc"))

    cmd = build_kimi_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert cmd.endswith("kimi --auto --session abc")
    assert "--auto-approve" not in cmd
    assert "--continue" not in cmd


def test_kimi_start_cmd_resumes_only_the_prevalidated_exact_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=False)
    spec = _spec("kimi_agent", "kimi")
    prepared = {
        "kimi_resume_flag": "--session",
        "kimi_resume_session_id": "session-owned-by-kimi-agent",
        "kimi_resume_session_path": str(tmp_path / "wire.jsonl"),
        "kimi_resume_status": "exact_session_ready",
    }

    cmd = build_kimi_start_cmd(
        command,
        spec,
        tmp_path / "runtime",
        "launch-2",
        prepared_state=prepared,
    )

    command_parts = shlex.split(cmd.rsplit("; ", 1)[-1])
    assert command_parts[-2:] == [
        "--session",
        "session-owned-by-kimi-agent",
    ]
    assert command_parts.count("--session") == 1
    assert "--continue" not in cmd
    assert prepared["kimi_resume_status"] == "exact_session_selected"
    assert KIMI_RESTART_SESSION_MARKER not in cmd
    assert prepared["kimi_restart_start_cmd_template"].count(KIMI_RESTART_SESSION_MARKER) == 1
    assert prepared["kimi_capability_command_parts"] == ["kimi"]


def test_kimi_explicit_session_control_wins_over_owned_resume(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=False)
    spec = _spec("kimi_agent", "kimi", startup_args=("--continue",))
    prepared = {
        "kimi_resume_flag": "--session",
        "kimi_resume_session_id": "session-owned-by-kimi-agent",
        "kimi_resume_status": "exact_session_ready",
    }

    cmd = build_kimi_start_cmd(
        command,
        spec,
        tmp_path / "runtime",
        "launch-3",
        prepared_state=prepared,
    )

    parts = shlex.split(cmd.rsplit("; ", 1)[-1])
    assert parts.count("--continue") == 1
    assert "--session" not in parts
    assert prepared["kimi_resume_status"] == "explicit_session_control"


def test_kimi_exact_selector_survives_provider_command_template_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=True, auto_permission=False)
    spec = _spec(
        "kimi_agent",
        "kimi",
        provider_command_template="env KIMI_WRAPPED=1 {command}",
    )
    prepared = {
        "kimi_resume_flag": "--session",
        "kimi_resume_session_id": "native-owned-session",
        "kimi_resume_status": "exact_session_ready",
    }

    cmd = build_kimi_start_cmd(
        command,
        spec,
        tmp_path / "runtime",
        "launch-template",
        prepared_state=prepared,
    )

    parts = shlex.split(cmd.rsplit("; ", 1)[-1])
    assert parts == ["env", "KIMI_WRAPPED=1", "kimi", "--session", "native-owned-session"]
    assert prepared["kimi_restart_start_cmd_template"].count(KIMI_RESTART_SESSION_MARKER) == 1


def test_kimi_clear_reset_discards_carried_automatic_resume(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=False, auto_permission=False)
    spec = _spec("kimi_agent", "kimi")
    prepared = {
        "kimi_resume_flag": "--session",
        "kimi_resume_session_id": "session-owned-by-kimi-agent",
        "kimi_resume_status": "exact_session_ready",
    }

    cmd = build_kimi_start_cmd(
        command,
        spec,
        tmp_path / "runtime",
        "launch-reset",
        prepared_state=prepared,
    )

    assert "--session" not in shlex.split(cmd.rsplit("; ", 1)[-1])
    assert "--continue" not in cmd
    assert prepared["kimi_resume_status"] == "fresh_restore_disabled"


def test_kimi_session_payload_retains_only_selected_exact_binding(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    context = SimpleNamespace(project=SimpleNamespace(project_id="project-1", project_root=project))
    spec = _spec("kimi_agent", "kimi")
    plan = SimpleNamespace(workspace_path=project)
    prepared = {
        "kimi_share_dir": str(tmp_path / "share"),
        "kimi_resume_session_id": "session-owned-by-kimi-agent",
        "kimi_resume_session_path": str(tmp_path / "share" / "sessions" / "hash" / "session-owned-by-kimi-agent" / "wire.jsonl"),
        "kimi_resume_status": "exact_session_selected",
    }

    payload = build_kimi_session_payload(
        context=context,
        spec=spec,
        plan=plan,
        runtime_dir=tmp_path / "runtime",
        run_cwd=project,
        pane_id="%1",
        pane_title_marker="marker",
        start_cmd="kimi --session session-owned-by-kimi-agent",
        launch_session_id="launch-4",
        prepared_state=prepared,
    )

    assert payload["kimi_share_dir"] == str(tmp_path / "share")
    assert payload["kimi_session_id"] == "session-owned-by-kimi-agent"
    assert payload["kimi_session_path"] == prepared["kimi_resume_session_path"]
    assert payload["kimi_resume_status"] == "exact_session_selected"
    assert payload["kimi_restart_start_cmd_template"] == ""
    assert payload["kimi_capability_command_parts"] == []


def test_kimi_start_cmd_adds_materialized_skill_dirs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("KIMI_START_CMD", raising=False)
    home = tmp_path / "home"
    project = tmp_path / "repo"
    workspace = project / "pkg"
    state_dir = tmp_path / "provider-state" / "kimi"
    project_skill_dir = project / ".kimi" / "skills"
    user_skill_dir = home / ".kimi" / "skills"
    ccb_skill_dir = state_dir / "inherited-skills"
    for path in (project / ".git", workspace, project_skill_dir, user_skill_dir, ccb_skill_dir):
        path.mkdir(parents=True)
    command = ParsedStartCommand(project=None, agent_names=("kimi_agent",), restore=False, auto_permission=False)
    spec = _spec("kimi_agent", "kimi", startup_args=("--model", "kimi-k2"))

    cmd = build_kimi_start_cmd(
        command,
        spec,
        tmp_path / "runtime",
        "launch-1",
        prepared_state={
            "kimi_skill_dirs": [
                str(path)
                for path in kimi_skill_dirs_for_launch(
                    project_root=project,
                    workspace_path=workspace,
                    state_dir=state_dir,
                    env={"HOME": str(home)},
                )
            ]
        },
    )

    parts = shlex.split(cmd)
    kimi_index = parts.index("kimi")
    assert parts[kimi_index : kimi_index + 7] == [
        "kimi",
        "--skills-dir",
        str(project_skill_dir),
        "--skills-dir",
        str(user_skill_dir),
        "--skills-dir",
        str(ccb_skill_dir),
    ]
    assert parts[-2:] == ["--model", "kimi-k2"]


def test_materialize_kimi_skills_projects_skill_overlays(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    state_dir = tmp_path / "provider-state" / "kimi"
    overlay_source = tmp_path / "codex-skills"
    project.mkdir(parents=True)
    for skill_name in ("trellis-check", "trellis-start", "unrelated"):
        skill_dir = overlay_source / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"{skill_name}\n", encoding="utf-8")

    active_dirs = materialize_kimi_skills(
        project_root=project,
        agent_name="agent1",
        state_dir=state_dir,
        profile=ProviderProfileSpec(
            inherit_skills=False,
            skill_overlays={
                "n14_trellis": SkillOverlaySpec(
                    source=str(overlay_source),
                    include=("trellis-*",),
                ),
            },
        ),
    )

    overlay_dir = state_dir / "overlay-skills"
    assert overlay_dir in active_dirs
    assert (overlay_dir / "trellis-check" / "SKILL.md").read_text(encoding="utf-8") == "trellis-check\n"
    assert (overlay_dir / "trellis-start" / "SKILL.md").read_text(encoding="utf-8") == "trellis-start\n"
    assert (overlay_dir / "trellis-check.ccb-projection.json").is_file()
    assert (overlay_dir / "trellis-start.ccb-projection.json").is_file()
    assert not (overlay_dir / "unrelated").exists()


def test_materialize_kimi_skills_preserves_unmarked_packaged_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    packaged = tmp_path / 'packaged-kimi-skills'
    (packaged / 'ask').mkdir(parents=True)
    (packaged / 'ask' / 'SKILL.md').write_text('packaged\n', encoding='utf-8')
    state_dir = tmp_path / 'provider-state' / 'kimi'
    inherited_dir = state_dir / 'inherited-skills'
    (inherited_dir / 'user-skill').mkdir(parents=True)
    (inherited_dir / 'user-skill' / 'SKILL.md').write_text('user\n', encoding='utf-8')
    monkeypatch.setattr(
        'provider_core.inherited_skills.packaged_inherited_skills_dir',
        lambda provider: packaged,
    )

    active_dirs = materialize_kimi_skills(
        project_root=None,
        agent_name='agent1',
        state_dir=state_dir,
        profile=ProviderProfileSpec(inherit_skills=True),
    )

    assert inherited_dir not in active_dirs
    assert (inherited_dir / 'user-skill' / 'SKILL.md').read_text(encoding='utf-8') == 'user\n'
    assert not (inherited_dir / 'ask').exists()
    assert not Path(f'{inherited_dir}.ccb-projection.json').exists()


def test_deepseek_start_cmd_defaults_to_deepcode_and_keeps_startup_args(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEEPSEEK_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("deep_agent",), restore=True, auto_permission=True)
    spec = _spec("deep_agent", "deepseek", startup_args=("--raw",))

    cmd = build_deepseek_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert cmd.endswith("deepcode --raw")


def test_deepseek_start_cmd_supports_env_override_and_template(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEEPSEEK_START_CMD", "/tmp/deepcode --config demo")
    command = ParsedStartCommand(project=None, agent_names=("deep_agent",), restore=False, auto_permission=False)
    spec = _spec("deep_agent", "deepseek", provider_command_template="sandbox=1 {command}")

    cmd = build_deepseek_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert cmd.endswith("sandbox=1 /tmp/deepcode --config demo")


def test_deepseek_start_cmd_compiles_model_and_thinking_to_deepcode_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEEPSEEK_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("deep_agent",), restore=False, auto_permission=False)
    spec = _spec(
        "deep_agent",
        "deepseek",
        model="deepseek-v4-pro",
        thinking="max",
    )

    cmd = build_deepseek_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert "DEEPCODE_MODEL=deepseek-v4-pro" in cmd
    assert "DEEPCODE_THINKING_ENABLED=true" in cmd
    assert "DEEPCODE_REASONING_EFFORT=max" in cmd
    assert cmd.endswith("deepcode")


def test_deepseek_start_cmd_compiles_thinking_off_without_effort(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEEPSEEK_START_CMD", raising=False)
    command = ParsedStartCommand(project=None, agent_names=("deep_agent",), restore=False, auto_permission=False)
    spec = _spec(
        "deep_agent",
        "deepseek",
        model="deepseek-v4-flash",
        thinking="off",
    )

    cmd = build_deepseek_start_cmd(command, spec, tmp_path / "runtime", "launch-1")

    assert "DEEPCODE_MODEL=deepseek-v4-flash" in cmd
    assert "DEEPCODE_THINKING_ENABLED=false" in cmd
    assert "DEEPCODE_REASONING_EFFORT" not in cmd


def test_mimo_start_cmd_uses_managed_home_config_and_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MIMO_START_CMD", "/tmp/stub-mimo --provider mimo")
    runtime_dir = tmp_path / "runtime"
    state_dir = tmp_path / "provider-state" / "mimo"
    config_path = state_dir / "mimocode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    command = ParsedStartCommand(project=None, agent_names=("mimo_agent",), restore=True, auto_permission=False)
    spec = _spec("mimo_agent", "mimo", startup_args=("--model", "mimo-auto"))

    cmd = build_mimo_start_cmd(
        command,
        spec,
        runtime_dir,
        "launch-1",
        prepared_state={
            "mimo_home": str(state_dir / "home"),
            "mimo_config_path": str(config_path),
        },
    )

    assert "MIMOCODE_HOME=" + str(state_dir / "home") in cmd
    assert "MIMOCODE_CONFIG=" + str(config_path) in cmd
    assert "MIMOCODE_DISABLE_AUTOUPDATE=true" in cmd
    assert "MIMOCODE_ENABLE_ANALYSIS=false" in cmd
    parts = shlex.split(cmd.rsplit("; ", 1)[-1])
    mimo_index = parts.index("/tmp/stub-mimo")
    assert parts[mimo_index : mimo_index + 5] == [
        "/tmp/stub-mimo",
        "--provider",
        "mimo",
        "--continue",
        "--model",
    ]
