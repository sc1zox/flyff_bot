---
id: BUG-041
title: Camera alignment fails closed with top-down pitch inversion and non-functional zoom-out
status: reported
severity: high
created: 2026-08-30
updated: 2026-08-30
---

# BUG-041: Camera alignment fails closed with top-down pitch inversion and non-functional zoom-out

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14.7 (`.python-version`)
- Application revision: `main` (`9e12353`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Launch Flyff with a character logged into the game world and foreground the client window.
2. Trigger camera alignment via desktop UI ("Align Camera" button / pre-flight startup) or automated session.
3. Observe the resulting camera zoom and pitch movements in the active game viewport.

## Expected behavior

Per [US-042](../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), [US-056](../user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md), and [US-084](../user-stories/completed/US-084-bounded-tactical-parameter-space-and-unified-profile-schema.md), `CameraAligner.align()` must:
1. Zoom the camera all the way out to the physical engine hard stop (`zoom_out_notches` / `camera_zoom_level = 20.0`).
2. Adjust vertical camera pitch to the standardized ~45° downward-looking perspective (or configured target pitch in tactical parameters).
3. Successfully converge and return `CameraAlignmentStatus.ALIGNED`.

## Actual behavior

1. **Top-Down Pitch Inversion:** `live_camera.py` calculates `pitch_radians = asin(forward.y)`. When the camera looks downward at the player/ground, `forward.y` is negative, yielding negative pitch angles (e.g. -45.0°). However, `CALIBRATED_CAMERA_PITCH_DEGREES` and `TacticalParameterName.CAMERA_PITCH_DEGREES` define the target as positive `+45.0°`. The error calculation `error = target_pitch_degrees - reading.pitch_degrees` produces a large positive error (`45.0 - (-45.0) = +90.0°`). Because `error > 0.0`, `CameraAligner` repeatedly sends `pitch_up_virtual_key` (`VK_UP`), tilting the camera upward into the maximum vertical top-down ceiling. After reaching `maximum_pitch_steps` (20), `CameraAligner.align()` returns `CameraAlignmentStatus.NOT_CONVERGED`.
2. **Premature Zoom Loop Abort:** The zoom loop checks `zoom_delta = reading.zoom_distance - previous_zoom` on single-notch increments (`scroll_wheel_while_guarded(1)`). If a single notch produces no immediate measurable change within `step_settle_seconds` (`zoom_delta <= 0.01`), the loop prematurely breaks (`zoom_stopped = True`) on the very first step without zooming out.

## Impact and frequency

- Impact: High. Camera alignment fails completely on live clients, leaving the camera stuck in top-down view and preventing pre-flight farming automation from starting.
- Frequency: 100% deterministic on every camera alignment attempt in live gameplay.

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
