---
id: BUG-045
title: Test navigation inactive due to missing client window focus and unattached NavMesh
status: resolved
severity: high
created: 2026-08-31
updated: 2026-08-31
---

# BUG-045: Test navigation inactive due to missing client window focus and unattached NavMesh

## Environment

- Windows version: Windows 11 x64
- Python version: 3.14
- Application revision: main
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch the application desktop dashboard (`run_desktop()`) with `neuz.exe` running in the background.
2. Switch to the "Navigation & Karte" (Navigation & World) tab or open the standalone popout map window.
3. Right-click any coordinate or spawn zone on the interactive map canvas.
4. Select "Hierhin navigieren (Test) - (X, Z)" / "Navigate here (Test) - (X, Z)".
5. Observe the bot's behavior: Nothing happens. The character does not move, the game client does not focus, and the navigation mode immediately halts back to `PAUSED`.

## Expected behavior

Per [US-095](../user-stories/completed/US-095-interactive-map-direct-navigation-test-mode.md):
1. **Window Focus Handoff:** Selecting "Hierhin navigieren (Test)" must foreground the game client window (`controller.focus_window(window_handle)`) before initiating movement, identical to `start_farming` and `arm_autopilot`.
2. **Authoritative NavMesh Adoption:** `PathingController` must hold or adopt the authoritative `BakedNavMesh` from the loaded map scene so that `request_test_navigation` can compute routes and steer the character even if vector farming navigation was not previously activated.
3. **Smooth Movement & Arrival:** The character steers along the NavMesh to the destination and completes arrival cleanly with a localized event log entry.

## Actual behavior

1. `connect_test_navigation` in `src/flyff_bot/ui/app.py` passes `NavigationTestRequest` directly to `orchestrator.request_test_navigation(request)` without foregrounding the game client window.
2. Because the Qt UI window retains foreground focus, the next `SessionWorker` tick in `_run_test_navigation` evaluates `not self._input_adapter.is_foreground(self._window_handle)` to true and immediately invokes `_halt_test_navigation("focus_lost")`, resetting the mode to `PAUSED` within ~50ms.
3. `PathingController` is constructed with `navmesh=None` and only receives a mesh when `configure_vector_navigation` is called. If the operator tests navigation directly from the map without activating vector navigation, `orchestrator.request_test_navigation` aborts with `test_navigation_unavailable`.

## Impact and frequency

- Impact: High. Interactive map test navigation is completely inoperable from the UI.
- Frequency: Deterministic on every right-click navigation test attempt in the desktop UI.

## Regression verification

- [x] Unit test in `tests/unit/test_ui.py` verifying that `start_test_navigation` brings the game client foregrounded before requesting test navigation.
- [x] Unit test in `tests/unit/test_ui.py` verifying that `start_test_navigation` pauses gracefully without traceback if focus fails.
- [x] Unit test in `tests/unit/test_interactive_path_inspector.py` verifying that `NavigationTestRequest` carries the scene's loaded `BakedNavMesh`.
- [x] Unit test in `tests/unit/test_orchestrator.py` verifying that `request_test_navigation` adopts the request's `BakedNavMesh` onto `PathingController` when not previously attached.
- [x] `./scripts/check.ps1` runs cleanly with zero lint, formatting, type, and test errors.
