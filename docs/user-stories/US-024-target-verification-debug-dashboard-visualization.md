---
id: US-024
title: Target verification decision and threshold debug dashboard visualization
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-024: Target verification decision and threshold debug dashboard visualization

## Story

As a bot operator debugging target acquisition, I want target verification criteria metrics and decision results displayed directly on the dashboard UI, so that I can inspect why a targeted mob is classified as valid, wrong, or missing without guessing template thresholds or visual bounds.

## Context and assumptions

- **Architectural & Subsystem Links:**
  - Integrates with target verification in [US-004](completed/US-004-target-mob-verification.md) (`TargetVerifier`, `TargetStatus`, `TargetVerificationResult`) and [US-012](completed/US-012-real-world-vision-refactoring.md).
  - Integrates with world-state perception feeding in [US-007](completed/US-007-perception-worldstate-feed.md) (`PerceptionPipeline`, `SelectedTarget`, `WorldState`).
  - Integrates with PySide6 desktop dashboard UI in [US-010](completed/US-010-pyside6-dashboard-and-overlay.md), [US-014](completed/US-014-configurable-ui-attack-key.md), and [US-022](US-022-modern-dark-theme-and-streamlined-dashboard-ui.md) (`MainWindow`, `DashboardFeed`).
  - Connects to combat state decisions in [US-023](completed/US-023-reliable-combat-targeting-and-kill-verification.md) (`CombatController`), where `TargetState.VALID` is required to dispatch attack hotkeys.
- **Problem Statement:**
  - `TargetVerifier.verify()` checks header anchor match score, HP bar pixel count, and target name template match score against configured thresholds (`anchor_match_threshold`, `minimum_hp_pixel_count`, `name_match_threshold`).
  - Currently, `SelectedTarget` only exposes `state`, `name`, and `hp_pixel_count`. The dashboard UI only shows generic status text (`VALID`, `WRONG`, `NONE`) without displaying individual score components or decision reasons.
  - When target acquisition fails or a name template fails to match, operators cannot determine whether the anchor failed, HP was missing, or name matching fell below the threshold.
- **Safety Boundaries:**
  - All UI updates run on the main Qt event loop via `DashboardFeed` signals, preserving performance without blocking the 100ms perception tick.
  - Game window foregrounding checks and `END` emergency stop remain unaffected.
  - All user-visible labels, metrics, tooltips, and status descriptions are fully synchronized in German (`de.json`) and English (`en.json`).

## Acceptance criteria

- [ ] `TargetVerificationResult` (or `SelectedTarget`) conveys complete decision metrics for the active target: header anchor match score & pass status, HP pixel count & pass status, best name template match name/score & pass status, and overall decision status (`VALID_TARGET`, `WRONG_TARGET`, `NO_TARGET`).
- [ ] `PerceptionPipeline` forwards complete target verification decision details into `WorldState.selected_target`.
- [ ] The PySide6 Dashboard UI (`MainWindow` / `DashboardFeed`) displays a dedicated Target Verification Debug section showing live decision metrics:
  - Header Anchor status and score (e.g. `0.95 / 0.90`).
  - HP bar status, pixel count, and HP percentage (e.g. `45 px (100.0%)`).
  - Name Match status, matched template name, and score (e.g. `'Flame' 0.92 / 0.90`).
  - Overall Target State and failure reason when classified as `WRONG` or `NONE`.
- [ ] Automated unit tests in `tests/unit/` verify:
  - `SelectedTarget` / `WorldState` accurately preserves full target verification metrics.
  - `DashboardFeed` and UI update handlers format and display target verification metrics correctly.
- [ ] All user-visible text, labels, status metrics, and tooltips are available in German (`de.json`) and English (`en.json`).

## Out of scope

- Modifying the underlying `TargetVerifier` verification thresholds or state machine transition logic.
- Adding interactive calibration sliders for template matching inside the UI during runtime.

## Verification

- Automated:
  - `uv run pytest tests/unit/test_target_verification.py`
  - `uv run pytest tests/unit/test_ui.py`
  - `uv run pytest tests/unit/test_perception.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  1. Launch the desktop UI dashboard (`uv run flyff-bot gui`).
  2. Select a target mob in Flyff and verify the dashboard updates live with Anchor score, HP pixels, Name match score, and Target state.
  3. Select an un-whitelisted target or empty area and verify the dashboard clearly indicates which criterion failed (e.g. Name match score below threshold).
