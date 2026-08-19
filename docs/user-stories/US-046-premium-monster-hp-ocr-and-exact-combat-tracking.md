---
id: US-046
title: Toggleable Premium monster HP OCR extraction and exact combat progress tracking
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-046: Toggleable Premium monster HP OCR extraction and exact combat progress tracking

## Story

As a **bot operator with an active Premium account on Entropia Flyff**, I want **the application to provide a toggleable feature that OCR-extracts exact numeric monster health values (`Health: Current / Max` and percentage) from the target header, feeding exact HP values into combat tracking and kill verification**, so that **the bot measures damage on every single hit with mathematical precision, confirms kills without relying on visual pixel-gauge thresholds, and falls back gracefully to standard gauge-bar measurements when Premium is disabled**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Previous work:
  - [US-004](completed/US-004-target-mob-verification.md), [US-012](completed/US-012-real-world-vision-refactoring.md), and [US-029](completed/US-029-configurable-target-verification-thresholds.md) established template-matched target header anchoring and red pixel-column fill measurement for standard HP bars.
  - [US-023](completed/US-023-reliable-combat-targeting-and-kill-verification.md) and [US-034](completed/US-034-background-independent-monster-stats-kill-confirmation.md) established combat engagement tracking and OCR kill verification.
- Premium HUD differences:
  - On Entropia Flyff, characters with active **Premium** status have exact numeric monster health rendered inside the target header (e.g. `Health: 888,888,888 / 888,888,888` and/or exact percentage numbers).
  - Characters without Premium only see the standard red graphical gauge bar without numeric health text.
- Because player accounts vary, this capability must be **strictly toggleable** in the dashboard UI and configuration (`premium_monster_hp_enabled: bool`, default: `false`).
- Extraction mechanism:
  - The target header region already matches the anchor template (`target_anchor.png`).
  - Below the monster nameplate and header icon, a dedicated text sub-ROI contains the white/yellow numeric health string.
  - Using color-range thresholding (similar to [US-032](completed/US-032-tesseract-ocr-target-name-verification.md) and [US-034](completed/US-034-background-independent-monster-stats-kill-confirmation.md)), text glyphs are isolated from the background and OCR-parsed via `TesseractTextRecognizer`.
  - The parsed values are normalized into `current_hp: int`, `max_hp: int`, and `hp_percentage: float = (current_hp / max_hp) * 100.0`.
- Combat integration:
  - When Premium HP OCR is active and successfully parsing values, `TargetVerificationMetrics` and `SelectedTarget.hp_percentage` use the exact mathematical percentage.
  - `CombatController` detects damage whenever `current_hp` decreases, tracks exact damage dealt per rotation, and confirms a kill when `current_hp == 0` or upon target clearance after `hp_percentage <= 5.0%`.
- Fallback & resilience:
  - If the toggle is disabled, or if OCR encounters unreadable text (e.g. occluding skill animations or transient redraws), the system seamlessly falls back to the existing pixel-gauge percentage without interrupting combat.
- All operations adhere strictly to project safety boundaries: pure vision / OCR perception; no game memory reading or injection.

## Acceptance criteria

- [ ] **Configurable Premium HP Toggle & Persistence:**
  - The desktop UI (Combat / Target Settings panel) features a toggle/checkbox: *"Premium Monster-HP OCR"* / *"Premium Monster HP OCR"* (`premium_monster_hp_enabled: bool`, default: `false`).
  - The setting is persisted across sessions in configuration storage.
- [ ] **Target Header Numeric Health OCR Reader:**
  - A dedicated parser function (`extract_premium_target_hp`) crops the anchored health text ROI from the target header.
  - Applies color masking to isolate health glyphs and uses `TextRecognizer` (Tesseract) to parse current and max HP (handling comma/digit formatting, e.g. `Health: 553,753 / 553,753` -> `(553753, 553753)`).
  - Calculates the exact `hp_percentage` with float precision ($0.0\%$ to $100.0\%$).
- [ ] **Target Verification Metrics & Telemetry:**
  - `TargetVerificationMetrics` carries optional `parsed_current_hp: int | None`, `parsed_max_hp: int | None`, and `is_premium_reading: bool`.
  - The Target Debug panel renders these exact numeric values when available.
- [ ] **Combat Execution & Kill Confirmation:**
  - When valid numeric HP is parsed:
    - `CombatController` records exact HP deltas as combat progress (`damage_dealt = True` on decrease).
    - Engagement timeout resets reliably on numeric decrease.
    - Confirms `TARGET_DEAD` immediately when `current_hp == 0` or when target clears after observed low HP ($\le 5.0\%$).
- [ ] **Graceful Fallback:**
  - If the toggle is off, Tesseract is unavailable, or a reading fails to parse valid digits, `TargetVerifier` falls back to the existing red-pixel gauge bar percentage.
- [ ] **Localization:**
  - All new UI toggle labels, tooltips, and debug metrics rows are localized in German (`de.json`) and English (`en.json`).

## Out of scope

- OCR extraction of other player names, chat window text, or buff icon tooltips.
- Reading memory offsets or injecting client hooks.

## Verification

- Automated:
  - Unit tests with synthetic and real screenshot crops verifying numeric health text isolation and OCR parsing (testing full HP, mid-fight HP, low HP, and comma-separated numbers).
  - Unit tests verifying seamless fallback to pixel-bar gauge calculation when OCR is disabled or unparseable.
  - Unit tests verifying `CombatController` kill confirmation and damage detection with numeric HP inputs.
  - `./scripts/check.ps1` runs clean without lint or type errors.
- Manual (Windows):
  - Enable "Premium Monster-HP OCR" in the dashboard on an account with active Premium.
  - Target a monster in Flyff and verify exact `Current HP / Max HP` and `%` in the Target Debug panel.
  - Attack the monster and verify that every hit decrements the numeric HP and kill confirmation triggers immediately on monster death.
