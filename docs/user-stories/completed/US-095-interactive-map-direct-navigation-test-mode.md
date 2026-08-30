---
id: US-095
title: Interactive map direct navigation test mode
status: completed
created: 2026-08-30
updated: 2026-08-30
---

# US-095: Interactive map direct navigation test mode

## Story

As a **bot operator testing NavMesh pathfinding and GPS movement**,
I want **to right-click any coordinate or zone on the interactive navigation map and trigger a pure navigation test**,
so that **the character walks directly to the selected destination using authoritative NavMesh routing without engaging in combat or requiring a full farming session**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon:
  - [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md): Visual navigation path and heatmap inspector.
  - [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md): Vector world terrain extraction, spawn zones, and visibility-graph A* pathing.
  - [US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md): Authoritative 3D world geometry and NavMesh foundation.
  - [US-074](completed/US-074-interactive-world-map-and-spawn-zone-visualizer.md): Interactive world map and spawn zone visualizer.
  - [US-091](completed/US-091-unified-goal-navigation-fluid-scanning-and-intelligent-unstuck.md): Unified goal navigation, fluid scanning, and intelligent unstuck.
  - [US-093](completed/US-093-geometry-verified-stall-recovery-and-navmesh-routing-unification.md): Geometry-verified stall recovery and NavMesh routing unification.
- Current capabilities:
  - `PathInspectorWidget` (`src/flyff_bot/ui/path_inspector.py`) and `NavigationMapWindow` (`src/flyff_bot/ui/navigation_window.py`) render the 2D/3D map, terrain, NavMesh polygons, spawn zones, and player position, supporting pan, zoom, and zone selection.
  - `PathingController.begin_position_approach` (`src/flyff_bot/features/navigation/pathing.py`) already calculates NavMesh A* routes to arbitrary world coordinates (`WorldPosition`) and manages closed-loop steering and obstacle avoidance.
  - Currently, moving to a location is only invoked during active farming (`FarmingMode.SEARCHING` or quest travel), which also engages YOLO mob detection, target verification, combat rotations, and looting.
- Operator requirement:
  - Provide a standalone test capability to right-click any location (or spawn zone) on the interactive map (`PathInspectorWidget` / `NavigationMapWindow`) and select "Hierhin navigieren (Test)" / "Navigate here (Test)".
  - When invoked, the bot initiates pure movement to the destination using the existing `PathingController` NavMesh pathfinding and stall recovery.
  - Combat, target verification, and looting remain completely inactive during this navigation test.
  - Upon reaching the target position within arrival tolerance, the bot halts all movement and returns to idle/standby without starting farming loops.
  - Safety boundaries remain strictly enforced: foreground window guard, F12 emergency stop, and release of all movement keys on halt or focus loss.

## Acceptance criteria

- [x] **Context Menu & Coordinate Selection on Map:**
  - `PathInspectorWidget` provides a context menu (via right-click or context menu trigger) on the map canvas with the localized action "Hierhin navigieren (Test)" / "Navigate here (Test)".
  - The menu displays the clicked world coordinates `(X, Z)` or zone name.
  - Triggering the action emits a typed test navigation request carrying the target `WorldPosition` and optional zone identifier.
- [x] **Pure Navigation Mode Execution:**
  - `FarmingOrchestrator` (or the navigation controller) supports a dedicated test navigation mode (`FarmingMode.TEST_NAVIGATING` or direct position approach).
  - During test navigation, YOLO mob detection, combat targeting, attack hotkey dispatch, and looting are bypassed.
  - The character is steered along the NavMesh route calculated by `PathingController` using live GPS and camera heading.
  - Stall detection and geometry-verified obstacle recovery (`US-093`) remain active to handle collision recovery during the test.
- [x] **Arrival & Halt Behavior:**
  - When the character arrives within the arrival tolerance (`navmesh_waypoint_arrival_units`) of the destination, all movement keys are released, the test completes, and the bot transitions to `PAUSED` / `IDLE`.
  - A localized notification/event log entry confirms test arrival (e.g. "Navigationstest erfolgreich: Ziel {x}, {z} erreicht.").
- [x] **Safety Boundaries & Cancellation:**
  - If the game client loses foreground focus (`NOT_FOREGROUND`), test navigation immediately releases all held keys and pauses.
  - Pressing `F12` immediately halts test navigation, releases keys, and transitions to `EMERGENCY_STOPPED`.
  - The operator can manually pause or cancel the test at any time via the UI Pause/Stop buttons.
- [x] **Localization:**
  - All context menu entries, status badges, tooltips, and log messages are fully synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Automated combat or mob engagement upon arrival at the test destination.
- Cross-continent automated teleporter chaining for test navigation (test navigation operates within the loaded world map/NavMesh).
- Direct in-game path editing or custom waypoint manipulation.

## Verification

- Automated:
  - Unit tests for `PathInspectorWidget` context menu action and coordinate mapping to `WorldPosition`.
  - Unit tests for `FarmingOrchestrator` / `PathingController` verifying pure navigation execution without combat/targeting triggers.
  - Unit tests verifying arrival completion, key release, and pause state transition.
  - Unit tests verifying foreground loss and F12 emergency stop safety guards during test navigation.
  - `./scripts/check.ps1` runs cleanly with zero lint, formatting, type, and test errors.
- Manual (Windows):
  - Open the interactive map in the dashboard or popout window.
  - Right-click a point on the map and select "Hierhin navigieren (Test)".
  - Verify the bot steers to the point, avoids obstacles via NavMesh, stops at the destination, and does not attack nearby mobs.
