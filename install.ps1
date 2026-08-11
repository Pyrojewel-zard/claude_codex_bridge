param(
  [Parameter(Position = 0)]
  [ValidateSet("install", "uninstall", "help")]
  [string]$Command = "help",
  [string]$InstallPrefix = "$env:LOCALAPPDATA\codex-dual",
  [string]$SourceArchive = "",
  [string]$ExpectedSha256 = "",
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$installer = Join-Path $PSScriptRoot "platforms\windows\installer\install.ps1"
if (-not (Test-Path -LiteralPath $installer)) {
  throw "Windows installer implementation not found: $installer"
}

& $installer -Command $Command -InstallPrefix $InstallPrefix -SourceArchive $SourceArchive -ExpectedSha256 $ExpectedSha256 -Yes:$Yes
exit $LASTEXITCODE
