---
title: Architecture
status: active
updated: 2026-08-16
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
related:
  - project-overview.md
  - glossary.md
  - ../decisions/ADR-001-cli-before-http-server.md
  - ../decisions/ADR-002-target-architecture-and-pyside6.md
  - ../user-stories/completed/US-002-vision-frame-capture.md
  - ../user-stories/completed/US-003-mob-detection-yolo.md
  - ../user-stories/completed/US-004-target-mob-verification.md
  - ../user-stories/completed/US-005-loot-log-ocr.md
  - ../user-stories/completed/US-008-reactive-combat-controller.md
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
  - ../user-stories/completed/US-023-reliable-combat-targeting-and-kill-verification.md
---

# Architecture

The codebase follows a typed `src` layout with feature-scoped modules. The system is designed to evolve into a multi-tier closed-loop control system:

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
Game Client
```

## Layers and Components

1. **Perception Layer:**
   - **YOLO:** `OpenCVDnnYoloDetector` loads raw YOLO ONNX models and ordered UTF-8 labels,
     performs CPU OpenCV-DNN inference, filters by confidence and class name, and applies NMS.
     It returns structured client-space detections with a bounding box, confidence, class ID, and
     class name; the `Detector` protocol supports deterministic mock implementations.
   - **Template Matching:** Detection of fixed 2D UI elements and anchors.
   - **ROI OCR:** `LootLogReader` extracts a configurable normalized central loot/system-log
     region, applies CLAHE contrast enhancement and adaptive thresholding, and delegates text
     recognition to an injectable engine. Its Tesseract adapter reads English and German text;
     pickup parsing produces typed timestamped loot events without dispatching input.
  - **Frame capture:** `WindowsFrameSource` captures the foreground client's exact client area
     through documented Win32 GDI APIs and exposes contiguous BGR or RGB `numpy.ndarray` frames.
     Its `FrameSource` protocol is injectable for deterministic tests, and capture failures use
     typed error codes.
   - **Target verification:** `TargetVerifier` template-matches a configured header anchor before
     inspecting the configured target-bar sub-region for HP colour and template-matching a
     whitelisted name. It returns `VALID_TARGET`, `WRONG_TARGET`, or `NO_TARGET`, including an
     HP percentage calculated only from the target-bar sub-region, without dispatching any input.
   - **Perception pipeline:** `PerceptionPipeline` captures one frame per tick and passes that
     shared frame to mob detection, target verification, and loot-log OCR. It maps their outputs
     into a fresh immutable `WorldState`, emits target-change and newly-visible-mob events, and
     records feed-specific failures while retaining the prior value for a failed feed.
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
to sweeping rotation without executing uncalibrated minimap clicks. (Minimap radar navigation is isolated
for future calibrated enhancement in US-027). Every search tick first evaluates the newest perception snapshot:
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
commanded, and its verdict also sets `WorldState.is_stuck`.

`RoutePlanner` runs Dijkstra over the recorded edges and scores candidate goals by decayed spawn
density per unit of travel cost, chaining the densest reachable clusters into a patrol circuit that
returns to its start. `PathingController` owns the loop: it observes each snapshot, steers toward
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
