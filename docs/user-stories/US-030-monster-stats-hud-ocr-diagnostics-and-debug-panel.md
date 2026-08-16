---
id: US-030
title: Monster stats HUD OCR diagnostics and debug dashboard panel
status: draft
created: 2026-08-17
updated: 2026-08-17
---

# US-030: Monster stats HUD OCR diagnostics and debug dashboard panel

## Story

As a **player monitoring autonomous farming and monster kill statistics**,
I want **a dedicated Monster Stats Debug panel and checkbox toggle in the dashboard displaying live OCR readouts, anchor match scores, and parsed kill counts**,
so that **I can visually inspect and diagnose the monster kill counter extraction in real time across different HUD positions and window resolutions**.

## Context and assumptions

- `MonsterStatsReader` (`src/flyff_bot/features/vision/monster_stats.py`) performs template-anchored ROI extraction and OCR on the in-game "Monster Kills:" session stats HUD window.
- In `PerceptionPipeline`, `monster_stats_reader` updates `monster_kill_count` in `WorldState`, but the dashboard currently only renders the integer count without diagnostic details.
- Unlike target verification (which has `Zielverifizierungs-Debug` / `US-024`), there is currently no live diagnostic panel showing:
  - Header anchor match score and threshold (`score / threshold`, `BESTANDEN` / `FEHLGESCHLAGEN`).
  - Extracted ROI pixel dimensions and status.
  - Raw OCR text recognized from the HUD.
  - Parsed kill count integer.
  - Feed health / failure status (`OK`, `Anker nicht gefunden`, `OCR fehlgeschlagen`).
- Adding a dedicated group box toggle (**"Monster-Stats-Debug"** / **"Monster Stats Debug"**) under *Diagnose / Ansichten* provides direct visual verification of the OCR pipeline.
- Links:
  - [Architecture](file:///i:/coding%20projects/flyff_bot/docs/wiki/architecture.md)
  - [US-005: Loot log OCR](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-005-loot-log-ocr.md)
  - [US-023: Reliable combat targeting and kill verification](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-023-reliable-combat-targeting-and-kill-verification.md)
  - [US-024: Target verification debug dashboard visualization](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-024-target-verification-debug-dashboard-visualization.md)
  - [US-026: Static HUD anchoring and field hardening](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md)

## Acceptance criteria

- [ ] Given `MonsterStatsReader`, structured diagnostic metrics (`anchor_score`, `anchor_threshold`, `anchor_passed`, `raw_text`, `parsed_count`, `status`) are measured and exposed on every frame tick.
- [ ] Given the desktop UI (`MainWindow`), a dedicated checkbox toggle (**"Monster-Stats-Debug"** / **"Monster Stats Debug"**) is available under the *Diagnose / Ansichten* section.
- [ ] Given the toggle is checked, a `Monster-Stats-Debug` group box is displayed in the dashboard showing:
  - Header anchor match score vs threshold with a Pass/Fail badge.
  - Parsed monster kill count.
  - Raw OCR text recognized from the ROI.
  - Feed status message (e.g. OK, Anchor not found, OCR error).
- [ ] Given the toggle is unchecked, the group box is hidden and the window shrinks smoothly to fit remaining contents.
- [ ] All user-visible labels, values, statuses, and tooltips are synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Modifying Tesseract OCR engine internals or generating custom font datasets.
- Automatic movement or resizing of the in-game HUD stats window.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_monster_stats.py` verifying diagnostic metric emission.
  - UI tests in `tests/unit/test_ui.py` verifying toggle behavior, widget rendering, and metric updates.
- Manual (Windows):
  - Launch the UI, toggle "Monster-Stats-Debug", open the stats HUD in Flyff, and verify live anchor score, raw text, and kill count update in real time.
