from __future__ import annotations

from pathlib import Path

from storage.path_helpers import (
    _account_home_dir,
    choose_runtime_state_placement,
    runtime_state_base_root,
    runtime_state_root_for_project,
)
from storage.paths import PathLayout


def _clear_relocation_env(monkeypatch) -> None:
    monkeypatch.delenv('CCB_RUNTIME_STATE_ANCHOR', raising=False)
    monkeypatch.delenv('CCB_RUNTIME_STATE_HOME', raising=False)
    monkeypatch.delenv('XDG_STATE_HOME', raising=False)


def _expected_base() -> Path:
    return _account_home_dir() / '.local' / 'ccb' / 'projects'


def test_runtime_state_base_root_defaults_to_local_ccb(monkeypatch) -> None:
    _clear_relocation_env(monkeypatch)
    assert runtime_state_base_root() == _expected_base()


def test_runtime_state_root_for_project_lands_under_local_ccb(monkeypatch) -> None:
    _clear_relocation_env(monkeypatch)
    assert runtime_state_root_for_project('proj-abc') == _expected_base() / 'proj-abc'


def test_choose_placement_relocates_by_default(monkeypatch, tmp_path: Path) -> None:
    _clear_relocation_env(monkeypatch)
    anchor = tmp_path / 'repo' / '.ccb'
    anchor.mkdir(parents=True)
    placement = choose_runtime_state_placement(
        project_root=tmp_path / 'repo',
        project_id='proj-abc',
        anchor_path=anchor,
    )
    assert placement.root_kind == 'relocated'
    assert placement.relocation_reason == 'default_relocate'
    assert placement.effective_path == _expected_base() / 'proj-abc'


def test_choose_placement_anchors_when_opt_in(monkeypatch, tmp_path: Path) -> None:
    _clear_relocation_env(monkeypatch)
    monkeypatch.setenv('CCB_RUNTIME_STATE_ANCHOR', '1')
    anchor = tmp_path / 'repo' / '.ccb'
    anchor.mkdir(parents=True)
    placement = choose_runtime_state_placement(
        project_root=tmp_path / 'repo',
        project_id='proj-abc',
        anchor_path=anchor,
    )
    assert placement.root_kind == 'project'
    assert placement.effective_path == anchor


def test_path_layout_routes_agent_state_under_local_ccb(monkeypatch, tmp_path: Path) -> None:
    _clear_relocation_env(monkeypatch)
    project_root = tmp_path / 'repo'
    project_root.mkdir()
    layout = PathLayout(project_root)
    assert layout.runtime_state_root != layout.ccb_dir
    assert str(layout.agents_dir).startswith(str(_expected_base()))
    # anchor-only entries stay under .ccb
    assert layout.ccb_dir == project_root / '.ccb'
    assert layout.config_path == project_root / '.ccb' / 'ccb.config'


def test_codex_auth_mode_defaults_to_symlink(monkeypatch) -> None:
    _clear_relocation_env(monkeypatch)
    monkeypatch.delenv('CCB_CODEX_AUTH_MODE', raising=False)
    from provider_profiles.codex_home_config import _codex_auth_mode

    assert _codex_auth_mode(None) == 'symlink'


def test_codex_auth_mode_respects_env(monkeypatch) -> None:
    _clear_relocation_env(monkeypatch)
    from provider_profiles.codex_home_config import _codex_auth_mode

    monkeypatch.setenv('CCB_CODEX_AUTH_MODE', 'copy')
    assert _codex_auth_mode(None) == 'copy'
    monkeypatch.setenv('CCB_CODEX_AUTH_MODE', 'none')
    assert _codex_auth_mode(None) == 'none'


def test_codex_auth_mode_respects_profile_env(monkeypatch) -> None:
    _clear_relocation_env(monkeypatch)
    monkeypatch.delenv('CCB_CODEX_AUTH_MODE', raising=False)
    from provider_profiles.codex_home_config import _codex_auth_mode
    from provider_profiles.models import ProviderProfileSpec

    assert _codex_auth_mode(ProviderProfileSpec(env={'CCB_CODEX_AUTH_MODE': 'copy'})) == 'copy'
    assert _codex_auth_mode(ProviderProfileSpec(env={'CCB_CODEX_AUTH_MODE': 'none'})) == 'none'
