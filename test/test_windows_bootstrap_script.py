from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PS1 = REPO_ROOT / "scripts" / "bootstrap-windows-test-env.ps1"
CCB8_PS1 = REPO_ROOT / "ccb8.ps1"


def test_windows_bootstrap_script_installs_expected_prerequisites() -> None:
    text = BOOTSTRAP_PS1.read_text(encoding="utf-8")

    assert "Git.Git" in text
    assert "Python.Python.3.12" in text
    assert "OpenJS.NodeJS.LTS" in text
    assert "Invoke-CCBInstall" in text
    assert "Test-CCBInstalled" in text
    assert "CCB already installed at $InstallPrefix" in text
    assert "deferring strict Python validation to install.ps1" in text
    assert "SkipCCSwitch" in text
    assert "Start-Transcript" in text
    assert "Bootstrap log:" in text
    assert 'Join-Path $script:BootstrapScriptDir "bootstrap-logs"' in text
    assert 'Join-Path $logsDir "bootstrap.log"' in text
    assert '$env:CCB_PYTHON_CMD = $workingPython' in text
    assert 'Add-PythonCandidate "py -3"' in text
    assert 'npm global bin prefix:' in text
    assert 'where codex => ' in text
    assert 'Windows Store alias ignored' in text
    assert 'InstallAllUsers=0 PrependPath=1 Include_launcher=1' in text
    assert 'Show-ProviderSummary' in text
    assert 'Show-PathDiagnostics' in text


def test_windows_bootstrap_script_installs_expected_provider_clis() -> None:
    text = BOOTSTRAP_PS1.read_text(encoding="utf-8")

    assert "@openai/codex" in text
    assert "@anthropic-ai/claude-code" in text
    assert "@google/gemini-cli" in text
    assert "opencode-ai" in text
    assert "https://api.github.com/repos/farion1231/cc-switch/releases/latest" in text
    assert 'CC-Switch-v*-Windows.msi' in text


def test_windows_install_script_prefers_discovered_real_python_over_store_alias() -> None:
    text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "Get-PythonCandidates" in text
    assert 'Add-Candidate "py -3"' in text
    assert '$env:CCB_PYTHON_CMD' in text
    assert "Get-PythonVersionInfo" in text
    assert "Test-IsWindowsStoreAliasPath" in text
    assert 'sys.executable' in text
    assert 'set `"PYTHON=$escapedPythonExecutable`"' in text


def test_windows_bootstrap_script_creates_four_provider_smoke_config() -> None:
    text = BOOTSTRAP_PS1.read_text(encoding="utf-8")

    assert "cmd,writer:codex;reviewer:claude,qa:gemini,ops:opencode" in text
    assert "scripts/bootstrap-windows-test-env.ps1" in text
    assert "'```powershell'" in text
    assert "'```'" in text
    assert 'ccswitch' in text
    assert 'bootstrap-logs' in text


def test_windows_ccb8_wrapper_surfaces_config_ui_launcher_hint() -> None:
    text = CCB8_PS1.read_text(encoding="utf-8")

    assert 'Show-ConfigUiLauncherHint' in text
    assert 'ccb8: config ui: run .\\ccb8.cmd config ui' in text
    assert 'ccb8: config ui: after release run ccb config ui' in text
    assert 'ccb8: config ui: the command prints http://127.0.0.1:PORT/?token=... for copy' in text


def test_windows_ccb8_wrapper_stops_one_click_after_ccb_start_failure() -> None:
    text = CCB8_PS1.read_text(encoding="utf-8")

    failure_guard = "if ($isOneClick -and $null -ne $ccbExit -and $ccbExit -ne 0)"
    assert failure_guard in text
    assert "ccb8: ccb startup failed with exit code " in text
    assert text.index(failure_guard) < text.index("# One-click mode: after CCB starts")
    # P1: ccbd readiness moved into Python (`--wait-ready`); the PowerShell
    # one-click path must no longer poll lifecycle.json itself.
    assert "ccb8: waiting for ccbd to be ready..." not in text
    assert "--wait-ready" in text


def test_windows_ccb8_wrapper_installs_herdr_agent_state_hook_for_one_click() -> None:
    text = CCB8_PS1.read_text(encoding="utf-8")

    assert "function Install-HerdrAgentStateHook" in text
    assert r"lib\terminal_runtime\herdr_backend_runtime\ccb\herdr-agent-state.ps1" in text
    assert "CCB_SOURCE_HOME" in text
    assert r".ccb\hooks" in text
    assert "Install-HerdrAgentStateHook" in text
    assert "ccb8: Herdr agent-state hook ready:" in text


def test_windows_ccb8_wrapper_no_longer_prestarts_herdr_server() -> None:
    """P0: server pre-start + session probe removed from the PowerShell shim.

    ``HerdrCliRequestAdapter`` owns server startup via NotFound recovery; the
    bootstrap (``ccb herdr open``) auto-starts the ccbd-derived session server
    and ``--wait-ready`` waits for ccbd mounted.  PowerShell must not re-probe
    ``herdr session list`` or launch ``--session <name> server`` itself.
    """
    text = CCB8_PS1.read_text(encoding="utf-8")

    assert "session list --json" not in text
    assert "--session $ccbSession server" not in text
    assert "herdr session list" not in text
    assert "ccb8: waiting for ccbd to be ready..." not in text


def test_windows_ccb8_wrapper_uses_structured_herdr_session_attach() -> None:
    """P2: Herdr UI attach uses structured ``herdr session attach``.

    ``wezterm cli spawn -- <prog>`` runs the program as the tab's foreground
    ConPTY process (interactive terminal), replacing the old spawn +
    ``send-text --no-paste`` keyboard injection.  A send-text fallback remains.
    """
    text = CCB8_PS1.read_text(encoding="utf-8")

    assert "session attach $ccbSession" in text
    assert "weztermCli cli spawn --cwd" in text
    assert "falling back to send-text" in text
