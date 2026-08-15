---
id: US-019
title: Topological spawn heatmap and dead-reckoning grid pathing
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-019: Topological spawn heatmap and dead-reckoning grid pathing

## Story

As a player using autonomous farming, I want the bot to maintain an internal 2D topological spatial grid that records monster spawn locations, kill frequencies, and verified traversable paths, so that the bot never gets lost, avoids obstacles, and intelligently navigates back to active spawn clusters when no monsters are in the immediate camera view.

## Context and assumptions

- **Architectural Dependencies & Safety:**
  - Depends on [US-008](completed/US-008-reactive-combat-controller.md) (Combat completion events), [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`), and [US-015](completed/US-015-idle-timeout-and-search-navigation.md) (Search loop).
  - Operates purely within documented Win32 input simulation and internal mathematical models without memory injection, process hooking, or game client tampering.
- **Dead Reckoning & Spatial Localization:**
  - The bot maintains an internal 2D relative coordinate space $(x, y)$ starting at origin $(0, 0)$ when farming starts.
  - Movement vectors are calculated by integrating directional keystrokes (`W`, `S`, `A`, `D`) and camera rotation heading angles over time (e.g. forward velocity $v \times \Delta t$).
- **2D Spatial Grid & Spawn Heatmap Model:**
  - A discrete 2D grid (configurable cell size, e.g. $2.0\,\text{m} \times 2.0\,\text{m}$) where each cell stores:
    - `spawn_score: int` (accumulated kill/detection count at this location)
    - `last_kill_timestamp: float` (timestamp to model respawn cooldowns, e.g. Flyff standard 15–30s respawn cycles)
    - `traversable: bool` (whether the cell is verified as walkable or marked blocked due to collision/stall)
    - `visit_count: int` (number of times the character traversed the cell)
- **Intelligent Return & Breadcrumb Pathing:**
  - During `SEARCHING` mode, instead of blind random exploration, the path planner calculates the optimal path (A* / Dijkstra over traversable grid cells) towards the highest-weighted spawn cluster whose respawn cooldown has elapsed.
  - A configurable **Leash Radius** (e.g. 50 meters from origin) constrains navigation to stay strictly within the designated farming zone.
  - **Stuck & Obstacle Detection:** If forward movement is dispatched but visual progress / state change is not observed by the Supervisor, the target grid cell is marked as blocked (`traversable = False`), and an alternate bypass path is planned.
- **Persistent Storage:**
  - The topological grid is serialized to and deserialized from JSON files (e.g. `data/maps/{mob_name}_heatmap.json`) so learned spawn hotspots and obstacle maps persist across bot restarts.

## Acceptance criteria

- [ ] `SpatialGridMap` provides a 2D topological occupancy and heatmap data structure:
  - Discrete cell quantization with configurable cell size (default `2.0m`).
  - Cell attributes: `spawn_score`, `last_kill_timestamp`, `traversable`, `visit_count`.
  - Methods to record kills, update traversability, and query high-density candidate spawn clusters.
- [ ] `DeadReckoningTracker` maintains relative character position $(x, y)$ and heading vector integrated from dispatched movement keys and camera rotation durations.
- [ ] `GridPathPlanner` implements shortest-path search (A* / Dijkstra) over traversable cells:
  - Selects target waypoint based on highest spawn density with matured respawn timers.
  - Enforces a configurable `max_leash_radius` (default `50.0m`) from start origin.
  - Returns a sequence of directional movement steps to reach the target cluster.
- [ ] Integration into `SearchController` / `FarmingOrchestrator`:
  - When idle search reaches roaming stage, navigation follows planned grid path instead of random keys.
  - Instantly interrupted if a mob enters visual perception (`state.visible_mobs`).
- [ ] Obstacle / collision avoidance: cells flagged as blocked by supervisor stall detection are avoided in future path planning.
- [ ] Grid persistence: `save_to_json(path)` and `load_from_json(path)` serialize and restore learned heatmap data.
- [ ] Automated unit tests in `tests/unit/test_spatial_heatmap.py` verify:
  - Coordinate integration from movement pulses.
  - Heatmap cell updates on mob kills.
  - A* path calculation across obstacles and leash boundary constraints.
  - JSON serialization/deserialization roundtrip.

## Out of scope

- UI rendering or graphical heatmap overlays (pure internal algorithmic data structure).
- 3D Z-axis terrain mesh / vertical jumping pathfinding.
- Minimap template tracking or visual odometry.

## Verification

- Automated: Unit tests in `tests/unit/test_spatial_heatmap.py` and `tests/unit/test_search_navigation.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Start farming at a multi-spawn spot.
  2. Kill several monsters in different spots of the area.
  3. Clear all visible monsters and observe that the bot navigates directly back towards previously recorded spawn points rather than walking aimlessly away.
