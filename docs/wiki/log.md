# Wiki log

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
