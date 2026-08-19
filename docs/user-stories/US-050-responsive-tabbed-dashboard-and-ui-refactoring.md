---
id: US-050
title: Responsive tabbed dashboard and UI design overhaul
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-050: Responsive tabbed dashboard and UI design overhaul

## Story

As a **bot operator**, I want **a clean, responsive, tabbed dashboard interface that replaces the cluttered horizontal checkbox toolbar with dedicated functional views (Dashboard, Combat & Targets, Vitals & Buffs, Navigation & World, Diagnostics & Logs) and standard desktop controls**, so that **I have an intuitive, visually appealing, and ergonomic user experience without layout instability or UI clutter**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- The desktop UI is built using PySide6 (Qt) as specified in [ADR-002](../../decisions/ADR-002-target-architecture-and-pyside6.md) and styled with Qt Style Sheets (QSS) ([US-022](completed/US-022-modern-dark-theme-and-streamlined-dashboard-ui.md)).
- The previous UI suffered from checkbox bloat (11 bare checkboxes in a single toolbar) and vertical accordion stacking, causing erratic window jumping ([BUG-005](../bugs/fixed/BUG-005-dashboard-window-fails-to-shrink-on-overlay-toggle.md)) on dynamic panel toggles.
- Operator requirements from interview:
  - Tab-based navigation (`QTabWidget`) dividing the UI into 5 dedicated views:
    1. **Dashboard (`Übersicht`):** Camera preview toggle/display, live vitals, target state summary, kill counters, primary quick-status indicators.
    2. **Combat & Targets (`Kampf & Ziele`):** Target monster selection table & quotas (`TargetSelectionPanel`), combat grace timing, kill verification switch, anchor match threshold, emergency stuck teleport recovery (`EmergencyRecoveryConfig`).
    3. **Vitals & Buffs (`Vitals & Buffs`):** HP/MP/FP threshold rules, debounces, consumable hotkeys, timed power-ups / buff table (`PowerUpPanel`).
    4. **Navigation & World (`Navigation & Karte`):** Embedded map inspector preview (`PathInspectorWidget`), profile management (save/load/reset), spawn anchor, world data extractor dialog, popout map button.
    5. **Diagnostics & Logs (`Diagnose & Tools`):** Session event log (`EventLogPanel`), Target verification OCR debug panel, Monster stats HUD OCR debug panel, transparent in-game placement guides overlay toggle.
  - Top Action Bar / Header:
    - Status badges (`ACTIVE`, `STANDBY`, `COMBAT`, `PAUSED`, `EMERGENCY_STOPPED`), window condition chip, GPS / tracking indicators.
    - Clean primary action controls: Start button, Pause button.
    - Attack key binding button, Camera alignment button & Auto-align switch, Language selector.
    - Clutter removal: The dedicated giant red "Not-Aus" button is removed from the primary header bar to streamline the UI. Safety requirement: In accordance with `AGENTS.md` and safety boundaries, the global emergency stop (`END` key hook), window `Escape` shortcut, and emergency stop signal dispatch remain fully active in the application and controllers.
  - Standard styling & responsiveness:
    - No "AI slop" (no excessive gradients, neon glows, or irregular styling). Modern Windows 11 Slate Dark QSS styling with clean spacing, standard form layouts, and responsive scroll areas (`QScrollArea`) inside tabs to prevent window resizing jitter.
    - Elimination of bare checkbox toggles in favor of proper switches/toggles or styled components.

## Acceptance criteria

- [ ] **Structured tabbed navigation (`QTabWidget`):**
  - Given the dashboard is initialized, when the main window is displayed, then a cohesive `QTabWidget` renders the 5 dedicated functional tabs with localized labels and tooltips.
  - Switching tabs preserves all active worker feeds, background updates, and controller state without lagging or desyncing.
- [ ] **Streamlined Header & Control Bar:**
  - Status badges, window status chips, tracking/GPS chips, and primary actions (Start, Pause, Attack Key, Camera Align, Auto-Align, Language) remain pinned at the top above the tab widget for persistent access.
  - The global emergency stop (`END` key, `Escape` key) remains fully operational and halts automation instantly upon trigger.
- [ ] **Elimination of Checkbox Bloat:**
  - The 11 bare panel-toggling checkboxes in the previous telemetry card are completely replaced by the dedicated tab pages.
  - Setting options (e.g. Auto-Align, Kill Verification, Vitals enable) are styled cleanly as standard switches or integrated form controls.
- [ ] **Scrollable & Responsive Tab Layouts:**
  - Each tab contains an internal `QScrollArea` or responsive container so content scales cleanly without triggering erratic `adjustSize()` window shrinking/growing jumps.
- [ ] **Cohesive Dark Slate Styling (QSS):**
  - The dark theme is expanded to style `QTabWidget`, `QTabBar`, `QScrollArea`, and all child controls consistently with the dark slate palette (`#0f172a`, `#1e293b`, `#334155`, `#3b82f6`).
- [ ] **Localization:**
  - All user-visible strings (tab headers, new control labels, tooltips) are completely synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Automated verification:**
  - Application wiring in `src/flyff_bot/ui/app.py` and UI tests in `tests/unit/test_ui.py` are updated to reflect the tabbed hierarchy and verify all interactions.

## Out of scope

- Web runtimes, Electron, or external GUI frameworks.
- Changes to core perception algorithms (YOLO, OCR, template matching) or pathfinding math.

## Verification

- Automated:
  - `uv run pytest tests/unit/test_ui.py`
  - `./scripts/check.ps1`
- Manual (Windows):
  - Run `uv run flyff-bot ui` or `uv run flyff-bot --farm --auto`.
  - Verify modern dark theme appearance, tab navigation responsiveness, hover/pressed button feedback, status badge updates, popping out the navigation map window, and triggering emergency stop via `Escape` or `END`.
