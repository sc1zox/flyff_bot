---
id: US-039
title: Combat obstacle stall detection and adaptive re-navigation
status: completed
created: 2026-08-18
updated: 2026-08-19
---

# US-039: Combat obstacle stall detection and adaptive re-navigation

## Story

As a **bot operator running autonomous combat farming**,
I want **the bot to detect when the character is blocked by terrain or obstacles during target approach, abort stalled attack attempts, re-position via camera rotation and roaming, and blacklist repeatedly unreachable mobs for 30s**,
so that **the bot does not get permanently stuck running against obstacles towards unreachable monsters and can autonomously recover and continue farming**.

## Context and assumptions

- In the Entropia Flyff PServer (`neuz.exe`) client, clicking a mob causes the game client to automatically walk/run the player character towards the target.
- If an obstacle (tree, rock, fence, wall, terrain elevation) blocks the direct path, the character continues its running animation in place against the obstacle.
- Currently, `StallDetector` in [`flyff_bot.features.navigation.tracking`](file:///i:/coding%20projects/flyff_bot/src/flyff_bot/features/navigation/tracking.py) only samples motion when `movement_commanded` is True, which is only set when the bot explicitly sends the `W` key during navigation or roaming. During `TARGETING` and `COMBAT`, the character is moved by the game client after a mouse click, so `movement_commanded` remains False and `StallDetector` never triggers a stall.
- In [`CombatController`](file:///i:/coding%20projects/flyff_bot/src/flyff_bot/features/automation/controllers.py), `engagement_timeout_seconds` (default 10.0s) triggers when no HP reduction occurs, but the resulting `TargetLockout` is only 4.0s. If the mob is still visible and the bot did not move, `CombatController._best_candidate()` picks the same mob again after 4.0s, causing the character to repeatedly run against the obstacle (> 20s stuck loop).
- Links:
  - [Architecture](file:///i:/coding%20projects/flyff_bot/docs/wiki/architecture.md)
  - [BUG-009: WASD movement tracking heading error and obstacle stall detection failure against terrain](file:///i:/coding%20projects/flyff_bot/docs/bugs/fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md)
  - [BUG-010: Combat targeting thrashing and stuck engagement timeout](file:///i:/coding%20projects/flyff_bot/docs/bugs/fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md)
  - [US-015: Idle timeout and search navigation](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-015-idle-timeout-and-search-navigation.md)
  - [US-019: Intelligent pathing and spawn heatmap](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-019-intelligent-pathing-and-spawn-heatmap.md)
  - [US-031: Target selection cooldown and dead mob spatial lockout](file:///i:/coding%20projects/flyff_bot/docs/user-stories/completed/US-031-target-cooldown-and-dead-mob-blacklist.md)

## Acceptance criteria

- [x] Given an ongoing target approach or engagement in `CombatMode.TARGETING` or `CombatMode.FIGHTING` without dealt damage, `StallDetector` (or an approach stall tracker) actively samples peripheral frame difference to detect if the character is running in place against an obstacle.
- [x] Given a detected obstacle stall or an engagement timeout (10.0s) without damage dealt during combat approach, `CombatController` / `FarmingOrchestrator` cleanly breaks the engagement with a typed reason (e.g. `EngagementBreakReason.OBSTACLE_STALL` or `ENGAGEMENT_TIMEOUT`).
- [x] On the first stall against a target, the bot does not immediately apply a long blacklist, but initiates adaptive re-navigation / re-positioning: executing camera rotation and roaming movement steps to clear the obstacle and re-orient the viewpoint.
- [x] If an attack attempt against the same target location stalls or times out repeatedly (a second consecutive stall/timeout on the same mob candidate), the mob's position is placed on an extended blacklist/lockout for 30.0 seconds so the bot ignores it and pursues other targets.
- [x] If navigation/spatial mapping is active, the stall location is registered in `SpatialMap` to penalize the blocked path.
- [x] All failure and cancellation behaviors (lost foreground focus, emergency stop via `END`/`Escape`) immediately halt re-navigation and combat input.
- [x] All user-visible debug text, break reasons, and dashboard statuses are synchronized in German and English locale files (`src/flyff_bot/locales/*.json`).

## Implementation notes

- The combat approach stall is sampled by `FarmingOrchestrator` rather than by
  `PathingController`: the session is the only layer that knows the game client is walking the
  character after a target click. It prefers the minimap-measured speed when pathing supplies one
  and falls back to the peripheral frame difference otherwise.
- Sampling stops once `CombatController.damage_dealt` is true, because a character standing in
  attack range produces the same motionless scenery a blocked approach does.
- `OBSTACLE_STALL` and `ENGAGEMENT_TIMEOUT` share one strike counter (`UNREACHABLE_BREAK_REASONS`):
  both mean the approach never arrived. "The same mob candidate" is judged by client-space proximity
  within `target_lockout_radius_pixels`, exactly as `TargetLockout` already does, because an
  engagement carries no detection identity (BUG-010).
- Re-positioning reuses `SearchController` as a bounded rotate-then-roam sweep rather than
  introducing a second controller for the same behavior.
- Consequence: a fight that lands no damage for `stall_timeout_seconds` (5.0 s) now breaks as an
  obstacle stall instead of waiting out the 10.0 s engagement timeout. Both reasons take the same
  recovery path and the same strike, so the session simply recovers sooner.

## Out of scope

- Direct 3D mesh navmesh extraction or reading in-game geometry from client memory.
- Dynamic jumping over obstacles.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_combat_controller.py` verifying stall/timeout break handling, first-time re-positioning transition, and 30s blacklist on repeated consecutive stalls.
  - Unit tests in `tests/unit/test_stall_detector.py` verifying that stall detection operates during combat approach.
  - Integration tests in `tests/unit/test_orchestrator.py` asserting proper transition from combat stall to search/roaming re-positioning.
- Manual (Windows):
  - Run autonomous farming near obstacles (trees, rocks, fences) in Flyff.
  - Target a mob obstructed by terrain and verify that after running against the obstacle, the bot detects the stall within 10s, aborts the attack, rotates camera / roams to a new position, and blacklists the mob for 30s if obstructed again.
