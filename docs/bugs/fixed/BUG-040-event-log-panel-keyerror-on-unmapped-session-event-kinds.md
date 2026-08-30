---
id: BUG-040
title: EventLogPanel crashes with KeyError on unmapped SessionEventKind events
status: resolved
severity: high
created: 2026-08-30
updated: 2026-08-30
---

# BUG-040: EventLogPanel crashes with KeyError on unmapped SessionEventKind events

## Environment

- Windows version: Windows 11 Pro 26200
- Python version: 3.14.7 (`.python-version`)
- Application revision: `main` (`9e12353`)
- Client/server version: Entropia Flyff PServer (`neuz.exe`)

## Reproduction

1. Launch the application desktop dashboard (`MainWindow`).
2. Run a session where the orchestrator or diagnostics subsystem emits an event whose `kind` is `TICK_FAULT`, `BUDGET_EXHAUSTED`, `AUTOPILOT_ARMED`, `AUTOPILOT_DISARMED`, `AUTOPILOT_GOAL`, `PLAYER_DEATH`, or `RECOVERY_RESUMED`.
3. The periodic dashboard update timer invokes `MainWindow.update_dashboard()` -> `MainWindow._render_update()` -> `EventLogPanel.set_events()`.
4. `EventLogPanel.set_events()` calls `_summary(event)` which executes `kind=self._translator.text(_KIND_MESSAGES[event.kind])`.
5. Python raises `KeyError: <SessionEventKind.TICK_FAULT: 'tick_fault'>` (or `BUDGET_EXHAUSTED`, etc.), aborting the dashboard update loop on every timer tick.

## Expected behavior

- `EventLogPanel` defines complete mappings for all declared `SessionEventKind` variants in `_KIND_MESSAGES` and `_KIND_BADGE_COLORS`.
- All `SessionEventKind` messages are fully translated with synchronized English (`en.json`) and German (`de.json`) locale definitions.
- `EventLogPanel` provides a safe fallback (e.g. falling back to `event.kind.value` / neutral badge color) so that any future or unrecognized event kind cannot crash the UI or freeze dashboard rendering.
- Automated tests verify exhaustive mapping between `SessionEventKind` and UI panel dictionaries.

## Actual behavior

- `SessionEventKind` in `src/flyff_bot/features/diagnostics/models.py` defines 15 event kinds, but `_KIND_MESSAGES` and `_KIND_BADGE_COLORS` in `src/flyff_bot/ui/event_log_panel.py` only contain entries for 8 kinds.
- The 7 missing kinds (`TICK_FAULT`, `AUTOPILOT_ARMED`, `AUTOPILOT_DISARMED`, `AUTOPILOT_GOAL`, `PLAYER_DEATH`, `RECOVERY_RESUMED`, `BUDGET_EXHAUSTED`) result in immediate `KeyError` exceptions when accessed via `_KIND_MESSAGES[event.kind]` and `_KIND_BADGE_COLORS[event.kind]`.
- Because `MainWindow.update_dashboard` runs repeatedly on a timer, this exception is thrown on every tick, flooding the console with tracebacks and preventing all dashboard UI panels from updating.

## Impact and frequency

- Impact: High. Freezes the dashboard update loop and prevents real-time diagnostic rendering whenever any unmapped session event is emitted.
- Frequency: 100% deterministic whenever any of the 7 unmapped event kinds is emitted into the session event log.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
- [x] The check passes after the fix.
- [x] Related documentation is current.
