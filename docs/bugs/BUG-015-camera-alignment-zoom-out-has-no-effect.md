---
id: BUG-015
title: Camera alignment mouse wheel zoom-out has no observable effect on game viewport
status: reported
severity: high
created: 2026-08-18
updated: 2026-08-18
---

# BUG-015: Camera alignment mouse wheel zoom-out has no observable effect on game viewport

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff (neuz.exe)

## Reproduction

1. Launch Flyff with a character logged into the game world and set camera zoom to an intermediate or zoomed-in level.
2. Run `uv run python scripts/capture_spawn_distance_samples.py walk-in --mob-class Flame --label flame_run1 --hold 4.0` (or click "Align Camera" / trigger auto-align in the desktop dashboard).
3. Foreground the game client window during the 3-second countdown.
4. Observe the minimap zoom clicks, mouse cursor repositioning to screen centre, wheel scroll events, and vertical pitch adjustment.

## Expected behavior

Per [US-042](../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md), `CameraAligner.align()` must:
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

## Regression verification

- [ ] A failing automated test or deterministic manual check exists.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
