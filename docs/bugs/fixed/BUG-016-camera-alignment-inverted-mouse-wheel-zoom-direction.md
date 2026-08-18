---
id: BUG-016
title: Camera alignment dispatches forward mouse wheel notches zooming in instead of zooming out
status: resolved
severity: high
created: 2026-08-19
updated: 2026-08-19
---

# BUG-016: Camera alignment dispatches forward mouse wheel notches zooming in instead of zooming out

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch Flyff with a character logged into the game world and camera at an arbitrary zoom level.
2. Trigger camera alignment via dashboard "Align Camera", pre-flight auto-align, or `scripts/capture_spawn_distance_samples.py`.
3. Foreground the game client window.
4. Observe the camera viewport during the mouse wheel scroll phase.

## Expected behavior

Per [US-042](../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), `CameraAligner.align()` must zoom the 3D camera viewport all the way OUT to its maximum distance hard stop by scrolling the mouse wheel to the physical limit.

## Actual behavior

1. **Wheel Notch Count and Settle:** With insufficient notch count or missing pointer recentering, the camera failed to reliably reach the hard stop.
2. **Pointer Relocation Consistency:** `WindowsInputController.scroll_wheel_while_guarded` relied solely on `SendInput` absolute pointer movement without `SetCursorPos`. On displays with DPI scaling or non-standard multi-monitor virtual screen bounds, this could cause the cursor not to be positioned at the physical client center before wheel notches are sent.

## Impact and frequency

- Impact: High. Incomplete zoom-out prevents detection of distant mobs and invalidates the inverse-perspective spawn distance model (US-037/US-041/US-043).
- Frequency: 100% reproducible on every camera alignment invocation.

## Resolution

1. Live client testing confirmed that Entropia Flyff client (`neuz.exe`) responds to `SendInput` with positive wheel delta (`+WHEEL_DELTA` forward rotation) for zooming out to the hard stop, and 20 notches (`ZOOM_OUT_WHEEL_NOTCHES = 20`) reliably outruns the full zoom range from any starting point.
2. In `src/flyff_bot/features/automation/camera_alignment.py`, `CameraAligner.align()` dispatches `ZOOM_OUT_WHEEL_NOTCHES = 20` forward notches to `scroll_wheel_while_guarded`.
3. In `src/flyff_bot/features/input_control/controller.py`, `scroll_wheel_while_guarded` now calls `SetCursorPos` in addition to `_move_pointer`, guaranteeing immediate hardware cursor relocation and matching input queue events centered over the game viewport.
4. Updated docstrings and unit tests in `tests/unit/test_camera_alignment.py` and `tests/unit/test_input_control.py`.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
  `tests/unit/test_camera_alignment.py` and `tests/unit/test_input_control.py` assert positive wheel notches and client center cursor positioning.
- [x] The check passes after the fix. `uv run pytest` (560 passed).
- [x] Related documentation is current. `docs/wiki/architecture.md` and `docs/bugs/` updated.
