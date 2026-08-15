---
id: US-012
title: Real-world vision refactoring for robust target verification and multi-mob detection
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-012: Real-world vision refactoring for robust target verification and multi-mob detection

## Story

As a bot developer, I want to refactor `TargetVerifier` and integrate real-world game evidence from `data/eden/flame/`, so that target-bar detection is immune to background sky/cloud color artifacts, reliably distinguishes `NO_TARGET` from active targets, and supports multiple configured mob types.

## Context and assumptions

- Source: [Target architecture proposal](../sources/2026-08-15-target-architecture-proposal.md) and discovery from real game screenshots (`data/eden/flame/`).
- Real-world observation: Sunset sky and red/orange clouds in the background cause naive global HP color thresholds to trigger false `WRONG_TARGET` instead of `NO_TARGET`.
- Target-bar in Flyff client has distinct visual anchors (element icon box, header frame, HP bar located in the sub-row under the nameplate).
- Refactoring must support multiple configured mob names and whitelists (e.g. `Flame`, etc.) with positive and negative test fixtures from real screenshots.

## Acceptance criteria

- [x] `TargetVerifier` checks for header anchor existence (element box or header frame match) before measuring HP pixels.
- [x] Correctly returns `TargetStatus.NO_TARGET` on screenshots with red/orange sky/cloud backgrounds without a selected target (e.g. `Screenshot ...203618.png`).
- [x] Correctly returns `TargetStatus.VALID_TARGET` with target name `Flame` and valid HP percentage on targeted screenshots (e.g. `Screenshot ...204002.png`).
- [x] Correctly returns `TargetStatus.WRONG_TARGET` when a target is selected whose name is not in the active monster whitelist.
- [x] Measures HP percentage strictly within the dedicated target-bar sub-rectangle rather than the entire sky ROI.
- [x] Fast automated unit tests verify detection using real cropped image fixtures from `data/eden/flame/`.
- [x] All user-visible logs, status codes, and error messages exist in German and English.

## Out of scope

- Direct input dispatching (covered in [US-008](US-008-reactive-combat-controller.md)).
- Loot OCR parsing (covered in [US-005](US-005-loot-log-ocr.md)).

## Verification

- Automated: Unit tests with real game screenshot crops for positive (`Flame` targeted), negative (unwanted target), and empty (sky background without target); `./scripts/check.ps1`.
- Manual (Windows): Run target verifier against live `neuz.exe` client while targeting and clearing target.
