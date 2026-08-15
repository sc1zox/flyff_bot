---
id: US-021
title: Navigation map profile slots, persistence management, and session reset
status: completed
created: 2026-08-16
updated: 2026-08-16
---

# US-021: Navigation map profile slots, persistence management, and session reset

## Story

As an operator managing automated farming sessions across different game zones, I want to save, load, and switch named navigation map profile slots, configure fine-grained spatial grids, and reset live navigation data directly from the desktop dashboard, so that I can maintain distinct route and spawn heatmap profiles for specific mob camps, avoid cross-zone map contamination, and clear old path memory without manual file system edits.

## Context and assumptions

- **Architectural Grounding:**
  - Extends [US-019](US-019-intelligent-pathing-and-spawn-heatmap.md) (`SpatialMap`, `PathingController`, `save_spatial_map`, `load_spatial_map`) and [US-020](US-020-visual-navigation-path-and-heatmap-inspector.md) (`PathInspectorWidget`, `MainWindow`).
  - Stored in the native Windows filesystem under `data/navigation/*.json`.
- **Operating State & Concurrency Safety:**
  - Map modifications (Loading a different profile, saving as a new name, or resetting live memory) are strictly permitted **only while farming is paused or stopped** (`FarmingMode.PAUSED` or `FarmingMode.EMERGENCY_STOPPED`).
  - All profile modification buttons and dropdown controls are automatically disabled in the UI while the session is actively executing (`SEARCHING`, `TARGETING`, `COMBAT`, `LOOTING`, `RECONCILING`).
- **Profile Slot Management & UI Workflow:**
  - **Storage Directory:** All profile files reside in `data/navigation/`.
  - **Profile Selector Dropdown (`QComboBox`):** Scans and displays all valid `.json` map profiles in `data/navigation/`. Displays the profile name and cell count summary (e.g. `mushpang_valley.json (14 Kacheln)`).
  - **Profile Name Input (`QLineEdit`):** Editable text field with placeholder text, automatically sanitizing invalid Windows filename characters (`\ / : * ? " < > |`) and whitespace.
  - **Action Controls:**
    - `[💾 Speichern / Save]`: Serializes the current live spatial map, recorded graph edges, spawn weights, and stalls to `data/navigation/<name>.json`. Updates the dropdown selection immediately.
    - `[📂 Laden / Load]`: Deserializes the selected profile into `PathingController`, restores the traversal graph and spawn heatmaps, and refreshes the `PathInspectorWidget` canvas.
    - `[🔄 Karte leeren / Reset]`: Opens a modal confirmation prompt. Upon confirmation, resets the active in-memory spatial map and centers the dead-reckoning tracker back to the origin $(0.0, 0.0, 0^\circ)$.
    - `[🗑️ Löschen / Delete]` (optional/secondary): Allows deleting an unused profile file from disk with confirmation.
- **Persistence Guarantees & Lifecycle Hooks:**
  - **State Transition Auto-Save:** Pausing farming (`orchestrator.pause()`), triggering an emergency stop (`orchestrator.emergency_stop()`), or reaching a farming goal automatically persists the active profile.
  - **Window Close Hook (`closeEvent`):** Closing the desktop window via the title bar 'X' cleanly triggers `orchestrator.pause()` and flushes the active spatial map to disk before application termination.
  - **Periodic Background Persistence:** While farming is active, the orchestrator flushes the active profile every 30 seconds of game time to protect against unexpected process loss.
- **Visual Detailing & Granularity Standards:**
  - **Fine-Grained Grid Resolution:** Standard cell size set to $15.0$ game units (down from $40.0$), producing fine-grained $10 \times 10$ to $20 \times 20$ topological grids per camp.
  - **High-Contrast Heatmap & Player Frustum:**
    - Distinct electric cyan player marker (`#00f0ff`) with $60^\circ$ field-of-view camera cone.
    - Dedicated ember/fire spawn heatmap gradient (Gold `#ffc53d` $\rightarrow$ Amber `#fa8c16` $\rightarrow$ Flame Red `#ff4d4f`), visually distinct from walkable paths and player markers.
    - Shape-matching legend glyphs (`▲` Player/FOV, `●` Hotspot, `━` Path, `⛝` Hazard, `━` Route, `◆` Safe Fallback).
- **Localization:**
  - All button labels, input placeholders, tooltips, confirmation dialogs, and error messages are synchronized in German (`de.json`) and English (`en.json`).

## Acceptance criteria

### 1. Profile Slot Management UI
- [x] Given the dashboard is launched, when the operator views the path inspection panel, then a dedicated **Profile Management Bar** is visible containing:
  - A profile selector dropdown listing all `.json` files in `data/navigation/`.
  - A text input for entering custom profile names.
  - Action buttons: **Speichern (Save)**, **Laden (Load)**, and **Karte leeren (Reset)**.
- [x] Given the bot is in `SEARCHING`, `TARGETING`, or `COMBAT` mode, when the UI renders, then the profile dropdown, name field, Save, Load, and Reset buttons are disabled (`setEnabled(False)`).
- [x] Given the bot is in `PAUSED` or `EMERGENCY_STOPPED` mode, then all profile management controls are enabled.

### 2. Saving and Loading Profiles
- [x] Given a session has recorded movement and mob spawns, when the operator enters `flame_north` and clicks **Speichern**, then:
  - The map is written to `data/navigation/flame_north.json` following the versioned JSON schema.
  - The profile dropdown updates to include `flame_north.json` as the selected item.
- [x] Given multiple saved map profiles exist in `data/navigation/`, when the operator selects `mushpang_valley.json` and clicks **Laden**, then:
  - `PathingController` is updated with the loaded map data.
  - `PathInspectorWidget` repaints immediately showing the loaded cells, edges, and spawn hotspots.
- [x] Given a corrupted or invalid JSON file is selected for loading, when the operator clicks **Laden**, then an error message dialog is presented and the active map state remains intact without crashing.

### 3. Session Map Reset Safeguard
- [x] Given an active map with visited cells and spawn weights, when the operator clicks **Karte leeren (Reset)**, then a modal confirmation dialog is displayed:
  - German: *"Möchten Sie die aktuelle Navigationskarte wirklich zurücksetzen? Ungespeicherte Änderungen gehen verloren."*
  - English: *"Are you sure you want to reset the current navigation map? Unsaved changes will be lost."*
- [x] Given the confirmation dialog is open, when the operator clicks **Abbrechen (Cancel)**, then the map state remains unchanged.
- [x] Given the confirmation dialog is open, when the operator clicks **Ja / Bestätigen (Confirm)**, then:
  - All cells, edges, spawn weights, and stalls are purged from the spatial map.
  - The player's dead-reckoning tracker resets position to $(0.0, 0.0)$ and heading to $0.0^\circ$.
  - The 2D inspector canvas clears and displays a fresh origin grid.

### 4. Automatic Persistence & Close Hook
- [x] Given a farming session is running, when the operator clicks **Pausieren** or triggers the emergency stop, then the active navigation profile is automatically saved to disk.
- [x] Given continuous farming is active for $\ge 30$ seconds, then the orchestrator automatically writes an updated map snapshot to disk.
- [x] Given the user closes the desktop application window via the 'X' title bar button, then `MainWindow.closeEvent` invokes `pause_requested`, ensuring the current navigation map is written to disk before process termination.

### 5. Localization & Verification
- [x] All new UI controls, button labels, tooltips, dialog titles, prompt messages, and status notices are synchronized in `de.json` and `en.json`.
- [x] Automated unit tests in `tests/unit/test_ui.py` and `tests/unit/test_path_inspector.py` verify:
  - Profile dropdown discovery and population.
  - Save, Load, and Reset signal flows and validation.
  - State gating (enabled when paused, disabled when active).
  - Confirmation dialog acceptance and rejection paths.
  - Window close event persistence.

## Out of scope

- Cloud backup or peer-to-peer sharing of map files.
- Manual graphical waypoint placement by clicking on the canvas.

## Verification

- Automated: Unit tests in `tests/unit/test_ui.py` and `tests/unit/test_navigation_profiles.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. Farm a spot for 2 minutes, enter `spot_a` in the profile name field, and click **Speichern**.
  3. Verify `data/navigation/spot_a.json` is created.
  4. Click **Karte leeren (Reset)**, confirm the prompt, and verify that the canvas clears back to $(0, 0)$.
  5. Select `spot_a` in the dropdown and click **Laden**; observe all previous cells and spawn clusters restored immediately.
  6. Close the window with 'X' while paused and verify the map file is intact.
