# OAuth Safety And Provider Capabilities

Date: 2026-08-04

Role: Provider qualification model

Status: Planning

Read when: adding a Provider, importing credentials, handling refresh/logout,
or claiming Agent login isolation.

## Core Rule

A copied credential representation is safe only when the Provider's remote
semantics make it safe. Different filenames, private homes, keyring service
names, or database rows do not create independent remote authorizations.

For mutable credentials:

```text
one remote refresh lineage = one authorized mutable writer
```

If two processes may both rotate, replace, or revoke one refresh lineage, CCB
must serialize them behind one authority or give them independently issued
credentials. Copying the token is not serialization.

## Credential Classes

| Class | Default policy | Reason |
| :--- | :--- | :--- |
| Static API key | Allow private one-way projection after qualification | No client-side refresh lineage |
| Static custom bearer | Allow only when Provider documents non-rotation | Token shape alone does not prove safety |
| Setup/automation token | Allow only within documented scope and lifetime | May be safer than interactive OAuth but still remotely revocable |
| OAuth access token without refresh | Status/use only for its bounded lifetime when supported; never synthesize refresh | Expiration is expected and recovery must be explicit |
| OAuth access + refresh token | Do not clone as independent authority | Refresh rotation and revoke scope can couple all copies |
| OS keyring record | Treat according to contained credential, not storage backend | Keyring namespace is not remote-session namespace |
| Unknown/opaque auth database | Fail closed or require Agent-private login | Rotation and mutation surfaces are unknown |

## Required Provider Capability Record

Each built-in Provider needs evidence-backed fields equivalent to:

- external sources and their read mechanism;
- credential kinds that may be present;
- whether each kind is static, rotating, or unknown;
- whether safe independent derivation/token exchange exists;
- whether a derived credential is truly independent, requires the source
  session to remain active, or is revoked together with the source;
- whether private file/keyring storage can be forced;
- refresh writer and native cross-process locking behavior;
- logout/revoke scope;
- whether visible and headless processes share a credential writer;
- local-only clear/removal mechanism;
- source files/keyrings that must remain read-only;
- tests and exact Provider versions used for qualification.

Unknown is a first-class value and must route to fail-closed behavior.

## Initial Qualification Direction

This table is planning input, not a shipped support claim:

| Provider/auth kind | Initial direction | Required evidence before implementation acceptance |
| :--- | :--- | :--- |
| Claude official OAuth | Do not clone into concurrent Agents; require independent Agent login, a documented independent token, or explicit API authority | Refresh/revoke behavior, private login workflow, visible/headless writer model |
| Codex official ChatGPT OAuth | Retain existing single-stream warning and generalize enforcement | Current contract plus runtime enforcement and migration evidence |
| Gemini official OAuth | Treat as rotating/unknown until qualified | Credential-store and refresh/logout source evidence |
| Provider static API key | Permit one-way Agent-private projection | Env/config precedence and proof Provider cannot rewrite source |
| Custom gateway bearer | Explicit CCB authority preferred | Token lifetime/rotation semantics and route isolation |
| Native CLI opaque credential store | Status only or Agent-private login | Documented private store switch and mutation inventory |

## Independent Credential Paths

Acceptable ways to obtain Agent authority are:

1. User explicitly configures a CCB-only API key/token/route.
2. User performs a Provider login while all Provider roots point to that
   stopped Agent's private home, and the resulting remote credential is
   independently issued.
3. CCB invokes a documented Provider token-exchange/derivation operation that
   creates a new independent credential without changing external authority.
4. CCB inherits a credential proven static and safe for multiple readers.

Unacceptable shortcuts include:

- copying one rotating refresh token into multiple Agent homes;
- renaming the keyring service and calling the remote session independent;
- refreshing one copy and synchronizing the result back to external state;
- invoking account-wide logout during kill/clear/cleanup;
- allowing a managed Provider to fall back to ambient external keyrings;
- treating successful startup as evidence that later refresh is isolated.

## Within-One-Agent Concurrency

Agent-private storage alone is insufficient when both visible and headless
Provider processes can refresh the same credential concurrently. A Provider
must satisfy one of:

- one long-lived Provider process owns all work;
- CCB serializes credential-mutating operations;
- the Provider supplies and CCB verifies a correct cross-process refresh lock;
- visible and headless processes use independently issued credentials.

Until proven, a single Agent credential must have only one live refresh-capable
process.

The one-writer rule is enforced through a ccbd-owned authority-generation
lease. A Provider-native cross-process lock is accepted only when the exact
Provider version and all visible/headless paths have been qualified. Sharing a
home or recording `single_agent_writer` in diagnostics is not enforcement.

For derived credentials, capability qualification must distinguish:

- independent validity after source logout;
- validity that requires the source session;
- revocation coupled to the source;
- unknown dependency.

CCB must not deactivate a truly independent child merely because the external
source logs out, and must not continue an unknown child as if independence had
been proven.

Related decision:

- [Rotating OAuth Is Not Copyable Authority](../decisions/002-rotating-oauth-is-not-copyable-authority.md)
