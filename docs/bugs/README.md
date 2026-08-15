# Bugs

One Markdown file represents one reproducible defect. Copy `TEMPLATE.md` to
`BUG-NNN-short-title.md`. Link the story or expected behavior that proves it is a defect.

Lifecycle: `reported` -> `confirmed` -> `in-progress` -> `fixed` -> `verified` (or `rejected`). Do
not close a bug without a regression check or a documented reason why automation is impractical. Fixed
bugs are moved to `docs/bugs/fixed/`.

---

## Active Defect Backlog

- [ ] [**BUG-002: TypeError on null foreground window handle during guarded search key dispatch**](BUG-002-null-foreground-window-type-error.md)
- [ ] [**BUG-004: Navigation map visualization confusing player color with spawn cells and missing close-event persistence**](BUG-004-navigation-map-visualization-and-persistence-clarity.md)
- [ ] [**BUG-005: Dashboard window fails to shrink when toggling off debug overlay or path inspector**](BUG-005-dashboard-window-fails-to-shrink-on-overlay-toggle.md)

## Fixed Defects

- [x] [**BUG-001: Desktop UI does not run perception or detection feed when started**](fixed/BUG-001-desktop-ui-perception-feed-not-running.md)
- [x] [**BUG-003: Search mode camera rotation uses character movement keys instead of camera arrow keys**](fixed/BUG-003-search-mode-camera-rotation-keys.md)


