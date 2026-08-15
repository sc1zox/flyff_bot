---
id: US-008
title: Reactive combat controller and target engagement
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-008: Reactive combat controller and target engagement

## Story

As a player using permitted automation, I want the bot to select valid target mobs, navigate within combat range, and execute attack/skill rotations with post-action verification, so that monsters are fought efficiently without manual button pressing.

## Context and assumptions

- Source: [Target architecture proposal](../../sources/2026-08-15-target-architecture-proposal.md).
- Depends on [US-006](completed/US-006-target-architecture-bootstrap.md) (Architecture/Controllers) and [US-007](US-007-perception-worldstate-feed.md) (WorldState Feed).
- Flyff target selection is performed by dispatching a Win32 mouse click to the detected monster's screen coordinates `(x + width/2, y + height/2)` from `WorldState.visible_mobs`.
- Post-action visual verification: selection is confirmed by observing the target bar appearance (`TargetStatus.VALID_TARGET`), and attack progress is confirmed by target HP decrease.

## Acceptance criteria

- [x] `CombatController` selects the best candidate mob from `WorldState.visible_mobs` (e.g. closest distance to screen center / valid whitelist type).
- [x] Dispatches a mouse click action to the target mob's bounding-box center coordinates and verifies target lock via `TargetStatus.VALID_TARGET`.
- [x] Executes attack/skill actions (hotkeys `1`-`9`, `C`, or `Space` action slot) mapped to key bindings with configurable cooldowns.
- [x] Verifies ongoing combat progress; transitions to idle when target HP drops to 0 or target is cleared.
- [x] Honors emergency stop (`END` key) and focus loss immediately by halting combat inputs.
- [x] Automated unit tests verify combat state machine transitions under synthetic world state feeds.
- [x] All user-visible logs, status messages, and errors exist in German and English.

## Out of scope

- Complex obstacle avoidance in 3D terrain.
- Loot collection (covered in [US-009](US-009-reactive-loot-controller.md)).

## Verification

- Automated: Unit tests covering state machine transitions (`IDLE` -> `TARGETING` -> `ENGAGING` -> `FIGHTING` -> `TARGET_DEAD`); `./scripts/check.ps1`.
- Manual (Windows): Run combat loop in test environment with active game client.
