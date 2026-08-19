---
id: US-058
title: NavMesh-aware targeting, autonomous funnel approach, and live telemetry integration
status: completed
created: 2026-08-20
updated: 2026-08-20
---

# US-058: NavMesh-Aware Targeting, Autonomous Funnel Approach, and Live Telemetry Integration

## Story

As a **Flyff bot developer and autonomous systems engineer**,
I want **the targeting controller, approach navigation, and telemetry recorder to integrate authoritative 3D NavMesh queries and estimated mob world coordinates**,
so that **mob selection strictly rejects unreachable candidates, approach movement executes active 3D Funnel corridor pathfinding with continuous GPS reconciliation rather than opaque client-side click-to-move, and farming telemetry records complete, noise-free ground truth for offline reinforcement learning.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Client asset extraction foundation.
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for player position and camera state.
  - [`docs/user-stories/completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md`](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md): Authoritative 3D terrain heightfields.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Farming telemetry, SQLite database, and Parquet dataset export.
  - [`docs/user-stories/completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md`](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md): 3D world geometry extraction, `NavMeshBaker`, and `BakedNavMesh` query API.
  - [`docs/user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md`](completed/US-056-client-camera-state-and-projection-matrix-reader.md): Live camera memory reader and D3D9 view-projection matrix unprojection.
  - [`docs/user-stories/US-057-yolo-bottom-center-camera-unprojection-and-navmesh-mob-positioning.md`](US-057-yolo-bottom-center-camera-unprojection-and-navmesh-mob-positioning.md): Bottom-center unprojection and `EstimatedMobWorldPosition` raycast service.
  - [`docs/bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md`](../bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md): Live collision stall detection and recovery.

### Target Selection Pipeline

Target scoring evaluates visible candidates in strict order of authority:
1. **Topological Reachability (`is_reachable`):** Hard filter. Candidates located on disconnected NavMesh regions (e.g. across impassable chasms, unmeshed terrain, isolated platforms) are rejected immediately before any click or approach.
2. **Lockout Status:** Candidates within active target lockout radii or approach failure cooldowns are excluded.
3. **Leash Enforcement:** Candidates whose NavMesh path distance from the spawn anchor exceeds the configured leash radius are rejected (falling back to 2D Euclidean leash when NavMesh data is unavailable).
4. **Shortest NavMesh Path Distance ($d_{\text{path}}$):** Candidates with valid world coordinates are ranked by the exact length of the A* + Funnel corridor.
5. **Viewport Distance Tie-Breaker ($d_{\text{screen}}$):** When path distances are equal or when candidates lack raycast hits (`world_position is None`), 2D viewport center distance acts as a secondary tie-breaker with lower priority.

```text
Visible YOLO Detections + US-057 Estimated 3D Coordinates
        ↓
Reachability Filter (is_reachable == True)
        ↓
Lockout & Leash Filter (NavMesh path distance <= leash)
        ↓
Shortest NavMesh Path Distance (A* + Funnel d_path)
        ↓ (Tie-breaker or Unprojected Fallback)
Viewport Center Proximity (d_screen)
        ↓
Selected Target Mob
```

### Approach Navigation Architecture

Rather than relying on client-side click-to-move (which suffers from obstacle stalls against unmodeled geometry and unpredictable pathing), the bot actively navigates along the calculated 3D Funnel waypoints:
1. `BakedNavMesh.find_path(player_pos, mob_pos)` generates smoothed 3D waypoints.
2. The pathing controller steers heading and dispatches forward movement pulses toward consecutive waypoints.
3. Live 10 Hz GPS coordinates reconcile position error and detect obstacle stalls in real time.
4. Mob selection/attack input is dispatched once the character enters engagement range.

```text
Selected Target Mob (3D World Position)
        ↓
find_path(player_position, mob_position)
        ↓
3D Funnel Waypoints [(x0, y0, z0), (x1, y1, z1), ...]
        ↓
Heading Controller + Forward Movement (WASD)
        ↓
Continuous 10 Hz GPS Position Tracking & Stall Monitoring
        ↓
Engagement Range Reached → Combat Dispatch
```

### Telemetry Integration Contract (US-054 Closure)

All nullable geometry and trajectory fields in `TelemetryRecorder` are populated from authoritative sources without fabricating data:
- **Snapshots:** `player_navmesh_polygon_id`, `player_terrain_slope` (derived from active player polygon normal).
- **Target Candidate Matrix:** `world_position`, `relative_distance`, `relative_elevation`, `target_navmesh_polygon_id`, `path_distance`, `is_locked_out`.
- **Navigation Episodes:** Start/goal coordinates, planned 3D Funnel waypoints, 10 Hz real GPS trajectory, actual travel distance, path efficiency $\eta = L_{\text{planned}} / L_{\text{actual}}$, stall events, and evasion steps.
- **Kill-to-Kill Cycle ($T_{\text{k2k}}$):** Exact four-part decomposition into $T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$.

## Functional Requirements

### FR-1 – NavMesh-Aware Target Filtering & Scoring
- `CombatController` and `FarmingOrchestrator` must filter mob candidates against the active `BakedNavMesh`:
  - Reject any candidate where `is_reachable(player_pos, mob_pos)` is `False`.
  - Reject any candidate where `path_distance(anchor_pos, mob_pos) > leash_radius_units`.
  - Rank reachable candidates primarily by ascending `path_distance(player_pos, mob_pos)`.
  - Use 2D screen distance to viewport center as a tie-breaker among equal distances or as a fallback for candidates with unprojected positions (`world_position is None`).

### FR-2 – Autonomous NavMesh Approach Execution
- `PathingController` must execute active 3D Funnel corridor navigation toward the selected mob:
  - Generate waypoints via `BakedNavMesh.find_path(player_pos, mob_pos)`.
  - Align camera/player heading toward current sub-goal waypoint and dispatch forward movement pulses.
  - Dynamically advance to the next waypoint when within waypoint arrival tolerance.
  - Transition to combat targeting when within configured melee/combat engagement distance.
  - Trigger local obstacle evasion (strafe/backstep) and replanning if forward movement stalls.

### FR-3 – Fallback and Graceful Degradation
- If no `BakedNavMesh` is loaded or if camera state is unavailable:
  - Target selection degrades gracefully to the existing 2D viewport center proximity heuristic.
  - Leash enforcement falls back to 2D Euclidean distance from the session/map anchor.
  - Approach movement falls back to direct client-relative click-to-move with stall recovery.

### FR-4 – Complete Live Telemetry Population (US-054 Closure)
- `TelemetryRecorder` must populate all previously nullable fields whenever authoritative data is present:
  - World snapshots include `player_navmesh_polygon_id` and `player_terrain_slope`.
  - Target decision envelopes include the full candidate feature matrix with exact 3D coordinates, relative elevations $\Delta y$, NavMesh polygon IDs, path distances, and lockout flags.
  - Completed navigation episodes record planned 3D Funnel waypoints, 10 Hz GPS trajectories, path length metrics, efficiency $\eta$, and stall counts.
  - Verified kill cycles record the decomposed intervals ($T_{\text{decision}}, T_{\text{navigation}}, T_{\text{combat}}, T_{\text{idle}}$).
  - If a raycast or NavMesh lookup fails for an individual candidate, its corresponding geometric fields remain explicitly `null` (no fabricated heuristics).

### FR-5 – Diagnostic Navigation Inspector Overlay
- `PathInspectorWidget` must optionally display live diagnostic geometry:
  - Mob 3D world positions as color-coded markers (green = reachable/selected, red/gray = unreachable or locked out).
  - Active 3D Funnel navigation path polyline from player to target.
  - Historical 10 Hz GPS trajectory line for the active navigation episode.
  - Visual display is purely diagnostic and decoupled from the control loop.

## Acceptance criteria

- [x] **Reachability Rejection:** Given a visible mob detection whose raycast lands on a disconnected NavMesh region (`is_reachable == False`), when target selection evaluates candidates, then the unreachable candidate is excluded and never clicked.
- [x] **Shortest Path Prioritization:** Given multiple reachable mob candidates within leash bounds, when target selection runs, then the candidate with the shortest NavMesh path distance $d_{\text{path}}$ is selected.
- [x] **Unprojected Fallback:** Given a mob candidate whose raycast misses the NavMesh (`world_position is None`), when no shorter reachable candidates exist, then the candidate remains selectable via 2D viewport proximity with lower priority than valid 3D candidates.
- [x] **NavMesh Leash Enforcement:** Given a mob candidate whose 3D position is reachable but whose NavMesh path distance from the spawn anchor exceeds the leash radius, when target selection runs, then the candidate is rejected.
- [x] **Autonomous Funnel Navigation:** Given a selected target mob, when the bot initiates approach, then it follows 3D Funnel waypoints from `find_path()` using heading adjustments and forward movement pulses until within engagement distance.
- [x] **Graceful Degradation:** Given a session running without a loaded NavMesh or without camera state, when farming runs, then target selection, leash checking, and approach movement function using 2D heuristics and direct click-to-move without raising uncaught exceptions.
- [x] **Complete Telemetry Stream:** Given a farming session with active NavMesh and camera state, when world snapshots, target decisions, navigation episodes, and kill cycles are recorded, then all geometry and trajectory fields are populated with exact numerical values in both JSONL and SQLite storage.
- [x] **Parquet Export Verification:** When `--export-telemetry` is executed, then `target_decisions.parquet`, `navigation_trajectories.parquet`, and `kill_cycles.parquet` contain non-null 3D coordinates, polygon IDs, and decomposed cycle timings.
- [x] **Safety Boundaries Preserved:** Process memory access remains strictly read-only (`PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`); all key/mouse inputs remain guarded by foreground focus and the `END`/`Escape` emergency stops.
- [x] **Quality Gate:** `./scripts/check.ps1` passes cleanly (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- [x] **Localization:** All user-visible diagnostic strings, inspector tooltips, and log messages are synchronized across German (`de.json`) and English (`en.json`).

## Out of scope

- Generating or baking new NavMesh assets (handled in US-055).
- Parsing raw `.o3d` or `.dyo` geometry (handled in US-055).
- Memory extraction of camera matrices or viewport ray unprojection (handled in US-056 / US-057).
- Multi-step forward target sequencing or offline RL policy training.
- Dynamic avoidance of other moving players or mobile NPCs.
- Writing to game process memory (`WriteProcessMemory`) or injecting code.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_navmesh_targeting.py` verifying reachable candidate ranking, unreachable filtering, unprojected fallback, and leash enforcement.
  - Unit tests in `tests/unit/test_funnel_approach.py` verifying active waypoint following, arrival thresholds, heading correction, and transition to combat range.
  - Unit tests in `tests/unit/test_telemetry_geometry.py`, `tests/unit/test_telemetry_sqlite.py`, and `tests/unit/test_telemetry_parquet.py` verifying measured geometry, persisted payloads, and exported fields.
  - Check suite pass: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run a live session in Entropia Flyff in an area with multi-level terrain or obstacle geometry (e.g. Madrigal or Eden).
  - Verify on the Navigation Inspector that mobs across impassable cliffs are marked red/unreachable and ignored by targeting.
  - Verify that the character actively walks along 3D Funnel corridors around obstacles to engage reachable mobs.
  - Verify that `data/telemetry.sqlite3` and exported Parquet files contain populated 3D coordinates, polygon IDs, and complete navigation episodes.
