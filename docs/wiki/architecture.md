---
title: Architecture
status: active
updated: 2026-08-17
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
     typed error codes. `require_foreground=False` relaxes only the foreground precondition for
     read-only standby previews (US-028); closed and minimized windows still fail.
   - **Target verification:** `TargetVerifier` template-matches a configured header anchor, then
     crops the HP-bar and mob-name rectangles at fixed pixel offsets from that match position and
     measures HP colour and the best whitelisted name template. It returns `VALID_TARGET`,
     `WRONG_TARGET`, or `NO_TARGET`, including an HP percentage calculated only from the HP-bar
     crop, without dispatching any input.
   - **Perception pipeline:** `PerceptionPipeline` captures one frame per tick and passes that
     shared frame to mob detection, target verification, and an optional loot-log OCR feed, which
     defaults to a no-op reader that performs no subprocess or disk I/O when none is attached. It
     maps their outputs into a fresh immutable `WorldState`, emits target-change and
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
`models/target_anchor.png` — track the header wherever it is drawn inside the searched region, which
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
`MonsterStatsStatus` (`IDLE`, `OK`, `ANCHOR_NOT_FOUND`, `ROI_UNAVAILABLE`, `OCR_FAILED`, `NO_MATCH`)
are measured on the same tick whether or not the reading succeeded. `_extract_anchored_roi` now
returns the best `cv2.matchTemplate` score alongside its crop instead of discarding it on the
below-threshold path, so the panel shows how close a missed match came — the same lesson US-029
applied to `TargetVerifier`. `PerceptionPipeline` carries the value object on
`WorldState.monster_stats` and still leaves `monster_kill_count` untouched when `parsed_count` is
`None`, because `CombatController` confirms a kill from an exact `+1` delta and a zero written on a
failed read would fake one. The dashboard adds a "Monster Stats Debug" toggle and panel with five
read-only rows (anchor score/threshold with the shared PASS/FAIL badge, cropped ROI dimensions,
parsed kill count, raw OCR text rendered as `Qt.TextFormat.PlainText` because OCR output is
untrusted markup, and the feed status sentence), rendered from `_render_update` independent of the
toggle. No monster-stats anchor template ships in `models/` and `run_desktop` constructs the reader
without one, so the shipped app reads the fixed normalized ROI; `anchor_configured` is `False`
there and the anchor row states that no template is configured rather than showing a Fail badge for
a criterion that was never evaluated.

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

US-022 overhauls the desktop dashboard boundary (`flyff_bot.ui`) with a cohesive Dark Slate Qt Style Sheet (QSS) theme, card-based panel grouping, streamlined visual hierarchy, a standalone pop-out navigation map window (`NavigationMapWindow`), and an `Escape` key emergency stop shortcut. All UI windows, inputs, buttons, and modal dialogs adopt dark slate styling with emerald green (Start), amber (Pause), and danger crimson (Emergency Stop) action accents alongside responsive hover/pressed states. Dashboard controls are organized into logical card panels—*Status & Metrics Card* (with colored status pill badges and metric chips), *Action Controls Card*, *Navigation & Profiles Card*, and *Telemetry & Diagnostics Toolbar*—eliminating redundant text clutter. Operators can pop out `PathInspectorWidget` into a secondary standalone window (`NavigationMapWindow`) to maintain a compact controller dashboard while monitoring live 2D pathing and heatmap telemetry on a separate display. Pressing `Escape` (`Qt.Key.Key_Escape`) while any UI window has focus instantly triggers an emergency stop (`emergency_stop_requested.emit()`), matching the physical UI button and the global Win32 `END` key safeguard. All user-visible strings, badge labels, and tooltips are localized across German and English.

