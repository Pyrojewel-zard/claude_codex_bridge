# Claude Settings Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each CCB Claude startup refresh managed settings and plugins from the current source settings while preserving CCB runtime hooks and permissions.

**Architecture:** Keep the existing Claude HOME materialization call in the startup preparation path. Change only settings merge ownership: source owns ordinary/plugin fields, while managed CCB hooks and permissions remain preserved. Add regression tests at the existing `materialize_claude_home_config` boundary.

**Tech Stack:** Python, pytest, JSON settings materialization.

## Global Constraints

- Do not change CCB configuration format or non-Claude providers.
- Preserve CCB-injected hooks, permissions, and protected auth state.
- Do not modify `test/conftest.py`.

---

### Task 1: Lock source-authoritative plugin refresh behavior

**Files:**
- Modify: `test/test_provider_profiles.py` near `test_materialize_claude_home_config_preserves_existing_enabled_plugins`
- Modify: `test/test_provider_profiles.py` near the Claude settings materialization tests

**Interfaces:**
- Consumes: `materialize_claude_home_config()` and existing source/managed settings fixtures.
- Produces: Regression coverage proving stale plugin entries are removed and changed values are refreshed while hooks/permissions remain.

- [x] **Step 1: Update the existing plugin test expectation**

Change the managed `enabledPlugins` fixture to represent stale entries and assert that the result contains only the source map, including the source disable value.

- [x] **Step 2: Add a deletion regression test**

Materialize once with a source plugin, remove that plugin from the source settings, materialize again, and assert the managed settings no longer contain it.

- [x] **Step 3: Run the focused tests and verify failure**

Run: `python3 -m pytest test/test_provider_profiles.py -k 'materialize_claude_home_config and enabled_plugins' -q`

Expected: the new source-authoritative assertions fail before the implementation change.

### Task 2: Make plugin settings source-authoritative

**Files:**
- Modify: `lib/provider_backends/claude/launcher_runtime/home.py` around `_CLAUDE_RUNTIME_SETTINGS_KEYS` and `_merge_settings_payload`

**Interfaces:**
- Consumes: projected source settings from `_projected_settings_payload()` and existing managed settings.
- Produces: merged settings where `enabledPlugins` is not carried forward from the managed file, while hooks and permissions retain current behavior.

- [x] **Step 1: Narrow managed runtime carry-forward keys**

Remove `enabledPlugins` from the loop that carries managed runtime settings forward. Leave `hooks` and `permissions` in that loop, so `merged` retains the existing hook merge and CCB-only permission handling.

- [x] **Step 2: Preserve source plugin projection semantics**

Keep `merged` initialized from `projected_payload`; do not add a second plugin merge path. This makes an absent source `enabledPlugins` remove the stale target field and makes source values authoritative.

- [x] **Step 3: Run the focused tests**

Run: `python3 -m pytest test/test_provider_profiles.py -k 'materialize_claude_home_config and enabled_plugins' -q`

Expected: all plugin refresh tests pass.

### Task 3: Verify runtime preservation and launch behavior

**Files:**
- Test: `test/test_provider_profiles.py`
- Test: `test/test_v2_runtime_launch.py`

**Interfaces:**
- Consumes: updated settings merge behavior through normal Claude HOME preparation.
- Produces: evidence that CCB hooks/permissions and startup materialization remain intact.

- [x] **Step 1: Run Claude settings and profile tests**

Run: `python3 -m pytest test/test_provider_profiles.py -k 'claude_home_config or claude' -q`

- [x] **Step 2: Run Claude runtime launch tests**

Run: `python3 -m pytest test/test_v2_runtime_launch.py -k 'claude_home_overrides or claude' -q`

- [x] **Step 3: Run syntax validation**

Run: `python3 -m py_compile lib/provider_backends/claude/launcher_runtime/home.py`
