---
id: US-010
title: Native PySide6 dashboard and visual debug overlay
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-010: Native PySide6 dashboard and visual debug overlay

## Story

As a bot user and operator, I want a desktop UI dashboard with live metrics, bot state indicators, start/pause/killswitch buttons, and a visual debug overlay showing YOLO mob boxes and target bar status, so that bot activity can be monitored and operated comfortably.

## Context and assumptions

- Source: [Target architecture proposal](../../sources/2026-08-15-target-architecture-proposal.md) and [ADR-002](../../decisions/ADR-002-target-architecture-and-pyside6.md).
- Depends on [US-006](US-006-target-architecture-bootstrap.md) (PySide6 Foundation) and [US-007](US-007-perception-worldstate-feed.md) (Perception Feed).
- UI runs on the Qt main thread; all bot loops and vision feeds communicate asynchronously via Qt signals and slots.

## Acceptance criteria

- [x] Displays live bot status (Active, Paused, Emergency Stopped, Healing/Reconciling).
- [x] Shows current farming recipe/goal progress (e.g. `124/500 Sunstones`).
- [x] Provides Start, Pause, and Emergency Stop action buttons in the UI.
- [x] Renders an optional visual debug viewport showing captured game frames with YOLO mob bounding boxes and target bar state overlay.
- [x] Supports dynamic language switching between German and English.
- [x] Automated unit tests verify UI widget initialization, signal reception, and status updates.

## Out of scope

- Complex web socket or remote browser hosting.

## Verification

- Automated: Unit tests with `pytest-qt` or synthetic Qt event loop checking widget signals and state sync; `./scripts/check.ps1`.
- Manual (Windows): Launch `python -m flyff_bot ui` and interact with controls and live overlay.
