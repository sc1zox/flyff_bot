---
id: US-020
title: Visual navigation path and spawn heatmap inspector in desktop UI
status: completed
created: 2026-08-16
updated: 2026-08-16
---

# US-020: Visual navigation path and spawn heatmap inspector in desktop UI

## Story

As an operator using the desktop dashboard, I want to toggle a visual 2D navigation map and spawn heatmap inspector widget, so that I can visually observe the character's real-time position, traversed pathways, learned spawn hotspots, stuck cost penalties, and active patrol routes during farming sessions.

## Context and assumptions

- **Architectural Dependencies:**
  - Extends [US-010](completed/US-010-pyside6-dashboard-and-overlay.md) (Native PySide6 Dashboard) and [US-019](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) (`SpatialGridMap`, `NavigationMap`, `PathingController`).
  - Operates purely within the PySide6 UI layer (`flyff_bot.ui`) without introducing web runtimes or external rendering frameworks.
- **Visual Presentation & Representation:**
  - The navigation map renders a 2D top-down view centered on the farming area origin $(0, 0)$:
    - **Spawn Heatmap:** Colored circles/cells shaded by `spawn_score` (e.g., green/yellow/red heat gradient) representing monster encounter density.
    - **Traversed Network:** Waypoint nodes and connecting path lines showing recorded walkable routes.
    - **Obstacles / Stuck Penalties:** Nodes or edges with elevated pathing costs rendered with distinct caution indicators.
    - **Current Player Position & Heading:** Prominent marker with directional indicator showing the character's estimated position.
    - **Active Planned Path:** Highlighted polyline showing the currently targeted waypoint route.
    - **Leash Boundary:** Dotted boundary circle indicating the configured maximum farming radius.
- **UI Integration & Controls:**
  - Dashboard includes a toggle control (checkbox or button) to display/hide the visual path map alongside the video debug overlay.
  - Updates are received via `DashboardUpdate` on the Qt main thread in a thread-safe, non-blocking manner.
  - All user-facing strings (toggle label, legend items, tooltips) are localized in German and English (`de.json` / `en.json`).

## Acceptance criteria

- [x] `NavigationMapWidget` (or `PathInspectorWidget`) provides a 2D top-down canvas rendering:
  - Coordinate axes / origin $(0, 0)$ and leash radius boundary circle.
  - Spawn heatmap hotspots with visual intensity scaling.
  - Traversed path nodes and connecting line segments.
  - Penalized / high-cost stuck locations marked with distinct visual styling.
  - Current character position and heading direction arrow.
  - Active planned route path highlighted when navigating.
- [x] Dashboard `MainWindow` incorporates a toggle control to show/hide the visual navigation inspector.
- [x] `DashboardUpdate` carries the latest navigation snapshot (`NavigationMap` / pathing state) to update the canvas in real-time during active farming ticks.
- [x] The widget auto-scales or fits the bounding box of visited nodes and leash boundary smoothly.
- [x] All UI strings and legend labels are synchronized in German and English (`de.json` and `en.json`).
- [x] Automated unit tests in `tests/unit/test_ui.py` verify:
  - Widget instantiation and clean painting with empty, initial, and populated navigation maps.
  - Toggle visibility behavior in `MainWindow`.
  - Signal update propagation from `DashboardUpdate`.

## Out of scope

- Interactive map editing (e.g. clicking on canvas to add manual waypoints or delete nodes).
- 3D terrain heightmap rendering.

## Verification

- Automated: Unit tests in `tests/unit/test_ui.py` and `tests/unit/test_path_inspector.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. Enable the navigation map checkbox; observe the 2D canvas displaying origin, player marker, and leash radius.
  3. Start farming; observe the path expanding, spawn hotspots coloring up, and active routes drawing in real-time.
