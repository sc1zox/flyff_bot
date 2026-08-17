---
id: BUG-011
title: Target name verification failure causes false wrong-target status and prevents combat skill execution
status: reported
severity: high
created: 2026-08-17
updated: 2026-08-17
---

# BUG-011: Target name verification failure causes false wrong-target status and prevents combat skill execution

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff Universe / Flyff PC Desktop Client (e.g. 1600x900 resolution)

## Reproduction

1. Launch the application via `uv run python -m flyff_bot ui` with YOLO mob detection, target header anchor (`models/target_anchor.png`), and target name template (`models/target_flame.png`).
2. In the game client (e.g. running at 1600x900 resolution), ensure valid target monsters (e.g. "Flame") are present in the viewport.
3. Start autonomous farming by clicking **"Starten"** (**"Start"**).
4. Observe the combat cycle when a candidate mob is detected:
   - The bot enters `TARGETING` and clicks the candidate monster.
   - In the Flyff client, the target bar appears at the top center with monster name "Flame" and a full HP bar.
   - In the desktop dashboard and the `Zielverifizierungs-Debug` (Target Debug) panel, observe the verification metrics:
     - **Kopf-Anker (Header Anchor):** `BESTANDEN 0.80 / 0.75` (Anchor match passes)
     - **HP-Leiste (HP Bar):** `BESTANDEN 1051 px (100.0%)` (HP bar passes)
     - **Namensabgleich (Name Match):** `FEHLGESCHLAGEN 'Flame' 0.19 / 0.75` (Name match fails with correlation score ~0.19)
     - **Zielstatus (Target State):** `Falsches Ziel` (`WRONG_TARGET` / `TargetState.WRONG`)
     - **Grund (Reason):** `Keine Namensvorlage aus der Whitelist stimmte überein`
     - **Kampfabbruch (Break Reason):** `Das angeklickte Ziel wurde nie bestätigt, daher ist seine Position gesperrt.`
5. Observe that `CombatController` refuses to transition to `ENGAGING` or dispatch the attack hotkey (`F3`) because `selected_target.state` is not `TargetState.VALID`.
6. After `target_acquisition_grace_seconds` (0.8s) expires, `ACQUISITION_TIMEOUT` triggers, the target position is registered as a `TargetLockout` for 4.0s, and the bot reverts to `SEARCHING` without ever attacking or defeating the monster.

## Expected behavior

1. **Robust Target Name Verification Across Resolutions:**
   - When a whitelisted monster (e.g. "Flame") is targeted, the target header verification should reliably match the name template or name text across standard client resolutions (including 1600x900) and varying font anti-aliasing / level prefix renderings.
   - The target must evaluate to `TargetStatus.VALID_TARGET` (`TargetState.VALID`).
2. **Combat Attack Dispatch:**
   - Upon valid target confirmation, `CombatController` transitions from `TARGETING` to `ENGAGING`/`FIGHTING` and immediately sends the configured attack hotkey (e.g. `F3`).
3. **Resilient Matching or Fallback Options:**
   - Target name verification must not fail with an extremely low match score (~0.19) on genuine whitelist targets due to minor pixel shifts, font rendering differences, or resolution scaling.

## Actual behavior

- Rigid template matching against `models/target_flame.png` via `DEFAULT_NAME_OFFSET = AnchorOffsetRegion(dx=40, dy=-4, width=125, height=35)` achieves only ~0.19 correlation score on 1600x900 client resolution.
- The target is falsely classified as `TargetStatus.WRONG_TARGET` ("Falsches Ziel").
- `CombatController` stays blocked in `TARGETING`, never dispatches `F3`, and times out into `ACQUISITION_TIMEOUT`, locking out the monster coordinate and halting progression.

## Impact and frequency

- **Impact:** Critical blocker for autonomous combat. The bot detects monsters and clicks them, but is unable to attack or defeat them due to false wrong-target rejection.
- **Frequency:** 100% reproducible when running at 1600x900 resolution or whenever name template pixel differences drop the correlation score below the threshold.

## Resolution

Addressed by [US-032: Tesseract OCR Target Name Verification](../user-stories/US-032-tesseract-ocr-target-name-verification.md). Replacing rigid RGB template matching with preprocessed Tesseract OCR text recognition on the target header name ROI enables resolution-independent, robust string matching against the configured mob whitelist.

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.

