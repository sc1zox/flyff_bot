---
id: BUG-009
title: WASD movement tracking heading error and obstacle stall detection failure against terrain
status: resolved
severity: high
created: 2026-08-16
updated: 2026-08-17
---

# BUG-009: WASD movement tracking heading error and obstacle stall detection failure against terrain

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

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

- [x] Unit tests in `tests/unit/test_tracking.py` verify heading rotation on `A`/`D`, backward translation on `S`, and correct forward translation on `W`.
- [x] Unit tests in `tests/unit/test_stall_detector.py` verify that center character animation with stationary background triggers stall detection after the configurable threshold (5.0s).
- [x] Unit tests verify that stall detection triggers obstacle cell registration and retreat to safe waypoint. Deviation: these live in the existing `tests/unit/test_path_planning.py`, which already covers `PathingController`, instead of a near-duplicate `tests/unit/test_pathing.py`.
- [x] Unit tests in `tests/unit/test_path_inspector.py` verify proper rendering of all legend elements (player, trail, stall hazards, safe nodes, routes).
- [x] `./scripts/check.ps1` passes cleanly. Deviation: PowerShell is unavailable in the development environment, so the five gate steps (`uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`) were run directly; all pass (293 passed, 7 skipped, 89.68% coverage).

## Resolution notes

- `MovementTracker.apply` turns on `A`/`D` through the shared `ROTATION_VIRTUAL_KEYS` set and walks
  backwards on `S`; `MovementModel.strafe_speed_units_per_second` was replaced by
  `backward_speed_units_per_second` because no caller strafes any more.
- `StallDetector` accumulates motionless seconds against `StallConfig.stall_timeout_seconds`
  (default `5.0`) instead of counting consecutive samples, measures motion only outside a centred
  player-model mask, holds the accumulator across non-commanded ticks within
  `movement_grace_seconds`, and clamps a single sample to `MAXIMUM_STALL_SAMPLE_SECONDS`.
- The pre-existing `test_visible_progress_or_idle_ticks_clear_the_stall_streak` asserted the
  instant-reset behaviour this report requires to stop, so it was replaced by the grace-window
  tests in `tests/unit/test_stall_detector.py` rather than preserved.
- Two follow-on defects surfaced while verifying the retreat path and were fixed with it:
  `PathingController._register_stall` now resets the detector so `WorldState.is_stuck` marks only
  the registration tick instead of latching through the whole retreat, and
  `_remember_safe_waypoint` refuses to promote a cell with recorded stalls, which previously made
  the bot retreat into the obstacle cell it had just fled.
- Criterion 4 needed no widget change: US-020 already renders every legend element. The gap was
  pixel-level assertions, now covered by
  `test_rendered_stall_cell_route_and_safe_waypoint_are_readable` (stall marker, purple route,
  green safe node, leash ring) alongside the pre-existing player-marker, trail-border, and legend
  glyph/color tests.
- Known limitation: the centre mask excludes the player model but not the HUD bands, so animated
  HUD elements can still mask a genuine stall. The mask fractions are estimates and have not been
  calibrated against measured client frames, and `DEFAULT_MOTION_THRESHOLD` was left at `1.5`
  although it was originally chosen against a full-frame mean rather than the masked population.
