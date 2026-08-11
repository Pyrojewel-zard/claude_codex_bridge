# Decision 002: stable CCB with a Windows beta asset

Date: 2026-08-12
Status: accepted

## Decision

Publish `v8.6.0` as a stable CCB release across the existing Linux, macOS, npm,
Sidebar, and Android routes. Attach `ccb-windows-x86_64.zip` and its checksum to
the same GitHub Release through the isolated Windows workflow.

The stable CCB version does not promote the Windows support tier. Windows
manifests, diagnostics, installation guidance, and release notes must continue
to say beta until real WezTerm, Herdr, and provider workflow qualification is
accepted.

## Consequences

- `v8.6.0-beta.3` remains immutable and supplies native Windows build/install
  evidence for the stable candidate.
- Stable tags trigger both the existing stable product workflows and the
  isolated Windows workflow.
- Windows code remains outside Unix installers, Unix release builders, and npm
  package metadata.
- Windows still requires native x64, Python 3.10+, WezTerm, Git Bash, and Herdr
  0.8.0+; its PE launchers remain unsigned and not fully self-contained.
- Publication must not claim full real GUI or provider acceptance.
