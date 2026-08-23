---
id: BUG-027
title: Arrival observer relies on private reader state
status: reported
severity: medium
created: 2026-08-23
updated: 2026-08-23
---

# BUG-027: Arrival observer relies on private reader state

## Environment

- Windows version: Windows 11 (unit-level code review)
- Python version: Python 3.14.7 (`uv` environment)
- Application revision: branch `refactor/main-window-feature-slices` (commit `d4a166f`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`) for the production observer path

## Reproduction

1. Instantiate `LiveArrivalObserver` with a position-reader object exposing public `poll()` and `_last_reading`.
2. Call `LiveArrivalObserver.observe()`.
3. Trace the implementation's `getattr(..., "poll", None)` and `getattr(..., "_last_reading", None)` fallbacks.
4. Change the position reader API to return its reading through a differently named accessor or make `_last_reading` unavailable.

## Expected behavior

A production adapter should depend on a small explicitly typed protocol owned at the feature boundary, such as one operation returning position and sample time. It should not introspect object shape or read another class's private attributes. Imports belong at module scope unless a documented lazy-loading requirement exists.

## Actual behavior

`LiveArrivalObserver` treats `position_reader` as `object`, probes for callable `poll()`, then falls back to private `_last_reading`. It imports `time.monotonic` locally inside the polling branch. This couples the dispatcher to implementation details of the position reader, weakens typing and error behavior, and makes alternate readers fragile.

## Impact and frequency

- Impact: Medium. Reduces maintainability and type safety and can silently select stale/private state instead of producing a clear contract failure.
- Frequency: Deterministic on every production arrival observation using the current coupling.

## Regression verification

- [ ] A failing mypy/test check rejects a position reader that does not satisfy the explicit arrival-sampling protocol.
- [ ] Tests cover fresh polling, unavailable readings, and malformed adapters without accessing private attributes.
- [ ] Production code removes reflective access and the function-local standard-library import.
- [ ] The complete repository gate passes.
