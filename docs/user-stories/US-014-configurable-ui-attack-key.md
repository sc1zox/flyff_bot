---
id: US-014
title: Configurable attack key in UI with key capture and F3 default
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-014: Configurable attack key in UI with key capture and F3 default

## Story

As a player using the desktop dashboard, I want to configure the attack key directly in the UI (with key-press recording and a default of `F3`), so that the bot can trigger the desired action slot or skill with a single key command after targeting and seamlessly transition to defeat monitoring and looting.

## Context and assumptions

- Depends on [US-010](completed/US-010-pyside6-dashboard-and-overlay.md) (PySide6 Dashboard), [US-008](completed/US-008-reactive-combat-controller.md) (`CombatController`), and [US-013](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) (`FarmingOrchestrator`).
- In Flyff, players often map combat macros or primary skills to function keys (`F1`–`F12`) or number keys (`1`–`9`, `0`), which when pressed once on a selected target initiate an automated attack sequence.
- Currently, `CombatController.KeyBinding` restricts virtual keys to `1`–`9`, `C`, and `Space`. This must be extended to support `F1`–`F12` (`0x70`–`0x7B`) and other supported single-character/macro keys parsed by `parse_virtual_key`.
- The dashboard UI needs an interactive key-selection control that displays the current attack key and allows the user to click and press any valid key to set it, defaulting to `F3`.

## Acceptance criteria

- [ ] `CombatController` and `KeyBinding` accept function keys (`VK_F1`–`VK_F12`), number keys (`0`–`9`), `Space`, and alpha keys (`A`–`Z`).
- [ ] Desktop dashboard UI ([`MainWindow`](../../src/flyff_bot/ui/main_window.py)) includes an attack key configuration control that defaults to `F3`.
- [ ] The key configuration control allows pressing a physical keyboard key to automatically detect and assign the attack key (e.g. `F3`, `F1`, `1`, `Space`).
- [ ] When farming is started from the UI, `FarmingOrchestrator` uses the configured attack key for target engagements.
- [ ] After targeting a valid mob, the configured attack key is dispatched to initiate combat, followed by monitoring for target defeat (`hp_pixel_count == 0` or target loss) and loot OCR confirmation before transitioning to the next mob.
- [ ] The CLI `--farm` / `--auto` and `--rotation-key` options also support function keys (e.g. `--rotation-key F3`).
- [ ] All user-visible UI labels, tooltips, and log messages are fully synchronized in German and English (`de.json` and `en.json`).
- [ ] Automated unit tests in `tests/unit/` verify function key validation, UI key recording, orchestrator combat dispatch, and error handling.

## Out of scope

- Complex multi-key macro sequences requiring customized timing delays between sub-skills in the UI.
- Mouse button remapping (e.g. right-click attack).

## Verification

- Automated: Unit tests in `tests/unit/test_combat_controller.py`, `tests/unit/test_ui.py`, and `tests/unit/test_keymap.py`; `./scripts/check.ps1`.
- Manual (Windows): Launch `uv run python -m flyff_bot ui`, press the key configuration button, press `F3` (or `F1`), click "Starten", and verify that the bot focuses the client, targets a mob, and sends the configured key.
