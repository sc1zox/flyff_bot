---
id: US-026
title: Static HUD anchoring and field hardening for vitals and monster stats
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-026: Static HUD anchoring and field hardening for vitals and monster stats

## Story

As a **bot operator running the game at various resolutions (e.g. 1080p, 1440p, 4K)**, I want **the player vitals gauge extraction to use resolution-independent fixed top-left pixel anchoring, the monster stats reader to reliably locate the HUD window via template matching, and a "Placements" visual guide toggle in the UI that draws expected ROI overlay boxes over the game window**, so that **vital gauges (HP/MP/FP) are read with zero false drops across any screen resolution, and operators can easily align and verify in-game HUD elements against the bot's expected detection areas**.

## Context and assumptions

- In Flyff (both Flyff Universe and v15+ clients), the player character's vital gauge HUD element (the HP/MP/FP orb) is anchored at the exact top-left corner `(0,0)` of the client window and renders with fixed pixel dimensions (reference ~`260x113` pixels), rather than scaling dynamically with window width and height.
- [US-017](completed/US-017-player-vitals-perception-and-threshold-triggers.md) previously applied relative normalized percentages (`hud_right = 0.25`, `hud_bottom = 0.20`). As documented in [BUG-006](../bugs/BUG-006-player-vitals-resolution-scaling-and-flicker-spam.md), on standard resolutions such as 1920x1080, this extracted a 480x216 region and sampled dynamic 3D game scenery, causing gauge values to falsely drop to 0% and triggering endless consumable spam.
- Switching `PlayerVitalsReader` to fixed top-left pixel bounding (`0..260` width, `0..113` height from `(0,0)` across all frame resolutions $\ge 260\times 113$) solves resolution drift cleanly without introducing unnecessary template matching overhead on every frame.
- [US-023](completed/US-023-reliable-combat-targeting-and-kill-verification.md) introduced `MonsterStatsReader` with normalized screen coordinates calibrated against a single 1600x900 window. If an operator moves the in-game session stats HUD window or runs at a different resolution, OCR sampling fails.
- Hardening `MonsterStatsReader` with a lightweight template-match anchor for the session stats window header (similar to `TargetVerifier`'s header anchor pattern) dynamically and reliably extracts the exact relative text sub-ROI (`Monster Kills: <int>`) wherever the window is placed on screen.
- To eliminate any guesswork regarding HUD placement and screen scaling, the desktop UI provides a dedicated **"Placements" ("Platzierungshilfen")** toggle button. When enabled, the live preview overlay renders color-coded, labeled bounding boxes over the captured game frame showing exactly where each vision/OCR component expects HUD elements (Vitals orb, Stats window, Target bar).
- All user-facing strings, debug overlay guides, and error messages must remain synchronized in German and English (`de.json` and `en.json`).

## Acceptance criteria

- [ ] **Resolution-independent static player vitals anchoring (fixes BUG-006):**
  - Given any client frame resolution (1024x768, 1280x720, 1920x1080, 2560x1440, etc.), `PlayerVitalsReader` extracts the top-left HUD orb from fixed pixel dimensions (`0..260` width, `0..113` height) rather than normalized fractions of the total window width/height.
  - Gauge bar column-sampling (HP in Red, MP in Blue, FP in Green) operates strictly on the fixed-pixel HUD crop.
  - When player vitals are full in high-resolution frames, HP/MP/FP read stably at ~100.0% with zero false 0.0% dips and zero unwanted consumable key dispatches.
- [ ] **Template-matched anchoring for monster stats HUD window:**
  - `MonsterStatsReader` searches the captured client frame for a session stats header template (or anchor icon) using normalized correlation (`cv2.matchTemplate`).
  - When the stats window header anchor is found above the configured threshold (default $\ge 0.85$), the relative `Monster Kills:` text region is cropped relative to the anchor's matched position and parsed via OCR.
  - When the stats window is closed or not present on screen, `MonsterStatsReader.read()` returns `None` gracefully without throwing exceptions or blocking the pipeline.
- [ ] **UI "Placements" visual guide toggle & ROI calibration overlay:**
  - The desktop UI provides a prominent **"Placements" ("Platzierungshilfen")** toggle button in the diagnostics/overlay controls.
  - When toggled ON, the visual preview overlay renders distinct, color-coded, and labeled bounding boxes over the game frame:
    - *Player Vitals:* Top-left dashed box (`260x113` px) with internal HP/MP/FP gauge scan bars.
    - *Monster Stats OCR:* Highlighted search zone or matched window bounding box showing the exact `Monster Kills:` text extraction ROI.
    - *Target Header:* Top-center target bar and name-match verification region.
  - These placement guide boxes automatically scale proportionally with the live viewport preview, allowing operators to visually align their in-game windows with 100% precision.
- [ ] **Safety, localization, and error handling:**
  - Frames smaller than `260x113` handle boundary clipping gracefully without index errors.
  - All user-visible labels, tooltips, and status texts are synchronized in German and English.
- [ ] **Automated verification:**
  - Automated unit tests in `tests/unit/test_vitals.py`, `tests/unit/test_monster_stats.py`, and `tests/unit/test_ui.py` verify static vitals extraction across multiple simulated resolution fixtures (720p, 1080p, 1440p), template-anchored stats window detection, and placement guide rendering.
  - `./scripts/check.ps1` (ruff, mypy, pytest) passes cleanly.

## Out of scope

- Dynamic HUD resizing or custom UI skins modifying the internal pixel layout of the Flyff top-left orb.
- OCR parsing of other stats in the session window (e.g. Exp gained, Penya earned).

## Verification

- Automated:
  - `uv run pytest tests/unit/test_vitals.py tests/unit/test_monster_stats.py tests/unit/test_ui.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui` with the game running at 1920x1080.
  2. Toggle the **"Placements"** button; verify clearly visible guide boxes overlaying the top-left vitals orb and monster stats regions.
  3. Verify top-left vitals read accurate ~100% values and do not trigger food/potions at full health.
  4. Move the in-game monster stats window and verify the placement guide and OCR dynamically follow the window anchor.
