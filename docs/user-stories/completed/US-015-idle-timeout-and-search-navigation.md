---
id: US-015
title: Idle timeout detection and staged search navigation
status: completed
created: 2026-08-15
updated: 2026-08-16
---

# US-015: Idle timeout detection and staged search navigation

## Story

As a player using autonomous farming, I want the bot to detect prolonged idle states when no monsters are in view and automatically execute staged search actions (camera rotation, directional exploration, and optional minimap radar dot navigation), so that the bot can relocate to active spawns and continuously resume farming without getting stuck at cleared spots.

## Context and assumptions

- Depends on [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`), [US-008](completed/US-008-reactive-combat-controller.md) (`CombatController`), and [US-006](completed/US-006-target-architecture-bootstrap.md) (`Supervisor` / `NavigationController`).
- When all mobs in the immediate camera viewport are defeated, the bot enters the `SEARCHING` state. If no new mobs spawn within a configurable timeout, searching progresses through tiered recovery strategies:
  1. **Tier 1 (Camera Rotation):** Rotate the camera (e.g. `A` / `D` or arrow keys) in increments to scan the surrounding 360-degree area.
  2. **Tier 2 (Directional Exploration):** If a full rotation yields no detections, take short directional steps (e.g. `W` forward or roaming in alternating directions) while continuously checking perception.
  3. **Tier 3 (Stretch Goal - Minimap Radar Navigation):** Detect red mob radar dots in the minimap circle (top-right viewport) via color/pixel scanning and click on the closest red dot cluster on the minimap to walk toward it.
- **Immediate State Transition Guarantee:** The moment a valid mob enters the camera viewport or is detected by perception, search movement halts immediately, and the orchestrator transitions back to `TARGETING` -> `COMBAT` -> `LOOTING`.
- All movement actions must respect emergency stops (`END` key) and window focus guards.

## Acceptance criteria

- [x] `SearchController` / `NavigationController` implements a staged search state machine: `ROTATE` -> `ROAM_STEP` -> `MINIMAP_RADAR` (stretch).
- [x] Configurable search parameters: idle timeout before search (e.g. 5.0s default), rotation step duration (e.g. 0.4s), and movement step duration (e.g. 1.0s).
- [x] Tier 1 (Rotation): When no mob is visible in `SEARCHING` mode, dispatches camera turn inputs to sweep the horizontal field of view.
- [x] Tier 2 (Directional movement): If camera sweep finds no target, dispatches short directional movement pulses to discover new spawn clusters.
- [x] Tier 3 (Minimap radar scanning - Stretch): Scans the top-right minimap region for red mob indicators and dispatches guarded navigation clicks if dots are detected outside viewport range.
- [x] Interruptibility: Every perception frame is evaluated during search ticks; if `state.visible_mobs` contains a valid target, all search input is stopped and control transitions immediately to `TARGETING`.
- [x] Dashboard displays search state in the UI status area (e.g. "Suchen: Kamera drehen" / "Suchen: Bewegung").
- [x] Emergency stop (`END`) and window blur immediately abort all navigation/search key presses.
- [x] All user-visible logs, CLI options, and dashboard statuses are synchronized in German and English.
- [x] Automated unit tests in `tests/unit/` verify search state transitions, timeout progression, instant mob interruption, and safety aborts.

## Out of scope

- 3D NavMesh global pathfinding across complex obstacles or world maps.
- Collision avoidance around buildings or impassable mountain geometry.

## Verification

- Automated: Unit tests in `tests/unit/test_orchestrator.py` and `tests/unit/test_search_navigation.py`; `./scripts/check.ps1`.
- Manual (Windows): Start farming at a cleared spot; observe the bot rotating its camera and taking exploratory steps until a newly spawned mob is detected, then verifying that it immediately stops and engages the target.
