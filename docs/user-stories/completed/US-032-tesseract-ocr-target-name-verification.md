---
id: US-032
title: Tesseract OCR target name verification and robust whitelist matching
status: completed
created: 2026-08-17
updated: 2026-08-17
---

# US-032: Tesseract OCR target name verification and robust whitelist matching

## Story

As a **bot operator**, I want **the target verification system to use Tesseract OCR text recognition and string matching against allowed whitelist monster names rather than rigid RGB template matching**, so that **valid targets across various client resolutions (such as 1600x900) and font renderings are reliably confirmed as valid targets without failing into false 'Wrong Target' states and blocking combat execution**.

## Context and assumptions

- [Architecture](../../wiki/architecture.md) (US-004, US-012, US-023, US-024, US-029).
- Defect report [BUG-011](../../bugs/fixed/BUG-011-target-name-verification-failure-wrong-target.md): Rigid `cv2.matchTemplate` against static RGB templates (`models/target_flame.png`) fails on 1600x900 and varying font rendering with a low correlation score (~0.19), causing genuine targets to be falsely classified as `WRONG_TARGET` ("Falsches Ziel") and preventing attack key (`F3`) dispatch.
- `TesseractTextRecognizer` is already established and integrated in the repository (`flyff_bot.features.vision.loot_ocr` and `MonsterStatsReader`).
- The target header contains the monster name rendered as text above or alongside the HP bar. With standard contrast enhancement and binarization preprocessing, Tesseract OCR can reliably extract the textual monster name.
- Whitelist matching can compare the parsed OCR text against configured allowed mob names (e.g. from `models/labels.txt` or configured target names) using case-insensitive string containment or normalized fuzzy matching, removing the need for fragile pixel-exact PNG templates for every monster.

## Acceptance criteria

- [x] Given a captured game frame with an active target header, `TargetVerifier` extracts and preprocesses the target name crop and reads the text via an injectable `TextRecognizer` (e.g. `TesseractTextRecognizer`).
- [x] Given recognized OCR text from the target name region, it is evaluated against the configured whitelist monster names (case-insensitive substring/normalized match).
- [x] When the recognized text matches a whitelisted monster name and the HP bar criteria passes, `TargetVerifier` reports `TargetStatus.VALID_TARGET` (`TargetState.VALID`).
- [x] When the target header anchor passes but the recognized text does not match any whitelisted monster name, `TargetVerifier` reports `TargetStatus.WRONG_TARGET` ("Falsches Ziel").
- [x] When valid target status is reached, `CombatController` transitions to `ENGAGING` and dispatches the configured attack hotkey (e.g. `F3`).
- [x] The desktop UI Target Debug panel (`Zielverifizierungs-Debug`) displays the parsed raw OCR text, matched candidate name, and pass/fail outcome.
- [x] Target name verification gracefully handles unreadable or empty OCR results without throwing exceptions or stalling the perception pipeline.
- [x] All user-visible strings and status messages are synchronized in German and English in `src/flyff_bot/locales/*.json`.

## Out of scope

- Training or modifying YOLO mob detection ONNX models.
- Changing navigation, movement dead-reckoning, or vitals triggers.

## Implementation notes

- The root cause was not the crop geometry or the threshold value: the HUD is drawn at a fixed pixel
  size, so `DEFAULT_NAME_OFFSET` already lands on the nameplate at every tested resolution. The
  125x35 crop is mostly world background, and `TM_CCOEFF_NORMED` measured that background. The
  shipped `models/target_flame.png` was deleted rather than retuned.
- Preprocessing thresholds the one fixed pale-yellow nameplate fill colour (BGR ~160/255/255) with
  `cv2.inRange` and upscales 2x, rather than the CLAHE + adaptive-threshold pipeline the loot and
  monster-stats readers use: on this ROI those brightness-based paths track the scenery too. The
  shared `TesseractTextRecognizer` (`eng+deu`, `--psm 6`) is reused unchanged.
- Only the canonical whitelist entry reaches `TargetVerificationResult.target_name`; the raw OCR
  string stays on `TargetVerificationMetrics.name_text`, which is `compare=False` on
  `SelectedTarget`, so a flickering reading cannot re-create the US-024 spurious `TARGET_CHANGED`
  events.
- Name recognition is the one criterion not measured on every tick (US-029): it runs only once the
  header anchor is accepted, and the reading is cached against the previous tick's mask. The OCR
  subprocess costs ~75 ms against a 100 ms Qt timer that already runs `MonsterStatsReader`, and the
  mask is byte-identical across separate captures of the same target. A failed recognition is never
  cached, so a recoverable engine problem is retried.
- Known consequence: containment matching is looser than the template matching it replaced. A
  nameplate that *contains* a whitelist entry passes, so a hypothetical "Flame Giant" would be
  accepted as "Flame". With `models/labels.txt` holding only `Flame` this cannot misfire, and YOLO
  class filtering remains the primary gate on which mobs are clicked at all — but a future
  multi-monster whitelist with overlapping names needs an explicit decision here rather than
  inheriting this behaviour silently.
- The operator-facing name-match threshold spin box was removed together with the mechanism it
  tuned; `MainWindow.anchor_threshold_changed` now carries a single float into
  `TargetVerifier.update_anchor_threshold`. The CLI's `--target-template NAME PATH` became
  `--target-name NAME`.

## Verification

- Automated: `uv run pytest tests/unit/test_target_verification.py` and `uv run pytest tests/unit/test_orchestrator.py` verifying OCR target name extraction, whitelist matching, and combat transition.
- Automated (executed): `ruff check`, `ruff format --check`, `mypy`, and `pytest` are green — 346 passed, 7 skipped. `tests/unit/test_target_verification.py` covers the preprocessing, whitelist matching, every `TargetNameStatus`, the anchor gate on OCR invocation, the nameplate cache, and the real 1276x747 and 2559x1439 fixtures through a real Tesseract install (skipped when English and German language data is absent).
- Manual (Windows, not executed here — requires the game client): Run `uv run python -m flyff_bot ui`, select a Flame monster, verify in `Zielverifizierungs-Debug` that the OCR text row shows the recognized nameplate, target state confirms as "Gültiges Ziel", and the F3 attack key executes.
