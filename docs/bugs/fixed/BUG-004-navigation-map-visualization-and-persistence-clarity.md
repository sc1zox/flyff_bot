---
id: BUG-004
title: Navigation map visualization confusing player color with spawn cells and missing close-event persistence
status: resolved
severity: medium
created: 2026-08-16
updated: 2026-08-17
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

## Resolution

The visual palette was already corrected in commit `d66c5e9` (cyan heading arrow with field-of-view
beam, gold-to-ember spawn gradient, slate borders on visited non-spawn cells, glyph legend), but the
change carried no regression coverage and left the palette duplicated between the canvas and the
legend: `_draw_legend` hardcoded the spawn swatch as `QColor(250, 140, 22)`, which matched
`_spawn_heat_edge_color(0.0)` only by coincidence and would have silently drifted on the next
palette edit — the same class of misleading legend the report describes.

`src/flyff_bot/ui/path_inspector.py` now derives every marker color from one named palette:
`SPAWN_HEAT_BASE_COLOR` feeds both the legend swatch and the sparse end of the heat gradient,
`LEGEND_ITEMS` is a module constant pairing each glyph with the color the canvas actually paints,
and the remaining inline `QColor(...)` literals (visited-cell border, stall fill, player cone,
marker outline, safe-waypoint fill) became named constants. `_spawn_heat_center_color` and
`_spawn_heat_edge_color` are now channel-wise interpolations between named endpoints instead of
open-coded arithmetic.

Close-event persistence needed no production change: `MainWindow.closeEvent` emits
`pause_requested`, which `connect_farming_controls` binds to `FarmingOrchestrator.pause()`, which
calls `_persist_navigation()` and flushes the spatial map to disk. That chain is now covered
end-to-end by a test that asserts the JSON file is written, rather than only that the signal fired.

Judgment call: the expected-behavior list gives "dot for node" as an example glyph, but graph nodes
have no legend entry today and adding one would require a new synchronized `de.json` / `en.json`
key. The "e.g." was read as illustrative, so the legend was left with its existing six entries.

## Regression verification

- [x] Unit tests in `tests/unit/test_path_inspector.py` verify distinct player glyph and non-colliding heatmap palette.
- [x] Unit tests in `tests/unit/test_ui.py` verify that `MainWindow.closeEvent` triggers clean pause and map persistence.
- [x] The verification gate passes cleanly (`uv sync --locked`, `ruff check`, `ruff format --check`,
      `mypy`, `pytest`: 270 passed, 7 skipped). Run as the equivalent `uv` commands because the fix
      was made on a Linux workstation where `pwsh` — and therefore `./scripts/check.ps1` — is
      unavailable.
