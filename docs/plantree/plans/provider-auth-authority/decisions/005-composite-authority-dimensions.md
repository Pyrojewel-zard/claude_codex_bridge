# Composite Provider Authority Dimensions

Date: 2026-08-04

## Context

A Provider launch may combine credential selection, API endpoint or route,
account or organization selection, and non-auth configuration. Treating all of
those inputs as one mutually exclusive authority mode either rejects safe
combinations or allows one explicit field to suppress unrelated state without
an intentional policy decision.

## Decision

CCB resolves Provider authority as a validated composite, not one scalar mode.
The minimum independent dimensions are:

- credential authority;
- API endpoint and route authority;
- account, organization, or profile-selection authority;
- non-auth configuration inheritance.

Each dimension records its own source, precedence reason, provenance, and
generation. The composite resolver then validates cross-dimension compatibility
before any managed state is materialized.

An explicit value wins only in the dimension it owns unless a documented
shortcut intentionally selects a complete credential-and-route bundle. The
existing `key/url` shortcut remains such a complete bundle for its supported
Providers and continues disabling competing inherited auth/API state. Advanced
environment fields are classified individually by Provider allowlists.

Adapters report Provider facts and compatibility constraints. They must not
collapse the composite back into ad hoc fallback behavior.

## Consequences

- The sanitized authority record contains a composite selection and one
  aggregate generation derived from its dimension generations.
- Resume compatibility is evaluated against every session-relevant dimension.
- Diagnostics can explain which explicit or inherited field won without
  printing its value.
- Tests must cover both valid mixed configurations and rejected incompatible
  combinations.
- Adding a new public `auth_source` field remains optional; it cannot replace
  the internal dimensional model.
