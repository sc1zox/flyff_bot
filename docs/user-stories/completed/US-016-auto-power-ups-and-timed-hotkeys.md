---
id: US-016
title: Auto power-ups and timed hotkeys with dynamic UI configuration and persistence
status: completed
created: 2026-08-15
updated: 2026-08-17
---

# US-016: Auto power-ups and timed hotkeys with dynamic UI configuration and persistence

## Story

As a player using the desktop dashboard, I want to define and manage a dynamic list of timed power-up hotkeys with configurable intervals and persistent storage, so that character buffs, food, scrolls, and periodic utility items are automatically refreshed during farming sessions without manual intervention.

## Context and assumptions

- Depends on [US-010](completed/US-010-pyside6-dashboard-and-overlay.md) (PySide6 Dashboard), [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`), and [US-014](US-014-configurable-ui-attack-key.md) (Configurable Key Inputs).
- In Flyff, players frequently activate timed consumables (e.g., Grilled Eel, Upcut Stone, Bull Hams) and self-buff skills mapped to action slots (`F1`–`F12`, `0`–`9`, `A`–`Z`) that expire after a set duration (e.g. 180s, 300s, 3600s).
- The dashboard UI requires a dynamic table or list where users can add, edit, and remove power-up items with individual hotkeys, intervals (in seconds), enabled flags, and optional descriptive labels.
- Key timers begin countdown upon bot start and dispatch their keystroke after the full interval has elapsed (first trigger after interval, then recurring).
- Timed hotkeys trigger whenever due during active bot execution; if multiple timers expire simultaneously, actions are queued and executed with a small stagger delay (default 30 ms) to avoid input collisions.
- Safety boundaries are strictly preserved: keystrokes are only dispatched if the Flyff client window is currently foregrounded and the emergency stop is not active.
- Configured power-up entries are saved persistently (e.g. JSON configuration or Qt settings) and reloaded automatically across application launches.
- All user-visible strings (labels, table headers, buttons, error messages) must be localized in German and English.

## Acceptance criteria

- [x] Dashboard UI provides a dynamic power-up / timed hotkey management section allowing users to add (`+`) and remove (`-`) arbitrary rows.
- [x] Each entry allows configuring:
  - Optional descriptive name/label (e.g. "Grilled Eel", "Haste")
  - Hotkey (supporting key capture / all valid keys: `F1`–`F12`, `0`–`9`, `A`–`Z`, `Space`)
  - Interval in seconds (positive integer)
  - Enabled checkbox (to toggle individual buffs on/off without deleting them)
- [x] Power-up entries are automatically persisted to disk and restored upon application restart.
- [x] When the bot/farming session is started, active power-up timers start and dispatch their keystroke after their configured interval has elapsed, recurring periodically.
- [x] When multiple timed hotkeys become ready concurrently, they are dispatched sequentially with a 30 ms stagger delay.
- [x] Keystrokes are only dispatched if the game window is foregrounded and the emergency stop is inactive; if focus is lost, triggers are held until focus returns or skipped safely.
- [x] Pausing or stopping the bot halts interval timers; resuming continues or resets timers cleanly.
- [x] All user-facing UI labels, tooltips, and status texts are fully synchronized in German and English (`de.json` and `en.json`).
- [x] Automated unit tests in `tests/unit/` verify the timed action scheduler, concurrent queue stagger logic, persistence serialization/deserialization, and UI component behavior.

## Implementation notes

- The hotkey column is a combo box covering every valid key (`F1`–`F12`, `0`–`9`, `A`–`Z`, `Space`)
  rather than a physical key-capture button. The acceptance criterion allows either, and a fixed
  list cannot record an unsupported key that then has to be rejected.
- The 30 ms stagger is a *minimum* gap, not the observed spacing. `FarmingOrchestrator` dispatches at
  most one power-up per tick and its tick interval is 100 ms, so concurrently due buffs actually land
  about 100 ms apart. Blocking inside `tick()` to hit a true 30 ms gap was rejected: the Qt timer
  drives it on the GUI thread, so sleeping there would violate the UI-thread isolation rule.
- Timers accumulate only the session time the orchestrator actually steps, so pausing, losing focus,
  completing a goal, or emergency-stopping freezes each countdown where it stood and resuming
  continues from there. A due keystroke is consumed only after the dispatcher confirms it passed the
  foreground and END guards, so a trigger during lost focus is held rather than silently skipped.
- Editing a row preserves the countdowns of every entry whose key and interval are unchanged, so
  renaming one buff cannot restart a 3600 s timer. The name field publishes on `editingFinished`
  rather than per keystroke to avoid one disk write per typed character.
- An empty entry list is a valid stored state; deleting every row does not restore defaults on the
  next launch.
- Preserved countdowns are keyed by row position, because a row has no identity that survives into
  `PowerUpConfig`. Deleting a row mid-session therefore shifts the rows below it up one position and
  they inherit the deleted row's countdown, which can make the next buff fire early once. Removing a
  row is an explicit operator action and the worst case is a single early press, so this is accepted
  rather than fixed with a per-row identifier.

## Out of scope

- OCR / vision-based detection of buff icons or remaining buff duration in the game UI.
- Dynamic re-buffing triggered by character death or respawn detection (buffs are strictly interval-based).
- Multi-step macro sequences per slot with complex internal sub-delays.

## Verification

- Automated: Unit tests in `tests/unit/test_powerups.py` (or scheduler/persistence tests) and `tests/unit/test_ui.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. In the power-ups section, add two entries (e.g., `F4` at 5s, `F5` at 10s).
  3. Start the bot with Flyff window active; verify `F4` is pressed after 5s and `F5` after 10s with proper focus and no input jamming.
  4. Restart UI; verify that configured entries and settings persist.
