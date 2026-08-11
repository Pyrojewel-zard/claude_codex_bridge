# Explicit CCB Authority And Precedence

Date: 2026-08-04

## Context

Users may configure an Agent-specific API key, token, URL, or Provider route in
`.ccb/ccb.config`. Mixing that explicit authority with inherited external login
or API state creates ambiguous routing and can reintroduce external side
effects.

## Decision

Explicit Agent auth/API/route configuration is CCB-local authority and has
highest precedence in each authority dimension it owns. It applies only inside
CCB-managed process environment and Provider state.

The supported `key/url` shortcut intentionally selects a complete
credential-and-route bundle and suppresses inherited auth, API, and external
config that could redefine that route. Advanced explicit environment fields
are classified per Provider and suppress only their owned dimensions plus any
documented incompatible dimensions. Failure of explicit authority is terminal
and must not fall back to ambient external credentials. Changing or removing it
requires stopped Agent replacement; it never rewrites external Provider state.

## Consequences

- Current `key/url` compilation toward `inherit_api=false` and
  `inherit_auth=false` remains the baseline behavior.
- Advanced Provider-profile API env must converge on the same internal
  authority resolver rather than create a second path.
- The resolver must retain separate credential, route, account-selection, and
  non-auth config decisions, then validate the final composite.
- Diagnostics can explain precedence without printing secrets.
- Config UI and reload must record restart intent rather than mutate a running
  credential authority.
- A safer secret-reference syntax remains an open design question.
