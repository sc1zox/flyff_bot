---
id: US-018
title: Multi-axis camera search with vertical pitch tilt and paced scanning
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-018: Multi-axis camera search with vertical pitch tilt and paced scanning

## Story

As a player using autonomous farming, I want the bot's search navigation to support vertical camera pitch adjustments (Up/Down arrow keys) and gentler, paced rotation steps with inter-step observation pauses, so that the bot can discover monsters located on slopes, elevations, or uneven terrain without spinning past spawns too quickly for visual perception to catch.

## Context and assumptions

- **Related Items & Architecture:**
  - Extends [US-015](completed/US-015-idle-timeout-and-search-navigation.md) (`SearchController` and `FarmingOrchestrator` search loop) and incorporates lessons from [BUG-003](bugs/fixed/BUG-003-search-mode-camera-rotation-keys.md) (arrow-key camera control).
  - Works cooperatively with [US-007](completed/US-007-perception-worldstate-feed.md) (`PerceptionPipeline`), [US-003](completed/US-003-mob-detection-yolo.md) (`OpenCVDnnYoloDetector`), and [US-008](completed/US-008-reactive-combat-controller.md) (`CombatController`).
- **Flyff Camera Mechanics & Terrain Scanning:**
  - **Horizontal Yaw (Left/Right Arrow `VK_LEFT` / `VK_RIGHT`):** Rotates the camera 360 degrees horizontally.
  - **Vertical Pitch (Up/Down Arrow `VK_UP` / `VK_DOWN`):** Tilts the camera elevation angle (Up Arrow raises camera into bird's-eye view, Down Arrow lowers camera to look upward).
  - In many Flyff hunting areas (e.g. Lawolf hills, Steamwalker slopes, Darkon mountains), terrain slope or vertical spawn placement obscures mobs from a flat camera perspective.
  - Tilting the camera pitch (e.g. a short Up-Arrow pulse to gain high-angle perspective or Down-Arrow for climbing slopes) significantly broadens the effective detection field of view.
- **Paced Camera Movement & Visual Settling:**
  - Fast, continuous key presses can rotate the viewport faster than the perception frame rate (e.g. 10–20 FPS), creating motion blur or causing the camera to overshoot candidate mobs before YOLO inference completes.
  - Paced search uses shorter, gentler key pulses (e.g. default 0.2s duration) followed by a configurable visual settling pause (e.g. default 0.3s) between rotation/tilt increments.
  - **Instant Interruption:** As with US-015, if any perception frame during a settling tick reveals an eligible mob in `state.visible_mobs`, all search movement immediately stops and transitions to `TARGETING`.
- **Safety Boundaries:**
  - All camera keystrokes (`VK_LEFT`, `VK_RIGHT`, `VK_UP`, `VK_DOWN`) are dispatched exclusively when the Flyff window is foregrounded and immediately released upon focus loss or emergency stop (`END` key).

## Acceptance criteria

- [ ] `SearchController` supports multi-axis camera scanning stages:
  - Horizontal rotation (`SearchMode.ROTATE` via `VK_RIGHT` or `VK_LEFT`)
  - Vertical tilt / pitch (`SearchMode.TILT` via `VK_UP` or `VK_DOWN`)
- [ ] `SearchConfig` exposes configurable pacing and pitch parameters:
  - `rotation_step_duration_seconds: float` (default `0.2s` for gentler rotation steps)
  - `rotation_settle_pause_seconds: float` (default `0.3s` observation pause between rotation pulses)
  - `tilt_step_duration_seconds: float` (default `0.2s` for vertical pitch adjustment)
  - `tilt_virtual_key: int` (default `VK_UP = 0x26`, supporting `VK_DOWN = 0x28`)
  - `tilt_steps: int` (default `2`)
- [ ] During `SearchMode.ROTATE` and `SearchMode.TILT`, search pulses alternate between brief key presses and settle pauses to ensure clean perception frames without visual overshooting.
- [ ] If perception detects a valid mob in `state.visible_mobs` at any point during rotation, tilt, or settle pause, search immediately aborts and control transitions to `TARGETING`.
- [ ] Guarded key holds and emergency stop (`END`) immediately release any active arrow key and halt searching.
- [ ] CLI arguments (`--search-tilt-duration`, `--search-settle-pause`, `--search-tilt-key`) and Dashboard status strings are localized in German and English (`de.json` / `en.json`).
- [ ] Automated unit tests in `tests/unit/test_search_navigation.py` verify:
  - Transition sequence: `ROTATE` -> settle pause -> `TILT` -> `ROAM_STEP` -> `MINIMAP_RADAR`.
  - Pacing timers and duration enforcement.
  - Immediate interruption on perception detection.
  - Safety abort on focus loss and emergency stop.

## Out of scope

- 3D terrain heightmap pathfinding or automated obstacle climbing.
- Mouse-drag camera rotation (strictly virtual-key arrow input).

## Verification

- Automated: Unit tests in `tests/unit/test_search_navigation.py` and `tests/unit/test_orchestrator.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Start the bot on uneven/sloped terrain with no mobs in immediate view.
  2. Observe the camera rotating in smooth, paced increments with brief pauses, followed by a vertical tilt adjustment.
  3. Observe that the bot immediately stops turning and engages when a mob enters the camera field of view.
