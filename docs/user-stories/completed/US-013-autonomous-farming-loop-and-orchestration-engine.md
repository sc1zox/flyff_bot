---
id: US-013
title: Autonomous farming loop and orchestration engine
status: completed
created: 2026-08-15
updated: 2026-08-15
---

# US-013: Autonomous farming loop and orchestration engine

## Story

As a player using permitted automation, I want a unified closed-loop orchestration engine that coordinates perception, combat targeting, attack rotation, loot pickup, and searching/recovery, so that the bot can farm autonomously in a continuous cycle while strictly obeying foreground and emergency stop constraints.

## Context and assumptions

- Source: [Target architecture proposal](../sources/2026-08-15-target-architecture-proposal.md), [Roadmap](../wiki/roadmap.md), and [ADR-002](../decisions/ADR-002-target-architecture-and-pyside6.md).
- Depends on [US-007](completed/US-007-perception-worldstate-feed.md) (`PerceptionPipeline` and `WorldState`), [US-008](completed/US-008-reactive-combat-controller.md) (`CombatController`), [US-009](completed/US-009-reactive-loot-controller.md) (`LootController`), and [US-006](completed/US-006-target-architecture-bootstrap.md) (`Supervisor`).
- Connects to UI Dashboard [US-010](US-010-pyside6-dashboard-and-overlay.md) via Qt signals (`start_requested`, `pause_requested`, `emergency_stop_requested`) and CLI entry point via `--farm` / `--auto`.
- The loop operates sequentially per tick: Perception Frame -> Update WorldState -> Evaluate Controller State (Search/Target/Combat/Loot/Recover) -> Dispatch Safe Action -> Observe Result.
- Safe execution guarantees: never dispatch inputs when game window is not foregrounded, minimized, occluded, or when emergency stop (`END` key) is active.

## Acceptance criteria

- [x] `FarmingOrchestrator` implements an asynchronous/non-blocking loop that coordinates `PerceptionPipeline`, `CombatController`, `LootController`, and `Supervisor`.
- [x] State transitions smoothly through the complete lifecycle: `SEARCHING` -> `TARGETING` -> `COMBAT` -> `LOOTING` -> `RECONCILING` -> `SEARCHING`.
- [x] In `SEARCHING` state: When no target mob is visible, executes configurable search actions (e.g. camera rotation or brief pause) before retrying perception.
- [x] In `COMBAT` state: Selects and targets valid mobs, executes attack rotation, monitors mob HP, and detects mob defeat (`TARGET_DEAD`).
- [x] In `LOOTING` state: Executes loot pickup key sequence (`F`), processes OCR loot notifications, updates loot counters, and handles loot timeout.
- [x] In `RECONCILING` state: Uses `Supervisor` to check for stuck states or lack of progress and applies recovery strategies or pauses.
- [x] Provides CLI command (`--farm` or `--auto`) with configurable parameters (mob class whitelist, rotation keys/cooldowns, loot key/cooldowns, search policy, target item/kill count goal).
- [x] Integrates with PySide6 desktop dashboard by responding to start/pause/killswitch signals and continuously emitting `DashboardUpdate` payloads for UI rendering.
- [x] Instantly stops or pauses execution upon `END` key press, UI emergency stop button, or when target game window loses foreground focus.
- [x] Automated unit tests verify orchestration loop transitions, recovery behavior, safety abortion, and goal completion using synthetic feeds.
- [x] All user-visible logs, CLI outputs, error messages, and dashboard text exist in German and English without string assembly.

## Out of scope

- 3D pathfinding over complex terrain meshes or multi-zone teleportation.
- Inventory bag organization, vendor shopping, or NPC quest interaction.

## Verification

- Automated: Unit tests in `tests/unit/` testing `FarmingOrchestrator` state machine, loop ticking, cancellation upon emergency stop / lost focus, and error handling; `./scripts/check.ps1`.
- Manual (Windows): Run `uv run flyff-bot --farm --model models/mob_detector.onnx --labels models/labels.txt --target-anchor <anchor.png> --target-template Flame <flame.png>` or start via `python -m flyff_bot ui`, verify full cycle (search -> target -> combat -> loot -> next mob) on the foreground live client.
