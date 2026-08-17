---
id: US-032
title: Tesseract OCR target name verification and robust whitelist matching
status: draft
created: 2026-08-17
updated: 2026-08-17
---

# US-032: Tesseract OCR target name verification and robust whitelist matching

## Story

As a **bot operator**, I want **the target verification system to use Tesseract OCR text recognition and string matching against allowed whitelist monster names rather than rigid RGB template matching**, so that **valid targets across various client resolutions (such as 1600x900) and font renderings are reliably confirmed as valid targets without failing into false 'Wrong Target' states and blocking combat execution**.

## Context and assumptions

- [Architecture](../../wiki/architecture.md) (US-004, US-012, US-023, US-024, US-029).
- Defect report [BUG-011](../../bugs/BUG-011-target-name-verification-failure-wrong-target.md): Rigid `cv2.matchTemplate` against static RGB templates (`models/target_flame.png`) fails on 1600x900 and varying font rendering with a low correlation score (~0.19), causing genuine targets to be falsely classified as `WRONG_TARGET` ("Falsches Ziel") and preventing attack key (`F3`) dispatch.
- `TesseractTextRecognizer` is already established and integrated in the repository (`flyff_bot.features.vision.loot_ocr` and `MonsterStatsReader`).
- The target header contains the monster name rendered as text above or alongside the HP bar. With standard contrast enhancement and binarization preprocessing, Tesseract OCR can reliably extract the textual monster name.
- Whitelist matching can compare the parsed OCR text against configured allowed mob names (e.g. from `models/labels.txt` or configured target names) using case-insensitive string containment or normalized fuzzy matching, removing the need for fragile pixel-exact PNG templates for every monster.

## Acceptance criteria

- [ ] Given a captured game frame with an active target header, `TargetVerifier` extracts and preprocesses the target name crop and reads the text via an injectable `TextRecognizer` (e.g. `TesseractTextRecognizer`).
- [ ] Given recognized OCR text from the target name region, it is evaluated against the configured whitelist monster names (case-insensitive substring/normalized match).
- [ ] When the recognized text matches a whitelisted monster name and the HP bar criteria passes, `TargetVerifier` reports `TargetStatus.VALID_TARGET` (`TargetState.VALID`).
- [ ] When the target header anchor passes but the recognized text does not match any whitelisted monster name, `TargetVerifier` reports `TargetStatus.WRONG_TARGET` ("Falsches Ziel").
- [ ] When valid target status is reached, `CombatController` transitions to `ENGAGING` and dispatches the configured attack hotkey (e.g. `F3`).
- [ ] The desktop UI Target Debug panel (`Zielverifizierungs-Debug`) displays the parsed raw OCR text, matched candidate name, and pass/fail outcome.
- [ ] Target name verification gracefully handles unreadable or empty OCR results without throwing exceptions or stalling the perception pipeline.
- [ ] All user-visible strings and status messages are synchronized in German and English in `src/flyff_bot/locales/*.json`.

## Out of scope

- Training or modifying YOLO mob detection ONNX models.
- Changing navigation, movement dead-reckoning, or vitals triggers.

## Verification

- Automated: `uv run pytest tests/unit/test_target_verification.py` and `uv run pytest tests/unit/test_orchestrator.py` verifying OCR target name extraction, whitelist matching, and combat transition.
- Manual (Windows): Run `uv run python -m flyff_bot ui`, select a Flame monster in Flyff client at 1600x900 resolution, verify in `Zielverifizierungs-Debug` that the OCR reads "Flame", target state confirms as "Gültiges Ziel", and F3 attack key executes.
