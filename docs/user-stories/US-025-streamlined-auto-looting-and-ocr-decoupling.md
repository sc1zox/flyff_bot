---
id: US-025
title: Streamlined auto-looting and loot-log OCR decoupling
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-025: Streamlined auto-looting and loot-log OCR decoupling

## Story

As a **bot operator**, I want **the farming loop to seamlessly transition directly to searching for new targets upon monster defeat without pausing for key-press pickup routines or blocking on loot-log OCR recognition**, so that **the bot farms fluidly with active in-game loot pets, eliminates unnecessary CPU overhead and fragile Tesseract subprocess calls, and avoids drop-recognition timeouts**.

## Context and assumptions

- In Flyff (both Flyff Universe and v15+), players farming efficiently utilize active in-game Pick-up Pets (Loot Pets) which automatically pick up dropped penya and items immediately upon mob death without requiring player keypresses.
- [US-005](completed/US-005-loot-log-ocr.md) and [US-009](completed/US-009-reactive-loot-controller.md) originally introduced a central `LootLogReader` utilizing local Tesseract OCR subprocesses and a `LootController` that pressed a hardcoded `F` key and blocked in `LootMode.WAITING` for up to 2.0 seconds.
- In practice, in-game notification text disappears rapidly, is obscured by battle effects/transparency, and often fails OCR recognition, causing the bot to stall for the full 2.0s timeout after every mob kill before resuming search.
- Running Tesseract OCR on every frame or perception tick consumes substantial CPU and disk I/O (writing temporary PNG files to disk) and fails silently when Tesseract is not installed on the host system.
- In [US-023](completed/US-023-reliable-combat-targeting-and-kill-verification.md), ground-truth kill tracking via `MonsterStatsReader` was established. Session progress and goals are better served by kill counts rather than fragile OCR-parsed item drop accounting.
- Decoupling `LootLogReader` from the mandatory `PerceptionPipeline` and updating `FarmingOrchestrator` to transition smoothly from `TARGET_DEAD` directly to `SEARCHING` ensures reliable, fast combat cycles.
- Code referencing `LootFeed` in `PerceptionPipeline` should make OCR optional or default-disabled without breaking backward-compatible interface contracts where mocked in unit tests.

## Acceptance criteria

- [ ] **Direct combat-to-search transition (Auto-Looting):**
  - Given a monster is defeated (`CombatMode.TARGET_DEAD`), when the orchestrator processes the combat outcome, then the bot transitions directly into the search/targeting cycle (`SEARCHING` or `TARGETING` if candidates are already in view) without blocking in a 2.0-second pickup wait loop.
  - Given a defeated mob, no redundant `F` keypresses or pickup actions are dispatched to the game client when auto-looting via loot-pet is assumed.
- [ ] **Loot-Log OCR decoupling from default perception pipeline:**
  - Given the standard perception pipeline running during farming, `LootLogReader` and Tesseract OCR sub-processes are not invoked on every capture tick, eliminating disk I/O and CPU overhead.
  - `PerceptionPipeline` gracefully operates without an active `LootFeed` (or with a no-op feed by default), ensuring `tick()` does not raise OCR failures or spawn external processes.
- [ ] **Farming goals and progress decoupling:**
  - Given session progress tracking, progress metrics and session completion are driven by mob kill verification ([US-023](completed/US-023-reliable-combat-targeting-and-kill-verification.md)) rather than OCR inventory parsing.
  - Existing `WorldState` snapshot structures remain typed and backwards compatible (`recent_loot` and `inventory` default to empty tuples when no OCR feed is attached).
- [ ] **Safety boundaries and state consistency:**
  - Emergency stop (`END` / `Escape`) and window focus checks continue to be enforced before and during transitions.
  - Navigation pathing and spatial map dead-reckoning continue uninterrupted across mob kill transitions.
- [ ] **Localization and UI consistency:**
  - Any dashboard status displays reflect streamlined states (`SEARCHING`, `TARGETING`, `COMBAT`) without lingering in deprecated waiting states.
  - User-facing text in `de.json` and `en.json` remains synchronized and free of orphaned loot-OCR error notices.
- [ ] **Automated verification:**
  - Automated unit tests in `tests/unit/` verify the decoupled perception pipeline, direct `FarmingOrchestrator` kill-to-search transition, and elimination of the blocking 2.0s loot wait.
  - `./scripts/check.ps1` (ruff, mypy, pytest) passes cleanly.

## Out of scope

- Inventory bag OCR or visual grid analysis of in-game inventory slots.
- Complex inventory fullness detection or vendor selling routines.
- In-game loot pet feeding or pet buff automation.

## Verification

- Automated:
  - `uv run pytest tests/unit/test_perception_pipeline.py tests/unit/test_orchestrator.py tests/unit/test_loot_controller.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. Start farming with an active in-game loot pet.
  3. Slay a monster; verify the bot immediately transitions to searching/engaging the next mob without pausing for 2 seconds or pressing `F`.
  4. Verify no Tesseract errors or CPU spikes occur during farming.
