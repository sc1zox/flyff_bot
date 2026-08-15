---
id: US-008
title: Reactive combat controller and target engagement
status: draft
created: 2026-08-15
updated: 2026-08-15
---

# US-008: Reactive combat controller and target engagement

## Story

As a player using permitted automation, I want the bot to select valid target mobs, navigate within combat range, and execute attack/skill rotations with post-action verification, so that monsters are fought efficiently without manual button pressing.

## Context and assumptions

- Source: [Target architecture proposal](../sources/2026-08-15-target-architecture-proposal.md).
- Depends on [US-006](completed/US-006-target-architecture-bootstrap.md) (Architecture/Controllers) and [US-007](US-007-perception-worldstate-feed.md) (WorldState Feed).
- Win32 `SendInput` is used for target selection (e.g. `TAB` or screen click) and attack actions (e.g. `1`-`9` hotkeys).
- Post-action visual verification: attacks are confirmed by observing target HP decrease or combat animations.

## Acceptance criteria

- [ ] `CombatController` selects the best candidate mob from `WorldState.visible_mobs` (closest / valid type).
- [ ] Issues target selection action and verifies target lock via `TargetStatus.VALID_TARGET`.
- [ ] Executes attack/skill actions mapped to key bindings with configurable cooldowns.
- [ ] Verifies ongoing combat progress; transitions to idle when target HP drops to 0 or target is cleared.
- [ ] Honors emergency stop (`END` key) and focus loss immediately by halting combat inputs.
- [ ] Automated unit tests verify combat state machine transitions under synthetic world state feeds.
- [ ] All user-visible logs, status messages, and errors exist in German and English.

## Out of scope

- Complex obstacle avoidance in 3D terrain.
- Loot collection (covered in [US-009](US-009-reactive-loot-controller.md)).

## Verification

- Automated: Unit tests covering state machine transitions (`IDLE` -> `TARGETING` -> `ENGAGING` -> `FIGHTING` -> `TARGET_DEAD`); `./scripts/check.ps1`.
- Manual (Windows): Run combat loop in test environment with active game client.
