# Public Relay Package A/B Candidate

Date: 2026-07-22
Branch: `worker1/mobile-relay-ab-job_555408fffa4f`
Base: `78e54cb68e240a1fac5904310f2dc7b0726b05aa`

## Scope

- Package A: fixed relay crypto protocol v2, cleartext envelope field set,
  prohibited plaintext field set, X25519/HKDF-SHA256/ChaCha20-Poly1305 key
  schedule, transcript/key confirmation, direction-separated keys, sequence
  AAD, replay/reorder/corruption/downgrade rejection, host fingerprint
  confirmation, and best-effort in-memory key wipe on close.
- Package B: SQLite/WAL one-time invitation store with unused/consumed/
  expired/revoked states, keyed verifier only, atomic concurrent claim,
  host Ed25519 public-key binding, short-lived PoP session capabilities,
  invite/host status/list/revoke, and redacted operator rendering.

## Operator Boundary

The operator surface is local/admin only:

```bash
ccb relay invite issue --db /path/to/relay-admission.sqlite3 --ttl-seconds 900 --json
ccb relay invite status --db /path/to/relay-admission.sqlite3 <invite_id> --json
ccb relay invite list --db /path/to/relay-admission.sqlite3
ccb relay invite revoke --db /path/to/relay-admission.sqlite3 <invite_id> --reason "rotation"
ccb relay host status --db /path/to/relay-admission.sqlite3 <host_id> --json
ccb relay host list --db /path/to/relay-admission.sqlite3
ccb relay host revoke --db /path/to/relay-admission.sqlite3 <host_id> --reason "rotation"
```

Only `relay invite issue` prints the newly generated invitation, once, to the
explicit operator output. Status/list/revoke output does not include raw
invitation values. The database stores `invite_id`, keyed verifier, state,
quota, host public-key hash, and payload-free audit events, not raw invitation
secrets or CCB payload fields.

## Verification

- `PYTHONPATH=lib python -m pytest test/test_mobile_gateway_relay_crypto_v2.py test/test_mobile_gateway_relay_admission.py test/test_mobile_gateway_relay.py -q`
  - `18 passed`
- `PYTHONPATH=lib python -m pytest test/test_mobile_gateway_*.py test/test_v2_cli_parser.py test/test_v2_cli_render.py test/test_v2_phase2_wiring.py -q`
  - `232 passed`
- `/home/bfly/yunwei/test_ccb2/flutter-3.44.2/bin/flutter pub get`
- `/home/bfly/yunwei/test_ccb2/flutter-3.44.2/bin/flutter test test/relay_crypto_v2_vectors_test.dart`
  - `3 passed`
- `/home/bfly/yunwei/test_ccb2/flutter-3.44.2/bin/flutter test test/relay_protocol_test.dart`
  - `5 passed`
- `/home/bfly/yunwei/test_ccb2/flutter-3.44.2/bin/flutter test`
  - `664 passed`
- `/home/bfly/yunwei/test_ccb2/flutter-3.44.2/bin/flutter analyze`
  - `No issues found`

## Non-Claims

This evidence does not prove a production relay listener, public WSS routing,
host connector integration, Android public-route emulator acceptance, physical
device acceptance, cloud deployment, or Alibaba Cloud security-group/runtime
configuration. Those remain Package C/D/E/F work.
