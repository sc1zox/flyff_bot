---
id: US-019
title: Intelligent pathing and topological spawn heatmap for monster farming
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-019: Intelligent pathing and topological spawn heatmap for monster farming

## Story

As a user of the autonomous farming system, I want the bot to automatically learn and internally map monster spawn locations, traversed pathways, and problematic terrain during farming sessions, so that it can establish efficient farming routes, avoid known obstacles, and reliably navigate back to high-yield spawn areas after deviations.

## Context and assumptions

- **Architectural Dependencies & Safety:**
  - Extends [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`), [US-008](completed/US-008-reactive-combat-controller.md) (Combat), and [US-015](completed/US-015-idle-timeout-and-search-navigation.md) (Search navigation).
  - Operates strictly without process injection, memory hooking, or game client modification.
  - Mapping and pathing logic is purely internal/algorithmic and requires no rendering or interaction in the game UI or desktop overlay.
- **Internal Spatial Memory & Spawn Heatmap:**
  - Monster detections and combat events are recorded with their estimated relative spatial positions into an internal spawn heatmap.
  - Traversed paths build a local navigation graph / spatial grid with visit history and frequency weights.
- **Dynamic Costing & Stuck Avoidance:**
  - Problematic areas (stalls, collisions, no-progress detections) are recorded with elevated pathing costs rather than hard binary blocks, enabling graceful avoidance while retaining accessibility if needed.
  - After encountering a stuck situation, the bot can back up to its last verified safe navigation waypoint and recalculate an alternate route.
- **Route Optimization & Persistence:**
  - The routing algorithm balances distance, stuck risk, and spawn density to prioritize high-yield spawn clusters and establish recurring patrol circuits (e.g. `A → B → C → A`).
  - Routes dynamically adjust if spawn densities shift or new obstacles are encountered.
  - Learned spatial maps, spawn weights, and path costs are persisted to disk across application restarts.

## Acceptance criteria

- [ ] Monster positions identified during active farming are recorded and accumulated into an internal spawn heatmap.
- [ ] Successfully traversed movement paths are tracked to automatically construct an internal navigation graph / local map.
- [ ] Previously visited locations and connecting pathways are recognized and annotated with a visit history.
- [ ] Movement stalls and stuck situations are detected automatically.
- [ ] Areas and pathways where movement stalls repeatedly occur receive an elevated pathing cost penalty and are avoided during future route planning.
- [ ] Upon encountering a stuck situation, the bot can retreat to its last known safe navigation waypoint and compute an alternative bypass route.
- [ ] Route calculation incorporates distance, stuck risk, and spawn density, prioritizing high-yield monster clusters over sparse areas.
- [ ] The bot can automatically derive and execute recurring farming circuits between active spawn clusters.
- [ ] Preferred farming routes dynamically adapt when local spawn densities change over time.
- [ ] The entire mapping, heatmap, and path planning system operates internally without requiring any visual representation in the game client or dashboard UI.
- [ ] Learned navigation graphs, spawn heatmaps, and cost weights are persisted to disk and restored across farming sessions.
- [ ] Emergency stop (`END` key) and window focus loss immediately halt all pathing movements safely.
- [ ] Automated unit tests in `tests/unit/` verify:
  - Spawn heatmap accumulation and decay.
  - Navigation graph construction from movement paths.
  - Pathing cost penalty assignment and avoidance on simulated stuck events.
  - Safe-waypoint fallback and alternative route generation.
  - Dynamic circuit recalculation on changing density weights.
  - Map persistence serialization and deserialization.

## Out of scope

- Rendering a visual map or heatmap overlay in the desktop UI or game viewport.
- 3D Z-axis terrain heightmaps or jumping navigation across vertical obstacles.
- Manual waypoint editing or custom path drawing via GUI tools.

## Verification

- Automated: Unit tests in `tests/unit/test_spatial_heatmap.py` and `tests/unit/test_path_planning.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Start autonomous farming at a multi-spawn spot with terrain obstacles.
  2. Observe the bot learning spawn locations and establishing a natural path between spawn groups.
  3. Induce a temporary obstacle/stall; verify that the bot retreats to the last safe node, marks the segment with higher cost, and plans an alternative route.
  4. Restart the bot and verify that previously learned spawn hotspots and obstacle costs persist.
