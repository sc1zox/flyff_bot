---
id: BUG-023
title: Player stats reader masks invalid pointer and malformed read diagnostics
status: reported
severity: medium
created: 2026-08-23
updated: 2026-08-23
---

# BUG-023: Player stats reader masks invalid pointer and malformed read diagnostics

## Environment

- Windows version: Windows 11
- Python version: Python 3.14 (.python-version)
- Application revision: branch `feature-us-076-client-player-stats-reader` (commit `ec1ddbc`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Instantiate `LivePlayerStatsReader` with a synthetic or mock API where the player pointer at `module_base + player_pointer_rva` evaluates to `0` (null) or where `read()` returns a short or non-finite payload.
2. Call `reader.poll(at_seconds=0.0)`.
3. Inspect `snapshot.error.code`.
4. Observe that `snapshot.error.code` is `PlayerStatsReadErrorCode.HANDLE_LOST` instead of `PlayerStatsReadErrorCode.INVALID_POINTER` or `PlayerStatsReadErrorCode.MALFORMED_READ`.

## Expected behavior

According to [US-076](../user-stories/US-076-complete-client-player-stats-reader.md):
- When an invalid (null) pointer is encountered, `LivePlayerStatsReader` must return diagnostic error code `PlayerStatsReadErrorCode.INVALID_POINTER`.
- When a short read or non-finite value occurs during structure decoding, `LivePlayerStatsReader` must return diagnostic error code `PlayerStatsReadErrorCode.MALFORMED_READ`.
- `PlayerStatsReadErrorCode.HANDLE_LOST` should only be returned when an underlying OS read error (`OSError`, `struct.error`) occurs on an established handle.

## Actual behavior

In `LivePlayerStatsReader.poll()`:
- `_InvalidPlayerPointer`, `_MalformedStatsRead`, and `ValueError` from `profile.decode()` are caught in the catch-all `except (OSError, ValueError, struct.error) as error:` block.
- `_fail(PlayerStatsReadErrorCode.HANDLE_LOST, str(error))` is invoked unconditionally, making `INVALID_POINTER` and `MALFORMED_READ` unreachable dead code.

## Impact and frequency

- **Impact:** Medium. Degrades observability by reporting all read decoding and null pointer errors as lost handles.
- **Frequency:** Deterministic whenever a null player pointer, short structure read, or profile bounds violation occurs.

## Regression verification

- [ ] A failing automated test asserts `PlayerStatsReadErrorCode.INVALID_POINTER` when player pointer is null.
- [ ] A failing automated test asserts `PlayerStatsReadErrorCode.MALFORMED_READ` when short or non-finite payloads are read.
- [ ] The checks pass after adding explicit `except` handlers for `_InvalidPlayerPointer` and `_MalformedStatsRead` in `LivePlayerStatsReader.poll()`.
- [ ] Related documentation is current.
