---
id: BUG-029
title: Tesseract OCR TSV argument ordering causes empty stdout and unreadable target names
status: resolved
severity: high
created: 2026-08-23
updated: 2026-08-23
---

# BUG-029: Tesseract OCR TSV argument ordering causes empty stdout and unreadable target names

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Start the desktop UI with `uv run python -m flyff_bot ui` or run target verification with `TesseractTextRecognizer(language="eng")` on any valid target screenshot (e.g. `data/assets/mobs/eden/flame/Screenshot 2026-08-16 231337.png`).
2. Activate a target monster (e.g. "Flame") or start a farming session targeting Flame mobs in game.
3. Observe the `TargetDebugPanel` / `Zielverifizierungs-Debug` overlay upon clicking a mob:
   - **Kopf-Anker:** `BESTANDEN 1.00 / 0.75`
   - **HP-Leiste:** `BESTANDEN 1051 px (100.0%)`
   - **Namensabgleich:** `FEHLGESCHLAGEN '' -> keines`
   - **Zielstatus:** `Falsches Ziel` (`TargetState.WRONG`)
   - **Grund:** `Im Zielnamensbereich wurde kein lesbarer Text gefunden` (`TargetNameStatus.UNREADABLE`)
4. Observe that `CombatController` refuses to attack (`F3`), times out into `ACQUISITION_TIMEOUT`, and locks out the target position for 1.0s. Under US-060, the bot immediately selects the same mob again in the next search cycle, entering an infinite loop of targeting without attacking.

## Expected behavior

1. When a whitelisted monster (such as "Flame") is targeted, `TesseractTextRecognizer.recognize_lines()` must execute Tesseract CLI with `stdout` as the `outputbase` and `tsv` as the trailing configfile:
   ```powershell
   tesseract - stdout -l <language> --psm 6 tsv
   ```
2. Recognized text lines and bounding boxes must be parsed from Tesseract's standard output stream into `RecognizedTextLine` objects.
3. `TargetVerifier` must match recognized strings against `allowed_names` and evaluate legitimate targets to `TargetStatus.VALID_TARGET` (`TargetState.VALID`), allowing `CombatController` to engage and attack.

## Actual behavior

- `TesseractTextRecognizer.recognize_lines()` executes Tesseract with arguments:
  ```powershell
  tesseract - tsv -l <language> --psm 6
  ```
- Because `tsv` is supplied in the second position (`outputbase`), Tesseract interprets `tsv` as a target file prefix and writes output to a file named `tsv.txt` in the working directory instead of streaming to standard output.
- `result.stdout` is completely empty `""`.
- `_parse_tesseract_tsv("")` returns an empty tuple `()`.
- `TargetVerifier._read_name()` reports `raw_text = ""` with status `TargetNameStatus.UNREADABLE`.
- All selected monsters evaluate to `TargetState.WRONG` with reason "Im Zielnamensbereich wurde kein lesbarer Text gefunden", leaving the bot unable to engage any monster.

## Impact and frequency

- **Impact:** Critical blocker for autonomous combat. The bot repeatedly acquires and clicks valid monsters, but never attacks or kills them.
- **Frequency:** 100% reproducible whenever Tesseract OCR is invoked for target verification or monster name recognition on Windows.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
- [x] The check passes after the fix.
- [x] Related documentation is current.
