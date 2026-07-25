# Decision 007: Marker-First Projected-Asset Ownership

Date: 2026-07-21
Status: Accepted and verified in R12

## Problem

`route_projected_tree` historically exposed `allow_unmarked_replace=True`.
Packaged inherited skills, Claude inherited skills/commands, and Droid
inherited skills still enabled it. The core replacement predicate also treated
any same-name marker file as ownership proof and treated an unmarked directory
with the same content as replaceable. Those rules can delete, replace, or
claim user-owned state without a valid CCB ownership record.

## Inventory

R12 owns the remaining production uses:

| Consumer | Target class | R12 rule |
| :--- | :--- | :--- |
| `provider_core.inherited_skills` | packaged inherited skill tree, currently used by Kimi | remove the bypass; preserve unmarked/foreign targets |
| Claude inherited assets | managed-home `.claude/skills` and `.claude/commands` | remove the bypass; preserve local user assets |
| Droid inherited assets | managed `FACTORY_HOME/skills` | remove the bypass; preserve local user assets |

Droid plugin seeds, Gemini/Qwen extension seeds, Codex plugin/cache seeds,
RolePack projections, and per-skill projections already use separate
marker-first paths or `allow_unmarked_replace=False`; they receive regression
coverage but no compatibility broadening.

## Ownership Proof

A projected-tree marker is valid only when all of these hold:

- it is a local regular file, not a symlink;
- `schema_version` is exactly `1`;
- `record_type` is exactly `ccb_projected_asset`;
- `label` exactly matches the consumer's stable label;
- `source` is a non-empty path string;
- `mode` is one of `symlink`, `copy`, or `copy-seed`.

A valid same-label marker proves CCB ownership even when the configured source
path changes. A missing, malformed, symlinked, wrong-schema, wrong-record, or
wrong-label marker proves no ownership. Source/content equality alone proves no
ownership of an ordinary directory.

## One Bounded Legacy Migration

When the marker is absent, R12 may adopt only an existing symlink whose
resolved target is exactly the current projection source. The target is not
replaced; CCB atomically writes its marker beside that exact legacy projection.
Marker-write failure leaves the symlink unchanged and unowned.

An unmarked directory is always preserved, even when its content is identical
to the source. A foreign or malformed marker blocks adoption even when the
target is an exact source symlink or the target itself is absent.

## Routing And Cleanup

- Enabled projection may create or refresh only an absent target without a
  conflicting marker, a valid marker-owned target, or the exact unmarked
  symlink migration above.
- Disabled inheritance or a missing source removes only a target with a valid
  same-label marker. It preserves every unmarked or foreign-marker target.
- Failed symlink/copy/marker creation removes only the candidate created by the
  current call; it never removes a pre-existing unowned target.
- `allow_unmarked_replace` remains a compatibility keyword temporarily but no
  longer grants destructive authority. All production `True` call sites are
  removed in R12.
- No provider-specific fallback, whole-home copy, login, credential access, or
  mutation of source authority is authorized.

## Evidence Gate

R12 must preserve counterexamples for unmarked different and identical
directories, unmarked foreign symlinks, exact-source legacy symlink adoption,
foreign/malformed/symlinked markers, target-absent marker conflicts, disabled
and source-missing cleanup, marker-write failure, and valid owned refresh.
Consumer tests must cover packaged Kimi skills, Claude skills/commands, Droid
skills, and unaffected marker-first seed/projection paths. External candidate
validation must use isolated fake source homes, prove source hashes unchanged,
and leave the project unmounted. No real provider login is needed because R12
changes deterministic pre-launch filesystem ownership rather than native CLI
behavior.
