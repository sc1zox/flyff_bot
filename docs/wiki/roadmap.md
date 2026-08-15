---
title: Product and technical roadmap
status: active
updated: 2026-08-15
sources:
  - ../sources/2026-08-15-repository-bootstrap-request.md
  - ../sources/2026-08-15-computer-vision-and-yolo-request.md
  - ../sources/2026-08-15-target-architecture-proposal.md
related:
  - project-overview.md
  - architecture.md
  - ../decisions/ADR-001-cli-before-http-server.md
  - ../decisions/ADR-002-target-architecture-and-pyside6.md
---

# Product and technical roadmap

The development roadmap is structured into 4 sequential phases, evolving from base infrastructure to a closed-loop perception and automation system:

```text
Phase 1 (Bootstrap & Architecture) ──► Phase 2 (Perception Pipeline) ──► Phase 3 (Closed-Loop & Controllers) ──► Phase 4 (UI Dashboard)
```

## Phases and Milestones

### Phase 1: Foundation & Architecture (Completed)
- **US-001:** Agentic repository bootstrap (Python 3.14, `uv`, quality gates, locale sync, Win32 input PoC).
- **US-006:** Target architecture bootstrap (`WorldState` snapshot, `Supervisor` reconciliation loop, `GoalPlanner`, PySide6 foundation).

### Phase 2: Perception & Computer Vision Pipeline (Active)
- **US-002 (Completed):** Screen and client frame capture (`FrameProvider` producing `numpy.ndarray`).
- **US-003 (Completed):** Mob detection skeleton with YOLO and OpenCV (Dynamic entity detection and bounding boxes).
- **US-004 (Completed):** Target mob verification skeleton (Target-bar ROI extraction, name matching, HP bar inspection).
- **US-005 (Completed):** Central loot and system log OCR extraction (Drop notification parsing into structured events).
- **US-011:** Multi-mob training dataset pipeline and custom YOLO model training (Manual labeling workflow, dataset manifest, ONNX export).
- **US-012 (Completed):** Real-world vision refactoring for robust target verification and multi-mob detection (Header-anchor validation, sky-color immunity, real game fixtures).

### Phase 3: Closed-Loop Execution & Reactive Controllers
- **US-007:** Perception to WorldState feed integration (Connecting CV pipelines to the central `WorldState` snapshot).
- **US-008:** Reactive combat controller and target engagement (Attack sequencing with post-action visual verification).
- **US-009 (Completed):** Reactive loot collector and drop accounting (Item pickup sequence and recipe progress tracking).

### Phase 4: Desktop UI & Visual Debugging
- **US-010:** Native PySide6 dashboard and visual debug overlay (Live monitoring, YOLO box overlay, killswitch controls).
