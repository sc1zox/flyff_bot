---
id: US-029
title: Anchor-relative target verification, configurable thresholds, and full diagnostic metrics
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-029: Anchor-relative target verification, configurable thresholds, and full diagnostic metrics

## Story

As a **player configuring combat targeting across different Flyff client resolutions and HUD positions**,
I want **target verification to dynamically anchor HP bar and name recognition to the matched header anchor location, provide configurable match thresholds in the dashboard, and evaluate all diagnostic metrics on every tick**,
so that **HP gauges and mob name templates are accurately extracted regardless of window size, and I can inspect live anchor, HP, and name matching metrics simultaneously in the debug panel**.

## Context and assumptions

- In [`TargetVerifier`](file:///i:/coding%20projects/flyff_bot/src/flyff_bot/features/vision/target_verification.py), `verify()` currently extracts `hp_region` and `name_region` from fixed normalized fractions of the broad top-center `target_region` (`x=0.34, y=0.5, width=0.32, height=0.12`), rather than dynamically offsetting from the detected header anchor's exact `(x, y)` match position. On varying client resolutions or UI layouts, this causes the HP bar crop to miss the actual gauge pixels (measuring `0 px (0.0%)`).
- `TargetVerifier.verify()` currently uses rigid short-circuit evaluation:
  - If `anchor_passed` is false (e.g. score 0.83 vs 0.90 threshold), it exits immediately, leaving HP pixels and Name match at zero.
  - If `anchor_passed` is true (e.g. score 0.93) but `hp_passed` fails (e.g. 0 px), it exits immediately with `WRONG_TARGET`, leaving `name_candidate` as `None` ('keines') and `name_score` as `0.00`.
- The default template matching thresholds (`0.90`) are too rigid for in-game font anti-aliasing and transparency variations.
- Lowering default thresholds to robust baselines (e.g. 0.75 - 0.80), dynamically anchoring HP/Name ROIs to the matched header anchor coordinates, and computing all metrics on every tick provides complete diagnostic transparency and robust target validation across all client resolutions.
- Links:
  - [Architecture](file:///i:/coding%20projects/flyff_bot/docs/wiki/architecture.md)
  - [US-004: Target mob verification](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-004-target-mob-verification.md)
  - [US-012: Real-world vision refactoring](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-012-real-world-vision-refactoring.md)
  - [US-024: Target verifier metrics and debug panel](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-024-target-verifier-metrics-and-debug-panel.md)
  - [US-026: Static HUD anchoring and field hardening](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md)

## Acceptance criteria

- [ ] Given `TargetVerifier`, `hp_region` and `name_region` are cropped dynamically relative to the detected `(x, y)` location of the header anchor match, ensuring the HP bar and mob name text align accurately across any window resolution and aspect ratio.
- [ ] Given `TargetVerifier.verify()`, all diagnostic metrics (header anchor match score, HP bar pixel count/percentage, and best name template match score and candidate) are measured and populated on every tick, eliminating short-circuit blanking in the debug panel.
- [ ] Given `TargetVerifier`, default template matching thresholds for `anchor_match_threshold` and `name_match_threshold` are set to robust baseline values (0.75) that prevent false negatives from rendering noise while reliably rejecting non-targets.
- [ ] Given the desktop UI (`MainWindow`), the target verification / combat panel exposes configurable controls (spinboxes/sliders) for Anchor Match Threshold (0.30–1.00) and Name Match Threshold (0.30–1.00).
- [ ] Given a running session, adjusting target verification threshold controls in the UI updates the active `TargetVerifier` configuration live without resetting running combat state.
- [ ] All user-visible setting labels, tooltips, and debug metrics are synchronized in German (`de.json`) and English (`en.json`).

## Out of scope

- Modifying YOLO object detector confidence settings (configured at 0.30).
- Automatic OCR training or custom font generation.
- Dispatching input to the game client when target status is not `VALID_TARGET`.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_target_verification.py` verifying anchor-relative dynamic ROI extraction, full diagnostic metric computation, and robust default threshold matching.
  - UI tests in `tests/unit/test_ui.py` verifying target threshold control signals, value updates, and debug panel rendering.
- Manual (Windows):
  - Select a target in Flyff, open "Ziel-Debug", and verify that anchor score (e.g. 0.93), HP bar (e.g. 100%), and name match candidate (e.g. 'Flame' 0.95) are simultaneously measured and visible.
  - Verify target status switches to "Gültiges Ziel" (`VALID_TARGET`).
