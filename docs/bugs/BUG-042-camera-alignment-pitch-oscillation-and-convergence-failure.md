---
id: BUG-042
title: Camera alignment pitch oscillation, excessive steepness, and search rotation perception failure
status: reported
severity: high
created: 2026-08-30
updated: 2026-08-30
---

# BUG-042: Camera alignment pitch oscillation, excessive steepness, and search rotation perception failure

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14.7 (`.python-version`)
- Application revision: `main`
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Launch Flyff with a character logged into the game world and foreground the client window.
2. Start an automated session or trigger camera alignment via desktop UI.
3. Observe the camera behavior in the game viewport during the `Ausrichtung` (Alignment) phase.
4. If alignment succeeds or terminates, observe character behavior during search mode when no immediate target is in close proximity.

## Expected behavior

Per [US-018](../user-stories/completed/US-018-multi-axis-camera-search-and-paced-scanning.md), [US-042](../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), [US-056](../user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md), and [US-084](../user-stories/completed/US-084-bounded-tactical-parameter-space-and-unified-profile-schema.md):
1. **Zoom & Pitch Alignment**:
   - The camera zooms out to the hard stop.
   - The vertical camera pitch smoothly converges to a calibrated, ergonomic ~30.0° target perspective (providing a clear forward view of the horizon and distant monster spawns) within a stable tolerance band (±2.5°) without limit-cycle oscillation.
   - `CameraAligner.align()` returns `CameraAlignmentStatus.ALIGNED` in 1–3 gentle steps.
2. **Search Mode Perception**:
   - When searching for monsters, the camera rotates in paced micro-steps with clean settle pauses so YOLO perception operates on unblurred stationary frames.
   - With the 30.0° elevation, far-field spawns are visible in the viewport, preventing repeated endless 360° spin loops.

## Actual behavior

1. **Pitch Oscillation and Convergence Failure**:
   - Mouse wheel zoom-out succeeds.
   - During pitch adjustment, the camera rapidly bobs / wobbles up and down ("wackelt hoch und runter") between high and low angles.
   - Because each fixed key pulse (`0.08s`) causes an angular displacement (~6°–10°) larger than the narrow tolerance window (`±1.5°`), the bang-bang control loop repeatedly overshoots the target in alternating directions.
   - When 20 steps (`maximum_pitch_steps = 20`, ~7 seconds elapsed) are exhausted, `CameraAligner.align()` returns `CameraAlignmentStatus.NOT_CONVERGED` and pauses the session (`alignment_failed:not_converged`).
2. **Excessive 45° Pitch Angle (Steep Bird's-Eye View)**:
   - When the pitch loop occasionally happens to land inside the 45.0° target window by chance, the camera remains pitched at 45.0° (too steep).
   - At 45.0°, the camera points steeply downward onto the character's head, cutting off the horizon and distant spawn areas.
3. **Endless 360° Search Spin and YOLO Degradation**:
   - Because distant spawns are outside the steep 45° viewport, the search controller performs multiple full 360° camera rotations.
   - During continuous rotational movement, motion smearing impairs YOLO detection confidence, resulting in missed mob detections and persistent spinning.

## Root Cause Analysis

1. **Fixed Bang-Bang Pitch Actuation**:
   - `CameraAligner` sends fixed `0.08s` key pulses (`VK_UP` / `VK_DOWN`). Flyff's camera pitch velocity (~80°/s) produces ~6°–10° jumps per step, making it impossible to reliably land within a `±1.5°` tolerance without proportional pulse damping.
2. **Overly Steep 45.0° Target Pitch**:
   - `CALIBRATED_CAMERA_PITCH_DEGREES = 45.0` and `TacticalParameterName.CAMERA_PITCH_DEGREES = 45.0` default to a steep downward angle rather than a balanced 30.0° perspective.
3. **Search Rotation Settling**:
   - Continuous or insufficiently settled rotation causes motion blur that degrades real-time YOLO object detection.

## Proposed Resolution

1. **Update Default Target Pitch**:
   - Change `CALIBRATED_CAMERA_PITCH_DEGREES` and `TacticalParameterSpace` default from `45.0°` to `30.0°`.
2. **Implement Proportional Adaptive Pitch Damping**:
   - Scale key pulse duration dynamically based on remaining angular error:
     - $|error| > 10.0^\circ$: `0.08s`
     - $5.0^\circ < |error| \le 10.0^\circ$: `0.05s`
     - $|error| \le 5.0^\circ$: `0.025s`
   - Set `pitch_tolerance_degrees = 2.5` to ensure swift, robust convergence without oscillation.
3. **Refine Search Settling Pacing**:
   - Ensure search rotation settle duration allows YOLO to capture stable, unblurred frames.

## Impact and frequency

- Impact: High. Camera alignment fails or locks the camera into an excessively steep perspective that degrades mob detection and induces spinning.
- Frequency: 100% reproducible on live client startup.

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
