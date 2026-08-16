---
id: US-028
title: Live perception standby, bot status visualization, and robust start focus workflow
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-028: Live perception standby, bot status visualization, and robust start focus workflow

## Story

As a **player configuring and supervising the Flyff bot**,
I want **the perception pipeline and HUD placement guides to run continuously in a read-only standby mode and the dashboard to display dedicated bot status indicators with reliable window-focus startup**,
so that **I can inspect and verify all vision/vitals readings before launching automation and seamlessly start farming with clear feedback**.

## Context and assumptions

- Currently, `FarmingOrchestrator.tick()` exits early when paused without invoking `PerceptionPipeline.tick()`, leaving `WorldState`, vitals, target debug, and overlay frames uninitialized until combat is actively started.
- The UI status badge currently conflates mob count (`UI_WORLD_STATUS`) with execution status (`UI_BOT_STATUS`), causing labels to overwrite each other.
- Clicking the "Starten" button can result in an immediate, silent transition back to `PAUSED` if the game window is not yet foregrounded, giving the user the appearance that clicking "Starten" has no effect.
- Read-only perception (capturing frames, detecting mobs, reading HUD vitals, evaluating target verification) sends zero mouse or keyboard inputs to the game window and can safely execute in the background or standby mode.
- Links:
  - [Architecture](file:///i:/coding%20projects/flyff_bot/docs/wiki/architecture.md)
  - [US-010: Native PySide6 dashboard and visual debug overlay](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-010-pyside6-dashboard-and-overlay.md)
  - [US-013: Autonomous farming loop and orchestration engine](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-013-autonomous-farming-loop-and-orchestration-engine.md)
  - [US-022: Modern dark theme and streamlined dashboard UI](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-022-modern-dark-theme-and-streamlined-dashboard-ui.md)
  - [US-026: Static HUD anchoring and field hardening for vitals and monster stats](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md)

## Acceptance criteria

- [ ] Given the desktop UI is open and the bot is paused, when a valid game window is present, the perception pipeline runs continuously in read-only mode to update player vitals (HP/MP/FP), visible mob count, target debug metrics, and debug overlays without sending any game inputs.
- [ ] Given the desktop UI is open, when the game window is not found, closed, or minimized, the dashboard displays an explicit status notification (e.g. "Spielfenster nicht gefunden" / "Spielfenster minimiert") rather than silently doing nothing.
- [ ] Given the status & metrics card in `MainWindow`, the UI displays a dedicated Bot Status badge (e.g., `Bereit (Live-Vorschau)`, `Sucht Monster`, `Kämpft`, `Pausiert`, `Notstopp`) alongside separate telemetry labels for visible mob count, target status, and player vitals.
- [ ] Given the bot is in standby/paused mode, when the user clicks "Starten", the application focuses the Flyff game window and starts farming immediately without artificial countdown delays once foregrounded; if foreground focus cannot be acquired, the bot transitions to paused and visibly reflects the focus state.
- [ ] Given the emergency stop (Escape key or button), when triggered, input dispatching ceases immediately, navigation data is saved, and status reflects `Notstopp` while read-only perception remains accessible.
- [ ] All user-visible text is available and synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Process injection, memory tampering, or background window input dispatching.
- Auto-relaunching the game client if crashed.
- Modifying combat skill rotations or navigation map formats.

## Verification

- Automated:
  - Unit tests in `tests/test_orchestrator.py` verifying perception ticks execute and publish dashboard updates during `PAUSED` mode without invoking input dispatchers.
  - UI tests in `tests/test_main_window.py` verifying status badge separation from mob count and correct status transitions.
- Manual (Windows):
  - Launch application while Flyff is running, toggle "Debug-Overlay anzeigen" and "Platzierungshilfen", and verify live bounding boxes and vitals update while paused.
  - Click "Starten" and verify Flyff gains focus and farming automation begins immediately.
  - Minimize Flyff and verify status notification reflects the window state.
