---
id: BUG-010
title: Combat targeting thrashing, false floor clicks, and missing stuck engagement break timeout
status: reported
severity: high
created: 2026-08-17
updated: 2026-08-17
---

# BUG-010: Combat targeting thrashing, false floor clicks, and missing stuck engagement break timeout

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff Universe / Flyff PC Desktop Client

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

## Regression verification

- [ ] Automated unit tests in `tests/unit/test_controllers.py` and `tests/unit/test_orchestrator.py` asserting no instant re-acquisition thrashing on failed target verification and verifying the 10.0s stuck combat engagement break timeout.
- [ ] Manual Windows check verifying the bot does not spam-click dead mobs on the floor and breaks out of stuck engagements after 10s.
- [ ] Related durable documentation in `docs/wiki/` and `docs/bugs/` is current.
