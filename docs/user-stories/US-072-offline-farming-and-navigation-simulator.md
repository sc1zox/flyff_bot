---
id: US-072
title: Fast offline farming, navigation, and quest dynamics simulator
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-072: Fast offline farming, navigation, and quest dynamics simulator

## Story

As a **Flyff bot developer and RL researcher**,
I want **a fast, offline Python simulation environment modeling NavMesh pathing, mob spawning/combat, stuck dynamics, and quest objective progression without requiring a running game client (`neuz.exe`)**,
so that **RL policies can be trained and evaluated across millions of simulated steps in minutes with reproducible seeds and real-telemetry calibration**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Extracted 3D NavMeshes, spawn zones (.rgn), and world metadata.
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md): Calibration baseline.
  - [`docs/user-stories/US-069-experience-based-navmesh-routing.md`](US-069-experience-based-navmesh-routing.md): Traversal time and stuck probability distributions.
  - [`docs/user-stories/US-071-unified-rl-environment-and-reward.md`](US-071-unified-rl-environment-and-reward.md): Observation and action spaces.
  - Follow-up story: [`US-073-hierarchical-rl-farming-navigation-and-quest-policy.md`](US-073-hierarchical-rl-farming-navigation-and-quest-policy.md).
- **Scope & Modeling Principles:**
  - **Not a full game emulator:** Simulates only the high/mid-level tactical dynamics (movement time, path traversal, monster spawns/combat, stuck events, quest states).
  - **Performance:** Runs $\ge 100\times$ to $1000\times$ faster than real-time.
  - **Reproducibility:** Seeded pseudo-random number generator (PRNG) ensures bit-exact reproducible episodes.
  - **Calibration:** Transition distributions are fitted directly from US-054 telemetry.

## Functional Requirements & Technical Architecture

### FR-1 – Offline NavMesh & Movement Dynamics Engine
- Loads US-052 3D NavMesh data directly from local files.
- Simulates character movement along corridors using nominal speed $v$, turn rates $\omega$, and empirical traversal distributions from US-069.
- Advances simulated time $\Delta t = d / v + t_{\text{turn}}$.

### FR-2 – Monster Spawning & Respawn Engine
- Ingests zone spawn metadata (.rgn):
  - Monster ID, bounding region, max count, respawn interval $\tau_{\text{respawn}}$.
- Simulates dynamic mob lifecycles: `SPAWNING`, `ALIVE`, `IN_COMBAT`, `DEAD`, `DESPAWNING`.
- Simulates line-of-sight and visual field perception cone ($360^\circ$ or camera FOV).

### FR-3 – Combat & Time-to-Kill Stochastic Engine
- Simulates combat duration $T_{\text{ttk}}$ sampled from calibrated telemetry distributions (log-normal or empirical histograms per mob class and player level).
- Emits kill events, target HP decay, and player HP/MP/FP consumption.

### FR-4 – Obstacle Stall & Recovery Model
- Simulates stochastic stuck events based on US-069 polygon stuck probabilities $P_{\text{stuck}}(e)$.
- Applies simulated recovery maneuvers (strafe/backstep) with stochastic recovery duration $T_{\text{recovery}}$.

### FR-5 – Quest Objectives Engine
- Supports key quest objective types:
  - `GO_TO(location, radius)`
  - `KILL(mob_class, count)`
  - `INTERACT(object_id)`
  - `TALK_TO_NPC(npc_id)`
- Tracks quest state transitions: `NOT_STARTED`, `IN_PROGRESS`, `READY_TO_TURN_IN`, `COMPLETED`.

### FR-6 – Real-Telemetry Calibration & Validation Harness
- Compares simulation aggregate metrics against real US-054 sessions:
  - Kills per minute (KPM)
  - Travel time distribution
  - Kill-to-kill cycle distribution
  - Stuck frequency
  - Quest step completion time.

### FR-7 – Gymnasium Interface & Fast Step Loop
- Implements `gymnasium.Env` (`reset(seed=...)`, `step(action)`).
- Zero disk I/O during episode stepping.

## Acceptance criteria

- [ ] **Offline Operation:** Simulator runs 100% offline without requiring `neuz.exe` or any active game process.
- [ ] **NavMesh Pathing Simulation:** Simulates character path traversal across real US-052 3D NavMesh maps with realistic speeds and turn delays.
- [ ] **Spawn & Combat Dynamics:** Simulates monster spawning, density limits, respawn timers, and stochastic combat durations matching telemetry distributions.
- [ ] **Stall Dynamics:** Simulates obstacle stalls and recovery times based on empirical terrain statistics.
- [ ] **Quest State Progression:** Models `GO_TO`, `KILL`, `INTERACT`, and `TALK_TO_NPC` quest objectives and completion conditions.
- [ ] **Reproducibility:** Initializing with a fixed seed produces identical episode trajectories and outcomes.
- [ ] **Execution Speed:** Simulation steps execute at $\ge 100\times$ real-time speed.
- [ ] **Telemetry Validation:** Mean KPM and travel times deviate $< 10\%$ from calibrated US-054 session baselines.
- [ ] **Localization & Diagnostics:** Status messages and metrics are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated tests pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Rendering 3D graphics or Direct3D simulation frames.
- Simulating client UI widget animations.
- Real-time multiplayer synchronization or server emulation.
- Memory write operations (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_simulator_navmesh.py` validating simulated movement speed, path lengths, and turn pacing.
  - Unit tests in `tests/unit/test_simulator_spawns.py` validating spawn region caps, respawn timers, and combat TTK sampling.
  - Unit tests in `tests/unit/test_simulator_quests.py` validating quest objective triggers and state transitions.
  - Unit tests in `tests/unit/test_simulator_determinism.py` verifying identical transitions under identical seeds.
  - Benchmark test verifying $\ge 100\times$ real-time simulation throughput.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Run a 10,000-step simulated farming session in Python: verify generated metrics (KPM, travel time, stuck rate) match expected values from real farming sessions.
