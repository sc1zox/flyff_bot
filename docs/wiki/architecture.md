---
title: Architecture
status: active
updated: 2026-08-15
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
   - **Target verification:** `TargetVerifier` extracts a normalized target-header region from a
     captured frame, detects the configured HP-bar colour, and template-matches a whitelisted name.
     It returns `VALID_TARGET`, `WRONG_TARGET`, or `NO_TARGET` without dispatching any input.
   - **Perception pipeline:** `PerceptionPipeline` captures one frame per tick and passes that
     shared frame to mob detection, target verification, and loot-log OCR. It maps their outputs
     into a fresh immutable `WorldState`, emits target-change and newly-visible-mob events, and
     records feed-specific failures while retaining the prior value for a failed feed.
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
