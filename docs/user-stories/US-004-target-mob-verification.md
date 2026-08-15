---
id: US-004
title: Target mob verification and inspection
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-004: Target mob verification and inspection

## Story

As a player using permitted automation, I want the bot to verify that a selected or targeted entity is
the correct target mob before initiating attacks, so that wrong monsters, NPCs, or players are not accidentally targeted.

## Context and assumptions

- Source: [Computer vision and YOLO request](../sources/2026-08-15-computer-vision-and-yolo-request.md).
- Depends on [US-002](completed/US-002-vision-frame-capture.md) for frame capture.
- In Flyff, selecting a target displays a target header/bar (top-center of client) with the target name, level, and HP bar.
- Verification can combine template matching, color/HP bar detection, OCR, or bounding-box classification.

## Acceptance criteria

- [ ] Extracts the target info region (e.g. top target bar area) from the captured game frame.
- [ ] Inspects whether a valid target is currently selected.
- [ ] Validates target attributes (e.g. target name match against configured whitelist/pattern, alive status via HP bar).
- [ ] Returns a structured verification result (e.g. `TargetStatus.VALID_TARGET`, `TargetStatus.WRONG_TARGET`, `TargetStatus.NO_TARGET`).
- [ ] Fast automated unit tests verify detection logic using cropped target bar fixtures (positive, negative, empty).
- [ ] All user-visible logs and messages exist in German and English.

## Out of scope

- Issuing attack key sequences or movement.
- Full text chat recognition (covered in [US-005](US-005-loot-log-ocr.md)).

## Verification

- Automated: Unit tests against sample target header image fixtures; `./scripts/check.ps1`.
- Manual (Windows): Run verification against an active game client with selected target.
