# Bugs

One Markdown file represents one reproducible defect. Copy `TEMPLATE.md` to
`BUG-NNN-short-title.md`. Link the story or expected behavior that proves it is a defect.

Lifecycle: `reported` -> `confirmed` -> `in-progress` -> `fixed` -> `verified` (or `rejected`). Do
not close a bug without a regression check or a documented reason why automation is impractical. Fixed
bugs are moved to `docs/bugs/fixed/`.

---

## Active Defect Backlog

- [ ] [**BUG-014: Camera alignment uses inverted wheel direction and non-functional pitch keys**](BUG-014-camera-alignment-inverted-zoom-and-wrong-pitch-keys.md)


## Fixed Defects

- [x] [**BUG-001: Desktop UI does not run perception or detection feed when started**](fixed/BUG-001-desktop-ui-perception-feed-not-running.md)
- [x] [**BUG-002: TypeError on null foreground window handle during guarded search key dispatch**](fixed/BUG-002-null-foreground-window-type-error.md)
- [x] [**BUG-003: Search mode camera rotation uses character movement keys instead of camera arrow keys**](fixed/BUG-003-search-mode-camera-rotation-keys.md)
- [x] [**BUG-004: Navigation map visualization confusing player color with spawn cells and missing close-event persistence**](fixed/BUG-004-navigation-map-visualization-and-persistence-clarity.md)
- [x] [**BUG-005: Dashboard window fails to shrink when toggling off debug overlay or path inspector**](fixed/BUG-005-dashboard-window-fails-to-shrink-on-overlay-toggle.md)
- [x] [**BUG-006: Player vitals resolution scaling and flicker spam**](fixed/BUG-006-player-vitals-resolution-scaling-and-flicker-spam.md)
- [x] [**BUG-007: Start button causes silent pause loop on focus mismatch and standby perception is completely bypassed**](fixed/BUG-007-start-button-silent-pause-and-standby-perception-bypass.md)
- [x] [**BUG-008: Placement guides in-game overlay**](fixed/BUG-008-placement-guides-in-game-overlay.md)
- [x] [**BUG-009: WASD movement tracking heading error and obstacle stall detection failure against terrain**](fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md)
- [x] [**BUG-010: Combat targeting thrashing, false floor clicks, and missing stuck engagement break timeout**](fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md)
- [x] [**BUG-011: Target name verification failure engages the wrong target**](fixed/BUG-011-target-name-verification-failure-wrong-target.md)
- [x] [**BUG-012: Monster stats OCR failure and misleading anchor diagnostics in fixed placeholder mode**](fixed/BUG-012-monster-stats-ocr-failure-and-misleading-anchor-diagnostics.md)
- [x] [**BUG-013: Tesseract OCR subprocess UnicodeDecodeError on Windows CP1252**](fixed/BUG-013-tesseract-ocr-subprocess-unicodedecodeerror-on-windows-cp1252.md)


