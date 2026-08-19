---
id: US-048
title: 3D world navigation with auto-teleport dispatch, terrain-aware elevation pathing, and evasion maneuvers
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-048: 3D world navigation with auto-teleport dispatch, terrain-aware elevation pathing, and evasion maneuvers

## Story

As a **bot operator automating multi-mob farming across challenging terrain**, I want **the navigation system to intelligently dispatch teleports for distant zones, compute 3D elevation-aware A* routes with contour strafing, execute active evasion maneuvers on obstacles, and visualize 3D terrain heights in the dashboard navigation map**, so that **the bot moves reliably and smoothly through 3D game environments without getting trapped by cliffs or obstacles**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon the offline vector extraction and navigation foundation:
  - [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md): Authoritative extraction of `.lnd` height fields, `.rgn` spawn zones, and `.dyo` obstacles.
  - [US-035](completed/US-035-measured-minimap-odometry-and-tracking-quality.md): Minimap odometry and tracking quality.
  - [US-039](completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md) & [BUG-009](fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md): Stall detection and combat obstacle recovery.
  - [US-040](US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md): Unrecoverable stuck emergency teleport.
  - [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md): Visual navigation inspector.
- The Flyff client terrain consists of 3D grid height fields where vertical rise $(\Delta Y)$ over horizontal run $(\Delta d)$ dictates passability (slopes $> 45^\circ$ / gradient $> 1.0$ cannot be walked directly).
- Adheres strictly to project safety boundaries:
  - No process memory injection, reading, or tampering.
  - Traversal decisions rely on authoritative offline client terrain data combined with continuous visual odometry and Win32 input dispatch.

## Acceptance criteria

- [ ] **Long-Range Goal Dispatch & Teleport Automation:**
  - Given an active farming target zone or quest goal change, when the calculated path distance to the destination exceeds a configurable long-range threshold (e.g. `> 150` world units), the navigation controller initiates an automated fast-travel/teleport dispatch (via configured in-game teleport command/hotkey) to the nearest available zone anchor before engaging ground pathing.
  - If teleportation is disabled, unavailable, or the character is already within walking range, the system smoothly defaults to direct ground pathing.
- [ ] **3D Elevation-Aware A\* Pathing with Contour Strafing:**
  - Given extracted 3D heightfield data (`.lnd`), the A* path planner incorporates vertical elevation deltas $(\Delta Y)$ and slope penalty weights into edge traversal costs.
  - Paths automatically route along natural terrain contours and saddles, avoiding steep vertical ascents that cause physics stalls.
  - Waypoint generation includes lateral strafe angles when rounding convex terrain corners or hugging hillsides to maintain momentum without wall friction.
- [ ] **Active 3D Evasion Maneuvers & Anti-Stall Recovery:**
  - When the `StallDetector` signals a movement interruption during path traversal:
    - The controller executes a multi-step evasion sequence: immediate lateral strafe pulse (left/right bias based on local terrain slope gradient), brief backstep, and dynamic tangent re-routing.
    - If repeated evasion attempts at the same location fail, the bot marks the local node as temporarily impassable and re-plans the global A* route around the obstruction.
- [ ] **3D-Enriched Navigation View & Elevation Profile:**
  - The PySide6 Navigation Map Inspector is enhanced with elevation-aware visual layers:
    - Visual elevation contour coloring (topographic shading / height gradient overlay from `.lnd` data).
    - 3D waypoint markers and active trajectory vectors.
    - A miniature elevation profile strip showing the remaining route's ascent/descent profile.
- [ ] **Safety & Emergency Controls:**
  - Pressing the emergency stop key (`END` or `Escape`) immediately aborts all active navigation sequences, halts all movement inputs (`W`, `A`, `S`, `D`, jump), and resets state to idle.
  - Foreground window validation is strictly enforced before every movement input dispatch.
- [ ] **Localization Sync:**
  - All user-visible settings, navigation statuses, dashboard labels, and log entries are synchronized in both German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Out of scope

- Direct process memory reading, hooking, or DLL injection into `neuz.exe`.
- Direct modification of client game assets on disk.
- Free-flight 3D aerobatics or flight-mount combat.

## Verification

- Automated:
  - Unit tests for 3D elevation cost heuristics and contour smoothing in `test_vector_routing.py`.
  - Unit tests for long-range teleport dispatch decision logic and thresholds.
  - Unit tests for directional evasion maneuver sequences and stall escalation.
- Manual (Windows):
  - Load a multi-zone map with hilly terrain in the dashboard.
  - Verify that selecting distant spawn zones triggers teleport dispatch when configured.
  - Observe the character navigating steep slopes via smooth contour routes and successfully executing evasion pulses when intentionally blocked by an obstacle.
  - Verify that the Navigation Inspector renders the elevation-shaded map and path profile correctly.
