---
id: US-091
title: Unified Goal Navigation, Fluid Perception Scanning, and Intelligent Evasion Recovery
status: completed
created: 2026-08-29
updated: 2026-08-29
---

# US-091: Unified Goal Navigation, Fluid Perception Scanning, and Intelligent Evasion Recovery

## Story

As an **operator configuring automated farming sessions**, I want **the session to strictly navigate to and farm within user-selected spawn zones, perform fluid perception-preserving camera sweeps without idle delays or blind roaming, and automatically execute ML/RL-informed unstuck evasion maneuvers when movement is obstructed**, so that **farming is reliable, high-yield, obstacle-resilient, and eliminates dead loops**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Extracted world maps (`WorldVectorMap`) provide terrain heightfields and vector spawn zones (`VectorSpawnZone`) ([world-extractor](docs/wiki/architecture.md)).
- Goal selection previously diverged across `KillGoalTracker`, `VectorZoneNavigator`, `QuestGoals`, and `Autopilot`, causing multi-target presets to override user-selected zone navigation targets.
- Search mode previously had a 5-second idle timeout (`DEFAULT_SEARCH_IDLE_TIMEOUT_SECONDS = 5.0`), rigid 8-step jerky rotations with 0.3s pauses, and blind `[W, D, W, A]` roaming that walked characters into collisions.
- Continuous camera rotation degrades YOLO mob detection accuracy due to motion blur; fluid paced micro-sweeps with brief inference windows preserve perception clarity while minimizing rotation time.
- Obstacle collisions in canyons or against placed objects (`.dyo` / models) produced infinite loops because `SEARCHING` mode ignored `is_stuck` flags and lacked proactive evasion (backstep, strafe, jump, temporary A* obstacle registration, and nearest walkable mesh escape routing).
- Relevant decisions and ADRs: [ADR-007](docs/decisions/ADR-007-offline-tactical-simulation-boundary.md), [ADR-008](docs/decisions/ADR-008-closed-learning-loop-invariants.md), [ADR-009](docs/decisions/ADR-009-bounded-tactical-parameter-space.md).

## Acceptance criteria

- [x] **Zone-Constrained Goal Unification:** Given an operator selects one or more specific spawn zones in the World Data Dialog (e.g. MiniMush), when vector navigation is activated, then the session's active farming goals and target class whitelist strictly lock to the monster classes of those selected zones.
- [x] **Off-Zone Target Suppression:** Given a session with a single active spawn zone, when navigating and scanning, then the bot does not divert to engage off-zone or unselected monster types (e.g. Flame) unless directly attacked in self-defense.
- [x] **Multi-Zone Ordered Progression:** Given multiple selected spawn zones, when one zone is exhausted or its quota is satisfied, then the navigator advances in sequential order along the operator's active zone list.
- [x] **Zero-Delay Search Initialization:** Given no eligible target is visible in the current viewport, when entering search mode, then the camera sweep begins immediately (0.0s idle delay).
- [x] **Fluid Perception-Preserving Micro-Sweeps:** Given active search scanning, when sweeping the camera, then the scan executes fluid micro-rotations calibrated to avoid motion blur, ensuring YOLO object detection operates reliably on clear frames.
- [x] **Immediate Target Acquisition Interruption:** Given a target is detected during a camera sweep, when YOLO validates the mob, then camera rotation halts immediately to begin approach and combat.
- [x] **Elimination of Blind Roaming:** Given search mode is active, when sweeping for targets, then blind `[W, D, W, A]` keyboard roaming is completely disabled.
- [x] **Mesh & Hotspot Patrol Routing:** Given the character is in an active spawn zone, when no target is immediately visible, then character movement follows calculated NavMesh / terrain patrol stations (hotspots) rather than arbitrary ground movements.
- [x] **Proactive Jump & Backstep Evasion:** Given a stall is detected (`is_stuck=True` or `StallDetector` triggers) in any navigation or search mode, when movement is obstructed, then the bot immediately triggers an evasion sequence consisting of controlled backstep (`S`), jump (`Space`), directional pivot/strafe (`A`/`D`), and temporary obstacle registration in `_temporary_blocks`.
- [x] **NavMesh Canyon & Trap Escape Routing:** Given a character located inside an impassable canyon or collision mesh where standard A* routing returns `blocked=True`, when replanning, then the router computes an escape path to the nearest reachable walkable NavMesh node before resuming zone travel.
- [x] **ML & Tactical Policy Integration:** Given ML/RL tactical parameter spaces, when configuring search turn rates, engagement radii, and candidate ranking, then candidate economics and policy action masks prioritize active zone targets and rank attack points safely outside recorded obstacle boundaries.
- [x] **Emergency Stop Safety & Localization:** Given an emergency stop (`F12`), when triggered, then all movement, camera scanning, and evasion routines immediately release input keys and halt safely; all user-visible text is synchronized in German and English.

## Implementation notes

- The operator's camp selection is turned into goals by `zone_locked_goals`
  (`features/navigation/vector_navigation.py`) and applied to the quota tracker by
  `FarmingOrchestrator._lock_goals_to_selected_zones`, which is what locks the combat whitelist, the
  candidate-value bonus and the policy action mask in one write.
- Self-defence (`features/automation/self_defense.py`) lifts the zone lock only for a bounded window
  opened by health lost outside an engagement, and closes it when the session halts.
- `VectorZoneNavigator` routes patrol legs over the `BakedNavMesh`. The extracted heightfield router
  `TerrainRoutePlanner` remains as the fallback for a world whose mesh has not been baked yet, since
  a baked mesh is still optional at session start. Deleting `terrain_routing.py` / `vector_routing.py`
  and moving `SimulatorEngine` off `VectorRoutePlanner` is the agreed follow-up pruning task.
- `SearchConfig` lost `roam_steps` and `movement_step_duration_seconds`, the CLI lost
  `--search-movement-duration`, and the dashboard status `search_roaming` became `search_scanning`.

## Out of scope

- 3D mesh model extraction from proprietary binary formats.
- Process memory injection or code hooking.
- Automatic teleporter bypass through wall clipping or speed hacks.

## Verification

- Automated:
  ```powershell
  uv run pytest tests/unit/test_vector_navigation.py tests/unit/test_controllers.py tests/unit/test_pathing.py tests/unit/test_orchestrator.py
  ```
- Manual (Windows):
  1. Open World Data Dialog and select a single spawn zone (e.g. MiniMush) while character is in another zone (e.g. Flame).
  2. Start farming session and verify character immediately navigates toward MiniMush without attacking surrounding Flames.
  3. Verify camera sweep starts with 0s delay and executes fluid sweeps while YOLO reliably acquires targets.
  4. Block character movement against an obstacle or canyon wall and verify backstep + jump + pivot evasion triggers cleanly and escapes without looping.
