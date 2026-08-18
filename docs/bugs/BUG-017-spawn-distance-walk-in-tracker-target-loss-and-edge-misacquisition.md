---
id: BUG-017
title: Spawn distance walk-in tracker target loss and edge mob misacquisition
status: reported
severity: high
created: 2026-08-19
updated: 2026-08-19
---

# BUG-017: Spawn distance walk-in tracker target loss and edge mob misacquisition

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Position a character in Flyff facing towards a target mob (e.g. Flame) in the game world.
2. Run `uv run python scripts/capture_spawn_distance_samples.py walk-in --mob-class Flame --label flame_run --hold 4.0`.
3. Let the character walk in for 4.0 seconds while the client is foregrounded.
4. Inspect the resulting manifest report.

## Expected behavior

Per [US-043](../user-stories/completed/US-043-spawn-distance-calibration-data-collection-and-model-fitting.md), `capture_spawn_distance_samples.py walk-in` must reliably acquire the mob directly in front of the character along the central approach corridor, follow it continuously across the approach frames as its bounding-box height increases, tolerate minor YOLO detection dropouts and scale growth, and record sufficient samples (typically 30–50 frames per 4s run) to fit the inverse-distance regression model.

## Actual behavior

1. **Peripheral Mob Misacquisition:** `ApproachTargetTracker._acquire` lacks a maximum acquisition corridor gate. If no candidate is detected in the exact center on early frames, it picks any candidate at the far screen periphery (e.g. `x = 317` on a 2560px viewport, `centre_x_offset = -933.5 px`). As the player moves forward, this peripheral mob quickly drifts off-screen after 2–4 frames.
2. **Premature Permanent Lockout:** `APPROACH_TARGET_MAXIMUM_MISSED_FRAMES = 2` permanently latches `self._lost = True` after only 2 consecutive missed frames (~120ms). Once the misacquired peripheral mob leaves the screen or if YOLO has a brief 3-frame detection skip, the tracker permanently refuses all remaining frames of the run. In `flame_run4`, 92 mob detections were recorded across 58 frames, but the approach tracker dropped out at frame 8 and ignored a 94% confidence Flame right in front of the camera at frame 17.
3. **Approach Steering & Key Support:** Blindly holding `w` requires manual alignment that diverges if the character or mob is slightly offset. Supporting targeted attack/approach keys (e.g. action slot / `F3` melee attack approach) or adaptive central corridor tracking would keep the target centered throughout the approach.

## Impact and frequency

- Impact: High. Walk-in calibration runs capture only 1 to 6 samples instead of 40–50, producing insufficient data for robust inverse-distance model fitting.
- Frequency: 100% reproducible on standard walk-in calibration runs.

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
