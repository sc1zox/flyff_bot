# ADR-002: Architecture blueprint with World State, Supervisor, Planner, and PySide6 UI

- Status: accepted
- Date: 2026-08-15
- Related stories: [US-001](../user-stories/completed/US-001-agentic-repository-bootstrap.md), [US-006](../user-stories/completed/US-006-target-architecture-bootstrap.md)

## Context

The bot requires computer vision (YOLO, OpenCV, OCR), multi-tier decision making (high-level goal planning vs. reactive micro-combat/navigation), robust self-healing, and a user-friendly operator interface without excessive complexity or memory overhead.

## Decision

1. **Language & Runtime:** Python as the primary language to maintain native compatibility with OpenCV, YOLO (ONNX/Torch), and OCR libraries.
2. **User Interface:** Native Windows desktop UI using PySide6 (Qt). Web frameworks (Node, Angular, React) are explicitly excluded to keep overhead minimal and avoid separate runtime processes.
3. **Perception Strategy:**
   - YOLO for dynamic 3D game entities (mobs/players).
   - Template Matching for static 2D UI elements (icons, window frames).
   - Targeted ROI OCR for screen logs (loot/system notifications) rather than full-screen OCR.
4. **State & Control Pipeline:**
   - Central immutable `WorldState` snapshot updated by the perception pipeline.
   - `Supervisor` running a reconciliation loop comparing desired state to observed state, detecting failures (`NO_PROGRESS`, `NO_MOBS`, `STUCK`, `INVENTORY_MISMATCH`).
   - Strategic `Planner` (STRIPS-style) for recipes/goals (e.g. collecting item quotas).
   - Reactive sub-controllers (`Combat`, `Navigation`, `Loot`) as focused state machines.
   - Decoupled `Executor` sending Win32 inputs with mandatory post-action visual verification.

```text
Recipe / Goal
     ↓
Planner
     ↓
Supervisor
     ↕
World State
     ↑
YOLO / OCR / CV
     ↓
Combat / Navigation / Loot
     ↓
Executor
     ↓
Game
```

## Alternatives

- Web UI with Node.js/Angular: Rejected due to unnecessary multi-process overhead, inter-process communication complexity, and memory footprint.
- Monolithic monolithic script loop: Rejected due to inability to recover from failures, difficulty of testing, and tight coupling of perception and action.

## Consequences

- Clean separation of concerns and high testability via synthetic `WorldState` snapshots.
- Perception, decision-making, and execution can be tested and developed independently in isolated units.
- PySide6 will be added as a dependency when implementing the UI story.

## Verification

Unit tests with synthetic world-state feeds and simulated game loops pass via `./scripts/check.ps1`.
