from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalize_arch_maps_common_aliases() -> None:
    module = _load_module()

    assert module.normalize_arch("amd64") == "x86_64"
    assert module.normalize_arch("x86_64") == "x86_64"
    assert module.normalize_arch("arm64") == "aarch64"
    assert module.normalize_arch("aarch64") == "aarch64"


def test_release_identity_requires_matching_package_version_and_unique_manifest(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "package.json").write_text(json.dumps({"version": "8.1.5"}), encoding="utf-8")
    manifest = tmp_path / "releases.json"
    manifest.write_text(json.dumps({"releases": [{"version": "8.1.4", "commit": "oldbuild"}]}), encoding="utf-8")

    module.validate_release_identity(
        repo_root,
        version="8.1.5",
        commit="newbuild",
        release_manifest=manifest,
    )

    manifest.write_text(json.dumps({"releases": [{"version": "8.1.5", "commit": "oldbuild"}]}), encoding="utf-8")
    try:
        module.validate_release_identity(
            repo_root,
            version="8.1.5",
            commit="newbuild",
            release_manifest=manifest,
        )
    except RuntimeError as exc:
        assert "collision" in str(exc)
    else:
        raise AssertionError("expected a release manifest collision")


def test_release_identity_allows_exact_checked_out_release_tag(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "VERSION").write_text("8.1.5\n", encoding="utf-8")
    (repo_root / "package.json").write_text(json.dumps({"version": "8.1.5"}), encoding="utf-8")
    _git(repo_root, "add", "VERSION", "package.json")
    _git(repo_root, "commit", "-m", "release")
    _git(repo_root, "tag", "v8.1.5")

    commit, _date = module.resolve_git_metadata(repo_root, git_ref="HEAD")

    module.validate_release_identity(repo_root, version="8.1.5", commit=commit, git_ref="HEAD")


def test_release_identity_rejects_same_version_tag_on_different_commit(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "VERSION").write_text("8.1.5\n", encoding="utf-8")
    (repo_root / "package.json").write_text(json.dumps({"version": "8.1.5"}), encoding="utf-8")
    _git(repo_root, "add", "VERSION", "package.json")
    _git(repo_root, "commit", "-m", "tagged release")
    _git(repo_root, "tag", "v8.1.5")
    (repo_root / "note.txt").write_text("next commit\n", encoding="utf-8")
    _git(repo_root, "add", "note.txt")
    _git(repo_root, "commit", "-m", "different build")

    commit, _date = module.resolve_git_metadata(repo_root, git_ref="HEAD")

    try:
        module.validate_release_identity(repo_root, version="8.1.5", commit=commit, git_ref="HEAD")
    except RuntimeError as exc:
        assert "different commit" in str(exc)
    else:
        raise AssertionError("expected a release tag collision")


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True, text=True)


def test_copy_repo_tree_excludes_runtime_state(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    destination = tmp_path / "out"
    (repo_root / ".git").mkdir(parents=True)
    (repo_root / ".ccb" / "ccbd").mkdir(parents=True)
    (repo_root / ".ccb-requests").mkdir(parents=True)
    (repo_root / ".loop").mkdir(parents=True)
    (repo_root / ".architec").mkdir(parents=True)
    (repo_root / ".tmp_pytest" / "run").mkdir(parents=True)
    (repo_root / ".tmp_test_env_arch1" / "env").mkdir(parents=True)
    (repo_root / "dev_tools" / "skills").mkdir(parents=True)
    (repo_root / "tools" / "ccb-agent-sidebar" / "target" / "debug").mkdir(parents=True)
    (repo_root / "tools" / "ccb-rs-helper" / "target" / "debug").mkdir(parents=True)
    (repo_root / "mobile" / "app" / ".dart_tool" / "flutter_build").mkdir(parents=True)
    (repo_root / "mobile" / "app" / ".gradle" / "caches").mkdir(parents=True)
    (repo_root / "mobile" / "app" / ".idea" / "libraries").mkdir(parents=True)
    (repo_root / "mobile" / "app" / "build" / "app" / "outputs").mkdir(parents=True)
    (repo_root / "mobile" / "app" / "node_modules" / "pkg").mkdir(parents=True)
    (repo_root / "dist-mobile").mkdir(parents=True)
    (repo_root / "inherit_skills" / "codex_skills" / "ask").mkdir(parents=True)
    (repo_root / "inherit_skills" / "claude_skills" / "ask").mkdir(parents=True)
    (repo_root / "inherit_skills" / "grok_skills" / "ask").mkdir(parents=True)
    (repo_root / "useful_tools" / "codex_skills" / "plan-tree").mkdir(parents=True)
    (repo_root / "useful_tools" / "claude_skills" / "plan-tree").mkdir(parents=True)
    (repo_root / "roles" / "ccb.archi").mkdir(parents=True)
    (repo_root / "lib").mkdir(parents=True)
    (repo_root / "ccb").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (repo_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo_root / "lib" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (repo_root / ".ccb" / "ccbd" / "lease.json").write_text("{}", encoding="utf-8")
    (repo_root / ".ccb-requests" / "job_1.md").write_text("queued", encoding="utf-8")
    (repo_root / ".loop" / "state.json").write_text("{}", encoding="utf-8")
    (repo_root / ".architec" / "summary.json").write_text("{}", encoding="utf-8")
    (repo_root / ".tmp_pytest" / "run" / "state.json").write_text("{}", encoding="utf-8")
    (repo_root / ".tmp_test_env_arch1" / "env" / "state.json").write_text("{}", encoding="utf-8")
    (repo_root / "dev_tools" / "skills" / "README.md").write_text("dev only\n", encoding="utf-8")
    (repo_root / "tools" / "ccb-agent-sidebar" / "target" / "debug" / "ccb-agent-sidebar").write_text(
        "build output\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "ccb-rs-helper" / "target" / "debug" / "ccb-rs-helper").write_text(
        "build output\n",
        encoding="utf-8",
    )
    (repo_root / "mobile" / "app" / ".dart_tool" / "flutter_build" / "app.dill").write_text(
        "flutter build cache\n",
        encoding="utf-8",
    )
    (repo_root / "mobile" / "app" / ".gradle" / "caches" / "state.bin").write_text(
        "gradle cache\n",
        encoding="utf-8",
    )
    (repo_root / "mobile" / "app" / ".idea" / "libraries" / "workspace.xml").write_text(
        "ide metadata\n",
        encoding="utf-8",
    )
    (repo_root / "mobile" / "app" / "build" / "app" / "outputs" / "app-debug.apk").write_text(
        "mobile build output\n",
        encoding="utf-8",
    )
    (repo_root / "mobile" / "app" / "node_modules" / "pkg" / "index.js").write_text(
        "dependency cache\n",
        encoding="utf-8",
    )
    (repo_root / "dist-mobile" / "ccb-mobile.apk").write_text("mobile artifact\n", encoding="utf-8")
    (repo_root / "inherit_skills" / "codex_skills" / "ask" / "SKILL.md").write_text("ask\n", encoding="utf-8")
    (repo_root / "inherit_skills" / "claude_skills" / "ask" / "SKILL.md").write_text("ask\n", encoding="utf-8")
    (repo_root / "inherit_skills" / "grok_skills" / "ask" / "SKILL.md").write_text("ask\n", encoding="utf-8")
    (repo_root / "useful_tools" / "codex_skills" / "plan-tree" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (repo_root / "useful_tools" / "claude_skills" / "plan-tree" / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (repo_root / "roles" / "ccb.archi" / "role.toml").write_text('schema = "rolepack/v1"\n', encoding="utf-8")

    module.copy_repo_tree(repo_root, destination)

    assert (destination / "lib" / "app.py").exists()
    assert (destination / "inherit_skills" / "codex_skills" / "ask" / "SKILL.md").exists()
    assert (destination / "inherit_skills" / "claude_skills" / "ask" / "SKILL.md").exists()
    assert (destination / "inherit_skills" / "grok_skills" / "ask" / "SKILL.md").exists()
    assert (destination / "useful_tools" / "codex_skills" / "plan-tree" / "SKILL.md").exists()
    assert (destination / "useful_tools" / "claude_skills" / "plan-tree" / "SKILL.md").exists()
    assert not (destination / "roles").exists()
    assert not (destination / ".git").exists()
    assert not (destination / ".ccb").exists()
    assert not (destination / ".ccb-requests").exists()
    assert not (destination / ".loop").exists()
    assert not (destination / ".architec").exists()
    assert not (destination / ".tmp_pytest").exists()
    assert not (destination / ".tmp_test_env_arch1").exists()
    assert not (destination / "dev_tools").exists()
    assert not (destination / "tools" / "ccb-agent-sidebar" / "target").exists()
    assert not (destination / "tools" / "ccb-rs-helper" / "target").exists()
    assert not (destination / "mobile" / "app" / ".dart_tool").exists()
    assert not (destination / "mobile" / "app" / ".gradle").exists()
    assert not (destination / "mobile" / "app" / ".idea").exists()
    assert not (destination / "mobile" / "app" / "build").exists()
    assert not (destination / "mobile" / "app" / "node_modules").exists()
    assert not (destination / "dist-mobile").exists()


def test_copy_repo_tree_excludes_generated_output_subtree_inside_repo(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    output_dir = repo_root / "dist-macos-smoke"
    destination = output_dir / ".stage-ccb-macos-universal" / "ccb-macos-universal"
    (repo_root / ".git").mkdir(parents=True)
    (repo_root / "lib").mkdir(parents=True)
    (repo_root / "lib" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (output_dir / "old-build" / "stale.txt").parent.mkdir(parents=True)
    (output_dir / "old-build" / "stale.txt").write_text("stale\n", encoding="utf-8")

    module.copy_repo_tree(
        repo_root,
        destination,
        generated_paths=(output_dir, destination.parent, output_dir / "SHA256SUMS"),
    )

    assert (destination / "lib" / "app.py").exists()
    assert not (destination / "dist-macos-smoke").exists()


def test_copy_repo_tree_excludes_generated_stage_when_output_dir_is_repo_root(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    stage_root = repo_root / ".stage-ccb-linux-x86_64"
    destination = stage_root / "ccb-linux-x86_64"
    (repo_root / ".git").mkdir(parents=True)
    (repo_root / "lib").mkdir(parents=True)
    (repo_root / "lib" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (stage_root / "stale.txt").parent.mkdir(parents=True)
    (stage_root / "stale.txt").write_text("stale\n", encoding="utf-8")

    module.copy_repo_tree(
        repo_root,
        destination,
        generated_paths=(repo_root, stage_root, repo_root / "ccb-linux-x86_64.tar.gz", repo_root / "SHA256SUMS"),
    )

    assert (destination / "lib" / "app.py").exists()
    assert not (destination / ".stage-ccb-linux-x86_64").exists()


def test_dirty_worktree_entries_reads_porcelain_output(monkeypatch) -> None:
    module = _load_module()

    def _fake_run(cmd, **kwargs):
        assert cmd[-2:] == ["--porcelain", "--untracked-files=all"]
        return SimpleNamespace(returncode=0, stdout=" M install.sh\n?? scripts/build_linux_release.py\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    entries = module.dirty_worktree_entries(Path("/tmp/repo"))

    assert entries == (" M install.sh", "?? scripts/build_linux_release.py")


def test_dirty_worktree_entries_ignores_excluded_local_metadata(monkeypatch) -> None:
    module = _load_module()

    def _fake_run(cmd, **kwargs):
        assert cmd[-2:] == ["--porcelain", "--untracked-files=all"]
        return SimpleNamespace(
            returncode=0,
            stdout="?? .gemini/settings.json\n?? .ccb-requests/job_1.md\n M install.sh\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    entries = module.dirty_worktree_entries(Path("/tmp/repo"))

    assert entries == (" M install.sh",)


def test_dirty_worktree_entries_ignores_excluded_codex_local_metadata(monkeypatch) -> None:
    module = _load_module()

    def _fake_run(cmd, **kwargs):
        assert cmd[-2:] == ["--porcelain", "--untracked-files=all"]
        return SimpleNamespace(
            returncode=0,
            stdout="?? .codex\n M install.sh\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    entries = module.dirty_worktree_entries(Path("/tmp/repo"))

    assert entries == (" M install.sh",)


def test_dirty_worktree_entries_ignores_excluded_temp_env_prefix(monkeypatch) -> None:
    module = _load_module()

    def _fake_run(cmd, **kwargs):
        assert cmd[-2:] == ["--porcelain", "--untracked-files=all"]
        return SimpleNamespace(
            returncode=0,
            stdout="?? .tmp_test_env_arch1/runtime/state.json\n M install.sh\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    entries = module.dirty_worktree_entries(Path("/tmp/repo"))

    assert entries == (" M install.sh",)


def test_dirty_worktree_entries_ignores_dev_tools(monkeypatch) -> None:
    module = _load_module()

    def _fake_run(cmd, **kwargs):
        assert cmd[-2:] == ["--porcelain", "--untracked-files=all"]
        return SimpleNamespace(
            returncode=0,
            stdout="?? dev_tools/skills/ccb-github/SKILL.md\n M install.sh\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    entries = module.dirty_worktree_entries(Path("/tmp/repo"))

    assert entries == (" M install.sh",)


def test_ensure_clean_worktree_raises_on_dirty(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "dirty_worktree_entries",
        lambda repo_root: (" M install.sh", "?? scripts/build_linux_release.py"),
    )

    try:
        module.ensure_clean_worktree(Path("/tmp/repo"))
    except RuntimeError as exc:
        text = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "dirty worktree" in text
    assert "install.sh" in text


def test_export_release_tree_uses_git_archive_when_clean(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    destination = tmp_path / "out"
    repo_root.mkdir()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(module, "is_git_checkout", lambda path: True)
    monkeypatch.setattr(module, "ensure_clean_worktree", lambda path: calls.append(("clean", path)))
    monkeypatch.setattr(
        module,
        "export_git_archive",
        lambda path, dest, *, git_ref: calls.append(("archive", path, dest, git_ref)),
    )
    monkeypatch.setattr(module, "copy_repo_tree", lambda path, dest: calls.append(("copy", path, dest)))

    module.export_release_tree(repo_root, destination, git_ref="HEAD", allow_dirty=False)

    assert calls == [
        ("clean", repo_root),
        ("archive", repo_root, destination, "HEAD"),
    ]


def test_export_release_tree_allows_dirty_preview(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    destination = tmp_path / "out"
    repo_root.mkdir()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(module, "is_git_checkout", lambda path: True)
    monkeypatch.setattr(
        module,
        "copy_repo_tree",
        lambda path, dest, *, generated_paths=None: calls.append(("copy", path, dest, generated_paths)),
    )
    monkeypatch.setattr(module, "ensure_clean_worktree", lambda path: calls.append(("clean", path)))
    monkeypatch.setattr(
        module,
        "export_git_archive",
        lambda path, dest, *, git_ref: calls.append(("archive", path, dest, git_ref)),
    )

    generated_paths = (repo_root / "dist",)

    module.export_release_tree(
        repo_root,
        destination,
        git_ref="HEAD",
        allow_dirty=True,
        generated_paths=generated_paths,
    )

    assert calls == [("copy", repo_root, destination, generated_paths)]


def test_build_sidebar_helper_for_release_copies_real_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-agent-sidebar"
    output_bin = artifact_root / "bin" / "ccb-agent-sidebar"
    crate_dir.mkdir(parents=True)
    output_bin.parent.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-agent-sidebar"\n', encoding="utf-8")
    output_bin.write_text("#!/usr/bin/env bash\n# CCB_AGENT_SIDEBAR_WRAPPER\n", encoding="utf-8")
    output_bin.chmod(0o755)

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["cargo", "build", "--release"]
        built = crate_dir / "target" / "release" / "ccb-agent-sidebar"
        built.parent.mkdir(parents=True)
        built.write_text("#!/usr/bin/env bash\necho release-sidebar\n", encoding="utf-8")
        built.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_sidebar_helper_for_release(artifact_root)

    assert output_bin.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho release-sidebar\n"
    assert os.access(output_bin, os.X_OK)
    assert not (crate_dir / "target").exists()


def test_build_sidebar_helper_for_release_builds_macos_universal_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-agent-sidebar"
    output_bin = artifact_root / "bin" / "ccb-agent-sidebar"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-agent-sidebar"\n', encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:3] == ["cargo", "build", "--release"]:
            target = cmd[cmd.index("--target") + 1]
            built = crate_dir / "target" / target / "release" / "ccb-agent-sidebar"
            built.parent.mkdir(parents=True)
            built.write_text(f"{target}\n", encoding="utf-8")
            built.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["lipo", "-create", "-output", str(output_bin)]:
            output_bin.parent.mkdir(parents=True, exist_ok=True)
            output_bin.write_text("universal-sidebar\n", encoding="utf-8")
            output_bin.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:1] == ["file"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{output_bin}: Mach-O universal binary with 2 architectures\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_sidebar_helper_for_release(artifact_root, target_platform="macos")

    assert any("--target" in call and "x86_64-apple-darwin" in call for call in calls)
    assert any("--target" in call and "aarch64-apple-darwin" in call for call in calls)
    assert any(call[:4] == ["lipo", "-create", "-output", str(output_bin)] for call in calls)
    assert output_bin.read_text(encoding="utf-8") == "universal-sidebar\n"
    assert os.access(output_bin, os.X_OK)
    assert not (crate_dir / "target").exists()


def test_build_sidebar_helper_for_release_fails_when_cargo_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-agent-sidebar"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-agent-sidebar"\n', encoding="utf-8")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="cargo failed"),
    )

    try:
        module.build_sidebar_helper_for_release(artifact_root)
    except RuntimeError as exc:
        text = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "failed to build ccb-agent-sidebar" in text
    assert "cargo failed" in text


def test_build_rs_helper_for_release_copies_real_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-rs-helper"
    output_bin = artifact_root / "bin" / "ccb-rs-helper"
    crate_dir.mkdir(parents=True)
    output_bin.parent.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-rs-helper"\n', encoding="utf-8")
    output_bin.write_text("#!/usr/bin/env bash\n# CCB_RS_HELPER_WRAPPER\n", encoding="utf-8")
    output_bin.chmod(0o755)

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["cargo", "build", "--release"]
        built = crate_dir / "target" / "release" / "ccb-rs-helper"
        built.parent.mkdir(parents=True)
        built.write_text("#!/usr/bin/env bash\necho release-rs-helper\n", encoding="utf-8")
        built.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_rs_helper_for_release(artifact_root)

    assert output_bin.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho release-rs-helper\n"
    assert os.access(output_bin, os.X_OK)
    assert not (crate_dir / "target").exists()


def test_build_rs_helper_for_release_builds_macos_universal_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-rs-helper"
    output_bin = artifact_root / "bin" / "ccb-rs-helper"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-rs-helper"\n', encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:3] == ["cargo", "build", "--release"]:
            target = cmd[cmd.index("--target") + 1]
            built = crate_dir / "target" / target / "release" / "ccb-rs-helper"
            built.parent.mkdir(parents=True)
            built.write_text(f"{target}\n", encoding="utf-8")
            built.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["lipo", "-create", "-output", str(output_bin)]:
            output_bin.parent.mkdir(parents=True, exist_ok=True)
            output_bin.write_text("universal-rs-helper\n", encoding="utf-8")
            output_bin.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:1] == ["file"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{output_bin}: Mach-O universal binary with 2 architectures\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_rs_helper_for_release(artifact_root, target_platform="macos")

    assert any("--target" in call and "x86_64-apple-darwin" in call for call in calls)
    assert any("--target" in call and "aarch64-apple-darwin" in call for call in calls)
    assert any(call[:4] == ["lipo", "-create", "-output", str(output_bin)] for call in calls)
    assert output_bin.read_text(encoding="utf-8") == "universal-rs-helper\n"
    assert os.access(output_bin, os.X_OK)
    assert not (crate_dir / "target").exists()


def test_build_rs_helper_for_release_fails_when_cargo_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    crate_dir = artifact_root / "tools" / "ccb-rs-helper"
    crate_dir.mkdir(parents=True)
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-rs-helper"\n', encoding="utf-8")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="cargo failed"),
    )

    try:
        module.build_rs_helper_for_release(artifact_root)
    except RuntimeError as exc:
        text = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "failed to build ccb-rs-helper" in text
    assert "cargo failed" in text


def test_build_runtime_accelerator_for_release_copies_real_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    workspace_dir = artifact_root / "rust"
    crate_dir = workspace_dir / "crates" / "ccb-runtime-accelerator"
    output_bin = artifact_root / "bin" / "ccb-runtime-accelerator"
    crate_dir.mkdir(parents=True)
    output_bin.parent.mkdir(parents=True)
    (workspace_dir / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/ccb-runtime-accelerator"]\n', encoding="utf-8")
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-runtime-accelerator"\n', encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["cargo", "build", "--release"]
        assert "-p" in cmd and "ccb-runtime-accelerator" in cmd
        built = workspace_dir / "target" / "release" / "ccb-runtime-accelerator"
        built.parent.mkdir(parents=True)
        built.write_text("#!/usr/bin/env bash\necho runtime-accelerator\n", encoding="utf-8")
        built.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_runtime_accelerator_for_release(artifact_root)

    assert output_bin.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho runtime-accelerator\n"
    assert os.access(output_bin, os.X_OK)
    assert not (workspace_dir / "target").exists()


def test_build_runtime_accelerator_for_release_builds_macos_universal_binary(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    workspace_dir = artifact_root / "rust"
    crate_dir = workspace_dir / "crates" / "ccb-runtime-accelerator"
    output_bin = artifact_root / "bin" / "ccb-runtime-accelerator"
    crate_dir.mkdir(parents=True)
    (workspace_dir / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/ccb-runtime-accelerator"]\n', encoding="utf-8")
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-runtime-accelerator"\n', encoding="utf-8")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:3] == ["cargo", "build", "--release"]:
            target = cmd[cmd.index("--target") + 1]
            built = workspace_dir / "target" / target / "release" / "ccb-runtime-accelerator"
            built.parent.mkdir(parents=True)
            built.write_text(f"{target}\n", encoding="utf-8")
            built.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:4] == ["lipo", "-create", "-output", str(output_bin)]:
            output_bin.parent.mkdir(parents=True, exist_ok=True)
            output_bin.write_text("universal-runtime-accelerator\n", encoding="utf-8")
            output_bin.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:1] == ["file"]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{output_bin}: Mach-O universal binary with 2 architectures\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    module.build_runtime_accelerator_for_release(artifact_root, target_platform="macos")

    assert any("--target" in call and "x86_64-apple-darwin" in call for call in calls)
    assert any("--target" in call and "aarch64-apple-darwin" in call for call in calls)
    assert any(call[:4] == ["lipo", "-create", "-output", str(output_bin)] for call in calls)
    assert output_bin.read_text(encoding="utf-8") == "universal-runtime-accelerator\n"
    assert os.access(output_bin, os.X_OK)
    assert not (workspace_dir / "target").exists()


def test_build_runtime_accelerator_for_release_fails_when_cargo_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    artifact_root = tmp_path / "artifact"
    workspace_dir = artifact_root / "rust"
    crate_dir = workspace_dir / "crates" / "ccb-runtime-accelerator"
    crate_dir.mkdir(parents=True)
    (workspace_dir / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/ccb-runtime-accelerator"]\n', encoding="utf-8")
    (crate_dir / "Cargo.toml").write_text('[package]\nname = "ccb-runtime-accelerator"\n', encoding="utf-8")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="cargo failed"),
    )

    try:
        module.build_runtime_accelerator_for_release(artifact_root)
    except RuntimeError as exc:
        text = str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert "failed to build ccb-runtime-accelerator" in text
    assert "cargo failed" in text


def test_resolve_version_prefers_git_ref_snapshot(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    (repo_root / "VERSION").write_text("worktree-version\n", encoding="utf-8")

    def _fake_read_git_file(path, *, git_ref, relative_path):
        if relative_path == "VERSION":
            return "gitref-version\n"
        return ""

    monkeypatch.setattr(module, "read_git_file", _fake_read_git_file)

    version = module.resolve_version(repo_root, git_ref="v5.2.8")

    assert version == "gitref-version"


def test_create_tarball_includes_legacy_update_alias(tmp_path: Path) -> None:
    module = _load_module()
    stage_root = tmp_path / "stage"
    artifact_root = stage_root / "ccb-linux-x86_64"
    artifact_root.mkdir(parents=True)
    (artifact_root / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    artifact_path = tmp_path / "ccb-linux-x86_64.tar.gz"

    module.create_tarball(stage_root=stage_root, artifact_root=artifact_root, artifact_path=artifact_path)

    with tarfile.open(artifact_path, "r:gz") as archive:
        install_member = archive.getmember("ccb-linux-x86_64/install.sh")
        alias_member = archive.getmember("ccb-linux-x86_64.tar.gz")

    assert install_member.isfile()
    assert alias_member.issym()
    assert alias_member.linkname == "ccb-linux-x86_64"
