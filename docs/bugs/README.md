# Bugs

One Markdown file represents one reproducible defect. Copy `TEMPLATE.md` to
`BUG-NNN-short-title.md`. Link the story or expected behavior that proves it is a defect.

> **Target Scope:** All bug reports and reproductions target the **Entropia Flyff private server (PServer)**
> classic Windows PC client (`neuz.exe`).

Lifecycle: `reported` -> `confirmed` -> `in-progress` -> `fixed` -> `verified` (or `rejected`). Do
not close a bug without a regression check or a documented reason why automation is impractical. Fixed
bugs are moved to `docs/bugs/fixed/`.

---

## Active Defect Backlog

*No open active defects.* All reported bugs have been verified and moved to `fixed/`. Any new defects discovered during production execution begin in this backlog with a testable reproduction.

---

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
- [x] [**BUG-014: Camera alignment uses inverted wheel direction and non-functional pitch keys**](fixed/BUG-014-camera-alignment-inverted-zoom-and-wrong-pitch-keys.md)
- [x] [**BUG-015: Camera alignment mouse wheel zoom-out has no observable effect on game viewport**](fixed/BUG-015-camera-alignment-zoom-out-has-no-effect.md)
- [x] [**BUG-016: Camera alignment dispatches forward mouse wheel notches zooming in instead of zooming out**](fixed/BUG-016-camera-alignment-inverted-mouse-wheel-zoom-direction.md)
- [x] [**BUG-017: Invisible wall collision stall detection and recovery pathfinding**](fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md)
- [x] [**BUG-018: Win32 ModuleEntry32W structure bad length error in LivePositionReader**](fixed/BUG-018-win32-module-entry-structure-bad-length-error.md)
- [x] [**BUG-019: Live camera poll suppressed by the GPS sample guard freezes the steering heading**](fixed/BUG-019-live-camera-poll-suppressed-by-gps-sample-guard.md)
- [x] [**BUG-020: Emergency recovery measures world-unit GPS movement against a minimap pixel threshold**](fixed/BUG-020-emergency-recovery-progress-threshold-in-minimap-pixels.md)
- [x] [**BUG-021: Vector navigation offers no multi-zone selection and renders debug values unlocalized**](fixed/BUG-021-multi-zone-selection-and-localized-debug-values-missing.md)
- [x] [**BUG-022: Dungeon live reader missing foreground guard and disk-thrashing SHA-256 hashing**](fixed/BUG-022-dungeon-live-reader-missing-foreground-guard-and-disk-thrashing.md)
- [x] [**BUG-023: Player stats reader masks invalid pointer and malformed read diagnostics**](fixed/BUG-023-player-stats-reader-masks-invalid-pointer-and-malformed-read-diagnostics.md)
- [x] [**BUG-024: Teleporter dispatch is not integrated or production capable**](fixed/BUG-024-teleporter-dispatch-is-not-integrated-or-production-capable.md)
- [x] [**BUG-025: Committed test artifacts mutate the repository**](fixed/BUG-025-committed-test-artifacts-mutate-the-repository.md)
- [x] [**BUG-026: Teleporter hotkey bypasses foreground guard**](fixed/BUG-026-teleporter-hotkey-bypasses-foreground-guard.md)
- [x] [**BUG-027: Arrival observer relies on private reader state**](fixed/BUG-027-arrival-observer-relies-on-private-reader-state.md)
- [x] [**BUG-028: UI refactor retains private control coupling and stale gate evidence**](fixed/BUG-028-ui-refactor-retains-private-control-coupling-and-stale-gate-evidence.md)
- [x] [**BUG-029: Tesseract OCR TSV argument ordering causes empty stdout and unreadable target names**](fixed/BUG-029-tesseract-ocr-tsv-argument-ordering-causes-empty-stdout-and-unreadable-target-names.md)
- [x] [**BUG-030: RL and ML stack cannot produce or execute a valid learned policy**](fixed/BUG-030-rl-ml-stack-invalid-training-and-live-execution.md)
- [x] [**BUG-031: The learning loop is open - recorded data is untrainable and no trained policy can act live**](fixed/BUG-031-learning-loop-is-open-recorded-data-and-live-inference.md)
- [x] [**BUG-032: Simulator dynamics and paired evaluation invalidate every learned-policy metric**](fixed/BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md)
- [x] [**BUG-033: Unified setup does not ingest or autoload the client data it reports**](fixed/BUG-033-unified-setup-does-not-ingest-or-autoload-client-data.md)
- [x] [**BUG-034: Live readers ignore foreground contract**](fixed/BUG-034-live-readers-ignore-foreground-contract.md)
