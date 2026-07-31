# Decision 024: Official And Self-Hosted Relay Modes

Status: accepted for activation and pairing.

CCB exposes `official` Relay mode backed by the fixed CCB endpoint and
`self_hosted` mode backed by a user-provided `wss://` endpoint. Official mode
uses an operator-issued one-time invitation; self-hosted operators issue their
own invitation. Desktop credentials remain owner-only and the phone QR never
contains the invitation.

Pairing carries `relay_mode`. Python and Flutter reject an official-labelled
endpoint unless it matches the CCB official endpoint. This prevents a QR from
gaining the official trust signal for an arbitrary Relay.
