---
id: US-057
title: YOLO bottom-center camera unprojection and NavMesh mob world positioning
status: completed
created: 2026-08-20
updated: 2026-08-20
---

# US-057: YOLO Bottom-Center Camera Unprojection and NavMesh Mob World Positioning

## Story

As a **Flyff bot developer and autonomous combat engineer**,
I want **detected YOLO entity bounding boxes to be unprojected from their bottom-center ground contact points into 3D world rays and intersected against authoritative NavMesh surfaces**,
so that **mobs have exact, terrain-conforming 3D world coordinates and NavMesh polygon IDs for navigation, range leashing, and collision-free pathing without relying on fragile 2D distance heuristics or body-center parallax errors.**

## Scope & Pipeline

This story integrates the camera memory reader ([US-056](completed/US-056-client-camera-state-and-projection-matrix-reader.md)), the authoritative 3D NavMesh ([US-055](US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md)), and YOLO mob detection ([US-003](completed/US-003-mob-detection-yolo.md)):

```text
YOLO Bounding Box (x1, y1, x2, y2)
        ↓
Ground Contact Point: bottom-center ((x1 + x2) / 2, y2)
        ↓
Camera State via RPM (US-056) + Viewport Dimensions (W, H)
        ↓
Screen-to-World Ray Unprojection (WorldRay3D)
        ↓
Möller–Trumbore Ray–Triangle Intersection vs. Active NavMesh Chunks (US-055)
        ↓
EstimatedMobWorldPosition
  - position: WorldPosition(X, Y, Z)
  - navmesh_polygon_id: int | None
  - distance_to_player: float
  - confidence: float
  - class_name: str
```

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only process memory access for camera and player state.
  - [`docs/user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md`](completed/US-056-client-camera-state-and-projection-matrix-reader.md): Live camera memory reader and `unproject_screen_ray()` unprojection.
  - [`docs/user-stories/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md`](US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md): Authoritative 3D world geometry and multi-layer NavMesh.
  - [`docs/user-stories/completed/US-003-mob-detection-yolo.md`](completed/US-003-mob-detection-yolo.md): YOLO entity detection pipeline.
  - [`docs/user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Farming telemetry and adaptive navigation dataset.
  - [`docs/user-stories/completed/US-020-visual-navigation-path-and-heatmap-inspector.md`](completed/US-020-visual-navigation-path-and-heatmap-inspector.md): 2D Path and heatmap inspector.
- **Bottom-Center Ground Contact vs. Bounding Box Center:**
  - The bounding box center $(u_{\text{mid}}, v_{\text{mid}})$ represents a 3D point in the mob's torso or head. Projecting this point into the world creates severe parallax errors and places the mob far behind or below its actual location.
  - The bounding box bottom-center $((x_1 + x_2) / 2, y_2)$ represents the contact point between the entity's feet and the walkable ground surface.
- **Ray–Triangle Intersection & Multi-Layer Occlusion:**
  - Using the Möller–Trumbore intersection algorithm, the unprojected ray $\mathbf{r}(t) = \mathbf{p}_{\text{cam}} + t \cdot \mathbf{d}_{\text{ray}}$ is tested against candidate walkable NavMesh triangles.
  - The closest positive intersection ($t > 0$ with minimum $t$) correctly resolves the topmost visible surface (e.g. a bridge deck rather than the terrain below it).
- **Chunk Partitioning & Performance:**
  - Ray-casting is spatially filtered using active NavMesh spatial spans / chunks around the player/camera, ensuring batch raycasts for 10–20 detections take $\le 2$ ms on CPU without impacting the 10–20 Hz perception loop.
- **Safety Boundaries:**
  - Strictly read-only computation (RPM for camera matrices/position, screen capture for YOLO, offline geometry for NavMesh). Zero memory writes, zero process injection, zero hooking.

## Functional Requirements

### FR-1 – Bottom-Center Anchor Calculation
- For any 2D bounding box $(x_1, y_1, x_2, y_2)$ with $x_1 \le x_2$ and $y_1 \le y_2$, the ground contact screen anchor is computed as:
  $$u = \frac{x_1 + x_2}{2.0}, \quad v = y_2$$
- Validates that coordinates lie within viewport bounds $[0, W] \times [0, H]$.

### FR-2 – 3D World Ray Unprojection
- Transforms $(u, v)$ via `unproject_screen_ray(u, v, W, H, camera_state)` from US-056 to obtain `WorldRay3D(origin=camera_pos, direction=dir)`.

### FR-3 – Fast NavMesh Ray–Triangle Intersection
- Implements deterministic, robust Möller–Trumbore ray-triangle intersection against walkable `NavMeshPolygon` triangles in `BakedNavMesh`.
- Filters triangles by spatial spans/chunks along the ray to avoid brute-force scanning.
- Selects the smallest $t > 0$ along the ray direction.

### FR-4 – EstimatedMobWorldPosition Data Model
- Represents an immutable, typed result:
  ```python
  @dataclass(frozen=True, slots=True)
  class EstimatedMobWorldPosition:
      position: WorldPosition
      navmesh_polygon_id: int | None
      distance_to_player: float
      confidence: float
      class_name: str
      ray_distance: float
  ```

### FR-5 – Graceful Handling of Missed Rays
- If a ray points towards the sky, horizon, or outside the walkable NavMesh boundary, the estimator returns `None` for the estimated position without raising uncaught exceptions or inventing synthetic coordinates.

### FR-6 – Batch Perception Integration
- Provides a dedicated `MobWorldPositionEstimator` service:
  ```python
  def estimate_mob_world_positions(
      detections: tuple[DetectedMob, ...],
      camera_state: CameraState | None,
      player_position: WorldPosition | None,
      viewport_width: int,
      viewport_height: int,
      navmesh: BakedNavMesh | None,
  ) -> tuple[EstimatedMobWorldPosition, ...]: ...
  ```
- Integrates with `PerceptionPipeline` so `WorldState.visible_mobs` (or enriched `DetectedMob`) carries optional estimated 3D coordinates when camera state and NavMesh are active.

### FR-7 – Telemetry & Visualization Integration
- Exposes `EstimatedMobWorldPosition` to `US-054` telemetry datasets (`estimated_mob_x`, `estimated_mob_y`, `estimated_mob_z`, `estimated_mob_polygon_id`).
- Supplies optional live mob position markers to the `US-020` Path Inspector.

## Acceptance criteria

- [x] **Bottom-Center Anchor Precision:** Bounding boxes strictly use the bottom-center coordinate $((x_1 + x_2) / 2, y_2)$ as the screen-space ground anchor.
- [x] **3D Ray Unprojection:** Ray direction accurately matches the Direct3D 9 view-projection camera state verified in US-056.
- [x] **Möller–Trumbore Ray–Triangle Intersection:** Raycast against `BakedNavMesh` returns the exact intersection $(X, Y, Z)$ and polygon ID.
- [x] **Multi-Layer Surface Correctness:** On multi-level geometry (bridges, ramps, elevated platforms), the ray hits the first visible surface along the ray ($t > 0$ minimum) and does not fall through to occluded lower ground.
- [x] **Robust Miss & Sky Handling:** Rays not intersecting walkable NavMesh polygons (horizon, sky, unmeshed regions) return `None` safely.
- [x] **Batch Performance:** Estimating 20 mob detections against local NavMesh chunks executes in $\le 2$ ms on CPU.
- [x] **WorldState Integration:** `PerceptionPipeline` populates estimated mob world positions whenever camera state and NavMesh are available, and degrades to `None` when either is missing.
- [x] **Safety Boundaries Preserved:** Process memory access remains strictly read-only (`PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`); no memory writes or DLL injections.
- [x] **Quality Gate:** `./scripts/check.ps1` passes cleanly (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- [x] **Localization:** Any user-visible diagnostics, inspector legends, or status indicators are fully synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Dynamic mob collision avoidance or pushing physics.
- Writing to game process memory (`WriteProcessMemory`).
- Full 3D mesh deformation or animated skeletal pose estimation of mobs.
- Runtime on-the-fly NavMesh regeneration (NavMesh baking remains offline).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_mob_world_position_estimator.py` validating:
    - Bounding box bottom-center coordinate math.
    - Möller–Trumbore intersection against flat, inclined, and multi-layer bridge triangles.
    - First-hit occlusion verification for multi-layer spans.
    - Horizon / sky ray miss handling returning `None`.
    - Batch evaluation latency benchmarks ($\le 2$ ms for 20 mobs).
    - Pipeline degradation when camera state or NavMesh is unavailable (`None`).
  - Check suite pass: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run against live `neuz.exe` in outdoor areas and on bridges.
  - Compare estimated mob 3D coordinates with player GPS coordinates when walking directly to the mob's position.
