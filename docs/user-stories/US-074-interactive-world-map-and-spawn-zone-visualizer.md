---
id: US-074
title: Interactive world map and spawn zone inspector with right-click pan, zoom, and zone selection
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-074: Interactive world map and spawn zone inspector with right-click pan, zoom, and zone selection

## Story

As a **bot operator on Entropia Flyff**, I want **a dedicated, interactive world map and spawn zone inspector in the UI that visualizes extracted game regions (3D terrain heightfields, NavMesh passability, and monster spawn camps) with right-click drag panning, mouse-wheel zooming, click-to-select zone targeting, detailed monster hover tooltips, and player follow mode**, so that **I can intuitively inspect, explore, and select farming locations, pathing trajectories, and monster distributions across entire game regions in real time**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Client assets (`.wld`, `.lnd`, `.rgn`, `.dyo`) provide authoritative 3D terrain heightfields (129x129 heights per block), NavMesh passability triangles, and 7,300+ respawn zone bounding boxes extracted via [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md), [US-052](completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md), [US-055](completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md), and [US-059](completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md).
- Follows [ADR-002](../decisions/ADR-002-target-architecture-and-pyside6.md) (PySide6 Qt UI) and [ADR-005](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md) (offline read-only extraction of game assets).
- Camera Pan & Zoom:
  - **Pan:** Dragging with the **right mouse button (RMB)** smoothly translates the viewport across world coordinates (X/Z). Left-click is reserved for selecting spawn zones and interacting with UI elements.
  - **Zoom:** Rotating the **mouse wheel** smoothly scales the view in and out, centered at the current cursor position, bounded by configurable minimum and maximum scale limits.
  - **Auto-Follow / Center on Player:** A toggle button and shortcut allow locking the viewport to the live character position (`WorldPosition`) received from read-only memory per [ADR-006](../decisions/ADR-006-read-only-process-memory-access.md). Dragging the map automatically suspends follow mode.
- Visual Representation & Rendering:
  - Renders 3D terrain surface meshes / heightfields (with isometric / 3D tilt capability where supported, and top-down relief shading fallback), static object collision footprints, NavMesh passability corridors, active path waypoints, and spawn zone boundaries.
  - Uses viewport frustum culling to efficiently render large world maps (e.g. Madrigal / Darkon) at interactive framerates without UI lag.
- Interactive Spawn Zone Features:
  - **Hover Tooltips:** Hovering over a spawn zone reveals a rich metadata card showing monster name, monster ID, spawn capacity, respawn interval, and center coordinates.
  - **Camp Selection:** Left-clicking a spawn zone selects it, highlights its boundary, and sets it as the active farming / navigation target.
- UI Integration:
  - Embedded as a dedicated interactive map feature in the UI, accessible both as a primary tab and within the standalone `NavigationMapWindow`.
- Localization: All user-visible labels, tooltips, buttons, legend items, and HUD elements must remain synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).

## Acceptance criteria

- [ ] Given extracted world data (`WorldVectorMap`), when the interactive map view is opened, then terrain heightfields, NavMesh passability, and respawn zones are rendered with clear visual differentiation.
- [ ] Given the map canvas, when the user drags with the right mouse button (RMB), then the camera pans across world coordinates smoothly without triggering selection events.
- [ ] Given the map canvas, when the user scrolls the mouse wheel, then the view zooms in or out smoothly centered at the mouse cursor position within bounded zoom limits.
- [ ] Given an active bot session with live GPS coordinates, when the "Center on Player" / "Follow Player" mode is activated, then the viewport continuously centers on the player's live position and heading.
- [ ] Given the map canvas, when hovering over a respawn zone, then a tooltip displays monster name, monster ID, capacity, respawn interval, and coordinates if available.
- [ ] Given the map canvas, when left-clicking a respawn zone, then the zone is highlighted and selected as an active target camp / navigation goal.
- [ ] Given large world regions with thousands of height vertices and zones, rendering performs smoothly at interactive framerates (>30 FPS) with view-frustum culling of off-screen terrain blocks.
- [ ] All user-visible strings, tooltips, and controls are localized and synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- In-game client memory writing (`WriteProcessMemory`) or modifying game files.
- Injecting artificial mouse clicks into `neuz.exe` from the bot map view.
- Real-time client packet injection or server-side mob manipulation.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_interactive_path_inspector.py` testing world-to-screen and screen-to-world coordinate transformations, right-click pan offsets, zoom level clamping, frustum culling, and zone hit-testing.
- Manual (Windows):
  - Launch the bot UI, open the interactive map view, pan by dragging with the right mouse button, zoom with the mouse wheel, hover over spawn zones to verify metadata tooltips, click a zone to select it, and enable player follow mode during live gameplay.
