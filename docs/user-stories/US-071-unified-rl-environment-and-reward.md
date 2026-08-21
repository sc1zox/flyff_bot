---
id: US-071
title: Unified RL environment formulation, state-action space, and progress reward modeling
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-071: Unified RL environment formulation, state-action space, and progress reward modeling

## Story

As a **Flyff bot developer and RL researcher**,
I want **to formulate farming, navigation, and quest execution into a standardized Reinforcement Learning environment with discrete tactical actions, rich state observations, action masking, and progress-driven rewards**,
so that **offline and simulation-based RL agents can be trained to maximize operational progress per unit time without learning raw keypresses or violating safety boundaries**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md)
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md)
  - [`docs/user-stories/completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md`](completed/US-054-farming-telemetry-and-adaptive-navigation-dataset.md)
  - [`docs/user-stories/US-066-farming-and-navigation-value-model.md`](US-066-farming-and-navigation-value-model.md)
  - [`docs/user-stories/US-067-unified-tactical-policy-integration.md`](US-067-unified-tactical-policy-integration.md)
  - Follow-up stories: [`US-072-offline-farming-and-navigation-simulator.md`](US-072-offline-farming-and-navigation-simulator.md), [`US-073-hierarchical-rl-farming-navigation-and-quest-policy.md`](US-073-hierarchical-rl-farming-navigation-and-quest-policy.md).
- **Markov Decision Process (MDP) Abstraction Level:**
  RL operates at the **tactical abstraction layer**, not at the keyboard/mouse pulse level.
  Low-level movement execution, heading tracking, and emergency stops remain deterministic.
- **Reward Principle:**
  $$\boxed{\text{Maximize useful progress per unit time}}$$
  For farming: $\max \text{Kills / min}$.
  For quests: $\max \text{QuestProgress / min}$.

## Functional Requirements & Technical Architecture

### FR-1 – RL State Observation Space
- The state observation $S_t$ encapsulates:
  - **Player Kinematics:** 3D coordinates $(x,y,z)$, heading $\theta$, velocity $(\dot{x}, \dot{y}, \dot{z})$, scalar speed $v$.
  - **Player Vitals:** $HP\%, MP\%, FP\%$ and active buff cooldowns.
  - **NavMesh Context:** Current polygon ID, terrain slope, active route distance.
  - **Perception Matrix:** For each visible candidate $j \in \{0..K-1\}$: class ID, confidence, 3D position, path distance, relative elevation, lockout flag.
  - **Operational State:** Current target ID, recent kill rate (last 60s), recent stuck count, active farming/navigation mode.
  - **Objective State:** Active quest ID, target mob/item quota progress, distance to objective target.

### FR-2 – Tactical Action Space
- Discrete action space $A_t$ includes:
  - `SELECT_TARGET(candidate_index)`
  - `GO_TO_POSITION(x, y, z)`
  - `GO_TO_ATTACK_POINT(candidate_index, point_index)`
  - `SELECT_CORRIDOR(corridor_id)`
  - `INTERACT_WITH_OBJECT(object_id)`
  - `INTERACT_WITH_NPC(npc_id)`
  - `WAIT(duration)`
- Raw keyboard scan codes and mouse clicks are excluded.

### FR-3 – Deterministic Action Masking
- The environment provides a binary action mask $M(S_t)$ where invalid actions are masked out:
  - Unreachable or dead targets
  - Locked out monsters
  - Positions outside configured patrol leash
  - Inactive or distant NPCs / objects
  - Blocked corridors

### FR-4 – Multi-Objective Progress Reward
- Reward $R_t$ is computed deterministically:
  $$R_t = w_k \cdot \mathbb{I}(\text{KillVerified}) + w_q \cdot \Delta \text{QuestProgress} + w_c \cdot \mathbb{I}(\text{ObjectiveComplete}) - \left( w_t T_{\text{travel}} + w_i T_{\text{idle}} + w_s T_{\text{stuck}} + w_r T_{\text{recovery}} + w_f \mathbb{I}(\text{FailedAction}) \right)$$
- Component weights are fully configurable and versioned.

### FR-5 – Offline Telemetry Episode Exporter
- Telemetry datasets from US-054 and quest logs are converted into standard MDP transition tuples:
  $$(S_t, A_t, R_t, S_{t+1}, M(S_t), d_t)$$
  and exported as columnar Parquet datasets.

### FR-6 – Gymnasium-Compatible Environment Interface
- Provides standard `gymnasium.Env` compliance (`reset()`, `step(action)`) for training algorithms.

## Acceptance criteria

- [ ] **State Representation:** Encapsulates kinematics, vitals, NavMesh context, mob perception matrix, and active quest progress into typed observation arrays.
- [ ] **Tactical Action Catalog:** Supports discrete tactical action variants without exposing raw keyboard/mouse inputs.
- [ ] **Action Masking:** Generates deterministic action masks for dead, locked out, unreachable, or out-of-leash targets.
- [ ] **Reward Engine:** Calculates progress-driven rewards (positive for kills and quest steps, negative for travel, idle, stuck, and failed actions).
- [ ] **Telemetry Transition Exporter:** Converts recorded session JSONL/Parquet datasets into valid $(s, a, r, s', m, d)$ transition batches.
- [ ] **Gymnasium Interface:** Implements `gymnasium.Env` compliant interface for offline training frameworks.
- [ ] **Localization & Diagnostics:** Reward configs and diagnostic logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated checks pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Live in-game RL policy exploration or online weight updates during live farming.
- Direct keypress/mouse generation by RL models.
- Client memory writes (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_rl_state_space.py` validating observation construction, bounds, and normalizations.
  - Unit tests in `tests/unit/test_action_masking.py` validating mask generation for unreachable/locked targets.
  - Unit tests in `tests/unit/test_reward_engine.py` validating reward calculations across kills, stalls, and quest advances.
  - Unit tests in `tests/unit/test_rl_exporter.py` validating transition export into Parquet format.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Export real recorded farming telemetry to an RL dataset: verify schema correctness and verify training a simple tabular/DQN agent against the exported transitions.
