---
id: US-027
title: Minimap radar mob detection and calibrated navigation clicks
status: rejected
created: 2026-08-16
updated: 2026-08-17
---

# US-027: Minimap radar mob detection and calibrated navigation clicks

## Rejection

Rejected on 2026-08-17 without implementation. Radar navigation solves the same problem as the
spatial memory delivered by [US-019](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) and
[US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md): reaching spawns that lie
outside the camera viewport. `FarmingOrchestrator` already consults `PathingController` before the
staged search stages, so a learned spawn heatmap and its patrol circuit steer the character toward
recorded mob density without ever clicking the HUD.

That leaves radar navigation valuable only on a cold, unmapped camp — a transient window that
closes after the first patrol lap — while permanently adding a calibrated pixel geometry, a second
guarded click path aimed at the HUD, and a dashboard option to maintain. The remaining coverage gap
is better closed by improving how quickly `SpatialMap` bootstraps a usable route than by adding a
parallel navigation mechanism.

Two findings from the calibration spike are worth keeping, should this ever be revisited:

- The minimap is a fixed-pixel HUD element like the vitals orb in
  [BUG-006](../bugs/fixed/BUG-006-player-vitals-resolution-scaling-and-flicker-spam.md), not a fraction of
  the window. Measured against `data/full_screen_view_with_monster_stats_1600_900_Res.png`, its
  centre sits 88 px left of the client right edge and 104 px below the client top, with an outer
  ring radius of 82 px and a navigable inner map surface ending at radius 67 px. The existing
  normalized bounds in `MinimapRadarConfig` would drift off the circle on any other resolution.
- All five minimap buttons (collapse, close, help, zoom in, zoom out) sit *on* the decorative ring
  at radius 77–79 px, so a circular mask inset to the inner map surface already excludes them; the
  explicit UI exclusion zones this story specifies would be a second, redundant layer.
- The prescribed dot thresholds (`Red >= 150`, `Green <= 120`, `Blue <= 120`) match reddish terrain
  inside the reference minimap, producing 763 qualifying pixels in components of up to 50 px with
  no monster dots present. The `>= 4` pixel minimum alone does not reject them.

`MinimapRadar` and `SearchMode.MINIMAP_RADAR` remain in the codebase as the uncalibrated,
never-dispatched components US-015 left behind; `SearchController` still cycles from roaming back to
rotation without emitting radar clicks.

The original specification is preserved below unchanged.

## Story

As a **bot operator farming in sparse or wide spawn zones**, I want **the bot to accurately locate distant monster radar dots on the minimap using circular radar masking, UI button exclusion, and calibrated navigation clicks**, so that **the character can navigate toward distant monster spawns without risking accidental clicks on adjacent UI buttons, channel menus, or window close controls**.

## Context and assumptions

- In Flyff, the top-right HUD displays a circular minimap radar indicating nearby monsters as distinct red dots.
- [US-015](completed/US-015-idle-timeout-and-search-navigation.md) originally explored minimap radar clicking as an experimental Tier 3 stretch goal via a simple bounding-box color filter. However, in field testing, raw rectangular ROI scanning risks misclicking on nearby red UI elements (such as window close buttons, event banners, or channel menus).
- [US-019](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) and [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md) introduced internal spatial memory and topological patrol routes, making raw minimap clicking unnecessary for standard known routes.
- This story provides the complete, robust specification for minimap radar navigation when operators choose to enable long-range radar navigation in unmapped or wide spawn fields.
- Radar navigation requires:
  1. **Anchor Calibration:** Template-matching the minimap compass/border to establish the exact center coordinate $(C_x, C_y)$ and radius $R$.
  2. **Circular Geometric Mask:** Constraining dot searches strictly to the inner radar circle: $(x - C_x)^2 + (y - C_y)^2 \le (R - \text{margin})^2$.
  3. **UI Exclusion Zones:** Explicitly masking out zoom buttons (`+`/`-`), coordinate text overlays, channel dropdowns, and map expand icons.
  4. **Paced Click Dispatch:** Enforcing a navigation movement debounce (e.g. 2.0s–3.0s) after a minimap click to allow the character to travel toward the destination before re-evaluating.
  5. **Immediate Perception Interruption:** The instant a valid monster enters the camera viewport and is detected by YOLO, radar movement halts immediately and the bot transitions to `TARGETING`.

## Acceptance criteria

- [ ] **Minimap anchor calibration and circular masking:**
  - Given a captured game frame, the minimap component locates the radar center and boundary using a template anchor or calibrated top-right offset.
  - Pixel scanning for red monster dots is restricted to a circular mask, ignoring all rectangular corners and outer borders.
- [ ] **UI button exclusion and false-positive rejection:**
  - Known static button regions (zoom controls, channel selector, window controls) within the minimap ROI are masked out as non-navigable.
  - Red-dot candidate clusters must satisfy minimum density and area constraints ($\ge 4$ pixels) and distinct color thresholds (`Red >= 150`, `Green <= 120`, `Blue <= 120`).
- [ ] **Safe navigation click dispatching:**
  - When radar navigation triggers in search mode, the dispatcher verifies that the target click coordinates lie strictly within the valid circular radar interior.
  - Clicks are dispatched via standard foreground- and END-guarded platform adapters.
  - A configurable travel debounce (default 2.5s) prevents click spamming while the character moves toward the target coordinate.
- [ ] **Configurable UI toggle & Placements overlay:**
  - The desktop dashboard provides an explicit opt-in toggle (`"Minimap-Radar Navigation aktivieren"` / `"Enable Minimap Radar Navigation"`, default: `false`).
  - When the dashboard's **"Placements"** guide toggle is enabled, the circular minimap boundary and active UI exclusion zones are rendered directly onto the live viewport preview, allowing operators to verify minimap position and scaling at a glance.
  - When disabled, staged search relies entirely on camera rotations, pitch tilting, roaming steps, and topological pathing.
- [ ] **Immediate combat preemption:**
  - Any newly visible target mob detected by the perception pipeline immediately aborts radar navigation and hands over control to `TARGETING` -> `COMBAT`.
- [ ] **Localization:**
  - All user-facing toggle labels, tooltips, and radar status messages are synchronized in German (`de.json`) and English (`en.json`).
- [ ] **Automated verification:**
  - Unit tests verify circular mask filtering, button exclusion zones, travel debounce timing, and UI signal handling.
  - `./scripts/check.ps1` passes cleanly.

## Out of scope

- Dynamic minimap zoom level adjustment or optical character recognition of minimap map labels.
- Obstacle avoidance during minimap travel (relies on player pathfinding built into the Flyff client).

## Verification

- Automated:
  - `uv run pytest tests/unit/test_minimap_radar.py tests/unit/test_search_navigation.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui` in a wide spawn area with the minimap toggle enabled.
  2. Clear nearby mobs and wait for staged search to activate.
  3. Verify that the bot clicks exclusively inside the circular radar on distant red dots, ignores surrounding UI buttons, and immediately engages any mob that appears on screen.
