---
id: US-093
title: Geometry-Verified Stall Recovery and NavMesh Routing Unification
status: draft
created: 2026-08-29
updated: 2026-08-29
---

# US-093: Geometry-Verified Stall Recovery and NavMesh Routing Unification

## Story

As an **operator running automated farming sessions**, I want **movement stall recovery to be geometrically planned over authoritative NavMesh with temporary obstacle projection and local escape routing, rather than blind key macros, and the navigation stack unified under BakedNavMesh with the legacy 2D TerrainRoutePlanner removed**, so that **navigation is robust against collisions and terrain traps, free of hardcoded evasion keystrokes, and architecturally unified**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Pathing previously fell back to an `EVADING` state in `PathingController._register_live_stall()` that queued blind `[W+A -> S]` keypress sequences with hardcoded durations (`EVASION_DIAGONAL_DURATION_SECONDS = 0.25`, `EVASION_BACKSTEP_DURATION_SECONDS = 0.25`) ([pathing.py](src/flyff_bot/features/navigation/pathing.py)).
- Jump (`Space`) in stall recovery risks clipping through terrain or landing in unverified coordinates; jump is strictly prohibited in stall recovery and reserved exclusively for explicit off-mesh links.
- Previous obstacle registration stored the character's *own* coordinate (`player_position`) in `_temporary_blocks`, causing A* pathfinding from `start` to fail or collide with the start node.
- Projecting obstacles ahead along the intended movement vector (`player_position + intended_direction * probe_distance`) and projecting onto the NavMesh surface avoids blocking the player's own position while blocking the actual obstruction.
- The navigation stack had dual routing implementations:
  - `BakedNavMesh` (`navmesh.py`): 3D triangle mesh with Funnel string-pulling for target mob approach, tactical attack points, and NPC interaction ([US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md)).
  - Legacy `TerrainRoutePlanner` (`terrain_routing.py`): 2D heightfield grid A* for zone patrol stations and long-range routing ([US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md)).
- Replacing `TerrainRoutePlanner` with `BakedNavMesh.find_path()` unifies all routing (zone patrol sweeps, mob approaches, escape routes) under a single authoritative 3D NavMesh pipeline.
- Relevant decisions and ADRs: [architecture](docs/wiki/architecture.md), [ADR-002](docs/decisions/ADR-002-target-architecture-and-pyside6.md), [ADR-008](docs/decisions/ADR-008-closed-learning-loop-invariants.md), [ADR-009](docs/decisions/ADR-009-bounded-tactical-parameter-space.md).

## Acceptance criteria

- [ ] **Removal of Hardcoded Evasion & `EVADING` Mode:** Given a stall is detected during navigation, when recovery is initiated, then no blind jump, turn, or backstep macros are executed; `PathingMode.EVADING` and `_evasion_steps` are removed and the controller remains logically in `PathingMode.TRAVELING`.
- [ ] **Structured Stall Observation:** Given a commanded movement fails to produce the required GPS displacement within the stall timeout (`StallDetector`), when `PathingController` registers the stall, then it captures a typed `StallObservation` containing `previous_position`, `current_position`, `intended_direction`, `intended_waypoint`, `current_polygon_id`, and `timestamp`.
- [ ] **Projected Temporary Obstacle Registry:** Given a `StallObservation`, when registering the obstacle in `TemporaryObstacleRegistry`, then the obstacle position is computed ahead along the intended direction (`player_position + intended_direction * obstacle_probe_distance`, default 1.2m) and projected onto the NavMesh (`nearest_walkable_position`), assigned a radius (default 1.5m) and dynamic TTL (15s for 1 hit, 30s for 2 hits, 60s for 3+ hits), without blocking the player's start coordinate.
- [ ] **Temporary Obstacle Integration in `BakedNavMesh`:** Given active temporary obstacles, when `BakedNavMesh.find_path()` or `find_polygon_path()` computes a route, then intersecting polygons are excluded or penalized in A*, while protecting the start polygon from being hard-blocked.
- [ ] **Immediate Local Replan on First Stall:** Given a first stall at an obstacle, when the temporary obstacle is registered, then the active route is invalidated and immediately re-planned via `BakedNavMesh.find_path()` with active temporary obstacles, resuming movement exclusively through standard `_steer()`.
- [ ] **Repeated Stall Escalation & Local Stall History:** Given multiple stalls within a local spatial radius (default 2.0m) and sliding time window (default 10s), when the hit count reaches the threshold (`hit_count >= 2`), then the controller records `REPEATED_LOCAL_STALL` and escalates to the geometric escape planner (`_plan_escape_route`).
- [ ] **Geometric Escape Planning & Validation:** Given repeated local stalls or an unroutable goal, when `_plan_escape_route()` executes, then it samples candidate points in concentric radial rings (e.g. 0.75m, 1.5m, 2.5m with 8–16 radial directions), validates each candidate on walkable NavMesh, checks slope limits, clearance, and obstacle distance, and scores candidates deterministically (goal progress, distance, clearance).
- [ ] **Escape Execution via Standard Steering Pipeline:** Given a valid escape plan, when executing escape movement, then the chosen escape point is set as a temporary navigation waypoint and routed via `BakedNavMesh` and `_steer()`; upon reaching the escape point, standard routing to the original goal resumes automatically.
- [ ] **Decommissioning of Legacy `TerrainRoutePlanner`:** Given `VectorZoneNavigator` and the navigation subsystem, when planning zone patrol sweeps and long-distance routes, then routes are planned directly over `BakedNavMesh.find_path()`; `terrain_routing.py` (`TerrainRoutePlanner`, `TerrainRouteConfig`, `TerrainWaypoint`) is completely removed.
- [ ] **Telemetry & State Introspection:** Given stall and recovery events, when stepped, then `TelemetryRecorder` logs structured events (`STALL_DETECTED`, `TEMPORARY_OBSTACLE_CREATED`, `LOCAL_REPLAN_REQUESTED`, `LOCAL_REPLAN_SUCCEEDED`, `ESCAPE_PLAN_SUCCEEDED`, etc.); internal recovery status is tracked via `RecoveryContext` without exposing custom movement modes.
- [ ] **Safety & Emergency Stop:** Given an emergency stop (`F12`), when triggered, then all movement, replanning, and recovery actions halt immediately and release input keys; all user-visible strings are synchronized in German and English.

## Out of scope

- Direct process memory injection or code hooking (`WriteProcessMemory`).
- Backward evasion / contact release backstep macros (recovery relies strictly on forward steering toward replanned NavMesh / escape waypoints).
- Off-mesh jump traversal links (reserved for a dedicated jump-pathing user story).
- Persistent disk serialization of learned collision maps across game patches (in-memory runtime registry only).

## Verification

- Automated:
  ```powershell
  uv run pytest tests/unit/test_vector_pathing.py tests/unit/test_navmesh.py tests/unit/test_tracking.py tests/unit/test_telemetry.py
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy
  ```
- Manual (Windows):
  1. Start a farming session and intentionally obstruct character movement against a solid world object or wall.
  2. Verify no hardcoded `[W+A -> S]` or jump macros occur; verify immediate local replan routes around the obstacle via `_steer()`.
  3. Trap the character in a concave corner or dead-end; verify repeated stall triggers `_plan_escape_route()`, chooses a verified walkable point, and navigates out.
  4. Verify that emergency stop (`F12`) instantly aborts all movement and recovery actions.
