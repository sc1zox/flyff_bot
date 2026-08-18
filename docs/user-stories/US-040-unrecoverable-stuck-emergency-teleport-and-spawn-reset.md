---
id: US-040
title: Unrecoverable stuck emergency teleport and spawn point reset
status: draft
created: 2026-08-18
updated: 2026-08-18
---

# US-040: Unrecoverable stuck emergency teleport and spawn point reset

## Story

As a **bot operator running autonomous farming**,
I want **the bot to detect when all unstuck mechanisms have failed continuously for a configurable duration (default 60s), trigger a configurable emergency teleport hotkey (e.g. Town Blinkwing), and reset the pathing/navigation position to a configurable per-map spawn point anchor**,
so that **the character does not remain stuck permanently off the map or in un-walkable geometry, and can resume navigation or safely recover from the designated town/spawn location**.

## Context and assumptions

- [Architecture](../wiki/architecture.md) (US-013, US-015, US-018, US-019, US-021, US-035, US-036, US-039).
- In the Entropia Flyff PServer (`neuz.exe`) client, characters can occasionally fall off world edges (e.g. floating island borders, cliff drops, bridge gaps) or get wedged in un-walkable terrain geometry where normal movement, camera rotation, and obstacle bypass maneuvers cannot free them.
- The bot already contains micro-unstuck and staged recovery mechanisms:
  - `SearchController` executes horizontal and vertical camera scans and roaming pulses ([US-015](../user-stories/completed/US-015-idle-timeout-and-search-navigation.md), [US-018](../user-stories/completed/US-018-multi-axis-camera-search-and-paced-scanning.md)).
  - `PathingController` executes waypoint retreats and Dijkstra bypasses around stalled cells ([US-019](../user-stories/completed/US-019-intelligent-pathing-and-spawn-heatmap.md)).
  - `CombatController` breaks stalled engagements on obstacles ([US-039](US-039-combat-obstacle-stall-detection-and-re-navigation.md)).
- When all of these mechanisms fail to restore mobility and no spatial progress or combat occurs for an extended duration (default 60.0s, user-configurable), the situation is unrecoverable without external teleportation.
- Flyff provides instant or near-instant teleport items (e.g. Town Blinkwing / Blinkwing) or teleport skills assigned to a quickslot/hotkey.
- Activating a Town Blinkwing teleports the player directly to a known respawn/town area.
- Because teleportation instantly alters world coordinates, the bot's internal spatial state (`MovementTracker`, `SpatialMap`, active route) must be cleanly reset to avoid carrying corrupted out-of-bounds coordinates.
- Each navigation profile supports mapping a designated spawn point coordinate $(x_s, y_s)$ representing the town/respawn anchor for that map.
- Standard safety boundaries apply: input dispatch strictly checks Windows foreground focus and the `END`/`Escape` emergency stop.
- All user-visible settings, tooltips, and status messages must be localized in German and English (`src/flyff_bot/locales/*.json`).

## Acceptance criteria

- [ ] **Configurable Unstuck Timeout & Teleport Hotkey:**
  - The UI exposes a configurable unrecoverable stuck timeout (default: `60.0s`, configurable range `10.0s`–`300.0s`).
  - The UI exposes a configurable emergency teleport hotkey (supporting `F1`–`F12`, `0`–`9`, `A`–`Z`; default `F4` or unassigned).
  - Teleport settings are persisted to disk alongside recovery configurations.
- [ ] **Unrecoverable Stuck Detection:**
  - `FarmingOrchestrator` / `Supervisor` monitors the continuous duration during which the bot remains in a stalled or stuck state without successful spatial progress, movement displacement, or target engagement.
  - Any successful mob engagement, damage deal, or verified position advancement immediately resets the unrecoverable stuck timer.
  - If the continuous stuck duration reaches the configured timeout, the bot initiates emergency teleport recovery.
- [ ] **Guarded Emergency Teleport Dispatch:**
  - The bot dispatches the configured emergency teleport hotkey using guarded Win32 input (ensuring foreground window focus and verifying that the `END`/`Escape` emergency stop is clear).
  - An instant post-teleport settling delay (default: `2.0s`) pauses controller actions while the client rendering/teleport transition settles.
- [ ] **Per-Map Spawn Point Mapping:**
  - The navigation map profile schema and UI (`PathInspectorWidget` / Profile Controls) allow the operator to mark/set a single designated spawn anchor coordinate $(x_s, y_s)$ per navigation profile (e.g. via a "Set Spawn Point" button or right-click coordinate selection).
  - The mapped spawn coordinate is persisted in the profile `.json` file.
- [ ] **Pathing & Position Reset:**
  - Upon successful emergency teleport execution, `MovementTracker` resets its estimated dead-reckoning coordinates directly to the profile's mapped spawn point $(x_s, y_s)$ (or $(0.0, 0.0)$ if no custom spawn coordinate was mapped).
  - `SpatialMap` clears transient route traces and marks the previous stuck position as blocked/penalized to prevent immediately walking back off the same ledge.
  - The bot resumes navigation/patrol planning from the mapped spawn anchor.
- [ ] **Failure & Cancellation Behavior:**
  - If the emergency teleport hotkey is triggered but foreground focus is lost or emergency stop is engaged, input is immediately aborted.
  - If no emergency hotkey is configured when the timeout expires, the bot pauses farming and alerts the operator in the dashboard.
- [ ] **Localization:**
  - All new dashboard labels, tooltips, dialogs, and recovery status messages are fully synchronized in German (`de.json`) and English (`en.json`).
- [ ] **Verification:**
  - Unit tests verify timer accumulation, timer cancellation upon progress, guarded hotkey execution, and position reset to mapped spawn coordinates.
  - `./scripts/check.ps1` passes cleanly with zero lint and type errors.

## Out of scope

- Reading 3D client geometry, bounding boxes, or navmeshes from game memory.
- OCR inventory scanning to count remaining physical Blinkwing item stacks.
- Automated NPC interaction for buying replacement Blinkwings.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_emergency_recovery.py` verifying stuck timeout trigger logic and timer reset upon progress.
  - Unit tests in `tests/unit/test_pathing.py` and `tests/unit/test_movement_tracker.py` verifying spawn point anchoring and coordinate reset on teleport.
  - Integration tests in `tests/unit/test_orchestrator.py` verifying orchestrator transition into emergency recovery and back to navigation.
  - `./scripts/check.ps1` passes.
- Manual (Windows):
  - In the dashboard, configure an emergency teleport key (e.g. assigned to Town Blinkwing) and map a spawn point.
  - Test in Flyff by placing the character in a wedged/stuck obstacle or ledge.
  - Verify that after the configured timeout (e.g. 60s) of failed unstuck attempts, the bot presses the emergency hotkey, teleports to town, resets its coordinate to the spawn point, and resumes from the mapped spawn location.
