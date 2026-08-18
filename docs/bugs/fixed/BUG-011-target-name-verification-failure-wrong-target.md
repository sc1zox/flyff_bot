---
id: BUG-011
title: Target name verification failure causes false wrong-target status and prevents combat skill execution
status: resolved
severity: high
created: 2026-08-17
updated: 2026-08-17
---

# BUG-011: Target name verification failure causes false wrong-target status and prevents combat skill execution

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe, e.g. 1600x900 resolution)

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

## Root cause

The reported 1600x900 resolution was not reproduced directly — no capture at that size exists in
`data/eden/flame` — but the same failure mode reproduces deterministically on the tracked 2559x1439
captures, which is stronger evidence than the resolution number suggests:

- On `Screenshot 2026-08-16 231337.png` (2559x1439) the header anchor matches at `0.897` and the
  name crop cleanly contains `Flame <Lvl 175>`, yet `models/target_flame.png` scores `0.245`.
- On `Screenshot 2026-08-15 204002.png` (1276x747), the capture the template was cropped from, the
  same template scores `1.000`.

The reported 1600x900 session points the same way from the other side: its own metrics record the
header anchor at `0.80 / 0.75` **PASS** and the HP bar at `1051 px (100.0%)` **PASS**, with the name
match the sole failing criterion at `0.19`. A passing anchor means the header was located and the
anchor-relative crops landed where they were configured to land, so the name template was the only
thing that failed at the reported resolution as well.

The crop geometry was therefore never wrong: the Flyff HUD is drawn at a fixed pixel size, so
`DEFAULT_NAME_OFFSET` lands on the nameplate at both resolutions. The defect is in what
`TM_CCOEFF_NORMED` measures. The 125x35 rectangle is mostly *world background* — grass, sky, dirt —
which changes with the camera while the glyphs do not, so the correlation tracks the scenery rather
than the name. No threshold value separates a genuine target on new scenery from a wrong target, so
the mechanism, not its tuning, had to change.

## Impact and frequency

- **Impact:** Critical blocker for autonomous combat. The bot detects monsters and clicks them, but is unable to attack or defeat them due to false wrong-target rejection.
- **Frequency:** 100% reproducible when running at 1600x900 resolution or whenever name template pixel differences drop the correlation score below the threshold.

## Resolution

Addressed by [US-032: Tesseract OCR Target Name Verification](../../user-stories/completed/US-032-tesseract-ocr-target-name-verification.md). Replacing rigid RGB template matching with colour-masked Tesseract OCR text recognition on the target header name ROI enables background-independent, robust string matching against the configured mob whitelist.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
  `tests/unit/test_target_verification.py::test_verifier_accepts_real_flame_fixtures_through_tesseract`
  runs the production default configuration and the shipped `models/target_anchor.png` over both
  `Screenshot 2026-08-15 204002.png` (1276x747) and `Screenshot 2026-08-16 231337.png` (2559x1439);
  the 2559x1439 case is the one the deleted template scored `0.245` on.
- [x] The check passes after the fix. The full suite is green
  (`ruff check`, `ruff format --check`, `mypy`, `pytest`: 346 passed, 7 skipped). The three
  real-Tesseract fixture tests skip when no Tesseract install with English and German language data
  is present, so a machine without the engine reports skipped rather than failing.
- [x] Related documentation is current. `docs/wiki/architecture.md` records the US-032 mechanism and
  `docs/wiki/log.md` the synthesis entry.

