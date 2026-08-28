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

### Phase 2: Perception & Computer Vision Pipeline (Completed)
- [x] [**US-002: Screen and client frame capture**](completed/US-002-vision-frame-capture.md) — Fast Win32 window client capture into standard numpy image arrays.
- [x] [**US-003: Mob detection with YOLO and OpenCV**](completed/US-003-mob-detection-yolo.md) — Object detection skeleton for dynamic monsters with bounding boxes and confidence scores.
- [x] [**US-004: Target mob verification and inspection**](completed/US-004-target-mob-verification.md) — Target-bar analysis skeleton (mob name match, level, HP percentage).
- [x] [**US-005: Central loot and system log OCR extraction**](completed/US-005-loot-log-ocr.md) — Targeted OCR for drop notifications and loot events.
- [x] [**US-007: Perception to WorldState feed integration**](completed/US-007-perception-worldstate-feed.md) — Unified perception pipeline updating the immutable `WorldState`.
- [x] [**US-011: Multi-mob training dataset pipeline and custom YOLO model training**](completed/US-011-multi-mob-training-dataset-pipeline.md) — Manual annotation pipeline, dataset manifest, and lightweight ONNX export.
- [x] [**US-012: Real-world vision refactoring for robust target verification and multi-mob detection**](completed/US-012-real-world-vision-refactoring.md) — Sky/cloud-immune target-bar verification and multi-mob fixtures from real game data.
- [x] [**US-026: Static HUD anchoring and field hardening for vitals and monster stats**](completed/US-026-static-hud-anchoring-and-field-hardening.md) — Fixed top-left pixel bounding for player vitals (HP/MP/FP) and template-anchored session stats HUD detection across all window resolutions.
- [x] [**US-034: Background-independent monster stats reading and reliable kill confirmation**](completed/US-034-background-independent-monster-stats-kill-confirmation.md) — HUD text colour keying instead of contrast thresholding, mask-based anchoring on the shipped `data/monster_stats.png`, sampled OCR off the GUI thread, and baseline-gated kill confirmation.

### Phase 3: Closed-Loop Execution & Reactive Controllers (Completed)
- [x] [**US-008: Reactive combat controller and target engagement**](completed/US-008-reactive-combat-controller.md) — Target selection, skill rotation, and post-action visual verification.
- [x] [**US-009: Reactive loot collector and drop accounting**](completed/US-009-reactive-loot-controller.md) — Automated item pickup routines and drop counting.
- [x] [**US-013: Autonomous farming loop and orchestration engine**](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md) — Unified closed-loop session coordinating perception, combat, looting, and recovery.
- [x] [**US-023: Reliable combat targeting, click debouncing, and monster kill verification**](completed/US-023-reliable-combat-targeting-and-kill-verification.md) — Target click debouncing, reliable attack hotkey dispatching, and kill verification via health decay and HUD monster stats counter.
- [x] [**US-025: Streamlined auto-looting and loot-log OCR decoupling**](completed/US-025-streamlined-auto-looting-and-ocr-decoupling.md) — Seamless kill-to-search transition with in-game loot pets and removal of fragile Tesseract OCR from active farming loop.
- [ ] [**US-027: Minimap radar mob detection and calibrated navigation clicks**](obsolete/US-027-minimap-radar-mob-detection-and-calibrated-navigation.md) — **Rejected**: superseded by the US-019 spawn heatmap and patrol circuits.
- [x] [**US-031: Target selection cooldown and dead mob spatial lockout**](completed/US-031-target-cooldown-and-dead-mob-blacklist.md) — Prevent re-clicking dying mob corpses and empty ground by locking out recently defeated or failed mob positions for 4.0s. Delivered by BUG-010.

### Phase 4: Desktop UI & Visual Debugging (Completed)
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
- [ ] [**US-033: Automated Tesseract OCR installation via winget and live reload**](obsolete/US-033-tesseract-ocr-automated-installation-and-detection.md) — One-click background `winget` installation of Tesseract OCR.
- [x] [**US-050: Responsive tabbed dashboard and UI design overhaul**](completed/US-050-responsive-tabbed-dashboard-and-ui-refactoring.md) — Pinned session controls above five scrollable functional tabs, stable geometry, localized switch controls, and independent live state feeds.
- [x] [**US-074: Interactive world map and spawn zone inspector**](completed/US-074-interactive-world-map-and-spawn-zone-visualizer.md) — Extracted terrain, NavMesh, and spawn-zone visualization with guarded pan/zoom, follow mode, tooltips, and camp selection.

### Phase 5: Navigation Accuracy & World Integration (Completed)
- [x] [**US-035: Measured minimap odometry, tracking quality gating, and calibrated movement constants**](completed/US-035-measured-minimap-odometry-and-tracking-quality.md) — Position and heading measured from the north-up minimap.
- [x] [**US-036: Navigation profile anchoring so saved maps mean the same place in a later session**](completed/US-036-navigation-profile-anchoring-across-sessions.md) — Schema v2 anchor record per profile.
- [x] [**US-037: Measured spawn distance model and an enforced patrol leash**](completed/US-037-measured-spawn-distance-and-enforced-leash.md) — Patrol leash enforcement and operator bounds visibility.
- [x] [**US-038: Target mob dropdown and early YOLO filtering**](completed/US-038-target-mob-dropdown-and-early-yolo-filtering.md) — Dynamic class dropdown selection populated from YOLO model labels.
- [x] [**US-039: Combat obstacle stall detection and adaptive re-navigation**](completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md) — Peripheral stall detection during combat approach, engagement breaking, and 30s obstacle blacklist.
- [x] [**US-040: Unrecoverable stuck emergency teleport and spawn point reset**](completed/US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md) — Continuous unstuck timeout and last-resort recovery.
- [x] [**US-041: Automated mob spawn distance and bearing calibration capture script**](completed/US-041-spawn-distance-calibration-capture-script.md) — Developer capture harness recording synchronized walk-in sequences.
- [x] [**US-035 (quotas): Multi-target monster selection and per-mob kill quotas**](completed/US-035-multi-target-selection-and-per-mob-kill-quotas.md) — Multi-select monster panel with per-class kill quotas.
- [x] [**US-042: Automated camera alignment and standardized viewport initialization**](completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md) — Deterministic pre-flight and on-demand camera alignment routine.
- [x] [**US-043: Continuous approach target tracking and minimap zoom initialization**](completed/US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md) — Continuous Kalman/odometry tracking during combat approaches.
- [x] [**US-045: Vector world and terrain passability extraction with goal-driven zone navigation**](completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md) — Vector spawn zones, terrain elevation, impassable slope extraction, and Visibility-Graph A* path planning.
- [ ] [**US-046: Premium monster HP OCR and exact combat tracking**](obsolete/US-046-premium-monster-hp-ocr-and-exact-combat-tracking.md) — Direct numeric HP text reading.
- [ ] [**US-047: In-game area farm start marker and vector zone boundary overlay**](obsolete/US-047-in-game-area-farm-start-marker-and-zone-overlay.md) — Transparent desktop overlay.
- [x] [**US-048: Live 3D coordinates, terrain-aware routing, and teleport dispatch**](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md) — Fingerprinted coordinate-only memory reads, live-confirmed long-range dispatch, elevation-aware A*.
- [x] [**US-051: Teleport dispatch simplification and emergency Eden reset**](completed/US-051-teleport-dispatch-simplification-and-emergency-eden-reset.md) — Built-in teleporter UI extraction and authoritative arrival confirmation.
- [x] [**US-053: Pure 3D GPS navigation and client profile configuration**](completed/US-053-pure-gps-navigation-and-client-profile-configuration.md) — Operator-editable fingerprinted client profiles and GPS-only vector routing.
- [x] [**US-056: Client camera state and projection matrix memory reader**](completed/US-056-client-camera-state-and-projection-matrix-reader.md) — Exact-fingerprint, foreground-gated camera matrix reads.
- [x] [**US-060: Combat class profiles, responsive direct targeting, and lockout minimization**](completed/US-060-combat-class-profiles-responsive-direct-targeting-and-lockout-minimization.md) — Melee/ranged/custom engagement presets.
- [x] [**US-064: Continuous human-like movement, held-key pathing, and smooth heading control**](completed/US-064-continuous-human-like-movement-and-held-key-pathing.md) — Authoritative NavMesh/GPS pathing controller with multi-key turning support, consolidated into US-085.
- [ ] [**US-075: Portable one-click static client data extraction**](obsolete/US-075-portable-client-static-data-extraction.md) — **Superseded**: Consolidated into US-078.
- [x] [**US-076: Complete fingerprinted client player stats reader**](completed/US-076-complete-client-player-stats-reader.md) — Profile-driven, bounded client-stat snapshots.
- [x] [**US-077: Central live-state readiness gate refactor**](completed/US-077-central-live-state-readiness-gate.md) — Central typed readiness aggregation validates GPS, camera, player stats, dungeon state, perception freshness, and focus.
- [x] [**US-078: Initial setup wizard, unified client data extraction, and memory profile generation**](completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md) — Guided first-launch wizard and static client data extraction.

### Phase 6: Machine Learning, Empirical Navigation & Reinforcement Learning (Completed)
- [x] [**US-066: Farming and navigation value model and offline telemetry learning**](completed/US-066-farming-and-navigation-value-model.md) — Offline predictive models for travel time, stuck risk, recovery cost, and kill duration.
- [x] [**US-067: Unified tactical policy interface, heuristic baseline, and learned policy integration**](completed/US-067-unified-tactical-policy-integration.md) — Typed `TacticalPolicy` abstraction with `HeuristicPolicy` and `LearnedPolicy` implementations.
- [x] [**US-068: Rolling-horizon multi-target sequencing and lookahead planning**](completed/US-068-rolling-horizon-multi-target-planning.md) — Multi-kill candidate evaluation using lookahead.
- [x] [**US-069: Experience-based NavMesh routing and empirical traversal cost integration**](completed/US-069-experience-based-navmesh-routing.md) — Empirical polygon/edge statistics and weighted A* costs.
- [x] [**US-070: Learned attack point positioning and local waypoint optimization**](completed/US-070-learned-attack-point-and-local-waypoint-optimization.md) — NavMesh attack-point sampling and Funnel pathing.
- [x] [**US-071: Unified RL environment formulation, state-action space, and progress reward modeling**](completed/US-071-unified-rl-environment-and-reward.md) — MDP observation space, discrete tactical actions, and telemetry transition exporter.
- [x] [**US-072: Fast offline farming, navigation, and quest dynamics simulator**](completed/US-072-offline-farming-and-navigation-simulator.md) — Offline Python simulator modeling NavMesh pathing, mob spawns, and combat TTK.
- [x] [**US-073: Hierarchical RL policy for unified farming, navigation, and quest optimization**](completed/US-073-hierarchical-rl-farming-navigation-and-quest-policy.md) — Two-tier hierarchical RL policy in simulation.
- [x] [**US-079: Unified versioned goal-conditioned decision contract**](completed/US-079-unified-goal-conditioned-decision-contract.md) — Unified observation, parameterized action, mask, and reward contract.
- [x] [**US-080: Goal-driven quest execution and objective bus**](completed/US-080-goal-driven-quest-execution-and-objective-bus.md) — Autonomous quest objective resolution, teleporter travel, NPC interaction, and combat.
- [x] [**US-081: Experience database and a reproducible train, evaluate, promote and deploy loop**](completed/US-081-experience-database-and-train-evaluate-promote-loop.md) — SQLite experience recording and closed offline loop consolidated into US-085.
- [x] [**US-082: ML and RL engineering quality gate**](completed/US-082-ml-rl-engineering-quality-gate.md) — Production code assert removal and quality gate consolidated into US-085.
- [x] [**US-083: Authoritative client-data fusion for YOLO-guided efficient farming**](completed/US-083-authoritative-client-data-fusion-for-yolo-farming.md) — Mover catalog extraction, label mapping, temporal observation interval coherence, target reconciliation, and early YOLO filtering.
- [x] [**US-084: ML-modifiable tactical parameter space, hybrid tuning, and clamped safety bounds**](completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md) — Bounded tactical parameter space with preset management.

### Phase 7: Production Readiness & Autonomous Farming Polish (Active)
- [ ] [**US-085: Production readiness, first-run wizard autostart, and autonomous farming polish**](US-085-production-readiness-and-autonomous-farming-polish.md) — First-run wizard auto-detection on desktop startup, seamless dataset autoloading, production code assertion cleanup, robust autonomous farming loop with NavMesh/GPS pathing and combat reconciliation, 100% synchronized locales, and complete green quality gate.
- [ ] [**US-086: Unattended autopilot mode, session resilience, and autonomous goal arbitration**](US-086-unattended-autopilot-session-resilience-and-goal-arbitration.md) — Guarded tick loop with heartbeat and watchdog, player death state and respawn, emergency stop without `ESC`, graded fault recovery instead of session pause, deterministic goal arbitration with time and recovery budgets, and camera-projected quest NPC interaction.
- [x] [**US-087: Dedicated ML/RL insights and policy debugging dashboard tab**](completed/US-087-ml-rl-insights-and-policy-debugging-dashboard-tab.md) — Read-only ML and policy dashboard tab with live inference latency against the 5 ms budget, candidate ranking and mask verdicts, shadow agreement tracking, decomposed reward and experience telemetry, and the dynamic tactical-parameter comparison.
