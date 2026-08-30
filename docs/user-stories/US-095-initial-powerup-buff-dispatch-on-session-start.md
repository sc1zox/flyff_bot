---
id: US-095
title: Initial Power-Up and Buff Dispatch on Session Start
status: draft
created: 2026-08-30
updated: 2026-08-30
---

# US-095: Initial Power-Up and Buff Dispatch on Session Start

## Story

As an **operator starting an automated farming session**, I want **all enabled power-up and buff hotkeys to be dispatched immediately upon session start (with inter-key stagger delays)**, so that **character buffs, scrolls, and food items are active right from the beginning of farming without waiting for a full initial interval to elapse**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Under [US-016](completed/US-016-auto-power-ups-and-timed-hotkeys.md), `PowerUpScheduler` initializes each entry's elapsed time at `0.0`, requiring a full interval to elapse (e.g. 10800s / 3h for World Buffs or 300s for scrolls) before the first keystroke is sent.
- When an operator launches or restarts an automated farming session, the character typically lacks active buffs or consumables, requiring manual casting before starting the bot.
- Initial power-up dispatch must strictly preserve existing safety boundaries:
  - The Flyff game client window must be foregrounded (`is_foreground`).
  - Emergency stop (`F12`) must be respected (`is_aborted`).
  - Concurrently due keystrokes must be dispatched sequentially with the configured stagger delay (`stagger_seconds`, default 30 ms) to avoid input collisions.
- Pausing and resuming a session must not re-trigger initial buffs unless a session reset has occurred or the timer has actually expired.
- UI tooltips and descriptions in German and English must reflect that power-up hotkeys trigger on session start and recur periodically.

## Acceptance criteria

- [ ] Given configured enabled power-up entries, when a farming session is started from an idle/reset state, then all enabled power-up hotkeys are flagged as due immediately and dispatched sequentially honoring the stagger delay once the client window is foregrounded.
- [ ] Given a session is paused and resumed without a session reset, when resuming, then elapsed timers continue from their pre-pause countdown rather than re-dispatching start buffs.
- [ ] Given an emergency stop (`F12`) or loss of game window focus during initial buff dispatch, when triggered, dispatching immediately halts and resumes safely when focus is regained or abort is cleared.
- [ ] Given a session reset or power-up reconfiguration (`reset_powerups`), when triggered, elapsed times are re-initialized so the initial dispatch fires on the next session start.
- [ ] All user-visible strings, tooltips, and documentation in German and English (`de.json`, `en.json`) are updated and kept synchronized.
- [ ] Automated unit tests in `tests/unit/test_powerups.py` verify that `PowerUpScheduler` fires enabled entries immediately on initial start step, respects staggering, and preserves countdowns across pause/resume.

## Out of scope

- OCR or vision-based detection of buff icons or remaining buff duration in the game HUD.
- Dynamic re-buffing triggered by character death or response (buffs remain interval-driven).

## Verification

- Automated:
  ```powershell
  uv run pytest tests/unit/test_powerups.py tests/unit/test_orchestrator.py
  uv run ruff check .
  uv run mypy
  ```
- Manual (Windows):
  1. Open dashboard, configure a power-up (e.g. hotkey `1` with 300s interval).
  2. Focus game client and click "Start" (or start autopilot); verify key `1` is dispatched immediately upon start.
  3. Verify that after the initial dispatch, the next key press occurs after the 300s interval.
