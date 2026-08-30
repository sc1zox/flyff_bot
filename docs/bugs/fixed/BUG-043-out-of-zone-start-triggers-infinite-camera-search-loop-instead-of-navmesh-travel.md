---
id: BUG-043
title: Out-of-zone start triggers infinite camera search loop instead of NavMesh travel
status: resolved
severity: high
created: 2026-08-30
updated: 2026-08-30
---

# BUG-043: Out-of-zone start triggers infinite camera search loop instead of NavMesh travel

## Environment

- Windows version: Windows 11 x64
- Python version: 3.14
- Application revision: main
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch the application and attach to the running `neuz.exe` client in the Eden world with character standing at a location away from the intended target camp (e.g. at town or a different spawn).
2. Open the World Data Dialog (`Karten-Inspektor`), load the Eden map with extracted NavMesh, select a monster spawn zone (e.g. a specific mob camp in Eden), and click "Aktivieren" (Activate).
3. Foreground the client and click "Start" (or trigger session start).
4. Observe the bot's behavior in `FarmingMode.SEARCHING`: No target monsters of the selected quota/class are in the immediate camera viewport.
5. Record the first observable failure: Instead of pathfinding across the NavMesh towards the selected spawn zone (`PathingMode.TRAVELING`), the bot gets trapped in an endless `SearchController` camera rotation loop (`SearchMode.ROTATE` / `SearchMode.SETTLE` live perception preview) spinning in place indefinitely.

## Expected behavior

Per [US-059](../user-stories/completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md), [US-091](../user-stories/completed/US-091-unified-goal-navigation-fluid-scanning-and-intelligent-unstuck.md), and [US-093](../user-stories/completed/US-093-geometry-verified-stall-recovery-and-navmesh-routing-unification.md):
1. When a spawn zone is activated and the player character is currently located outside that zone, `PathingController` / `VectorZoneNavigator` must construct a NavMesh route from the current GPS position to the target zone's patrol ring / center.
2. The orchestrator must enter `PathingMode.TRAVELING` and steer the character along the NavMesh waypoints to the target zone without spinning the camera in place.
3. During transit to the designated target zone, the bot must strictly ignore non-target monster classes.
4. If no valid NavMesh path exists between the current position and the destination zone (e.g. disconnected mesh island or impassable geometry), the session must not fall back to an infinite in-place camera search loop; instead, it must record a structured error event (e.g. `zone_unreachable` / `route_unavailable`) and pause safely with a localized status diagnostic.

## Actual behavior

When `_advance_pathing()` yields an idle or empty route when started outside the zone, the orchestrator immediately falls through to `_search.step()`. This causes `SearchController` to endlessly dispatch camera rotation key strokes (`A` / `D`) followed by settle intervals to check for mobs. Since the player is far away from the configured mob spawn, no matching mob is ever detected, leaving the bot stuck in a permanent rotation-preview death loop ("Todesloop zwischen Drehen und Live-Vorschau").

## Impact and frequency

- Impact: High. Prevents autonomous farming sessions from starting unless the operator manually walks the character into the exact spawn zone beforehand.
- Frequency: Deterministic (100% reproducible whenever starting a session outside the activated zone).

## Regression verification

- [x] `test_out_of_zone_start_uses_navmesh_travel_instead_of_camera_search` reproduces an activated, out-of-zone start and verifies that the session dispatches NavMesh travel rather than camera search.
- [x] `test_unreachable_selected_zone_pauses_without_camera_search` verifies that an unreachable selected zone latches a safe pause and records `zone_route_unavailable` rather than entering the search rotation loop.
- [x] Focused verification passed: `uv run pytest tests\unit\test_vector_pathing.py tests\unit\test_i18n.py --no-cov --basetemp C:\Windows\Temp\pytest-bug043` reported 29 passed in 0.29s.
- [x] Related documentation is current. The existing architecture documentation already establishes selected-zone NavMesh routing; this regression does not introduce a separate durable architectural boundary.

## Verification limits

The canonical `./scripts/check.ps1` gate passed dependency synchronization, Ruff, formatting, and
MyPy, but its pytest phase remains blocked by three unrelated failures in
`tests/unit/test_quest_objectives.py` (lines 624, 721, and 812). Those failures are outside the
BUG-043 change; the focused BUG-043 regression coverage passed as recorded above.
