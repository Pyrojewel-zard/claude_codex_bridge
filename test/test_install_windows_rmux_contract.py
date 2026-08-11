from __future__ import annotations

from pathlib import Path


def test_windows_install_keeps_backend_environment_confirmation_before_install_work() -> None:
    text = Path('install.ps1').read_text(encoding='utf-8')
    install_body = text.split('function Install-Native', 1)[1]

    assert 'function Confirm-BackendEnv' in text
    assert install_body.index('Confirm-BackendEnv') < install_body.index('$pythonCmd = Find-Python')
    assert 'Show-WindowsX64ReleaseSurfaceProjection' in install_body


def test_windows_release_surface_diagnostics_do_not_claim_rmux_packaging_support() -> None:
    text = Path('install.ps1').read_text(encoding='utf-8').lower()

    release_surface_start = text.index('function show-windowsx64releasesurfaceprojection')
    release_surface_end = text.index('function test-windowsx64releasehostgatevaluepresent', release_surface_start)
    assert release_surface_end > release_surface_start
    release_surface_block = text[release_surface_start:release_surface_end]

    assert 'rmux' not in release_surface_block
    assert 'support_tier' not in release_surface_block
