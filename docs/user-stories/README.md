# User Story Backlog & Roadmap

One Markdown file represents one independently testable slice of user value. Copy `TEMPLATE.md` to
`US-NNN-short-title.md`. Keep stories small; split unrelated acceptance criteria.

> **Target Scope:** All user stories target the **Entropia Flyff private server (PServer)** classic Windows
> PC client (`neuz.exe`).

Lifecycle: `draft` -> `ready` -> `in-progress` -> `done` (or `rejected`). A story is done only when
all acceptance criteria and required checks pass and affected durable docs are current. Completed
stories are moved to `docs/user-stories/completed/`.

---

## 🗺️ Story Map & Phased Roadmap

### Phase 1: Foundation & Architecture (Completed)
- [x] [**US-001: Agentic repository bootstrap**](completed/US-001-agentic-repository-bootstrap.md) — Base repository, Python 3.14, `uv`, check script, i18n, and basic Win32 input.
- [x] [**US-006: Target architecture bootstrap**](completed/US-006-target-architecture-bootstrap.md) — WorldState snapshot, Supervisor loop, STRIPS Planner skeleton, and PySide6 foundation.

### Phase 2: Perception & Computer Vision Pipeline (Active)
- [x] [**US-002: Screen and client frame capture**](completed/US-002-vision-frame-capture.md) — Fast Win32 window client capture into standard numpy image arrays.
- [x] [**US-003: Mob detection with YOLO and OpenCV**](completed/US-003-mob-detection-yolo.md) — Object detection skeleton for dynamic monsters with bounding boxes and confidence scores.
- [x] [**US-004: Target mob verification and inspection**](completed/US-004-target-mob-verification.md) — Target-bar analysis skeleton (mob name match, level, HP percentage).
- [x] [**US-005: Central loot and system log OCR extraction**](completed/US-005-loot-log-ocr.md) — Targeted OCR for drop notifications and loot events.
- [x] [**US-007: Perception to WorldState feed integration**](completed/US-007-perception-worldstate-feed.md) — Unified perception pipeline updating the immutable `WorldState`.
- [x] [**US-011: Multi-mob training dataset pipeline and custom YOLO model training**](completed/US-011-multi-mob-training-dataset-pipeline.md) — Manual annotation pipeline, dataset manifest, and lightweight ONNX export.
- [x] [**US-012: Real-world vision refactoring for robust target verification and multi-mob detection**](completed/US-012-real-world-vision-refactoring.md) — Sky/cloud-immune target-bar verification and multi-mob fixtures from real game data.
- [x] [**US-026: Static HUD anchoring and field hardening for vitals and monster stats**](completed/US-026-static-hud-anchoring-and-field-hardening.md) — Fixed top-left pixel bounding for player vitals (HP/MP/FP) and template-anchored session stats HUD detection across all window resolutions.
- [x] [**US-034: Background-independent monster stats reading and reliable kill confirmation**](completed/US-034-background-independent-monster-stats-kill-confirmation.md) — HUD text colour keying instead of contrast thresholding, mask-based anchoring on the shipped `data/monster_stats.png`, sampled OCR off the GUI thread, and baseline-gated kill confirmation.

### Phase 3: Closed-Loop Execution & Reactive Controllers
- [x] [**US-008: Reactive combat controller and target engagement**](completed/US-008-reactive-combat-controller.md) — Target selection, skill rotation, and post-action visual verification.
- [x] [**US-009: Reactive loot collector and drop accounting**](completed/US-009-reactive-loot-controller.md) — Automated item pickup routines and drop counting.
- [x] [**US-013: Autonomous farming loop and orchestration engine**](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) — Unified closed-loop session coordinating perception, combat, looting, and recovery.
- [x] [**US-023: Reliable combat targeting, click debouncing, and monster kill verification**](completed/US-023-reliable-combat-targeting-and-kill-verification.md) — Target click debouncing, reliable attack hotkey dispatching, and kill verification via health decay and HUD monster stats counter.
- [x] [**US-025: Streamlined auto-looting and loot-log OCR decoupling**](completed/US-025-streamlined-auto-looting-and-ocr-decoupling.md) — Seamless kill-to-search transition with in-game loot pets and removal of fragile Tesseract OCR from active farming loop.
- [ ] [**US-027: Minimap radar mob detection and calibrated navigation clicks**](US-027-minimap-radar-mob-detection-and-calibrated-navigation.md) — **Rejected**: superseded by the US-019 spawn heatmap and patrol circuits, which already reach spawns outside the viewport without a second guarded click path aimed at the HUD.
- [x] [**US-031: Target selection cooldown and dead mob spatial lockout**](completed/US-031-target-cooldown-and-dead-mob-blacklist.md) — Prevent re-clicking dying mob corpses and empty ground by locking out recently defeated or failed mob positions for 4.0s. Delivered by BUG-010.

### Phase 4: Desktop UI & Visual Debugging
- [x] [**US-010: Native PySide6 dashboard and visual debug overlay**](completed/US-010-pyside6-dashboard-and-overlay.md) — Desktop monitoring, live YOLO overlay, recipe progress, and killswitch controls.
- [x] [**US-014: Configurable UI attack key with key capture**](completed/US-014-configurable-ui-attack-key.md) — Dynamic combat hotkey configuration with F3 default.
- [x] [**US-015: Idle timeout detection and staged search navigation**](completed/US-015-idle-timeout-and-search-navigation.md) — Camera rotation and staged exploration when no mobs are in view.
- [x] [**US-016: Auto power-ups and timed hotkeys**](completed/US-016-auto-power-ups-and-timed-hotkeys.md) — Timed recurring buff and utility hotkey scheduler with UI management.
- [x] [**US-017: Player vital gauges perception and threshold-based auto-consumables**](completed/US-017-player-vitals-perception-and-threshold-triggers.md) — Top-left HP/MP/FP pixel extraction with configurable threshold triggers.
- [x] [**US-018: Multi-axis camera search with vertical pitch tilt and paced scanning**](completed/US-018-multi-axis-camera-search-and-paced-scanning.md) — Multi-axis camera scanning with vertical pitch adjustment and paced settling.
- [x] [**US-019: Intelligent pathing and topological spawn heatmap for monster farming**](completed/US-019-intelligent-pathing-and-spawn-heatmap.md) — Internal spatial memory, spawn heatmaps, stuck cost penalties, and adaptive patrol circuits.
- [x] [**US-020: Visual navigation path and spawn heatmap inspector in desktop UI**](completed/US-020-visual-navigation-path-and-heatmap-inspector.md) — 2D canvas inspector for live position, traversed pathways, spawn hotspots, and active patrol routes.
- [x] [**US-021: Navigation map profile slots, persistence management, and session reset**](completed/US-021-navigation-map-profiles-and-session-reset.md) — Named `.json` profile slots, Load/Save/Reset controls in UI, and confirmation safeguards.
- [x] [**US-022: Modern dark theme and streamlined dashboard UI**](completed/US-022-modern-dark-theme-and-streamlined-dashboard-ui.md) — Visually polished modern dark theme (QSS), card layout, pop-out navigation map window, and Escape key emergency stop.
- [x] [**US-024: Target verification decision and threshold debug dashboard visualization**](completed/US-024-target-verification-debug-dashboard-visualization.md) — Live header-anchor, HP-bar, and name-match scores/thresholds surfaced in a dedicated `MainWindow` debug panel.
- [x] [**US-028: Live perception standby, bot status visualization, and robust start focus workflow**](completed/US-028-live-perception-standby-and-focus-workflow.md) — Standby read-only perception loop for live HUD/vitals/mobs inspection, dedicated status indicators, and reliable game window focus startup.
- [x] [**US-029: Anchor-relative target verification, configurable thresholds, and full diagnostic metrics**](completed/US-029-configurable-target-verification-thresholds.md) — Dynamic target header anchor-relative ROI extraction and live UI threshold controls.
- [x] [**US-030: Monster stats HUD OCR diagnostics and debug dashboard panel**](completed/US-030-monster-stats-hud-ocr-diagnostics-and-debug-panel.md) — Live OCR diagnostics and dedicated dashboard debug panel for session monster kill statistics.
- [x] [**US-032: Tesseract OCR target name verification and robust whitelist matching**](completed/US-032-tesseract-ocr-target-name-verification.md) — Robust OCR-based target name verification replacing rigid template matching.
- [ ] [**US-033: Automated Tesseract OCR installation via winget and live reload**](US-033-tesseract-ocr-automated-installation-and-detection.md) — One-click background `winget` installation of Tesseract OCR with UI guidance and non-restarting live reload.

### Phase 5: Navigation Accuracy (Planned)

Closes the open-loop gap in the US-019 pathing stack: today every learned cell, edge, hotspot, and
route rests on a dead-reckoned position built from unmeasured key-press constants. Grounded in the
[minimap odometry spike](../sources/2026-08-18-minimap-odometry-feasibility-spike.md).

- [x] [**US-035: Measured minimap odometry, tracking quality gating, and calibrated movement constants**](completed/US-035-measured-minimap-odometry-and-tracking-quality.md) — Position and heading measured from the north-up minimap by phase correlation and marker orientation, map learning gated on measurement confidence, and the movement constants fitted from recorded frames ([calibration](../sources/2026-08-18-minimap-odometry-calibration.md)).
- [x] [**US-036: Navigation profile anchoring so saved maps mean the same place in a later session**](completed/US-036-navigation-profile-anchoring-across-sessions.md) — Schema v2 anchor record per profile, re-anchoring on load against the live minimap, and a defined refusal path instead of a silently shifted map. The manual field walkthrough, including the usable re-anchoring radius, stays open.
- [ ] [**US-037: Measured spawn distance model and an enforced patrol leash**](US-037-measured-spawn-distance-and-enforced-leash.md) — Replace the guessed bounding-box distance literals with a fitted inverse-projection relation and make `leash_radius_pixels` constrain planning instead of only the drawing. Leash enforcement and its operator visibility landed on 2026-08-18; the fitted distance relation stays blocked on recorded approach sequences.
- [ ] [**US-038: Target mob dropdown and early YOLO filtering**](US-038-target-mob-dropdown-and-early-yolo-filtering.md) — Dynamic class dropdown selection populated from YOLO model labels.
- [ ] [**US-039: Combat obstacle stall detection and adaptive re-navigation**](US-039-combat-obstacle-stall-detection-and-re-navigation.md) — Peripheral stall detection during combat approach, engagement breaking, and 30s obstacle blacklist.
- [x] [**US-040: Unrecoverable stuck emergency teleport and spawn point reset**](completed/US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md) — Continuous unstuck timeout, configurable emergency teleport key (Town Blinkwing), and per-map spawn point re-anchoring.
- [x] [**US-041: Automated mob spawn distance and bearing calibration capture script**](completed/US-041-spawn-distance-calibration-capture-script.md) — Developer capture harness recording synchronized walk-in sequences (YOLO bounding box heights + minimap odometry) and bearing offsets for fitting US-037 distance curves.
- [x] [**US-035 (quotas): Multi-target monster selection and per-mob kill quotas**](completed/US-035-multi-target-selection-and-per-mob-kill-quotas.md) — Multi-select monster panel with per-class kill quotas, SQLite kill history, live quota progress, dynamic whitelist narrowing, and an optional client shutdown on completion. The identifier repeats the minimap odometry US-035 above; the two are distinguished by file name.
- [x] [**US-042: Automated camera alignment and standardized viewport initialization**](completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md) — Deterministic pre-flight and on-demand camera alignment routine setting zoom hard-stop and ~45° pitch so perception distance models match live farming.
- [x] [**US-043: Continuous approach target tracking and minimap zoom initialization**](completed/US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md) — Continuous Kalman/odometry tracking during combat approaches and automated minimap zoom initialization.
- [x] [**US-045: Vector world and terrain passability extraction with goal-driven zone navigation**](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md) — Vector spawn zones, terrain elevation, impassable slope extraction, and Visibility-Graph A* path planning.
- [ ] [**US-046: Premium monster HP OCR and exact combat tracking**](US-046-premium-monster-hp-ocr-and-exact-combat-tracking.md) — Direct numeric HP text reading from target nameplates for exact combat progress.
- [ ] [**US-047: In-game area farm start marker and vector zone boundary overlay**](US-047-in-game-area-farm-start-marker-and-zone-overlay.md) — Transparent desktop overlay rendering the start anchor, vector zone origin, and live player offset directly over the game client.
- [x] [**US-048: Live 3D coordinates, terrain-aware routing, and teleport dispatch**](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md) — Fingerprinted coordinate-only memory reads, live-confirmed long-range dispatch, elevation-aware A*, recovery maneuvers, and a 3D-enriched inspector. The full repository gate passes; the Windows live-client walkthrough remains open.
