---
id: BUG-011
title: Monster stats OCR failure and misleading anchor diagnostics in fixed placeholder mode
status: resolved
severity: medium
created: 2026-08-17
updated: 2026-08-17
---

# BUG-011: Monster stats OCR failure and misleading anchor diagnostics in fixed placeholder mode

## Environment

- Windows version: Windows 10 / 11 (64-bit)
- Python version: 3.14.7
- Application revision: main
- Client/server version: Flyff Universe / Flyff PC Client with PySide6 desktop dashboard

## Reproduction

1. Start the Flyff client and open the in-game session statistics window ("Time: ... Monster Kills: ...").
2. Launch `flyff-bot` desktop UI (`uv run python -m flyff_bot ui`).
3. Toggle "Platzierungshilfen" to show the placement guides over the game client.
4. Position the in-game session stats HUD window inside the cyan dashed placement guide region.
5. In the dashboard, enable the "Monster-Stats-Debug" checkbox to inspect diagnostics.
6. Observe the readouts under "Monster-Stats-Debug":
   - "Kopf-Anker" displays: `Keine Ankervorlage konfiguriert; fester Ausschnitt wird gelesen`
   - "Status" displays: `OCR fehlgeschlagen`
   - "OCR-Rohtext" displays: `Kein Text erkannt`
   - "Monster-Kills" displays: `Nicht erkannt`

## Expected behavior

1. When using the predefined fixed placement box / guide ("Platzierungshilfe"), the diagnostic panel should not show confusing or irrelevant header-anchor warnings (since a dedicated placement region is intentionally defined and aligned). The UI should clearly indicate that the predefined placement region is active.
2. The OCR engine dependency (e.g. self-contained Python OCR / bundled OCR engine or clearly diagnosed dependency requirement) must reliably execute text recognition out of the box without requiring manual system PATH configurations or silently failing with generic error messages.
3. If an OCR dependency is missing or fails, the application must provide an explicit, actionable status (e.g., distinguishing "OCR engine unavailable / not found" from "No text / pattern matched in region") instead of a misleading generic failure.

## Actual behavior

- `MonsterStatsReader` relies on `TesseractTextRecognizer`, which attempts to invoke an external `tesseract` binary via `subprocess.run()`. When Tesseract is not installed in the Windows system `PATH`, `LootOcrError(ENGINE_UNAVAILABLE)` is raised.
- `MonsterStatsReader.read()` catches all exceptions with a broad `except Exception:` and maps engine unavailability to a generic `MonsterStatsStatus.OCR_FAILED` ("OCR fehlgeschlagen"), giving the operator no actionable indication of what is wrong.
- The diagnostics panel displays `Keine Ankervorlage konfiguriert; fester Ausschnitt wird gelesen` under "Kopf-Anker", which misleads the operator into believing an anchor configuration is missing, even though the session stats window is properly aligned inside the predefined placement guide.

## Impact and frequency

- **Impact:** High usability impact. Operators cannot track monster kills via OCR because external Tesseract binaries are missing, and the diagnostic messages provide misleading guidance regarding anchor configuration.
- **Frequency:** 100% reproducible on systems where external `tesseract.exe` is not installed or configured in system `PATH`.

## Regression verification

- [x] Clear diagnostic readouts reflect the predefined fixed placement guide mode without confusing anchor warnings.
- [x] OCR engine dependency is cleanly managed/bundled or provides explicit, localized diagnostic status when unavailable.
- [x] Automated unit tests in `tests/unit/test_monster_stats.py` and `tests/unit/test_ui.py` verify distinct status reporting for engine unavailability vs recognition errors.
- [x] Related documentation is current.

## Resolution

- `resolve_tesseract_executable()` (`features/vision/loot_ocr.py`) prefers `shutil.which()` and then
  probes the two documented Windows install directories, because the official Tesseract installer
  does not extend the system `PATH`. An explicitly passed executable is still honoured verbatim.
- `ENGINE_UNAVAILABLE` now also covers an executable that exists but cannot be started (`OSError`
  rather than only `FileNotFoundError`), evaluated after the `SubprocessError` branch so a non-zero
  exit or timeout stays `RECOGNITION_FAILED`.
- `MonsterStatsStatus.ENGINE_UNAVAILABLE` is reported when `MonsterStatsReader` catches a
  `LootOcrError` carrying that code, with its own localized sentence in both locales. The residual
  broad handler is kept so an injected `TextRecognizer` cannot raise into the Qt timer tick.
- The shipped anchor row states that the predefined placement region is read instead of reporting a
  missing anchor template, since the fixed region is the intended mode.
- Known limitation: no Tesseract binary is bundled. When none is installed the dashboard now names
  that condition explicitly instead of failing generically, which is the alternative the regression
  criteria allow.
