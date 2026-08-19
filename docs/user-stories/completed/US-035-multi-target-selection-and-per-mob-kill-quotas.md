---
id: US-035
title: Multi-target monster selection and per-mob kill quotas
status: completed
created: 2026-08-18
updated: 2026-08-19
---

# US-035: Multi-target monster selection and per-mob kill quotas

## Story

As a **bot operator farming quest mobs or specific materials**, I want **to select multiple target monster types in the UI, assign individual kill quotas per type, track kills internally in a database, dynamically ignore completed types, and optionally close the client upon reaching all goals**, so that **I can automate multi-monster farming sessions reliably without manual supervision or over-farming completed objectives**.

## Context and assumptions

- [Architecture](../../wiki/architecture.md) (US-003, US-004, US-008, US-013, US-019, US-023, US-032, US-034).
- `OpenCVDnnYoloDetector` and `CombatController` already support filtering by `allowed_class_names` (`frozenset[str]`), but `MainWindow` previously loaded all labels statically from `labels.txt` with no interactive UI selection.
- The Flyff client's Monster-Stats HUD provides only a single global kill count ([US-030](US-030-monster-stats-hud-ocr-diagnostics-and-debug-panel.md), [US-034](US-034-background-independent-monster-stats-kill-confirmation.md)), without breaking down kills by monster class.
- When an engaged target is killed (confirmed via target HP drop to 0, target loss after damage dealt, or Monster-Stats HUD counter increment), the bot knows the exact mob class of the engaged candidate and can attribute the kill to that specific monster type.
- Per-mob quotas and historical session statistics are recorded in a lightweight local database (SQLite) or structured session storage to maintain progress across pauses or reconnects.
- Once a monster type reaches its configured quota, it is removed from the active targeting whitelist in real-time, allowing the bot to focus strictly on remaining incomplete mob types.
- Once all configured quotas are satisfied, the session enters `FarmingMode.COMPLETED`, disengages input, and optionally closes the target game client window via standard Win32 `WM_CLOSE` messaging.

## Acceptance criteria

- [x] **Interactive Multi-Mob Selection UI:**
  - The dashboard presents a monster selection panel populated dynamically with all classes detected from the active YOLO model/labels.
  - Each monster type features an activation toggle/checkbox and an optional integer input field for the target kill quota (e.g. `0` or blank = unlimited farming).
  - Implementation note: this panel replaces the single-select target-monster dropdown from
    [US-038](US-038-target-mob-dropdown-and-early-yolo-filtering.md). Two controls writing
    the same targeting whitelist would contradict each other; no monster activated means every
    detected monster stays eligible, which preserves the previous default.
- [x] **Internal Per-Mob Kill Tracking & Persistence:**
  - Kills are tracked individually per monster class upon verified combat completion.
  - Kill events and session progress are stored in a local SQLite database / session store (recording timestamp, monster class name, and session ID).
- [x] **Live UI Progress Indicators:**
  - The dashboard displays live progress counters per active monster type (e.g. `Mushpoie: 14 / 20`, `Lawolf: 5 / 30`).
- [x] **Dynamic Target Quota Enforcement:**
  - As soon as the kill count for a specific monster type reaches its quota, that class is automatically removed from active candidate targeting and target name verification.
  - Combat and search controllers bypass completed monster types and prioritize visible mobs belonging to unfinished quotas.
- [x] **Session Completion & Client Shutdown:**
  - When all configured monster quotas are achieved, the farming orchestrator transitions to `FarmingMode.COMPLETED`.
  - If the optional "Close client upon completion" setting is enabled, the bot safely posts a `WM_CLOSE` message to the game client window.
- [x] **Localization:**
  - All new UI labels, tooltips, and status readouts are synchronized in German (`de.json`) and English (`en.json`).
- [x] **Verification:**
  - Unit tests verify per-mob kill attribution, quota completion state transitions, dynamic whitelist filtering, and database persistence.
  - `./scripts/check.ps1` passes cleanly without lint or type errors.

## Out of scope

- OCR parsing of quest dialogue windows or in-game quest log text.
- Spawning new game client instances or automated character re-logging.

## Verification

- Automated:
  - `uv run pytest tests/unit/test_multi_target_goals.py tests/unit/test_combat_controller.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  - Configure quotas for two distinct monster types in the dashboard (e.g. 2x Mob A, 3x Mob B).
  - Verify the bot kills 2x Mob A, then ignores Mob A and hunts only Mob B until reaching 3x Mob B, then concludes the session.
