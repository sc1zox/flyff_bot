---
id: US-043
title: Continuous approach target tracking and automated minimap zoom initialization
status: draft
created: 2026-08-18
updated: 2026-08-18
---

# US-043: Continuous approach target tracking and automated minimap zoom initialization

## Story

As a **developer or operator executing spawn distance calibration or approach runs**,
I want **the capture harness and pre-flight routines to automatically zoom out the minimap to the standardized base level (10x clicks on `-`) and continuously track the specific mob in front of the player across frames via bounding-box proximity instead of picking arbitrary high-confidence mobs**,
so that **recorded calibration walk-ins yield consistent, monotonically growing bounding box heights against stable minimap odometry without manual UI adjustment or detection thrashing across multi-mob groups**.

## Context and assumptions

- During calibration runs ([US-037](US-037-measured-spawn-distance-and-enforced-leash.md), [US-041](completed/US-041-spawn-distance-calibration-capture-script.md)), the player walks toward a target mob in the center of the screen while recording YOLO bounding box heights $h$ and minimap odometry $\Delta d$.
- Multiple mobs of the target class often populate the viewport simultaneously (e.g. 10+ Flames in a spawn cluster).
- Previously, `scripts/capture_spawn_distance_samples.py` selected the candidate with `max(candidates, key=lambda d: d.confidence)`. Because confidence fluctuated frame-to-frame, the focus jumped between foreground and background mobs (e.g. from $h=49$ px to $h=196$ px to $h=85$ px), corrupting the monotonic distance relation.
- Tracking the specific approach target requires:
  1. In frame 0, identifying the target candidate matching the target class closest to the horizontal centerline of the screen ($|x_{\text{centre}} - \text{viewport\_width}/2|$ minimal).
  2. In subsequent frames, tracking that specific bounding box across frames using spatial proximity (nearest centroid / bounding box IoU / distance gate) so the recorded heights $h$ reflect the same physical mob instance throughout the approach.
- Minimap Odometry ([US-035](completed/US-035-measured-minimap-odometry-and-tracking-quality.md)) operates at a calibrated zoom scale. If the minimap is not at its hard-stop zoom-out level, or if UI setup varies, odometry and zoom signatures can deviate.
- In the Flyff client, the minimap HUD includes a zoom-out (`-`) button positioned relative to the located minimap ring geometry (`MinimapGeometry`).
- Similar to the camera zoom hard-stop in [US-042](completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), clicking the minimap `-` button 10 times establishes a deterministic, reproducible zoom-out hard-stop prior to calibration and farming sessions.
- In addition, the minimap ring detection angular deviation tolerance (`RING_MAXIMUM_ANGULAR_DEVIATION`) and zoom signature tolerance (`ZOOM_SIGNATURE_TOLERANCE_FRACTION`) should accommodate natural variations across different terrain textures without falsely dropping into `degraded` mode during contiguous linear runs.

## Acceptance criteria

### 1. Continuous Approach Target Tracking
- [ ] Given a walk-in run initiated with a specified `--mob-class`, when frame 0 is processed, the candidate matching `--mob-class` with the smallest horizontal distance from the screen centerline ($|x_{\text{centre}} - \text{viewport\_width}/2|$) is selected as the primary approach target.
- [ ] Across all subsequent frames of the walk-in sequence, the detector tracks the target mob instance based on nearest spatial centroid distance and bounding-box overlap relative to the previous frame's tracked box.
- [ ] If the tracked mob is temporarily obscured or dropped for 1-2 frames, the tracker maintains its last estimated position and re-acquires the matching candidate within a configurable pixel radius rather than jumping to unrelated distant mobs.
- [ ] Stored frame crops and `manifest.json` detection entries designate the tracked approach mob uniquely per frame.

### 2. Automated Minimap Zoom-Out Initialization
- [ ] Given a pre-flight alignment sequence (or capture harness initialization), when automated setup runs (unless `--no-camera-align` is specified), the system identifies the minimap HUD geometry (`MinimapGeometry`).
- [ ] The system computes the relative client click coordinates of the minimap zoom-out (`-`) button from `MinimapGeometry` and dispatches 10 guarded mouse click pulses (with settle delay between clicks).
- [ ] This guarantees the minimap enters its maximum zoom-out hard-stop deterministically before odometry recording or navigation starts.

### 3. Odometry Robustness across Varying Terrains
- [ ] Minimap ring detection tolerates minor ambient lighting / UI shadow variations (angular deviation threshold calibrated to 20.0).
- [ ] The `MovementTracker` zoom signature tolerance (`ZOOM_SIGNATURE_TOLERANCE_FRACTION`) is set to 0.20 (20%) to prevent terrain texture detail variations during straight walks from falsely triggering uncommanded zoom-change state transitions.

### 4. Safety and Cancellation Boundaries
- [ ] Minimap clicks and camera inputs strictly enforce Windows foreground window checks and abort immediately if focus is lost or if the `END` key emergency stop is pressed.
- [ ] All user-facing error messages, diagnostics, and CLI feedback are clearly formatted and logged.

## Out of scope

- Direct 3D camera injection or client memory modification.
- Multi-target tracking across disconnected non-contiguous camera pans (covered by separate navigation stories).
- Modifying the core YOLO ONNX model weights.

## Verification

- Automated:
  - Unit tests verifying centroid/IoU tracking on multi-mob sequence fixtures, asserting zero target jumping between disparate mobs.
  - Unit tests for minimap button coordinate computation and guarded click dispatch.
  - Unit tests verifying tracking quality resilience across terrain texture transitions within 20% tolerance.
  - `pwsh -File .\scripts\check.ps1`.
- Manual (Windows):
  - Run `uv run python scripts/capture_spawn_distance_samples.py walk-in --mob-class Flame --label test_track` in a dense mob group.
  - Verify that the minimap is clicked 10x to zoom out, the camera is aligned, and the single target mob in front is tracked smoothly from start to finish with monotonically increasing bounding box height.
