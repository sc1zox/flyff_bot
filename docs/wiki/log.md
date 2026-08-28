# Wiki log

## [2026-08-25] synthesis | Simulator dynamics and evaluation invariants (BUG-032)

Recorded the repaired offline-simulator invariants in `architecture.md`: one budgeted tick clock
whose buckets sum to elapsed time, movement only through the routed corridor, mask enforcement
inside `step()`, all spawn zones active with an explicit visibility radius, objective-free farming
as a continuing task, and the single versioned reward configuration. Also recorded the disjoint
training/evaluation/calibration seed blocks, the state-derived mid-level labels, the exported
trained-action sets, and the calibration gate in the training pipeline. Extended ADR-007 with the
tactical-modeling condition these invariants enforce. Live-client validation remains outstanding.

## [2026-08-24] completion | Learned attack point positioning (US-070)

Added the US-070 architecture section covering deterministic melee/ranged attack-point annuli,
strict X/Z containment, bounded multi-criteria scoring, two-unit target-movement hysteresis, and
direct-Funnel fallback. Live Windows/client validation remains outstanding.

## [2026-08-24] synthesis | Experience-weighted NavMesh routing (US-069)

Added the US-069 architecture section covering digest-bound empirical polygon/edge storage,
trajectory schema v2 correlation, weighted A* costs, smooth cold-start fallback, preserved
reachability, localized diagnostics, and synthetic performance guards.

## [2026-08-24] completion | Rolling-horizon multi-target planning (US-068)

Synthesized the bounded learned lookahead into `architecture.md` and defined its advisory
provisional plan in `glossary.md`: deterministic masks, expected-cost accumulation, first-target-only
commitment, per-snapshot replanning, and heuristic fallback. Live dense-spawn Windows validation
remains outstanding.

## [2026-08-24] completion | Unified tactical policy integration (US-067)

Synthesized the completed US-067 policy boundary into `architecture.md`: pure TacticalPolicy
decisions, deterministic masking, heuristic baseline, US-066 five-head ONNX inference,
deadline-guarded fallback, and HEURISTIC/ML_SHADOW/ML_ACTIVE modes. Safety execution remains
downstream, and live Windows/client validation remains outstanding.

## [2026-08-24] synthesis | Dungeon reader foreground and resource correction (BUG-022)

Synthesized the BUG-022 correction into `architecture.md`: dungeon cooldown polling is foregrounded
before process attachment, verifies the executable once, retains the read-only handle and module base,
and releases them on unrecoverable read loss for safe recovery.

## 2026-08-23

- Architecture now documents the completed US-078 initial setup and unified client extraction
  workflow, including exact-fingerprint-only player-stat profile installation.

Append entries using `## [YYYY-MM-DD] operation | subject`. Do not rewrite past entries; add a
correction that links to the superseded entry.

## [2026-08-15] ingest | Repository bootstrap request

Captured the original request as an immutable source and created the initial project overview,
architecture, glossary, schema, index, user story, and CLI-first decision from it and the existing
PoC.

## [2026-08-15] ingest | Target architecture proposal

Captured the target architecture proposal as an immutable source, updated the architecture wiki
page, created ADR-002, and filed user story US-006 for the target architecture bootstrap.

## [2026-08-15] synthesis | Target architecture bootstrap

Recorded the completed US-006 implementation in the architecture and glossary pages, grounded in
the target architecture proposal and ADR-002.

## [2026-08-15] synthesis | Vision frame capture (US-002)

Recorded the completed US-002 foreground client-area capture boundary, injectable frame-source
contract, typed capture errors, and client-coordinate mapping in the architecture and glossary.

## [2026-08-15] synthesis | Product and technical roadmap

Synthesized the phased 4-stage roadmap (US-001 through US-010) across sources and architecture ADRs,
indexed in docs/wiki/roadmap.md and organized the user story backlog.

## [2026-08-15] synthesis | Mob detection with YOLO (US-003)

Recorded the completed OpenCV DNN YOLO adapter, structured client-space detection contract,
configurable filtering, injectable detector seam, and UTF-8 label-file convention in the
architecture and glossary; moved US-003 to the completed stories directory.

## [2026-08-15] synthesis | Target mob verification (US-004)

Recorded the completed normalized target-header extraction, HP-colour and whitelisted
name-template verification, typed target statuses, and perception-only safety boundary in the
architecture and glossary; moved US-004 to the completed stories directory.

## [2026-08-15] synthesis | Central loot and system log OCR (US-005)

Recorded the completed configurable loot-log ROI, contrast and threshold preprocessing,
injectable Tesseract recognition boundary, bilingual pickup parsing, and typed timestamped loot
events in the architecture and glossary; moved US-005 to the completed stories directory.

## [2026-08-15] synthesis | Perception to WorldState feed integration (US-007)

Recorded the completed shared-frame perception pipeline, immutable world-state aggregation,
target and new-mob events, and isolated feed-failure behavior in the architecture and glossary;
moved US-007 to the completed stories directory.

## [2026-08-15] synthesis | Multi-mob training dataset pipeline (US-011)

Recorded the completed offline YOLO dataset layout and validator, optional local Ultralytics
training/export adapter, and ordered ONNX-label artifact contract in the architecture and glossary;
moved US-011 to the completed stories directory.

## [2026-08-15] synthesis | Reactive combat controller (US-008)

Recorded the completed deterministic target-selection and attack-rotation state machine,
target-header/HP progress verification, and foreground/END-guarded Win32 combat-input boundary;
moved US-008 to the completed stories directory.

## [2026-08-15] synthesis | Real-world target-verification refactoring (US-012)

Recorded the anchor-gated target-header verification, dedicated HP-bar percentage measurement, and
real Flyff screenshot coverage for empty, whitelisted, and non-whitelisted target states; moved
US-012 to the completed stories directory.

## [2026-08-15] synthesis | Reactive loot collector and drop accounting (US-009)

Recorded the completed one-attempt pickup state machine, newly visible OCR loot accounting,
inventory and recipe-progress updates, timeout patrol recovery, and foreground/END-guarded loot
input boundary; moved US-009 to the completed stories directory.

## [2026-08-15] synthesis | Autonomous farming loop and orchestration engine (US-013)

Recorded the completed cooperative farming session lifecycle, guarded perception-to-controller
dispatch, reconciliation and goal completion behavior, CLI configuration path, and dashboard
control/update boundary; moved US-013 to the completed stories directory.

## [2026-08-15] synthesis | Configurable UI attack key (US-014)

Recorded the dashboard's default-F3 physical-key capture, supported combat-key ranges, and
paused-session orchestrator configuration path; moved US-014 to the completed stories directory.

## [2026-08-16] synthesis | Idle timeout and staged search navigation (US-015)

Recorded the staged no-mob recovery controller, localized timing and dashboard configuration,
minimap red-dot selection, and foreground/END-guarded navigation boundary; moved US-015 to the
completed stories directory.

## [2026-08-16] synthesis | Intelligent pathing and topological spawn heatmap (US-019)

Recorded the internal navigation feature: dead-reckoned relative position tracking, the decaying
spawn heatmap and traversal graph, frame-difference stall detection with bounded cost penalties,
safe-waypoint retreat and bypass planning, density-weighted patrol circuits, and versioned map
persistence; moved US-019 to the completed stories directory.

## [2026-08-16] synthesis | Visual navigation path and heatmap inspector (US-020)

Recorded the desktop dashboard navigation path and spawn heatmap inspector: PathInspectorWidget
2D canvas rendering of player position, heading, origin axes, leash boundary, color-scaled spawn
heatmaps, traversal graph edges, stall markers, safe waypoints, and active patrol routes, fed via
DashboardUpdate; moved US-020 to the completed stories directory.

## [2026-08-16] synthesis | Multi-axis camera search and paced scanning (US-018)

Recorded the multi-axis camera search stage, vertical pitch tilt controls (VK_UP/VK_DOWN),
gentle rotation pacing with visual settle pauses, instant perception interruption, and dead-reckoning
coordination in architecture and glossary; moved US-018 to the completed stories directory.

## [2026-08-16] synthesis | Navigation map profiles and session reset (US-021)

Recorded the completed navigation profile slot management under data/navigation/, custom profile name validation and loading, modal reset safeguards purging dead-reckoning and spatial map memory, periodic and shutdown persistence hooks, and localized PySide6 UI profile controls; moved US-021 to the completed stories directory.

## [2026-08-16] synthesis | Reliable combat targeting and kill verification (US-023)

Recorded the completed target-acquisition click-debounce grace period, the attack-cooldown reset fix
that guarantees a fresh engagement's hotkey fires even inside a prior binding's cooldown window,
OCR-based `MonsterStatsReader` HUD kill-count extraction wired into `PerceptionPipeline` and
`WorldState.monster_kill_count`, exact-`+1` kill-count-increment death confirmation as an authoritative
alternative to HP-decrease-based confirmation, the resolution-scaled debug-overlay calibration guide
box for aligning the in-game monster-stats HUD, and live dashboard configuration of the target-click
grace period and kill-verification toggle via `FarmingOrchestrator.configure_combat_grace` and
`configure_kill_verification`; moved US-023 to the completed stories directory.

## [2026-08-16] synthesis | Target verification debug dashboard visualization (US-024)

Recorded the new `TargetVerificationMetrics` value object carrying each verification criterion's raw
score, threshold, and pass/fail outcome, populated by `TargetVerifier.verify()` on every decision
branch including previously-discarded `NO_TARGET` and HP-failure evidence; the switch from
first-passing to highest-scoring name-template matching; `hp_percentage`/`metrics` forwarded through
`TargetVerificationResult` and `SelectedTarget` into `WorldState.selected_target` with
`compare=False` on `metrics` to keep continuous score jitter from firing spurious `TARGET_CHANGED`
events; and the new localized `MainWindow` "Target Debug" toggle panel rendering live anchor, HP-bar,
name-match, target-state, and failure-reason readouts; moved US-024 to the completed stories
directory.

## [2026-08-16] synthesis | Streamlined auto-looting and loot-log OCR decoupling (US-025)

Recorded `FarmingOrchestrator`'s direct `TARGET_DEAD` → `RECONCILING` transition (removing
`FarmingMode.LOOTING` and its key-press pickup wait, assuming an active in-game loot pet),
`WorldState.progress_marker` now advancing from confirmed kills instead of summed loot-event
counts so `Supervisor.NO_PROGRESS` stays accurate without any OCR feed attached, and
`PerceptionPipeline`'s `loot_log_reader` becoming an optional parameter defaulting to a no-op feed
that performs no subprocess or disk I/O; `LootController`, `LootConfig`, `LootMode`, and
`LootInputDispatcher` remain standalone, independently tested components no longer wired into the
orchestrator, and the CLI/desktop app no longer construct a Tesseract-backed `LootLogReader` for
farming by default. Updated architecture and glossary; moved US-025 to the completed stories
directory.

## [2026-08-16] synthesis | Static HUD anchoring and field hardening (US-026)

Recorded the fixed-pixel top-left player vitals HUD anchoring (resolving BUG-006 false 0% drops and consumable spam across arbitrary screen resolutions), template-matched session stats window header anchoring for dynamic `MonsterStatsReader` OCR extraction, and the desktop UI "Placements" visual guide toggle rendering color-coded ROI overlay boxes (Vitals orb, Target header, Monster Stats window) scaled over the live viewport preview; moved US-026 to the completed stories directory and BUG-006 to fixed bugs.

## [2026-08-16] synthesis | Modern dark theme and streamlined dashboard UI (US-022)

Recorded the modern Dark Slate QSS theme (`src/flyff_bot/ui/theme.qss` / `src/flyff_bot/ui/theme.py`), card-based panel grouping (Status & Telemetry, Controls, Navigation & Profiles, Diagnostics & Views), dynamic status pill badges and metric chips, standalone pop-out `NavigationMapWindow` for the 2D path inspector, and `Escape` key emergency stop shortcut in the architecture and glossary wikis; moved US-022 to the completed stories directory.

## [2026-08-17] synthesis | Live perception standby and focus workflow (US-028)

Recorded standby read-only perception in `FarmingOrchestrator._observe()` for `STANDBY_MODES`
(paused, completed, emergency-stopped) with navigation observation kept on the active path,
`FrameCaptureError` handling that pauses a running session instead of raising out of the Qt timer,
`WindowsFrameSource(require_foreground=False)` for the background standby preview and its occlusion
tradeoff, the typed `WindowStatus` published on `DashboardUpdate`, and the dashboard's separation of
the bot-status badge (`BotStatus.STANDBY` / `BotStatus.COMBAT` added) from dedicated mob-count,
target-state, vitals, and goal chips. Updated architecture and glossary; moved US-028 to the
completed stories directory and BUG-007 to fixed bugs.

## [2026-08-17] synthesis | In-game placement guide overlay (BUG-008)

Recorded the desktop placement guide overlay: the non-activating click-through
`PlacementOverlayWindow`, the `client_screen_bounds()` Win32 geometry lookup with timer-based
tracking and hide-on-unavailable behavior, the `logical_geometry()` device-pixel-ratio conversion,
the shared pure `PlacementGuide` model behind both the overlay and the dashboard preview, and the
`CAPTUREBLT` tradeoff of drawing over the captured client area. Updated architecture; moved BUG-008
to fixed bugs.

## [2026-08-17] synthesis | Minimap radar navigation rejected (US-027)

Recorded the rejection of calibrated minimap radar navigation. The US-019 spawn heatmap and patrol
circuits already reach spawns outside the camera viewport, and `FarmingOrchestrator` consults
`PathingController` before the staged search stages, leaving radar clicks valuable only on a cold
unmapped camp while permanently adding a second guarded click path aimed at the HUD. Corrected the
architecture note and both glossary entries that described the minimap-radar click as a live staged
search stage or as pending US-027 work; `MinimapRadar` and `SearchMode.MINIMAP_RADAR` remain
unreachable leftovers from US-015. Preserved the calibration spike findings (fixed-pixel top-right
anchoring at 88/104 px with an 82 px ring and 67 px inner surface, buttons sitting on the ring at
radius 77-79 px, and 763 unclassified pixels matching the prescribed red thresholds in a frame whose
visible minimap markers are orange) in the story file.

## [2026-08-17] lint | Remove unreachable minimap radar leftovers

Removed unreachable US-015 minimap radar leftovers following the US-027 rejection: deleted
`src/flyff_bot/features/vision/minimap_radar.py` and its unit tests, removed `SearchMode.MINIMAP_RADAR`
and unused radar parameters from `SearchController`, removed `BotStatus.SEARCH_MINIMAP`, and removed the
`ui.status_search_minimap` locale entry pair. Updated architecture and glossary.

## [2026-08-17] synthesis | Anchor-relative target verification (US-029)

Recorded the anchor-relative target-header geometry, the full per-tick diagnostic metrics, and the
operator-tunable match thresholds delivered by US-029. Replaced the architecture claim that the HP
and name crops come from a configured target-bar sub-region with the `AnchorOffsetRegion` offsets
measured from the matched anchor, and noted the fixed-pixel HUD assumption this shares with US-026:
`cv2.matchTemplate` is not scale invariant, so the mechanism gives translation invariance only.
Documented why the raw HP measurements live on `TargetVerificationMetrics` while the fields on
`TargetVerificationResult` stay anchor-gated (`CombatController` kill evidence and `SelectedTarget`
equality behind `TARGET_CHANGED`). Added glossary entries for anchor-relative ROI, match threshold,
and diagnostic metric.

## [2026-08-17] synthesis | Monster stats OCR diagnostics (US-030)

Recorded the monster-kills HUD OCR instrumentation delivered by US-030: `MonsterStatsFeed.read()`
returning the typed `MonsterStatsMetrics` value object instead of `int | None`, the retained best
`cv2.matchTemplate` score on the below-threshold path, the `MonsterStatsStatus` feed-health states,
and the dashboard panel's five read-only rows. Documented why `PerceptionPipeline` keeps the prior
`monster_kill_count` on a failed reading (the exact `+1` kill delta `CombatController` relies on),
and stated the shipped limitation that no monster-stats anchor template exists in `models/`, so the
desktop app reads the fixed normalized ROI with `anchor_configured` false.

## [2026-08-17] synthesis | Movement model and stall detection corrected (BUG-009)

Recorded the dead-reckoning and stall-detection corrections delivered by BUG-009: `A`/`D` joining
the arrow keys as character turns, `S` walking the estimate backwards at the new
`MovementModel.backward_speed_units_per_second` that replaced the unused strafe rate, and
`StallDetector` trading its consecutive-sample counter for an elapsed-time accumulator measured
outside a centred player-model mask, held rather than cleared across non-commanded ticks inside the
movement grace. Amended the US-019 paragraph, which still described the sample-counting comparison.
Documented why the stall verdict no longer latches (`_register_stall` consumes the evidence, so
`Supervisor` sees `STUCK` for the registration tick only) and why a stalled cell can never become
the retreat anchor. Stated the known limitation that the centre mask leaves the HUD bands sampled
and that the mask fractions are uncalibrated estimates.

## [2026-08-17] synthesis | Combat targeting lockout and engagement timeout (BUG-010, US-031)

Recorded the combat-thrashing fix: `CombatController`'s `TargetLockout` list, registered on every
terminal engagement exit including a confirmed `TARGET_DEAD`, filtered by `_best_candidate()` inside
`target_lockout_radius_pixels` for `target_lockout_seconds`, and deliberately surviving `_reset()`
because `_reset()` is what runs on the failure paths. Documented `engagement_timeout_seconds`
measuring elapsed time since the last observed HP decrease and evaluated after the kill-count and
HP-zero checks so a kill on the timeout tick still counts. Noted the orchestrator change that limits
the staged-search idle-timeout reset to verified engagements, without which the lockout retry cycle
sat just under `SearchConfig.idle_timeout_seconds` and camera recovery never ran. Recorded
`EngagementBreakReason` travelling on `CombatDecision`/`DashboardUpdate` rather than `WorldState`,
and the two screen-space limitations of the lockout anchor. Linked BUG-010 and US-031, which this
change delivered together.

## [2026-08-17] synthesis | Timed power-up hotkeys and dynamic UI configuration (US-016)

Recorded the interval-driven power-up subsystem: `PowerUpScheduler`'s per-entry elapsed-time
accumulators advancing only across stepped ticks, the single `halt()` call on the orchestrator's
standby branch that freezes every countdown for pause, lost focus, goal completion, and emergency
stop alike, and the `step`/`confirm` split borrowed from `PathingController` that holds an
unconfirmed trigger instead of spending it. Documented why `PowerUpConfig.stagger_seconds` is a floor
rather than the observed gap — one dispatch per 100 ms tick, and blocking the Qt GUI thread to reach
a true 30 ms spacing was rejected — and why `update_config()` preserves countdowns for unchanged
key/interval positions. Noted the deliberate divergence from `vitals_config_from_dict`: a stored
empty entry list stays empty rather than resurrecting defaults. Linked `PowerUpPanel` as the
row-owning presentation widget and its persistence path `data/powerups_config.json`.

## [2026-08-17] synthesis | OCR target name verification and whitelist matching (US-032, BUG-011)

Recorded why rigid `cv2.matchTemplate` name verification could not be fixed by retuning its
threshold: the HUD is drawn at a fixed pixel size, so the anchor-relative crop geometry was already
correct, but the 125x35 name rectangle is mostly world background whose grass/sky/dirt varies while
the glyphs do not — the shipped `models/target_flame.png` scored 1.00 on the 1276x747 capture it was
cropped from and ~0.25 on a 2559x1439 capture of the same monster. Documented the replacement:
`preprocess_target_name_region()` masking the one fixed pale-yellow nameplate fill colour with
`cv2.inRange` before OCR, `match_whitelisted_name()` resolving `Flame <Lvl 175>` by normalized
containment, and only the canonical whitelist entry reaching `SelectedTarget.name` so US-024's
target-changed equality stays quiet. Noted `TargetNameStatus` naming a missing Tesseract install
separately, because that failure is indistinguishable from BUG-011 at the dashboard. Recorded the
two deliberate departures from US-029's measure-everything rule — OCR gated on the accepted anchor,
and the reading cached against the previous tick's mask — with the ~75 ms subprocess cost against a
100 ms Qt timer as the reason, and the deleted name-threshold spin box as an obsolete control.

## [2026-08-17] synthesis | Monster-stats OCR engine diagnostics and anchor wording (BUG-012)

Recorded why a missing Tesseract install reached the dashboard as "OCR failed": `MonsterStatsReader`
collapsed every recognizer exception into `OCR_FAILED`, so the one failure an operator can act on was
indistinguishable from one they cannot. Documented `MonsterStatsStatus.ENGINE_UNAVAILABLE` and the
`LootOcrError`-code branch that produces it, following US-032's `TargetNameStatus` precedent, and why
the residual broad handler stays (the `TextRecognizer` Protocol admits arbitrary exceptions, and the
Qt timer tick must not see them). Noted `resolve_tesseract_executable()` probing `shutil.which()` then
the two documented Windows install directories, because the official installer does not extend `PATH`
— the actual reason OCR failed on a complete install — and the widening of the `ENGINE_UNAVAILABLE`
mapping from `FileNotFoundError` to `OSError`, ordered after the `SubprocessError` branch. Recorded
the reworded shipped anchor row: the fixed placement region is the intended mode, so stating that no
template is configured framed it as a missing configuration.

## 2026-08-18 — synthesis: US-034 background-independent monster stats

Ingested US-034 into `architecture.md`. Recorded the measurement that drove it: the stats HUD is
transparent, and the client renders every glyph in the constant colour BGR `(255, 209, 249)` = HSV
`(146, 46, 255)`, so keying that colour isolates the text where CLAHE + `adaptiveThreshold` kept the
scenery behind the panel — verified on both shipped screenshots, whose backgrounds are unrelated.
Noted that the same mask is what makes `data/monster_stats.png` usable as an anchor template
(`1.00` match against the reference screenshot versus `0.67` for raw colour, threshold `0.85`), which
reverses the note added on 2026-08-17 that the fixed placement region is the intended mode: that note
recorded a consequence of having no working template, not a design preference. Recorded the removal
of `MonsterStatsStatus.ANCHOR_NOT_FOUND` in favour of `MonsterStatsMetrics.source`, since a missed
anchor now falls back to the fixed region and the operator needs to know which crop produced the
number rather than that a reading did not happen. Also recorded the three combat-side changes
(sampling interval, baseline-gated increase instead of an exact `+1`, kill verification on by
default) and the replacement of the `QTimer` tick with `SessionWorker`, which brings the desktop app
back in line with the project's own rule that the Qt GUI thread never runs OCR.

## 2026-08-18 — synthesis: US-035 measured minimap odometry

Ingested US-035 into `architecture.md` and `glossary.md`, and ingested the operator's calibration
recordings as `../sources/2026-08-18-minimap-odometry-calibration.md`. Recorded the ring geometry in
client-area coordinates (88.0 px from the right edge, 106.5 px from the top, reproduced within
0.25 px across both zoom levels and both bursts) and the 29-row re-basing that reconciles it with the
whole-window measurement of the feasibility spike.

Corrected two claims the spike and the story carried. The spike's 0.6-0.9 px systematic underestimate
is not an artefact of its synthetic `BORDER_REFLECT` edges: `cv2.phaseCorrelate` returns (0.5, 0.5)
for identical even-sized inputs, and subtracting that offset recovers known shifts to within 0.03 px.
And a zoom change does not leave the correlation response untouched as the story assumed — a 2x
step collapses it to 0.062, below the gate — but the zoom-signature check is still required,
because the gate only rejects the two frames spanning the change while every measurement afterwards
correlates cleanly in a different unit.

Recorded the fitted constants and what they replaced: forward speed 9.4 minimap px/s (was a guessed
60 units/s) and turn rate 240 deg/s (was a guessed 90 deg/s). The turn rate is the consequential one:
the previous default 0.15 s pathing turn pulse would have swung 36 deg past a 25 deg tolerance and
oscillated, so the pulse is now 0.08 s. Recorded that backward speed was removed rather than fitted,
since no `S` burst was recorded and no controller dispatches `S`; the minimap observes backward motion
regardless. Recorded that the marker's nose is resolved by the third moment of its projection rather
than by a sign constant, because the farthest-point heuristic the spike used flipped on 8 of 53
recorded turn frames while the skew flipped on none.

Also recorded the unit rename across the navigation feature (`cell_size_pixels`,
`leash_radius_pixels`, `distance_pixels`), which makes the minimap pixel visible in the code rather
than only in the story, and the repair of the navigation-automation import cycle that had made
`flyff_bot.features.navigation.tracking` unimportable without initialising the automation package
first.

## 2026-08-18 — US-037 leash enforcement synthesis

Recorded that the patrol leash stopped being decorative. `leash_radius_pixels` had been validated,
carried in `NavigationSnapshot`, and drawn as a circle by the path inspector while `RoutePlanner`
considered every recorded hotspot regardless of distance from the session anchor, so the drawing
promised a constraint the engine never applied. The bound is now `LeashBound` around the origin of
the relative navigation frame — the session start point, which is why no second anchor is
configured — and it filters both goal selection and Dijkstra expansion, so no waypoint of a leashed
route can lie outside it.

Recorded the one case the constraint is deliberately dropped for: a character that is already
outside the bound. `RoutePlanner.return_route` searches unconstrained and stops at the first cell
inside, because walking back in is only possible through the cells the character actually stands
among; refusing to leave the bound there would strand the session instead of recalling it.

Recorded that the drawn radius and the enforced radius are one value on `PathingController`, so the
inspector cannot describe a radius the planner does not apply, and that a runtime change to it takes
effect at the next replan. The radius is operator configuration rather than learned state, so it
survives a map reset or profile load.

Recorded the re-derived default. The previous 50 was carried over from before the US-035 unit rename
and derived from nothing; now that the number constrains behaviour it is the measured usable minimap
surface radius of 62 px, which defines the camp as the terrain visible around the anchor on the
minimap and is already expressed in minimap pixels. No persisted operator setting for the leash
exists, so nothing was silently reinterpreted.

Recorded that a sighting arriving without a known viewport is no longer placed at a fixed distance
ahead but dropped, which removed the last spawn-distance fallback literal. The remaining
bounding-box distance constants are now named and documented as provisional; the fitted
inverse-projection relation of US-037 criterion 1 stays blocked on approach sequences that must be
recorded on Windows.

## 2026-08-18 — synthesis: US-041 spawn distance calibration harness

Recorded the second developer calibration harness, `scripts/capture_spawn_distance_samples.py`, and
the architecture rule it shares with `capture_minimap_samples.py`: offline harnesses live in
`scripts/`, are never imported by `flyff_bot`, depend inward on the same feature modules the
application uses so that what they measure is what the application sees, and obey the same
foreground and emergency-stop boundaries.

Recorded what a walk-in approach actually measures. The client stops the character at melee range,
so the absolute distance to a mob is never observable; the harness records the travel that still
remains from each frame to the stopping point, which turns the pinhole relation `d = a / h + b` into
`remaining_travel = a / h + (b - r_melee)`. The inverse-height coefficient is recovered unchanged and
the fitted intercept carries the melee stopping distance folded into it, which is the second of the
two options US-037 criterion 1 allows. Remaining travel is accumulated backwards from the stop, so an
unmeasured odometry increment invalidates only the frames before it rather than silently
under-counting the whole run.

Recorded that `scripts/` is now type-checked and on the pytest import path, because the manifest
schema, sample extraction, curve fit, and window-safety gate are unit tested.

No measurement was ingested: US-041 delivers the instrument. US-037 criteria 1 and the fit-dependent
bullets of criterion 2 stay open until an operator records approach sequences on Windows and the
result is ingested into `docs/sources/`.


## 2026-08-18 — synthesis: US-042 automated camera alignment

Recorded the standardized camera alignment routine in the architecture page and glossary. The zoom
hard-stop and ~45° pitch protocol US-041 wrote down as an operator instruction is now executed by
`CameraAligner`, which the farming pre-flight (`FarmingMode.ALIGNING`) and the spawn distance capture
harness both run, so the calibration state and the farming state cannot drift apart.

Recorded that the routine dispatches nothing blind: it re-checks the emergency stop and foreground
focus before every step and after the last one, and the new guarded wheel path centres the cursor
over the client area because Windows routes wheel input by cursor position. A failed pre-flight
pauses the session with a localized failure badge rather than farming on an uncalibrated
perspective, and the blocking sequence runs on the session worker thread, never on the Qt GUI thread.

No measurement was ingested: the ~45° pitch remains the protocol US-041 documented, and the
coefficients of the distance relation still wait on recorded approach runs.


## 2026-08-18 — synthesis: US-036 navigation profile anchoring

Recorded that a navigation profile now states which frame its coordinates belong to. The architecture
page describes the stored landmark (greyscale minimap disk, capture coordinates, heading, zoom
signature), the five load outcomes, and why loading is a decision rather than a file read: before
this, a loaded profile was silently reinterpreted relative to wherever the new session happened to
start, so its routes and hotspots pointed at an arbitrary offset.

Recorded that matching reuses the US-035 odometry machinery instead of duplicating it — the same
surface preparation, the same response-gated phase correlation, and the same map-scroll-to-player sign
rule — and that only the translation is recovered, because the north-up minimap already makes rotation
absolute and the zoom signature is checked rather than solved for.

Recorded the ADR-003 consequence as implemented: schema version 2 is the only format, version 1 is
rejected by name, and `save_spatial_map` / `load_spatial_map` were deleted in favour of
`save_profile` / `load_profile` over a `NavigationProfile` rather than kept as compatibility shims.

No measurement was ingested. The matching thresholds are the ones the feasibility spike already
measured (0.30 response gate; 0.665-0.928 for genuine overlap against -0.052 for unrelated content),
and the confidence separation is now asserted against the shipped frames in
`tests/unit/test_profile_anchoring.py`. The usable re-anchoring radius inside the one-surface-radius
bound remains an open field measurement, as does the manual Windows walkthrough US-036 lists.


## [2026-08-18] synthesis | Camera alignment direction and pitch keys (BUG-014)

Corrected the camera alignment protocol recorded for US-042: Flyff zooms *out* on a forward wheel
rotation, so the fifteen backwards notches the architecture page and glossary described zoomed the
camera in towards the character, and the count is now thirty so a fully zoomed-in start still reaches
the engine's clamped maximum. Recorded that camera pitch is bound to `VK_UP`/`VK_DOWN` and that the
`VK_PRIOR`/`VK_NEXT` holds the routine dispatched are unmapped for pitch in the standard client, which
left the elevation at whatever the operator had last set — the ~45° standardization the distance model
depends on never happened. The pitch keys now come from the single `controllers.py` definition rather
than a second set of constants in `camera_alignment.py`.

No measurement was ingested. The notch count is an overshoot bound, not a measured zoom range, and the
0.8 s / 0.35 s pitch timings still await confirmation against a live client; the fitted coefficients of
the distance relation remain open. Moved BUG-014 to fixed bugs.


## [2026-08-18] synthesis | Approach target tracking and minimap zoom initialization (US-043)

Recorded that a calibration walk-in now follows one mob rather than re-picking the most confident
candidate per frame. `ApproachTargetTracker` acquires the target on the first frame that detects it,
as the candidate closest to the viewport's vertical centreline, and matches every later frame against
the previous tracked box by bounding-box overlap (0.2 IoU) and centroid proximity (120 px), with a
two-frame miss budget after which the target counts as lost rather than re-acquired. Manifest schema
version 2 marks the tracked mob per frame; version 1 runs are rejected, not migrated (ADR-003).

Recorded the minimap zoom-out hard stop as the first step of the viewport pre-flight. The click point
is derived from the located `MinimapGeometry` at a measured offset of (-66.5, +45.5) px from the ring
centre, read off the client-area stills shipped under `data/assets/fixtures/minimap/`, where the
button's pale disk spans x 1442-1451 and y 146-156 against a located ring centre of (1513.0, 105.5).
A widget that cannot be located reports `MINIMAP_NOT_FOUND` before any input is dispatched.

Widened two odometry tolerances against terrain variation: the zoom signature tolerance from 12 % to
20 %, and the ring locator's angular deviation bound from 15.0 to 20.0. The 12 % figure was fitted to
the 4.2 % spread inside one recorded burst and dropped contiguous linear runs into `degraded`. No new
measurement was ingested for either bound; the 20 % tolerance still sits below the 24.6 % step between
the two recorded zoom levels, but that margin is now thin enough that the scale-mismatch test states
its intent relative to the tolerance instead of pinning the recorded pair. The fitted coefficients of
the distance relation, and the 0.8 s / 0.35 s pitch timings, remain open. Moved US-043 to completed
user stories.


## [2026-08-18] synthesis | Injected pointer move for wheel input (BUG-015)

Recorded why the camera half of the US-042 alignment left the zoom untouched while its minimap and
pitch steps worked: `scroll_wheel_while_guarded` relocated the pointer with `SetCursorPos`, which
teleports the cursor without placing a move into the injected input stream the client reads, so a
client that tracks the pointer from move events kept hit-testing the notches against the position it
had last seen — the minimap zoom-out button the preceding clicks had left it on. The architecture
page now states the invariant that a pointer relocation preceding synthetic wheel input is dispatched
as `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` through `SendInput`, normalized
onto the 0-65535 virtual-desktop range, and is given 0.15 s to be processed before the first notch.
Two guards were recorded with it: the emergency stop and foreground focus are checked before the
pointer moves, and an unmeasurable client rectangle dispatches nothing rather than scrolling wherever
the pointer sat.

No measurement was ingested. The 0.15 s settle is a conservative bound, not a measured client
latency, and the notch count, the 0.8 s / 0.35 s pitch timings, and the fitted coefficients of the
distance relation all remain open. Moved BUG-015 to fixed bugs.

## [2026-08-19] ingest | Target server clarification: Entropia Flyff PServer

Ingested the target server specification (`docs/sources/2026-08-19-target-server-entropia-pserver-clarification.md`),
clarifying that the project is built for the Entropia Flyff private server (PServer, `https://entropia.fun`) running
the classic native Windows client (`neuz.exe`). Updated `docs/wiki/project-overview.md`, `docs/wiki/architecture.md`,
`docs/wiki/glossary.md`, and project documentation.

## [2026-08-19] synthesis | Operator-selected target monster and early perception filtering

Recorded US-038 on `docs/wiki/architecture.md`: the dashboard's target-monster dropdown and the single
fan-out (`connect_target_mob_selection`) that applies one selection to `OpenCVDnnYoloDetector`,
`TargetVerifier`, and `FarmingOrchestrator` live, plus the reason the filter sits in YOLO decoding
rather than in candidate selection — a discarded monster never enters `WorldState.visible_mobs`, so
neither prioritization nor anchor template matching runs for it.

No measurement was ingested. Whether restricting the anchor templates to one mob measurably changes
per-frame verification cost was not measured; the change is argued from the number of
`cv2.matchTemplate` calls per frame, not from a timing. Moved US-038 to completed user stories.

## [2026-08-19] synthesis | Combat obstacle stalls and adaptive re-navigation

Recorded US-039 on `docs/wiki/architecture.md`: why the combat approach stall has to be sampled by
`FarmingOrchestrator` rather than by `PathingController` (the game client walks the character after a
target click, so no movement key is dispatched and `StallDetector` reads the tick as evidence-free),
the shared strike counter behind `EngagementBreakReason.OBSTACLE_STALL` and `ENGAGEMENT_TIMEOUT`, the
escalation from a 4.0 s lockout plus a re-positioning sweep to a 30.0 s unreachable lockout on the
second consecutive failure, and `FarmingMode.REPOSITIONING` as a bounded reuse of `SearchController`.

No measurement was ingested. The approach stall threshold and the re-positioning step counts are
carried over defaults and estimates, not values fitted against recorded client frames; the peripheral
centre-mask fractions they depend on were already marked as estimates in BUG-009. The named
consequence — a damage-free fight now breaking at 5.0 s instead of 10.0 s — is reasoned from the
configured timeouts, not observed in a live session. Moved US-039 to completed user stories.

## [2026-08-19] synthesis | Verified forward wheel zoom-out direction and 20 notches (BUG-016)

Recorded BUG-016 on `docs/wiki/architecture.md` and `docs/wiki/glossary.md`: Entropia Flyff (`neuz.exe`) zooms
the 3D camera *out* to its hard stop on forward wheel rotation (`+WHEEL_DELTA`), and twenty notches outrun the
engine's zoom range. `CameraAligner.align()` dispatches 20 positive notches to `scroll_wheel_while_guarded`. In
addition, `scroll_wheel_while_guarded` now sets the hardware cursor via `SetCursorPos` in addition to injecting
`MOUSEEVENTF_MOVE` absolute mouse events, ensuring the pointer is centered over the game viewport across DPI-scaled
and multi-monitor setups before wheel notches are sent. Moved BUG-016 to fixed bugs.

## [2026-08-19] synthesis | Multi-target monster selection and per-mob kill quotas

Recorded the multi-target US-035 on `docs/wiki/architecture.md` and `docs/wiki/glossary.md`: why kill
attribution has to come from the engaged candidate's class rather than the Monster-Stats HUD (the HUD
reports one global count with no breakdown), how `KillGoalTracker` turns completed quotas into the
active targeting whitelist that detection, verification, and combat all follow, the SQLite kill log
(`data/kill_log.sqlite3`) that carries progress across pauses, and the cooperative `WM_CLOSE` a
completed session may post. Noted that this story's panel replaces the single-select dropdown from
US-038 rather than joining it, because two controls writing the same whitelist would contradict each
other, and amended the US-038 section accordingly.

No measurement was ingested; every claim is read from the implementation and its tests. Two user
stories now carry the identifier US-035 — the measured minimap odometry work and this one — and are
distinguished only by file name; the architecture section and the story index say so explicitly
rather than renumbering an already-completed story. Moved the multi-target US-035 to completed user
stories.

## [2026-08-19] synthesis | Unrecoverable stuck recovery and spawn re-anchoring (US-040)

Recorded US-040 on `docs/wiki/architecture.md` and `docs/wiki/glossary.md`: why the last-resort
recovery is a teleport item rather than another movement manoeuvre, why one no-progress accumulator
replaces a timer per unstuck stage, and why a target click is deliberately not counted as progress
while landed damage and a reconciled kill are. Documented the two-moment reset — the escaped cell is
blamed at dispatch while its position is still known, the position estimate is re-anchored only after
the settle window closes — and the spawn anchor's ownership by the navigation profile rather than the
session. Noted the unassigned-hotkey path that pauses and alerts instead of silently pressing nothing.

No measurement was ingested; every claim is read from the implementation and its tests. The manual
in-client walkthrough named in the story's verification section has not been performed. Moved US-040
to completed user stories.

## [2026-08-19] synthesis | Authoritative world geometry and goal-driven zone navigation (US-045)

Recorded US-045 on `docs/wiki/architecture.md` and `docs/wiki/glossary.md`: the offline client world
extractor (`.wld`, `.rgn`, `.lnd`, `.dyo`), slope-derived impassable rectangles, the corridor-local
visibility-graph A* planner, `WorldRegistration`, `VectorZoneNavigator`, and the World Data & Maps
dialog.

Measurements ingested, taken against the operator's own Entropia client tree rather than a fixture:
Eden extracts 83 spawn zones, 6 monster classes, 348 impassable slope rectangles from its one loose
terrain block, and 1 placed-object footprint, in 0.01 s. Routing over those 349 obstacles solves
intra-zone patrol legs in 0.26 ms median and zone-to-zone hops in 2.5 ms median with a 36 ms worst
case; 6 of 72 zone pairs report blocked and fall back to learned pathing. The story's sub-millisecond
figure holds for the short legs a patrol walks, not for cross-block queries.

Three assumptions are recorded as assumptions, not findings. The monster-id to detector-class
mapping is ascending-order pairing, because the client's own table ships only inside the obfuscated
`data.one`. The minimap-pixels-per-world-unit scale is a provisional constant for the same reason
US-035 records for every other world-unit conversion. And the `.dyo` record offsets are read off a
single shipped file, guarded by a region-bounds check rather than a schema. Moved US-045 to
completed user stories.

## [2026-08-19] ingest + synthesis | Coordinate-only live XYZ and 3D navigation (US-048)

Ingested `docs/sources/2026-08-19-entropia-client-navigation-data-extraction.md` into the
architecture, glossary, roadmap, and index. Recorded the two complete client fingerprints, the
single module-relative player global per build, the exact pointer-width plus 12-byte XYZ read
boundary, retained loose `.lnd` height fields, elevation-aware A*, configured long-range dispatch,
live position stall recovery, GPS source state, and 3D-enriched inspector. Recorded the
durable decision that forbids broader state reads, scanning, writes, injection, and hooks.

The same synthesis records the evidence limit: only 153 of 3,861 declared terrain blocks have loose
height data, object/collision mappings and teleport semantics are incomplete, and dynamic server
state is unavailable offline. Focused affected suites pass, but the full repository gate has not
yet run and the Windows live-client walkthrough remains unchecked; no 100% fault-free navigation
claim is made. Moved US-048 to completed user stories.

## [2026-08-19] synthesis | Session event log and transition diagnostics (US-049)

Recorded the completed US-049 implementation in the architecture and glossary pages and the phased
roadmap. Added `flyff_bot.features.diagnostics` (`SessionEventLogger`, `SessionEvent`,
`SessionEventKind`) as a standalone, fail-safe, non-Qt logging feature; routed every
`FarmingOrchestrator` mode transition through one new `_set_mode()` chokepoint instead of direct
`self._mode` assignment; added `WindowsInputController.foreground_window_info()` for `FOCUS_LOST`
diagnostics without widening the orchestrator's existing Win32-free adapter contract; and added the
localized `EventLogPanel` dashboard widget fed by a new `DashboardUpdate.events` field. Full gate
(`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`) passes at 719 passed / 3 skipped,
92.53% coverage. Moved US-049 to completed user stories.

## [2026-08-19] synthesis | Responsive tabbed dashboard and UI refactoring (US-050)

Recorded the completed US-050 presentation refactoring in the architecture, glossary, roadmap, and
story index: one pinned status/action header above five localized, internally scrollable tabs for
Dashboard, Combat & Targets, Vitals & Buffs, Navigation & World, and Diagnostics & Logs. Documented
that selecting a tab changes visibility only; perception, navigation, diagnostics, controller, and
`DashboardUpdate` feeds continue updating hidden pages, while stable top-level geometry replaces the
old accordion and `adjustSize()` behavior.

Recorded the deliberate control distinction: styled switches change boolean configuration, while
the eleven former panel-visibility checkboxes were removed because tab selection now owns view
navigation. The dedicated UI emergency-stop button was removed from the header, but the `Escape`
shortcut, global `END` hook, Qt emergency signal, orchestrator latch, foreground guards, and input
release paths remain unchanged. Expanded Dark Slate QSS covers tabs, scroll areas, switches, and
child controls, with all user-visible tab labels, controls, and tooltips synchronized in English
and German.

The full `./scripts/check.ps1` repository gate passed: 750 tests passed, 2 skipped, and coverage was
92.54%. The Windows live-client visual and interaction walkthrough remains outstanding, including
tab responsiveness and confirmation of both emergency-stop keys against `neuz.exe`; no automated
result is treated as live-client validation. Moved US-050 to completed user stories.

## [2026-08-19] synthesis | Fast live collision recovery for combat approaches (BUG-017)

Recorded BUG-017 in `docs/wiki/architecture.md`: the combat-approach stall detector receives the
latest supported live XYZ sample and timestamp, and a confirmed stall calls the same bounded
strafe/backstep, tangent-replan, and repeated-coordinate temporary block path used by autonomous
live navigation. The orchestrator drains that local evasion before its generic rotate-and-roam
repositioning sweep, while a trustworthy learned minimap map retains its obstacle penalty and
minimap/frame evidence remains the fallback when live coordinates are unavailable.

No raw source or live measurement was ingested; these claims are derived from the implementation
and regression tests. The automated repository gate passed, but a foregrounded Windows
`neuz.exe` walkthrough against real invisible collision geometry remains outstanding. Moved BUG-017
to fixed bugs.

## [2026-08-19] synthesis | Packed client archive extraction and complete terrain (US-052)

Recorded US-052 in `docs/wiki/architecture.md` and `docs/wiki/glossary.md`: the client's
`<world>.hdr` index layout, the file-name keystream that obfuscates `<world>.one` entries, and the
known-prefix lookup that finds a terrain block without ever learning the index's opaque identities.
Corrected the US-045 paragraph that stated the packed archive was permanently out of reach.
Documented world-map schema version 3, which moves height grids out of the JSON document into
`.lnd` height fields beside it, and the three typed extraction diagnostics that skip an unsupported
archive index, an undecodable packed block, or an unknown placed-object layout without costing a
region its terrain.

Evidence is the shipped `2026-08-19` extraction audit plus a run of the new
`--extract-world` command against the operator's own unmodified Entropia installation: 1,116
decoded height fields against the 153 loose blocks the audit counted, and Eden resolving all 25 of
its declared blocks. The full `./scripts/check.ps1` gate passed at 768 tests passed, 3 skipped, and
92.44% coverage. No live `neuz.exe` session was run, so terrain accuracy against the client's own
physics over newly mapped blocks remains outstanding. Moved US-052 to completed user stories.

## [2026-08-19] synthesis | Unrestricted read-only client asset extraction (ADR-005)

Recorded ADR-005 establishing full read-only access to local Entropia client files (`Data/World/`,
`.one`, `.hdr`, `.lnd`, `.wld`, `.rgn`, `.dyo`, `.inc`, `neuz.exe`, etc.) for offline static data
extraction and NavMesh baking tooling. Decoupled offline asset parsing from runtime safety boundaries,
confirmed the non-destructive read-only requirement on local installations, and reinforced the
repository safety boundary forbidding commits of raw proprietary client files.

## [2026-08-19] synthesis | Async farming telemetry and offline datasets (US-054, in progress)

Recorded the landed `flyff_bot.features.telemetry` path in the architecture and glossary: a
non-blocking, bounded JSONL worker, local transactional SQLite mirror, numeric schema-v1 event
contracts, and zstd Parquet export for target decisions, navigation trajectories, and kill cycles.
The full repository gate passed at 758 passed / 2 skipped / 92.15% coverage.

Documented the incomplete integration rather than treating the generated contracts as live
evidence: US-052 NavMesh/raycast fields are explicit `null` values when their producer is absent;
navigation/stall episode instrumentation and the complete four-part kill-cycle timing decomposition
remain open; session metadata producers and candidate-lockout integration are also incomplete. The
two Windows manual checks for an actual farming session and direct Parquet loading remain
outstanding, so US-054 stays in progress and was not moved to completed stories.

## [2026-08-20] synthesis | GPS-only vector navigation and configurable client profiles (US-053)

Recorded US-053 in the architecture and glossary: operator-editable, SHA-256-fingerprinted client
position profiles with embedded defaults only when the profile file is absent; explicit invalid-
profile and unknown-build diagnostics; and the GPS-only precondition that blocks and clears all
vector-route movement when no finite live XYZ sample is available. The retained minimap-fallback
source marker is not a vector-navigation fallback. Documented direct client-world-unit routing and
the World Data dialog's `QSettings` persistence of stable region, map, zone, and quota identities.

No raw source or live measurement was ingested; these claims are derived from the implementation and
regression tests. The automated repository gate passed. The Windows `neuz.exe` walkthrough for live
GPS, focus loss, and dialog persistence remains outstanding. Moved US-053 to completed user stories.

## [2026-08-20] ingest | Read-only process memory access policy (ADR-006)

Recorded ADR-006 generalizing runtime `ReadProcessMemory` safety boundaries to permit unrestricted read-only
access to game client process memory for automation, navigation, perception, and telemetry state extraction
(coordinates, camera state, projection matrices, player/actor data, and client structures). Replaced the
coordinate-only limitation across `AGENTS.md`, `CLAUDE.md`, and project rules while preserving non-invasive
safety invariants (strictly no memory writes, no code injection, no hooking, and no anti-cheat evasion).

## [2026-08-20] synthesis | Offline O3D geometry and multi-layer NavMesh foundation (US-055, in progress)

Recorded the implemented offline foundation in the architecture and glossary: strict version-22
O3D collision parsing from loose models or caller-supplied known-name model archive entries;
supported DYO scale/rotation/translation transforms; terrain-plus-resolved-collision world
geometry; and a deterministic multi-layer NavMesh query API with agent slope, radius, height, and
step constraints. The existing US-052 terrain and other live-routing fallbacks remain active, and
the new code opens neither the game process nor an input path.

Recorded the evidence boundary as well: the full repository gate passed at 780 tests passed, 2
skipped, and 89.15% coverage, but the implementation does not yet have Funnel-smoothed,
segment-validated paths, a CLI bake/persistence integration, telemetry-adapter wiring, a real
outdoor/complex-area reconstruction, or a foregrounded Windows/client traversal walkthrough.

## [2026-08-20] ingest | Fingerprinted camera state and projection reader (US-056)

Ingested the immutable camera static-analysis source into the architecture and glossary. Recorded
that supported x86/x64 profiles separate pointer-relative camera fields from the independent
module-relative projection RVA, and that pitch, yaw, FOV, and distance are derived from verified
matrices/vectors rather than unproven scalar fields. Updated ADR-006 to scope read-only runtime
access to exact fingerprinted fixed ranges and to clarify that `check.ps1` is a quality gate, not a
complete prohibited-API detector. The automated gate passed at 792 tests passed, 2 skipped, and
91.48% coverage; Windows live rotation, zoom, resize, sign, latency, restart, and minimize checks
remain outstanding.

## [2026-08-20] synthesis | Completed Funnel, persisted NavMesh, and telemetry polygon wiring (US-055)

Updated the US-055 architecture and glossary synthesis for completed offline NavMesh work: X/Z
Funnel string pulling over consistently oriented polygon portals, strict schema-v1 canonical
`.navmesh.json` persistence, and the offline `--extract-world --bake-navmesh` workflow. The optional
`--navmesh-map` provider now gives US-054 `player_navmesh_polygon_id` only from finite live GPS;
minimap fallback, missing mesh/position, and all candidate screen-to-world fields remain explicit
`null` rather than inferred.

The full repository gate passed on 2026-08-20 at 797 passed, 2 skipped, and 91.35% coverage.
US-052 and other navigation paths remain the live-routing fallbacks: this does not activate NavMesh
routing. Manual Windows/client-asset validation remains open for the supported collision/placement
formats, generated artifacts, bridge/archway/ramp traversal, live Funnel collision confirmation,
and live-GPS telemetry polygon output.

## [2026-08-20] synthesis | Completed farming telemetry and adaptive navigation dataset (US-054)

Updated the US-054 architecture and glossary synthesis from the implementation and regression
tests. `FarmingOrchestrator` now starts `TelemetryRecorder` with configured vector spawn-zone
metadata, while the CLI supplies the readable client digest, bot version, model paths, and optional
NavMesh digest. Its live-frame snapshots use finite GPS plus the loaded mesh for player polygon and
slope. Pathing lifecycle events now form navigation episodes with live-GPS trajectories, replans,
stalls, evasions, and final outcomes; controller lockout decisions and confirmed attack dispatches
are also recorded. Verified kills create reset-at-kill decision/navigation/combat/idle cycles whose
decision timestamp deterministically links reward and verification to Parquet target-decision rows.

Recorded the read-only camera-to-NavMesh candidate projection: a detected bottom-centre ray yields
world coordinate, relative distance/elevation, polygon, and path distance only on a measured mesh
hit. Every unavailable prerequisite or miss remains explicit `null`; no screen-space approximation
is stored as client-world data. The full automated repository gate passed on 2026-08-20 at 800
passed, 2 skipped, and 91.30% coverage. The manual Windows farming-session and direct Parquet-load
walkthroughs remain outstanding. Moved US-054 to completed user stories.

## [2026-08-20] synthesis | NavMesh-aware targeting and telemetry integration (US-058)

Updated the US-058 architecture and glossary synthesis from the implementation and regression
tests. Candidate enrichment now shares camera/GPS/NavMesh measurements between selection,
telemetry, and the diagnostic inspector: unreachable and outside-leash candidates are rejected,
valid 3D candidates rank by Funnel path distance, and unprojected candidates retain the existing
2D fallback. The first finite live-GPS sample is the session leash anchor, distinct from the
emergency-teleport spawn point.

Active approaches follow the baked Funnel route using the existing foreground- and emergency-stop-
guarded pathing dispatcher before issuing the target click. JSONL/SQLite and Parquet now carry the
measured geometry, route, trajectory, and timing fields directly. The full automated gate passed
on 2026-08-20 at 806 passed, 2 skipped, and 90.60% coverage. Windows/client validation of actual
reachability marking, Funnel traversal, and exported live telemetry remains unrun. Moved US-058 to
completed user stories.

## [2026-08-20] synthesis | Perception-side mob world positioning (US-057)

Recorded the US-057 architecture and glossary synthesis from the implementation and its unit tests.
Detections are now unprojected from their bounding-box bottom-centre ground contact point through the
US-056 camera state and intersected with the baked NavMesh inside the perception tick, so targeting,
telemetry, and the inspector share one measured estimate instead of casting separate rays. A missing
camera, live GPS, mesh, or ray hit stays explicitly unmeasured.

`navigation.raycast` now holds the project's single Moller-Trumbore implementation plus a horizontal
chunk index; walking only the crossed cells resolves multi-layer geometry to the first visible surface
and measured 0.49-0.71 ms for twenty detections against a 512-polygon mesh. Exported target-decision
Parquet columns were renamed to `estimated_mob_x/y/z` and `estimated_mob_polygon_id` per ADR-003. The
full automated gate passed on 2026-08-20 at 823 passed, 3 skipped, and 90.77% coverage. The Windows
live-client walkthrough on open ground and bridges remains unrun. Moved US-057 to completed user
stories.

## [2026-08-20] synthesis | Pure authoritative vector navigation and multi-zone selection (US-059)

Recorded the completed US-059 implementation. Purged legacy minimap odometry (`MinimapOdometer`),
key dead reckoning (`MovementTracker`), 2D spatial heatmap learning (`SpatialMap`, `RoutePlanner`),
and minimap JSON profiles from production code. Gated navigation strictly on live GPS (`LivePositionReader`)
and authoritative 3D NavMesh extraction (`BakedNavMesh`), enforcing the strict invariant "no GPS, no bot".
Implemented multi-zone selection and sequential camp quota progression in `VectorZoneNavigator` and
`WorldDataDialog`. The full automated repository gate passed on 2026-08-20 at 608 passed, 2 skipped, and
88.77% coverage. Moved US-059 to completed user stories.

## [2026-08-20] synthesis | US-059 review remediation (BUG-019, BUG-020, BUG-021)

Reviewed the implementing commit `4a81b34` against the repository rules and corrected what it
claimed but did not deliver. `_poll_live_camera` guarded its freshness check against the *position*
sample timestamp, and since both call sites poll the position first, the camera reader was called
exactly once per session and `heading_degrees` froze at the first frame's yaw (BUG-019). The
emergency stuck monitor kept the removed minimap-pixel threshold while the orchestrator started
feeding it live GPS world units (BUG-020). Multi-zone selection existed only in the navigator API:
`WorldDataDialog` armed a single zone and no production caller reached `advance_to_next_zone`, and
the target/monster debug panels rendered their values from hardcoded f-strings instead of the
locale templates (BUG-021).

`WorldDataDialog` now lists camps as checkable entries, `PathingController.completed_zone_sweeps`
counts patrol laps without a confirmed kill, and the orchestrator hands the session to the next
selected camp after `PATROL_SWEEPS_BEFORE_ZONE_CHANGE` laps. `PositionSource.MINIMAP_FALLBACK` was
renamed to `UNAVAILABLE` because no fallback source exists any more, and 37 orphaned `Message`
members plus their `en.json` / `de.json` entries, the unused `tests/unit/minimap_fixtures.py`
loader, and a magic `0x70` hotkey fallback were removed. The duplicate `US-059` id on the draft
"continuous human-like movement" story was renumbered to `US-064`; the shipped minimap stills under
`data/assets/fixtures/minimap/` are kept as the measurement evidence the wiki cites. The gate
`35e21bf` left red (one ruff `F841` and one mypy `comparison-overlap` in the GPS-resume tests) is
green again. Full automated gate on 2026-08-20: 623 passed, 2 skipped, 89.09% coverage. The Windows
walkthrough of live camera tracking, multi-camp transit, and the teleport threshold remains unrun.

## 2026-08-21 synthesis - keyed client archives and quest farming (US-061)

Ingested
[2026-08-21 Entropia keyed archive and quest data static analysis](../sources/2026-08-21-entropia-keyed-archive-and-quest-data-analysis.md)
and synthesized it into `architecture.md`.

The 663 client archives US-052 refused as `UNSUPPORTED_ARCHIVE_INDEX` are a second archive
generation, not a corrupt one. Its index record opens with `int32 -1`, stores the entry start
negated, and reports a length 10 bytes short of the file; its identity is
`sha256("m1k3d3RS945TI!" + name.lower())`, which makes the archive name-addressable; and its payload
keystream advances with byte position, seeded from the file name's adjacent-character XOR and the
file's own length. Both salt literals sit beside the `.one` / `.hdr` and `.res` / `.hdr` extension
strings in `neuz.exe`. The decoder round-trips byte-exactly against 55 loose/packed file pairs.

That unlocked `flyff_bot.features.quests`: offline extraction of 1,434 quests (563 farmable) into
`data/quests/quests.json`, quest-to-spawn-zone resolution over the extracted world maps, sequential
quest queue progression inside `FarmingOrchestrator`, and a searchable `Quest Goals` dashboard tab.
Localized in English and German. Gate on 2026-08-21: 674 passed, 2 skipped, 89.22% coverage. The
live Windows walkthrough is outstanding.

## 2026-08-21 synthesis - offline farming value models (US-066)

Synthesized the US-066 implementation into `architecture.md` and `glossary.md`. No new source was
ingested; the durable facts come from the shipped code and the recorded US-054 dataset contract.

`flyff_bot.features.ml` is a second offline consumer of the US-054 Parquet tables. It joins one
supervised sample per executed target decision through the `target_decision_timestamp_ns` the
recorder already writes, correlates the navigation episode that ran between decision and kill for
corridor and trajectory geometry, and splits holdout data by whole session so no session appears on
both sides. Unselected candidates stay counterfactually unknown, unmeasured features stay `NaN` with
a paired missing indicator, and follow-up windows past the end of a session stay right-censored.

Five regularized linear heads (ridge, plus logistic for stuck risk) are fitted on numpy alone,
benchmarked on holdout sessions against per-head heuristic reference predictors, and exported as
self-contained ONNX graphs with a provenance `metadata.json`. Localized in English and German.

Correction recorded while implementing: importing the telemetry package before automation raised a
circular `ImportError`. `automation/orchestrator.py` now imports `CombatVerificationSource` from
`telemetry.models` and `TelemetryRecorder` under `TYPE_CHECKING`, and `telemetry/__init__.py` no
longer re-exports `geometry`, which the navigation layer it depends on also consumes.

Gate on 2026-08-21: 719 passed, 2 skipped, 89.70% coverage. Running the trainer against a real
recorded Windows session is outstanding.

## [2026-08-23] ingest | Official Entropia game wiki consultation

Ingested
[official Entropia Wiki access and inventory](../sources/2026-08-23-entropia-wiki-access-and-page-inventory.md)
into `project-overview.md` and `entropia-game-wiki.md`. Established the official gameplay-domain
consultation workflow, documented the GitBook `.md` endpoint and `llms.txt` index, and added a
260-entry sitemap-derived page inventory without copying wiki prose.

## [2026-08-23] synthesis | Teleporter extraction and dispatch (US-065)

Added the US-065 architecture section covering offline `TeleportOption.inc` extraction, typed
destination records, guarded no-OCR UI dispatch, and closed-loop arrival confirmation. Recorded
that live confirmation fails closed until a verified world-ID memory profile exists.

## 2026-08-22 — US-060 architecture synthesis

- Ingested implemented US-060 facts into architecture: combat class profiles, live engagement
  distance configuration, straight-route direct targeting, obstacle-aware approach hand-off,
  reduced spatial lockout, same-tick post-kill candidate evaluation, and localized dashboard controls.
- Recorded scoped verification and explicitly excluded two unrelated pre-existing POSIX/Python
  environment test failures from the story result.

## [2026-08-22] synthesis | Configured NPC quest interaction (US-062)

Synthesized configured NPC locations, position-based NavMesh approach, read-only dialogue evidence,
bounded retry/backoff, and queue safety into `architecture.md`. Recorded that client NPC identity and
live dialogue templates remain unverified and that Windows end-to-end validation is outstanding.

## [2026-08-23] correction | US-060 completion audit

Moved the combat-class story out of completed and synthesized its partial implementation status into
`architecture.md`: lockout and post-kill recovery are tested, responsive-targeting regressions and UI
wiring coverage are missing, preset engagement distances are unmeasured operator defaults, and live
Windows validation is outstanding.

## [2026-08-23] synthesis | Dungeon data and cooldown reader (US-063)

Synthesized offline keyed-archive dungeon extraction, empty-by-default fingerprinted cooldown
profiles, typed read-only degradation, dashboard presentation, and outstanding Windows/live-offset
verification into `architecture.md`.

## [2026-08-23] integration | Quest interaction dispatch (US-062 follow-up)

Wired `QuestInteractionController` into `FarmingOrchestrator`: explicit NPC position approaches use
NavMesh routing and interaction is now strictly click-based: the incorrect C-key fallback was removed.
Arrival clicks the measured NPC screen box, then `QuestMenuPerceiver` proves a generic/configurable
menu action with OCR before clicking its concrete row. Tesseract line geometry is parsed from bounded
TSV output and supplies the guarded row centre. Timeout retreat retains exponential backoff. Live
Windows OCR/menu validation remains outstanding.

## [2026-08-23] synthesis | Profile-driven player-stat reader (US-076)

Synthesized the US-076 implementation boundary into `architecture.md`: perception now prefers a
foreground-gated, SHA-256-bound, read-only player-stats snapshot over constructing player-vitals OCR.
Profiles are validated before handle creation and every snapshot is immutable with explicit
unavailability. The glossary defines the snapshot contract. Because repository evidence contains no
verified player-stat field offsets, the shipped registry remains empty and live values remain
explicitly unavailable until static-analysis and in-game verification provide x86/x64 profiles.

## [2026-08-23] synthesis | Player-stat diagnostics correction (US-076)

Synthesized the review correction into `architecture.md`: invalid pointers are distinct from
malformed reads, unavailable snapshots retain the last complete field-name set across repeated
failures, and profile bounds govern legitimate negative values.

## [2026-08-24] synthesis | Offline tactical simulator (US-072)

Synthesized US-072 into `architecture.md`: a seeded in-memory tactical simulator over extracted
maps with movement, spawn/respawn, calibrated combat/stall timing, quest objectives, typed RL
observations, Gymnasium-shaped reset/step semantics, and aggregate calibration. The boundary is
strictly offline and adds no client access.

## [2026-08-24] synthesis | Player-stat story completion (US-076)

Completed the US-076 acceptance record and moved the story to `completed/`. The implementation
remains evidence-safe: synthetic process tests cover bounded snapshots and diagnostics, while no
x86/x64 player-stat offsets are claimed as live-verified until operator validation supplies them.

## [2026-08-24] completion | Built-in teleporter emergency reset (US-051)

Synthesized US-051 into `architecture.md` and `glossary.md`: removed the generic long-range
anchor/blinkwing controller, made Flyff's built-in teleporter UI (US-065) the only teleport
boundary, and routed emergency reset through its guarded deterministic sequence. The operator now
selects a client-declared destination from extracted data; confirmation requires authoritative world
identity plus live position at that anchor within 2.0 seconds, while timeout latches emergency stop.
The story records live Windows validation as outstanding.

## [2026-08-24] completion | Combat class profiles and responsive targeting (US-060)

Added a direct post-kill reconciliation regression proving same-tick selection and guarded click
dispatch, exposed the combat-controller completion reset at the orchestration boundary, restored
US-060 to completed, and synthesized the closed criterion set into `architecture.md`. Preset
engagement distances remain unmeasured operator defaults and live Windows validation remains
outstanding.

## [2026-08-24] synthesis | Offline tactical RL environment (US-071)

Synthesized the completed US-071 contracts into `architecture.md` and `glossary.md`: typed bounded
observations, seven discrete tactical actions, deterministic masking, versioned progress rewards,
Parquet transition export, and a Gymnasium-compatible offline adapter. No live input dispatch or
expanded client access was added.

## [2026-08-25] synthesis | Hierarchical policy and interactive world map (US-073, US-074)

Synthesized the completed two-tier policy and interactive map into `architecture.md` and `glossary.md`.
Evidence is offline simulator/training, ONNX metadata and deterministic fallback, Qt interaction and
culling tests, localization checks, and synthetic timing budgets. The gate passed at 866 passed, 5
skipped, and 88.30% coverage. No Windows/live-client walkthrough, real-client convergence, exact
client performance, arbitrary object interaction, or live map-FPS measurement is claimed.

## [2026-08-25] synthesis | Closed learning loop (BUG-031)

Synthesized the repaired learning loop into `architecture.md` and recorded its invariants in
`../decisions/ADR-008-closed-learning-loop-invariants.md`: parameterized actions with per-instance
candidate identity, session- and episode-scoped transitions, per-interval reward attribution, a
75-column observation with explicit missing indicators, a supported CLI and UI path to a trained
artifact, and learned automation that fails closed with a synchronized diagnostic. Corrected the
stale US-073 claim that `PolicyRunner` substitutes `HeuristicPolicy` on a learned fault. The gate
passed at 906 passed, 6 skipped, and 88.2% coverage. No Windows or live-client walkthrough was run,
so live promotion of a trained artifact remains unverified.

## [2026-08-26] synthesis | Goal-driven quest execution and the objective bus (US-080)

Synthesized the completed US-080 goal sequence, objective bus, goal travel planning, per-objective
whitelist/zone/leash projection, goal-conditioned policy objective, and telemetry schema v4 into
`architecture.md` and `glossary.md`. Evidence is offline: goal-sequence, travel-planning, objective
switch, teleport-confirmation, refusal, timeout, telemetry, localization and Qt tests, with the gate
at 918 passed, 6 skipped, and 88.88% coverage. No Windows/live-client quest walkthrough is claimed,
and no new client access or input capability was added.

## [2026-08-28] synthesis | One action contract for simulator, exporter, and live policy (US-079, partial)

Synthesized the first US-079 acceptance criterion into `architecture.md`: `StrategicGoalKind`,
`TacticalActionKind`, `TacticalAction`, and the payload union are now declared once in
`features/policy/action_payloads.py`; the simulator's private four-member enum and the third
meaning of `TacticalAction` in `policy/models.py` are deleted; and `HIGH_LEVEL_ACTION_ORDER` is
derived from the shared wire order instead of being written out. Discrete index values are
unchanged, so `bug031-v1` artifacts stay readable. Evidence is offline: an AST-based single-
definition test plus wire-order and mapping tests, gate at 965 passed, 5 skipped, 89.20% coverage.
The remaining US-079 criteria (goal-conditioned observation, encoder parity, single versioned
reward configuration, contract-version rejection diagnostics) are explicitly still open.

## [2026-08-28] synthesis | One goal-conditioned, versioned decision contract (US-079, complete)

Synthesized the remaining US-079 acceptance criteria into `architecture.md`, replacing the partial
section. `ObjectiveKind` joined `features/policy/action_payloads.py` as the fourth shared vocabulary
and replaced the simulator's `QuestObjectiveKind`; the observation grew an eleven-column goal block
and is now `us079-v1` at 86 columns; the simulator and live encoders are asserted to produce one
identical vector for the same world state; `RewardConfig` cannot change a weight without declaring a
new version and `DEFAULT_REWARD_CONFIG` is stamped into every artifact and dataset it scored; and
`features/policy/contract.py` rejects a foreign artifact with a field-level diagnostic that is
localized in German and English. Evidence is offline: goal-conditioning, parity, reward-stamp,
per-field rejection and localization tests, with the gate at 994 passed, 5 skipped, 89.26% coverage.
No live `neuz.exe` shadow-mode session against the new contract is claimed, and no new client access
or input capability was added.

## [2026-08-28] synthesis | Static client catalog, source manifest and label join (US-083, partial)

Recorded the US-083 foundation layer in `architecture.md`. `features/client_data/` normalizes the
client's mover, drop, item, skill and NPC tables into a schema-versioned catalog in which every
record is either parsed or carries a typed rejection; mover numeric columns are located by the
client's own column header so a differently laid out table cannot yield a fabricated combat value.
`UnifiedClientExtractor` now parses and persists those rows instead of counting file names
(BUG-033). One versioned source manifest states each table's client digest, content digest, schema,
completeness, freshness rule, field provenance and exact production consumers, and refuses a
manifest with an unconsumed field or an undeclared table - which surfaced that nothing yet reads the
client's skill rows. The YOLO-label-to-mover join is a curated versioned artifact, because the
source analysis shows the symbol-to-id table is compiled into `neuz.exe` and not shipped; it fails
closed on every ambiguity rather than matching a similar name. Also pinned that the operator class
whitelist is applied inside YOLO decoding before NMS, and repaired four files the pinned formatter
had left syntactically invalid. Evidence is offline: 31 new catalog/manifest/join tests plus
whitelist regression tests; ruff and mypy clean across 296 files; the 172 tests covering the touched
files pass. The 11 failing tests in the full run belong to a concurrent US-084 session sharing the
working tree. No live `neuz.exe` session is claimed, and no new client access or input capability
was added. Criteria 4-12 of US-083 remain open.

## [2026-08-28] synthesis | Bounded tactical parameter space and hybrid tuning (US-084)

Recorded US-084 in `architecture.md`, `glossary.md`, and [ADR-009](../decisions/ADR-009-bounded-tactical-parameter-space.md): exactly 16 immutable bounded scalar parameters, per-monster engagement profiles, precedence from defaults through loaded and per-monster profiles to a prevalidated transient approach override, deterministic finite clamping, source-specific non-finite handling, and a positive allow-list that excludes system invariants. The standalone digest-checked `us084-v1` profile is documented as compatible with a future US-081 registry reference while US-081 remains draft. Camera pitch and zoom are guarded open-loop calibration settings with no live confirmation claimed. Evidence is offline: 18 focused tactical tests, the affected 276-test slice after the i18n fix, 55 orchestrator tests, Ruff, and MyPy passed. The final canonical gate passed on 2026-08-28: `uv sync --locked`, Ruff, format, and MyPy completed successfully, and pytest reported 1063 passed, 5 skipped, and 89.38% coverage; live Windows validation remains unrun.

## [2026-08-28] synthesis | YOLO detections joined to the client catalog in perception (US-083 AC3)

Recorded in `architecture.md` that `PerceptionPipeline` now assigns each decoded box its US-079
per-instance candidate identity and joins the frame's own detections through `MobCatalogJoin`, so
`WorldState` carries `mob_catalog_joins` (mover id, symbol, display name, verified combat
properties, declared drops, spawn evidence) and `mob_catalog_rejections`. Spawn evidence is
aggregated per mover from the adopted world map and pushed in by `configure_vector_navigation`.
Documented the three deliberately distinct states - no artifacts installed, a mapping refused for a
foreign client digest or mapping version, and an unbound label - and that a rejection is a property
of the class rather than of one box. Also recorded that the curated
`data/client/mover_label_mapping.json` artifact is operator-supplied data: the six detector-label
mover *symbols* are not proven against a client, so until one is authored the mechanism reports
every detection as explicitly unmapped rather than joining by name similarity. Evidence is offline:
16 new perception/join tests plus one orchestrator wiring test; `uv sync --locked`, Ruff, format and
MyPy (298 files) clean, pytest 1085 passed, 5 skipped, 89.32% coverage. No live `neuz.exe` session
is claimed and no new client access or input capability was added. Criteria 4-12 of US-083 remain
open.

## [2026-08-28] ingest | Operator manual verification of Eden mover symbols (US-083)

Ingested [2026-08-28-operator-verified-eden-mover-symbols.md](../sources/2026-08-28-operator-verified-eden-mover-symbols.md):
the operator manually inspected local client tables (`propMover.txt`, `propMover.txt.txt`, and client definitions)
and confirmed that the six Eden detector labels bind 1-to-1 to mover IDs 1453–1458 and mover symbols
`MI_FLAME`, `MI_LADYBLUM`, `MI_MINIMUSH`, `MI_NIGHTMIST`, `MI_OLDRUT`, and `MI_RAPRA`. Updated
`architecture.md` and US-083 with this grounded evidence, resolving the unproven-symbol caveat for the
Eden detector classes.

