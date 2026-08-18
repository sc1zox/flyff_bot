---
id: BUG-014
title: Camera alignment uses inverted wheel direction and non-functional pitch keys
status: resolved
severity: high
created: 2026-08-18
updated: 2026-08-18
---

# BUG-014: Camera alignment uses inverted wheel direction and non-functional pitch keys

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff (neuz.exe)

## Reproduction

1. Launch Flyff with a character logged into the game world.
2. Run `uv run python scripts/capture_spawn_distance_samples.py walk-in --mob-class Rapra --label rapra_run1 --hold 4.0` (or click "Align Camera" / trigger auto-align in the desktop dashboard).
3. Foreground the game client window during the 3-second countdown.
4. Observe the mouse wheel zoom action and keyboard pitch adjustments in the Flyff viewport.

## Expected behavior

Per [US-042](../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), `CameraAligner` must:
1. Zoom the camera all the way out to its physical hard-stop by scrolling the mouse wheel forward (`+WHEEL_DELTA` with sufficient notches).
2. Drive vertical camera pitch to its ceiling limit using the Flyff camera pitch up key (`VK_UP` / Up Arrow).
3. Apply a calibrated downward pitch pulse using the Flyff camera pitch down key (`VK_DOWN` / Down Arrow) to achieve the standardized ~45° elevation.

## Actual behavior

1. **Inverted Wheel Direction:** `CameraAlignmentConfig.zoom_out_notches` is set to `-15` (negative wheel delta), which in Flyff causes the camera to zoom *in* towards the character rather than zooming *out* to maximum distance. Furthermore, 15 notches may be insufficient to guarantee hitting the zoom hard stop from a fully zoomed-in state.
2. **Wrong Pitch Keys:** `CameraAlignmentConfig` dispatches `VK_PRIOR` (`0x21` / Page Up) and `VK_NEXT` (`0x22` / Page Down). In Flyff, vertical camera pitch is controlled by `VK_UP` and `VK_DOWN` (Arrow keys). Because Page Up/Down are unmapped or ignored for camera pitch in the standard client, the camera does not recover to the ~45° standardized pitch (remaining stuck at whatever pitch it was in, e.g. top-down if manually tilted up).

## Impact and frequency

- Impact: High. Inverted zoom and missing pitch adjustment invalidate the perspective assumptions of the spawn distance calibration model (US-037/US-041) and blind the bot to distant spawns.
- Frequency: 100% reproducible on any invocation of `CameraAligner.align()` (via calibration script, UI button, or orchestrator pre-flight).

## Resolution

`CameraAlignmentConfig` now scrolls the wheel forwards (`ZOOM_OUT_WHEEL_NOTCHES = 30`), which is
Flyff's zoom-out direction, and the notch count outruns the zoom range from a fully zoomed-in start
instead of only from a partial one. `__post_init__` rejects a non-positive count so a backwards
configuration cannot be supplied again. Camera pitch is dispatched with `VIRTUAL_KEY_UP` /
`VIRTUAL_KEY_DOWN`, reused from `features/automation/controllers.py` rather than redefined, so the
alignment routine tilts with the same arrow keys the search sequence already uses. The
`scroll_wheel_while_guarded` docstring, which documented the inverted direction as fact, was
corrected with it.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
  `tests/unit/test_camera_alignment.py::test_alignment_zooms_out_forwards_past_the_hard_stop_with_the_arrow_pitch_keys`
  pins the forward wheel direction, the overshooting notch count, and the arrow pitch keys; the
  sequence and configuration-validation tests assert the same values through `CameraAligner.align()`.
- [x] The check passes after the fix. `pwsh -File .\scripts\check.ps1` is green (504 passed, 2 skipped).
- [x] Related documentation is current. `docs/wiki/architecture.md` and `docs/wiki/glossary.md` state
  the corrected direction and keys.
