---
id: US-090
title: World data dialog resizable layout and batch spawn zone selection
status: completed
created: 2026-08-29
updated: 2026-08-31
---

# US-090: World data dialog resizable layout and batch spawn zone selection

## Story

As a **bot operator managing vector-world farming**,
I want **the World Data dialog to be resizable, expand the spawn-zone list flexibly in both dimensions, persist its window geometry across sessions, and provide one-click "Select All" and "Deselect All" batch controls**,
so that **long zone names and coordinates are easily readable, multi-zone patrol routes across large regions can be selected effortlessly, and window layout adjustments are preserved**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Builds upon:
  - [US-045](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md): Vector world terrain extraction, spawn zones, and visibility-graph A* pathing.
  - [US-053](completed/US-053-pure-gps-navigation-and-client-profile-configuration.md): Pure 3D GPS navigation, dynamic client profile configuration, and minimap fallback retirement.
  - [US-059](completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md): Authoritative vector navigation, legacy subsystem removal, and multi-zone selection.
- Current constraints in `WorldDataDialog` (`src/flyff_bot/ui/world_data_dialog.py`):
  - `_zone_list` enforces an artificial maximum height of 4 visible rows (`_ZONE_LIST_VISIBLE_ROWS = 4`, `_zone_list_height()`), preventing the list from expanding vertically when the dialog is enlarged.
  - The dialog does not persist its window dimensions or position in `QSettings`, resetting to default dimensions on each open.
  - Selecting multiple camps across densely populated maps (e.g. `WdEden` or `WdMadrigal`) requires clicking every checkbox individually.
- Linked decisions and docs:
  - [Architecture](../wiki/architecture.md)
  - [ADR-002: Target Architecture and PySide6](../decisions/ADR-002-target-architecture-and-pyside6.md)
  - [BUG-021](../bugs/fixed/BUG-021-multi-zone-selection-and-localized-debug-values-missing.md)

## Acceptance criteria

- [x] **Batch Spawn-Zone Selection Controls:**
  - Dedicated "Select All" (`UI_WORLD_DATA_SELECT_ALL`) and "Deselect All" (`UI_WORLD_DATA_DESELECT_ALL`) action buttons are added adjacent to or below the spawn zones list. (`_batch_selection_row()` sits directly under `_zone_list` in the grid.)
  - Clicking "Select All" marks all listed spawn zones as `Qt.CheckState.Checked`, updates `active_zones`, enables the activate button, and persists the full selection to `QSettings`. (`_on_select_all_clicked` → `_set_all_zone_check_states`.)
  - Clicking "Deselect All" marks all listed spawn zones as `Qt.CheckState.Unchecked`, clears `active_zones`, disables the activate button, and persists the empty selection to `QSettings`. (`_on_deselect_all_clicked` → `_set_all_zone_check_states`.)
- [x] **Resizable Layout & Dynamic Expansion:**
  - `WorldDataDialog` removes the fixed 4-row maximum height constraint on `_zone_list` (`_ZONE_LIST_VISIBLE_ROWS` and `_zone_list_height()` deleted, no `setMaximumHeight` call).
  - The dialog layout and size policies allow `_zone_list` to expand dynamically in both vertical and horizontal directions when the window is resized or maximized (`QSizePolicy.Expanding`/`Expanding`, grid row/column stretch, `QVBoxLayout` stretch factor).
  - Default initial dimensions provide sufficient width and height to display zone names, mob counts, and coordinates without horizontal truncation (`_DEFAULT_DIALOG_WIDTH`/`_DEFAULT_DIALOG_HEIGHT` 640×560, `_MINIMUM_DIALOG_WIDTH`/`_MINIMUM_DIALOG_HEIGHT` 520×400).
- [x] **Window Geometry Persistence:**
  - `WorldDataDialog` saves its window geometry/size to `QSettings` on close or state synchronization (`_persist_state` stores `saveGeometry()` under `_GEOMETRY_SETTING`; `closeEvent` already calls `_persist_state`).
  - When re-opened within the same session or across application restarts, the dialog restores the saved window size and position (`_restore_geometry` calls `restoreGeometry`, falling back to the default resize).
- [x] **Navigation Dispatch & Multi-Zone Integrity:**
  - Activating navigation with batch-selected zones maintains deterministic list order for sequential multi-zone patrol and quota progression as established in US-059. (`active_zones` is still derived by iterating `_zone_list` in row order; batch selection only sets check states.)
- [x] **Localization:**
  - All new button labels, tooltips, and status text are synchronized in German (`de.json`) and English (`en.json`). (`ui.world_data_select_all` / `ui.world_data_deselect_all`; no new tooltip or status text was required.)

## Out of scope

- Changes to underlying 3D NavMesh routing or pathfinding algorithms (`VectorZoneNavigator` / `TerrainRoutePlanner`).
- Adding text-based search or filtering to the spawn-zone list widget.
- Custom polygon drawing or in-game overlay zone editing.

## Verification

- Automated:
  - [x] Unit tests in `tests/unit/test_world_data_dialog.py` verifying "Select All" and "Deselect All" button behavior, `active_zones` synchronization, and activation button enable/disable states (`test_select_all_checks_every_zone_and_enables_activation`, `test_deselect_all_clears_every_zone_and_disables_activation`, `test_batch_selection_is_persisted_and_restored_on_reopen`, `test_batch_controls_are_disabled_without_an_extracted_map`).
  - [x] Unit test verifying window geometry save and restore logic in `QSettings` (`test_window_geometry_is_saved_and_restored_across_reopen`).
  - [x] Unit test verifying dynamic layout constraints and zone list sizing (`test_zone_list_expands_without_a_fixed_row_cap`).
  - [x] `./scripts/check.ps1` runs clean with zero type and lint errors (1303 passed, coverage 88.85%).
- Manual (Windows):
  - Open `Weltdaten & Karten` dialog, resize the window manually and maximize: verify spawn-zone list expands smoothly and shows many rows at once.
  - Click "Alle auswählen": verify all zones are checked and "Navigation aktivieren" is enabled.
  - Click "Keine auswählen": verify all zones are unchecked and "Navigation aktivieren" is disabled.
  - Close and reopen dialog: verify resized window dimensions and checked zones are fully preserved.
