# Bugs

One Markdown file represents one reproducible defect. Copy `TEMPLATE.md` to
`BUG-NNN-short-title.md`. Link the story or expected behavior that proves it is a defect.

Lifecycle: `reported` -> `confirmed` -> `in-progress` -> `fixed` -> `verified` (or `rejected`). Do
not close a bug without a regression check or a documented reason why automation is impractical. Fixed
bugs are moved to `docs/bugs/fixed/`.

---

## Active Defect Backlog

- [ ] [**BUG-004: Navigation map visualization confusing player color with spawn cells and missing close-event persistence**](BUG-004-navigation-map-visualization-and-persistence-clarity.md)
- [ ] [**BUG-007: Start button causes silent pause loop on focus mismatch and standby perception is completely bypassed**](BUG-007-start-button-silent-pause-and-standby-perception-bypass.md)
- [ ] [**BUG-008: Placement guides in-game overlay**](BUG-008-placement-guides-in-game-overlay.md)
- [ ] [**BUG-009: WASD movement tracking heading error and obstacle stall detection failure against terrain**](BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md)


## Fixed Defects

- [x] [**BUG-001: Desktop UI does not run perception or detection feed when started**](fixed/BUG-001-desktop-ui-perception-feed-not-running.md)
- [x] [**BUG-002: TypeError on null foreground window handle during guarded search key dispatch**](fixed/BUG-002-null-foreground-window-type-error.md)
- [x] [**BUG-003: Search mode camera rotation uses character movement keys instead of camera arrow keys**](fixed/BUG-003-search-mode-camera-rotation-keys.md)
- [x] [**BUG-005: Dashboard window fails to shrink when toggling off debug overlay or path inspector**](fixed/BUG-005-dashboard-window-fails-to-shrink-on-overlay-toggle.md)
- [x] [**BUG-006: Player vitals resolution scaling and flicker spam**](fixed/BUG-006-player-vitals-resolution-scaling-and-flicker-spam.md)


