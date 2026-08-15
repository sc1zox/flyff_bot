---
id: BUG-005
title: Dashboard window fails to shrink when toggling off debug overlay or path inspector
status: reported
severity: medium
created: 2026-08-16
updated: 2026-08-16
---

# BUG-005: Dashboard window fails to shrink when toggling off debug overlay or path inspector

## Environment

- Windows version: Windows 10/11
- Python version: 3.14 (.venv)
- Application revision: HEAD (main)
- Client/server version: Flyff (neuz.exe) / Desktop UI

## Reproduction

1. Launch the desktop UI via `uv run python -m flyff_bot ui` or instantiate `MainWindow`.
2. Check the "Debug-Overlay anzeigen" (or "Path Inspector") checkbox while receiving a dashboard feed with frames.
3. Observe the window expanding to accommodate the full frame pixmap dimensions (e.g. 1920x1080).
4. Uncheck the "Debug-Overlay anzeigen" (or "Path Inspector") checkbox.
5. Observe that the overlay widget is hidden, but the main window remains expanded at the large dimensions with empty whitespace instead of dynamically shrinking back.

## Expected behavior

- When toggling off "Debug-Overlay anzeigen" (`_debug_toggle`) or "Path Inspector" (`_path_toggle`), the main window must dynamically shrink back to its compact size (`adjustSize()`).
- When the debug overlay is active, the overlay viewport should support dynamic, responsive aspect-ratio scaling when resizing the window.

## Actual behavior

Toggling visibility via `setVisible(False)` hides child widgets (`_overlay_label`, `_path_inspector`), but Qt `QMainWindow` does not automatically shrink back layout geometry. The window stays stretched at the maximum captured frame size.

## Impact and frequency

- Impact: Medium. Suboptimal operator experience requiring manual window resizing every time debug monitoring is turned off.
- Frequency: 100% reproducible whenever debug overlay or path inspector is toggled on and off.

## Regression verification

- [ ] A failing automated test verifying that toggling off the debug overlay and path inspector triggers window size adjustment.
- [ ] The check passes after the fix.
- [ ] Related documentation is current.
