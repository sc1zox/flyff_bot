---
id: BUG-010
title: Combat targeting thrashing, false floor clicks, and missing stuck engagement break timeout
status: resolved
severity: high
created: 2026-08-17
updated: 2026-08-17
---

# BUG-010: Combat targeting thrashing, false floor clicks, and missing stuck engagement break timeout

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch the application via `uv run python -m flyff_bot ui` with YOLO mob detection active and at least one mob visible on screen.
2. Start autonomous farming (**"Starten"** / **"Start"**).
3. Observe the bot behavior when target verification fails or is unconfirmed (e.g. target header anchor template score is below threshold, or the clicked target was already dead / unselectable):
   - `CombatController` enters `CombatMode.TARGETING` and issues a click on the mob center coordinates.
   - `TargetVerifier` evaluates the target region and returns `TargetStatus.NO_TARGET` or `WRONG_TARGET` (e.g. anchor score `0.53 / 0.90` or missing target bar).
   - After `target_acquisition_grace_seconds` (0.8s) expires without valid target confirmation, `CombatController` abruptly resets to `CombatMode.IDLE`.
   - `FarmingOrchestrator._advance` immediately reverts `_mode` from `FarmingMode.TARGETING` back to `FarmingMode.SEARCHING`.
   - In the very next tick in `SEARCHING`, the same visible mob candidate is still present in YOLO detections. `CombatController.step` immediately selects it and returns `CombatMode.TARGETING`, issuing another click at the same location.
4. Observe the resulting loop:
   - The bot rapidly oscillates between `Kämpft` (`TARGETING`) and `Suche` (`SEARCHING`) every ~0.8s without ever attacking or killing the mob.
   - If the mob died or is unselectable, the cursor repeatedly clicks on the ground/corpse.
   - If the player character gets stuck or the target is obstructed/unreachable during engagement, there is no maximum engagement break timeout (10.0s break) to abort the fight and trigger search/recovery.

## Expected behavior

1. **Target Acquisition Stability & Thrashing Prevention:**
   - When a mob candidate is clicked and engaged, the state machine must not erraticly oscillate back and forth between search and combat states every fraction of a second.
   - If target acquisition fails or target verification does not confirm within the grace period, or if the mob is unresponsive/dead, the controller must record a transient failure or cooldown/blacklist for that mob detection to prevent immediate repeated floor clicking at the same location.
2. **Stuck Combat Engagement Break Timeout (10s):**
   - Similar to navigation stall detection, `CombatController` / `FarmingOrchestrator` must enforce a maximum combat engagement timeout (10.0 seconds).
   - If engaged in combat without target HP reduction, target death, or kill count increment within 10.0 seconds (stuck engagement), the controller must break/abort the engagement, reset target state, and transition cleanly to search/navigation recovery.
3. **Clear Dashboard Status & Reason:**
   - When an engagement breaks due to the 10s stuck timeout or failed acquisition, the dashboard / target debug reflects the timeout reason cleanly rather than flickering.

## Actual behavior

- `CombatController` immediately resets to `IDLE` after 0.8s on unverified targets.
- `Orchestrator` immediately re-picks the same visible mob on the very next tick, leading to high-frequency thrashing between `SEARCHING` and `TARGETING`.
- The bot repeatedly clicks the floor where a dead or unverified mob is located.
- No 10s stuck combat engagement timeout exists to break out of deadlocks.

## Impact and frequency

- Impact: The bot gets stuck in an infinite click loop on unverified or dead mobs, clicking the floor and failing to farm or rotate camera.
- Frequency: Consistently reproducible whenever target header anchor verification fails or dead mob corpses remain detected by YOLO.

## Resolution

`CombatController` records a time-bounded spatial lockout (`TargetLockout`) for the engaged
client-space location on every terminal exit that is not an in-progress fight: acquisition grace
expiry, mid-fight loss of the target header, the new engagement timeout, an undamaged
`TARGET_LOST`, and a confirmed `TARGET_DEAD`. `_best_candidate()` purges expired entries and skips
any mob whose center falls inside `target_lockout_radius_pixels` (default 50 px) of an active
lockout for `target_lockout_seconds` (default 4.0 s), so the corpse or unverifiable mob cannot be
re-clicked on the next tick. Lockouts deliberately survive `_reset()`, which runs on exactly those
failure paths.

`engagement_timeout_seconds` (default 10.0 s) measures elapsed time since the last observed HP
decrease, falling back to the moment the target header was first confirmed. When it expires the
engagement breaks, registers a lockout, and returns to `CombatMode.IDLE`. The kill-count and
HP-zero checks run before the timeout check, so a tick that confirms a kill is never pre-empted.

`FarmingOrchestrator` no longer resets the staged-search idle timeout when a target is merely
clicked — only a verified engagement (`ENGAGING`/`FIGHTING`) does. Without this, the 4.0 s lockout
retry cycle stayed just under the 5.0 s search idle timeout and camera recovery never ran.

`CombatDecision.break_reason` carries a typed `EngagementBreakReason`
(`ACQUISITION_TIMEOUT`, `TARGET_UNVERIFIED`, `ENGAGEMENT_TIMEOUT`) that the orchestrator latches and
publishes on `DashboardUpdate.engagement_break`; the target debug panel renders it as one localized
sentence, cleared when the next engagement starts. It is not carried on `WorldState` /
`SelectedTarget`, which would re-create the US-024 spurious `TARGET_CHANGED` problem.

### Known limitations

- A lockout anchors a client-space point, not a world object. `_track_engaged_position()` follows the
  nearest allowed detection inside the lockout radius during the fight so the lockout lands on the
  corpse rather than the original click point, but this is a proximity heuristic with no detection
  identity.
- Camera rotation invalidates the screen-space mapping, so an active lockout can briefly shadow a
  different live mob that moves into that screen position. The 4.0 s expiry bounds this.

## Regression verification

- [x] Automated unit tests in `tests/unit/test_combat_controller.py` and
  `tests/unit/test_orchestrator.py` asserting no instant re-acquisition thrashing on failed target
  verification and verifying the 10.0s stuck combat engagement break timeout. (The original
  criterion named `tests/unit/test_controllers.py`; combat tests live in `test_combat_controller.py`.)
- [ ] Manual Windows check verifying the bot does not spam-click dead mobs on the floor and breaks
  out of stuck engagements after 10s. **Not performed — this fix was developed on Linux with no
  Flyff client available.**
- [x] Related durable documentation in `docs/wiki/` and `docs/bugs/` is current.
