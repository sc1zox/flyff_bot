---
id: US-016
title: Auto power-ups and timed hotkeys with dynamic UI configuration and persistence
status: draft
created: 2026-08-15
updated: 2026-08-15
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

- [ ] Dashboard UI provides a dynamic power-up / timed hotkey management section allowing users to add (`+`) and remove (`-`) arbitrary rows.
- [ ] Each entry allows configuring:
  - Optional descriptive name/label (e.g. "Grilled Eel", "Haste")
  - Hotkey (supporting key capture / all valid keys: `F1`–`F12`, `0`–`9`, `A`–`Z`, `Space`)
  - Interval in seconds (positive integer)
  - Enabled checkbox (to toggle individual buffs on/off without deleting them)
- [ ] Power-up entries are automatically persisted to disk and restored upon application restart.
- [ ] When the bot/farming session is started, active power-up timers start and dispatch their keystroke after their configured interval has elapsed, recurring periodically.
- [ ] When multiple timed hotkeys become ready concurrently, they are dispatched sequentially with a 30 ms stagger delay.
- [ ] Keystrokes are only dispatched if the game window is foregrounded and the emergency stop is inactive; if focus is lost, triggers are held until focus returns or skipped safely.
- [ ] Pausing or stopping the bot halts interval timers; resuming continues or resets timers cleanly.
- [ ] All user-facing UI labels, tooltips, and status texts are fully synchronized in German and English (`de.json` and `en.json`).
- [ ] Automated unit tests in `tests/unit/` verify the timed action scheduler, concurrent queue stagger logic, persistence serialization/deserialization, and UI component behavior.

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
