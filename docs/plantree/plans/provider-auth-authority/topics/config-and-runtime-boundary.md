# Config And Runtime Boundary

Date: 2026-08-04

Role: Config and lifecycle solution map

Status: Planning

Read when: changing `.ccb/ccb.config`, Provider profile compilation, launch
environment, managed-home cleanup, or diagnostics.

## External Inheritance Default

When no CCB-specific API authority is configured, CCB may inspect allowlisted
external Provider state and select only a capability-qualified inheritance
path.

External state remains authoritative only at its source. The managed result is
either:

- an explicitly marked static snapshot;
- an independently derived Agent credential;
- account/login status metadata with no credential projection; or
- no usable authority.

CCB must not interpret “external Provider is logged in” as “its refresh token
is safe to duplicate”.

For an Agent that remains in external-inheritance mode, this resolution is
repeated on every stopped start/restart. External login, logout, account
selection, qualified static credential, API endpoint, and route changes flow
into the next managed generation. An old source-owned projection is not a
fallback when the authoritative source has changed or logged out.

Source resolution uses three outcomes:

- `present`: synchronize the current qualified state;
- `authoritative_absent`: remove the prior source-owned projection;
- `unknown_error`: do not launch with stale authority and do not mutate either
  source or existing Agent-owned state.

## Explicit CCB Configuration

Current canonical shortcut:

```toml
[agents.worker]
key = "..."
url = "https://provider.example/api"
```

Advanced authority may use `provider_profile.env` and Provider-specific profile
fields. Regardless of syntax, explicit authority must compile into the
appropriate dimensions of one internal composite:

- explicit credential authority disables competing `inherit_auth`;
- explicit endpoint/route authority disables competing `inherit_api` and only
  the Provider config fields that can redefine that route;
- the supported `key/url` shortcut intentionally selects both dimensions and
  keeps its current `inherit_auth=false` / `inherit_api=false` behavior;
- conflicting inherited account/route/config dimensions are rejected by
  Provider-specific compatibility rules;
- values exported only into the managed Provider environment/home;
- no global Provider settings, shell profiles, IDE state, or keyrings changed;
- no fallback to ambient credentials if the explicit credential fails.

Model or non-auth configuration may still inherit where it cannot redefine the
selected API/auth route. Mixed files require field-level allowlists.

## Configuration Precedence Examples

| Inputs | Selected result |
| :--- | :--- |
| External login only, rotating OAuth | `external_status_only`; require Agent-private login or explicit API authority |
| External qualified static API key only | `external_static_snapshot` |
| External login plus `[agents.a] key/url` | `ccb_explicit`; external auth/API ignored |
| Existing Agent-private login plus `inherit_auth=false` | `agent_private`; external login ignored |
| Agent-private login plus compatible explicit endpoint | Private credential plus explicit route composite |
| Explicit key plus inherited provider base URL | Invalid dual authority unless the explicit config deliberately supplies the complete compatible route |
| Explicit credential fails at runtime | Report explicit-authority failure; never fall back to external login |
| External inherited login changes, then Agent restarts | Re-resolve and synchronize the new safe source state before launch |
| External inherited login is authoritatively removed, then Agent restarts | Remove its source-owned projection and start unauthenticated/status-only |
| External source read fails transiently during restart | Block launch as source-resolution unknown; do not reuse stale inherited auth |
| External changes while Agent uses explicit/private authority | Ignore the external change for that Agent |

## Runtime Roots

Visible panes and headless subprocesses must receive the same resolved:

- private HOME/USERPROFILE/XDG roots;
- Provider config, data, state, session, and cache roots;
- credential-store selection;
- API/token/URL environment;
- provenance id and refresh-writer policy.

They must also bind to the same durable authority generation and ccbd-owned
writer lease. Provider-native locking is not assumed merely because two
processes share one home.

Provider launchers must overwrite these roots. A command wrapper that resets
them is an unsupported isolation escape and must be diagnosed.

When CCB is invoked from a managed Provider pane, control-plane processes must
scrub the pane's Provider roots and injected API authority before resolving the
real external source home. A managed home can never become the next launch's
external source.

## Refresh, Logout, Clear, And Cleanup

- Refresh is allowed only for independently Agent-owned credentials and only by
  the declared writer.
- `/logout` or equivalent is disabled when its remote scope is unknown or may
  include external/shared authority.
- `ccb clear` clears conversation context only.
- `ccb kill` and project cleanup stop writers first, then delete only managed
  artifacts marked as CCB-owned.
- Local cleanup never invokes remote logout/revoke.
- External logout is observed on a future launch but never repaired from a
  managed copy.
- External login/account/API changes are synchronized only at a stopped
  external-inheritance launch boundary; running processes are not rewritten.
- Removing explicit CCB configuration never writes the old credential or route
  into external Provider state.

## Diagnostics

Safe diagnostics should report:

- selected authority mode and precedence reason;
- external source class and whether it was read, ignored, or status-only;
- credential class: static, rotating, unknown, independently derived;
- refresh writer count and process identity class, not secret identity;
- managed storage roots and whether they are private ordinary paths;
- restart/re-login requirement;
- suspected duplicate-authority condition using protected correlation evidence;
- config conflicts and unsupported Provider semantics.

Diagnostics must not report token values, raw credential JSON, keyring payloads,
or stable cross-project secret hashes.

Diagnostic bundle staging must also sanitize or exclude every serialized shell
command and session/launch record that may contain injected environment values.
This includes `start_cmd`, structured launch intent, Provider launch context,
runtime/helper records, and pane crash logs. Owner-only file permissions do not
make those values safe to copy into a support archive.

## Config Change Semantics

Authentication and route changes are startup authority changes:

1. validate the new config;
2. classify the affected Agent as restart/replace required;
3. do not mutate its running process or credential store during reload;
4. stop the old writer through normal lifecycle authority;
5. materialize the new composite authority;
6. start and verify the replacement;
7. clean obsolete managed credentials only after ownership is proven.

The replacement uses a two-phase authority transaction: persist a prepared
generation and writer lease before spawn, verify the new process, then activate
the generation. Any post-spawn failure terminates the new writer.

Related decision:

- [Explicit CCB Authority And Precedence](../decisions/003-explicit-ccb-authority-and-precedence.md)
- [Restart Resynchronizes External State](../decisions/004-restart-resynchronizes-external-state.md)
- [Composite Provider Authority Dimensions](../decisions/005-composite-authority-dimensions.md)
- [Prepared Authority Before Provider Spawn](../decisions/006-prepared-authority-before-spawn.md)
