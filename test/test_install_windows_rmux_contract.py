from __future__ import annotations

from pathlib import Path


def test_windows_install_keeps_backend_environment_confirmation_before_install_work() -> None:
    text = Path('platforms/windows/installer/install.ps1').read_text(encoding='utf-8-sig')
    install_body = text.split('function Install-Native', 1)[1]

    assert 'function Confirm-BackendEnv' in text
    assert install_body.index('Confirm-BackendEnv') < install_body.index('$pythonCmd = Find-Python')
    assert 'Show-WindowsX64ReleaseSurfaceProjection' in install_body


def test_windows_release_surface_diagnostics_do_not_claim_rmux_packaging_support() -> None:
    text = Path('platforms/windows/installer/install.ps1').read_text(encoding='utf-8-sig').lower()

    release_surface_start = text.index('function show-windowsx64releasesurfaceprojection')
    release_surface_end = text.index('function test-windowsx64releasehostgatevaluepresent', release_surface_start)
    assert release_surface_end > release_surface_start
    release_surface_block = text[release_surface_start:release_surface_end]

    assert 'rmux' not in release_surface_block
    assert 'support_tier' not in release_surface_block


def test_root_windows_installer_is_a_thin_platform_wrapper() -> None:
    text = Path('install.ps1').read_text(encoding='utf-8-sig')

    assert 'platforms\\windows\\installer\\install.ps1' in text
    assert 'function Install-Native' not in text


def test_windows_installer_creates_and_smokes_managed_python_runtime() -> None:
    installer = Path('platforms/windows/installer/install.ps1').read_text(encoding='utf-8-sig')
    requirements = Path('platforms/windows/installer/requirements.txt').read_text(encoding='utf-8')

    assert 'function Install-ManagedPythonRuntime' in installer
    assert '-m venv $venvDir' in installer
    assert '--requirement $requirements' in installer
    assert "import aiohttp, cryptography, watchdog" in installer
    assert 'aiohttp==' in requirements
    assert 'cryptography==' in requirements
    assert 'watchdog>=' in requirements


def test_windows_installer_yes_mode_never_prompts_for_missing_herdr() -> None:
    installer = Path('platforms/windows/installer/install.ps1').read_text(encoding='utf-8-sig')
    herdr_block = installer.split('function Confirm-HerdrReady', 1)[1].split(
        'function Install-Native', 1
    )[0]

    acknowledgement = 'if ($Yes -or $env:CCB_INSTALL_ASSUME_YES -eq "1")'
    assert acknowledgement in herdr_block
    assert herdr_block.index(acknowledgement) < herdr_block.index('Read-Host "继续安装? (y/N)"')
    assert '$reply = [string](Read-Host "继续安装? (y/N)")' in herdr_block
