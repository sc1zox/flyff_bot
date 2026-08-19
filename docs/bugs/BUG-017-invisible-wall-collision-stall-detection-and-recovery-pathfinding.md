---
id: BUG-017
title: Invisible wall collision stall detection latency and recovery pathfinding loop
status: reported
severity: high
created: 2026-08-19
updated: 2026-08-19
---

# BUG-017: Invisible wall collision stall detection latency and recovery pathfinding loop

## Environment

- Windows version: Windows 10/11
- Python version: 3.14.7 (.venv)
- Application revision: HEAD
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch autonomous farming (`uv run python -m flyff_bot ui`) in an area featuring terrain boundaries, elevation ridges, or invisible map barriers (e.g. Garden of Rhisis / Darkon giant mushroom area).
2. The bot detects and targets a monster located across or behind an invisible collision wall.
3. The game client commands character movement toward the target, running continuously into the invisible collision wall with zero progress in world distance.
4. Observe the bot behavior and state machine transitions:
   - The bot remains in `FarmingMode.COMBAT` / `CombatMode.TARGETING` running in place against the invisible barrier.
   - Stall detection latency is too high (taking 5–10 seconds of running into the wall before triggering `OBSTACLE_STALL` or `ENGAGEMENT_TIMEOUT`).
   - When the engagement breaks, the repositioning sweep (`SearchController` rotate-and-roam) often moves the character directly back toward the same impassable barrier or immediately re-targets the unreachable monster.
   - Repeated collisions cause the bot to cycle between `COMBAT` and `SEARCHING` in place, or eventually trigger emergency teleport (`Blinkwing`), which acts as an unneeded bandaid instead of resolving the root pathfinding/stall cause.

## Expected behavior

1. **Fast and Responsive Collision / Stall Detection:**
   - The bot must detect zero-progress collisions and obstacle stalls against invisible walls much faster (e.g. using live memory coordinate velocity / delta tracking or rapid minimap odometry) rather than waiting out a long 5–10 second delay.
2. **Adaptive Obstacle Evasion and Pathfinding:**
   - Once a collision/stall against an invisible wall or obstacle heading is confirmed, the pathfinding and repositioning logic must intelligently evade the blocked heading (e.g. vector repulsion / directional blacklist) rather than walking straight back into the wall.
3. **Prevention of Emergency Teleport as a Masking Mechanism:**
   - Emergency teleport should remain a true last-resort safety measure; local navigation and approach loops must autonomously resolve terrain barriers efficiently without relying on emergency teleport bandaids.

## Actual behavior

- The character runs indefinitely against invisible collision walls during combat approach.
- The state machine repeatedly re-enters combat against unreachable mobs on the other side of invisible barriers.
- Stall detection and repositioning recovery are too slow and inefficient, severely degrading farming yield and triggering unnecessary emergency teleports.

## Impact and frequency

- **Impact:** High. The bot spends significant active farming time blocked against invisible collision geometry, failing to defeat targets and repeatedly entering stalled combat cycles.
- **Frequency:** Consistently occurs whenever farming in areas with non-trivial map boundaries, elevation ledges, or invisible collision meshes.

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
