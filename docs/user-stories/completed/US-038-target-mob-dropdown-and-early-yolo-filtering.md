---
id: US-038
title: Target monster dropdown selection and early YOLO perception filtering
status: completed
created: 2026-08-18
updated: 2026-08-19
---

# US-038: Target monster dropdown selection and early YOLO perception filtering

## Story

As a **bot operator farming in areas with multiple monster types**, I want **to select the target monster type via a UI dropdown and have non-target mobs filtered out immediately during YOLO object detection before any candidate selection or template matching**, so that **the bot only tracks, targets, and verifies the desired mob type without wasting CPU cycles on irrelevant mobs or attempting false-positive template matches**.

## Context and assumptions

- [Architecture](../wiki/architecture.md) (US-003, US-004, US-008, US-013, US-023, US-024, US-029, US-032).
- `OpenCVDnnYoloDetector` already supports `DetectionConfig.allowed_class_names: frozenset[str]`, discarding candidate bounding boxes in `_decode()` when configured.
- However, `MainWindow` and `app.py` currently initialize `OpenCVDnnYoloDetector` with an empty `allowed_class_names` set, returning all detected entities regardless of operator intent.
- `TargetVerifier` currently loads all anchor templates for all known labels in `load_mob_anchor_templates()` and tests all templates sequentially on every frame.
- When an operator selects a specific mob from the dropdown (or "All" / "Alle" for unconstrained hunting), the perception pipeline, `TargetVerifier`, and `CombatController` should update dynamically without restarting the application.
- Note on ID: Sequentially assigned as US-038 because US-034 is completed ([US-034](completed/US-034-background-independent-monster-stats-kill-confirmation.md)) and US-035–US-037 are assigned in the active backlog.

## Acceptance criteria

- [x] **Target Monster Dropdown in Dashboard UI:**
  - The combat/targeting configuration panel in `MainWindow` displays a "Target Monster" (`Ziel-Monster`) dropdown combo box (`QComboBox`).
  - The dropdown is dynamically populated with "All" (`Alle`) followed by each monster class found in the active model's `labels.txt` (e.g. `Flame`, `Rapra`).
- [x] **Early YOLO Perception Filtering:**
  - When a specific monster class is selected in the dropdown, `OpenCVDnnYoloDetector` updates its `allowed_class_names` configuration.
  - Mobs not matching the selected class are discarded immediately during YOLO bounding box decoding (`_decode()`) and do not appear in `WorldState.visible_mobs`.
  - When "All" is selected, `allowed_class_names` is cleared (`frozenset()`), allowing all detected mobs through.
- [x] **Synchronized Target Verification & Template Matching:**
  - `TargetVerifier` updates its active allowed names and resolves the corresponding mob-specific anchor template(s) dynamically via `load_mob_anchor_templates()` when the selection changes.
  - Template matching (`cv2.matchTemplate`) in `TargetVerifier._match_anchor()` evaluates only the relevant anchor template for the active selection.
- [x] **Combat Controller Synchronization:**
  - `CombatController` updates its `allowed_class_names` to remain in sync with the selected mob type, ensuring candidate prioritization and click targeting only target eligible mobs.
- [x] **Dynamic Live Switching:**
  - Changing the dropdown selection while the bot is running or in standby immediately applies the new filter across Detector, Verifier, and Combat Controller without requiring an application restart.
- [x] **Localization:**
  - All new UI labels, combobox entries ("All"), and tooltips are fully synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [x] **Verification:**
  - Unit tests verify dynamic filter propagation to `OpenCVDnnYoloDetector`, `TargetVerifier`, and `CombatController`.
  - `./scripts/check.ps1` passes cleanly with no ruff, mypy, or pytest failures.

## Out of scope

- Training new YOLO models from within the dashboard UI (handled by CLI `--train-mob-detector`).
- Complex multi-quota scheduling per mob (covered separately in US-035).

## Verification

- Automated:
  - `uv run pytest tests/unit/test_vision_detection.py tests/unit/test_target_verification.py tests/unit/test_orchestrator.py tests/unit/test_ui.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  - Launch `uv run python -m flyff_bot ui` in an area with multiple mob types (e.g. Flame and Rapra).
  - Select "Rapra" in the Target Monster dropdown.
  - Verify that only Rapra mobs appear in the debug overlay / visible mobs counter, and Flame mobs are ignored.
  - Switch to "Flame" and verify only Flame mobs are targeted and matched.
