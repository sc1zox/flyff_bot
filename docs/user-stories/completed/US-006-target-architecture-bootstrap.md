---
id: US-006
title: Target architecture bootstrap
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-006: Target architecture bootstrap

## Story

As a bot developer, I want an overarching architecture foundation (World State snapshot, Supervisor/Reconciliation Loop,
STRIPS-style Goal Planner, reactive domain controllers, verified Executor, and PySide6 desktop UI),
so that long-term farming goals can be planned, executed, observed, and self-healed reliably without architectural drift.

## Context and assumptions

- Source: [Target architecture proposal](../../sources/2026-08-15-target-architecture-proposal.md).
- Python remains the core runtime to support YOLO, OpenCV, and OCR natively.
- PySide6 is chosen for the native Windows UI to avoid the complexity and overhead of web stacks (Node/Angular).
- CV combines YOLO (dynamic entities/mobs), Template Matching (static UI/anchors), and targeted ROI OCR (loot log/chat).
- A central, immutable `WorldState` snapshot represents the current observed and assumed game reality.
- The `Supervisor` reconciles desired state vs. observed state and triggers self-healing on failure flags (`NO_PROGRESS`, `NO_MOBS`, `STUCK`, `INVENTORY_MISMATCH`).
- A strategic planner (STRIPS/Recipe Planner) breaks high-level goals into subgoals, leaving micro-execution to reactive domain controllers (Combat, Navigation, Loot).
- The `Executor` is decoupled from planning and strictly dispatches inputs, marking actions complete only upon post-action visual verification.

## Architecture Blueprint

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

## Acceptance criteria

- [x] Core interfaces and dataclasses for `WorldState`, `Supervisor`, `Planner`, `Action`, and `Observation` are defined and typed.
- [x] The `Supervisor` loop supports reconciliation between desired state and observed state with configurable timeout and error detection (`NO_PROGRESS`, `NO_MOBS`, `STUCK`, `INVENTORY_MISMATCH`).
- [x] Action execution enforces an observation-verification step before confirming success.
- [x] Domain controllers (`CombatController`, `NavigationController`, `LootController`) are organized as isolated state machines that can be unit-tested with synthetic state feeds.
- [x] PySide6 dependency and application skeleton are configured for desktop UI presentation without introducing web runtime overhead.
- [x] All public interfaces, models, and states are strictly typed (`mypy --strict`).
- [x] All user-visible UI labels, status messages, and log entries are localized in German and English.

## Out of scope

- Specific mob ML model training or full Flyff map waypoints.
- Web-based frontends (Angular, React, Node.js).
- Direct memory manipulation or game client modification.

## Verification

- Automated: Unit tests for state transitions, reconciliation decisions, mock action verification, and planner step sequences; `./scripts/check.ps1`.
- Manual (Windows): Launch the PySide6 UI window and observe state updates from a simulated world-state feed.
