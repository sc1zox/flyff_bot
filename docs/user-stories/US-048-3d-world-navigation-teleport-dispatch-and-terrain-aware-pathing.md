---
id: US-048
title: 3D world navigation with live coordinate reading, auto-teleport dispatch, terrain-aware elevation pathing, and evasion maneuvers
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-048: 3D world navigation with live coordinate reading, auto-teleport dispatch, terrain-aware elevation pathing, and evasion maneuvers

## Story

As a **bot operator automating multi-mob farming across challenging terrain**, I want **the navigation system to read the player's live 3D world coordinates directly from the game client process, use those as the authoritative position truth for teleport dispatch decisions, terrain-aware A\* routing, and stall detection, and visualize the real-time position and elevation profile in the dashboard**, so that **the bot always knows exactly where in the world it is, navigates without drift or dead-reckoning error, and moves reliably through 3D environments without getting trapped by cliffs or obstacles**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon the offline vector extraction and navigation foundation:
  - [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md): Authoritative extraction of `.lnd` height fields, `.rgn` spawn zones, and `.dyo` obstacles.
  - [US-035](completed/US-035-measured-minimap-odometry-and-tracking-quality.md): Minimap odometry and tracking quality (retained as fallback).
  - [US-039](completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md) & [BUG-009](fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md): Stall detection and combat obstacle recovery.
  - [US-040](US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md): Unrecoverable stuck emergency teleport.
  - [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md): Visual navigation inspector.
- **Live position reading via `ReadProcessMemory`:**
  - The game client (`neuz.exe`) maintains the player's current 3D world coordinates in process
    memory. Read-only access to this region via the documented Win32 `ReadProcessMemory` API is
    explicitly permitted by the project's safety boundaries.
  - Live coordinate reads replace dead-reckoning as the **primary position source**, giving the
    navigation layer a guaranteed, always-accurate position in world space with no accumulated
    drift across long sessions or teleports.
  - If the memory read fails (process handle lost, address relocated), the system falls back
    gracefully to minimap odometry (`MovementTracker`) and logs a diagnostic warning.
- The Flyff client terrain consists of 3D grid height fields where vertical rise $(\Delta Y)$ over horizontal run $(\Delta d)$ dictates passability (slopes $> 45^\circ$ / gradient $> 1.0$ cannot be walked directly).
- Adheres to project safety boundaries:
  - Read-only `ReadProcessMemory` for player/actor world coordinates only. No other memory
    regions are accessed.
  - No `WriteProcessMemory`, code injection, hooking, or anti-cheat evasion.
  - Traversal decisions combine live position with authoritative offline terrain data and Win32 input dispatch.

## Acceptance criteria

- [ ] **Live World Coordinate Reader:**
  - A `LivePositionReader` adapter (`flyff_bot.features.navigation.live_position`) opens a
    read-only handle to `neuz.exe` and reads the player's $(X, Y, Z)$ world coordinates via
    `ReadProcessMemory` at a configurable poll rate (default: 10 Hz).
  - The adapter exposes a typed `WorldPosition(x: float, y: float, z: float)` value object.
  - If the handle is lost or the read fails, the adapter emits a `PositionReadError` event,
    logs a diagnostic, and signals fallback to minimap odometry.
  - The dashboard status bar shows a live "GPS" indicator: green when memory reads succeed,
    amber when running on minimap fallback.
- [ ] **Long-Range Goal Dispatch & Teleport Automation:**
  - Using the live world position as ground truth, when the Euclidean distance to the target
    spawn zone centroid exceeds a configurable long-range threshold (default: `> 150` world
    units), the navigation controller initiates an automated fast-travel/teleport dispatch
    (via configured in-game teleport command/hotkey) to the nearest available zone anchor.
  - After teleport completion, the live position read immediately confirms the new location;
    no manual re-registration or odometry reset is required.
  - If teleportation is disabled, unavailable, or the character is already within walking range,
    the system smoothly defaults to direct ground pathing.
- [ ] **3D Elevation-Aware A\* Pathing with Contour Strafing:**
  - Given extracted 3D heightfield data (`.lnd`) and the live $(X, Y, Z)$ start position, the
    A* path planner incorporates vertical elevation deltas $(\Delta Y)$ and slope penalty weights
    into edge traversal costs.
  - Paths automatically route along natural terrain contours and saddles, avoiding steep ascents
    that cause physics stalls.
  - Waypoint generation includes lateral strafe angles when rounding convex terrain corners or
    hugging hillsides to maintain momentum without wall friction.
- [ ] **Position-Anchored Stall Detection:**
  - `StallDetector` uses the live world position delta between ticks as its primary movement
    signal instead of key-dispatch heuristics.
  - A stall is declared when the live position delta falls below a configurable threshold
    (default: `< 0.5` world units/s) for a configurable duration (default: `2.0 s`) despite
    active movement keys being held.
  - On stall: the controller executes a multi-step evasion sequence (lateral strafe pulse,
    brief backstep, dynamic tangent re-route); repeated failures at the same world coordinate
    mark the node as temporarily impassable and trigger global A* re-plan.
- [ ] **3D-Enriched Navigation View & Live Position Overlay:**
  - The PySide6 Navigation Map Inspector renders the live player position as a real-time dot
    on the world vector map, updated from the memory reader at 10 Hz.
  - Visual elevation contour coloring (topographic shading from `.lnd` data).
  - 3D waypoint markers and active trajectory vectors anchored to live world coordinates.
  - A miniature elevation profile strip showing the remaining route's ascent/descent profile.
- [ ] **Safety & Emergency Controls:**
  - Pressing the emergency stop key (`END` or `Escape`) immediately closes movement inputs,
    resets navigation state to idle, and releases the process handle.
  - Foreground window validation is strictly enforced before every movement input dispatch.
- [ ] **Localization Sync:**
  - All user-visible settings, navigation statuses, GPS indicator labels, and log entries are
    synchronized in both German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- Memory writes (`WriteProcessMemory`), code injection, DLL injection, or hooking into `neuz.exe`.
- Reading any memory region other than the player's live world coordinate struct.
- Direct modification of client game assets on disk.
- Free-flight 3D aerobatics or flight-mount combat.

## Verification

- Automated:
  - Unit tests for `LivePositionReader` with a mock `ReadProcessMemory` stub: happy path,
    handle-lost fallback, and malformed read.
  - Unit tests for 3D elevation cost heuristics and contour smoothing in `test_vector_routing.py`.
  - Unit tests for long-range teleport dispatch using live coordinates as distance input.
  - Unit tests for position-anchored stall detection thresholds and escalation.
- Manual (Windows):
  - Launch `neuz.exe`, start bot, confirm GPS indicator is green in the status bar.
  - Walk or teleport to a distant zone; verify the dashboard map dot tracks the character
    in real time with no lag or drift.
  - Intentionally block the character against a cliff; confirm stall detection fires and
    evasion maneuvers execute without dead-reckoning drift contaminating the recovery.
  - Verify that the Navigation Inspector renders the elevation-shaded map, live position dot,
    and path profile correctly.
