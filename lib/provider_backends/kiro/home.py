"""Kiro provider isolated HOME projection.

The CCB runtime launches each kiro agent under an isolated HOME (see
``lib/provider_backends/native_cli_support/launcher.py``) so that multiple
agents on the same provider do not fight over ``~/.kiro/sessions/`` or share
the same conversation history. Without any seeding, however, the isolated HOME
is an empty directory: kiro-cli then reports "not logged in" and — on macOS —
triggers a Keychain authorisation prompt the first time it tries to read or
write ``kirocli:social:token``.

This module mirrors the pattern used by ``claude/launcher_runtime/home.py``,
scaled down to what kiro actually needs:

* create ``<HOME>/.kiro/{sessions,settings}`` so kiro can start writing
  session state inside the isolated tree (session isolation is intentional —
  we do **not** copy the user's real ``~/.kiro/sessions/``);
* copy the user's ``~/.kiro/settings/*.json`` (CLI preferences) into the
  isolated ``settings/`` directory so per-user options survive;
* on macOS, symlink ``~/Library/Keychains`` into the isolated HOME so
  kiro-cli sees the existing ``kirocli:social:token`` item and skips both
  the login prompt and the "new application wants to access your keychain"
  system dialog.

The materialize function is idempotent: it may run on every agent launch.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from provider_core.source_home import current_provider_source_home


_KIRO_INHERITED_SETTINGS = ("cli.json", "survey_state.json")


def managed_kiro_home_for_runtime(runtime_dir: Path) -> Path:
    """Return the isolated HOME directory kiro should run under.

    Mirrors ``managed_droid_home_for_runtime``: the CCB provider-state layout
    stores per-agent provider data under
    ``.ccb/agents/<agent>/provider-state/kiro/home``. When a ``runtime_dir``
    already lives inside a ``provider-runtime`` tree we resolve back to that
    canonical location; otherwise we fall back to a sibling ``kiro-home``
    directory next to the runtime dir.
    """

    runtime_dir = Path(runtime_dir).expanduser()
    if runtime_dir.parent.name == "provider-runtime":
        return runtime_dir.parent.parent / "provider-state" / "kiro" / "home"
    return runtime_dir / "kiro-home"


def materialize_kiro_home_config(
    target_home: Path,
    *,
    profile=None,
    source_home: Path | None = None,
) -> Path:
    """Populate the isolated kiro HOME from the user's real HOME.

    Steps:

    1. ensure ``<target_home>/.kiro/{sessions,settings}`` exist;
    2. copy inherited settings files (``cli.json`` etc.) if the source has
       them and the isolated tree does not carry a fresher user-authored
       copy (a plain per-file copy is used — kiro settings are user-scoped
       preferences, not per-conversation state, so it is safe to share);
    3. on macOS, mount the user's ``~/Library/Keychains`` as a symlink so
       kiro-cli can read/write ``kirocli:social:token`` without triggering
       a "new application" Keychain authorisation prompt.

    All disk operations are best-effort: a missing source is skipped, and
    unexpected errors are swallowed so a bad seed does not abort the agent
    launch (the user can still log in manually inside the pane if projection
    fails).
    """

    del profile  # reserved for future per-profile knobs (inherit_settings etc.)
    target_home = Path(target_home).expanduser()
    source_root = (
        Path(source_home).expanduser() if source_home is not None else _system_home_root()
    )

    target_home.mkdir(parents=True, exist_ok=True)
    target_kiro_dir = target_home / ".kiro"
    target_kiro_dir.mkdir(parents=True, exist_ok=True)
    (target_kiro_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (target_kiro_dir / "settings").mkdir(parents=True, exist_ok=True)

    if target_home.resolve() == source_root.resolve():
        # Running against the real user HOME: nothing to project.
        return target_home

    _materialize_settings(source_root, target_kiro_dir)
    _materialize_macos_keychains_link(source_root, target_home)
    return target_home


def _system_home_root() -> Path:
    if os.environ.get("CCB_SOURCE_HOME"):
        return current_provider_source_home()
    return Path.home().expanduser()


def _materialize_settings(source_home: Path, target_kiro_dir: Path) -> None:
    source_settings = source_home / ".kiro" / "settings"
    if not source_settings.is_dir():
        return
    target_settings = target_kiro_dir / "settings"
    for name in _KIRO_INHERITED_SETTINGS:
        src = source_settings / name
        if not src.is_file():
            continue
        dst = target_settings / name
        try:
            shutil.copy2(src, dst)
        except Exception:
            # Best-effort; kiro-cli can re-create defaults if seeding fails.
            pass


def _materialize_macos_keychains_link(source_home: Path, target_home: Path) -> None:
    """Symlink ``~/Library/Keychains`` into the isolated HOME on macOS.

    kiro-cli stores its login token as a Keychain item
    (``kirocli:social:token``). macOS considers a Keychain access "new"
    whenever the calling app runs under a HOME whose ``Library/Keychains``
    it has not previously touched, which triggers the authorisation
    prompt. Mounting the real keychain directory as a symlink lets
    kiro-cli see the item the user already authorised, so the prompt does
    not fire again on every agent restart.

    Non-Darwin platforms and missing source directories are ignored.
    """

    if platform.system() != "Darwin":
        return
    source_keychains = source_home / "Library" / "Keychains"
    if not source_keychains.is_dir():
        return
    target_library = target_home / "Library"
    target_keychains = target_library / "Keychains"
    try:
        target_library.mkdir(parents=True, exist_ok=True)
        if target_keychains.is_symlink():
            try:
                if target_keychains.resolve() == source_keychains.resolve():
                    return
            except Exception:
                pass
            target_keychains.unlink()
        elif target_keychains.exists():
            # A real directory already lives here (e.g. previous partial
            # projection); leave it alone rather than clobbering user data.
            return
        target_keychains.symlink_to(source_keychains, target_is_directory=True)
    except Exception:
        pass


__all__ = [
    "managed_kiro_home_for_runtime",
    "materialize_kiro_home_config",
]
