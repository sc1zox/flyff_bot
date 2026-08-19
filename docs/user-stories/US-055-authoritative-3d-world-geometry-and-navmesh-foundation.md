---
id: US-055
title: Authoritative 3D world geometry and multi-layer NavMesh foundation
status: in-progress
created: 2026-08-19
updated: 2026-08-20
---

# US-055: Authoritative 3D World Geometry & NavMesh Foundation

## Story

As a **Flyff bot system developer and operator**,
I want **terrain (`.lnd`) and static object geometry (`.dyo` / `.o3d`) extracted from Flyff client assets fused into a unified, authoritative 3D world model and compiled into a multi-layer navigation surface representation**,
so that **outdoor areas, dungeons, bridges, tunnels, ramps, and multi-level structures are geometrically available for reachability, corridor pathfinding, and 3D navigation queries with zero stuck rate**.

## Scope & Pipeline

This story extends the [US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md) terrain extraction pipeline with static 3D world and collision geometry:

```text
.lnd Terrain
+
.dyo Object Placements
+
.o3d Geometry / Collision Geometry (m_CollObject)
        ↓
World-Space Triangle Geometry
        ↓
Walkability Processing (Slope, Radius, Clearance, Step Height)
        ↓
Multi-Layer NavMesh
        ↓
Navigation Query API
```

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Unrestricted read-only access to local client assets for offline extraction.
  - [`docs/user-stories/completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md`](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md): Authoritative `.lnd` terrain heightfields and packed `.one` archive reading.
  - [`docs/user-stories/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Farming telemetry and offline RL dataset foundation.
  - [`docs/bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md`](../bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md): Live collision and stall detection.
  - Raw source: [`docs/sources/2026-08-19-entropia-client-navigation-data-extraction.md`](../sources/2026-08-19-entropia-client-navigation-data-extraction.md).
- **Flyff Object Collision Architecture (`.o3d` / `.dyo`):**
  - In the Flyff engine architecture (`CObject3D`), 3D assets distinguish between visual render meshes and separate collision geometry (`m_CollObject` / `COLLISION_MESH`).
  - Extracting the dedicated collision mesh rather than dense render meshes avoids unnecessary polygon explosion and captures the ground-truth collision hulls used by the game client.
  - Object instances placed via `.dyo` define world coordinates $(X, Y, Z)$, Euler rotations $(\text{yaw}, \text{pitch}, \text{roll})$, and model resource names.
- **Multi-Layer Surface NavMesh Architecture:**
  - Multi-level regions (bridges, archways, layered terrain, tunnels, galleries) require a multi-layer surface representation (voxelized heightfields with multiple vertical height spans) rather than a single 2.5D elevation grid.
  - The baked NavMesh produces convex walkable polygons with explicit neighbor connectivity, stable polygon IDs, clearance margins for agent radius, and maximum step heights.
- **Safety Boundaries:**
  - All archive unpacking, `.o3d` parsing, and NavMesh baking remain strictly offline and read-only. No game process injection, memory writing, or runtime archive hooking is permitted.

## Functional Requirements

### FR-1 – `.o3d` Geometry Extraction
- The system must extract navigation-relevant geometry from `.o3d` assets (packed in `model.one` / `model.hdr` or loose in `Data/Model/`).
- When separate collision geometry (`m_CollObject`) is present, it must be preferred over raw visual render geometry.

### FR-2 – `.dyo` World Placement
- Object instances must be transformed into world coordinates using their placement metadata:
  - Translation $(X, Y, Z)$
  - Rotation $(\text{yaw}, \text{pitch}, \text{roll})$
  - Scale

### FR-3 – Unified World Geometry
- `.lnd` terrain and placed `.o3d` geometry must share a unified world coordinate frame.
- The existing US-052 terrain representation must not be removed.

### FR-4 – Multi-Layer Navigation
- The navigation representation must support multiple walkable surfaces at the same $(X, Z)$ coordinate.
- Specifically support:
  - Bridges and archways
  - Tunnels
  - Dungeon levels
  - Ramps and stairs
  - Galleries and overlapping walkable surfaces

### FR-5 – Agent Walkability
- Walkable surface generation must respect configurable agent parameters:
  - Maximum walkable slope (default $45^\circ$)
  - Agent radius (horizontal clearance margin)
  - Agent height / vertical clearance
  - Maximum step height (traversable ledges)

### FR-6 – Navigation Query API
- The navigation layer must provide typed query functions:
  ```python
  def nearest_walkable_position(position: WorldCoordinate) -> WorldCoordinate | None: ...
  def is_reachable(start: WorldCoordinate, goal: WorldCoordinate) -> bool: ...
  def find_path(start: WorldCoordinate, goal: WorldCoordinate) -> tuple[WorldCoordinate, ...]: ...
  def path_distance(start: WorldCoordinate, goal: WorldCoordinate) -> float | None: ...
  def polygon_or_region_id(position: WorldCoordinate) -> int | None: ...
  ```
- `find_path()` must return smoothed 3D waypoints.

### FR-7 – Existing Routing Compatibility
- The US-052 Heightfield / Visibility Graph A* remains intact as:
  - a robust fallback,
  - a comparison baseline,
  - or an outdoor-specific performance optimization.
- US-055 must not blindly replace existing navigation without verified compatibility.

### FR-8 – Telemetry Integration Contract (US-054)
- The API must provide data for the nullable geometry fields in [US-054](US-054-farming-telemetry-and-adaptive-navigation-dataset.md):
  - `navmesh_polygon_id`
  - `navmesh_path_distance`
  - `navigation_region_id`
- US-055 does **not** implement ML/RL optimization.

## Out of scope

- YOLO Screen-to-World-Raycasting.
- Mob world coordinates from 2D bounding boxes.
- ML/RL training and learned path cost updates (handled separately in US-054 / future stories).
- Target sequencing and combat optimization.
- Dynamic player / mob collision avoidance.
- Modifying, repacking, or writing data back into the game client's `.one` / `.hdr` archives.
- Runtime code injection, DLL hooking, or writing to game process memory (`WriteProcessMemory`).

## Acceptance criteria

- [x] **`.o3d` Geometry Extraction:** `.o3d` collision and bounding geometry can be extracted reproducibly from loose files and known-name archive entries.
- [x] **`.dyo` World Placement:** `.dyo` object placements are transformed correctly into world space $(X, Y, Z, \text{rot}, \text{scale})$.
- [x] **Unified World Coordinate System:** Terrain (`.lnd`) and object geometry (`.o3d`) share the identical world coordinate frame.
- [x] **Multi-Layer Surface Representation:** Multiple walkable surfaces at the same $(X, Z)$ coordinate are cleanly separated and indexed.
- [x] **Agent Walkability Parameters:** Walkable surfaces respect agent radius, slope threshold, vertical clearance, and step-height limits.
- [x] **Nearest Walkable Position:** `nearest_walkable_position()` resolves valid ground-projected coordinates.
- [x] **Reachability Checking:** `is_reachable()` accurately distinguishes connected from disconnected topological regions.
- [ ] **3D Pathfinding:** `find_path()` returns valid, collision-free 3D waypoints across single- and multi-level structures.
- [x] **Path Distance Calculation:** `path_distance()` returns the exact distance along the returned navigation waypoints.
- [x] **Stable NavMesh Polygon IDs:** NavMesh polygons expose deterministic IDs for [US-054](US-054-farming-telemetry-and-adaptive-navigation-dataset.md) telemetry consumption when baked from the same input geometry and configuration.
- [x] **Backward Compatibility:** US-052 remains functional as a fallback and comparison baseline.
- [x] **Safety Boundaries Preserved:** No changes to memory-read safety boundaries.
- [x] **Quality Gate:** `./scripts/check.ps1` passes cleanly (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- [x] **Localization:** The foundation adds no CLI messages, summary outputs, or diagnostics, so no user-visible locale resources changed.

## Definition of Done

The story is complete when at least one outdoor area and one geometrically complex test area (e.g. town or bridge structure) can be reconstructed from client assets and the following query pipeline functions deterministically:

```text
WorldPosition A
      ↓
nearest navigation surface
      ↓
3D path query
      ↓
polygon / region sequence
      ↓
WorldPosition B
```

The resulting navigation path and polygon IDs can be referenced by [US-054](US-054-farming-telemetry-and-adaptive-navigation-dataset.md) without altering its telemetry schema.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_o3d_extractor.py` verifying `.o3d` binary parsing, collision mesh extraction, and bounding hull calculation.
  - Unit tests in `tests/unit/test_navmesh_baker.py` verifying multi-layer span indexing, polygon adjacency graph construction, and agent clearance.
  - The current baker coverage verifies disconnected overlaid decks, 3D corridor waypoints and returned-path distance, slope/radius rejection, and insufficient headroom; it does not yet verify Funnel smoothing or collision validation of every smoothed segment.
  - `./scripts/check.ps1` passed on 2026-08-20: `ruff check`, `ruff format --check`, and `mypy` passed; `pytest` reported 780 passed, 2 skipped, and 89.15% coverage.
- Manual (Windows):
  - Still required: verify the supported version-22 `.o3d` collision layout and `.dyo` transform convention against the approved local Entropia client assets, including at least one outdoor placement and one multi-level structure.
  - Still required: add and exercise an explicit offline bake/persistence entry point, then test 3D path queries on bridges/archways against a foregrounded `neuz.exe` session and confirm live collision-free traversal.

## Implemented foundation and remaining scope

`features/navigation/o3d_extractor.py` is a deliberately narrow, read-only parser for the supported
version-22 `.o3d` layout. It validates the XOR-obfuscated basename in the header, retains model
bounds, and reconstructs the dedicated collision hull from its source vertices and index buffers;
it does not substitute dense render geometry. Loose files can be read directly. A packed model can
also be read only when the caller supplies its exact file name: the predictable encrypted O3D
header lets the existing `.hdr` / `.one` known-prefix lookup find that one entry without archive
enumeration. Unsupported or malformed payloads are refused rather than guessed at.

`features/navigation/world_geometry.py` retains the observed 200-byte `.dyo` placement data needed
for navigation: model name, XYZ translation, yaw plus X/Y/Z axis rotation, non-uniform scale, and
object identity. Collision vertices are scaled, rotated around X, Y, then Z, and translated into the
same client world frame as triangles generated from the retained US-052 `LandBlock` height fields.
`fuse_world_geometry()` omits an unresolved model instead of treating a render mesh or guessed
footprint as collision geometry.

`features/navigation/navmesh.py` provides the offline multi-layer query foundation. It filters
triangles using the configurable 45-degree default slope, radius, vertical clearance, and maximum
step limits; groups walkable polygons by horizontal cell without flattening distinct elevations; and
assigns deterministic polygon and connected-region IDs for the same geometry and configuration.
`BakedNavMesh` exposes nearest-surface projection, polygon/region lookup, reachability, A* corridor
waypoints, and the exact sum of those returned 3D segments. It is not yet a runtime routing
integration: the current A* waypoints are projected endpoints plus polygon centroids, not a
Funnel-smoothed and segment-validated path.

US-052's `TerrainRoutePlanner`, visibility-graph, and learned navigation remain the live-routing
paths. No controller automatically selects this NavMesh, and no change widens process-memory or
input permissions. The query API makes polygon, region, and path-distance values available to a
future US-054 telemetry adapter; the existing telemetry producer remains intentionally unchanged
until a matching baked world can be selected at runtime.
