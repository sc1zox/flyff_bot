---
id: BUG-015
title: Camera alignment mouse wheel zoom-out has no observable effect on game viewport
status: resolved
severity: high
created: 2026-08-18
updated: 2026-08-18
---

# BUG-015: Camera alignment mouse wheel zoom-out has no observable effect on game viewport

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Entropia Flyff PServer (neuz.exe)

## Reproduction

1. Launch Flyff with a character logged into the game world and set camera zoom to an intermediate or zoomed-in level.
2. Run `uv run python scripts/capture_spawn_distance_samples.py walk-in --mob-class Flame --label flame_run1 --hold 4.0` (or click "Align Camera" / trigger auto-align in the desktop dashboard).
3. Foreground the game client window during the 3-second countdown.
4. Observe the minimap zoom clicks, mouse cursor repositioning to screen centre, wheel scroll events, and vertical pitch adjustment.

## Expected behavior

Per [US-042](../../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), `CameraAligner.align()` must:
1. Zoom the minimap HUD widget out to its physical hard stop via clicks.
2. Zoom the 3D camera viewport all the way out to its hard-stop distance by dispatching mouse wheel rotation over the active game viewport.
3. Drive vertical camera pitch up to its ceiling limit and pulse down to the standardized ~45° elevation.

## Actual behavior

While minimap zoom clicks and vertical pitch adjustments (`VK_UP` / `VK_DOWN`) execute successfully, the mouse wheel zoom-out step has no observable effect:
1. The mouse cursor is placed in the client centre, but no camera zoom movement occurs in the Flyff client (the camera remains stuck at its current zoom level).
2. The wheel events dispatched via `SendInput(MOUSE_EVENT_WHEEL)` after `SetCursorPos` are ignored or swallowed by Flyff's input processing loop (e.g. lack of client activation/mouse-move event after cursor relocation, event dispatch timing/rate, or window message routing).

## Impact and frequency

- Impact: High. Without reaching the physical zoom-out hard stop, the camera focal length varies between sessions, invalidating the perspective geometry of the spawn distance calibration model (US-037/US-041/US-043) and reducing the bot's effective detection horizon.
- Frequency: 100% reproducible when executing camera alignment via calibration scripts, desktop dashboard, or pre-flight initialization.

## Resolution

`WindowsInputController.scroll_wheel_while_guarded` relocated the pointer with `SetCursorPos`, which
teleports the cursor without placing a move into the injected input stream the client reads. A client
that tracks the pointer from move events therefore kept hit-testing the notches against the position
it had last seen the pointer move to — after the minimap zoom-out clicks, the HUD button — so the
wheel never reached the 3D viewport.

The pointer is now moved with an injected absolute mouse move (`MOUSEEVENTF_MOVE |
MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` through `SendInput`, normalized onto the 0-65535
virtual-desktop range by `GetSystemMetrics`), and the client is given `POINTER_MOVE_SETTLE_SECONDS`
(0.15 s) to process that move before the first notch is dispatched. Two related gaps closed with it:
the emergency stop and foreground focus are now checked *before* the pointer is moved, so an
unfocused client never has the operator's pointer dragged across it, and a client rectangle that
cannot be measured now dispatches nothing instead of scrolling wherever the pointer was left. The
sequence, notch count, direction, and guards of US-042/BUG-014 are unchanged.

## Regression verification

- [x] A failing automated test or deterministic manual check exists.
  `tests/unit/test_input_control.py::test_scroll_wheel_injects_a_pointer_move_over_the_client_before_the_notches`
  pins the injected absolute move, its normalized client-centre coordinates, and the settle before
  the notches; `test_scroll_wheel_sends_nothing_when_the_client_area_is_unknown` and
  `test_scroll_wheel_stops_immediately_when_the_client_loses_focus` pin the two guards.
- [x] The check passes after the fix. `pwsh -File .\scripts\check.ps1` is green (529 passed, 2 skipped).
- [x] Related documentation is current. `docs/wiki/architecture.md` states the injected-move
  invariant for wheel input.
