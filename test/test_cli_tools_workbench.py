from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import sys
import zipfile

import pytest

from cli.tools_runtime import cmd_tools
from cli.tools_runtime import workbench as workbench_tools
from terminal_runtime.ui_theme import theme_config_path


def _fake_executable(path: Path, text: str = '#!/usr/bin/env sh\nexit 0\n') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o755)
    return path


def _prepare_env(tmp_path: Path, monkeypatch) -> Path:
    fake_bin = tmp_path / 'fake-bin'
    for name in (
        'yazi',
        'ya',
        'wezterm',
        'python3',
        'chafa',
        'pdfinfo',
        'pdftotext',
        'pdftoppm',
        'ffprobe',
        'ffmpeg',
    ):
        _fake_executable(fake_bin / name)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg-config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg-data'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg-state'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))
    monkeypatch.setenv('CODEX_BIN_DIR', str(tmp_path / 'global-bin'))
    monkeypatch.setenv('PATH', str(fake_bin))
    monkeypatch.setenv('TERM', 'xterm-256color')
    monkeypatch.setenv('TERM_PROGRAM', 'WezTerm')
    monkeypatch.setenv('CCB_RICH_DOWNLOAD_BINARIES', '0')
    fake_proc = tmp_path / 'fake-proc'
    (fake_proc / 'sys' / 'fs' / 'inotify').mkdir(parents=True)
    (fake_proc / 'sys' / 'fs' / 'inotify' / 'max_user_instances').write_text('1024\n', encoding='utf-8')
    monkeypatch.setenv('CCB_WORKBENCH_PROC_ROOT', str(fake_proc))
    monkeypatch.delenv('CCB_WORKBENCH_THEME', raising=False)
    monkeypatch.delenv('CCB_WORKBENCH_THEME_CONFIG_WINDOWS', raising=False)
    monkeypatch.delenv('CCB_TMUX_THEME_PROFILE', raising=False)
    monkeypatch.delenv('CCB_SIDEBAR_THEME_PROFILE', raising=False)
    monkeypatch.delenv('TMUX', raising=False)
    return fake_bin


def test_workbench_install_writes_independent_bundle_profiles(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)

    result = workbench_tools.provision_workbench(profile='rich')

    root = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench'
    assert result['status'] == 'ok'
    assert result['profile'] == 'rich'
    assert result['enabled'] is False
    assert root.exists()
    assert (root / 'manifest.json').is_file()
    assert (root / 'bin' / 'ccb-workbench').is_file()
    assert (root / 'bin' / 'ccb-yazi').is_file()
    assert (root / 'bin' / 'ccb-yazi-rich').is_file()
    assert (root / 'bin' / 'ccb-md-preview').is_file()
    assert (root / 'bin' / 'ccb-image-preview').is_file()
    assert (root / 'bin' / 'ccb-pdf-preview').is_file()
    assert (root / 'bin' / 'ccb-video-preview').is_file()
    assert (root / 'profiles' / 'yazi-safe' / 'yazi.toml').is_file()
    assert (root / 'profiles' / 'yazi-rich' / 'yazi.toml').is_file()
    assert (root / 'profiles' / 'yazi-safe' / 'plugins' / 'piper.yazi' / 'main.lua').is_file()
    assert (root / 'profiles' / 'yazi-rich' / 'plugins' / 'piper.yazi' / 'main.lua').is_file()
    assert (root / 'profiles' / 'wezterm' / 'wezterm.lua').is_file()
    assert theme_config_path() == tmp_path / 'xdg-config' / 'ccb' / 'theme.json'
    theme_config = json.loads(theme_config_path().read_text(encoding='utf-8'))
    assert theme_config['theme'] == 'dark'
    assert theme_config['palette'] == 'dark'
    assert theme_config['tmux_profile'] == 'default'
    assert (tmp_path / 'global-bin' / 'ccb-workbench').exists()
    assert (tmp_path / 'global-bin' / 'ccb-yazi').exists()
    assert (tmp_path / 'global-bin' / 'ccb-yazi-rich').exists()
    assert (tmp_path / 'global-bin' / 'ccb-image-preview').exists()
    assert not (tmp_path / 'home' / '.config' / 'yazi').exists()
    assert not (tmp_path / 'home' / '.config' / 'wezterm').exists()

    safe_config = (root / 'profiles' / 'yazi-safe' / 'yazi.toml').read_text(encoding='utf-8')
    rich_config = (root / 'profiles' / 'yazi-rich' / 'yazi.toml').read_text(encoding='utf-8')
    assert 'piper -- "' in safe_config
    assert '*.png' in safe_config
    assert 'ccb-image-preview' in safe_config
    assert 'previewers = [' in safe_config
    assert 'preloaders = []' in safe_config
    assert 'prepend_preloaders' not in safe_config
    assert 'ratio = [0, 4, 3]' not in safe_config
    assert '*.pdf' in safe_config
    assert '*.mp4' in safe_config
    assert 'ratio = [0, 4, 3]' in rich_config
    assert '*.png' not in rich_config
    assert 'ccb-image-preview' not in rich_config
    assert 'run = "image"' in rich_config
    assert 'mime = "application/pdf"' in rich_config
    assert 'run = "pdf"' in rich_config
    assert 'mime = "video/*"' in rich_config
    assert 'run = "video"' in rich_config
    assert '*.mp4' not in rich_config
    wezterm_config = (root / 'profiles' / 'wezterm' / 'wezterm.lua').read_text(encoding='utf-8')
    assert 'config.warn_about_missing_glyphs = false' in wezterm_config
    assert 'config.use_ime = true' in wezterm_config
    assert 'config.xim_im_name = xim_im_name' in wezterm_config
    assert 'config.font = wezterm.font_with_fallback' in wezterm_config
    assert 'JetBrains Mono' in wezterm_config
    assert 'Fira Code' in wezterm_config
    assert 'Noto Sans Mono CJK SC' in wezterm_config
    assert 'Noto Sans Symbols2' in wezterm_config
    assert 'Symbols Nerd Font Mono' in wezterm_config
    assert 'Symbols Nerd Font' in wezterm_config
    assert 'Unifont CSUR' in wezterm_config
    assert 'Segoe UI Emoji' in wezterm_config
    assert 'weight = "Regular"' not in wezterm_config
    assert 'config.harfbuzz_features = { "calt=0", "clig=0", "liga=0" }' in wezterm_config
    assert 'config.font_size = 10.5' in wezterm_config
    assert 'config.line_height = 1.05' in wezterm_config
    assert 'config.initial_cols = 132' in wezterm_config
    assert 'config.initial_rows = 38' in wezterm_config
    assert 'config.automatically_reload_config = true' in wezterm_config
    assert 'local theme_config_paths = {' in wezterm_config
    assert 'local theme_config_path = theme_config_paths[1]' in wezterm_config
    assert 'wezterm.add_to_config_reload_watch_list(theme_config_path)' in wezterm_config
    assert 'local themes = {' in wezterm_config
    assert 'ansi = { "#3b4252"' in wezterm_config
    assert 'brights = { "#4c566a"' in wezterm_config
    assert 'latte = {' in wezterm_config
    assert 'solarized_light = {' in wezterm_config
    assert 'tokyo_night_light = {' in wezterm_config
    assert 'gruvbox_light = {' in wezterm_config
    assert 'rose_pine_dawn = {' in wezterm_config
    assert 'local function normalize_theme(value)' in wezterm_config
    assert 'local function system_theme()' in wezterm_config
    assert 'wezterm.gui.get_appearance' in wezterm_config
    assert 'local function read_theme_file(path)' in wezterm_config
    assert 'local requested_theme = read_theme_file(theme_config_path) or os.getenv("CCB_WORKBENCH_THEME")' in wezterm_config
    assert 'config.enable_tab_bar = false' in wezterm_config
    assert 'config.window_padding = {' in wezterm_config
    assert 'config.hide_tab_bar_if_only_one_tab = true' in wezterm_config
    assert 'ansi = theme.ansi' in wezterm_config
    assert 'brights = theme.brights' in wezterm_config
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM = "WezTerm"' in wezterm_config
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM_VERSION = wezterm.version' in wezterm_config
    assert 'CCB_WORKBENCH_THEME = theme_name' in wezterm_config
    assert 'CCB_TMUX_THEME_PROFILE = theme.tmux_profile' in wezterm_config
    assert 'CCB_SIDEBAR_THEME_PROFILE = theme.tmux_profile' in wezterm_config
    assert 'default_cwd' not in wezterm_config
    assert 'return config' in wezterm_config
    wrapper = (root / 'bin' / 'ccb-yazi-rich').read_text(encoding='utf-8')
    assert 'YAZI_CONFIG_HOME=' in wrapper
    assert 'CCB_WORKBENCH_FORCE_RICH' in wrapper
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM' in wrapper
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM_VERSION' in wrapper
    assert 'export TERM_PROGRAM="${CCB_WORKBENCH_TERMINAL_PROGRAM}"' in wrapper
    assert 'export TERM_PROGRAM_VERSION="${CCB_WORKBENCH_TERMINAL_PROGRAM_VERSION}"' in wrapper
    assert str(tmp_path / 'home' / '.config') not in wrapper
    workbench = (root / 'bin' / 'ccb-workbench').read_text(encoding='utf-8')
    assert 'WEZTERM_PANE' in workbench
    assert 'reuse_current_wezterm=0' in workbench
    assert 'current_workbench_root="${CCB_WORKBENCH_ROOT:-}"' in workbench
    assert 'current_workbench_profile="$(printf \'%s\' "${CCB_WORKBENCH_PROFILE:-}"' in workbench
    assert '"$wezterm_bin" cli spawn --cwd "$PWD" -- env' in workbench
    assert '"$wezterm_bin" --config-file' in workbench
    assert 'find_windows_wezterm()' in workbench
    assert 'wsl.exe -d "$WSL_DISTRO_NAME" --cd "$PWD"' in workbench
    assert '--config-file' in workbench
    assert 'start --always-new-process --no-auto-connect --cwd "$PWD"' in workbench
    assert ' --skip-config' not in workbench
    assert 'start -n ' not in workbench
    assert str(root / 'profiles' / 'wezterm' / 'wezterm.lua') in workbench
    assert 'CCB_WORKBENCH_FORCE_RICH=1' in workbench
    assert 'normalize_workbench_theme()' in workbench
    assert 'detect_system_workbench_theme()' in workbench
    assert 'theme_config_file=' in workbench
    assert 'read_workbench_theme_config()' in workbench
    assert 'requested_theme="$(read_workbench_theme_config)"' in workbench
    assert 'requested_theme="${CCB_WORKBENCH_THEME:-${CCB_TMUX_THEME_PROFILE:-}}"' in workbench
    assert 'available_themes: dark latte solarized_light tokyo_night_light gruvbox_light rose_pine_dawn' not in workbench
    assert 'ccb-tmux-on.sh >/dev/null 2>&1 || true' not in workbench
    assert 'CCB_WORKBENCH_THEME="$workbench_theme"' in workbench
    assert 'CCB_TMUX_THEME_PROFILE="$workbench_tmux_theme"' in workbench
    assert 'CCB_SIDEBAR_THEME_PROFILE="$workbench_tmux_theme"' in workbench
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM=WezTerm' in workbench
    assert 'configure_wayland_cursor_env()' in workbench
    assert '[ "${is_wsl:-0}" = 0 ] || return 0' in workbench
    assert 'CCB_WORKBENCH_XCURSOR_COMPAT=1' in workbench
    assert "XMODIFIERS='@im=fcitx'" in workbench
    assert 'GTK_IM_MODULE=fcitx' in workbench
    assert 'QT_IM_MODULE=fcitx' in workbench
    assert "XMODIFIERS='@im=ibus'" in workbench
    assert 'CCB_WORKBENCH_TERMINAL_PROGRAM_VERSION="${TERM_PROGRAM_VERSION:-}"' not in workbench
    assert 'ccb-workbench terminal requires WezTerm or Windows wezterm.exe under WSL' in workbench
    assert 'set -- "${SHELL:-/bin/sh}" -lc' in workbench
    assert '-u TMUX' in workbench
    assert '-u TMUX_PANE' in workbench
    assert '-u CCB_TMUX_SOCKET' in workbench
    assert '-u CCB_TMUX_SOCKET_PATH' in workbench
    md_preview = (root / 'bin' / 'ccb-md-preview').read_text(encoding='utf-8')
    assert 'color_system="256"' in md_preview
    assert 'color_system="256color"' not in md_preview
    assert 'text = path.read_text' in md_preview
    assert 'sys.stdout.write(text)' in md_preview
    image_preview = (root / 'bin' / 'ccb-image-preview').read_text(encoding='utf-8')
    assert '--format=symbols' not in image_preview
    assert '--probe=off' not in image_preview
    assert 'Inline image preview requires the rich Yazi profile' in image_preview

    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['schema_version'] == 1
    assert manifest['components']['yazi']['status'] == 'ok'
    assert manifest['components']['wezterm']['status'] == 'ok'
    assert 'neovim' not in manifest['components']
    assert manifest['components']['markdown']['status'] == 'ok'
    assert manifest['components']['image_preview']['status'] == 'ok'


def test_workbench_wezterm_config_watches_native_windows_theme_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _prepare_env(tmp_path, monkeypatch)
    windows_theme_path = (
        r'\\wsl.localhost\Ubuntu\home\bfly\.config\ccb\theme.json'
    )
    monkeypatch.setenv(
        'CCB_WORKBENCH_THEME_CONFIG_WINDOWS',
        windows_theme_path,
    )

    workbench_tools.provision_workbench(profile='rich')

    wezterm_config = (
        tmp_path
        / 'xdg-data'
        / 'ccb'
        / 'tools'
        / 'workbench'
        / 'profiles'
        / 'wezterm'
        / 'wezterm.lua'
    ).read_text(encoding='utf-8')
    escaped_windows_path = windows_theme_path.replace('\\', '\\\\')
    assert f'"{escaped_windows_path}"' in wezterm_config
    assert 'wezterm.add_to_config_reload_watch_list(theme_config_path)' in wezterm_config


def test_workbench_doctor_reports_manifest_and_component_paths(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    stdout = StringIO()
    stderr = StringIO()

    code = cmd_tools(['doctor', 'workbench', '--profile', 'rich'], stdout=stdout, stderr=stderr)

    output = stdout.getvalue()
    assert code == 0
    assert stderr.getvalue() == ''
    assert 'workbench_status: ok' in output
    assert 'profile: rich' in output
    assert 'yazi_status: ok' in output
    assert 'wezterm_status: ok' in output
    assert 'neovim' not in output.lower()
    assert 'yazi_safe_config:' in output
    assert 'wezterm_config:' in output
    assert 'wezterm_xcursor_root:' in output


def test_standalone_neovim_tool_route_is_unsupported() -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cmd_tools(['doctor', 'neovim'], stdout=stdout, stderr=stderr)

    assert code == 2
    assert stdout.getvalue() == ''
    assert 'standalone Neovim tools are no longer supported' in stderr.getvalue()
    assert 'ccb update rich' in stderr.getvalue()


def test_update_rich_workbench_provisions_and_enables_bundle(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)

    result = workbench_tools.update_rich_workbench()

    assert result['status'] == 'ok'
    assert result['enabled'] is True
    assert result['rich_update_status'] == 'ok'
    manifest = json.loads((tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['enabled'] is True


def test_rich_auto_start_allowed_respects_enabled_state_and_terminal_guard(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)

    assert workbench_tools.rich_auto_start_allowed(environ={}) is False

    workbench_tools.update_rich_workbench()

    assert workbench_tools.rich_auto_start_allowed(environ={}) is True
    assert workbench_tools.rich_auto_start_allowed(environ={'WEZTERM_PANE': '1'}) is True
    assert workbench_tools.rich_auto_start_allowed(environ={'TERM_PROGRAM': 'WezTerm'}) is True
    assert workbench_tools.rich_auto_start_allowed(environ={'CCB_WORKBENCH_PROFILE': 'rich'}) is False
    assert workbench_tools.rich_auto_start_allowed(environ={'CCB_WORKBENCH_ROOT': '/tmp/ccb-workbench'}) is False
    assert workbench_tools.rich_auto_start_allowed(environ={'CCB_RICH_AUTO_START': '0'}) is False


def test_install_bundled_rich_binaries_downloads_yazi_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'xdg-data'))
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg-state'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'xdg-cache'))
    monkeypatch.setenv('CODEX_BIN_DIR', str(tmp_path / 'global-bin'))
    monkeypatch.setenv('PATH', str(tmp_path / 'fake-bin'))
    monkeypatch.delenv('CCB_RICH_DOWNLOAD_BINARIES', raising=False)
    monkeypatch.setattr(workbench_tools.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(workbench_tools.platform, 'machine', lambda: 'x86_64')
    archive = tmp_path / 'yazi.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('yazi-x86_64-unknown-linux-musl/yazi', '#!/bin/sh\nexit 0\n')
        bundle.writestr('yazi-x86_64-unknown-linux-musl/ya', '#!/bin/sh\nexit 0\n')
    release = {
        'tag_name': 'v-test',
        'assets': [
            {
                'name': 'yazi-x86_64-unknown-linux-musl.zip',
                'browser_download_url': 'https://example.invalid/yazi.zip',
            }
        ],
    }
    monkeypatch.setattr(workbench_tools, '_github_latest_release', lambda _url: release)
    monkeypatch.setattr(workbench_tools, '_download_asset', lambda _asset, destination: destination.write_bytes(archive.read_bytes()))

    result = workbench_tools.install_bundled_rich_binaries()

    root = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench'
    assert result['status'] == 'ok'
    assert result['tool'] == 'github-release'
    assert result['asset'] == 'yazi-x86_64-unknown-linux-musl.zip'
    assert (root / 'bin' / 'yazi').is_file()
    assert (root / 'bin' / 'ya').is_file()
    assert workbench_tools._which_workbench_command('yazi') == str(root / 'bin' / 'yazi')
    manifest = json.loads((root / 'binary-bundles.json').read_text(encoding='utf-8'))
    assert manifest['yazi']['version'] == 'v-test'


def test_update_rich_workbench_installs_missing_dependencies(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    for name in ('yazi', 'ya', 'wezterm', 'chafa', 'pdfinfo', 'pdftotext', 'pdftoppm', 'ffprobe', 'ffmpeg'):
        (fake_bin / name).unlink()
    monkeypatch.setattr(workbench_tools, '_font_dependency_missing', lambda _spec: False)
    monkeypatch.setattr(workbench_tools, '_python_module_available', lambda _module, *, python: True)
    commands_by_package = {
        'yazi': ('yazi', 'ya'),
        'wezterm': ('wezterm',),
        'chafa': ('chafa',),
        'imagemagick': ('identify',),
        'poppler-utils': ('pdfinfo', 'pdftotext', 'pdftoppm'),
        'ffmpeg': ('ffprobe', 'ffmpeg'),
    }
    calls: list[list[str]] = []

    class _Input:
        def isatty(self) -> bool:
            return False

    def _run(command, **_kwargs):
        calls.append(list(command))
        package = command[-1]
        for executable in commands_by_package.get(package, ()):
            _fake_executable(fake_bin / executable)
        return workbench_tools.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(workbench_tools.sys, 'stdin', _Input())
    monkeypatch.setattr(workbench_tools.os, 'geteuid', lambda: 1000)
    _fake_executable(fake_bin / 'sudo')
    _fake_executable(fake_bin / 'apt-get')
    monkeypatch.setattr(workbench_tools.subprocess, 'run', _run)

    result = workbench_tools.update_rich_workbench()

    assert result['status'] == 'ok'
    assert result['enabled'] is True
    assert result['dependency_install_status'] == 'ok'
    assert result['dependency_install_tool'] == 'apt'
    assert result['dependency_install_packages'] == 'wezterm,yazi,chafa,imagemagick,poppler-utils,ffmpeg'
    assert calls[0] == ['sudo', '-n', 'apt-get', 'update']
    assert ['sudo', '-n', 'apt-get', 'install', '-y', 'yazi'] in calls
    assert ['sudo', '-n', 'apt-get', 'install', '-y', 'wezterm'] in calls


def test_workbench_enable_disable_and_uninstall_are_bundle_scoped(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)
    legacy_editor_marker = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'neovim' / 'keep.txt'
    legacy_editor_marker.parent.mkdir(parents=True, exist_ok=True)
    legacy_editor_marker.write_text('keep\n', encoding='utf-8')
    workbench_tools.provision_workbench(profile='rich')
    assert not legacy_editor_marker.exists()

    enabled = workbench_tools.enable_workbench(profile='rich')
    assert enabled['enabled'] is True
    manifest_path = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'manifest.json'
    assert json.loads(manifest_path.read_text(encoding='utf-8'))['enabled'] is True

    disabled = workbench_tools.disable_workbench(profile='rich')
    assert disabled['enabled'] is False
    assert json.loads(manifest_path.read_text(encoding='utf-8'))['enabled'] is False

    removed = workbench_tools.uninstall_workbench(profile='rich')
    assert removed['status'] == 'ok'
    assert not (tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench').exists()
    assert not (tmp_path / 'xdg-state' / 'ccb' / 'tools' / 'workbench').exists()
    assert (tmp_path / 'xdg-cache' / 'ccb' / 'tools' / 'workbench').exists()
    assert not (tmp_path / 'global-bin' / 'ccb-workbench').exists()
    assert not (tmp_path / 'global-bin' / 'ccb-yazi-rich').exists()
    assert not (tmp_path / 'global-bin' / 'ccb-image-preview').exists()


def test_workbench_launch_dry_run_prints_component_commands(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    stdout = StringIO()

    code = cmd_tools(['launch', 'workbench', '--profile', 'rich', '--dry-run'], stdout=stdout, stderr=StringIO())

    output = stdout.getvalue()
    assert code == 0
    assert 'workbench_status: ok' in output
    assert 'launch_status: dry_run' in output
    assert 'launch_command:' in output
    assert 'ccb-yazi-rich' in output
    assert 'neovim' not in output.lower()
    assert 'ccb-nvim' not in output


def test_workbench_launch_detaches_outer_tmux_environment(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    workbench_tools.enable_workbench(profile='rich')
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')
    monkeypatch.setenv('CCB_TMUX_SOCKET', 'outer')
    monkeypatch.setenv('CCB_TMUX_SOCKET_PATH', '/tmp/outer.sock')
    calls: list[tuple[list[str], dict[str, object]]] = []

    class _Process:
        pid = 2424

    def _popen(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        return _Process()

    monkeypatch.setattr(workbench_tools.subprocess, 'Popen', _popen)

    result = workbench_tools.launch_workbench(profile='rich')

    assert result['launch_status'] == 'started'
    assert calls
    command, kwargs = calls[0]
    env = kwargs.get('env')
    assert command == [str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'), 'terminal']
    assert isinstance(env, dict)
    assert 'TMUX' not in env
    assert 'TMUX_PANE' not in env
    assert 'CCB_TMUX_SOCKET' not in env
    assert 'CCB_TMUX_SOCKET_PATH' not in env
    assert kwargs['stdin'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['stdout'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['stderr'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['close_fds'] is True
    assert kwargs['start_new_session'] is True


def test_detached_terminal_process_has_no_tty_and_owns_its_session(tmp_path: Path, capfd) -> None:
    if os.name != 'posix':
        return
    output = tmp_path / 'detached-process.json'
    probe = tmp_path / 'detached-process.py'
    probe.write_text(
        'import json, os, pathlib, sys\n'
        'pathlib.Path(sys.argv[1]).write_text(json.dumps({\n'
        '    "pid": os.getpid(),\n'
        '    "sid": os.getsid(0),\n'
        '    "isatty": [os.isatty(0), os.isatty(1), os.isatty(2)],\n'
        '}), encoding="utf-8")\n'
        'print("detached-stdout-noise")\n'
        'print("detached-stderr-noise", file=sys.stderr)\n',
        encoding='utf-8',
    )

    process = workbench_tools._spawn_detached_terminal(
        [sys.executable, str(probe), str(output)],
        cwd=tmp_path,
        env=dict(os.environ),
    )

    assert process.wait(timeout=10) == 0
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['sid'] == payload['pid']
    assert payload['isatty'] == [False, False, False]
    captured = capfd.readouterr()
    assert 'detached-stdout-noise' not in captured.out
    assert 'detached-stderr-noise' not in captured.err


def test_workbench_wayland_cursor_overlay_preserves_requested_theme(tmp_path: Path, monkeypatch) -> None:
    if workbench_tools._is_wsl():
        pytest.skip('native Linux Wayland XCursor overlay is intentionally disabled under WSL')
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    cursor_root = tmp_path / 'xcursor'
    pointer = cursor_root / 'TestTheme' / 'cursors' / 'pointer'
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b'valid-test-xcursor')
    monkeypatch.setattr(workbench_tools.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('XCURSOR_PATH', str(cursor_root))
    monkeypatch.setenv('XCURSOR_THEME', 'TestTheme')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    wezterm_env_log = tmp_path / 'wezterm-env.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'env > "$WEZTERM_ENV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    monkeypatch.setenv('WEZTERM_ENV_LOG', str(wezterm_env_log))

    workbench_tools.provision_workbench(profile='rich')

    root = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench'
    cursor_asset = root / 'profiles' / 'wezterm' / 'xcursor' / '.ccb-assets' / 'hand'
    assert cursor_asset.read_bytes() == pointer.read_bytes()
    wrapper = root / 'bin' / 'ccb-workbench'
    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    result = workbench_tools.subprocess.run(
        [str(wrapper), 'terminal', '/bin/sh', '-lc', 'exit 0'],
        cwd=tmp_path,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    overlay = root / 'profiles' / 'wezterm' / 'xcursor' / 'TestTheme' / 'cursors' / 'hand'
    assert overlay.read_bytes() == pointer.read_bytes()
    wezterm_env = dict(
        line.split('=', 1)
        for line in wezterm_env_log.read_text(encoding='utf-8').splitlines()
        if '=' in line
    )
    assert wezterm_env['XCURSOR_THEME'] == 'TestTheme'
    assert wezterm_env['XCURSOR_PATH'].split(':', 1)[0] == str(root / 'profiles' / 'wezterm' / 'xcursor')
    assert wezterm_env['CCB_WORKBENCH_XCURSOR_COMPAT'] == '1'


def test_workbench_terminal_uses_saved_theme_instead_of_stale_inherited_theme(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    monkeypatch.setenv('WEZTERM_PANE', '7')
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')
    monkeypatch.setenv('CCB_WORKBENCH_THEME', 'gruvbox-light')

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    env.pop('CCB_WORKBENCH_PROFILE', None)
    env.pop('CCB_WORKBENCH_ROOT', None)
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    assert argv[:6] == ['--config-file', str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'profiles' / 'wezterm' / 'wezterm.lua'), 'start', '--always-new-process', '--no-auto-connect', '--cwd']
    assert str(project_root) in argv
    assert '-u' in argv
    assert 'TMUX' in argv
    assert 'CCB_WORKBENCH_THEME=dark' in argv
    assert 'CCB_TMUX_THEME_PROFILE=default' in argv
    assert 'CCB_SIDEBAR_THEME_PROFILE=default' in argv
    assert 'CCB_WORKBENCH_THEME=gruvbox_light' not in argv
    assert 'CCB_WORKBENCH_FORCE_RICH=1' in argv
    assert argv[-3:] == ['/bin/sh', '-lc', 'echo rich']


def test_workbench_terminal_reads_global_theme_config(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    wrapper = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'
    theme_config = theme_config_path()
    theme_config.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'theme': 'solarized',
                'palette': 'solarized_light',
                'tmux_profile': 'light',
            },
            indent=2,
            sort_keys=True,
        )
        + '\n',
        encoding='utf-8',
    )
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv-theme.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    result = workbench_tools.subprocess.run(
        [str(wrapper), 'terminal', '/bin/sh', '-lc', 'echo themed'],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    assert 'CCB_WORKBENCH_THEME=solarized_light' in argv
    assert 'CCB_TMUX_THEME_PROFILE=light' in argv
    assert 'CCB_SIDEBAR_THEME_PROFILE=light' in argv


def test_workbench_terminal_resolves_system_theme_without_user_wezterm_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    wrapper = tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'
    theme_config_path().write_text(
        json.dumps(
            {
                'schema_version': 1,
                'theme': 'system',
                'palette': 'system',
                'tmux_profile': 'system',
            },
            indent=2,
            sort_keys=True,
        )
        + '\n',
        encoding='utf-8',
    )
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv-system-theme.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    env['WEZTERM_ARGV_LOG'] = str(wezterm_log)
    env['CCB_SYSTEM_THEME'] = 'light'
    result = workbench_tools.subprocess.run(
        [str(wrapper), 'terminal', '/bin/sh', '-lc', 'echo system-themed'],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    assert 'CCB_WORKBENCH_THEME=latte' in argv
    assert 'CCB_TMUX_THEME_PROFILE=light' in argv
    assert 'CCB_SIDEBAR_THEME_PROFILE=light' in argv
    assert all('.wezterm.lua' not in item for item in argv)


def test_workbench_terminal_reports_inotify_exhaustion_before_new_wezterm(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv-inotify.txt'
    (tmp_path / 'fake-proc' / 'sys' / 'fs' / 'inotify' / 'max_user_instances').write_text('0\n', encoding='utf-8')
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    (fake_bin / 'python3').write_text('#!/usr/bin/env sh\nexit 75\n', encoding='utf-8')
    (fake_bin / 'python3').chmod(0o755)
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    env.pop('CCB_WORKBENCH_PROFILE', None)
    env.pop('CCB_WORKBENCH_ROOT', None)
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 75
    assert 'Linux inotify instance allocation failed' in result.stderr
    assert 'fs.inotify.max_user_instances=1024' in result.stderr
    assert not wezterm_log.exists()


def test_workbench_terminal_reuses_current_ccb_rich_wezterm_window(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    monkeypatch.setenv('WEZTERM_PANE', '7')
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))
    monkeypatch.setenv('CCB_WORKBENCH_PROFILE', 'rich')
    monkeypatch.setenv('CCB_WORKBENCH_ROOT', str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench'))
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    assert argv[:5] == ['cli', 'spawn', '--cwd', str(project_root), '--']
    assert 'start' not in argv
    assert '--always-new-process' not in argv
    assert '-u' in argv
    assert 'TMUX' in argv
    assert 'CCB_WORKBENCH_FORCE_RICH=1' in argv
    assert argv[-3:] == ['/bin/sh', '-lc', 'echo rich']


def test_workbench_terminal_sets_input_method_env_for_fcitx(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-argv.txt'
    wezterm_env_log = tmp_path / 'wezterm-env.txt'
    (fake_bin / 'wezterm').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n'
        'env > "$WEZTERM_ENV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm').chmod(0o755)
    (fake_bin / 'pgrep').write_text(
        '#!/usr/bin/env sh\n'
        '[ "$1" = "-x" ] && [ "$2" = "fcitx5" ]\n',
        encoding='utf-8',
    )
    (fake_bin / 'pgrep').chmod(0o755)
    monkeypatch.delenv('XMODIFIERS', raising=False)
    monkeypatch.delenv('GTK_IM_MODULE', raising=False)
    monkeypatch.delenv('QT_IM_MODULE', raising=False)
    monkeypatch.setenv('WEZTERM_PANE', '7')
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))
    monkeypatch.setenv('WEZTERM_ENV_LOG', str(wezterm_env_log))

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    wezterm_env = wezterm_env_log.read_text(encoding='utf-8').splitlines()
    assert 'XMODIFIERS=@im=fcitx' in wezterm_env
    assert 'GTK_IM_MODULE=fcitx' in wezterm_env
    assert 'QT_IM_MODULE=fcitx' in wezterm_env
    assert argv[-3:] == ['/bin/sh', '-lc', 'echo rich']


def test_workbench_terminal_uses_windows_wezterm_from_wsl(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    (fake_bin / 'wezterm').unlink()
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-exe-argv.txt'
    (fake_bin / 'wezterm.exe').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm.exe').chmod(0o755)
    monkeypatch.setenv('WEZTERM_PANE', '7')
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    monkeypatch.setenv('WSL_INTEROP', '/run/WSL/1_interop')
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    env['WEZTERM_PANE'] = '7'
    env['WEZTERM_ARGV_LOG'] = str(wezterm_log)
    env['WSL_DISTRO_NAME'] = 'Ubuntu'
    env['WSL_INTEROP'] = '/run/WSL/1_interop'
    env.pop('CCB_WORKBENCH_PROFILE', None)
    env.pop('CCB_WORKBENCH_ROOT', None)
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    config_path = str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'profiles' / 'wezterm' / 'wezterm.lua')
    assert argv[:1] + argv[2:8] == ['--config-file', 'start', '--always-new-process', '--no-auto-connect', '--', 'wsl.exe', '-d']
    assert argv[1] == config_path or argv[1].replace('\\', '/').endswith('/xdg-data/ccb/tools/workbench/profiles/wezterm/wezterm.lua')
    assert 'Ubuntu' in argv
    assert str(project_root) in argv
    env_index = argv.index('env')
    assert argv[env_index - 1] == '--'
    assert '--cwd' not in argv
    path_arg = next(item for item in argv if item.startswith('PATH='))
    assert str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin') in path_arg
    assert env['PATH'] in path_arg
    assert 'CCB_WORKBENCH_FORCE_RICH=1' in argv
    assert argv[-3:] == ['/bin/sh', '-lc', 'echo rich']


def test_workbench_terminal_reuses_current_ccb_rich_wezterm_window_from_wsl(tmp_path: Path, monkeypatch) -> None:
    fake_bin = _prepare_env(tmp_path, monkeypatch)
    (fake_bin / 'wezterm').unlink()
    workbench_tools.provision_workbench(profile='rich')
    project_root = tmp_path / 'project'
    project_root.mkdir()
    wezterm_log = tmp_path / 'wezterm-exe-argv.txt'
    (fake_bin / 'wezterm.exe').write_text(
        '#!/usr/bin/env sh\n'
        'printf "%s\\n" "$@" > "$WEZTERM_ARGV_LOG"\n',
        encoding='utf-8',
    )
    (fake_bin / 'wezterm.exe').chmod(0o755)
    monkeypatch.setenv('WEZTERM_PANE', '7')
    monkeypatch.setenv('WEZTERM_ARGV_LOG', str(wezterm_log))
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    monkeypatch.setenv('WSL_INTEROP', '/run/WSL/1_interop')
    monkeypatch.setenv('CCB_WORKBENCH_PROFILE', 'rich')
    monkeypatch.setenv('CCB_WORKBENCH_ROOT', str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench'))
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')

    env = workbench_tools._detached_terminal_env()
    env['PATH'] = f'{fake_bin}:/usr/bin:/bin'
    env['WEZTERM_PANE'] = '7'
    env['WEZTERM_ARGV_LOG'] = str(wezterm_log)
    env['WSL_DISTRO_NAME'] = 'Ubuntu'
    env['WSL_INTEROP'] = '/run/WSL/1_interop'
    env['CCB_WORKBENCH_PROFILE'] = 'rich'
    env['CCB_WORKBENCH_ROOT'] = str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench')
    result = workbench_tools.subprocess.run(
        [
            str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'),
            'terminal',
            '/bin/sh',
            '-lc',
            'echo rich',
        ],
        cwd=project_root,
        env=env,
        text=True,
        stdout=workbench_tools.subprocess.PIPE,
        stderr=workbench_tools.subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    argv = wezterm_log.read_text(encoding='utf-8').splitlines()
    assert argv[:9] == ['cli', 'spawn', '--', 'wsl.exe', '-d', 'Ubuntu', '--cd', str(project_root), '--']
    assert argv[9] == 'env'
    assert '--cwd' not in argv
    path_arg = next(item for item in argv if item.startswith('PATH='))
    assert str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin') in path_arg
    assert env['PATH'] in path_arg
    assert 'CCB_WORKBENCH_FORCE_RICH=1' in argv
    assert argv[-3:] == ['/bin/sh', '-lc', 'echo rich']


def test_rich_launch_opens_wezterm_with_source_test_entrypoint(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)
    workbench_tools.provision_workbench(profile='rich')
    workbench_tools.enable_workbench(profile='rich')
    script_root = tmp_path / 'source'
    project_root = tmp_path / 'project'
    script_root.mkdir()
    project_root.mkdir()
    _fake_executable(script_root / 'ccb')
    _fake_executable(script_root / 'ccb_test')
    monkeypatch.setenv('CCB_TEST_ENTRYPOINT', '1')
    monkeypatch.setenv('TMUX', '/tmp/tmux-1000/outer,123,0')
    monkeypatch.setenv('TMUX_PANE', '%7')
    monkeypatch.setenv('CCB_TMUX_SOCKET', 'outer')
    monkeypatch.setenv('CCB_TMUX_SOCKET_PATH', '/tmp/outer.sock')
    calls: list[tuple[list[str], dict[str, object]]] = []

    class _Process:
        pid = 4242

    def _popen(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        return _Process()

    monkeypatch.setattr(workbench_tools.subprocess, 'Popen', _popen)

    result = workbench_tools.launch_rich_ccb(script_root=script_root, cwd=project_root)

    assert result['launch_status'] == 'started'
    assert result['launch_pid'] == 4242
    assert calls
    command, kwargs = calls[0]
    cwd = kwargs.get('cwd')
    env = kwargs.get('env')
    assert cwd == str(project_root)
    assert command[:2] == [str(tmp_path / 'xdg-data' / 'ccb' / 'tools' / 'workbench' / 'bin' / 'ccb-workbench'), 'terminal']
    assert command[2:4] == ['/bin/sh', '-lc']
    assert str(script_root / 'ccb_test') in command[4]
    assert 'exec "${SHELL:-/bin/sh}" -l' in command[4]
    assert isinstance(env, dict)
    assert 'TMUX' not in env
    assert 'TMUX_PANE' not in env
    assert 'CCB_TMUX_SOCKET' not in env
    assert 'CCB_TMUX_SOCKET_PATH' not in env
    assert kwargs['stdin'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['stdout'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['stderr'] == workbench_tools.subprocess.DEVNULL
    assert kwargs['close_fds'] is True
    assert kwargs['start_new_session'] is True


def test_rich_launch_requires_update_rich_first(tmp_path: Path, monkeypatch) -> None:
    _prepare_env(tmp_path, monkeypatch)

    result = workbench_tools.launch_rich_ccb(script_root=tmp_path / 'source', cwd=tmp_path / 'project')

    assert result['status'] == 'failed'
    assert result['launch_status'] == 'missing_rich_bundle'
    assert 'ccb update rich' in result['reason']
