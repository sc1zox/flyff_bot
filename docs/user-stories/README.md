# User Story Backlog & Roadmap

One Markdown file represents one independently testable slice of user value. Copy `TEMPLATE.md` to
`US-NNN-short-title.md`. Keep stories small; split unrelated acceptance criteria.

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

### Phase 3: Closed-Loop Execution & Reactive Controllers
- [x] [**US-008: Reactive combat controller and target engagement**](completed/US-008-reactive-combat-controller.md) — Target selection, skill rotation, and post-action visual verification.
- [ ] [**US-009: Reactive loot collector and drop accounting**](US-009-reactive-loot-controller.md) — Automated item pickup routines and drop counting.

### Phase 4: Desktop UI & Visual Debugging
- [ ] [**US-010: Native PySide6 dashboard and visual debug overlay**](US-010-pyside6-dashboard-and-overlay.md) — Desktop monitoring, live YOLO overlay, recipe progress, and killswitch controls.
