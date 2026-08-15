---
id: US-022
title: Modern dark theme and streamlined dashboard UI
status: draft
created: 2026-08-16
updated: 2026-08-16
---

# US-022: Modern dark theme and streamlined dashboard UI

## Story

As a **bot operator**, I want **a visually polished, modern dark-themed dashboard with card-based grouping, concise icon-driven controls, a pop-out navigation map window, and an `Escape` key emergency stop shortcut**, so that **I can monitor and operate the bot in a clean, uncluttered, and ergonomic interface without visual bloat**.

## Context and assumptions

- The current desktop UI ([US-010](completed/US-010-pyside6-dashboard-and-overlay.md), [US-020](completed/US-020-visual-navigation-path-and-heatmap-inspector.md), [US-021](completed/US-021-navigation-map-profiles-and-session-reset.md)) uses default unstyled Qt widgets ("bare metal"), resulting in an uncohesive appearance and vertical crowding when the map inspector is active.
- Decision [ADR-002](../decisions/ADR-002-target-architecture-and-pyside6.md) specifies PySide6 (Qt) for the native Windows desktop client without web runtimes.
- The visual overhaul is implemented purely using Qt Style Sheets (QSS), custom widget grouping/cards, and native Qt window management without introducing external heavyweight dependencies.
- User feedback confirmed preferences:
  - Theme: Modern Dark / Slate theme with clean contrast, rounded corners, and distinct action colors.
  - Layout: Card-/Panel-based grouping separating status telemetry, primary actions, profile management, and viewport toggles.
  - Streamlined presentation: Minimal redundant text, concise metric chips/badges, and icon-supported action buttons with tooltips.
  - Map Inspector: Supports embedding or popping out into a standalone secondary window.
  - Emergency Stop: Quick emergency stop trigger via `Escape` (`Qt.Key.Key_Escape`) keypress within the UI window in addition to the global `END` key hook and UI button.

## Acceptance criteria

- [ ] **Modern dark theme (QSS):**
  - Given the PySide6 application is launched, when the main window appears, then a cohesive dark slate stylesheet is applied to all windows, dialogs, buttons, inputs, combo boxes, checkboxes, and labels.
  - Action buttons feature clear visual hierarchy: Start (emerald green accent), Pause (amber/yellow accent), and Emergency Stop (prominent danger crimson).
  - Controls include responsive hover, pressed, and disabled visual states.
- [ ] **Card-based layout & reduced text clutter:**
  - Given the dashboard interface, when rendered, then controls are organized into visual card panels:
    - *Status & Metrics Card:* Displays live bot state with colored status pill badges (`ACTIVE`, `PAUSED`, `EMERGENCY_STOP`) and concise stat chips (mob count, goal progress) rather than raw multiline text labels.
    - *Action Controls Card:* Prominent Start, Pause, Emergency Stop buttons, attack key configuration button with tooltip, and language selector.
    - *Navigation & Profiles Card:* Compact profile selection combo box, sanitized name input, and icon/action buttons for Save, Load, and Reset.
    - *Telemetry & Diagnostics Toolbar:* Compact toggle switches/buttons for debug overlay and path inspector.
- [ ] **Pop-out navigation map window:**
  - Given the path inspector is opened, when the operator clicks a pop-out button or checkbox, then the `PathInspectorWidget` can be displayed inside a separate standalone top-level window (`NavigationMapWindow`), keeping the main controller window compact.
  - When the pop-out window is closed or toggled back, the state is cleanly synced without interrupting farming or navigation telemetry updates.
- [ ] **`Escape` key emergency stop:**
  - Given the application window or popped-out navigation window has focus, when the operator presses the `Escape` key, then an emergency stop is immediately triggered (`emergency_stop_requested.emit()`), matching the behavior of the UI Emergency Stop button.
- [ ] **Failure and cancellation behavior:**
  - If a theme stylesheet file fails to load or contains a syntax error, the application falls back safely without crashing.
  - Modal confirmation dialogs (e.g. navigation map reset) conform to the dark theme styling.
- [ ] **Localization:**
  - All user-visible text, tooltips, status badges, and dialog strings are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Automated verification:**
  - Unit tests verify QSS application, card panel hierarchy, `Escape` key event handling, pop-out window lifecycle, and signal emission.

## Out of scope

- Web-based frontends, Electron, or browser-based streaming dashboards.
- Modifying underlying perception models, YOLO inference pipelines, or Win32 input dispatch protocols.
- Custom raster/SVG icon asset build pipelines beyond standard Unicode glyphs or lightweight Qt vector rendering.

## Verification

- Automated:
  - `uv run pytest tests/test_ui_main_window.py tests/test_ui_path_inspector.py` (including new tests for dark theme QSS loading, pop-out window behavior, and `Escape` key emergency stop).
  - `./scripts/check.ps1` (ruff, mypy, pytest).
- Manual (Windows):
  - Run `uv run flyff-bot ui` or `uv run flyff-bot --farm --auto`.
  - Verify modern dark theme appearance, hover/pressed button feedback, status badge updates, popping out the navigation map window, and triggering emergency stop via `Escape`.
