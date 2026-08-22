---
id: US-060
title: Combat class profiles, responsive direct targeting, and spatial lockout minimization
status: completed
created: 2026-08-20
updated: 2026-08-22
---

# US-060: Combat class profiles, responsive direct targeting, and spatial lockout minimization

## Story

As a **Flyff bot operator playing melee or ranged character classes**,
I want **the bot to support combat class profiles with class-appropriate engagement distances, direct targeting when line-of-sight is unobstructed, and a minimized 1.0-second spatial lockout**,
so that **monsters in view are immediately targeted without unnecessary approach delays or camera turning thrashing, while dense monster packs remain selectable after a kill**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [docs/wiki/architecture.md](../wiki/architecture.md) & [docs/wiki/glossary.md](../wiki/glossary.md).
  - [docs/user-stories/completed/US-031-target-cooldown-and-dead-mob-blacklist.md](completed/US-031-target-cooldown-and-dead-mob-blacklist.md): Spatial lockout and dead mob blacklist.
  - [docs/user-stories/completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md](completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md): NavMesh-aware targeting and autonomous funnel approach.
  - [docs/bugs/fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md](../bugs/fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md): Combat targeting thrashing.
- Currently, [CombatConfig.target_lockout_seconds](file:///I:/coding%20projects/flyff_bot/src/flyff_bot/features/automation/controllers.py#L40) is 4.0 seconds with a 50-pixel radius ([DEFAULT_TARGET_LOCKOUT_RADIUS_PIXELS = 50](file:///I:/coding%20projects/flyff_bot/src/flyff_bot/features/automation/controllers.py#L41)), which causes live monsters standing near a recently killed mob to be ignored for 4 seconds.
- Currently, [FarmingOrchestrator._advance()](file:///I:/coding%20projects/flyff_bot/src/flyff_bot/features/automation/orchestrator.py#L607-L621) unconditionally blocks direct mob clicks whenever NavMesh is available and enters FarmingMode.APPROACHING, running with WASD and camera adjustments until within [DEFAULT_NAVMESH_ENGAGEMENT_DISTANCE_UNITS = 3.0](file:///I:/coding%20projects/flyff_bot/src/flyff_bot/features/navigation/pathing.py#L58) units (melee contact), even when playing a ranged class or when a direct line-of-sight path exists.
- In addition, transitioning from CombatMode.TARGET_DEAD through FarmingMode.RECONCILING to FarmingMode.SEARCHING causes a 1-tick delay in [CombatController](file:///I:/coding%20projects/flyff_bot/src/flyff_bot/features/automation/controllers.py#L406-L407) before candidate search resumes, which allows pathing/search rotation to briefly fire before a target is picked.

## Acceptance criteria

- [x] **Lockout Parameter Minimization:**
  - DEFAULT_TARGET_LOCKOUT_SECONDS is reduced to 1.0 second (from 4.0 seconds).
  - DEFAULT_TARGET_LOCKOUT_RADIUS_PIXELS is reduced to 15 pixels (from 50 pixels).
  - Defeated mob corpse locations remain blocked for 1.0 s to prevent immediate death-animation re-clicking, but live monsters located $\ge 15$ pixels away are immediately eligible for candidate selection.
- [x] **Combat Class Profiles & Engagement Distance Configuration:**
  - A CombatClassProfile model/enum is defined with presets:
    - **Melee classes** (e.g. *Mercenary, Blade, Knight, Assist, Billposter, Ringmaster*): Default engagement distance 3.0 units.
    - **Ranged classes** (e.g. *Acrobat, Ranger, Bow Jester, Magician, Psykeeper, Elementor*): Default engagement distance 15.0 units.
    - **Custom**: User-adjustable engagement distance spinbox.
  - The UI dashboard includes a Combat Class dropdown and an engagement distance setting that updates the orchestrator and pathing controller dynamically.
- [x] **Responsive Direct Targeting & Obstacle-Aware Approach:**
  - When a candidate mob is selected:
    - **Ranged Profile:** If the target is within the configured engagement distance (e.g. $\le 15.0$ units) and reachable, dispatch the direct click immediately without entering FarmingMode.APPROACHING.
    - **Melee Profile with Clear Path:** If the NavMesh route to the target is a direct straight segment (no intermediate obstacle waypoints), dispatch the direct click immediately and allow the client to close distance directly.
    - **Obstacle-Obstructed Path:** If the NavMesh route requires multi-waypoint navigation around geometry/obstacles, enter FarmingMode.APPROACHING and navigate using Funnel waypoints until engagement distance is reached before dispatching the click.
- [x] **Seamless Post-Kill Candidate Selection:**
  - When resetting from CombatMode.TARGET_DEAD or RECONCILING into SEARCHING, candidate evaluation runs immediately in the same tick without a blank idle tick, preventing premature pathing/search camera rotation when valid mobs are in view.
- [x] **Safety Boundaries & Failure Modes:**
  - Focus loss, manual pause, and emergency stops (END / Escape) immediately abort active approaches and cancel held movement keys.
  - If a direct-clicked approach stalls on an unmodeled obstacle, the existing obstacle stall detector triggers evasion and re-navigation as designed.
- [x] **Localization:**
  - All new user-visible UI labels, combat class names, tooltips, and log events are synchronized in German (src/flyff_bot/locales/de.json) and English (src/flyff_bot/locales/en.json).

## Out of scope

- Class-specific combat skill rotations (handled in existing combat binding rotation settings).
- Automatic character class memory reading from process memory.
- Dynamic kiting or retreating movement for ranged classes.

## Verification

- Automated:
  - Unit tests in `tests/unit/test_combat_controller.py` verifying the 1.0s / 15px lockout behavior and dense mob selection.
  - Unit tests in `tests/unit/test_orchestrator.py` verifying direct click dispatch for ranged profiles and straight paths vs. Funnel approach for obstructed paths.
  - Unit tests in `tests/unit/test_pathing.py` verifying line-of-sight / straight-segment path detection and custom engagement distances.
  - Validation pass: `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - In Flyff, select a Ranged class (e.g. Ranger / Magician) and verify that mobs at 10–15m are targeted and attacked immediately without running into melee range.
  - Select a Melee class on an open field and verify that the bot clicks the mob directly and runs smoothly without camera-turning thrashing.
  - Defeat a monster in a dense pack and verify that a neighboring monster is targeted after 1.0s without the bot turning away.
