---
id: BUG-003
title: Search mode camera rotation uses character movement keys instead of camera arrow keys
status: resolved
severity: medium
created: 2026-08-16
updated: 2026-08-16
---

# BUG-003: Search mode camera rotation uses character movement keys instead of camera arrow keys

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Start autonomous farming with no monsters in the immediate camera viewport.
2. Allow the bot to transition to `SEARCHING` and trigger Tier 1 search rotation (`SearchMode.ROTATE`).
3. Observe the game client behavior.

## Expected behavior

Per [US-015](../../user-stories/US-015-idle-timeout-and-search-navigation.md), Tier 1 search should rotate the in-game camera 360 degrees horizontally to scan for nearby monsters. In Flyff, camera rotation is bound to the **Arrow Keys** (Left Arrow `VK_LEFT` / Right Arrow `VK_RIGHT`). The rotation step should continuously turn the camera in one direction (e.g. Right Arrow) to complete a sweep of the surrounding area.

## Actual behavior

`SearchController` in `src/flyff_bot/features/automation/controllers.py` dispatches `VIRTUAL_KEY_A` and `VIRTUAL_KEY_D` alternately:
```python
virtual_key = (VIRTUAL_KEY_A, VIRTUAL_KEY_D)[self._rotation_index % 2]
```
In Flyff, `A` and `D` are character turning/strafing keys rather than camera orbit controls. Consequently, the camera viewport does not rotate, and the character merely oscillates back and forth in place without scanning the environment.

## Impact and frequency

- Impact: Medium. The bot fails to rotate the camera viewport to detect monsters outside its immediate initial field of view during search mode.
- Frequency: 100% reproducible whenever `SearchMode.ROTATE` executes.

## Regression verification

- [x] A failing automated test verifying `SearchController` emits camera arrow keys (`VK_RIGHT` or `VK_LEFT`) during `SearchMode.ROTATE`.
- [x] The check passes after the fix.
- [x] Related documentation is current.
