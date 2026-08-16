# CCB Mobile Third-Party Notices

## Paseo Provider Control Semantics

- Project: Paseo
- Source: https://github.com/getpaseo/paseo
- Pinned source commit: `b599d38a772f621e0001abfb90a769de11c8cd8b`
- Copyright: Copyright 2025-present Mohamed Boudra
- License: GNU Affero General Public License v3.0 or later
- CCB modifications: Python gateway/ccbd and Flutter adaptations for CCB's
  project/window/agent/session authority, device scopes, Relay transport, and
  restart-required configuration model.

Source-to-target mapping:

| Paseo source | CCB adaptation |
| :--- | :--- |
| `packages/protocol/src/agent-types.ts` | `lib/provider_control/session_usage.py`, `mobile/app/lib/models/ccb_provider_control.dart` |
| `packages/protocol/src/messages.ts` | `lib/mobile_gateway/service.py`, Flutter repository/transport Provider-control interfaces |
| `packages/protocol/src/provider-manifest.ts` | `lib/cli/services/config_ui.py`, ProjectView Provider capability records |
| `packages/server/src/server/agent/provider-snapshot-manager.ts` | bounded transcript revision cache and Provider runtime snapshots |
| `packages/server/src/services/quota-fetcher/` | `lib/provider_control/quota.py` |
| `packages/app/src/provider-selection/` | `mobile/app/lib/features/provider_control/provider_control_sheet.dart` |
| `packages/app/src/provider-usage/` | Flutter session-usage and account-quota sections |

No Paseo daemon, React Native component, asset, icon, credential, or runtime
process is bundled. The implementation adapts data contracts, normalization,
state semantics, and interaction behavior to CCB's existing architecture.
