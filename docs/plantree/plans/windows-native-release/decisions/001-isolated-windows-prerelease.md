# Decision 001: isolated Windows prerelease

Date: 2026-08-11
Status: accepted

## Decision

Publish PR #293 follow-up work as a dedicated Windows prerelease. Windows
runtime code lives in `lib/platforms/windows/`; installer, launcher, packaging,
docs, and tools live in `platforms/windows/`. Shared Linux/macOS release
builders and npm metadata remain Windows-free.

The prerelease contains native PE command launchers plus Python source. It is
explicitly not a self-contained or signed executable distribution. A future
self-contained build requires a separate design because CCB spawns Python
daemon and helper processes at runtime.

## Consequences

- Stable release workflows skip prerelease tags.
- Windows artifacts are built only by the Windows workflow.
- A failed immutable beta tag is followed by a new beta tag; it is not moved.
- Real Windows/WezTerm/Herdr qualification may downgrade or block subsequent
  promotion without retracting the test artifact.
