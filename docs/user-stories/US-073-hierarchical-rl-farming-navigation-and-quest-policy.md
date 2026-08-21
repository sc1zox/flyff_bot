---
id: US-073
title: Hierarchical RL policy for unified farming, navigation, and quest optimization
status: draft
created: 2026-08-21
updated: 2026-08-21
---

# US-073: Hierarchical RL policy for unified farming, navigation, and quest optimization

## Story

As a **Flyff bot developer and operator**,
I want **a two-tier hierarchical RL policy (High-Level Strategic Goal / Mid-Level Tactical Navigation & Attack Positioning) trained in the US-072 simulator to optimize farming throughput and quest progress per unit time**,
so that **the bot autonomously coordinates multi-objective missions with minimal wasted time while relying on deterministic low-level controllers for motion and safety.**

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md)
  - [`docs/decisions/ADR-006-read-only-process-memory-access.md`](../decisions/ADR-006-read-only-process-memory-access.md)
  - [`docs/user-stories/US-067-unified-tactical-policy-integration.md`](US-067-unified-tactical-policy-integration.md): `TacticalPolicy` integration.
  - [`docs/user-stories/US-069-experience-based-navmesh-routing.md`](US-069-experience-based-navmesh-routing.md): Experience-based routing.
  - [`docs/user-stories/US-070-learned-attack-point-and-local-waypoint-optimization.md`](US-070-learned-attack-point-and-local-waypoint-optimization.md): Attack point optimization.
  - [`docs/user-stories/US-071-unified-rl-environment-and-reward.md`](US-071-unified-rl-environment-and-reward.md): RL state, action, and reward space.
  - [`docs/user-stories/US-072-offline-farming-and-navigation-simulator.md`](US-072-offline-farming-and-navigation-simulator.md): Fast simulator training ground.
- **Hierarchical Policy Architecture:**
  ```text
  Current Objective (Farming Quota | Quest Step | Zone Transition)
         +
  WorldState Snapshot
         ↓
  High-Level Strategic Policy (Decides: Target Mob / Spawn Cluster / NPC / Quest Point / Wait)
         ↓
  Sub-Goal / Target Intent
         ↓
  Mid-Level Tactical Policy (Decides: Attack Point / NavMesh Corridor / Local Waypoint / Approach Angle)
         ↓
  Deterministic Low-Level Controllers (Heading, WASD, Target Clicks, Stall Recovery, Emergency Stop)
         ↓
  Guarded Win32 Input Execution
  ```
- **Separation of Concerns:**
  - *High-Level Policy:* Operates at macro-event boundaries (mob killed, quest step updated, objective reached).
  - *Mid-Level Policy:* Operates at navigation and approach boundaries (attack point selection, corridor steering).
  - *Low-Level Controllers:* 100% deterministic (heading adjustments, continuous WASD holding, obstacle evasion, emergency stops).

## Functional Requirements & Technical Architecture

### FR-1 – High-Level Strategic Policy
- Evaluates the active objective and macro world state to select the next strategic sub-goal:
  - Select monster $A$ from visible mobs
  - Navigate to spawn cluster $B$
  - Travel to NPC $X$ for quest dialog
  - Navigate to quest area $Y$
  - Interact with world object $Z$
  - Standby / wait for respawn
- Re-evaluates primarily when:
  - A monster is confirmed dead
  - Quest progress advances
  - Target becomes unreachable or locked out
  - Strategic sub-goal is reached.

### FR-2 – Mid-Level Tactical Policy
- Given a selected target or navigation sub-goal, selects:
  - Optimal attack point $\mathbf{p}_k$ within valid engagement radius (US-070)
  - Preferred NavMesh corridor (US-069)
  - Local approach angle and waypoint adjustments.
- Re-evaluates dynamically on target movement or navigation progress.

### FR-3 – Action Masking Enforcement
- Enforces strict binary action masks:
  - Unreachable targets $\to$ masked
  - Locked out monsters $\to$ masked
  - Blocked corridors $\to$ masked
  - Invalid NPCs / non-interactable objects $\to$ masked
- The policy cannot emit an invalid or illegal action.

### FR-4 – Multi-Objective Optimization
- Maximizes useful progress per unit time:
  $$\text{Objective}(\pi) = \mathbb{E} \left[ \sum_{t=0}^{T} \gamma^t R_t \right]$$
  - For Farming: $\max \text{Kills / min}$ with minimal travel, idle, and stuck time.
  - For Quests: $\max \text{QuestProgress / min}$ with optimal routing.

### FR-5 – Offline Simulator Training Pipeline
- The policy is trained using Deep RL (e.g. PPO or SAC with Action Masking) inside the US-072 offline simulator.
- No live game exploration or unverified live trial-and-error is performed.

### FR-6 – Live Deployment via TacticalPolicy Protocol
- The trained policy is exported to ONNX and integrated into the live bot via the US-067 `TacticalPolicy` protocol.
- Any invalid policy output, NaN, or timeout immediately triggers a clean fallback to `HeuristicPolicy`.

### FR-7 – Performance & Telemetry Tracking
- Live inference execution for both high- and mid-level policies MUST complete in $< 5\text{ ms}$.
- Telemetry logs strategic decisions, mid-level choices, predicted values, and fallback diagnostics.

## Acceptance criteria

- [ ] **Hierarchical Policy Structure:** High-Level and Mid-Level policies are decoupled and operate at their respective decision frequencies.
- [ ] **Objective Handling:** Supports farming kill quotas, navigation travel goals, and multi-step quest objectives.
- [ ] **Action Masking:** Prevents selection of unreachable, locked out, dead, or invalid actions.
- [ ] **Simulation Training:** Policy converges in the US-072 simulator, achieving higher KPM and faster quest completion than the heuristic baseline.
- [ ] **ONNX Model Export:** Trained hierarchical models are exported to ONNX format with metadata schemas.
- [ ] **Live Integration:** Deploys into the live bot via `TacticalPolicy` protocol with zero architectural changes to low-level movement or combat controllers.
- [ ] **Deterministic Safety & Fallback:** Safety guards, stall detection, and emergency stop remain outside the policy, and invalid outputs trigger fallback to `HeuristicPolicy`.
- [ ] **Performance:** End-to-end policy inference completes in $< 5\text{ ms}$.
- [ ] **Localization & Diagnostics:** All UI status indicators and logs are synchronized in German (`src/flyff_bot/locales/de.json`) and English (`src/flyff_bot/locales/en.json`).
- [ ] **Quality Gate:** Automated checks pass `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).

## Out of scope

- Live Reinforcement Learning / online policy gradient updates in the live game client.
- Direct keypress or mouse simulation inside the policy network.
- Automated client deployment or auto-patching.
- Memory write operations (`WriteProcessMemory`).

## Verification

- Automated:
  - Unit tests in `tests/unit/test_hierarchical_policy.py` validating high-level and mid-level decision dispatching.
  - Unit tests in `tests/unit/test_policy_action_masking.py` verifying mask enforcement on simulated invalid states.
  - Unit tests in `tests/unit/test_hierarchical_fallback.py` validating fallback to `HeuristicPolicy` upon simulated model faults.
  - Benchmark test verifying $< 5\text{ ms}$ inference execution.
  - `./scripts/check.ps1` (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - In Flyff, execute a multi-objective farming and quest session with the hierarchical policy enabled: verify the bot plans efficient target sequences, selects optimal attack points, navigates corridors without getting stuck, and completes quest goals autonomously.
