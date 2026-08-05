# Open Questions

Date: 2026-08-04

Only unresolved design questions belong here.

## Config Surface

1. Should the user-facing surface remain the existing combination of
   `inherit_auth`, `inherit_api`, `key/url`, and `provider_profile.env`, or add
   one typed field such as `auth_source = "external|agent|explicit"`?
   Code-backed default: keep the current public fields for the first slices and
   compile them to a typed internal authority; add a public field only when the
   Agent-private workflow needs an unambiguous operator selection.
2. Should CCB add `key_env`, `token_env`, or owner-only file references so API
   authority need not be stored literally in project TOML?
   This does not block the authority core, but diagnostic bundle redaction is a
   prerequisite even if safe references are deferred.
3. When explicit CCB authority is removed, should the next stopped launch
   revert to safe external inheritance automatically, or remain unauthenticated
   until the operator explicitly selects inheritance?
4. What is the supported meaning of `provider_profile.home`? Current code may
   use an arbitrary absolute path as the writable Provider root. The
   recommended boundary is to treat it as a read-only source profile and keep
   all writable runtime state under CCB-owned `provider-state`; the alternative
   is to reject any path outside that managed root.

## OAuth And Provider Capabilities

5. Which supported Providers document a token-exchange, device authorization,
   setup-token, or other operation that creates an independent credential
   without invalidating the source login?
6. For each Provider, is logout scoped to one credential, one client session,
   or the whole account? Unknown scope must remain fail-closed.
7. Can visible and headless processes for one Agent share the Provider's native
   cross-process refresh lock safely, or must CCB serialize them behind one
   credential writer?
8. Which Provider-issued long-lived bearer/setup tokens are non-rotating and
   safe to copy, and which only appear static but remain remotely coupled?
9. For every Provider operation claimed to derive an independent credential,
   is the child truly independent, valid only while the source session remains
   active, or revoked together with the source? Unknown dependency must block
   automatic source-logout handling.

## Agent-Private Login

10. What is the supported Agent-private login workflow when managed login/logout
   commands are currently disabled to protect external state?
11. Should CCB provide a stopped-Agent maintenance command that launches a
   login-only process with private roots, or require an operator-controlled
   shell command documented per Provider?
12. How should CCB locally clear an Agent-owned credential when the Provider's
    logout command may perform account-wide remote revocation?

## Migration

13. At upgrade, should existing cloned rotating OAuth credentials be blocked at
    the next launch immediately, or receive one warning-only release before
    enforcement?
14. How should CCB identify likely duplicate credential authority without
    persisting stable raw token hashes that become sensitive correlation data?
15. If an affected Provider pane is already running, should it remain untouched
    until stopped, while new headless jobs are rejected, or should all new work
    be blocked pending re-authentication?

## Restart Compatibility

16. What should `ccb restart` do for a legacy Provider session that has only a
    persisted shell `start_cmd` and no structured launch intent? The
    fail-closed default is `restart_requires_full_start`; parsing or replaying
    the old shell string can silently reintroduce stale auth environment.
17. After the old writer is quiesced, should a source-probe or projection
    failure retain the dead pane for diagnosis or replace it with a bounded CCB
    error shell? Either choice must keep the Provider stopped and must not
    restore the old authority automatically.

## Secret Injection And Writer Recovery

18. Which owner-only mechanism should provide API/token values at spawn without
    embedding them in persisted `start_cmd`: an ephemeral env file, inherited
    descriptor, local secret reference, or Provider-native private config?
19. How long may a `prepared` authority generation survive daemon failure before
    it is failed or resumed, and what exact process evidence is required to
    activate it after recovery?
20. When a visible Provider process is alive but its writer lease cannot be
    proven after daemon recovery, should CCB terminate it immediately or park
    the Agent and require explicit operator recovery?

## Session Continuity

21. For each Provider and exact CLI version, which account/API/route changes
    permit the same native session id to resume, and which require a new native
    session linked to the stable CCB conversation?
22. When native rebind is incompatible, what is the minimum lossless
    continuation payload: full local transcript, bounded summary plus recent
    turns, or a Provider-specific import format? The old transcript must remain
    independently resume-visible regardless of this choice.
23. Should `resume` show one stable conversation with generation details on
    demand, or list each Provider generation as a child entry? The default must
    not make an authority change look like a clear.
24. How should a crash-time continuation preserve an in-flight turn that the
    Provider may have accepted but CCB did not commit? Duplicate submission and
    silent turn loss must both be detectable.
