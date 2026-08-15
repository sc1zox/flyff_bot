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
