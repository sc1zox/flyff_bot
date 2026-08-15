---
id: US-021
title: Navigation map profile slots, persistence management, and session reset
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-021: Navigation map profile slots, persistence management, and session reset

## Story

As an operator managing farming sessions, I want to save, load, and switch named navigation map profile slots and reset the current spatial map from the desktop dashboard, so that I can easily maintain dedicated route and heatmap profiles for different mob locations and clear old navigation data without manual file edits.

## Context and assumptions

- **Architectural Dependencies & Safety:**
  - Extends [US-019](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) (`SpatialMap`, `PathingController`, `save_spatial_map`, `load_spatial_map`) and [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md) (`PathInspectorWidget`, `MainWindow`).
  - To prevent race conditions or erratic movements, map switching, loading, and resetting are strictly disabled during active farming ticks and only permitted when the bot is in a `PAUSED` or `STOPPED` state.
- **Profile Slot Management:**
  - Navigation profiles are stored as individual `.json` map files in the `data/navigation/` directory.
  - The UI populates a dropdown selector with all available `.json` maps found in the navigation directory.
  - A text input allows specifying a custom slot name (e.g. `mushpang_valley`, `flame_north`) for saving new or existing profiles.
  - An explicit **Save** button writes the current live spatial map, spawn weights, and recorded edges to the selected/named file.
  - An explicit **Load** button restores the selected profile into the active session and refreshes the visual path inspector.
  - Automatic persistence writes updates to the currently active profile slot upon session pause, stop, or application close.
- **Session Map Reset:**
  - A dedicated **Reset** button allows clearing all live navigation data.
  - Clicking **Reset** triggers a modal confirmation dialog to prevent accidental data loss.
  - Upon confirmation, the spatial map resets its cells, traversal edges, and spawn heatmaps, and re-centers the dead-reckoned character position and heading back to the origin $(0, 0, 0^\circ)$.
- **Localization:**
  - All button labels, input placeholders, status notifications, and dialog prompts are fully synchronized in German and English (`de.json` / `en.json`).

## Acceptance criteria

- [ ] The dashboard provides map profile controls (profile selector dropdown, name input field, Save button, Load button, and Reset button) accessible within the path inspection panel or controls bar.
- [ ] Map management controls (Load, Save, Reset) are enabled only while the bot is paused or stopped, and disabled during active farming.
- [ ] The profile dropdown lists all `.json` files existing in `data/navigation/`, updating dynamically when new profiles are saved.
- [ ] Saving a profile writes the full JSON schema of the current `SpatialMap` to `data/navigation/<name>.json` with sanitized filename validation.
- [ ] Loading a profile deserializes the map, updates `PathingController`, and immediately refreshes `PathInspectorWidget`.
- [ ] Clicking the Reset button opens a confirmation prompt asking the operator to verify clearing the map.
- [ ] Confirming the reset clears all known cells, edges, spawn weights, active waypoints, and resets character position/heading to $(0, 0, 0^\circ)$.
- [ ] The active profile auto-saves to disk when the bot transitions from active to paused/stopped.
- [ ] All user-facing text, button labels, tooltips, and dialog messages are localized in German and English.
- [ ] Automated unit tests in `tests/unit/test_ui.py` and `tests/unit/test_path_inspector.py` verify:
  - Profile listing and selection handling.
  - Save, Load, and Reset execution on paused sessions.
  - Inactive state gating during active sessions.
  - Confirmation dialog acceptance and rejection paths.

## Out of scope

- Cloud synchronization or remote sharing of navigation profiles.
- Partial node deletion or manual map geometry editing.

## Verification

- Automated: Unit tests in `tests/unit/test_ui.py` and `tests/unit/test_navigation_profiles.py`; `./scripts/check.ps1`.
- Manual (Windows):
  1. Launch `uv run python -m flyff_bot ui`.
  2. Record a brief movement path, enter a profile name `test_spot`, and click **Speichern / Save**.
  3. Verify `test_spot.json` is created in `data/navigation/` and appears in the dropdown.
  4. Click **Reset**, confirm the dialog, and observe the canvas clearing back to origin $(0, 0)$.
  5. Select `test_spot` from the dropdown and click **Laden / Load**; observe the previous path and heatmap reappearing on the canvas.
