---
id: US-023
title: Reliable combat targeting, click debouncing, and monster kill verification
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-023: Reliable combat targeting, click debouncing, and monster kill verification

## Story

As a player using the autonomous farming bot, I want the combat controller to debounce target-selection clicks, reliably dispatch the configured attack hotkey upon target acquisition, accurately verify monster kills via target health decay and the HUD monster stats counter, and display an on-screen overlay guide box for HUD placement across client resolutions, so that target selection never causes accidental character walking, skips attack hotkeys, drops active fights prematurely, or mistakes target loss for a kill.

## Context and assumptions

- **Architectural & Subsystem Links:**
  - Extends reactive combat control in [US-008](completed/US-008-reactive-combat-controller.md) (`CombatController`, `CombatMode`, `CombatInputDispatcher`).
  - Integrates with target verification in [US-004](completed/US-004-target-mob-verification.md) and [US-012](completed/US-012-real-world-vision-refactoring.md) (`TargetVerifier`, `TargetStatus`, `TargetState`).
  - Integrates with the autonomous farming loop in [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`).
  - Integrates with configurable attack hotkeys in [US-014](completed/US-014-configurable-ui-attack-key.md).
  - Coordinates with the loot controller in [US-009](completed/US-009-reactive-loot-controller.md) (`LootController`) so pickup routines only trigger after genuine kills.
  - Connects to dead-reckoning navigation in [US-019](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) (`MovementTracker`, `SpatialMap`), where unintended character walking severely corrupts position tracking.
  - Connects to PySide6 visual overlays in [US-010](completed/US-010-pyside6-dashboard-and-overlay.md) and [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md).
- **Target Selection & Double-Click Movement Defect:**
  - In Flyff, clicking twice on ground/world coordinates in rapid succession commands the character to walk to that spot.
  - If a target mob is clicked and the target header does not render within a single tick (100 ms) or temporarily flickers, the existing controller immediately resets from `TARGETING` to `IDLE`/`SEARCHING`.
  - In the subsequent tick, the visible mob is clicked again, generating an accidental double-click that moves the player, ruins navigation tracking, and pulls unwanted aggro.
  - A click debouncer with a configurable acquisition grace window (default 0.8s) must prevent repeated clicks while waiting for the target header to register.
- **Attack Hotkey Dispatching & Engagement Guarantee:**
  - Upon observing `TargetState.VALID`, the controller must guarantee the configured attack hotkey (e.g. `F3` or custom binding) is dispatched and repeated according to cooldowns until combat progress (HP reduction) or target death is observed.
  - Single-frame visual drops or template score dips during active fighting must not prematurely reset the combat state machine.
- **Kill Verification & HUD Monster Stats Counter:**
  - A target loss (e.g. deselect, line-of-sight break, or animation flicker) must be clearly distinguished from target death:
    - **Target Bar Health:** Target HP reached 0% or disappeared *after* confirmed combat damage was dealt (`hp_pixel_count` decreased). If a target disappears without receiving damage, it is treated as a target loss (triggering retargeting), not a kill.
    - **HUD Monster Stats Counter:** The server's in-game session stats HUD (as evidenced in `data/monster_stats.png` and client screenshots) displays `Monster Kills: <int>` adjacent to the top-left player vitals orb. Incrementing this counter provides unambiguous ground-truth kill confirmation.
  - **Resolution Scaling & Overlay Guide Box:**
    - The monster stats region scales relative to client window dimensions.
    - The desktop overlay renders a visible guide bounding box (placement alignment rectangle) so the operator knows exactly where to position the in-game monster stats window on screen for reliable detection.
- **Safety Boundaries:**
  - All input actions remain strictly guarded by foreground window focus checks and the `END` emergency stop key.
  - All user-facing text and overlay elements are fully synchronized in German (`de.json`) and English (`en.json`).

## Acceptance criteria

- [ ] `CombatController` implements target click debouncing with a configurable acquisition grace window (default 0.8s) that prevents sending multiple rapid clicks for the same target acquisition attempt.
- [ ] Transitioning from `TARGETING` to `ENGAGING` guarantees that the configured attack hotkey is dispatched without being skipped by intermediate tick state resets.
- [ ] During `FIGHTING`, transient single-frame target-header verification dropouts do not immediately reset combat or trigger loot routines; an engagement timeout/grace period is maintained.
- [ ] `MonsterStatsReader` (or OCR perception feed) extracts the numeric `Monster Kills` count from the top-left HUD stats area with resolution scaling support.
- [ ] `WorldState` reflects the verified kill count and tracks combat kill events.
- [ ] Target death confirmation requires either:
  - An increment in the observed `Monster Kills` counter, OR
  - Target HP reaching 0% / target bar disappearing *after* measurable HP decrease was observed during combat.
- [ ] If a target is lost before any damage is dealt, the orchestrator returns to targeting the candidate rather than transitioning to `LootController`.
- [ ] The PySide6 visual debug overlay renders a distinct calibration guide box outlining the expected position and bounds of the in-game monster stats window across all supported client resolutions.
- [ ] Dashboard settings expose options to configure the target click grace period and toggle monster stats kill verification.
- [ ] All new UI controls, overlay guide labels, tooltips, and status descriptions are fully synchronized in German (`de.json`) and English (`en.json`).
- [ ] Automated unit tests in `tests/unit/` verify:
  - Target click debouncing and prevention of duplicate clicks within the acquisition window.
  - Reliable attack hotkey dispatching upon valid target acquisition.
  - Distinguishing genuine target death from un-damaged target loss.
  - Monster stats ROI extraction and kill count OCR parsing across scaled resolutions.
  - Overlay calibration guide box geometry calculation.
  - Focus loss and emergency stop halting behavior.

## Out of scope

- Direct reading or modification of game memory, process memory scanning, or packet inspection.
- Automatically dragging or repositioning windows inside the third-party game client.
- Multi-target party aggro management or kill attribution across external party members.

## Verification

- Automated:
  - `uv run pytest tests/unit/test_combat_controller.py`
  - `uv run pytest tests/unit/test_orchestrator.py`
  - `uv run pytest tests/unit/test_monster_stats.py`
  - `uv run pytest tests/unit/test_ui.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  1. Open Flyff client and launch desktop dashboard with debug overlay enabled.
  2. Verify the monster stats overlay guide box is drawn in the top-left area matching the client HUD.
  3. Align the in-game monster stats window to the guide box.
  4. Start autonomous farming in a spawn area (`Flame`).
  5. Verify single-click targeting occurs without double-click character walking.
  6. Verify attack hotkey fires immediately upon target lock and combat proceeds until monster dies.
  7. Verify kill counter increments and triggers loot collection cleanly.
