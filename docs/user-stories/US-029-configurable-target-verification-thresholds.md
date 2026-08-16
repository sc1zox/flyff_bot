---
id: US-029
title: Configurable target verification thresholds and comprehensive visual diagnostics
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-029: Configurable target verification thresholds and comprehensive visual diagnostics

## Story

As a **player calibrating combat targeting for various Flyff client resolutions and environments**,
I want **configurable target verification thresholds in the dashboard and non-short-circuiting diagnostic inspection for the header anchor, HP bar, and mob name template**,
so that **valid targets with minor rendering variances (e.g. font antialiasing, transparency) are reliably accepted and I can inspect live HP and name matching scores even when calibrating anchor thresholds**.

## Context and assumptions

- In [`TargetVerifier`](file:///i:/coding%20projects/flyff_bot/src/flyff_bot/features/vision/target_verification.py), the default match thresholds (`DEFAULT_ANCHOR_MATCH_THRESHOLD = 0.9`, `DEFAULT_NAME_MATCH_THRESHOLD = 0.9`) are too rigid for in-game template matching with antialiasing, slight transparency, and dynamic background rendering, causing genuine selected targets (e.g. anchor score 0.83) to fail with `NO_TARGET` / `Kopf-Anker nicht erkannt`.
- When the header anchor score is below threshold, `TargetVerifier.verify()` currently short-circuits before measuring the HP bar or matching name templates, reporting `0 px (0.0%)` and `keines` (0.00 score) in the debug panel. This prevents operators from diagnosing HP bar extraction and name recognition.
- Lowering the default template matching thresholds (e.g., from 0.90 to 0.75 - 0.80) and exposing live threshold controls (anchor threshold, name threshold, minimum HP pixels) in the PySide6 UI allows robust target verification across varying client resolutions and visual themes.
- Links:
  - [Architecture](file:///i:/coding%20projects/flyff_bot/docs/wiki/architecture.md)
  - [US-004: Target mob verification](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-004-target-mob-verification.md)
  - [US-012: Real-world vision refactoring](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-012-real-world-vision-refactoring.md)
  - [US-024: Target verifier metrics and debug panel](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-024-target-verifier-metrics-and-debug-panel.md)
  - [US-026: Static HUD anchoring and field hardening](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md)

## Acceptance criteria

- [ ] Given `TargetVerifier`, the default template matching thresholds for `anchor_match_threshold` and `name_match_threshold` are set to robust baseline values (0.75) that prevent false negatives from minor rendering noise while continuing to reject non-targets.
- [ ] Given `TargetVerifier.verify()`, all diagnostic metrics (anchor match score, HP bar pixel count/percentage, and best name candidate match score) are populated on every tick, ensuring full visibility in the debug panel regardless of whether individual criteria passed or failed.
- [ ] Given the desktop UI (`MainWindow`), the target verification / combat panel exposes configurable controls (spinboxes/sliders) for Anchor Match Threshold (e.g. 0.30–1.00) and Name Match Threshold (e.g. 0.30–1.00).
- [ ] Given a running session, adjusting target verification threshold controls in the UI updates the active `TargetVerifier` and `FarmingOrchestrator` configuration live without resetting running combat state.
- [ ] All user-visible setting labels, tooltips, and debug metrics are synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Modifying YOLO object detector confidence settings (already configured at 0.30).
- Automatic OCR training or template font generation.
- Dispatching input to the game client when target status is not `VALID_TARGET`.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_target_verification.py` verifying full diagnostic metric computation and robust default threshold matching.
  - UI tests in `tests/unit/test_ui.py` verifying target threshold control signals, value updates, and debug panel rendering.
- Manual (Windows):
  - Select a target in Flyff, open "Ziel-Debug", and verify that anchor score (e.g. 0.83), HP bar (e.g. 100%), and name match candidate (e.g. 'Flame' 0.95) are simultaneously measured and visible.
  - Adjust threshold to 0.80 and verify target status switches to "Gültiges Ziel" (`VALID_TARGET`).
