---
title: Product and technical roadmap
status: active
updated: 2026-08-19
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-computer-vision-and-yolo-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
  - ../sources/2026-08-19-entropia-client-navigation-data-extraction.md
related:
  - project-overview.md
  - architecture.md
  - ../decisions/ADR-001-cli-before-http-server.md
  - ../decisions/ADR-002-target-architecture-and-pyside6.md
  - ../decisions/ADR-004-coordinate-only-read-process-memory.md
---

# Product and technical roadmap

The development roadmap has five phases, evolving from base infrastructure to closed-loop,
world-aware navigation:

```text
Phase 1 (Bootstrap) -> Phase 2 (Perception) -> Phase 3 (Controllers) -> Phase 4 (UI) -> Phase 5 (Navigation accuracy)
```

## Phases and Milestones

### Phase 1: Foundation & Architecture (Completed)
- **US-001:** Agentic repository bootstrap (Python 3.14, `uv`, quality gates, locale sync, Win32 input PoC).
- **US-006:** Target architecture bootstrap (`WorldState` snapshot, `Supervisor` reconciliation loop, `GoalPlanner`, PySide6 foundation).

### Phase 2: Perception & Computer Vision Pipeline (Completed)
- **US-002 (Completed):** Screen and client frame capture (`FrameProvider` producing `numpy.ndarray`).
- **US-003 (Completed):** Mob detection skeleton with YOLO and OpenCV (Dynamic entity detection and bounding boxes).
- **US-004 (Completed):** Target mob verification skeleton (Target-bar ROI extraction, name matching, HP bar inspection).
- **US-005 (Completed):** Central loot and system log OCR extraction (Drop notification parsing into structured events).
- **US-011 (Completed):** Multi-mob training dataset pipeline and custom YOLO model training (Manual labeling workflow, dataset manifest, ONNX export).
- **US-012 (Completed):** Real-world vision refactoring for robust target verification and multi-mob detection (Header-anchor validation, sky-color immunity, real game fixtures).
- **US-026 (Completed):** Static HUD anchoring and field hardening for vitals and monster stats (Fixed-pixel top-left vitals anchoring fixing BUG-006, template-matched monster stats OCR).

### Phase 3: Closed-Loop Execution & Reactive Controllers (Completed)
- **US-007 (Completed):** Perception to WorldState feed integration (Connecting CV pipelines to the central `WorldState` snapshot).
- **US-008 (Completed):** Reactive combat controller and target engagement (Attack sequencing with post-action visual verification).
- **US-009 (Completed):** Reactive loot collector and drop accounting (Item pickup sequence and recipe progress tracking).
- **US-013 (Completed):** Autonomous farming loop and orchestration engine (Unified closed-loop session coordinating perception, combat, looting, and recovery).
- **US-017 (Completed):** Player vital gauges perception and threshold-based auto-consumable triggers (Pure pixel-color HP/MP/FP perception, debounce cooldown, low-HP recovery priority).
- **US-018 (Completed):** Multi-axis camera search and paced scanning (Vertical pitch tilt, visual settling pauses, terrain discovery).

### Phase 4: Desktop UI & Visual Debugging (Completed)
- **US-010 (Completed):** Native PySide6 dashboard and visual debug overlay (Live monitoring, YOLO box overlay, killswitch controls).
- **US-020 (Completed):** Visual navigation path and heatmap inspector (2D canvas inspector, topology graph, spawn density heatmap).
- **US-021 (Completed):** Navigation map profiles and session reset safeguards (Multi-profile persistence, dirty session safeguards, auto-save).
- **US-024 (Completed):** Target verification decision and threshold debug dashboard visualization (Live header-anchor, HP-bar, and name-match scores/thresholds in a dedicated `MainWindow` debug panel).
- **US-026 (Completed):** Placement calibration visual guide overlay ("Placements" toggle button, color-coded HUD ROI overlay boxes).
- **US-049 (Completed):** Session event log and transition diagnostics (per-session fail-safe JSONL log, typed `SessionEventLogger`, and a localized "Diagnostic Event Log" dashboard panel).
- **US-050 (Completed):** Responsive tabbed dashboard overhaul (pinned session header, five localized scrollable functional tabs, stable top-level geometry, and live feeds independent of selected tab).

### Phase 5: Navigation Accuracy (Active)

- **US-035 (Completed):** Measured minimap odometry and tracking-quality gating.
- **US-036 (Completed):** Persisted navigation-frame anchoring with explicit refusal states.
- **US-039 (Completed):** Combat obstacle stall detection and adaptive re-navigation.
- **US-041 (Completed):** Spawn-distance and bearing calibration capture harness.
- **US-042 (Completed):** Standardized camera alignment and viewport initialization.
- **US-043 (Completed):** Continuous approach tracking and minimap zoom initialization.
- **US-045 (Completed):** Offline vector spawn, terrain, and obstacle extraction with goal routing.
- **US-048 (Full automated gate passing; Windows field validation open):** Fingerprinted coordinate-only
  live XYZ, terrain-aware 3D A*, configured long-range teleport dispatch, position-anchored
  recovery, and an elevation-enriched inspector. Incomplete loose terrain/collision data and
  runtime server state prevent any 100% fault-free guarantee.
