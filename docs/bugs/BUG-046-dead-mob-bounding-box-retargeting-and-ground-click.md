---
id: BUG-046
title: Dead mob YOLO bounding box retargeting and false ground movement on kill
status: reported
severity: high
created: 2026-08-31
updated: 2026-08-31
---

# BUG-046: Dead mob YOLO bounding box retargeting and false ground movement on kill

## Environment

- Windows version: Windows 11 x64
- Python version: 3.14 (.venv)
- Application revision: main
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch the bot with YOLO mob perception enabled and start autonomous farming.
2. Target and successfully defeat a monster (target HP reaches 0 and/or kill counter increments).
3. Observe the bot behavior during the monster's 2–4 second 3D death animation:
   - The YOLO detector continues detecting the dying mob corpse bounding box.
   - `CombatController` transitions via `TARGET_DEAD` / `confirm_kill`, resetting to `CombatMode.IDLE`.
   - On the very next tick, `_eligible_candidates` evaluates the dying mob's bounding box.
   - Because spatial lockout uses a single-point 15-pixel radius Euclidean distance (`DEFAULT_TARGET_LOCKOUT_RADIUS_PIXELS = 15`), any bounding box center jitter or death animation position shift exceeds 15px, bypassing the lockout.
   - The bot selects the dying mob candidate and issues a left-click at the mob's center.
   - In Flyff, clicking an unselectable dying mob / corpse registers as a ground click, causing the player character to start running towards the corpse location.
   - After `target_acquisition_grace_seconds` (0.8s) expires without a target header, `CombatController` breaks engagement with `ACQUISITION_TIMEOUT`.

## Expected behavior

1. **Bounding Box Overlap Lockout (IoU / Spatial Overlap):**
   - When a monster is confirmed defeated (`TARGET_DEAD` via HP = 0 or kill counter increment), its 2D screen bounding box (`VisibleMob.x, y, width, height`) must be registered into the lockout blacklist.
   - Subsequent candidate filtering (`_eligible_candidates`) must exclude any visible mob candidate whose 2D bounding box significantly overlaps (Intersection over Union / IoU threshold or center containment) with an active lockout box.
2. **Lockout Duration & ML-Tuning Configurability:**
   - The default lockout duration for defeated mob bounding boxes must be 3.0 seconds (covering the death animation duration).
   - The duration must be configurable through `TacticalParameterSpace` (`target_lockout_seconds`) so that ML / tactical tuning can adjust it.
3. **No False Ground Movement:**
   - With the dying mob bounding box locked out, if no other valid live mobs are on screen, the bot must not click the floor and instead transition seamlessly to camera search or NavMesh pathing.

## Actual behavior

- In ~80% of kills, the bot immediately re-clicks the dying mob bounding box.
- The left-click hits the ground beneath the unselectable corpse, causing the player character to walk/run towards the dead mob.
- `CombatController` experiences acquisition timeouts (`ACQUISITION_TIMEOUT`) and erratic movement towards dead mob locations.

## Impact and frequency

- Impact: Severely degrades farming efficiency, causes unnecessary character movement towards dead mobs, delays target search/patrol, and increases detection risk due to erratic floor clicking.
- Frequency: Occurs in ~80% of confirmed monster kills while death animations play.

## Regression verification

- [ ] A failing automated unit test in `tests/unit/test_combat_controller.py` reproduces the issue: a visible mob candidate overlapping a recently killed mob's bounding box (with center shifted >15px) is rejected during the 3.0s lockout window.
- [ ] The check passes after implementing bounding box IoU / overlap lockout and ML-configurable duration.
- [ ] Related durable documentation in `docs/wiki/` and `docs/bugs/` is current.
