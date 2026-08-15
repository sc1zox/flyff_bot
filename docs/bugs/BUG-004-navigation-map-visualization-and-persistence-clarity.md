---
id: BUG-004
title: Navigation map visualization confusing player color with spawn cells and missing close-event persistence
status: reported
severity: medium
created: 2026-08-16
updated: 2026-08-16
---

# BUG-004: Navigation map visualization confusing player color with spawn cells and missing close-event persistence

## Environment

- Windows version: Windows 11
- Python version: 3.14.7
- Application revision: commit `ac12003`
- Client/server version: Flyff Universe / Desktop PySide6 UI

## Reproduction

1. Launch the desktop application via `uv run python -m flyff_bot ui`.
2. Check **"Wegkarte anzeigen"** (**"Show path map"**).
3. Start farming and allow the bot to kill multiple monsters in a spot.
4. Observe the 2D path inspector canvas.
5. Notice that all visited cells with low/medium spawn weight are filled with the same green color as the "Spieler" (Player) legend badge, creating visual confusion as if the map only displays player markers everywhere.
6. Close the window using the Windows 'X' title bar button and observe that `closeEvent` is not hooked to persist navigation data automatically.

## Expected behavior

- The player character marker should have a distinct, prominent visual style (bright cyan/white heading arrow and beam) that cannot be confused with stationary terrain cells.
- Spawn heatmap cells should use a dedicated heat palette (transparent gold/yellow for moderate density to intense red for dense spawn hotspots) and distinct circular or shaded tile styling.
- Visited non-spawn cells should appear with subtle dark slate borders rather than solid green fills.
- The legend should display matching geometric glyphs (e.g. directional arrow for player, dot for node, flame/circle for spawn heatmap, dashed box for stalls) rather than uniform colored squares.
- Window close events (`closeEvent`) should automatically invoke `orchestrator.pause()` and persist the active spatial map to disk.

## Actual behavior

- `_spawn_heat_color` started with green (`QColor(82, 196, 26)`), exactly matching `PLAYER_COLOR`.
- Visited cells were drawn as solid green squares with blue waypoint dots, while the legend listed green as "Spieler", misleading operators into thinking the cells were player markers.
- Closing the window did not trigger navigation map persistence.

## Impact and frequency

- Impact: Misleading UI representation of learned spawn clusters and potential loss of unpersisted pathing updates upon window close.
- Frequency: 100% reproducible when viewing the 2D path inspector.

## Regression verification

- [ ] Unit tests in `tests/unit/test_path_inspector.py` verify distinct player glyph and non-colliding heatmap palette.
- [ ] Unit tests in `tests/unit/test_ui.py` verify that `MainWindow.closeEvent` triggers clean pause and map persistence.
- [ ] `./scripts/check.ps1` passes cleanly.
