---
id: BUG-008
title: Placement guides render only inside internal dashboard preview instead of directly over the game window
status: resolved
severity: medium
created: 2026-08-16
updated: 2026-08-17
---

# BUG-008: Placement guides render only inside internal dashboard preview instead of directly over the game window

## Environment

- Windows version: Windows 10 / 11 (64-bit)
- Python version: 3.14.7
- Application revision: main
- Client/server version: Entropia Flyff PServer (neuz.exe) with PySide6 desktop dashboard

## Reproduction

1. Launch `uv run python -m flyff_bot ui` while the game client is running.
2. In the desktop dashboard toolbar, toggle the **"Platzierungshilfen"** ("Placements") button.
3. Observe that no visual placement guides appear on screen over the actual Flyff game window.
4. If "Debug-Overlay anzeigen" is unchecked, no guides are visible anywhere; if checked, guides only render inside the miniature image preview widget inside the bot's dashboard rather than aligning directly over the live game client.

## Expected behavior

Per user expectation and [US-026](../user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md):
- When "Platzierungshilfen" is toggled ON, the application should display an on-screen transparent HUD guide overlay aligned directly over the client window coordinates on the operator's desktop.
- The overlay must display color-coded, labeled bounding boxes directly over the in-game HUD regions (Player Vitals orb, Target Header region, and Monster Stats OCR crop) so operators can align in-game windows directly in the client.
- The transparent overlay should be click-through (pass mouse events to the game) and track the game window's position on screen.

## Actual behavior

- `_placements_toggle` only toggles a boolean flag passed to `render_debug_overlay()`, which draws dashed bounding boxes onto the downscaled QImage preview in `_overlay_label` inside the dashboard window.
- If `_debug_toggle` is not enabled, the dashboard preview widget is hidden, giving the operator no visible feedback that placement guides are active.
- No transparent overlay window is spawned on the desktop over the Flyff game window.

## Impact and frequency

- **Impact:** Usability issue; operators cannot visually align in-game UI elements directly over the game screen and must compare against an internal dashboard thumbnail.
- **Frequency:** 100% reproducible when toggling "Platzierungshilfen".

## Regression verification

- [x] A dedicated transparent overlay window (`PlacementOverlayWindow`) or viewport is created and positioned over the target game client HWND coordinates.
- [x] Toggling "Platzierungshilfen" displays the transparent guide overlay over the game window with correct client-coordinate ROI bounding boxes.
- [x] Automated tests in `tests/unit/test_ui.py` verify placement overlay window lifecycle, geometry tracking, and toggle signals.
- [x] Related documentation is current.

## Resolution

`PlacementOverlayWindow` (`src/flyff_bot/ui/placement_overlay.py`) is a frameless, translucent,
always-on-top `Qt.Tool` window that draws the guides directly over the game client. It carries
`Qt.WindowType.WindowTransparentForInput` and `WA_ShowWithoutActivating`, so it is click-through and
never becomes the foreground window — taking focus would pause the guarded session and make the
client register as occluded for frame capture.

`WindowsInputController.client_screen_bounds()` returns the client area in desktop pixels
(`GetClientRect` + `ClientToScreen`), or `None` when the window is gone, hidden, or minimized. The
overlay polls it every 250 ms while enabled, hides itself whenever the bounds are unavailable, and
converts physical pixels into Qt logical units through the pure `logical_geometry()` helper so
scaled displays stay aligned. Guides are computed once as client-space `PlacementGuide` values by
`compute_placement_guides()` and are shared with the dashboard preview, which keeps both surfaces
identical; the overlay scales them by its own width relative to the tracked client width.

`MainWindow.attach_placement_target()` binds the overlay to the discovered game window, and
`run_desktop` calls it as soon as the window is found — before the model-file guard — so the guides
also work when no detection model is installed and no frame preview exists. `closeEvent` stops the
poll timer and closes the overlay.
