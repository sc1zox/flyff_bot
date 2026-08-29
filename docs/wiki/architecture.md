---
title: Architecture
status: active
updated: 2026-08-29
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
  - ../sources/2026-08-18-minimap-odometry-calibration.md
  - ../sources/2026-08-19-target-server-entropia-pserver-clarification.md
  - ../sources/2026-08-19-entropia-client-navigation-data-extraction.md
  - ../sources/2026-08-20-entropia-camera-static-analysis.md
  - ../sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md
  - ../sources/2026-08-28-operator-verified-eden-mover-symbols.md
  - ../sources/2026-08-28-tactical-policy-inference-latency-measurement.md
related:
  - project-overview.md
  - glossary.md
  - ../decisions/ADR-001-cli-before-http-server.md
  - ../decisions/ADR-002-target-architecture-and-pyside6.md
  - ../decisions/ADR-003-clean-schema-over-backward-compatibility.md
  - ../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md
  - ../decisions/ADR-006-read-only-process-memory-access.md
  - ../decisions/ADR-008-closed-learning-loop-invariants.md
  - ../decisions/ADR-009-bounded-tactical-parameter-space.md
  - ../decisions/ADR-011-dungeon-cooldowns-are-not-fingerprint-bindable-only-the-account-lockout-is.md
  - ../user-stories/completed/US-002-vision-frame-capture.md
  - ../user-stories/completed/US-003-mob-detection-yolo.md
  - ../user-stories/completed/US-004-target-mob-verification.md
  - ../user-stories/completed/US-005-loot-log-ocr.md
  - ../user-stories/completed/US-008-reactive-combat-controller.md
  - ../user-stories/completed/US-079-unified-goal-conditioned-decision-contract.md
  - ../user-stories/completed/US-084-ml-modifiable-tactical-parameters-and-tuning.md
  - ../user-stories/completed/US-085-production-readiness-and-autonomous-farming-polish.md
  - ../user-stories/completed/US-091-unified-goal-navigation-fluid-scanning-and-intelligent-unstuck.md
  - ../user-stories/completed/US-093-geometry-verified-stall-recovery-and-navmesh-routing-unification.md
  - ../user-stories/completed/US-086-unattended-autopilot-session-resilience-and-goal-arbitration.md
  - ../user-stories/completed/US-009-reactive-loot-controller.md
  - ../user-stories/completed/US-011-multi-mob-training-dataset-pipeline.md
  - ../user-stories/completed/US-012-real-world-vision-refactoring.md
  - ../user-stories/completed/US-013-autonomous-farming-loop-and-orchestration-engine.md
  - ../user-stories/completed/US-014-configurable-ui-attack-key.md
  - ../user-stories/completed/US-015-idle-timeout-and-search-navigation.md
  - ../user-stories/completed/US-018-multi-axis-camera-search-and-paced-scanning.md
  - ../user-stories/completed/US-019-intelligent-pathing-and-spawn-heatmap.md
  - ../user-stories/completed/US-020-visual-navigation-path-and-heatmap-inspector.md
  - ../user-stories/completed/US-021-navigation-map-profiles-and-session-reset.md
  - ../user-stories/completed/US-071-unified-rl-environment-and-reward.md
  - ../user-stories/completed/US-035-measured-minimap-odometry-and-tracking-quality.md
  - ../user-stories/completed/US-036-navigation-profile-anchoring-across-sessions.md
  - ../user-stories/completed/US-037-measured-spawn-distance-and-enforced-leash.md
  - ../user-stories/completed/US-041-spawn-distance-calibration-capture-script.md
  - ../user-stories/completed/US-042-automated-camera-alignment-and-standardized-viewport-initialization.md
  - ../user-stories/completed/US-022-modern-dark-theme-and-streamlined-dashboard-ui.md
  - ../user-stories/completed/US-023-reliable-combat-targeting-and-kill-verification.md
  - ../user-stories/completed/US-025-streamlined-auto-looting-and-ocr-decoupling.md
  - ../user-stories/completed/US-026-static-hud-anchoring-and-field-hardening.md
  - ../user-stories/completed/US-028-live-perception-standby-and-focus-workflow.md
  - ../user-stories/completed/US-029-configurable-target-verification-thresholds.md
  - ../user-stories/completed/US-030-monster-stats-hud-ocr-diagnostics-and-debug-panel.md
  - ../bugs/fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md
  - ../bugs/fixed/BUG-010-combat-targeting-thrashing-and-stuck-engagement-timeout.md
  - ../user-stories/completed/US-031-target-cooldown-and-dead-mob-blacklist.md
  - ../user-stories/completed/US-016-auto-power-ups-and-timed-hotkeys.md
  - ../user-stories/completed/US-032-tesseract-ocr-target-name-verification.md
  - ../bugs/fixed/BUG-011-target-name-verification-failure-wrong-target.md
  - ../bugs/fixed/BUG-012-monster-stats-ocr-failure-and-misleading-anchor-diagnostics.md
  - ../user-stories/completed/US-034-background-independent-monster-stats-kill-confirmation.md
  - ../user-stories/completed/US-035-multi-target-selection-and-per-mob-kill-quotas.md
  - ../user-stories/completed/US-038-target-mob-dropdown-and-early-yolo-filtering.md
  - ../bugs/fixed/BUG-014-camera-alignment-inverted-zoom-and-wrong-pitch-keys.md
  - ../bugs/fixed/BUG-015-camera-alignment-zoom-out-has-no-effect.md
  - ../user-stories/completed/US-043-continuous-approach-target-tracking-and-minimap-zoom-initialization.md
  - ../user-stories/completed/US-039-combat-obstacle-stall-detection-and-re-navigation.md
  - ../user-stories/completed/US-040-unrecoverable-stuck-emergency-teleport-and-spawn-reset.md
  - ../user-stories/completed/US-045-vector-world-terrain-extraction-and-goal-navigation.md
  - ../user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md
  - ../bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md
  - ../user-stories/completed/US-049-session-event-log-and-transition-diagnostics.md
  - ../user-stories/completed/US-050-responsive-tabbed-dashboard-and-ui-refactoring.md
  - ../user-stories/completed/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md
  - ../user-stories/completed/US-056-client-camera-state-and-projection-matrix-reader.md
  - ../user-stories/completed/US-076-complete-client-player-stats-reader.md
  - ../user-stories/completed/US-077-central-live-state-readiness-gate.md
  - ../user-stories/completed/US-055-authoritative-3d-world-geometry-and-navmesh-foundation.md
  - ../user-stories/completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md
  - ../user-stories/completed/US-057-yolo-bottom-center-camera-unprojection-and-navmesh-mob-positioning.md
  - ../user-stories/completed/US-059-authoritative-vector-navigation-legacy-removal-and-multi-zone-selection.md
  - ../user-stories/completed/US-061-client-quest-data-extraction-and-goal-driven-quest-farming.md
  - ../user-stories/completed/US-062-automated-npc-quest-acceptance-and-turn-in.md
  - ../user-stories/completed/US-080-goal-driven-quest-execution-and-objective-bus.md
  - ../user-stories/completed/US-066-farming-and-navigation-value-model.md
  - ../user-stories/completed/US-069-experience-based-navmesh-routing.md
  - ../user-stories/completed/US-068-rolling-horizon-multi-target-planning.md
  - ../user-stories/completed/US-063-client-dungeon-data-and-live-cooldown-memory-extraction.md
  - ../user-stories/completed/US-089-automated-client-binary-reverse-engineering-and-memory-profiling.md
  - ../bugs/fixed/BUG-036-dungeon-extraction-missing-script-and-misleading-ui-status.md
  - ../user-stories/completed/US-078-initial-setup-wizard-and-unified-client-data-extraction.md
  - ../bugs/fixed/BUG-029-tesseract-ocr-tsv-argument-ordering-causes-empty-stdout-and-unreadable-target-names.md
  - ../bugs/fixed/BUG-032-simulator-dynamics-and-paired-evaluation-invalidate-policy-metrics.md
  - ../decisions/ADR-007-offline-tactical-simulation-boundary.md
---

# Architecture

The codebase follows a typed `src` layout with feature-scoped modules. The target game client is the
**Entropia Flyff private server (PServer)** running as a native Windows desktop client (`neuz.exe`).

The architecture is designed as a multi-tier closed-loop control system:

```text
Recipe / Goal
     ↓
Planner (STRIPS / High-level Goals)
     ↓
Supervisor (Reconciliation & Self-Healing Loop)
     ↕
World State (Central Snapshot)
     ↑
Perception (YOLO / Template Matching / ROI OCR)
     ↓
Reactive Controllers (Combat / Navigation / Loot)
     ↓
Executor (Win32 Input with Action Verification)
     ↓
Game Client (Entropia Flyff neuz.exe)
```

## Layers and Components

1. **Perception Layer:**
   - **YOLO:** `OpenCVDnnYoloDetector` loads raw YOLO ONNX models and ordered UTF-8 labels,
     performs CPU OpenCV-DNN inference, filters by confidence and class name, and applies NMS.
     It returns structured client-space detections with a bounding box, confidence, class ID, and
     class name; the `Detector` protocol supports deterministic mock implementations.
   - **Template Matching:** Detection of fixed 2D UI elements and anchors.
   - **OCR Engine:** `TesseractTextRecognizer` (`features/vision/ocr.py`) implements the `TextRecognizer`
     protocol, providing localized OCR text recognition for target nameplate verification and HUD
     monster stats extraction with UTF-8 decoding resilience.
   - **Frame capture:** `WindowsFrameSource` captures the foreground client's exact client area
     through documented Win32 GDI APIs and exposes contiguous BGR or RGB `numpy.ndarray` frames.
     Its `FrameSource` protocol is injectable for deterministic tests, and capture failures use
     typed error codes. `require_foreground=False` relaxes only the foreground precondition for
     read-only standby previews (US-028); closed and minimized windows still fail.
   - **Target verification:** `TargetVerifier` template-matches a configured header anchor, then
     crops the HP-bar and mob-name rectangles at fixed pixel offsets from that match position,
     measures HP colour, and reads the nameplate through an injectable OCR `TextRecognizer` before
     matching it against the configured whitelist. It returns `VALID_TARGET`, `WRONG_TARGET`, or
     `NO_TARGET`, including an HP percentage calculated only from the HP-bar crop, without
     dispatching any input.
   - **Perception pipeline:** `PerceptionPipeline` captures one frame per tick and passes that
     shared frame to mob detection, target verification, player vitals reading, and monster stats
     reading. It maps their outputs into a fresh immutable `WorldState`, emits target-change and
     newly-visible-mob events, and records feed-specific failures while retaining the prior value
     for a failed feed.
   - **Training dataset:** `flyff_bot.features.training` provides an offline standard-YOLO
     dataset validator and an optional Ultralytics training/export adapter. The validator checks
     the train/validation image-label layout, image readability, matching label files, normalized
     annotations, and a contiguous numeric class registry. The adapter exports an ONNX model and
     ordered UTF-8 labels compatible with `OpenCVDnnYoloDetector`; neither path accesses the game
     client.
2. **State & Supervisor:**
   - **World State:** Immutable snapshot representing current assumed game reality.
   - **Supervisor:** Closed-loop reconciliation comparing desired state vs. observed state; detects stalls and triggers self-healing (`NO_PROGRESS`, `NO_MOBS`, `STUCK`, `INVENTORY_MISMATCH`).
3. **Planning & Control:**
   - **Strategic Planner:** STRIPS/Goal-based planner for recipes and high-level milestones.
   - **Reactive Controllers:** Modular state machines for micro-behaviors (Combat, Navigation, Loot).
4. **Execution & Platform:**
   - **Executor:** Decoupled Win32 input adapter; actions require post-execution visual verification to be deemed successful.
   - **User Interface:** Native Windows UI using PySide6 (Qt) to avoid separate web runtimes.

Classes are used for stateful controllers, supervisor loops, and resource bundles. Pure transformations remain functions. Business defaults and Win32 codes are named in constants, and user-facing text is localized in locale JSON files.

## Implemented bootstrap

US-006 establishes the typed foundation under `flyff_bot.features.automation`. Immutable
`WorldState`, `Action`, and `Observation` contracts are shared by the planning, control, and
execution boundaries. The `Supervisor` reconciles a `DesiredState` with each world-state snapshot
and reports the four failure flags defined by ADR-002; its no-progress threshold is configurable.

The initial `Planner` is a deterministic STRIPS-style search over typed planning actions. Combat,
navigation, and loot are separate reactive controllers whose `step` methods accept synthetic
world-state snapshots. `VerifiedExecutor` dispatches through a platform adapter and returns a
successful result only when the next observation is both confirmed and matches the action's
required observation.

The desktop presentation is a small PySide6 application boundary (`flyff_bot.ui`) that renders a
localized world-state summary. It introduces no web runtime. It is deliberately a bootstrap: real
Win32 input dispatch remains separate future work. US-002 provides foreground client-area capture
with client-space coordinates preserved for downstream vision and input verification; US-003 adds
the first production-facing model adapter for YOLO object detection. US-004 adds target-header
verification as a pure perception component: a target must have sufficient configured HP-colour
pixels and match a configured name template before it is reported as valid.

US-007 connects the capture and vision components at the application boundary. Its
`PerceptionPipeline` produces a timestamped snapshot on every successful capture, preserving the
non-perception state carried from the previous snapshot. Individual detection, target-verification,
and loot-reading failures are non-fatal and are exposed alongside the resulting state.

US-008 implements the reactive combat boundary. `CombatController` deterministically filters
whitelisted visible mobs and chooses the closest to the captured client viewport centre, then
emits client-relative clicks and configured `1`-`9`, `C`, or Space rotations with per-binding
cooldowns. It requires a valid target-header observation before attacking, detects HP-pixel
decreases as progress, and reaches `TARGET_DEAD` when the target clears or has zero HP. Its
`CombatInputDispatcher` is the only platform dispatch boundary: it sends no input unless the game
window remains foregrounded and the END emergency stop is clear.

US-009 implements the reactive loot boundary. `LootController` begins one configured pickup-key
attempt from explicit combat-death evidence, waits for newly emitted OCR loot confirmation, and
requests patrol movement once when that confirmation window expires. `PerceptionPipeline`
de-duplicates still-visible OCR notifications before updating immutable inventory counts and the
recipe-progress marker, then emits loot-collected perception events. `LootInputDispatcher` sends
the pickup key only while the game window is foregrounded and the END emergency stop is clear.

US-011 adds the offline operational path for custom mob models. The repository supplies the empty
multi-class YOLO layout at `data/datasets/mobs/` and its `data.yaml` class registry. The CLI can
validate it without a game window, or—with the optional `training` dependency—train `yolo11n.pt`
by default and export `models/mob_detector.onnx` plus its matching `models/labels.txt`.

US-012 hardens target verification against visually similar sky and cloud colours in real Flyff
screenshots. A configured header-anchor template must match before the dedicated HP-bar region is
measured; a missing anchor is `NO_TARGET`, while an anchored header with an unrecognized whitelist
name is `WRONG_TARGET`. Real cropped fixtures cover empty, whitelisted `Flame`, and non-whitelisted
target cases.

US-013 adds `FarmingOrchestrator`, a cooperative, sequential session loop over the perception
pipeline, combat and loot controllers, and supervisor. Its typed lifecycle moves from searching
through target selection, combat, loot, and reconciliation; a configurable retry delays a new
search when no mob is visible. It exposes foreground- and END-guarded dispatch through the existing
combat and loot dispatchers, pauses on lost focus, latches an emergency stop, and completes an
optional inventory goal. The `--farm`/`--auto` CLI path configures model, target, rotation, loot,
search, and goal inputs. An optional `DashboardFeed` publishes immutable `DashboardUpdate` values,
and the Qt signal adapter connects dashboard start, pause, and emergency-stop intents to a session.

US-014 makes the combat attack key configurable at the desktop boundary. The dashboard captures a
single supported physical key, displays `F3` by default, and passes its virtual-key code into a
paused `FarmingOrchestrator` before a session starts. Combat bindings and the existing CLI rotation
key parser support `A`–`Z`, `0`–`9`, Space, and `F1`–`F12`; dispatch, defeat monitoring, loot OCR,
and foreground/END safeguards remain on their existing paths.

US-015 adds staged, non-blocking no-mob recovery to `FarmingOrchestrator`. After a configurable
idle timeout, `SearchController` dispatches camera-rotation arrow-key pulses (default `Right Arrow`),
followed by pitch tilt pulses (US-018) and bounded `W`/`A`/`D` roaming pulses, continuously cycling back
to sweeping rotation without executing uncalibrated minimap clicks. (US-027 proposed calibrating those
clicks and was rejected in favour of the US-019 spawn heatmap and patrol circuits, which already reach spawns
outside the viewport without a second guarded click path aimed at the HUD; obsolete US-015 minimap leftovers
were removed). Every search tick first evaluates the newest perception snapshot:
a visible eligible mob resets search and immediately returns to targeting. `SearchInputDispatcher` checks
foreground focus and END before every search action, while the Windows guarded key hold releases on either condition;
dashboard search statuses and CLI timing options are localized in English and German.

US-018 enhances staged search with multi-axis camera scanning and visual settle pauses.
`SearchController` extends `SearchMode` with `SearchMode.TILT`, dispatching vertical pitch pulses
(`VK_UP` or `VK_DOWN`) after horizontal rotation pulses (`VK_RIGHT` or `VK_LEFT`). Configurable
pacing (`rotation_step_duration_seconds`, `tilt_step_duration_seconds`, and
`rotation_settle_pause_seconds`) introduces observation pauses between key actions to ensure the
perception pipeline processes unblurred frames and prevents spinning past spawns on slopes or
elevations. Pitch adjustments are decoupled from horizontal heading, keeping `MovementTracker`
dead-reckoning and `SpatialMap` coordinates accurate while broadening elevation FoV. Any newly visible
mob instantly aborts search and transitions to targeting; arrow keys remain strictly guarded by
foreground focus and the END emergency stop.

US-019 adds `flyff_bot.features.navigation`, the internal spatial memory that sits behind staged
search. `MovementTracker` dead-reckons a session-relative position and compass heading from the
movement and camera keys that were actually dispatched, so no game memory or client modification is
involved. `SpatialMap` folds those estimates into a grid: every tick records a cell visit and links
consecutive cells into a traversal graph, mob sightings accumulate an exponentially decaying spawn
weight, and stalls raise a bounded multiplicative cost on both the stalled cell and the edge that
reached it, so a penalized area stays reachable instead of being hard-blocked. `StallDetector`
supplies that stall evidence by comparing consecutive captured frames while forward movement was
commanded, and its verdict also sets `WorldState.is_stuck`. BUG-009 later replaced that
sample-counting comparison with an elapsed-time accumulator measured outside the centred player
region.

`RoutePlanner` runs Dijkstra over the recorded edges and scores candidate goals by decayed spawn
density per unit of travel cost, chaining the densest reachable clusters into a patrol circuit that
returns to its start. US-037 made the patrol leash an enforced planning bound rather than a
drawing: `LeashBound` is the circle around the session anchor — which is the origin of the
relative frame, so no separate anchor is configured — and the planner refuses to expand into or
target any cell whose centre lies outside it. `RoutePlanner.return_route` covers the case of a
character that starts outside the bound, searching without the constraint and stopping at the first
cell inside it, because walking back in is only possible through the cells it actually stands
among. `PathingController.leash_radius_pixels` is the single value the inspector draws and the
planner enforces, so the two cannot drift apart, and changing it applies at the next replan without
restarting the session. `PathingController` owns the loop: it observes each snapshot, steers toward
the next waypoint with camera-rotation and forward pulses, retreats to the last verified stall-free
waypoint after a stall, and replans a bypass that avoids the blocked cell. `FarmingOrchestrator`
consults it before the staged search stages and falls back to `SearchController` whenever the map
is still too sparse to plan. `PathingInputDispatcher` re-checks foreground focus and END before
every pathing key. Learned maps are persisted as versioned JSON (`--navigation-map`, default
`data/navigation/spatial_map.json`) and restored on the next session; the whole subsystem is
internal and renders nothing in the game client.

US-020 adds `PathInspectorWidget` to the desktop dashboard boundary (`flyff_bot.ui.path_inspector`).
Operators can toggle a 2D top-down canvas showing the character's live dead-reckoned position and
compass facing, origin axes, leash boundary circle, color-shaded spawn heatmap cells, recorded
traversal graph edges (with stall risk highlights), safe waypoint fallback anchors, and active
patrol route polylines. `FarmingOrchestrator` delivers an immutable `NavigationSnapshot` on every
published tick via `DashboardUpdate` without blocking worker threads. Localized labels in German and
English explain all map elements and legend badges.

US-021 adds named navigation map profile slots, persistence management, and session reset safeguards
to the desktop dashboard. Operators can save, load, and switch discrete map profiles from
`data/navigation/*.json` via a profile management bar, avoiding cross-camp topological contamination.
The profile selector scans for valid `.json` maps and displays cell count summaries, while custom
profile name inputs sanitize invalid Windows filename characters. Profile modifications are strictly
gated to paused or stopped farming states (`FarmingMode.PAUSED` / `FarmingMode.EMERGENCY_STOPPED`).
A modal reset safeguard confirms map clearing before purging in-memory spatial cells, edge graphs,
and spawn weights, resetting the dead-reckoning tracker back to $(0.0, 0.0, 0.0^\circ)$. Continuous
sessions auto-persist the active profile every 30 seconds of farming, on pause/emergency stop
transitions, and upon window close (`MainWindow.closeEvent`), with complete German and English
localization for all dialogs and notices.

US-017 adds `flyff_bot.features.vision.vitals` and `flyff_bot.features.automation.vitals_controller`,
providing pure pixel-color perception of player vital gauges (HP, MP, FP) from the top-left HUD orb
and reactive threshold-triggered consumable dispatching. `PlayerVitalsReader` extracts the top-left HUD
region from captured frames and column-scans calibrated horizontal gauge bars (HP in Red, MP in Blue,
FP in Green), measuring the furthest filled column to compute accurate fill percentages (0.0% to 100.0%)
even when overlaid with black or white digit text. The measured values populate `PlayerVitals` on `WorldState`.
`VitalsTriggerController` evaluates configurable per-vital threshold rules (`hp_percentage <= threshold`),
enforcing debounce cooldowns (default 800ms) and prioritizing low-HP emergency recovery over combat rotations.
`VitalsInputDispatcher` executes consumable hotkeys while strictly enforcing foreground window focus and END
emergency stop. The PySide6 dashboard exposes live vitals readouts, overlay annotations, and a configurable
vitals trigger panel with automatic disk persistence to `data/vitals_config.json` and synchronized German/English
translations.

US-023 hardens `CombatController` engagement reliability and adds ground-truth kill verification. A
configurable target-acquisition grace period (default 0.8s) keeps the state machine in `TARGETING` while
waiting for the target header to register instead of resetting to `IDLE` and re-clicking the same world
coordinate, which is what previously risked accidental double-click character walking. `_reset()` now also
clears the attack cooldown timer, so a fresh engagement started while a prior binding's cooldown is still
counting down still fires its hotkey on the very next tick rather than silently skipping it. `MonsterStatsReader`
(`flyff_bot.features.vision.monster_stats`) OCR-extracts the HUD `Monster Kills: <int>` counter from a
resolution-scaled ROI and feeds it into `WorldState.monster_kill_count` through `PerceptionPipeline`.
`CombatController` treats a clean `+1` increment of that counter as authoritative kill confirmation independent
of HP tracking; requiring an exact `+1` (rather than any increase) rejects the large jump produced when OCR
first succeeds mid-engagement and reports the session's running total instead of a genuine one-kill delta. Kill
confirmation remains an `OR` with the existing HP-based path: target HP reaching zero or the target bar
disappearing only counts as a kill after measurable HP decrease was observed during the fight, otherwise it is
`TARGET_LOST` and the orchestrator returns to searching rather than handing off to `LootController`. The debug
overlay renders a resolution-scaled calibration guide box so operators can align the in-game monster-stats HUD
window with the ROI `MonsterStatsReader` reads. Both the target-acquisition grace period and the kill-count
verification toggle are dashboard-configurable and apply live via `FarmingOrchestrator.configure_combat_grace`
and `configure_kill_verification`, which update the running `CombatController`'s configuration without resetting
its in-progress engagement state.

US-024 exposes `TargetVerifier`'s internal decision evidence for live debugging instead of only the collapsed
`VALID_TARGET`/`WRONG_TARGET`/`NO_TARGET` outcome. `TargetVerificationMetrics`
(`flyff_bot.features.vision.models`) is a new value object carrying each criterion's raw score, configured
threshold, and pass/fail outcome (header anchor, HP-bar minimum pixel count, name-template match), populated by
`TargetVerifier.verify()` on every branch of its short-circuit evaluation, including the `NO_TARGET` and
HP-failure paths that previously discarded this evidence. Name-template matching now scores every configured
template and reports the highest-scoring one (`_best_name_match`) rather than the first template past
threshold in dict-iteration order, matching the debug panel's "best name match" requirement without changing
which status a target resolves to. `TargetVerificationResult` and `SelectedTarget` both carry `hp_percentage`
and `metrics` alongside their existing fields; `PerceptionPipeline._selected_target()` forwards them unchanged
into `WorldState.selected_target`. Because `TM_CCOEFF_NORMED` scores jitter by fractions of a percent between
otherwise-identical ticks, `SelectedTarget.metrics` is declared `compare=False` so this continuous noise cannot
trigger a spurious `PerceptionEventKind.TARGET_CHANGED` event; only `state`, `name`, `hp_pixel_count`, and
`hp_percentage` remain part of that equality check. The dashboard exposes this data as a new "Target Debug"
toggle and `MainWindow` panel (mirroring the existing vitals/combat panel pattern) with five read-only rows:
anchor score/threshold, HP pixel count/percentage, best name-match candidate/score, overall target state, and
a failure-reason row derived purely from the forwarded pass/fail booleans (never re-deriving verifier
thresholds), always kept up to date in `_render_update` independent of the panel's own visibility toggle.

US-025 decouples farming from key-press pickup and loot-log OCR, assuming an active in-game loot pet instead.
`FarmingOrchestrator._advance()` now transitions a confirmed `CombatMode.TARGET_DEAD` directly into
`FarmingMode.RECONCILING` (bumping `WorldState.progress_marker` by one for that kill) rather than into the
removed `FarmingMode.LOOTING`, so a session moves from kill to search/re-targeting within one to two ticks
with no blocking wait and no `F`-key pickup dispatch; `LootController`, `LootConfig`, `LootMode`, and
`LootInputDispatcher` remain as standalone, independently tested components but are no longer wired into the
orchestrator. Driving `progress_marker` from confirmed kills instead of summed loot-event counts keeps
`Supervisor`'s `NO_PROGRESS` reconciliation check accurate without any OCR feed attached — previously it would
have stalled after `no_progress_timeout_seconds` once loot OCR stopped running. `PerceptionPipeline`'s
`loot_log_reader` constructor parameter is now optional and defaults to an internal no-op feed that returns no
events and touches no subprocess or disk I/O; `WorldState.inventory` and `.recent_loot` stay typed and default
to empty when no real `LootFeed` is attached, but the pipeline still updates them normally when one is. The CLI
and desktop app no longer construct a `LootLogReader`/`TesseractTextRecognizer` pair for farming sessions by
default; `--read-loot` remains an explicit opt-in diagnostic path unaffected by this change. Item-quantity
`FarmingGoal` completion is unchanged and still requires an explicitly attached loot feed to observe inventory.

US-026 hardens player vitals extraction and monster stats window detection against arbitrary client resolutions and screen layouts, fixing BUG-006. `PlayerVitalsReader` switches from normalized relative window fractions to fixed-pixel top-left anchoring (`0..260` width, `0..113` height), ensuring gauge bar column-sampling (HP in Red, MP in Blue, FP in Green) operates strictly on the 2D HUD orb across any resolution (720p, 1080p, 1440p, 4K) without sampling dynamic 3D world scenery or causing false 0% consumable spam. `MonsterStatsReader` is hardened with template-matched anchoring (`cv2.matchTemplate`), dynamically searching the frame for the session stats window header and extracting the relative `Monster Kills:` text ROI regardless of where the operator positions the window on screen, gracefully returning `None` if the window is closed. At the presentation boundary, the desktop UI adds a "Placements" ("Platzierungshilfen") visual guide toggle that renders color-coded, labeled ROI overlay boxes (Player Vitals orb, Target Header bar, and Monster Stats OCR crop) proportionally scaled over the live viewport preview, allowing operators to visually calibrate and align in-game HUD elements with complete precision.

BUG-008 moves the placement guides out of the dashboard thumbnail and onto the desktop.
`PlacementOverlayWindow` (`flyff_bot.ui.placement_overlay`) is a frameless, translucent,
always-on-top `Qt.Tool` window drawn directly over the game client area. It is click-through and
never activates (`Qt.WindowType.WindowTransparentForInput`, `WA_ShowWithoutActivating`, and no
`raise_()`/`activateWindow()` call), because an overlay that took foreground would pause the guarded
session and make the client register as occluded for frame capture. `WindowsInputController` gains
`client_screen_bounds()`, which returns the client area in desktop pixels (`GetClientRect` plus
`ClientToScreen`) or `None` when the window is invalid, hidden, or minimized; the overlay polls it
on a Qt timer while enabled and hides itself whenever the bounds are unavailable. Physical pixels
are converted into Qt logical units once, in the pure `logical_geometry()` helper, so scaled
displays stay aligned. The guides themselves are pure client-space `PlacementGuide` values produced
by `compute_placement_guides()` and drawn by `draw_placement_guides()`, shared by the desktop
overlay and the dashboard preview so both surfaces cannot drift apart; the overlay scales them by
its own width relative to the tracked client width. `MainWindow.attach_placement_target()` binds the
overlay to the discovered window handle, and `run_desktop` calls it before the model-file guard, so
placement calibration works even with no detection model installed and no preview frame. Because
`WindowsFrameSource` blits with `CAPTUREBLT`, an overlay drawn over the HUD can appear in captured
frames; the overlay is operator-toggled and intended for calibration rather than continuous farming.

US-028 makes read-only perception a continuous standby service and separates bot status from
telemetry at the dashboard, fixing BUG-007. `FarmingOrchestrator.tick()` no longer returns before
perception while paused, completed, or emergency-stopped: those `STANDBY_MODES` now run
`_observe()`, the single read-only step that captures one frame, refreshes `WorldState` (vitals,
visible mobs, target verification metrics, monster kill count) and the debug-overlay frame, and
dispatches nothing. The active path uses the same helper, so a `FrameCaptureError` raised mid-session
— the game client being closed or minimized — pauses the session instead of raising out of the Qt
timer slot every tick. Navigation observation stays on the active path only, keeping standby out of
the spawn heatmap and dead-reckoning state. `WindowsFrameSource` gains `require_foreground`, and the
desktop app constructs it with `require_foreground=False`: a background but visible client is still
captured through its own device context for the standby preview, which is safe because it sends no
input and because every dispatcher independently re-checks foreground focus and the END emergency
stop before any key or click. The tradeoff is that occluding windows are copied with the frame, so
`DashboardUpdate` carries a typed `WindowStatus` (`OK`, `NOT_FOREGROUND`, `MINIMIZED`, `NOT_FOUND`,
`CAPTURE_FAILED`) mapped from the capture error code or the foreground check, which the dashboard
renders as its own chip with one complete localized sentence per state. `BotStatus` adds `STANDBY`
(paused with a live preview) and `COMBAT` (targeting or fighting); `MainWindow` stops writing the
visible-mob count into the status badge and instead renders dedicated mob-count, target-state,
vitals, and goal chips beside a badge that only ever shows bot status. Start remains the existing
focus-then-start handoff with no artificial countdown: when foreground focus cannot be acquired the
session stays paused and the next standby publish states the focus condition on the window chip.

US-029 makes target verification anchor-relative, tunable, and fully instrumented. `TargetVerifier`
no longer crops the HP bar and mob name from fixed normalized fractions of the broad top-centre
header region: `TargetVerificationConfig` replaces `hp_region`/`name_region` with `hp_offset` and
`name_offset`, typed `AnchorOffsetRegion` pixel rectangles measured from the top-left corner of the
matched header anchor (`extract_anchor_relative_region`, clipped to the region bounds). The shipped
defaults — HP `(dx=5, dy=27, 150x12)` and name `(dx=40, dy=-4, 125x35)` relative to the 30x26
`data/assets/mobs/target_anchor.png` — track the header wherever it is drawn inside the searched region, which
is what previously made the HP crop miss the gauge entirely and report `0 px (0.0%)`. Like US-026's
fixed-pixel vitals anchoring, this assumes the Flyff HUD is drawn at a fixed pixel size on every
client resolution; `cv2.matchTemplate` is not scale invariant, so the mechanism buys translation
invariance rather than accuracy under arbitrary scaling. `verify()` drops its short-circuit
returns and measures every criterion on every tick, so the debug panel keeps showing HP pixels and
the best name candidate even when the anchor score falls just below its threshold. The raw
measurements live in `TargetVerificationMetrics.hp_pixel_count`/`.hp_percentage`, which the panel
renders; the identically named fields on `TargetVerificationResult` and `SelectedTarget` stay zero
unless the anchor passed, because `CombatController` reads them as kill evidence and they take part
in the `SelectedTarget` equality that raises `PerceptionEventKind.TARGET_CHANGED`. The HP percentage
divides by the configured gauge width rather than the cropped width, so a header clipped by the
region edge cannot report a falsely full bar. Default anchor and name thresholds drop from `0.90` to
`0.75`, and the dashboard combat panel adds two `0.30`-`1.00` spin boxes whose
`target_thresholds_changed` signal is connected in `run_desktop` straight to
`TargetVerifier.update_thresholds`, applying live without touching controller state; labels and
tooltips are localized in German and English.

US-030 instruments the monster-kills HUD OCR the way US-024 instrumented target verification.
`MonsterStatsFeed.read()` returns `MonsterStatsMetrics` (`flyff_bot.features.vision.models`) rather
than a bare `int | None`: the kill count is `parsed_count`, and `anchor_configured`, `anchor_score`,
`anchor_threshold`, `anchor_passed`, `roi_width`, `roi_height`, `raw_text`, and a typed
`MonsterStatsStatus` (`IDLE`, `OK`, `ROI_UNAVAILABLE`, `ENGINE_UNAVAILABLE`, `OCR_FAILED`,
`NO_MATCH`) are measured on the same tick whether or not the reading succeeded. `_extract_anchored_roi` now
returns the best `cv2.matchTemplate` score alongside its crop instead of discarding it on the
below-threshold path, so the panel shows how close a missed match came — the same lesson US-029
applied to `TargetVerifier`. `PerceptionPipeline` carries the value object on
`WorldState.monster_stats` and still leaves `monster_kill_count` untouched when `parsed_count` is
`None`, because a zero written on a failed read would look like the counter had been reset. The
dashboard adds a "Monster Stats Debug" toggle and panel with read-only rows (anchor score/threshold with the shared PASS/FAIL badge, cropped ROI dimensions,
parsed kill count, raw OCR text rendered as `Qt.TextFormat.PlainText` because OCR output is
untrusted markup, and the feed status sentence), rendered from `_render_update` independent of the
toggle. The fixed client-pixel ROI stays docked directly to the right edge of the Player Vitals HUD
(`x=260..410`, `y=0..120` px), and the placement guide overlay renders it as a red guide box
(`QColor(255, 70, 70)`). US-034 supersedes this section's anchor handling; see below.

BUG-012 (monster stats) separates a missing OCR install from a failed recognition and stops the
shipped anchor row from reading as a missing configuration. `TesseractTextRecognizer` no longer
takes the bare command name as its default: `resolve_tesseract_executable()` prefers
`shutil.which()` and then probes `TESSERACT_INSTALL_CANDIDATES`, the two documented Windows install
directories, because the official installer does not extend the system `PATH` — which is what made
every OCR consumer fail on an otherwise complete install. An explicitly passed executable is still
honoured verbatim so injected test paths keep working, and the resolver falls back to the bare
command so a genuinely absent engine still surfaces as `ENGINE_UNAVAILABLE` rather than raising out
of the lookup. That mapping now also covers an executable that exists but cannot be started
(`OSError` rather than `FileNotFoundError`), evaluated after the `SubprocessError` branch so a
non-zero exit or timeout stays `RECOGNITION_FAILED`. `MonsterStatsReader.read()` catches
`LootOcrError` ahead of its residual broad handler and maps `ENGINE_UNAVAILABLE` to the new
`MonsterStatsStatus.ENGINE_UNAVAILABLE`, following US-032's `TargetNameStatus` precedent: an
operator can install Tesseract, but cannot act on "OCR failed". The broad handler is kept because
`TextRecognizer` is a Protocol whose implementations may raise anything, and narrowing it entirely
would let an injected engine's exception escape into the Qt timer tick; `PerceptionPipeline` records
the failure and retains the previous count either way, so `parsed_count` stays `None` and
`CombatController`'s exact-`+1` kill verification is untouched.

BUG-009 corrects the dead-reckoning movement model and rebuilds stall detection around elapsed
time and peripheral scenery. `MovementTracker.apply` now treats `A` and `D` as character turns
exactly like the Left and Right arrow keys (`ROTATION_VIRTUAL_KEYS`), because Flyff's default
controls rotate rather than strafe; the previous strafe translation drifted the estimate sideways
on every turn the US-018 roam sequence dispatched. `VIRTUAL_KEY_S` translates backwards along the
negated forward vector at `MovementModel.backward_speed_units_per_second`, which replaces the now
unused `strafe_speed_units_per_second`. `StallDetector` replaces its consecutive-sample counter
with `StallConfig.stall_timeout_seconds` (default `5.0`): each observation carries `at_seconds`
and adds the elapsed interval — clamped to `MAXIMUM_STALL_SAMPLE_SECONDS` so one delayed capture
cannot fake a stall on its own — whenever the measured motion stays below `motion_threshold`.
Motion is measured only outside a centred rectangle sized by `center_mask_width_fraction` and
`center_mask_height_fraction`, because the player model's running animation keeps producing pixel
differences while the character is pinned against an obstacle; those two fractions are estimates
rather than values calibrated against measured client frames, and the unchanged
`DEFAULT_MOTION_THRESHOLD` shares that status because it was chosen against a full-frame mean and
now scores the peripheral samples only. The known limitation is that
masking the centre still leaves the HUD bands sampled, so animated HUD elements can mask a genuine
stall. A tick that commands no forward movement no longer clears the accumulated stall time while
it falls inside `movement_grace_seconds` of the last commanded `W`; the accumulator is held rather
than extended, so the turn ticks between forward steps neither reset nor fabricate a stall, and
the detector stays free of controller state. `PathingController._register_stall` consumes the
evidence by resetting the detector, and `is_stalled` reports the verdict of the most recent
observation, so `WorldState.is_stuck` marks the registration tick instead of latching `Supervisor`
into `STUCK` for the whole retreat. `_remember_safe_waypoint` refuses to promote a cell that has
recorded stalls into `_safe_waypoint`, which previously let a retreat target the obstacle cell it
had just fled.

BUG-010 stops combat targeting from thrashing and bounds a stuck engagement, delivering US-031 in
the same change. `CombatController` keeps a list of `TargetLockout` values — a client-space
`Position` and an expiry — registered on every terminal exit that is not an in-progress fight:
acquisition-grace expiry, mid-fight loss of the target header, the new engagement timeout, an
undamaged `TARGET_LOST`, and a confirmed `TARGET_DEAD`. `_best_candidate()` purges expired entries
against `observed_at_seconds` and rejects any mob whose center lies within
`CombatConfig.target_lockout_radius_pixels` (default 50 px) of an active lockout, so the 0.8 s
acquisition grace can no longer expire straight back into a re-click of the same corpse or
unverifiable mob. The lockouts deliberately survive `_reset()`, which is exactly what runs on those
failure paths; nothing clears them early, because `emergency_stop()` latches a session permanently
and a new session builds a new controller. `CombatConfig.engagement_timeout_seconds` (default
10.0 s) measures elapsed time since the last observed HP decrease, seeded at the tick the target
header was first confirmed, and breaks the engagement when it expires. Kill-count and HP-zero
confirmation are evaluated before the timeout so a genuine kill on the timeout tick still counts.
`FarmingOrchestrator` now resets the staged-search idle timeout only for a verified engagement
(`ENGAGING`/`FIGHTING`), not for every dispatched click: the 4.0 s lockout retry cycle otherwise sat
just under the 5.0 s `SearchConfig.idle_timeout_seconds` and camera recovery never ran at all.
A typed `EngagementBreakReason` (`ACQUISITION_TIMEOUT`, `TARGET_UNVERIFIED`, `ENGAGEMENT_TIMEOUT`)
travels on `CombatDecision.break_reason`, is latched by the orchestrator, and is published on
`DashboardUpdate.engagement_break` for one localized sentence in the target debug panel, cleared
when the next engagement begins. It is kept off `WorldState`/`SelectedTarget` so it cannot
re-create the US-024 spurious `TARGET_CHANGED` problem. Two limitations are inherent to anchoring a
lockout in screen space rather than to a world object: `_track_engaged_position()` follows the
nearest allowed detection inside the radius during the fight so the lockout lands on the corpse
instead of the original click point, but it is a proximity heuristic with no detection identity;
and a camera rotation remaps the screen, so an active lockout can briefly shadow a different live
mob that moves into that position until the 4.0 s expiry.

US-016 adds `flyff_bot.features.automation.powerup_controller`, the interval-driven refresh of timed
consumables and self-buffs. `PowerUpScheduler` holds one elapsed-time accumulator per configured
`PowerUpEntry` (virtual key, integer interval, optional label, enabled flag) and advances them only
by the span between the ticks it is actually stepped. That is what makes pause, lost focus, a
completed goal, and an emergency stop freeze every countdown: `FarmingOrchestrator.tick()` calls
`halt()` on the single standby branch, which drops the last-step timestamp so the halted span is
never added, and every route into `STANDBY_MODES` therefore freezes uniformly rather than relying on
each transition to remember. `step()` reports the first due entry without consuming it and
`confirm()` restarts that entry's countdown, mirroring the `PathingController.step`/`confirm`
split — a keystroke the guards refuse stays due instead of being silently spent, which is how a
trigger during lost focus is held rather than skipped. `PowerUpInputDispatcher` re-checks foreground
focus and the END emergency stop before every key, like the combat, search, pathing, and vitals
dispatchers. The orchestrator evaluates power-ups after `VitalsTriggerController` so an emergency
heal always outranks a buff refresh, and dispatches at most one per tick; because the tick interval
is 100 ms, `PowerUpConfig.stagger_seconds` (default 30 ms) is a floor on the gap between two
concurrently due buffs rather than the observed spacing, and blocking inside `tick()` to hit a true
30 ms gap was rejected because the Qt timer drives it on the GUI thread. `update_config()` carries
elapsed time over for every position whose key and interval are unchanged, so editing one row cannot
restart a 3600 s timer while the operator is still typing. At the presentation boundary
`PowerUpPanel` (`flyff_bot.ui.powerup_panel`) is a standalone widget owning an arbitrary number of
rows — each a `QWidget` in a `QVBoxLayout`, so removal is `removeWidget` plus `deleteLater()` rather
than `QGridLayout` row surgery — with a name field, a combo box covering `F1`–`F12`, `0`–`9`,
`A`–`Z`, and `Space`, an interval spin box, an enabled check box, and a delete button. Its
`config_changed` signal drives JSON persistence to `data/powerups_config.json` and
`MainWindow.powerup_config_changed`, wired straight to `FarmingOrchestrator.configure_powerups`; the
name field publishes on `editingFinished` rather than per keystroke to avoid a disk write per typed
character. In the current tabbed dashboard, added rows extend the Vitals & Buffs page inside its
scroll area without resizing the top-level window. Unlike `vitals_config_from_dict`, a parsed-empty
entry list is preserved instead of
being replaced by defaults, because deleting every row is a legitimate configuration; only an absent
or corrupt file falls back. Labels and tooltips are localized in German and English.

US-022 introduced the desktop dashboard's cohesive Dark Slate Qt Style Sheet (QSS), streamlined
visual hierarchy, standalone pop-out navigation map window (`NavigationMapWindow`), and `Escape`
emergency-stop shortcut. US-050 retains and expands that theme while replacing the earlier card and
telemetry-toolbar composition with the tabbed layout documented below. Operators can still pop out
`PathInspectorWidget` into the secondary navigation window. Pressing `Escape`
(`Qt.Key.Key_Escape`) while either UI window has focus emits `emergency_stop_requested`, alongside
the global Win32 `END` safeguard; US-050 removes the former physical emergency-stop button without
removing either shortcut or the signal path. All user-visible strings, badge labels, and tooltips
remain localized across German and English.


US-032 replaces target name verification's RGB template matching with colour-masked OCR, fixing
BUG-011. `cv2.matchTemplate` scored a genuine `Flame` nameplate at ~0.25 on a 2559x1439 capture
against the same shipped `models/target_flame.png` that scored 1.00 on the 1276x747 capture it was
cropped from: the HUD is drawn at a fixed pixel size, so the crop geometry was never the problem —
the 125x35 name rectangle is mostly *background*, and the grass, sky, and dirt behind the glyphs
move while the glyphs do not, which is what the correlation actually measured. No threshold can
separate those two cases, so the shipped template was deleted rather than retuned.
`preprocess_target_name_region()` instead thresholds the one fixed pale-yellow fill colour Flyff
renders the nameplate in (BGR ~160/255/255, identical on both captures) with `cv2.inRange`, inverts
it to dark glyphs on white, and upscales by `name_ocr_upscale` (default 2x) for OCR; the resulting
mask is byte-identical across separate captures of the same target regardless of scenery.
`TargetVerifier` now takes `allowed_names` plus the shared `TextRecognizer` in place of a name
template per mob, and `match_whitelisted_name()` resolves the reading — Flyff appends a level suffix
such as `Flame <Lvl 175>` — by normalized case-insensitive containment. Only the canonical whitelist
entry reaches `TargetVerificationResult.target_name`; the raw OCR string stays on
`TargetVerificationMetrics.name_text`, which is `compare=False` on `SelectedTarget`, so a flickering
reading cannot raise the spurious `PerceptionEventKind.TARGET_CHANGED` events US-024 removed.
`TargetVerificationMetrics` swaps `name_score`/`name_threshold` for `name_text` and a typed
`TargetNameStatus` (`NOT_EVALUATED`, `MATCHED`, `NO_MATCH`, `UNREADABLE`, `OCR_FAILED`,
`ENGINE_UNAVAILABLE`), each with its own localized sentence in the target debug panel's reason row —
a missing Tesseract install produces exactly BUG-011's symptom of never attacking, so it is named
rather than folded into a generic OCR failure. Two deliberate departures from US-029's
"measure every criterion on every tick": name recognition runs only once the anchor is accepted and
otherwise reports `NOT_EVALUATED`, and the reading is cached against the previous tick's mask,
because the mask is stable while a target stays selected and the OCR subprocess costs ~75 ms against
a 100 ms Qt timer that already runs `MonsterStatsReader`. A failed recognition is never cached, so a
recoverable engine problem is retried. The operator-facing name-match threshold spin box is gone with
the mechanism it tuned; `MainWindow.anchor_threshold_changed` now carries one float into
`TargetVerifier.update_anchor_threshold`. The desktop app sources the whitelist from
`models/labels.txt` and the CLI from `--target-name`, `--class-name`, or that same labels file in
that order, so the names combat is allowed to engage and the names the header will accept cannot
drift apart.

US-034 makes the monster-stats reading independent of the game world drawn behind it and turns the
kill counter into dependable combat evidence. The stats window has no opaque backing, so contrast
thresholding (CLAHE + `adaptiveThreshold`) kept whatever scenery happened to be behind the panel and
merged it with the glyphs; verified against
`data/assets/fixtures/full_screen_view_with_monster_stats_1600_900_Res.png`, that produced no readable text at all.
The client renders every stats glyph in one constant colour instead — BGR `(255, 209, 249)` = HSV
`(146, 46, 255)`, with a pure black outline — so `extract_hud_text_mask()`
(`flyff_bot.features.vision.monster_stats`) keys that colour with `cv2.inRange` and yields glyphs
alone on both shipped screenshots, whose backgrounds are unrelated. The same mask drives anchor
matching: `data/assets/stats/monster_stats.png` ships as the reference stats window,
`load_header_anchor_template()` crops its "Time:" header line, and `run_desktop` passes it to
`MonsterStatsReader`, reversing BUG-012's "the fixed region is the intended mode" note. Matching
masks rather than raw pixels is what makes the shipped template usable — measured against the
reference screenshot it scores `1.00`, where raw-colour matching scores `0.67` and would never clear
the `0.85` threshold. From a match, the panel origin is recovered by subtracting the template's
inset (`anchor_inset_x`/`anchor_inset_y`) and the full panel extent is cropped, because the narrow
single-line crop US-026 used produced OCR garbage. A missed anchor falls back to the fixed region
rather than reporting nothing, and `MonsterStatsMetrics.source` (`MonsterStatsSource.ANCHORED` /
`FIXED_REGION`) names which crop produced the number, so the fallback cannot silently masquerade as
an anchored reading — `MonsterStatsStatus.ANCHOR_NOT_FOUND` is gone with the failure it described.
The reader asks Tesseract for `eng` alone (`TESSERACT_LANGUAGE_ENGLISH`), since the stats HUD is
English in every client locale and a missing German pack would otherwise fail it.

Three changes make the counter trustworthy for `CombatController`. `PerceptionPipeline` samples the
reader on its own `DEFAULT_MONSTER_STATS_INTERVAL_SECONDS` (0.5 s) interval instead of on every
tick, because each reading spawns an OCR subprocess. `_kill_count_incremented` no longer demands an
exact `+1`: it takes a baseline only from a reading whose status is `OK`, and then accepts any
increase. The old rule rejected the session-total jump that appears when OCR first succeeds
mid-engagement, but it also discarded a genuine two-kill delta — gating the baseline on a successful
reading rejects the former without the latter. `CombatConfig.kill_verification_enabled` now defaults
to `True`, and the dashboard checkbox is initialized from that default. Finally, `run_desktop` no
longer drives ticks from a `QTimer` on the Qt event loop, which ran frame capture and OCR on the GUI
thread against the project's own PySide6 rule. `SessionWorker` (`flyff_bot.ui.session_worker`) runs
the loop on a `threading.Thread`, waiting on a stop `Event` rather than sleeping so teardown is
immediate; `MainWindow.register_teardown()` stops it from `closeEvent` before the widgets go away,
and results still reach the UI only through `DashboardFeed`'s signal.

US-038 makes the monster the operator is hunting a single dashboard choice that every stage of the
pipeline follows. Its single-select dropdown was replaced by the multi-select panel described under
[multi-target kill quotas](#multi-target-monster-selection-and-per-mob-kill-quotas-us-035-quotas);
what survives unchanged is where the selection is applied and why. The three surfaces that must agree
are `OpenCVDnnYoloDetector.update_allowed_class_names()`, `TargetVerifier.update_allowed_names()`,
and `FarmingOrchestrator.configure_target_classes()`. All three replace their frozen configuration in
place, so switching monsters applies on the next tick of the running session — no restart, and no
reset of an engagement already in progress. `MainWindow.set_target_mob_options()` still fills the
choices from the same `models/labels.txt` the whitelist comes from, so the dashboard cannot offer a
class the model cannot detect.

The filter is applied at the earliest point it can be. `_decode()` already dropped candidates outside
`DetectionConfig.allowed_class_names` before non-maximum suppression; pushing the operator's choice
into that set means a non-target monster never reaches `WorldState.visible_mobs`, so no candidate
scoring, no click, and no anchor template match is ever spent on it — which is also why the dashboard
mob counter and the debug overlay show only the selected class. `TargetVerifier` follows with the
matching whitelist and, through `load_mob_anchor_templates()`, only that mob's anchor image, so
`_match_anchor()` correlates one template per frame instead of one per known monster. A selection
whose mob ships no anchor of its own keeps the templates already loaded rather than leaving the
verifier with nothing to match, and the cached nameplate reading is dropped on every change because
it was resolved against the previous whitelist. `CombatController` receives the same set so
`_allowed_mobs()` cannot prioritize a monster perception has been told to ignore; an empty set
everywhere is the unconstrained "every monster" case.


## Measured minimap odometry and tracking quality (US-035)

US-035 replaces the open-loop position estimate with a measurement. `MovementTracker` no longer
integrates dispatched key presses into the position it reports: it anchors on the last confident
minimap measurement and keeps the command model only as a short-term predictor for the ticks in
between, which the next measurement discards. Every constant in that model is now fitted from
recorded client frames rather than guessed
([calibration](../sources/2026-08-18-minimap-odometry-calibration.md)).

`flyff_bot.features.vision.minimap` is the sensor. It is read-only: it locates the ring, reads the
frame, and dispatches no input of any kind — US-027 stays rejected and `SearchMode.MINIMAP_RADAR`
stays never-dispatched. `locate_minimap` anchors the ring centre 88 px from the client's right edge
and 106.5 px from its top edge, in client-area coordinates, then refines that within +-5 px once per
client size and reports "not found" when no opaque ring stroke survives its intensity and
angular-deviation bounds. A collapsed minimap, an unexpected window decoration, and a client too
small for the widget all take that path, and the session keeps running. `read_minimap` returns the
Hanning-windowed 62 px surface disk, the marker heading, and a zoom signature; `measure_translation`
phase-correlates two disks and returns the scroll only when the correlation response clears 0.30 and
the displacement stays inside 24 px.

Because the minimap is north-up and player-centred, its scroll is already expressed in world axes,
so no heading rotation is applied to it and a heading error cannot corrupt the translation. Because
it observes motion rather than commands, `TARGETING` and `COMBAT` motion reaches the estimate without
any `integrate_movement` call on the combat dispatch paths, and standby ticks follow the character
while the operator moves it by hand (`PathingController.track`, called from the orchestrator's
standby branch). Heading comes from the colour-keyed marker's principal axis, with the nose picked by
the third moment of its projection — the wedge tapers towards the nose, which resolves the 180 deg
ambiguity from the shape instead of from a constant.

`TrackingQuality` gates what the session is allowed to learn. `MEASURED` is a confident measurement;
`PREDICTED` is the command model covering at most `prediction_grace_seconds` (1.5 s, one grid cell of
worst-case error at the fitted speed); `DEGRADED` is everything beyond that. While `DEGRADED`,
`PathingController.observe` writes no visit, spawn, or stall, and calls `SpatialMap.break_trail()` so
that recovery cannot link an edge across a span the session never observed. Routes may still be
followed or abandoned; nothing new is created. The quality is published on `NavigationSnapshot` and
shown as a badge on both the dashboard and the path inspector.

`StallDetector` now has two mutually exclusive paths. With a measured displacement it compares the
measured speed against 3.0 minimap px/s, which the recordings separate cleanly from both the 0.02
px/s of standing still and the 9.4 px/s of running, and it never computes the peripheral frame
signature. The pixel-difference signature from BUG-009 remains only as the fallback for ticks with no
usable measurement.

**The minimap pixel is the canonical unit** of the whole navigation feature. There is no world-unit
conversion anywhere, because deriving one would need a run speed the client does not display. The
`*_units` identifiers were renamed accordingly (`cell_size_pixels`, `leash_radius_pixels`,
`distance_pixels`, `forward_speed_pixels_per_second`). The unit is only defined per zoom level: one
pixel at maximum zoom-out covers exactly two at the default zoom, and the ring geometry itself does
not change between them. The tracker anchors a zoom signature on its first measurement, publishes it
alongside every position, and drops to `DEGRADED` until `reanchor()` when five consecutive readings
deviate from it by more than 20 %. The tolerance was 12 %, which was fitted to the 4.2 % spread
*inside* one recorded burst; a longer contiguous walk crosses terrain whose drawn detail varies far
more than that without any scale change, and dropped into `DEGRADED` mid-run. 20 % absorbs that and
still sits below the 24.6 % step between the two zoom levels (US-043). The ring locator's angular
deviation bound moved from 15.0 to 20.0 for the same reason: the stroke is drawn over the map, so
high-contrast terrain under the annulus lifts the deviation past the original bound while the
intensity bound still rejects every recorded scenery sample. Backward speed was removed rather than guessed: no `S` burst was
recorded, no controller dispatches `S`, and backward motion is observed anyway.

The measured turn rate is 240 deg/s, not the 90 deg/s that was assumed, so the default pathing turn
pulse dropped from 0.15 s to 0.08 s to keep one pulse inside the 25 deg heading tolerance. The added
measurement costs 1.06 ms per tick with the geometry cached, on the existing `SessionWorker` thread,
never on the Qt GUI thread.

## Navigation profile anchoring (US-036)

A learned map is a set of minimap-pixel coordinates relative to wherever its session started, so
loading one into a later session used to reinterpret it relative to the new start point: every cell,
edge, hotspot, and stall marker shifted by an arbitrary offset. Since US-035 the frame's *rotation* is
absolute (the minimap is north-up), which leaves exactly one unknown — the translation. US-036 closes
it with a stored landmark.

**Schema version 2 is the only format.** `SPATIAL_MAP_SCHEMA_VERSION` is 2 and
`SpatialMap.from_dict` rejects anything else by name. There is no migration branch and no read-only
legacy mode for pre-odometry version 1 documents: their dead-reckoned coordinates carry no physical
ground truth to remap (ADR-003). Profiles recorded before this change are invalid and must be newly
recorded.

**The landmark.** `flyff_bot.features.navigation.anchoring` owns the anchor record: the greyscale
minimap disk the profile was recorded at, the map coordinates (in minimap pixels) it was captured at,
the measured heading, and the zoom signature that *is* the scale. It is stored inside the same profile
document as a base64 PNG under an `anchor` key, so a profile stays one self-contained file.
`MinimapSample` now also carries the unprepared `surface_greyscale` disk and `MinimapReading` passes
it up, which is how the navigation layer obtains a landmark without decoding frames itself.
`PathingController.track` keeps the freshest `MEASURED` disk as the anchor candidate, so standby
ticks alone keep both saving and loading possible while the session is paused.

**Loading is a decision, not a file read.** `PathingController.load_map` returns a
`ProfileLoadResult` and takes one of five outcomes:

| Outcome | Condition | Effect |
| --- | --- | --- |
| `ANCHORED` | landmark correlated above 0.30 within one surface radius | map loaded and writable; `MovementTracker.relocate` moves the tracker into the profile's frame |
| `SCALE_MISMATCH` | stored zoom signature deviates from the live one by more than 20 % | nothing loaded; the active map stays intact |
| `UNMATCHED` | no live disk, or correlation below the gate | nothing loaded; the operator is offered read-only or cancel, defaulting to cancel |
| `READ_ONLY` | the operator accepted a read-only load (`accept_unmatched`) | map loaded, learning suspended |
| `UNANCHORED` | the profile carries no landmark (saved while `DEGRADED`) | map loaded read-only |

## Teleporter extraction and dispatch (US-065)

The navigation feature includes offline teleporter destination extraction from
`TeleportOption.inc` (loose or packed in `System3`), typed `TeleporterDestination` records,
and a guarded `TeleporterDispatcher`. The dispatcher defers while combat is active or damage
is observed, enforces foreground and emergency-stop checks, sends a deterministic no-OCR UI
sequence (`V` hotkey, search-field click, text input, first-result click, teleport-button
click), and confirms arrival only when the authoritative world ID and position match. On
timeout or blocked UI state it closes the teleporter window and enters safe standby.

The current `LivePositionReader` provides XYZ only; there is no verified world-ID memory
offset. Production arrival confirmation therefore fails closed rather than guessing identity.

Matching reuses the odometry machinery rather than a second implementation:
`windowed_surface` applies the same marker masking and Hanning window to a stored disk that
`read_minimap` applies to a live one, `correlate_surfaces` is the shared response-gated phase
correlation (`measure_translation` adds only the per-frame 24 px bound, anchoring the one-radius
bound), and the map-scroll-to-player sign rule comes from `MinimapReading.player_dx/player_dy`. The
recovered offset is the position of the *capture point*; whatever the character covered since is added
from the live prediction offset, which is the same vector in both frames because they share rotation
and scale. Heading is not re-applied from the anchor — it is measured absolutely every tick.

**Read-only maps never learn and are never written back.** A read-only load takes the same branch in
`PathingController.observe` as `DEGRADED` tracking: no visit, spawn, or stall is recorded and
`break_trail()` runs, so stall-driven retreat is off too (it needs the map to record the obstacle).
`save_map` refuses while read-only, because persisting coordinates offset from the profile's frame by
an unknown amount would corrupt the very profile the session failed to re-anchor to. It otherwise
returns the `ProfileAnchorState` a later load will get, and stores no anchor at all when tracking is
`DEGRADED` at save time.

**Operator visibility.** `NavigationSnapshot.profile_anchor_state` publishes `SESSION`, `ANCHORED`,
`READ_ONLY`, or `UNANCHORED`, rendered as a chip beside the profile controls. The refusal paths get
their own localized dialogs: the two-outcome prompt (`MainWindow.confirm_read_only_profile`, exactly
two buttons with cancel as the default) and the scale-mismatch notice, which names both signatures.

**Persistence API.** `save_spatial_map` / `load_spatial_map` were replaced by `save_profile` /
`load_profile` over a `NavigationProfile` (map plus optional anchor); the obsolete pair was deleted
rather than kept as a shim. A corrupted or truncated anchor record costs the profile only its
landmark — it then loads unanchored, and no exception escapes to the UI, matching the corrupt-profile
behaviour of US-021. The usable matching radius inside the one-radius bound is a field measurement
that is still open.

## Standardized viewport alignment (US-042, US-043)

The inverse-perspective distance relation of US-037/US-041 only holds at the camera state it was
fitted at, and the odometry of US-035 only reports calibrated minimap pixels at the zoom level it was
measured at, so `features/automation/camera_alignment.py` restores both instead of trusting the
operator to reproduce them by hand. `CameraAligner.align()` runs four steps against one client: ten
clicks on the minimap's zoom-out button past the widget's own range, twenty forward wheel notches to
the engine's hard-clamped zoom limit, a 0.8 s hold on the pitch-up key (`VK_UP`) into the vertical
ceiling, and a 0.55 s pitch-down pulse (`VK_DOWN`) onto the standardized elevation that keeps
horizon spawns visible. Every camera step settles for 0.2 s before the next one, because the client
interpolates the camera, and every minimap click settles for 0.12 s, because the widget swallows a
click that lands during its redraw. Nothing about the game's memory or rendering is inspected: the
sequence is deterministic only because both limits are clamped by the engine and the pitch is
measured from its own limit rather than from wherever the camera happened to be.

**The minimap step is located, not hard-coded to the screen.** `minimap_zoom_out_button` derives the
click point from the `MinimapGeometry` the odometry locator already returns, at a measured offset of
(-66.5, +45.5) px from the ring centre — the button's pale disk in the client-area stills shipped
under `data/assets/fixtures/minimap/`. `frame_minimap_locator` binds a `FrameSource` and window handle
into the `MinimapLocator` callable the aligner takes, and a widget that cannot be found (collapsed,
or a frame that could not be captured) returns the new `CameraAlignmentStatus.MINIMAP_NOT_FOUND`
before any input is dispatched, which the orchestrator treats like any other failed pre-flight. The
minimap runs first so the pointer ends over the client centre, where the camera's wheel notches have
to land. An aligner constructed without a locator skips the step and runs the camera sequence alone.

> **Superseded by US-059.** The minimap step, `minimap_zoom_out_button`, `frame_minimap_locator`,
> `MinimapLocator`, and `CameraAlignmentStatus.MINIMAP_NOT_FOUND` were removed together with the
> minimap odometry they calibrated. `CameraAligner.align()` now runs the two camera steps only
> (zoom-out notches, pitch ceiling plus calibrated down pulse). The paragraphs above describe the
> US-042/US-043 state and are kept as the record of why the camera steps exist; the stills under
> `data/assets/fixtures/minimap/` remain as the measurement evidence they were read from.

`CameraAligner` re-checks the emergency stop and foreground focus before every step — including
before each of the ten minimap clicks — and once more after the last one, returning
`CameraAlignmentStatus.ABORTED` or `FOCUS_LOST` instead of dispatching the remainder. The wheel itself goes through the new
`WindowsInputController.scroll_wheel_while_guarded`, which centres the cursor over the client area —
Windows routes wheel input by cursor position — and stops between notches on either condition.

**The pointer is moved with `SetCursorPos`, injected mouse move, and right-click focus pulse (BUG-015, BUG-016).** Teleporting
the cursor leaves no move in the injected input stream the client reads, while absolute injection alone
can diverge on DPI-scaled displays, so `scroll_wheel_while_guarded` sets the hardware cursor via
`SetCursorPos`, dispatches `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` through
`SendInput` (normalized onto the 0-65535 virtual-desktop range), and pulses a right-click (`MOUSEEVENTF_RIGHTDOWN` / `UP`)
to reclaim 3D world focus after HUD/minimap interactions without walking or deselecting, waiting 0.15 s for the client to
process it before the first notch. The emergency stop and foreground focus are checked before that move, so an
unfocused client never has the operator's pointer dragged across it, and a client area that cannot be
measured now dispatches nothing at all rather than scrolling wherever the pointer happened to be left.

BUG-014 and BUG-016 established the verified alignment sequence. In Entropia Flyff (`neuz.exe`), the
client zooms *out* on forward wheel rotation (`+WHEEL_DELTA`), so twenty forward notches outrun the
zoom range from a fully zoomed-in start. Camera pitch is bound to `VK_UP`/`VK_DOWN`; the `VK_PRIOR`/`VK_NEXT`
holds the routine used to dispatch are unmapped for pitch in the standard client, so the camera stayed at
whatever elevation it had been left at and the ~45° standardization never happened. The pitch keys are now
taken from the single `controllers.py` definition the search sequence already tilts with.

`FarmingOrchestrator` owns alignment as a session phase, `FarmingMode.ALIGNING`, entered from
`start()` when `FarmingConfig.auto_align_camera` is set and left only once the camera is standing
still. The blocking sequence runs on the existing `SessionWorker` thread, never on the Qt GUI thread,
and the orchestrator publishes the `BotStatus.ALIGNING` dashboard update *before* it blocks so the
badge covers the whole sequence. A failed pre-flight never farms on an uncalibrated perspective: a
lost foreground pauses the session and latches `BotStatus.ALIGNMENT_FAILED` until the next start,
and a held `END` latches the session-local emergency stop. Pre-flight alignment is configured via the
"Auto-align camera on start" dashboard toggle. `capture_spawn_distance_samples.py` runs the identical
routine after `acquire_window` and refuses to record a run it could not align (`--no-camera-align`
opts out).

## Developer calibration harnesses (US-035, US-041, US-043)

`scripts/` holds the offline harnesses that produce the measurements the shipped constants cite.
They are never imported by `flyff_bot` and ship with nothing: they depend inward on the same feature
modules the application uses, so what they measure is what the application will see. Their console
output is developer diagnostics and deliberately does not go through `locales/`.

- `capture_minimap_samples.py` records minimap frame sequences (`burst`, `still`) and produced
  [the odometry calibration](../sources/2026-08-18-minimap-odometry-calibration.md).
- `capture_spawn_distance_samples.py` records synchronized approach sequences (`walk-in`), stationary
  bearing frames (`bearing`), and fits the inverse-perspective distance relation offline (`fit`). It
  drives `MinimapOdometer` plus `MovementTracker` for odometry and `OpenCVDnnYoloDetector` for the
  mob boxes, on the same frame, so each recorded sample pairs an apparent bounding-box height with a
  measured travel.

Both obey the same safety boundaries as the application: capture goes through the documented GDI
path, no input is dispatched until the client is confirmed foregrounded, and `END` releases every
held key and flushes what was captured so far to disk.

**Perspective model and camera reproducibility.** Apparent bounding-box height falls off with the
inverse of distance ($d = a / h + b$). Because coefficient $a$ depends directly on focal length
(zoom) and camera pitch, 100% reproducibility across sessions without memory inspection is guaranteed
by standardizing on the **zoom hard-stop** (mouse wheel scrolled all the way back to the game's maximum
zoom limit) and a **controlled ~45° camera pitch** (navigated from vertical limit/reset to preserve
forward FOV for spawn sightings), both during calibration captures and live bot farming. US-042
automated that protocol as `CameraAligner`, which both the harness and the farming pre-flight run, so
the two can no longer drift apart. US-043 added the minimap zoom-out hard stop to the same routine,
which fixes the odometry scale the walk-in's travel is measured in as well.

**One walk-in follows one mob.** A spawn cluster puts ten or more mobs of the target class in the
viewport at once, and the harness used to record the most confident candidate per frame. Confidence
flaps frame to frame, so the recorded height jumped between foreground and background mobs of the
same cluster (49 px, then 196 px, then 85 px) and destroyed the monotonic height/travel relation the
fit depends on. `ApproachTargetTracker` acquires the target once, on the first frame that detects it,
as the candidate whose box centre sits closest to the viewport's vertical centreline — the mob the
operator lined the character up with — and every later frame is matched against the *previous*
tracked box rather than re-selected on its own merits: any candidate overlapping it by 0.2 IoU, or
whose centroid moved less than 120 px, is eligible, and the highest overlap wins with centroid
distance breaking ties. A frame with no acceptable match leaves the last box in place and records
nothing, so a mob hidden behind another model for a frame or two is picked up where it reappears;
beyond two consecutive misses the target counts as lost and nothing further is tracked, because
adopting whatever is nearby is exactly the jump the tracker exists to prevent. Manifest schema
version 2 marks the tracked mob with `is_approach_target` on exactly one detection per frame, which
is what the offline fit reads and what the stored crop pictures. Runs recorded under version 1 are
rejected rather than migrated (ADR-003): their per-frame selection cannot be reconstructed.

**A walk-in measures remaining travel, not distance.** The client stops the character at melee
range, so the absolute distance to the mob is never observable. Per frame the harness records how far
the character still travels until the approach ends, which turns `distance = a / h + b` into
`remaining_travel = a / h + (b - r_melee)`: the inverse-height coefficient is recovered unchanged and
the fitted intercept carries the melee stopping distance folded into it. Remaining travel is
accumulated backwards from the stop, so an unmeasured odometry increment invalidates only the frames
before it. Every distance is in minimap pixels, the canonical unit of US-035.

`scripts/` is type-checked under the same strict `mypy` configuration as `src/` and `tests/`, and is
on the pytest import path, because the manifest schema and the curve fit are unit tested.

## Combat obstacle stalls and adaptive re-navigation (US-039)

US-039 closes the gap that let one blocked approach hold a session hostage. Clicking a mob makes the
game client walk the character there, so during `TARGETING` and `COMBAT` no movement key is
dispatched at all: `PathingController` sees `movement_commanded` false, `StallDetector` reads the
tick as carrying no evidence, and the character can run against a tree indefinitely. The observation
therefore moves to the only layer that knows a client-driven walk is under way.
`FarmingOrchestrator` owns a second `StallDetector` (`FarmingConfig.approach_stall`) and samples it
every combat tick with `movement_commanded=True`, using `PathingController.measured_speed_pixels_per_second`
when the minimap supplies one and falling back to the peripheral frame difference otherwise. Sampling
stops the moment `CombatController.damage_dealt` turns true, because a character standing in attack
range produces exactly the motionless scenery the detector looks for, and that is not a blocked path.

The verdict travels into the state machine as `CombatController.step(state, approach_stalled=...)`
rather than as controller state, so the machine stays a pure function of what it is told, and it
leaves as `EngagementBreakReason.OBSTACLE_STALL`. That reason and `ENGAGEMENT_TIMEOUT` form
`UNREACHABLE_BREAK_REASONS`: both mean the approach never arrived, so they share one strike counter.
`ApproachFailure` records the engaged client-space position, its strike count, and an expiry
(`approach_failure_memory_seconds`, 30.0 s), and judges "the same mob candidate" by proximity within
`target_lockout_radius_pixels` exactly as `TargetLockout` already does — an engagement carries no
detection identity, so a place is the only identity available (BUG-010). The first strike keeps the
short 4.0 s lockout and sets `CombatDecision.reposition_requested`; the second consecutive strike
against the same location registers a `unreachable_lockout_seconds` (30.0 s) lockout and clears the
record, which is what stops the > 20 s re-click loop the story reported.

`FarmingMode.REPOSITIONING` is the recovery. It is a second `SearchController` configured as a
bounded sweep (`idle_timeout_seconds` 0.0 so it starts immediately, four rotation steps, two roam
steps) and it ends after one full rotate-then-roam cycle, which `SearchController.completed_cycles`
now reports. Reusing the search controller is deliberate: rotating the camera and roaming is
precisely what re-positioning means here, and a separate class would have duplicated it. The phase
dispatches through the existing `SearchInputDispatcher` and feeds `PathingController.integrate_movement`,
so it obeys the same foreground and `END` guards as every other phase and its steps stay inside the
position estimate. When the sweep ends the session returns to `SEARCHING` with a reset idle timeout.

Where a map is being learned, `PathingController.register_obstacle` writes the blocked cell and the
edge that reached it exactly as a self-steered stall would, then retreats to the last verified safe
waypoint. It refuses when the position is unknown or the map is read-only — a stall is only evidence
about a place while the place is known — and while a retreat is already running, so one obstacle is
never counted twice.

One consequence is worth naming: a fight that lands no damage for `stall_timeout_seconds` (5.0 s)
now breaks as an obstacle stall instead of waiting for the 10.0 s engagement timeout. Both reasons
lead to the same recovery and the same strike, so the only observable difference is that the session
recovers sooner.


## Multi-target monster selection and per-mob kill quotas (US-035 quotas)

US-035 turns the single hunted monster of US-038 into a set of monsters, each with its own kill
quota, and makes the session end when all of them are satisfied. Two US-035 stories exist in this
repository — the other one is the minimap odometry work above; this section is the one backed by
`docs/user-stories/completed/US-035-multi-target-selection-and-per-mob-kill-quotas.md`.

`flyff_bot.features.automation.kill_goals` holds the domain. `MobKillQuota` pairs a class name with
the kills it owes, where `UNLIMITED_KILL_QUOTA` (0) means "farm without an upper bound";
`KillGoalConfig` is the operator's whole selection plus the optional shutdown flag and rejects a
repeated class. `KillGoalTracker` is the only stateful piece: it counts kills per class, answers
`active_class_names` with the classes whose quota is still open, and answers `is_completed` only when
every configured quota is bounded and reached — one unlimited entry keeps a session running forever
by design. An unconfigured tracker answers `frozenset()`, which is the same "no restriction" every
filtering boundary already understands, so the selected-monsters path and the all-monsters path are
one path.

Attribution needs the mob's identity, and the HUD counter cannot supply it: US-030 and US-034 give a
single global kill count with no breakdown by class. The identity that does exist is the candidate
the engagement clicked, so `CombatController` records `engaged_class_name` when it leaves `IDLE` and
carries it on the `TARGET_DEAD` decision. `FarmingOrchestrator._record_kill` counts that class and
nothing else — an engagement whose class is unknown is deliberately not counted, because guessing
would corrupt a quota. Every kill route (target HP reaching zero, target loss after damage, HUD
counter increment) reaches the same decision, so all three attribute identically.

A completed quota narrows the session in place. `_apply_active_target_classes()` pushes the still-open
classes through `configure_target_classes()` into `CombatController` and through the
`on_target_classes_changed` callback into the detector and the verifier, which is the same fan-out
`target_class_applier` (`flyff_bot.ui.app`) performs for an operator edit. The orchestrator owns that
fan-out rather than the dashboard: a quota that completes mid-run has to narrow targeting exactly the
way an operator's edit does, and only the session knows when that happens. Once `is_completed` turns
true `_goal_completed()` reports it alongside the existing item goal, and `_complete_session()` moves
to `FarmingMode.COMPLETED`, flushes the navigation map, and — only when the operator ticked the
option — asks the client to close through `SessionShutdownAdapter.close_window()`, one request per
session. That call is `PostMessageW(WM_CLOSE)`: the same cooperative notification the title bar's
close button sends, which the client may refuse, and never a process kill.

`flyff_bot.features.automation.kill_persistence.SqliteKillLog` is the durable record: `kill_events`
rows carry session id, class name, and an ISO-8601 UTC timestamp, `kill_quotas` stores what the
session is working towards. Each operation opens its own short-lived connection — kills arrive at
most once per engagement, so a connection per write is cheap and keeps the store safe to call from
the session worker thread and the Qt thread without owning a lock. A tracker constructed with an
existing session id restores its counts from the log, which is what lets progress survive a pause or
a reconnect. The database lives at `data/kill_log.sqlite3` and is git-ignored like the other local
session state.

On the dashboard, `TargetSelectionPanel` (`flyff_bot.ui.target_panel`) replaces US-038's dropdown: one
row per model class with an activation checkbox, a quota spin box whose zero renders as "unlimited",
and a live `14 / 20` progress label fed from `DashboardUpdate.kill_progress`. No checked row means
every detected monster stays eligible, which preserves the previous default exactly. Keeping both
controls was rejected: two widgets writing the same whitelist would contradict each other. The
completed session also gets its own `BotStatus.COMPLETED` badge instead of reading as generic
standby.
## Unrecoverable stuck recovery and spawn re-anchoring (US-040)

US-039 gave a blocked *approach* a way out; US-040 gives a blocked *character* one. When the camera
sweep, the roaming pulses, the Dijkstra bypass, the retreat to the last safe waypoint, and the
re-positioning sweep have all run and none of them moved the character — the picture of a body wedged
in terrain geometry or dropped off a floating-island edge — nothing inside the movement model can
help, because the only remaining exit is not walkable. The recovery is therefore a teleport item or
skill on a quickslot, and the price of using one is that the session's whole spatial estimate becomes
wrong at once.

`flyff_bot.features.automation.emergency_recovery` holds the detection. `EmergencyRecoveryMonitor`
accumulates one span: the continuous time across the ticks it is actually stepped in which the session
produced no evidence of progress. Three things count as evidence and each resets the span to zero — a
position that moved at least `progress_distance_pixels` (10.0, deliberately below the 15-pixel
navigation cell so real travel always counts while measurement jitter around a wedged character never
does), a fight that is landing damage, and the tick a kill reconciles on. A target *click* is
explicitly not evidence: running against a tree towards a mob re-targets forever, which is the exact
situation this recovery exists for. One accumulator covers every failed unstuck mechanism rather than
one timer per stage, because their common observable outcome is the same absence of progress. Like
`PowerUpScheduler`, the monitor is halted rather than reset in standby, so a paused, unfocused, or
settling span never expires the timeout unobserved.

`EmergencyTeleportDispatcher` is the only place the hotkey is sent, and it applies the same two guards
as every other dispatcher: the client must be foregrounded and the `END` emergency stop clear. A
refused dispatch changes nothing — the span stays expired, so the attempt simply repeats on the next
tick the guards allow through. An operator who assigns no hotkey gets the honest alternative rather
than a silent no-op: `EmergencyRecoveryAction.UNAVAILABLE` pauses the session and raises
`BotStatus.EMERGENCY_TELEPORT_UNAVAILABLE` on the dashboard, because only a person can free the
character at that point. The default hotkey is `F4`, so an untouched installation teleports instead of
pausing; leaving it unassigned is a choice the persisted `null` in
`data/emergency_recovery_config.json` preserves across restarts.

Because the teleport is instantaneous, `FarmingMode.TELEPORTING` exists purely to *stop* doing things.
For `settle_delay_seconds` (2.0) the session still captures frames but observes nothing into the map
and steps no controller: every estimate measured during the transition describes the place the
character just left. The reset splits across the two moments accordingly.
`PathingController.begin_teleport_recovery()` runs at dispatch, while the stuck position is still
known, and records it as a stall on its cell exactly as a self-steered stall would — without it the
first route planned from the spawn anchor would lead straight back off the same ledge — then drops the
route. It refuses on an unknown or read-only position for the same reason `register_obstacle` does: a
stall is only evidence about a place while the place is known. `complete_teleport_recovery()` runs when
the settle window closes and relocates `MovementTracker` onto the profile's mapped spawn point, or onto
the session origin when none is mapped. It also breaks the map trail, so the traversal graph never
invents an edge across a jump the character did not walk. The session then rebuilds
`CombatController` from the active config — an engagement, its lockouts, and its approach-failure
strikes all describe a mob that is now a map away — resets the search stages, and returns to
`FarmingMode.SEARCHING`.

The spawn anchor belongs to the map, not to the session, so it travels in the profile:
`NavigationProfile.spawn_point` serializes as a `spawn_point` object beside the existing `anchor`
record, and an unreadable one costs the profile only its anchor rather than failing the load, matching
how a corrupted landmark is already handled. `PathingController.mark_spawn_point_here()` stores the
currently measured position and refuses a degraded one, which the dashboard turns into a localized
refusal dialog rather than a silently stored guess. On the dashboard the "Set Spawn Point" button sits
in the Profile Controls next to save, load, and reset — the anchor is map-scoped like they are — the
chip beside it reads the value back out of the live `NavigationSnapshot`, and `PathInspectorWidget`
draws it as a magenta crosshair with its own legend entry.

## Authoritative world geometry and goal-driven zone navigation (US-045)

Every navigation surface before this one learned the world by walking into it. US-045 adds the
other half: the client already ships the region's spawn zones and its terrain, so the map can be
read before the first step instead of inferred from thousands of them.

`flyff_bot.features.navigation.world_extractor` is the reader, and it is strictly offline file
I/O - no game process is opened, read, or written. Four loose client files carry everything it
needs. The world script (`.wld`) states the block grid and `MPU`, the world units one terrain
vertex spans. The region script (`.rgn`) is UTF-16 text whose `respawn7` records become typed
`VectorSpawnZone` values: monster id, 3D centroid, 2D bounding rectangle, mob capacity, and
respawn interval. Each terrain block (`.lnd`) is a version integer, its block coordinates, and a
raw 129x129 IEEE-754 float32 height grid addressed row-major with z as the row. The
dynamic-object file (`.dyo`) places props, and its position is validated against the region
bounds because a position off the map is the clearest available evidence that the record offsets
do not describe that file.

**The packed archive was out of reach when US-045 shipped.** `<world>.one` is obfuscated, so
extraction saw only the blocks a client leaves loose on disk. For Eden that was exactly one -
`WdEden03-02.lnd` - beside the full 83 spawn zones and all six monster classes. Zones outside that
block extracted normally and routed without terrain constraints, which is what left `StallDetector`
as their safety net rather than a redundancy. US-052 lifts that limit and reads the archives
themselves; the paragraphs below describe the state US-045 left behind. The client's own
identifier-to-name table shares that fate, so `data/assets/world/monster_ids.json` pairs the six
Eden identifiers with the six `models/labels.txt` classes in ascending identifier order as an
operator-editable assumption; an unmapped identifier still extracts under its numeric identity.

Passability is a slope test, not a paint layer. A terrain quad whose steepest rise between two
adjacent corners exceeds one metre per metre of run is impassable, which is the >45 deg cliff the
client's physics refuses. Contiguous impassable quads are merged greedily into maximal
axis-aligned rectangles, because the planner needs only their outer corners and a raster of
single quads would hand it thousands of redundant ones. Eden's one mapped block is a quarter
impassable and reduces to 348 rectangles.

`vector_routing.VectorRoutePlanner` searches those rectangles exactly. Among axis-aligned
obstacles the shortest obstacle-free path bends only at corners, so the corners plus the two
endpoints are a complete vertex set and A* over their mutual visibility is optimal rather than
heuristic. Three things keep it affordable. The graph is built per query over a corridor - the
endpoints' bounding box plus a margin - instead of the whole region. Route vertices are clipped
to that corridor, which is what makes the local view *sound*: the box is convex, so every leg
between two vertices stays inside it, and every obstacle overlapping it is a blocker, so nothing
a leg can reach was left out. And one vertex's visibility against every other is evaluated as a
single vectorised Liang-Barsky slab clip. Measured on the extracted Eden map: intra-zone legs
solve in 0.26 ms median, zone-to-zone hops in 2.5 ms median and 36 ms worst case. A query whose
detour would have to swing wider than the corridor, or whose corridor exceeds the obstacle
ceiling, is reported blocked - a refusal that falls back, never a wrong route.

**US-045 originally had no live world-frame measurement.** Session positions were minimap pixels
relative to the session start while the extracted map spoke client world units, so
`WorldRegistration` used an operator-selected zone correspondence and provisional scale. US-048
now supplies the player's absolute XYZ from a narrowly bounded, read-only adapter for two
fingerprinted supported client builds. That live sample is the primary world-frame position while
available; `WorldRegistration` and measured minimap odometry remain the fallback for an unsupported
build or failed read.

`vector_navigation.VectorZoneNavigator` owns the three decisions above the geometry. Which goal
is still unfinished - `ZoneGoal(monster_name, kill_quota)`, worked through in order. Which of that
monster's zones the session is bound to - the nearest, and the binding is deliberately sticky, so
drifting toward a neighbour never abandons a route in progress. And what polyline leads there: a
zone is a patrol *boundary*, so the route sweeps an inset ring of its rectangle starting at the
station nearest the character, with each leg planned through the visibility graph. Completing a
quota drops the binding, which is what makes the session walk to the next monster's nearest zone
without a restart. Kills reach it from `FarmingOrchestrator`, which remembers the verified target
nameplate while fighting because the header is already gone by the time a kill confirms. These
quotas are the minimum the story's zone-switching criterion needs, not the dashboard and SQLite
surface the pending multi-target selection story specifies.

**Only route generation is replaced.** `PathingController.waypoints` became continuous
`WorldPoint`s so a vector route needs no rounding through the grid, and `_plan` consults the
navigator first, falling through to the learned circuit whenever it has nothing - no extracted
map, no zone for the active monster, or a blocked corridor. Everything underneath keeps running
unchanged: `MinimapOdometer` and `MovementTracker` measure, `StallDetector` still catches the
obstacles no file describes (other players, dynamic entities), retreat to the last safe waypoint
still works, and visit and stall history is still written. What *is* bypassed is the spawn
heatmap: the decaying sighting weight exists to decide where to explore, and an extracted map
already states where the spawns are, so accumulating estimated sightings beside it would only
compete with authoritative geometry.

The operator surface is `flyff_bot.ui.world_data_dialog`. It lists the client regions found under
the configured world root, extracts one on a worker thread - decoding megabytes of terrain is far
too slow for the Qt event loop, so results reach the widgets only through its signals - and
reports zones, impassable areas, terrain blocks, monster classes, and the output path. Extracted
maps are written as versioned JSON to `data/navigation/worlds/<world>.json`. The same dialog arms
navigation: the standing zone, the scale calibration, and an optional per-monster kill quota
become a `VectorNavigationRequest`, which `run_desktop` turns into a navigator against the live
position estimate at the moment the operator confirms it. The dialog cannot do that itself, and
deliberately does not see the estimate, because a registration is only meaningful against the
position it was applied at.

## Closed-loop 3D world navigation (US-048)

US-048 makes live client XYZ the primary position signal without widening the process-memory
boundary. Its two SHA-256 client fingerprints documented by
[the static extraction](../sources/2026-08-19-entropia-client-navigation-data-extraction.md), opens
`neuz.exe` with query and read rights, resolves one module-relative player global, reads the pointer
width, and then reads exactly the 12-byte float32 XYZ struct at player offset `0x188`. It does not
scan memory or read game state around the coordinate. An unknown build, lost handle, short read, or
non-finite coordinate closes the handle and reports an unavailable coordinate; a later poll may
recover.

The world-map schema now retains decoded `.lnd` height blocks rather than only their derived steep
rectangles. `navigation.terrain_routing.TerrainRoutePlanner` samples that field into 3D route nodes,
rejects edges above the configured walkable gradient, and weights traversable edges by both
horizontal distance and elevation change. A* therefore detours around steep cells; smoothed turns
carry lateral strafe metadata for contour-following movement. Temporary live-coordinate blocks can
be excluded on a global replan after repeated recovery failure. Terrain routing is authoritative
only where a decoded loose height block covers the query; the existing visibility graph and learned
navigation remain available outside that coverage.

`PathingController` polls live position at the adapter's default 10 Hz, anchors route and dashboard
snapshots to it, and gives that delta to `StallDetector` before its older minimap/frame signals. A
commanded speed below 0.5 world units per second for 2.0 seconds triggers a bounded strafe,
backstep, and tangent-replan sequence. Repeated failure at the same coordinate adds a temporary
impassable node and requests a wider replan. Input still crosses the foreground-checked Win32
dispatcher, and either END or Escape aborts dispatch; emergency stop also clears navigation state
and releases the process handle idempotently.

BUG-017 makes that live-collision path equally authoritative during a client-driven combat approach.
`FarmingOrchestrator` forwards the newest live XYZ sample and its timestamp to its separate approach
stall detector; when it confirms an obstacle, `PathingController.register_obstacle()` queues the
same bounded strafe/backstep and tangent replan rather than merely recording a learned minimap
obstacle. The orchestrator drains that local evasion before its one-cycle generic repositioning
sweep, so it does not immediately roam back towards the blocked heading. This path remains useful
with a read-only minimap map because its temporary world-coordinate block is transient, while a
trustworthy writable minimap map retains its learned obstacle penalty too; without a supported live
sample, the existing minimap/frame-based approach recovery remains the fallback.

Long-range travel uses ground pathing; the obsolete generic anchor/blinkwing controller was removed.
The only teleport boundary is Flyff's built-in teleporter UI (US-065), driven from the extracted
client destination catalog. Emergency reset reuses that guarded dispatcher: the operator selects one
client-declared destination, combat/focus/END guards are enforced, and confirmation requires both the
authoritative world identity and a position at the extracted anchor within 2 seconds. Failure latches
emergency stop with `emergency_reset_unconfirmed` instead of guessing that arrival occurred.

The dashboard exposes the position-source boundary instead of hiding it: green GPS means a finite
XYZ sample from a hash-supported client, while an unavailable GPS state displays its typed reason.
The Navigation Inspector draws that world point, height-derived topographic samples, 3D route
markers, trajectory vectors, and a remaining-route elevation strip. Green GPS does not mean that
collision, teleport, terrain, or server state is complete.

The source inventory is materially incomplete: only 153 of 3,861 declared terrain blocks have a
matching loose `.lnd`, placed-object formats vary, collision mappings and packed indices are
unresolved, and dynamic/server state is not present in client files. The resulting design is a
closed-loop controller with live confirmation, fallback, bounded recovery, and emergency abort. It
does not and cannot establish a literal guarantee of 100% fault-free autonomous navigation. The
automated suite covers the adapter and control decisions; the Windows live-client walkthrough in
US-048 remains outstanding field validation.

## GPS-only vector navigation and configurable client profiles (US-053)

US-053 makes the read-only GPS contract a hard precondition for vector-world movement. The optional
`data/navigation/client_profiles.json` is an operator-maintained JSON list of complete client
profiles: each profile supplies a SHA-256 executable digest, player-pointer RVA, pointer width, and
an optional coordinate offset. When that file is absent, the two embedded profiles remain the safe
defaults; when it is present but invalid, it is an explicit GPS configuration error rather than a
reason to guess an offset. An unsupported build diagnostic names both the detected digest and the
executable path, allowing an operator to add a profile without expanding the allowed memory reads.

`PathingController` may plan or follow an extracted `VectorZoneNavigator` route only with
`PositionSource.LIVE` and a finite live position. Any unavailable reading—including the retained
`MINIMAP_FALLBACK` source marker—clears queued waypoints, pending decisions, evasion steps, and
movement state before entering `PathingMode.BLOCKED`; it therefore cannot dispatch a vector movement
key. The status bar and inspector retain the typed unavailability reason. This restriction applies
to vector navigation; it does not silently convert an unavailable GPS coordinate into a world-space
route based on minimap odometry.

The World Data dialog now operates directly in client world units: its obsolete minimap-pixels-per-
world-unit calibration control is gone. It persists region, extracted-map filename, zone identity,
and quota through `QSettings`, restoring a matching stable identity after refresh or on a later
application start rather than persisting fragile list indexes. Escape/END emergency paths continue
to close the read-only process handle and abort movement. These details are implementation-derived;
the automated repository gate passed, while the Windows `neuz.exe` walkthrough remains outstanding.

## Session event log and transition diagnostics (US-049)

Before US-049 a paused or stalled session left no inspectable trail: the dashboard showed only the
current `BotStatus`, and the reason a run had stopped unattended — lost focus, a killswitch press,
an unreachable target, a reconciliation failure, a capture error, or a completed goal — was never
recorded anywhere. `flyff_bot.features.diagnostics` adds that trail as its own small feature rather
than folding it into `automation`, because logging is a cross-cutting concern the orchestrator
depends on, not a farming behavior itself.

`SessionEventLogger` (`diagnostics.event_log`) is a plain, non-Qt class so it stays independently
unit-testable and safe to call from either the session worker thread or the Qt thread. Constructing
it creates one `logs/sessions/session_<UTC timestamp>.jsonl` file (`DEFAULT_SESSION_LOG_DIRECTORY`);
`record()` appends one JSON object per line and keeps a bounded in-memory ring buffer
(`DEFAULT_EVENT_HISTORY_LIMIT`, 200) that `recent_events` returns most-recent-first. Every failure
path — a directory that cannot be created, a write that raises `OSError`, or a formatting failure —
is caught narrowly (never a bare or broad `except`) and swallowed: a full disk can never interrupt
the farming loop or the Qt event loop that ticks it, per the story's fail-safe acceptance criterion.
A `SessionEvent` is immutable and typed: ISO-8601 timestamp, `SessionEventKind`, previous and new
`FarmingMode` values, an optional free-text `reason`, and optional foreground-window diagnostics.

`FarmingOrchestrator._set_mode()` is the single place every `FarmingMode` transition now passes
through, replacing direct `self._mode = ...` assignment everywhere except the initial `PAUSED`
construction. It is a no-op when the mode does not actually change — so an idempotent
`emergency_stop()` call, or a RECONCILING tick that stays RECONCILING, never spams a duplicate
event — and otherwise records the transition through the optional `SessionEventLogger` the
orchestrator was constructed with. Seven `SessionEventKind` values classify *why* a transition
happened: `MODE_TRANSITION` is the generic case (session start, a mob detected, a confirmed kill, a
completed reconciliation, a finished re-positioning sweep), and `FOCUS_LOST`, `EMERGENCY_STOPPED`,
`OBSTACLE_STALL`, `SUPERVISOR_FAILURE`, `FRAME_CAPTURE_ERROR`, and `GOAL_COMPLETED` cover the six
discrete pause/stop triggers the story enumerates. `EngagementBreakReason` values (including the
other break reasons `ACQUISITION_TIMEOUT`, `TARGET_UNVERIFIED`, and `ENGAGEMENT_TIMEOUT`, which stay
under the generic `MODE_TRANSITION` kind) and comma-joined `FailureFlag` values travel unchanged as
the event's `reason`, so the diagnostics module never re-derives or duplicates a classification that
already exists as a typed enum elsewhere.

Foreground-window diagnostics stay decoupled from the orchestrator's existing Win32-free design:
`FarmingOrchestrator` takes an optional `foreground_window_info: Callable[[], ForegroundWindowInfo |
None]` rather than depending on `WindowsInputController` through its `FarmingInputAdapter` protocol,
so every existing test fake is unaffected. `WindowsInputController.foreground_window_info()`
(`input_control.controller`) is the one concrete implementation: it reads whichever window currently
holds `GetForegroundWindow()` — not the farming session's own window — and returns its title and
owning process name via the same `GetWindowTextW`/`QueryFullProcessImageNameW` calls
`find_windows()` and `focus_window()` already use. `run_desktop` wires it in as
`controller.foreground_window_info`, so a `FOCUS_LOST` event names whatever stole focus (Notepad, a
notification toast, another window) without widening the Win32 surface the safety boundaries
restrict.

On the dashboard, `DashboardUpdate.events` carries the logger's `recent_events` tuple on every
publish, mirroring how `kill_progress` and `engagement_break` already travel — an empty tuple when
no logger is attached, exactly like the other optional diagnostics fields. `EventLogPanel`
(`flyff_bot.ui.event_log_panel`) is a standalone `QGroupBox` widget, matching the `TargetSelectionPanel`
and `PowerUpPanel` precedent of decomposing telemetry panels rather than inlining more widgets into
`MainWindow`. US-050 hosts it directly on the Diagnostics & Logs tab; `set_events()` clears and
repopulates a `QListWidget` from the update's `events` tuple regardless of which tab is selected, so
the panel stays current while hidden. Each row is one summary sentence colour-coded by
`SessionEventKind` (neutral, amber
for the four warning kinds, crimson for emergency stop, emerald for goal completion) and localized
through `Message.UI_EVENT_LOG_SUMMARY`; `previous_mode`/`new_mode` map through a small `FarmingMode`
value dictionary to their own localized labels, and the stored UTC timestamp renders as the
operator's local wall-clock time (`datetime.astimezone()`). The free-text `reason` and any
foreground-window title/process stay untranslated diagnostic detail appended to the sentence,
following the same precedent as OCR raw text and world-data status strings elsewhere in the
dashboard: they are operator-facing evidence, not narrative prose, and a window title cannot be
localized. `logs/` is git-ignored alongside the other local session state
(`data/navigation/`, `data/kill_log.sqlite3`).

## Responsive tabbed dashboard and UI refactoring (US-050)

US-050 keeps the desktop application as one native PySide6 boundary but replaces the growing
accordion-style dashboard with a pinned header above one `QTabWidget`. The header retains the
session status and window-condition badges, tracking and GPS indicators, Start and Pause actions,
attack-key binding, camera alignment and auto-alignment, and the language selector. The five
localized pages separate the operator surface by job: Dashboard, Combat & Targets, Vitals & Buffs,
Navigation & World, and Diagnostics & Logs. Each page owns an internal `QScrollArea`, so changing
content or selecting another page does not call `adjustSize()` or resize the top-level window; the
main-window geometry remains stable while page content scrolls within the available viewport.

The tabs reorganize presentation only. They neither start nor stop workers, and the selected tab is
not an input to perception, navigation, diagnostics, or controller updates. `DashboardUpdate` and
the existing widget-specific update paths continue feeding every page while it is hidden, so
switching tabs reveals current state rather than a feed that paused when its widgets were not
visible. The camera preview, vitals and target summary, target quotas, power-up configuration,
embedded and pop-out navigation inspector, world-data tools, placement guide, OCR diagnostics, and
session event log remain on their existing application and feature boundaries.

The former telemetry row of eleven panel-visibility checkboxes is removed because tabs now own
panel discovery and visibility. Boolean configuration remains interactive, but uses the reusable
styled `QCheckBox#Switch` treatment for settings such as auto-alignment, kill verification, and
vitals rules.
This is an intentional distinction: a switch changes application configuration, while selecting a
tab changes only which already-live view is shown. Keeping generic panel toggles beside the tabs
would create two competing visibility models and reintroduce the unstable accordion geometry.

The dedicated red emergency-stop button is also removed from the header as a presentation choice,
not as a safety-boundary change. The window-level `Escape` shortcut, global `END` hook, Qt emergency
signal, orchestrator latch, foreground checks, and guarded input release paths remain active. The
expanded Dark Slate QSS applies the existing `#0f172a`, `#1e293b`, `#334155`, and `#3b82f6` palette
to the tab widget, tab bar, scroll areas, switches, and their child controls. Tab names, controls,
and tooltips are message-catalog entries synchronized in English and German; the stylesheet itself
contains presentation rules, not user-visible prose.

The automated repository gate covers the hierarchy, wiring, geometry contract, locale parity, and
interaction paths. It passed at 750 tests passed, 2 skipped, and 92.54% coverage. The Windows
live-client visual walkthrough remains outstanding, including visual responsiveness and confirmation
that both `Escape` and `END` halt a live `neuz.exe` session; automated evidence is not presented as
field validation.

## Feature-scoped main-window composition

A follow-up quality refactor keeps `MainWindow` as the stable public composition and intent
boundary while moving feature-specific construction, localization, persistence, rendering, and
navigation lifecycle out of the monolithic window class:

- `ui.main_window_parts` contains feature-scoped slices for header metrics, operator controls,
  combat settings, emergency recovery, vitals rules, quest loading, navigation, diagnostics, and
  status presentation.
- The second pass moved dashboard rendering, camera-preview rendering, configuration persistence,
  and world-data dialog lifecycle behind presenters/controllers. `MainWindow` now composes those
  slices and forwards operator intent; it no longer owns feature rendering rules, persistence
  paths, or dialog construction.
- `MainWindow` retains the public Qt signals, widget accessors, event handling, emergency paths,
  and composition-root wiring expected by the application and tests.
- Feature panels own their business ranges, defaults, configuration conversion, localized labels,
  and internal rendering; the window no longer duplicates their control knowledge.

This change is behavior-preserving at the UI boundary. It does not alter perception, orchestration,
Win32 input, foreground checks, `END`, or `Escape` safety behavior. The remaining largest modules
(`automation.orchestrator`, `navigation.world_extractor`, `navigation.pathing`, and `cli`) need
dedicated, independently reviewed slices because they mix several lifecycle and parsing
responsibilities; bundling those changes into this UI refactor would make the review unsafe.

## Packed client archives and complete terrain height fields (US-052)

US-045 read only the terrain blocks a patch had left loose on disk. Across the client that was 153
of 3,861 declared blocks - 3.96% - so almost every region routed over flat approximation with
`StallDetector` as its only safety net. US-052 reads the packed archives themselves, and the same
client tree now yields 1,116 decoded height fields.

`flyff_bot.features.navigation.client_archive` is the reader. Each region ships one `<world>.hdr`
index and one `<world>.one` payload. The index is `int32 count` followed by one record per packed
file: `int32 name_length`, that many identity bytes, `int32 offset`, `int32 size`. The identity is a
64-character digest of the original file name, so the index never states what an entry is called.
Entry bytes are obfuscated with a keystream derived from the file name itself:

```text
stored[i] = swap_nibbles(plain[i]) ^ ((name[i % len(name)] - 1) & 0xFF)
```

The name is the plain lower-case file name, which makes the transform its own inverse and makes the
opaque identities irrelevant. A terrain block is named by the client's own
`<world><xx>-<zz>.lnd` convention, and its first twelve plaintext bytes are known in advance -
version 3 plus the two block coordinates - so the extractor encodes that prefix and finds the entry
by its *stored* bytes. Lookup is therefore one pass over the index rather than a search: Madrigal's
1,800 entries index in 0.33 s and its 874 blocks extract in about 10 s. Decoding runs as one
`bytes.translate` per key position, so it needs no new dependency.

**Extraction is strictly offline and non-destructive.** No game process is opened, and no client
file is written, repacked, or modified. `encode_archive_payload` exists only to rebuild a known
plaintext prefix in memory so an entry can be recognized.

`extract_world` now merges two terrain sources. A loose `.lnd` is a patch the client itself
prefers, so it wins; every remaining coordinate in the `.wld` grid is read from the archive. Blocks
the archive simply does not hold are not failures - Madrigal declares 900 and ships 874, the rest
being void the client never renders. Extracted maps are named after the region *directory* rather
than its world script, because the seasonal Madrigal variants all declare `wdmadrigal` and a shared
name would have them overwrite each other.

Persistence changes shape with schema version 3. Height grids no longer sit inside the JSON
document: `save_world_map` writes each block beside it as a plain 66,576-byte `.lnd` height field
under `data/navigation/worlds/<region>/`, and `load_world_map` reads them back. Madrigal is
therefore an 11 MB document plus 58 MB of height fields instead of a single JSON of several hundred
megabytes, and it reloads in about a second. The terrain directory is the extractor's own output
namespace, so a re-extraction replaces its `.lnd` files wholesale rather than merging with a larger
earlier run.

**Two client layouts are read, and the third is refused rather than guessed at.** Twenty-five
regions ship a `.hdr` whose records carry an extra leading `-1` field; every later offset lands
wrong and the index cannot describe itself. Those archives are reported as
`UNSUPPORTED_ARCHIVE_INDEX` and skipped, and the region still extracts whatever it leaves loose -
`wdverux` keeps 7 blocks and all 281 spawn zones. A packed block that decodes to something other
than a version 3 height field is reported as `UNREADABLE_ARCHIVE_BLOCK`, and a `.dyo` in one of the
placement layouts this reader does not know is reported as `UNREADABLE_OBJECT_FILE`. All three are
typed `ExtractionDiagnostic` values that the CLI prints as localized lines on stderr and the world
dialog summarizes as a count; none of them costs a region its height field.

`uv run python -m flyff_bot --extract-world` drives this offline. It opens no game window, takes
`--client-world-root`, `--world-map-directory`, and a repeatable `--world` region filter, and
reports blocks extracted against blocks declared per region. Eden goes from 1 mapped block to all
25, with sampled height coverage over its whole 5-by-5 grid.

The automated repository gate passed at 768 tests passed, 3 skipped, and 92.44% coverage, and the
extractor was run against the operator's own unmodified Entropia installation. Terrain accuracy in
a live `neuz.exe` session - that routes over newly mapped blocks match what the client's physics
actually permits - remains outstanding and is not claimed here.

## Offline O3D geometry and multi-layer NavMesh foundation (US-055, completed)

US-055 adds a deliberately narrow **offline** geometry/query layer below the existing live
controllers. `navigation.o3d_extractor` reads supported version-22 O3D payloads only: it checks the
XOR-obfuscated basename embedded in the model header, retains the model bounds, and reconstructs the
dedicated collision mesh from its source-vertex and indexed buffers. Render geometry is deliberately
not used as a collision substitute. `extract_o3d_file()` reads a loose model. `extract_packed_o3d()`
uses the existing read-only HDR/ONE known-prefix lookup for one supplied model name; it cannot
enumerate the archive's opaque entries, so an unknown model name simply remains unresolved.

`navigation.world_geometry` parses the supported fixed-size DYO placement records and preserves the
model reference, XYZ translation, yaw and axis rotations, non-uniform scale, and object identity.
It applies scale, X/Y/Z rotation, and translation to collision vertices, while `terrain_triangles()`
turns the retained US-052 `LandBlock` height fields into triangles in that same client-world frame.
`fuse_world_geometry()` only joins a placement whose collision hull is known. It omits missing or
unsupported models instead of guessing a footprint or treating a visual mesh as physics geometry.

`navigation.navmesh` bakes this static geometry into individually indexed walkable triangles. The
`AgentNavigationConfig` supplies a 45-degree default slope threshold, radius, height, step, and
cell-size constraints. `SurfaceSpan` indexes the polygon IDs that share a horizontal cell without
collapsing vertically distinct floors; polygon adjacency requires a common edge and allowed vertical
step. Canonical triangle ordering gives polygon and connected-region IDs deterministic values for
the same geometry/configuration. `BakedNavMesh` exposes nearest-surface projection, polygon and
region lookup, reachability, A* polygon-corridor waypoints, and distance as the exact sum of the
returned 3D segments. `find_path()` turns the ordered shared portal edges into a consistently
oriented X/Z Funnel corridor: string pulling removes centroid detours while retaining the selected
portal vertices' authored 3D elevations. A malformed persisted corridor falls back to the
conservative deterministic centroid route instead of making an unverified shortcut.

`navigation.navmesh_persistence` persists a canonical `.navmesh.json` document at strict schema
version 1. It validates the configuration, contiguous ordered polygon IDs, finite vertices,
symmetric adjacency, and exact derived surface spans before exposing a mesh; it never regenerates
stable IDs during loading. `--extract-world --bake-navmesh` performs this terrain-NavMesh bake
offline for each extracted region and writes `<world>.navmesh.json` next to its world map. The
optional `--navmesh-map <path>` loads one validated artifact for telemetry and records its content
digest in session metadata.

US-054 receives `player_navmesh_polygon_id` and local slope from that optional provider only when a
snapshot has a finite live-GPS position. At target selection, the camera-state projection unprojects
the detected bounding box's bottom centre and accepts world coordinates, candidate polygon IDs, and
path distances only after its ray intersects the loaded NavMesh. Missing artifacts/positions,
minimap fallback, unavailable camera state, and ray misses remain JSON `null`; no screen-space
estimate is represented as a world observation.

This remains an offline foundation rather than an active movement path. No controller loads or
automatically chooses a baked mesh for routing, and US-052 terrain A*, vector visibility routing,
and learned navigation remain the live fallbacks. The new modules use client files only and do not
read or write process memory, dispatch input, mutate archives, or widen the existing safety paths.
The full automated gate passed on 2026-08-20 at 797 passed, 2 skipped, and 91.35% coverage. Real
client-asset reconstruction and foregrounded Windows/client traversal—including live Funnel
collision confirmation—remain manual checks, not automated claims.

## Asynchronous farming telemetry and offline dataset export (US-054, completed)

US-054 introduces `flyff_bot.features.telemetry` as a write-only observation sidecar to the farming
loop. `TelemetryRecorder` is owned by `FarmingOrchestrator`: it queues a schema-v1 session header
at start, one compact numerical snapshot per newly observed frame, complete visible-candidate
matrices at target selection, and measured combat/key-dispatch/verified-kill records. The tick
thread never waits for serialization or storage. `JsonlTelemetryWorker` owns a bounded
`queue.Queue` and one daemon persistence thread, writes append-only envelopes under
`data/telemetry/<area_id>/<UTC-date>/session_<session_id>.jsonl`, and drops records under pressure
instead of delaying farming. Narrow filesystem, JSON, and SQLite failures are counted and contained
inside that worker; they do not escape into the orchestrator or Qt event loop.

The same worker optionally mirrors each envelope into `SqliteTelemetryStore`
(`data/telemetry.sqlite3`) using a short-lived transactional connection. It keeps a common
timestamped event stream and query-oriented tables/indexes for session headers, target decisions,
navigation episodes, combat episodes, stall events, and kill cycles. The separate
`TelemetryDatasetExporter` reads that normalized SQLite stream and the `--export-telemetry` CLI
action writes zstd-compressed, dataframe-compatible `target_decisions.parquet`,
`navigation_trajectories.parquet`, and `kill_cycles.parquet` under `data/datasets/rl/`. JSONL,
SQLite, and generated datasets remain local git-ignored operational data, not source evidence.

At session start, `FarmingOrchestrator` supplies configured vector spawn-zone metadata and the CLI
supplies the readable client digest, bot version, model paths, and optional NavMesh artifact digest.
The recorder emits one snapshot for each newly observed live frame. It derives player polygon and
slope only from finite live GPS plus a loaded NavMesh; it preserves `null` otherwise. The active
pathing lifecycle now opens/replans terrain-route episodes, adds only live-GPS samples, records
stalls and confirmed evasions, and finalizes an outcome on arrival, target selection, or close.
The combat controller supplies the active lockout decision and dispatch-confirmed attack actions;
verified kills emit a reset-at-kill four-part decision/navigation/combat/idle timing decomposition.
Their target-decision timestamp deterministically joins each verified cycle's reward and kill flag
to the exported target-decision rows.

For a target decision, `TelemetryRecorder` projects each detection's bottom centre with the measured
`CameraState` and raycasts it against the optional loaded NavMesh. A successful hit produces the
candidate's world coordinate, relative distance/elevation, polygon, and mesh path distance; no
camera, GPS, mesh, or intersection remains explicit JSON `null`. This makes missing geometry
observable rather than fabricated while keeping the projection read-only. The full automated
repository gate passed on 2026-08-20 at 800 passed, 2 skipped, and 91.30% coverage. The Windows
live-client farming and direct Parquet-load walkthroughs remain outstanding and are not implied by
the automated result.

## Perception-side mob world positioning and chunked NavMesh raycasting (US-057, completed)

US-057 makes one measured estimate of where a detection stands the shared input of targeting,
telemetry, and the inspector. `perception.mob_world_position` takes each detection's bottom-centre
ground contact point — never the box centre, whose parallax places a mob behind or below its actual
position — unprojects it through the US-056 `CameraState`, and intersects the resulting world ray
with the baked NavMesh. An `EstimatedMobWorldPosition` carries the surface point, polygon ID,
distance to the player, ray distance, class name, and confidence; a missing camera, GPS, mesh, or
ray hit yields `None` rather than a fabricated coordinate.

`navigation.raycast` owns the project's single Moller-Trumbore implementation together with a
horizontal chunk index built from each walkable triangle's X/Z coverage. `BakedNavMesh.raycast()`
builds that index once per mesh and walks only the cells a ray actually crosses (Amanatides and
Woo), returning as soon as the nearest hit found so far precedes the next cell boundary. That
ordering is what makes a bridge deck win over the terrain it occludes, and it keeps a batch of
twenty detections against a 512-polygon mesh at roughly 0.5-0.7 ms instead of a full-mesh scan.

`PerceptionPipeline.attach_world_geometry` binds the pathing controller — which owns the polled
camera, live GPS, and loaded mesh — so one tick publishes `WorldState.visible_mobs` already carrying
world coordinates and polygon IDs. The composition roots (`cli` and the desktop app) perform that
wiring; without a feed the pipeline keeps reporting purely client-space detections. `PathingController`
then reuses the measurement for reachability, path distance, and leash instead of casting a second
ray, and US-058 telemetry projects only the candidates the pipeline could not resolve. Exported
`target_decisions.parquet` names this geometry `estimated_mob_x`, `estimated_mob_y`,
`estimated_mob_z`, and `estimated_mob_polygon_id`; the raw JSONL event schema is unchanged.

The automated repository gate passed on 2026-08-20 at 823 tests passed, 3 skipped, and 90.77%
coverage. The foregrounded Windows walkthrough against a live client on open ground and on bridges
remains unrun and is not implied by the automated result.

## NavMesh-aware targeting, active Funnel approach, and telemetry integration (US-058, completed)

US-058 makes the baked NavMesh a shared, read-only enrichment provider for targeting and telemetry.
Targeting filters candidates by reachability, path-distance leash, and lockout state, then ranks valid
candidates by shortest path distance before using viewport distance as a lower-priority tie-breaker.
A raycast miss remains an explicitly unprojected candidate and uses the existing 2D selection fallback.

The first finite live GPS sample establishes the session leash anchor. This runtime anchor is distinct
from the operator-configured teleport spawn anchor: the latter serves recovery/reset destinations,
while the former bounds target selection for the current run. With mesh and camera state available,
the controller follows 3D Funnel waypoints; heading and forward pulses use the existing foreground-
and emergency-stop-guarded dispatcher. Missing NavMesh or camera state preserves 2D leash/selection
and direct client click-to-move with stall recovery.

The telemetry sidecar consumes the same measured candidate enrichment and records direct numerical
world coordinates, relative distance/elevation, polygon IDs, path distance, lockout state, planned
Funnel waypoints, live GPS trajectories, path metrics, stalls/evasions, and decomposed kill timings.
JSONL and SQLite retain these fields, while `--export-telemetry` exposes them in target-decision,
navigation-trajectory, and kill-cycle Parquet tables. `PathInspectorWidget` renders candidate markers,
the active Funnel polyline, and the episode GPS trail as an optional diagnostic view decoupled from
control. Missing measurements remain explicit `null`.

The automated repository gate passed on 2026-08-20 at 806 tests passed, 2 skipped, and 90.60% coverage.
The foregrounded Windows/client walkthrough for reachability, Funnel traversal, telemetry files, and
inspector rendering remains unrun and is not implied by the automated result.

## Fingerprinted camera state and projection reads (US-056, completed)

`LiveCameraReader` performs foreground-gated, read-only process reads only after resolving an exact
SHA-256 `neuz.exe` profile. The profile separates the camera pointer RVA and pointer-relative eye,
view, and look-at offsets from the independent module-relative projection-matrix RVA. The supported
x86 and x64 addresses are grounded in the [2026-08-20 static analysis](../sources/2026-08-20-entropia-camera-static-analysis.md);
the reader does not scan or dump process memory and returns typed errors with no fabricated state for
unknown builds, unavailable handles, background windows, malformed reads, or invalid profiles.

The camera snapshot uses the verified row-major D3DX matrices. View-projection multiplication and
inverse-matrix unprojection produce unit world rays using Direct3D's `[0, 1]` depth range. Effective
eye position comes from the inverse View Matrix (therefore retaining transient camera shake), while
pitch, yaw, vertical FOV, and distance are derived from the forward vector, projection matrix, and
look-at target rather than unverified scalar fields. The implementation is covered by synthetic
memory, matrix, profile, lifecycle, and UI tests; the full automated gate passed at 792 tests passed,
2 skipped, and 91.48% coverage.

Static analysis does not establish live `ReadProcessMemory` latency or client behavior. A foregrounded
Windows walkthrough remains open for camera rotation, zoom, viewport resize, pitch/yaw sign and
matrix tracking, latency, and recovery after restart or minimize. Those checks must not be inferred
from the automated gate.

## Pure Authoritative Navigation, Legacy Removal, and Multi-Zone Selection (US-059, completed)

All legacy navigation fallbacks—including heuristic minimap odometry (`MinimapOdometer`), dead reckoning
key tracking (`MovementTracker`), 2D heatmap cell tracking (`SpatialMap`, `RoutePlanner`), and legacy
minimap JSON profiles—have been completely purged from the codebase.

The navigation subsystem operates strictly on:
1. Exact client archive extraction (`flyff_bot.features.navigation.world_extractor` / `BakedNavMesh`)
2. Read-only live GPS pointer reads (`LivePositionReader`)
3. Read-only live camera matrix reads (`LiveCameraReader`)
4. Authoritative 3D Funnel pathfinding (`PathingController`)
5. Multi-zone sequencing and preferred camp routing (`VectorZoneNavigator`)

**Invariant**: If live GPS is unavailable, unverified, or returns a read error, navigation transitions
immediately to `PathingMode.BLOCKED` / `FarmingMode.PAUSED` without dispatching movement commands.
`PositionSource` therefore names only `LIVE` and `UNAVAILABLE`; there is no second source to fall
back to. A GPS pause is not latched: `FarmingOrchestrator` resumes searching once the coordinate
read recovers, while an operator's manual pause stays latched.

**Multi-zone selection.** `WorldDataDialog` lists a map's spawn camps as checkable entries and arms
every checked one as `VectorNavigationRequest.active_zones`, with the first as the anchor. The
navigator hands the session on in two ways: `record_kill` advances the zone index when a monster's
quota completes, and `PathingController.completed_zone_sweeps` counts full patrol laps of the active
camp that produced no confirmed kill, which the orchestrator turns into a hand-over after
`PATROL_SWEEPS_BEFORE_ZONE_CHANGE` laps. A selection of a single camp has nowhere to advance to and
stays bound rather than re-planning the route it is already following.

The automated test gate passed on 2026-08-20 with 608 passed tests, 2 skipped, and 88.77% coverage.

## Keyed client archives and goal-driven quest farming (US-061, completed)

The client ships two archive generations behind the same `.hdr` / `.one` extensions. US-052 read
the name-keyed one and reported the other as `UNSUPPORTED_ARCHIVE_INDEX`; every quest file lives in
that second, *keyed* generation, together with 25 world regions. The
[2026-08-21 static analysis](../sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md)
establishes its layout, and `navigation.client_archive` now reads it alongside the original:

- A keyed index record opens with `int32 -1`, stores the entry's start negated, and states a size
  that excludes a fixed 10-byte region header, so a file's true length is `size + 10`.
- The 64-character identity is `sha256("m1k3d3RS945TI!" + name.lower())`, which makes a keyed
  archive **name-addressable** instead of requiring the US-052 known-plaintext-prefix search.
- The payload keystream advances with the byte position and is seeded from the file name's adjacent
  character XOR plus the file's own length:
  `stored[i] = swap_nibbles(plain[i]) ^ ((length - 1 + (name[i % n] ^ name[(i+1) % n]) + i) & 0xFF)`.

Reading stays strictly offline and non-destructive under ADR-005: no game process is opened and no
client file is written. The decoder was verified by byte-exact round-trip against the 55 loose files
that still match their packed entry; a further 20 loose files decode into valid headers but differ
in content, which is what the client's loose-file preference implies for a patched file.

`flyff_bot.features.quests` is the feature this unlocks. `extraction` unpacks the five
`propQuest*.inc` scripts, `propMover.txt`, `Spec_Item.txt`, and one language's `*.txt.txt`
catalogs; `client_tables` resolves `MI_*` / `II_*` symbols and `IDS_*` references into localized
labels; `script_parser` reads the quest grammar into typed models. A bare-number script block is a
quest *group* heading rather than a quest, and its title becomes the quest's area label - which for
this client reads as `Flaris`, `Saintmorning`, and so on, so it doubles as the zone filter. Only the
calls a session can act on are modelled: kill and collect conditions with their declared drop
sources, begin-level window, objective text, and reward summary. Dialogue, party rules, and script
hooks are skipped rather than half-modelled. `persistence` writes schema version 1 to
`data/quests/quests.json`, which is git-ignored local operational data like the extracted world
maps, and `uv run python -m flyff_bot --extract-quests` drives the whole pass offline. Against the
operator's own installation it produced 1,434 quests, 563 of them farmable, with no diagnostics.

`quests.goals` binds a quest to the ground. `QuestGoalResolver` matches each objective's monster to
an extracted spawn zone by display name, by the numeric identifier when a quest states one directly,
and - where several zones hold the same monster - by proximity to the coordinates the quest script
itself names. A collection objective is farmed as kills of its declared drop sources, because a
verified kill is the smallest unit of progress a session can observe without a loot feed attached
(US-025). Missing geometry is reported rather than guessed: `NO_FARMABLE_OBJECTIVE`, `NO_WORLD_MAP`,
and `NO_SPAWN_ZONE` are typed issues the dashboard renders as localized sentences.

`QuestFarmingQueue` walks the operator's selection one quest at a time, counting only kills the
session could attribute to a monster class. `FarmingOrchestrator` takes an optional queue: a
verified kill that completes the active quest binds the next one, replacing the kill quotas, the
combat class filter, and the navigator's camp selection, then re-attaching the navigator so the
pathing controller drops its current route and plans towards the new area. When the queue runs out,
the session reaches `FarmingMode.COMPLETED` with the reason `quest_queue`. A session without a queue
is unchanged and still completes on its own quotas or item goal.

The quests feature deliberately does not import the automation package: it states what a quest needs
as `(monster, count)` pairs, and the orchestrator turns those into the `KillGoalConfig` it owns.
The orchestrator's own quest imports are type-only, because the quests feature reaches the
navigation package, which reaches back into automation. `QuestObjectiveProgress` therefore lives in
`quests.models` beside the other dependency-free value objects, so `ui.dashboard` can carry it.

`QuestGoalPanel` is the operator surface, on its own `Quest Goals` tab between Vitals & Buffs and
Navigation & World. It filters the loaded database by free text, category, area, and character
level, queues quests in the order they are checked, and renders the active quest and its objective
counters from the same `DashboardUpdate` that feeds every other panel. All 563 farmable quests of
this client render in about 30 ms and re-filter in under 10 ms, so the list is rebuilt on the Qt
thread without a worker.

The automated repository gate passed on 2026-08-21 at 674 passed, 2 skipped, and 89.22% coverage,
and the extractor was run against the operator's own unmodified Entropia installation. The
foregrounded Windows walkthrough - selecting quests, watching autonomous navigation to the resolved
camps, and confirming the hand-over to the next quest in a live `neuz.exe` session - remains unrun
and is not implied by the automated result.

## Offline farming value models from recorded telemetry (US-066, completed)

US-066 adds `flyff_bot.features.ml`, a second offline consumer of the US-054 datasets beside the
YOLO training adapter. It reads the three exported Parquet tables and never opens a window, sends
input, or reads process memory; `python -m flyff_bot.features.ml.train_farming_value` runs with no
game client present.

`dataset.py` joins one supervised sample per *executed* target decision. A kill cycle is linked to
its decision through the `target_decision_timestamp_ns` US-054 already records, and the navigation
episode that started between those two timestamps supplies the corridor and trajectory geometry.
Candidates the bot did not select never become samples; they contribute only observed context
counts, so the off-policy dataset carries no invented counterfactual reward. Splitting moves whole
sessions into the holdout, falling back to a contiguous temporal tail when only one session exists,
so a session is never on both sides of the boundary.

Features and labels stay strictly observational. Anything the session did not measure is `None`,
becomes `NaN` in the model matrix, and reaches a model as the training-set median plus an explicit
`<feature>__is_missing` indicator column, so an imputed value stays distinguishable from a
measurement. Follow-up windows reaching past the end of a session are treated as right-censored and
stay unknown rather than being recorded as zero kills; recovery time exists only for cycles where a
stall was actually observed. Corridor clearance is not in the US-054 schema, so the corridor is
described by length, waypoint count, turn angles, and detour ratio instead of a fabricated width.

The five heads - travel time, stuck risk, recovery time, kill time, and follow-up value - are
regularized linear models fitted on numpy alone: ridge regression, plus an L2-penalized logistic
classifier via Newton iterations for stuck risk. Each is benchmarked on holdout sessions against a
heuristic reference predictor: a least-squares scaling of the single measurement the deterministic
controller would have used, or the training mean where it has no such rule. Heads without enough
observed labels are reported as untrained instead of being fitted to noise. `cost.py` combines the
five predictions into the weighted expected farming cost with operator-configurable component
weights.

Each head exports to a self-contained ONNX graph (`IsNaN` -> `Where` -> `Cast` -> `Concat` ->
`Gemm`, closed by `Sigmoid` for the classifier) that takes the raw `NaN`-carrying feature matrix, so
a consumer cannot disagree with the training-time preparation. The ONNX writer is the only reason
for the new optional `ml` dependency; live inference stays on the OpenCV DNN runtime the app already
ships. `models/farming_value/<version>/metadata.json` records the dataset digest, session
identifiers, split strategy, feature and label schema, follow-up value definition, cost weights,
per-head model and baseline metrics, the checked-out git commit, and the client build hashes read
from the telemetry database.

Importing the telemetry package first used to raise a circular `ImportError` through `navigation`
and `automation`, which the new offline entry point would have hit on every run.
`automation/orchestrator.py` now takes `CombatVerificationSource` from `telemetry.models` and
`TelemetryRecorder` under `TYPE_CHECKING`, and `telemetry/__init__.py` no longer re-exports
`geometry`, which is shared with the navigation layer telemetry itself depends on. Both packages
keep their behaviour; only the import direction was corrected.

The automated repository gate passed on 2026-08-21 at 719 passed, 2 skipped, and 89.70% coverage.
Running the trainer on a real recorded Windows farming session and inspecting the produced
artifacts remains outstanding and is not implied by the automated result.
## Combat class profiles and responsive direct targeting (US-060, completed)

`CombatClassProfile` provides melee, ranged, and custom engagement profiles with defaults of
3.0 and 15.0 world units. `FarmingOrchestrator.configure_combat_class()` and
`configure_engagement_distance()` apply the operator's choice live to both orchestration and
`PathingController.update_engagement_distance()`. A selected measured target is clicked directly
when it is already inside that distance; a melee target is also clicked directly when the
NavMesh route is one straight segment. Only a longer multi-waypoint route enters
`FarmingMode.APPROACHING`. Unmeasured, unreachable, or outside-leash candidates retain the
existing safe fallbacks.

The corpse lockout now defaults to one second at 15 pixels so dense packs remain selectable,
while failed acquisition still suppresses immediate re-clicks. Post-kill reconciliation resets the
finished combat engagement, returns to searching, and evaluates candidates in the same tick. The
combat dashboard exposes a localized class dropdown plus engagement-distance control wired
dynamically through the app boundary.
Focus loss, pause, and emergency stop continue to abort all dispatch paths before input.

A regression now proves that post-kill reconciliation selects and clicks the next candidate in the
same tick. Regression coverage also proves the ranged preset, straight versus multi-waypoint route
handling, profile/custom-distance propagation, and dashboard signal wiring. The 3.0 / 15.0 unit
presets remain operator defaults rather than measured Entropia client ranges, and live Windows
validation of actual attack-range selection remains required.

## Unified tactical policy boundary (US-067, completed)

The TacticalPolicy layer is pure decision logic: it receives an immutable WorldState, a
deterministic candidate/action mask, and optional versioned features, then returns one typed
TacticalAction or no action. It never dispatches input. Alive/recognition, spatial-lockout,
leash, NavMesh reachability, and valid 3D-position predicates are applied before policy choice;
foreground checks, emergency stop (Escape/END), stall recovery, route planning, and guarded
Win32 execution remain downstream and independent of policy selection.

HeuristicPolicy preserves the deterministic targeting baseline. LearnedPolicy loads the
US-066 five-head ONNX set with schema-versioned metadata and ranks eligible candidates by
expected farming cost using cached in-memory sessions. Missing/incompatible models, malformed
features, NaN predictions, exceptions, no valid action, or exceeding the 5 ms budget are handled
by PolicyRunner through immediate heuristic fallback; runtime modes are HEURISTIC,
ML_SHADOW (record learned intent only), and ML_ACTIVE (execute learned intent when legal).
This action vocabulary leaves room for US-068 sequences, US-069 corridor preferences, and
US-071/073 RL policies without moving safety into the policy layer.

## Offline tactical RL environment (US-071, completed)

`features.rl` formulates recorded tactical experience as an offline MDP. A typed observation
combines normalized kinematics, vitals and buff cooldowns, NavMesh context, a bounded candidate
matrix, operational state, and quest progress. The stable seven-action catalog maps target,
navigate, attack-point, corridor, object/NPC interaction, and wait intents to discrete indices; it
reuses the US-067 action payloads and contains no raw key, scan-code, or click contract.
`build_action_mask()` deterministically disables dead, locked-out, unreachable, out-of-leash, and
missing-world-position candidates plus invalid destinations, corridors, and interactions. The
versioned `RewardEngine` computes verified kills, quest-step deltas, objective completion, travel,
idle, stuck, recovery, and failed-action costs from observed facts only.

`TelemetryTransitionExporter` correlates snapshots, selected decisions, and linked kill cycles into
schema-versioned `(observation, action, reward, next_observation, action_mask, terminated)` Parquet
batches with deterministic provenance. `TacticalRlEnvironment` exposes those transitions through a
Gymnasium-compatible reset/step shape for external training frameworks. Every path is offline and
read-only: no RL component dispatches input, touches live control, expands process access, or
performs online exploration. Automated coverage proves state bounds, masks, rewards, Parquet export,
and masked-action behavior. Real telemetry export and training remain operator validation.

The automated gate passed on 2026-08-24 at 806 passed, 5 skipped, and 88.14% coverage. Live
Windows/client validation remains outstanding.

## Rolling-horizon multi-target lookahead (US-068, completed)

`RollingHorizonPlanner` extends the learned US-066 policy with bounded acyclic beam search over the
deterministic eligible mask. It evaluates horizons of two to four steps and beam widths of one to
five, accumulates travel, kill, stuck-risk recovery, and follow-up value through the same expected
farming-cost model, and commits only the first candidate. `TargetAction.expected_cost` carries the
sequence cost; `provisional_sequence` and `last_sequence_cost` expose the remaining plan as advisory
diagnostics only. Every orchestration cycle rebuilds candidates from a fresh perception snapshot,
which makes death, despawn, new detections, lockout changes, stalls, and selection timeout natural
receding-horizon replanning triggers. Missing features, no valid sequence, model faults, or the
existing 5 ms deadline immediately use `PolicyRunner`'s heuristic fallback.

The planner performs no input dispatch, reachability bypass, memory access, or persistent route
commitment. Automated coverage includes sequence validity, first-target commitment, per-snapshot
replanning, fallback behavior, and a synthetic twenty-candidate timing check; live dense-spawn
Windows validation remains outstanding.

## Experience-weighted NavMesh routing (US-069, completed)

`navigation.empirical_routing` adds an immutable, schema-versioned empirical cost index beside the
baked NavMesh artifact (`<world>.empirical.json`). The index records per-polygon and directed edge
traversal counts, observed travel duration, stall counts, stuck probability, mean recovery time, and
mean segment distance. Its payload digest is validated on load and its stored SHA-256 must exactly
match `NavMeshArtifact.content_digest`, so evidence is never applied to regenerated geometry.

`telemetry.navmesh_correlation` maps consecutive live GPS samples to stable polygon IDs, validates
that transitions are present in the unchanged mesh adjacency, and aggregates mapped segments into
the index. Trajectory schema v2 now carries each sample's polygon ID and sampled stall state; Parquet
export exposes these as `navmesh_polygon_id` and `is_stalled`. Samples without mesh attribution or
with non-adjacent IDs are excluded rather than guessed.

`BakedNavMesh.find_path()` now evaluates A* edges with configurable empirical weights while funnel
string-pulling remains geometric. The default blend is 0.5 nominal geometry and 0.5 empirical cost.
Sparse edges scale confidence by sample count toward geometric cost, so unobserved corridors remain
fully reachable and penalties cannot remove topology. Tests cover open-detour preference,
digest/integrity rejection, sparse fallback, reachability preservation, localized diagnostics, and
per-edge lookup below 0.5 ms with route generation below 2 ms in synthetic fixtures.

## Learned attack points and local waypoint optimization (US-070, completed)

`navigation.attack_point_planner` adds deterministic attack-point sampling for active target
approaches. Melee samples the 2.5–3.5 unit engagement annulus and ranged samples 12–15 units; both
rings are filtered through a strict X/Z containment query that uses interpolated surface height and
the baked walkability/slope rules instead of nearest-surface projection. Candidates are scored by
straight approach distance, bounded local corridor clearance, turn error to target, and weighted
distance to anticipated follow-up positions, then validated with one Funnel route before adoption.
The existing direct-click hand-off remains at its configured engagement distance.

## Offline tactical simulator (US-072, completed)

`features.simulator` adds a seeded, in-memory tactical simulator over extracted world maps and
spawn zones. `FarmingSimulator` models fixed-tick movement, heading turn time, terrain height,
spawn capacity and respawn timing, log-normal combat duration, stochastic stall recovery, and the
four US-072 objective kinds. It emits typed RL observations plus aggregate KPM, travel, combat,
recovery, idle, distance, and stuck metrics.

`SimulatorGymEnvironment` exposes reset/step/close and action masks without requiring Gymnasium as
a runtime dependency. Calibration fits baselines from recorded kill cycles and rejects aggregate
KPM or navigation-time drift beyond a configurable fraction. The simulator is strictly offline:
it has no client-process, memory-read, input-dispatch, rendering, or network boundary. It validates
simulation behavior only; live Windows/client performance still requires separate field checks.

BUG-032 fixed the dynamics that made simulated throughput unreachable in the client. The invariants
the simulator now holds are:

- One tick is a budget of simulated seconds partitioned into recovery, travel (turning included),
  combat, and idle, so `elapsed_seconds` equals the sum of those buckets exactly.
- Only travel moves the player. Combat is a multi-tick engagement that spends the sampled duration
  from the same clock, and a monster out of engagement range must be walked to first.
- `step()` rejects any action the current mask forbids with `IllegalSimulatorAction`. A pending
  stall recovery blocks every action but `WAIT`.
- All extracted spawn zones populate and respawn. Candidate visibility is an explicit radius over
  live monsters; dead monsters are never offered as candidates.
- Travel follows a `VectorRoutePlanner` corridor over the extracted obstacle geometry, so a blocked
  straight line becomes a detour rather than a wall-crossing.
- An episode without objectives is a valid continuing farming task and ends by truncation only.
- The reward is `RewardEngine` under the versioned `RewardConfig` shared with the telemetry
  exporter and recorder; the simulator holds no weights of its own.

`PathingController` plans an attack point when NavMesh targeting starts and retains hysteresis:
periodic replans preserve the route until the measured target has moved more than two world units.
Timeout, disconnected geometry, or no contained candidate returns immediately to the unchanged
direct-Funnel path, so reachability and emergency/stall behavior stay intact. Automated tests cover
strict containment, class bands, scoring, timeout fallback, dynamic movement, and synthetic
sub-millisecond planning; live Windows/client positioning remains outstanding.

## Client dungeon data and live cooldown extraction (US-063, completed)

`flyff_bot.features.dungeons` adds a second keyed-archive consumer beside quests. The offline CLI
pass (`--extract-dungeons`) reads `PartyDungeon.lua`, resolves world identifiers and localized
labels from the dungeon text table, and writes only complete declarations to schema-versioned
`data/dungeons/dungeons.json`. `SetCoolTime(MIN(minutes))` is interpreted as minutes; a declaration
without verifiable level or cooldown fields is skipped rather than defaulted. No client file is
written or modified.

A client that packs no dungeon script is not a client without dungeons (BUG-036). Extraction then
falls back to the ranking table `DungeonRanking.inc`, which declares one numeric world identifier
and label per reward block; the leading reset period and commented-out blocks are not declarations.
That table carries no level range or cooldown, so those `DungeonDefinition` fields are optional and
stay undeclared (`None`) instead of being defaulted. A client packing neither source reports both
`MISSING_DUNGEON_SCRIPT` and `MISSING_DUNGEON_RANKING`. The real Entropia install yields 32
dungeons this way.

Live cooldowns use the existing documented read-only process boundary and require the client window to
be foregrounded before attachment or any fixed read. A SHA-256 fingerprint in
`data/config/client_dungeon_profiles.json` selects an exact module RVA, pointer width, and container
shape. `LiveDungeonCooldownReader` opens, fingerprints, resolves the module base, and validates that
profile once in `_ensure_open()`, then retains only the read-only handle and those verified values
across bounded polls; malformed reads close it for recovery on a later foregrounded poll. Each
successful poll performs one fixed pointer read plus one bounded read and emits immutable snapshots
with `READY`, `ON_COOLDOWN`, `ENTRY_LIMIT_REACHED`, or `UNKNOWN`. Missing/malformed profiles,
background windows, unavailable processes, and failed reads produce typed `UNCONFIGURED_PROFILE`,
`WINDOW_NOT_FOREGROUND`, `PROCESS_UNAVAILABLE`, or `HANDLE_LOST` diagnostics instead of inferred
addresses.

`DungeonContainerKind` supports two contiguous per-record containers (`fixed_array`,
`begin_end_span`) plus `global_lockout_timestamp`. The shipped Entropia build
`8079c88f…dada5` keeps per-dungeon cooldown rows only in transient `std::vector` members owned by the
cooldown windows, with no fingerprint anchor, so its profile binds the one persistent bounded read
the dungeon UI itself performs: the account-wide daily lockout `__time64_t` at `player + 0x2678`
(`now < *(player + 0x2678)` -> "Locked until 03:00 AM"). `GlobalDungeonLockout` profiles carry no
record fields; while the lockout is in the future the reader maps that one end time onto every known
dungeon, and reports `UNKNOWN` for all of them when it is zero or past rather than an invented
`READY` ([ADR-011](../decisions/ADR-011-dungeon-cooldowns-are-not-fingerprint-bindable-only-the-account-lockout-is.md)).
The automated profiler proves this offset by scanning the `CWndDungeonCooldownList` /
`CWndDungeonCooldownQuick` vtables for the fixed `mov rcx,[rip+player]; call <time-member helper>`
shape; `ClientBinaryProfiler.profile()` runs to completion for this digest. Its camera, dungeon,
and player-stat outputs are RTTI- and prologue-anchored and match the committed `data/config/`
registries; its `position_offset` output is **not** trustworthy — `_discover_player` byte-matches
`48 05` rather than decoding an instruction and emits a false positive (`184`) for this build,
where the verified player coordinate is `CMover + 0x188` (`PLAYER_POSITION_OFFSET`). The setup
wizard's `persist_profile_bundle` call installs that value into the `.gitignore`d
`data/navigation/client_profiles.json` without a correctness check, so a wrong GPS offset can be
installed silently on operator setup; the fingerprinted position and world-id profiles have no
committed home under `data/config/` alongside camera / dungeon / player-stats. See
[BUG-039](../bugs/BUG-039-generated-position-offset-false-positive-and-empty-position-world-id-registries.md).
The `CWndStatus` gauge-float path for vital percentages was investigated and closed as not
bounded-readable on this build
([US-094](../user-stories/completed/US-094-cwndstatus-gauge-vital-memory-path.md),
[ADR-010](../decisions/ADR-010-client-derived-vital-maxima-are-not-runtime-resolvable.md));
vital percentages stay on `PlayerVitalsReader`.

The dashboard's Dungeons & Cooldowns tab renders extracted names, level ranges, localized status,
entry counts, and zero-padded `HH:MM:SS` timers from dashboard snapshots. `MainWindow` binds the
database during `reload_client_data()`, and the panel keeps that database apart from the live poll so
its status line names the actual gap rather than always asking for extraction (BUG-036): no readable
database on disk, an extracted database declaring no dungeons, or a loaded database whose rows cannot
be enriched because the client is not connected — the last case still renders the extracted rows with
`UNKNOWN` status. Automated coverage includes
synthetic archive extraction/persistence, mocked read-only memory buffers, status precedence, graceful
degradation, panel rendering/retranslation, and locale synchronization. On this POSIX host the suite
passes after excluding two unrelated pre-existing Python/POSIX environment failures in Windows struct
sizing and OCR decoding.

## Initial setup and unified client extraction (US-078, completed)

`flyff_bot.features.setup` provides the first-run detector and sequential extraction orchestrator.
The dashboard opens a localized modal wizard when any required offline artifact is absent, and an
Initial Setup menu action reopens it at any time. The operator selects the Entropia folder; setup
validates `neuz.exe` plus `Data/`, then runs mover/static-item discovery, quests with NPC locations,
dungeons, all discovered world regions, and executable fingerprinting on a cancellable worker thread.
Progress, stage detail, counts, warnings, and skipped tables are marshalled to Qt signals so the UI
remains responsive.

Player-stat profile installation is deliberately conservative: the wizard hashes `neuz.exe`, checks
the PE machine type, and installs only a validated registry entry whose SHA-256 exactly matches that
binary. Missing or malformed proven profiles are typed diagnostics; no offset is inferred. This
preserves ADR-006 and the empty shipped player-stat registry until controlled static-analysis and
live evidence supplies real offsets.

## Fingerprinted player-stat snapshots (US-076)

`flyff_bot.features.player_stats` adds a second stage for authoritative vitals: `PerceptionPipeline`
now accepts an optional `LivePlayerStatsReader`. When that provider is present it polls a frozen
`ClientPlayerStatsSnapshot`, copies only profile-declared HP/MP/FP values into the existing
`PlayerVitals` contract when all three are present and valid, and stores the complete snapshot on
`WorldState.player_stats_snapshot`. It no longer constructs or invokes `PlayerVitalsReader`; target,
monster-stats, loot, and mob OCR are unchanged. Missing or partial client stats therefore retain the
previous vitals instead of falling back to screen recognition.

The reader reuses the documented read-only Win32 boundary from `LivePositionReader`
(`PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION`) and adds foreground gating like
`LiveCameraReader`. It hashes the executable, resolves an exact lowercase SHA-256 profile before any
field read, reads one fixed pointer-width pointer plus one bounded structure span, validates every
value against finite profile bounds, closes the handle promptly on failure, throttles repeated polls,
and emits one diagnostic per error transition. Profiles live in
`data/config/client_player_stats_profiles.json`; malformed JSON, duplicate fingerprints, invalid
pointer widths, overlapping ranges, unknown primitive types, or out-of-range bounds fail before any
process handle opens.
Incomplete structure reads and out-of-bounds/non-finite decoded values are reported as malformed
reads; a non-positive player pointer is reported separately as an invalid pointer. An unavailable
snapshot retains the field names from the most recent complete snapshot so repeated failures remain
diagnostically stable. Profile-declared signed or floating-point fields may legitimately be negative;
the profile bounds remain the authority for value validity.
Automated synthetic-process coverage validates snapshots, profile rejection, diagnostics, handle
lifecycle, throttling, recovery, foreground loss, and OCR-free perception integration. Live
x86/x64 offset verification against a running client remains separate operator validation.

No verified player-stat field offsets exist in repository evidence today. The shipped registry is
therefore intentionally empty: production sessions receive typed unavailable snapshots rather than
guessed addresses or fabricated values. Adding x86/x64 profiles requires new static-analysis evidence
and controlled in-game verification; until then this story cannot be marked complete.

## Central live-state readiness (US-077, completed)

`LiveReadinessGate` is the single readiness boundary for autonomous capabilities. The orchestrator
registers foreground, perception, GPS, camera, player-stat, and dungeon providers with freshness
limits and declares capability-specific dependencies. Each tick normalizes provider results into
typed samples, evaluates freshness and clock continuity, and publishes one immutable
`LiveReadinessStatus` containing every failure plus a deterministic primary reason.

The gate pauses only capabilities whose dependencies are unhealthy; session-dispatching capabilities
also set `action_blocked`, causing the orchestrator to clear armed actions and send no movement,
combat, interaction, teleport, or skill input until recovery. Foreground checks and emergency teardown
remain independent final guards. END/Escape and shutdown latch terminal cancellation, close live
providers, and prevent later samples from reopening the session. Dashboard rows expose localized
source health, age, diagnostic code, and consequence; telemetry and offline RL observations retain
the aggregate state, failed source codes, sample ages, and action-blocked flag.

Automated repository verification passed on 2026-08-25 (883 tests passed, 5 skipped, 88.35% coverage;
Ruff, format, mypy, and locked dependency synchronization passed). Windows/live-client removal and
recovery walkthroughs remain operator validation and were not run for this story.

## Two-tier hierarchical policy (US-073, completed)

`features.policy.hierarchical` separates macro strategic decisions from tactical action selection.
The high-level policy retains a target until a macro-event token changes; the mid-level policy then
chooses only a prevalidated attack point, NavMesh corridor, local destination, or interaction.
`PolicyRunner` validates learned output against deterministic masks and, since BUG-031, reports a
typed fault for invalid, missing, late, NaN, or faulting output instead of substituting
`HeuristicPolicy` (see the closed-loop section below). Movement, combat, stall recovery, foreground,
and emergency-stop safeguards remain outside the learned heads.

`hierarchical_training` runs masked Q-learning against the seeded US-072 simulator, compares KPM
and objective throughput with a paired baseline, and exports distinct digest-checked linear ONNX
heads with metadata. Since BUG-032 it draws training, evaluation, and calibration seeds from three
disjoint blocks (`seed_ranges`), labels the mid-level head from the tactical state rather than from
a relabeling of the strategic action, records the trained action classes per head so
`HierarchicalOnnxPolicy` cannot select an untrained one live, and runs `validate_calibration` over
held-out heuristic rollouts before any artifact is written.
Automated tests cover dispatch, objectives, masking, fallback, export, and a synthetic five-
millisecond inference budget. The 2026-08-25 gate passed at 866 passed, 5 skipped, and 88.30%
coverage. These are offline results; real-client convergence and exact client latency remain
unverified.

## Interactive world-map inspector (US-074, completed)

`WorldMapScene` and `PathInspectorWidget` provide a Qt map over an extracted `WorldVectorMap` and
optional baked NavMesh. Terrain, passability, routes, trajectories, and spawn zones use distinct
layers; transforms support bounded cursor-anchored zoom and right-button panning. Right-drag emits
no camp-selection event and suspends follow mode. Follow mode recenters on finite live position
snapshots while retaining heading; left-click selects the smallest containing zone and hover text
shows available metadata. Terrain, polygons, and zones are frustum-culled before drawing.

Automated Qt tests cover transforms, input semantics, culling, metadata, follow updates,
localization, and a synthetic warm-render budget above 30 FPS. This is not a live map-FPS result:
no Windows/client walkthrough was run, so live GPS convergence and large-region client performance
remain unverified.

## Closed learning loop: trainable experience and servable policies (BUG-031, fixed)

The loop the project is built toward - farm live, record, train offline, evaluate, promote - was
open at both ends. `docs/decisions/ADR-008-closed-learning-loop-invariants.md` records the five
invariants that close it; this section describes where they live.

**Export.** `TelemetryTransitionExporter` groups recorded events by `session_id` first and rebuilds
one transition per decision interval within a session: the snapshot preceding the decision with the
decision's own candidates, the exact parameterized choice, the reward observed until the next
decision, the state at that next decision, both masks, and how the interval ended. `Transition`
carries `session_id`, `episode_index`, and `truncated` alongside `terminated`. A verified kill no
longer terminates an episode; an observed objective completion does, and the last interval of a
recording is truncated. `TelemetryDatasetExporter` keys kill cycles by `(session_id, timestamp)` for
the same reason.

**Actions.** `ParameterizedAction` and `TacticalActionCatalog.encode`/`decode` round-trip every
typed payload - candidate instance, destination, attack point and approach angle, corridor,
interaction target and type, wait duration - so the exported action is no longer a constant
`SELECT_TARGET`. `TacticalActionMask` pairs the discrete mask with a per-candidate mask and
`allows()` rejects one exact parameterized choice. `TargetAction`, `AttackPointAction`, and
`CorridorAction` carry `candidate_index`; `validate_policy_action` and the orchestrator resolve a
selection by that index rather than by an ambiguous detector class identifier or a coordinate
convention.

**Reward.** `interval_reward_event` fills every configured `RewardConfig` component from its own
recorded observation: kill cycles, navigation-episode duration, stall duration, measured evasion
seconds, combat-episode duration for the idle remainder, non-success outcomes for failed actions,
and the new `objective_progress` telemetry event for quest progress and completion. An episode is
attributed to the interval its end falls into, so nothing is rewarded twice.

**Serving.** `FarmingConfig.policy_model_directory` is now writable from the CLI (`--policy-mode`,
`--policy-model-dir`) and from the combat settings panel, and `configure_policy_model_directory`
loads and warms up the artifact while the session is paused. The orchestrator builds
`PolicyContext.feature_matrix` from live candidates through the shared `candidate_feature_row`, so
the trainer and the live policy assemble identical columns; a quantity that is genuinely unobserved
while the target is still being chosen stays missing rather than being fabricated. `PolicyContext`
also carries `LiveObservationState`, and `live_observation` builds the hierarchical observation from
measured position, heading, NavMesh polygon, terrain slope, and remaining route distance instead of
zeroed placeholders. The hierarchical policy is bound to the session's active quest objective.

**Observation encoding.** `ObservationSpace` was 75 columns (`bug031-v1`) at this point and is 86
columns (`us079-v1`) since the goal block was added below. Every optional value is encoded as a
scaled measurement plus an explicit missing indicator, signed quantities keep their sign, and an
unoccupied candidate slot reports all four of its optional columns as missing and the slot as
unusable. This matches the `NaN`-plus-`__is_missing` convention of the supervised value models.
Artifacts trained against an older contract are rejected rather than silently misread.

**Failing closed.** `PolicyRunner` no longer runs `HeuristicPolicy` in place of a learned policy
that failed. It records a typed `PolicyFault` - `model_unavailable`, `no_valid_action`,
`invalid_or_masked_action`, `latency_budget_exceeded`, or `policy_exception` - and returns no
action. The orchestrator halts learned automation, reverting the mode to `HEURISTIC` and pausing an
`ML_ACTIVE` session, and publishes the `PolicyFault` to the dashboard where the combat panel renders
the synchronized German and English diagnostic. An empty candidate set is not a fault: the
deterministic search path continues untouched.

Automated repository verification passed on 2026-08-25 (906 tests passed, 6 skipped, 88.2% coverage;
Ruff, format, mypy, and locked dependency synchronization passed). Windows and live-client
validation - a real recorded session, an artifact trained from it, and its promotion into
`ML_ACTIVE` - remains operator validation and was not run.

## Goal-driven quest execution and the objective bus (US-080, completed)

Until US-080 the quest building blocks existed but nothing stated *which* step a session was on:
the teleporter served emergency recovery only, `HierarchicalObjective` came from a hard-coded
default, and telemetry recorded no quest identity. `flyff_bot.features.quests.objectives` supplies
the missing connective tissue.

`build_goal_sequence` decomposes one `QuestResolution` into ordered, typed `QuestGoal` values -
travel to the accept NPC, accept, travel to and satisfy each objective, travel to the turn-in NPC,
turn in. Each goal states its completion condition (`required_progress`) and the timeout that bounds
it. Only executable steps are emitted: a quest whose accept or turn-in NPC the client never resolved
contributes no goal for it and starts at its first objective.

`QuestGoalSequence` is the objective bus. It owns the active index, the measured progress per goal,
the failure reason, and the world identifier the active goal resolved to travel into. It decides
nothing about the world: the session reports the executor phase through `synchronize`, the measured
kill counts through `apply_progress`, and refusals through `fail`. Its `QuestGoalIdentity` is the
single value the dashboard, the tactical policy and the telemetry sidecar all read. The goal timeout
measures *stalled* progress - recorded progress restarts it - so a long objective never trips it
while a wedged one does.

`navigation.goal_travel.plan_goal_travel` answers whether a goal destination is walked to,
teleported to, or unreachable. A destination in the player's live world and within the configured
walking distance is walked; otherwise the nearest extracted teleporter destination that covers it is
dispatched, and when neither holds the plan refuses explicitly. `TeleporterDispatcher` still owns
the guarded UI sequence and confirms arrival from live client state; a quest teleport only releases
its goal on `CONFIRMED`, and a `FAILED_STANDBY` fails the goal instead of walking on.

`automation.quest_goals` projects the active goal onto the knobs the session turns: an objective
goal narrows the kill quotas, the navigator's preferred zones and the targeting leash to its own
resolved spawn zone, while an NPC goal keeps the whole quest in scope. `PathingController` gained
`set_objective_leash`, which re-anchors the leash away from the start-of-session position.
`hierarchical_objective_for` turns the same goal into the `HierarchicalObjective` that
`PolicyRunner.set_objective` conditions the learned policy on, so a tactical decision is made under
the goal the executor is pursuing.

Telemetry schema version 4 adds `ActiveGoal` to every `WorldSnapshot` and every `TargetDecision`:
quest identity, goal kind, index, count, progress, state, monster, active spawn zone and world
identifier. The Parquet exporter carries the same columns into the target-decision table.

A refused or timed-out goal advances the quest queue when one has a next quest and otherwise pauses
the session for good, per `FarmingConfig.quest_goal_failure_policy`. Foreground verification, the
emergency stop, guarded key release and read-only client access are unchanged and remain outside
every policy.

The 2026-08-26 gate passed at 918 passed, 6 skipped, and 88.88% coverage. This is offline evidence:
the foregrounded Windows walkthrough of one full quest against a live `neuz.exe` - teleport, accept,
farm, return, turn in - remains unrun, so live teleporter coverage of real quest regions and live
arrival timing are unverified.

## One goal-conditioned, versioned decision contract (US-079)

Before this change the name `TacticalAction` meant three unrelated things: a seven-member `IntEnum`
in `features/rl/actions.py`, a four-member `IntEnum` in `features/simulator/engine.py`, and a union
type alias of the payload dataclasses in `features/policy/models.py`. The simulator's private enum
was in truth the *strategic* vocabulary, and its index order matched the exported high-level head's
hand-written `HIGH_LEVEL_ACTION_ORDER = ("target", "navigate", "interact", "wait")` only by
coincidence: nothing prevented one from being reordered without the other.

### One vocabulary module

`features/policy/action_payloads.py` is the single decision contract module and holds four
vocabularies exactly once:

- `StrategicGoalKind` - the macro sub-goal the high-level tier picks. `STRATEGIC_GOAL_ORDER` is its
  wire order, and `strategic_goal_index` / `strategic_goal_at` are the only conversions between a
  goal and its discrete index.
- `TacticalActionKind` - the kind of tactical payload the mid-level tier picks.
- `TacticalAction` - the stable discrete index a tactical payload encodes to, plus
  `TACTICAL_ACTION_COUNT` and `TacticalAction.for_kind`.
- `ObjectiveKind` - what the pursued objective asks for (`farm`, `go_to`, `kill`, `interact`,
  `talk_to_npc`). `OBJECTIVE_KIND_ORDER` is the one-hot column order of the goal block. The
  simulator's former `QuestObjectiveKind` is deleted in favour of it, so an offline quest objective
  and a live quest goal are stated in the same terms.
- `TacticalActionPayload` - the payload union, previously defined a second time as
  `policy.models.TacticalAction`.

`FarmingSimulator` steps on `STRATEGIC_GOAL_ORDER` indices, `HIGH_LEVEL_ACTION_ORDER` is derived
from that order instead of being written out, and `HierarchicalOnnxPolicy` resolves an argmax column
through `strategic_goal_at`. `features/rl/actions.py` keeps only the encoding machinery:
`ParameterizedAction`, `TacticalActionMask`, and `TacticalActionCatalog`.

### The goal-conditioned observation

`ObjectiveState` no longer states only *where* the objective is. It names which objective is being
pursued: its identity, its `ObjectiveKind`, its index inside the quest sequence, the sequence
length, its measured progress against its requirement, and the remaining route distance. The encoder
appends an eleven-column goal block - a stable BLAKE2b digest of the objective identity, the kind
one-hot, the position in the sequence, and the progress fraction, each optional value paired with
its own missing indicator - so the same world state pursued under two different goals encodes
differently. The observation is `us079-v1` at 86 columns; `bug031-v1` artifacts at 75 columns are no
longer readable and are rejected rather than padded.

Both encoders fill that block from the same facts. `FarmingSimulator.observation` reports its active
quest objective, and `live_observation` reports `HierarchicalObjective.encoded_identity` and
`encoded_kind`, which `features/automation/quest_goals.py` states explicitly from the active
`QuestGoal`. `tests/unit/test_decision_contract.py` builds one world twice - once as a seeded
simulator episode, once as a live `WorldState` plus `PolicyContext` derived from the same map facts
- and asserts both encode to one identical vector, including the candidate's measured relative
elevation, which the simulator previously hard-coded to zero.

### One versioned reward configuration

`RewardConfig` refuses to change a weight while keeping the shared version string, so a version
identifies its weights. `DEFAULT_REWARD_CONFIG` is the one instance `SimulatorConfig`, the telemetry
transition exporter and the training evaluation all use, and its version is written into the trained
artifact metadata, the exported Parquet dataset (as schema metadata and as a per-row column) and the
export provenance document.

### Contract stamping and rejection

`features/policy/contract.py` owns `DECISION_CONTRACT_VERSION` (`us079-v1`) and the `ContractStamp`
that names the observation schema and width, the strategic goal and objective kind orders, the
tactical action count, and the reward configuration version. Every artifact and dataset carries the
stamp; `read_hierarchical_metadata` and `read_transition_contract` verify it before anything else is
read and raise `ContractVersionError` naming the exact field that disagrees plus both values. No
compatibility shim exists, as [ADR-003](../decisions/ADR-003-clean-schema-over-backward-compatibility.md)
authorizes. The orchestrator turns that error into a `PolicyFault` carrying the
`ContractIncompatibility`, and the combat panel renders one complete localized sentence per
incompatibility in German and English rather than pasting a raw code into a sentence.

`tests/unit/test_action_contract.py` parses every source file and asserts each vocabulary class is
declared in exactly one module; `tests/unit/test_decision_contract.py` covers goal conditioning,
encoder parity, the reward version stamp, per-field contract rejection and the localized
diagnostics. This completes [US-079](../user-stories/completed/US-079-unified-goal-conditioned-decision-contract.md).
Evidence is offline: the 2026-08-28 gate passed at 994 passed, 5 skipped, 89.26% coverage; no live
`neuz.exe` shadow-mode session has been run against the new contract.

## Bounded tactical parameters and hybrid tuning (US-084)

`features/tactical_parameters.py` is the single boundary for ML-modifiable operational heuristics.
`TacticalParameterSpace` contains exactly 16 typed scalar fields covering navigation, combat and
targeting, perception and camera, and vitals/recovery. Each field has one immutable finite
minimum, maximum, and safe default in `TACTICAL_PARAMETER_DEFINITIONS`; engagement distance also
has bounded, case-insensitive per-monster profiles. The positive profile allow-list excludes
Win32 virtual keys, process fingerprints and memory offsets, foreground checks, emergency-stop
keys, and schema digests.

Values resolve in this order: safe defaults, a loaded validated profile, a per-monster engagement
profile, then a prevalidated transient approach-distance override supplied by one policy decision.
The transient override has the highest and final precedence for that decision.
Finite outliers clamp deterministically. Config-file and offline non-finite values become the safe
default and retain a typed diagnostic that the synchronized German/English UI can render. A live
learned non-finite, malformed, masked, or otherwise invalid action instead fails closed under
[ADR-008](../decisions/ADR-008-closed-learning-loop-invariants.md); it is not silently replaced by
a default or heuristic action.

`TacticalParameterProfile` persists the vector as deterministic, digest-checked JSON under the
standalone `us084-v1` schema. This is compatible with a future US-081 model-registry reference;
US-081's experience database and train/evaluate/promote lifecycle remain draft. The simulator,
pathing, combat, search, vitals, camera-alignment, and orchestrator boundaries consume the active
validated vector, and the desktop UI exposes display, export, load, and reset controls. Camera
pitch and zoom are guarded open-loop actuator calibration settings; foregrounded Windows/live
client confirmation remains unrun.

Automated evidence is offline: 18 focused tactical tests passed, as did the affected 276-test
slice after the i18n fix, the 55-test orchestrator slice, Ruff, and MyPy. These checks establish
contracts and synthetic integration, not live camera or zoom behavior.

The final canonical gate passed on 2026-08-28: `uv sync --locked`, Ruff, format, and MyPy completed
successfully, and pytest reported 1063 passed, 5 skipped, and 89.38% coverage. This remains
automated/offline evidence; live camera and zoom confirmation against `neuz.exe` is unrun.

This section records the boundary chosen in [ADR-009](../decisions/ADR-009-bounded-tactical-parameter-space.md).

## Authoritative static client catalog and its source manifest (US-083, partial)

`features/client_data/` owns the normalized static gameplay tables and the manifest that says who
reads them, and `features/perception/catalog_join.py` applies it to a tick's own detections. It is
the data layer the remaining US-083 fusion criteria build on; the policy, telemetry and reporting
halves of that story are not implemented.

**Catalog.** `tables.py` parses movers, drops, items, skills and NPCs; `extraction.py` reads them
through the keyed-archive reader `features/quests/extraction.py` already owns, rather than opening
the archives a second way; `persistence.py` writes and reloads a schema-versioned
`data/client/catalog.json`. Every record is either fully parsed or is absent with a typed
`CatalogRejection` naming the reason and locator. Nothing is completed from a neighbouring row.

A mover's numeric columns are located by the client's own commented column header, not by a fixed
index, because a private-server table can carry extra columns and a fixed index would hand a policy
a value the client never stated about that mover. The header's comment marker occupies a
tab-separated field that data rows lack, so leading blank fields are dropped to keep names aligned
with data columns. With no header the combat fields stay `None` behind a `LAYOUT_UNVERIFIED`
rejection, and `MoverCombatProperties.is_aggressive` returns `None` rather than defaulting to
passive.

**Setup.** `UnifiedClientExtractor._run_mover_stage` parses, validates, persists and only then
counts. The presence-only `monster_table_count` and `static_item_table_found` fields are deleted:
finding a file name is not ingestion (BUG-033).

**Source manifest.** `manifest.py` and `sources.py` describe every parsed table with its client
digest, content digest, schema version, completeness, freshness rule, per-field provenance and the
exact production consumers that read it. A static table's freshness is `STATIC_UNTIL_REEXTRACTION`;
a live provider must state a sample age instead, which its constructor enforces.
`verify_consumer_coverage` refuses a manifest in which any declared field names no consumer, and
`undeclared_tables` refuses a table that produced records but appears in no entry - together they
make "extracted but silently unused" a test failure. The check found a real gap on its first run:
no decision path reads the client's skill rows, so `client.skills` carries zero promoted fields and
`PARTIAL` completeness rather than an invented consumer.

**Label join.** The client does not ship the `MI_*`-to-numeric-mover-id table; it is compiled into
`neuz.exe` (see `docs/sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md`), so the
join from a YOLO class to a mover is a curated, versioned artifact rather than a derivation.
`label_mapping.py` binds a detector label to exactly one mover id and symbol, stamped with the
client digest it was proven against. It fails closed on an unmapped label, a label bound to two
movers, a display name shared by two movers, a binding naming a symbol the mover table never
declared, a foreign client digest and a foreign mapping version. The join is keyed by the US-079
per-instance candidate identity, so two simultaneously visible monsters of one class stay distinct.

**Perception enrichment.** `PerceptionPipeline` assigns each decoded box its candidate identity and
joins the frame's own detections through `MobCatalogJoin`, so `WorldState` carries
`mob_catalog_joins` (mover id, symbol, display name, verified combat properties, declared drops and
spawn evidence) keyed by that identity, plus `mob_catalog_rejections` for classes it could not join.
The join runs on the boxes the same tick produced, so enrichment can never outlive them: a failed
detection keeps the previous mobs *and* their previous join rather than re-keying a stale one.
Spawn evidence - zone count, total capacity and the shortest respawn interval per mover - comes from
the adopted world map, pushed in by `FarmingOrchestrator.configure_vector_navigation`.

A rejection is a property of the class, not of one box, so five unjoinable detections of one class
state one fact. Three states are deliberately distinct: no artifacts installed (no join, no
rejection), a mapping refused for a foreign client digest or mapping version (a `MobCatalogJoin`
that keeps stating the refusal on every tick), and a label the installed mapping does not bind
(`LABEL_UNMAPPED`). `load_mob_catalog_join` reads `data/client/catalog.json`,
`data/client/mover_label_mapping.json` and the manifest's client digest; a catalog artifact of
another *schema* version is not a label-join problem and is raised to the caller, because the fix
is to re-run extraction. The curated mapping artifact itself is operator-supplied data: the six
Eden mover symbols (`MI_FLAME`, `MI_LADYBLUM`, `MI_MINIMUSH`, `MI_NIGHTMIST`, `MI_OLDRUT`,
`MI_RAPRA`) and their numeric IDs (1453–1458) have been manually verified by the operator against
the local client (`docs/sources/2026-08-28-operator-verified-eden-mover-symbols.md`). Detections
for any unmapped class continue to report as explicitly unmapped rather than guessing by name
similarity.

**Detector whitelist.** `OpenCVDnnYoloDetector._decode` applies the operator's class whitelist
before `_suppress_per_class`, so a filtered class never reaches suppression, tracking, world
projection, catalog joins or ranking, and no enrichment step can reintroduce it. A regression test
records what reaches NMS and asserts an unknown class name cannot widen the selection.

**Formatter constraint.** The pinned `ruff format` rewrites an inline `except (A, B):` into invalid
Python. Multi-type handlers must therefore use a named module-level tuple constant. Four committed
files (`navigation/teleporter_extraction.py`, `quests/extraction.py`, `setup/profiles.py`,
`telemetry/storage.py`) had been left syntactically invalid by this defect and were repaired.

## Production readiness: setup autostart, artifact autoload, HUD fallback (US-085, completed)

**Mandatory artifacts.** `SetupRequiredDatasets` now also names `data/client/catalog.json` and
`data/client/source_manifest.json` alongside the world maps, quest database, dungeon database and
player-stat profile registry. Without the catalog and its manifest no detection can be attributed
to the mover the client declares, so an install missing them is unfinished setup rather than a
degraded session. `UnifiedClientExtractor.is_first_run_required` reports the same set the wizard
writes.

**One load path.** `MainWindow.reload_client_data()` loads the teleporter catalog, the quest
database and the mover catalog join, refreshes the world-data dialog, re-evaluates the arming gate,
and republishes the join over the `client_data_reloaded` signal. `ui/app.py::run_desktop` calls it
before the window is shown, and `SetupWizard.setup_completed` calls it again, so a fresh extraction
reaches the live `PerceptionPipeline` without restarting the application. A catalog written under
another schema version cannot be repaired at runtime, so it is treated as unfinished setup - which
is exactly the remedy the wizard offers - rather than crashing startup.

**Arming gate.** `run_desktop` opens the wizard automatically when `MainWindow.is_setup_required()`
holds. While it holds, the start button is disabled and carries a localized reason. Constructing the
window never reads the filesystem: only a load pass re-evaluates the gate, so window construction
stays deterministic in tests and headless runs.

**Graceful memory-profile fallback.** A client build with no verified player-stat profile reports
`ProviderHealth.UNSUPPORTED` forever, which previously left combat and vitals blocked and the
autonomous loop deadlocked. After `PLAYER_STATS_FALLBACK_GRACE_SECONDS` of continuous unsupported
results, `FarmingOrchestrator` calls `LiveReadinessGate.demote_source` and
`PerceptionPipeline.demote_player_stats_provider`: the gate stops requiring the source and drops any
capability it solely carried, and the pipeline releases the read-only handle and resumes reading
vitals from the visual HUD. Only `UNSUPPORTED` demotes - a window that lost focus or a handle that
dropped reports `UNAVAILABLE` and keeps its chance to recover, so alt-tabbing can never cost the
session its exact statistics. The demotion is recorded once as a `capability_degraded` session event
and surfaces in the readiness panel as a localized fallback row plus a distinct ready-with-fallback
summary. `LiveReadinessStatus.degraded_sources` carries the same fact to telemetry consumers.

**No asserts in production code.** `src/flyff_bot/` contains no `assert` statement, so behavior under
`python -O` is identical to a normal run. Where a statement only re-narrowed optional attributes, the
owning read-only reader's `_ensure_open` now returns the `(handle, module_base, profile)` triple that
only ever exists together (`live_position`, `live_camera`, `live_world_id`, `player_stats.reader`,
`dungeons.live_reader`), and the Qt painters in `path_inspector` take the already-narrowed `scene` or
`snapshot` as a parameter from the one place that checked it. The remaining cases became typed
exceptions or total functions: the readiness failure sort key ranks a reasonless source behind every
real failure instead of asserting, and `_telemetry_position` is a non-optional converter beside the
optional `_position`. A guard test parses every production module and fails on any `ast.Assert`.

**Verification gate.** `--cov-fail-under` moved from 60% to 85%. The 2026-08-28 run of
`scripts/check.ps1` passed with 1176 tests passed, 5 skipped, and 89.60% coverage; `uv sync --locked`,
Ruff, `ruff format --check`, and mypy (316 files) were clean. Live-client walkthroughs (wizard on a
clean install, farming, and the END / focus-loss release) remain operator validation on Windows.

## Unattended autopilot, session resilience, and goal arbitration (US-086, completed)

**Import graph repaired first.** `flyff_bot.cli` and `flyff_bot.ui.app` could not be imported from a
cold interpreter at all: `features/automation/__init__.py` re-exported `FarmingOrchestrator`, so
importing any automation leaf pulled in policy, RL, telemetry and navigation, and
`navigation/pathing.py` closed the loop by importing `flyff_bot.ui.dashboard`. Only
`tests/unit/conftest.py`, which happens to import navigation first, ever hid it. Three changes fix
the layering rather than the symptom: the movement virtual keys moved to the dependency-free
`input_control/keymap.py`, the navigation view objects (`NavigationSnapshot`, `NavMeshMobSnapshot`,
`VectorZoneSnapshot`) moved from `ui/dashboard.py` to `features/navigation/snapshots.py` and are
re-exported for the UI, and the automation package stopped re-exporting the orchestrator (import it
from `features.automation.orchestrator`). `tests/integration/test_module_import_graph.py` imports
every entry point in its own subprocess so the regression cannot hide again.

**A tick fault ends the tick, not the worker.** `SessionWorker._run` wraps `tick()` and hands the
exception to `on_fault`, which `ui/app.py` wires to `FarmingOrchestrator.handle_tick_fault`. That
releases every held key, stops pathing, records a `tick_fault` session event carrying
`exception_type` and `exception_message`, and moves to the new `FarmingMode.FAULTED`. An emergency
stop and a completed budget are declared outcomes (`TERMINAL_MODES`) that a later fault never
overwrites. Each successful tick publishes a `WorkerHealth` heartbeat; a `QTimer` on the Qt thread
evaluates `is_worker_stalled` once a second, so a dead worker replaces the state line on the
dashboard instead of leaving the last successful state on screen.

**Death is a state.** `DeathDetector` confirms a death exactly once after a named continuous
zero-HP dwell (`DEFAULT_DEATH_CONFIRMATION_SECONDS`), which is the fallback the story allowed
because no memory profile exposes a death flag. `FarmingMode.DEAD` is a standby mode, so vitals are
never evaluated there, and `VitalsTriggerController` additionally refuses to fire below
`MINIMUM_TRIGGERABLE_VITAL_PERCENTAGE` - zero percent HP is death evidence, not a reason to press
the potion key forever. Under autopilot, `RespawnMenuPerceiver` reads a bounded centre ROI for the
client's `Lodestar` revive row and `RespawnInputDispatcher` clicks only that OCR-proven point,
foreground-checked and killswitch-checked. Without autopilot the session pauses and waits for the
operator. More deaths than `maximum_deaths` inside the rolling window pause autopilot with a reason
naming the count instead of respawning again.

**One documented killswitch.** `WindowsInputController.is_aborted` polls `F12` only, reading both
`KEY_IS_DOWN_MASK` and `KEY_PRESSED_SINCE_LAST_QUERY_MASK`, so a short press between two ticks is
still detected. `ESC` is no longer an abort key anywhere: it is an ordinary Flyff dialogue key that
the quest flow itself provokes, and the dashboard and map windows now bind `F12` too. This
supersedes every earlier `END` / `Escape` statement on this page.

**A policy fault costs a decision.** `FarmingOrchestrator._record_policy_fault` discards the faulted
decision and lets the tick fall through to the deterministic path. Consecutive faults are counted;
only beyond `maximum_policy_faults` is learned automation demoted to `HEURISTIC` with a
`capability_degraded` event, and farming continues. A successful evaluation clears the counter. An
unroutable attack point is now such a fault, so the candidate is skipped for that decision instead
of pausing the session. `PolicyFaultCode.MODEL_UNAVAILABLE` keeps the BUG-031 halt, because a model
that cannot load can never start working. `POLICY_LATENCY_BUDGET_SECONDS` is unchanged at 5 ms but
is no longer assumed: `scripts/measure_policy_latency.py` measured a worst case of 0.070 ms across
1-16 candidates on the target machine, recorded in
[the latency measurement](../sources/2026-08-28-tactical-policy-inference-latency-measurement.md).

**Budgets, arbitration, and the summary.** `features/automation/autopilot.py` holds the whole
unattended-session rulebook with no Win32 and no Qt: `AutopilotConfig` (every budget with a named
default, a validated finite range, and `AutopilotConfigError` on an invalid value), `RollingBudget`,
`DeathDetector`, `AutopilotSessionController`, and the pure `arbitrate_goal`. Arbitration is
deterministic and explainable in a fixed order - continue the active quest, farm its kill objective,
turn a completed quest in, accept the next quest, otherwise farm the configured fallback zone - and
each decision is recorded as an `autopilot_goal` event. A fallback zone is named by its monster
classes, which is what the extracted world map and the navigator already key on; the arbiter arms
them as unlimited kill quotas rather than inventing a zone. Lost focus, a capture error, or a
readiness block start a bounded backoff and resume on their own, each resume counted against
`maximum_recoveries`; a client absent beyond `maximum_absence_seconds`, an exhausted recovery or
tick-fault budget, or the session time budget end the session in `COMPLETED` with a typed
`AutopilotSummary` the dashboard renders as one localized sentence. The time budget waits out
`ENGAGEMENT_MODES` first, so a budget never abandons a live engagement.

**Quest NPCs are projected, not matched.** `project_world_to_screen` runs the world position through
the live `CameraState.view_projection_matrix` and returns a fail-closed `WorldScreenProjection`:
`BEHIND_CAMERA`, `OUTSIDE_VIEWPORT` and `INVALID` yield no pixel at all. The former code matched the
NPC's world position against `WorldState.visible_mobs`, which only ever holds YOLO monster
detections, so `npc_screen_position` stayed `None` and the dialogue was never opened; it also routed
to the world origin when the NPC had no known position, which no longer happens. An unprovable
projection drops the stored click target through `observe_npc_projection_failure`, so the bounded
interaction timeout fails the goal with a typed reason instead of clicking where the NPC used to be.
Both dialogue perceivers now OCR a bounded ROI and report the matched line's centre in client pixels.

**Verification.** `tests/integration/` now exists and drives the real tick path against fakes: a
contained tick fault with a live worker, a death with an OCR-proven respawn and a resumed session, a
death without autopilot that waits, an exhausted death budget, a focus loss that resumes after the
backoff, an exhausted absence budget, an arbitrated goal, and a time budget that finishes with a
summary - with no client, no window, and no dispatched input.

## ML and policy insight view (US-087, completed)

**One frozen snapshot per tick.** `features/policy/insights.py` holds the whole read-only decision
telemetry vocabulary - `ModelArtifactIdentity`, `CandidateInsight`, `ChosenActionInsight`,
`ShadowComparison`, `ParameterOverrideInsight` and the `PolicyInsightSnapshot` that carries them -
plus the `PolicyInsightRecorder` the orchestrator feeds on the farming tick thread. Nothing in the
module reads live session state and nothing it produces is mutable, so the eighth dashboard tab
(`DashboardTab.ML_POLICY`) renders it without ever reaching back into the worker (ADR-002). The
snapshot travels on the existing `DashboardUpdate`, so there is no second publication path.

**What is measured, and what is deliberately absent.** `PolicyRunner.last_latency_seconds` now
retains the wall time it already measured, so the operator watches the 5 ms decision budget being
spent rather than only learning that it was exceeded. A learned artifact is identified by digesting
its provenance document (`hierarchical-metadata.json`, else `metadata.json`) - the document that
names the contract, the heads and the bound inputs, and therefore the thing that changes when the
artifact stops being the same artifact. Candidates that the deterministic mask rejected stay in the
table as rejected: the option set a decision was taken from is what makes the decision judgeable.
A per-candidate model score is only shown for the chosen candidate, because the hierarchical heads
rank goals and action kinds and expose no per-instance value; showing a number for the others would
be an invention. Reachability is the NavMesh predicate, not a line-of-sight trace, which the client
does not expose.

**Reward and experience come from the recorder that already computes them.**
`SessionExperienceTotals` (`features/telemetry/models.py`) is maintained incrementally by
`TelemetryRecorder`: one completed kill cycle is one episode, the decisions since the last one are
its steps, and the decomposition (kill reward, navigation penalty, objective progress) is computed
with the same `RewardConfig` weights the cycle's own reward used, so the parts always add up to the
total the session was steered by. Elapsed time and the reward accrued inside the unfinished episode
are derived at read time. Benchmarks - verified kills per minute, travel seconds per kill, stall
rate - are measured from this live session; the offline evaluation registry US-081 once proposed was
consolidated away, so there is nothing to summarize from a promoted-model report and the view does
not pretend otherwise. Every unmeasured quantity renders as "not measured" rather than as zero.

**Dynamic parameters.** `POLICY_MODULATED_PARAMETERS` names the tactical parameters a live learned
decision may modulate. Today that is the approach distance carried by an `AttackPointAction`; the
replan interval and stall timeout are listed with baseline equal to active, which is the honest
statement that no policy moves them. The table compares the configured baseline against the value
the current decision actually used.

**Placement.** `PolicyRuntimeMode` and `DEFAULT_POLICY_RUNTIME_MODE` moved from
`features/automation/orchestrator.py` to `features/policy/models.py`. The mode is a property of the
policy contract, and a presentation layer must be able to name the mode a decision was taken in
without importing the session that executed it.

## Unified goal navigation, micro-sweep scanning, and mesh evasion (US-091, completed)

**The camp selection is the whole statement of what to farm.** Goal selection used to diverge:
`VectorZoneNavigator` walked to the operator's selected spawn zones while `KillGoalTracker` still
carried whatever the dashboard preset listed, so a session sent to one camp fought every other
monster on the way there. `zone_locked_goals` (`features/navigation/vector_navigation.py`) now
derives exactly one `ZoneGoal` per selected camp, in selection order, keeping a quota only where the
preset named that camp's monster. `VectorNavigationRequest.navigator()` applies it at construction
and `FarmingOrchestrator._lock_goals_to_selected_zones` rewrites the session's quotas from the
navigator's goals on activation. Because the quota tracker is what feeds the combat whitelist, the
candidate-economics quota bonus and the policy action mask, one write locks all four.

**Self-defence is the single exception.** `features/automation/self_defense.py` holds a
`SelfDefenseGuard` that opens a bounded window when health drops while no engagement is in progress.
While it is open the whitelist is lifted to "any class"; when it closes the zone lock returns.
Damage taken inside an engagement is the fight the session chose and never opens it, and a halted or
paused session closes it, because its health baseline is stale by the time the session resumes.

**Searching is a camera sweep and nothing else.** `SearchController` lost `SearchMode.ROAM_STEP`
along with `roam_steps` and `movement_step_duration_seconds`: blind `[W, D, W, A]` roaming walked the
character into collision geometry it could not see. What remains alternates `SearchMode.ROTATE`
bursts with `SearchMode.SETTLE` windows - the only ticks in which a detection runs on an unsmeared
frame - and `idle_timeout_seconds` defaults to `0.0`, because a viewport that just proved empty
learns nothing from being stared at. The burst length is the tactical parameter
`search_turn_duration_seconds`, whose default dropped to `0.12 s` and whose upper bound narrowed to
`0.5 s` so a tuned or learned profile cannot leave the micro-sweep regime (ADR-009). A verified
detection calls `SearchController.reset()` before the approach begins, so no further rotation is
dispatched between acquisition and combat. Ground movement while no mob is visible is the NavMesh
patrol route, not the sweep. The dashboard status `search_roaming` became `search_scanning`
(`ui.status_search_scanning`, synchronized in `de.json` and `en.json`), and `--search-movement-duration`
was removed from the CLI.

**One mesh for patrol and for combat.** `VectorZoneNavigator` now takes a `BakedNavMesh` and routes
each patrol-ring leg with `BakedNavMesh.find_path`, so zone travel and combat approaches read the
same walkable polygons instead of two routers disagreeing about what is solid.
`PathingController.attach_vector_navigator` is where the session settles on one mesh: the controller's
loaded mesh wins, and a mesh the operator loaded next to the world map (carried on
`VectorNavigationRequest.navmesh` by the World Data Dialog) is adopted when the controller was built
without one. `TerrainRoutePlanner` remains only as the fallback for a world whose mesh has not been
baked yet; removing it, and moving `SimulatorEngine` off `VectorRoutePlanner`, is deliberately left
as the follow-up pruning task rather than folded into this story.

**Evasion is proactive, and a trap has an exit.** A live stall queues backstep (`S`), jump (`Space`)
and a directional pivot (`W` plus `A`/`D`), and records the blocked node in `_temporary_blocks`
immediately rather than only on a repeated stall - a global replan that still routed through it would
only walk back into the same collision. A second stall at the same spot flips the pivot direction,
because the previous one is the direction that did not work. When every leg of the camp route is
refused - what standing in a canyon or a collision pocket looks like to the router -
`PathingController._plan_escape_route` samples rings of candidate nodes, projects them with
`nearest_walkable_position`, and takes the nearest one that is both reachable and closer to the camp
than the trap. "Closest walkable surface" alone would be the wall the character is already pressed
against. `AttackPointPlanner.plan` accepts those recorded obstacles: a candidate inside
`OBSTACLE_CLEARANCE_UNITS` is refused outright and one inside `OBSTACLE_INFLUENCE_UNITS` is ranked
worse than the same point in the open, so a learned attack-point action lands clear of known
collisions.

## Geometry-verified stall recovery and unified NavMesh routing (US-093, completed)

**No blind macro survives.** US-091's stall recovery queued a fixed `S` backstep, `Space` jump, and
`W`+`A`/`D` pivot and stored the character's *own* coordinate as the obstacle, so an A* replan from
`start` either failed or collided with the start node. `PathingMode.EVADING`, `_evasion_steps`, and
every `EVASION_*` constant are gone. A stall now stays in `PathingMode.TRAVELING`; recovery is a
geometry problem, and every recovery move goes through the same `_steer()` the normal route uses.

**A stall is a structured observation.** `PathingController._register_stall` builds a
`StallObservation` (`features/navigation/stall_recovery.py`) carrying the previous and current live
position, the intended movement direction (toward the active waypoint, else the camera heading), the
intended waypoint, the current polygon id, and a timestamp. From it, `TemporaryObstacleRegistry`
projects the obstruction `obstacle_probe_distance` (1.2 m) *ahead* along that direction, snaps it to
the mesh with `nearest_walkable_position`, and stores it with a 1.5 m radius and a hit-scaled TTL
(15 s / 30 s / 60 s for 1 / 2 / 3+ hits). A projection that collapses back onto the character is
discarded, so the start coordinate is never blocked. `RepeatedLocalStallTracker` counts stalls
inside a 2.0 m radius and a 10 s sliding window.

**Obstacles are corridor-level exclusions.** `BakedNavMesh.find_path` / `find_polygon_path` take an
`obstacles` tuple of `(centre, radius)` circles; `_polygon_ids_in_obstacles` marks a polygon blocked
when the circle covers its interior (`_height_at_xz`) or comes within `radius` of an edge (2D segment
distance), and `_a_star` skips those - except the start polygon, which is always removed from the
blocked set so a character standing on an obstruction can still route out. `_plan_leg` in
`VectorZoneNavigator` passes the active obstacles through and keeps a cheap coordinate check that
skips the leg's own start point.

**First stall replans, repeated stalls escape.** The first stall invalidates the route and sets
`RecoveryContext.phase = LOCAL_REPLAN`; the next `step()` re-plans over the mesh with the active
obstacles and resumes steering, emitting `LOCAL_REPLAN_REQUESTED` then `LOCAL_REPLAN_SUCCEEDED`. When
`RepeatedLocalStallTracker` reaches two hits, the phase becomes `ESCAPE` and `_plan_escape_route`
runs `plan_escape_candidates`: concentric rings at 0.75 / 1.5 / 2.5 m with 12 radial directions,
each candidate projected onto the mesh, validated for containment, slope
(`BakedNavMesh.surface_slope_degrees`), obstacle clearance, reachability, and goal progress, then
scored deterministically on goal progress, travel distance, and clearance with a coordinate
tie-break. The chosen point becomes a temporary waypoint routed through `_steer()`; on arrival
`_follow_route` clears the escape state and replans to the original goal instead of idling. If
nothing can be routed at all, `_plan` clears the recovery state so a stuck route can never latch the
controller into a permanent recovering mode.

**The legacy 2D router is gone.** `terrain_routing.py` (`TerrainRoutePlanner`, `TerrainRouteConfig`,
`TerrainWaypoint`) and `test_terrain_routing.py` are deleted. `VectorZoneNavigator` routes every
patrol leg over the `BakedNavMesh` alone and refuses every leg when no mesh is loaded, so a world
with no baked NavMesh hard-blocks and `FarmingOrchestrator` pauses rather than steering over an
unverified 2D heightfield. `PathingController.__init__` adopts the navigator's mesh at construction,
matching `attach_vector_navigator`, so patrol, combat, and escape routing can never disagree.

**Recovery is observable without a custom mode.** `TelemetryEventKind` gains `STALL_DETECTED`,
`TEMPORARY_OBSTACLE_CREATED`, `LOCAL_REPLAN_REQUESTED`, `LOCAL_REPLAN_SUCCEEDED`,
`REPEATED_LOCAL_STALL`, `ESCAPE_PLAN_SUCCEEDED`, and `ESCAPE_PLAN_FAILED`;
`PathingController.drain_recovery_events()` hands a queue of `RecoveryEvent` values to
`FarmingOrchestrator._forward_recovery_events`, which forwards each to
`TelemetryRecorder.record_stall_recovery_event` and bumps the retained
`NavigationEpisode.collision_evasions` / `evasion_seconds` counters on a successful replan or escape.
`RecoveryContext` / `RecoveryPhase` stay internal to the controller. `emergency_stop()` clears the
obstacle registry, the local-stall history, the recovery context, and the queued events alongside
the existing key release.
