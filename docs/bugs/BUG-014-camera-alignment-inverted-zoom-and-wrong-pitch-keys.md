---
id: BUG-014
title: Camera alignment uses inverted wheel direction and non-functional pitch keys
status: reported
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

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
