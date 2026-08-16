---
id: BUG-009
title: WASD movement tracking heading error and obstacle stall detection failure against terrain
status: reported
severity: high
created: 2026-08-16
updated: 2026-08-16
---

# BUG-009: WASD movement tracking heading error and obstacle stall detection failure against terrain

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff Universe / Flyff PC Desktop Client

## Reproduction

1. Launch the application via `uv run python -m flyff_bot ui`.
2. Enable the 2D path map (**"Wegkarte anzeigen"** / **"Show path map"**).
3. Observe movement tracking during both autonomous navigation and manual character movement:
   - When pressing `A` or `D`, the character turns in-game, but `MovementTracker` models `A`/`D` as strafing translation instead of heading rotation.
   - When pressing `S`, backward movement is completely ignored by `MovementTracker`.
4. Walk the character against a solid obstacle (e.g. tree, fence, rock, wall) while moving forward (`W`).
5. Observe the stall detection and map behavior:
   - In-game, the character model continues its running animation in place, producing continuous frame pixel differences in the center screen area.
   - `StallDetector.observe` samples the entire frame including the character running animation, causing `motion` to stay above `motion_threshold` even though world coordinates do not change.
   - If movement commands pause between ticks, the `_consecutive` sample counter immediately resets to 0, preventing the stall threshold from ever being met.
   - The bot fails to detect the obstacle stall, never registers the stall node on the spatial map, and does not initiate retreat (`RETREATING`) to the safe waypoint.

## Expected behavior

1. **WASD Movement Model Alignment:**
   - In Flyff default controls, `A` turns the character left (rotates heading counter-clockwise) and `D` turns the character right (rotates heading clockwise). `MovementTracker.apply` must update `_heading_degrees` rather than translating along a strafe vector.
   - `VIRTUAL_KEY_S` (0x53) must be integrated into `MovementTracker.apply` to translate backward along `-forward_vector`.
   - Forward movement (`W`), backward movement (`S`), and turning (`A`/`D`) must accurately update the dead-reckoning position and heading.
2. **Robust Obstacle & Stall Detection:**
   - Stall detection must mask out or exclude the central viewport region occupied by the player character's running animation so that walking against walls/obstacles does not trigger false motion.
   - Frame difference analysis must focus on the outer scenery, terrain, or background flow to detect genuine camera/world movement.
   - Stall detection must support a configurable timeout / threshold (default 5.0 seconds of sustained forward movement without scene parallax).
   - Non-commanded tick pauses must not instantly reset the accumulated stall streak if the character is in an ongoing travel/roam phase.
3. **Obstacle Registration & Safe Retreat:**
   - Upon detecting a stall, the controller must record the obstacle cell as a stall node (`_register_stall`), mark adjacent edges as stalled, and trigger safe retreat (`RETREATING`) to the last verified safe waypoint (`_safe_waypoint`).
   - The spatial route planner must avoid stalled cells during subsequent pathing.
4. **2D Path Inspector Visualization:**
   - The 2D map widget must accurately render all legend elements:
     - Player position and heading beam/cone.
     - Breadcrumb trail of visited cells.
     - Stalled obstacle cells/edges in distinct red.
     - Safe retreat waypoints in green.
     - Active planned routes in purple.
     - Leash boundary circle.

## Actual behavior

- `MovementTracker.apply` treated `A` and `D` as strafing lateral translations rather than heading rotations, causing severe position drift when turning.
- `VIRTUAL_KEY_S` (backward movement) was unhandled and silently dropped.
- `StallDetector.observe` computed frame difference over the entire screen including the animated player character, preventing stall detection while walking against obstacles.
- `StallDetector` reset `_consecutive = 0` whenever `movement_commanded` was False on any intermediate tick, preventing multi-sample stall accumulation.
- Obstacles were neither detected nor visualized as stall markers on the 2D path map, and the bot remained stuck running against obstacles without retreating.

## Impact and frequency

- Impact: High. Navigation position tracking drifts significantly during turns, and the bot becomes permanently stuck against obstacles without triggering obstacle avoidance or retreat.
- Frequency: 100% reproducible when moving with A/D, S, or running against terrain obstacles.

## Regression verification

- [ ] Unit tests in `tests/unit/test_tracking.py` verify heading rotation on `A`/`D`, backward translation on `S`, and correct forward translation on `W`.
- [ ] Unit tests in `tests/unit/test_stall_detector.py` verify that center character animation with stationary background triggers stall detection after the configurable threshold (5.0s).
- [ ] Unit tests in `tests/unit/test_pathing.py` verify that stall detection triggers obstacle cell registration and retreat to safe waypoint.
- [ ] Unit tests in `tests/unit/test_path_inspector.py` verify proper rendering of all legend elements (player, trail, stall hazards, safe nodes, routes).
- [ ] `./scripts/check.ps1` passes cleanly.
