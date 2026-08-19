---
id: US-044
title: Universal ground-plane spawn distance model
status: rejected
created: 2026-08-19
updated: 2026-08-19
---

# US-044: Universal ground-plane spawn distance model

## Rejection / Obsolescence

Superseded on 2026-08-19 by [US-045](../US-045-vector-world-terrain-extraction-and-goal-navigation.md) without implementation.

US-044 proposed estimating mob world coordinates from 2D camera bounding boxes using an inverse projective ground-plane model ($d = k / (y_{\text{bottom}} - y_{\text{horizon}})$) to populate a learned heuristic spawn heatmap without per-species calibration runs.

With US-045, the application extracts authoritative ground-truth vector spawn zones, coordinates, and bounds directly from client world files (`.rgn`, `.wld`, `.lnd`). Because all spawn clusters and boundaries are known a priori, heuristic estimation of spawn distances from camera viewport projections is completely obsolete.

The original specification is preserved below unchanged.

## Story

As a **bot operator setting up navigation on any mob camp**, I want **the spawn distance to be calculated from the bottom edge of mob bounding boxes using a projective ground-plane model instead of requiring individual calibration per mob species**, so that **spawn hotspots are placed accurately for all monster types with a single universal camera calibration**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Previous work:
  - [US-035](completed/US-035-measured-minimap-odometry-and-tracking-quality.md) established the canonical coordinate system in minimap pixels via minimap odometry.
  - [US-037](US-037-measured-spawn-distance-and-enforced-leash.md) and [US-041](completed/US-041-spawn-distance-calibration-capture-script.md) introduced distance calibration using bounding box height (`a / bbox_height + b`), but that approach inherently depends on each mob's physical 3D mesh height ($H_{\text{3D}}$), requiring repeated calibration runs for every mob class.
  - [US-042](completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md) established deterministic pre-flight camera alignment: mouse wheel zoomed out to hard-stop and a standardized ~45° pitch tilt.
- Ground-plane projection principle:
  - In Flyff's third-person perspective, all terrestrial mobs stand on the ground plane ($Z = 0$).
  - Given a fixed camera pitch and zoom, the vertical screen coordinate of a mob's contact point with the ground (the bottom edge of its bounding box, $y_{\text{bottom}} = y + \text{height}$) uniquely defines its forward distance $d_{\text{forward}}$ on the ground plane, regardless of how tall or short the mob's 3D mesh is.
  - The projective ground-plane distance formula is:
    $$d_{\text{forward}} = \frac{k}{y_{\text{bottom}} - y_{\text{horizon}}}$$
    where $y_{\text{horizon}}$ is the vertical horizon line on screen (where ground distance approaches infinity) and $k$ is the camera geometry scaling coefficient.
  - The lateral offset (and resulting bearing angle) is computed from the horizontal offset of the box centre from the viewport midline ($x_{\text{centre}} - x_{\text{midpoint}}$).
- Calibration requirements:
  - A single reference walk-in on any ground mob is sufficient to fit $k$ and $y_{\text{horizon}}$.
  - The resulting parameters are universal across all mob classes, eliminating per-species calibration.

## Acceptance criteria

- [ ] Given a detected mob bounding box and a known viewport, when `PathingController._estimate_mob_position` estimates its world position, then the forward distance is computed from $y_{\text{bottom}}$ using the projective ground-plane model ($k / (y_{\text{bottom}} - y_{\text{horizon}})$).
- [ ] Given any mob class (large or small), when standing at the same ground distance from the player, their estimated positions on the 2D navigation map have consistent distance values.
- [ ] Given a mob whose $y_{\text{bottom}}$ is near or above the horizon line ($y_{\text{bottom}} \le y_{\text{horizon}} + \epsilon$), when estimating its position, then its distance is clamped to a maximum visibility limit (e.g. `leash_radius_pixels`) or discarded rather than producing negative or infinite distances.
- [ ] Given a mob directly adjacent to or below the character, when estimating its position, then its distance is clamped to a minimum melee clearance distance (e.g. `3.0` minimap pixels).
- [ ] Given the calibration harness in `scripts/capture_spawn_distance_samples.py`, when a walk-in is analyzed, then it fits the universal ground-plane parameters ($k$, $y_{\text{horizon}}$) and residual error across the approach sequence.
- [ ] Given no viewport is known or frame dimensions are invalid, then sightings are ignored rather than recorded at arbitrary fixed coordinates.
- [ ] All constants, parameters, and residual tolerances are explicitly named, typed, and documented with references to calibration evidence.
- [ ] All new user-visible text or diagnostics (if any) are present and synchronised in `de.json` and `en.json`.

## Out of scope

- Flying / elevated aerial pathing (Flyff ground monsters only).
- Non-flat 3D topographical mesh raytracing (ground plane approximation is used).
- Real-time dynamic camera pitch tracking during manual player camera movements (camera must be aligned via standard pre-flight alignment).

## Verification

- Automated:
  - Unit tests verifying the ground-plane projection formula with synthetic and fixture-based bounding boxes of various heights and positions.
  - Unit tests verifying clamping behavior (horizon singularity clamping, melee minimum clamping, invalid viewport dropping).
  - Regression tests for `capture_spawn_distance_samples.py` fitting $k$ and $y_{\text{horizon}}$ accurately from sample sequences.
  - Verification suite pass (`./scripts/check.ps1`: `uv sync`, `ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run one walk-in calibration run on a test mob using `scripts/capture_spawn_distance_samples.py`.
  - Start a farming session on a camp with mixed or different mobs and verify on the Path Inspector widget that spawn heat dots align with visible monster positions in the 3D world.
