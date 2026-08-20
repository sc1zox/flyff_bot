---
id: US-064
title: Continuous human-like movement, held-key pathing, and smooth heading control
status: draft
created: 2026-08-20
updated: 2026-08-20
---

# US-064: Continuous Human-Like Movement, Held-Key Pathing, and Smooth Heading Control

## Story

As a **Flyff bot operator and automation designer**,
I want **the bot to navigate fluidly by holding movement keys continuously with dynamic heading corrections rather than stuttering through discrete keypress pulses**,
so that **in-game character motion appears natural and human-like during zone travel, search roaming, and target approach without regressions in stall detection or emergency safety.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md): Read-only memory access for real-time live position feedback.
  - [`docs/user-stories/completed/US-013-autonomous-farming-loop-and-orchestration-engine.md`](completed/US-013-autonomous-farming-loop-and-orchestration-engine.md): Autonomous loop and tick execution.
  - [`docs/user-stories/completed/US-018-multi-axis-camera-search-and-paced-scanning.md`](completed/US-018-multi-axis-camera-search-and-paced-scanning.md): Search and camera rotation pacing.
  - [`docs/user-stories/completed/US-019-intelligent-pathing-and-spawn-heatmap.md`](completed/US-019-intelligent-pathing-and-spawn-heatmap.md): Spatial map and waypoint route following.
  - [`docs/user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md`](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md): 3D terrain-aware pathing.
  - [`docs/user-stories/completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md`](completed/US-058-navmesh-aware-targeting-and-telemetry-integration.md): NavMesh Funnel approach pathing.
  - [`docs/bugs/fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md`](../bugs/fixed/BUG-009-movement-tracking-wasd-and-obstacle-stall-detection.md): Movement tracking and obstacle stall detection.
  - [`docs/bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md`](../bugs/fixed/BUG-017-invisible-wall-collision-stall-detection-and-recovery-pathfinding.md): Collision stall detection and recovery pathfinding.

### Problem Analysis & Motivation

Currently, the pathing controller (`PathingController`) issues discrete movement pulses (`DEFAULT_PATHING_STEP_DURATION_SECONDS = 0.6s` and `DEFAULT_PATHING_TURN_DURATION_SECONDS = 0.08s`). In each tick cycle, the bot presses `W`, holds it for 0.6s, releases it, pauses for state re-evaluation, adjusts heading by pulsing rotation keys, and then presses `W` again.

This creates an unnatural, robotic "staccato" walking behavior (stopping and starting every 0.6s). Human players hold `W` down continuously while traversing terrain or approaching targets, adjusting their heading concurrently without halting forward momentum.

### Technical Concept

1. **Continuous Movement State Model:**
   - Transition from one-shot pulse dispatching to a stateful movement stream where `W` remains pressed across ticks as long as the character is actively traversing a route.
   - Smooth waypoint chaining: When reaching a waypoint with remaining waypoints on the active path, advance `_waypoint_index` immediately without releasing `W`.
2. **Concurrent Heading Adjustment:**
   - When the angle error to the active waypoint is within a manageable correction threshold (e.g. $\le 45^\circ$), apply turning corrections while `W` remains depressed (simultaneous key holding or mouse rotation).
   - Only release `W` or halt forward momentum if a sharp turn ($> 45^\circ$ or heading inversion) requires pivotal reorientation.
3. **Fail-Safe Release Guarantees:**
   - Release all held movement keys immediately upon:
     - Reaching final waypoint / entering target engagement range.
     - Obstacle stall detection (position delta below threshold over duration window).
     - Focus loss or window occlusion.
     - Emergency stop activation (`END` or `ESC` keys).
     - State transitions to `IDLE`, `COMBAT`, `PAUSED`, `TELEPORTING`, or `EMERGENCY_STOPPED`.

---

## Acceptance criteria

### 1. Continuous Forward Motion & Waypoint Chaining
- [ ] **Given** an active route with multiple waypoints (NavMesh, vector zone, or heatmap), **when** the bot moves between consecutive waypoints, **then** `W` remains pressed continuously without halting or releasing between waypoints.
- [ ] **Given** a character traversing a path, **when** the character enters within the arrival tolerance of an intermediate waypoint, **then** the target waypoint advances seamlessly to the next waypoint in the queue without releasing `W`.

### 2. Concurrent Steering
- [ ] **Given** `W` is currently held down, **when** minor heading adjustments are required ($\le \text{heading\_tolerance}$), **then** steering keys (`A`/`D` or `Left`/`Right`) are applied concurrently without releasing `W`.
- [ ] **Given** a sharp turn is required ($> \text{heading\_pivot\_threshold}$, default $45^\circ$), **when** changing direction, **then** `W` is temporarily released to allow a clean pivot before forward movement resumes.

### 3. Immediate Stop on Target Arrival & Mode Transition
- [ ] **Given** the bot is approaching a monster or traveling along a path, **when** the character reaches the final waypoint or enters engagement range ($d \le \text{engagement\_distance}$), **then** all movement keys are immediately released.
- [ ] **Given** active continuous movement, **when** the farming mode transitions to `COMBAT`, `PAUSED`, `TELEPORTING`, or `COMPLETED`, **then** all movement keys are immediately released.

### 4. Safety, Stall Detection, and Emergency Stop
- [ ] **Given** continuous movement is active, **when** the character fails to progress in position (measured via live GPS or minimap odometry) for longer than the stall threshold, **then** all movement keys are released immediately and obstacle stall evasion/re-pathing is triggered.
- [ ] **Given** continuous movement is active, **when** the target window loses foreground focus or the operator presses `END` or `ESC`, **then** all held keys are released immediately via guarded input adapter.

### 5. Configurable Parameters & Humanization
- [ ] **Given** pathing configuration, **when** inspecting defaults, **then** settings exist for heading tolerance, pivot threshold, and waypoint arrival tolerance with sensible human-like defaults.
- [ ] **Given** user-visible status or settings, **when** displayed, **then** all strings are localized in English and German in sync (`src/flyff_bot/locales/*.json`).

---

## Out of scope

- Direct memory manipulation / client code injection (`WriteProcessMemory`).
- Automated mouse click-to-move terrain navigation (relying on client navmesh).
- Flying / hoverboard / mount navigation systems.
- Evasion of server-side bot detection heuristics.

---

## Verification

### Automated
```powershell
uv run pytest tests/test_pathing.py tests/test_input_control.py tests/test_orchestrator.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

### Manual (Windows)
1. Launch Entropia Flyff client and start the bot with active navigation/farming.
2. Observe character movement across multiple waypoints: verify character runs smoothly without stopping and starting every 0.6s.
3. Observe target approach: verify character runs straight towards the mob and halts cleanly upon entering combat range.
4. Test emergency stop (`END`) and window alt-tab during continuous running: verify character immediately stops moving and does not get stuck in a held `W` state.
