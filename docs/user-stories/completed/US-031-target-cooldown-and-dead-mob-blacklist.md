---
id: US-031
title: Target selection cooldown and dead mob spatial lockout
status: completed
created: 2026-08-17
updated: 2026-08-17
---

# US-031: Target selection cooldown and dead mob spatial lockout

## Story

As a **bot operator running autonomous combat farming**,
I want **the combat controller to temporarily blacklist recently defeated or failed mob target locations with a spatial lockout cooldown**,
so that **the bot does not repeatedly re-click dying mob corpses or empty ground during death animations and acquisition timeouts, preventing combat thrashing and wasted clicks**.

## Context and assumptions

- In Flyff, when a monster reaches 0 HP or is defeated, its 3D death animation plays for 1.5 to 3.5 seconds before the corpse fades and despawns.
- During this window, the YOLO object detector continues to detect the monster's visual bounding box and classifies it as a live visible candidate.
- In [`CombatController`](file:///home/sc1zox/code/flyff_bot/src/flyff_bot/features/automation/controllers.py), `_best_candidate()` currently evaluates all `state.visible_mobs` solely based on distance to screen center without checking if a mob at that screen position was just killed or failed target verification.
- When the bot clicks a dead/dying mob, no target header appears (or target verification fails/times out), causing `CombatController` to reset to `IDLE` after the grace period (0.8s) and immediately re-select the same corpse in the next frame.
- A time-based spatial lockout (default cooldown of 4.0 seconds within a bounded pixel radius around the last engaged target center) ensures defeated or unselectable mobs are ignored by `_best_candidate()` until they despawn.
- Links:
  - [Architecture](file:///home/sc1zox/code/flyff_bot/docs/wiki/architecture.md)
  - [BUG-010: Combat targeting thrashing and stuck engagement timeout](file:///home/sc1zox/code/flyff_bot/docs/bugs/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md)
  - [US-008: Reactive combat controller](file:///home/sc1zox/code/flyff_bot/docs/user-stories/completed/US-008-reactive-combat-controller.md)
  - [US-023: Reliable combat targeting and kill verification](file:///home/sc1zox/code/flyff_bot/docs/user-stories/completed/US-023-reliable-combat-targeting-and-kill-verification.md)

> Delivered by [BUG-010](file:///home/sc1zox/code/flyff_bot/docs/bugs/fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md),
> which needed the same spatial lockout to stop targeting thrashing.

## Acceptance criteria

- [x] Given a monster that transitions to `CombatMode.TARGET_DEAD` or fails target acquisition after `target_acquisition_grace_seconds`, its center coordinate is registered into an active target lockout blacklist in `CombatController` with a timestamp and expiration deadline (default lockout duration: 4.0 seconds).
- [x] Given `CombatController._best_candidate()`, any `VisibleMob` whose center coordinate falls within a configured spatial tolerance radius (e.g. 50 pixels) of an actively locked-out target location is excluded from candidate selection until its lockout expires.
- [x] Expired lockout entries are automatically purged during `step()` or when querying candidates to prevent unbounded memory growth.
- [x] Lockout state is cleared upon session reset. No explicit clear on emergency stop was added:
  `FarmingOrchestrator.emergency_stop()` latches the session permanently, so the next session always
  builds a fresh `CombatController` with an empty lockout list. A public clear would have been dead
  code.
- [x] If all visible mobs on screen are currently locked out, `_best_candidate()` returns `None`, allowing `FarmingOrchestrator` to seamlessly transition into search/rotation or navigation without clicking the floor.
- [x] Failure and cancellation behavior is defined: lost focus or emergency stop immediately halts combat without retaining stale locks on next fresh session start.

## Out of scope

- Persistent 3D world-coordinate object tracking across full 360-degree camera rotations.
- Custom optical flow tracking or YOLO model retraining for dead mob animation frames.

## Verification

- Automated:
  - Done. Unit tests in `tests/unit/test_combat_controller.py` verifying that defeated mobs and acquisition timeouts register a lockout, subsequent candidate selection ignores mobs within the lockout radius, and locks expire after the configured duration.
  - Done. Integration tests in `tests/unit/test_orchestrator.py` verifying that the orchestrator transitions to search when all visible mobs are locked out rather than re-clicking corpses.
- Manual (Windows) — not performed, developed on Linux without a Flyff client:
  - Defeat a mob in Flyff and observe that the cursor does not click on the dying mob corpse while it plays its death animation, immediately targeting the next live mob or initiating search rotation.
