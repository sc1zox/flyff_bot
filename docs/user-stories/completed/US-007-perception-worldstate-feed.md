---
id: US-007
title: Perception to WorldState feed integration
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-007: Perception to WorldState feed integration

## Story

As a bot developer, I want the outputs from the perception pipeline (frame capture, YOLO mob detection, target verification, and loot OCR) to be aggregated into the central `WorldState` snapshot, so that reactive controllers and the supervisor always receive a coherent, up-to-date observation of game reality.

## Context and assumptions

- Source: [Target architecture proposal](../../sources/2026-08-15-target-architecture-proposal.md).
- Depends on [US-002](US-002-vision-frame-capture.md), [US-003](US-003-mob-detection-yolo.md), [US-004](US-004-target-mob-verification.md), and [US-005](US-005-loot-log-ocr.md).
- Integrates with the foundational architecture created in [US-006](US-006-target-architecture-bootstrap.md).
- `WorldState` remains immutable; each perception cycle produces a new timestamped snapshot.

## Acceptance criteria

- [x] Connects `FrameProvider`, `MobDetector`, `TargetVerifier`, and `LootLogReader` into a unified `PerceptionPipeline`.
- [x] Aggregates detections into a new `WorldState` instance on each tick (player status, selected target, visible mobs, recent loot).
- [x] Emits state change events/signals when target transitions occur or new mobs appear.
- [x] Handles individual component failures gracefully (e.g. OCR timeout does not crash mob detection).
- [x] Automated unit tests verify end-to-end perception aggregation with mock feeds.
- [x] All user-visible logs and messages exist in German and English.

## Out of scope

- Direct input dispatching or attack sequencing (covered in [US-008](../US-008-reactive-combat-controller.md)).
- Complex pathfinding across 3D game geometry.

## Verification

- Automated: Unit tests feeding mock frames and detection fixtures through `PerceptionPipeline` into `WorldState`; `./scripts/check.ps1`.
- Manual (Windows): Run perception loop against test video or active client and print updated world states.
