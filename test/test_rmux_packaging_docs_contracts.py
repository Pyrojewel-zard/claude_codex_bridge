from __future__ import annotations

from terminal_runtime.backend_resolver import resolve_mux_backend_v2
from terminal_runtime.mux_backend_contract import backend_family_for_impl


def test_rmux_remains_legacy_tmux_family_backend() -> None:
    assert backend_family_for_impl('rmux') == 'tmux-family'


def test_non_windows_auto_can_still_select_rmux_legacy_default() -> None:
    result = resolve_mux_backend_v2(
        requested_backend='auto',
        source='auto_probe',
        platform_gate={'supported': False, 'os_platform': 'linux', 'cpu_arch': 'x64'},
        capability_report=None,
        capability_report_ref=None,
        legacy_default_backend='rmux',
    )

    assert result.get('blocked') is not True
    assert result['backend_impl'] == 'rmux'
    assert result['effective_backend'] == 'rmux'
